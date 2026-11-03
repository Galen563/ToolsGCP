"""外链打开（含 Ctrl+左键的"静默打开"）

**普通左键** → 系统默认浏览器打开并切到前台；**Ctrl+左键** → 浏览器照常打开，但不抢走
当前程序的焦点（Windows 用 SW_SHOWNOACTIVATE，其它平台退回普通打开）。

⚠️ 判断 Ctrl 用 `QApplication.keyboardModifiers()` 在**按下那一刻**取，不能缓存、也不能看
   事件里的 modifiers（不同入口拿到的事件类型不一样）。
"""

import sys
import webbrowser

# 打开方式：SW_SHOWNORMAL(1) = 正常到前台；SW_SHOWNOACTIVATE(4) = 不激活
_SW_SHOWNORMAL = 1
_SW_SHOWNOACTIVATE = 4

# "把前台抢回来"的重试时刻（毫秒，相对发起打开那一刻）。
# ⚠️ 要重试好几拍：浏览器提窗口的时机不确定 —— 已开着时几十毫秒，冷启动要几百毫秒
_RECLAIM_DELAYS_MS = (0, 150, 400, 800)


def ctrl_pressed() -> bool:
    """现在按住 Ctrl 了吗（拿不到 Qt 就当没按）"""
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return False
        return bool(app.keyboardModifiers() & Qt.ControlModifier)
    except Exception:
        return False


# ⚠️⚠️ 除了"现在按住没"之外还要记"按下那一刻按住没"：
#    `clicked` 是**松开鼠标**时才发的，那时问 keyboardModifiers() 在连点/卡顿的
#    时序里经常已经拿不到 Ctrl（Qt 的修饰键状态和鼠标事件不同步）；而"每个控件
#    自己装事件过滤器"也不稳（按下事件不一定落在那个控件上）。
#    所以装一个全程序级观察器记下每次按下的 Ctrl，判断时两个来源**取或** ——
#    宁可多静默一次，也不要违背用户按住的意图。
_last_press_ctrl = False
_global_watcher = None


def _ensure_global_watcher():
    """懒装全程序鼠标观察器（只装一次）"""
    global _global_watcher
    if _global_watcher is not None:
        return _global_watcher
    try:
        from PyQt5.QtCore import QEvent, QObject, Qt
        from PyQt5.QtWidgets import QApplication

        class _GlobalCtrlWatcher(QObject):
            def eventFilter(self, obj, event):
                global _last_press_ctrl
                try:
                    if event.type() == QEvent.MouseButtonPress:
                        _last_press_ctrl = bool(
                            event.modifiers() & Qt.ControlModifier)
                except Exception:
                    pass
                return False

        app = QApplication.instance()
        if app is None:
            return None
        watcher = _GlobalCtrlWatcher(app)
        app.installEventFilter(watcher)
        _global_watcher = watcher
        return watcher
    except Exception:
        return None


def install_ctrl_watcher() -> bool:
    """**启动时**就把全程序 Ctrl 观察器装好（主窗口 __init__ 里调）

    ⚠️⚠️ 别改回"用到才懒装"：观察器记的是**鼠标按下那一刻**的 Ctrl，等到第一次 open_url
       才装的话触发这次打开的按下事件早就过去了，那一下永远记不到 Ctrl。
    """
    return _ensure_global_watcher() is not None


def ctrl_active() -> bool:
    """"用户现在是不是想静默打开"：按下那一刻按住 或 此刻还按着（Ctrl+左键判断的唯一入口）"""
    _ensure_global_watcher()
    return bool(_last_press_ctrl or ctrl_pressed())


def is_web_url(url: str) -> bool:
    return str(url or "").strip().lower().startswith(("http://", "https://"))


# ---------- Windows：把被浏览器抢走的前台窗口要回来 ----------
# ⚠️⚠️ 别把这段删掉换回"只调 SW_SHOWNOACTIVATE"：
#   现代浏览器基本是**单实例**，ShellExecute 只是把 URL 转交给已在跑的浏览器进程，
#   由那个进程自己决定要不要提窗口（多数会提），于是 nShowCmd 形同虚设。
#   可靠的做法是打开之后**把我们自己的窗口重新置前**：发起打开那一刻的前台窗口就是
#   "用户本来在用的窗口"，打开后立刻 + 稍后几拍抢回来，浏览器慢半拍抢也覆盖得到。

