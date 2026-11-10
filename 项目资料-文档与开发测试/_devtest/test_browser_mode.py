# -*- coding: utf-8 -*-
"""浏览器模式服务端到端：起服务 → 静态页能取 → js_bridge 能调真后端 → 事件能长轮询 → 跨源被拒"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

# 本文件在 `<仓库根>/项目资料-…/_devtest/` → 往上三层才是仓库根
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

from desktop import browsermode as bm                   # noqa: E402


# ---- 造一个假 shell（带 api 对象），避免起整个桌面程序 ----
class ResourcesApi:
    def list_items(self, keyword=""):
        return {"ok": True, "items": [f"item:{keyword}"]}

    def boom(self):
        raise RuntimeError("故意炸")

    def add(self, a, b=0):
        return {"ok": True, "sum": int(a) + int(b)}


class FakeAppApi:
    def info(self):
        return {"ok": True, "app": "ToolsGCP", "version": "x"}


class FakeApi:
    resources = ResourcesApi()
    app = FakeAppApi()


class FakeShell:
    def __init__(self):
        self.api = FakeApi()
        self.pushed = []

    def push_event(self, name, payload):
        self.pushed.append((name, payload))
        bm.BUS.publish(name, payload)


shell = FakeShell()
res = bm.ensure_browser_mode(shell, open_browser=False)
print("ensure_started:", res)
assert res["ok"] and res["port"] > 0, res
base = res["url"]

# 幂等
res2 = bm.ensure_browser_mode(shell, open_browser=False)
print("second call started:", res2["started"], "same url:", res2["url"] == base)
assert res2["started"] is False and res2["url"] == base


def post(path, body=None, origin=None, headers=None):
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Origin", origin or base.rstrip("/"))
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:200]}


# ① 首页与静态资源（复用 webhost 的路由）
# ⚠️ 这里必须用 `/api/health` 判断"静态路由通了"，不能断言 index.html 的字节数：
#    `pymodels.constants` 是按**入口脚本所在目录**推 CONFIG_DIR 的，本文件从
#    `项目资料-…/_devtest/` 运行时，WEBUI_DIR 会指到 _devtest 旁边（那儿没有 webui/），
#    webhost 于是回它那段"前端入口还没生成"的占位页。生产入口是仓库根的 ToolsGCP.pyw，
#    同一个应用会正常吐出完整 index.html（实测 14 万+ 字节）。
with urllib.request.urlopen(base + "api/health", timeout=10) as r:
    health = json.loads(r.read().decode("utf-8"))
print("GET /api/health ->", r.status, health)
assert r.status == 200 and health.get("ok") is True, "webhost 路由没被复用"

with urllib.request.urlopen(base, timeout=10) as r:
    html = r.read().decode("utf-8", "replace")
print("GET / ->", r.status, "len", len(html),
      "(占位页说明 WEBUI_DIR 指向了 _devtest 旁边，属测试环境现象)")
assert r.status == 200 and len(html) > 200

# ② capabilities（前端要靠它重建 api 对象）
st, caps = post("/jsbridge/capabilities")
print("capabilities ->", st, "methods:", len(caps.get("methods", [])),
      "has resources.list_items:", "resources.list_items" in caps.get("methods", []))
assert st == 200 and "resources.list_items" in caps["methods"]

# ③ 真调用（带参数）
st, out = post("/jsbridge/call/resources.add", {"args": [20, 22]})
print("call resources.add ->", st, out)
assert st == 200 and out["result"]["sum"] == 42

st, out = post("/jsbridge/call/resources.list_items", {"args": ["git"]})
print("call list_items ->", st, out)
assert st == 200 and out["result"]["items"] == ["item:git"]

# ④ 不存在的方法 / 后端抛异常：都要变成结构化错误，不能 500 页面
st, out = post("/jsbridge/call/resources.nope", {"args": []})
print("missing method ->", st, out)
assert st == 404 and out["ok"] is False

st, out = post("/jsbridge/call/resources.boom", {"args": []})
print("backend raise ->", st, out)
assert out["ok"] is False and "故意炸" in out["error"]

# ⑤ 跨源必须被拒（安全边界）
st, out = post("/jsbridge/call/resources.add", {"args": [1, 2]}, origin="http://evil.example")
print("cross-origin ->", st, out)
assert st == 403, "跨源没被挡住"

# ⑥ 事件长轮询：后端 push_event → 浏览器端能取到
bm.BUS.publish("download.progress", {"percent": 33})
t0 = time.time()
st, out = post("/jsbridge/events/poll")
print("events poll ->", st, "took %.2fs" % (time.time() - t0), out.get("events"))
assert st == 200 and out["events"] and out["events"][0]["name"] == "download.progress"

# 空队列时应该等满 ~EVENT_POLL_WAIT_S 再返回空（不是立刻空转返回）
t0 = time.time()
st, out = post("/jsbridge/events/poll")
waited = time.time() - t0
print("empty poll waited %.2fs events=%s" % (waited, out.get("events")))
assert out["events"] == [] and waited >= 1.0

# ⑦ 停止
bm.SERVER.stop()
try:
    urllib.request.urlopen(base, timeout=3)
    print("!! 停了还能访问")
except Exception as e:
    print("after stop, server closed:", type(e).__name__)

print("\n*** BROWSER MODE SERVER PASSED ***")
