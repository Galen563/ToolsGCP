# -*- coding: utf-8 -*-
"""真机最小可行性验证：能不能在子进程主线程起一个 pywebview 窗口。

目的：本轮用户允许弹窗，我要在真机上确认"浅色主题首帧不再黑"这条修复。
但真跑整个 ToolsGCP.pyw 需要 pythonnet/WebView2 都正常 —— 上一轮 teammate 在沙箱里
撞到 `Failed to initialize Python.Runtime.dll`（子进程继承沙箱导致），
所以先用**最小**脚本确认这条路能不能走通，走得通再上真程序。

跑法：python "项目资料-文档与开发测试/_devtest/probe_pywebview_canary.py"
"""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(BASE, ".ToolsGCP"), os.path.join(BASE, ".ToolsGCP", "modules")]

LOG = os.path.join(HERE, "_canary_result.txt")
out = []


def log(msg):
    out.append(str(msg))
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(str(msg) + "\n")
    except Exception:
        pass


def main():
    try:
        with open(LOG, "w", encoding="utf-8") as fh:
            fh.write("")
    except Exception:
        pass
    log("step=import_webview")
    try:
        import webview
    except Exception as exc:
        log("FAIL import " + type(exc).__name__ + " " + str(exc)[:200])
        return 2
    log("step=import_winforms_dependents")
    try:
        import clr  # pythonnet 探测：这步在沙箱里最容易炸
        log("clr OK")
    except Exception as exc:
        log("CLR_FAIL " + type(exc).__name__ + " " + str(exc)[:200])
        return 3
    log("step=create_window")
    state = {"done": False}
    try:
        win = webview.create_window("TG-CANARY", url="about:blank",
                                    width=300, height=200, hidden=True)
    except Exception as exc:
        log("CREATE_FAIL " + type(exc).__name__ + " " + str(exc)[:200])
        return 4

    def gui_started():
        try:
            hwnd = 0
            try:
                from desktop.native import frame
                hwnd = frame.hwnd_of_window(win) or 0
            except Exception as exc:
                log("hwnd probe fail " + str(exc)[:120])
            log("GUI_STARTED hwnd=" + str(hwnd))
            state["done"] = True
        except Exception as exc:
            log("started_cb fail " + str(exc)[:160])
        finally:
            try:
                win.destroy()
            except Exception:
                pass

    log("step=webview.start")
    try:
        webview.start(gui_started, gui="edgechromium")
    except Exception as exc:
        log("START_FAIL " + type(exc).__name__ + " " + str(exc)[:200])
        return 5
    log("DONE ok=" + str(state["done"]))
    return 0 if state["done"] else 6


if __name__ == "__main__":
    sys.exit(main())
