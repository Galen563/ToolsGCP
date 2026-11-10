"""无边框窗口补丁：让 frameless 窗口仍然可拖边缩放、最大化贴合工作区、Win11 圆角。
========== 圆角策略：为什么要用 DWMWCP_ROUND ==========
主窗口要求**圆润角**而不是直角。
曾因窗口底边两角出现极小白角/黑角把圆角整个关掉（DWMWCP_DONOTROUND）。
实测查清了白边/黑边的**真正来源**（不是圆角的 AA 边缘，而是 pywebview
`shadow=True` 留下的那 1px 玻璃条，详见 `_update_corner` 的说明），把它消掉后，
圆角可以安全地使用 `DWMWCP_ROUND`。
========== 为什么需要这一层 ==========
pywebview 的 `frameless=True` 会把 WinForms 的 FormBorderStyle 设成 None，窗口变成
WS_POPUP：**没有缩放边框、没有最大化吸附、也没有系统阴影**（实测 WM_NCHITTEST 全部返回
HTCLIENT）。原版 PyQt5 用的是 qframelesswindow，它在 nativeEvent 里自己做命中测试 + 自己
处理 WM_NCCALCSIZE，视觉与手感都是"无边框但仍像原生窗口"。
所以这里做三件事（顺序不能反）：
  1. 把 WS_THICKFRAME / WS_SYSMENU / WS_MINIMIZEBOX / WS_MAXIMIZEBOX 加回窗口样式
     → 系统重新提供**四边四角的原生缩放手势**（实测左/右/下/角全部返回 HTLEFT 等）；
  2. 子类化窗口过程，在 WM_NCCALCSIZE 里返回 0（wParam=TRUE 时）
     → 把"系统要画的边框"吃掉，客户区重新铺满整个窗口（否则四周会多出 7px 边框）；
  3. 在 WM_GETMINMAXINFO 里把最大化尺寸钉到**当前显示器工作区**
     → 加了 WS_THICKFRAME 之后系统默认会按"边框外扩"最大化，任务栏会被盖住
       （实测 -7,-7 → 1927,1087）；钉住之后正好 0,0 → 1920,1032。
⚠️ 三条都必须有：只加样式 → 四周边框 + 任务栏被盖住；只吃 NCCALCSIZE → 不能缩放。
⚠️ 窗口过程里抛异常会直接终止进程，所有分支都走 wndproc_guard。
"""

import ctypes
import threading
import time
from ctypes import wintypes

from . import win32
from .win32 import (GWL_EXSTYLE, GWL_STYLE, GWLP_WNDPROC, HTBOTTOM, HTBOTTOMLEFT,
                    HTBOTTOMRIGHT, HTCLIENT, HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT,
                    HTTOPRIGHT, SC_CLOSE, SC_MAXIMIZE, SC_MINIMIZE, SC_RESTORE,
                    SWP_FRAMECHANGED, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOZORDER,
                    SWP_NOSIZE, SWP_SHOWWINDOW, WM_CLOSE, WM_GETMINMAXINFO, WM_NCCALCSIZE,
                    WM_NCHITTEST, WM_SYSCOMMAND, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW,
                    WS_EX_TOPMOST, MINMAXINFO, RECT,
                    WS_MAXIMIZEBOX, WS_MINIMIZEBOX, WS_SYSMENU, WS_THICKFRAME,
                    wndproc_guard, WNDPROC)

# 缩放热区的逻辑像素宽度（历史常量，保留给外部查询；实际宽度见 RESIZE_INSET）
BORDER_WIDTH = 5
# HTNOWHERE：屏幕坐标不在本窗口内（WM_NCHITTEST 的合法返回值之一，数值 0）
HTNOWHERE = 0

# Win11 圆角/边框色
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
# 关掉本窗口的 DWM 过渡动画（最小化 / 最大化 / 还原 / 全屏 / 关闭）。
# Win11 默认给这些动作加"缩放 + 淡出"动画，对无边框自绘标题栏来说很突兀；
# 需求：像 Win10 一样干脆。
#⚠️ 属性号**是 3，不是 2**（复核结论，别再改）：DWMWINDOWATTRIBUTE 的第一个成员不是 0 ——
#    微软文档 dwmapi.h 明确写着 "The value of DWMWA_NCRENDERING_ENABLED is 1"，于是枚举是
#        1 DWMWA_NCRENDERING_ENABLED / 2 DWMWA_NCRENDERING_POLICY
#        3 DWMWA_TRANSITIONS_FORCEDISABLED   ← 我们要的
#        4 DWMWA_ALLOW_NCPAINT ...
#    （DWMWA_USE_IMMERSIVE_DARK_MODE=20 / CORNER_PREFERENCE=33 / BORDER_COLOR=34 与本文件
#      其它常量一起对得上同一份文档，可以互相印证。）
#    值语义：pvAttribute 指向 **BOOL**，TRUE = 强制禁用过渡，FALSE = 恢复。
# ⚠️ 这是**逐窗口**（per-window）属性：只影响我们这一个 hwnd，不写注册表、不改
#   SystemParametersInfo 的全局"视觉效果"，所以不会影响系统里其它程序（不像
#    SPI_SETANIMATION 那样一刀切全局）。Win8 及更早不支持会返回失败 —— 那种情况下
#    我们只记日志、不抛异常，窗口照常用它自己那套动画。
DWMWA_TRANSITIONS_FORCEDISABLED = 3
# Win11 圆角档位（DWMWCP_*）
DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3
# DwmSetWindowAttribute 的 HRESULT：S_OK
S_OK = 0

# ---------- 全屏专用（win32.py 里没有这几个） ----------
SW_SHOW = 5
SW_RESTORE = 9
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
VK_F11 = 0x7A

# ---------- 页面底色（四角/顶边"白边/黑边"的唯一色源） ----------
# ⚠️ 必须和 `webui/css/variables.css` 的 `--page` 一致：
#      深色 --page: #1c1c1c   → (0x1C, 0x1C, 0x1C)
#      浅色 --page: #f3f4f7   → (0xF3, 0xF4, 0xF7)
#    为什么重要：frameless 窗口的**四角圆弧外**、以及 DWM 给窗口画的 1px 边框，
#    露出来的就是 WinForms Form 的 BackColor / DWM 边框色。它们一旦和页面底色不一致，
#    浅色主题下看到白边、深色主题下看到黑边 —— 就是用户说的"四角/顶部有时出现白边或黑边"。
PAGE_BG_DARK = (0x1C, 0x1C, 0x1C)
PAGE_BG_LIGHT = (0xF3, 0xF4, 0xF7)
# 顶部 6px 是窗口拉伸留出的父窗口区域；它紧贴标题栏，颜色必须取标题栏的
# --page-2（深 #202020 / 浅 #eceef3），否则深色主题下会看到一条更黑的边。
PAGE_TOP_DARK = (0x23, 0x23, 0x23)
# 浅色标题栏实际是近白（毛玻璃叠白后的观感），不是 --page-2 的 #eceef3
PAGE_TOP_LIGHT = (0xFD, 0xFD, 0xFD)
# DWM 最外 1px 只能整圈同色；取页面底色与标题栏色的中间值，
# 使顶部/左右/底部的色差都只有 3~5 个色阶（看起来就是没有描边）。
#⚠️⚠️ 这两个值**必须启用**（曾经一度改成 DWMWA_COLOR_NONE = 不画描边，是错的）。
#    原因（实测）：pywebview 建窗时 `shadow=True` 会调
#    `DwmExtendFrameIntoClientArea(1,1,1,1)` —— 那 1px 非客户区被 DWM 当成玻璃，
#    **桌面颜色会从窗口边缘透进来**。实测（深色内容 #1C1C1C + 浅桌面 #F0F0F0）：
#        border = COLOR_NONE → 窗口最外 1px = (250,250,250) ≈ 桌面色 = 一圈**白边**
#        border = 本值       → 窗口最外 1px = (32,32,32)   = 与页面几乎同色 = 看不见
#    深色主题 + 浅桌面 → 白边；浅色主题 + 深桌面 → 黑边。底边两角因为对比最强，
#    就是"极小白角/黑角"的来源。所以这 1px 必须**画**，而且要画成接近页面底色的颜色。
PAGE_BORDER_DARK = (0x20, 0x20, 0x20)
PAGE_BORDER_LIGHT = (0xF8, 0xF8, 0xF8)


def page_background(dark: bool):
    """当前主题的页面底色 (r, g, b)（和 CSS `--page` 对齐）"""
    return PAGE_BG_DARK if dark else PAGE_BG_LIGHT


def page_top_background(dark: bool):
    """标题栏底色 (r, g, b)（和 CSS `--page-2` 对齐，用于顶部可拉伸留白）"""
    return PAGE_TOP_DARK if dark else PAGE_TOP_LIGHT


def _colorref(rgb) -> int:
    """(r, g, b) → COLORREF（DWM 边框色要的是 0x00BBGGRR，不是 RGB！）"""
    r, g, b = (max(0, min(255, int(v))) for v in rgb)
    return (b << 16) | (g << 8) | r


class _FrameState:
    """一个窗口的补丁状态（窗口过程需要一个永久引用，否则 Python 侧会被 GC 掉）"""

    __slots__ = ("hwnd", "old_proc", "proc", "fullscreen", "saved_rect", "saved_style",
                 "dark", "rounded", "transitions", "window", "page_bg", "border_key",
                 "inset_px", "padding_paint_handler",
                 "fullscreen_maximized", "fullscreen_topmost", "fullscreen_native")

    def __init__(self):
        self.hwnd = None
        self.old_proc = None
        self.proc = None
        self.fullscreen = False
        self.saved_rect = None
        self.saved_style = None
        self.dark = None
        self.rounded = None
        self.transitions = None          # None=未设置/设置失败 / True=动画已关 / False=动画已开
        # pywebview 的 Window 对象（由 shell 在 install() 时传进来）：要把 Form.BackColor /
        # WebView2.DefaultBackgroundColor 刷成页面底色，必须拿到它（WinForms 属性只能在
        # GUI 线程改）。⚠️ 只存引用，不在这里调用任何方法。
        self.window = None
        self.page_bg = None              # None/"dark"/"light"：最近一次刷成哪种页面底色
        self.border_key = None           # None/"dark"/"light"：DWM 边框色是按哪套主题设的
        self.inset_px = None             # WebView2 当前内缩的物理像素（见 _apply_resize_inset）
        self.padding_paint_handler = None  # 顶部拉伸留白的 Paint 处理器（防 GC）
        # 进全屏前的"原状"：退出时必须按它们还原（最大化过就还原成最大化，别把人家的
        # 窗口状态吃掉；之前是 TOPMOST 的也别顺手取消掉）
        self.fullscreen_maximized = False
        self.fullscreen_topmost = False
        self.fullscreen_native = False   # 本次全屏是不是靠 pywebview 原生 toggle 实现的

    def reset_derived(self):
        """换窗口（或窗口刚创建）时清掉"已应用"缓存
        ⚠️ 必须清：这些字段是"DWM 属性已经设过了"的记忆。如果 hwnd 变了还留着旧记忆，
           新窗口就永远等不到那三次 DwmSetWindowAttribute（表现为新窗口没圆角、动画又回来了）。
        """
        self.dark = None
        self.rounded = None
        self.transitions = None
        self.page_bg = None
        self.border_key = None
        self.inset_px = None


_state = _FrameState()
_lock = threading.RLock()


# ============ 命中测试 / 最大化范围（客户端脚本也会问到这些） ============

def hit_test(hwnd, x: int, y: int) -> int:
    """屏幕坐标 → 命中区（给前端/自检用的查询入口，和窗口过程用的是同一套算法）
    ⚠️ 内部直接复用 `border_hit_test()`：两处如果各写一份，必然出现
       "探针说四角有热区、真机却拖不动"这种对不上的情况。
    """
    try:
        return border_hit_test(hwnd, x, y)
    except Exception:
        return HTCLIENT


def _apply_minmax(hwnd, lparam):
    """把最大化尺寸/位置钉到当前显示器的工作区（不放大的话会盖住任务栏）"""
    try:
        info = ctypes.cast(lparam, ctypes.POINTER(MINMAXINFO)).contents
        mleft, mtop, mright, mbottom = win32.work_area(hwnd)
        # 工作区是屏幕坐标；WM_GETMINMAXINFO 用的是**显示器坐标**（多屏时相对该显示器左上角）
        # 用 MonitorFromWindow 拿到显示器的 rcMonitor 再换算。
        try:
            hmon = win32.user32.MonitorFromWindow(hwnd, 2)
            mi = win32.MONITORINFO()
            mi.cbSize = ctypes.sizeof(win32.MONITORINFO)
            if hmon and win32.user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                mon_left, mon_top = mi.rcMonitor.left, mi.rcMonitor.top
            else:
                mon_left, mon_top = 0, 0
        except Exception:
            mon_left, mon_top = 0, 0
        info.ptMaxPosition.x = mleft - mon_left
        info.ptMaxPosition.y = mtop - mon_top
        info.ptMaxSize.x = mright - mleft
        info.ptMaxSize.y = mbottom - mtop
        # 拖拽/双击还原时也不能超过工作区
        info.ptMaxTrackSize.x = max(info.ptMaxTrackSize.x, mright - mleft)
        info.ptMaxTrackSize.y = max(info.ptMaxTrackSize.y, mbottom - mtop)
    except Exception:
        pass


def _lparam_screen_point(lparam: int):
    """WM_NCHITTEST 的 lParam → (屏幕 x, 屏幕 y)（低 16 位 x、高 16 位 y，有符号）"""
    return (ctypes.c_short(lparam & 0xFFFF).value,
            ctypes.c_short((lparam >> 16) & 0xFFFF).value)


# 可拉伸边框的**逻辑像素**宽度（会按窗口 DPI 放大）。
#当前 = 0（不用"内缩 WebView2 留出边框带"的方案）：
#   旧方案为了让 WM_NCHITTEST 落到父窗口，把 WebView2 内缩 6px，于是窗口四周必然出现
#   一条 6px 的父窗口底色带。顶部带要画成标题栏色、左右带要画成页面/侧栏色，而标题栏
#   在毛玻璃/亚克力档下是半透明+渐变，**任何纯色都匹配不上** —— 现象就是
#   "四周白边/黑边、还加粗了"。
#   现在的做法：WebView2 铺满整个窗口（没有色带），缩放由前端在窗口边缘放 8 个不可见热区，
#   按下时调 `window.start_resize` → `start_resize()`（ReleaseCapture + WM_NCLBUTTONDOWN，
#   和标题栏拖动同一套系统模态循环）。既没有可视边框，也保留原生缩放手感。
RESIZE_INSET = 0


