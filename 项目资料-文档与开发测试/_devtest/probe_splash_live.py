# -*- coding: utf-8 -*-
"""启动画面自检（**默认完全不弹窗**，可安全在游戏/工作时运行）。

⚠️ 默认离屏：只算位图像素 + 目标居中矩形，**不调 ShowWindow、不截屏、不弹任何东西**。
   想真机弹一次（会闪一个 260x260 小窗约 1.2 秒）必须显式加 --show，平时别加。

验证两件事（对应 win-visual 的两条 bug）：
  ① 浅色主题底色：`_prepare_bitmap(..., dark=False)` 的**背景像素**必须是 #F3F4F7，
     且 `resolve_splash_dark()` 对 浅色主题/浅色/淺色主題/Light Theme 都判成浅色
     （以前只认死字符串 "浅色主题"，其它写法一律回退深色 = 用户报的"浅色还是黑"）。
  ② 居中：按 work_area 算出的目标矩形 == 理论中心（第一帧就居中，没有"先居中再跑偏"）。
     —— 这条以前用真机 --show 抓过 GetWindowRect：实测单帧 (830,386,1090,646)=理论中心，无跳变。

跑法：python "项目资料-文档与开发测试/_devtest/probe_splash_live.py"          # 离屏，不弹窗
      python "项目资料-文档与开发测试/_devtest/probe_splash_live.py" --show    # 才真弹一次
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

import pymodels.constants as constants_mod                    # noqa: E402
from pymodels.utils.system_utils import detect_system_theme   # noqa: E402
from desktop import splash as S                                # noqa: E402
from desktop.native import win32                               # noqa: E402

TMP = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", "splash-probe")
ICON = os.path.join(ROOT, ".ToolsGCP", "logo.png")

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def hex_of(rgb):
    return "#%02X%02X%02X" % tuple(rgb[:3])


def pixel(raw, w, x, y):
    i = (y * w + x) * 4
    return (raw[i], raw[i + 1], raw[i + 2], raw[i + 3])     # Pillow RGBA


def offscreen_checks():
    print("== ① 浅色主题底色（离屏，不弹窗）==")
    print("  本机 Windows 应用主题 =", detect_system_theme(),
          "（这是'跟随系统'会走到的分支，不代表用户选的浅色）")
    # resolve_splash_dark：各种"浅色"写法都要判成浅色（返回 False）
    for v in ["浅色主题", "浅色", "淺色主題", "Light Theme", "light"]:
        check(f"resolve_splash_dark({v!r}) → 浅色", S.resolve_splash_dark(v) is False)
    for v in ["深色主题", "深色", "Dark Theme", "dark"]:
        check(f"resolve_splash_dark({v!r}) → 深色", S.resolve_splash_dark(v) is True)
    check("空/坏值回退深色（不白屏不崩）", S.resolve_splash_dark("") is True)

    # 位图：**本轮已去掉底板**（用户要求"底板去除 + 给加载图片四角加圆润效果"），
    # 所以正常路径不再产生任何"背景像素"，_SPLASH_BG_* 只用于图片缺失/损坏的兜底块。
    # 这里改断言：① 窗口尺寸 == logo 尺寸（80px 边距没了）② 四角 alpha==0（真透明）
    # ③ 中心是 logo 自己的像素（没被底色覆盖）。
    w, h, raw = S._prepare_bitmap(ICON, dark=False)
    from PIL import Image
    im = Image.open(ICON)
    lw, lh = im.size
    if max(lw, lh) > S._SPLASH_LOGO_MAX:
        ratio = min(S._SPLASH_LOGO_MAX / lw, S._SPLASH_LOGO_MAX / lh)
        lw, lh = int(lw * ratio), int(lh * ratio)
    check(f"窗口尺寸 == logo 尺寸 {lw}x{lh}（底板与 80px 边距已去除）",
          (w, h) == (lw, lh), f"{w}x{h}")

    def corner(x, y):
        i = (y * w + x) * 4
        return (raw[i], raw[i + 1], raw[i + 2], raw[i + 3])

    cs = [corner(0, 0), corner(w - 1, 0), corner(0, h - 1), corner(w - 1, h - 1)]
    check(f"四角 alpha 全 0（真透明，无黑边/白边/脏边）{cs}",
          all(c[3] == 0 for c in cs))
    cx, cy = w // 2, h // 2
    got = corner(cx, cy)
    src = im.convert("RGBA").getpixel((im.size[0] // 2, im.size[1] // 2))
    check(f"中心 = logo 原像素 {got}（不是底色）", got[:3] == src[:3], f"logo={src}")
    w2, h2, raw2 = S._prepare_bitmap(ICON, dark=True)
    check("深浅两次出图字节完全相同（正常路径已无主题相关的背景像素）",
          (w2, h2) == (w, h) and raw2 == raw, f"{w2}x{h2}")
    # 兜底块仍然跟随主题（图片缺失/损坏时才有底色）
    fb_w, fb_h, fb_raw = S._prepare_bitmap(os.path.join(ROOT, "no-such.png"), False)
    i = ((fb_h // 2) * fb_w + fb_w // 2) * 4
    check("兜底块（图片缺失）中心 = 浅色底 #F3F4F7/240",
          tuple(fb_raw[i:i + 4]) == (243, 244, 247, 240), str(tuple(fb_raw[i:i + 4])))
    check("兜底块四角仍然 alpha==0（带圆角）", fb_raw[3] == 0, str(fb_raw[0:4]))

    print("== ② 居中矩形（离屏算，不弹窗）==")
    wa = win32.work_area()
    width, height = w, h
    x = int(wa[0] + ((wa[2] - wa[0]) - width) / 2)
    y = int(wa[1] + ((wa[3] - wa[1]) - height) / 2)
    print(f"  work_area={wa}  目标居中=({x},{y}) 尺寸 {width}x{height}")
    # 中心点应落在工作区正中（±1px），且完全在工作区内
    cx, cy = x + width / 2, y + height / 2
    ax, ay = (wa[0] + wa[2]) / 2, (wa[1] + wa[3]) / 2
    check("splash 中心 ≈ 工作区中心（无跑偏）",
          abs(cx - ax) <= 1.5 and abs(cy - ay) <= 1.5,
          f"splash=({cx:.1f},{cy:.1f}) 工作区中心=({ax:.1f},{ay:.1f})")
    check("整窗在工作区内（不越界到屏幕外）",
          x >= wa[0] and y >= wa[1] and x + width <= wa[2] and y + height <= wa[3])


def show_once():
    """⚠️ 只有显式 --show 才真弹一次（会抢一眼屏幕）。默认不走到这里。"""
    import threading
    import ctypes
    from ctypes import wintypes
    print("== --show：真弹一次 splash（约 1.2 秒）==")
    os.makedirs(os.path.join(TMP, "config"), exist_ok=True)
    with open(os.path.join(TMP, "config", "toolsgcp_config.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"theme": "浅色主题"}, fh, ensure_ascii=False)
    constants_mod.DATA_DIR = os.path.join(TMP, "config")
    S.__dict__["_read_theme_setting"] = (lambda: "浅色主题")
    ctl = S.SplashController(ICON, 1200, enabled=True)
    if not ctl.start():
        print("  起不来（平台/沙箱限制）")
        return
    stop = threading.Event()
    seen = []
    user32 = ctypes.windll.user32
    EnumWindows = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    buf = (ctypes.c_wchar * 256)()

    def watch():
        while not stop.is_set():
            def cb(h, _):
                user32.GetClassNameW(h, buf, 256)
                if str(buf.value).startswith("ToolsGCP_Splash"):
                    r = wintypes.RECT()
                    if user32.GetWindowRect(h, ctypes.byref(r)):
                        k = (r.left, r.top, r.right, r.bottom)
                        if not seen or seen[-1] != k:
                            seen.append(k)
                return True
            user32.EnumWindows(EnumWindows(cb), 0)
            time.sleep(0.02)
    import time
    threading.Thread(target=watch, daemon=True).start()
    time.sleep(1.0)
    stop.set()
    ctl.stop(2.0)
    print("  实测矩形（期望只有 1 个 = 居中）:", seen)
    check("--show 真机：只出现 1 个矩形（无跳变）", len(seen) <= 1, str(seen))


def main():
    offscreen_checks()
    if "--show" in sys.argv:
        show_once()
    else:
        print("\n（默认离屏模式，未弹任何窗。要真机弹一次加 --show）")
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)}: {FAILS}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
