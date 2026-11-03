"""任务栏右键菜单：**自绘**圆角卡片 —— 逐常量复刻原版 PyQt5 `ui/tray_menu.py`。
========== 为什么不用系统 TrackPopupMenu ==========
系统菜单是 Windows 经典样式：白底、直角、系统字体、图标糊成 16×16 的位图，
和程序里那套深色玻璃界面完全不搭。原版 PyQt5 用 QMenu + WA_TranslucentBackground +
setStyleSheet 自己画；Web 版里没有 Qt，所以这里用 Win32 开一个**分层窗口**
（WS_EX_LAYERED + UpdateLayeredWindow）画同一套。
========== 原版常量与实测基准 ==========
来源：`.ToolsGCP/modules/pymodels/ui/tray_menu.py`（样式表常量）+
      `.ToolsGCP/modules/pymodels/ui/main_window.py:995 _show_tray_menu`（弹出定位）。
    圆角 12 / padding 6 / 行高 30 / 图标 14 / 图标左 10 / 文字左 30 /
    右留白 10 / 最小内容宽 92 / border 1px / margin 0 1px / hover 圆角 8 /
    分隔线 1px、margin 4px 8px（整行 9px）
    深色：底 rgba(43,43,43,.98) 边 rgba(255,255,255,.10) 字 #E8E8E8
          hover rgba(255,255,255,.10) 分隔线 rgba(255,255,255,.10)
    浅色：底 rgba(252,252,253,.98) 边 rgba(0,0,0,.08) 字 #1F2329
          hover rgba(0,0,0,.06) 分隔线 rgba(0,0,0,.08)
⚠️ Qt 样式表里的 `min-width / padding / margin` 是**盒模型**，不是"整条宽度"，
   所以最容易算错的就是宽度。原版真实数值是用离屏渲染量出来的
   （本机实测，微软雅黑 9pt @96dpi，原版 nav 文案）：
        中文标签（呼出主窗口/呼出搜索框/呼出AI/退出）  148 × 143
        英文标签（Show Main Window/…/Exit）            191 × 143
        条目 y = 7 / 37 / 67（分隔线行 97，高 9）/ 106，条目高 30
        hover 高亮框 = (8, 行顶, 宽-16, 30)，圆角 8
        分隔线 = y 行顶+4，x 从 15 到 (宽-16)
        图标墨迹 x 18..33（14px 宽），深色主题下是纯白 #FFFFFF
        文字墨迹 x 58 起，深色 #E8E8E8
    ⇒ 宽度 = 2*(border + padding + margin_x) + TEXT_LEFT
              + max(ITEM_MIN_WIDTH, 文字宽 + (有图标 ? ICON_SIZE+6 : 0))
              + ITEM_RIGHT_PADDING
       Qt 在条目有图标时会把文字起点和所需宽度同时 +20（图标 14 + 间距 6）；
       文字起点 = 58也是实测反推的，不是拍脑袋。
⚠️ 文字宽度必须用**真实字体度量**（见 `_text_width`）：GDI `GetTextExtentPoint32W`
   配 微软雅黑/12px，在本机 8 条文案上与 Qt `QFontMetrics.horizontalAdvance`
   **逐条完全相等**（115/101/48/20/60/60/36/24）。
   （旧实现按"中文 15px/英文 7px"估算，那是 12.5pt 的量级，比原版大 30%+。）
⚠️ 一切都在**托盘那条原生线程**上跑（见 tray.py），本模块不加锁保护跨线程状态。
"""

import ctypes
import threading
import time
from ctypes import wintypes

from . import win32
from .win32 import (HTCLIENT, SW_HIDE, SW_SHOWNOACTIVATE, VK_ESCAPE, WM_ACTIVATE,
                    WM_KEYDOWN, WM_KILLFOCUS, WM_LBUTTONUP, WM_MOUSEMOVE,
                    WM_NCHITTEST, WM_RBUTTONUP, WNDPROC, WS_EX_LAYERED,
                    WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_POPUP, wndproc_guard)

# ---------- 尺寸常量 ----------
# 基准来自原版 ui/tray_menu.py（圆角 12 / padding 6 / 行高 30 / 图标 14 / 文字左 30 …），
# 为了"菜单小一点"整体收过一档（圆角 12→9 / padding 6→4 / 行高 30→25 …）。
# ⚠️ 图标 13→16、最小字号 9→10pt 是**清晰度**考虑调回来的：
#    13px 的线稿图标 + 12px 的中文，在 100%/125% 缩放下笔画只有 1px，怎么抗锯齿都发虚；
#    16px 图标（源图是 32px，正好 2:1 下采样）+ 10pt（96dpi 下 13px）明显清楚，
#    代价只是菜单宽/高各多一点。清晰度优先于"逐像素复刻原版"。
MENU_RADIUS = 9               # QMenu { border-radius } —— 需求"缩小些"，12→10→9
MENU_PADDING = 4              # QMenu { padding } —— 6→5→4
MENU_BORDER = 1               # QMenu { border: 1px solid … }
ITEM_HEIGHT = 27              # QMenu：item { height } —— 25→27（字大了一号，行高跟着给一点）
ITEM_RADIUS = 7               # QMenu：item { border-radius } —— 8→7
ITEM_MARGIN_X = 1             # QMenu：item { margin: 0px 1px }
ITEM_MARGIN_Y = 0             # 同上，竖直方向是 0
ICON_SIZE = 16                # QMenu：icon { width/height } —— 13→16（清晰度）
ICON_LEFT = 8                 # QMenu：icon { left } —— 9→8（图标变大，左边收一点保持居中）
TEXT_LEFT = 26                # QMenu：item { padding-left } —— 30→26（横着更短）
ITEM_RIGHT_PADDING = 8        # QMenu：item { padding-right } —— 10→8
ITEM_MIN_WIDTH = 82           # QMenu：item { min-width }（内容盒）—— 92→82
ICON_SPACING = 5              # 有图标时额外让位 —— 6→5
SEPARATOR_LINE = 1            # QMenu：separator { height: 1px }
SEPARATOR_MARGIN_X = 7        # QMenu：separator { margin: 3px 7px }
SEPARATOR_MARGIN_Y = 3
SEPARATOR_HEIGHT = SEPARATOR_LINE + SEPARATOR_MARGIN_Y * 2      # 7

# 内容区原点（边框 + 内边距）：条目/图标/文字的绝对位置都从它起算
CONTENT_ORIGIN = MENU_BORDER + MENU_PADDING                     # 5

# ---------- 颜色（原版 refresh_theme 的两套，RGBA） ----------
# ⚠️⚠️ 底色 alpha 由 249（0.98）改成 **255（不透明）**，这是"字糊"的根治点：
#   托盘菜单用 UpdateLayeredWindow 贴图，而位图来自 `Bitmap.GetHbitmap(Transparent)`，
#   那条路**不保留逐像素 alpha** —— 文字的抗锯齿像素被当成"半透明底"再混一次，
#   于是笔画边缘发虚、整行字看着像蒙了一层雾。底色改成完全不透明后，
#   每个像素的 alpha 都是 255，混色退化成"直接拷贝"，文字栅格原样上屏。
#   视觉上和 0.98 几乎没差别（差 2% 亮度），但字锐利很多。
#   hover/separator 的 alpha 保持原值（它们是画在不透明底上的纯色，不参与混合）。
DARK = {
    "bg": (43, 43, 43, 255),
    "border": (255, 255, 255, 26),
    "text": (232, 232, 232, 255),
    "danger": (255, 82, 82, 255),     # 退出= 红字（#FF5252：饱和度更足的正红，深色底上够亮）
    "hover": (255, 255, 255, 26),
    "separator": (255, 255, 255, 26),
}
LIGHT = {
    "bg": (252, 252, 253, 255),
    "border": (0, 0, 0, 20),
    "text": (31, 35, 41, 255),
    "danger": (196, 43, 28, 255),     # 系统关闭按钮同款红
    "hover": (0, 0, 0, 15),
    "separator": (0, 0, 0, 20),
}
# ⚠️ 其余 alpha 的取值：原版写的是 rgba(...,0.10) / 0.08 / 0.06，
#    Qt 用 int(f*255) 截断 → 0.10 = 25 或 26、0.08 = 20、0.06 = 15。

# ---------- 界面字体（原版 = QApplication 的 UI 字体，字号 max(9, 系统字号)） ----------
# 候选表同 `.ToolsGCP/modules/pymodels/utils/fonts.py` 的 DEFAULT_FONT_CANDIDATES
UI_FONT_CANDIDATES = ("微软雅黑", "Microsoft YaHei UI", "等线", "DengXian",
                      "Segoe UI", "Arial")
# ⚠️ 9→10：9pt 在 96dpi 下只有 12px，中文笔画几乎是"1px 灰边"，用户反馈托盘菜单字发虚。
#    10pt = 13px，配合下面的 ClearTypeGridFit/物理像素渲染明显更实（菜单只高一点点）。
#    系统字号更大时仍然取系统值（max(10, 系统字号)），不会把高分屏压小。
UI_FONT_MIN_POINT = 10
# DIB 常量（CreateDIBSection 用；数值来自 wingdi.h）
DIB_RGB_COLORS = 0            # 位图里直接存 RGB 值（不是调色板索引）
BI_RGB = 0                    # 无压缩（32bpp 时 = BGRA）

# 键盘（win32.py 里没有这几个 VK_*）
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_RETURN = 0x0D
VK_SPACE = 0x20
VK_END = 0x23
VK_HOME = 0x24
VK_UP = 0x26
VK_DOWN = 0x28
PM_REMOVE = 0x0001
QS_ALLINPUT = 0x04FF
DT_VCENTER = 0x00000004
DT_SINGLELINE = 0x00000010

_CLASS_NAME = "ToolsGCP_TrayMenu"
_class_lock = threading.Lock()
_class_registered = False
_atom = None


# ======================================================================
# 日志：任何"降级/失败"都必须留下明确原因（不许静默退回系统菜单）
# ======================================================================
def _log(level: str, message: str):
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)("外壳", "tray", message)
    except Exception:
        pass


_success_logged = [False]


