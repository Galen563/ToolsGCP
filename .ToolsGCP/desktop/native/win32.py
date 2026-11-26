"""Win32 基础封装：常量、结构体、函数原型、以及"别让异常把进程带走"的装饰器。
⚠️ 所有 argtypes/restype 都必须显式声明：ctypes 默认按 32 位 int 处理返回值，64 位下
   窗口句柄会被截断（原版 `self_update.py:228` 那条注释踩的就是这个坑）。
"""

import ctypes
import functools
import sys
import threading
import traceback
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
else:                                            # pragma: no cover - 仅 Windows
    user32 = kernel32 = shell32 = gdi32 = dwmapi = None


LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint,
                             ctypes.c_size_t, ctypes.c_ssize_t)

# ---------- 窗口样式 ----------
GWL_STYLE = -16
GWL_EXSTYLE = -20
GWLP_WNDPROC = -4
GWLP_USERDATA = -21

WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_POPUP = 0x80000000

# 扩展样式（自绘托盘菜单 / 分层窗口用）
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
# WS_EX_APPWINDOW 强制"在任务栏有按钮"（有父/属主窗口时用来覆盖默认规则）。
# 和 TOOLWINDOW 成对使用：去掉任务栏按钮 = 清 APPWINDOW + 置 TOOLWINDOW；
# 恢复任务栏按钮 = 清 TOOLWINDOW + 置 APPWINDOW。改完必须 SetWindowPos 带
# SWP_FRAMECHANGED 才会重算任务栏按钮（见 frame.set_taskbar_hidden）。
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040

# ---------- 消息 ----------
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
# 图标：WM_SETICON 给窗口设图标（任务栏/Alt+Tab 读的就是它），WM_GETICON 回读做自检
WM_SETICON = 0x0080
WM_GETICON = 0x007F
WM_QUIT = 0x0012
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_GETMINMAXINFO = 0x0024
# 带超时的 SendMessage 标志：对端线程不泵消息时不要一直等下去
SMTO_ABORTIFHUNG = 0x0002
WM_NCLBUTTONDOWN = 0x00A1
WM_SYSCOMMAND = 0x0112
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_HOTKEY = 0x0312
WM_APP = 0x8000
WM_USER = 0x0400
WM_NULL = 0x0000
WM_MOUSEMOVE = 0x0200
WM_ACTIVATE = 0x0006
WM_KILLFOCUS = 0x0008
WM_KEYDOWN = 0x0100
VK_ESCAPE = 0x1B

# ShowWindow 命令
SW_HIDE = 0
SW_SHOWNOACTIVATE = 5

SC_MINIMIZE = 0xF020
SC_MAXIMIZE = 0xF030
SC_RESTORE = 0xF120
SC_CLOSE = 0xF060

# ---------- 窗口图标（WM_SETICON / 窗口类图标）----------
ICON_SMALL = 0            # 标题栏/任务栏小图标（SM_CXSMICON 尺寸）
ICON_BIG = 1              # Alt+Tab / 任务栏大图标（SM_CXICON 尺寸）
ICON_SMALL2 = 2           # 另一个小图标槽（Win 不常用，回读时兜底看）
IMAGE_ICON = 1
LR_DEFAULTCOLOR = 0
LR_SHARED = 0x8000
# SetClassLongPtr / GetClassLongPtr 的索引（**不是** GWL_*，是 GCLP_*）
GCLP_HICON = -14
GCLP_HICONSM = -34
GCLP_ICON_SM = -34
# GetSystemMetrics 索引：系统图标尺寸
SM_CXICON = 11
SM_CYICON = 12
SM_CXSMICON = 49
SM_CYSMICON = 50

# ---------- MessageBox（原生确认框）----------
# ⚠️ 这些值是 Win32 API 的固定约定，不能自己"优化"：
#    MB_* 是 uType 的位标志，IDYES/IDNO 是返回值（不是按钮序号）。
MB_OK = 0x00
MB_YESNO = 0x04
MB_ICONQUESTION = 0x20
MB_ICONWARNING = 0x30
MB_DEFBUTTON1 = 0x000
MB_DEFBUTTON2 = 0x100        # 默认焦点落在"否"（危险操作的安全默认值）
IDOK = 1
IDCANCEL = 2
IDYES = 6
IDNO = 7

# ---------- 命中测试 ----------
HTTRANSPARENT = -1
HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

