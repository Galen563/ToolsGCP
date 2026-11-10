# -*- coding: utf-8 -*-
"""对照实验：GDI BitBlt 抓屏时，**存在**分层窗口(UpdateLayeredWindow)会不会把
"窗口外的桌面"也抓成纯黑？（决定 probe 里"四角真透明"该用什么判据）

做法：同一个坐标，连抓 4 张
  1) splash 出现之前          → 期望 = 真实桌面
  2) splash 显示中（窗口内角外/角外 8px/远处 50,50）
  3) splash 销毁之后          → 期望 = 真实桌面
  4) 再一张（无窗口，验证桌面是否静态/幻灯片）
如果 (2) 的"远处 50,50"也变成 (0,0,0)，而 (1)(3)(4) 是壁纸色 → 是 **BitBlt 的抓取伪影**，
不是渲染 bug；真透明的验证必须改用 PrintWindow / 或"同图内角内 vs 角外"的连续性判据。
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TMP = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", "splash-r2")
os.makedirs(TMP, exist_ok=True)
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]

try:
    ctypes.windll.shcore.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:                                       # noqa: BLE001
    pass

U, G, K = (ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32)


class BIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def shot(path, captureblt=True):
    from PIL import Image
    sw, sh = U.GetSystemMetrics(0), U.GetSystemMetrics(1)
    hdc = U.GetDC(None)
    mem = G.CreateCompatibleDC(hdc)
    bmp = G.CreateCompatibleBitmap(hdc, sw, sh)
    old = G.SelectObject(mem, bmp)
    flag = 0x00CC0020 | (0x40000000 if captureblt else 0)
    G.BitBlt(mem, 0, 0, sw, sh, hdc, 0, 0, flag)
    bmi = BIH()
    bmi.biSize = ctypes.sizeof(BIH)
    bmi.biWidth, bmi.biHeight, bmi.biPlanes, bmi.biBitCount = sw, -sh, 1, 32
    buf = ctypes.create_string_buffer(sw * sh * 4)
    ok = G.GetDIBits(mem, bmp, 0, sh, buf, ctypes.byref(bmi), 0)
    G.SelectObject(mem, old)
    G.DeleteObject(bmp)
    G.DeleteDC(mem)
    G.DeleteDC(hdc)
    if not ok:
        raise SystemExit("GetDIBits failed")
    im = Image.frombuffer("RGBA", (sw, sh), buf, "raw", "BGRA", 0, 1)
    im.convert("RGB").save(path)
    return im


def splash_rect():
    rows = []
    buf = (ctypes.c_wchar * 64)()
    U.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    U.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    cb = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def f(h, _):
        U.GetClassNameW(h, buf, 64)
        if str(buf.value).startswith("ToolsGCP_Splash"):
            r = wintypes.RECT()
            U.GetWindowRect(h, ctypes.byref(r))
            rows.append((int(h), (r.left, r.top, r.right, r.bottom)))
        return True
    U.EnumWindows(cb(f), 0)
    return rows


def main():
    from desktop import splash as S
    icon = os.path.join(ROOT, ".ToolsGCP", "logo.png")
    far = (60, 60)

    p1 = shot(os.path.join(TMP, "cmp1_before.png"))
    ctl = S.SplashController(icon, 6000, enabled=True)
    ctl.start()
    time.sleep(0.5)
    rows = splash_rect()
    p2 = shot(os.path.join(TMP, "cmp2_during.png"))
    p2b = shot(os.path.join(TMP, "cmp2b_during_nocaptureblt.png"), captureblt=False)
    ctl.stop(3)
    time.sleep(0.6)
    p3 = shot(os.path.join(TMP, "cmp3_after.png"))
    p4 = shot(os.path.join(TMP, "cmp4_after_again.png"))

    print("splash 窗口:", rows)
    if not rows:
        raise SystemExit("没抓到 splash 窗口")
    (_, l, t, r, b) = (0,) + rows[0][1]
    pts = {"角内 TL": (l + 1, t + 1), "角外 8px": (l - 8, t - 8),
           "远处 60,60": far, "屏幕中心": (U.GetSystemMetrics(0) // 2,
                                          U.GetSystemMetrics(1) // 2),
           "logo 中心": ((l + r) // 2, (t + b) // 2)}
    print(f"{'点':<12} {'① splash前':<20} {'② splash中(CAPTUREBLT)':<26} "
          f"{'② splash中(不带 CAPTUREBLT)':<28} {'③ splash后':<20} {'④ 再一张'}")
    for name, xy in pts.items():
        vals = []
        for im in (p1, p2, p2b, p3, p4):
            vals.append(im.getpixel(xy) if 0 <= xy[0] < im.width and 0 <= xy[1] < im.height else None)
        print(f"{name:<12} {str(vals[0]):<20} {str(vals[1]):<26} {str(vals[2]):<28} "
              f"{str(vals[3]):<20} {str(vals[4])}")
    same = all(p1.getpixel(far) == p3.getpixel(far) == p4.getpixel(far))
    print(f"\n桌面是否静态（①③④ 同点相等）: {same}")
    print(f"② 远处点是否被抓成纯黑: {p2.getpixel(far) == (0, 0, 0, 255)}")
    print(f"②b 不带 CAPTUREBLT 的 logo 中心: {p2b.getpixel(pts['logo 中心'])}")


if __name__ == "__main__":
    main()