# ======================================================================
# DPI 缩放：原版 Qt 在 150% 缩放下把整个菜单放大 1.5 倍（逻辑像素→物理像素），
# 这里用系统 DPI 复刻；96dpi 时 _UI_SCALE == 1，上文实测数值原样成立。
# ======================================================================
def _compute_ui_scale() -> float:
    dpi = 96
    try:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetDpiForSystem.restype = ctypes.c_uint
        u.GetDpiForSystem.argtypes = []
        value = int(u.GetDpiForSystem())          # Win10 1607+
        if value > 0:
            dpi = value
    except Exception:
        try:
            gdi = ctypes.WinDLL("gdi32", use_last_error=True)
            usr = ctypes.WinDLL("user32", use_last_error=True)
            dc = usr.GetDC(None)
            dpi = int(gdi.GetDeviceCaps(ctypes.c_void_p(dc), 90))   # LOGPIXELSY
        except Exception:
            dpi = 96
    return max(1.0, min(3.0, dpi / 96.0))


_UI_SCALE = _compute_ui_scale()


def _s(value) -> int:
    """逻辑像素 → 本机物理像素（96dpi 时原样返回）"""
    if _UI_SCALE == 1.0:
        return int(value)
    return int(round(float(value) * _UI_SCALE))


# ======================================================================
# GDI / GDI+ 句柄签名
# ⚠️ 必须显式给 argtypes/restype：64 位下句柄会被默认 c_int 截断 → 静默画不出来。
# ⚠️ pythonnet 默认**不会**自动加载 System.Drawing：直接 `from System.Drawing import …`
#    会抛 ModuleNotFoundError，必须先用 clr.AddReference。
# ======================================================================
_gdi32 = None
_user32 = None
_gdiplus_ready = None
_gdiplus_error = ""
_gdiplus_lock = threading.Lock()
_init_lock = threading.Lock()


def _hval(handle) -> int:
    """pythonnet 的 IntPtr → int（`int(IntPtr)` 会 TypeError，必须走 ToInt64）"""
    to_int64 = getattr(handle, "ToInt64", None)
    if callable(to_int64):
        return int(to_int64())
    return int(handle)


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


# 32bpp DIB（分层窗口要"带逐像素 alpha 的位图"，只能用 CreateDIBSection 自己造）
class _BITMAPINFOHEADER(ctypes.Structure):
    """BITMAPINFOHEADER（wingdi.h；字段顺序不能动）"""
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),          # 负数 = top-down（行序与 GDI+ 一致）
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    """BITMAPINFO = 头 + 1 个 RGBQUAD 占位（32bpp 不用调色板，但结构体必须有这一项）
    ⚠️ bmiColors 是 **1 个 RGBQUAD（4 字节）**，sizeof(BITMAPINFO) 必须等于 44；
       写成 3 个 DWORD 会变成 52 字节 —— CreateDIBSection 只按 biSize 读头，
       多传几字节不会当场报错，但结构布局一旦被人当规范抄走就是坑。
    """
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 1),
    ]


class _BITMAP(ctypes.Structure):
    """BITMAP（GetObject 出来的信息；这里只需要 bmBits 指针做自检/兜底）"""
    _fields_ = [
        ("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
        ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
        ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


def _init_gdi() -> bool:
    global _gdi32, _user32
    if _gdi32 is not None:
        return True
    with _init_lock:
        if _gdi32 is not None:
            return True
        try:
            gdi = ctypes.WinDLL("gdi32", use_last_error=True)
            usr = ctypes.WinDLL("user32", use_last_error=True)
            gdi.CreateFontW.restype = ctypes.c_void_p
            gdi.CreateFontW.argtypes = [
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                wintypes.DWORD, wintypes.LPCWSTR]
            gdi.DeleteObject.restype = wintypes.BOOL
            gdi.DeleteObject.argtypes = [ctypes.c_void_p]
            gdi.SelectObject.restype = ctypes.c_void_p
            gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            gdi.GetTextExtentPoint32W.restype = wintypes.BOOL
            gdi.GetTextExtentPoint32W.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                                  ctypes.c_int,
                                                  ctypes.POINTER(_SIZE)]
            gdi.CreateCompatibleDC.restype = ctypes.c_void_p
            gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
            gdi.CreateCompatibleBitmap.restype = ctypes.c_void_p
            gdi.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                   ctypes.c_int]
            gdi.CreateSolidBrush.restype = ctypes.c_void_p
            gdi.CreateSolidBrush.argtypes = [wintypes.DWORD]
            gdi.CreatePen.restype = ctypes.c_void_p
            gdi.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.DWORD]
            gdi.MoveToEx.restype = wintypes.BOOL
            gdi.MoveToEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_void_p]
            gdi.LineTo.restype = wintypes.BOOL
            gdi.LineTo.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
            gdi.SetBkMode.restype = ctypes.c_int
            gdi.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
            gdi.SetTextColor.restype = wintypes.DWORD
            gdi.SetTextColor.argtypes = [ctypes.c_void_p, wintypes.DWORD]
            gdi.BitBlt.restype = wintypes.BOOL
            gdi.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                   ctypes.c_int, ctypes.c_int, wintypes.DWORD]
            gdi.DeleteDC.restype = wintypes.BOOL
            gdi.DeleteDC.argtypes = [ctypes.c_void_p]
            # 纯 GDI 兜底分支画图标用：一个像素一个 SetPixel（图标只有 16×16，够快；
            # 用 StretchDIBits 要再拼一套 BITMAPINFOHEADER，为一条降级路径不值当）
            gdi.SetPixel.restype = wintypes.DWORD
            gdi.SetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                     wintypes.DWORD]
            # 分层窗口的位图：CreateDIBSection 造一块**带逐像素 alpha** 的 32bpp DIB。
            # ⚠️ 参数 4 是 VOID**（输出位图 bits 的地址），必须传 byref(c_void_p)。
            gdi.CreateDIBSection.restype = ctypes.c_void_p
            gdi.CreateDIBSection.argtypes = [
                ctypes.c_void_p,                          # HDC（可为 NULL）
                ctypes.POINTER(_BITMAPINFO),              # const BITMAPINFO *
                wintypes.UINT,                            # usage（DIB_RGB_COLORS）
                ctypes.POINTER(ctypes.c_void_p),          # VOID **ppvBits
                ctypes.c_void_p,                          # HANDLE hSection
                wintypes.DWORD]                           # DWORD offset
            gdi.GetObjectW.restype = ctypes.c_int
            gdi.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            usr.GetDC.restype = ctypes.c_void_p
            usr.GetDC.argtypes = [wintypes.HWND]
            usr.ReleaseDC.restype = ctypes.c_int
            usr.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
            usr.FillRect.restype = ctypes.c_int
            usr.FillRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
            usr.DrawTextW.restype = ctypes.c_int
            usr.DrawTextW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int,
                                      ctypes.c_void_p, wintypes.UINT]
            usr.InvalidateRect.restype = wintypes.BOOL
            usr.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
            usr.GetAsyncKeyState.restype = ctypes.c_short
            usr.GetAsyncKeyState.argtypes = [ctypes.c_int]
            usr.MsgWaitForMultipleObjects.restype = wintypes.DWORD
            usr.MsgWaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.c_void_p,
                                                      wintypes.BOOL, wintypes.DWORD,
                                                      wintypes.DWORD]
            _gdi32, _user32 = gdi, usr
            return True
        except Exception as exc:
            _log("warn", f"gdi32/user32 签名初始化失败，菜单绘制与文字度量将降级: "
                         f"{type(exc).__name__}: {exc}")
            return False


def _ensure_gdiplus() -> bool:
    """确保 System.Drawing 可用（幂等）；失败原因存进 _gdiplus_error"""
    global _gdiplus_ready, _gdiplus_error
    if _gdiplus_ready is not None:
        return _gdiplus_ready
    with _gdiplus_lock:
        if _gdiplus_ready is not None:
            return _gdiplus_ready
        ok = False
        try:
            import clr                                   # pythonnet
            for name in ("System.Drawing", "System.Drawing.Common",
                         "System.Windows.Forms", "System"):
                try:
                    clr.AddReference(name)
                except Exception:
                    pass                                 # 缺个别程序集不算致命
            from System.Drawing import Bitmap            # noqa: F401  探针
            ok = True
            _gdiplus_error = ""
        except Exception as exc:
            _gdiplus_error = f"{type(exc).__name__}: {exc}"
            _log("warn", f"GDI+ 不可用（{_gdiplus_error}）：托盘菜单改用纯 GDI 绘制"
                         "（圆角改为区域裁切、图标改为逐像素合成），功能不受影响")
        _gdiplus_ready = ok
        return ok


# ======================================================================
# 字体与文字度量
# ======================================================================
_font_family_hint = ""            # 调用方传入（设置里的 ui_font_family）
_resolved_family = None
_resolved_point = None
_resolve_lock = threading.Lock()
_text_width_cache = {}
_text_width_lock = threading.Lock()
_gdiplus_font_cache = {}
_scratch_bitmap = None
_scratch_graphics = None
_measure_dc = None
_measure_font = None
_measure_key = None
_measure_lock = threading.Lock()
_fallback_warned = [False]


def set_font_family(family: str):
    """设置界面字体族（设置里的 ui_font_family；空 = 用默认候选表）"""
    global _font_family_hint, _resolved_family, _resolved_point
    family = str(family or "")
    if family == _font_family_hint:
        return
    with _resolve_lock:
        _font_family_hint = family
        _resolved_family = None
        _resolved_point = None
    with _text_width_lock:
        _text_width_cache.clear()


def _font_installed(name: str) -> bool:
    if not name:
        return False
    if not _ensure_gdiplus():
        return True                      # 判断不了就先用着（系统会做字体替换）
    try:
        from System.Drawing import FontFamily
        FontFamily(name)
        return True
    except Exception:
        return False


def ui_font_family() -> str:
    """界面字体族：优先设置值，否则按原版默认候选表取第一个装得上的"""
    global _resolved_family
    if _resolved_family:
        return _resolved_family
    with _resolve_lock:
        if _resolved_family:
            return _resolved_family
        candidates = ([_font_family_hint] if _font_family_hint else []) + \
            list(UI_FONT_CANDIDATES)
        chosen = ""
        for name in candidates:
            if _font_installed(name):
                chosen = name
                break
        _resolved_family = chosen or _font_family_hint or UI_FONT_CANDIDATES[0]
        return _resolved_family


def ui_font_point_size() -> int:
    """字号（pt）：原版 = max(9, QApplication.font().pointSize())，
    而 Qt 那个默认字号取自系统消息字体（SPI_GETNONCLIENTMETRICS）"""
    global _resolved_point
    if _resolved_point:
        return _resolved_point
    point = UI_FONT_MIN_POINT
    try:
        if _ensure_gdiplus():
            from System.Drawing import SystemFonts
            value = int(round(float(SystemFonts.MessageBoxFont.SizeInPoints)))
            if value > 0:
                point = max(UI_FONT_MIN_POINT, value)
    except Exception:
        point = UI_FONT_MIN_POINT
    _resolved_point = point
    return point