# ---------- 热键 ----------
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# ---------- 托盘（Shell_NotifyIcon）----------
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETFOCUS = 3
NIM_SETVERSION = 4

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_STATE = 0x00000008
NIF_INFO = 0x00000010
NIF_GUID = 0x00000020
NIF_REALTIME = 0x00000040
NIF_SHOWTIP = 0x00000080

NIIF_INFO = 0x00000001
NIIF_WARNING = 0x00000002
NIIF_ERROR = 0x00000003

# ---------- DWM ----------
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    """⚠️ 必须声明 rgrc[3] 三份矩形：NCCALCSIZE 的 lParam 指向它（wParam=True 时）"""
    _fields_ = [("rgrc", RECT * 3),
                ("lppos", ctypes.c_void_p)]


class MINMAXINFO(ctypes.Structure):
    _fields_ = [("ptReserved", POINT), ("ptMaxSize", POINT), ("ptMaxPosition", POINT),
                ("ptMinTrackSize", POINT), ("ptMaxTrackSize", POINT)]


class WINDOWPLACEMENT(ctypes.Structure):
    """GetWindowPlacement/SetWindowPlacement 的参数结构

    ⚠️ 为什么必须用它（而不是自己拿 GetWindowRect 记一个矩形）：
       对**最大化**窗口来说，窗口矩形是系统外扩过边框的（日志实测：1920x1032 的工作区
       → 窗口矩形 (-8,-8,1928,1040)），而系统真正记住的「还原点」是
       rcNormalPosition（普通态矩形）。F11 全屏退出时若拿窗口矩形去 SetWindowPos，
       那一刻窗口不是最大化 → 这一步会把还原点**改写成最大化矩形**，之后点最大化/
       还原就再也回不到原来的窗口大小（用户报的"窗口大小被固定死全屏大小 / 伪全屏"）。
       GetWindowPlacement 的 rcNormalPosition + showCmd 才是官方口径，存下来原样塞回去
       （SetWindowPlacement）就能同时处理"回普通态"和"回最大化"两种情况。
    ⚠️ length 必须由调用方先写 sizeof（系统靠它判版本，写 0 直接失败）。
    """
    _fields_ = [("length", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("showCmd", wintypes.UINT), ("ptMinPosition", POINT),
                ("ptMaxPosition", POINT), ("rcNormalPosition", RECT)]


class SIZE(ctypes.Structure):
    """分层窗口 UpdateLayeredWindow 的尺寸参数"""
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    """UpdateLayeredWindow 的混合参数（ AlphaFormat=1 表示源位图带 alpha）"""
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


def _declare():
    """显式声明所有函数原型（64 位下必须，见模块 docstring）"""
    if not IS_WINDOWS:
        return

    u, k, s, g, d = user32, kernel32, shell32, gdi32, dwmapi

    k.GetModuleHandleW.restype = wintypes.HMODULE
    k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k.GetCurrentThreadId.restype = wintypes.DWORD
    k.GetCurrentThreadId.argtypes = []

    u.DefWindowProcW.restype = LRESULT
    u.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                 ctypes.c_size_t, ctypes.c_ssize_t]
    u.CallWindowProcW.restype = LRESULT
    u.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, ctypes.c_uint,
                                  ctypes.c_size_t, ctypes.c_ssize_t]
    u.RegisterClassW.restype = wintypes.ATOM
    u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    u.UnregisterClassW.restype = wintypes.BOOL
    u.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                  wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                  wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    u.DestroyWindow.restype = wintypes.BOOL
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.GetWindowLongW.restype = ctypes.c_long
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowLongW.restype = ctypes.c_long
    u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    u.GetWindowLongPtrW.restype = ctypes.c_void_p
    u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowLongPtrW.restype = ctypes.c_void_p
    u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    u.SetWindowPos.restype = wintypes.BOOL
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u.GetWindowRect.restype = wintypes.BOOL
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    u.GetClientRect.restype = wintypes.BOOL
    u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    u.ClientToScreen.restype = wintypes.BOOL
    u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    u.ScreenToClient.restype = wintypes.BOOL
    u.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    u.GetMessageW.restype = ctypes.c_int
    u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                              ctypes.c_uint, ctypes.c_uint]
    u.PeekMessageW.restype = wintypes.BOOL
    u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
    u.TranslateMessage.restype = wintypes.BOOL
    u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u.DispatchMessageW.restype = LRESULT
    u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u.PostMessageW.restype = wintypes.BOOL
    u.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, ctypes.c_size_t,
                               ctypes.c_ssize_t]
    u.SendMessageW.restype = LRESULT
    u.SendMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, ctypes.c_size_t,
                               ctypes.c_ssize_t]

    # 带超时的 SendMessage：向「可能正忙」的窗口问它自己的最小尺寸
    # （WM_GETMINMAXINFO）只能用这个，裸 SendMessageW 在对端不泵消息时
    # 会把调用线程挂住 —— 而调用方正是 pywebview 的 JS 桥线程。
    u.SendMessageTimeoutW.restype = ctypes.c_size_t
    u.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, ctypes.c_void_p,
                                      wintypes.UINT, wintypes.UINT,
                                      ctypes.POINTER(ctypes.c_size_t)]
    u.PostQuitMessage.restype = None
    u.PostQuitMessage.argtypes = [ctypes.c_int]
    u.RegisterHotKey.restype = wintypes.BOOL
    u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
    u.UnregisterHotKey.restype = wintypes.BOOL
    u.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    u.ReleaseCapture.restype = wintypes.BOOL
    u.ReleaseCapture.argtypes = []
    u.SetForegroundWindow.restype = wintypes.BOOL
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.BringWindowToTop.restype = wintypes.BOOL
    u.BringWindowToTop.argtypes = [wintypes.HWND]
    u.SetActiveWindow.restype = wintypes.HWND
    u.SetActiveWindow.argtypes = [wintypes.HWND]
    u.ShowWindow.restype = wintypes.BOOL
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.IsWindow.restype = wintypes.BOOL
    u.IsWindow.argtypes = [wintypes.HWND]
    u.IsWindowVisible.restype = wintypes.BOOL
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsZoomed.restype = wintypes.BOOL
    u.IsZoomed.argtypes = [wintypes.HWND]
    u.IsIconic.restype = wintypes.BOOL
    u.IsIconic.argtypes = [wintypes.HWND]
    # 窗口位置/状态的官方口径（还原点 = rcNormalPosition，不是窗口矩形）
    u.GetWindowPlacement.restype = wintypes.BOOL
    u.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
    u.SetWindowPlacement.restype = wintypes.BOOL
    u.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetForegroundWindow.argtypes = []
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.AttachThreadInput.restype = wintypes.BOOL
    u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    # 锁定/解锁「前台窗口」的切换权（Ctrl+左键后台开链接要靠它，见 shell.py 注释）
    u.LockSetForegroundWindow.restype = wintypes.BOOL
    u.LockSetForegroundWindow.argtypes = [wintypes.UINT]
    u.MonitorFromWindow.restype = wintypes.HMONITOR
    u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    u.GetMonitorInfoW.restype = wintypes.BOOL
    u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    u.SystemParametersInfoW.restype = wintypes.BOOL
    u.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                        wintypes.LPVOID, wintypes.UINT]
    u.GetCursorPos.restype = wintypes.BOOL
    u.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    # 物理按键状态：拖动兜底要判断"用户此刻还按着左键吗"（与消息队列无关）
    u.GetAsyncKeyState.restype = ctypes.c_short
    u.GetAsyncKeyState.argtypes = [ctypes.c_int]
    u.GetKeyState.restype = ctypes.c_short
    u.GetKeyState.argtypes = [ctypes.c_int]
    u.EnumWindows.restype = wintypes.BOOL
    u.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    u.GetWindowTextLengthW.restype = ctypes.c_int
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextW.restype = ctypes.c_int
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetClassNameW.restype = ctypes.c_int
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.LoadImageW.restype = wintypes.HANDLE
    u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, ctypes.c_uint,
                             ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u.CreateIconFromResourceEx.restype = wintypes.HICON
    u.CreateIconFromResourceEx.argtypes = [wintypes.LPVOID, wintypes.DWORD,
                                           wintypes.BOOL, wintypes.DWORD,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u.DestroyIcon.restype = wintypes.BOOL
    u.DestroyIcon.argtypes = [wintypes.HICON]
    # 窗口图标：设置/回读 + 窗口类图标（dlgclass 用 GCLP_*，句柄走 LONG_PTR）
    u.GetSystemMetrics.restype = ctypes.c_int
    u.GetSystemMetrics.argtypes = [ctypes.c_int]
    u.GetClassLongPtrW.restype = ctypes.c_void_p
    u.GetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetClassLongPtrW.restype = ctypes.c_void_p
    u.SetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    u.CreatePopupMenu.restype = wintypes.HMENU
    u.CreatePopupMenu.argtypes = []
    u.AppendMenuW.restype = wintypes.BOOL
    u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t,
                              wintypes.LPCWSTR]
    u.TrackPopupMenu.restype = ctypes.c_int
    u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                 ctypes.c_void_p]
    u.DestroyMenu.restype = wintypes.BOOL
    u.DestroyMenu.argtypes = [wintypes.HMENU]
    u.SetMenuDefaultItem.restype = wintypes.BOOL
    u.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
    # 原生确认框（退出时"还有下载任务在跑"那种）
    # ⚠️ 必须显式声明：MessageBoxW 的返回值是 int（按钮 ID），
    #    不声明的话 ctypes 默认按 32 位 int 处理，倒不会截断，但传 LPCWSTR 参数时
    #    默认会把 Python 字符串当 wchar* 处理（没问题）—— 显式声明是为了不出意外。
    u.MessageBoxW.restype = ctypes.c_int
    u.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                              wintypes.UINT]
    # 分层窗口（自绘托盘菜单用）
    u.UpdateLayeredWindow.restype = wintypes.BOOL
    u.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC,
                                      ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
                                      wintypes.HDC, ctypes.POINTER(POINT),
                                      ctypes.c_uint,
                                      ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
    u.LoadCursorW.restype = wintypes.HANDLE
    # ⚠️ 第二个参数是 **MAKEINTRESOURCE**（整数资源 ID，例如 IDC_ARROW=32512），
    #    不是字符串指针。以前写成 LPCWSTR 会让 LoadCursorW(None, 32512) 直接抛
    #    ArgumentError → 被 _register_class() 的 except 吞掉 → 托盘菜单永远建不出来。
    u.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]

    s.Shell_NotifyIconW.restype = wintypes.BOOL
    s.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
    s.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    s.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    s.ShellExecuteW.restype = wintypes.HINSTANCE
    s.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]

    d.DwmSetWindowAttribute.restype = ctypes.c_long
    d.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                        wintypes.LPVOID, wintypes.DWORD]
    d.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
    d.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.c_void_p]


