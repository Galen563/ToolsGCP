"""主题安全的对话框：替代 Qt 原生的 QInputDialog。

原生弹窗不跟随 qfluentwidgets 主题，深色模式下会出现浅色字 + 浅色底看不见。

⚠️ 不用 qfluentwidgets 的 MessageBoxBase：它在 parent=None 时会去读
window().width() 算尺寸并抛 AttributeError；本模块的弹窗任何时机建都不会炸。

用法：
    ok, value = ask_choice(self, "标题", "说明文字", ["选项1", "选项2"])
    ok, text = ask_text(self, "新建收藏夹", "名称：", "默认名字")
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QWidget)

from qfluentwidgets import (BodyLabel, ComboBox, LineEdit, PrimaryPushButton,
                            PushButton, SubtitleLabel, isDarkTheme)


# 两个通用按钮的多语言兜底（三种语言都写全，查不到时才用）
_DIALOG_FALLBACK = {
    "dialog_cancel": {"简体中文": "取消", "繁體中文": "取消", "English": "Cancel"},
    "dialog_ok": {"简体中文": "确定", "繁體中文": "確定", "English": "OK"},
}


def _dialog_text(key: str, default: str) -> str:
    """查一次界面语言（拿不到语言管理器就退回兜底）

    ⚠️ 优先用全程序那个当前的语言管理器，它才带上用户选的语言。
    """
    try:
        from ..core.language_manager import (LanguageManager,
                                             get_current_manager)
        manager = get_current_manager() or LanguageManager()
        for module in ("plugin", "settings"):
            try:
                text = manager.get_text(module, key)
            except Exception:
                text = key
            if text and text != key:
                return str(text)
        language = getattr(manager, "current_language", "简体中文")
        fallback = _DIALOG_FALLBACK.get(key, {})
        # ⚠️ 语言文件没给这条文案时一律用英文兜底，否则语言文件夹一移走就中英混杂
        return str(fallback.get("English") or default)
    except Exception:
        return default


def _dialog_qss() -> str:
    """弹窗自己的底色/文字色（跟随深浅主题）

    ⚠️ QDialog 是顶层窗口，不继承主窗口的样式表；不给它底色的话，
    深色主题下就是系统默认的浅色底 + 浅色字。
    """
    if isDarkTheme():
        bg, text, border = "#272727", "#E8E8E8", "#343434"
    else:
        bg, text, border = "#FFFFFF", "#1F2329", "#E6E9F0"
    return (f"QDialog {{ background-color: {bg}; }}\n"
            f"QDialog QLabel {{ color: {text}; background: transparent; }}")


class _BaseDialog(QDialog):
    """标题 + 说明 + 一个输入控件 + 确定/取消"""

    def __init__(self, parent, title: str, tip: str = "", subtitle: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        # ⚠️ 只给 QDialog 自己上底色：qfluentwidgets 的标签本来就跟随主题，不要插手
        if isDarkTheme():
            self.setStyleSheet("QDialog { background-color: #272727; }")
        else:
            self.setStyleSheet("QDialog { background-color: #FFFFFF; }")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 18)
        outer.setSpacing(12)

        self.title_label = SubtitleLabel(title, self)
        outer.addWidget(self.title_label)

        if subtitle:
            label = BodyLabel(subtitle, self)
            label.setWordWrap(True)
            outer.addWidget(label)

        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        if tip:
            tip_label = BodyLabel(tip, self.body)
            tip_label.setWordWrap(True)
            self.body_layout.addWidget(tip_label)
        outer.addWidget(self.body)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        # ⚠️ 标题/正文由调用方自己做 i18n，只有这两个通用按钮属于本模块，需自己查语言
        self.cancel_btn = PushButton(_dialog_text("dialog_cancel", "取消"), self)
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)
        self.ok_btn = PrimaryPushButton(_dialog_text("dialog_ok", "确定"), self)
        self.ok_btn.clicked.connect(self.accept)
        buttons.addWidget(self.ok_btn)
        outer.addLayout(buttons)

        self.setMinimumWidth(400)

    def value(self):
        raise NotImplementedError


class FluentChoiceDialog(_BaseDialog):
    """下拉选择（替代 QInputDialog.getItem）"""

    def __init__(self, parent, title: str, tip: str = "", items=None,
                 current: int = 0):
        super().__init__(parent, title, tip)
        self.combo = ComboBox(self.body)
        for item in (items or []):
            self.combo.addItem(str(item))
        if 0 <= current < self.combo.count():
            self.combo.setCurrentIndex(current)
        self.combo.setMinimumWidth(340)
        self.body_layout.addWidget(self.combo)

    def value(self):
        return self.combo.currentText()


class FluentInputDialog(_BaseDialog):
    """单行文本输入（替代 QInputDialog.getText）"""

    def __init__(self, parent, title: str, tip: str = "", text: str = "",
                 placeholder: str = ""):
        super().__init__(parent, title, tip)
        self.edit = LineEdit(self.body)
        self.edit.setText(str(text or ""))
        if placeholder:
            self.edit.setPlaceholderText(placeholder)
        self.edit.setMinimumWidth(340)
        self.edit.setClearButtonEnabled(True)
        self.body_layout.addWidget(self.edit)
        self.edit.selectAll()

    def value(self):
        return self.edit.text().strip()


def ask_choice(parent, title: str, tip: str = "", items=None, current: int = 0):
    """主题安全的下拉选择。返回 (是否确定, 选中的文字)"""
    dialog = FluentChoiceDialog(parent, title, tip, items, current)
    if dialog.exec_() != QDialog.Accepted:
        return False, ""
    return True, dialog.value()


def ask_text(parent, title: str, tip: str = "", text: str = "",
             placeholder: str = ""):
    """主题安全的文本输入。返回 (是否确定, 输入的文字)"""
    dialog = FluentInputDialog(parent, title, tip, text, placeholder)
    if dialog.exec_() != QDialog.Accepted:
        return False, ""
    return True, dialog.value()