def _screen_graphics():
    """屏幕 DC 的 GDI+ Graphics
    ⚠️ `Graphics.FromHwnd` 只接受 `System.IntPtr`：传 `0` / `ctypes.c_void_p(0)`
       都会抛 `TypeError: No method matches given arguments`（pythonnet 3.x）。
       而 `_present()` 里一旦抛异常又会被上层吞掉 ⇒ 菜单再次变全透明，
       所以这里单独封装并让调用方把异常写进 last_error。
    """
    from System import IntPtr
    from System.Drawing import Graphics
    return Graphics.FromHwnd(IntPtr(0))


def ui_font_px() -> int:
    """字号（物理像素）：Qt 的 pointSize × 逻辑 DPI / 72"""
    dpi = 96.0
    try:
        if _ensure_gdiplus():
            probe = _screen_graphics()
            dpi = float(probe.DpiY) or 96.0
            probe.Dispose()
    except Exception:
        dpi = 96.0
    return max(1, int(round(ui_font_point_size() * dpi / 72.0)))


def _measure_dc_font():
    """量文字用的 (hdc, hfont)；失败返回 (None, None)"""
    global _measure_dc, _measure_font, _measure_key
    if not _init_gdi():
        return None, None
    key = (ui_font_family(), ui_font_px())
    if _measure_key == key and _measure_dc:
        return _measure_dc, _measure_font
    with _measure_lock:
        if _measure_key == key and _measure_dc:
            return _measure_dc, _measure_font
        hdc = _user32.GetDC(None)
        if not hdc:
            return None, None
        hfont = _gdi32.CreateFontW(-ui_font_px(), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5,
                                   0, ui_font_family())
        if not hfont:
            _user32.ReleaseDC(None, ctypes.c_void_p(hdc))
            return None, None
        _measure_dc, _measure_font, _measure_key = hdc, hfont, key
        return hdc, hfont


def _text_width_gdi(text: str):
    """GDI GetTextExtentPoint32W —— 与 Qt QFontMetrics 逐条相等（见模块 docstring）"""
    hdc, hfont = _measure_dc_font()
    if not hdc or not hfont:
        return None
    old = _gdi32.SelectObject(hdc, hfont)
    size = _SIZE()
    ok = _gdi32.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(size))
    _gdi32.SelectObject(hdc, ctypes.c_void_p(old))
    return float(size.cx) if ok else None


def _text_width_gdiplus(text: str):
    """兜底：GDI+ 排版度量（比 GDI 宽窄 0~3px，可接受）"""
    global _scratch_bitmap, _scratch_graphics
    if not _ensure_gdiplus():
        return None
    try:
        from System.Drawing import Bitmap, Font, Graphics, GraphicsUnit, StringFormat
        if _scratch_graphics is None:
            _scratch_bitmap = Bitmap(1, 1)
            _scratch_graphics = Graphics.FromImage(_scratch_bitmap)
        font = Font(ui_font_family(), ui_font_px(), GraphicsUnit.Pixel)
        fmt = StringFormat(StringFormat.GenericTypographic)
        return float(_scratch_graphics.MeasureString(text, font, 10000, fmt).Width)
    except Exception as exc:
        if not _fallback_warned[0]:
            _fallback_warned[0] = True
            _log("warn", f"GDI+ 文字度量不可用（{type(exc).__name__}: {exc}）")
        return None


def _text_width_estimate(text: str) -> float:
    """最后的估算兜底：CJK 按 1 em、ASCII 按 0.55 em（误差可达 ±15%）"""
    px = float(ui_font_px())
    return sum(px if ord(ch) > 0x2E80 else px * 0.55 for ch in text)


_estimate_warned = [False]


def _text_width(text: str) -> float:
    """条目文字宽度（物理像素）"""
    if not text:
        return 0.0
    with _text_width_lock:
        cached = _text_width_cache.get(text)
    if cached is not None:
        return cached
    value = _text_width_gdi(text)
    if value is None:
        value = _text_width_gdiplus(text)
    if value is None:
        value = _text_width_estimate(text)
        if not _estimate_warned[0]:
            _estimate_warned[0] = True
            _log("warn", "托盘菜单文字宽度改用估算值（GDI 与 GDI+ 均不可用），宽度可能有 ±15% 偏差")
    value = float(value)
    with _text_width_lock:
        _text_width_cache[text] = value
    return value


def _gdiplus_font():
    """GDI+ 字体（按 family+px 缓存）"""
    from System.Drawing import Font, GraphicsUnit
    key = (ui_font_family(), ui_font_px())
    font = _gdiplus_font_cache.get(key)
    if font is None:
        font = Font(key[0], key[1], GraphicsUnit.Pixel)
        _gdiplus_font_cache[key] = font
    return font


def _argb(rgba):
    """(r,g,b,a) → System.Drawing.Color（GDI+ 顺序是 A,R,G,B）"""
    _ensure_gdiplus()
    from System.Drawing import Color
    return Color.FromArgb(int(rgba[3]) if len(rgba) > 3 else 255,
                          int(rgba[0]), int(rgba[1]), int(rgba[2]))


def _rgb(rgba) -> int:
    """(r,g,b,a) → COLORREF（0x00BBGGRR，GDI 用）"""
    return (int(rgba[2]) << 16) | (int(rgba[1]) << 8) | int(rgba[0])


def _premultiply_dib(bits, width: int, height: int, stride: int = 0) -> int:
    """把一块 32bpp **BGRA（straight alpha）** 位图**就地**预乘成 premultiplied alpha
    ========== 为什么必须做（不预乘会在圆角出现黑/白边）==========
    GDI+ 的 `PixelFormat.Format32bppArgb` 是 **straight alpha**（RGB 与 alpha 无关），
    而 `UpdateLayeredWindow` 配 `AC_SRC_ALPHA` 要求位图是 **premultiplied alpha**
    （每个像素的 RGB 已经乘过 alpha/255）。不预乘时：
      · 圆角/描边那一圈抗锯齿像素（alpha 1..254）的 RGB 还是"满亮度"原色，
        DWM 按预乘公式合成 → 颜色被高估 → **深色桌面上看着是白边、浅色桌面上是黑边**；
      · 四个圆角粒度最粗，所以肉眼先看到的就是"黑角/白角"。
    预乘之后：A 不变，RGB = RGB*A/255（+127 四舍五入，和 GDI+ 内部算法一致）。
    ⚠️ 字节序是 **BGRA**（DIB 32bpp BI_RGB 的内存布局），但三个颜色通道乘同一个 alpha，
       所以顺序无关，只认 `[i+3]` 是 alpha。
    ⚠️ 完全不透明（255）直接跳过、全透明（0）把 RGB 清零 —— 菜单里 99% 像素是这两种，
       真正要算的只有圆角/描边那几百个像素，一次重绘远小于 1ms。
    返回真正被修改的像素数（= 半透明像素个数，日志/自检用）。
    """
    if not bits or width <= 0 or height <= 0:
        return 0
    row_bytes = int(width) * 4
    stride = int(stride or row_bytes)
    if stride < row_bytes:
        raise ValueError(f"DIB 行距 {stride} 小于一行字节数 {row_bytes}")
    changed = 0
    for y in range(int(height)):
        row = (ctypes.c_ubyte * row_bytes).from_address(int(bits) + y * stride)
        for i in range(0, row_bytes, 4):
            alpha = row[i + 3]
            if alpha == 255:
                continue
            if alpha == 0:
                row[i] = 0
                row[i + 1] = 0
                row[i + 2] = 0
                continue
            row[i] = (row[i] * alpha + 127) // 255
            row[i + 1] = (row[i + 1] * alpha + 127) // 255
            row[i + 2] = (row[i + 2] * alpha + 127) // 255
            changed += 1
    return changed


def _round_rect_path(graphics, x, y, w, h, radius):
    """GDI+ 圆角矩形路径（半径 > 边长一半时自动收一半，避免崩）"""
    from System.Drawing.Drawing2D import GraphicsPath
    r = max(0.0, min(float(radius), min(w, h) / 2.0))
    path = GraphicsPath()
    path.AddArc(x, y, r * 2, r * 2, 180, 90)
    path.AddArc(x + w - r * 2, y, r * 2, r * 2, 270, 90)
    path.AddArc(x + w - r * 2, y + h - r * 2, r * 2, r * 2, 0, 90)
    path.AddArc(x, y + h - r * 2, r * 2, r * 2, 90, 90)
    path.CloseFigure()
    return path


# ======================================================================
# 图标染色：.**两个绘制分支** 都必须能把退出图标染成主题 danger 红
# ======================================================================
def _tint_matrix_cells(rgba) -> dict:
    """返回 .NET `ColorMatrix` 的单元格值（行主序，见 TrayMenu._tint_bitmap 的长注释）
    单独拆出来是为了能被自检脚本直接验证"矩阵算出来的确实是目标色"，
    而不必真的起 GDI+（沙箱里 pythonnet 初始化不了）。
    """
    rgb = (rgba or (255, 82, 82))[:3]
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    return {
        # 原色贡献清零（R'/G'/B' 只由常量行决定）
        "Matrix00": 0.0,
        "Matrix11": 0.0,
        "Matrix22": 0.0,
        # A' = A（alpha 原样保留 ⇒ 图标形状保留，只是颜色被换掉）
        "Matrix33": 1.0,
        # 常量行：R' = r/255 …（第 4 行 = 那个"1"输入，列号才是输出分量）
        "Matrix40": r / 255.0,
        "Matrix41": g / 255.0,
        "Matrix42": b / 255.0,
    }


def _apply_tint_matrix(cells, pixel):
    """按 .NET 文档的变换公式算一遍（自检/文档用；GDI+ 分支走 ColorMatrix 本体）
    pixel = (R,G,B,A)，分量都是 0..1。返回变换后的 (R,G,B,A)。
    """
    r, g, b, a = [float(v) for v in pixel]
    one = 1.0
    out = []
    for column in range(4):
        value = (r * cells.get(f"Matrix0{column}", 0.0)
                 + g * cells.get(f"Matrix1{column}", 0.0)
                 + b * cells.get(f"Matrix2{column}", 0.0)
                 + a * cells.get(f"Matrix3{column}", 0.0)
                 + one * cells.get(f"Matrix4{column}", 0.0))
        out.append(max(0.0, min(1.0, value)))
    return tuple(out)


