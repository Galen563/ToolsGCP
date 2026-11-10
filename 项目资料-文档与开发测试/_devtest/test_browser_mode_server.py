# -*- coding: utf-8 -*-
"""浏览器模式**服务端加固**回归测试（对应三个真实故障点）。

覆盖三件事（都是用户实测到的"浏览器里配置/图片/资源全加载不上、功能失效"）：

  A. 服务器**真的**每请求一线程。
     原代码 `_ThreadingWSGIServer(wsgiref.simple_server.WSGIServer)` 只写了
     `daemon_threads = True`，但 `WSGIServer` 的 MRO 里**根本没有 ThreadingMixIn**
     （`WSGIServer → HTTPServer → TCIPServer → BaseServer`），
     那个属性没人读 → 服务器实际**完全串行**：一次只处理一个请求。
     而浏览器端的事件长轮询每 2.5 秒占满一条连接 → 首屏 HTML、/static/js/app.js、
     /res/... 的图标、每一个 /jsbridge/call 全都在排队 → 页面看起来"全都加载不上"。

  B. 同源校验的端口比较。
     原写法 `int(parsed.port or 0) != port`：Origin 里**省略端口**（或被按默认端口
     规范化）时 `parsed.port` 是 None → 被当成 0 和真实端口比 → 恒不等 → 一律 403。
     另外 `_pick_port(0)` "临时 bind 拿号→关闭→再让 make_server 用同号"中间号可能被抢走，
     传进闭包的端口可能不是真实监听端口 → 同样是 403。现在用 _PortHolder 回填真实端口。

  C. `shell.api` 还没就绪时**不能**回 `ok:True, methods:[]`（空清单 = 前端全线降级）。

⚠️⚠️ 跑法（必须照做）：
    python "项目资料-文档与开发测试/_devtest/test_browser_mode_server.py"
    第一件事是 `sys.argv[0] = <仓库根>/ToolsGCP.pyw`：
    `constants.CONFIG_DIR = dirname(sys.argv[0]) + "/.ToolsGCP"`，
    不设的话从 _devtest 目录跑会把资源根算错 → 静态路由**全 404**（Lead 踩过）。
"""
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]      # ← 资源根按真实入口算
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

from pymodels.constants import CONFIG_DIR                     # noqa: E402
from desktop import browsermode as bm                         # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


print("[0] 资源根定位")
check("CONFIG_DIR = 仓库根/.ToolsGCP",
      os.path.normcase(CONFIG_DIR) == os.path.normcase(os.path.join(ROOT, ".ToolsGCP")),
      CONFIG_DIR)
check("webui/index.html 存在（否则静态全 404 是测试环境问题）",
      os.path.isfile(os.path.join(CONFIG_DIR, "webui", "index.html")))


# ---------------------------------------------------------------- 假 shell
class Domain:
    def __init__(self, ready=True):
        self._ready = ready

    def list_items(self, keyword=""):
        return {"ok": True, "items": [f"item:{keyword}"]}

    def slow(self, seconds=4.0):
        """模拟长任务（用来占住一条连接）"""
        time.sleep(float(seconds))
        return {"ok": True, "slept": seconds}


class Api:
    """形状接近真实 Api：既有域对象，也有根级可调用"""

    def __init__(self):
        self.resources = Domain()
        self.settings = Domain()

    def ping(self):
        return {"ok": True, "pong": True}


class Shell:
    def __init__(self, api=None):
        self.api = api
        self.pushed = []

    def push_event(self, name, payload):
        self.pushed.append((name, payload))
        bm.BUS.publish(name, payload)


# ---------------------------------------------------------------- 起服务
server_shell = Shell(Api())
res = bm.ensure_browser_mode(server_shell, open_browser=False)
print(f"\n[1] 起服务 -> {res}")
assert res["ok"], res
BASE = res["url"]
REAL_PORT = res["port"]
check("返回的端口 == 服务器真实监听端口（同源校验用的就是它）",
      int(bm.SERVER._httpd.server_address[1]) == REAL_PORT, f"{REAL_PORT}")