def resize_inset(hwnd: int) -> int:
    """当前窗口应让出的可拉伸边框宽度（物理像素）；最大化/全屏时为 0
    ⚠️ 最大化/全屏**不能留**拉伸边：否则在屏幕边缘拖拽会把窗口拽出全屏状态，
       而且最大化时四边贴屏幕边缘，多出来的热区会抢走任务栏附近的点击。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return 0
    if _state.fullscreen:
        return 0
    try:
        if win32.user32.IsZoomed(hwnd):
            return 0
    except Exception:
        pass
    try:
        scale = float(win32.dpi_scale(hwnd) or 1.0)
    except Exception:
        scale = 1.0
    width = int(round(RESIZE_INSET * scale))
    return max(2, width) if width > 0 else 0


def border_hit_test(hwnd: int, x: int, y: int, inset: int = 0) -> int:
    """屏幕坐标 → 边框命中码（HTLEFT/HTTOPLEFT/… / HTCLIENT）
    ========== 这是窗口不能拉伸的修复核心 ==========
    无边框窗口加了 WS_THICKFRAME 之后，**系统的边框已经被 WM_NCCALCSIZE 吃掉了**
    （客户区 = 整个窗口），而 WebView2 控件是 Dock=Fill 的真实子窗口、铺满客户区
    （它内部还有跨进程的 Chromium 子窗口）。鼠标落在边缘时，系统的 WM_NCHITTEST
    发给的是**最上层子窗口**（WebView2/Chromium，跨进程、我们改不了），父窗口收不到，
    因此永远得不到 HTLEFT/HTTOP，拖边功能失效。
    修法：用 `Form.Padding` 把 WebView2 从窗口边缘**内缩** RESIZE_INSET 像素
    （见 `_apply_resize_inset`），让出的一圈属于父窗口客户区 → WM_NCHITTEST 发给父窗口
    → 本函数在四边/四角返回对应的 HT* → 系统进入原生拉伸流程。
    ⚠️ 四角优先于四边（先判角）；只有在窗口处于普通状态时才给拉伸热区。
    ⚠️ **不要**返回 HTCAPTION：标题栏拖动由前端 `start_drag()` 驱动，
       在这里抢成 HTCAPTION 会让标题栏上的按钮点不动。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return HTCLIENT
    if inset:
        bw = int(inset)
    else:
        # 以**实际让出的宽度**为准（见 _apply_resize_inset 的回读）：
        # WinForms 开了 AutoScaleMode.Dpi，Padding 有可能被再缩放一次；热区绝不能被判得
        # 比真正的空白带还宽（否则会把点击从页面上抢走），所以取两者较小值。
        state_px = resize_inset(hwnd)                # 0 = 最大化/全屏，不留热区
        if state_px <= 0:
            return HTCLIENT
        applied = _state.inset_px
        bw = state_px if not applied else max(2, min(int(applied), state_px))
    if bw <= 0:
        return HTCLIENT
    try:
        left, top, right, bottom = win32.rect_of(hwnd)
    except Exception:
        return HTCLIENT
    # 点在窗口外（系统偶尔会问）：明确返回"不在本窗口"
    if x < left or x >= right or y < top or y >= bottom:
        return HTNOWHERE
    near_left = x < left + bw
    near_right = x >= right - bw
    near_top = y < top + bw
    near_bottom = y >= bottom - bw
    if near_top and near_left:
        return HTTOPLEFT
    if near_top and near_right:
        return HTTOPRIGHT
    if near_bottom and near_left:
        return HTBOTTOMLEFT
    if near_bottom and near_right:
        return HTBOTTOMRIGHT
    if near_left:
        return HTLEFT
    if near_right:
        return HTRIGHT
    if near_top:
        return HTTOP
    if near_bottom:
        return HTBOTTOM
    return HTCLIENT


def _make_proc():
    @wndproc_guard
    def proc(hwnd, msg, wparam, lparam):
        state = _state
        if msg == WM_NCHITTEST:
            # 四条边 + 四个角都走自己的命中测试（系统默认的边框已被 NCCALCSIZE 吃掉，
            # 不能再指望 DefWindowProc 给出 HTLEFT 之类的结果）。
            # 全屏时 resize_inset() 返回 0 → 整块都是 HTCLIENT，不会把全屏窗口拽小。
            px, py = _lparam_screen_point(lparam)
            return border_hit_test(hwnd, px, py)
        if msg == WM_NCCALCSIZE:
            # wParam=TRUE：lParam 是 NCCALCSIZE_PARAMS，客户区自己算
            if wparam:
                if not state.fullscreen and not win32.user32.IsZoomed(hwnd):
                    # 让客户区仍让出一点点做系统阴影/圆角的视觉余量？
                    # ⚠️ 不：原版是"无边框 + 完全铺满"，让出余量会看到一圈透明缝。
                    pass
                return 0
            return 0
        if msg == WM_GETMINMAXINFO and not state.fullscreen:
            _apply_minmax(hwnd, lparam)
            return 0
        if state.old_proc:
            return win32.user32.CallWindowProcW(state.old_proc, hwnd, msg, wparam, lparam)
        return win32.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    return WNDPROC(proc)


# ============ 对外 API ============

