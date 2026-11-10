# -*- coding: utf-8 -*-
"""浏览器模式 = **真隐藏到托盘**（任务栏不留图标）+ Ctrl+Shift+O 可切回桌面。

⚠️⚠️ 本脚本**推翻** test_browser_mode_minimize.py 的契约（那个保留作历史证据）：
   上一轮我把用户那句「任务栏的ToolsGCP彻底消失而不是还保留在任务栏中显示」
   按"前半是现象、后半是期望"断句，实现成了 minimize（任务栏保留图标）。
   本轮用户原话说清了：「切换到浏览器模式按理应该自动到托盘 任务栏无ToolsGCP」，
   并在选项里选了「真缩进托盘，任务栏不留图标」→ 行为改回 hide_to_tray()。

覆盖 4 件事（全程不起窗口，桩对象跑真实方法）：
  [1] 进浏览器模式 → 调 hide_to_tray、**不调** minimize_window、置 _browser_mode_hidden
  [2] 起服务失败 → 不碰窗口、不留标记（失败时窗口留着，用户看得见"出错了"）
  [3] 切回桌面 → 清标记 + show_window + 事件 hidden=False；**不关 HTTP 服务**
  [4] 两道闸门：_browser_mode_hidden 期间 api.window.show / api.window.center 不掀窗口
  [5] 用户从托盘呼出（show_window）→ 标记自动清掉，闸门放行

跑法：python "项目资料-文档与开发测试/_devtest/test_browser_mode_tray.py"
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__ + "/..")))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(BASE, ".ToolsGCP"),
                os.path.join(BASE, ".ToolsGCP", "modules")]

FAILS = []


def check(name, cond, extra=""):
    print(("  OK    " if cond else "  FAIL  ") + name + (f"  <- {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


SHELL_PY = os.path.join(BASE, ".ToolsGCP", "desktop", "shell.py")
API_PY = os.path.join(BASE, ".ToolsGCP", "desktop", "api", "__init__.py")
src = io.open(SHELL_PY, encoding="utf-8").read()

# =========================================================================
# 桩：跑真实的 AppShell.open_browser_mode / toggle_browser_mode
# =========================================================================
from desktop.shell import AppShell                                  # noqa: E402
from desktop import browsermode                                     # noqa: E402


class Stub(AppShell):
    """只桩掉"起服务 / 动窗口"，其余逻辑跑真实代码"""

    def __init__(self, ensure_result):
        # 故意不走 AppShell.__init__（那会建窗口/起线程）
        self._browser_mode_hidden = False
        self._startup_hidden = False
        self._teardown_started = False
        self._quitting = False
        self.calls = []
        self.events = []
        self.settings_manager = None
        self.window = None
        self.tray = None
        self._ensure = ensure_result

    def hide_to_tray(self):
        self.calls.append("hide_to_tray")

    def minimize_window(self):
        self.calls.append("minimize_window")
        return True

    def show_window(self):
        self.calls.append("show_window")
        return True

    def push_event(self, name, payload):
        self.events.append((name, payload))

    def _log(self, *a, **k):                          # noqa: D102
        pass


def run_open(result):
    """把 browsermode.ensure_browser_mode 换成桩，跑真实 open_browser_mode"""
    stub = Stub(result)
    real = browsermode.ensure_browser_mode
    browsermode.ensure_browser_mode = lambda shell, open_browser=True, port=0: result
    try:
        out = AppShell.open_browser_mode(stub)
    finally:
        browsermode.ensure_browser_mode = real
    return stub, out


print("[1] 进浏览器模式 → 真隐藏到托盘（任务栏不留图标）")
stub, out = run_open({"ok": True, "url": "http://127.0.0.1:9999/", "started": True,
                      "port": 9999, "opened": True, "error": ""})
check("调用了 hide_to_tray", "hide_to_tray" in stub.calls, str(stub.calls))
check("没有调用 minimize_window（上一轮的误读已纠正）",
      "minimize_window" not in stub.calls, str(stub.calls))
check("置了 _browser_mode_hidden 闸门标记", stub._browser_mode_hidden is True)
name, payload = stub.events[0]
check("browser-mode 事件带 hidden=True（字段语义跟着改了）",
      name == "browser-mode" and payload.get("hidden") is True, json.dumps(payload))

print("[2] 起服务失败 → 不碰窗口、不留标记")
stub2, out2 = run_open({"ok": False, "url": "", "started": False, "port": 0,
                        "opened": False, "error": "端口被占用"})
check('没动窗口（失败时窗口留着，用户至少看得见"出错了"）', stub2.calls == [], str(stub2.calls))
check("标记保持 False", stub2._browser_mode_hidden is False)
check("返回原样的失败结果", out2.get("ok") is False and out2.get("error") == "端口被占用")

print("[3] 再按一次 Ctrl+Shift+O → 切回桌面")
stub3, _ = run_open({"ok": True, "url": "http://127.0.0.1:9999/", "started": True,
                     "port": 9999, "opened": True, "error": ""})
# ⚠️ browsermode.SERVER.url / .running 是**只读 property**（从内部状态算出来的），
#    桩不掉它们 —— 直接桩 AppShell._browser_url（切回桌面时只用来填事件里的 url 字段）。
real_bu = AppShell._browser_url
AppShell._browser_url = lambda self: "http://127.0.0.1:9999/"
try:
    got = AppShell.toggle_browser_mode(stub3)
finally:
    AppShell._browser_url = real_bu
check('已经藏着 → 这次是"出"：呼出主窗口', "show_window" in stub3.calls, str(stub3.calls))
check("标记已清（之后前端事件不再被闸门吞掉）", stub3._browser_mode_hidden is False)
check("返回 mode=desktop", got.get("mode") == "desktop", json.dumps(got))
check('切回桌面**不关** HTTP 服务（浏览器页签还要用）',
      "shutdown" not in str(stub3.calls).lower()
      and not hasattr(AppShell, "close_browser_mode"),
      "存在 close_browser_mode 说明有关服务路径，需复核")
last = stub3.events[-1][1]
check("事件带 hidden=False", last.get("hidden") is False, json.dumps(last))

print('[4] 没在浏览器模式（或用户自己显示过窗口）→ 按快捷键是"进"')
stub4 = Stub({"ok": True, "url": "x", "started": True, "port": 1, "opened": True, "error": ""})
stub4._browser_mode_hidden = False
calls = []
real_open = AppShell.open_browser_mode
AppShell.open_browser_mode = lambda self, notify=True: (calls.append("open"), {"ok": True})[1]
try:
    AppShell.toggle_browser_mode(stub4)
finally:
    AppShell.open_browser_mode = real_open
check("走 open_browser_mode（重新进）", calls == ["open"], str(calls))
check("没有直接 show_window", "show_window" not in stub4.calls, str(stub4.calls))

print("[5] 闸门：api.window.show / window.center 在浏览器模式隐藏期间不掀窗口")
api_src = io.open(API_PY, encoding="utf-8").read()


class MiniShell:
    def __init__(self, hidden):
        self._browser_mode_hidden = hidden
        self._startup_hidden = False
        self.shown = 0
        self.window = None
        self.settings_manager = None

    def show_window(self):
        self.shown += 1
        return True

    def hwnd(self):
        return 0


from desktop.api import WindowDomain                                # noqa: E402

hidden = MiniShell(True)
wd = WindowDomain(hidden)
r1 = wd.show()
check("隐藏期间 window.show 被挡（skipped）",
      r1.get("ok") is True and r1.get("skipped") is True and hidden.shown == 0,
      json.dumps(r1))
r2 = wd.center()
check('隐藏期间 window.center 也被挡（resize/move 带 SWP_SHOWWINDOW，'
      '不挡就等于"桌面窗口自己蹦到最前"）',
      r2.get("skipped") is True, json.dumps(r2))

visible = MiniShell(False)
wd2 = WindowDomain(visible)
r3 = wd2.show()
check("正常状态（非浏览器模式）window.show 照常呼出并置前",
      r3.get("ok") is True and not r3.get("skipped") and visible.shown == 1,
      json.dumps(r3))

print("[6] 源码层防回归")
body = re.search(r"def open_browser_mode.*?\n    def browser_mode_status|def open_browser_mode[\s\S]*?\n    def (?!open_browser_mode)", src)
text = body.group(0) if body else ""
check("open_browser_mode 里调的是 hide_to_tray", "self.hide_to_tray()" in text, text[:60])
check("open_browser_mode 里不再调 minimize_window",
      "self.minimize_window()" not in text)
check("show_window 里会清掉 _browser_mode_hidden（托盘呼出后闸门放行）",
      "_browser_mode_hidden = False" in src[src.find("def show_window"):src.find("def hide_to_tray")])

print("=" * 72)
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL OK")
