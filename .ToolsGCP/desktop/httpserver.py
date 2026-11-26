"""本地 HTTP/1.1 **keep-alive** WSGI 服务器
=====================================================================
为什么需要这个模块
---------------------------------------------------------------------
用户报的现象："启动后 UI 堆叠在一起、样式是最基础底层的（可能 CSS 未加载），
加载国外网页或小概率碰到，开 50 多次基本遇到一次"。

已核实的根因链条（实测数据见文件末尾"实测数据"）：
1. 桌面端把 **WSGI callable** 直接当 `create_window(url=app)` 的 url 传，
   pywebview 于是用自己的 `webview/http.py` 起服务（随机端口 + 每请求一线程）。
2. 那一套的底座是 `wsgiref.simple_server`，而 **wsgiref 的
   `WSGIRequestHandler.handle()` 只服务一个请求就把连接关掉**
   （`protocol_version = 'HTTP/1.0'`）
   ⇒ 页面里每一个静态资源（app.js / 6 个 css / tailwind / vue…）都要
     **新建一条 TCP 连接**。
3. `wsgiref.simple_server.WSGIServer.request_queue_size = 5`
   （监听 backlog 只有 5！）⇒ 连接一多就排队/被拒。
⇒ 三条叠加，就表现为"资源偶尔没加载出来、CSS 丢失、UI 堆在一起"。

本模块提供两样东西（互相独立，哪条都能单独用）：
A. `serve(app, host="127.0.0.1", port=0)`
   —— **独立可用的 keep-alive 服务器**，完全不依赖 pywebview，
      适合 "自己起服务器 + `create_window(url='http://127.0.0.1:<port>/')`" 的接法。
B. `BottleKeepAliveAdapter` + `patch_pywebview_server()`
   —— 给 pywebview 用的适配器（锦上添花；它内部还是复用 A）。

⚠️ 本模块**只**用标准库 + bottle，不引新依赖、不 import PyQt5。
"""

from __future__ import annotations

import logging
import socket
import socketserver
import threading
import time
import traceback
import wsgiref.simple_server
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

try:                                            # bottle 只用来做适配器，理论上项目里一定有
    import bottle
except Exception:                               # pragma: no cover
    bottle = None

__all__ = [
    "KeepAliveServer",
    "KeepAliveWSGIRequestHandler",
    "KeepAliveServerHandler",
    "BottleKeepAliveAdapter",
    "serve",
    "stop",
    "make_keepalive_server",
    "patch_pywebview_server",
]

# 兜底日志器（项目日志模块不可用时用）
_FALLBACK_LOG = logging.getLogger("toolsgcp.httpserver")

# 监听队列长度。⚠️ wsgiref/TCPServer 的默认值只有 **5**，
#   而浏览器对一个域名最多会同时开 6 条 HTTP/1.1 连接 —— backlog=5 时
#   第 6 条连接直接被系统拒掉，表现为"某个静态资源（多半是 CSS）没加载"。
_REQUEST_QUEUE_SIZE = 128


def _log(level: str, message: str) -> None:
    """写项目日志；拿不到项目日志模块就退回标准 logging。**绝不抛异常**。"""
    try:
        from pymodels.utils.logger import log as project_log

        fn = getattr(project_log, {"info": "info", "warn": "warn", "err": "err"}.get(level, "info"))
        fn("HTTP 服务", "http", message)
        return
    except Exception:
        pass
    try:
        _FALLBACK_LOG.log(
            {"info": logging.INFO, "warn": logging.WARNING, "err": logging.ERROR}.get(level, logging.INFO),
            message,
        )
    except Exception:
        pass


