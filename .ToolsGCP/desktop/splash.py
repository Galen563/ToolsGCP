"""启动画面：**纯 Win32 实现，不再依赖 PyQt5**
========== 为什么换掉 Qt 版 ==========
旧版把原版 PyQt5 的 `SplashScreen` 放到 worker 线程里跑。它能用，但代价很实在：
  · **打包体积**：PyQt5 + PyQt-Fluent-Widgets 一起进 exe 就是几十 MB —— 而整个 Web 版
    的界面根本不用 Qt 画，只为了这一块启动画面拖着整套 Qt 进去（用户明确要求砍掉）；
  · **必须装在 worker 线程**：Qt 的 QApplication 有线程亲和性，主线程一旦 import 过
    PyQt5，进程退出就 100% 崩 0xC0000005（见旧版长注释，实测 8/8）；顺带还逼出了
    "退出时必须在创建线程里销毁、还要轮询 stop 请求"那一整套绕法。
现在改成 Win32 分层窗口（`UpdateLayeredWindow` 画**没有底板的圆角 logo**）：
  · 零第三方依赖：只用 ctypes + 本仓库已有的 `desktop/native/win32.py`；
  · 在**自己的线程**里建窗口，和 `traymenu.py`（自绘托盘菜单）是同一个成熟路子；
  · logo 解码用 `Pillow`（requirements.txt 里本来就有，`native/appicon.py` 在用）。
========= 与旧版保持完全一致的对外契约 =========
`SplashController(icon_path, duration_ms, enabled, on_finished)`：
    `.start() -> bool`   真正起来了吗（False = 关闭/降级，此时已经 _finish 过）
    `.finished`          bool，播放结束了吗
    `.wait(timeout)`     等到结束
    `.stop(timeout)`     退出流程用：让窗口线程收尾并 join
shell.py 只依赖这几个方法，所以换实现不动外壳逻辑（双条件 ready 照旧）。
========= 视觉规格（本轮按需求去掉"底板"） =========
旧版对齐原版 `pymodels/splash_screen.py`：logo 夹到 300px、窗口 = logo + 80px 边距、
画一块圆角半透明底（rgba(43,43,43,240) / 圆角 20）再把 logo 居中贴上去。
**本轮用户要求：底板去除，只留 logo 本身，并给加载图片自己的四个角加圆润效果。**
所以现在：
  · logo 最长边仍然夹到 300px（`_SPLASH_LOGO_MAX`，LANCZOS 平滑缩放）；
  · **窗口尺寸 == logo 尺寸**（不再有 80px 边距 ⇒ 不再有那块底板）；
  · 圆角打在 **logo 位图自己的 alpha 通道**上（`_SPLASH_CORNER_RATIO`，半径随图片尺寸等比走，
    180px 的 logo → 半径 29px，视觉上和原来底板的 20px 圆角接近但不死板）；
    圆角外 alpha **必须为 0**，否则分层窗口会留一圈脏边（黑边/白边）；
  · 底板没了 ⇒ 底色常量 `_SPLASH_BG_*` 只剩一个用途：**图片缺失/损坏时的兜底圆角块**
    （仍跟随主题二选一、仍 alpha 240，保证"永远有东西显示、且不崩"）。
    兜底块尺寸 = 原来的 220×220，圆角半径同样按比例算。
  · 无边框 + 置顶 + 不抢焦点（WS_POPUP + WS_EX_TOOLWINDOW|TOPMOST|LAYERED，
    ShowWindow(SW_SHOWNOACTIVATE)）。
本项目 logo 是 180×180 → 窗口 180×180（以前是 260×260）。
⚠️ 它**永远是独立小窗口**，绝不许拿主窗口冒充（那是"启动时闪一个等大空窗"的来源）。
"""

import ctypes
import json
import os
import sys
import threading
import time
import traceback
from ctypes import wintypes

# 启动画面最长等待（毫秒）：超过就当作"已经结束"，避免异常让窗口永远不出现
SPLASH_HARD_TIMEOUT_MS = 12000