holder = getattr(bm.SERVER, "_port_holder", None)
if holder is not None:
    check("_PortHolder 已回填真实端口", int(holder.port) == REAL_PORT, str(holder.port))


def post(path, body=None, origin=None, timeout=25, headers=None, raw=None):
    data = raw if raw is not None else json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(BASE + path.lstrip("/"), data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if origin is not None:
        req.add_header("Origin", origin)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, {"raw": txt[:160]}


# ---------------------------------------------------------------- A. 并发
print("\n[A] 并发：长轮询/慢请求不能把别的请求饿死")
# 先制造"占住一条连接"的场景：一次长轮询（BUS 空 → 等满 EVENT_POLL_WAIT_S）
t0 = time.time()
poll_thread = threading.Thread(
    target=lambda: post("/jsbridge/events/poll", origin=BASE.rstrip("/")))
poll_thread.start()
time.sleep(0.35)                      # 确保 poll 已经挂在服务器上

t1 = time.time()
st, caps = post("/jsbridge/capabilities", origin=BASE.rstrip("/"))
fast_ms = (time.time() - t1) * 1000
poll_thread.join(timeout=20)
check(f"长轮询占线时，capabilities 仍然立刻返回（{fast_ms:.0f} ms）",
      st == 200 and fast_ms < 1200, f"status={st} 耗时={fast_ms:.0f}ms")

# 再来一次更狠的：一个 4 秒的慢调用挂着，同时打 3 条快调用 + 静态资源
st_slow = {}


def slow_call():
    st_slow["r"] = post("/jsbridge/call/resources.slow", {"args": [4]},
                        origin=BASE.rstrip("/"), timeout=30)


th = threading.Thread(target=slow_call)
th.start()
time.sleep(0.3)
latencies = []
for _ in range(3):
    ta = time.time()
    st2, out2 = post("/jsbridge/call/resources.list_items", {"args": ["git"]},
                     origin=BASE.rstrip("/"))
    latencies.append(((time.time() - ta) * 1000, st2))
    time.sleep(0.02)

# 静态资源也必须同时可取（这就是用户说的"图片/资源配置加载不上"）
ts = time.time()
with urllib.request.urlopen(BASE, timeout=25) as r:
    html = r.read().decode("utf-8", "replace")
static_ms = (time.time() - ts) * 1000
stj = time.time()
with urllib.request.urlopen(BASE + "static/js/app.js", timeout=25) as r:
    appjs = r.read()
appjs_ms = (time.time() - stj) * 1000
with urllib.request.urlopen(BASE + "res/logo.png", timeout=25) as r:
    logo = r.read()
th.join(timeout=30)

worst = max(x[0] for x in latencies)
check(f"慢调用(4s)挂线时 3 条 bridge 调用都不排队（最差 {worst:.0f} ms）",
      worst < 1500 and all(s == 200 for _, s in latencies),
      [(f"{m:.0f}ms", s) for m, s in latencies])
check(f"慢调用挂线时首页 / 仍能立刻取到（{static_ms:.0f} ms，{len(html)} 字节）",
      static_ms < 1500 and len(html) > 1000)
check(f"慢调用挂线时 /static/js/app.js 仍能立刻取到（{appjs_ms:.0f} ms）",
      appjs_ms < 1500 and len(appjs) > 1000)
check("慢调用挂线时 /res/logo.png 也能取到（图标不再 404/卡死）",
      len(logo) > 100, f"{len(logo)} bytes")
check("慢调用自己也正常返回", st_slow.get("r", (0,))[0] == 200, str(st_slow)[:120])

# 事件仍能端到端（这条队列同时验证 seq/name/payload 结构）
bm.BUS.publish("download.progress", {"percent": 77})
st, out = post("/jsbridge/events/poll", origin=BASE.rstrip("/"))
ev = (out.get("events") or [{}])[0]
check("事件长轮询拿到刚推的那条（name/payload 结构不变）",
      st == 200 and ev.get("name") == "download.progress"
      and ev.get("payload", {}).get("percent") == 77, str(out)[:160])
check("BUS.delivered 在投出去之后真的涨了（watchers 那个假计数器已废弃）",
      bm.BUS.delivered >= 1, f"delivered={bm.BUS.delivered} pending={bm.BUS.pending}")

# ---------------------------------------------------------------- B. 同源
print("\n[B] 同源校验：localhost / 省略端口 / 默认端口 都要放行")
cases = [
    (f"http://127.0.0.1:{REAL_PORT}", True, "标准写法"),
    (f"http://localhost:{REAL_PORT}", True, "localhost 别名"),
    (f"http://127.0.0.1:{REAL_PORT}/jsbridge/capabilities", True, "带路径（Referer 形状）"),
    ("http://127.0.0.1", False, "端口 80 ≠ 我们的端口（必须拒）"),
    ("http://evil.example", False, "外站（必须拒）"),
    (f"http://127.0.0.1:{REAL_PORT + 1}", False, "隔壁端口（必须拒）"),
    ("", False, "不带 Origin/Referer（curl 之类，必须拒）"),
]
for source, want, label in cases:
    environ = {"HTTP_ORIGIN": source, "HTTP_HOST": f"127.0.0.1:{REAL_PORT}"}
    got = bm._same_origin(environ, REAL_PORT)
    check(f"{label}: {source or '(空)'} → {'放行' if want else '拒绝'}", got is want,
          f"实际={got}")

# 省略端口的 Origin：走默认端口 80 的比较（老写法把 None 当 0 → 一律误判）
env80 = {"HTTP_ORIGIN": "http://localhost/", "HTTP_HOST": "127.0.0.1:80"}
check("Origin 省略端口 + 服务在 80 → 放行（老写法这里必然误判成跨源）",
      bm._same_origin(env80, 80) is True)
check("Origin 省略端口(=80) + 服务在随机端口 → 拒绝（端口确实是隔离条件）",
      bm._same_origin(env80, REAL_PORT) is False)
# _PortHolder 也要能用（ensure_started 传的就是它）
h = bm._PortHolder(REAL_PORT)
check("_same_origin 接受 _PortHolder（读实时端口）",
      bm._same_origin({"HTTP_ORIGIN": f"http://127.0.0.1:{REAL_PORT}",
                       "HTTP_HOST": "x"}, h) is True)
h.port = 0
check("端口未知（0）时一律拒绝，宁拒不错放",
      bm._same_origin({"HTTP_ORIGIN": f"http://127.0.0.1:{REAL_PORT}",
                       "HTTP_HOST": "x"}, h) is False)

# 真发一个 localhost 的桥调用，确认 200 而不是 403
try:
    local_base = f"http://localhost:{REAL_PORT}/"
    stl, outl = json.loads(urllib.request.urlopen(
        urllib.request.Request(local_base + "jsbridge/capabilities", data=b"{}",
                               method="POST",
                               headers={"Origin": local_base.rstrip("/")}),
        timeout=15).read().decode()), None
    check("用 localhost 主机名真打一次 capabilities → 200（不是 403）",
          stl.get("ok") is True and stl.get("methods"), str(stl)[:120])
except Exception as exc:
    check("用 localhost 主机名真打一次 capabilities → 200（不是 403）", False, repr(exc))

# ---------------------------------------------------------------- C. api 未就绪
print("\n[C] capabilities / call 在 shell.api 未就绪时的行为")
early_holder = bm._PortHolder(0)
early = {"api": None}


class EarlyShell(Shell):
    def __init__(self):
        super().__init__(api=None)


es = EarlyShell()
t_start = time.time()
caps_out = bm._capabilities(es)
waited = time.time() - t_start
check("api 为空时 capabilities 明确报 api_not_ready（不是空清单当成功）",
      caps_out.get("ok") is False and caps_out.get("error") == "api_not_ready"
      and caps_out.get("methods") == [], str(caps_out)[:160])
check(f"但没有白等很久（{waited:.2f}s 上限 1.5s，首屏不能被卡住）", waited < 1.5,
      f"{waited:.2f}s")


class LateShell(Shell):
    """1 秒后才把 api 挂上 —— 模拟快捷键抢在 Api 建好之前触发"""

    def __init__(self):
        super().__init__(api=None)
        threading.Timer(0.6, lambda: setattr(self, "api", Api())).start()


ls = LateShell()
caps2 = bm._capabilities(ls)
check("api 稍后建好时，capabilities 等得到并返回完整清单",
      caps2.get("ok") is True and "resources.list_items" in caps2.get("methods", [])
      and "ping" in caps2.get("methods", []),
      f"ok={caps2.get('ok')} methods={len(caps2.get('methods', []))}")

# 真实 HTTP 层的 call 也要结构化报 503，而不是 404 missing_method
print("\n[C2] HTTP 层：api 未就绪时 /jsbridge/call 必须回 503 api_not_ready")


def _base_404(environ, start_response):
    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"no"]