_declare()


def last_error() -> int:
    """最近一次 Win32 错误码（ctypes 的 use_last_error 版本）"""
    try:
        return ctypes.get_last_error()
    except Exception:
        return 0


def message_box(hwnd, text, title, flags=MB_OK) -> int:
    """弹原生 MessageBox；返回按钮 ID（IDYES=6 / IDNO=7）
    为什么用原生框而不是前端的 HTML 弹窗：
        退出确认发生在"前端可能正在销毁"的时刻，走 WebView 的弹窗容易和
        evaluate_js 竞态（AGENTS 第 8 条）；原生 MessageBox 走 Win32 消息循环，
        不碰 WebView2，稳。
    ⚠️ 非 Windows 平台（开发机 / 单测）直接返回 IDYES —— 不能因为弹不出框就把用户卡住。
    ⚠️ 任何异常都按"用户同意"处理：宁可放行也不要让程序退不出去。
    """
    if not IS_WINDOWS:
        return IDYES
    try:
        return int(user32.MessageBoxW(hwnd or None, str(text), str(title), int(flags)))
    except Exception:
        return IDYES


def current_thread_messages_pump(stop_event=None):
    """在当前线程跑一个标准消息循环（托盘/热键线程用）
    ⚠️ 必须在**创建窗口的那个线程**里跑：WM_HOTKEY 与托盘回调都投递到该线程的消息队列。
    """
    if not IS_WINDOWS:
        return
    msg = wintypes.MSG()
    while True:
        ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if ret <= 0:                       # 0 = WM_QUIT，-1 = 错误
            break
        if stop_event is not None and stop_event.is_set():
            break
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def safe(fallback=None, label: str = ""):
    """把函数包成"绝不抛"（原生壳里的任何异常都不该带走界面）
    ⚠️ 与原版 `pymodels` 里的写法一致：失败只记日志，不改变调用方语义。
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:       # noqa: BLE001 - 兜底
                try:
                    from pymodels.utils.logger import log
                    log.err("外壳", "native",
                            f"{label or func.__name__} 失败: {exc}\n"
                            + traceback.format_exc())
                except Exception:
                    pass
                return fallback
        return wrapper
    return decorator


def wndproc_guard(func):
    """WndProc 专用守卫：异常绝对不能逃出窗口过程（会直接 terminate 进程）
    ⚠️ 必须用 `*args` 转发：如果显式写成 (hwnd, msg, wparam, lparam)，这个包装器就成了
       "只接受 4 个参数"的普通函数；被 `WNDPROC(self._wndproc)` 绑到实例上之后会变成
       "self + 4 个实参 = 5 个"，ctypes 一回调就是 TypeError（实测踩过：
       `_wndproc() takes 4 positional arguments but 5 were given`，且 ctypes 只打印
       "Exception ignored"，窗口照建但所有消息都被吞掉）。
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:           # noqa: BLE001
            try:
                from pymodels.utils.logger import log
                msg = args[1] if len(args) > 1 else "?"
                log.err("外壳", "wndproc",
                        f"窗口过程异常 msg=0x{int(msg) & 0xFFFFFFFF:04X}: {exc}")
            except Exception:
                pass
            # ⚠️⚠️ 兜底**必须回到系统默认过程**，不能返回 0。
            #   教训（2026-11-23 真实故障）：窗口过程里写错一个常量名 →
            #   NameError → 这里吞掉异常并 return 0 → **每一条窗口消息都被丢弃**：
            #     · WM_CLOSE 被吞 → Form.Close() 永远不完成 → 主线程卡在
            #       webview.start() → 进程退不出去（托盘点了"退出"还剩一个 python 进程）；
            #     · WM_NCCALCSIZE/WM_SIZE 被吞 → 窗口过程彻底失效 →
            #       **任务栏没有窗口、只有托盘**（用户原话："程序打不开"）。
            #   DefWindowProcW 是"没接住这条消息"的**正确**去处：交给系统默认值，
            #   窗口照样能显示、能关闭。return 0 只对个别消息成立，不能当通用兜底。
            try:
                hwnd, msg_id = args[0], args[1]
                wparam = args[2] if len(args) > 2 else 0
                lparam = args[3] if len(args) > 3 else 0
                return user32.DefWindowProcW(hwnd, msg_id, wparam, lparam)
            except Exception:
                return 0
    return wrapper


