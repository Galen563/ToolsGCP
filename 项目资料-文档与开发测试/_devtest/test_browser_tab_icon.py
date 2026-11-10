# -*- coding: utf-8 -*-
"""浏览器模式页签「程序图标 + 名称 ToolsGCP」的离线自检（task-1 第 1 项）。

不弹窗、不起浏览器、零第三方依赖：直接手工构造 WSGI environ 打 webhost 的应用，
再打一遍浏览器模式那层（bridge_app），确认两端拿到的 HTML / favicon 完全一致。

断言：
  ① index.html 的 <head> 里有 <link rel="icon" … /res/logo.png>
     （没有它浏览器只会去要 /favicon.ico，本地 WSGI 没这个文件 → 页签只剩默认地球图标）。
  ② <title>ToolsGCP</title>（页签名称）。
  ③ GET /res/logo.png → 200 + image/png + 真是 PNG 字节。
  ④ 浏览器模式 bridge_app 对 / 与 /res/logo.png 的行为与桌面端**逐字节一致**
     （两端页签图标同源，不会出现"桌面有图标、浏览器没有"）。
  ⑤ 桌面窗口标题常量 WINDOW_TITLE == "ToolsGCP"。

跑法：python "项目资料-文档与开发测试/_devtest/test_browser_tab_icon.py"
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

from desktop import webhost                                 # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def call(app, path, method="GET", query="", host="127.0.0.1:0"):
    """最小 WSGI 调用：返回 (status, headers_dict, body_bytes)"""
    environ = {
        "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
        "SERVER_NAME": "127.0.0.1", "SERVER_PORT": host.rsplit(":", 1)[-1],
        "SERVER_PROTOCOL": "HTTP/1.1", "HTTP_HOST": host,
        "wsgi.url_scheme": "http", "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": sys.stderr, "SCRIPT_NAME": "",
    }
    box = {}

    def start_response(status, headers, exc_info=None):
        box["status"] = status
        box["headers"] = dict(headers)
        return lambda data: None

    chunks = app(environ, start_response)
    body = b"".join(c if isinstance(c, bytes) else str(c).encode("utf-8") for c in chunks)
    try:
        close = getattr(chunks, "close", None)
        if callable(close):
            close()
    except Exception:
        pass
    return box.get("status", ""), box.get("headers", {}), body


HTML = io.open(os.path.join(ROOT, ".ToolsGCP", "webui", "index.html"),
               encoding="utf-8").read()

print("[1] index.html 的 <head>：favicon + 标题")
head = HTML[:HTML.find("</head>")]
title = re.search(r"<title>(.*?)</title>", head, re.S)
check("<title> 是 ToolsGCP", bool(title) and title.group(1).strip() == "ToolsGCP",
      title.group(1).strip() if title else "没有 title")
links = re.findall(r"<link[^>]+rel=[\"'](?:shortcut )?icon[\"'][^>]*>", head, re.I)
check("有 <link rel=\"icon\">", bool(links), str(links))
check("favicon 指向 /res/logo.png（复用既有 /res 路由，不新增文件/路由）",
      any("/res/logo.png" in l for l in links), str(links))
check("声明了 type=image/png", any("image/png" in l for l in links), str(links))

print("[2] webhost 路由：/res/logo.png 真的端得出图")
app = webhost.create_app()
status, headers, body = call(app, "/res/logo.png")
check("GET /res/logo.png → 200", status.startswith("200"), status)
check("响应非空（>1KB）", len(body) > 1000, f"{len(body)} 字节")
check("Content-Type = image/png", "image/png" in (headers.get("Content-Type") or ""),
      headers.get("Content-Type"))
check("字节流真是 PNG（签名 89 50 4E 47）", body[:4] == b"\x89PNG", str(body[:4]))

print("[3] GET / 的 HTML 里带着那条 link（浏览器才会去要 favicon）")
status, headers, idx_body = call(app, "/")
text = idx_body.decode("utf-8", "replace")
check("GET / → 200", status.startswith("200"), status)
check("HTML 含 rel=\"icon\"", 'rel="icon"' in text)
check("HTML 含 <title>ToolsGCP</title>", "<title>ToolsGCP</title>" in text)
check("禁缓存头还在（改完刷新立刻生效）",
      "no-store" in (headers.get("Cache-Control") or ""), headers.get("Cache-Control"))

print("[4] 浏览器模式 bridge_app：与桌面端逐字节一致（两端页签同源）")
from desktop import browsermode                              # noqa: E402

# create_bridge_app(shell, base_app, port)：静态/资源路径只是原样转给 base_app，
# shell 只在 /jsbridge/* 里用 → 这里传 None 足够（不碰任何真实外壳）。
bridge = browsermode.create_bridge_app(None, app, 0)
home = ""
for path in ("/", "/res/logo.png"):
    s1, h1, b1 = call(app, path)
    s2, h2, b2 = call(bridge, path)
    check(f"bridge_app {path} 状态一致", s1 == s2, f"{s1} vs {s2}")
    check(f"bridge_app {path} 字节数一致", len(b1) == len(b2), f"{len(b1)} vs {len(b2)}")
    if path == "/":
        home = b2.decode("utf-8", "replace")
check("bridge_app 透传的 HTML 里 favicon link 还在（浏览器模式同样有图标）",
      'rel="icon"' in home and "<title>ToolsGCP</title>" in home)

print("[5] 桌面端窗口标题常量")
from desktop.shell import WINDOW_TITLE                       # noqa: E402

check('shell.WINDOW_TITLE == "ToolsGCP"', WINDOW_TITLE == "ToolsGCP", repr(WINDOW_TITLE))

print()
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL OK")