no_api_shell = Shell(api=None)
bridge_only = bm.create_bridge_app(no_api_shell, _base_404, REAL_PORT)


def _wsgi_call(app, path, origin):
    """直接跑一次 WSGI，不用起第二个服务器"""
    from io import BytesIO
    from wsgiref.util import setup_testing_defaults
    body = json.dumps({"args": []}).encode()
    env = {"PATH_INFO": path, "REQUEST_METHOD": "POST",
           "CONTENT_LENGTH": str(len(body)),
           "HTTP_ORIGIN": origin, "wsgi.input": BytesIO(body)}
    setup_testing_defaults(env)          # ⚠️ 原地改，返回 None（别写成 env = ...）
    got = {}

    def sr(status, headers, exc_info=None):
        got["status"] = status
        return lambda *a: None

    out = b"".join(app(env, sr) or [])
    return got.get("status", "?"), json.loads(out.decode("utf-8"))


status_line, payload = _wsgi_call(bridge_only, "/jsbridge/call/resources.list_items",
                                  f"http://127.0.0.1:{REAL_PORT}")
check("api 为空时 call → 503（而不是 404 missing_method：404 前端不会重试）",
      status_line.startswith("503") and payload.get("error") == "api_not_ready",
      f"{status_line} {str(payload)[:120]}")