def install(hwnd: int, dark: bool = False, window=None) -> bool:
    """给无边框窗口打补丁（幂等；必须在窗口 Handle 已创建之后调用）
    返回是否成功。失败时窗口仍可用，只是不能拖边缩放。
    `window`（pywebview 的 Window）可选：传进来之后本层就能把 Form.BackColor /
    WebView2.DefaultBackgroundColor 刷成页面底色（见 `_refresh_page_background`），
    否则只能刷 DWM 那部分属性、四角底色仍可能和页面不一致。
    ⚠️ 这里的 `SetWindowPos(SWP_FRAMECHANGED)` **不会**把隐藏窗口显示出来
       （没带 SWP_SHOWWINDOW；探针 install_keeps_hidden 实测 visible 保持 false），
       所以它可以在 ready 之前的 `_wait_for_window` 里安全调用。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return False
    with _lock:
        try:
            if window is not None:
                _state.window = window
            # ⚠️ 顺序不能反：必须**先**子类化窗口过程，**再**改样式并让系统重算非客户区。
            #    反过来的话，系统是在"老窗口过程"上算的 NCCALCSIZE，会老老实实留出一圈
            #    7px 边框（实测 gap=(14,14)），要等到下一次 SetWindowPos(FRAMECHANGED)
            #    走新过程才收敛成 0 —— 表现出来就是"窗口四周有一圈黑边"。
            if _state.hwnd != hwnd or _state.proc is None:
                if _state.hwnd and _state.hwnd != hwnd and _state.old_proc:
                    # 换窗口了：把旧窗口的过程还原（一般不会发生，防御式处理）
                    try:
                        win32.user32.SetWindowLongPtrW(
                            _state.hwnd, GWLP_WNDPROC, _state.old_proc)
                    except Exception:
                        pass
                _state.hwnd = hwnd
                _state.reset_derived()          # ⚠️ 换了 hwnd 就得忘掉"已设过"的记忆
                _state.proc = _make_proc()
                _state.old_proc = win32.user32.SetWindowLongPtrW(
                    hwnd, GWLP_WNDPROC, ctypes.cast(_state.proc, ctypes.c_void_p))

            style = win32.user32.GetWindowLongW(hwnd, GWL_STYLE)
            style = (style & 0xFFFFFFFF)
            new_style = (style | WS_THICKFRAME | WS_SYSMENU
                         | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
            if new_style != style:
                win32.user32.SetWindowLongW(hwnd, GWL_STYLE, ctypes.c_long(new_style))
            win32.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                      SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER
                                      | SWP_FRAMECHANGED | SWP_NOACTIVATE)
            apply_dark(dark)
            # 让出可拉伸的边框带（WebView2 内缩，见 _apply_resize_inset 的说明）
            _apply_resize_inset(force=True)
            # ⚠️ force=True：install() 会被调多次（等待句柄那次 + show 之前那次），
            #    而"第一次可能在窗口还没被 DWM 接管时失败"。带 force 的重放保证只要有一次
            #    成功就真的设上了（缓存只在返回 S_OK 时才写，见 disable_transitions）。
            disable_transitions(True, force=True)
            return True
        except Exception:
            return False


def disable_transitions(disabled: bool = True, force: bool = False) -> bool:
    """关闭 / 恢复**本窗口**的 DWM 过渡动画（逐窗口属性，不影响别的程序）
    需求："Win11 下最小化 / 最大化 / 全屏 / 关闭的窗口动画太过度，要像 Win10 一样干脆"。
    做法：`DwmSetWindowAttribute(DWMWA_TRANSITIONS_FORCEDISABLED)`（属性号 3，见文件顶部注释）。
    它是**逐窗口**属性：不写注册表、不动系统"视觉效果"，系统里其它程序的动画完全不受影响。
    ⚠️ 只在 `DwmSetWindowAttribute` 真的返回 S_OK 时才更新 `_state.transitions` 缓存：
       Win8 及更早不支持这个属性，会返回 E_INVALIDARG；窗口在 DWM 接管之前调用也可能失败。
       缓存写早了就等于"以后再也不重试"，动画会一直留着。
    ⚠️ `force=True`：即使缓存说已经设过也再发一次（最大化/还原/全屏进出/首次显示之后用）。
       不是多余的 —— 这几条路径会触发 DWM 重建窗口表面，重放一次可以确保属性仍然生效。
    ⚠️ 任何失败都只记日志、绝不向上抛（调用点包括窗口过程与退出流程）。
    """
    if not win32.IS_WINDOWS or not _state.hwnd:
        return False
    want = bool(disabled)
    if _state.transitions == want and not force:
        return True
    try:
        value = ctypes.c_int(1 if want else 0)
        result = int(win32.dwmapi.DwmSetWindowAttribute(
            _state.hwnd, DWMWA_TRANSITIONS_FORCEDISABLED,
            ctypes.byref(value), ctypes.sizeof(value)))
        if result != S_OK:
            # 失败不写缓存（保留 None/旧值），下次还有机会重试
            _log("warn", "外壳", "frame",
                 f"关闭窗口过渡动画失败（DwmSetWindowAttribute hr=0x{result & 0xFFFFFFFF:08X}），"
                 f"窗口保留系统默认动画")
            return False
        _state.transitions = want
        return True
    except Exception as exc:                                       # noqa: BLE001
        _log("warn", "外壳", "frame", f"关闭窗口过渡动画异常（已跳过）: {exc}")
        return False


def _log(level: str, category_zh: str, category_en: str, message: str):
    """frame 层自己的日志出口（失败也不许影响窗口逻辑）"""
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)(category_zh, category_en, message)
    except Exception:
        pass


def refresh_window_attrs():
    """重放本窗口的 DWM 属性（圆角/边框色 + 过渡动画）
    在"窗口状态刚变过"的路径上调用：最大化 / 还原 / 进全屏 / 退全屏 / 窗口第一次显示。
    这类动作会让 DWM 重建窗口表面，重放一次最保险；`disable_transitions(force=True)`
    即使缓存命中也会再发一次 DwmSetWindowAttribute。
    同时把 Form / WebView2 的底色再刷一遍（见 `_refresh_page_background`）：窗口显示、
    换主题之后四角露出来的那一圈颜色必须和页面一致。
    """
    _update_corner(force=True)
    disable_transitions(True, force=True)
    _refresh_page_background(force=True)
    # 最大化/还原/全屏会改变"能不能拉伸"，内缩边距要跟着状态走
    _apply_resize_inset(force=True)


def _schedule_attr_refresh(delays=(0.05, 0.25, 0.60)):
    """状态切换后延迟重放几次（异步、daemon、异常吞掉）
    ⚠️ 用 daemon 线程：`threading.Timer` 默认是**非 daemon**，退出时会把进程多拖住几百毫秒。
    ⚠️ 不用"等 180ms 再 _update_corner"那种单拍：SC_MAXIMIZE/SC_RESTORE 是异步命令，
       系统什么时候真正完成窗口状态切换并不确定，多拍重放比赌一个固定延迟稳。
    """
    for delay in delays:
        try:
            timer = threading.Timer(delay, _safe_refresh)
            timer.daemon = True
            timer.start()
        except Exception:
            pass


def _safe_refresh():
    try:
        refresh_window_attrs()
    except Exception:
        pass


def _install_padding_paint(native):
    """在 Form 的顶部拉伸留白上画出标题栏同色，避免出现一条更黑的边
    ⚠️ WebView2 内缩后，最外一圈是父窗口的 padding 区，Form 只能给整圈一个
       BackColor（页面底色）。顶部这 6px 紧贴标题栏（--page-2），如果也用页面底色，
       深色主题下会看到一条比标题栏更黑的横边、浅色主题下偏灰 —— 这正是用户说的
       窗口四周都是白边/黑边、还加粗了。这里只补最顶部一条，左右/底部仍由
       BackColor（页面底色）自然衔接，视觉上边框带就消失了。
    ⚠️ 处理器必须挂在 _state 上保活；主题变化时 Invalidate 重画即可。
    """
    if native is None:
        return
    if _state.padding_paint_handler is not None:
        return
    try:
        from System import EventHandler
    except Exception:
        return

    def _on_paint(sender, event):
        try:
            pad = int(getattr(native, "Padding").Top or 0)
            if pad <= 0:
                return
            from System.Drawing import Color, Rectangle, SolidBrush
            rgb = page_top_background(bool(_state.dark))
            brush = SolidBrush(Color.FromArgb(255, rgb[0], rgb[1], rgb[2]))
            try:
                width = int(native.ClientSize.Width)
                event.Graphics.FillRectangle(brush, Rectangle(0, 0, width, pad))
            finally:
                brush.Dispose()
        except Exception:
            pass

    try:
        handler = EventHandler(_on_paint)
        native.Paint += handler
        _state.padding_paint_handler = handler
    except Exception:
        _state.padding_paint_handler = None


def _refresh_page_background(force: bool = False) -> bool:
    """把 Form.BackColor / WebView2.DefaultBackgroundColor 刷成**页面底色**
    ========== 为什么需要（四角/顶部出现白边或黑边）==========
    frameless 窗口的四个圆角外、以及窗口被 DWM 重新合成的那 1px 边缘，露出来的是：
      · WinForms Form 的 `BackColor`（建窗时 pywebview 用 create_window 的
        `background_color` 写死成 #16181D）；
      · WebView2 控件的 `DefaultBackgroundColor`（同上）。
    程序默认是深色主题，所以深色下"看不出来"；一旦切到浅色主题，这层深色底就从
    四角和顶边透出来 = 用户说的"白/黑边"（取决于当时主题与页面底色的偏差方向）。
    ========== 圆角启用后这里还多了一件必须做的事 ==========
    恢复圆角之后，"页面底色"这个值同时出现在**三个地方**，必须永远一致：
      ① Form.BackColor                  —— 窗口最外那一圈的底色
      ② WebView2.DefaultBackgroundColor —— WebView2 自己的底色（0px 内缩时露不出来，
                                            但保底）
      ③ DWM 描边色 `DWMWA_BORDER_COLOR` —— 盖住 pywebview `shadow=True` 留下的
                                            那 1px 玻璃条（= 白边/黑边的来源，
                                            见 `_update_corner` 的说明）
    ①② 取 `page_background(dark)`（= CSS 的 `--page`），③ 取与之相差 3~5 个色阶的
    `PAGE_BORDER_*`（中间值）—— 两者刻意不同：③ 要同时贴近标题栏色。
    ⚠️ 主题切换时（`apply_dark`）三处都要跟着换：`apply_dark` 里
       `_update_corner(force=True)`（换描边色）+ `_refresh_page_background(force=True)`
       （换 Form/WebView2 底色）**成对**调用，别只改一个。
    两个属性都是 WinForms 控件属性 → **只能在创建窗口的 GUI 线程上改**（走 on_gui_thread）。
    任何失败只记日志：颜色不完美也不会影响窗口可用性。
    """
    window = _state.window
    if window is None or not _state.hwnd:
        return False
    dark = bool(_state.dark)
    key = "dark" if dark else "light"
    changed = _state.page_bg != key
    if not force and not changed:
        return True
    rgb = page_background(dark)
    result = {"ok": False, "error": ""}

    def _apply():
        try:
            from System.Drawing import Color
            # ⚠️ GDI+ 的 Color.FromArgb 参数顺序是 (A, R, G, B)
            color = Color.FromArgb(255, rgb[0], rgb[1], rgb[2])
            native = getattr(window, "native", None)
            if native is None:
                result["error"] = "未取得 WinForms 窗口对象"
                return
            # 顶部可拉伸留白：画出标题栏同色，避免深色主题下出现一条更黑的边
            _install_padding_paint(native)
            try:
                native.BackColor = color
            except Exception as exc:                      # noqa: BLE001
                result["error"] = f"BackColor: {exc}"
            try:
                native.Invalidate()
            except Exception:
                pass
            webview = getattr(native, "webview", None)
            if webview is not None:
                try:
                    webview.DefaultBackgroundColor = color
                except Exception as exc:                  # noqa: BLE001
                    result["error"] = (result["error"] + f" DefaultBackgroundColor: {exc}").strip()
            result["ok"] = True
        except Exception as exc:                          # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"

    try:
        on_gui_thread(window, _apply, timeout=2.0)
    except Exception as exc:                              # noqa: BLE001
        result["error"] = result["error"] or str(exc)
    if not result["ok"]:
        _log("warn", "外壳", "frame",
             f"刷新窗口底色失败（四角可能与页面有色差）: {result['error']}")
        return False
    _state.page_bg = key
    if changed:
        # ⚠️ 只在**主题真的变了**时记一条：这个方法会被"最大化/还原/全屏"的多拍重放反复调用，
        #    每次都记 INFO 会在一次窗口操作里刷出 3 条重复日志。
        # DWM 描边不是 COLOR_NONE，而是**中间值**（盖住圆角最外那 1px 玻璃条）。
        _log("info", "外壳", "frame",
             f"窗口底色已按主题刷新: 主题={key} "
             f"页面底色=#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X} "
             f"DWM 描边=#{_colorref(PAGE_BORDER_DARK if dark else PAGE_BORDER_LIGHT):06X}"
             f"（盖住窗口最外 1px 的玻璃条，消除白边/黑边）")
    return True


def _apply_resize_inset(force: bool = False) -> bool:
    """按当前窗口状态把 **WebView2 控件内缩**出可拉伸的边框带（GUI 线程执行）
    ========== 为什么要内缩（窗口不能拉伸的根因）==========
    无边框窗口把 WS_THICKFRAME 加回来、又用 WM_NCCALCSIZE 把系统边框吃掉之后，
    客户区 = 整个窗口；而 WebView2 是 Dock=Fill 的真实子窗口，铺满整个客户区
    （内部还有跨进程的 Chromium 子窗口）。鼠标落在边缘时 WM_NCHITTEST 发给的是
    最上层子窗口（跨进程，无法改），父窗口根本收不到 → 拖边/拖角全部失效。
    把 WebView2 内缩 RESIZE_INSET 像素后，最外一圈属于父窗口客户区，
    WM_NCHITTEST 才会发给父窗口 → `border_hit_test()` 返回 HTLEFT/… → 系统原生拉伸。
    ⚠️ 最大化/全屏时内缩必须是 0（`resize_inset()` 返回 0）：内容要铺满屏，
       同时避免屏幕边缘多出一圈拉伸热区。
    ⚠️ 用 Form.Padding 而不是改 WebView2 的 Bounds：Padding 对 Dock=Fill 的子控件
       自动生效，窗口尺寸变化时不需要额外处理 Resize 事件。
    ⚠️ 幂等 + 结果缓存：同一个内缩值不重复设置（避免每次调用都触发一次布局）。
    """
    window = _state.window
    hwnd = _state.hwnd
    if window is None or not hwnd:
        return False
    px = int(resize_inset(hwnd) or 0)
    changed = _state.inset_px != px
    if not force and not changed:
        return True
    result = {"ok": False, "error": "", "actual": px}

    def _apply():
        try:
            from System.Windows.Forms import Padding
            native = getattr(window, "native", None)
            if native is None:
                result["error"] = "未取得 WinForms 窗口对象"
                return
            native.Padding = Padding(px, px, px, px)
            # 回读实际生效的边距：Form 的 AutoScaleMode=Dpi 可能在 DPI 变化时二次缩放
            # （热区按实际值算才不会越过空白带把页面点击抢走）。
            try:
                pad = native.Padding
                actual = min(int(pad.Left), int(pad.Top), int(pad.Right), int(pad.Bottom))
            except Exception:
                actual = px
            result["ok"] = True
            result["actual"] = max(0, int(actual))
        except Exception as exc:                          # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"

    try:
        on_gui_thread(window, _apply, timeout=2.0)
    except Exception as exc:                              # noqa: BLE001
        result["error"] = result["error"] or str(exc)
    if not result["ok"]:
        _log("warn", "外壳", "frame",
             f"设置窗口拉伸边距失败（边缘拖拽可能无效）: {result['error']}")
        return False
    actual = int(result.get("actual") or px)
    _state.inset_px = actual
    if changed or actual != px:
        # 同上：只有"能不能拉伸"真的变了才记一条（最大化/还原/全屏各一条）
        if px > 0:
            _log("info", "外壳", "frame",
                 f"窗口拉伸边距已更新: {actual}px（四边四角可拖拽缩放）")
        else:
            # 内容铺满窗口（0px 内缩），缩放交给前端边缘热区
            _log("info", "外壳", "frame",
                 "窗口内容铺满（0px 内缩），缩放由前端边缘热区调用 window.start_resize 完成")
    return True


def apply_dark(dark: bool):
    """Win11 圆角 + 边框色 + 页面底色 跟随主题（DWM 在 Win10 上会静默失败，不影响功能）
    ⚠️ 换主题时**三处颜色必须一起换**，否则圆角会露馅：
       · `DWMWA_BORDER_COLOR`（描边色 = `PAGE_BORDER_*`，盖住窗口最外那 1px 玻璃条）
       · `Form.BackColor`（= `page_background(dark)`）
       · `WebView2.DefaultBackgroundColor`（= `page_background(dark)`）
       前两个由下面这两行成对完成（`_update_corner` 换描边色 + `_refresh_page_background`
       换 Form/WebView2 底色）；三处都随主题走，不会出现"换了主题角上还是旧色"。
    """
    if not win32.IS_WINDOWS or not _state.hwnd:
        return
    if _state.dark is dark:
        return
    _state.dark = bool(dark)
    try:
        value = ctypes.c_int(1 if dark else 0)
        win32.dwmapi.DwmSetWindowAttribute(
            _state.hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass
    _update_corner(force=True)      # 换主题：描边色也变了，必须绕过缓存重设
    _refresh_page_background(force=True)


def _update_corner(force: bool = False):
    """窗口圆角策略 + DWM 描边（圆润角，并且必须同时消掉白角/黑角）
    ========== 背景：为什么不能只把 DONOTROUND 换成 ROUND ==========
    曾用 `DWMWCP_DONOTROUND`（统一方角）关掉圆角，理由是"DWM 圆角的 AA 边缘会和桌面
    背景半透明混合，在窗口底边两角产生渐暗/渐亮的小角（'极小白角/黑角'）"。
    需求是圆润角，所以**不能**只把 DONOTROUND 换成 ROUND
    （那会把老 bug 原样带回来），必须把"白角/黑角到底是什么"搞清楚并真正消掉。
    ========== 实测结论（ctypes 复刻真实窗口构造 + 逐像素截图）==========
    白角/黑角其实是**两件不同的事**，之前被混成一件了：
    ① **窗口最外那 1px 的"玻璃条"（真·白边/黑边，实测到的就是它）**
       pywebview 建窗时 `shadow=True` 会调 `DwmExtendFrameIntoClientArea(1,1,1,1)`
       —— 那 1px 非客户区被 DWM 当成玻璃，于是**桌面颜色从窗口边缘透进来**。
       实测（内容 #1C1C1C 深色 + 桌面 #F0F0F0 浅色）：
           最外 1px = (250,250,250)  ← 几乎是桌面色 ⇒ 一圈**白边**
       深色主题 + 浅桌面 → 白边；浅色主题 + 深桌面 → 黑边。而且它是**整圈**的
       （顶边/左边/右边/底边都有），底边那两角因为内容最深、最贴近浅桌面，
       对比最强 ⇒ 用户看到的就是"底边两角的白角/黑角"。
       ⚠️ 这层玻璃条跟 Form.BackColor / WebView2 底色**无关**，
          所以"把底色刷成页面底色"消不掉它（当初按"底色不对"去修，判断方向本来就对不上号）。
    ② **圆角弧线本身**：DWM 把窗口按圆角裁切，弧线**外面**那几像素是**桌面**
       （实测：父窗口刷蓝、子窗口刷品红，弧外仍是桌面灰 123,123,123 —— 不是
       Form.BackColor）。这是圆角的正常表现，Win11 原生应用也是这样，
       **不是 bug，也不该去动它**。
    ========== 解法（两条一起上）==========
    ① **圆角**：还原/普通状态用 `DWMWCP_ROUND`（Win11 风格的大圆角）。
    ② **白角/黑角**：把 `DWMWA_BORDER_COLOR` 从 COLOR_NONE 改成 `PAGE_BORDER_*`
       （页面底色与标题栏色的中间值：深 #202020 / 浅 #F8F8F8）。
       DWM 画的那 1px 描边正好落在**玻璃条那一行**上 —— 描边色一给，
       那一行就不再是"桌面透进来的玻璃"，而是接近页面底色的颜色：
           实测（内容 #1C1C1C 深色 + 桌面 #F0F0F0 浅色）：
               border=NONE      → 最外 1px = (250,250,250)（= 桌面色，一圈白边）
               border=描边色     → 最外 1px = (32,32,32)（= 描边色，看不见）
       窗口最外那一圈本来就是页面底色（网页 body 底色 = --page），
       所以描一圈几乎同色 = **看不见**，白边/黑边同时消失。
       ⚠️ 描边是**整圈**生效的：顶部那一行会压在标题栏上。取中间值后
          顶部/左右/底部的色差都只有 3~5 个色阶（看起来就是没有描边）——
          这正是 PAGE_BORDER_DARK / PAGE_BORDER_LIGHT 这两个常量当初的用途，
          别再改回 COLOR_NONE。
    ========== 最大化 / 全屏（两条路径不一样，别混）==========
    ⚠️ **最大化**（`IsZoomed`）：DWM 会**自动忽略**圆角（贴边必须是方角），
       实测在最大化状态下重发 ROUND 也**不会**给最大化窗口加圆角
       ⇒ 不需要我们自己判断最大化状态。
    ⚠️ **全屏**：⚠️ 全屏是本层自己用 `SetWindowPos` 铺满显示器的（**不是**最大化，
       `IsZoomed` 仍是 False），DWM **不会**自动去圆角 —— 实测全屏下重发 ROUND
       圆角还在 ⇒ 全屏时必须**显式**发 DONOTROUND，否则屏幕四角会露出四个
       圆角缺口（内容被裁掉、露出桌面）。本函数用 `_state.fullscreen` 判断。
       ⚠️ 顺序：`enter_fullscreen()` 是**先**设 `_state.fullscreen` **再**调
          `_update_corner()`；`exit_fullscreen()` 是**先**清 `_state.fullscreen`
          **再**重发 —— 顺序对的，别改反。
    ⚠️ `force=True` 时**绕过缓存**：最大化/还原/全屏进出会让 DWM 重建窗口表面，
       圆角属性会被丢掉；而 `_state.rounded` 仍记着旧值，不加 force 就永远不会重发
       —— 表现就是"有时候四个角的圆角不对/变成直角"。这条路径由
       `refresh_window_attrs()` 在多拍重放里调用。
    """
    if not win32.IS_WINDOWS or not _state.hwnd:
        return
    try:
        dark = bool(_state.dark)
        dark_key = "dark" if dark else "light"
        # 普通/还原状态 = 圆润角（DWMWCP_ROUND，Win11 风格大圆角）。
        #   全屏时用 DONOTROUND：全屏是本层自己 SetWindowPos 铺满显示器的，
        #   不是最大化，DWM 不会自动去圆角（见函数头最大化/全屏段）。
        want = DWMWCP_DONOTROUND if _state.fullscreen else DWMWCP_ROUND
        # 圆角和边框色是两件事：边框色只跟主题走，所以两个缓存都要看
        if not force and _state.rounded == want and _state.border_key == dark_key:
            return
        pref = ctypes.c_int(want)
        win32.dwmapi.DwmSetWindowAttribute(
            _state.hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(pref), ctypes.sizeof(pref))
        # 描边用"页面底色与标题栏色的中间值"（PAGE_BORDER_*），不用 COLOR_NONE。
        #   它盖住的正是 pywebview `shadow=True` 留下的那 1px 玻璃条 —— 那才是白边/黑边
        #   的真正来源（实测：border=NONE 时最外 1px = 桌面色 ≈ (250,250,250) = 白边；
        #   给了描边色后最外 1px = 描边色，白边消失）。
        #   ⚠️ 取中间值而不是纯页面底色：DWM 最外 1px 只能整圈同色，而这一圈
        #      上面接标题栏（深 ≈ #202020 / 浅 ≈ #FFFFFF）、其余三面接页面底色
        #      （深 #1C1C1C / 浅 #F3F4F7）。取中间值后四条边的色差都只有 3~5 个
        #      色阶（看起来就是没有描边），取纯页面底色则顶部会多一条略深的线。
        #      这两个常量的原始注释就是这么写的，别改回 COLOR_NONE。
        border = ctypes.c_uint(_colorref(PAGE_BORDER_DARK if dark else PAGE_BORDER_LIGHT))
        win32.dwmapi.DwmSetWindowAttribute(
            _state.hwnd, DWMWA_BORDER_COLOR,
            ctypes.byref(border), ctypes.sizeof(border))
        _state.rounded = want
        _state.border_key = dark_key
    except Exception:
        pass


def refresh_corners():
    _update_corner()


# ---------- 拖动 / 最大化 / 最小化 / 关闭 ----------

# ⚠️ 必须在这里就定义好：`start_drag` 的 _drag() 闭包里**读**这个变量，
#    而 window=None 那条路（不走锁、不赋值）下如果它从来没被创建过，
#    读它就是 NameError —— 被 except 吞掉后表现为"拖动静默失效"。
_drag_token = 0
_drag_token_lock = threading.Lock()


def start_drag(hwnd: int, window=None, token=None) -> bool:
    """用系统原生"拖动标题栏"启动窗口拖动

    ⚠️ 必须在**创建窗口的那条 GUI 线程**上发：鼠标捕获挂在 WinForms 的 WebView2 子窗上，
       在别的工作线程里调 `ReleaseCapture()` 是**空操作**（它只释放调用线程自己的捕获），
       随后排队过去的 `WM_NCLBUTTONDOWN` 到达时用户往往已经松手 —— 这就是"窗口拖不动"的根因。
       现在走 `on_gui_thread()` 编组，并把当前光标坐标塞进 lParam（系统据此定位拖动起点）。

    ⚠️⚠️ 本轮新增 `token`（前端每次按下的自增号）：**过期的排队消息必须作废**。
       `on_gui_thread` 的 timeout 到点只是"调用方不再等"，那条闭包**仍会在稍后被
       GUI 线程执行**（BeginInvoke 的队列不清）。于是快速连点标题栏 / 上一次拖完
       消息才到位时，会补发一次 WM_NCLBUTTONDOWN —— 用户此刻**并没有按着鼠标**，
       系统却进入了一次"无主"的模态拖动：窗口跟着**鼠标移动**（哪怕没按键）跑，
       表现就是"窗口自己乱飘 / 往几个方向跳"。
       ⇒ 排队前先登记 token，真正执行时发现自己已经不是最新的一次就**直接放弃**。
    """
    global _drag_token
    if not win32.IS_WINDOWS or not hwnd:
        return False
    if token is not None:
        try:
            token = int(token)
        except (TypeError, ValueError):
            token = None
    my_token = token

    # ⚠️ 顺序很重要：**先登记 token，再决定怎么执行**。
    #    之前写成"只有走线程那条路才登记"，于是 window=None（同步执行）那条路
    #    永远拿着一个从未登记过的 token 去比 `_drag_token != my_token` → 第一次
    #    就判定"已过期"直接 return False ⇒ 那条路**彻底拖不动**（自己埋的坑）。
    if my_token is not None:
        with _drag_token_lock:
            _drag_token = my_token

    def _drag():
        # 过期检查：已经有更新的一次按下了 → 这条排队消息作废，
        # 否则它会在用户**没有按键**的时候补发一次模态拖动 = 窗口自己乱飘。
        if my_token is not None and _drag_token != my_token:
            return False
        try:
            win32.user32.ReleaseCapture()
            win32.user32.SendMessageW(hwnd, win32.WM_NCLBUTTONDOWN,
                                      win32.HTCAPTION, _cursor_lparam())
            return True
        except Exception:
            return False

    if window is None:
        return bool(_drag())
    # 另起一条线程去 **编组到 GUI 线程**：SendMessage 会一直阻塞到用户松开鼠标
    # （系统的模态拖动循环），直接在 js_api 的工作线程里等会把那次调用挂住整个会话。
    threading.Thread(
        target=lambda: on_gui_thread(window, _drag, timeout=1.0),
        name="ToolsGCP-drag", daemon=True).start()
    return True


def _cursor_lparam() -> int:
    """当前光标的 lParam 打包（低 16 位 x、高 16 位 y，屏幕坐标）"""
    try:
        pt = win32.POINT()
        win32.user32.GetCursorPos(ctypes.byref(pt))
        return (int(pt.y) & 0xFFFF) << 16 | (int(pt.x) & 0xFFFF)
    except Exception:
        return 0


# 前端边缘热区方向 → 系统命中码（和 WM_NCHITTEST 的返回值一致）
_RESIZE_DIRECTIONS = {
    "left": HTLEFT, "right": HTRIGHT, "top": HTTOP, "bottom": HTBOTTOM,
    "topleft": HTTOPLEFT, "topright": HTTOPRIGHT,
    "bottomleft": HTBOTTOMLEFT, "bottomright": HTBOTTOMRIGHT,
}


def start_resize(hwnd: int, window=None, direction: str = "") -> bool:
    """从前端的窗口边缘热区启动**系统原生缩放**
    为什么需要：WebView2 铺满整个窗口（没有内缩 6px 的边框带），鼠标永远落在 WebView2
    子窗口上，父窗口收不到 WM_NCHITTEST，`border_hit_test()` 那条原生边路就失效了。
    于是把"可缩放边缘"搬到页面里：8 个不可见的窄热区，按下时调这里。
    实现和 `start_drag()` 完全同一套（本机实测有效）：
      1. `ReleaseCapture()` 释放 WebView2 子窗口的鼠标捕获；
      2. 给**主窗口**发 `WM_NCLBUTTONDOWN`，wParam = HTLEFT/HTTOPLEFT/…，
         lParam = 当前光标屏幕坐标；
      3. 系统进入模态缩放循环，直到用户松开鼠标。
    ⚠️ 必须编组到 GUI 线程（跨线程 ReleaseCapture 是空操作），且 SendMessage 会阻塞到
       松开鼠标，所以必须放到后台线程里等，不能占住 js_api 工作线程。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return False
    code = _RESIZE_DIRECTIONS.get(str(direction or "").strip().lower())
    if code is None:
        return False

    def _resize():
        try:
            win32.user32.ReleaseCapture()
            win32.user32.SendMessageW(hwnd, win32.WM_NCLBUTTONDOWN, code, _cursor_lparam())
            return True
        except Exception:
            return False

    if window is None:
        return bool(_resize())
    threading.Thread(
        target=lambda: on_gui_thread(window, _resize, timeout=1.0),
        name="ToolsGCP-resize", daemon=True).start()
    return True