# ======================================================================
# 一、响应处理器：把 wsgiref 的响应头处理补齐成 HTTP/1.1 语义
# ======================================================================
class KeepAliveServerHandler(wsgiref.simple_server.ServerHandler):
    """在 wsgiref 的响应处理上补齐 HTTP/1.1 keep-alive 需要的几件事。

    1. **状态行版本跟请求走**：请求是 HTTP/1.1 就回 `HTTP/1.1`，
       请求是 HTTP/1.0 就回 `HTTP/1.0`。
       ⚠️ 为什么要跟着请求走：老客户端（HTTP/1.0）靠**状态行**判断连接能不能复用。
       如果对 HTTP/1.0 客户端回 HTTP/1.1 又不主动关连接，客户端会以为连接还能用，
       下次复用时直接收到 RemoteDisconnected。
    2. **每个响应都有准确的 Content-Length**（keep-alive 的生死线）：
       没有 Content-Length 的 1.1 响应，客户端会一直等 body，界面就"卡在白屏"；
       Content-Length 大于实际发出去的字节数，同样会挂住。
    3. **304/204/1xx 一律删掉 Content-Length**：
       bottle 的 `Bottle.wsgi()` 在状态码是 304 时会把 body 丢成 `[]`
       （bottle.py 里 `if response._status_code in (100, 101, 204, 304) ... out = []`），
       但 header 里的 `Content-Length` 还留着（bottle 是在丢 body **之前**算好的）。
       ⇒ 客户端按 Content-Length 等 body，而服务端永远不发 → **连接挂死**。
       RFC 7232 允许 304 带 Content-Length（表示"如果我发 200 会有多长"），
       但为了绝对安全，这里统一删掉：304 本来就没有 body。
    """

    # ---------- 生命周期 ----------

    def setup_environ(self):
        super().setup_environ()
        proto = str(self.environ.get("SERVER_PROTOCOL", "HTTP/1.0")).upper()
        # 只有请求方是 HTTP/1.1 时才敢用 HTTP/1.1 的响应行（= 才敢保持连接）
        self.http_version = "1.1" if proto == "HTTP/1.1" else "1.0"
        self._written = 0
        self._declared_length = None

    def run(self, application):
        """重写 `BaseHandler.run()`，只为在"发响应头之前"先拿到应用的返回值。

        为什么必须这么做：`Content-Length` 是在**发头那一刻**写进响应头的，
        而 wsgiref 默认的 `set_content_length()` 只有在应用返回的 iterable
        **正好是长度 1 的序列**时才算得出来（`len(self.result) == 1`）。
        bottle 绝大多数情况满足（返回 `[bytes]`），但只要路由返回生成器 /
        文件流 / 多段列表，就**算不出长度** ⇒ 1.1 keep-alive 下客户端挂死。
        所以这里在 `finish_response()`（真正发头）之前先把返回值拿到手，
        自己算长度、自己决定"关连接兜底"。
        """
        try:
            self.setup_environ()
            self.result = application(self.environ, self.start_response)
            self._fix_headers()
            self.finish_response()
            self._verify_length()
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            # 客户端自己断了（正常现象，浏览器的 keep-alive 超时就是这种）
            return
        except Exception:
            try:
                self.handle_error()
            except Exception:
                self.close()
                raise

    # ---------- 内部工具 ----------

    def write(self, data):
        """统计真正写出去多少字节（用来事后核对 Content-Length）"""
        try:
            self._written = getattr(self, "_written", 0) + len(data)
        except Exception:
            pass
        super().write(data)

    def _body_length(self):
        """能精确算出 body 字节数就返回，否则返回 None"""
        result = self.result
        if isinstance(result, (bytes, bytearray)):
            return len(result)
        if isinstance(result, (list, tuple)):
            total = 0
            for item in result:
                if not isinstance(item, (bytes, bytearray)):
                    return None
                total += len(item)
            return total
        return None

    def _drop_result(self):
        """丢弃应用返回的 body（204/304/1xx 不允许带 body）。

        ⚠️ 为什么必须真的丢掉、而不只是"不发出去"：
        声明了"没有长度"却还把字节写出去，客户端就会把这些字节当成
        **下一个响应**的开头 → 串包。所以"不发 body"和"真的没有 body"
        必须同时成立。
        """
        result = getattr(self, "result", None)
        if result is None:
            return
        try:
            if hasattr(result, "close"):
                result.close()
        except Exception:
            pass
        self.result = []

    def _mark_close(self):
        """告诉请求处理器"这个连接用完就关"（不能复用）"""
        holder = getattr(self, "request_handler", None)
        if holder is not None:
            try:
                holder.close_connection = True
            except Exception:
                pass

    def _fix_headers(self):
        """在**发响应头之前**把 Content-Length / Connection 定死"""
        headers = self.headers
        if headers is None:
            return
        method = str(self.environ.get("REQUEST_METHOD", "GET")).upper()
        proto = str(self.environ.get("SERVER_PROTOCOL", "HTTP/1.0")).upper()
        # 客户端请求里带的头（wsgiref 把请求头放在 request_handler.headers）
        try:
            req_connection = str(self.request_handler.headers.get("Connection", ""))
        except Exception:
            req_connection = ""

        # --- ① 无 body 的状态码（204 / 304 / 1xx）：删掉长度相关头 ---
        if self._is_bodyless_status():
            for name in ("Content-Length", "Transfer-Encoding"):
                if name in headers:
                    del headers[name]
            # ⚠️ 还要把 body 本身丢掉：RFC 7230 规定 204/304 不能带 body。
            #    如果应用真的返回了 body 而状态码是 304，我们必须保证
            #    「声明了没有长度」和「确实没发字节」是自洽的，否则客户端会把这串
            #    字节当成下一个响应的开头 → 串包。
            self._drop_result()
            self._declared_length = None

        # --- ② HEAD：Content-Length 保留实体长度，但一个字节的 body 也不发 ---
        elif method == "HEAD":
            # ⚠️ 应用自己声明的 Content-Length 要**原样保留**：
            #    HEAD 的 Content-Length 表示「如果发 GET 会有多长」；
            #    而 HEAD 请求下应用的返回值往往已经被丢掉了（bottle 的 wsgi() 里
            #    REQUEST_METHOD == HEAD 时 out = []），
            #    这时从返回值算出来的 0 会把真实长度覆盖掉 ⇒ 错。
            if headers.get("Content-Length") is None:
                actual = self._body_length()
                headers["Content-Length"] = str(actual if actual is not None else 0)
            self._declared_length = None
            # ⚠️ HEAD 的响应体必须为空，否则客户端会按 GET 的语义去解析它
            self._drop_result()

        # --- ③ 能算出准确长度 → 用算出来的（应用自己写错长度时以实际为准） ---
        else:
            actual = self._body_length()
            if actual is not None:
                declared = headers.get("Content-Length")
                if declared is not None and str(declared).strip() != str(actual):
                    _log("warn", f"应用声明的 Content-Length={declared} 与实际 body "
                                 f"{actual} 字节不符，以实际值为准（否则客户端会挂住）")
                headers["Content-Length"] = str(actual)
                self._declared_length = actual
            elif headers.get("Content-Length") is None:
                # --- ④ 长度完全未知：只能用「关连接」来界定 body 结束 ---
                # 这是 HTTP/1.0 式的 close-delimited body：安全，但连接不能复用。
                headers["Connection"] = "close"
                self._mark_close()
            else:
                try:
                    self._declared_length = int(str(headers.get("Content-Length")).strip())
                except Exception:
                    self._declared_length = None


        # --- ⑤ Connection 头：把客户端的意图回显清楚 ---
        # 客户端说 close → 明确回 close，并且这条连接用完就关。
        if "close" in req_connection.lower():
            headers["Connection"] = "close"
            self._mark_close()
        elif proto == "HTTP/1.0" and "keep-alive" in req_connection.lower():
            # HTTP/1.0 的老客户端主动要求 keep-alive：回一个 keep-alive，
            # 它才知道可以复用这条连接。
            headers["Connection"] = "keep-alive"
        elif proto == "HTTP/1.0":
            # HTTP/1.0 的老客户端没说 keep-alive → 明确告诉他这条连接用完就关
            #（wsgiref 的 parse_request 也已经把 close_connection 置 True 了，
            #  这里只是把意图写进响应头，避免客户端猜）
            headers["Connection"] = "close"
            self._mark_close()
        elif "close" in str(headers.get("Connection", "")).lower():
            # 应用自己要求关连接 → 尊重它
            self._mark_close()

    def _verify_length(self):
        """事后核对：真写出去的字节数必须和 Content-Length 一致。

        不一致说明这条连接已经"脏了"（客户端会按声明的长度等 body），
        必须**立刻关掉**（把"永久挂住"降级成"读到一个 EOF 后报错"）。
        """
        declared = self._declared_length
        if declared is None:
            return
        written = int(getattr(self, "_written", 0) or 0)
        if declared != written:
            _log("warn", f"响应体长度不符：声明 {declared} 字节，实际写出 {written} 字节，"
                         f"关闭该连接以免影响后续请求")
            self._mark_close()

    def _is_bodyless_status(self):
        """这个状态码按 RFC 7230 不允许带 body（204 / 304 / 1xx）"""
        code = str(self.status or "")[:3]
        if not code.isdigit():
            return False
        value = int(code)
        return value in (204, 304) or 100 <= value < 200

    def cleanup_headers(self):
        """重写：**不许** wsgiref 给"没有 body 的状态码"自动补 Content-Length。

        ⚠️ 这里才是 304 挂死的真正根因，光改 `finish_content()` 没用：
        wsgiref 的 `send_headers()` 会先调 `cleanup_headers()`，它发现缺
        Content-Length 就调 `set_content_length()`；而后者的判断条件是
        **`len(self.result) == 1`** —— bottle 的 304 返回值是 `[b""]`
        （长度正好是 1！）⇒ 命中条件 ⇒ 自动补上 `Content-Length: 0`。
        （实测：删掉之后又被补了回来。）
        补一个 0 本身无害，但同一段逻辑在"应用声明了长度但实际发不出那么多
        字节"时会让客户端**一直等 body** → 连接挂死。
        ⇒ 204/304/1xx 一律不带 Content-Length，语义最干净也最安全。
        """
        if self._is_bodyless_status():
            return
        super().cleanup_headers()

    def finish_content(self):
        """重写以避免 wsgiref 给"无 body 的状态码"补上 Content-Length: 0。

        wsgiref 的 `finish_content()` 在"还没发过头"时会
        `self.headers.setdefault('Content-Length', "0")` —— 对 304 来说
        客户端会以为"body 有 0 字节"（这个其实无害），但我们统一
        让 304 一个 Content-Length 都不带，语义最干净。
        """
        if self._is_bodyless_status():
            if not self.headers_sent:
                self.send_headers()
            return
        super().finish_content()