def dpi_scale(hwnd) -> float:
    """窗口所在显示器的缩放比例（96 DPI = 1.0）
    ⚠️ pywebview 的 API 全部按**逻辑像素**收发，Win32 这边拿到的都是物理像素，换算必须
       用同一个值，否则高 DPI 下窗口尺寸/位置会整体缩小一圈。
    """
    try:
        dpi = user32.GetDpiForWindow(hwnd)
        if dpi:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def system_dpi_scale() -> float:
    """**进程当前坐标系**的缩放比例（还没有任何窗口时用这个）。

    ⚠️ 为什么不用 GetDpiForWindow(0)：那条要一个已存在的句柄；启动画面在建窗之前
       就得把 logo 尺寸算对，只能先问系统。GetDpiForSystem 是 Win10+ 的 API，
       老系统 / 导出缺失时退回 DC 的 LOGPIXELSX，再不行就 1.0 —— 绝不抛。
    ⚠️ 前提是进程 DPI awareness 已经定下来（见本模块 ensure_dpi_awareness）：
       awareness 没确定之前，这个值随时会被系统改写，算出来的尺寸就不作数。
    """
    try:
        dpi = user32.GetDpiForSystem()
        if dpi:
            return dpi / 96.0
    except Exception:
        pass
    try:
        gdi32 = ctypes.windll.gdi32
        hdc = user32.GetDC(None)
        try:
            dpi = gdi32.GetDeviceCaps(hdc, 88)          # LOGPIXELSX
            if dpi:
                return dpi / 96.0
        finally:
            user32.ReleaseDC(None, hdc)
    except Exception:
        pass
    return 1.0