# ---------- 纯 GDI 兜底分支：自己解 PNG（那时 System.Drawing 根本不可用） ----------
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_png_cache = {}
_png_cache_lock = threading.Lock()


def _png_decode(data: bytes):
    """纯 Python 解 8 位、非隔行 PNG → [(r,g,b,a)] 像素列表 + (宽, 高)
    ⚠️ 为什么要自己写一个解码器：纯 GDI 兜底分支的定义就是"GDI+（pythonnet +
       System.Drawing）不可用"，而托盘图标的 PNG 正是用 GDI+ 栅格化出来的。
       兜底分支要"也把退出图标染红"，就只能自己解像素。
       只支持本程序自己产出的格式（8 位、非隔行、颜色类型 0/2/3/4/6），
       遇到别的一律抛 ValueError，由调用方降级成"这项不画图标"。
    """
    import struct
    import zlib
    if not data or not data.startswith(_PNG_SIGNATURE):
        raise ValueError("不是 PNG")
    offset = len(_PNG_SIGNATURE)
    width = height = 0
    bit_depth = color_type = interlace = 0
    palette = b""
    trns = b""
    idat = bytearray()
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        ctype = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        offset += 12 + length                      # 长度 + 类型 + 数据 + CRC
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filter, interlace = \
                struct.unpack(">IIBBBBB", body[:13])
        elif ctype == b"PLTE":
            palette = body
        elif ctype == b"tRNS":
            trns = body
        elif ctype == b"IDAT":
            idat.extend(body)
        elif ctype == b"IEND":
            break
    if width <= 0 or height <= 0:
        raise ValueError("PNG 缺 IHDR")
    if bit_depth != 8 or interlace:
        raise ValueError(f"只支持 8 位非隔行 PNG（bit_depth={bit_depth} "
                         f"interlace={interlace}）")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise ValueError(f"不支持的 PNG 颜色类型 {color_type}")
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    if len(raw) < (stride + 1) * height:
        raise ValueError("PNG 数据不足")
    # 逐行反滤波（PNG 规范 6.2：None/Sub/Up/Average/Paeth）
    pixels = bytearray(stride * height)
    prev = bytearray(stride)
    for y in range(height):
        base = y * (stride + 1)
        kind = raw[base]
        line = bytearray(raw[base + 1:base + 1 + stride])
        if kind == 1:                              # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif kind == 2:                            # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif kind == 3:                            # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif kind == 4:                            # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        elif kind != 0:
            raise ValueError(f"未知 PNG 滤波类型 {kind}")
        pixels[y * stride:(y + 1) * stride] = line
        prev = line
    # 展开成 RGBA
    out = []
    for i in range(width * height):
        p = i * channels
        if color_type == 6:
            out.append((pixels[p], pixels[p + 1], pixels[p + 2], pixels[p + 3]))
        elif color_type == 2:
            out.append((pixels[p], pixels[p + 1], pixels[p + 2], 255))
        elif color_type == 0:
            gray = pixels[p]
            out.append((gray, gray, gray, 255))
        elif color_type == 4:
            gray, alpha = pixels[p], pixels[p + 1]
            out.append((gray, gray, gray, alpha))
        else:                                      # 索引色
            index = pixels[p]
            base = index * 3
            if base + 2 >= len(palette):
                out.append((0, 0, 0, 0))
            else:
                alpha = trns[index] if index < len(trns) else 255
                out.append((palette[base], palette[base + 1], palette[base + 2], alpha))
    return out, (width, height)