# ======================================================================
# 二、请求处理器：把 handle() 改成"一条连接服务多个请求"
# ======================================================================
class _CountingReader:
    """套在 socket 文件对象外面数"这次请求读走了多少字节"。

    ⚠️ 为什么需要它：**请求体必须被读完**，否则同一条连接上的下一个请求
    会从请求体的残留字节开始解析 → 请求串台（表现为随机 400 / 拿到别的页面）。
    keep-alive 之前每个请求独占一条连接，残留字节无所谓；
    keep-alive 之后就必须把没被应用读完的请求体丢掉。
    """

    def __init__(self, fp):
        self._fp = fp
        self.count = 0

    def read(self, *args):
        data = self._fp.read(*args)
        self.count += len(data or b"")
        return data

    def readline(self, *args):
        data = self._fp.readline(*args)
        self.count += len(data or b"")
        return data

    def readlines(self, *args):
        data = self._fp.readlines(*args)
        self.count += sum(len(x or b"") for x in data)
        return data

    def __getattr__(self, name):
        return getattr(self._fp, name)


class KeepAliveWSGIRequestHandler(WSGIRequestHandler):
    """keep-alive 请求处理器。

    ⚠️ **必须重写 `handle()`**：wsgiref 的 `WSGIRequestHandler.handle()`
    （wsgiref/simple_server.py:111-137）只做**一次**：
    读一行请求行 → parse_request → 跑一次 app → 然后连接就结束了。
    所以哪怕把 `protocol_version` 改成 HTTP/1.1，连接照样只活一个请求
    （`parse_request()` 里 `self.close_connection = False` 只对"这一次"有效，
     下一轮循环里还得重新判断）。⇒ 资源再多也会一条一个连接地重建 TCP，
     再叠上 backlog=5 的监听队列，就出现"资源偶尔没加载出来"。
    """

    # HTTP/1.1：状态行按 1.1 发，并且允许一条连接复用
    protocol_version = "HTTP/1.1"

    # 空闲 keep-alive 连接的最长存活时间。
    # ⚠️ 不是为了"快"，是为了不让空闲连接的线程无限堆积
    #    （ThreadingMixIn 是"一个连接一个线程"，不是"一个请求一个线程"）。
    #    设得宽松（300s），避免把慢请求/长响应误杀。
    #    （socketserver.StreamRequestHandler.timeout 默认 None = 永不超时）
    timeout = 300

    # ---- 静音访问日志 ----
    def log_message(self, fmt, *args):
        """wsgiref 默认每个请求往 stderr 打一行访问日志。
        本地桌面端一秒可能十几个静态资源，几分钟就能把日志刷满，
        真正的后端日志会被埋掉 ⇒ 一律静音（错误另行记到项目日志）。"""
        return

    def log_request(self, *args, **kwargs):
        return

    def log_error(self, fmt, *args):
        try:
            message = (fmt % args) if args else str(fmt)
        except Exception:
            message = str(fmt)
        _log("warn", f"HTTP 请求出错: {message}")

    def address_string(self):
        """不返回客户端地址字符串，避免反向 DNS 查询把每个请求拖慢（wsgiref 老坑）"""
        return str(self.client_address[0])

    # ---- 请求体收尾（keep-alive 的必要条件）----
    def _drain_request_body(self, reader) -> bool:
        # 把这次请求没被应用读完的请求体丢掉。
        # 返回 True = 这条连接还是干净的（可以继续服务下一个请求）；
        # False = 必须关掉这条连接。
        #
        # 为什么必须这么做：HTTP/1.1 允许一条连接上跑多个请求，而下一个请求的
        # 请求行紧跟在请求体后面。如果应用只读了半个请求体就返回，剩下的字节
        # 会被下一个循环当成请求行去解析 -> 请求串台（随机 400、拿到上一次的响应）。
        # 桌面端当前只有 GET 路由，但浏览器模式（browsermode.py）有
        # POST /jsbridge/<域>.<方法>，所以这条兜底必须有。
        try:
            expected = int(str(self.headers.get('Content-Length', '') or '0').strip() or '0')
        except Exception:
            expected = 0
        if expected <= 0:
            return True
        remaining = expected - int(getattr(reader, 'count', 0) or 0)
        if remaining <= 0:
            return True
        try:
            # 最多丢 8MB，防御畸形请求头
            remaining = min(remaining, 8 * 1024 * 1024)
            got = reader.read(remaining) or b''
        except Exception:
            return False
        if len(got) < remaining:
            # 请求体没读够（客户端提前断了）-> 连接不可信
            return False
        return True
    # ---- 核心：循环处理同一条连接上的多个请求 ----
    def handle(self):
        while True:
            try:
                self.raw_requestline = self.rfile.readline(65537)
            except (TimeoutError, OSError):
                # 空闲超时（socket timeout）或客户端断开 ⇒ 结束这条连接
                self.close_connection = True
                return
            if not self.raw_requestline:
                # 客户端主动关连接
                self.close_connection = True
                return
            if len(self.raw_requestline) > 65536:
                self.requestline = ""
                self.request_version = ""
                self.command = ""
                try:
                    self.send_error(414)
                except Exception:
                    pass
                return
            if not self.parse_request():
                # 协议错误，parse_request 内部已经回了错误响应
                return

            # ⚠️ 请求体必须读完（否则同一条连接上的下一个请求会串台）
            reader = _CountingReader(self.rfile)
            handler = KeepAliveServerHandler(
                reader,
                self.wfile,
                self.get_stderr(),
                self.get_environ(),
                multithread=True,          # 本服务器是多线程的，WSGI 环境变量要如实反映
            )
            handler.request_handler = self   # 反向指针：让响应处理器能改 close_connection
            try:
                handler.run(self.server.get_app())
            except Exception:
                # 单个请求出错绝不能掀掉整个服务器线程
                _log("err", f"处理请求时异常: {traceback.format_exc(limit=3)}")
            try:
                self.wfile.flush()
            except Exception:
                self.close_connection = True
                return
            if not self._drain_request_body(reader):
                # 请求体没读完 ⇒ 这条连接已经"脏了"，只能关掉
                return

            if self.close_connection:
                # 客户端说 close、或者这次响应只能用 close-delimited body
                return
            # 否则：**继续用同一条连接服务下一个请求**（这就是 keep-alive）


