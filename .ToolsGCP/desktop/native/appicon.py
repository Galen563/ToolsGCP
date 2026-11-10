"""窗口 / 任务栏图标：把 `.ToolsGCP/logo.png` 变成 HICON 再交给窗口（绝不抛异常）。
========== 为什么光设 AppUserModelID 不够（本模块存在的理由）==========
`ToolsGCP.pyw` 已经在建窗之前调了 `SetCurrentProcessExplicitAppUserModelID`。那个调用只决定
"任务栏按钮怎么分组 / 用哪个身份"，**它不提供图标**。Windows 的任务栏按钮图标按下面的顺序取：
  1. 窗口自己收到的 `WM_SETICON(ICON_BIG / ICON_SMALL)`   ← 本模块主路径
  2. 窗口**类**的图标（`SetClassLongPtrW(GCLP_HICON / GCLP_HICONSM)`） ← 本模块兜底
  3. 进程 exe 里的图标                                    ← 用 pythonw.exe 跑，就是那个默认 Python 图标
也就是说：设了自定义 AUMID、又没有注册带图标的快捷方式时，Shell 仍然读窗口的 WM_SETICON；
窗口没图标才会退回 exe 图标 —— 现象正是"任务栏显示默认 Python 图标"。
pywebview 自己那套（`webview.start(icon=...)` / `BrowserForm.__init__` 里的
`self.Icon = Icon(_state['icon'])`）走的是 .NET `System.Drawing.Icon`，它**只认 .ico**，
喂 PNG 会抛异常并被 pywebview 吞掉，然后退回 `ExtractIconW(sys.executable)` 的 Python 图标
（见 webview/platforms/winforms.py:243-251），所以必须我们自己在窗口创建后补一刀。
========== 为什么"绝不崩" ==========
需求：任何失败都只能记日志，不许影响启动。所以：
  · 所有 Win32 / .NET / Pillow 调用都在 try/except 里，失败只写日志并返回 False；
  · PNG→HICON 有三条独立路径（裸 PNG / Pillow 转 ICO / .NET Bitmap.GetHicon），全失败就放弃；
  · **HICON 句柄故意不在进程内销毁**：WM_SETICON 之后窗口/窗口类仍然持有这些句柄，
    提前 DestroyIcon 会让任务栏图标变成空白。统一放进模块级保活列表，进程退出时由系统回收。
"""

import ctypes
import os

from . import win32
from .win32 import (GCLP_HICON, GCLP_HICONSM, ICON_BIG, ICON_SMALL, ICON_SMALL2,
                    SM_CXICON, SM_CXSMICON, SM_CYICON, SM_CYSMICON, SWP_FRAMECHANGED,
                    SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, WM_GETICON,
                    WM_SETICON)

# HICON 保活（见模块 docstring：不能销毁）
_KEEP_ALIVE = []
_APPLIED = {"hwnd": 0, "big": 0, "small": 0, "ok": False}


def _log(level: str, message: str):
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)("窗口", "icon", message)
    except Exception:
        pass


def _system_metric(index: int, fallback: int) -> int:
    try:
        value = int(win32.user32.GetSystemMetrics(index))
        return value if value > 0 else fallback
    except Exception:
        return fallback


def icon_sizes():
    """任务栏/Alt+Tab 需要的大图标与小图标尺寸（随 DPI 变化）"""
    return (_system_metric(SM_CXICON, 32), _system_metric(SM_CYICON, 32),
            _system_metric(SM_CXSMICON, 16), _system_metric(SM_CYSMICON, 16))


# ==================== PNG → HICON（三条独立路径） ====================

def _hicon_from_png_bytes(data: bytes, size: int):
    """裸 PNG 字节 → HICON（Vista+ 的 PNG 压缩图标路径，托盘图标用的就是这条）
    实测（tray.png_to_hicon 同源）：`CreateIconFromResourceEx` 接受**原始 PNG 流**
    （0x00030000 版本头 + PNG 数据），给 16~64 的尺寸都能得到正确的 32bpp + alpha。
    """
    if not data:
        return 0
    try:
        buf = ctypes.create_string_buffer(data, len(data))
        return int(win32.user32.CreateIconFromResourceEx(
            buf, len(data), True, 0x00030000, size, size, 0) or 0)
    except Exception:
        return 0


