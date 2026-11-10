# -*- coding: utf-8 -*-
"""浏览器模式并发压力测试：真起桥服务，同时打 24 路请求（静态 + 资源 + 桥调用 + 长轮询）。

为什么单独有这一份：修好"服务器其实是串行的"之后，webhost 的 bottle 路由
第一次被**真正并发**地访问（以前一次只有一个请求在处理，任何共享状态的竞态
都被串行化掩盖了）。这个脚本用来确认改动没有把并发问题带进来。

跑法： python "项目资料-文档与开发测试/_devtest/test_browser_mode_concurrency.py"
"""
import concurrent.futures as cf
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]      # ← 资源根按真实入口算
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

# ⚠️ Windows 控制台默认 GBK：结尾那句结论里有 ✅/❌，不重设编码会在**打印时**抛
#    UnicodeEncodeError 把整个测试判成失败（实测崩在最后一行，前面 48 个请求全过）。
#    和 test_ai_versions.py 用同一套口径。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                               # noqa: BLE001
        pass

from pymodels.constants import CONFIG_DIR            # noqa: E402
from pymodels.core.settings_manager import SettingsManager  # noqa: E402
from desktop import browsermode as bm                # noqa: E402
from desktop.api import Api                          # noqa: E402

# ⚠️ 设置必须用**临时目录**：真实配置里 load_settings 会跑一次性迁移并回写文件，
#    自检脚本绝不能改用户数据（AGENTS.md 里 update_setting 那个开关只挡 update，
#    挡不住迁移里的 save_settings，所以只能换目录）。
TMP_CFG = tempfile.mkdtemp(prefix="tgcp-conc-")
with open(os.path.join(TMP_CFG, "toolsgcp_config.json"), "w", encoding="utf-8") as fh:
    json.dump({"hotkey_enabled": True, "hotkey_browser": "Ctrl+Caps+O"}, fh)


class Shell:
    """只提供 Api 需要的最小接口（不起窗口/托盘）"""

    def __init__(self):
        self.settings_manager = SettingsManager(config_dir=TMP_CFG)
        self.language_manager = None
        self.favorites_manager = None
        self.privacy_manager = None
        self.announcement_store = None
        self.api = None
        self.started_at = time.time()
        self._teardown_started = False
        self._quitting = False
        self.window = None

    def push_event(self, name, payload):
        bm.BUS.publish(name, payload)

    def browser_mode_status(self):
        return {"ok": True, "running": True, "url": "", "port": 0}


shell = Shell()
shell.api = Api(shell)
res = bm.ensure_browser_mode(shell, open_browser=False)
assert res["ok"], res
BASE = res["url"]
ORIGIN = BASE.rstrip("/")
print(f"服务: {BASE}  真实配置: {CONFIG_DIR}")

PATHS = [
    ("GET", ""),
    ("GET", "static/js/app.js"),
    ("GET", "static/js/icons.js"),
    ("GET", "static/css/base.css"),
    ("GET", "static/css/variables.css"),
    ("GET", "res/logo.png"),
    ("GET", "res/ToolsGCP-Resources.json"),
    ("GET", "res/image/icon/TG-000001.png"),
    ("GET", "api/health"),
    ("POST", "jsbridge/capabilities"),
    ("POST", "jsbridge/call/app.info"),
    ("POST", "jsbridge/call/resources.all"),
    ("POST", "jsbridge/call/settings.get"),
    ("POST", "jsbridge/call/favorites.list"),
    ("POST", "jsbridge/call/ping"),
    ("POST", "jsbridge/events/poll"),
]


def hit(job):
    method, path = job
    url = BASE + path
    data = b"{}" if method == "POST" else None
    headers = {"Origin": ORIGIN}
    if method == "POST":
        headers["Content-Type"] = "application/json"
        body = json.dumps({"args": []}).encode() if path.startswith("jsbridge/call/") else b"{}"
        data = body
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = r.read()
            return (path, r.status, len(payload), (time.time() - t0) * 1000, None,
                    payload[:1])
    except urllib.error.HTTPError as e:
        return (path, e.code, 0, (time.time() - t0) * 1000, str(e)[:80], b"")
    except Exception as e:                            # noqa: BLE001
        return (path, "ERR", 0, (time.time() - t0) * 1000, repr(e)[:80], b"")


# 3 轮 × 16 条 = 48 个请求，最大 24 并发
jobs = PATHS * 3
t_start = time.time()
with cf.ThreadPoolExecutor(max_workers=24) as pool:
    results = list(pool.map(hit, jobs))
total = time.time() - t_start

bad = [r for r in results if r[1] != 200]
zero = [r for r in results if r[1] == 200 and r[2] == 0]
slow = [r for r in results if r[3] > 6000]
print(f"\n{len(jobs)} 个请求（24 并发，3 轮），总耗时 {total:.2f}s")
print(f"  非 200: {len(bad)}   零字节: {len(zero)}   >6s: {len(slow)}")
worst = max(results, key=lambda r: r[3])
print(f"  最慢一条: {worst[0] or '/'} {worst[3]:.0f} ms")

for path, status, size, ms, err, head in sorted(results, key=lambda x: -x[3])[:8]:
    print(f"   {status}  {size:>7}B  {ms:>7.0f}ms  /{path}" + (f"  {err}" if err else ""))

# 静态资源必须**内容完整**（并发下 bottle 的 route 复用不能串包）
by_path = {}
for r in results:
    by_path.setdefault(r[0], []).append(r)
# ⚠️ 这些路径的响应体**本来就每次不同**（ping 带 ts=time.time()、poll 带事件批次），
#    拿字节数一致性判"串包"对它们没有意义，排除掉（静态资源/资源库仍然严格判）。
VOLATILE = {"jsbridge/call/ping", "jsbridge/events/poll", "jsbridge/capabilities"}
mismatch = {p: sorted({x[2] for x in v}) for p, v in by_path.items()
            if p not in VOLATILE and len({x[2] for x in v}) > 1}
print(f"  同一路径多次请求字节数不一致: {mismatch or '无'}")

# 桥调用在并发下**不能串包**：同一个方法的多次响应必须是同一份内容
for probe in ("jsbridge/call/app.info", "jsbridge/call/settings.get",
              "jsbridge/call/resources.all"):
    sizes = sorted({x[2] for x in by_path.get(probe, [])})
    if len(sizes) > 1:
        print(f"  ❌ {probe} 并发下内容长度不稳定: {sizes}")
        mismatch[probe] = sizes

ok = (not bad and not zero and not slow and not mismatch
      and by_path.get("", [{"", 200, 0}])[0][2] > 100000)
bm.SERVER.stop()
shutil.rmtree(TMP_CFG, ignore_errors=True)
print("\n结论:", "✅ 并发正常（无排队、无串包、无非 200）" if ok else "❌ 有问题")
sys.exit(0 if ok else 1)