def ensure_dpi_awareness() -> str:
    """把进程的 DPI awareness **定下来**，返回一句给日志看的实际状态。

    ⚠️⚠️ 这是"启动画面先在屏幕中央、随后突然跳到别处"那个用户反馈的**正解**，
       改这行之前务必看懂为什么（别再当成居中算法算错了）：
         ① pywebview 6.2.1 的 winforms 后端是在 **webview.start() 里面**才调
            `SetProcessDPIAware()`（webview/platforms/winforms.py:820，master 分支）。
         ② 启动画面是在 start() **之前**、用自己那条线程建的裸 Win32 分层窗口。
            建窗那一刻进程还是 DPI-Unaware → 我们给的坐标被系统**虚拟化**
            （除以缩放比），DWM 再把整块画面拉伸，看上去是居中的。
         ③ 紧接着 webview.start() 把进程切成 System-DPI-Aware → 同一组坐标从此
            按**物理像素**解释 → 已存在窗口的位置和尺寸同时变了含义
            → 用户看到"画面先在正中间，然后猛地跳到偏左上/右上角"。
         ④ 100% 缩放的机器上虚拟化是恒等操作，翻转前后一模一样 →
            **开发者本机永远不复现**，只有 125%/150% 缩放的用户会看到。
       修法：在**建任何窗口之前**，先调用和 pywebview **完全同一个 API**。
       这样坐标系从第一帧起就是物理像素、再不会中途翻转；而 pywebview 后面那次
       同名调用会因为"已经设置过"而返回 False 并被它自己忽略 —— 也就是说
       **进程最终状态与不改之前完全一样**：主窗口的 _ui_scale、WebView2 的
       ZoomFactor、frame.apply_page_zoom 那一整套缩放语义都不受任何影响。
       （这是刻意选的保守做法：只提前"什么时候定下来"，不换"定成什么"。
        想升级 Per-Monitor v2 必须整条主窗口缩放链路重新验证，别顺手改。）
       返回值只给日志用；任何异常都吞掉（顶多少一层保护，不能让它挡住启动）。
    """
    try:
        if user32.SetProcessDPIAware():
            return "已置 System-DPI-Aware"
        return "SetProcessDPIAware 返回 False（awareness 已由别处定下，保持现状）"
    except Exception as exc:                            # noqa: BLE001
        return f"SetProcessDPIAware 异常（忽略）: {exc}"