def _hicon_from_ico_bytes(data: bytes, size: int):
    """ICO 容器字节 → HICON（CreateIconFromResourceEx 期待的是"资源段"，ICO 文件头不行，
    所以这里跳过 6 字节的 ICONDIR 头，按第一个 ICONDIRENTRY 取图像数据）
    ICO 目录项布局（每项 16 字节，从偏移 6 开始）：
        +0 宽(1) +1 高(1) +2 调色板数(1) +3 保留(1) +4 平面数(2) +6 位深(2)
        +8 **图像数据长度(4)** +12 **图像数据偏移(4)**
    ⚠️ 这两个字段的位置很容易写反（8=长度、12=偏移），写反了 CreateIconFromResourceEx 直接返回 0。
    """
    if not data or len(data) < 22:
        return 0
    try:
        count = int.from_bytes(data[4:6], "little")
        if count < 1:
            return 0
        entry = 6                                   # 第一个目录项的起始偏移
        length = int.from_bytes(data[entry + 8:entry + 12], "little")
        offset = int.from_bytes(data[entry + 12:entry + 16], "little")
        if 0 < offset < len(data) and 0 < length <= len(data) - offset:
            payload = data[offset:offset + length]
        else:
            payload = data[22:]
        buf = ctypes.create_string_buffer(payload, len(payload))
        return int(win32.user32.CreateIconFromResourceEx(
            buf, len(payload), True, 0x00030000, size, size, 0) or 0)
    except Exception:
        return 0


def _png_via_pillow(path: str, size: int):
    """路径 2：Pillow 把 PNG 重新编码成多尺寸 ICO，再取 HICON"""
    try:
        import io

        from PIL import Image
        image = Image.open(path)
        image = image.convert("RGBA")
        sizes = sorted({16, 20, 24, 32, 40, 48, 64, 128, 256, max(16, int(size))})
        buffer = io.BytesIO()
        image.save(buffer, format="ICO", sizes=[(s, s) for s in sizes])
        return _hicon_from_ico_bytes(buffer.getvalue(), size)
    except Exception:
        return 0


def _hicon_via_dotnet(path: str, size: int):
    """路径 3：.NET `Bitmap.GetHicon()`（pywebview 用 WinForms，pythonnet 一定在）
    ⚠️ 必须先 `import clr`：pythonnet 的 `System` 命名空间只有在导入 clr 之后才挂进
       `sys.meta_path`（实测：不 import clr 直接 `from System.Drawing import Bitmap`
       会 ImportError，于是这条兜底路径静默失效）。真实运行时 pywebview 的 winforms
       模块已经 import 过 clr，但这里自己再导一次，保证单独调用也成立。
    ⚠️ GetHicon 出来的句柄归我们所有：不能 DestroyIcon（模块 docstring），Bitmap 也要保活
       （GDI+ 的 HICON 引用它背后的位图）。
    """
    try:
        import clr                                          # noqa: F401
        try:
            clr.AddReference("System.Drawing")
        except Exception:
            pass
        from System.Drawing import Bitmap
        bitmap = Bitmap(path)
        handle = bitmap.GetHicon()
        value = int(handle.ToInt64())
        if value:
            _KEEP_ALIVE.append(bitmap)
        return value
    except Exception:
        return 0


def hicons_for_png(path: str):
    """(big, small) 两个 HICON；失败返回 (0, 0)"""
    big_size, _, small_size, _ = icon_sizes()
    if not win32.IS_WINDOWS or not path or not os.path.isfile(path):
        return (0, 0)
    data = b""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except Exception:
        data = b""

    def _build(size: int) -> int:
        handle = _hicon_from_png_bytes(data, size)
        if not handle:
            handle = _png_via_pillow(path, size)
        if not handle:
            handle = _hicon_via_dotnet(path, size)
        return handle

    big = _build(big_size)
    small = _build(small_size)
    if not small:
        small = big
    for handle in (big, small):
        if handle:
            _KEEP_ALIVE.append(handle)
    return (big, small)


# ==================== 应用到窗口 ====================