# ---- 视觉常量（见模块 docstring 的"视觉规格"） ----
# 底色按用户主题二选一：与 webui/css/variables.css 的 `--page` 对齐 ——
# 浅色 #F3F4F7、深色 #1C1C1C，不另造一套色；alpha 240 沿用原视觉规格。
# ⚠️ 本轮去掉底板之后，这两个色**只用于图片缺失/损坏时的兜底圆角块**；
#    正常情况下启动画面就是 logo 本身（不再有背景矩形），所以"浅色主题看到深色底"
#    不可能再由这两个常量造成 —— 取证时别把它们当第一嫌疑。
#    旧值 (43,43,43,240) 是原 Qt 版写死的深色，浅色主题下和主窗口底对不上。
_SPLASH_BG_DARK = (28, 28, 28, 240)      # #1C1C1C = webui 深色 --page
_SPLASH_BG_LIGHT = (243, 244, 247, 240)  # #F3F4F7 = webui 浅色 --page
_SPLASH_LOGO_MAX = 300                  # 原版 max_size = 300（logo 最长边上限）
# 圆角半径按**图片短边的比例**算，而不是写死像素：图片被缩放后圆润程度保持一致。
# 0.16 → 180px 的 logo ≈ 29px 半径（原来"底板圆角 20 / 底板 260"的视觉比例是 0.077，
# 但那是整块大底板的角；现在是 logo 自己的角，同样的绝对半径看着更小，所以比例放大一些）。
_SPLASH_CORNER_RATIO = 0.16
_SPLASH_CORNER_MAX = 48                 # 半径上限：大图标别圆成圆形贴纸
# 图片缺失/损坏时的兜底方块尺寸（保留旧版数字，改小会显得"启动画面消失了"）
_SPLASH_FALLBACK_SIZE = 220
# 兼容旧引用（回归脚本 test_splash_theme.py 里有名字检查）：
# _SPLASH_MARGIN 已经废弃（去底板 = 不再有 80px 边距），保留为 0 只作占位；
# _SPLASH_RADIUS 保留 = 原底板圆角规格，仅作文档/测试参照，不再参与绘制。
_SPLASH_MARGIN = 0
_SPLASH_RADIUS = 20.0

# ---- Win32 常量（本地定义，避免动 win32.py 的公开面） ----
_WS_POPUP = 0x80000000
_WS_EX_LAYERED = 0x00080000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_TOPMOST = 0x00000008
_SW_SHOWNOACTIVATE = 0x0004
_ULW_ALPHA = 0x00000002
_AC_SRC_OVER = 0x00
_AC_SRC_ALPHA = 0x01
_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_ERASEBKGND = 0x0014


# ======================================================================
# 日志（失败一律吞掉：启动画面绝不能因为它自己把程序卡死）
# ======================================================================
def _log(level: str, message: str):
    try:
        from pymodels.utils.logger import log
        getattr(log, level)("启动", "splash", message)
    except Exception:
        pass


def _log_info(message: str):
    _log("info", message)


def _log_warn(message: str):
    _log("warn", message)


def _log_err(message: str):
    _log("err", message)


# ======================================================================
# 主题：决定启动画面用深色还是浅色底
# ======================================================================
def _read_theme_setting() -> str:
    """只读一次用户配置里的 `theme`（**不实例化 SettingsManager**）

    ⚠️ 为什么不用 SettingsManager：它构造时会跑一次性迁移、并可能**落盘** ——
       启动画面这条路径要求"极早 + 只读 + 无副作用"（为了配色去写用户配置不值当）。
       这里直接读同一个配置文件（`DATA_DIR/toolsgcp_config.json`，和 SettingsManager
       用的是同一个路径），读不到/JSON 坏了/键缺失都返回空串，由调用方回退深色。
    """
    from pymodels.constants import DATA_DIR
    path = os.path.join(DATA_DIR, "toolsgcp_config.json")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return ""
    return str(data.get("theme") or "")


