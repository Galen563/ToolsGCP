"""Ctrl+左键"静默打开"是否真的不抢焦点的现场测试

⚠️ 这个脚本**会真的用系统默认浏览器打开一个网址**（默认 example.com）——
   验证的就是"浏览器会不会把前台抢走"，所以必须有真浏览器参与。

用法：
    python link_focus_probe.py [url]
"""

import ctypes
import sys

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QWidget

URL = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
SW_SHOWNOACTIVATE = 4

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32
state = {}


def text_of(hwnd) -> str:
    try:
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(int(hwnd), buf, 512)
        return buf.value
    except Exception:
        return ""


def class_of(hwnd) -> str:
    try:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(int(hwnd), buf, 256)
        return buf.value
    except Exception:
        return ""


def pid_of(hwnd) -> int:
    try:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def visible_windows():
    """当前所有可见顶层窗口：{hwnd: (pid, 标题)}"""
    out = {}

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            hwnd = int(hwnd)
            out[hwnd] = (pid_of(hwnd), text_of(hwnd))
        return True

    user32.EnumWindows(enum_proc, 0)
    return out


def dump(tag):
    hwnd = int(user32.GetForegroundWindow())
    print(f"[{tag}] 前台=0x{hwnd:x} 类={class_of(hwnd)!r} pid={pid_of(hwnd)} "
          f"标题={text_of(hwnd)!r}", flush=True)
    return hwnd


app = QApplication(sys.argv[:1])
win = QWidget()
win.resize(420, 200)
win.setWindowTitle("ToolsGCP 链接焦点测试")
win.show()
win.raise_()
win.activateWindow()


def step1():
    print(f"[自己] hwnd=0x{int(win.winId()):x} pid={kernel32.GetCurrentProcessId()}",
          flush=True)
    state["before"] = dump("打开前")
    state["windows"] = visible_windows()
    rc = shell32.ShellExecuteW(None, "open", URL, None, None, SW_SHOWNOACTIVATE)
    print(f"[ShellExecuteW] 返回={rc}（>32 才算成功）", flush=True)
    dump("调用后立刻")
    QTimer.singleShot(400, step2)


def step2():
    dump("400ms 后")
    QTimer.singleShot(900, step3)


def step3():
    dump("1300ms 后")
    new = visible_windows()
    added = {h: v for h, v in new.items() if h not in state["windows"]}
    print(f"[新增可见窗口] {len(added)} 个", flush=True)
    for hwnd, (pid, title) in list(added.items())[:10]:
        print(f"    0x{hwnd:x} pid={pid} 标题={title!r}", flush=True)
    print(f"[判定] 后台打开后前台是否变过: "
          f"{int(user32.GetForegroundWindow()) != state['before']}", flush=True)
    QTimer.singleShot(200, step4)


def step4():
    # 把我们自己的窗口重新置前
    user32.SetForegroundWindow(int(win.winId()))
    QTimer.singleShot(300, step5)


def step5():
    back = int(user32.GetForegroundWindow())
    print(f"[恢复后] 前台=0x{back:x} 标题={text_of(back)!r} "
          f"是我们自己={back == int(win.winId())}", flush=True)
    app.quit()


QTimer.singleShot(1200, step1)
app.exec_()
