r"""浏览器模式：把同一套 webui 喂给系统默认浏览器（快捷键 Ctrl+Caps+O 呼出）。
========== 需求 ==========
用户原话："功能和操作完全一致，只是换到了浏览器中。"
→ 桌面窗口照常存在（触发后**最小化**它），另外在 `127.0.0.1:<port>` 起一个 HTTP 服务，
  把 `webhost.create_app()` 那一套静态资源 + 图标路由原样端出去，再用系统默认浏览器打开。

========== 关键问题：浏览器里没有 window.pywebview ==========
桌面端前端靠 `window.pywebview.api.<域>.<方法>()` 调后端（见 webui/js/app.js 的 bridge）。
浏览器里没有 pywebview 注入，所以这里补**两条等价通道**，让 bridge 换一种传输、
其余前端代码一行都不用改：
① `POST /jsbridge/<域>.<方法>` —— 请求体 `{"args": [...]}`，返回方法的结果 JSON；
   前端把 `bridge.call` 换成 fetch 即可（见 app.js 的 HTTP 适配器）。
② `POST /jsbridge/events/poll` —— **长轮询**取后端推送的事件（`shell.push_event`
   同时投递一份到这里），前端拿到后照常 `window.ToolsGCP.emit(...)`。
   ⚠️ 为什么用长轮询而不是 SSE：SSE 要占着一条连接不返回，本地服务用的是
   每请求一线程的 WSGI 服务器，几个页签就能把线程堆满；长轮询有超时、能被
   中止，行为可控得多。

========== 三条安全边界（必须守住） ==========
1. **只听 127.0.0.1**：绝不绑 0.0.0.0 —— 这个桥能调用任意后端方法（读收藏、写设置、
   下载文件、开目录），暴露到局域网等于把整机交给别人。
2. **同源校验**：只接受 `Origin`/`Referer` 是 `127.0.0.1:本端口`（或 `localhost:本端口`）
   的请求。浏览器里用户可能从别的网站误发 fetch；挡在门口比"信任本地端口"更稳。
3. **路径只走 create_app 的既有路由**：本模块自己不开任何"读任意文件"的口子，
   静态与资源全部交给 webhost 的 `_safe_join` 处理。

========== 幂等 ==========
`ensure_started()` 可以反复调（快捷键连按、用户在设置里点"打开浏览器版"）：
服务只起一次、端口不变；只有浏览器才每次都开（用户可能就是关掉页签又想打开）。
"""

import json
import os
import socket
import socketserver
import threading
import time
import wsgiref.simple_server

from pymodels.constants import APP_NAME, APP_VERSION

# 长轮询：最多等多久就返回一批（哪怕空）。太短 = 前端空转打请求；太长 = 取消按钮反应慢。
EVENT_POLL_WAIT_S = 2.5
# 事件队列上限：页签挂着不取事件时，超过这个数就丢最老的（宁缺莫炸内存）
EVENT_QUEUE_MAX = 200
DEFAULT_PORT = 0                    # 0 = 让系统挑空闲端口
# capabilities 等 shell.api 的最长等待（秒）。
# ⚠️ 为什么不"直接返回空清单"、也不"一直等下去"：
#   · 返回空清单 = 前端 bridge.has() 全 false → 到处 needApi 降级（就是用户看到的"功能全废"）；
#   · 但这条路由必须尽快返回，否则首屏 fetch 卡住，浏览器会以为页面挂了；
#   · shell.api 就是 `self.api = Api(self)` 一行赋值，正常情况下早就有了 → 短暂等一下兜底，
#     等不到就**明确报 api_not_ready**，前端（httpBridge.retryCaps）会自己再来取。
API_READY_WAIT_S = 1.0


