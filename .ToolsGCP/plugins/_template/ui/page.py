"""专属界面模块
一个页面对应一个类，都提供 on_show()：被切过来时调用一次（用来刷新数据）。
界面里只做显示和收集用户输入，真正的计算交给 core/logic.py。
"""

import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QListWidgetItem, QScrollArea, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, FluentIcon as FIF, LineEdit, ListWidget,
    PrimaryPushButton, SubtitleLabel,
)


class BasePage(QWidget):
    """所有页面的基类：统一留白 + on_show() 钩子"""

    def __init__(self, context, config, i18n, logic, parent=None):
        super().__init__(parent)
        self.context = context
        self.config = config
        self.i18n = i18n
        self.logic = logic

    def on_show(self):
        """被切到这个页面时调用（子类按需重写）"""
        pass


class HomePage(BasePage):
    """首页：放标题、统计数字和示例图片"""

    def __init__(self, context, config, i18n, logic, parent=None):
        super().__init__(context, config, i18n, logic, parent)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        layout.addWidget(SubtitleLabel(i18n.t("title"), content))
        layout.addWidget(BodyLabel(i18n.t("intro"), content))

        self.stats_label = BodyLabel("", content)
        layout.addWidget(self.stats_label)

        layout.addSpacing(6)

        # 示例：显示 assets/ 里的图片
        image_path = os.path.join(context.plugin_dir, "assets", "icon.png")
        if os.path.exists(image_path):
            image = QLabel(content)
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                image.setPixmap(pixmap.scaled(96, 96, Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation))
            layout.addWidget(image)

        self.times_label = CaptionLabel("", content)
        layout.addWidget(self.times_label)

        layout.addStretch()

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def on_show(self):
        """每次切过来：刷新统计 + 记一次打开次数"""
        summary = self.logic.summary()
        self.stats_label.setText(
            self.i18n.t("stats_line", total=summary["total"],
                        categories=summary["categories"],
                        repo=summary["with_repo"]))
        times = self.config.bump("open_times")
        self.times_label.setText(self.i18n.t("open_times", n=times))


class StatsPage(BasePage):
    """统计页：演示界面调用逻辑的标准写法"""

    def __init__(self, context, config, i18n, logic, parent=None):
        super().__init__(context, config, i18n, logic, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        layout.addWidget(SubtitleLabel(i18n.t("stats_title"), self))

        row = QHBoxLayout()
        self.search_edit = LineEdit(self)
        self.search_edit.setPlaceholderText(i18n.t("search_placeholder"))
        self.search_edit.returnPressed.connect(self.refresh)
        row.addWidget(self.search_edit, 1)

        button = PrimaryPushButton(i18n.t("search_button"), self, FIF.SEARCH)
        button.clicked.connect(self.refresh)
        row.addWidget(button)
        layout.addLayout(row)

        self.list = ListWidget(self)
        layout.addWidget(self.list, 1)

    def on_show(self):
        self.refresh()

    def refresh(self):
        """把用户输入交给 logic 处理，再把结果画出来"""
        keyword = self.search_edit.text().strip()
        self.list.clear()
        if keyword:
            items = self.logic.search(keyword)
            for item in items[:200]:
                self.list.addItem(QListWidgetItem(
                    f"{item.get('code', '')}  {item.get('name', '')}"))
            self.context.log(f"搜索 {keyword}，命中 {len(items)} 条")
            return

        for name, count in self.logic.count_by_category():
            self.list.addItem(QListWidgetItem(f"{name}  ({count})"))
