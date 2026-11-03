"""「左上角返回按钮 → Esc 也能返回」自检 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_back_esc.py

覆盖三处非 AI 的返回上级页面：反馈页大图页、GitHub 赞助二维码大图页、资源详情页。
"""

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = []


def check(ok, label, detail=""):
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def pump(app, rounds=4, ms=60):
    from PyQt5.QtCore import QTimer
    for _ in range(rounds):
        QTimer.singleShot(ms, app.quit)
        app.exec_()


def send_esc(app, widget):
    from PyQt5.QtCore import Qt, QEvent
    from PyQt5.QtGui import QKeyEvent
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    app.sendEvent(widget, event)
    pump(app, 3)


def main():
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.LIGHT, lazy=False)
    apply_app_palette(False)

    from pymodels.core.language_manager import LanguageManager
    from pymodels.core.settings_manager import SettingsManager

    lang = LanguageManager()
    settings = SettingsManager()

    # 1) 反馈页大图页
    from pymodels.interfaces.feedback_interface import FeedbackInterface
    feedback = FeedbackInterface(lang, settings)
    feedback.resize(1180, 800)
    feedback.show()
    pump(app, 5)

    cards = getattr(feedback, "qq_cards", [])
    check(bool(cards), "反馈页应当有 QQ 加群图片卡片", str(len(cards)))
    if cards:
        image_path = cards[0]._path
        feedback.show_full_image(image_path)
        pump(app, 4)
        check(feedback.page_stack.currentIndex() == 1,
              "点 QQ 图片应当进入大图页")
        send_esc(app, feedback)
        check(feedback.page_stack.currentIndex() == 0,
              "大图页按 Esc 应当返回反馈内容页",
              f"当前 index={feedback.page_stack.currentIndex()}")

        # 再进一次，这回直接点图片退出
        feedback.show_full_image(image_path)
        pump(app, 4)
        feedback.full_image_label.clicked.emit()
        pump(app, 3)
        check(feedback.page_stack.currentIndex() == 0,
              "再点一次图片应当退出大图页",
              f"当前 index={feedback.page_stack.currentIndex()}")

    # 2) GitHub 大图页
    from pymodels.interfaces.github_interface import GithubInterface
    github = GithubInterface(lang, settings)
    github.resize(1180, 800)
    github.show()
    pump(app, 5)
    qr = os.path.join(PROJECT_ROOT, ".ToolsGCP", "images",
                      "微信Galen563的ToolsGCP项目赞助.jpg")
    github.qr_path = qr
    github.show_full_image()
    pump(app, 4)
    if github.stack.currentIndex() == 1:
        send_esc(app, github)
        check(github.stack.currentIndex() == 0,
              "GitHub 大图页按 Esc 应当返回内容页",
              f"当前 index={github.stack.currentIndex()}")
    else:
        check(False, "GitHub 大图页没打开（图片路径可能不对）", qr)

    # 3) 资源详情页
    from pymodels.interfaces.resource_detail_interface import ResourceDetailInterface
    detail = ResourceDetailInterface(None, language_manager=lang)
    detail.resize(1180, 800)
    hits = []
    detail.back_requested.connect(lambda: hits.append(1))
    detail.show()
    pump(app, 4)
    send_esc(app, detail)
    check(bool(hits), "资源详情页按 Esc 应当发出「返回」信号", str(hits))

    # 4) 复制按钮样式（与 AI 的 copy 按钮同款：透明底 + 悬停淡底）
    if cards:
        button = feedback.qq_copy_buttons[0]
        qss = button.styleSheet()
        check("background: transparent" in qss.replace("  ", " "),
              "复制群号按钮应当是透明底（AI copy 按钮同款）", qss[:60])
        check("border-radius" in qss and "hover" in qss,
              "复制群号按钮应当有圆角 + 悬停底色")
        check(button.text() and button.icon() is not None and not button.icon().isNull(),
              "复制群号按钮的文字和图标逻辑不能被改掉",
              f"text={button.text()!r}")

    if FAILURES:
        print(f"\n[!!] {len(FAILURES)} 项失败")
        return 1
    print("\n[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