def _theme_is_light(text: str):
    """把一个 theme 配置值判成 浅色(True) / 深色(False) / 认不出来(None)

    ⚠️️ 这是"浅色主题下启动画面仍是深色"的**真正修复点**：
       旧代码只认死字符串 `== "浅色主题"`，可配置里的 theme 值远不止这一种写法：
         · 设置页下拉框存的是规范简体（浅色主题 / 深色主题 / 跟随系统）—— 这一种以前能认；
         · GCP-AI 的 set_theme 工具（core/ai/agent_tools.py）写的是**短形式** "浅色"/"深色"；
         · 老版本 / 繁体 / 英文界面下用户存过 "浅色主題" / "Light Theme" / "dark" 等；
       上面这些以前全部走到"认不出来 → 回退深色"，于是**用户明明选了浅色，启动画面还是黑的**。
       这里把能认出的浅/深写法都收进来（大小写、全半角、繁简、中英文、短形式），
       认不出来才返回 None（交给调用方按"跟随系统 / 兜底深色"处理）。
    """
    t = str(text or "").strip().lower()
    if not t:
        return None
    # 浅色族
    if ("浅色" in t or "淺色" in t or "light" in t or t in ("亮色", "明亮", "白色")):
        return True
    # 深色族
    if ("深色" in t or "暗色" in t or "黑色" in t or "dark" in t
            or "night" in t or t in ("夜间", "夜間")):
        return False
    # 跟随系统族（返回 None 表示"要按系统判定"，不是"认不出来"）
    if ("跟随" in t or "跟隨" in t or "follow" in t or "system" in t or "auto" in t):
        return None
    return None


def _theme_diagnostics() -> dict:
    """取证用：把"到底读到了什么"原样吐出来（**只读、绝不抛异常**）

    ⚠️ 为什么需要它：上一轮把 `resolve_splash_dark()` 改成兼容各种 theme 写法后，
       离屏采样证明浅色分支算出来的背景字节确实是 (243,244,247,240)，但用户**仍然**看到深色。
       这说明真因不在算色，而在"有没有走到浅色分支"或者"看到的东西根本不是 splash"。
       没有现场数据就只能猜，所以这里把关键事实记进日志：
         · `DATA_DIR` 是哪个目录（data_root 指针是否已迁移 / 是不是 import 期算的旧值）；
         · 配置文件在不在、能不能读；
         · **theme 的原值**（repr，能看出全半角/繁简/空串/前后空格）；
         · `_theme_is_light` 的判定结果 + 最终 dark。
    """
    info = {"data_dir": "", "cfg_path": "", "cfg_exists": False,
            "theme_raw": None, "light": None, "dark": None, "error": ""}
    try:
        from pymodels.constants import DATA_DIR
        info["data_dir"] = str(DATA_DIR)
        path = os.path.join(DATA_DIR, "toolsgcp_config.json")
        info["cfg_path"] = path
        info["cfg_exists"] = os.path.isfile(path)
        raw = _read_theme_setting()
        info["theme_raw"] = repr(raw)
        info["light"] = _theme_is_light(raw)
        info["dark"] = resolve_splash_dark(raw)
    except Exception as exc:                            # noqa: BLE001
        info["error"] = repr(exc)
    return info


def resolve_splash_dark(theme=None) -> bool:
    """启动画面用深色底吗？**绝不抛异常**：任何异常/认不出来的值都回退深色

    规则（顺序固定）：
      · `theme` 显式传入就用它（测试与其它调用方可以绕过读文件）；
      · 认得出浅/深（含 浅色主题 / 浅色 / 淺色主題 / Light Theme / dark …）→ 直接用；
      · "跟随系统"（或认不出但属于跟随族）→ 按 Windows 的浅色/深色判定 —— 复用项目里现成的
        `pymodels.utils.system_utils.detect_system_theme()`，**不新写一套注册表读取**
        （那个模块是纯 Python、顶层不 import PyQt5，可以安全地跑在启动路径上）；
      · 其它情况（含读设置失败 / 设置文件损坏 / 键缺失 / 完全认不出的值）→ **回退深色**：
        宁可启动画面是深色，也不能因为设置有问题就崩或者白屏。
    """
    try:
        if theme is None:
            theme = _read_theme_setting()
        verdict = _theme_is_light(theme)
        if verdict is True:
            return False        # 浅色 → 不深色
        if verdict is False:
            return True         # 深色
        # 跟随系统 / 认不出：跟随系统按注册表判定；完全认不出（空/坏值）回退深色
        text = str(theme or "").strip().lower()
        follows = ("跟随" in text or "跟隨" in text or "follow" in text
                   or "system" in text or "auto" in text)
        if follows:
            from pymodels.utils.system_utils import detect_system_theme
            return detect_system_theme() == "深色主题"
        return True
    except Exception:                                   # noqa: BLE001
        return True


