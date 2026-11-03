"""UI 质检截图工具 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/ui_shot.py [tray|home|workshop|qq|chat|window]

输出到 .ToolsGCP/tools/_out/ 下。
"""

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"
OUT_DIR = TOOLS_DIR / "_out"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
# ⚠️ 截图脚本不该改用户真实设置：设了它 update_setting 只改内存、不落盘。
os.environ.setdefault("TOOLSGCP_NO_SETTINGS_WRITE", "1")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))


def _boot(dark: bool):
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.DARK if dark else Theme.LIGHT, lazy=False)
    apply_app_palette(dark)
    return app


def _save(widget, name):
    from PyQt5.QtCore import QTimer
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app = _boot(False)
    for _ in range(3):
        QTimer.singleShot(60, app.quit)
        app.exec_()
    path = OUT_DIR / name
    widget.grab().save(str(path))
    print(f"[ok] {path}")


def shot_tray():
    from PyQt5.QtCore import QPoint, QTimer
    from pymodels.core.language_manager import LanguageManager
    from pymodels.ui.tray_menu import make_tray_menu

    hits = []
    for dark in (False, True):
        app = _boot(dark)
        lang = LanguageManager()
        menu = make_tray_menu(lang, {k: (lambda n=k: hits.append(n))
                                     for k in ("home", "search", "ai", "exit")})
        menu.popup(QPoint(200, 200))
        for _ in range(6):
            QTimer.singleShot(40, app.quit)
            app.exec_()
        name = "tray_dark.png" if dark else "tray_light.png"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / name
        menu.grab().save(str(path))
        print(f"[ok] {path}  size={menu.width()}x{menu.height()} "
              f"items={[a.text() for a in menu.actions()]}")
        menu.close()


def shot_home():
    from PyQt5.QtCore import QTimer
    from pymodels.core.language_manager import LanguageManager
    from pymodels.interfaces.home_interface import HomeInterface

    for dark, name in ((False, "home_light.png"), (True, "home_dark.png")):
        app = _boot(dark)
        page = HomeInterface(LanguageManager(), None)
        page.resize(1180, 800)
        page.show()
        for _ in range(8):
            QTimer.singleShot(80, app.quit)
            app.exec_()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / name
        page.grab().save(str(path))
        print(f"[ok] {path}")
        page.close()


def shot_workshop():
    from PyQt5.QtCore import QTimer
    from pymodels.core.language_manager import LanguageManager
    from pymodels.interfaces.gcp_workshop_interface import GCPWorkshopInterface

    for dark, name in ((False, "workshop_light.png"), (True, "workshop_dark.png")):
        app = _boot(dark)
        page = GCPWorkshopInterface(LanguageManager())
        page.resize(1180, 800)
        page.show()
        for _ in range(6):
            QTimer.singleShot(60, app.quit)
            app.exec_()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / name
        page.grab().save(str(path))
        labels = [w.text() for w in page.findChildren(type(page))
                  if hasattr(w, "text")]
        print(f"[ok] {path}  text_labels={labels}")
        page.close()


def shot_qq():
    from PyQt5.QtCore import QTimer
    from pymodels.core.language_manager import LanguageManager
    from pymodels.interfaces.feedback_interface import FeedbackInterface

    for dark, tag in ((False, "light"), (True, "dark")):
        app = _boot(dark)
        page = FeedbackInterface(LanguageManager(), None)
        page.resize(1180, 800)
        page.show()
        for _ in range(8):
            QTimer.singleShot(80, app.quit)
            app.exec_()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        page.grab().save(str(OUT_DIR / f"feedback_{tag}.png"))
        print(f"[ok] feedback_{tag}.png")
        path = page.qq_cards[0]._path if getattr(page, "qq_cards", None) else ""
        if path:
            page.show_full_image(path)
            for _ in range(4):
                QTimer.singleShot(60, app.quit)
                app.exec_()
            page.grab().save(str(OUT_DIR / f"feedback_full_first_{tag}.png"))
            lbl = page.full_image_label
            pm = lbl.pixmap()
            print(f"[ok] feedback_full_first_{tag}.png  pixmap="
                  f"{pm.width() if pm else 0}x{pm.height() if pm else 0} "
                  f"viewport={page.image_scroll.viewport().width()}x"
                  f"{page.image_scroll.viewport().height()}")
        page.close()


def _chat_messages():
    return [
        {"role": "user", "content": "帮我找个局域网传文件的工具", "ts": "2026-01-01 10:00:00"},
        {"role": "assistant",
         "content": "推荐 **LocalSend**：跨平台、开源、免登录，手机和电脑在同一个 Wi-Fi 下"
                    "就能直接互传。\n\n它的特点是：\n1. 不需要服务器中转；\n2. 支持 Windows / macOS / "
                    "Linux / Android / iOS；\n3. 传输走的是局域网，速度取决于路由器。",
         "ts": "2026-01-01 10:00:05"},
        {"role": "user", "content": "@LocalSend(TG-000001) 这个怎么用？", "ts": "2026-01-01 10:01:00"},
        {"role": "assistant", "content": "打开就能用，两端都装好之后会自动互相发现。",
         "ts": "2026-01-01 10:01:03"},
        {"role": "user", "content": "好", "ts": "2026-01-01 10:02:00"},
        {"role": "assistant", "content": "还有别的想找的随时说。", "ts": "2026-01-01 10:02:02"},
    ]


