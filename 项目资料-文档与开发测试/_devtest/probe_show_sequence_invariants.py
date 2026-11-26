# -*- coding: utf-8 -*-
"""lead 独立复核：show_window_on_gui_thread 的显示序列不变量（无头驱动真实函数体）。

要钉死的契约（本轮「窗口里的启动动画先小一圈、随后突然撑满」的修复）：
  A. show 那一刻之前的每一次原生 SetWindowPos 都不带 SWP_SHOWWINDOW；
  B. show 之前必须已经跑过一轮「显示前布局同步」，
     即第一次可见帧的内容层 bounds 已经等于目标客户区；
  C. r=1.0 基准机（建窗尺寸==目标、内容层已就位）：show 之后什么都不做
     （⑤ 对账相等就跳过）—— 零额外动作、逐像素不变；
  D. 尺寸对不上时：show 之后重设几何并再同步一轮布局；
  E. Padding 非对称时按 L/R/T/B 分别扣减，且第二次调用不重钉（幂等）。

做法：把 frame.win32 换成记录调用的假模块、on_gui_thread 换成立即执行，
再用假的 window/native 驱动**真实**的 _do 函数体。全程不建真窗口、不需要 pythonnet。
"""
import io
import os
import sys
import types

ROOT = os.getcwd()
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]

from desktop.native import frame                      # noqa: E402

SWP_SHOWWINDOW = 0x0040
results = []

# ⚠️ 必须在**任何** drive() 之前注册 System.Drawing 垫片：
#    _sync_client_layout 里"内容层 bounds ≠ 客户区"那条分支要
#    `from System.Drawing import Rectangle`（沙箱里没有 pythonnet）。
#    它被包在 try/except 里，注册晚了不会报错、只会**静默不重钉** ——
#    于是测出"钉过了"的假结论（第一版就踩了这个：D4 断言拿到旧 bounds）。
#    注册语句在下面的 SHIM 段落里（必须早于任何 drive() 调用）。


def check(name, cond, detail=None):
    results.append((name, bool(cond)))
    line = ("  OK    " if cond else "  FAIL  ") + name
    print(line + ("" if detail is None else "   <- " + repr(detail)))


class Size:
    def __init__(self, w, h):
        self.Width, self.Height = w, h


class Pad:
    def __init__(self, l=0, r=0, t=0, b=0):
        self.Left, self.Right, self.Top, self.Bottom = l, r, t, b


class Bounds:
    def __init__(self, x, y, w, h):
        self.X, self.Y, self.Width, self.Height = x, y, w, h


class Rect:
    """顶替 System.Drawing.Rectangle（沙箱里没有 pythonnet）"""
    def __init__(self, x, y, w, h):
        self.X, self.Y, self.Width, self.Height = x, y, w, h


class FakeWebView:
    def __init__(self, b):
        self.Bounds = b


class FakeNative:
    def __init__(self, client, pad, bounds):
        self.ClientSize = Size(*client)
        self.Padding = pad
        self.webview = FakeWebView(bounds)
        self.layout_calls = 0
        self.update_calls = 0

    def PerformLayout(self):
        self.layout_calls += 1

    def Update(self):
        self.update_calls += 1


class FakeWindow:
    def __init__(self, native):
        self.native = native
        self.shown = False


# ==== SHIM：注册 System.Drawing 垫片（必须早于任何 drive() 调用，见上面注释） ====
sys.modules.setdefault("System", types.ModuleType("System"))
sys.modules.setdefault("System.Drawing", types.ModuleType("System.Drawing"))
sys.modules["System.Drawing"].Rectangle = Rect


def make_fake(phys, dpi=1.0, work=(0, 0, 1920, 1032)):
    seq = []

    class U:
        @staticmethod
        def SetWindowPos(hwnd, after, x, y, w, h, flags):
            seq.append(("spos", int(flags), int(w), int(h)))
            return 1

        @staticmethod
        def IsIconic(hwnd):
            return 0

        @staticmethod
        def ShowWindow(hwnd, cmd):
            seq.append(("showwin", cmd, 0, 0))
            return 1

    class W:
        IS_WINDOWS = True
        user32 = U()

        @staticmethod
        def dpi_scale(hwnd):
            return dpi

        @staticmethod
        def work_area(hwnd=None):
            return work

        @staticmethod
        def rect_of(hwnd):
            return (100, 50, 100 + phys[0], 50 + phys[1])

    return seq, W()


