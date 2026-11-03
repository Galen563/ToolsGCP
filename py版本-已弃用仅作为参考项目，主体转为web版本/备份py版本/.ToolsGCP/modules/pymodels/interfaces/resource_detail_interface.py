"""资源详情页（版面参考「应用商店」）：工具栏（返回 / 收藏）→ 头部（大图标 + 名称 + 标签 + 版本切换）
→ 应用介绍 → 详细信息（键值卡片：适用系统 / CPU 架构 / 类别 / 上架时间 / 官网 / GitHub …）。

几条硬约定：
1. 头部保持原样（只加不改），本次只在它下面新增「应用介绍」「详细信息」两个区块。
2. 字段不存在就整行不渲染，不显示「未知」「--」这类占位噪音（systems: [] 的条目会自动短一截）。
3. 不做「软件版本」「软件体积」：库里没有事实数据；要加就在 DETAIL_ROW_DEFS 里插一行。
4. 文案走 search 语言模块（search_language.json），头部原有四个按钮的文案保持不动。
⚠️ 颜色一律从 settings.theme.tokens() 取，不要写死十六进制色。
"""

import os
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap, QIcon, QColor, QMovie, QKeySequence
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QShortcut, QSizePolicy, QApplication,
)
from qfluentwidgets import (
    PushButton,
    TransparentToolButton,
    FluentIcon as FIF,
    StrongBodyLabel,
    CaptionLabel,
    BodyLabel,
    SegmentedWidget,
    SimpleCardWidget,
    ScrollArea,
    IconWidget,
    isDarkTheme,
    themeColor,
)

from ..utils.smooth_scroll import install_smooth_scroll
from ..widgets.app_card import TagLabel, tinted_icon, themed_icon, tooltip_style

# 设置页的设计 token（详情页跟设置页共用同一套色板与尺寸，避免两套视觉）
try:
    from .settings.theme import SIZES as _SIZES, tokens as _tokens
except Exception:  # pragma: no cover - 理论上不会发生
    _SIZES = {"card_radius": 10, "card_padding": 20, "card_gap": 16,
              "content_max_width": 880, "content_margin": 30}
    def _tokens(dark=False):
        return {"card": "#FFFFFF", "card_border": "#E6E9F0",
                "divider": "#EFF1F5", "text": "#1F2329",
                "text_secondary": "#6B7280", "icon": "#4B4F58",
                "accent": "#4F7BF7"}


# 详情页自己的尺寸（不塞进 SIZES：那是设置页专用的表）
DETAIL_OUTER_MARGIN = 32        # 上下 / 左侧留白
# 右侧留白同左侧（需求：收藏按钮与返回按钮的左右边距一致）——工具栏两侧对称；滚动条也因此离右边缘这么远
DETAIL_SCROLLBAR_MARGIN = DETAIL_OUTER_MARGIN
SEARCH_CONTENT_MARGIN = 24      # 滚动内容左右内边距（和搜索页 scroll_content 一致）
DETAIL_KEY_WIDTH = 96           # 详细信息里左侧键名列的宽度
DETAIL_ROW_GAP = 12             # 键值行之间的垂直间距
DETAIL_KEY_VALUE_GAP = 20       # 键列与值列之间的水平间距
DETAIL_BLOCK_GAP = 16           # 区块标题与它下面卡片之间的距离
DETAIL_SECTION_GAP = 26         # 两个区块之间的距离
DETAIL_TOP_BAR_HEIGHT = 56      # 顶部栏（返回 / 收藏）的高度

# 详细信息里要展示的「字段 -> 文案 key」，顺序就是界面上的顺序；每一项都是有值才渲染。
# ⚠️ 想加「软件版本」就在这里插一行 ("version", "row_version") 即可。
DETAIL_ROW_DEFS = (
    ("systems", "row_systems"),
    ("architectures", "row_architectures"),
    ("category", "row_category"),
    ("listed_at", "row_listed_at"),
)

# 详细信息里的「链接行」：字段 -> 文案 key（值是网址，渲染成可点链接）
DETAIL_LINK_DEFS = (
    ("url", "row_url"),
    ("github", "row_github"),
)

def _detail_text(key: str, default: str = "") -> str:
    """详情页里"模块级"文案的三语言查询（拿不到语言管理器就返回兜底）。

    ⚠️ 类里的文案走 self.get_text（会用 search 段），但 CopyLinkButton 这种独立小控件没有那个上下文。
    """
    try:
        from ..core.language_manager import get_current_manager
        manager = get_current_manager()
        if manager is not None:
            for module in ("search", "settings"):
                try:
                    text = manager.get_text(module, key)
                except Exception:
                    text = key
                if text and text != key:
                    return str(text)
    except Exception:
        pass
    return default


def _term_text(value) -> str:
    """资源库术语（类别 / 标签 / 适用系统 / CPU 架构）的显示译名。

    只改显示：值本身（筛选、收藏、存盘）仍然是规范中文，一个字节都不动。
    """
    try:
        from ..core.language_manager import translate_term
        return translate_term(str(value or ""))
    except Exception:
        return str(value or "")