# ---------- 兜底拖动（绝对定位、坐标全部取自 Win32 物理像素） ----------
# ⚠️⚠️ 本轮重写的原因 = 用户报的「拖动一厘米，它往几个方向卡顿地移动好多
#    不同路径方向和距离」。旧写法有两个致命点：
#      ① **累加式不幂等**：`move_by()` 语义是"在当前值上 +dx"，而 js_api 是异步的 ——
#         只要有一条还在飞、下一条又发出去，"当前值"就不是发指令时以为的那个值；
#         后到的加在错误基线上，GUI 线程把顺序打乱时窗口还会往回/往旁边跳。
#      ② **前端给的像素单位不可信**：`screenX/screenY` 是 WebView2 视口里的 CSS 像素，
#         同时受 DPI 和**页面 ZoomFactor**（本项目非 1080p 会等比缩放，见 apply_page_zoom）
#         影响；而 `window.x/y` 是 WinForms 逻辑像素。两者不等时每一帧都按错误比例
#         累加一遍 → 窗口和鼠标越拖越脱开。上一轮我把这条通道和原生循环**同时**挂着
#         （以为原生接管后页面收不到 mousemove，实测是错的 —— WebView2 在系统模态
#         循环期间照常投递 DOM mousemove），两条一起搬 = 方向与距离全乱。
#    ⇒ 现在：主路径只留**原生那一条**（`start_drag`），本函数只在原生明确不可用时启用；
#      且所有坐标都从 Win32 取（GetCursorPos / GetWindowRect 都是物理像素，
#      物理像素之间做差不存在单位问题），只在最后一步除以 DPI 换成逻辑像素交给
#      `window.move()`（走 pywebview 正规通道，不绕开托管属性）。
_drag_lock = threading.Lock()
_drag_session = None


def drag_start(window) -> dict:
    """兜底拖动：记下起始窗口矩形 + 起始光标（都用**物理像素**），返回 {ok}"""
    global _drag_session
    hwnd = _drag_hwnd(window)
    if not win32.IS_WINDOWS or window is None or not hwnd:
        return {"ok": False, "error": "非 Windows 或窗口未就绪"}
    try:
        pt = win32.POINT()
        if not win32.user32.GetCursorPos(ctypes.byref(pt)):
            raise OSError("GetCursorPos 返回 False")
        rect = win32.RECT()
        if not win32.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise OSError("GetWindowRect 返回 False")
    except Exception as exc:                           # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    with _drag_lock:
        _drag_session = {"origin": (int(rect.left), int(rect.top)),
                         "cursor": (int(pt.x), int(pt.y))}
    return {"ok": True}


def drag_step(window) -> dict:
    """兜底拖动：按"起始矩形 + 光标总偏移"算目标位置（**幂等、抗乱序**）。

    目标 = 起始窗口左上角 + (当前光标 − 起始光标)。
    起始值只在 `drag_start` 写一次，所以同一帧发两遍、第 3 条比第 2 条先到，
    落点都完全一样 —— 不可能叠加出偏移，也不可能往回跳。
    前端只负责"报一声鼠标动了"，**不传任何坐标**：它那些 CSS 像素单位
    受 DPI 与页面缩放影响，写进坐标链就是本轮这个 bug 的一半来源。
    """
    hwnd = _drag_hwnd(window)
    if not win32.IS_WINDOWS or window is None or not hwnd:
        return {"ok": False, "moved": False, "error": "非 Windows 或窗口未就绪"}
    with _drag_lock:
        session = dict(_drag_session or {})
    if not session.get("origin") or not session.get("cursor"):
        return drag_start(window)          # 没起始值（比如启动时漏调）：就地补一次
    try:
        pt = win32.POINT()
        if not win32.user32.GetCursorPos(ctypes.byref(pt)):
            raise OSError("GetCursorPos 返回 False")
    except Exception as exc:                          # noqa: BLE001
        return {"ok": False, "moved": False, "error": str(exc)}
    start_x, start_y = session["origin"]
    base_cx, base_cy = session["cursor"]
    target_px = start_x + (int(pt.x) - base_cx)
    target_py = start_y + (int(pt.y) - base_cy)
    try:
        scale = float(win32.dpi_scale(hwnd)) or 1.0
    except Exception:                                 # noqa: BLE001
        scale = 1.0
    # ⚠️ 只换算**坐标**、不动尺寸：`window.move(x, y)` 是纯移动
    #    （webview/window.py:419 → platforms/winforms.py:620 `BrowserView.move`，
    #     内部带 SWP_NOSIZE，并把传进去的**逻辑像素**乘上它自己的 `self._scale`
    #     = GetDpiForWindow/96 换算成物理矩形）。
    #    所以我们这里必须先把物理像素**除以 DPI** 还原成逻辑像素 ——
    #    直接喂物理值会被 pywebview 再乘一次 scale，非 100% DPI 下窗口会越拖越偏。
    lx = int(round(target_px / scale))
    ly = int(round(target_py / scale))
    result = {"ok": False, "moved": False, "error": ""}

    def _move():
        try:
            # ⚠️ 用 pywebview 的 `window.move(x, y)`（webview/window.py:419）——
            #    它只收**坐标**、不带尺寸，内部 SetWindowPos 固定带 SWP_NOSIZE，
            #    且把自己收到的**逻辑像素**乘上 `self._scale` 换算成物理矩形。
            #    （这个包里**没有** `move_to` 这个方法，别凭印象写。）
            window.move(lx, ly)
            result["ok"] = True
            result["moved"] = True
        except Exception as exc:                      # noqa: BLE001
            result["error"] = "%s: %s" % (type(exc).__name__, exc)

    try:
        on_gui_thread(window, _move, timeout=0.5)
    except Exception as exc:                          # noqa: BLE001
        result["error"] = result["error"] or str(exc)
    return result


def drag_end(*_ignored) -> dict:
    """结束兜底拖动会话（前端 mouseup 调用；不调也不会错，下次按下会重置）"""
    global _drag_session
    with _drag_lock:
        _drag_session = None
    return {"ok": True}


def _drag_hwnd(window):
    """取窗口句柄。
    ⚠️ pywebview 的 Window **没有** `handle` 属性（本包里没有 def handle），
       所以走项目自己的 `hwnd_of_window()`（shell.hwnd() 也是这条），
       再退回模块状态里 install() 记下的那份。
    """
    hwnd = 0
    try:
        hwnd = int(hwnd_of_window(window) or 0)
    except Exception:                                  # noqa: BLE001
        hwnd = 0
    return hwnd or int(_state.hwnd or 0)


def move_by(window, dx: int, dy: int) -> bool:
    """按**增量**移动窗口（前端兜底拖动用；同样必须编组到 GUI 线程）
    ⚠️ 走 pywebview 的 `window.move()` 而不是裸 SetWindowPos：WinForms 的 Form.Location
       是托管属性，绕过它改原生位置会被下一次布局同步改回去（见 center_on_screen 的说明）。
    ⚠️⚠️ 但 `window.move()` 内部**没有** Invoke 到 GUI 线程
       （platforms/winforms.py:619-643 直接调 SetWindowPos）→
       在**非 GUI 线程**上调用时，跨线程读写的 WinForms 托管属性（Form.Location）
       会和真实矩形**可能**失配 → 位置"自己跑掉"。
       而这个函数是从 **js_api 工作线程**调进来的（api/__init__.py 的 move_by），
       → 必须自己编组到 GUI 线程。
    ⚠️⚠️ **返回值必须如实反映"有没有真的动"**：
       `on_gui_thread` 返回的是"有没有抛异常"，**不是** func 的返回值。
       如果直接把 func 的返回值丢掉、函数末尾无条件 `return True`，
       那 func 内部失败时也会返回 True → api 层回 `{"ok": True, "moved": True}`
       → 前端以为窗口动了，其实没动（**静默失败**）。
       → 用一个 dict 把结果带出来。
    """
    if not win32.IS_WINDOWS or window is None:
        return False
    result = {"ok": False}

    def _move():
        try:
            x = int(getattr(window, "x", 0) or 0) + int(dx)
            y = int(getattr(window, "y", 0) or 0) + int(dy)
            window.move(x, y)
            result["ok"] = True
        except Exception:
            result["ok"] = False

    try:
        on_gui_thread(window, _move, timeout=1.0)
    except Exception:
        _move()
    # ⚠️ 如实返回"真的动了没有"，不要无条件 True
    return bool(result["ok"])


def minimize(hwnd: int):
    """系统原生最小化（SC_MINIMIZE）
    ⚠️ 不要用 SetWindowPos(SW_HIDE) 或 ShowWindow(SW_MINIMIZE) 代替：
       WinForms 的无边框窗口在某些 DPI 下不会触发 DWM 的最小化。
    ⚠️ Win11 的过渡动画已在 install() 里用 DWMWA_TRANSITIONS_FORCEDISABLED 关掉，
       所以这里仍然走 SC_MINIMIZE（行为正确）但视觉上是"瞬间"收起，不再有缩放动画。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return
    try:
        win32.user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_MINIMIZE, 0)
    except Exception:
        try:
            win32.user32.ShowWindow(hwnd, 6)
        except Exception:
            pass


def toggle_maximize(hwnd: int) -> bool:
    """最大化 / 还原（返回操作后的"是否最大化"）
    ⚠️ 用 WM_SYSCOMMAND(SC_MAXIMIZE / SC_RESTORE)，不要直接 ShowWindow：
       SC_* 走的是系统窗口命令，会正确触发 WM_GETMINMAXINFO 的贴工作区逻辑。
       （Win11 的过渡动画同样已被 DWMWA_TRANSITIONS_FORCEDISABLED 关掉。）
    """
    if not win32.IS_WINDOWS or not hwnd:
        return False
    try:
        maximized = bool(win32.user32.IsZoomed(hwnd))
        command = SC_RESTORE if maximized else SC_MAXIMIZE
        win32.user32.PostMessageW(hwnd, WM_SYSCOMMAND, command, 0)
        # ⚠️ 命令是异步处理的，而且这个动作会让 DWM 重建窗口表面：
        #    延迟重放"圆角 + 过渡动画"两件属性（见 _schedule_attr_refresh），
        #    确保最大化/还原之后 DWMWA_TRANSITIONS_FORCEDISABLED 仍然生效。
        _schedule_attr_refresh()
        return not maximized
    except Exception:
        return bool(win32.user32.IsZoomed(hwnd))


def close_window(hwnd: int) -> bool:
    """发送原生 WM_CLOSE（标题栏 × 走这条路，才能跑到 closing 事件里的 close_mode 逻辑）
    ⚠️ Win11 的关闭过渡动画已被 DWMWA_TRANSITIONS_FORCEDISABLED 关掉；
       这里仍必须走 WM_CLOSE（而不是 destroy），否则会绕过"隐藏到托盘 / 彻底退出"的设置。
    返回 False 表示没有发出（调用方可以退回 pywebview 的 destroy）。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return False
    try:
        win32.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return True
    except Exception:
        return False


def fit_size(width: int, height: int):
    """把窗口尺寸夹进工作区（小屏/高 DPI 下不要比可用区域还大）"""
    if not win32.IS_WINDOWS:
        return (width, height)
    try:
        left, top, right, bottom = win32.work_area(None)
        return (max(320, min(int(width), right - left)),
                max(240, min(int(height), bottom - top)))
    except Exception:
        return (width, height)


# ---------- 分辨率等比适配（需求：以 1080p 为基准，其它分辨率按同比例放大窗口与界面） ----------
# 基准 = 用户实测"刚刚好"的那一档：1080p 工作区下窗口 1280×880、界面 1:1。
#
# ⚠️ 算法只依赖一个比值 r =「当前(逻辑)工作区宽 ÷ 1920」，推导如下：
#   · 本函数在 `create_window()` **之前**被调用，此刻进程还没被 pywebview 声明
#     DPI 感知（SetProcessDPIAware 发生在 winforms.start() 里，platforms/winforms.py:820），
#     SPI_GETWORKAREA 返回的是**逻辑像素**（= 物理 ÷ 系统缩放 s）。
#   · pywebview 建窗时会把我们传的"逻辑宽"乘 s 变成物理宽 → 想让**物理窗口占屏幕
#     的比例**与基准一致（1280/1920 = 66.7%），就传逻辑宽 = 1280 × r（s 自动抵消）。
#   · WebView2 的布局视口 CSS px = 逻辑宽 ÷ ZoomFactor → 把 ZoomFactor 也设成 r，
#     视口恒等于基准的 1280：布局与 1080p 完全一致，元素随屏幕同比放大/缩小。
#   · 1080p@100% → r=1：窗口 1280×880、ZoomFactor 1.0，与用户现在的观感**逐像素相同**
#     （回归安全）。2560×1440@100% → r=1.33：窗口物理 1707、界面等比放大。
#     1920×1080@125% → 逻辑工作区 1536 → r=0.8：物理窗口 1280（占比不变），
#     ZoomFactor 0.8 抵消系统缩放 → 视口仍是 1280。
UI_BASE_WORK_W = 1920.0        # 基准：1080p 逻辑工作区宽
UI_SCALE_MIN = 0.8             # 缩放上下限：再小字就糊了，再大就浪费屏幕
UI_SCALE_MAX = 2.2