# ======================================================================
# 三、服务器类：线程化 + 大 backlog
# ======================================================================
class KeepAliveServer(socketserver.ThreadingMixIn, WSGIServer):
    """每个连接一个线程（keep-alive 之后线程数比请求数少得多）。

    ⚠️ `daemon_threads = True`：请求线程不能挡住进程退出。
    ⚠️ `block_on_close = False`：默认 True 时 `server_close()` 会等**所有**线程结束，
       keep-alive 连接上的线程会一直等着下一个请求 ⇒ 退出流程会被拖住好几秒。
    ⚠️ `allow_reuse_address = True`：重启时端口还在 TIME_WAIT 里也能马上重新绑定。
       ⚠️⚠️ 但 Windows 的 `SO_REUSEADDR` 语义是"**允许多个 socket 绑同一个端口**"，
       所以"端口有没有被占"**不能**靠 bind 失败来判断（见 `_port_in_use()`）。
    ⚠️ `request_queue_size = 128`：**wsgiref 默认只有 5**！监听 backlog 只有 5 时，
       浏览器一次性开 6 条连接（HTTP/1.1 每个域名 6 条）就会把队列塞满，
       后面的连接被系统直接拒掉 —— 这正是"CSS 偶尔没加载"最可能的机制。
    """

    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True
    request_queue_size = _REQUEST_QUEUE_SIZE


