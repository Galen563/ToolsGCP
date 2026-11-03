"""搜索页滚动性能探针 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/perf_search_scroll.py

投递真实 QWheelEvent 并统计视口重绘的帧间隔（p50 / p90 / 最差 / 丢帧）。
"""

import os
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    from PyQt5.QtCore import QEvent, QObject, QPoint, QTimer, Qt
    from PyQt5.QtGui import QWheelEvent
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])

    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.LIGHT, lazy=False)
    apply_app_palette(False)

    from pymodels.core.settings_manager import SettingsManager
    from pymodels.core.favorites_manager import FavoritesManager
    from pymodels.core.language_manager import LanguageManager
    from pymodels.interfaces.search_interface import SearchInterface

    settings = SettingsManager()
    favorites = FavoritesManager()
    lang = LanguageManager()
    page = SearchInterface(settings, lang, favorites)
    page.resize(1180, 800)
    page.show()

    # 让首屏渲染完（要跑真事件循环，别用 processEvents 忙等）
    for _ in range(6):
        QTimer.singleShot(120, app.quit)
        app.exec_()

    framework = page.apps_framework
    viewport = page.scroll_area.viewport()
    bar = page.scroll_area.verticalScrollBar()

    if "--before" in sys.argv:
        # 把优化临时改回旧行为，用于 A/B 对照
        from pymodels.widgets import apps_index_framework as aif
        aif.BUFFER_SCREENS = 1.0
        aif.ICON_BUDGET_MS = 10_000.0
        framework.MAX_ASSIGN_PER_PASS = 10_000

        def old_maybe(self):
            vp = self._viewport_widget
            if vp is None or not self._groups:
                return
            top = self._viewport_top()
            anchor = self._window_anchor
            if anchor is not None:
                step = max(60, vp.viewport().height() // 2)
                if abs(top - anchor) < step:
                    return
            self._apply_window()

        import types
        framework._maybe_apply_window = types.MethodType(old_maybe, framework)
        print("[..] MODE=before (optimizations disabled)")

    print(f"[..] items={len(framework.items)} alive_cards="
          f"{len(framework._rendered_cards())} scroll_max={bar.maximum()}")

    frames = []

    class PaintWatch(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Paint:
                frames.append(time.perf_counter())
            return False

    paint_watch = PaintWatch()
    viewport.installEventFilter(paint_watch)

    # 一格 = 120 单位角度
    def wheel(delta):
        ev = QWheelEvent(viewport.rect().center(), QPoint(0, 0),
                         QPoint(0, 0), QPoint(0, delta),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        app.sendEvent(viewport, ev)

    t0 = time.perf_counter()
    stop_at = t0 + 2.4
    tick = {"n": 0}

    def tick_wheel():
        # 每 90ms 滚一格，模拟用户连续滚动
        tick["n"] += 1
        wheel(-120)

    timer = QTimer()
    timer.setInterval(90)
    timer.timeout.connect(tick_wheel)
    timer.start()
    QTimer.singleShot(2400, app.quit)
    app.exec_()
    timer.stop()

    if len(frames) < 5:
        print("[!!] no repaint captured")
        return 1

    gaps = [(frames[i] - frames[i - 1]) * 1000.0 for i in range(1, len(frames))]
    gaps_sorted = sorted(gaps)
    n = len(gaps_sorted)
    p50 = gaps_sorted[n // 2]
    p90 = gaps_sorted[int(n * 0.9)]
    dropped = sum(1 for g in gaps if g > 16.7)
    bad = sum(1 for g in gaps if g > 33.0)
    print(f"[OK] frames={len(frames)}  p50={p50:.1f}ms  p90={p90:.1f}ms  "
          f"worst={max(gaps):.1f}ms  mean={sum(gaps) / n:.1f}ms")
    print(f"[..] dropped(>16.7ms)={dropped}/{n}  very_bad(>33ms)={bad}")
    print(f"[..] final scroll={bar.value()} alive_cards="
          f"{len(framework._rendered_cards())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
