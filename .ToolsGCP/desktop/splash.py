"""启动画面：**纯 Win32 实现，不再依赖 PyQt5**
========== 为什么换掉 Qt 版 ==========
旧版把原版 PyQt5 的 `SplashScreen` 放到 worker 线程里跑。它能用，但代价很实在：
  · **打包体积**：PyQt5 + PyQt-Fluent-Widgets 一起进 exe 就是几十 MB —— 而整个 Web 版
    的界面根本不用 Qt 画，只为了这一块启动画面拖着整套 Qt 进去（用户明确要求砍掉）；
  · **必须装在 worker 线程**：Qt 的 QApplication 有线程亲和性，主线程一旦 import 过
    PyQt5，进程退出就 100% 崩 0xC0000005（见旧版长注释，实测 8/8）；顺带还逼出了
    "退出时必须在创建线程里销毁、还要轮询 stop 请求"那一整套绕法。
现在改成 Win32 分层窗口（`UpdateLayeredWindow` 画圆角半透明底 + 居中 logo）：
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
========= 视觉规格（照原版逐个数值对齐） =========
原版 `pymodels/splash_screen.py`：
  · logo 最长边夹到 300px（`max_size = 300`，KeepAspectRatio 平滑缩放）；
  · 窗口 = logo + 80px 边距（`setFixedSize(w + 80, h + 80)`）；
  · 背景 rgba(43,43,43,240)、圆角 20（`paintEvent` 的 drawRoundedRect）；
  · 无边框 + 置顶 + 不抢焦点（Frameless | StaysOnTop | Tool ⇒ 这里用
    WS_POPUP + WS_EX_TOOLWINDOW|TOPMOST|LAYERED，且 ShowWindow(SW_SHOWNOACTIVATE)）。
本项目 logo 是 180×180 → 窗口 260×260（和旧版日志里那个数一致）。
⚠️ 它**永远是独立小窗口**，绝不许拿主窗口冒充（那是"启动时闪一个等大空窗"的来源）。
"""

import ctypes
import os
import sys
import threading
import time
import traceback
from ctypes import wintypes

# 启动画面最长等待（毫秒）：超过就当作"已经结束"，避免异常让窗口永远不出现
SPLASH_HARD_TIMEOUT_MS = 12000

# ---- 视觉常量（与 pymodels/splash_screen.py 逐个对齐，见模块 docstring） ----
_SPLASH_BG = (43, 43, 43, 240)        # 原版 paintEvent: QColor(43,43,43,240)
_SPLASH_RADIUS = 20.0                # 原版 drawRoundedRect(..., 20, 20)
_SPLASH_MARGIN = 80                   # 原版 setFixedSize(w+80, h+80)
_SPLASH_LOGO_MAX = 300                # 原版 max_size = 300

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
# 位图准备（Pillow）
# ======================================================================
def _prepare_bitmap(icon_path: str):
    """把 logo 解码成"圆角半透明底 + 居中 logo"的 ARGB 像素，返回 (w, h, bytes)

    按原版规则：最长边超过 300 → 平滑缩到 300；窗口 = 图片 + 80px 边距；
    图片缺失/损坏 → 退回深底方块（保证启动画面永远有东西显示，不抛异常）。
    """
    from PIL import Image, ImageDraw

    logo = None
    if icon_path and os.path.exists(icon_path):
        try:
            logo = Image.open(icon_path).convert("RGBA")
        except Exception as exc:                        # noqa: BLE001
            _log_warn(f"启动画面图片加载异常: {exc}")
            logo = None
    else:
        _log_warn(f"启动画面图片不存在: {icon_path}")

    if logo is None:
        w = h = 220
        logo = None
    else:
        w, h = logo.size
        if w > _SPLASH_LOGO_MAX or h > _SPLASH_LOGO_MAX:
            ratio = min(_SPLASH_LOGO_MAX / float(w), _SPLASH_LOGO_MAX / float(h))
            w, h = max(1, int(w * ratio)), max(1, int(h * ratio))
            logo = logo.resize((w, h), Image.LANCZOS)

    win_w, win_h = w + _SPLASH_MARGIN, h + _SPLASH_MARGIN

    # 圆角底：先 2 倍超采样画圆角再缩回来，边缘更平滑（Pillow 的 rounded_rectangle
    # 在 1x 下会有锯齿，而启动画面是"窗口第一眼"，锯齿很明显）
    canvas = Image.new("RGBA", (win_w, win_h), (0, 0, 0, 0))
    mask = Image.new("L", (win_w * 2, win_h * 2), 0)
    try:
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle([0, 0, win_w * 2 - 1, win_h * 2 - 1],
                               radius=int(_SPLASH_RADIUS * 2), fill=255)
        mask = mask.resize((win_w, win_h), Image.LANCZOS)
    except Exception:
        mask = Image.new("L", (win_w, win_h), 255)      # 没圆角也认，不影响可用性
    bg = Image.new("RGBA", (win_w, win_h), _SPLASH_BG)
    canvas.paste(bg, (0, 0), mask)

    if logo is not None:
        canvas.alpha_composite(logo, ((win_w - w) // 2, (win_h - h) // 2))
    return win_w, win_h, canvas.tobytes()


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


def _update_layered(hwnd: int, width: int, height: int, raw_argb: bytes,
                    x: int = 0, y: int = 0) -> bool:
    """把 ARGB 像素贴到分层窗口：UpdateLayeredWindow + 32bpp premultiplied DIB

    ⚠️ `x, y` 是**窗口的屏幕坐标**（UpdateLayeredWindow 的 pptDst），必须传建窗时
       算好的居中位置；不传就会被强行拉到 (0,0)（第一版就这么错，窗口跑到左上角）。
    ⚠️ 分层窗口的 32bpp 位图要求**预乘 alpha**，且通道顺序是 B,G,R,A（见下面注释）。
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

        n = width * height * 4
        src = raw_argb
        dst = ctypes.cast(bits, ctypes.POINTER(ctypes.c_ubyte))
        # ⚠️⚠️ 两个字节序坑，改这里之前务必看明白：
        #   ① Pillow 的 `RGBA.tobytes()` 是 **R,G,B,A** 顺序；
        #   ② 而 BI_RGB 的 32bpp DIB 在内存里是 **B,G,R,A**（小端）。
        #   按"src[i] 当 B 用"直接拷会把红蓝通道装反（灰色看不出来、彩色 logo 会变色）。
        #   所以取色时 src[i+2]→B、src[i+1]→G、src[i]→R。
        # ③ 分层窗口要求 **预乘 alpha**：RGB 先乘 A/255 再填，否则半透明区域会糊。
        for i in range(0, n, 4):
            a = src[i + 3]
            if a == 0:
                dst[i] = dst[i + 1] = dst[i + 2] = dst[i + 3] = 0
            elif a == 255:
                dst[i], dst[i + 1], dst[i + 2] = src[i + 2], src[i + 1], src[i]
                dst[i + 3] = 255
            else:
                dst[i] = (src[i + 2] * a) // 255            # B
                dst[i + 1] = (src[i + 1] * a) // 255        # G
                dst[i + 2] = (src[i] * a) // 255            # R
                dst[i + 3] = a

        # ⚠️⚠️ `UpdateLayeredWindow` 的 **pptDst 是"窗口新的屏幕坐标"**，不是源图偏移！
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

        width, height, raw = _prepare_bitmap(self.icon_path)

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
