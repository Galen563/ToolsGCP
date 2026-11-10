# -*- coding: utf-8 -*-
"""托盘菜单 hover 状态机单测（win-visual 第 3 项：鼠标移出菜单后高亮残留）。

不弹窗、不联网：把 TrayMenu 的 _draw / _hit_test / _track_mouse_leave 换成假的，
只验**状态逻辑**：
  ① 窗口内移动 → hover 跟着命中项变；
  ② 第一次收到 mousemove 会申请 TrackMouseEvent(TME_LEAVE)（一次性）；
  ③ WM_MOUSELEAVE（_on_mouse_leave）→ hover 清零 + 重绘 + 允许重新申请；
  ④ 移出去再回来 → 重新申请 leave，不会"永远不再通知"。
跑法：python "项目资料-文档与开发测试/_devtest/test_traymenu_hover.py"
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

from desktop.native import traymenu as TM                    # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


class _FakeItem:
    def __init__(self, sep=False):
        self.separator = sep
        self.callback = None


def make_menu():
    menu = TM.TrayMenu(items=[_FakeItem(), _FakeItem(True), _FakeItem(), _FakeItem()])
    menu.hwnd = 12345          # 假句柄（TrackMouseEvent 被换掉，不会真调）
    draws = []
    tracks = []
    menu._draw = lambda: draws.append(menu._hover)
    # 命中表：y 0-27 → 0；分隔线 → -1；27-54 → 2；54-81 → 3
    rows = [(0, _FakeItem(), 0, 27), (1, _FakeItem(True), 27, 27),
            (2, _FakeItem(), 54, 27), (3, _FakeItem(), 81, 27)]
    menu._size = (120, 108)
    menu._rows = lambda: (rows, 120)
    real_track = TM._track_mouse_leave
    TM._track_mouse_leave = lambda hwnd: tracks.append(int(hwnd))
    try:
        return menu, draws, tracks, real_track
    finally:
        pass


menu, draws, tracks, real_track = make_menu()
try:
    print("[1] 窗口内移动：hover 跟手")
    menu._on_mouse_move(0 | (5 << 16))            # (0,5) → 第 0 项
    check("第一次 mousemove 申请了 TME_LEAVE", tracks == [12345], str(tracks))
    check("hover=0", menu._hover == 0)
    menu._on_mouse_move(0 | (60 << 16))           # → 第 2 项
    check("hover 变成 2", menu._hover == 2)
    check("TrackMouseEvent 一次性：没重复申请", tracks == [12345], str(tracks))

    print("[2] 移出窗口（WM_MOUSELEAVE）：高亮必须清零")
    menu._on_mouse_leave()
    check("hover 被清成 -1", menu._hover == -1, str(menu._hover))
    check("清零后重画过一次（最后一笔是 -1）", draws[-1] == -1, str(draws))
    check("leave 标志重置（允许回来时重新申请）", menu._tracking_leave is False)

    print("[3] 回来再出去：能再次收到 leave 通知")
    menu._on_mouse_move(0 | (90 << 16))           # → 第 3 项
    check("回来重新申请 leave", tracks == [12345, 12345], str(tracks))
    check("hover=3", menu._hover == 3)
    menu._on_mouse_leave()
    check("再次移出 → 再次清零", menu._hover == -1)

    print("[4] 消息分发：proc 里 WM_MOUSELEAVE 有分支（静态接线检查）")
    src = open(os.path.join(ROOT, ".ToolsGCP", "desktop", "native", "traymenu.py"),
               encoding="utf-8").read()

    check("窗口过程处理 WM_MOUSELEAVE 并调 _on_mouse_leave",
          "WM_MOUSELEAVE" in src and "_on_mouse_leave()" in src)
finally:
    TM._track_mouse_leave = real_track

print()
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL OK")
