"""外链静默打开相关代码的自检（不参与程序运行）

用法（项目根目录）：
    python .ToolsGCP/tools/check_url_open.py

检查地址过滤 / Ctrl 观察器 / win32 抢前台辅助函数 / 非法地址返回值，
只查代码侧约定：不真的打开网址（那会弹出浏览器标签页）。
"""

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("TOOLSGCP_NO_SETTINGS_WRITE", "1")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = []


def check(ok, label, detail=""):
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""),
          flush=True)
    if not ok:
        FAILURES.append(label)


def main():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QWidget

    app = QApplication(sys.argv[:1])
    from pymodels.utils import url_open

    # 地址过滤
    check(url_open.is_web_url("https://www.nvidia.cn/software/nvidia-app/"),
          "https 地址算外链")
    check(url_open.is_web_url("http://example.com"), "http 地址算外链")
    check(not url_open.is_web_url("toolsgcp://api_key"),
          "内部协议不算外链（不能丢给浏览器）")
    check(not url_open.is_web_url(""), "空地址不算外链")
    check(not url_open.is_web_url("file:///C:/Windows"), "file 协议不算外链")

    # Ctrl 观察器
    check(url_open.install_ctrl_watcher(), "全程序 Ctrl 观察器装得上")
    check(isinstance(url_open.ctrl_active(), bool), "ctrl_active() 返回布尔值")
    check(not url_open.ctrl_active(), "没按 Ctrl 时 ctrl_active() 是 False")

    # win32 辅助函数（真实窗口）
    win = QWidget()
    win.resize(360, 200)
    win.setWindowTitle("ToolsGCP 外链自检窗口")
    win.show()

    def pump(rounds=6, ms=60):
        for _ in range(rounds):
            QTimer.singleShot(ms, app.quit)
            app.exec_()

    pump(8)
    if sys.platform == "win32":
        hwnd = int(win.winId())
        check(url_open._win_window_alive(hwnd), "自己的窗口被判为「活着」",
              f"hwnd=0x{hwnd:x}")
        check(url_open._win_foreground() != 0, "能取到前台窗口句柄",
              f"0x{url_open._win_foreground():x}")
        try:
            ok = url_open._win_set_foreground(hwnd)
            check(isinstance(ok, bool), "_win_set_foreground 正常返回",
                  f"返回 {ok}（前台锁定下失败是允许的）")
        except Exception as exc:
            check(False, "_win_set_foreground 不抛异常", str(exc))
        try:
            url_open._reclaim_foreground(hwnd)
            check(True, "_reclaim_foreground 排队重试不抛异常")
        except Exception as exc:
            check(False, "_reclaim_foreground 不抛异常", str(exc))
        pump(6)
        check(url_open._win_window_alive(hwnd), "重试跑完之后窗口还在")
        check(not url_open._win_window_alive(0), "空句柄不算活窗口")
    else:
        print("[..] 非 win32，跳过抢前台相关的检查")

    # 非法地址不落地（不会去开浏览器）
    check(url_open.open_url("", "空") is False, "空地址 open_url 返回 False")
    check(url_open.open_url("toolsgcp://api_key", "内部") is False,
          "内部协议 open_url 返回 False")
    check(url_open.open_clicked_url(None, "not a url") is False,
          "open_clicked_url 对非法地址返回 False")

    win.close()

    if FAILURES:
        print(f"\n[!!] {len(FAILURES)} 项失败")
        return 1
    print("\n[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
