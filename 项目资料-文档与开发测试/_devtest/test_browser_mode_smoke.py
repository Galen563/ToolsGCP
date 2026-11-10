# -*- coding: utf-8 -*-
"""浏览器模式完整冒烟：真实 Api 域 → capabilities → bridge 伪装对象 → 事件流。

模拟浏览器里的前端行为：
  1. fetch capabilities → 重建 api 对象（Proxy）
  2. api.<域>.<方法>(...) 走 /jsbridge/call
  3. shell.push_event → 长轮询取到
并验证桌面端零影响（webhost 应用本身没有 /jsbridge 路由）。

跑法： python 项目资料-文档与开发测试/_devtest/test_browser_mode_smoke.py
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]

from desktop import browsermode as bm                   # noqa: E402


class _Api:
    """接近真实 Api 形状的假对象（真实 Api 会碰 settings_manager，冒烟不起整个壳）"""

    def ping(self):
        return {"ok": True, "pong": True}

    def app_info(self):
        return {"ok": True, "app": "ToolsGCP", "version": "test"}

    def _private(self):                                  # 必须被 capabilities 排除
        return {"ok": True}


class _Shell:
    api = _Api()

    def push_event(self, name, payload):
        bm.BUS.publish(name, payload)


res = bm.ensure_browser_mode(_Shell(), open_browser=False)
assert res["ok"], res
base = res["url"]
print("server:", base)

# ① capabilities
# ⚠️ 必须带 Origin：桥的同源校验（_same_origin）对没有 Origin/Referer 的请求一律拒绝
#    （浏览器里的同源 fetch 一定会带；不带的是 curl 之类的陌生客户端）。
caps_req = urllib.request.Request(base + "jsbridge/capabilities", data=b"{}", method="POST",
                                  headers={"Origin": base.rstrip("/")})
with urllib.request.urlopen(caps_req, timeout=10) as r:
    caps = json.loads(r.read().decode())
methods = set(caps["methods"])
print("caps methods:", sorted(methods))
assert "ping" in methods and "app_info" in methods, methods
assert not any(m.startswith("_") for m in methods), "私有方法泄漏进 capabilities"


# ② 模拟前端 Proxy 的调用路径
def proxy_call(path, args):
    req = urllib.request.Request(base + "jsbridge/call/" + path,
                                 data=json.dumps({"args": args}).encode(),
                                 method="POST",
                                 headers={"Origin": base.rstrip("/"),
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


out = proxy_call("ping", [])
print("api.ping() ->", out)
assert out == {"ok": True, "result": {"ok": True, "pong": True}}

out = proxy_call("app_info", [])
assert out["result"]["version"] == "test"

# ③ 桌面端隔离：webhost 应用本身没有 /jsbridge 路由
from desktop.webhost import create_app as _create_base           # noqa: E402
base_app = _create_base()

def _capture(environ):
    """跑一次 base_app，返回它给的状态行（start_response 带齐 3 参签名）"""
    captured = {}

    def _sr(status, headers, exc_info=None):
        captured["status"] = status
        return lambda *a: None

    environ = dict(environ)
    body = base_app(environ, _sr)
    return captured.get("status", "?"), b"".join(body or [])

# 用 base_app 直接伺服一个 /jsbridge 请求 → 期望 404（bottle 的默认兜底）
from wsgiref.util import setup_testing_defaults                   # noqa: E402
environ = {"PATH_INFO": "/jsbridge/call/ping", "REQUEST_METHOD": "POST",
           "CONTENT_LENGTH": "2", "wsgi.input": None}
status, _body = _capture(environ)
print("desktop webhost on /jsbridge/call/ping ->", status)
assert status.startswith("404") or status.startswith("405"), \
    f"桌面端不该有桥路由（得到 {status}）"

# ④ 事件：push_event → 长轮询取到（模拟 ai.stream / download.progress）
_Shell().push_event("ai.stream", {"stream_id": "s1", "delta": "你好"})
req = urllib.request.Request(base + "jsbridge/events/poll", data=b"{}", method="POST",
                             headers={"Origin": base.rstrip("/")})
with urllib.request.urlopen(req, timeout=10) as r:
    evs = json.loads(r.read().decode())["events"]
print("polled events:", [e["name"] for e in evs])
assert evs and evs[0]["name"] == "ai.stream" and evs[0]["payload"]["delta"] == "你好"

bm.SERVER.stop()
print("\n*** BROWSER MODE SMOKE PASSED ***")