def ui_scale_factor() -> float:
    """分辨率适配比值 r（见上方推导）。取不到工作区时返回 1.0，绝不抛。"""
    if not win32.IS_WINDOWS:
        return 1.0
    try:
        left, top, right, bottom = win32.work_area(None)
        work_w = float(right - left)
        work_h = float(bottom - top)
        if work_w <= 0 or work_h <= 0:
            return 1.0
        # 目标占比 r（相对 1080p 基准）
        ratio = work_w / UI_BASE_WORK_W
        # 只有明显比基准"更矮"的屏（16:9 之外，如 16:10 工作区、带常驻工具条的屏）
        # 才需要按高度收缩；1080p 的工作区（1920×1032，扣了任务栏）不能误伤，
        # 所以阈值取得比真实宽高比 0.5375 更低。
        if work_h / work_w < 0.5:
            ratio = min(ratio, work_h / 1032.0)
        return max(UI_SCALE_MIN, min(UI_SCALE_MAX, ratio))
    except Exception:
        return 1.0


def apply_page_zoom(window, zoom: float, on_ready=None):
    """把 WebView2 的 ZoomFactor 设成 zoom（GUI 线程编组；拿不到就静默跳过）

    ⚠️ 为什么用原生 ZoomFactor：
      · `window.evaluate_js` 早期有 js_bridge_call 竞态（见 shell 模块 docstring 退出闸门
        同款问题），且 ZoomFactor 是 WebView2 官方 API，字体/图片/CSS 一起等比缩放；
      · ZoomFactor 挂在 **CoreWebView2Controller**（不是 CoreWebView2.Settings），
        COM 对象有线程亲和 → 必须编组回 GUI 线程，且要等控件初始化完成
        （复用 _subscribe_core_ready 的轮询模式，绝不在后台线程直接读控件属性）。
    ⚠️ zoom==1.0 时也要显式设（把可能被别的代码改过的值钉回基准），但失败无所谓。

    ⚠️⚠️ 本轮新增 `on_ready`（启动"界面自动适配"跳变的根治点之一）：
       用户报「启动时……然后自动适配调整界面和 ui 大小适配窗口大小」——
       根因是 ZoomFactor 要等 CoreWebView2 就绪才设得进去，而窗口显示**不等它**：
       于是首帧按 ZoomFactor=1.0 渲染（内容偏小、挤在左上），ZoomFactor 生效后
       内容才放大填满 = 肉眼可见的"界面自己适配了一下"。
       现在 shell 把它变成显示的前置条件之一（带超时兜底），所以这里必须
       **明确告知"缩放已落地"**：`on_ready` 在设置成功、或被网关拒绝而放弃重试时
       都会调用一次（幂等），绝不能只在成功那条路径调用 —— 否则窗口永不显示。
       ⚠️ 回调运行在 **GUI 线程**上：接收方只能做纯状态置位，
          任何"改窗口几何 / show"的动作都必须另起线程编组，
          否则 on_gui_thread 的 BeginInvoke+WaitOne 会等自己排队的消息 = 自锁。
    """
    if not win32.IS_WINDOWS or window is None or zoom <= 0:
        _make_zoom_notifier(on_ready)()
        return
    target = float(round(zoom, 4))
    notify = _make_zoom_notifier(on_ready)

    def _get_webview():
        try:
            return getattr(getattr(window, "native", None), "webview", None)
        except Exception:
            return None

    def _set():
        webview = _get_webview()
        core = getattr(webview, "CoreWebView2", None) if webview is not None else None
        if webview is None or core is None:
            return False
        controller = _core_controller(webview)
        if controller is None:
            return False
        try:
            controller.ZoomFactor = target
            _log("info", "启动", "startup",
                 f"界面缩放已应用：ZoomFactor={target}（按 1080p 基准等比适配）")
            notify()
            return True
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "启动", "startup",
                 f"设置 WebView2 界面缩放失败（不影响使用）: {exc}")
            # 试过但被拒：不再无限重试 —— 也必须上报"就绪"，不然显示闸门永远等不到
            notify()
            return True

    def _install():
        if _set():
            return
        webview = _get_webview()
        if webview is None:
            # 控件还没挂到 native 上：用代理对象让轮询每轮重新取
            #（_subscribe_core_ready 只读传入对象的 .CoreWebView2 属性）
            class _Proxy:
                @property
                def CoreWebView2(self):                 # noqa: N802（与 .NET 同名）
                    wv = _get_webview()
                    return getattr(wv, "CoreWebView2", None) if wv is not None else None
            webview = _Proxy()
        # WebView2 还没初始化完：安排"就绪后再设一次"（与 F11 安装同一套路；
        # 回调仍在 GUI 线程上执行，_set 会重新取控件/控制器）
        _subscribe_core_ready(window, webview, _set)

    def _wrap():
        """_install 万一没排上（拿不到 native / 编组超时），也必须放行显示闸门"""
        try:
            _install()
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "启动", "startup", f"安排应用界面缩放失败: {exc}")
            notify()

    try:
        ok = on_gui_thread(window, _wrap, timeout=3.0)
        if not ok:
            # 编组没成功（GUI 线程忙/窗口还没建好）：闸门不能因此卡死显示
            notify()
    except Exception:
        notify()


def _make_zoom_notifier(on_ready):
    """把 on_ready 包成**每次调用只生效一次**的通知器

    ⚠️ 用"本次调用私有的 holder"而不是模块级标志：apply_page_zoom 将来可能被
       再次调用（分辨率/显示器变化），模块级标志会让第二次的回调永远不触发。
       回调必须幂等，因为"成功"和"被拒"两条路径都可能各走一次。
    """
    done = {"flag": False}

    def _fire():
        if done["flag"] or not callable(on_ready):
            return
        done["flag"] = True
        try:
            on_ready()
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "启动", "startup", f"界面缩放就绪回调异常: {exc}")

    return _fire