# ==========================================================================
# 一、事件投递（shell.push_event 会往这里塞一份）
# ==========================================================================
class _EventBus:
    """浏览器端事件的**单队列**（多个页签共用一份，先到先取）
    ⚠️ 为什么不按页签分队列：现在的事件都是"全局状态变化"（下载进度、资源更新），
       分队列要么让前端自己认领、要么每个页签各存一份队列（内存和重复推送都翻倍）。
       真出现"两个页签互相抢事件"再说。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._queue = []
        self._has = threading.Condition(self._lock)
        self._delivered = 0              # 累计投出去的事件条数（诊断用，取代原来的实时计数）

    def publish(self, name: str, payload: dict):
        with self._has:
            # ⚠️ 队列里的条目结构**不能加字段**：前端 (ev) => emit(ev.name, ev.payload)
            #    直接吃这个形状，改了就是给 Lead 的前端挖坑。
            self._queue.append({"name": str(name), "payload": payload})
            if len(self._queue) > EVENT_QUEUE_MAX:
                del self._queue[:len(self._queue) - EVENT_QUEUE_MAX]
            self._has.notify_all()

    def claim(self, wait_s: float) -> list:
        """取走当前积压的事件（没有就最多等 wait_s）"""
        deadline = time.monotonic() + max(0.0, float(wait_s))
        with self._has:
            while not self._queue:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._has.wait(min(remaining, 0.5))
            batch = self._queue[:]
            self._queue = []
            self._delivered += len(batch)
            return batch

    @property
    def delivered(self) -> int:
        """累计投给浏览器端的条数（**单调递增**，所以能在"没人轮询"的时候观察到流量）"""
        with self._lock:
            return self._delivered

    @property
    def pending(self) -> int:
        """当前积压、还没被取走的条数"""
        with self._lock:
            return len(self._queue)

    # ---------- 兼容旧接口 ----------
    # ⚠️ 原来的 `client_up/client_down/watchers` 全仓库**没有任何调用方**（grep 实证：
    #    只有这里的定义和 shell.browser_mode_status() 里读 watchers），也就是说
    #    "有几个页签在轮询"从来没被真正统计过，那个值恒为 0、只会误导排查。
    #    改成 delivered/pending 这两个真能观察到的量；下面两个方法只为不炸第三方脚本而留空壳。
    def client_up(self):
        return

    def client_down(self):
        return

    @property
    def watchers(self) -> int:
        """已废弃：永远返回 0（见上面的说明）。诊断请用 `delivered` / `pending`。"""
        return 0


BUS = _EventBus()


# ==========================================================================
# 二、js_bridge：把前端的方法名转成对 Api 对象的真实调用
# ==========================================================================
def _lookup(api, dotted: str):
    """按 `resources.list_items` 这种点号路径找方法（pywebview 也是这么解的）"""
    target = api
    for part in str(dotted or "").split("."):
        if part == "" or target is None:
            return None
        target = getattr(target, part, None)
    return target if callable(target) else None


def _jsonable(value):
    """结果必须是 JSON 可序列化的；意外对象退化成 str（**绝不抛给前端**）"""
    try:
        json.dumps(value)
        return value
    except Exception:                               # noqa: BLE001
        return str(value)


def _dispatch(api, dotted: str, args: list):
    """执行一次调用 → (状态码, dict)
    ⚠️ 这条路径跑在 **WSGI 请求线程**里，和 pywebview 的 js_api 工作线程等价：
       后端各域本来就按"不在 GUI 线程"写的（窗口操作全走 pywebview 的 Invoke /
       我们的原生封装），所以直接调是安全的。
    ⚠️ 异常一律转成 `{"ok": false, "error": ...}`：前端 tryCall 拿到 null 才会
       走降级分支，这里抛出去只会变成一个 500 页面，排查更困难。
    """
    fn = _lookup(api, dotted)
    if fn is None:
        return 404, {"ok": False, "error": "missing_method", "method": dotted}
    try:
        result = fn(*list(args or []))
    except TypeError as exc:                        # 参数个数不对：明确报出来
        return 400, {"ok": False, "error": f"bad_arguments: {exc}", "method": dotted}
    except Exception as exc:                        # noqa: BLE001
        return 500, {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                     "method": dotted}
    return 200, {"ok": True, "result": _jsonable(result)}


# ==========================================================================
# 三、WSGI 应用 = 原 webhost + 桥路由
# ==========================================================================
def _read_body(environ) -> bytes:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        length = 0
    if length <= 0 or length > 8 * 1024 * 1024:      # 8MB 上限：桥不是上传通道
        return b""
    stream = environ.get("wsgi.input")
    try:
        return stream.read(length) if stream else b""
    except Exception:                               # noqa: BLE001
        return b""


class _PortHolder:
    """可变的端口号：建应用时端口还没定，起完服务器再回填真实监听端口
    ⚠️ 为什么不能把端口当普通整数传进闭包：
       `_pick_port()` 是"bind 一个临时 socket 拿端口 → 关掉 → 再让 make_server 用这个端口"，
       中间那一步端口**可能被别人抢走**，make_server 实际分到的会是另一个号。
       闭包里写死那个"猜出来的"端口，同源校验就拿错端口比 → 把浏览器自己的
       同源请求全判成跨源 → 403 →「浏览器里功能全不生效」。
       所以这里传对象，起完服务把 `httpd.server_address[1]`（真值）写回来。
    """

    __slots__ = ("port",)

    def __init__(self, port: int = 0):
        self.port = int(port or 0)


def _default_port_for(scheme: str) -> int:
    """http/https 的默认端口：URL 里**省略端口**时必须按默认端口补，否则误判"""
    return 443 if str(scheme or "").lower() == "https" else 80


def _same_origin(environ, port) -> bool:
    """只放行来自本机的同源请求（见模块 docstring 安全边界 ②）
    ⚠️ `port` 允许传 int 或 _PortHolder（后者读实时值，见那个类的说明）。
    ⚠️ 端口比较的三个坑（"浏览器里功能全废"就出在这里）：
       ① 老写法 `int(parsed.port or 0) != port`：Origin 里**省略端口**时
          `parsed.port` 是 **None** → 被当成 0 和真实端口比 → 恒不等 → 一律 403。
          （浏览器地址栏 `http://localhost/` 这种写法、以及被人用 80 端口反代时都会撞上。）
       ② 缺端口应按**该协议的默认端口**补（http=80 / https=443），不是补 0。
       ③ `localhost` 与 `127.0.0.1` 是同一台机器：宿主名两个都放行，但端口必须严格相等
          —— 端口是这里唯一的实质隔离条件，宿主已经限死在本机回环，不会因此放宽安全性。
    """
    origin = str(environ.get("HTTP_ORIGIN") or "").strip()
    referer = str(environ.get("HTTP_REFERER") or "").strip()
    source = origin or referer
    if not source:
        # 没带 Origin/Referer：curl 之类的东西 → 拒绝。
        # 浏览器里的同源 fetch 一定带得到（本桥不给跨源用，不需要 CORS 预检）。
        # ⚠️ 顶层文档导航（地址栏直接打开/刷新）确实不带 Origin，但它不是 /jsbridge
        #    请求 —— 那条走 webhost，压根到不了这个判断，所以这里拒不到它。
        return False
    real_port = getattr(port, "port", port)
    try:
        real_port = int(real_port or 0)
    except (TypeError, ValueError):
        real_port = 0
    host = str(environ.get("HTTP_HOST") or "").split(":")[0].strip().lower()
    allowed_hosts = {"127.0.0.1", "localhost", "::1", host}
    try:
        import urllib.parse as _up
        parsed = _up.urlparse(source)
    except Exception:                               # noqa: BLE001
        return False
    scheme = str(parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False
    hostname = str(parsed.hostname or "").strip().lower()
    # parsed.hostname 已经把 [::1] 的方括号去掉了，所以这里同时收两种写法
    if hostname not in allowed_hosts:
        return False
    try:
        got = int(parsed.port) if parsed.port is not None else _default_port_for(scheme)
    except (TypeError, ValueError):
        return False
    if real_port <= 0:
        return False                    # 端口还不知道 → 不放行（宁拒不错放）
    # 端口必须严格相等：宿主名已经限死在本机回环（127.0.0.1 / localhost / ::1），
    # 端口是这里唯一的实质隔离条件，放宽它等于让本机任意网页都能调后端方法。
    return got == real_port


def create_bridge_app(shell, base_app, port: int):
    """返回一个 WSGI 应用：`/jsbridge/*` 由本模块处理，其余**整串转交** webhost。

    ⚠️ 为什么用 WSGI 包一层，而不是"把 webhost 的路由复制进新 bottle 应用"：
       实测往 `app.routes` 里 append 原 route 对象 → 一律 404。
       bottle 的注册是 `app.add_route()` 同时写 `routes` 列表**和** router 的内部索引，
       只塞列表不进 router，匹配阶段根本看不见这些路由。
       包一层的好处：静态/图标/`/api/health` 全部走 webhost 原样逻辑
       （包括它的 `_safe_join` 目录穿越防护），本模块不复制任何路径知识，
       webhost 以后加路由这里也自动生效 —— 不会出现"桌面端能看、浏览器端 404"。
    ⚠️ 为什么不直接改 webhost.create_app()：那是 pywebview **内部**也在用的应用，
       桥路由一旦也进那条路，桌面端 WebView2 就多了一个能任意调后端方法的攻击面。
       分开 = 桌面端零新增风险。
    ⚠️ `port` 必须是 `_PortHolder`（或 int）：见 `_same_origin` 的说明 ——
       起服务后 `ensure_started` 会把**真实监听端口**回写进这个对象。
    """

    def bridge_app(environ, start_response):
        path = str(environ.get("PATH_INFO") or "")
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        if not path.startswith("/jsbridge/"):
            # ① 其余请求原样交给 webhost（静态、图标、健康检查）
            return base_app(environ, start_response)
        if method != "POST":
            return _json_reply(start_response, "405 Method Not Allowed",
                               {"ok": False, "error": "POST only"})
        if not _same_origin(environ, port):
            return _json_reply(start_response, "403 Forbidden",
                               {"ok": False, "error": "forbidden_origin"})

        body = _read_body(environ)
        if path == "/jsbridge/capabilities":
            return _json_reply(start_response, "200 OK", _capabilities(shell))

        if path.startswith("/jsbridge/call/"):
            dotted = path[len("/jsbridge/call/"):]
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:                       # noqa: BLE001
                return _json_reply(start_response, "400 Bad Request",
                                   {"ok": False, "error": "bad_json"})
            args = payload.get("args")
            if args is None:
                args = []
            if not isinstance(args, list):
                return _json_reply(start_response, "400 Bad Request",
                                   {"ok": False, "error": "args_must_be_array"})
            api = _wait_api(shell)
            if api is None:
                # ⚠️ 不能退化成"返回 404 missing_method"：那样前端会以为"这个接口不存在"，
                #    走 needApi 降级并且**不会重试**（和 capabilities 空清单同一个后果）。
                #    api_not_ready 是明确的"稍后再试"信号。
                return _json_reply(start_response, "503 Service Unavailable",
                                   {"ok": False, "error": "api_not_ready",
                                    "method": dotted})
            status, out = _dispatch(api, dotted, args)
            return _json_reply(start_response, _HTTP_TEXT.get(status, "200 OK"), out)

        if path == "/jsbridge/events/poll":
            events = BUS.claim(EVENT_POLL_WAIT_S)
            return _json_reply(start_response, "200 OK", {"ok": True, "events": events})

        return _json_reply(start_response, "404 Not Found",
                           {"ok": False, "error": "unknown_bridge_path", "path": path})

    return bridge_app


_HTTP_TEXT = {200: "200 OK", 400: "400 Bad Request", 403: "403 Forbidden",
              404: "404 Not Found", 405: "405 Method Not Allowed",
              500: "500 Internal Server Error",
              # 503 = "后端还没就绪，等一下再来"（和 404「这个方法不存在」必须分开：
              # 前端对 404 不会重试，对 503 会 —— 见 _dispatch 的 api_not_ready）
              503: "503 Service Unavailable"}


def _json_reply(start_response, status: str, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    start_response(status, [("Content-Type", "application/json; charset=utf-8"),
                            ("Content-Length", str(len(body))),
                            ("Cache-Control", "no-store")])
    return [body]


def _wait_api(shell, timeout: float = API_READY_WAIT_S):
    """拿到 shell.api（没有就短暂等一会）
    ⚠️ 为什么需要：`shell.api` 是 `run()` 里 `self.api = Api(self)` 赋的，
       而浏览器模式的入口有**三条**并发路径 —— 快捷键线程、托盘菜单、
       `api.hotkey.browser_open`（js_api 工作线程）。快捷键那条尤其可能抢在
       Api 建好之前进来（托盘/热键是在 GUI 启动回调里装的）。
       api 为空时返回**空清单**是最坏的：前端 `bridge.has()` 全 false →
       每个调用都走 needApi 降级，界面看起来"到处都提示接口未就绪"。
    """
    deadline = time.monotonic() + max(0.0, float(timeout))
    api = getattr(shell, "api", None)
    while api is None and time.monotonic() < deadline:
        time.sleep(0.05)
        api = getattr(shell, "api", None)
    return api


def _capabilities(shell) -> dict:
    """告诉前端"后端有哪些方法"
    前端的 `bridge.has(path)` 是按"函数存不存在"判断的，浏览器里没有 pywebview 注入
    → 必须靠这份清单把 api 对象**重建**出来，否则每个调用都会走 needApi 降级，
    界面看起来就是"到处都提示接口未就绪"。
    ⚠️ 两层都要收：属性是**域对象**（app/resources/ai…）→ 收 `域.方法`；
       属性本身就是**可调用**（Api.ping() 这种根级方法）→ 收裸名字 `ping`。
       漏了第二层的话，前端 `bridge.has('ping')` 判空 → 启动探针走降级
       （冒烟测试 test_browser_mode_smoke.py 抓到过：capabilities 恒为空）。
    ⚠️ api 还没就绪时**必须**回 `ok:False + error:"api_not_ready"`，不能回
       `ok:True, methods:[]`：空清单会被前端当成"这台后端什么接口都没有"，
       于是全部功能降级（用户报的"浏览器里配置/图片/资源全加载不上、功能失效"）。
       路由状态行仍是 200 —— 前端靠 200 判定"这是桥"（这条路由只有桥才有），
       再靠 ok/methods 决定要不要重试（app.js 的 httpBridge.retryCaps）。
    """
    names = []
    api = _wait_api(shell)
    if api is None:
        _log("warn", "浏览器模式 capability 请求过早：shell.api 尚未就绪"
                     f"（等满 {API_READY_WAIT_S}s 仍为空）")
        return {"ok": False, "error": "api_not_ready", "methods": [],
                "app": APP_NAME, "version": APP_VERSION, "mode": "browser"}
    try:
        domains = list(dir(api))
    except Exception:                           # noqa: BLE001
        domains = []
    for domain in domains:
        if domain.startswith("_"):
            continue
        try:
            obj = getattr(api, domain)
        except Exception:                       # noqa: BLE001
            continue
        if callable(obj):
            # 根级方法（pywebview 同样把它暴露成 api.ping）
            names.append(domain)
            continue
        try:
            members = list(dir(obj))
        except Exception:                       # noqa: BLE001
            continue
        for meth in members:
            if meth.startswith("_"):
                continue
            try:
                if callable(getattr(obj, meth)):
                    names.append(f"{domain}.{meth}")
            except Exception:                   # noqa: BLE001
                continue
    return {"ok": True, "methods": names, "app": APP_NAME,
            "version": APP_VERSION, "mode": "browser"}



# ==========================================================================
# 四、服务器生命周期
# ==========================================================================
class _ThreadingWSGIServer(socketserver.ThreadingMixIn,
                           wsgiref.simple_server.WSGIServer):
    """每请求一线程（长轮询会占住一条连接，单线程服务器会把整个页面卡死）
    ⚠️⚠️ **必须显式混入 `socketserver.ThreadingMixIn`**：
       `wsgiref.simple_server.WSGIServer` 的 MRO 是
       `WSGIServer → HTTPServer → TCPServer → BaseServer`，**根本没有 ThreadingMixIn**。
       只写 `daemon_threads = True` 是个**没人读的装饰性属性**（BaseServer 不认它），
       结果这个"号称多线程"的服务器实际是**完全串行**的：一次只处理一个请求。
       实测（_devtest/test_browser_mode_server.py 的 [A] 段）：一条请求占 6 秒时，
       另一条本来毫秒级的请求要等满 5.7 秒才拿到响应。
       → 后果就是用户报的现象：浏览器里事件的**长轮询每 2.5 秒占满一条连接**，
         于是 index.html、/static/js/app.js、/res/... 的图标、以及每一个
         `/jsbridge/call/*` 全都在队列后面排队 → "配置/图片/资源全都加载不上、
         功能失效"。桌面端不受影响（pywebview 自己那台服务器和本服务无关）。
    ⚠️ `block_on_close = False`：默认 True 时 `server_close()` 会等**所有**请求线程结束，
       而长轮询线程正卡在 `BUS.claim()` 里（最多 2.5s）+ 浏览器 keep-alive 不关连接，
       退出流程（shell._shutdown → SERVER.stop）就会白等几秒；daemon 线程反正不挡进程退出。
    """
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True


class _SilentHandler(wsgiref.simple_server.WSGIRequestHandler):
    """关掉 wsgiref 默认的 stderr 访问日志
    ⚠️ 长轮询每 2.5 秒一条日志，正常用一会儿就能把日志文件刷满 —— 而且这些
       全是噪音，真正要看的后端日志（pymodels.utils.logger）会被埋掉。
    """

    def log_message(self, fmt, *args):               # noqa: A003
        return


def _pick_port(requested: int) -> int:
    """拿一个能用的端口：设置里写死的端口被占 → 退回随机空闲端口（不硬失败）"""
    requested = int(requested or 0)
    if requested > 0:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", requested))
            return requested
        except OSError:
            _log("warn", f"设置里的浏览器端口 {requested} 已被占用，改自动选端口")
            return 0
        finally:
            try:
                probe.close()
            except Exception:                       # noqa: BLE001
                pass
    # 交给系统分配（bind 0 拿端口，再拿同一个端口去起服务）
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        try:
            probe.close()
        except Exception:                           # noqa: BLE001
            pass


class BrowserServer:
    """一个进程内只有一份的浏览器模式服务"""

    def __init__(self):
        self._lock = threading.RLock()
        self._httpd = None
        self._thread = None
        self._port = 0
        self._error = ""
        self._opened_at = 0.0
        # 同源校验读的端口对象（不是缓存值）：见 _PortHolder 的说明
        self._port_holder = _PortHolder(0)

    # ---------- 状态 ----------
    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        return self._port

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}/" if self._port else ""

    @property
    def error(self) -> str:
        return self._error

    # ---------- 起 ----------
    def ensure_started(self, shell, port: int = 0) -> dict:
        """起服务（已起就复用）→ `{ok, url, started, port, error}`
        ⚠️ 服务**永不**因为第二次触发而重启：重启会让浏览器里那个页签连到
           一个已经换掉的端口（用户看到的就是一页 404）。
        ⚠️ 同源校验用的端口必须是**真实监听端口**（`httpd.server_address[1]`），
           不是 `_pick_port()` 猜出来的那个：`_pick_port(0)` 是"临时 bind 拿到号 →
           关掉 → 再让 make_server 去 bind 同号"，中间端口可能被别人抢走，
           两者就不同了；拿猜的端口去做同源比较会把浏览器自己的请求全判成跨源（403）。
           → 用 `_PortHolder` 传引用，起完立刻回填。
        ⚠️ bind 失败时**退回让系统自选端口**再试一次：设置里写死的端口被占用、
           或者上面那个"抢占竞态"真的发生时，不该直接失败（用户看到的又是"按了没反应"）。
        """
        with self._lock:
            if self._httpd is not None:
                return {"ok": True, "started": False, "url": self.url,
                        "port": self._port, "error": ""}
            from .webhost import create_app
            chosen = _pick_port(port)
            holder = self._port_holder
            holder.port = chosen
            httpd = None
            last_exc = None
            for attempt, bind_port in ((0, chosen), (1, 0)):
                try:
                    base = create_app()
                    app = create_bridge_app(shell, base, holder)
                    httpd = wsgiref.simple_server.make_server(
                        "127.0.0.1", bind_port, app,
                        server_class=_ThreadingWSGIServer,
                        handler_class=_SilentHandler)
                    break
                except Exception as exc:                # noqa: BLE001
                    last_exc = exc
                    if attempt == 0:
                        _log("warn", f"用端口 {bind_port} 起服务失败，改让系统自选端口重试: "
                                     f"{type(exc).__name__}: {exc}")
            if httpd is None:
                self._error = f"{type(last_exc).__name__}: {last_exc}"
                _log("err", f"浏览器模式服务启动失败: {self._error}")
                return {"ok": False, "started": False, "url": "", "port": 0,
                        "error": self._error}
            real_port = int(httpd.server_address[1])
            holder.port = real_port                 # 回填真实端口（见上面说明）
            if real_port != chosen:
                _log("warn", f"浏览器模式实际监听端口 {real_port}（原计划 {chosen}）；"
                             f"同源校验按 {real_port} 走")
            self._httpd = httpd
            self._port = real_port
            self._error = ""
            self._thread = threading.Thread(target=httpd.serve_forever,
                                            name="ToolsGCP-browser-mode",
                                            daemon=True)
            self._thread.start()
            _log("op", f"浏览器模式服务已启动: http://127.0.0.1:{self._port}/")
            return {"ok": True, "started": True, "url": self.url,
                    "port": self._port, "error": ""}

    # ---------- 停 ----------
    def stop(self):
        with self._lock:
            httpd, thread = self._httpd, self._thread
            self._httpd = None
            self._thread = None
            self._port = 0
        if httpd is None:
            return
        try:
            httpd.shutdown()                        # 等 serve_forever 的循环退出
        except Exception:                           # noqa: BLE001
            pass
        try:
            httpd.server_close()
        except Exception:                           # noqa: BLE001
            pass
        try:
            if thread is not None:
                thread.join(timeout=2.0)
        except Exception:                           # noqa: BLE001
            pass
        _log("info", "浏览器模式服务已停止")


SERVER = BrowserServer()


# ==========================================================================
# 五、打开系统默认浏览器
# ==========================================================================
def open_in_default_browser(url: str) -> bool:
    """用**系统默认浏览器**打开（不猜浏览器、不开新实例）
    ⚠️ 三条路的差别（都踩过/查过）：
       · `os.startfile(url)` → 走 ShellExecute = 真的"默认浏览器"，会复用已开实例
         （不会像 start chrome.exe 那样拉起第二个进程）；
       · `webbrowser.open()` → Python 自己按注册表顺序挑，经常挑到**不是**用户默认
         的那个（尤其装了两个浏览器的机器），而且被浏览器"已有实例"抢走后
         可能整个调用无声失败；
       · `cmd /c start` → 和 startfile 等价，但会多闪一个 cmd 窗口（更新器那个坑）。
       → 选 startfile，失败再退回 webbrowser。
    """
    if not url:
        return False
    try:
        os.startfile(url)                           # noqa: S606 - Windows 专用
        return True
    except Exception as exc:                        # noqa: BLE001
        _log("warn", f"startfile 打开浏览器失败（退回 webbrowser）: {exc}")
    try:
        import webbrowser
        return bool(webbrowser.open(url))
    except Exception as exc:                        # noqa: BLE001
        _log("err", f"打开默认浏览器失败: {exc}")
        return False


# ==========================================================================
# 六、日志
# ==========================================================================
def _log(level: str, message: str):
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)("浏览器", "browser", message)
    except Exception:                               # noqa: BLE001
        pass


__all__ = ["BUS", "SERVER", "BrowserServer", "create_bridge_app",
           "ensure_browser_mode", "open_in_default_browser", "_dispatch",
           "_PortHolder", "_same_origin", "_capabilities",
           "EVENT_POLL_WAIT_S", "API_READY_WAIT_S"]


def ensure_browser_mode(shell, open_browser: bool = True,
                        port: int = 0) -> dict:
    """快捷键/设置页共用的入口：确保服务在跑 + （可选）打开浏览器
    返回 `{ok, url, started, port, opened, error}`
    """
    result = SERVER.ensure_started(shell, port=port)
    opened = False
    if result.get("ok") and open_browser:
        opened = open_in_default_browser(result["url"])
    return {"ok": bool(result.get("ok")), "url": result.get("url", ""),
            "started": bool(result.get("started")), "port": int(result.get("port") or 0),
            "opened": opened, "error": str(result.get("error") or "")}
