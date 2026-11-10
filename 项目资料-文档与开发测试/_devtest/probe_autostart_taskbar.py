# -*- coding: utf-8 -*-
"""task-6 ②③ 真机取证：开机自启静默启动时**任务栏到底有没有按钮**

两件事分开做（都能单独跑）：

  A. `--selftest`（不起主程序，纯原生探针）
     自己建一个和 shell 静默启动**同款样式**的顶层窗口（WS_POPUP + WS_THICKFRAME
     + WS_EX_APPWINDOW），依次量：
        旧行为基线（OFFSCREEN + Show）→ set_taskbar_hidden(True) → (False)
     每步打印 GWL_STYLE / GWL_EXSTYLE / IsWindowVisible / 矩形，
     并给出 Windows 的"任务栏按钮资格"判据。→ 证明**样式翻转成对生效**。
     顺带验一遍 tray._on_tray_left 的去抖/分发逻辑（不起真窗口，桩 on_select）。

  B. `--live`（真机跑一次开机自启路径）
     用 `pythonw ToolsGCP.pyw --autostart` 复现静默启动，等窗口建好，
     量它到底可不可见 / exstyle / 有没有任务栏按钮；
     再 PostMessage **NIN_SELECT**（Win11 左键单击的真实事件）给我们自己的
     托盘窗口 `ToolsGCP_TrayWindow`，验证"左键单击 = 呼出主窗口 + 样式恢复"。
     测完 PostMessage WM_CLOSE + 等进程退出，不留残留。

输出：`_tmp-ai-test/probe_autostart_taskbar.json`（报告里直接引用）
⚠️ 沙箱：临时文件只用固定名目录 `_tmp-ai-test/`。
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(BASE, ".ToolsGCP"),
                os.path.join(BASE, ".ToolsGCP", "modules")]

OUT_DIR = os.path.join(BASE, "项目资料-文档与开发测试", "_tmp-ai-test")
OUT_FILE = os.path.join(OUT_DIR, "probe_autostart_taskbar.json")

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_VISIBLE = 0x10000000
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
WM_CLOSE = 0x0010
WM_APP = 0x8000
WM_TRAY = WM_APP + 1                    # 与 desktop/native/tray.py 的 WM_TRAY 同值
NIN_SELECT = 0x0400                     # WM_USER+0：Vista+ 托盘左键**单击**
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
SW_SHOWNOACTIVATE = 4

u = ctypes.windll.user32
k = ctypes.windll.kernel32

u.GetWindowLongW.restype = ctypes.c_long
u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
u.IsWindowVisible.restype = ctypes.c_bool
u.IsIconic.restype = ctypes.c_bool
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.PostMessageW.restype = ctypes.c_bool
u.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM,
                           wintypes.LPARAM]
u.ShowWindow.restype = ctypes.c_bool
u.EnumWindows.restype = ctypes.c_bool
u.EnumChildWindows.restype = ctypes.c_bool
u.GetClassNameW.restype = ctypes.c_int
# ⚠️ DefWindowProcW 必须显式声明原型：WPARAM/LPARAM 是 64 位无符号，
#    默认按 int 转换会 OverflowError（探针里回调全废）。
u.DefWindowProcW.restype = ctypes.c_ssize_t
u.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM,
                             wintypes.LPARAM]
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint,
                             wintypes.WPARAM, wintypes.LPARAM)
ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def title_of(hwnd):
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def rect_of(hwnd):
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def snapshot(hwnd, label=""):
    st = u.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
    ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    vis = bool(u.IsWindowVisible(hwnd))
    # Windows 决定"任务栏有没有按钮"的判据（和我们代码里 is_taskbar_hidden 一致）：
    #   必须 WS_VISIBLE 且 IsWindowVisible 且（是 APPWINDOW 或 不是 TOOLWINDOW）
    has_button = bool((st & WS_VISIBLE) and vis
                      and (bool(ex & WS_EX_APPWINDOW) or not bool(ex & WS_EX_TOOLWINDOW)))
    return {
        "label": label, "hwnd": hwnd, "title": title_of(hwnd),
        "style": hex(st), "exstyle": hex(ex),
        "ws_visible": bool(st & WS_VISIBLE),
        "appwindow": bool(ex & WS_EX_APPWINDOW),
        "toolwindow": bool(ex & WS_EX_TOOLWINDOW),
        "IsWindowVisible": vis, "IsIconic": bool(u.IsIconic(hwnd)),
        "rect": rect_of(hwnd),
        "taskbar_button_expected": has_button,
    }


def enum_top(match="ToolsGCP"):
    found = []

    def _cb(hwnd, _l):
        if match and match in title_of(hwnd):
            found.append(snapshot(hwnd, "top-level"))
        return True

    u.EnumWindows(ENUMPROC(_cb), 0)
    return found


def taskbar_evidence():
    """任务栏证据：① 有按钮资格的顶层窗口 ② Shell_TrayWnd 的子窗口类名"""
    ours = [w for w in enum_top() if w["taskbar_button_expected"]]
    tray = u.FindWindowW("Shell_TrayWnd", None)
    kids = []

    def _kid(hwnd, _l):
        buf = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, buf, 256)
        kids.append(buf.value)
        return True

    if tray:
        u.EnumChildWindows(tray, ENUMPROC(_kid), 0)
    return {"shell_tray_hwnd": tray or 0,
            "tray_child_classes": sorted(set(kids))[:20],
            "our_windows_with_taskbar_button": ours,
            "count": len(ours)}


# =========================================================================
def selftest():
    """纯原生：量 set_taskbar_hidden 的成对效果（不碰用户窗口）"""
    from desktop.native import frame, win32

    WS_POPUP = 0x80000000
    WS_THICKFRAME = 0x00040000
    WS_SYSMENU = 0x00080000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000

    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                  wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                  wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    u.RegisterClassW.restype = ctypes.c_ushort
    u.CreateWindowExW.restype = wintypes.HWND
    u.DestroyWindow.restype = ctypes.c_bool

    keep = []                                   # 防 GC（窗口过程必须活着）
    proc = WNDPROC(lambda h, m, wp, lp: u.DefWindowProcW(h, m, wp, lp))
    keep.append(proc)
    wc = win32.WNDCLASSW()
    wc.lpfnWndProc = proc
    wc.hInstance = k.GetModuleHandleW(None)
    wc.lpszClassName = "ToolsGCP_ProbeWindow_v6"
    atom = u.RegisterClassW(ctypes.byref(wc))
    if not atom:
        return [{"error": f"RegisterClassW 失败 err={k.GetLastError()}"}]
    hwnd = u.CreateWindowExW(
        WS_EX_APPWINDOW, "ToolsGCP_ProbeWindow_v6", "ToolsGCP",
        WS_POPUP | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX,
        -32000, -32000, 800, 600, None, None, k.GetModuleHandleW(None), None)
    if not hwnd:
        return [{"error": f"CreateWindowExW 失败 err={k.GetLastError()}"}]

    steps = []
    try:
        # ① 旧行为基线：静默启动"留在屏幕外但仍然 Show"（= 用户报的现象）
        u.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        baseline = snapshot(hwnd, "①旧行为：OFFSCREEN 但窗口仍可见（未修）")
        steps.append(baseline)

        # ② 修后：收起任务栏按钮（无 pywebview window → 走 SW_HIDE + TOOLWINDOW）
        r_hide = frame.set_taskbar_hidden(hwnd, True)
        hidden = snapshot(hwnd, "②修后：set_taskbar_hidden(True)")
        steps.append({"set_taskbar_hidden": r_hide, "snapshot": hidden})

        # ③ 恢复：set_taskbar_hidden(False) 只负责把样式翻回 APPWINDOW，
        #    **不**负责 Show（Show 是 show_window_on_gui_thread 的活）。
        #    所以这里要自己 Show 一次，再断言"任务栏按钮回来了"。
        r_show = frame.set_taskbar_hidden(hwnd, False)
        u.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        restored = snapshot(hwnd, "③修后：set_taskbar_hidden(False) + Show")
        steps.append({"set_taskbar_hidden": r_show, "snapshot": restored})

        checks = {
            "①旧行为：可见→任务栏确实该有按钮（这就是 bug）":
                baseline["taskbar_button_expected"] is True,
            "②修后：IsWindowVisible=False": hidden["IsWindowVisible"] is False,
            "②修后：WS_EX_TOOLWINDOW 置上": hidden["toolwindow"] is True,
            "②修后：WS_EX_APPWINDOW 被清": hidden["appwindow"] is False,
            "②修后：任务栏按钮判据=False": hidden["taskbar_button_expected"] is False,
            "②修后：frame 返回 ok=True": bool(r_hide.get("ok")),
            "③恢复：TOOLWINDOW 清掉": restored["toolwindow"] is False,
            "③恢复：APPWINDOW 置回": restored["appwindow"] is True,
            "③恢复：任务栏按钮判据=True": restored["taskbar_button_expected"] is True,
        }
        steps.append({"checks": checks, "all_pass": all(checks.values())})
    finally:
        u.DestroyWindow(hwnd)

    # ④ tray 左键分发/去抖（桩 on_select，不起真窗口）
    from desktop.native import tray as tray_mod
    hits = []
    t = tray_mod.TrayIcon.__new__(tray_mod.TrayIcon)
    t.on_select = {"home": lambda: hits.append("home")}
    t._last_left_at = 0.0
    t._thread = None          # __new__ 造的对象没有 __init__ 的字段，手动补
    # _invoke 会起线程；直接桩掉，只看分发与去抖
    real_invoke = tray_mod.TrayIcon._invoke
    tray_mod.TrayIcon._invoke = lambda self, key: hits.append("invoke:" + key)
    try:
        t._on_tray_left("click")
        once = list(hits)
        t._on_tray_left("dbclk")          # 紧跟的双击应被去抖吞掉
        twice = list(hits)
        t._last_left_at = time.monotonic() - 5.0
        t._on_tray_left("dbclk")          # 隔一会儿再双击 → 应该生效
        third = list(hits)
    finally:
        tray_mod.TrayIcon._invoke = real_invoke
    checks_tray = {
        "左键单击 → 派发 home": once == ["invoke:home"],
        "0.25s 内的双击被去抖（不会呼出两次）": twice == once,
        "过了去抖窗口的双击仍然会呼出（双击路径没坏）":
            third == ["invoke:home", "invoke:home"],
    }
    steps.append({"tray_left_checks": checks_tray,
                  "all_pass": all(checks_tray.values()),
                  "hits": [once, twice, third]})
    return steps


# =========================================================================
def live():
    """真机：跑一次开机自启静默启动 + NIN_SELECT 左键呼出"""
    out = {"steps": []}
    pyw = os.path.join(BASE, "ToolsGCP.pyw")
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    # 和注册表里那条命令**完全一致**的启动方式（只是脚本路径大小写不同）
    proc = subprocess.Popen([pythonw, pyw, "--autostart"], cwd=BASE)
    out["pid"] = proc.pid
    out["cmd"] = [pythonw, pyw, "--autostart"]
    try:
        main = None
        deadline = time.time() + 120
        while time.time() < deadline:
            for w in enum_top():
                if w["title"].strip() == "ToolsGCP":
                    main = w
                    break
            if main:
                break
            time.sleep(0.4)
        if not main:
            out["steps"].append({"error": "120s 内没等到主窗口（可能没建起来）"})
            return out
        out["main_hwnd"] = main["hwnd"]
        out["steps"].append({"t": "窗口刚出现", "snapshot": main})

        # 静默启动的成对动作在 _try_show（前端 ready 后）才跑 → 给它时间
        time.sleep(8.0)
        st = snapshot(main["hwnd"], "静默启动稳定后（~8s）")
        tb = taskbar_evidence()
        out["steps"].append({"t": "静默启动 8s 后", "snapshot": st, "taskbar": tb})
        out["startup_hidden_no_taskbar_button"] = bool(
            st["taskbar_button_expected"] is False)

        # ③ NIN_SELECT（Win11 左键单击）→ 我们的托盘窗口 → 应呼出主窗口
        tray = u.FindWindowW("ToolsGCP_TrayWindow", None)
        out["tray_hwnd"] = tray or 0
        if tray:
            u.PostMessageW(tray, WM_TRAY, 1, NIN_SELECT)
            shown = None
            deadline = time.time() + 30
            while time.time() < deadline:
                s = snapshot(main["hwnd"], "NIN_SELECT 之后")
                if s["IsWindowVisible"] and s["taskbar_button_expected"]:
                    shown = s
                    break
                time.sleep(0.5)
            out["steps"].append({"t": "左键单击(NIN_SELECT)呼出", "snapshot": shown})
            out["left_click_opens_window"] = shown is not None
            if shown:
                out["left_click_restores_appwindow"] = bool(
                    shown["appwindow"] and not shown["toolwindow"])
                out["left_click_on_screen"] = bool(
                    shown["rect"][0] > -20000)
                # 再收起 → 测 WM_LBUTTONUP（老协议）
                u.ShowWindow(main["hwnd"], 0)
                time.sleep(1.0)
                u.PostMessageW(tray, WM_TRAY, 1, WM_LBUTTONUP)
                s2 = None
                deadline = time.time() + 20
                while time.time() < deadline:
                    s2 = snapshot(main["hwnd"], "WM_LBUTTONUP 之后")
                    if s2["IsWindowVisible"]:
                        break
                    time.sleep(0.5)
                out["steps"].append({"t": "左键单击(老协议 WM_LBUTTONUP)呼出",
                                     "snapshot": s2})
                out["lbuttonup_opens_window"] = bool(s2 and s2["IsWindowVisible"])
        # 双击那条（真机上是 DBLCLK）
        if tray:
            u.ShowWindow(main["hwnd"], 0)
            time.sleep(1.0)
            u.PostMessageW(tray, WM_TRAY, 1, WM_LBUTTONDBLCLK)
            s3 = None
            deadline = time.time() + 20
            while time.time() < deadline:
                s3 = snapshot(main["hwnd"], "左键双击之后")
                if s3["IsWindowVisible"]:
                    break
                time.sleep(0.5)
            out["steps"].append({"t": "左键双击(DBLCLK)呼出", "snapshot": s3})
            out["dblclick_opens_window"] = bool(s3 and s3["IsWindowVisible"])
    finally:
        try:
            h = out.get("main_hwnd")
            if h:
                u.PostMessageW(h, WM_CLOSE, 0, 0)
        except Exception:
            pass
        try:
            proc.wait(timeout=60)
            out["exit_code"] = proc.returncode
        except Exception:
            out["exit_code"] = "timeout-killed"
            try:
                proc.kill()
                proc.wait(timeout=10)
            except Exception:
                pass
    return out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--selftest", action="store_true")
    g.add_argument("--live", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    data = {"mode": "selftest" if args.selftest else "live",
            "python": sys.executable, "ts": time.strftime("%F %T"),
            "run_as_admin": bool(getattr(ctypes.windll.shell32,
                                         "IsUserAnAdmin", lambda: 0)())}
    data["result"] = selftest() if args.selftest else live()
    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    if args.selftest:
        bad = [s for s in data["result"]
               if isinstance(s, dict) and ("checks" in s or "tray_left_checks" in s)
               and not s.get("all_pass")]
        if bad:
            print("SELFTEST FAILED:", json.dumps(bad, ensure_ascii=False))
            return 1
        print("SELFTEST ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
