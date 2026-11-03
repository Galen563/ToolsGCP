"""系统托盘（Shell_NotifyIcon）+ 独立的 Win32 消息线程。
========== 为什么自己写 ==========
pywebview 没有任何托盘 API。原版用的是 `QSystemTrayIcon` + 自绘圆角菜单（`ui/tray_menu.py`，
圆角 12 / 行高 30 / 图标 14 / 5 项含分隔线）。这里用 Shell_NotifyIcon 复刻同一套菜单结构与
文案（含分隔线与"任务栏在下就往上弹"的位置计算），视觉跟随系统。
⚠️ 托盘回调（鼠标消息）和热键 WM_HOTKEY 都必须由**同一个线程**的消息循环分发：
   Shell_NotifyIcon 的 uCallbackMessage 是投递到登记时那个 hWnd 所属线程的队列。
   所以这里自建一条叫 ToolsGCP-native 的线程：建窗口 → 登记图标/热键 → GetMessage 循环。
⚠️ 图标必须是 HICON：Windows 只认图标资源。原版直接 setWindowIcon(QIcon("logo.png"))。
   这里把 PNG 原样交给 CreateIconFromResourceEx（Vista+ 支持 PNG 压缩图标，实测 16~64px
   都能得到正确的 32bpp + alpha 位图）。
"""

import ctypes
import threading
from ctypes import wintypes

from . import traymenu, win32
from .win32 import (NIF_ICON, NIF_MESSAGE, NIF_TIP, NIF_INFO, NIM_ADD, NIM_DELETE,
                    NIM_MODIFY, WM_APP, WM_HOTKEY, WM_LBUTTONUP, WM_LBUTTONDBLCLK,
                    WM_RBUTTONUP, wndproc_guard, WNDPROC)

WM_TRAY = WM_APP + 1
# ⚠️ 第二个进程（用户手动双击 exe）用这条消息"唤醒"藏在托盘里的实例：
#    「启动时最小化到托盘」生效后主窗口从没 show 过（也不可见），
#    ToolsGCP.pyw 那套 EnumWindows + IsWindowVisible 找不到任何窗口，
#    表现就是"双击图标没反应"。所以按托盘窗口类名找到它、投这条消息。
#    ⚠️ 数值同时写在 ToolsGCP.pyw 里（那边不能 import desktop，启动早期就得用），
#       改这里必须同步改那里。
WM_TRAY_WAKE = WM_APP + 3
TRAY_WINDOW_CLASS = "ToolsGCP_TrayWindow"
TRAY_ID = 1

MENU_ID_HOME = 1001
MENU_ID_SEARCH = 1002
MENU_ID_AI = 1003
MENU_ID_EXIT = 1005

TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TPM_BOTTOMALIGN = 0x0020
TPM_TOPALIGN = 0x0000
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
SW_HIDE = 0
SW_SHOW = 5
SW_RESTORE = 9


# ---------- 自绘菜单图标用的小工具（GDI+ 画 32×32 再缩到 14） ----------
def _menu_ink_color(danger: bool = False):
    """图标颜色，**必须和原版 `themed_icon()` 一致**：
    原版 `ui/tray_menu.py` → `widgets/app_card.py:529 themed_icon()`：
        深色 = QColor("#FFFFFF")（纯白）
        浅色 = QColor("#1F2329")
    这里以前写的是 #E8E8E8（那是**文字**色），比原版暗一档；
    实测原版深色菜单里图标墨迹最亮像素就是 (254,254,254) ≈ 纯白。
    danger=True → 用 traymenu 主题里的 danger 色（和退出文字同一个色源），
    这样即使 traymenu 的染色链路（ColorMatrix / 纯 GDI 兜底）出问题，
    图标本身就已经是红的。
    """
    try:
        from System.Drawing import Color
        if danger:
            rgba = (traymenu.DARK if _MENU_DARK[0] else traymenu.LIGHT).get("danger")
            if rgba:
                return Color.FromArgb(int(rgba[3]), int(rgba[0]), int(rgba[1]), int(rgba[2]))
        if _MENU_DARK[0]:
            return Color.FromArgb(255, 255, 255)
        return Color.FromArgb(31, 35, 41)
    except Exception:
        from System.Drawing import Color
        return Color.White


def _png_format():
    """PNG 编码器（GDI+ Save 需要 ImageFormat）"""
    try:
        from System.Drawing.Imaging import ImageFormat
        return ImageFormat.Png
    except Exception:
        return None