def centered_position(width: int, height: int):
    """工作区居中坐标（建窗时传给 pywebview 的 x/y，首帧就不会偏）"""
    if not win32.IS_WINDOWS:
        return (None, None)
    try:
        left, top, right, bottom = win32.work_area(None)
        w = max(320, min(int(width), right - left))
        h = max(240, min(int(height), bottom - top))
        return (left + max(0, (right - left - w) // 2),
                top + max(0, (bottom - top - h) // 2))
    except Exception:
        return (None, None)


def set_maximized(hwnd: int, maximized: bool):
    if not win32.IS_WINDOWS or not hwnd:
        return
    win32.user32.ShowWindow(hwnd, 3 if maximized else 9)
    _update_corner()
    disable_transitions(True, force=True)      # 状态变了：重放一次（见 disable_transitions）


def monitor_rect(hwnd: int):
    """窗口所在显示器的**显示器矩形** (l, t, r, b)（全屏要铺满它，而不是工作区）"""
    if not win32.IS_WINDOWS or not hwnd:
        return None
    try:
        hmon = win32.user32.MonitorFromWindow(hwnd, 2)          # NEAREST
        if not hmon:
            return None
        mi = win32.MONITORINFO()
        mi.cbSize = ctypes.sizeof(win32.MONITORINFO)
        if not win32.user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return None
        mon = mi.rcMonitor
        return (int(mon.left), int(mon.top), int(mon.right), int(mon.bottom))
    except Exception:
        return None


def fullscreen_diagnostics(hwnd: int) -> dict:
    """全屏切换前后的**诊断快照**（日志 + 前端排查都用这一份，别各算各的）
    需求原话：日志里完全没有『进入全屏』的记录 → 不确定请求到底有没有到后端。
    所以把"能不能全屏、现在什么状态、几何/显示器/样式分别是什么"一次全吐出来，
    任何一次切换都留得下证据。
    """
    data = {
        "hwnd": int(hwnd or 0),
        "alive": bool(is_window_alive(hwnd)),
        "fullscreen": bool(_state.fullscreen),
        "fullscreen_native": bool(_state.fullscreen_native),
        "saved_rect": _state.saved_rect,
        "saved_maximized": bool(_state.fullscreen_maximized),
        "rect": None,
        "monitor": None,
        "work_area": None,
        "maximized": False,
        "style": None,
    }
    if not win32.IS_WINDOWS or not hwnd:
        return data
    try:
        data["rect"] = win32.rect_of(hwnd)
        data["monitor"] = monitor_rect(hwnd)
        data["work_area"] = win32.work_area(hwnd)
        data["maximized"] = bool(win32.user32.IsZoomed(hwnd))
        data["style"] = int(win32.user32.GetWindowLongW(hwnd, GWL_STYLE)) & 0xFFFFFFFF
    except Exception:
        pass
    return data


def _rect_covers(rect, monitor, tolerance: int = 2) -> bool:
    """矩形是否**真的**铺满了显示器（容忍 1~2px 的 DPI 取整误差）"""
    if not rect or not monitor:
        return False
    try:
        return all(abs(int(a) - int(b)) <= tolerance for a, b in zip(rect, monitor))
    except Exception:
        return False


def enter_fullscreen(hwnd: int, window=None) -> bool:
    """全屏：窗口铺满**显示器**（不是工作区），并让前端隐藏自己的标题栏
    返回**切换后**是否真的处于全屏（以实测矩形为准，不是"我以为我设成功了"）。
    这里踩过的坑（逐条都对应一个可见现象，改动时别退回旧行为）：
    1. ⚠️ 最大化状态下点全屏没反应：窗口若处于最大化（IsZoomed），`SetWindowPos`
       在它身上基本不改变观感（系统会把它当成"还在最大化"）。所以必须先
       `ShowWindow(SW_RESTORE)` 再 `SetWindowPos`，退出时再把最大化还原回去。
    2. ⚠️ 铺满了但任务栏压在上面：任务栏是 TOPMOST 窗口，不 `HWND_TOPMOST`
       就会被它盖住一条。所以进全屏置顶、退出时取消置顶（且只在原来不置顶时才取消）。
    3. ⚠️ 少 `SWP_FRAMECHANGED`：改了几何却没让系统重算非客户区，无边框补丁
       可能还按旧尺寸算，出现一圈黑边/偏移。带上它。
    4. ⚠️⚠️ 必须编组到 GUI 线程：本函数是从 js_api 的工作线程调进来的，
       而 pywebview 的 `window.toggle_fullscreen()` 之类会**读写 WinForms 的托管属性**，
       跨线程读写**可能**与真实矩形失配（是否会被布局同步改回去，未实测证实）。
       → 用 `on_gui_thread` 把动作编组到 GUI 线程再执行。
    5. ⚠️ 兜底：原生 SetWindowPos 没铺满（某些 DPI/多屏组合下会遇到）时，退回
       pywebview 原生 `window.toggle_fullscreen()`。它会把 FormBorderStyle 设回 None
       （等于去掉我们打的 WS_THICKFRAME），**所以退出全屏时必须重新 install() 补丁**，
       否则"退出全屏后不能拖边缩放"。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return False
    with _lock:
        if _state.fullscreen:
            return True
        # ① 记下"原状"（普通/最大化、是否置顶、矩形），退出时按它还原
        try:
            _state.saved_rect = win32.rect_of(hwnd)
            _state.fullscreen_maximized = bool(win32.user32.IsZoomed(hwnd))
            _state.fullscreen_topmost = bool(
                int(win32.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)) & WS_EX_TOPMOST)
        except Exception:
            _state.saved_rect = None
            _state.fullscreen_maximized = False
            _state.fullscreen_topmost = False
        _state.fullscreen_native = False
        monitor = monitor_rect(hwnd)
        if monitor is None:
            _log("err", "外壳", "fullscreen",
                 "进入全屏失败：未取得显示器矩形（窗口可能已销毁）")
            return False
        result = {"ok": False, "error": "", "rect": None}

        def _apply():
            try:
                # ② 最大化先还原（见函数注释第 1 条）
                if win32.user32.IsZoomed(hwnd):
                    win32.user32.ShowWindow(hwnd, SW_RESTORE)
                left, top, right, bottom = monitor
                width, height = right - left, bottom - top
                flags = SWP_SHOWWINDOW | SWP_FRAMECHANGED
                ok = bool(win32.user32.SetWindowPos(hwnd, HWND_TOPMOST, left, top,
                                                    width, height, flags))
                error = win32.kernel32.GetLastError()
                if not ok:
                    # 部分环境不允许直接改 Z 序（前台锁/权限层级）：退一步只改几何
                    ok = bool(win32.user32.SetWindowPos(hwnd, 0, left, top, width, height,
                                                        flags | SWP_NOZORDER))
                    error = win32.kernel32.GetLastError()
                result["ok"] = ok
                result["error"] = "" if ok else f"SetWindowPos 失败 err={error}"
                result["rect"] = win32.rect_of(hwnd)
            except Exception as exc:                     # noqa: BLE001
                result["error"] = f"{type(exc).__name__}: {exc}"

        if window is not None:
            on_gui_thread(window, _apply, timeout=3.0)
        else:
            _apply()
        covered = _rect_covers(result.get("rect"), monitor)
        if not covered and window is not None:
            # ③ 兜底：pywebview 原生全屏（FormBorderStyle=None + WindowState=Maximized）
            try:
                window.toggle_fullscreen()
                _state.fullscreen_native = True
                covered = True
                result["rect"] = win32.rect_of(hwnd)
                _log("warn", "外壳", "fullscreen",
                     f"原生 SetWindowPos 未铺满（实测={result.get('rect')} 期望={monitor} "
                     f"{result.get('error')}）→ 已改用 pywebview 原生全屏")
            except Exception as exc:                     # noqa: BLE001
                _log("err", "外壳", "fullscreen",
                     f"pywebview 原生全屏也失败: {type(exc).__name__}: {exc}")
        _state.fullscreen = bool(covered)
        _log("info", "外壳", "fullscreen",
             (f"进入全屏: 成功={_state.fullscreen} "
              f"路径={'pywebview原生' if _state.fullscreen_native else 'SetWindowPos'} "
              f"原矩形={_state.saved_rect} 原最大化={_state.fullscreen_maximized} "
              f"原置顶={_state.fullscreen_topmost} 显示器={monitor} "
              f"结果矩形={result.get('rect')} {result.get('error')}").strip())
        if _state.fullscreen:
            _update_corner()
            # DWM 会重建表面：重放一次逐窗口的 DWMWA_TRANSITIONS_FORCEDISABLED
            _schedule_attr_refresh()
        return _state.fullscreen


def exit_fullscreen(hwnd: int, window=None) -> bool:
    """退出全屏：还原进全屏前的矩形 / 最大化状态 / Z 序，并补回可拖边缩放"""
    if not win32.IS_WINDOWS or not hwnd:
        return False
    with _lock:
        if not _state.fullscreen:
            return True
        saved = _state.saved_rect
        was_maximized = bool(_state.fullscreen_maximized)
        was_topmost = bool(_state.fullscreen_topmost)
        native = bool(_state.fullscreen_native)
        result = {"ok": False, "error": ""}

        def _apply():
            try:
                if native and window is not None:
                    # pywebview 那条路：先让它把 FormBorderStyle / 尺寸 / 位置还原
                    try:
                        window.toggle_fullscreen()
                    except Exception:                    # noqa: BLE001
                        pass
                # ① 取消置顶（进全屏时为了让开任务栏置顶过；原来就置顶的保持原样）
                if not was_topmost:
                    win32.user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                              SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                # ② 还原矩形
                if saved:
                    win32.user32.SetWindowPos(hwnd, 0, int(saved[0]), int(saved[1]),
                                              int(saved[2] - saved[0]),
                                              int(saved[3] - saved[1]),
                                              SWP_NOZORDER | SWP_SHOWWINDOW
                                              | SWP_FRAMECHANGED)
                # ③ 进来之前是最大化 → 还原成最大化（别把用户窗口状态吃掉）
                if was_maximized:
                    win32.user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_MAXIMIZE, 0)
                result["ok"] = True
            except Exception as exc:                     # noqa: BLE001
                result["error"] = f"{type(exc).__name__}: {exc}"

        if window is not None:
            on_gui_thread(window, _apply, timeout=3.0)
        else:
            _apply()
        _state.fullscreen = False
        _state.fullscreen_native = False
        # ④ 重新打一次无边框补丁：pywebview 原生全屏会把 FormBorderStyle 设成 None，
        #    等于把我们加的 WS_THICKFRAME 去掉 —— 不补回来"退出全屏后就不能拖边缩放"。
        try:
            install(hwnd, dark=bool(_state.dark))
        except Exception:
            pass
        _log("info", "外壳", "fullscreen",
             (f"退出全屏: 还原矩形={saved} 原最大化={was_maximized} "
              f"路径={'pywebview原生' if native else 'SetWindowPos'} "
              f"{result.get('error')}").strip())
        _schedule_attr_refresh()
        return bool(result["ok"])


def toggle_fullscreen(hwnd: int, window=None) -> bool:
    """返回切换后的"是否全屏"（以实测状态为准）"""
    if _state.fullscreen:
        exit_fullscreen(hwnd, window)
    else:
        enter_fullscreen(hwnd, window)
    return bool(_state.fullscreen)


def is_fullscreen() -> bool:
    return bool(_state.fullscreen)


def is_maximized(hwnd: int) -> bool:
    try:
        return bool(win32.user32.IsZoomed(hwnd))
    except Exception:
        return False


def window_state(hwnd: int) -> dict:
    """给前端同步"窗口现在是什么状态"（标题栏按钮图标要跟着变）
    `transitions` 是本窗口的 DWM 过渡动画状态（None=还没设上/不支持，
    True=已强制禁用，False=已恢复系统动画），给自检脚本当证据用。
    """
    return {
        "maximized": is_maximized(hwnd),
        "fullscreen": is_fullscreen(),
        "minimized": bool(win32.user32.IsIconic(hwnd)) if win32.IS_WINDOWS and hwnd else False,
        "dark": bool(_state.dark),
        "transitions": _state.transitions,
        "alive": is_window_alive(hwnd),
    }


def is_window_alive(hwnd: int) -> bool:
    """hwnd 还是不是一个活着的窗口（退出流程里判断"还能不能碰它"）
    ⚠️ 退出流程的关键守卫：`WebView2` 是先于顶层窗口销毁的，所以在窗口关掉之后再去
       `window.evaluate_js(...)`，pywebview 会在 edgechromium.py:152 抛
       `System.ObjectDisposedException: 无法访问已释放的对象。对象名:"WebView2"`
       并打一行 "[pywebview] Error occurred in script"。调用方（shell.push_event）
       先用本函数 + 自己的 `_teardown_started` 闸门拦掉。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return False
    try:
        return bool(win32.user32.IsWindow(hwnd))
    except Exception:
        return False


def is_on_screen(hwnd: int) -> bool:
    """窗口矩形是否与它所在显示器的工作区相交（离屏建窗的自检用）
    启动时我们**故意**把窗口建在虚拟桌面外（见 shell.run 的说明），ready 之后要确认
    真的移回屏幕了再 show；否则窗口会"隐藏着但永远在屏幕外"。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return False
    try:
        left, top, right, bottom = win32.work_area(hwnd)
        wl, wt, wr, wb = win32.rect_of(hwnd)
        # 只要有一点交集就当作"在工作区里"；完全没交集 = 离屏
        return (wl < right and wr > left and wt < bottom and wb > top)
    except Exception:
        return False


def force_center_on_screen(hwnd: int, window=None) -> bool:
    """把窗口强行挪回工作区正中（编组到 GUI 线程的原生 SetWindowPos 版本）
    与 `center_on_screen` 的分工：那个走 pywebview 的 `window.move/resize`（依赖 WinForms
    的托管属性），这个走 `_center_on_screen_now`（原生 SetWindowPos，必须编组到 GUI 线程）。
    离屏建窗的兜底用后者 —— 万一托管属性那条路没生效，也要保证窗口回到屏幕上。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return False
    if window is None:
        _center_on_screen_now(hwnd)
        return is_on_screen(hwnd)
    try:
        on_gui_thread(window, lambda: _center_on_screen_now(hwnd), timeout=2.0)
    except Exception:
        _center_on_screen_now(hwnd)
    return is_on_screen(hwnd)


def force_show(hwnd: int) -> bool:
    """原生"把窗口显示出来并抬到最前"（不依赖 pywebview 的任何托管 API）
    ⚠️ 这是**最后一道兜底**：当 pywebview 那条路（window.show/resize/move）因为
       线程不对而失效时，至少保证窗口是**可见的**且在**前台**。
    ⚠️⚠️ **最小化的窗口必须用 SW_RESTORE**：
       实测 `ShowWindow(hwnd, SW_SHOW)` 对**已最小化**的窗口**不会**还原
       （IsIconic 仍为 True，而且系统会把最小化窗口的矩形搬到 (-32000,-32000) 离屏处）
       → 窗口就一直是"看不见"的。SW_RESTORE 才能把它还原回屏幕内。
    ⚠️ 用 SW_SHOW 而不是 SW_SHOWNORMAL：后者会**重置窗口尺寸**（还原到建窗时的大小），
       我们要的是"按现在的大小显示出来"。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return False
    try:
        if win32.user32.IsIconic(hwnd):
            win32.user32.ShowWindow(hwnd, SW_RESTORE)   # SW_RESTORE（最小化状态下要先还原）
        else:
            win32.user32.ShowWindow(hwnd, 5)              # SW_SHOW
        win32.user32.BringWindowToTop(hwnd)
        win32.user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def show_window_on_gui_thread(window, hwnd: int, width: int = 0, height: int = 0) -> bool:
    """★ 把"显示窗口"这个动作**整体编组到 GUI 线程**执行（启动与托盘呼出共用）

    ⚠️⚠️ 为什么必须有这个函数（这是"任务栏有图标、窗口却不弹出"的根治点）：
       pywebview 6.2.1 的 winforms 后端里，各方法的线程安全性**不一致**：
         · `BrowserView.show()`（platforms/winforms.py:494-502）**有** Invoke 到 GUI 线程；
         · `BrowserView.resize()`（:600-617）和 `move()`（:619-643）**没有** Invoke ——
           它们**直接**调 `windll.user32.SetWindowPos(...)`，并且读写 WinForms 的
           **托管属性**（`Form.Location` / `Form.Size`）。
       ⚠️ 纯 Win32 探针实测结论（**重要，别再当成"调用被丢弃"**）：
          跨线程的原生 `SetWindowPos` 对普通窗口**是生效的**（返回 True、
          GetLastError=0、矩形真的变了）。真正的问题是**顺序**：
          · `resize()` 传的 flags=64（SWP_SHOWWINDOW）、`move()` 更是显式写了
            SWP_SHOWWINDOW → **"调用即等于显示窗口"**；
          · 而托管属性 `Form.Location/Size` 从**非 GUI 线程**读写会和真实矩形失配
            （WinForms 下一次布局同步会把值改回去）。
       → 于是旧代码在**后台线程**（js_api 工作线程 / threading.Timer）里调用
          `frame.center_on_screen()` → resize/move 的托管属性与真实矩形失配、
          且"显示"这一拍可能**先于**"搬回屏幕内"生效 →
          窗口停在 OFFSCREEN(-32000,-32000) →
          **任务栏有图标（pywebview 建窗时 Show+Hide 过）但屏幕上根本看不见**，
          症状与测试者的反馈完全吻合。
       → 本函数把「搬回屏幕 → 定尺寸 → 居中 → 显示 → 再收敛几何」**整串**
          放进 GUI 线程，消除"改几何"和"显示"之间被插队 / 托管属性失配的机会。

    ⚠️⚠️ **为什么尺寸用原生 SetWindowPos 自己算，而不调 window.resize()**：
       `window.resize()` 内部是 `phys = int(logical * self._scale)`，
       而 `self._scale = GetDpiForWindow(handle)/96`（platforms/winforms.py:317-325）；
       它设置的是 `Form.Size`（**客户区**尺寸），不是整个窗口矩形。
       ⚠️ 用原生 SetWindowPos + 我们自己算的 `dpi_scale(hwnd)`：
          换算**只发生一次**、作用在整个窗口矩形上，结果可控可复算。

    ⚠️⚠️ **顺序**有讲究：
       ① 先**搬回工作区**（move）：窗口必须先落到**目标显示器**上，
          `GetDpiForWindow` 才会返回**那台显示器**的 DPI。
       ② 再 **resize**（原生 SetWindowPos，物理像素）。
       ③ 再**居中**一次：尺寸变了要重新算居中位置。
       ④ 然后 `window.show()`（拿焦点 / 激活）—— 但**先确认 shown 事件已就绪**，
          否则它在 GUI 线程上会阻塞 20 秒（见 `_shown_event_ready`）。
       ⑤ **show 之后再收敛一次几何**：WinForms 的 `Form.Show()` 在 DPI 变化的显示器上
          会触发**自动缩放**（AutoScaleMode.Dpi，platforms/winforms.py:202-203），
          可能把尺寸又改掉 —— 所以 show 之后要按同样的物理尺寸再摆一次。

    参数 width/height：目标**逻辑像素**尺寸；0 = 不改尺寸（沿用当前尺寸）。
    """
    if not win32.IS_WINDOWS or window is None:
        return False
    try:
        hwnd = int(hwnd or hwnd_of_window(window) or 0)
    except Exception:
        hwnd = 0
    if not hwnd:
        return False

    def _do():
        """⚠️ 这一段**必须**在 GUI 线程上跑 —— 里面调的是 pywebview 的 show()
           （以及原生 SetWindowPos）。show() 自己也会 Invoke；我们在 GUI 线程上时
           它走"直接执行"分支，不会死锁。"""
        try:
            # ⓪ ⚠️⚠️ **最小化的窗口必须先还原**（托盘呼出时窗口可能处于最小化状态）：
            #    · `Form.Show()` 对**已最小化**的窗体**不会**还原（它只在"未创建/已隐藏"时显示）；
            #    · `ShowWindow(SW_SHOW)` 对已最小化的窗口也**不会**还原（IsIconic 仍为 True）；
            #    · 而系统会把**最小化窗口的矩形搬到 (-32000,-32000)**（离屏）——
            #      不还原的话，窗口就一直是"看不见"的（任务栏有图标但屏幕上没有）。
            #    → 只有 SW_RESTORE 能把它还原回屏幕内。
            if win32.user32.IsIconic(hwnd):
                win32.user32.ShowWindow(hwnd, SW_RESTORE)
            # ① 先搬回工作区（让窗口落到目标显示器上，GetDpiForWindow 才是对的）
            _center_on_screen_now(hwnd)
            # ② 定尺寸：逻辑像素 × 该显示器 DPI = 物理像素（原生 SetWindowPos）
            if width and height:
                _resize_to_physical(hwnd, int(width), int(height))
            # ③ 尺寸变了 → 重新居中
            _center_on_screen_now(hwnd)
            # ④ 显示出来
            # ⚠️⚠️ `window.show()` 带 `@_shown_call` 装饰器 → 内部 `event.wait(20)`：
            #    如果 shown 事件还没 set，它会**阻塞调用线程 20 秒**！
            #    而我们在 **GUI 线程**上 —— 那会把整个界面**冻住 20 秒**（界面假死）。
            #    → 先检查事件是否已 set：已 set 就走 pywebview 的 show()（正常路径，
            #      事件已 set 时 wait 立即返回）；没 set 就**不调**，直接走原生 force_show。
            #    （建窗时 hidden=True 走的是 "Opacity=0; Show(); Hide(); Opacity=1"，
            #      那条路径**已经触发过一次 Form.Shown** → shown 事件早已 set，
            #      所以正常情况下永远走 pywebview 这条。）
            if _shown_event_ready(window):
                try:
                    window.show()
                except Exception:
                    force_show(hwnd)
            else:
                # 事件没就绪 → 不能在 GUI 线程里阻塞等它，直接用原生显示
                force_show(hwnd)
            # ⑤ show 之后收敛一次几何（WinForms 在 DPI 变化的屏上 Show() 会自动缩放）
            if width and height:
                _resize_to_physical(hwnd, int(width), int(height))
                _center_on_screen_now(hwnd)
        except Exception:
            # resize/move 抛异常也不放弃"让它可见"这件事
            force_show(hwnd)

    try:
        on_gui_thread(window, _do, timeout=3.0)
    except Exception:
        _do()
    return True


def _shown_event_ready(window) -> bool:
    """pywebview 的 `shown` 事件是否**已经就绪**（已 set）
    ⚠️ 为什么必须先问一句：`Window.show()` 带 `@_shown_call` 装饰器，
       内部是 `event.wait(20)` —— 事件没 set 时它会**阻塞 20 秒**。
       我们在 GUI 线程上调它 → 界面假死 20 秒。
       → 所以先看事件状态：就绪才调（wait 立即返回），没就绪就走原生 force_show。
    """
    try:
        events = getattr(window, "events", None)
        shown = getattr(events, "shown", None)
        if shown is None:
            return True          # 拿不到事件 → 赌它已就绪（老版本 pywebview 没有这个事件）
        is_set = getattr(shown, "is_set", None)
        if callable(is_set):
            return bool(is_set())
        return True
    except Exception:
        return True


def _resize_to_physical(hwnd: int, logical_w: int, logical_h: int) -> bool:
    """把窗口设成"逻辑尺寸 × 该显示器 DPI"的**物理**尺寸（原生 SetWindowPos）
    ⚠️ 为什么要自己算：pywebview 的 `window.resize()` 内部也做同样的换算，
       但它用的是 `Form.Size`（**客户区**尺寸，且托管属性从非 GUI 线程读写会失配），
       而我们这里要的是**整个窗口矩形**（含边框）的物理尺寸 ——
       换算**只发生一次**、结果可控。
    ⚠️ 关于"边框宽度"：无边框补丁（frame.install）已经把非客户区清零，
       所以客户区 ≈ 整个窗口；但系统标题栏模式下两者不同 ——
       那种模式下用 `AdjustWindowRectEx` 才能把客户区尺寸换算成窗口尺寸。
       这里**不**做这个换算（无边框模式才是本项目的默认），需要时由调用方用
       `window_snapshot()` 读实际矩形来对账。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return False
    try:
        scale = win32.dpi_scale(hwnd) or 1.0
        phys_w = max(320, int(round(logical_w * scale)))
        phys_h = max(240, int(round(logical_h * scale)))
        wl, wt, wr, wb = win32.rect_of(hwnd)
        # SWP_NOMOVE：保持左上角不动（位置由随后的居中决定）
        win32.user32.SetWindowPos(hwnd, 0, wl, wt, phys_w, phys_h,
                                  SWP_NOZORDER | SWP_NOMOVE | SWP_NOACTIVATE)
        return True
    except Exception:
        return False


def window_snapshot(hwnd: int) -> dict:
    """窗口当前状态的**快照**（自检日志用）—— 一次采集，避免各处重复调 Win32
    返回：可见 / 在屏上 / 物理矩形 / 工作区 / DPI / 物理尺寸 / 逻辑尺寸
    ⚠️ ⚠️ **日志里必须把两套单位分清楚**，否则会误判成 bug：
       · `rect` / `work_area` 是**物理像素**（Win32 的 GetWindowRect / 工作区）；
       · `logical` 是**逻辑像素**（物理 ÷ 该显示器 DPI）。
       → 以前那条日志把"目标(逻辑像素)"和"窗口几何(物理像素)"**并排打印**，
         看起来像"目标 1024x680、实际 1513x964 = 大了 1.48 倍 = bug"，
         其实 1513 ≈ 1024 × 1.5（150% DPI）—— **同一个尺寸的两套单位**，根本没错。
    """
    out = {"hwnd": int(hwnd or 0), "visible": False, "on_screen": False,
           "rect": (0, 0, 0, 0), "work_area": (0, 0, 0, 0), "dpi": 1.0,
           "phys_size": (0, 0), "logical_size": (0, 0)}
    if not win32.IS_WINDOWS or not hwnd:
        return out
    try:
        out["visible"] = is_window_visible(hwnd)
        out["on_screen"] = is_on_screen(hwnd)
        wl, wt, wr, wb = win32.rect_of(hwnd)
        out["rect"] = (wl, wt, wr, wb)
        out["work_area"] = win32.work_area(hwnd)
        out["dpi"] = win32.dpi_scale(hwnd) or 1.0
        out["phys_size"] = (wr - wl, wb - wt)
        out["logical_size"] = (int((wr - wl) / out["dpi"]), int((wb - wt) / out["dpi"]))
    except Exception:
        pass
    return out


def is_window_visible(hwnd: int) -> bool:
    """窗口当前是否**可见**（IsWindowVisible）—— 显示自检用"""
    if not win32.IS_WINDOWS or not hwnd:
        return False
    try:
        return bool(win32.user32.IsWindowVisible(hwnd))
    except Exception:
        return False


def bring_to_front(hwnd: int):
    """把窗口真正抬到最前（原版 `_bring_to_front` 的等价实现）
    ⚠️ 只 SetForegroundWindow 不够：调用进程不是前台进程时会被前台锁拒绝（错误码 0）。
       这里保留了原版的三招：ShowWindow 还原 → AttachThreadInput 绕前台锁 → 置顶再取消置顶。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return
    u = win32.user32
    k = win32.kernel32
    try:
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)                          # SW_RESTORE
        else:
            u.ShowWindow(hwnd, 5)                          # SW_SHOW
        foreground = u.GetForegroundWindow()
        target_thread = u.GetWindowThreadProcessId(foreground, None)
        current_thread = k.GetCurrentThreadId()
        attached = False
        if target_thread and target_thread != current_thread:
            attached = bool(u.AttachThreadInput(target_thread, current_thread, True))
        u.SetWindowPos(hwnd, -1, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)      # TOPMOST
        u.SetWindowPos(hwnd, -2, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)      # NOTOPMOST
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
        u.SetActiveWindow(hwnd)
        if attached:
            u.AttachThreadInput(target_thread, current_thread, False)
    except Exception:
        pass


def hwnd_of_window(window) -> int:
    """从 pywebview 的 Window 对象取原生 HWND（WinForms 后端）"""
    try:
        native = getattr(window, "native", None)
        if native is None:
            return 0
        handle = native.Handle
        return int(handle.ToInt32()) if hasattr(handle, "ToInt32") else int(handle)
    except Exception:
        return 0


def on_gui_thread(window, func, timeout: float = 3.0):
    """把一段操作**编组到 WinForms 的 GUI 线程**上执行
    ⚠️⚠️ 这是本层最重要的一条纪律，踩了很久才定位：
        改变窗口几何（位置/尺寸）的调用，如果发起线程不是创建窗口的那个 GUI 线程，
        就**不该**直接做 —— 纯 Win32 探针实测：
          · 原生 `SetWindowPos` 跨线程**确实生效**（返回 True、矩形真的变了），
            所以"调用被丢弃"不是问题；
          · 但 pywebview 的 `resize()` / `move()` **读写的是 WinForms 的托管属性**
            （`Form.Size` / `Form.Location`），跨线程读写**可能**与真实矩形失配
            （是否会被 WinForms 下一次布局同步改回去，未实测证实）→
            窗口位置/尺寸可能"自己跑掉"；
          · 更关键：`resize()` 的 flags=64、`move()` 显式带 **SWP_SHOWWINDOW**
            → **"调用即等于显示窗口"**。于是"显示"可能**先于**"搬回屏幕内"发生，
            窗口就停在离屏位置（OFFSCREEN）—— 任务栏有图标、屏幕上却看不见。
        实测：`webview.start(func=...)` 的回调、`js_api` 的回调、`threading.Timer`
        回调**都不是** GUI 线程；在这些线程上居中/改尺寸全都不可靠，
        表现为"窗口位置每次启动都不一样（WinForms 自己摆的）、有时还压在任务栏下"。
        正确做法：`window.native.Invoke(Func[Type](func))` —— pywebview 的
        WinForms 后端自己就是这么干活的（见 platforms/winforms.py 的 `show()`）。
        `func` 拿不到 window（比如窗口已销毁）时直接同步执行，保证不抛。

    ⚠️⚠️ **`timeout` 现在是真的生效的**（之前签名收了 timeout 但函数体一次都没用）：
        `native.Invoke(...)` 是**无限阻塞**的 —— GUI 线程万一卡住（WebView2 正在加载、
        正在等某个 COM 调用），调用线程就**永久挂住**。
        而 `mark_frontend_ready()` 是在 **js_api 工作线程**里调的，
        js_bridge_call 的 `_call()` 会等它返回再 `evaluate_js`（webview/util.py:264）
        → **整个前端 bridge 静默卡死**（界面点不动、日志也不再出）。
        → 改用 `BeginInvoke` + `endInvoke.WaitOne(timeout)`：
          超时就不等了（**不再挂住调用线程**），并如实报告"没跑成"。
          ⚠️ 注意：BeginInvoke 是**异步**的 —— 超时后 GUI 线程**可能**稍后才执行 func。
             我们的 func 都是幂等的（设置几何 / 显示窗口），晚一点执行无害。
    """
    if not win32.IS_WINDOWS:
        return False
    try:
        native = getattr(window, "native", None)
        if native is None:
            return False
        from System import Action, Func, Type
        done = {"flag": False, "error": None}

        def _call():
            try:
                func()
            except Exception as exc:                     # noqa: BLE001
                done["error"] = exc
            finally:
                done["flag"] = True

        try:
            if native.InvokeRequired:
                # ⚠️ 用 BeginInvoke + 限时等待，**不要**用 Invoke（无限阻塞）
                try:
                    end = native.BeginInvoke(Action(_call))
                    ms = max(0, int(float(timeout or 0) * 1000))
                    # WaitOne 返回 False = 超时（GUI 线程还没跑到我们的回调）
                    if not end.WaitOne(ms):
                        return False
                except Exception:
                    # BeginInvoke 不可用（控件正在销毁等）→ 退回 Invoke
                    native.Invoke(Action(_call))
            else:
                _call()
        except Exception:
            # Invoke 失败（窗口正在销毁等）：退回同步执行，至少尝试一次
            _call()
        if not done["flag"]:
            # Invoke 没跑到我们的回调（例如控件已释放）→ 同步兜底
            _call()
        return done["error"] is None
    except Exception:
        try:
            func()
        except Exception:
            pass
        return False


# ============ 任务栏按钮的显示 / 隐藏（开机自启静默启动用） ============
def set_taskbar_hidden(hwnd: int, hidden: bool, window=None) -> dict:
    """把主窗口的**任务栏按钮**收起来 / 放回去（成对使用，必须配对调用）

    ⚠️⚠️ 为什么不能用"把窗口挪到屏幕外"糊弄过去（这就是用户报的 bug）：
       窗口只要满足"可见（WS_VISIBLE）+ 有任务栏按钮资格"，
       Windows 就会在任务栏给它建一个按钮 —— **和它在不在屏幕内无关**。
       旧做法把窗口留在 OFFSCREEN(-32000,-32000) 且不调 Show，
       但 pywebview 建 hidden=True 窗口的时序是 `Opacity=0 → Show() → Hide() → Opacity=1`，
       那一次真实 Show 已经让任务栏按钮建立起来了；再加上 `_on_shown` 里
       无条件的 `bring_to_front`（SW_SHOW + SWP_SHOWWINDOW）把窗口在**屏幕外**
       重新显示 → **"任务栏有 ToolsGCP 按钮、屏幕上什么都没有"**。
       点那个按钮走的是**系统自己的** SW_RESTORE：它既不经过我们的
       `show_window()`（里面才有"搬回工作区正中 + 焦点给回 WebView2"那串编组），
       还原到的又是系统记下的最小化位置 (-32000,-32000) →
       用户看到的"点任务栏图标不弹窗，必须右键托盘选『显示主窗口』才恢复"。

    正确做法（Windows 认可的两条）：
      ① 首选 **hide**：`window.hide()` → WS_VISIBLE 被清掉 → 任务栏按钮消失。
         这条和浏览器模式那套 `hide_to_tray()` 完全一致（同一个语义、同一条恢复路径），
         两条需求不会互相抵消 —— 本轮口径：静默启动 = 真的"没有窗口"，而不是"窗口在屏外"。
      ② 扩展样式兜底：清 WS_EX_APPWINDOW + 置 WS_EX_TOOLWINDOW → 任务栏不建按钮
         （但窗口仍然可见、仍占 Alt+Tab 之外的位置）。恢复时**反过来**：
         清 TOOLWINDOW + 置 APPWINDOW，再带 SWP_FRAMECHANGED 让系统重算。
         ⚠️ 只改样式不带 SWP_FRAMECHANGED 是**不生效**的（任务栏按钮不会立刻重算）。
         ⚠️ 光有 TOOLWINDOW 还不够：窗口若有**可见的父窗口**，任务栏按钮规则由父窗口
            决定；我们的主窗口是顶层窗口（无父），所以这条路是干净的。

    参数 hidden=True → 收起任务栏按钮；False → 恢复。
    返回 {"ok", "via", "style_before", "style_after", "visible", "error"}（给日志/自检用）。
    ⚠️ 线程：内部经 `on_gui_thread` 编组（hide() 自己 Invoke，样式改动跨线程也可，
       但和托管属性保持一致最安全）。
    """
    out = {"ok": False, "via": "", "style_before": None, "style_after": None,
           "visible": None, "error": ""}
    if not win32.IS_WINDOWS or not hwnd:
        out["error"] = "非 Windows 或窗口句柄无效"
        return out

    def _apply():
        try:
            before = int(win32.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)) & 0xFFFFFFFF
            out["style_before"] = before
            if hidden:
                # ① 首选 hide：窗口不可见 = 任务栏按钮消失（和 hide_to_tray 同一语义）
                #    ⚠️⚠️ 必须先问 `_shown_event_ready` 再调 `window.hide()`：
                #       pywebview 的 hide() 和 show() 一样带 `@_shown_call`
                #       （内部 `event.wait(20)`，见 webview/window.py:25-57）——
                #       shown 事件还没 set 时，在 GUI 线程上调它会**把界面冻住 20 秒**。
                #       没就绪就直接走原生 ShowWindow(SW_HIDE)（本函数已在 GUI 线程上）。
                hid = False
                if window is not None and _shown_event_ready(window):
                    try:
                        window.hide()
                        out["via"] = "window.hide"
                        hid = True
                    except Exception as exc:               # noqa: BLE001
                        out["error"] = f"window.hide 失败: {type(exc).__name__}: {exc}"
                if not hid:
                    try:
                        win32.user32.ShowWindow(hwnd, win32.SW_HIDE)
                        out["via"] = "SW_HIDE"
                    except Exception as exc:               # noqa: BLE001
                        out["error"] += f" / ShowWindow(SW_HIDE) 失败: {exc}"
                # ② 无论 hide 成没成，样式也一并改掉：
                #    万一 WinForms 下一次布局同步又把窗口 Show 回来（_on_shown 那种抢跑），
                #    TOOLWINDOW 保证它**仍然不会**在任务栏建按钮。
                after = (before & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW
            else:
                # 恢复：反过来 —— 清 TOOLWINDOW、置 APPWINDOW。
                # ⚠️ **不**在这里 Show 窗口：呼出由 shell.show_window() 走
                #    show_window_on_gui_thread（搬回工作区 → 定尺寸 → 居中 → show → 焦点）。
                #    这里只负责把"有任务栏按钮"这件事恢复成默认。
                after = (before & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            if after != before:
                win32.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ctypes.c_long(after))
                # SWP_FRAMECHANGED 才会让系统重算非客户区 + 任务栏按钮归属。
                # SWP_NOACTIVATE + SWP_NOMOVE + SWP_NOSIZE + SWP_NOZORDER：
                # ⚠️ 绝不能带 SWP_SHOWWINDOW —— 那是"调用即显示窗口"，
                #    静默启动路径带上就等于当场把窗口掀出来。
                win32.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                          SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
                                          SWP_NOACTIVATE | SWP_FRAMECHANGED)
            out["style_after"] = int(win32.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)) & 0xFFFFFFFF
            out["visible"] = bool(win32.user32.IsWindowVisible(hwnd))
            out["ok"] = True
        except Exception as exc:                           # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {exc}"

    try:
        if window is not None:
            on_gui_thread(window, _apply, timeout=3.0)
        else:
            _apply()
    except Exception as exc:                               # noqa: BLE001
        out["error"] = out["error"] or f"{type(exc).__name__}: {exc}"
    return out


def is_taskbar_hidden(hwnd: int) -> dict:
    """读当前窗口的"任务栏按钮状态"（取证/自检用，不改任何东西）
    返回 {"exists": 任务栏按钮是否存在, "visible": WS_VISIBLE, "exstyle": 扩展样式,
          "toolwindow": bool, "appwindow": bool}
    ⚠️ exists 的判据（和 Windows 自己的规则一致）：
       窗口可见 且（不是 TOOLWINDOW 或 是 APPWINDOW）→ 任务栏有按钮。
       真实截图/枚举 Shell_TrayWnd 太慢，这里用样式推断；
       `_devtest/probe_taskbar_button.py` 会同时给**枚举任务栏缩略按钮**的实测对照。
    """
    out = {"exists": False, "visible": False, "exstyle": None,
           "toolwindow": False, "appwindow": False}
    if not win32.IS_WINDOWS or not hwnd:
        return out
    try:
        ex = int(win32.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)) & 0xFFFFFFFF
        out["exstyle"] = ex
        out["toolwindow"] = bool(ex & WS_EX_TOOLWINDOW)
        out["appwindow"] = bool(ex & WS_EX_APPWINDOW)
        out["visible"] = bool(win32.user32.IsWindowVisible(hwnd))
        out["exists"] = out["visible"] and (out["appwindow"] or not out["toolwindow"])
    except Exception:
        pass
    return out


def _center_on_screen_now(hwnd: int, keep_size: bool = True):
    """真正干活的部分（**必须在 GUI 线程上执行**，见 center_on_screen 的说明）
    ⚠️⚠️ `keep_size=True`（默认）= **只挪位置、不改尺寸**。
       为什么必须这样：这一段是"把窗口搬回屏幕内"的动作，而**尺寸**是由
       `_resize_to_physical()` 单独负责的（用**目标逻辑尺寸 × DPI** 算出来）。
       如果这里顺手用"当前物理矩形"去算尺寸，就会出现两件事：
         ① 启动隐藏路径上，窗口建在 (-32000,-32000)，此时它的尺寸是
            pywebview 建窗时给的（客户区逻辑尺寸 × DPI），
            而**无边框补丁尚未生效**时客户区 ≠ 窗口矩形 → 尺寸会漂；
         ② 每次居中都可能把尺寸改一次，多次调用会**累积误差**。
       → 所以：位置用**当前实际尺寸**算（只用来定中心点），
         但 SetWindowPos 时**不传宽高**（传 0 + SWP_NOSIZE = 保持现尺寸）。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return
    try:
        # ⚠️⚠️ **最小化的窗口必须先还原**：系统会把最小化窗口的矩形搬到
        #    (-32000,-32000)（离屏），而 `ShowWindow(SW_SHOW)` 对最小化窗口**不还原**
        #    （IsIconic 仍为 True）→ 窗口就一直是"看不见"的。
        #    只有 SW_RESTORE 能把它还原回屏幕内。
        if win32.user32.IsIconic(hwnd):
            win32.user32.ShowWindow(hwnd, SW_RESTORE)
        left, top, right, bottom = win32.work_area(hwnd)
        wl, wt, wr, wb = win32.rect_of(hwnd)
        width, height = wr - wl, wb - wt
        avail_w = right - left
        avail_h = bottom - top
        # 中心点按"当前实际尺寸"算（尺寸由 _resize_to_physical 负责，不在这里改）
        cx = left + max(0, (avail_w - min(width, avail_w)) // 2)
        cy = top + max(0, (avail_h - min(height, avail_h)) // 2)
        if keep_size:
            # ⚠️ SWP_NOSIZE：宽高传 0 = **保持当前尺寸不变**
            win32.user32.SetWindowPos(hwnd, 0, cx, cy, 0, 0,
                                      SWP_NOZORDER | SWP_NOSIZE | SWP_SHOWWINDOW)
        else:
            win32.user32.SetWindowPos(hwnd, 0, cx, cy,
                                      min(width, avail_w), min(height, avail_h),
                                      SWP_NOZORDER | SWP_SHOWWINDOW)
    except Exception:
        pass


def center_on_screen(hwnd: int, window=None):
    """按工作区居中，并把窗口夹进工作区（原版 `center_window` 的等价实现）
    ⚠️⚠️ 现在是 `force_center_on_screen()` 的**薄封装**（原生 SetWindowPos + 自带
       GUI 线程编组），**不再**走 pywebview 的 `window.resize()/move()`。
       原因：那两个方法**没有** Invoke 到 GUI 线程、会跨线程读写 WinForms 的托管属性
       （`Form.Size` / `Form.Location`），**可能**与真实矩形失配；
       而且它们都带 **SWP_SHOWWINDOW** → **"调用即等于显示窗口"**，
       在后台线程上调用时，"显示"可能**先于**"搬回屏幕内"生效，
       窗口就停在离屏位置（OFFSCREEN）—— 任务栏有图标、屏幕上却看不见。
       ⚠️ 保留这个函数名是为了兼容旧调用点；**新代码请直接用**
       `force_center_on_screen()` 或 `show_window_on_gui_thread()`。
       ⚠️ 当前**全仓库已无调用方**（api 的 window.center 已改走 force_center_on_screen）——
          留在这里只是当参考实现，别再从它那条托管属性路径抄代码。
       ⚠️ 尺寸：这里**只挪位置、不改尺寸**（`_center_on_screen_now` 默认 keep_size=True）。
          要改尺寸请用 `show_window_on_gui_thread()`（它会按"目标逻辑尺寸 × DPI"设定）。
    """
    force_center_on_screen(hwnd, window)


# ============ WebView2 浏览器快捷键（F11 → 全屏） ============
# ⚠️ 这些 .NET 委托对象必须**保持强引用**：pythonnet 里被 GC 掉的委托会让事件订阅
#    变成野指针（轻则静默失效，重则进程直接消失）。所以统一放模块级列表里。
_accel_refs = []
# F11 的双保险去抖：原生两条通道（AcceleratorKeyPressed / 窗体 KeyDown）理论上只会
# 触发一条，但万一同时触发就会"切了两次 = 看起来没反应"。0.35s 内只认第一次。
_accel_last = [0.0]


def _fire_toggle(callback):
    """去抖后触发一次全屏切换（回调可能来自 .NET 事件，异常绝不能跨边界抛）"""
    try:
        now = time.time()
        if now - _accel_last[0] < 0.35:
            return
        _accel_last[0] = now
        if callable(callback):
            callback()
    except Exception as exc:                                   # noqa: BLE001
        _log("warn", "外壳", "fullscreen", f"F11 全屏回调失败: {exc}")


def _core_controller(webview):
    """WinForms 的 `WebView2` 控件 → `CoreWebView2Controller`
    ⚠️ pywebview 6.2.1 用的 Microsoft.Web.WebView2.WinForms 控件**没有公开**
       AcceleratorKeyPressed（它只转发给私有字段 _coreWebView2Controller），
       所以先试公开属性、再反射私有字段；都拿不到就返回 None（调用方降级）。
    """
    for name in ("CoreWebView2Controller", "Controller"):
        try:
            value = getattr(webview, name, None)
            if value is not None:
                return value
        except Exception:
            pass
    try:
        from System.Reflection import BindingFlags
        flags = BindingFlags.NonPublic | BindingFlags.Instance
        field = webview.GetType().GetField("_coreWebView2Controller", flags)
        if field is not None:
            return field.GetValue(webview)
    except Exception:
        pass
    return None


def _install_accel_on_core(webview, core, on_f11) -> bool:
    """真正的安装动作（必须在 GUI 线程上、且 CoreWebView2 已就绪）
    返回是否至少装上了一条原生通道。日志口径：
      两条通道（窗体级 KeyDown / AcceleratorKeyPressed）要**分开记录**，
      只有真的订阅成功才说 AcceleratorKeyPressed 接管 ——
      否则会出现"先打印已接管、紧接着又打印订阅失败"的自相矛盾日志。
    """
    accel_ok = False
    form_ok = False
    try:
        # ① 浏览器加速键（F11/Ctrl+F/Ctrl+P…）交给我们/页面，而不是被 WebView2 自己吃掉。
        #    pywebview 里这一项被设成 `_state['debug']`，非 debug 时本来就是 False——
        #    但这是"F11 到底会不会到页面"的唯一开关，显式再钉一次，别指望别人。
        core.Settings.AreBrowserAcceleratorKeysEnabled = False
    except Exception as exc:                                   # noqa: BLE001
        _log("warn", "外壳", "fullscreen", f"关闭 WebView2 浏览器加速键失败: {exc}")
    # ② 直接在原生层接管 F11：Handled=True 之后页面**收不到**这个键，
    #    这样就不会出现"原生切一次 + 前端又切一次 = 两下等于没切"。
    controller = _core_controller(webview)
    if controller is None:
        _log("warn", "外壳", "fullscreen",
             "未取得 CoreWebView2Controller，F11 改由页面脚本处理")
        return accel_ok or form_ok
    try:
        from Microsoft.Web.WebView2.Core import (
            CoreWebView2AcceleratorKeyPressedEventHandler)

        def _on_key(sender, args):
            try:
                # KeyEventKind: KeyDown=0 / KeyUp=1 / SystemKeyDown=2 / SystemKeyUp=3
                if int(args.KeyEventKind) not in (0, 2):
                    return
                if int(args.VirtualKey) != VK_F11:
                    return
                args.Handled = True
                _fire_toggle(on_f11)
            except Exception:
                pass

        delegate = CoreWebView2AcceleratorKeyPressedEventHandler(_on_key)
        _accel_refs.append(delegate)
        controller.AcceleratorKeyPressed += delegate
        accel_ok = True
    except Exception as exc:                                   # noqa: BLE001
        _log("warn", "外壳", "fullscreen",
             f"订阅 WebView2 AcceleratorKeyPressed 失败（F11 仍会由页面脚本处理）: {exc}")
    # ③ 再兜一层：焦点不在 WebView2 上（比如点到标题栏）时的窗体级 F11
    try:
        from System.Windows.Forms import KeyEventHandler

        def _on_form_key(sender, args):
            try:
                if int(args.KeyCode) != VK_F11:
                    return
                args.Handled = True
                args.SuppressKeyPress = True
                _fire_toggle(on_f11)
            except Exception:
                pass

        form = getattr(webview, "FindForm", lambda: None)()
        if form is not None:
            form.KeyPreview = True
            form_delegate = KeyEventHandler(_on_form_key)
            _accel_refs.append(form_delegate)
            form.KeyDown += form_delegate
            form_ok = True
    except Exception:
        pass
    if accel_ok:
        _log("info", "外壳", "fullscreen",
             "F11 已由原生层接管：WebView2 AcceleratorKeyPressed"
             + ("（窗体按键通道也已安装）" if form_ok else ""))
    elif form_ok:
        _log("info", "外壳", "fullscreen",
             "F11 仅安装了窗体级原生通道（焦点在 WebView2 内时由页面脚本处理）")
    return accel_ok or form_ok


def focus_webview(window, attempts: int = 20, interval: float = 0.05) -> bool:
    """★ 把**键盘焦点**交回 WebView2（托盘/热键呼出后必须做这一步）

    ⚠️⚠️ 为什么必须有这个函数（"呼出搜索框没有变成输入状态"的根因）：
       pywebview 只在 `Form.Shown` 事件里给 WebView2 焦点
       （platforms/winforms.py:367-370：`on_shown` → `self.browser.webview.Focus()`）。
       ⚠️ 但**从托盘呼出**时，窗口**早就 Shown 过了**（只是被 hide 起来）——
          `Form.Show()` 不会再触发一次 Shown → **WebView2 永远拿不到焦点**。
       → 于是前端 `input.focus()` 虽然把 DOM 焦点设上了，但**键盘事件根本不在 WebView2 里**，
          用户看着光标可能都在框里，却敲不进字（或者敲了没反应）——
          这正是用户报的"呼出搜索框并不是输入状态"。

    ⚠️ 这里的做法：
       ① 先在 **GUI 线程**上把焦点给 WebView2 控件（`webview.Focus()`）；
       ② 再让窗口本身成为前台（`SetForegroundWindow`）—— 键盘输入是发给**前台窗口**的，
          窗口不在前台时，WebView2 就算有焦点也收不到按键；
       ③ WebView2 可能还没初始化完 → 用 `_subscribe_core_ready` 那套轮询等它就绪，
          最多等 attempts × interval（默认 1 秒）。
    """
    if not win32.IS_WINDOWS or window is None:
        return False

    def _get_webview():
        try:
            return getattr(getattr(window, "native", None), "webview", None)
        except Exception:
            return None

    def _focus_now():
        """在 GUI 线程上把焦点交给 WebView2 控件（真机实测：控件没焦点就收不到键盘）"""
        try:
            webview = _get_webview()
            if webview is None:
                return False
            # ⚠️ 控件本身要拿到焦点（它是 WinForms 控件，有自己的 Handle）
            try:
                webview.Focus()
            except Exception:
                pass
            # ⚠️ CoreWebView2 也要拿焦点（它才是真正渲染网页、接收键盘的那个）
            try:
                core = getattr(webview, "CoreWebView2", None)
                if core is not None:
                    controller = _core_controller(webview)
                    if controller is not None:
                        # MoveFocus 让 WebView2 把键盘焦点交给页面里的活动元素
                        controller.MoveFocus()
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _do():
        # ① WebView2 控件拿焦点
        _focus_now()
        # ② 窗口成为前台（键盘事件只发给前台窗口）
        try:
            hwnd = hwnd_of_window(window)
            if hwnd:
                bring_to_front(hwnd)
        except Exception:
            pass
        # ③ 焦点可能又被别的控件抢走 → 再点一次（MoveFocus 之后焦点才真正落到页面上）
        _focus_now()

    try:
        on_gui_thread(window, _do, timeout=2.0)
    except Exception:
        _do()

    # ⚠️ 再补两次**延时**的尝试：原生焦点是异步生效的，而调用方（托盘/热键）
    #    紧接着就会往前端推"聚焦搜索框"事件 —— 那时焦点可能还没到位。
    #    延时重试能覆盖这个竞态（240ms / 700ms 各一次）。
    for delay in (0.24, 0.7):
        def _later(d=delay):
            try:
                on_gui_thread(window, _focus_now, timeout=1.0)
            except Exception:
                pass
        timer = threading.Timer(delay, _later)
        timer.daemon = True
        timer.start()

    # ⚠️ WebView2 还没初始化完时（刚启动那几秒），控件拿不到焦点 →
    #    排一个轮询，等 CoreWebView2 就绪后再补一次（复用 apply_page_zoom 那套模式）。
    webview = _get_webview()
    if webview is not None:
        try:
            if getattr(webview, "CoreWebView2", None) is None:
                _subscribe_core_ready(window, webview, lambda: _focus_now(),
                                      attempts=attempts, interval=interval)
                return True
        except Exception:
            pass
    return True


def _subscribe_core_ready(window, webview, callback, attempts: int = 150,
                          interval: float = 0.2) -> bool:
    """WebView2 初始化完成后再装（那时 CoreWebView2 才存在）
    ⚠️ 真机实测教训：**不要**用 `CoreWebView2InitializationCompleted` 的 .NET 事件委托——
       那一刻 Microsoft.Web.WebView2 的程序集还没被加载，import 委托类型直接
       `cannot import name 'CoreWebView2InitializationCompletedEventHandler'`
       ⇒ 原生 F11 永远装不上（日志里是"原生接管失败，交给页面 JS 处理"）。
    ⚠️⚠️ **绝不能在后台线程直接读 `webview.CoreWebView2`**：那是 WinForms 控件的属性，
        跨线程访问会等 GUI 线程（pythonnet 会 marshal），实测会把 WebView2 初始化卡住
        —— 表现为程序启动后一直不加载前端页面。所以这里只做"定时把检查动作编组回
        GUI 线程"；属性访问与安装全部在 GUI 线程里进行。
    """
    def _check(remaining):
        """在 GUI 线程上检查一次（就绪 → 安装；否则安排下一次）"""
        try:
            core = getattr(webview, "CoreWebView2", None)
        except Exception as exc:                               # noqa: BLE001
            _log("warn", "外壳", "fullscreen", f"检查 WebView2 就绪失败: {exc}")
            return
        if core is not None:
            callback()
            return
        if remaining <= 0:
            _log("warn", "外壳", "fullscreen",
                 "等待 WebView2 初始化超时（30 秒），F11 改由页面脚本处理")
            return

        def _tick():
            on_gui_thread(window, lambda: _check(remaining - 1), timeout=3.0)

        timer = threading.Timer(interval, _tick)
        timer.daemon = True
        timer.start()

    def _boot():
        on_gui_thread(window, lambda: _check(int(attempts)), timeout=3.0)

    timer = threading.Timer(interval, _boot)
    timer.daemon = True
    timer.start()
    return True


def install_webview_accelerators(window, on_f11=None) -> bool:
    """在 **GUI 线程**上给 WebView2 装 F11 处理器 + 关掉浏览器加速键
    为什么必须在原生层做（而不是只靠前端 window keydown）：
        F11 是 WebView2 的**浏览器加速键**。用户实测按 F11 完全没反应、后端日志里
        连一条全屏记录都没有—— 说明 keydown 很可能没到页面。所以在原生层兜一层：
        `AreBrowserAcceleratorKeysEnabled=False` + `AcceleratorKeyPressed` 直接 Handled。
    ⚠️ 必须在 GUI 线程调用（`on_gui_thread`）：WebView2 的 COM 对象有线程亲和性。
    ⚠️ 拿不到控件/控制器都只是降级（记日志，不抛）：那种情况下 F11 仍可能经页面 JS 到达
       后端 `window.toggle_fullscreen`，两条路最终都汇聚到 shell.toggle_fullscreen()。
    返回是否至少装上了一条通道。
    """
    if not win32.IS_WINDOWS or window is None:
        return False
    done = {"ok": False}

    def _install():
        try:
            native = getattr(window, "native", None)
            webview = getattr(native, "webview", None)          # WinForms 的 WebView2 控件
            if webview is None:
                return
            core = getattr(webview, "CoreWebView2", None)
            if core is None:
                # 还没初始化完：安排 GUI 线程轮询等它就绪，再装（见 _subscribe_core_ready）
                _subscribe_core_ready(
                    window, webview,
                    lambda: _install_accel_on_core(webview, webview.CoreWebView2, on_f11))
                # 返回 True = "已经安排好接管"，避免启动日志误报成"原生接管失败"
                done["ok"] = True
                _log("info", "外壳", "fullscreen",
                     "已安排 WebView2 就绪后安装 F11 原生处理器")
                return
            done["ok"] = _install_accel_on_core(webview, core, on_f11)
        except Exception as exc:                               # noqa: BLE001
            _log("warn", "外壳", "fullscreen",
                 f"安装 WebView2 快捷键处理器失败（F11 改由页面脚本处理）: {exc}")

    try:
        on_gui_thread(window, _install, timeout=3.0)
    except Exception:
        return False
    return bool(done["ok"])