# 顶层兜底文案（search_language.json 里没有对应 key 时用）
FALLBACK_TEXT = {
    "back_tip": "Back (Esc)",
    "favorited": "Favorited", "unfavorite_tip": "Click to remove from favorites",
    "favorite": "Favorite", "favorite_tip": "Add to favorites",
    "section_intro": "About",
    "section_detail": "Details",
    "variant_label": "Variant",
    "row_systems": "Platform",
    "row_architectures": "Architecture",
    "row_category": "Category",
    "row_listed_at": "Listed",
    "row_url": "Website",
    "row_github": "GitHub",
    # ⚠️ 下面这三条以前写死中文：详情页头部的「编码：TG-000001」和「作者 / 聊天」两个按钮切了语言也还是中文
    "row_author": "Author",
    "row_chat": "Chat",
    "detail_code_label": "Code: {code}",
    "no_intro": "No description has been provided for this resource yet.",
}


class CopyIconButton(TransparentToolButton):
    """复制按钮：点一下复制文本，图标换成 ✓ 并禁用 2 秒，然后恢复。

    ⚠️ 用 TransparentToolButton 而不是 QPushButton + setStyleSheet：给 qfluentwidgets 的按钮
    setStyleSheet 会让 Qt 样式引擎接管它、画成白底方块（app_card.py 里专门写过这个坑）。
    """

    COPIED_MS = 2000

    def __init__(self, parent, text: str):
        super().__init__(parent)
        self._text = str(text or "")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.COPIED_MS)
        self._timer.timeout.connect(self._restore)

        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(14, 14))
        self.setIcon(themed_icon(FIF.COPY, 14))
        # ⚠️ 这三处原来写死中文（"复制链接" / "已复制"），切到英文/繁体还是中文，统一走下面这个查表函数取
        self.setToolTip(_detail_text("detail_copy_link", "复制链接"))
        self.clicked.connect(self._copy)

    def _copy(self):
        try:
            QApplication.clipboard().setText(self._text)
        except Exception:
            return
        # 换 ✓ + 禁用（图标用主题色，深浅主题都看得清）
        self.setIcon(themed_icon(FIF.ACCEPT, 14))
        self.setToolTip(_detail_text("detail_copied", "已复制"))
        self.setEnabled(False)
        self._timer.start()

    def _restore(self):
        self.setIcon(themed_icon(FIF.COPY, 14))
        self.setToolTip(_detail_text("detail_copy_link", "复制链接"))
        self.setEnabled(True)

    def refresh_icon(self, force: bool = False):
        """主题切换后重取图标（没在"已复制"那 2 秒里才换回 copy）"""
        if self.isEnabled():
            self.setIcon(themed_icon(FIF.COPY, 14))
        else:
            self.setIcon(themed_icon(FIF.ACCEPT, 14))


class LinkButton(PushButton):
    """头部那种「图标 + 文字」的外链按钮（官网 / 作者 / 聊天 …），点击行为同详细信息里的链接文字：
    左键 = 浏览器打开并切到浏览器；Ctrl + 左键 = 浏览器也打开，但当前程序不切走。

    ⚠️ 必须在 mousePressEvent 里自己记 Ctrl 状态：clicked 信号不带修饰键信息，等信号发出来已经拿不到了。
    """

    def __init__(self, parent, text: str, icon=FIF.LINK):
        super().__init__(parent)
        self.setText(text)
        self.setIcon(icon)
        self.setIconSize(QSize(16, 16))
        self.setFixedHeight(30)
        self.setMinimumWidth(104)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(tooltip_style())
        self._url = ""
        self._ctrl_pressed = False
        # 用 clicked 信号，绝不再去猴补 mousePressEvent 的默认行为（那样点一下就会崩）
        self.clicked.connect(lambda _checked=False, b=self: _open_button_url(
            b, background=b._ctrl_pressed))

    def mousePressEvent(self, event):
        self._ctrl_pressed = bool(event.modifiers() & Qt.ControlModifier)
        super().mousePressEvent(event)


def _link_button(parent, text: str, icon=FIF.LINK) -> LinkButton:
    """外链按钮（图标 + 文字，和搜索页卡片上的链接按钮同一种风格）"""
    return LinkButton(parent, text, icon)


def _open_button_url(button, background=None):
    """打开按钮上记着的地址（同时记一条操作日志）。

    background=None → 交给我们统一的判断（按下时按住 或 此刻按着的 Ctrl）；
    宁可多静默一次，也不要违背用户"我明明按着 Ctrl"的意图。
    """
    url = str(getattr(button, "_url", "") or "").strip()
    if background:
        open_url(url, button.text(), background=True)
    else:
        open_url(url, button.text())


