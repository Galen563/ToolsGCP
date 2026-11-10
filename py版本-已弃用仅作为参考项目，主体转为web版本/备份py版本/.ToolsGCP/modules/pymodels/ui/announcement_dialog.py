"""公告弹窗（"检查更新"那种窗口内弹窗）：只弹最新发布的那一条公告。

⚠️ 父对象必须是顶层窗口（self.window()），遮罩才会盖住整个窗口。
⚠️ 文案通过构造时传进来的 t 回调取，本模块不 import 界面层（避免 ui → interfaces 反向依赖）。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (BodyLabel, CaptionLabel, MessageBoxBase,
                            PushButton, SmoothScrollArea, StrongBodyLabel,
                            SubtitleLabel)

from .update_dialog import _is_dark, _panel_colors, logo_pixmap

# 单条正文最多显示多少字（公告几千字时超长 QLabel 排版会明显变慢）
DIALOG_BODY_LIMIT = 2000

# 正文面板高度：只放一条公告，不用太高
DIALOG_BODY_HEIGHT = 220

# 未读红点颜色（同左侧栏）
BADGE_LIGHT = "#FA5151"
BADGE_DARK = "#F74C4C"


def _clip(text, limit=DIALOG_BODY_LIMIT):
    """超长正文截断（保留前 limit 个字符 + 省略号）"""
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "……"


class AnnouncementDialog(MessageBoxBase):
    """窗口内弹窗：只展示最新发布的那一条公告

    按钮结果在 dialog.action："view"（查看公告）/ "read"（全部已读）/ ""（关掉）。
    """

    def __init__(self, parent, t, item, unread_count=None):
        super().__init__(parent)
        self.t = t
        # ⚠️ 只弹最新那一条：传进来即使是一串，也只取第一条
        if isinstance(item, (list, tuple)):
            item = item[0] if item else {}
        self.item = dict(item or {})
        self.action = ""

        total = int(unread_count if unread_count is not None else 1)
        self.unread_total = max(1, total)

        self.titleLabel = SubtitleLabel(t("notice_dialog_title"), self.widget)
        self.viewLayout.addWidget(self.titleLabel)

        self.viewLayout.addLayout(self._build_header(total))
        self.viewLayout.addWidget(self._build_body())

        # ⚠️ "还有 N 条"必须放在滚动面板外面，否则正文一长这句就被顶出去
        rest = max(0, self.unread_total - 1)
        if rest > 0:
            more = CaptionLabel(t("notice_dialog_more").format(n=rest), self.widget)
            more.setWordWrap(True)
            more.setStyleSheet("color: rgba(128,128,128,1);")
            self.viewLayout.addWidget(more)

        hint = CaptionLabel(t("notice_dialog_hint"), self.widget)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: rgba(128,128,128,1);")
        self.viewLayout.addWidget(hint)

        self.yesButton.setText(t("notice_btn_view"))
        self.cancelButton.setText(t("notice_btn_later"))

        self.markButton = PushButton(t("notice_mark_all_read"), self.buttonGroup)
        self.markButton.clicked.connect(self._on_mark_all_read)
        self._reorder_buttons()

        self.widget.setMinimumWidth(560)

    # ---------- 顶部：图标 + 未读条数 ----------

    def _build_header(self, total):
        row = QHBoxLayout()
        row.setSpacing(14)

        logo = CaptionLabel("", self.widget)
        logo.setFixedSize(56, 56)
        logo.setAlignment(Qt.AlignCenter)
        pixmap = logo_pixmap(56)
        if pixmap is not None:
            logo.setPixmap(pixmap)
        row.addWidget(logo)

        column = QVBoxLayout()
        column.setSpacing(6)

        # 未读条数：红色小胶囊
        text = self.t("notice_unread_count").format(n=total)
        badge = CaptionLabel(text, self.widget)
        badge.setStyleSheet(
            f"color: #FFFFFF; background: {BADGE_DARK if _is_dark() else BADGE_LIGHT};"
            "border-radius: 9px; padding: 1px 9px;")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedHeight(20)

        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.addWidget(badge)
        badge_row.addStretch(1)
        column.addLayout(badge_row)
        column.addStretch(1)

        row.addLayout(column, 1)
        return row

    # ---------- 中间：这一条公告（可滚动） ----------

    def _build_body(self):
        panel = QFrame(self.widget)
        background, border = _panel_colors()
        panel.setStyleSheet(
            f"QFrame {{ background: {background}; border: 1px solid {border}; "
            "border-radius: 6px; }")

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)

        host = QWidget(panel)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        layout.addWidget(self._build_item(self.item, host))
        layout.addStretch(1)

        area = SmoothScrollArea(panel)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setFixedHeight(DIALOG_BODY_HEIGHT)
        area.setWidget(host)
        area.enableTransparentBackground()
        outer.addWidget(area)
        return panel

    def _build_item(self, item, parent):
        """一条公告：标题 + 日期 / 正文 / 来源信息"""
        box = QWidget(parent)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = StrongBodyLabel(str(item.get("title") or ""), box)
        title.setWordWrap(True)
        head.addWidget(title, 1)
        date = CaptionLabel(str(item.get("date") or ""), box)
        date.setStyleSheet("color: rgba(128,128,128,1);")
        head.addWidget(date, 0, Qt.AlignTop)
        layout.addLayout(head)

        body = BodyLabel(_clip(item.get("body")), box)
        body.setTextFormat(Qt.PlainText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(body)

        meta_text = self.t("notice_item_meta").format(
            author=item.get("author") or "", number=item.get("number") or "")
        meta = CaptionLabel(meta_text.strip(" ·"), box)
        meta.setStyleSheet("color: rgba(128,128,128,1);")
        layout.addWidget(meta)
        return box

    # ---------- 底部按钮 ----------

    def _reorder_buttons(self):
        """排成 [稍后] [全部已读] [查看公告]（主按钮最右）"""
        layout = self.buttonLayout
        for button in (self.yesButton, self.cancelButton):
            layout.removeWidget(button)
        layout.addWidget(self.cancelButton, 1, Qt.AlignVCenter)
        layout.addWidget(self.markButton, 1, Qt.AlignVCenter)
        layout.addWidget(self.yesButton, 1, Qt.AlignVCenter)

    def _on_mark_all_read(self):
        self.action = "read"
        self.accept()
