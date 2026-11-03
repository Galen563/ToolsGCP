"""系统剪贴板（Win32 原生）—— 前端复制按钮的真正落点。
========== 为什么不能只用 navigator.clipboard ==========
WebView2 里 `navigator.clipboard.writeText()` 经常直接 reject：
  · 它要求**安全上下文**（http://127.0.0.1 算，但 WebView2 里还要看权限策略）；
  · 即使成功，宿主没有用户手势时也会被拒。
网页端原来的 `copyText()`（webui/js/app.js）就是"先试 keyboard 焦点技巧，
再试 execCommand('copy')"，两条都可能静默失败 —— 于是出现"UI 提示复制成功，
剪贴板里其实什么都没有"。
这里直接操作 Win32 剪贴板（OpenClipboard/SetClipboardData），和原版 PyQt 的
`QApplication.clipboard().setText()` 语义完全一致：不依赖浏览器权限，必定生效。
前端仍然保留 `navigator.clipboard` / `execCommand` 兜底（例如在纯浏览器里调试时）。
"""

import ctypes
import sys
import time

IS_WINDOWS = sys.platform == "win32"

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    _user32.OpenClipboard.restype = ctypes.c_bool
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = ctypes.c_bool
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = ctypes.c_bool
    _user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    _user32.SetClipboardData.restype = ctypes.c_void_p
    _user32.GetClipboardData.argtypes = [ctypes.c_uint]
    _user32.GetClipboardData.restype = ctypes.c_void_p
    _user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    _user32.IsClipboardFormatAvailable.restype = ctypes.c_bool

    _kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = ctypes.c_void_p
    _kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalUnlock.restype = ctypes.c_bool
    _kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalFree.restype = ctypes.c_void_p
else:                                                # pragma: no cover - 仅 Windows
    _user32 = _kernel32 = None


def _open_clipboard(retries: int = 8) -> bool:
    """抢剪贴板。被别的进程占着时会失败 —— 原版 Qt 也会，这里重试几次"""
    for attempt in range(max(1, retries)):
        if _user32.OpenClipboard(None):
            return True
        time.sleep(0.03 * (attempt + 1))
    return False


def set_text(text: str) -> bool:
    """把字符串写进系统剪贴板（Windows 原生；失败返回 False，不抛异常）"""
    if not IS_WINDOWS:
        return False
    data = str(text if text is not None else "")
    if not _open_clipboard():
        return False
    handle = None
    try:
        if not _user32.EmptyClipboard():
            return False
        buf = ctypes.create_unicode_buffer(data)
        size = ctypes.sizeof(buf)
        handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        locked = _kernel32.GlobalLock(handle)
        if not locked:
            return False
        try:
            ctypes.memmove(locked, buf, size)
        finally:
            _kernel32.GlobalUnlock(handle)
        if not _user32.SetClipboardData(CF_UNICODETEXT, handle):
            return False
        # ⚠️ SetClipboardData 成功后所有权归系统，不能再 GlobalFree
        handle = None
        return True
    finally:
        if handle:
            try:
                _kernel32.GlobalFree(handle)
            except Exception:
                pass
        _user32.CloseClipboard()


def get_text() -> str:
    """读回剪贴板文本（自检用；失败返回空串）"""
    if not IS_WINDOWS:
        return ""
    if not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return ""
    if not _open_clipboard():
        return ""
    try:
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        locked = _kernel32.GlobalLock(handle)
        if not locked:
            return ""
        try:
            return ctypes.wstring_at(locked)
        finally:
            _kernel32.GlobalUnlock(handle)
    finally:
        _user32.CloseClipboard()