def _as_text_list(value) -> List[str]:
    """把 字符串 / 列表 / 多语言字典 的字段统一成"非空字符串列表"（空值返回空列表，上层据此决定整行不渲染）。

    ⚠️ 必须递归：早期版本对列表元素直接 str(item)，["工具", {"简体中文": "官方"}] 会被渲染成
    {'简体中文': '官方'} 这么一串原文。
    """
    if value is None:
        return []
    if isinstance(value, dict):
        # 多语言字典：按 简中 / 繁中 / 英文 的顺序取第一个非空值
        for key in ("简体中文", "繁體中文", "English"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return [text.strip()]
        out = []
        for item in value.values():
            out.extend(_as_text_list(item))
        return out
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            out.extend(_as_text_list(item))
        return out
    text = str(value).strip()
    return [text] if text else []


def _dedup(values: List[str]) -> List[str]:
    """去重但保留原顺序（多语言字典递归展开后可能出现重复值）"""
    seen = set()
    out = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _display_list(values: List[str]) -> str:
    """列表转展示文本：去重后用当前语言的顿号 / 逗号分隔。

    ⚠️ 分隔符也跟着语言走（简繁是「、」，英文是 ", "），从 common 段取。
    """
    separator = "、"
    try:
        from ..core.language_manager import translate_term, get_current_manager
        # list_separator 不是术语、translate_term 那张表里取不到，直接问一次语言管理器
        manager = get_current_manager()
        if manager is not None:
            text = manager.get_text("common", "list_separator")
            if text and text != "list_separator":
                separator = str(text)
    except Exception:
        pass
    return separator.join(_dedup(values))


class LinkLabel(QLabel):
    """详细信息里那种"网址行"的可点文字：左键 = 浏览器打开并切过去；
    Ctrl + 左键 = 浏览器也打开，但当前程序不切走（用 SW_SHOWNOACTIVATE，浏览器不抢焦点）。

    ⚠️ 不用 qfluentwidgets 的 HyperlinkLabel：它是 QPushButton 子类、不支持换行，
    库里的 GitHub 地址比键值区的值列还长，不换行只能被截断或把卡片撑歪。
    """

    def __init__(self, url: str, parent=None, log_name: str = "网址"):
        super().__init__(str(url), parent)
        self._url = str(url)
        self._log_name = log_name
        self.setWordWrap(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setToolTip(self._tip(self._url))

    def url(self) -> str:
        return self._url

    @staticmethod
    def _tip(url: str) -> str:
        """链接的悬浮提示（地址 + 操作说明，说明走三语言）"""
        return f"{url}{_detail_text('detail_link_tip', chr(10) + '左键：在浏览器打开')}"

    def setUrl(self, url: str):
        """换地址（切变体时用）"""
        self._url = str(url)
        self.setText(self._url)
        self.setToolTip(self._tip(self._url))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Ctrl 按住 = "后台打开"：浏览器照常打开，但窗口不抢焦点
            background = bool(event.modifiers() & Qt.ControlModifier)
            open_url(self._url, self._log_name, background=background)
            return
        super().mousePressEvent(event)


# 打开方式统一在 utils/url_open.py（全程序共用一份）；这里保留同名函数只是为了不动历史调用方。
from ..utils.url_open import open_url  # noqa: E402  (放在常量附近，便于阅读)


def _format_listed_at(value: str) -> str:
    """上架时间显示成 `2026-09-21 00:40`（秒对用户没意义，去掉）"""
    text = str(value or "").strip().replace("T", " ")
    if len(text) >= 16:
        return text[:16]
    return text


class ResourceDetailInterface(QWidget):
    """资源详情页。

    信号：back_requested() —— 点击返回按钮时发出。
    """

    back_requested = pyqtSignal()
    favorite_toggled = pyqtSignal(str)

    # 详细信息卡片高度"量到稳定"最多重试几拍（见 _sync_detail_card_height）
    _DETAIL_HEIGHT_MAX_ATTEMPTS = 6

    def __init__(self, parent=None, language_manager=None):
        super().__init__(parent)
        self.setObjectName("resourceDetailInterface")
        self.lang = language_manager
        self.current_data = {}
        self.current_variant = ""
        self._gif_movie = None
        self._favorite = False
        self._variant_list = []
        self._variant_keys = []
        self._variant_labels = []
        # 详情区每一条"键值行"（键 QLabel、值 QLabel/QWidget），换主题时要重新上色
        self._detail_rows = []
        self._detail_links = []
        self._detail_copy_buttons = []
        self._key_labels = []
        self._tag_chips = []
        # 内容控件的宽度由 _apply_content_width 卡在最大宽度内（见那里）
        self._content_width = 0
        # 详细信息卡片的高度是否需要重新量（填充/清空时置 True）
        self._detail_height_dirty = False
        self._setup_ui()
        self._apply_theme_style()

    # ---------- 文案 ----------
    def get_text(self, key: str) -> str:
        """取文案（详情页的文案放在 search 语言模块里）"""
        if self.lang is not None:
            text = self.lang.get_text("search", key)
            if text != key:
                return text
        return FALLBACK_TEXT.get(key, key)

    # ---------- UI ----------
    def _setup_ui(self):
        # 版面跟搜索页对齐（需求："拉伸窗口此页面 ui 遵循和搜索页一样的逻辑"）：
        # 工具栏铺满整宽、按钮贴左右两侧；滚动条贴窗口最右侧；
        # 滚动内容 = 24px 左右内边距 + 居中且最大 880px（和搜索页 scroll_content 同一套参数）
        self.outer = QVBoxLayout(self)
        # 右侧只留 8px：滚动条要尽量贴住窗口最右侧（需求："页面滚动条也恢复最右侧边缘"）
        self.outer.setContentsMargins(DETAIL_OUTER_MARGIN, DETAIL_OUTER_MARGIN,
                                      DETAIL_SCROLLBAR_MARGIN, 16)
        self.outer.setSpacing(16)

        # ---- 顶部栏（需求：卡片界面内顶部要有一个**专门的栏**，不然按钮飘着不好看）----
        # ⚠️ 以前是两个按钮直接塞进一个 QHBoxLayout 里加到页面顶部：返回贴最左、收藏贴最右，
        #    中间一大片空白，看着像"孤立漂浮"。现在改成一个真正的栏容器（圆角卡片），
        #    两个按钮都在栏里，位置关系明确。
        # ⚠️ 颜色一律走 _apply_theme_style 里的 card_qss（token 取色），这里不写死颜色。
        self.top_bar = SimpleCardWidget(self)
        self.top_bar.setBorderRadius(_SIZES["card_radius"])
        self.top_bar.setFixedHeight(DETAIL_TOP_BAR_HEIGHT)
        bar_box = QHBoxLayout(self.top_bar)
        bar_pad = _SIZES["card_padding"]
        bar_box.setContentsMargins(bar_pad, 0, bar_pad, 0)
        bar_box.setSpacing(12)

        self.back_btn = PushButton(self.get_text("detail_back"), self.top_bar, FIF.LEFT_ARROW)
        self.back_btn.setMinimumWidth(100)
        self.back_btn.setToolTip(self.get_text("back_tip"))
        self.back_btn.clicked.connect(self.back_requested.emit)
        bar_box.addWidget(self.back_btn, 0, Qt.AlignVCenter)
        bar_box.addStretch()

        self.favorite_btn = PushButton(self.get_text("detail_favorite"), self.top_bar, FIF.TAG)
        self.favorite_btn.setMinimumWidth(110)
        self.favorite_btn.clicked.connect(
            lambda: self.favorite_toggled.emit(self.current_code()))
        bar_box.addWidget(self.favorite_btn, 0, Qt.AlignVCenter)

        # ⚠️ 顶部栏宽度要跟内容列（880 居中）对齐：它不在滚动内容里，自己在 resize 时算一次
        self.outer.addWidget(self.top_bar, 0, Qt.AlignHCenter)

        # 内容区域（滚动条在它最右侧）
        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        install_smooth_scroll(self.scroll_area)

        # 居中容器：内容宽度由它限制（见 _apply_content_width）；滚动视口仍是整宽，滚动条紧贴右侧边缘
        self.content_host = QWidget(self.scroll_area)
        self.content_host.setStyleSheet("background: transparent;")
        host_outer = QVBoxLayout(self.content_host)
        host_outer.setContentsMargins(SEARCH_CONTENT_MARGIN, 0,
                                     SEARCH_CONTENT_MARGIN, 0)
        host_outer.setSpacing(0)

        self.content_widget = QWidget(self.content_host)
        self.content_widget.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setAlignment(Qt.AlignTop)
        self.content_layout.setSpacing(DETAIL_SECTION_GAP)

        self._build_header()
        self._build_variant_bar()
        self._build_intro_section()
        self._build_detail_section()
        self.content_layout.addStretch()

        host_outer.addWidget(self.content_widget, 0, Qt.AlignHCenter)
        self.scroll_area.setWidget(self.content_host)
        self.outer.addWidget(self.scroll_area, 1)

        # Esc 快捷键返回
        # ⚠️ 必须存成属性：QShortcut 只挂局部变量的话，Python 一回收它快捷键就静默失效
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._esc_shortcut.activated.connect(self.back_requested.emit)

    def _build_header(self):
        """头部：大图标 + 名称 + 标签 + 补充链接按钮"""
        header_layout = QHBoxLayout()
        header_layout.setSpacing(24)

        self.icon_widget = QLabel(self.content_widget)
        self.icon_widget.setFixedSize(96, 96)
        self.icon_widget.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.icon_widget, 0, Qt.AlignTop)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)
        right_layout.setAlignment(Qt.AlignTop)

        self.name_label = StrongBodyLabel("", self.content_widget)
        name_font = self.name_label.font()
        name_font.setPointSize(14)
        self.name_label.setFont(name_font)
        right_layout.addWidget(self.name_label)

        # 资源编码（部署清单里用这个编码指代该程序）
        self.code_label = CaptionLabel("", self.content_widget)
        right_layout.addWidget(self.code_label)

        # 简介在上、标签在下（需求："交换简介和标签的位置"）
        self.desc_label = CaptionLabel("", self.content_widget)
        self.desc_label.setWordWrap(True)
        right_layout.addWidget(self.desc_label)

        # 标签行：和搜索页卡片上的标签同一种胶囊样式（「官方」自动金色）
        self.tag_row = QHBoxLayout()
        self.tag_row.setContentsMargins(0, 0, 0, 0)
        self.tag_row.setSpacing(6)
        self.tag_row.addStretch()
        right_layout.addLayout(self.tag_row)

        right_layout.addSpacing(6)
        # 链接区：只剩「作者」「聊天」这类补充入口
        # （官网 / GitHub 按需求去掉了：地址在「详细信息」里以链接形式出现，头部不再重复摆按钮）
        self.link_buttons = {}
        link_row = QHBoxLayout()
        link_row.setSpacing(8)
        link_row.setContentsMargins(0, 0, 0, 0)
        for key, label_key, icon in (("author_url", "row_author", FIF.LINK),
                                     ("chat_url", "row_chat", FIF.LINK)):
            button = _link_button(self.content_widget, self.get_text(label_key), icon)
            button.hide()
            self.link_buttons[key] = button
            link_row.addWidget(button)
        link_row.addStretch()
        right_layout.addLayout(link_row)

        header_layout.addLayout(right_layout, 1)
        self._header_layout = header_layout
        self.content_layout.addLayout(header_layout)

    def _build_variant_bar(self):
        """变体切换（国际版 / 国内版 …）"""
        self.variant_bar = QWidget(self.content_widget)
        variant_layout = QHBoxLayout(self.variant_bar)
        variant_layout.setContentsMargins(0, 0, 0, 0)
        variant_layout.setSpacing(10)

        self.variant_label = CaptionLabel(
            self.get_text("variant_label"), self.variant_bar)
        variant_layout.addWidget(self.variant_label)

        self.variant_segment = SegmentedWidget(self.variant_bar)
        self.variant_segment.setFixedWidth(240)
        variant_layout.addWidget(self.variant_segment)
        variant_layout.addStretch()

        self.content_layout.addWidget(self.variant_bar)
        self.variant_bar.hide()

    # ---------- 区块 1：应用介绍 ----------
    def _build_intro_section(self):
        self.intro_section = QWidget(self.content_widget)
        box = QVBoxLayout(self.intro_section)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(DETAIL_BLOCK_GAP)

        self.intro_title = QLabel(self.get_text("section_intro"), self.intro_section)
        self.intro_title.setProperty("role", "detailSectionTitle")
        box.addWidget(self.intro_title)

        self.intro_card = SimpleCardWidget(self.intro_section)
        self.intro_card.setBorderRadius(_SIZES["card_radius"])
        card_box = QVBoxLayout(self.intro_card)
        pad = _SIZES["card_padding"]
        card_box.setContentsMargins(pad, pad - 6, pad, pad - 6)
        card_box.setSpacing(10)

        self.intro_label = BodyLabel("", self.intro_card)
        self.intro_label.setWordWrap(True)
        self.intro_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        card_box.addWidget(self.intro_label)

        # 补充说明（制作器里的 supplement）：有才显示，接在介绍下面
        self.supplement_label = CaptionLabel("", self.intro_card)
        self.supplement_label.setWordWrap(True)
        self.supplement_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.supplement_label.hide()
        card_box.addWidget(self.supplement_label)

        box.addWidget(self.intro_card)
        self.content_layout.addWidget(self.intro_section)

    # ---------- 区块 2：详细信息 ----------
    def _build_detail_section(self):
        self.detail_section = QWidget(self.content_widget)
        box = QVBoxLayout(self.detail_section)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(DETAIL_BLOCK_GAP)

        self.detail_title = QLabel(self.get_text("section_detail"), self.detail_section)
        self.detail_title.setProperty("role", "detailSectionTitle")
        box.addWidget(self.detail_title)

        self.detail_card = SimpleCardWidget(self.detail_section)
        self.detail_card.setBorderRadius(_SIZES["card_radius"])
        pad = _SIZES["card_padding"]
        self.detail_grid = QGridLayout(self.detail_card)
        self.detail_grid.setContentsMargins(pad, pad - 6, pad, pad - 6)
        self.detail_grid.setHorizontalSpacing(DETAIL_KEY_VALUE_GAP)
        self.detail_grid.setVerticalSpacing(DETAIL_ROW_GAP)
        self.detail_grid.setColumnMinimumWidth(0, DETAIL_KEY_WIDTH)
        self.detail_grid.setColumnStretch(0, 0)
        self.detail_grid.setColumnStretch(1, 1)
        self.detail_grid.setRowStretch(0, 0)

        box.addWidget(self.detail_card)
        self.content_layout.addWidget(self.detail_section)

    # ---------- 数据 ----------
    def current_code(self) -> str:
        return str(self.current_data.get("code") or self.current_data.get("id") or "")

    def is_favorite(self) -> bool:
        return self._favorite

    def set_favorite(self, value: bool):
        """更新收藏按钮的状态（不发送信号）"""
        self._favorite = bool(value)
        if self._favorite:
            self.favorite_btn.setText(self.get_text("favorited"))
            self.favorite_btn.setIcon(tinted_icon(FIF.TAG, QColor(themeColor()), 16))
            self.favorite_btn.setToolTip(self.get_text("unfavorite_tip"))
        else:
            self.favorite_btn.setText(self.get_text("favorite"))
            self.favorite_btn.setIcon(FIF.TAG)
            self.favorite_btn.setToolTip(self.get_text("favorite_tip"))

    def set_resource(self, data: dict):
        """设置当前展示的资源数据"""
        self.current_data = data or {}

        name = str(self.current_data.get("name", ""))
        self.name_label.setText(name)
        self.name_label.setVisible(bool(name))

        code = str(self.current_data.get("code", "") or "")
        self.code_label.setText(self.get_text("detail_code_label").format(code=code)
                                if code else "")
        self.code_label.setVisible(bool(code))

        # 头部原有的一句话简介（「应用介绍」区块是另外新增的，两者互不影响）
        desc_raw = str(self.current_data.get("description", "") or "")
        self.desc_label.setText(desc_raw)
        self.desc_label.setVisible(bool(desc_raw))

        # 标签（详情页头部也显示标签胶囊）
        # ⚠️ 一个 tags 都没填的条目（库里就有 11 条）以前这一行是空的（用户报的"标签加载不进来"）；
        #    退回显示「类别」，和搜索页卡片、筛选面板用的是同一个口径。
        self._set_tags(self.current_data.get("tags")
                       or self.current_data.get("category"))

        self._set_icon(self.current_data.get("icon"))
        self._fill_intro()
        self._fill_details()
        self._setup_variants()
        # 详情页第一次显示时（构造时视口宽度还是 0）内容宽度没算过，这里补算一次
        if self._content_width <= 0:
            self._apply_content_width()

    # ---------- 区块内容 ----------
    def _set_tags(self, tags):
        """重建标签行（「官方」自动走金色胶囊）。

        ⚠️ 和 _clear_detail_grid 同理：摘出布局后还要 setParent(None)，否则旧标签会叠在左上角。
        """
        while self.tag_row.count():
            item = self.tag_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._tag_chips = []

        values = _as_text_list(tags)
        for text in values:
            # 标签按当前语言显示（存盘 / 筛选用规范中文值）；「官方」的金色按规范值判断，不能拿翻译后的文字去比
            chip = TagLabel(_term_text(text), self.content_widget,
                            official=(str(text) == "官方"))
            self.tag_row.addWidget(chip)
            self._tag_chips.append(chip)
        self.tag_row.addStretch()

    def _fill_intro(self):
        """应用介绍：`intro` 是正文，`description` 只是它缺席时的退路。

        字段分工：description = 简介（卡片 / 头部那行小字，≤100 字）；intro = 应用介绍正文（可写几段）；
        supplement = 正文放不下的补充。intro 留空时退回 description，老条目也不会交白卷。
        """
        intro = " ".join(_dedup(_as_text_list(self.current_data.get("intro"))))
        desc = " ".join(_dedup(_as_text_list(self.current_data.get("description"))))
        supplement = " ".join(
            _dedup(_as_text_list(self.current_data.get("supplement"))))

        body = intro or desc
        if body:
            self.intro_label.setText(body)
            self.intro_label.setProperty("mutedText", False)
        else:
            # 一条都没有时也不用留空卡片：给一句淡色说明，界面不至于"缺一块"
            self.intro_label.setText(self.get_text("no_intro"))
            self.intro_label.setProperty("mutedText", True)
        self.intro_label.show()

        # 补充说明只在和正文不是同一段时才另起一段（老数据里两者曾经是同一个字段）
        if supplement and supplement != body:
            self.supplement_label.setText(supplement)
            self.supplement_label.show()
        else:
            self.supplement_label.setText("")
            self.supplement_label.hide()

        for label in (self.intro_label, self.supplement_label):
            label.style().unpolish(label)
            label.style().polish(label)

    def _clear_detail_grid(self):
        """清空详细信息卡片里的所有行。

        ⚠️ takeAt() 只是把控件从布局里摘掉，它仍然是卡片的子控件，会在 deleteLater 真正执行前
        原地叠在卡片左上角画出来（表现就是第一行"好几层字叠在一起"）。
        所以必须 setParent(None) + deleteLater() 两步都做 —— 切换资源 / 切换变体都会走这里。
        """
        while self.detail_grid.count():
            item = self.detail_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._detail_rows = []
        self._detail_links = []
        self._detail_copy_buttons = []
        self._key_labels = []
        # 内容变了：下一拍必须重新量一次高度
        self._detail_height_dirty = True

    def _make_key_label(self, text: str) -> QLabel:
        label = CaptionLabel(text, self.detail_card)
        label.setProperty("fieldLabel", True)
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        label.setWordWrap(True)
        self._key_labels.append(label)
        return label

    def _make_value_label(self, text: str) -> BodyLabel:
        label = BodyLabel(text, self.detail_card)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        return label

    def _fill_details(self):
        """详细信息：按 DETAIL_ROW_DEFS / DETAIL_LINK_DEFS 逐行铺开（每一项都是有值才加行）。

        整个卡片一行都排不出来时（极端情况：资源只有名称）直接隐藏整个区块，免得留个空卡片标题。
        """
        self._clear_detail_grid()
        data = self.current_data

        row = 0
        for field, text_key in DETAIL_ROW_DEFS:
            values = _as_text_list(data.get(field))
            if field == "listed_at":
                # 时间只保留到分钟，且不做「、」拼接（那份分隔符是给多值字段用的）
                values = [v for v in (_format_listed_at(v) for v in values) if v]
                text = values[0] if values else ""
            else:
                # ⚠️ 适用系统 / CPU 架构 / 类别这几项是资源库术语：按当前界面语言显示（存盘与筛选仍用规范中文值）
                values = [_term_text(v) for v in values]
                text = _display_list(values)
            if not text:
                continue
            self.detail_grid.addWidget(self._make_key_label(self.get_text(text_key)),
                                       row, 0)
            self.detail_grid.addWidget(self._make_value_label(text), row, 1)
            self._detail_rows.append(row)
            row += 1

        for field, text_key in DETAIL_LINK_DEFS:
            url = str(data.get(field) or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            self.detail_grid.addWidget(self._make_key_label(self.get_text(text_key)),
                                       row, 0)
            # 链接 + 右侧一个「复制」按钮（点击后换 accept 图标 2 秒，期间不可点）
            link_box = QWidget(self.detail_card)
            link_row = QHBoxLayout(link_box)
            link_row.setContentsMargins(0, 0, 0, 0)
            link_row.setSpacing(6)

            link = LinkLabel(url, link_box, log_name=self.get_text(text_key))
            link.setProperty("fieldValue", True)
            link.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            link.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            link_row.addWidget(link, 1)

            copy_btn = CopyIconButton(link_box, url)
            link_row.addWidget(copy_btn, 0, Qt.AlignTop)

            self.detail_grid.addWidget(link_box, row, 1)
            self._detail_links.append(link)
            self._detail_copy_buttons.append(copy_btn)
            self._detail_rows.append(row)
            row += 1

        has_rows = row > 0
        self.detail_section.setVisible(has_rows)
        if has_rows:
            # ⚠️ 高度必须推迟到下一拍再量（见 _sync_detail_card_height 的说明）：
            #    刚 addWidget 完 sizeHint() 还是过期值（实测拿到 28，而布局跑完是 283），照它设会把所有行压扁
            self._detail_height_dirty = True
            QTimer.singleShot(0, self._sync_detail_card_height)
        self._apply_theme_style()

    def _sync_detail_card_height(self):
        """把详细信息卡片的高度按布局的自然高度钉死。

        ⚠️ QGridLayout 的每个单元格都是 widget，单元格本身也会被拉开：卡片一旦比内容高，
        多出来的高度会被摊到若干行上 —— 表现就是"某一行下面多出一片空白"（位置还随行数 / 字体漂移）。
        上一版试过"尾部加一个弹簧行吃掉多余高度"，那个更错：跨两列的弹簧自己就占掉一整行。

        正确做法：不要任何弹簧，直接按布局的自然高度固定卡片高度。三个注意点：
        量之前先把上次设的高度限制解开（否则量到的就是上次的值）；必须等布局真的跑过
        （QTimer.singleShot(0)）再量；量一次不够 —— 实测第一拍 12 个控件只报 28px、第二拍才变成
        283px，所以要重试到值不再变化（最多 _DETAIL_HEIGHT_MAX_ATTEMPTS 次）。
        """
        if not getattr(self, "_detail_height_dirty", False):
            return
        grid = self.detail_grid
        grid.invalidate()
        grid.activate()
        hint = grid.sizeHint().height()
        last = getattr(self, "_detail_last_hint", None)

        if hint <= 0 or hint == last:
            # sizeHint 还没稳定（或已到上限）：再等一拍重试，直到两次量出的值一样
            attempts = getattr(self, "_detail_height_attempts", 0) + 1
            self._detail_height_attempts = attempts
            if hint > 0 and hint != last and attempts <= self._DETAIL_HEIGHT_MAX_ATTEMPTS:
                self._detail_last_hint = hint
                QTimer.singleShot(0, self._sync_detail_card_height)
                return
            if hint == last and self.detail_card.height() == hint:
                # 值稳定、卡片高度也已经对上 —— 收敛，收工
                self._detail_height_dirty = False
                self._detail_height_attempts = 0
                return
            if attempts <= self._DETAIL_HEIGHT_MAX_ATTEMPTS:
                self._detail_last_hint = hint if hint > 0 else last
                QTimer.singleShot(0, self._sync_detail_card_height)
                return
            self._detail_height_dirty = False
            return

        # 量到了一个新值：记下来，并按它固定卡片高度
        self._detail_last_hint = hint
        self._detail_height_attempts = 0
        self.detail_card.setMinimumHeight(0)
        self.detail_card.setMaximumHeight(16777215)   # QWIDGETSIZE_MAX
        self.detail_card.setFixedHeight(hint)
        self.detail_card.updateGeometry()
        # 设完高度布局会再算一次，下一拍回来确认是否收敛
        QTimer.singleShot(0, self._sync_detail_card_height)

    # ---------- 版本切换 ----------
    def _setup_variants(self):
        variants = self.current_data.get("variants")
        variants = variants if isinstance(variants, list) else []
        variants = [v for v in variants if isinstance(v, dict) and v.get("key")]
        self._variant_list = variants

        if len(variants) > 1:
            self.variant_segment.clear()
            self._variant_keys = []
            self._variant_labels = []
            for v in variants:
                key = str(v["key"])
                label = str(v.get("label") or key)
                self._variant_keys.append(key)
                self._variant_labels.append(label)
                self.variant_segment.addItem(
                    key, label, lambda _=False, k=key: self._apply_variant(k))
            default_key = str(self.current_data.get("default_variant")
                              or variants[0]["key"])
            if default_key not in self._variant_keys:
                default_key = self._variant_keys[0]
            self.variant_segment.setCurrentItem(default_key)
            # 变体只影响链接；详细信息里的官网 / GitHub 行要跟着刷新
            self._apply_variant(default_key)
            self.variant_bar.show()
        else:
            self._variant_keys = []
            self._variant_labels = []
            self.variant_segment.clear()
            self.variant_bar.hide()
            self._apply_variant(None)

    def _apply_variant(self, key):
        """切换版本：刷新头部链接按钮 + 详细信息里的官网 / GitHub 行"""
        self.current_variant = key or ""

        data = self.current_data
        variant = {}
        if key:
            for v in getattr(self, "_variant_list", []):
                if str(v.get("key")) == str(key):
                    variant = v
                    break

        for field, button in self.link_buttons.items():
            url = str(variant.get(field) or data.get(field) or "").strip()
            if url.startswith(("http://", "https://")):
                button._url = url
                button.setToolTip(f"{button.text()}\n{url}")
                button.show()
            else:
                button._url = ""
                button.hide()

        # 详细信息里的链接行跟着变体走：直接重铺一遍那块（字段少，比记住上一轮渲染顺序逐个对位稳得多）
        self._fill_details()

    # ---------- 主题 ----------
    def _apply_theme_style(self, force: bool = False):
        """按当前主题 / 组件配色重算样式。

        ⚠️ 只写类名 + 属性选择器，不要给单个控件内联颜色：一页十几行键值对，每行一份私有
        样式表的话，切主题 / 重排都要逐控件跑一遍 CSS 匹配（设置页当初就是因为这个发滞）。
        ⚠️ 同一主题下直接跳过：setStyleSheet 会让 Qt 把整棵子树重新 polish（本页最贵的操作），
        而 search_interface.refresh_theme() 会把详情页也顺手调一次，哪怕这一页根本不可见。
        force=True（换「组件配色」时）才强制重刷。
        """
        dark = bool(isDarkTheme())
        c = _tokens(dark)
        accent = c["accent"]
        signature = (dark, accent)
        if not force and getattr(self, "_theme_signature", None) == signature:
            return
        self._theme_signature = signature

        card_qss = (
            f"SimpleCardWidget {{"
            f" background-color: {c['card']};"
            f" border: 1px solid {c['card_border']};"
            f" border-radius: {_SIZES['card_radius']}px;"
            f"}}")
        # 卡片底色：SimpleCardWidget 默认几乎透明（深色下只有 13/255 的白），大块内容上看不出边界，按 token 给实色
        self.intro_card.setStyleSheet(card_qss)
        self.detail_card.setStyleSheet(card_qss)
        # 顶部栏也是同一张卡片样式（需求：顶部要有个专门的栏）
        self.top_bar.setStyleSheet(card_qss)

        self.setStyleSheet(f"""
            /* 页面底色：详情页是一整页内容（不是浮在主窗口上的一层），
               所以自己铺底色；卡片用比底色亮一档的 token，边界才看得出来。 */
            ResourceDetailInterface {{
                background-color: {c['page']};
            }}
            QWidget#resourceDetailInterface {{
                background-color: {c['page']};
            }}
            QLabel[role="detailSectionTitle"] {{
                color: {c['text']};
                font-size: 17px;
                font-weight: 600;
                background: transparent;
            }}
            QLabel[fieldLabel="true"] {{
                color: {c['text_secondary']};
                font-size: 12px;
                background: transparent;
            }}
            QLabel[mutedText="true"] {{
                color: {c['text_secondary']};
            }}
            QLabel {{
                background: transparent;
            }}
            LinkLabel[fieldValue="true"] {{
                color: {accent};
                font-size: 13px;
                background: transparent;
            }}
        """)

        # 动态属性（fieldLabel / mutedText / fieldValue）改了以后必须重新 polish，样式表里的属性选择器才会生效
        for label in self._key_labels:
            label.style().unpolish(label)
            label.style().polish(label)
        for link in self._detail_links:
            link.style().unpolish(link)
            link.style().polish(link)
        # 复制按钮的图标是 pixmap、按主题取的，切主题要重取一次
        for button in self._detail_copy_buttons:
            try:
                button.refresh_icon(force=force)
            except Exception:
                pass

    def refresh_theme(self, force: bool = False):
        """外部（切主题 / 换组件配色）调用的重刷入口"""
        self._apply_theme_style(force=force)

    # ---------- 宽度 ----------
    def _apply_content_width(self):
        """把内容本体限制到最大宽度并水平居中（和搜索页/设置页同一套逻辑）。

        滚动视口保持整宽（这样滚动条贴着窗口最右侧），只把 content_widget 的宽度卡在
        SIZES['content_max_width']（880）并居中；窄窗口下退化成"视口宽度 − 左右 24px 内边距"。
        """
        max_width = int(_SIZES.get("content_max_width", 880))
        available = max(0, self.scroll_area.viewport().width()
                        - 2 * SEARCH_CONTENT_MARGIN)
        width = max(1, min(max_width, available))
        if width == self._content_width:
            return
        self._content_width = width
        self.content_widget.setFixedWidth(width)
        # 顶部栏跟内容列同宽（它在滚动区外，不会自己跟随内容宽度）
        try:
            self.top_bar.setFixedWidth(width)
        except (RuntimeError, AttributeError):
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 边距调整会触发一次重排，推迟到事件循环的下一拍，避免在 resize 里改布局
        QTimer.singleShot(0, self._apply_content_width)

    # ---------- 图标 ----------
    def _set_icon(self, icon_path):
        if self._gif_movie:
            self._gif_movie.stop()
            self._gif_movie = None
            self.icon_widget.setMovie(None)

        if isinstance(icon_path, str) and icon_path.lower().endswith(".gif"):
            gif_path = icon_path
            if not os.path.isabs(gif_path):
                gif_path = os.path.join(str(Path(__file__).resolve().parents[4]), gif_path)
            self._gif_movie = QMovie(gif_path)
            self._gif_movie.setScaledSize(QSize(96, 96))
            self.icon_widget.setMovie(self._gif_movie)
            self._gif_movie.start()
            return

        icon = self._resolve_icon(icon_path, 96)
        if isinstance(icon, QIcon):
            self.icon_widget.setPixmap(icon.pixmap(QSize(96, 96)))
        elif hasattr(icon, "pixmap"):
            self.icon_widget.setPixmap(icon.pixmap(QSize(96, 96)))
        else:
            # FIF 枚举: 通过临时 IconWidget 渲染
            tmp = IconWidget(icon)
            pm = QPixmap(96, 96)
            pm.fill(Qt.transparent)
            tmp.resize(96, 96)
            tmp.render(pm)
            self.icon_widget.setPixmap(pm)

    def _resolve_icon(self, icon, size: int):
        """解析图标: 本地图片路径 > FIF 枚举名 > 关键字映射 > 默认 APP"""
        if icon is None:
            return FIF.APPLICATION
        if hasattr(icon, "icon"):
            return icon
        if isinstance(icon, str):
            if any(icon.lower().endswith(ext) for ext in
                   (".png", ".jpg", ".jpeg", ".svg", ".webp", ".bmp", ".gif")):
                candidate_paths = [icon]
                if not os.path.isabs(icon):
                    project_root = Path(__file__).resolve().parents[4]
                    candidate_paths.append(os.path.join(str(project_root), icon))
                for path in candidate_paths:
                    pixmap = QPixmap(path)
                    if not pixmap.isNull():
                        return QIcon(pixmap.scaled(
                            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return FIF.APPLICATION
            if hasattr(FIF, icon):
                return getattr(FIF, icon)
            mapping = {
                "github": FIF.GITHUB, "web": FIF.GAME, "tool": FIF.TOOLS,
                "app": FIF.APPLICATION, "code": FIF.CODE, "download": FIF.DOWNLOAD,
                "search": FIF.SEARCH, "setting": FIF.SETTING,
            }
            return mapping.get(icon.lower(), FIF.APPLICATION)
        return FIF.APPLICATION
