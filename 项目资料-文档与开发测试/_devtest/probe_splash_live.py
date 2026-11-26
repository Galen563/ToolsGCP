# -*- coding: utf-8 -*-
"""启动画面自检（**默认完全不弹窗**，可安全在游戏/工作时运行）。

⚠️ 默认离屏：只算位图像素 + 目标居中矩形，**不调 ShowWindow、不截屏、不弹任何东西**。
   想真机弹一次（会闪一个 244x244 小窗，显示到 stop() 为止）必须显式加 --show，平时别加。

⚠️⚠️ 本轮需求变了（第 32 轮），本脚本跟着改写：
    用户原话「浅色主题的悬浮启动动画底板要和深色一致。不是单纯改个颜色，而是把之前
    判断主题的那套逻辑删掉——底板固定一种颜色，不需要专门一套检测逻辑服务它」。
    ⇒ 上一版这里验的是"浅色主题底色"：_prepare_bitmap(ICON, dark=False) 的底板像素
      必须是 #F3F4F7，并断言 resolve_splash_dark() 对各种"浅色"写法都判成浅色。
      **那一族断言整段作废**：splash.py 里 _read_theme_setting / resolve_splash_dark /
      _theme_diagnostics / _SPLASH_BG_LIGHT 已删除，_prepare_bitmap 的签名变成
      (icon_path, scale=1.0)，显示路径对配置文件**零读取**。
    ⇒ 现在改成验"底板固定深色"：不管用户选浅色还是深色主题，画出来都是
      _SPLASH_BG_DARK (28,28,28,240)，而且配置怎么改都不影响出图字节。
    ⇒ "_theme_is_light 的浅/深/跟随系统兼容表"**继续测**：它没被删，desktop/shell.py
      的主窗口 / boot-screen 配色还在 import 它（那是"窗口**里面**的启动动画"另一条链路）。

验证三件事（对应 win-visual 的 bug + 本轮新契约）：
  ① 底板固定深色：_prepare_bitmap 的**左边距那一圈像素**必须是 (28,28,28,240)，
     且整张图里找不到浅色底板 (243,244,247,240) —— 浅色主题下也一样。
  ② 主题判定兼容表（_theme_is_light，服务 shell）没有退化。
  ③ 居中：按 work_area 算出的目标矩形 == 理论中心（第一帧就居中，没有"先居中再跑偏"）。
     —— 这条以前用真机 --show 抓过 GetWindowRect：实测单帧 (830,386,1090,646)=理论中心，无跳变。

跑法：python "项目资料-文档与开发测试/_devtest/probe_splash_live.py"          # 离屏，不弹窗
      python "项目资料-文档与开发测试/_devtest/probe_splash_live.py" --show    # 才真弹一次
"""
import os
import sys
# ⚠️ Windows 控制台默认是 GBK 代码页：本文件的断言名里有 ⇒ 这类非 GBK 字符，
#    直接 print 会抛 UnicodeEncodeError，把取证脚本**从中间打断**
#    （实测 probe_splash_live.py 因此崩在半路、退出码 1，看起来像断言失败）。
#    这里只把编不出来的字符替换掉，**不改编码**：中文仍按控制台原编码输出，
#    不会变乱码；换到 UTF-8 终端（Windows Terminal / PYTHONIOENCODING=utf-8）同样正常。
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:                            # noqa: BLE001
    pass


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# ⚠️ 必须在覆盖 sys.argv **之前**把命令行参数取走：下面为了把 pymodels 的"入口"
#    摆成真实入口，会把 sys.argv 改成 [ToolsGCP.pyw]。老脚本在这一步之后才读
#    "--show"，于是 --show 永远读不到、真机段从来没跑过（既有缺陷，本轮修掉）。
SHOW = "--show" in sys.argv
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
SKIPS = []

# 本轮需求要求"整套主题检测逻辑删掉"，这几个符号必须已经没了
DEAD_SYMBOLS = ("_read_theme_setting", "resolve_splash_dark",
                "_theme_diagnostics", "_SPLASH_BG_LIGHT")


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def pixel(raw, w, x, y):
    i = (y * w + x) * 4
    return (raw[i], raw[i + 1], raw[i + 2], raw[i + 3])     # Pillow RGBA


