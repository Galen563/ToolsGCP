"""GCP 工坊界面（左侧栏「收藏」下面的一页）。

⚠️ 页面刻意留空：不放工具入口 / 卡片 / 标题 / 署名；要加内容往 setup_ui 的 box 里追加。
"""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from qfluentwidgets import ScrollArea

from ..utils.smooth_scroll import install_smooth_scroll
from .settings.theme import SIZES, tokens

WORKSHOP_MARGIN = 32            # 上 / 左
WORKSHOP_SCROLLBAR_MARGIN = 8   # 右（滚动条贴边）
CONTENT_MAX_WIDTH = int(SIZES.get("content_max_width", 880))
CONTENT_SIDE_PADDING = 24       # 和搜索页 scroll_content 一致


class GCPWorkshopInterface(QWidget):
    """GCP 工坊（当前内容留空）

    # GCP工坊 —— Galne563 自制：内置好用的一些工具。
    """

    def __init__(self, language_manager=None, parent=None):
        super().__init__(parent)
        self.setObjectName("gcpWorkshopInterface")
        self.lang = language_manager
        self._content_width = 0
        self.setup_ui()
        self.refresh_theme(force=True)

    # ---------- 文案 ----------
    def get_text(self, key: str, fallback: str = "") -> str:
        if self.lang is not None:
            text = self.lang.get_text("nav", key)
            if text != key:
                return text
        return fallback or key

    # ---------- UI ----------
    def setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(WORKSHOP_MARGIN, WORKSHOP_MARGIN,
                                 WORKSHOP_SCROLLBAR_MARGIN, 16)
        outer.setSpacing(0)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        install_smooth_scroll(self.scroll_area)

        # 视口整宽（滚动条贴最右），内容本体由 _apply_content_width 收窄居中
        self.content_host = QWidget(self.scroll_area)
        self.content_host.setStyleSheet("background: transparent;")
        host_outer = QVBoxLayout(self.content_host)
        host_outer.setContentsMargins(CONTENT_SIDE_PADDING, 0,
                                     CONTENT_SIDE_PADDING, 0)
        host_outer.setSpacing(0)

        self.content_widget = QWidget(self.content_host)
        self.content_widget.setStyleSheet("background: transparent;")
        box = QVBoxLayout(self.content_widget)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        box.setAlignment(Qt.AlignTop)

        box.addStretch()

        host_outer.addWidget(self.content_widget, 0, Qt.AlignHCenter)
        self.scroll_area.setWidget(self.content_host)
        outer.addWidget(self.scroll_area, 1)

    # ---------- 宽度 / 主题 ----------
    def _apply_content_width(self):
        """内容本体限制在最大宽度内并居中（和搜索页 / 详情页同一套逻辑）"""
        available = max(0, self.scroll_area.viewport().width()
                        - 2 * CONTENT_SIDE_PADDING)
        width = max(1, min(CONTENT_MAX_WIDTH, available))
        if width == self._content_width:
            return
        self._content_width = width
        self.content_widget.setFixedWidth(width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._apply_content_width)

    def on_shown(self):
        """被切到前台时补齐宽度（第一次显示时视口宽度才有效）"""
        self._apply_content_width()

    def refresh_theme(self, force: bool = False):
        """按当前主题重算样式（search_interface.refresh_theme 会调到这里）"""
        from qfluentwidgets import isDarkTheme
        dark = bool(isDarkTheme())
        c = tokens(dark)
        signature = (dark, c.get("accent"))
        if not force and getattr(self, "_theme_signature", None) == signature:
            return
        self._theme_signature = signature

        self.setStyleSheet(f"""
            GCPWorkshopInterface, QWidget#gcpWorkshopInterface {{
                background: transparent;
            }}
        """)
