# -*- coding: utf-8 -*-
"""浏览器模式收起窗口的行为单测（task-1 第 2 项，**不弹窗**）。

用户原话断句（别再读反）：
  「打开浏览器模式没缩到托盘 bug（任务栏的 ToolsGCP 彻底消失 而不是 还保留在任务栏中显示）」
  → 括号里前半句是**现象**（彻底消失 = 错），后半句是**期望**（任务栏还留着图标）。
  → 正确实现 = `minimize_window()`（SW_MINIMIZE，任务栏保留按钮），
     **不是** `hide_to_tray()`（Visible=false，任务栏按钮一起没了）。

本脚本用桩对象直接跑 `AppShell.open_browser_mode`，断言它调的是 minimize、
没调 hide_to_tray，并且 browser-mode 事件带的是 `minimized`。全程不起窗口。

跑法：python "项目资料-文档与开发测试/_devtest/test_browser_mode_minimize.py"
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

from desktop import browsermode                              # noqa: E402
from desktop.shell import AppShell                           # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


class _Settings:
    settings = {"browser_port": 0}


class _StubShell:
    """只造 open_browser_mode 用到的那几样东西，绝不碰真窗口"""

    def __init__(self):
        self.settings_manager = _Settings()
        self.calls = []
        self.events = []

    def minimize_window(self):
        self.calls.append("minimize_window")
        return True

    def hide_to_tray(self):
        self.calls.append("hide_to_tray")

    def push_event(self, name, payload):
        self.events.append((name, payload))


def run_case(ensure_result):
    stub = _StubShell()
    real = browsermode.ensure_browser_mode
    browsermode.ensure_browser_mode = lambda shell, open_browser=True, port=0: ensure_result
    try:
        out = AppShell.open_browser_mode(stub, notify=True)
    finally:
        browsermode.ensure_browser_mode = real
    return stub, out


print("[1] 服务起成功 → 必须 minimize（任务栏保留图标），不许 hide 进托盘")
stub, out = run_case({"ok": True, "url": "http://127.0.0.1:9/", "started": True})
check("调用了 minimize_window", stub.calls == ["minimize_window"], str(stub.calls))
check("没有调用 hide_to_tray", "hide_to_tray" not in stub.calls, str(stub.calls))
check("返回 ok", out.get("ok") is True, str(out)[:120])
name, payload = stub.events[0] if stub.events else ("", {})
check("browser-mode 事件带 minimized=True",
      name == "browser-mode" and payload.get("minimized") is True,
      str(stub.events))
check("事件里不再有误导性的 hidden_to_tray", "hidden_to_tray" not in payload,
      str(payload))

print("[2] 服务起失败 → 窗口一动不动（用户要看得见『出错了』）")
stub, out = run_case({"ok": False, "error": "端口被占用"})
check("失败时不碰窗口（既没 minimize 也没 hide）", stub.calls == [], str(stub.calls))
check("失败时不推 browser-mode 事件", stub.events == [], str(stub.events))
check("返回 ok=False", out.get("ok") is False, str(out)[:120])

print("[3] 源码层防回归：open_browser_mode 里不许再出现 hide_to_tray")
src = io.open(os.path.join(ROOT, ".ToolsGCP", "desktop", "shell.py"),
              encoding="utf-8").read()
body = re.search(r"def open_browser_mode.*?\n    def minimize_window", src, re.S)
check("能定位 open_browser_mode 函数体", bool(body))
if body:
    text = body.group(0)
    check("函数体里没有 hide_to_tray() 调用", "self.hide_to_tray()" not in text)
    check("函数体里确实调了 minimize_window", "self.minimize_window()" in text)

print()
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL OK")