def offscreen_checks():
    print("== ① 底板固定深色（离屏，不弹窗）==")
    print("  本机 Windows 应用主题 =", detect_system_theme(),
          "（本轮起这**不影响**启动画面：底板固定深色，显示路径不读配置）")

    # —— 被删的符号：留一条"谁别把它加回来"的断言 ——
    for name in DEAD_SYMBOLS:
        check(f"splash 模块已删除 {name}（本轮需求：整套主题检测逻辑删掉）",
              not hasattr(S, name))
    check("_prepare_bitmap 新签名是 (icon_path, scale=1.0)",
          list(__import__("inspect").signature(S._prepare_bitmap).parameters)
          == ["icon_path", "scale"])

    # —— 位图：第 30 轮把底板加回来，本轮把"跟随主题的两种底色"改成"固定一种深色" ——
    # 断言：① 窗口尺寸 == logo + 2×边距 ② 四角 alpha==0（真透明）
    # ③ 窗口中心是 logo 自己的像素（居中贴图）④ 左边距那一圈是固定深色
    w, h, raw = S._prepare_bitmap(ICON)
    from PIL import Image
    im = Image.open(ICON)
    lw, lh = im.size
    if max(lw, lh) > S._SPLASH_LOGO_MAX:
        ratio = min(S._SPLASH_LOGO_MAX / lw, S._SPLASH_LOGO_MAX / lh)
        lw, lh = int(lw * ratio), int(lh * ratio)
    margin = S._SPLASH_MARGIN
    check(f"窗口尺寸 == logo 尺寸 + 2×边距 {lw + 2 * margin}x{lh + 2 * margin}（底板几何未动）",
          (w, h) == (lw + 2 * margin, lh + 2 * margin), f"{w}x{h}")

    cs = [pixel(raw, w, 0, 0), pixel(raw, w, w - 1, 0),
          pixel(raw, w, 0, h - 1), pixel(raw, w, w - 1, h - 1)]
    check(f"四角 alpha 全 0（真透明，无黑边/白边/脏边）{cs}",
          all(c[3] == 0 for c in cs))
    got = pixel(raw, w, w // 2, h // 2)
    src = im.convert("RGBA").getpixel((im.size[0] // 2, im.size[1] // 2))
    check(f"中心 = logo 原像素 {got}（不是底色）", got[:3] == src[:3], f"logo={src}")

    # 底板落在**左边距**上（窗口 = logo + 每边 32px，所以 x=margin//2 处没有 logo）
    board_px = pixel(raw, w, margin // 2, h // 2)
    check(f"底板像素 = 固定深色 (28,28,28,240) == _SPLASH_BG_DARK {board_px}",
          board_px == tuple(S._SPLASH_BG_DARK), str(board_px))
    check("浅色底板 (243,244,247,240) 在整张图里一个像素都找不到（浅色分支真的没了）",
          not any(tuple(raw[i:i + 4]) == (243, 244, 247, 240) for i in range(0, len(raw), 4)))

    # —— 本轮契约的核心：配置是浅色主题时，出图**字节**也得一模一样 ——
    # （老脚本在这里是"打桩 _read_theme_setting 让它返回浅色主题"；现在显示路径压根
    #   不读配置，打桩没有意义，改成"写真实配置文件 + 比对字节"，反而更硬。）
    cfg_dir = os.path.join(TMP, "config")
    os.makedirs(cfg_dir, exist_ok=True)
    cfg = os.path.join(cfg_dir, "toolsgcp_config.json")
    orig_data_dir = constants_mod.DATA_DIR
    try:
        constants_mod.DATA_DIR = cfg_dir
        for theme in ("浅色主题", "深色主题", "跟随系统"):
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write('{"theme": "%s"}' % theme)
            w2, h2, raw2 = S._prepare_bitmap(ICON)
            check(f"配置 theme={theme} → 出图字节与 theme 无关（底板固定深色）",
                  raw2 == raw and (w2, h2) == (w, h), f"{w2}x{h2}")
        check("底板固定深色 ⇒ 浅色主题下也是这一块（本轮需求），窗口仍是 %dx%d" % (w, h),
              True)
    finally:
        constants_mod.DATA_DIR = orig_data_dir

    # —— DPI 放大后尺寸与底色都得对（分层窗口用物理像素） ——
    for sc in (1.25, 1.5):
        sw, sh, sraw = S._prepare_bitmap(ICON, sc)
        sbar = pixel(sraw, sw, S._scaled(S._SPLASH_MARGIN, sc) // 2, sh // 2)
        check(f"scale={sc} → 窗口放大到 {sw}x{sh} 且底板仍是固定深色",
              sw > w and sh > h and sbar == tuple(S._SPLASH_BG_DARK),
              f"{sw}x{sh} 底板={sbar}")

    # —— 兜底块（图片缺失/损坏）：同构圆角底板，中心就是固定深色 ——
    fb_w, fb_h, fb_raw = S._prepare_bitmap(os.path.join(ROOT, "no-such.png"))
    i = ((fb_h // 2) * fb_w + fb_w // 2) * 4
    check(f"兜底块（图片缺失）中心 = 固定深色 (28,28,28,240)，尺寸 {fb_w}x{fb_h}",
          tuple(fb_raw[i:i + 4]) == tuple(S._SPLASH_BG_DARK), str(tuple(fb_raw[i:i + 4])))
    check("兜底块四角仍然 alpha==0（带圆角）", fb_raw[3] == 0, str(fb_raw[0:4]))

    print("== ② 主题判定兼容表（_theme_is_light：保留，服务 shell 主窗口配色）==")
    for v in ["浅色主题", "浅色", "淺色主題", "Light Theme", "light"]:
        check(f"_theme_is_light({v!r}) → 浅色 True", S._theme_is_light(v) is True)
    for v in ["深色主题", "深色", "Dark Theme", "dark"]:
        check(f"_theme_is_light({v!r}) → 深色 False", S._theme_is_light(v) is False)
    for v in ["跟随系统", "auto", ""]:
        check(f"_theme_is_light({v!r}) → None（跟随系统/认不出来交给调用方）",
              S._theme_is_light(v) is None)

    print("== ③ 居中矩形（离屏算，不弹窗）==")
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
    """⚠️ 只有显式 --show 才真弹一次（会占一眼屏幕）。默认不走到这里。

    本轮起这里**不再打桩 _read_theme_setting**：显示路径对配置零读取，桩函数已经
    没有对象可桩（那个函数被删了）。配置照旧写进临时数据根，只为证明"写了浅色主题
    也不会改变画面"；真机判据是**矩形序列**（第一帧就居中、无跳变）+ 窗口存在性。
    """
    import ctypes
    import threading
    import time
    from ctypes import wintypes
    print("== --show：真弹一次 splash（显示到 stop() 为止）==")
    if sys.platform != "win32":
        print("  ⚠️ 非 Windows：跳过真机段")
        SKIPS.append("--show 真机段（非 Windows）")
        return
    os.makedirs(os.path.join(TMP, "config"), exist_ok=True)
    import json
    with open(os.path.join(TMP, "config", "toolsgcp_config.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"theme": "浅色主题"}, fh, ensure_ascii=False)
    constants_mod.DATA_DIR = os.path.join(TMP, "config")
    ctl = S.SplashController(ICON, 1200, enabled=True)
    if not ctl.start():
        print("  起不来（平台/沙箱限制）→ 记为跳过，不算失败")
        SKIPS.append("--show 真机段（SplashController.start() 返回 False）")
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
    threading.Thread(target=watch, daemon=True).start()
    time.sleep(1.0)
    stop.set()
    ctl.stop(2.0)
    print("  实测矩形（期望只有 1 个 = 居中）:", seen)
    check("--show 真机：只出现 1 个矩形（无跳变）", len(seen) <= 1, str(seen))
    check("--show 真机：窗口已随 stop() 销毁（无残留）", not seen or ctl._hwnd == 0,
          f"_hwnd={ctl._hwnd}")


def main():
    offscreen_checks()
    if SHOW:
        try:
            show_once()
        except Exception as exc:                            # noqa: BLE001
            # 真机段依赖可见桌面 / 建窗权限：本机跑不了就**如实跳过**，
            # 不把环境限制硬改绿，也不算 FAIL（沙箱禁命名管道时 Chromium/建窗会失败）
            print(f"  ⚠️ --show 真机段无法在本机执行（{type(exc).__name__}: {exc}）→ 跳过")
            SKIPS.append("--show 真机段（本机环境限制）")
    else:
        print("\n（默认离屏模式，未弹任何窗。要真机弹一次加 --show）")
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)}: {FAILS}")
    else:
        print("ALL OK")
    if SKIPS:
        print(f"环境跳过: {SKIPS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