def work_area(hwnd=None):
    """工作区（不含任务栏）的物理像素矩形 (left, top, right, bottom)"""
    if hwnd:
        try:
            hmon = user32.MonitorFromWindow(hwnd, 2)          # NEAREST
            if hmon:
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                    r = info.rcWork
                    return (r.left, r.top, r.right, r.bottom)
        except Exception:
            pass
    r = RECT()
    try:
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)   # SPI_GETWORKAREA
        return (r.left, r.top, r.right, r.bottom)
    except Exception:
        return (0, 0, 1920, 1080)


def rect_of(hwnd):
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def is_thread_alive(thread) -> bool:
    return bool(thread is not None and thread.is_alive())


# LockSetForegroundWindow 的两个计数值（WinUser.h：LSFW_LOCK=1 / LSFW_UNLOCK=2）
LSFW_LOCK = 1
LSFW_UNLOCK = 2


def lock_foreground() -> bool:
    """锁住前台切换权：返回 TRUE 后**其它进程**调用 SetForegroundWindow 一律无效。

    为什么需要它（Ctrl+左键顽固 bug 的第二半边，用户说「修了很多次还是没解决」）：
      `ShellExecuteW(..., SW_SHOWNOACTIVATE)` 只约束「外壳启动进程时」要不要激活，
      而浏览器**本来就有实例在跑**时，"open" 动词是 IPC/DDE 转交给那个已有进程的，
      新窗口的显示方式由浏览器自己定 —— Chrome/Edge 都会在此刻自己 SetForegroundWindow
      把自己提到最前。所以 nShow=3 根本管不住它，这就是「有时」的来源：没有浏览器实例
      时正常，有实例时照样抢前台。
      解法是在这次打开动作期间**禁止任何进程改前台**：浏览器抢不到前台，就只能留在
      我们窗口的下面一层；随后解锁。全程不主动调用 SetForegroundWindow，
      所以不会出现旧版 `_reclaim()` 那种「闪一下把窗口唤回来」的观感（那是用户明确
      否掉的方案，别再走回头路）。
    """
    if user32 is None:
        return False
    try:
        return bool(user32.LockSetForegroundWindow(LSFW_LOCK))
    except Exception:
        return False


def unlock_foreground() -> None:
    """解除 lock_foreground() 的锁定（幂等；失败不抛，反正系统会在下次输入时自动放行）。"""
    if user32 is None:
        return
    try:
        user32.LockSetForegroundWindow(LSFW_UNLOCK)
    except Exception:
        pass