# ======================================================================
# 位图准备（Pillow）
# ======================================================================
def _corner_radius(w: int, h: int) -> int:
    """按图片尺寸算圆角半径（比例制，别写死像素）；夹到短边一半，防止圆成圆形贴纸"""
    try:
        r = int(round(min(w, h) * _SPLASH_CORNER_RATIO))
    except Exception:                                   # noqa: BLE001
        return 0
    return max(0, min(r, _SPLASH_CORNER_MAX, min(w, h) // 2))


def _rounded_mask(w: int, h: int, radius: int):
    """生成 0~255 的圆角蒙版（L 通道）。返回 None = 不要圆角。

    ⚠️ 为什么要"2x 超采样 + 再夹一层 1x 硬边"这两步，改之前先看明白：
      ① Pillow 的 rounded_rectangle 在 1x 下圆角是**锯齿**的，而启动画面是"窗口第一眼"，
         所以先在 2x 画、再缩放回 1x 拿到平滑的 0~255 过渡；
      ② 但**缩放（LANCZOS/BILINEAR）会在完全透明的圆角外沿产生振铃/漏光**，
         让"本该是 0"的角上像素变成 1~2 之类的非零值 —— 分层窗口下就是一圈洗不掉的脏边。
         所以再用 1x 的**二值硬蒙版取 min**：凡是在圆角矩形之外的像素，alpha 一律严格 0。
         内侧仍保留 ①的平滑过渡，视觉无损，边界却是真透明。
    """
    if radius <= 0 or w <= 0 or h <= 0:
        return None
    from PIL import Image, ImageChops, ImageDraw

    def _draw(scale, filt):
        mask = Image.new("L", (w * scale, h * scale), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, w * scale - 1, h * scale - 1], radius=radius * scale, fill=255)
        return mask if scale == 1 else mask.resize((w, h), filt)

    try:
        smooth = _draw(2, Image.LANCZOS)
        hard = _draw(1, None)
        return ImageChops.darker(smooth, hard)          # 逐像素取 min：外面强制 0
    except Exception as exc:                            # noqa: BLE001
        _log_warn(f"启动画面圆角蒙版生成失败（按直角显示）: {exc}")
        return None


def _apply_corner_radius(img, radius: int):
    """把圆角**乘到图片自己的 alpha 通道**上（不新建底板、不改 RGB）

    ⚠️ 只动 alpha：圆角外的像素会被 `_premultiply_bgra()` 的 `a == 0 → BGRA 全 0` 分支
       清成完全透明，所以不会留下"原图角上的深紫像素发黑边"。
       过渡像素（0 < a < 255）走预乘分支，RGB 来自原图，也不会脏。
    """
    mask = _rounded_mask(img.width, img.height, radius)
    if mask is None:
        return img
    from PIL import ImageChops
    try:
        # multiply = a*b/255：蒙版为 0 的角外像素必然得到 0（真透明）
        img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    except Exception as exc:                            # noqa: BLE001
        _log_warn(f"启动画面圆角应用失败（按直角显示）: {exc}")
    return img


def _prepare_bitmap(icon_path: str, dark: bool = True):
    """把 logo 解码成"**没有底板**、四角圆角、圆角外真透明"的 ARGB 像素

    返回 (w, h, bytes)，且 **w/h 就是窗口尺寸**（去底板后窗口 == 图片本身，
    不再有旧版那 80px 边距）。
    · 最长边超过 300 → LANCZOS 平滑缩到 300（原规格）；
    · 圆角半径按图片短边比例算（见 `_corner_radius`）；
    · 图片缺失/损坏 → 退回**同样带圆角的纯色块**（`dark` 决定深浅，alpha 240），
      保证启动画面永远有东西显示、且这条路径不抛异常。
    """
    from PIL import Image

    logo = None
    if icon_path and os.path.exists(icon_path):
        try:
            logo = Image.open(icon_path).convert("RGBA")
        except Exception as exc:                        # noqa: BLE001
            _log_warn(f"启动画面图片加载异常: {exc}")
            logo = None
    else:
        _log_warn(f"启动画面图片不存在: {icon_path}")

    if logo is not None:
        w, h = logo.size
        if w > _SPLASH_LOGO_MAX or h > _SPLASH_LOGO_MAX:
            ratio = min(_SPLASH_LOGO_MAX / float(w), _SPLASH_LOGO_MAX / float(h))
            w, h = max(1, int(w * ratio)), max(1, int(h * ratio))
            logo = logo.resize((w, h), Image.LANCZOS)
    else:
        # 兜底：没有图片也照样出一个"圆角纯色块"（尺寸沿用旧版 220）
        w = h = _SPLASH_FALLBACK_SIZE
        logo = Image.new("RGBA", (w, h),
                         _SPLASH_BG_DARK if dark else _SPLASH_BG_LIGHT)

    logo = _apply_corner_radius(logo, _corner_radius(w, h))
    return w, h, logo.tobytes()


# ======================================================================
# 分层窗口绘制
# ======================================================================
class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


def _premultiply_bgra(raw_argb: bytes, width: int, height: int) -> bytes:
    """把 Pillow 的 RGBA 像素转成 DIB 需要的**预乘 alpha 的 BGRA**（返回新 bytes）

    ⚠️️ 三个坑，改这里之前务必看明白（都是实测踩出来的）：
      ① Pillow 的 `RGBA.tobytes()` 是 **R,G,B,A** 顺序；
      ② 而 BI_RGB 的 32bpp DIB 在内存里是 **B,G,R,A**（小端）。
         按"src[i] 当 B 用"直接拷会把红蓝通道装反（灰色看不出来、彩色 logo 会变色）。
         所以取色时 src[i+2]→B、src[i+1]→G、src[i]→R。
      ③ 分层窗口要求 **预乘 alpha**：RGB 先乘 A/255 再填，否则半透明区域会糊。
    ⚠️ `a == 0` 必须把 **B/G/R 也强制清零**：这就是"圆角外不留脏边"的关键 ——
       预乘缓冲里 alpha=0 却留着非零 RGB，某些合成路径下会显出一圈边（而且截图看不出来）。
    单独抽成函数是为了**可测**：回归脚本直接断言这段的输出，不必依赖截屏
    （截屏会被桌面动态壁纸 / 上层窗口 / BitBlt 对分层窗口的行为干扰，实测不可靠）。
    """
    n = width * height * 4
    src = raw_argb
    if len(src) < n:
        src = src + bytes(n - len(src))
    dst = bytearray(n)
    dview = memoryview(dst)
    for i in range(0, n, 4):
        a = src[i + 3]
        if a == 0:
            dview[i] = 0
            dview[i + 1] = 0
            dview[i + 2] = 0
            dview[i + 3] = 0
        elif a == 255:
            dview[i], dview[i + 1], dview[i + 2] = src[i + 2], src[i + 1], src[i]
            dview[i + 3] = 255
        else:
            dview[i] = (src[i + 2] * a) // 255            # B
            dview[i + 1] = (src[i + 1] * a) // 255        # G
            dview[i + 2] = (src[i] * a) // 255            # R
            dview[i + 3] = a
    return bytes(dst)


def _update_layered(hwnd: int, width: int, height: int, raw_argb: bytes,
                    x: int = 0, y: int = 0) -> bool:
    """把 ARGB 像素贴到分层窗口：UpdateLayeredWindow + 32bpp premultiplied DIB

    ⚠️ `x, y` 是**窗口的屏幕坐标**（UpdateLayeredWindow 的 pptDst），必须传建窗时
       算好的居中位置；不传就会被强行拉到 (0,0)（第一版就这么错，窗口跑到左上角）。
    ⚠️ 分层窗口的 32bpp 位图要求**预乘 alpha**，且通道顺序是 B,G,R,A（见
       `_premultiply_bgra` 的注释）。
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    bmi = _BITMAPINFO()
    hdr = bmi.bmiHeader
    hdr.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    hdr.biWidth = width
    hdr.biHeight = -height          # 负高度 = 自顶向下，和 Pillow 的行序一致
    hdr.biPlanes = 1
    hdr.biBitCount = 32
    hdr.biCompression = 0           # BI_RGB

    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbitmap = 0
    try:
        bits = ctypes.c_void_p()
        hbitmap = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0,
                                         ctypes.byref(bits), None, 0)
        if not hbitmap or not bits:
            return False
        gdi32.SelectObject(hdc_mem, hbitmap)

        packed = _premultiply_bgra(raw_argb, width, height)
        ctypes.memmove(bits, packed, len(packed))

        # ⚠️️ `UpdateLayeredWindow` 的 **pptDst 是"窗口新的屏幕坐标"**，不是源图偏移！
        #    第一版把 `src_pt`(0,0) 传给它 → 窗口被强行挪到屏幕左上角，
        #    建窗时算好的居中坐标被覆盖（实测 GetWindowRect 返回 (0,0)-(260,260)）。
        #    这里显式传建窗时算出的 (left, top)。
        dst_pt = _POINT(int(x), int(y))
        src_pt = _POINT(0, 0)
        size = _SIZE(width, height)
        blend = _BLENDFUNCTION(_AC_SRC_OVER, 0, 255, _AC_SRC_ALPHA)
        ok = user32.UpdateLayeredWindow(
            wintypes.HWND(hwnd), hdc_screen, ctypes.byref(dst_pt),
            ctypes.byref(size), hdc_mem, ctypes.byref(src_pt), 0,
            ctypes.byref(blend), _ULW_ALPHA)
        return bool(ok)
    finally:
        try:
            if hbitmap:
                gdi32.DeleteObject(hbitmap)
        except Exception:
            pass
        try:
            gdi32.DeleteDC(hdc_mem)
        except Exception:
            pass
        try:
            user32.ReleaseDC(None, hdc_screen)
        except Exception:
            pass


# ======================================================================
# 控制器（对外契约与 PyQt5 版一致）
# ======================================================================
class SplashController:
    """启动画面控制器（内部 Win32 分层窗口；对外接口与旧 Qt 版逐字相同）"""

    def __init__(self, icon_path: str, duration_ms: int, enabled: bool = True,
                 on_finished=None):
        self.icon_path = icon_path
        self.duration_ms = max(0, int(duration_ms or 0))
        self.enabled = bool(enabled)
        self._on_finished = on_finished
        self._finished = threading.Event()
        self._stop_requested = threading.Event()
        self._thread = None
        self._lock = threading.RLock()
        self._fallback = False
        self._hwnd = 0
        self._class_registered = False

    # ---------- 状态 ----------
    @property
    def finished(self) -> bool:
        if not self.enabled:
            return True
        return self._finished.is_set()

    def wait(self, timeout: float = None) -> bool:
        if not self.enabled:
            return True
        return self._finished.wait(timeout)

    def stop(self, timeout: float = 3.0) -> bool:
        """请求停掉启动画面并等线程收尾（退出流程必须调它）

        ⚠️ 这里**只置位标志**，不跨线程 DestroyWindow：窗口只能在创建它的线程里销毁
           （旧 Qt 版踩的正是这个坑，只是换了个实现，规则没变）。
           等线程自己发现标志后收尾（它在 30ms 一轮的等待循环里检查）。
        """
        self._stop_requested.set()
        thread = self._thread
        if thread is None or not thread.is_alive():
            return True
        thread.join(timeout)
        return not thread.is_alive()

    # ---------- 启动 ----------
    def start(self) -> bool:
        """启动启动画面；返回是否真的起来了（False = 关闭/不可用，已 _finish）"""
        if not self.enabled:
            self._finish("关闭（设置里 splash_screen_enabled=False）")
            return False
        if sys.platform != "win32":
            self._fallback = True
            _log_warn("启动画面不可用（非 Windows 平台），已降级为无启动画面")
            self._finish("降级")
            return False
        try:
            import PIL  # noqa: F401  探针：缺 Pillow 就没法解码 logo
        except Exception:
            self._fallback = True
            _log_warn("启动画面不可用（缺少 Pillow），已降级为无启动画面")
            self._finish("降级")
            return False

        self._thread = threading.Thread(target=self._run, name="ToolsGCP-splash",
                                        daemon=True)
        self._thread.start()
        return True

    def _run(self):
        try:
            self._run_native()
        except Exception as exc:                        # noqa: BLE001
            _log_err(f"启动画面异常，已跳过: {exc}\n{traceback.format_exc()}")
            self._finish("异常")

    # ---------- 真正的实现 ----------
    def _run_native(self):
        """在工作线程里：建分层窗口 → 贴图 → 等时长/被要求退出 → 本线程销毁"""
        from .native import win32

        # ⚠️ 贴图前读一次用户主题（需求 A）：纯外观，失败一律回退深色、绝不抛异常。
        #    放在这条窗口线程里（而不是 __init__/主线程）：只有真的要画了才去读文件，
        #    启动画面关掉时一次 I/O 都不做。
        dark = resolve_splash_dark()
        width, height, raw = _prepare_bitmap(self.icon_path, dark)
        # 取证日志（需求 ①）：上一轮"算色对了但用户仍看到深色"，说明必须留下现场数据。
        #   半径/尺寸/读到的 theme 原值全部记进日志，用户复现时能直接看出走没走浅色分支。
        diag = _theme_diagnostics()
        _log_info(
            f"启动画面底色: {'深色' if dark else '浅色'}（跟随设置里的 theme）"
            f" theme={diag['theme_raw']} light={diag['light']}"
            f" DATA_DIR={diag['data_dir']} cfg_exists={diag['cfg_exists']}"
            f" 圆角半径={_corner_radius(width, height)}"
            + (f" 读取异常={diag['error']}" if diag["error"] else ""))

        # 每次用唯一类名，避免和上一次残留的注册冲突（启动画面可能开多次）
        class_name = "ToolsGCP_Splash_%d" % (int(time.time() * 1000) % 1000000)

        # 居中（按主屏工作区，等价原版 availableGeometry）
        try:
            left, top, right, bottom = win32.work_area()
            x = int(left + ((right - left) - width) / 2)
            y = int(top + ((bottom - top) - height) / 2)
        except Exception:
            x = y = 0

        hinst = win32.kernel32.GetModuleHandleW(None)

        # ---- 注册窗口类（幂等；类名唯一所以每次都是新的） ----
        result = {"hwnd": 0}

        def _wndproc(hwnd, msg, wparam, lparam):
            # ⚠️ 窗口过程异常绝不能逃出去（会直接 terminate 进程），统一用守卫包
            return _wndproc_guard(_wndproc_body)(hwnd, msg, wparam, lparam)

        def _wndproc_body(hwnd, msg, wparam, lparam):
            # 分层窗口是"画上去的"，必须吃掉擦背景，否则会闪一下白底
            if msg == _WM_ERASEBKGND:
                return 1
            # 关闭请求（外部 stop 也能走这里）→ 交给等待循环处理
            if msg == _WM_CLOSE:
                self._stop_requested.set()
                return 0
            if msg == _WM_DESTROY:
                result["hwnd"] = 0
                return 0
            return win32.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        try:
            cls = win32.WNDCLASSW()
            cls.style = 0
            cls.lpfnWndProc = win32.WNDPROC(_wndproc)
            cls.cbClsExtra = 0
            cls.cbWndExtra = 0
            cls.hInstance = hinst
            cls.hIcon = None
            cls.hCursor = win32.user32.LoadCursorW(None, 32512)   # IDC_ARROW
            cls.hbrBackground = None
            cls.lpszMenuName = None
            cls.lpszClassName = class_name
            atom = win32.user32.RegisterClassW(ctypes.byref(cls))
            if not atom and win32.kernel32.GetLastError() != 1410:   # 1410 = 已存在
                _log_warn("启动画面窗口类注册失败，降级")
                self._finish("降级")
                return
            self._class_registered = True
        except Exception as exc:                        # noqa: BLE001
            _log_warn(f"启动画面窗口类注册异常 {exc}，降级")
            self._finish("降级")
            return

        # ---- 建窗（无边框 + 置顶 + 分层 + 工具栏窗） ----
        ex = _WS_EX_LAYERED | _WS_EX_TOOLWINDOW | _WS_EX_TOPMOST
        try:
            hwnd = win32.user32.CreateWindowExW(
                ex, class_name, "ToolsGCP", _WS_POPUP, x, y, width, height,
                None, None, hinst, None)
        except Exception as exc:                        # noqa: BLE001
            _log_err(f"启动画面建窗异常: {exc}")
            self._finish("异常")
            return
        if not hwnd:
            _log_warn(f"启动画面建窗失败（error={win32.kernel32.GetLastError()}），降级")
            self._finish("降级")
            return
        self._hwnd = hwnd
        result["hwnd"] = hwnd

        # ---- 贴图（失败就降级，绝不留一个空白透明窗） ----
        # ⚠️ 必须把居中坐标 (x, y) 一起传进去：UpdateLayeredWindow 会用它设置窗口位置
        if not _update_layered(hwnd, width, height, raw, x, y):
            _log_warn("启动画面贴图失败，降级")
            self._close_window(win32, hwnd)
            self._finish("降级")
            return

        try:
            # SW_SHOWNOACTIVATE：启动画面不抢焦点（原版 Qt.Tool 的语义）
            win32.user32.ShowWindow(wintypes.HWND(hwnd), _SW_SHOWNOACTIVATE)
            win32.user32.UpdateWindow(wintypes.HWND(hwnd))
        except Exception:
            pass
        _log_info(f"启动画面窗口尺寸: {width}x{height}"
                  f"（独立 splash 窗口，主窗口 1280x880 不参与）")

        # ---- 等"时长到"或"被要求退出" ----
        # ⚠️ 用短睡轮询而不是阻塞消息循环：stop() 只置标志/发 WM_CLOSE，
        #    轮询是最简单可靠的接收方式（这条线程本来也不干别的）。
        # ⚠️ 硬超时是安全网：万一 duration 配得离谱或时钟异常，也不会让窗口赖着不走。
        deadline = time.monotonic() + min(self.duration_ms / 1000.0,
                                          SPLASH_HARD_TIMEOUT_MS / 1000.0)
        while time.monotonic() < deadline:
            if self._stop_requested.is_set() or not result["hwnd"]:
                break
            time.sleep(0.03)

        reason = "被要求退出" if self._stop_requested.is_set() else "播放完成"
        self._finish(reason)

        # ⚠️ 销毁必须在**建窗这条线程**上（跨线程 DestroyWindow 是未定义行为）
        self._close_window(win32, hwnd)

    def _close_window(self, win32, hwnd):
        try:
            win32.user32.DestroyWindow(wintypes.HWND(hwnd))
        except Exception as exc:                        # noqa: BLE001
            _log_warn(f"启动画面窗口销毁异常: {exc}")
        finally:
            self._hwnd = 0

    def _finish(self, reason: str):
        """标记结束 + 回调（**回调必须离开窗口线程**再执行）

        ⚠️⚠️ 回调会去 show()/install() 主窗口（WinForms 对象）；从窗口线程直接驱动它们
           会在退出时留下跨线程 GUI 状态残留（旧 Qt 版实测 6/6 崩 0xC0000005）。
           所以统一另起一条普通线程去调 —— 这条规则换实现后依然适用，别改回去。
        """
        with self._lock:
            if self._finished.is_set():
                return
            self._finished.set()
        _log_info(f"启动画面结束：{reason}")
        callback = self._on_finished
        if not callable(callback):
            return

        def _call():
            try:
                callback()
            except Exception as exc:                    # noqa: BLE001
                _log_warn(f"启动画面结束回调异常: {exc}")

        threading.Thread(target=_call, name="ToolsGCP-splash-done", daemon=True).start()


def _wndproc_guard(func):
    """窗口过程守卫：异常绝不能逃出 WndProc（逃出去会直接 terminate 整个进程）

    直接复用 `desktop/native/win32.py` 里那套（它已经处理好日志），
    这里只是把 import 挪到函数内，避免模块加载期就依赖 win32。
    """
    from .native.win32 import wndproc_guard as _guard
    return _guard(func)