class _FakeMainWindow:

    def __init__(self, parent=None):
        from PyQt5.QtWidgets import QWidget as _W
        self._widget = _W(parent)
        from pymodels.core.language_manager import LanguageManager
        from pymodels.core.settings_manager import SettingsManager
        self.language_manager = LanguageManager()
        self.settings_manager = SettingsManager()
        self.titleBar = _W(self._widget)


def shot_chat():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QFrame, QVBoxLayout, QWidget
    from pymodels.ui.ai_chat_panel import AIChatDrawer

    for dark, tag in ((False, "light"), (True, "dark")):
        app = _boot(dark)
        fake = _FakeMainWindow()

        # ① 抽屉形态（420 宽）
        holder = QWidget()
        holder.resize(420, 760)
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        drawer = AIChatDrawer(fake, holder, embedded=True)
        lay.addWidget(drawer)
        drawer.session.messages = [dict(m) for m in _chat_messages()]
        drawer._render_session()
        holder.show()
        for _ in range(10):
            QTimer.singleShot(80, app.quit)
            app.exec_()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        drawer.sync_bubble_width()
        for _ in range(3):
            QTimer.singleShot(60, app.quit)
            app.exec_()
        holder.grab().save(str(OUT_DIR / f"chat_drawer_{tag}.png"))
        print(f"[ok] chat_drawer_{tag}.png")

        # ② 空会话（默认对话已删掉）
        empty = QWidget()
        empty.resize(420, 760)
        lay2 = QVBoxLayout(empty)
        lay2.setContentsMargins(0, 0, 0, 0)
        drawer2 = AIChatDrawer(fake, empty, embedded=True)
        lay2.addWidget(drawer2)
        empty.show()
        for _ in range(8):
            QTimer.singleShot(60, app.quit)
            app.exec_()
        empty.grab().save(str(OUT_DIR / f"chat_empty_{tag}.png"))
        bubbles = [w for w in drawer2.message_host.findChildren(QFrame)
                   if w.__class__.__name__ == "ChatBubble"]
        print(f"[ok] chat_empty_{tag}.png  bubbles={len(bubbles)}")

        # ③ 侧边栏整页形态（1180 宽）
        page_holder = QWidget()
        page_holder.resize(1180, 800)
        lay3 = QVBoxLayout(page_holder)
        lay3.setContentsMargins(32, 32, 8, 16)
        drawer3 = AIChatDrawer(fake, page_holder, embedded=True)
        lay3.addWidget(drawer3)
        drawer3.session.messages = [dict(m) for m in _chat_messages()]
        drawer3._render_session()
        page_holder.show()
        for _ in range(10):
            QTimer.singleShot(90, app.quit)
            app.exec_()
        drawer3.sync_bubble_width()
        for _ in range(3):
            QTimer.singleShot(60, app.quit)
            app.exec_()
        page_holder.grab().save(str(OUT_DIR / f"chat_page_{tag}.png"))
        print(f"[ok] chat_page_{tag}.png")

        holder.close()
        empty.close()
        page_holder.close()


def shot_window():
    """真主窗口里截图（最接近用户看到的样子）；用法：python .ToolsGCP/tools/ui_shot.py window [home|workshop|feedback|search|settings]
    """
    from PyQt5.QtCore import QTimer

    page_name = sys.argv[2] if len(sys.argv) > 2 else "home"
    for dark, tag in ((False, "light"), (True, "dark")):
        app = _boot(dark)
        from pymodels.ui.main_window import MainWindow
        window = MainWindow()
        window.resize(1280, 880)
        window.show()
        for _ in range(12):
            QTimer.singleShot(110, app.quit)
            app.exec_()

        page = getattr(window, {
            "home": "homeInterface",
            "workshop": "workshopInterface",
            "feedback": "feedbackInterface",
            "search": "searchInterface",
            "settings": "settingsInterface",
            "plugins": "pluginInterface",
            "github": "githubInterface",
            "notice": "noticeInterface",
        }.get(page_name, "homeInterface"), None)
        if page is not None:
            window.switchTo(page)
            for _ in range(8):
                QTimer.singleShot(110, app.quit)
                app.exec_()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"window_{page_name}_{tag}.png"
        # ⚠️ 抓窗口句柄像素，不是 widget.grab()：半透明顶层窗口用 grab() 看着像"界面残缺"。
        shot = None
        try:
            screen = app.primaryScreen()
            shot = screen.grabWindow(int(window.winId()))
        except Exception:
            shot = None
        if shot is None or shot.isNull():
            shot = window.grab()
        shot.save(str(path))
        print(f"[ok] {path}  {shot.width()}x{shot.height()}")
        window.close()


SHOTS = {"tray": shot_tray, "home": shot_home,
         "workshop": shot_workshop, "qq": shot_qq, "chat": shot_chat,
         "window": shot_window}


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "tray"
    if target not in SHOTS:
        print("usage: ui_shot.py [tray|home|workshop|qq]")
        return 2
    SHOTS[target]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