def make_keepalive_server(host: str, port: int, app):
    """建一个（还没开始服务的）keep-alive 服务器对象"""
    return make_server(
        host,
        int(port),
        app,
        server_class=KeepAliveServer,
        handler_class=KeepAliveWSGIRequestHandler,
    )


# ======================================================================
# 四、对外入口：serve() / stop()
# ======================================================================
def _port_in_use(host: str, port: int) -> bool:
    """这个端口是不是已经被别的服务占着？

    ⚠️ **不能用 `allow_reuse_address=True` 的 socket 去试**：Windows 的
    `SO_REUSEADDR` 允许**第二个 socket 绑到同一个端口**（实测：bind 和 listen
    都成功），所以那样试永远返回"没被占"。必须用**不带** SO_REUSEADDR 的
    普通 socket 去 bind —— 实测这样能正确报 `WinError 10048`。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, int(port)))
    except OSError:
        return True
    finally:
        try:
            probe.close()
        except Exception:
            pass
    return False


def serve(app, host: str = "127.0.0.1", port: int = 0, *,
          name: str = "ToolsGCP-http", retries: int = 3,
          allow_port_fallback: bool = True) -> dict:
    """后台线程起一个 keep-alive WSGI 服务器，返回句柄。

    参数
    ----
    app : WSGI 可调用对象（bottle.Bottle 本身就是）
    host : 监听地址，默认只监听本机回环
    port : 0 = 让系统分配空闲端口（**推荐**：绝对不会撞端口）
    retries : 端口冲突时的重试次数（>=1）。第一次用传入的 port，
              之后一律退回 0（系统分配）⇒ **端口冲突绝不会让程序起不来**
    allow_port_fallback : 端口冲突时允不允许偷偷换端口。
              True（默认）适合"自己起服务器 + 自己知道 URL"的用法；
              False 适合"端口是别人定的、URL 也由对方拼"的用法
              （例如 pywebview：它先算出端口再把 f'http://127.0.0.1:{port}/'
                写死给窗口，我们要是偷偷换端口，它拼出来的 URL 就指到空处
                ⇒ 窗口白屏）。False 时只重试**同一个**端口，绝不换。

    返回
    ----
    dict：{"port": int, "url": str, "httpd": KeepAliveServer, "thread": Thread,
           "stop": callable, "host": str, "error": str}
    """
    if app is None:
        raise ValueError("serve() 需要一个 WSGI 应用")

    httpd = None
    last_exc = None
    attempts = max(1, int(retries or 1))
    for attempt in range(attempts):
        if allow_port_fallback:
            bind_port = int(port) if attempt == 0 else 0
            # ⚠️ 先用普通 socket 探端口（Windows 下带 SO_REUSEADDR 的监听者
            #    不会让第二次 bind 失败，光靠 bind 报错探测不到冲突，见 _port_in_use）
            if bind_port > 0 and _port_in_use(host, bind_port):
                _log("warn", f"端口 {bind_port} 已被占用，改让系统自选端口重试")
                bind_port = 0
        else:
            # 严格模式：端口是"别人"定的，换端口 ⇒ 对方的 URL 指到空处
            bind_port = int(port)
            # ⚠️ Windows 上带 SO_REUSEADDR 的 socket **可以绑到已被占用的端口**
            #    （等于把别人的服务抢过来），而我们这个服务器正好开着
            #    allow_reuse_address ⇒ 必须先探一下，占用就当失败重试，
            #    绝不能去抢别人的端口。
            if bind_port > 0 and _port_in_use(host, bind_port):
                last_exc = OSError(f"port {bind_port} is in use")
                _log("warn", f"端口 {bind_port} 已被占用（严格模式不换端口），"
                             f"第 {attempt + 1} 次重试")
                try:
                    time.sleep(0.2)
                except Exception:
                    pass
                continue
        try:
            httpd = make_keepalive_server(host, bind_port, app)
            break
        except OSError as exc:
            last_exc = exc
            _log("warn", f"端口 {bind_port} 起服务失败（{type(exc).__name__}: {exc}），"
                         f"第 {attempt + 1} 次重试")
            try:
                time.sleep(0.2)
            except Exception:
                pass
    if httpd is None:
        raise RuntimeError(f"本地 HTTP 服务启动失败: {last_exc}")

    real_port = int(httpd.server_address[1])
    if int(port) and real_port != int(port):
        _log("warn", f"实际监听端口 {real_port}（原计划 {int(port)}）")

    def _run():
        # 服务线程里的任何异常都不许冒泡到主线程
        try:
            httpd.serve_forever(poll_interval=0.2)
        except Exception:
            _log("err", f"HTTP 服务线程异常退出: {traceback.format_exc(limit=3)}")

    thread = threading.Thread(target=_run, name=name, daemon=True)
    thread.start()

    url = f"http://{host}:{real_port}/"
    info = {
        "port": real_port,
        "url": url,
        "httpd": httpd,
        "thread": thread,
        "host": host,
        "error": "",
    }
    info["stop"] = lambda: stop(info)
    _log("info", f"本地 HTTP 服务已启动: {url}（HTTP/1.1 keep-alive 已启用，"
                 f"监听队列 {_REQUEST_QUEUE_SIZE}）")
    return info


def stop(server_info) -> bool:
    """干净地关掉一个由 `serve()` 起好的服务。返回是否成功。"""
    if isinstance(server_info, dict):
        httpd = server_info.get("httpd")
        thread = server_info.get("thread")
    else:
        httpd = server_info
        thread = None
    if httpd is None:
        return False
    try:
        # `shutdown()` 必须**在别的线程**调用（它要等 serve_forever 返回）
        if thread is not None and thread.is_alive() and thread is threading.current_thread():
            threading.Thread(target=httpd.shutdown, daemon=True).start()
        else:
            httpd.shutdown()
    except Exception as exc:
        _log("warn", f"关闭 HTTP 服务时异常: {type(exc).__name__}: {exc}")
    try:
        httpd.server_close()
    except Exception as exc:
        _log("warn", f"关闭 HTTP 服务套接字时异常: {type(exc).__name__}: {exc}")
    _log("info", "本地 HTTP 服务已关闭")
    return True


# ======================================================================
# 五、给 pywebview 用的 bottle 适配器
# ======================================================================
if bottle is not None:
    class BottleKeepAliveAdapter(bottle.ServerAdapter):
        """让 `bottle.run(app=..., server=本适配器)` 用上我们的 keep-alive 服务器。

        bottle 0.13.4 的 `bottle.run()` 强制要求 server 是 `ServerAdapter` 实例，
        否则直接 `raise ValueError`（"Unknown or unsupported server"）；
        而 pywebview 的 `webview/http.py` 里 `BottleServer.start_server` 是
        `bottle.run(app=app, server=server_adapter, port=server.port, quiet=...)`，
        其中 `server_adapter` 是一个 **类**（`ThreadedAdapter`），
        bottle 会 `server(host=host, port=port, **kargs)` 把它实例化。
        ⇒ 把 `webview.http.ThreadedAdapter` 换成这个类即可（见 `patch_pywebview_server()`）。
        """

        def __init__(self, host="127.0.0.1", port=8080, **options):
            super().__init__(host=host, port=port, **options)
            self.server_info = None
            self.srv = None

        def run(self, handler):
            try:
                # ⚠️ allow_port_fallback=False：pywebview 已经把
                #    f'http://127.0.0.1:{server.port}/' 写死给窗口用了，
                #    我们要是偷偷换端口，窗口就会打开一个空地址 ⇒ 白屏。
                #    端口真被抢时只能重试同一个端口 + 记日志。
                info = serve(handler, host=self.host, port=self.port,
                             name="ToolsGCP-pywebview-http",
                             retries=5, allow_port_fallback=False)
            except Exception as exc:
                # 兜底：keep-alive 服务器起不来时，退回标准 wsgiref，
                # 至少让窗口能打开（功能退化 ≫ 程序起不来）
                _log("err", f"keep-alive 服务器启动失败，退回标准 wsgiref: "
                            f"{type(exc).__name__}: {exc}")
                fallback = wsgiref.simple_server.make_server(self.host, self.port, handler)
                self.srv = fallback
                try:
                    fallback.serve_forever()
                except KeyboardInterrupt:
                    fallback.server_close()
                return
            self.server_info = info
            self.port = info["port"]
            # bottle 的其它适配器都是"阻塞式"的，这里保持一致：
            # 阻塞在服务线程上，直到服务被关掉。
            try:
                info["thread"].join()
            except KeyboardInterrupt:
                stop(info)
            except Exception:
                stop(info)
else:                                            # pragma: no cover
    BottleKeepAliveAdapter = None                  # type: ignore


def patch_pywebview_server() -> bool:
    """把 pywebview 的默认服务器适配器换成我们的 keep-alive 版本。

    * **可重复调用**（幂等）：已经换过就直接返回 True。
    * **失败只记日志、不抛异常**：pywebview 没装 / 版本变了 / 属性名变了，
      都只是退回 pywebview 自带服务器（现状），绝不会让程序起不来。

    ⚠️ 为什么 patch `webview.http.ThreadedAdapter` 而不是改 pywebview 源码：
    `BottleServer.start_server` 里是 `server_adapter = ThreadedAdapter`，
    这是**函数运行时按模块全局名查找**的 ⇒ 只替换模块属性就能生效，
    不用碰 site-packages 里的文件（升级 pywebview 也不会被覆盖）。

    用法（由 lead 决定在哪儿调用，建议在 `create_window()` 之前）：
        from desktop.httpserver import patch_pywebview_server
        patch_pywebview_server()

    ⚠️ **接线位置很重要**：必须在 pywebview **第一次**起服务器之前调用。
    `webview/window.py` 的 `_initialize()` 会在 `is_app(url)` 为真时
    调 `http.start_server(...)`，那时才读 `webview.http.ThreadedAdapter`
    ⇒ 只要在 `create_window()` 之前 patch 过就生效；
    如果之后又创建了新的窗口，pywebview 会复用同一个 global_server
    （地址不变），也不受影响。
    """
    try:
        import webview.http as webview_http
    except Exception as exc:
        _log("warn", f"pywebview 不可用，跳过服务器 patch: {type(exc).__name__}: {exc}")
        return False
    if BottleKeepAliveAdapter is None:
        _log("warn", "bottle 不可用，跳过服务器 patch")
        return False
    try:
        current = getattr(webview_http, "ThreadedAdapter", None)
        if current is BottleKeepAliveAdapter:
            return True
        if current is None:
            _log("warn", "pywebview 里没有 ThreadedAdapter（版本可能变了），跳过 patch")
            return False
        webview_http.ThreadedAdapter = BottleKeepAliveAdapter
        _log("info", "pywebview 的内置服务器已换成 keep-alive 版本")
        return True
    except Exception as exc:
        _log("warn", f"patch pywebview 服务器失败（退回自带服务器）: "
                     f"{type(exc).__name__}: {exc}")
        return False


# ======================================================================
# 六、实测数据（本机 Windows 10/11 + Python 3.13.1 + bottle 0.13.4）
# ======================================================================
# 下面这些数字是开发这个模块时**实际跑出来的**，不是推测。
# 留给后来的人对照，避免重复调研。
#
# 【wsgiref 的坑】
#   · wsgiref.simple_server.WSGIServer.request_queue_size == 5
#     （TCPServer 的默认值；浏览器的 6 条并发连接会把它顶穿）
#   · wsgiref.simple_server.WSGIRequestHandler.protocol_version == 'HTTP/1.0'
#   · WSGIRequestHandler.handle() 只服务一个请求就关连接
#   · BaseHandler.set_content_length() 只在 len(self.result) == 1 时算得出长度
#     ⇒ bottle 的 304 返回值 [b''] 长度正好是 1 ⇒ 命中 ⇒ 自动补 Content-Length: 0
#   · BaseHandler.cleanup_headers() 缺 Content-Length 就调 set_content_length()
#     ⇒ **这里才是 304 挂死的真正根因**（只改 finish_content() 没用，实测过）
#   · BaseHandler.finish_content() 会 setdefault('Content-Length', '0')
#   · socketserver.StreamRequestHandler.timeout 默认 None（永不超时）
#
# 【bottle 0.13.4 的坑】
#   · Bottle.wsgi()：状态码 100/101/204/304 或方法 HEAD 时 body 丢成 []，
#     但 header 里的 Content-Length 是**丢 body 之前**算好的，仍留着
#   · _cast()：空输出补 Content-Length: 0；bytes 输出补 len(out)
#   · bad_headers：304 会剔掉 Content-Length/Content-Type（所以 bottle 自己不塞）
#   · bottle.run()：server 参数必须是 ServerAdapter 实例或子类，否则 raise ValueError；
#     传类时 bottle 会 server(host=host, port=port, **kargs) 实例化它
#
# 【Windows socket 的坑】
#   · 带 SO_REUSEADDR 的第二个 socket **bind 和 listen 都成功**
#     ⇒ 端口冲突不能靠 bind 失败判断；必须用**不带** SO_REUSEADDR 的
#       普通 socket 探 bind（会报 OSError [WinError 10048]）
#   · 探针 socket 不带 SO_REUSEADDR ⇒ 对任何监听者 bind 都会失败
#     ⇒ 探针法可靠
#   · SO_EXCLUSIVEADDRUSE 不能与 SO_REUSEADDR 同设（WinError 10022）
#   · TIME_WAIT 之后普通 bind 成功（与 Linux 不同）
#
# 【pywebview 的坑】
#   · webview/http.py 的 ThreadedAdapter 是**模块全局名**被 start_server 查找
#     ⇒ 替换 webview.http.ThreadedAdapter 就能生效，不用改 site-packages
#   · BottleServer.start_server 先算好 server.port 和 server.address
#     （f'http://127.0.0.1:{port}/'），再起线程跑 bottle.run(...)
#     ⇒ 适配器**必须用指定的端口**，不能偷偷换（换了窗口就白屏）
#   · _get_random_port() 只是 bind 一下就放弃（不 listen），存在竞态
#   · webview/window.py 的 create_window(server=...) 参数无效：
#     "HTTP server path magic" 段里 self._server = None
#   · js_api 走 window.chrome.webview.postMessage，不依赖这个 HTTP 服务器
#     ⇒ url 从 callable app 换成 http://127.0.0.1:<port>/ 是安全的