# 当前菜单主题深浅（_menu_icon 上色用；托盘线程写、读，简单布尔足够）
_MENU_DARK = [True]


class NOTIFYICONDATAW(ctypes.Structure):
    """⚠️ 结构体必须与系统头文件一致：cbSize 用本结构体实际大小（Vista+ 布局）"""
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", ctypes.c_uint), ("uFlags", ctypes.c_uint),
                ("uCallbackMessage", ctypes.c_uint), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", ctypes.c_uint), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def png_to_hicon(png_bytes: bytes, size: int = 32):
    """PNG 字节 → HICON（走 Vista+ 的 PNG 压缩图标路径）
    ⚠️ 不能用 ICO 容器包一层再交给它：实测那样返回 NULL（CreateIconFromResourceEx 期待的是
       资源段数据，裸 PNG 恰好是合法输入）。这里直接传原始 PNG 字节。
    """
    if not png_bytes:
        return None
    buf = ctypes.create_string_buffer(png_bytes, len(png_bytes))
    return win32.user32.CreateIconFromResourceEx(
        buf, len(png_bytes), True, 0x00030000, size, size, 0)


class TrayIcon:
    """托盘图标 + 右键菜单 + 气泡提示
    用法：
        tray = TrayIcon(icon_png=..., labels={"home": ..., "search": ...},
                        on_select={"home": cb, "search": cb, "ai": cb, "exit": cb})
        tray.start()
        tray.notify("ToolsGCP", "程序已隐藏到托盘")
        tray.stop()
    """

    def __init__(self, icon_png_path: str = "", labels=None, on_select=None,
                 tooltip: str = "ToolsGCP", settings_manager=None,
                 font_family: str = ""):
        self.icon_png_path = icon_png_path
        self.labels = dict(labels or {})
        self.on_select = dict(on_select or {})
        # 原生线程建好窗口后回调一次（热键必须在这里登记，见 invoke）
        self.on_ready_native = None
        self.on_hotkey = None
        self.tooltip = tooltip or "ToolsGCP"
        # ⚠️ 菜单配色要跟着**程序里的主题设置**走（不只是系统主题）：
        #    _is_dark() 只有拿到 settings_manager 才能读到"深色主题/浅色主题"。
        #    以前这个字段没人赋值，_is_dark() 永远走注册表 → 用户手动选了浅色主题时
        #    托盘菜单还是深色的。
        self._settings_manager = settings_manager
        self._menu_font_family = str(font_family or "")

        self._thread = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._hwnd = 0
        self._hicon = None
        self._hicon_small = None
        self._nid = None
        self._lock = threading.RLock()
        self._ok = False
        self._pending_notify = []
        # 想在这条线程上执行的任务（热键注册必须在创建窗口的线程里做，见 invoke()）
        self._jobs = []
        self._jobs_lock = threading.Lock()
        self._wake_msg = WM_APP + 2

    # ---------- 生命周期 ----------
    def start(self, timeout: float = 5.0) -> bool:
        if not win32.IS_WINDOWS:
            return False
        if self._thread is not None and self._thread.is_alive():
            return self._ok
        self._thread = threading.Thread(target=self._run, name="ToolsGCP-native",
                                        daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self._ok

    def stop(self, timeout: float = 2.0):
        if not win32.IS_WINDOWS:
            return
        self._stop.set()
        if self._hwnd:
            try:
                win32.user32.PostMessageW(self._hwnd, 0x0010, 0, 0)     # WM_CLOSE
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def hwnd(self) -> int:
        return self._hwnd

    @property
    def available(self) -> bool:
        return bool(self._ok)

    # ---------- 线程主体 ----------
    def _run(self):
        try:
            self._create_window()
        except Exception as exc:                          # noqa: BLE001
            # ⚠️ 以前这里是裸 `return`：托盘窗口建不出来时**一个日志都没有**，
            #    外部只看到 available=False，永远查不出原因。
            self._log("err", f"创建托盘原生窗口失败，托盘不可用: "
                             f"{type(exc).__name__}: {exc}")
            self._ready.set()
            return
        try:
            # ⚠️ 图标与热键的登记都必须在**这条线程**（见 invoke 的说明）
            self._add_icon()
            if callable(self.on_ready_native):
                try:
                    self.on_ready_native(self)
                except Exception as exc:                  # noqa: BLE001
                    self._log("err", f"托盘原生线程就绪回调失败: "
                                     f"{type(exc).__name__}: {exc}")
            self._ready.set()
            for title, text in list(self._pending_notify):
                self._notify_impl(title, text)
            self._pending_notify.clear()
            self._message_loop()
        except Exception as exc:                          # noqa: BLE001
            self._log("err", f"托盘消息线程异常退出: {type(exc).__name__}: {exc}")
        finally:
            self._ready.set()
            self._cleanup()

    @staticmethod
    def _log(level: str, message: str):
        try:
            from pymodels.utils.logger import log
            getattr(log, level, log.info)("外壳", "tray", message)
        except Exception:
            pass

    @wndproc_guard
    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = int(lparam) & 0xFFFF
            if event == WM_RBUTTONUP:
                self._show_menu()
                return 0
            if event == WM_LBUTTONDBLCLK:
                self._invoke("home")
                return 0
            return 0
        if msg == WM_HOTKEY:
            handler = getattr(self, "on_hotkey", None)
            if callable(handler):
                handler(int(wparam))
            return 0
        if msg == WM_TRAY_WAKE:
            # 第二个进程要求唤醒：等价于托盘菜单里的「显示主窗口」。
            # ⚠️ 走 _invoke（独立线程）而不是就地执行：show_window 会编组到
            #    WinForms 的 GUI 线程，就地等消息会把**托盘线程**卡住。
            self._invoke("home")
            return 0
        if msg == self._wake_msg:
            self._drain_jobs()
            return 0
        if msg == win32.WM_CLOSE:
            win32.user32.DestroyWindow(hwnd)
            return 0
        if msg == win32.WM_DESTROY:
            win32.user32.PostQuitMessage(0)
            return 0
        return win32.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _create_window(self):
        hinst = win32.kernel32.GetModuleHandleW(None)
        cls = win32.WNDCLASSW()
        self._proc = WNDPROC(self._wndproc)
        cls.lpfnWndProc = self._proc
        cls.hInstance = hinst
        cls.lpszClassName = TRAY_WINDOW_CLASS
        cls.hCursor = None
        win32.user32.RegisterClassW(ctypes.byref(cls))
        # ⚠️ 必须有真实 HWND（不能是 HWND_MESSAGE）：托盘图标要一个能收鼠标回调的窗口。
        self._hwnd = win32.user32.CreateWindowExW(
            0, "ToolsGCP_TrayWindow", "ToolsGCP Tray", win32.WS_POPUP,
            0, 0, 0, 0, None, None, hinst, None)
        if not self._hwnd:
            raise OSError(f"创建托盘窗口失败: {win32.last_error()}")

    def _load_icons(self):
        if self._hicon is not None:
            return
        data = b""
        try:
            if self.icon_png_path:
                with open(self.icon_png_path, "rb") as handle:
                    data = handle.read()
        except Exception:
            data = b""
        if data:
            self._hicon = png_to_hicon(data, 32)
            self._hicon_small = png_to_hicon(data, 16)
        if not self._hicon:
            # 兜底：用进程默认图标（等同原版"窗口图标没准备好"的兜底路径）
            try:
                self._hicon = win32.user32.LoadIconW(None, ctypes.c_wchar_p(32512))
            except Exception:
                self._hicon = None

    def _add_icon(self):
        self._load_icons()
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = TRAY_ID
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._hicon or 0
        nid.szTip = self.tooltip[:127]
        ok = bool(win32.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        self._nid = nid
        self._ok = ok
        if not ok:
            # 已经存在（上次崩溃没清掉）→ 先删再加
            try:
                win32.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                self._ok = bool(win32.shell32.Shell_NotifyIconW(
                    NIM_ADD, ctypes.byref(nid)))
            except Exception:
                self._ok = False

    def _cleanup(self):
        try:
            if self._nid is not None:
                win32.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
        except Exception:
            pass
        try:
            if self._hicon:
                win32.user32.DestroyIcon(self._hicon)
            if self._hicon_small and self._hicon_small != self._hicon:
                win32.user32.DestroyIcon(self._hicon_small)
        except Exception:
            pass
        self._hicon = self._hicon_small = None
        self._nid = None
        self._ok = False

    def _message_loop(self):
        msg = wintypes.MSG()
        while not self._stop.is_set():
            ret = win32.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            win32.user32.TranslateMessage(ctypes.byref(msg))
            win32.user32.DispatchMessageW(ctypes.byref(msg))

    # ---------- 菜单 ----------
    def set_labels(self, labels: dict):
        """语言切换时改菜单文案（下次弹出即生效）"""
        with self._lock:
            self.labels.update(labels or {})

    def _current_font_family(self) -> str:
        """界面字体族：**每次弹菜单现读**设置，用户改完字体下一次右键就生效"""
        try:
            manager = getattr(self, "_settings_manager", None)
            if manager is not None:
                value = str(manager.settings.get("ui_font_family", "") or "")
                if value:
                    return value
        except Exception:                                  # noqa: BLE001
            pass
        return self._menu_font_family

    def _menu_text(self, key, fallback):
        """菜单文案（**不转义 &** —— 自绘菜单里 & 就是普通字符）
        ⚠️ 系统菜单需要把 & 写成 &&（否则被当成快捷键前缀），但自绘菜单里
           GDI+ DrawString 会把 "&&" 原样画出来。所以转义只在 _show_system_menu 里做。
        """
        text = self.labels.get(key) or fallback
        return str(text)

    def show_menu(self, at=None):
        """公开入口：弹右键菜单（托盘右键 / 前端 api 调用都走这里）
        at: 可选 (x, y) 屏幕坐标；None 时按托盘图标矩形自动定位。
        """
        if at is not None:
            try:
                self._force_anchor = (int(at[0]), int(at[1]))
            except Exception:
                self._force_anchor = None
        try:
            self._show_menu()
        finally:
            self._force_anchor = None

    def _show_menu(self):
        """弹右键菜单：结构与顺序照原版（呼出主窗口 / 呼出搜索框 / 呼出AI / ──── / 退出）
        ⚠️ 用**自绘圆角菜单**（desktop/native/traymenu.py）而不是系统 TrackPopupMenu：
           系统菜单是 Windows 经典白底直角样式，和程序里那套深色玻璃界面完全不搭。
           自绘版逐常量复刻原版 PyQt5 `ui/tray_menu.py`（圆角 12 / 行高 30 / 图标 14 /
           文字左 58 / hover 圆角 8 …），主题跟随程序当前深浅色。
        ⚠️ 自绘菜单**失败绝不静默**：popup() 返回后看 `menu.opened`，
           没画上去就把原因写进日志，再降级到系统菜单（功能不丢，样式会说清原因）。
        """
        dark = self._is_dark()
        _MENU_DARK[0] = dark
        items = [
            traymenu.TrayMenuItem(
                text=self._menu_text("show_main_window", "Show Main Window"),
                icon_png=self._menu_icon("home"),
                callback=lambda: self._invoke("home")),
            traymenu.TrayMenuItem(
                text=self._menu_text("show_search_box", "Open Search Box"),
                icon_png=self._menu_icon("search"),
                callback=lambda: self._invoke("search")),
            traymenu.TrayMenuItem(
                text=self._menu_text("show_ai_search", "Open AI"),
                icon_png=self._menu_icon("ai"),
                callback=lambda: self._invoke("ai")),
            traymenu.TrayMenuItem(separator=True),
            traymenu.TrayMenuItem(
                text=self._menu_text("exit", "Exit"),
                # 需求：最底下的退出用红色字体 + 红色图标（破坏性操作，参照系统菜单习惯）
                # ⚠️ danger=True 同时喂给图标绘制（红墨迹）和 traymenu 的染色，
                #    两条保险保证图标是主题 danger 红而不是黑色。
                icon_png=self._menu_icon("exit", danger=True),
                danger=True,
                callback=lambda: self._invoke("exit")),
        ]
        menu = traymenu.TrayMenu(items, dark=dark,
                                 font_family=self._current_font_family())
        try:
            width, height = menu._measure()
            x, y = self._menu_position(width, height)
            menu.popup(x, y)
        except Exception as exc:                          # noqa: BLE001
            self._log("err", f"自绘托盘菜单异常，降级系统菜单: "
                             f"{type(exc).__name__}: {exc}")
            self._show_system_menu()
            return
        if not menu.opened:
            self._log("err", f"自绘托盘菜单未生效，降级系统菜单。原因: "
                             f"{menu.last_error or '未知'}")
            self._show_system_menu()

    # ---------- 菜单定位（原版 main_window.py:995 _show_tray_menu 的规则） ----------
    # 原版：x = 图标中心 x - 菜单宽/2；图标中心在屏幕下半边 → 往上弹（间距 6），
    #       否则往下弹；最后把窗口夹在工作区里、四边留 8px。
    MENU_GAP = 6
    MENU_SCREEN_MARGIN = 8

    def _menu_position(self, width: int, height: int):
        """算菜单左上角的屏幕坐标（不会被任务栏遮住）"""
        forced = getattr(self, "_force_anchor", None)
        if forced:
            # 前端显式给了坐标：把它当锚点，同样夹进工作区
            cx, cy = int(forced[0]), int(forced[1])
            left = right = cx
            top = bottom = cy
        else:
            rect = self._icon_rect()
            if rect:
                left, top, right, bottom = rect
                cx, cy = (left + right) // 2, (top + bottom) // 2
            else:
                pt = win32.POINT()
                win32.user32.GetCursorPos(ctypes.byref(pt))
                cx, cy = int(pt.x), int(pt.y)
                left = right = cx
                top = bottom = cy
        wa_left, wa_top, wa_right, wa_bottom = self._work_area_for_point(cx, cy)
        x = cx - width // 2
        if cy > (wa_top + wa_bottom) // 2:
            y = top - height - self.MENU_GAP          # 任务栏在下边 → 往上弹
        else:
            y = bottom + self.MENU_GAP                # 任务栏在上边 → 往下弹
        margin = self.MENU_SCREEN_MARGIN
        x = max(wa_left + margin, min(x, wa_right - width - margin))
        y = max(wa_top + margin, min(y, wa_bottom - height - margin))
        return int(x), int(y)

    def _work_area_for_point(self, x: int, y: int):
        """包含 (x, y) 的那块显示器的工作区（不含任务栏）
        ⚠️ 不能用 win32.work_area(self._hwnd)：那个按窗口所在显示器取，
           而托盘窗口是个 0×0 的 WS_POPUP，坐标 (0,0) —— 多显示器下会取错屏。
        """
        try:
            u = win32.user32
            if not getattr(self, "_monitor_sig_ready", False):
                try:
                    u.MonitorFromPoint.argtypes = [win32.POINT, wintypes.DWORD]
                    u.MonitorFromPoint.restype = wintypes.HMONITOR
                except Exception:
                    pass
                self._monitor_sig_ready = True
            hmon = u.MonitorFromPoint(win32.POINT(int(x), int(y)),
                                      2)                  # MONITOR_DEFAULTTONEAREST
            if hmon:
                info = win32.MONITORINFO()
                info.cbSize = ctypes.sizeof(win32.MONITORINFO)
                if u.GetMonitorInfoW(hmon, ctypes.byref(info)):
                    r = info.rcWork
                    return (r.left, r.top, r.right, r.bottom)
        except Exception as exc:                          # noqa: BLE001
            self._log("warn", f"取显示器工作区失败（退回主屏工作区）: "
                              f"{type(exc).__name__}: {exc}")
        return win32.work_area()

    # 图标：自绘菜单用 GDI+ 画，不需要外部 PNG 文件。
    # 语义必须对齐原版 `make_tray_menu()` 用的 4 个 FIF 成员：
    #     FIF.HOME(房子) / FIF.SEARCH(放大镜) / FIF.ROBOT(机器人头) / FIF.EMBED(门+右箭头)
    # （FIF.EMBED 在本机 qfluentwidgets 里渲染出来就是"门框 + 右箭头"，原版拿它当"退出"）
    MENU_ICON_KEYS = ("home", "search", "ai", "exit")
    # 线稿坐标只占画布 .14~.86，放大这个倍数后墨迹才与原版一样占满 14px 格
    MENU_ICON_INK_SCALE = 1.19
    _MENU_ICON_CACHE = {}

    def _menu_icon(self, key: str, danger: bool = False):
        """取一个菜单图标的 PNG 字节（画不出来就返回空：菜单只画文字，位置不歪）
        danger=True 时**直接用主题 danger 色画墨迹**：退出的文字已经是红的，
        图标也必须是红的（traymenu 那边还会再按主题色染一遍 —— 两条保险，任何一边
        失效另一条仍然让图标是红的）。
        ⚠️⚠️ 这里以前每一条都必然抛异常，异常又被 `except: return b""` 吞掉：
              · `from System.Drawing.Drawing2D import Graphics` —— Graphics 不在
                Drawing2D 命名空间里（在 System.Drawing），ImportError；
              · `g.CreatePen(...)` —— .NET 的 Graphics **没有** CreatePen（那是
                Qt/Win32 的写法），要用 `Pen(color, width)`；
              · 而且整个函数没有先 `_ensure_gdiplus()`（没 AddReference 时连
                `import System.Drawing` 都会 ModuleNotFoundError）。
            结果：**自绘菜单从来没有画过图标**（实测 4 个 key 全部返回 0 字节）。
        """
        dark = bool(_MENU_DARK[0])
        cache_key = (key, dark, bool(danger))
        cached = self._MENU_ICON_CACHE.get(cache_key)
        if cached is not None:
            return cached
        try:
            if not traymenu._ensure_gdiplus():             # 先 AddReference，再 import
                self._MENU_ICON_CACHE[cache_key] = b""
                return b""
            from System.Drawing import Bitmap, Pen, SolidBrush
            from System.Drawing.Drawing2D import (GraphicsPath, LineCap, LineJoin,
                                                  SmoothingMode)
            from System.Drawing import Graphics
            from System.IO import MemoryStream
            size = 32                      # 画大一点再让菜单缩到 14，抗锯齿更好
            bmp = Bitmap(size, size)
            g = Graphics.FromImage(bmp)
            g.SmoothingMode = SmoothingMode.AntiAlias
            # ⚠️ 原版 Fluent 图标在 14×14 里几乎画满（实测墨迹 x 18..31 = 整格 14px），
            #    而这里的线稿坐标只占到画布的 .14~.86（缩到 14px 后墨迹只有 ~10px，
            #    看着比原版"小一号、细一号"）。用中心缩放把线稿放大到同样的占比，
            #    线宽跟着一起放大（Pen 受变换影响）。
            scale = self.MENU_ICON_INK_SCALE
            g.TranslateTransform(size / 2.0, size / 2.0)
            g.ScaleTransform(scale, scale)
            g.TranslateTransform(-size / 2.0, -size / 2.0)
            color = _menu_ink_color(danger)
            # Fluent 风格：1px 线（32px 画布上 ≈2.3px）→ 缩到 14px 约 1px，圆头圆角
            ink = Pen(color, 2.3)
            ink.StartCap = LineCap.Round
            ink.EndCap = LineCap.Round
            ink.LineJoin = LineJoin.Round
            s = float(size)

            def line(x1, y1, x2, y2):
                g.DrawLine(ink, float(x1), float(y1), float(x2), float(y2))

            if key == "home":                                  # FIF.HOME：房子 + 门
                line(s * .14, s * .47, s * .50, s * .15)       # 左屋檐
                line(s * .50, s * .15, s * .86, s * .47)       # 右屋檐
                line(s * .21, s * .42, s * .21, s * .84)       # 左墙
                line(s * .79, s * .42, s * .79, s * .84)       # 右墙
                line(s * .21, s * .84, s * .38, s * .84)       # 地板（左段）
                line(s * .62, s * .84, s * .79, s * .84)       # 地板（右段）
                line(s * .38, s * .84, s * .38, s * .62)       # 门左侧
                line(s * .62, s * .84, s * .62, s * .62)       # 门右侧
                line(s * .38, s * .62, s * .62, s * .62)       # 门顶
            elif key == "search":                              # FIF.SEARCH：放大镜
                g.DrawEllipse(ink, s * .15, s * .15, s * .52, s * .52)
                line(s * .62, s * .62, s * .85, s * .85)
            elif key == "ai":                                  # AI：四角星（不再是机器人）
                # 与网页端 #i-robot 改成同一套形状：大四角星 + 右上/左下两颗小星。
                # 四角星用 4 段二次曲线（贝塞尔）连出尖角，4 个尖点分别在上/右/下/左。
                def star4(cx, cy, r):
                    k = r * 0.18                      # 控制点的内收量（决定"胖瘦"）
                    p = GraphicsPath()
                    p.AddBezier(float(cx), float(cy - r),
                                float(cx + k), float(cy - k),
                                float(cx + r), float(cy - k * 0.0),
                                float(cx + r), float(cy))
                    p.AddBezier(float(cx + r), float(cy),
                                float(cx + k), float(cy + k),
                                float(cx), float(cy + r),
                                float(cx), float(cy + r))
                    p.AddBezier(float(cx), float(cy + r),
                                float(cx - k), float(cy + k),
                                float(cx - r), float(cy),
                                float(cx - r), float(cy))
                    p.AddBezier(float(cx - r), float(cy),
                                float(cx - k), float(cy - k),
                                float(cx), float(cy - r),
                                float(cx), float(cy - r))
                    p.CloseFigure()
                    return p

                g.DrawPath(ink, star4(s * .42, s * .56, s * .30))        # 主星
                g.DrawPath(ink, star4(s * .74, s * .26, s * .14))        # 右上小星
                g.DrawPath(ink, star4(s * .26, s * .80, s * .10))        # 左下小星
            else:                                              # 退出：门 + 右箭头
                # 门框（左侧，稍斜，和原版 FIF.EMBED 的观感一致）
                door = GraphicsPath()
                door.AddLine(float(s * .30), float(s * .18), float(s * .14),
                             float(s * .26))
                door.AddLine(float(s * .14), float(s * .26), float(s * .14),
                             float(s * .76))
                door.AddLine(float(s * .14), float(s * .76), float(s * .30),
                             float(s * .84))
                door.AddLine(float(s * .30), float(s * .84), float(s * .30),
                             float(s * .18))
                g.DrawPath(ink, door)
                line(s * .46, s * .18, s * .46, s * .84)       # 门轴竖线
                line(s * .40, s * .50, s * .84, s * .50)       # 箭头杆
                line(s * .68, s * .35, s * .84, s * .50)       # 箭头（上）
                line(s * .68, s * .65, s * .84, s * .50)       # 箭头（下）
            stream = MemoryStream()
            bmp.Save(stream, _png_format())
            data = bytes(stream.ToArray())
            stream.Dispose()
            g.Dispose()
            bmp.Dispose()
            if not data:
                self._log("warn", f"菜单图标 {key} 编码结果为空")
            self._MENU_ICON_CACHE[cache_key] = data
            return data
        except Exception as exc:                          # noqa: BLE001
            # ⚠️ 不静默：图标画不出来要能在日志里看到（菜单仍可用，只是没图标）
            self._log("warn", f"菜单图标 {key} 绘制失败（该项只画文字）: "
                              f"{type(exc).__name__}: {exc}")
            self._MENU_ICON_CACHE[cache_key] = b""
            return b""

    def _is_dark(self) -> bool:
        """当前主题深浅（菜单配色跟着走）"""
        try:
            theme = ""
            manager = getattr(self, "_settings_manager", None)
            if manager is not None:
                theme = str(manager.settings.get("theme", "跟随系统"))
            if theme == "深色主题":
                return True
            if theme == "浅色主题":
                return False
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
        except Exception:
            return True

    def _show_system_menu(self):
        """兜底：自绘菜单起不来时退回系统菜单（至少功能在）
        ⚠️ 这是**降级**路径，调用方必须已经写过"为什么降级"的日志。
        ⚠️ 系统菜单是原生 HMENU：`&` 会被当成快捷键前缀，所以这里的文案要转义成 `&&`
           （自绘菜单反过来，见 _menu_text 的说明）。
        """
        u = win32.user32
        menu = u.CreatePopupMenu()
        if not menu:
            self._log("err", "系统菜单也建不出来（CreatePopupMenu 返回空）")
            return
        try:
            esc = lambda s: str(s).replace("&", "&&")      # noqa: E731
            u.AppendMenuW(menu, MF_STRING, MENU_ID_HOME,
                          esc(self._menu_text("show_main_window", "Show Main Window")))
            u.AppendMenuW(menu, MF_STRING, MENU_ID_SEARCH,
                          esc(self._menu_text("show_search_box", "Open Search Box")))
            u.AppendMenuW(menu, MF_STRING, MENU_ID_AI,
                          esc(self._menu_text("show_ai_search", "Open AI")))
            u.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            u.AppendMenuW(menu, MF_STRING, MENU_ID_EXIT,
                          esc(self._menu_text("exit", "Exit")))
            u.SetMenuDefaultItem(menu, MENU_ID_HOME, 0)
            rect = self._icon_rect()
            if rect:
                left, top, right, bottom = rect
                cx, cy = (left + right) // 2, (top + bottom) // 2
            else:
                forced = getattr(self, "_force_anchor", None)
                if forced:
                    cx, cy = int(forced[0]), int(forced[1])
                else:
                    pt = win32.POINT()
                    u.GetCursorPos(ctypes.byref(pt))
                    cx, cy = int(pt.x), int(pt.y)
                left, top, right, bottom = cx, cy, cx, cy
            wa_left, wa_top, wa_right, wa_bottom = self._work_area_for_point(cx, cy)
            flags = TPM_RIGHTBUTTON | TPM_RETURNCMD
            # TrackPopupMenu 的 (x, y) 是"对齐点"：任务栏在下边就贴着图标上沿往上弹
            if cy > (wa_top + wa_bottom) // 2:
                flags |= TPM_BOTTOMALIGN
                y = top
            else:
                flags |= TPM_TOPALIGN
                y = bottom
            x = max(wa_left + 8, min(cx, wa_right - 8))
            u.SetForegroundWindow(self._hwnd)
            choice = u.TrackPopupMenu(menu, flags, x, y, 0, self._hwnd, None)
            u.PostMessageW(self._hwnd, win32.WM_NULL, 0, 0)
            if choice:
                self._dispatch_menu(int(choice))
        finally:
            u.DestroyMenu(menu)

    def _icon_rect(self):
        """Shell_NotifyIconGetRect（Win7+）拿托盘图标矩形
        ⚠️ 私有 API 的替代：不用它就只能靠 QCursor.pos()，任务栏在底部时菜单会只露一半。
        """
        try:
            if self._nid is None:
                return None
            shell32 = win32.shell32
            if not hasattr(shell32, "Shell_NotifyIconGetRect"):
                return None
            class NOTIFYICONIDENTIFIER(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                            ("uID", ctypes.c_uint), ("guidItem", GUID)]
            ident = NOTIFYICONIDENTIFIER()
            ident.cbSize = ctypes.sizeof(NOTIFYICONIDENTIFIER)
            ident.hWnd = self._hwnd
            ident.uID = TRAY_ID
            rect = win32.RECT()
            hr = shell32.Shell_NotifyIconGetRect(ctypes.byref(ident),
                                                 ctypes.byref(rect))
            if hr != 0:
                return None
            return (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            return None

    def _dispatch_menu(self, choice: int):
        if choice == MENU_ID_HOME:
            self._invoke("home")
        elif choice == MENU_ID_SEARCH:
            self._invoke("search")
        elif choice == MENU_ID_AI:
            self._invoke("ai")
        elif choice == MENU_ID_EXIT:
            self._invoke("exit")

    def _invoke(self, key: str):
        """菜单回调放到独立线程跑：回调里可能弹窗口/等消息，不能卡住托盘线程"""
        callback = self.on_select.get(key)
        if not callable(callback):
            return

        def _run():
            try:
                callback()
            except Exception as exc:
                try:
                    from pymodels.utils.logger import log
                    log.err("外壳", "tray", f"托盘菜单回调 {key} 失败: {exc}")
                except Exception:
                    pass

        threading.Thread(target=_run, name=f"ToolsGCP-tray-{key}", daemon=True).start()

    # ---------- 在原生线程上执行任务 ----------
    def invoke(self, func, timeout: float = 3.0):
        """把 func 排到**原生消息线程**上执行，并等它跑完（返回 func 的返回值）
        ⚠️ 为什么需要：RegisterHotKey 注册的是"**调用线程**的热键"，WM_HOTKEY 也只会投递到
           那个线程的消息队列。如果从主线程注册、却让托盘线程去收消息，就会得到
           error code 1408（ERROR_HOTKEY_NOT_REGISTERED）——实测踩过。
           所以热键的注册/注销必须统统编组到这条线程上。
        ⚠️ 如果**已经在**这条线程上（例如 on_ready_native 回调里），必须直接执行：
           否则会 PostMessage 给自己再同步等待，等到超时为止（实测表现为"热键注册失败
           code=0 + 启动多卡 3 秒"）。
        """
        if self._is_native_thread():
            return func()
        if not self._thread or not self._thread.is_alive() or not self._hwnd:
            return False
        box = {"done": threading.Event(), "value": False}

        def _job():
            try:
                box["value"] = func()
            except Exception:
                box["value"] = False
            finally:
                box["done"].set()

        with self._jobs_lock:
            self._jobs.append(_job)
        try:
            win32.user32.PostMessageW(self._hwnd, self._wake_msg, 0, 0)
        except Exception:
            return False
        box["done"].wait(timeout)
        return box["value"]

    def _is_native_thread(self) -> bool:
        """当前线程是不是托盘那条原生消息线程"""
        try:
            return bool(self._thread is not None
                        and threading.current_thread() is self._thread)
        except Exception:
            return False

    def _drain_jobs(self):
        with self._jobs_lock:
            jobs, self._jobs = self._jobs, []
        for job in jobs:
            try:
                job()
            except Exception:
                pass

    # ---------- 气泡提示 ----------
    def notify(self, title: str, text: str):
        """弹一个气泡（"程序已隐藏到托盘"用）。图标还没就绪时排队，就绪后补发。"""
        if not win32.IS_WINDOWS:
            return
        if not self._ok:
            self._pending_notify.append((title, text))
            return
        self._notify_impl(title, text)

    def _notify_impl(self, title: str, text: str):
        if self._nid is None:
            return
        nid = self._nid
        nid.uFlags = NIF_INFO
        nid.szInfo = str(text)[:255]
        nid.szInfoTitle = str(title)[:63]
        nid.dwInfoFlags = 0x00000001                    # NIIF_INFO
        try:
            win32.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        finally:
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.szInfo = ""
            nid.szInfoTitle = ""
