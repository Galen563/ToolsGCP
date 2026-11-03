"""公告界面（左侧栏「公告」，在「查看日志」和「Github」之间）。

内容来自 GitHub Issues 的「公告」标签（一条 Issue = 一条公告），拉取/过滤/已读在 core/announcements.py。
⚠️ 页面不要自己铺一层底色，背景交给主窗口。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
                             QWidget)
from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon as FIF,
                            IndeterminateProgressRing, PushButton,
                            SimpleCardWidget, StrongBodyLabel, SubtitleLabel,
                            ToolButton)

from ..core.announcements import (AnnouncementFetchWorker, AnnouncementStore,
                                  log_announcements)
from ..core.language_manager import LanguageManager
from ..utils.smooth_scroll import install_smooth_scroll
from ..utils.url_open import open_url
from ..widgets.app_card import themed_icon

# 「未读」那个红色小圆点（与左侧栏红点同色）
UNREAD_RED = "#FA5151"

# 刷新按钮里进度环的直径（与设置页「检查更新」按钮一致）
REFRESH_RING_SIZE = 18

# 语言文件 / 内置兜底都没有时的英文文案
FALLBACK_TEXTS = {
    "notice_title": "Notice",
    "notice_empty": "No announcements yet",
    "notice_empty_hint": "New announcements will show up here.",
    "notice_loading": "Loading announcements…",
    "notice_load_failed": "Could not load announcements. Please try again later.",
    "notice_mark_all_read": "Mark all read",
    "notice_unread_count": "{n} unread",
    "notice_all_read_done": "All announcements marked as read",
    "notice_refresh": "Refresh",
    "notice_open_in_github": "View on GitHub",
    "notice_item_meta": "{author} · #{number}",
    "notice_dialog_title": "New announcement",
    "notice_dialog_hint": ("After you mark all as read, the unread number in the "
                           "sidebar is cleared."),
    "notice_dialog_more": "{n} more unread announcement(s)",
    "notice_btn_later": "Later",
    "notice_btn_view": "View",
}


def _text_of(lang, key, default=""):
    """查语言文件；查不到退内置英文兜底（最后一个参数才是 key 本身）"""
    if lang is not None:
        try:
            text = lang.get_text("notice", key)
            if text and text != key:
                return str(text)
        except Exception:
            pass
    return FALLBACK_TEXTS.get(key, default or key)


class AnnouncementCard(SimpleCardWidget):
    """一条公告：标题 + 日期 + 正文 + 来源"""

    def __init__(self, item: dict, unread: bool = False, lang=None, parent=None):
        super().__init__(parent)
        self.lang = lang
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)

        # 未读的卡片在标题前点一个红点
        if unread:
            dot = QLabel(self)
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(
                f"background: {UNREAD_RED}; border-radius: 4px;")
            head.addWidget(dot, 0, Qt.AlignVCenter)

        title = StrongBodyLabel(str(item.get("title") or ""), self)
        title.setWordWrap(True)
        title.setTextFormat(Qt.PlainText)
        head.addWidget(title, 1)

        head.addWidget(CaptionLabel(str(item.get("date") or ""), self),
                       0, Qt.AlignTop)
        layout.addLayout(head)

        body = BodyLabel(str(item.get("body") or ""), self)
        # ⚠️ 必须锁死纯文本：正文里可能带 <b> 这类片段，否则 QLabel 会按富文本渲染，排版变样
        body.setTextFormat(Qt.PlainText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(body)

        # ---- 底部：来源 + 在 GitHub 查看 ----
        footer = QHBoxLayout()
        footer.setSpacing(8)
        meta = _text_of(lang, "notice_item_meta").format(
            author=item.get("author") or "", number=item.get("number") or "")
        meta_label = CaptionLabel(meta.strip(" ·"), self)
        meta_label.setStyleSheet("color: rgba(128,128,128,1);")
        footer.addWidget(meta_label)
        footer.addStretch(1)

        url = str(item.get("url") or "")
        if url:
            link = PushButton(_text_of(lang, "notice_open_in_github"), self)
            link.setIcon(FIF.LINK)
            link.setFixedHeight(28)
            link.clicked.connect(lambda _checked=False, u=url: open_url(u, "公告"))
            footer.addWidget(link)
        layout.addLayout(footer)


class NoticeInterface(QWidget):
    """公告页"""

    # 未读数变化（左侧栏红点靠它更新）
    unread_changed = pyqtSignal(int)
    # 这一次拉取成功（无论有没有未读）
    announcements_fetched = pyqtSignal(list)
    # 这一次拉取失败（错误码，见 core/announcements.py）
    fetch_failed = pyqtSignal(str)
    # 用户点了「全部已读」，参数是这次新标了几条
    marked_all_read = pyqtSignal(int)

    def __init__(self, language_manager: LanguageManager = None,
                 settings_manager=None, store: AnnouncementStore = None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("noticeInterface")
        self.lang = language_manager
        self.settings_manager = settings_manager
        self.store = store if store is not None else AnnouncementStore()
        self._worker = None
        self._fetch_started = False
        self._last_error = ""
        # 刷新按钮里那个进度环（见 _start_refresh_ring）
        self._refresh_ring = None
        self._refresh_icon = None
        self._cards = []
        self.setup_ui()

    # ---------- 文案 ----------

    def get_text(self, key: str, default: str = "") -> str:
        return _text_of(self.lang, key, default)

    # ---------- 界面 ----------

    def setup_ui(self):
        if self.layout():
            while self.layout().count():
                item = self.layout().takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.layout().deleteLater()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("noticeScrollContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 24, 30, 30)
        layout.setSpacing(14)

        # ---- 标题行：图标 + 标题 + [未读条数] + [全部已读]（右上角）----
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        icon_label = QLabel(content)
        icon_label.setPixmap(themed_icon(FIF.MEGAPHONE, 20).pixmap(20, 20))
        title_row.addWidget(icon_label)
        title_row.addWidget(SubtitleLabel(self.get_text("notice_title"), content))

        self.unread_label = CaptionLabel("", content)
        self.unread_label.setStyleSheet(
            f"color: #FFFFFF; background: {UNREAD_RED}; border-radius: 8px;"
            "padding: 1px 8px;")
        self.unread_label.setAlignment(Qt.AlignCenter)
        self.unread_label.setFixedHeight(18)
        self.unread_label.hide()
        title_row.addWidget(self.unread_label, 0, Qt.AlignVCenter)

        title_row.addStretch(1)

        # ⚠️ 「全部已读」固定在右上角（放在标题行里靠右），不是页面底部
        self.mark_all_btn = PushButton(self.get_text("notice_mark_all_read"), content)
        self.mark_all_btn.setIcon(FIF.ACCEPT)
        self.mark_all_btn.setFixedHeight(30)
        self.mark_all_btn.clicked.connect(self.mark_all_read)
        title_row.addWidget(self.mark_all_btn, 0, Qt.AlignVCenter)

        self.refresh_btn = ToolButton(FIF.SYNC, content)
        self.refresh_btn.setFixedSize(30, 30)
        self.refresh_btn.setToolTip(self.get_text("notice_refresh"))
        self.refresh_btn.clicked.connect(lambda: self.start_fetch(force=True))
        title_row.addWidget(self.refresh_btn, 0, Qt.AlignVCenter)
        layout.addLayout(title_row)

        # ---- 空状态（没有公告 / 正在拉 / 拉取失败时显示）----
        self.empty_box = QWidget(content)
        empty_layout = QVBoxLayout(self.empty_box)
        empty_layout.setContentsMargins(0, 60, 0, 0)
        empty_layout.setSpacing(6)
        empty_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        self.empty_title = StrongBodyLabel(self.get_text("notice_empty"), self.empty_box)
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_title)

        self.empty_hint = CaptionLabel(self.get_text("notice_empty_hint"), self.empty_box)
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setWordWrap(True)
        empty_layout.addWidget(self.empty_hint)
        layout.addWidget(self.empty_box)

        # ---- 卡片列表 ----
        self.list_host = QWidget(content)
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(12)
        layout.addWidget(self.list_host)

        layout.addStretch()
        scroll.setWidget(content)
        install_smooth_scroll(scroll)
        outer.addWidget(scroll)

        # ⚠️ 页面不要自己铺底色：QScrollArea 的视口默认会被 qfluentwidgets 刷成主题底色，
        #    所以页面本体、滚动区、视口一并置透明
        self.setStyleSheet("""
            NoticeInterface, QWidget#noticeScrollContent { background: transparent; }
            QScrollArea, QWidget#qt_scrollarea_viewport {
                background: transparent; border: none;
            }
        """)

        self.refresh()

    # ---------- 渲染 ----------

    def refresh(self):
        """重建公告列表（内容来自本地缓存，网络结果回来后再调一次）"""
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = []

        items = list(self.store.items)
        has_any = bool(items)
        self.empty_box.setVisible(not has_any)
        self.list_host.setVisible(has_any)

        for item in items:
            card = AnnouncementCard(item, not self.store.is_read(item.get("id")),
                                    self.lang, self.list_host)
            self.list_layout.addWidget(card)
            self._cards.append(card)

        self._apply_empty_state()
        self._apply_unread_state()
        self.unread_changed.emit(self.store.unread_count())

    def _apply_empty_state(self):
        """没有内容时，把"正在拉 / 拉失败 / 真的一条都没有"三种情况分开说"""
        if self.store.items:
            return
        if self._worker is not None:
            self.empty_title.setText(self.get_text("notice_loading"))
            self.empty_hint.setText("")
        elif self._last_error:
            self.empty_title.setText(self.get_text("notice_empty"))
            self.empty_hint.setText(self.get_text("notice_load_failed"))
        else:
            self.empty_title.setText(self.get_text("notice_empty"))
            self.empty_hint.setText(self.get_text("notice_empty_hint"))

    def _apply_unread_state(self):
        """未读条数小标签 + 「全部已读」按钮的可用状态"""
        count = self.store.unread_count()
        if count > 0:
            self.unread_label.setText(
                self.get_text("notice_unread_count").format(n=count))
            self.unread_label.adjustSize()
            self.unread_label.show()
        else:
            self.unread_label.hide()
        self.mark_all_btn.setEnabled(count > 0)

    # ---------- 数据 ----------

    def unread_count(self) -> int:
        """还没读过的公告条数（左侧栏红点显示的就是它）"""
        return self.store.unread_count()

    def unread_items(self):
        return self.store.unread_items()

    def mark_all_read(self):
        """「全部已读」：把所有公告标成已读，并让左侧栏红点归零"""
        added = self.store.mark_all_read()
        self.refresh()
        if added:
            self.marked_all_read.emit(added)
        return added

    # ---------- 拉取 ----------

    def _search_source(self):
        """设置里的「搜索源」：决定官方直连失败后退到哪个镜像"""
        try:
            return str(self.settings_manager.settings.get("search_source") or "")
        except Exception:
            return ""

    def start_fetch(self, force=False):
        """起后台线程拉公告（网络不能跑在 UI 线程上，否则界面直接假死）。

        force=False 一个会话只自动拉一次；force=True（刷新按钮）会转圈，想拉几次拉几次。
        """
        if self._worker is not None:
            # 已经在拉了：把圈转起来，等这次结果回来一起收掉（别再叠一个线程）
            if force:
                self._start_refresh_ring()
            return
        if self._fetch_started and not force:
            return
        self._fetch_started = True
        if force:
            self._start_refresh_ring()

        worker = AnnouncementFetchWorker(search_source=self._search_source(),
                                         parent=self)
        worker.fetched.connect(self._on_fetched)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        self._apply_empty_state()
        worker.start()

    def _finish_fetch(self):
        self._worker = None
        self._finish_refresh_ring()

    # ---------- 刷新按钮里的转圈 ----------
    # 做法同设置页「检查更新」按钮（见 cards_misc.py 的 _start_check_update_ring）

    def _start_refresh_ring(self):
        """刷新按钮里转圈（已经在转就不重复建）"""
        if getattr(self, "_refresh_ring", None) is not None:
            return
        ring = IndeterminateProgressRing(self.refresh_btn)
        size = REFRESH_RING_SIZE
        ring.setFixedSize(size, size)
        try:
            ring.setStrokeWidth(2.2)
        except Exception:
            pass
        ring.move(max(0, (self.refresh_btn.width() - size) // 2),
                  max(0, (self.refresh_btn.height() - size) // 2))
        ring.show()
        ring.raise_()
        self._refresh_ring = ring
        # ⚠️ 纯图标按钮：得先把图标收起来，否则图标和进度环会叠在一起
        self._refresh_icon = self.refresh_btn.icon()
        self.refresh_btn.setIcon(QIcon())
        self.refresh_btn.setEnabled(False)

    def _finish_refresh_ring(self):
        """收掉进度环、把图标和可点状态恢复"""
        ring = getattr(self, "_refresh_ring", None)
        self._refresh_ring = None
        if ring is not None:
            try:
                if hasattr(ring, "stop"):
                    ring.stop()
                ring.hide()
                ring.deleteLater()
            except RuntimeError:
                pass
        self.refresh_btn.setIcon(getattr(self, "_refresh_icon", None) or FIF.SYNC)
        self.refresh_btn.setEnabled(True)

    def _on_fetched(self, items):
        self._finish_fetch()
        self._last_error = ""
        self.store.update_items(items)
        self.refresh()
        log_announcements(len(items), self.store.unread_count())
        self.announcements_fetched.emit(list(items))

    def _on_failed(self, code):
        self._finish_fetch()
        self._last_error = str(code or "")
        # 拉失败也把缓存刷一遍：空状态要切成"取不到公告"的提示
        self.refresh()
        self.fetch_failed.emit(self._last_error)

    def shutdown(self, timeout_ms: int = 3000):
        """等后台拉取线程收工（关窗口时调）。

        ⚠️ QThread 还在跑就被析构 → Qt 直接 abort。
        """
        worker = self._worker
        if worker is None:
            return
        try:
            if worker.isRunning():
                worker.wait(timeout_ms)
        except Exception:
            pass