def _win_foreground() -> int:
    """当前前台窗口句柄（拿不到就 0）"""
    try:
        import ctypes
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def _win_window_alive(hwnd) -> bool:
    """这个句柄还是一个可见的顶层窗口吗（窗口关了就别再碰它）"""
    try:
        import ctypes
        if not hwnd:
            return False
        user32 = ctypes.windll.user32
        return bool(user32.IsWindow(int(hwnd))) \
            and bool(user32.IsWindowVisible(int(hwnd)))
    except Exception:
        return False


def _win_set_foreground(hwnd) -> bool:
    """把 hwnd 提到前台；返回是否成功

    ⚠️ Windows 有"前台锁定"：不满足条件时 SetForegroundWindow 会被**静默拒绝**（返回 0、
       什么都不发生）。所以按副作用从小到大备了三招：SetForegroundWindow →
       SwitchToThisWindow（Alt+Tab 用的那个，宽容得多）→ 临时置顶再取消置顶后重试。
       ⚠️ 不用 AttachThreadInput：挂/摘一旦出错会把界面卡住。
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = int(hwnd)
        if not hwnd:
            return False
        if int(user32.GetForegroundWindow()) == hwnd:
            return True                    # 已经是前台了，不用折腾
        if user32.SetForegroundWindow(hwnd):
            return True
        try:
            user32.SwitchToThisWindow(hwnd, True)
            if int(user32.GetForegroundWindow()) == hwnd:
                return True
        except Exception:
            pass
        HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
        flags = 0x0001 | 0x0002 | 0x0040   # NOSIZE | NOMOVE | SHOWWINDOW
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        user32.SetForegroundWindow(hwnd)
        return int(user32.GetForegroundWindow()) == hwnd
    except Exception:
        return False


def _reclaim_foreground(previous) -> bool:
    """把"点链接之前的前台窗口"重新置前（只对 win32 有效；窗口已关就直接放手）"""
    if sys.platform != "win32" or not previous:
        return False
    if not _win_window_alive(previous):
        return False
    _win_set_foreground(previous)          # 立刻抢一次

    # 后面几拍靠 Qt 的定时器（这里**不能**自己 sleep：那会把界面卡住）
    try:
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication
        if QApplication.instance() is None:
            return True
    except Exception:
        return True

    def _retry(hwnd=previous):
        # 窗口中途关掉了（用户把主窗口关了/最小化到托盘）就别再抢
        if not _win_window_alive(hwnd):
            return
        _win_set_foreground(hwnd)

    for delay in _RECLAIM_DELAYS_MS[1:]:
        try:
            QTimer.singleShot(int(delay), _retry)
        except Exception:
            pass
    return True


def open_url(url: str, log_name: str = "网址", background=None) -> bool:
    """用系统默认浏览器打开地址

    background：None（推荐）= 按当前 Ctrl 状态自动决定；True = 强制后台；False = 强制前台。
    返回是否真的打开了（地址不合法 / 全部方式都失败时为 False）。
    """
    url = str(url or "").strip()
    if not is_web_url(url):
        return False
    if background is None:
        background = ctrl_active()

    try:
        from .logger import log
        log.op("外链", "open_link", 类型=log_name, url=url,
               方式="后台打开" if background else "前台打开")
    except Exception:
        pass

    if background and sys.platform == "win32":
        # 先记下"点链接前的前台窗口"（就是本程序那个窗口），打开完要抢回来
        previous = _win_foreground()
        try:
            import ctypes
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "open", url, None, None, _SW_SHOWNOACTIVATE)
            # ShellExecuteW 成功时返回 >32 的 HINSTANCE，<=32 才是错误码；
            # 失败就往下走 webbrowser.open 那条老路
            if int(rc or 0) > 32:
                _reclaim_foreground(previous)
                return True
        except Exception:
            pass
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def watch_ctrl(widget) -> dict:
    """（保留的兼容接口）确保"按下时记 Ctrl"的观察器已装好

    ⚠️ 观察器是**全程序级**的（见 ctrl_active），不再挂在单个控件上 ——"按下事件一定落在
       那个控件上"在多控件、深层级、快速连点时会翻车。调用点直接传 background=None 即可。
    """
    _ensure_global_watcher()
    return {"ctrl": False}


def open_clicked_url(widget, url, log_name: str = "网址", state=None) -> bool:
    """控件被点击时打开地址（统一交给 open_url 内部的全局 Ctrl 判断）

    ⚠️ 不再看 `state`（那是老的"每个控件自己记"的做法）。
    """
    return open_url(url, log_name, background=None)


__all__ = ["open_url", "ctrl_pressed", "ctrl_active", "is_web_url", "watch_ctrl",
           "install_ctrl_watcher", "open_clicked_url"]
