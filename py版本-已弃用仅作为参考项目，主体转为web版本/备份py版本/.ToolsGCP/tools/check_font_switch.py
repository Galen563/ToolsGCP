"""字体切换自检 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_font_switch.py

真建一个主窗口，统计切换前后的控件字体族并截图（浅色 + 深色）。
"""

import os
import sys
from collections import Counter
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"
OUT_DIR = TOOLS_DIR / "_out"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

TARGET = "KaiTi"


def families(app):
    """统计每个控件实际会用来渲染的字体族

    ⚠️ 必须用 font().families() 而不是 family()：setFamilies() 只改列表，
    而渲染用的是列表，用 family() 会把已切好的控件错报成旧字体。
    """
    counter = Counter()
    for widget in app.allWidgets():
        try:
            font = widget.font()
            names = font.families() or [font.family()]
            counter[names[0]] += 1
        except RuntimeError:
            continue
    return counter


def main():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.LIGHT, lazy=False)
    apply_app_palette(False)

    from pymodels.ui.main_window import MainWindow
    from pymodels.utils.fonts import apply_font, installed_families

    window = MainWindow()
    window.resize(1280, 880)
    window.show()
    for _ in range(10):
        QTimer.singleShot(120, app.quit)
        app.exec_()

    print(f"[..] {TARGET} 装了吗: {TARGET in installed_families()}")
    before = families(app)
    print(f"[..] 切换前字体族分布（前 6）: {before.most_common(6)}")

    applied = apply_font(TARGET)
    for _ in range(6):
        QTimer.singleShot(80, app.quit)
        app.exec_()

    after = families(app)
    print(f"[..] apply_font 返回: {applied}")
    print(f"[..] 切换后字体族分布（前 6）: {after.most_common(6)}")

    managed = before.get("Microsoft YaHei", 0) + before.get("微软雅黑", 0)
    switched = after.get(applied, 0)
    print(f"[OK] 旧字体控件 {managed} 个 → 新字体控件 {switched} 个")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(OUT_DIR / "font_kaiti.png"))
    print(f"[ok] {OUT_DIR / 'font_kaiti.png'}")

    # 再切回去，确认能切回默认字体（不是单向的）
    apply_font("微软雅黑")
    for _ in range(6):
        QTimer.singleShot(80, app.quit)
        app.exec_()
    back = families(app)
    print(f"[..] 切回微软雅黑后（前 6）: {back.most_common(6)}")
    window.grab().save(str(OUT_DIR / "font_default.png"))
    print(f"[ok] {OUT_DIR / 'font_default.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