status_line2, payload2 = _wsgi_call(bridge_only, "/jsbridge/capabilities",
                                    f"http://127.0.0.1:{REAL_PORT}")
check('api 为空时 capabilities → 200 + ok:False（200 仍是「这是桥」的决定性信号）',
      status_line2.startswith("200") and payload2.get("ok") is False
      and payload2.get("error") == "api_not_ready",
      f"{status_line2} {str(payload2)[:120]}")

# ---------------------------------------------------------------- D. 路由归属
print("\n[D] /jsbridge/* 之外仍全部转交 webhost（桌面端零新增风险）")
for path, label in [("", "首页 /"), ("static/css/base.css", "/static/*"),
                    ("api/health", "/api/health")]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=20) as r:
            check(f"{label} → {r.status}", r.status == 200)
    except Exception as exc:
        check(f"{label} 可取", False, repr(exc))

st, out = post("/jsbridge/unknown", origin=BASE.rstrip("/"))
check("未知的 /jsbridge 路径 → 404 unknown_bridge_path",
      st == 404 and out.get("error") == "unknown_bridge_path", str(out)[:120])

st, out = post("/jsbridge/capabilities", origin=BASE.rstrip("/"), raw=b'{"args": [')
check("坏 JSON 打 capabilities 不炸 500 页面", st in (200, 400), f"status={st}")

st, out = post("/jsbridge/call/resources.list_items", {"args": "not-a-list"},
               origin=BASE.rstrip("/"))
check("args 不是数组 → 400 args_must_be_array", st == 400, str(out)[:120])

# ---------------------------------------------------------------- 收尾
bm.SERVER.stop()
try:
    urllib.request.urlopen(BASE, timeout=3)
    check("stop() 之后端口不再可访问", False, "还能访问")
except Exception:
    check("stop() 之后端口不再可访问", True)

print("\n" + ("*** BROWSER MODE SERVER: 全部通过 OK ***"
              if not FAILS else f"*** 失败 {len(FAILS)} 项: {FAILS} ***"))
sys.exit(1 if FAILS else 0)
