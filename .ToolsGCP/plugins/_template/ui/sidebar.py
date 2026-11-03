"""左侧栏模块
插件页面里竖向的导航条。不想用可以不建这个文件，直接在 app.py 里换成标签页。
    bar = Sidebar(i18n, parent)
    bar.currentChanged.connect(on_switch)   # on_switch(key)
    bar.set_current("home")
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentIcon as FIF, TransparentToolButton

# 一项 = 一个按钮：key 用于切换页面，icon 用 FluentIcon 的名字，text_key 是文案键
DEFAULT_ITEMS = [
    {"key": "home", "icon": "HOME", "text_key": "nav_home"},
    {"key": "stats", "icon": "PIE_SINGLE", "text_key": "nav_stats"},
]


class Sidebar(QWidget):
    """竖向导航条"""

    currentChanged = pyqtSignal(str)

    def __init__(self, i18n, parent=None, items=None, width: int = 148):
        super().__init__(parent)
        self.i18n = i18n
        self.items = items or DEFAULT_ITEMS
        self.buttons = {}
        self.current = ""

        self.setFixedWidth(width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(6)

        title = BodyLabel(i18n.t("nav_title"), self)
        title.setAlignment(Qt.AlignLeft)
        layout.addWidget(title)
        layout.addSpacing(6)

        for item in self.items:
            button = TransparentToolButton(self._icon(item["icon"]), self)
            button.setFixedHeight(36)
            button.setToolTip(i18n.t(item["text_key"]))
            button.clicked.connect(lambda _c=False, k=item["key"]: self._on_click(k))
            layout.addWidget(button)
            self.buttons[item["key"]] = button

        layout.addStretch()

    @staticmethod
    def _icon(name: str):
        """按名字取 FluentIcon，取不到就给个默认的"""
        return getattr(FIF, name, FIF.APPLICATION)

    def _on_click(self, key: str):
        self.set_current(key)
        self.currentChanged.emit(key)

    def set_current(self, key: str):
        """高亮当前项"""
        self.current = key
        for k, button in self.buttons.items():
            button.setChecked(k == key)
