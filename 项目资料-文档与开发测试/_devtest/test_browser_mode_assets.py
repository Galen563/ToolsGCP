"""浏览器模式端到端探针：用**前端真正会请求的 URL**逐个验证，尤其是含空格/中文的文件名。

为什么单独写这个：用户报"浏览器模式下图片、资源、配置全部加载不上来"。
静态路由本身是 webhost 原样转交的，但一旦经过 wsgiref + 浏览器编码，
含空格 / 中文 / 百分号编码的路径最容易出问题 —— 所以要按真实 URL 逐一实测。

跑法（必须在仓库根，或让它自己算根）：
    python "项目资料-文档与开发测试/_devtest/test_browser_mode_assets.py"
"""
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
for _ in range(6):
    ROOT = os.path.dirname(ROOT)
    if os.path.isdir(os.path.join(ROOT, ".ToolsGCP")):
        break
# ⚠️ constants.CONFIG_DIR = dirname(sys.argv[0]) + ".ToolsGCP"
# 从 _devtest 目录直接跑会让它算成 `_devtest/.ToolsGCP` → 所有静态路由 404（假故障）。
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]

from desktop import browsermode as bm                      # noqa: E402
from desktop.api import Api                                # noqa: E402


class _StubShell:
    """只要能提供 api 就够：capabilities 会把 Api 的域/方法全列出来"""

    def __init__(self):
        self.api = Api(self)


def main() -> int:
    shell = _StubShell()
    srv = bm.BrowserServer()
    started = srv.ensure_started(shell, port=0)
    if not started.get("ok"):
        print("FAIL 服务起不来:", started)
        return 1
    base = srv.url

    # 前端真正请求的 URL（含空格与中文文件名 + 真实图标名）
    paths = [
        "/",
        "/static/js/app.js",
        "/static/js/icons.js",
        "/static/js/rich-input.js",
        "/static/css/base.css",
        "/static/css/ai-fixes.css",
        "/res/logo.png",
        "/res/ToolsGCP-Resources.json",
        "/res/image/icon/TG-000001.png",
        "/res/image/" + urllib.parse.quote("Galen563 png.png"),      # 文件名里有空格
        "/res/image/" + urllib.parse.quote("微信Galen563的ToolsGCP项目赞助.jpg"),
        "/res/image/qq/" + urllib.parse.quote("ToolsGCP-改进建议群.jpg"),
        "/res/plugins/gcp-ai-agent/config.html",
        "/res/plugins/gcp-plugin-maker/config.html",
        "/api/health",
    ]
    bad = 0
    print("== 静态与资源路由（浏览器里靠这些出图/加载配置） ==")
    for p in paths:
        req = urllib.request.Request(base + p)
        req.add_header("Origin", base)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = resp.read()
                print(f"  OK   {resp.status} {len(body):>8}B  {p}")
        except Exception as exc:                            # noqa: BLE001
            bad += 1
            print(f"  FAIL ------------  {p}   {exc}")

    print("== jsbridge ==")
    req = urllib.request.Request(base + "/jsbridge/capabilities", method="POST", data=b"{}",
                                headers={"Origin": base, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        import json as _json
        caps = _json.loads(resp.read().decode("utf-8"))
    methods = caps.get("methods") or []
    print(f"  capabilities: ok={caps.get('ok')} mode={caps.get('mode')} methods={len(methods)}")
    # 前端启动必依赖的几条（名字以真实 Api 域为准：settings 域是 get/set，不是 get_all）
    for need in ("resources.all", "settings.get", "settings.set", "ai.sessions",
                 "app.info", "favorites.list", "window.state"):
        mark = "OK " if need in methods else "MISS"
        print(f"  {mark}  {need}")
        if need not in methods:
            bad += 1

    # 同源校验：不带 Origin 必须 403（安全边界，别改坏）
    req = urllib.request.Request(base + "/jsbridge/capabilities", method="POST", data=b"{}")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            print(f"  FAIL 无 Origin 竟然通过 ({resp.status}) —— 安全边界破了")
            bad += 1
    except urllib.error.HTTPError as exc:
        print(f"  OK   无 Origin 被拒: HTTP {exc.code}")

    # localhost 别名 + 省略端口 的比较坑：parsed.port 为 None 时必须仍能通过
    from desktop.browsermode import _same_origin                      # noqa: E402
    cases = [
        ({"HTTP_ORIGIN": f"http://127.0.0.1:{srv.port}"}, True, "127.0.0.1 带端口"),
        ({"HTTP_ORIGIN": f"http://localhost:{srv.port}"}, True, "localhost 带端口"),
        ({"HTTP_ORIGIN": "http://localhost"}, False, "localhost 无端口（≠本端口）"),
        ({"HTTP_ORIGIN": "http://evil.example"}, False, "外部域名"),
        ({"HTTP_REFERER": f"http://127.0.0.1:{srv.port}/"}, True, "Referer 同源"),
        ({}, False, "什么都没带"),
    ]
    print("== 同源校验 ==")
    for env, want, label in cases:
        env = dict(env)
        env.setdefault("HTTP_HOST", f"127.0.0.1:{srv.port}")
        got = _same_origin(env, srv.port)
        mark = "OK  " if got == want else "FAIL"
        if got != want:
            bad += 1
        print(f"  {mark} {label}: {got} (期望 {want})")

    # 并发：capabilities + 事件长轮询 + 若干 call 不能互相饿死
    import threading
    results = {}

    def hit(key, path, method="GET", data=None):
        rq = urllib.request.Request(base + path, method=method, data=data,
                                    headers={"Origin": base,
                                             "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(rq, timeout=20) as rp:
                results[key] = (rp.status, len(rp.read()))
        except Exception as exc:                            # noqa: BLE001
            results[key] = ("ERR", str(exc)[:60])

    print("== 并发（含 2.5s 长轮询占线） ==")
    threads = [threading.Thread(target=hit, args=("poll", "/jsbridge/events/poll", "POST", b"{}")),
               threading.Thread(target=hit, args=("caps", "/jsbridge/capabilities", "POST", b"{}")),
               threading.Thread(target=hit, args=("app", "/static/js/app.js")),
               threading.Thread(target=hit, args=("img", "/res/logo.png"))]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=25)
    for k, v in results.items():
        print(f"  {k}: {v}")
        if v[0] != 200:
            bad += 1

    srv.stop()
    print("\n=== 结论：%s ===" % ("全部通过" if bad == 0 else f"{bad} 项失败"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
