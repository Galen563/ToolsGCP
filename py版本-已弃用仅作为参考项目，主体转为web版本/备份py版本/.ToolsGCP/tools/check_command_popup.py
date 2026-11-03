""""/命令候选面板"排版自检 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_command_popup.py

拉起聊天面板往输入框打 "/p"，量候选面板几何并截图到 _out/command_popup_*.png。
"""

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"
OUT_DIR = TOOLS_DIR / "_out"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = []


def check(ok, label, detail=""):
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def _pump(app, times=6, ms=40):
    from PyQt5.QtCore import QTimer
    for _ in range(times):
        QTimer.singleShot(ms, app.quit)
        app.exec_()


class _FakeMainWindow:
    def __init__(self, parent=None):
        from PyQt5.QtWidgets import QWidget
        self._widget = QWidget(parent)
        from pymodels.core.language_manager import LanguageManager
        from pymodels.core.settings_manager import SettingsManager
        self.language_manager = LanguageManager()
        self.settings_manager = SettingsManager()
        self.titleBar = QWidget(self._widget)


def shot_real_window():
    """最接近用户看到的样子：真主窗口 + 右侧抽屉形态，打 /p 之后抓窗口句柄"""
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.LIGHT, lazy=False)
    apply_app_palette(False)

    from pymodels.ui.main_window import MainWindow
    window = MainWindow()
    window.resize(1280, 880)
    window.show()
    _pump(app, 14, 100)
    window.open_ai_drawer(focus=True)
    _pump(app, 10, 100)

    drawer = window.ai_chat_drawer
    page = getattr(window, "aiSidebarPage", None)
    if page is not None and getattr(page, "_drawer", None) is not None:
        # 用户设置里开着「改用侧边栏 AI 单独界面」→ 真正在用的是本页那份面板
        drawer = page.drawer
        print("[info] 用的是 aiSidebarPage 里那份聊天面板")
    drawer.input_edit.setPlainText("/plugin")
    drawer.input_edit.setPlainText("/p")
    _pump(app, 10, 90)

    popup = getattr(drawer, "_command_popup", None)
    if popup is None or not popup.isVisible():
        print("[!!] 真窗口里候选面板没出现 —— 插件可能没登记 /plugin（先确认插件是开着的）")
        window.close()
        return 1

    top_left = popup.mapTo(window, QPoint(0, 0))
    print(f"[info] 窗口里的面板位置={top_left.x()},{top_left.y()} "
          f"{popup.width()}x{popup.height()}")
    from PyQt5.QtGui import QFontMetrics
    for insert, label in getattr(popup, "_items", []):
        metrics = QFontMetrics(label.font())
        needed = metrics.height() + 12
        print(f"[info] 条目「{insert}」={label.x()},{label.y()} "
              f"{label.width()}x{label.height()} font={label.font().pixelSize()}/"
              f"{label.font().pointSizeF()} family={label.font().family()} "
              f"文字高={metrics.height()} 需要≈{needed} "
              f"够装={'是' if label.height() >= needed else '否'}")
        print(f"[info] text={label.text()!r}")
        check(label.height() >= needed,
              f"候选「{insert}」的控件高度够不够装下文字",
              f"控件高={label.height()} 需要≈{needed} 文字高={metrics.height()}")
        check_ink_not_clipped(popup, label, insert)
    drawer_widget = popup.parentWidget()
    try:
        in_top = drawer.input_edit.mapTo(drawer_widget, QPoint(0, 0)).y()
        print(f"[info] 面板底={popup.y() + popup.height()} 输入框顶={in_top} "
              f"间隙={in_top - (popup.y() + popup.height())}")
    except Exception as exc:
        print(f"[info] 量输入框位置失败: {exc!r}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shot = None
    try:
        shot = app.primaryScreen().grabWindow(int(window.winId()))
    except Exception:
        shot = None
    if shot is None or shot.isNull():
        shot = window.grab()
    path = OUT_DIR / "command_popup_window.png"
    shot.save(str(path))
    print(f"[ok] {path}  {shot.width()}x{shot.height()}")
    window.close()
    return 0


def _ink_box(image, rect, dark=False):
    """在 rect 区域里找"文字像素"的包围盒，找不到返回 None

    判据：不透明（alpha ≥ 250）且亮度和面板底色差别够大。
    ⚠️ 必须排掉半透明像素：圆角处 grab() 拿到的是 alpha=0 的黑，会误报"被裁"。
    """
    top = bottom = None
    left = right = None
    for y in range(rect.top(), min(rect.bottom(), image.height())):
        for x in range(rect.left(), min(rect.right(), image.width())):
            color = image.pixelColor(x, y)
            if color.alpha() < 250:
                continue
            lum = (color.red() + color.green() + color.blue()) / 3
            if (lum > 150) if dark else (lum < 120):
                if top is None:
                    top = y
                bottom = y
                left = x if left is None else min(left, x)
                right = x if right is None else max(right, x)
    if top is None:
        return None
    return (left, top, right, bottom)


def check_ink_not_clipped(popup, label, insert):
    from PyQt5.QtCore import QRect
    try:
        from qfluentwidgets import isDarkTheme
        dark = bool(isDarkTheme())
    except Exception:
        dark = False
    image = popup.grab().toImage()
    # ⚠️ grab() 的图在 DPI 缩放下是物理像素，label.x()/width() 是逻辑像素，不换算会误判"被裁"
    ratio = (image.width() / popup.width()) if popup.width() else 1.0
    rect = QRect(round(label.x() * ratio), round(label.y() * ratio),
                 round(label.width() * ratio), round(label.height() * ratio))
    box = _ink_box(image, rect, dark)
    if box is None:
        check(False, f"候选「{insert}」的文字应当画得出来", "一个文字像素都没找到")
        return
    left, top, right, bottom = box
    # 上下各留 1px 以上才算没被裁
    margin_top = top - rect.top()
    margin_bottom = rect.bottom() - 1 - bottom
    check(margin_top >= 1 and margin_bottom >= 1,
          f"候选「{insert}」的文字上下不能被裁",
          f"文字行={top}..{bottom} 条目={rect.top()}..{rect.bottom()} "
          f"上留白={margin_top} 下留白={margin_bottom}")
    check(left > rect.left() and right < rect.right() - 1,
          f"候选「{insert}」的文字左右不能被裁",
          f"文字列={left}..{right} 条目={rect.left()}..{rect.right()}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "window":
        return shot_real_window()

    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.LIGHT, lazy=False)
    apply_app_palette(False)
    # ⚠️ 必须把用户设置的界面字体也装上，否则量出的高度偏小、自检会假通过
    try:
        from pymodels.core.settings_manager import SettingsManager
        from pymodels.utils.fonts import apply_font
        apply_font(str(SettingsManager().settings.get("ui_font_family") or ""))
    except Exception as exc:
        print(f"[warn] 装界面字体失败（自检结果可能偏松）: {exc!r}")

    # 装一条和「插件制作辅助」一样的命令（source 留空 = 主程序登记，永远算开着）
    from pymodels.core.ai.chat_hints import get_hint_registry
    get_hint_registry().register(
        hint_id="gcp-plugin-maker",
        label={"zh_CN": "AI帮你制作插件", "zh_TW": "AI幫你做外掛", "en_US": "let AI build a plugin"},
        insert="/plugin", prompt="", priority=10, source="")

    from pymodels.ui.ai_chat_panel import AIChatDrawer

    holder = QWidget()
    holder.resize(460, 760)
    lay = QVBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    drawer = AIChatDrawer(_FakeMainWindow(), holder, embedded=True)
    lay.addWidget(drawer)
    holder.show()
    _pump(app, 10, 70)

    drawer.input_edit.setPlainText("/p")
    _pump(app, 8, 60)

    popup = getattr(drawer, "_command_popup", None)
    check(popup is not None and popup.isVisible(), "打 /p 时候选面板应当出现",
          f"popup={popup!r}")
    if popup is None or not popup.isVisible():
        return 1

    items = getattr(popup, "_items", [])
    check(bool(items), "面板里应当至少有一条候选", f"items={len(items)}")

    for insert, label in items:
        # ⚠️ 控件高度不够 = 字被裁
        metrics = QFontMetrics(label.font())
        needed = metrics.height() + 12          # QSS 里 padding: 6px 10px
        print(f"[info] 条目字体 pixelSize={label.font().pixelSize()} "
              f"family={label.font().family()} 行高={metrics.height()} "
              f"需要≈{needed} 实际高={label.height()}")
        check(label.height() >= needed,
              f"候选「{insert}」的控件高度够不够装下文字",
              f"控件高={label.height()} 需要≈{needed} 文字高={metrics.height()}")
        check_ink_not_clipped(popup, label, insert)

    input_top = drawer.input_edit.mapTo(drawer, drawer.input_edit.rect().topLeft()).y()
    popup_bottom = popup.y() + popup.height()
    check(popup_bottom <= input_top,
          "面板底边不应压住输入框", f"面板底={popup_bottom} 输入框顶={input_top}")
    check(popup.y() >= 0, "面板顶边不应跑到面板外面", f"y={popup.y()}")

    print(f"[info] 面板={popup.x()},{popup.y()} {popup.width()}x{popup.height()} "
          f"输入框顶={input_top}")
    print(f"[info] 布局 minimumSize={popup._layout.minimumSize().height()} "
          f"item_h={getattr(popup, '_item_h', None)} items={len(items)}")
    for insert, label in items:
        print(f"[info] 条目「{insert}」="
              f"{label.x()},{label.y()} {label.width()}x{label.height()} "
              f"text={label.text()!r}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    holder.grab().save(str(OUT_DIR / "command_popup_light.png"))
    popup.grab().save(str(OUT_DIR / "command_popup_only_light.png"))
    print(f"[ok] {OUT_DIR / 'command_popup_light.png'}")
    print(f"[ok] {OUT_DIR / 'command_popup_only_light.png'}")

    holder.close()
    if FAILURES:
        print(f"\n[!!] {len(FAILURES)} 项失败")
        return 1
    print("\n[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
