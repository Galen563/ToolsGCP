# -*- coding: utf-8 -*-
"""悬浮启动动画消息泵的**独立**冒烟（lead 自己跑，不依赖队友的脚本）。

验证三件事：
  ① 窗口真的建起来并显示（分层窗口矩形非零）；
  ② 鼠标类消息跨线程 SendMessage 能**及时**得到处理（旧写法没有消息泵，
     调用方会阻塞到系统判"未响应"）—— 这里量往返毫秒；
  ③ stop() 能在合理时间内收尾，窗口真的销毁。
只碰 splash.py，不创建主窗口、不需要 WebView2。
"""
import ctypes
import os
import sys
import time

sys.path[:0] = [os.path.join(os.getcwd(), ".ToolsGCP"),
                os.path.join(os.getcwd(), ".ToolsGCP", "modules")]
from desktop.splash import SplashController          # noqa: E402

user32 = ctypes.windll.user32
WM_MOUSEMOVE, WM_NCHITTEST, WM_LBUTTONDOWN = 0x0200, 0x0084, 0x0201
HTCLIENT, HTCAPTION = 1, 2

def find_splash_window():
    """按类名前缀找 splash 窗口（控制器不对外暴露 hwnd，只能枚举）"""
    found = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value.startswith("ToolsGCP_Splash_"):
            found.append(hwnd)
        return True

    user32.EnumWindows(EnumProc(_cb), 0)
    return found[0] if found else 0

results = {}
icon = os.path.join(os.getcwd(), ".ToolsGCP", "logo.png")
ctl = SplashController(icon, enabled=True)
started = ctl.start()
results["start()"] = started
if not started:
    print("FAIL: 控制器没起来（缺 Pillow / 非 Windows？）")
    sys.exit(1)

hwnd = 0
for _ in range(60):
    hwnd = find_splash_window()
    if hwnd:
        break
    time.sleep(0.05)
results["找到窗口"] = bool(hwnd)
if not hwnd:
    print("FAIL: 找不到 splash 窗口")
    sys.exit(1)

rect = ctypes.wintypes.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
results["窗口矩形"] = (rect.right - rect.left, rect.bottom - rect.top)
results["IsWindowVisible"] = bool(user32.IsWindowVisible(hwnd))

def roundtrip(msg, wparam=0, lparam=0):
    t0 = time.perf_counter()
    r = user32.SendMessageW(hwnd, msg, wparam, lparam)
    return (time.perf_counter() - t0) * 1000.0, r

# 鼠标移动 / 命中测试 / 按下：全部是"鼠标一碰"会触发的跨线程同步调用
samples = []
for label, msg in (("WM_MOUSEMOVE", WM_MOUSEMOVE),
                   ("WM_NCHITTEST", WM_NCHITTEST),
                   ("WM_LBUTTONDOWN", WM_LBUTTONDOWN)):
    worst = 0.0
    last = None
    for _ in range(20):
        ms, ret = roundtrip(msg, 0, (120 << 16) | 120)
        worst = max(worst, ms)
        last = ret
    samples.append((label, round(worst, 2), last))
results["跨线程消息最坏往返(ms)"] = samples

# 连续 200 次触碰（模拟用户在画面上乱动鼠标），期间窗口必须还活着
for _ in range(200):
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, (100 << 16) | 100)
    user32.SendMessageW(hwnd, WM_NCHITTEST, 0, (100 << 16) | 100)
alive_after_poke = bool(user32.IsWindow(hwnd)) and bool(user32.IsWindowVisible(hwnd))
results["连续 200 次触碰后窗口仍在"] = alive_after_poke

t0 = time.perf_counter()
stopped = ctl.stop(timeout=3.0)
results["stop() 返回"] = stopped
results["stop() 耗时(ms)"] = round((time.perf_counter() - t0) * 1000, 1)
results["窗口已销毁"] = not bool(user32.IsWindow(hwnd))

for k, v in results.items():
    print(f"{k}: {v}")

ok = (started and results["找到窗口"] and results["IsWindowVisible"]
      and all(ms < 200 for _, ms, _ in samples)
      and alive_after_poke and stopped and results["窗口已销毁"])
print("\n==== 结论:", "PASS" if ok else "FAIL", "====")
sys.exit(0 if ok else 1)