def _resample_rows(pixels, source_size, target_size):
    """把源像素**带 alpha 权重的盒式平均**缩到 target_size（质量够用且只要十几行）"""
    sw, sh = source_size
    dw = dh = int(target_size)
    if dw <= 0 or sw <= 0 or sh <= 0:
        return []
    rows = []
    for y in range(dh):
        sy0 = int(y * sh / dh)
        sy1 = max(sy0 + 1, int((y + 1) * sh / dh))
        line = []
        for x in range(dw):
            sx0 = int(x * sw / dw)
            sx1 = max(sx0 + 1, int((x + 1) * sw / dw))
            red = green = blue = alpha = 0
            count = 0
            for sy in range(sy0, min(sy1, sh)):
                base = sy * sw
                for sx in range(sx0, min(sx1, sw)):
                    pr, pg, pb, pa = pixels[base + sx]
                    red += pr * pa
                    green += pg * pa
                    blue += pb * pa
                    alpha += pa
                    count += 1
            if alpha > 0 and count > 0:
                line.append((red // alpha, green // alpha, blue // alpha, alpha // count))
            else:
                line.append((0, 0, 0, 0))
        rows.append(line)
    return rows


def _icon_rgb_rows(png_bytes, size_px, ink_rgb=None, background_rgb=(0, 0, 0)):
    """PNG → size_px×size_px 的**不透明 RGB** 像素行（纯 GDI 兜底分支专用）
    ink_rgb 不为 None 时把整张图标换成该色（保留 alpha）——退出图标就是靠它变红的；
    为 None 时保留原色。GDI 的 SetPixel 不认 alpha，所以这里直接与菜单底色合成。
    失败返回 []（调用方就不绘制该图标，图标问题不应影响整张菜单）。
    """
    if not png_bytes:
        return []
    key = (hash(bytes(png_bytes)), len(png_bytes), int(size_px),
           ink_rgb, tuple(background_rgb))
    with _png_cache_lock:
        cached = _png_cache.get(key)
    if cached is not None:
        return cached
    try:
        pixels, (sw, sh) = _png_decode(png_bytes)
        rows = _resample_rows(pixels, (sw, sh), int(size_px))
        out = []
        for line in rows:
            result = []
            for r, g, b, alpha in line:
                if ink_rgb is not None:
                    r, g, b = ink_rgb
                remainder = 255 - alpha
                result.append(((r * alpha + background_rgb[0] * remainder) // 255,
                               (g * alpha + background_rgb[1] * remainder) // 255,
                               (b * alpha + background_rgb[2] * remainder) // 255))
            out.append(result)
    except Exception as exc:                          # noqa: BLE001
        _log("warn", f"兜底绘制：图标解码/染色失败（这项不画图标）: "
                     f"{type(exc).__name__}: {exc}")
        out = []
    with _png_cache_lock:
        _png_cache[key] = out
    return out


def _lparam_point(lparam):
    """WM_*BUTTON* 的 lParam → (x, y)（有符号）"""
    return (ctypes.c_short(lparam & 0xFFFF).value,
            ctypes.c_short((lparam >> 16) & 0xFFFF).value)


def _safe_call(callback):
    try:
        callback()
    except Exception as exc:
        _log("err", f"托盘菜单回调失败: {type(exc).__name__}: {exc}")


def _arrow_cursor():
    """IDC_ARROW（MAKEINTRESOURCE(32512)）—— 拿不到就返回 None（无光标也能注册类）
    ⚠️ LoadCursorW 的第二个参数是**整数资源 ID**，不是字符串。
    """
    try:
        return win32.user32.LoadCursorW(None, ctypes.c_void_p(32512))
    except Exception:
        try:
            return win32.user32.LoadCursorW(None, 32512)
        except Exception:
            return None


# ======================================================================
# 窗口类与窗口过程
# ======================================================================
_MENUS = {}                   # hwnd → TrayMenu
_MENU_WNDPROC = None          # ⚠️ 必须保持全局强引用，否则被 GC → 野指针崩溃


def _menu_proc():
    """菜单窗口过程（**模块级单例**）
    ⚠️⚠️ 必须只创建一次并保存在模块全局里：ctypes 的 WNDPROC 回调对象一旦被
       GC 回收，系统再往那个地址投递消息就是野指针（进程直接消失）。
    """
    global _MENU_WNDPROC
    if _MENU_WNDPROC is not None:
        return _MENU_WNDPROC

    @wndproc_guard
    def proc(hwnd, msg, wparam, lparam):
        menu = _MENUS.get(hwnd)
        if msg == win32.WM_NCCALCSIZE:
            return 0
        if msg == win32.WM_NCHITTEST:
            return HTCLIENT
        if menu is None:
            return win32.user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        if msg == WM_MOUSEMOVE:
            menu._on_mouse_move(lparam)
            return 0
        if msg == WM_LBUTTONUP:
            menu._on_click(lparam)
            return 0
        if msg == WM_RBUTTONUP:
            menu.close()
            return 0
        if msg == WM_ACTIVATE:
            # 失活（点了别处）就关：和系统菜单一个行为
            if (wparam & 0xFFFF) == 0:
                menu.close()
            return 0
        if msg == WM_KILLFOCUS:
            menu.close()
            return 0
        if msg == WM_KEYDOWN:
            menu._on_key(int(wparam))
            return 0
        if msg == win32.WM_DESTROY:
            _MENUS.pop(hwnd, None)
            menu._closed.set()
            return 0
        return win32.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    _MENU_WNDPROC = WNDPROC(proc)
    return _MENU_WNDPROC


def _register_class() -> bool:
    """注册菜单窗口类（幂等）；失败写明确日志，调用方据此降级"""
    global _class_registered, _atom
    if _class_registered:
        return True
    with _class_lock:
        if _class_registered:
            return True
        try:
            hinst = win32.kernel32.GetModuleHandleW(None)
            cls = win32.WNDCLASSW()
            cls.style = 0
            cls.lpfnWndProc = _menu_proc()
            cls.cbClsExtra = 0
            cls.cbWndExtra = 0
            cls.hInstance = hinst
            cls.hIcon = None
            cls.hCursor = _arrow_cursor()
            cls.hbrBackground = None
            cls.lpszMenuName = None
            cls.lpszClassName = _CLASS_NAME
            try:
                _atom = win32.user32.RegisterClassW(ctypes.byref(cls))
                last = win32.kernel32.GetLastError()
            except Exception as exc:
                _atom = 0
                last = f"{type(exc).__name__}: {exc}"
            # 1410 = ERROR_CLASS_ALREADY_EXISTS（之前注册过，属正常）
            _class_registered = bool(_atom) or last == 1410
            if not _class_registered:
                _log("err", f"注册托盘菜单窗口类失败 atom={_atom} err={last}")
        except Exception as exc:
            _class_registered = False
            _log("err", f"注册托盘菜单窗口类异常: {type(exc).__name__}: {exc}")
        return _class_registered


# ======================================================================
# 菜单数据 / 菜单本体
# ======================================================================
class TrayMenuItem:
    """一条菜单项（文字 + 可选图标 + 回调）；separator=True 时是分隔线
    `danger=True` → 文字用主题里的红色（退出这类破坏性操作，参照系统菜单习惯）。
    """

    __slots__ = ("text", "icon_png", "callback", "separator", "danger")

    def __init__(self, text="", icon_png=None, callback=None, separator=False,
                 danger=False):
        self.text = str(text or "")
        self.icon_png = icon_png
        self.callback = callback
        self.separator = bool(separator)
        self.danger = bool(danger)

    @property
    def has_icon(self) -> bool:
        return bool(self.icon_png)


class TrayMenu:
    """自绘托盘菜单：在**原生线程**上创建与弹窗（和托盘图标同一条线程）"""

    def __init__(self, items=None, dark=True, font_family=""):
        self.items = list(items or [])
        self.dark = bool(dark)
        if font_family:
            set_font_family(font_family)
        self.hwnd = 0
        self.opened = False           # 窗口是否真的建出来并画上去了
        self.last_error = ""          # 失败原因（调用方据此决定是否降级）
        self._hover = -1
        self._size = (0, 0)
        self._icons = {}              # index → Bitmap
        self._icons_loaded = False
        self._bitmap = None
        self._result = None
        self._closed = threading.Event()
        self._x = 0
        self._y = 0
        # 窗口当前是否被 SetWindowRgn 裁过圆角（旧路径/兜底用；alpha 贴图成功会清掉）
        self.window_region = False

    # ---------- 盒模型：图标/文字的绝对位置 ----------
    def _icon_reserve(self, item) -> int:
        """Qt 在条目有图标时额外让出的宽度（实测 20 = 图标 14 + 间距 6）"""
        return _s(ICON_SIZE) + _s(ICON_SPACING) if item.has_icon else 0

    def _icon_x(self) -> int:
        """图标左边缘（绝对）：1+6+1+10 = 18"""
        return _s(CONTENT_ORIGIN + ITEM_MARGIN_X + ICON_LEFT)

    def _text_x(self, item) -> int:
        """文字左边缘（绝对）：1+6+1+30 = 38，有图标再 +20 → 58"""
        return (_s(CONTENT_ORIGIN + ITEM_MARGIN_X + TEXT_LEFT)
                + self._icon_reserve(item))

    def _item_width(self, item) -> int:
        """单条所需总宽 = margin + padding-left + 内容 + padding-right + margin"""
        content = max(_s(ITEM_MIN_WIDTH),
                      _text_width(item.text) + self._icon_reserve(item))
        return (_s(ITEM_MARGIN_X) + _s(TEXT_LEFT) + int(round(content))
                + _s(ITEM_RIGHT_PADDING) + _s(ITEM_MARGIN_X))

    def _rows(self):
        """[(index, item, top, height)] + 菜单总高：量测/绘制/命中共用同一份布局"""
        rows = []
        top = _s(CONTENT_ORIGIN)
        for index, item in enumerate(self.items):
            height = (_s(SEPARATOR_HEIGHT) if item.separator
                      else _s(ITEM_HEIGHT) + 2 * _s(ITEM_MARGIN_Y))
            rows.append((index, item, top, height))
            top += height
        return rows, top + _s(CONTENT_ORIGIN)

    # ---------- 尺寸 ----------
    def _measure(self):
        """菜单宽高（与原版 sizeHint 同一个盒模型）
        宽 = 2*(border+padding+margin_x) + TEXT_LEFT
             + max(ITEM_MIN_WIDTH, 最长文字 + 图标让位) + ITEM_RIGHT_PADDING
        高 = 2*CONTENT_ORIGIN + 4*ITEM_HEIGHT + SEPARATOR_HEIGHT
        """
        width = 0
        for item in self.items:
            if not item.separator:
                width = max(width, self._item_width(item))
        if width <= 0:
            width = (_s(ITEM_MARGIN_X) + _s(TEXT_LEFT) + _s(ITEM_MIN_WIDTH)
                     + _s(ITEM_RIGHT_PADDING) + _s(ITEM_MARGIN_X))
        width += 2 * (_s(MENU_BORDER) + _s(MENU_PADDING))
        _, height = self._rows()
        self._size = (int(width), int(height))
        return self._size

    def _hit_test(self, x, y):
        """客户区坐标 → 命中的条目下标（-1 = 没命中 / 命中分隔线）"""
        if self._size == (0, 0):
            self._measure()
        width, height = self._size
        if x < 0 or y < 0 or x >= width or y >= height:
            return -1
        rows, _ = self._rows()
        for index, item, top, h in rows:
            if top <= y < top + h:
                return -1 if item.separator else index
        return -1

    # ---------- 画 ----------
    def render(self):
        """把整张菜单画进一张 Bitmap（**不需要窗口**，探针可直接出图核对）
        GDI+ 不可用时返回 None（调用方走 `_draw_fallback_gdi`）。
        """
        if not _ensure_gdiplus():
            return None
        try:
            from System.Drawing import (Bitmap, Color, Graphics, Pen, RectangleF,
                                        SolidBrush, StringAlignment, StringFormat)
            from System.Drawing.Drawing2D import (InterpolationMode, PixelOffsetMode,
                                                 SmoothingMode)
            from System.Drawing.Imaging import PixelFormat
            from System.Drawing.Text import TextRenderingHint
        except Exception as exc:
            _log("err", f"GDI+ 导入失败，改用纯 GDI 绘制: {type(exc).__name__}: {exc}")
            return None

        w, h = self._measure()
        if w <= 0 or h <= 0:
            return None
        if not self._icons_loaded:
            # render() 也要能独立出图（探针/预览不必先建窗口）
            self._load_icons()
        theme = DARK if self.dark else LIGHT
        # ⚠️ 必须**显式** 32bpp ARGB：分层窗口贴图要逐像素 alpha，圆角外才是真透明。
        #    （Bitmap(w,h) 默认也是 32bppArgb，但写死更保险 —— 谁也说不准 GDI+ 的默认
        #      会不会随版本/驱动变。）
        bmp = Bitmap(w, h, PixelFormat.Format32bppArgb)
        g = Graphics.FromImage(bmp)
        g.SmoothingMode = SmoothingMode.AntiAlias
        # ⚠️ 图标是 32px 源图缩到 16px：默认双线性下采样会把细线糊成一团灰，
        #    用 HighQualityBicubic 才保得住线稿的锐度（这就是"图标太模糊"的主因之一）。
        g.InterpolationMode = InterpolationMode.HighQualityBicubic
        # ⚠️⚠️ 这一行是"像不像原版"的关键：GDI+ 默认的像素栅格是**几何**的
        #     （矩形 (x,y,w,1) 会被 AA 拆到 y 和 y+1 两行、各 50% 浓度），
        #     而 Qt 用的是"整数坐标 = 像素中心"的栅格（整个画面 +0.5 偏移）。
        #     实测原版菜单圆角轮廓 [9,6,5,4,3,2,2,1,1,1,1,0,0] 正好等于
        #     "形状从 (0.5,0.5) 开始、半径 12"；分隔线也是整像素满浓度 (64,64,64)。
        #     设成 Half 后两者都对上，几何也统一成"矩形 (x,y,w,h) = 像素 x..x+w-1"。
        #     （PixelOffsetMode.HighQuality 与 Half 同为高质量 AA，保留 Half 是为了
        #       不改变已经实测对上的圆角/分隔线轮廓。）
        g.PixelOffsetMode = PixelOffsetMode.Half
        # ⚠️ 底色已改成完全不透明（见 DARK/LIGHT 的注释），所以这里可以用
        #    **ClearTypeGridFit**：次像素抗锯齿在实心底上不会出彩边，字比灰度
        #    抗锯齿（AntiAliasGridFit）锐利得多 —— 这正是"菜单里的字很模糊"的修法。
        g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit
        try:
            # ⚠️ 圆角外必须是**真透明**（alpha=0）：先整块清成 Transparent 再画圆角底，
            #    否则未绘制区域是"黑色 + alpha=0"或白底，贴到分层窗口上就会在圆角外
            #    露出黑/白边（"菜单四个角出现白边或者黑边"的现象）。
            g.Clear(Color.Transparent)
            # 底板：圆角 9 + 1px 描边（画满整块 w×h，和 Qt 的 widget 矩形一致）
            # ⚠️ .NET 里画线要 Pen 对象 + Graphics.DrawPath(pen, path)，
            #    不存在 Graphics.CreatePen（那是 Qt/Win32 的写法）。
            path = _round_rect_path(g, 0, 0, w, h, _s(MENU_RADIUS))
            g.FillPath(SolidBrush(_argb(theme["bg"])), path)
            g.DrawPath(Pen(_argb(theme["border"]), 1.0), path)

            font = _gdiplus_font()
            text_brush = SolidBrush(_argb(theme["text"]))
            # 退出这类破坏性条目用红字（主题里两套都有 danger）
            danger_brush = SolidBrush(_argb(theme.get("danger") or theme["text"]))
            # ⚠️ 必须 GenericTypographic 才能与 GDI/Qt 的字距一致（默认排版每行宽 ~6%）
            fmt = StringFormat(StringFormat.GenericTypographic)
            fmt.Alignment = StringAlignment.Near
            fmt.LineAlignment = StringAlignment.Center

            rows, _ = self._rows()
            for index, item, top, height in rows:
                if item.separator:
                    # 原版：QMenu：separator { height:1px; margin: 4px 8px }
                    # ⚠️ 分隔线**不套** `QMenu：item` 的 `margin: 0 1px`（那是 item
                    #    子控件自己的），所以左端 = 内容原点 + 8 = 15，右端 = w-16
                    #    （原版实测：zh 菜单 15..132、en 菜单 15..175）。
                    # ⚠️ 必须用**整数矩形填充**，不能用 DrawLine：GDI+ 的 1px 线以
                    #    坐标为中心，会被拆到相邻两行各 50% 覆盖 → 浓度只剩一半。
                    x0 = _s(CONTENT_ORIGIN + SEPARATOR_MARGIN_X)
                    y0 = top + _s(SEPARATOR_MARGIN_Y)
                    g.FillRectangle(SolidBrush(_argb(theme["separator"])),
                                    x0, y0, w - x0 * 2, _s(SEPARATOR_LINE))
                    continue
                if index == self._hover:
                    # 原版 hover 框：条目盒 + margin 1px，圆角 8
                    inset = _s(CONTENT_ORIGIN + ITEM_MARGIN_X)
                    g.FillPath(SolidBrush(_argb(theme["hover"])),
                               _round_rect_path(g, inset, top, w - inset * 2, height,
                                                _s(ITEM_RADIUS)))
                icon = self._icons.get(index)
                if icon is not None:
                    icon_top = top + (height - _s(ICON_SIZE)) / 2.0
                    g.DrawImage(icon, RectangleF(float(self._icon_x()), icon_top,
                                                 float(_s(ICON_SIZE)),
                                                 float(_s(ICON_SIZE))))
                if item.text:
                    left = self._text_x(item)
                    g.DrawString(item.text, font,
                                 danger_brush if getattr(item, "danger", False) else text_brush,
                                 RectangleF(float(left), float(top),
                                            float(max(1, w - left - 1)), float(height)),
                                 fmt)
            return bmp
        finally:
            try:
                g.Dispose()
            except Exception:
                pass

    def _present(self) -> bool:
        """把画好的位图贴进 WS_EX_LAYERED 窗口（优先走"带 alpha 的 32bpp DIB"）
        ========== 为什么必须自己造 DIB（"菜单四角白/黑边"的根治）==========
        `Bitmap.GetHbitmap(Color.Transparent)` 产出的是**没有逐像素 alpha** 的
        GDI 位图（透明像素的 RGB 被写成白色、alpha 当成不透明），UpdateLayeredWindow
        用 AC_SRC_ALPHA 读它时，四个圆角就变成"白/黑方块"（深色主题看着像黑边，浅色像白边）。
        只靠 `SetWindowRgn` 把窗口裁成圆角是治标：区域裁切没有抗锯齿，
        边缘是一圈硬锯齿，正好在圆角处露出杂色。
        系统推荐的做法（本函数走的路径）：
          ① `CreateDIBSection`(32bpp, top-down) 造一块**带 alpha 的 DIB**；
          ② `Bitmap.LockBits(Format32bppArgb)` 拿 GDI+ 的真实像素，逐行 memmove 进 DIB；
          ③ **预乘 alpha**（`RGB = RGB*A/255`）：GDI+ 给的是 straight alpha，而
             `AC_SRC_ALPHA` 要求 premultiplied —— 少了这一步圆角半透明像素会亮/暗一圈，
             肉眼就是"黑角/白角"；
          ④ `UpdateLayeredWindow(..., AC_SRC_OVER|AC_SRC_ALPHA)` 贴图；
          ⑤ **成功就不再 SetWindowRgn**（让 alpha 决定圆角，边上还有 1px 抗锯齿），
             同时把可能残留的旧区域清掉，避免"上一次失败留下的圆角裁切"继续生效。
        任一步失败 → `_present_legacy()`（GetHbitmap + SetWindowRgn）：
        宁可边缘差一档，也绝不能"右键托盘什么都不出来"。
        """
        if not self.hwnd or self._bitmap is None:
            return False
        if not _init_gdi() or not _gdi32:
            self.last_error = "gdi32 未就绪"
            return False
        if self._present_alpha():
            return True
        if self.last_error:
            _log("warn", f"托盘菜单 alpha 贴图失败，退回旧路径: {self.last_error}")
        return self._present_legacy()

    def _present_alpha(self) -> bool:
        """32bpp DIB + 逐像素 alpha 贴图（成功返回 True；失败把原因写进 last_error）"""
        try:
            from System.Drawing import Rectangle
            from System.Drawing.Imaging import ImageLockMode, PixelFormat
            screen = _screen_graphics()
        except Exception as exc:                          # noqa: BLE001
            self.last_error = f"取屏幕 DC 失败: {type(exc).__name__}: {exc}"
            return False
        w, h = int(self._size[0]), int(self._size[1])
        if w <= 0 or h <= 0:
            self.last_error = f"菜单尺寸异常: {w}x{h}"
            return False
        bitmap = self._bitmap
        hdc_screen = 0
        hdc_mem = 0
        hbmp = 0
        old = 0
        data = None
        locked = False
        ok = False
        premultiplied = 0
        try:
            hdc_screen = _hval(screen.GetHdc())
            hdc_mem = _gdi32.CreateCompatibleDC(ctypes.c_void_p(hdc_screen))
            if not hdc_mem:
                raise OSError("CreateCompatibleDC 失败")
            info = _BITMAPINFO()
            header = info.bmiHeader
            header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            header.biWidth = w
            # ⚠️ 负数高度 = top-down DIB：内存里第一行就是最上面那行，正好对上
            #    GDI+ LockBits 的 Scan0（正向 stride 也是从顶行开始）。
            header.biHeight = -h
            header.biPlanes = 1
            header.biBitCount = 32
            header.biCompression = BI_RGB
            header.biSizeImage = w * h * 4
            bits = ctypes.c_void_p()
            raw = _gdi32.CreateDIBSection(
                ctypes.c_void_p(hdc_screen), ctypes.byref(info), DIB_RGB_COLORS,
                ctypes.byref(bits), None, 0)
            hbmp = int(raw) if raw else 0     # 失败时 ctypes 返回 None
            if not hbmp or not bits.value:
                raise OSError("CreateDIBSection 失败")
            old = _gdi32.SelectObject(hdc_mem, ctypes.c_void_p(hbmp))
            # 尺寸一致性：位图和菜单窗口必须同尺寸，否则 UpdateLayeredWindow 会拉伸/裁切
            bmp_w, bmp_h = int(bitmap.Width), int(bitmap.Height)
            if (bmp_w, bmp_h) != (w, h):
                raise OSError(f"位图尺寸 {bmp_w}x{bmp_h} 与菜单 {w}x{h} 不一致")
            data = bitmap.LockBits(Rectangle(0, 0, w, h), ImageLockMode.ReadOnly,
                                   PixelFormat.Format32bppArgb)
            locked = True
            stride = int(data.Stride)
            source = _hval(data.Scan0)
            row_bytes = w * 4
            if stride < row_bytes:
                raise OSError(f"LockBits stride={stride} 小于一行 {row_bytes} 字节")
            if stride == row_bytes:
                ctypes.memmove(bits.value, source, row_bytes * h)
            else:
                # stride 可能有对齐填充：必须逐行拷，否则画面会斜着撕裂
                for y in range(h):
                    ctypes.memmove(bits.value + y * row_bytes,
                                   source + y * stride, row_bytes)
            # ⚠️⚠️ straight alpha → premultiplied alpha：
            #    GDI+ 给的是非预乘 ARGB，UpdateLayeredWindow 的 AC_SRC_ALPHA 要预乘。
            #    少了这一步，圆角/描边的半透明像素会亮/暗一圈（黑角/白角）。
            premultiplied = _premultiply_dib(bits.value, w, h, stride=row_bytes)
        except Exception as exc:                          # noqa: BLE001
            self.last_error = f"造 alpha 位图失败: {type(exc).__name__}: {exc}"
            return self._release_alpha(hdc_mem, hbmp, old, screen, hdc_screen, bitmap,
                                       data, locked)
        # 像素已经拷进 DIB：先解锁再贴图（贴图期间不需要占着 Bitmap）
        try:
            if locked:
                bitmap.UnlockBits(data)
                locked = False
        except Exception:
            pass
        try:
            pt_src = win32.POINT(0, 0)
            pt_dst = win32.POINT(self._x, self._y)
            size = win32.SIZE(w, h)
            blend = win32.BLENDFUNCTION()
            blend.BlendOp = 0          # AC_SRC_OVER
            blend.SourceConstantAlpha = 255
            blend.AlphaFormat = 1      # AC_SRC_ALPHA ← 有它才会用 DIB 的 alpha 通道
            ok = bool(win32.user32.UpdateLayeredWindow(
                self.hwnd, ctypes.c_void_p(hdc_screen), ctypes.byref(pt_dst),
                ctypes.byref(size), ctypes.c_void_p(hdc_mem), ctypes.byref(pt_src),
                0, ctypes.byref(blend), 2))
            if not ok:
                self.last_error = (f"UpdateLayeredWindow 失败 "
                                   f"err={win32.kernel32.GetLastError()}")
                return False
        except Exception as exc:                          # noqa: BLE001
            self.last_error = f"贴图异常: {type(exc).__name__}: {exc}"
            return False
        finally:
            self._release_alpha(hdc_mem, hbmp, old, screen, hdc_screen, bitmap, data,
                                locked)
        # alpha 已经能正确表达圆角 → 把可能存在的窗口区域裁切清掉
        # （否则上一次失败路径留下的圆角区域会继续生效，把抗锯齿边缘裁成硬边）
        try:
            if self.window_region:
                ctypes.windll.user32.SetWindowRgn(
                    ctypes.c_void_p(int(self.hwnd)), None, True)
                self.window_region = False
        except Exception:
            pass
        # 调试级别留一条证据：预乘了多少个半透明像素（= 圆角/描边那一圈）
        _log("dbg", f"托盘菜单 alpha 贴图成功: {w}x{h} 32bpp 预乘 {premultiplied} 个半透明像素")
        return ok

    @staticmethod
    def _release_alpha(hdc_mem, hbmp, old, screen, hdc_screen, bitmap, data, locked):
        """释放 alpha 贴图用到的 GDI 资源（任何一步失败都不许抛）"""
        try:
            if locked and data is not None:
                bitmap.UnlockBits(data)
        except Exception:
            pass
        try:
            if hdc_mem and old:
                _gdi32.SelectObject(hdc_mem, ctypes.c_void_p(old))
            if hbmp:
                # ⚠️ DIB section 也是 GDI 对象，用 DeleteObject 释放（连同它那块内存）
                _gdi32.DeleteObject(ctypes.c_void_p(hbmp))
            if hdc_mem:
                _gdi32.DeleteDC(hdc_mem)
        except Exception:
            pass
        try:
            if screen is not None:
                if hdc_screen:
                    screen.ReleaseHdc(ctypes.c_void_p(hdc_screen))
                screen.Dispose()
        except Exception:
            pass
        return False

    def _present_legacy(self) -> bool:
        """**旧路径**：GetHbitmap(Transparent) + SetWindowRgn 圆角裁切（alpha 贴图失败时兜底）
        ⚠️ 这条路径拿不到逐像素 alpha，圆角靠区域裁切（硬边、无抗锯齿），
           只在 DIB 那条路走不通时用 —— 至少菜单能显示出来。
        """
        if not self.hwnd or self._bitmap is None:
            return False
        try:
            from System.Drawing import Color as _Color
            screen = _screen_graphics()
        except Exception as exc:                          # noqa: BLE001
            self.last_error = f"取屏幕 DC 失败: {type(exc).__name__}: {exc}"
            _log("err", f"自绘托盘菜单贴图失败（{self.last_error}）")
            return False
        hdc_screen = 0
        hdc_mem = 0
        hbmp = 0
        old = 0
        ok = False
        try:
            hdc_screen = _hval(screen.GetHdc())
            hdc_mem = _gdi32.CreateCompatibleDC(ctypes.c_void_p(hdc_screen))
            hbmp = _hval(self._bitmap.GetHbitmap(_Color.Transparent))
            old = _gdi32.SelectObject(hdc_mem, ctypes.c_void_p(hbmp))
            w, h = self._size
            # 没有 alpha 就只能裁窗口区域（圆角外不属于本窗口 → 透出桌面）
            try:
                radius = int(round(_s(MENU_RADIUS) * 2))
                hrgn = ctypes.windll.gdi32.CreateRoundRectRgn(
                    0, 0, int(w) + 1, int(h) + 1, radius, radius)
                if hrgn:
                    self.window_region = True
                    ctypes.windll.user32.SetWindowRgn(
                        ctypes.c_void_p(int(self.hwnd)), ctypes.c_void_p(int(hrgn)), True)
            except Exception as exc:                      # noqa: BLE001
                _log("warn", f"托盘菜单圆角裁切失败（不影响弹出）: {exc}")
            pt_src = win32.POINT(0, 0)
            pt_dst = win32.POINT(self._x, self._y)
            size = win32.SIZE(w, h)
            blend = win32.BLENDFUNCTION()
            blend.BlendOp = 0          # AC_SRC_OVER
            blend.SourceConstantAlpha = 255
            blend.AlphaFormat = 1      # AC_SRC_ALPHA
            ok = bool(win32.user32.UpdateLayeredWindow(
                self.hwnd, ctypes.c_void_p(hdc_screen), ctypes.byref(pt_dst),
                ctypes.byref(size), ctypes.c_void_p(hdc_mem), ctypes.byref(pt_src),
                0, ctypes.byref(blend), 2))
            if not ok:
                self.last_error = (f"UpdateLayeredWindow 失败 "
                                   f"err={win32.kernel32.GetLastError()}")
                _log("err", f"自绘托盘菜单贴图失败（{self.last_error}）")
        except Exception as exc:                          # noqa: BLE001
            self.last_error = f"贴图异常: {type(exc).__name__}: {exc}"
            _log("err", f"自绘托盘菜单贴图失败（{self.last_error}）")
            ok = False
        finally:
            try:
                if hdc_mem and old:
                    _gdi32.SelectObject(hdc_mem, ctypes.c_void_p(old))
                if hbmp:
                    _gdi32.DeleteObject(ctypes.c_void_p(hbmp))
                if hdc_mem:
                    _gdi32.DeleteDC(hdc_mem)
            except Exception:
                pass
            try:
                screen.ReleaseHdc(ctypes.c_void_p(hdc_screen))
                screen.Dispose()
            except Exception:
                pass
        return ok

    def _draw(self):
        """重画 + 贴图（hover 变化、键盘移动时调用）"""
        bmp = self.render()
        if bmp is None:
            self._draw_fallback_gdi()
            return
        self._bitmap = bmp
        if self._present():
            self.opened = True
        elif not self.last_error:
            self.last_error = "UpdateLayeredWindow 失败"

    def _draw_fallback_gdi(self):
        """GDI+ 完全不可用时的兜底：底色 + 图标 + 文字 + 分隔线（圆角靠区域裁切）
        ⚠️ 以前这里调用的 `_rgb()` 根本没定义（NameError），又被 except 吞掉
           ⇒ 兜底路径也是死的。现在所有 GDI 调用都带显式 argtypes/restype + 日志。
        ⚠️ 以前这里**不画图标**（注释写着"无图标"），于是"所有绘制分支都要把退出
           图标染成主题红"这条根本无从谈起。现在补上 `_draw_icon_gdi`：
           自己解 PNG → 换色（danger 项换成 theme["danger"]）→ 与菜单底色合成 → SetPixel。
           注意这是**降级路径**（GDI+ 不可用才会走到），观感差一档可以接受，功能不能缺。
        ⚠️ 兜底路径也要用 `SetWindowRgn` 把窗口裁成圆角。兜底路径没有逐像素 alpha，
           不裁的话四角就是**方角**（深色主题下像四个黑角、浅色下像白角，
           观感就是"周围有时也有白边或者黑边"）。裁切没有抗锯齿，但至少形状和主题色是对的；
           字号/图标大小与其他分支共用同一套常量（`_s(ICON_SIZE)` / `ui_font_px()`）。
        """
        if not self.hwnd:
            return
        _init_gdi()
        if not _gdi32:
            self.last_error = "纯 GDI 兜底不可用（gdi32 未就绪）"
            _log("err", f"自绘托盘菜单无法显示：{self.last_error}")
            return
        w, h = int(self._size[0]), int(self._size[1])
        if w <= 0 or h <= 0:
            return
        theme = DARK if self.dark else LIGHT
        # ⚠️ 窗口是带 WS_EX_LAYERED 建的；分层窗口**不会**显示 BitBlt 上去的内容
        #    （必须走 UpdateLayeredWindow）。纯 GDI 兜底路径要先摘掉 WS_EX_LAYERED，
        #    否则"兜底绘制"看起来还是全透明 —— 又是一条静默死路。
        try:
            gwl_exstyle = -20
            ex = win32.user32.GetWindowLongPtrW(self.hwnd, gwl_exstyle)
            if ex and (int(ex) & WS_EX_LAYERED):
                win32.user32.SetWindowLongPtrW(self.hwnd, gwl_exstyle,
                                               ctypes.c_void_p(int(ex) & ~WS_EX_LAYERED))
        except Exception as exc:                          # noqa: BLE001
            _log("warn", f"纯 GDI 兜底：摘除 WS_EX_LAYERED 失败（窗口可能仍全透明）: "
                         f"{type(exc).__name__}: {exc}")
        # 圆角：兜底分支没有 alpha，只能裁窗口区域（硬边，但不会出现方角白/黑块）
        try:
            radius = int(round(_s(MENU_RADIUS) * 2))
            hrgn = ctypes.windll.gdi32.CreateRoundRectRgn(
                0, 0, w + 1, h + 1, radius, radius)
            if hrgn:
                self.window_region = True
                ctypes.windll.user32.SetWindowRgn(
                    ctypes.c_void_p(int(self.hwnd)), ctypes.c_void_p(int(hrgn)), True)
        except Exception as exc:                          # noqa: BLE001
            _log("warn", f"纯 GDI 兜底：圆角裁切失败（菜单会是方角）: {exc}")
        hdc = _user32.GetDC(self.hwnd)
        if not hdc:
            self.last_error = "GetDC 返回空"
            _log("err", f"纯 GDI 兜底失败：{self.last_error}")
            return
        mem = _gdi32.CreateCompatibleDC(ctypes.c_void_p(hdc))
        hbmp = _gdi32.CreateCompatibleBitmap(ctypes.c_void_p(hdc), w, h)
        old = _gdi32.SelectObject(mem, ctypes.c_void_p(hbmp))
        try:
            brush = _gdi32.CreateSolidBrush(_rgb(theme["bg"]))
            rect = win32.RECT(0, 0, w, h)
            _user32.FillRect(mem, ctypes.byref(rect), ctypes.c_void_p(brush))
            _gdi32.DeleteObject(ctypes.c_void_p(brush))

            _gdi32.SetBkMode(mem, 1)                       # TRANSPARENT
            _gdi32.SetTextColor(mem, _rgb(theme["text"]))
            rows, _ = self._rows()
            for index, item, top, height in rows:
                if item.separator:
                    pen = _gdi32.CreatePen(0, 1, _rgb(theme["separator"]))
                    oldpen = _gdi32.SelectObject(mem, ctypes.c_void_p(pen))
                    x0 = _s(CONTENT_ORIGIN + SEPARATOR_MARGIN_X)
                    y = top + _s(SEPARATOR_MARGIN_Y)
                    _gdi32.MoveToEx(mem, x0, y, None)
                    _gdi32.LineTo(mem, w - 1 - x0, y)
                    _gdi32.SelectObject(mem, ctypes.c_void_p(oldpen))
                    _gdi32.DeleteObject(ctypes.c_void_p(pen))
                    continue
                r = win32.RECT(self._text_x(item), top, w - 1, top + height)
                # 图标（danger 项在这里也换主题红，见 _draw_icon_gdi）
                self._draw_icon_gdi(mem, item, top, height, theme)
                _gdi32.SetTextColor(mem, _rgb(theme.get("danger") or theme["text"])
                                    if getattr(item, "danger", False)
                                    else _rgb(theme["text"]))
                _user32.DrawTextW(mem, item.text, len(item.text), ctypes.byref(r),
                                  DT_VCENTER | DT_SINGLELINE)
            _gdi32.BitBlt(ctypes.c_void_p(hdc), 0, 0, w, h, mem, 0, 0, 0x00CC0020)
            _user32.InvalidateRect(self.hwnd, None, True)
            self.opened = True
        except Exception as exc:
            self.last_error = f"纯 GDI 兜底绘制异常: {type(exc).__name__}: {exc}"
            _log("err", f"自绘托盘菜单降级为纯 GDI 绘制，但仍然失败（{self.last_error}）")
        finally:
            try:
                _gdi32.SelectObject(mem, ctypes.c_void_p(old))
                _gdi32.DeleteObject(ctypes.c_void_p(hbmp))
                _gdi32.DeleteDC(mem)
            except Exception:
                pass
            try:
                _user32.ReleaseDC(self.hwnd, ctypes.c_void_p(hdc))
            except Exception:
                pass

    def _draw_icon_gdi(self, mem_hdc, item, top, height, theme):
        """纯 GDI 兜底分支画一枚图标（**danger 项必须染成主题 danger 红**）
        与 GDI+ 分支的区别：这里没有 DrawImage，所以用"解码成像素 → 换色 → 与底色合成
        → 逐像素 SetPixel"。`ink` 为 None 表示保留图标原色（非 danger 项，观感与之前一致）。
        任何失败都只记日志、不抛（兜底路径再抛就整张菜单没了）。
        """
        if not getattr(item, "icon_png", None):
            return
        try:
            size = _s(ICON_SIZE)
            if size <= 0:
                return
            ink = None
            if getattr(item, "danger", False):
                # 和文字同一个色源：深浅两套主题各自的 danger（深色 (255,82,82) / 浅色 (196,43,28)）
                ink = tuple(int(c) for c in (theme.get("danger") or theme["text"])[:3])
            rows = _icon_rgb_rows(item.icon_png, size, ink,
                                  tuple(int(c) for c in theme["bg"][:3]))
            if not rows:
                return
            x0 = self._icon_x()
            y0 = int(top + (height - size) / 2.0)
            set_pixel = _gdi32.SetPixel
            for y, line in enumerate(rows):
                for x, rgb in enumerate(line):
                    set_pixel(mem_hdc, x0 + x, y0 + y, _rgb(rgb))
        except Exception as exc:                          # noqa: BLE001
            _log("warn", f"纯 GDI 兜底：图标绘制失败（该项只画文字）: "
                         f"{type(exc).__name__}: {exc}")

    def _load_icons(self):
        """把 PNG 字节转成可 DrawImage 的 Bitmap"""
        self._icons = {}
        self._icons_loaded = True
        if not _ensure_gdiplus():
            return
        try:
            from System.Drawing import Bitmap
            from System.IO import MemoryStream
        except Exception as exc:
            _log("warn", f"图标解码不可用，菜单只画文字: {type(exc).__name__}: {exc}")
            return
        theme = DARK if self.dark else LIGHT
        for index, item in enumerate(self.items):
            if item.separator or not item.icon_png:
                continue
            try:
                bitmap = Bitmap(MemoryStream(bytes(item.icon_png)))
                # 退出的图标也要是红的（不只是文字）—— 把图标整体染成 danger 色。
                # 做法：先把原图画进一张透明底的新图，再切 SourceIn 合成模式填满红色矩形：
                #      非透明像素的 RGB 被换成红色、alpha 原样保留 ⇒ 得到一个"红色剪影图标"。
                if getattr(item, "danger", False):
                    try:
                        bitmap = self._tint_bitmap(bitmap, theme.get("danger"))
                        # 仅调试级别：染色成功留一条证据（默认不写日志，避免刷屏）
                        _log("dbg", f"第 {index} 项「{item.text}」图标已染成主题 danger 色 "
                                    f"{theme.get('danger')}")
                    except Exception as exc:      # noqa: BLE001
                        _log("warn", f"第 {index} 项图标染色失败（用原色）: "
                                     f"{type(exc).__name__}: {exc}")
                self._icons[index] = bitmap
            except Exception as exc:
                _log("warn", f"第 {index} 项图标解码失败（该项只画文字）: "
                             f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _tint_bitmap(bitmap, rgba):
        """把一张位图整片染成指定颜色（保留 alpha），返回新位图
        ⚠️ 只在 GDI+ 可用时走到；任何一步失败都由调用方兜回原图，不让菜单变空白。
        ⚠️⚠️ **退出图标发黑的根因就在矩阵的行列序**：
            .NET 的 `ColorMatrix` 是**行主序**的 5×5 矩阵，.NET 文档给的变换是
                R' = R*M00 + G*M10 + B*M20 + A*M30 + 1*M40
                G' = R*M01 + G*M11 + B*M21 + A*M31 + 1*M41
                B' = R*M02 + G*M12 + B*M22 + A*M32 + 1*M42
                A' = R*M03 + G*M13 + B*M23 + A*M33 + 1*M43
            也就是说 **行号 = 输入分量（R/G/B/A/常量1）、列号 = 输出分量**。
            如果写成 `Matrix03/13/23 = r,g,b/255` —— 那是"输入 R/G/B 对**输出 alpha**
            的贡献"，于是：R' = G' = B' = 0（图标变成纯黑），A' 反而被三个通道抬到 1。
            现象就是"文字已变红、图标还是黑的"。
            正确写法是**常量行（第 4 行）**：M40/M41/M42 = 目标色，再让 M00/M11/M22 = 0
            把原色贡献清零、M33 = 1 保 alpha，于是 R'=r、G'=g、B'=b、A'=A，
            得到一张"目标色剪影"（这就是社区里通用的固定色矩阵写法）。
        """
        from System.Drawing import Bitmap as _Bmp, Color, Graphics, GraphicsUnit, Rectangle
        from System.Drawing.Imaging import ColorMatrix, ImageAttributes
        width, height = int(bitmap.Width), int(bitmap.Height)
        matrix = ColorMatrix()
        for name, value in _tint_matrix_cells(rgba).items():
            setattr(matrix, name, float(value))
        attrs = ImageAttributes()
        attrs.SetColorMatrix(matrix)
        tinted = _Bmp(width, height)
        g = Graphics.FromImage(tinted)
        try:
            g.Clear(Color.Transparent)
            g.DrawImage(bitmap, Rectangle(0, 0, width, height),
                        0, 0, width, height, GraphicsUnit.Pixel, attrs)
        finally:
            try:
                g.Dispose()
            except Exception:
                pass
            try:
                attrs.Dispose()
            except Exception:
                pass
        return tinted


    # ---------- 交互 ----------
    def _on_mouse_move(self, lparam):
        x, y = _lparam_point(lparam)
        hit = self._hit_test(int(x), int(y))
        if hit != self._hover:
            self._hover = hit
            self._draw()

    def _on_click(self, lparam):
        """鼠标左键抬起：用**点击位置**命中（不能只信最后一次 mousemove 的 hover）"""
        x, y = _lparam_point(lparam)
        hit = self._hit_test(int(x), int(y))
        if hit < 0 or hit >= len(self.items):
            return
        self._hover = hit
        self._activate(hit)

    def _activate(self, index: int):
        item = self.items[index]
        self._result = item
        callback = item.callback
        self.close()
        if callable(callback):
            # 回调放独立线程：里面可能弹窗口/等消息，不能卡住托盘线程
            threading.Thread(target=_safe_call, args=(callback,), daemon=True).start()

    def _on_key(self, vk) -> bool:
        """键盘操作（对齐原版 QMenu）：↑↓ 移动、Enter/Space 触发、Esc 关闭、Home/End 首尾"""
        selectable = [i for i, item in enumerate(self.items) if not item.separator]
        if vk == VK_ESCAPE:
            self.close()
            return True
        if vk in (VK_DOWN, VK_UP):
            if not selectable:
                return True
            if self._hover not in selectable:
                new = selectable[0] if vk == VK_DOWN else selectable[-1]
            else:
                pos = selectable.index(self._hover)
                pos = (pos + (1 if vk == VK_DOWN else -1)) % len(selectable)
                new = selectable[pos]
            self._hover = new
            self._draw()
            return True
        if vk in (VK_HOME, VK_END):
            if selectable:
                self._hover = selectable[0] if vk == VK_HOME else selectable[-1]
                self._draw()
            return True
        if vk in (VK_RETURN, VK_SPACE):
            if 0 <= self._hover < len(self.items) and not self.items[self._hover].separator:
                self._activate(self._hover)
            return True
        return False

    def _clicked_outside(self) -> bool:
        """鼠标左右键按下且光标不在菜单上 → 应当关闭
        ⚠️ 存在的意义：菜单是 WS_EX_TOPMOST 分层窗口，WM_ACTIVATE / WM_KILLFOCUS
           这两条失活消息**不一定**发得出来（SetForegroundWindow 被前台锁定拒绝时
           就是这样）。只靠失活消息会出现"点了别处菜单还赖在屏幕上"。这里再用
           GetAsyncKeyState + 光标位置兜一层，和系统菜单行为一致。
        """
        if not _user32:
            return False
        try:
            pressed = (_user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000) or \
                      (_user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
            if not pressed:
                return False
            pt = win32.POINT()
            win32.user32.GetCursorPos(ctypes.byref(pt))
            left, top, right, bottom = win32.rect_of(self.hwnd)
            return not (left <= pt.x < right and top <= pt.y < bottom)
        except Exception:
            return False

    # ---------- 弹出 / 关闭 ----------
    def popup(self, x, y):
        """在 (x, y) 弹出（阻塞到用户选完或取消）
        ⚠️ 必须在本线程跑消息循环：托盘菜单是模态的，和系统 TrackPopupMenu 一样。
        返回被选中的 TrayMenuItem；`self.opened` 表示窗口是否真的建出来并画上去了。
        调用方（tray.py）在 opened=False 时必须降级到系统菜单并记录 last_error。
        """
        if not win32.IS_WINDOWS:
            self.last_error = "非 Windows 平台"
            return None
        if not _init_gdi():
            self.last_error = "gdi32/user32 未就绪"
        if not _register_class():
            self.last_error = self.last_error or "菜单窗口类注册失败"
            return None
        self._x, self._y = int(x), int(y)
        w, h = self._measure()
        self._load_icons()

        hinst = win32.kernel32.GetModuleHandleW(None)
        ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
        self.hwnd = win32.user32.CreateWindowExW(
            ex, _CLASS_NAME, "", WS_POPUP, self._x, self._y, w, h,
            None, None, hinst, None)
        if not self.hwnd:
            self.last_error = f"CreateWindowExW 失败 err={win32.kernel32.GetLastError()}"
            _log("err", f"自绘托盘菜单建窗失败：{self.last_error}")
            return None
        _MENUS[self.hwnd] = self
        win32.user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        win32.user32.SetForegroundWindow(self.hwnd)
        self._draw()
        if not self.opened:
            # 画都没画上去就别进消息循环：否则界面像卡住（点了没反应）
            _log("err", "自绘托盘菜单未能绘制，降级为系统菜单。原因: "
                        f"{self.last_error or '未知'}")
            self.close()
            return None

        if not _success_logged[0]:
            _success_logged[0] = True
            _log("info", f"自绘托盘菜单已启用: 字体={ui_font_family()} "
                         f"{ui_font_point_size()}pt/{ui_font_px()}px "
                         f"缩放={_UI_SCALE:.2f} 尺寸={w}x{h}")
        _log("dbg", f"托盘菜单弹出: 自绘 {w}x{h} @({self._x},{self._y}) "
                     f"深色={self.dark} 项数={len(self.items)}")

        msg = wintypes.MSG()
        while not self._closed.is_set():
            if win32.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == win32.WM_QUIT:
                    break
                win32.user32.TranslateMessage(ctypes.byref(msg))
                win32.user32.DispatchMessageW(ctypes.byref(msg))
                continue
            # 空闲：等 30ms 或下一条消息（不忙等）
            try:
                _user32.MsgWaitForMultipleObjects(0, None, False, 30, QS_ALLINPUT)
            except Exception:
                time.sleep(0.03)
            if self._clicked_outside():
                self.close()
                break
        return self._result

    def close(self):
        if self.hwnd:
            try:
                win32.user32.ShowWindow(self.hwnd, SW_HIDE)
                win32.user32.DestroyWindow(self.hwnd)
            except Exception:
                pass
            _MENUS.pop(self.hwnd, None)
            self.hwnd = 0
        self._closed.set()