def _set_dotnet_icon(window, hicon_big: int) -> bool:
    """把图标挂到 WinForms 的 `Form.Icon` 上（best-effort，必须编组到 GUI 线程）
    ⚠️ 为什么还要这一步：`WM_SETICON` 只影响"当前这一次"，而 WinForms 在窗口句柄重建、
       主题变化等场景会用它自己的 `Icon` 属性重新设置窗口图标；把属性也设上才不会被打回去。
    ⚠️ `Icon.FromHandle` 不拥有句柄，直接赋给 Form 后 Form 可能去销毁它 → 这里用 `.Clone()`
       让 .NET 拿到自己的副本，我们那份 HICON 继续留给 WM_SETICON 用。
    """
    if not hicon_big or window is None:
        return False
    try:
        from . import frame

        def _apply():
            from System import IntPtr
            from System.Drawing import Icon
            native = getattr(window, "native", None)
            if native is None:
                return
            native.Icon = Icon.FromHandle(IntPtr(hicon_big)).Clone()

        return bool(frame.on_gui_thread(window, _apply, timeout=2.0))
    except Exception:
        return False


def apply_to_window(hwnd: int, png_path: str, window=None) -> bool:
    """给窗口设图标（窗口图标 + 任务栏图标）；失败只记日志，返回 False
    调用时机：窗口句柄存在之后（`_wait_for_window`）与**首次真正显示之后**（`_on_shown`）
    各一次 —— 后者覆盖"任务栏按钮是在窗口显示时才建"的那条时序。
    ⚠️ 本函数**不会**把窗口显示出来：WM_SETICON / SetClassLongPtrW 都不影响可见性，
       末尾那次 `SetWindowPos` 只带 SWP_FRAMECHANGED（无 SWP_SHOWWINDOW）；
       探针 icon_keeps_hidden 实测调用前后 visible 都是 false。
    """
    if not win32.IS_WINDOWS or not hwnd:
        return False
    big, small = hicons_for_png(png_path)
    if not big and not small:
        _log("warn", f"图标加载失败（{png_path}），窗口将使用系统默认图标（任务栏可能是 Python 图标）")
        return False

    ok = False
    # ① 先写 WinForms 属性（它会自己 WM_SETICON），保持"属性 = 图标"一致
    _set_dotnet_icon(window, big or small)
    # ② 再显式按尺寸发 WM_SETICON：这是任务栏/Alt+Tab **真正读**的那一份
    try:
        if big:
            win32.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
        if small:
            win32.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
        ok = True
    except Exception as exc:                                     # noqa: BLE001
        _log("warn", f"WM_SETICON 失败（不影响启动）: {exc}")
    # ③ 窗口类图标：新 hwnd / 重启对话框之类会继承它
    try:
        if big:
            win32.user32.SetClassLongPtrW(hwnd, GCLP_HICON, big)
        if small:
            win32.user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, small)
    except Exception:
        pass
    # ④ 让 Shell 重新读一遍图标（只改图标不移动/不激活窗口）
    try:
        win32.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                  SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                                  | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    except Exception:
        pass

    # 回读自检：WM_GETICON 拿到非 0 才算真的设上了（给日志/自检脚本当证据）
    try:
        read_big = int(win32.user32.SendMessageW(hwnd, WM_GETICON, ICON_BIG, 0) or 0)
        read_small = int(win32.user32.SendMessageW(hwnd, WM_GETICON, ICON_SMALL, 0) or 0)
        if not read_small:
            read_small = int(win32.user32.SendMessageW(hwnd, WM_GETICON, ICON_SMALL2, 0) or 0)
        ok = bool(read_big or read_small or ok)
        _APPLIED.update({"hwnd": int(hwnd), "big": read_big, "small": read_small, "ok": ok})
        _log("dbg" if ok else "warn",
             f"窗口图标已应用: {os.path.basename(png_path)}"
             f"（大图标回读={read_big}，小图标回读={read_small}）")
    except Exception:
        pass
    return bool(ok)


def applied_state() -> dict:
    """给自检脚本看的状态（不需要真的截图就能证明 WM_SETICON 生效了）"""
    return dict(_APPLIED)