def drive(logical_w, logical_h, native, fake_win32, seq):
    """用真实 _do 函数体跑一遍显示串，返回 seq（含 spos / sync / show 打点）"""
    old = (frame.win32, frame.on_gui_thread, frame._shown_event_ready,
           frame._sync_client_layout, getattr(FakeWindow, "show", None))
    real_sync = old[3]
    win = FakeWindow(native)
    frame.win32 = fake_win32
    frame._shown_event_ready = lambda w: True
    frame.on_gui_thread = lambda window, fn, timeout=None: (fn(), True)[1]
    frame._sync_client_layout = lambda window, after_show=False: (
        seq.append(("sync", after_show, 0, 0)), real_sync(window, after_show))
    FakeWindow.show = lambda self: seq.append(("show", None, None, None))
    try:
        frame.show_window_on_gui_thread(win, 1234, logical_w, logical_h)
    finally:
        (frame.win32, frame.on_gui_thread, frame._shown_event_ready,
         frame._sync_client_layout) = old[:4]
        if old[4] is None:
            del FakeWindow.show
        else:
            FakeWindow.show = old[4]
    return win, seq


print("[C] r=1.0 基准机：建窗尺寸==目标、内容层已就位")
native = FakeNative((1280, 842), Pad(), Bounds(0, 0, 1280, 842))
seq, fake = make_fake((1280, 880))
drive(1280, 880, native, fake, seq)
show_at = seq.index(("show", None, None, None))
before, after = seq[:show_at], seq[show_at + 1:]
check("A show 之前的 SetWindowPos 全部不带 SWP_SHOWWINDOW",
      all(not (f & SWP_SHOWWINDOW) for (k, f, _w, _h) in before if k == "spos"),
      [s for s in before if s[0] == "spos"])
check("B show 之前有一次显示前布局同步",
      any(k == "sync" and a is False for (k, a, _x, _y) in before), before)
check("B2 首帧内容层 bounds == 目标客户区",
      (native.webview.Bounds.Width, native.webview.Bounds.Height) == (1280, 842),
      (native.webview.Bounds.Width, native.webview.Bounds.Height))
check("C 基准机 show 之后不再改几何",
      not any(k == "spos" for (k, _f, _w, _h) in after), after)
check("C2 基准机 show 之后不再重钉布局",
      not any(k == "sync" and a is True for (k, a, _x, _y) in seq), seq)
check("C3 窗口确实被显示", any(k == "show" for (k, _a, _x, _y) in seq), seq)

print("\n[D] 尺寸未收敛（当前 900x620，目标 1280x880）")
native2 = FakeNative((1280, 842), Pad(), Bounds(0, 0, 500, 400))
seq2, fake2 = make_fake((900, 620))
drive(1280, 880, native2, fake2, seq2)
show_at2 = seq2.index(("show", None, None, None))
check("D show 之前仍不掀窗（无 SWP_SHOWWINDOW）",
      all(not (f & SWP_SHOWWINDOW) for (k, f, _w, _h) in seq2[:show_at2] if k == "spos"),
      [s for s in seq2[:show_at2] if s[0] == "spos"])
check("D2 show 之后重设几何（对账发现不一致才收敛）",
      any(k == "spos" for (k, _f, _w, _h) in seq2[show_at2 + 1:]), seq2[show_at2 + 1:])
check("D3 且补一次显示后布局同步",
      any(k == "sync" and a is True for (k, a, _x, _y) in seq2), seq2)
check("D4 显示前那次同步已把内容层钉到客户区",
      (native2.webview.Bounds.Width, native2.webview.Bounds.Height) == (1280, 842),
      (native2.webview.Bounds.Width, native2.webview.Bounds.Height))
check("D5 同步真的跑过布局（PerformLayout 被调用 ≥1 次）",
      native2.layout_calls >= 1, native2.layout_calls)

print("\n[E] Padding 非对称（lead 提的那点）")
native3 = FakeNative((1000, 700), Pad(3, 5, 7, 11), Bounds(0, 0, 500, 400))
frame._sync_client_layout(FakeWindow(native3))
b = native3.webview.Bounds
check("E1 宽 = client-Left-Right、高 = client-Top-Bottom、左上角 = (L, T)",
      (b.Width, b.Height, b.X, b.Y) == (992, 682, 3, 7), (b.Width, b.Height, b.X, b.Y))
frame._sync_client_layout(FakeWindow(native3))
check("E2 第二次调用不重钉（幂等，padding 场景也算进比较）",
      (native3.webview.Bounds.Width, native3.webview.Bounds.Height) == (992, 682),
      (native3.webview.Bounds.Width, native3.webview.Bounds.Height))

fails = [n for n, ok in results if not ok]
print("\n==== lead 独立复核: %d/%d 通过 ====" % (len(results) - len(fails), len(results)))
if fails:
    print("失败:", fails)
sys.exit(1 if fails else 0)