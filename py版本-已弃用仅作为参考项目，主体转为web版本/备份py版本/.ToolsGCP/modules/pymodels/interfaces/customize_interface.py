"""定制页（左侧栏「定制页」）：先选喜好，再照喜好推荐。

喜好设置和推荐两个视图装在同一个 QStackedWidget 里，页内都不再有自己的「定制页」小标题。
推荐网格复用 AppsIndexFramework（和搜索页同一套卡片 / 虚拟化 / 图标延迟加载），喜好胶囊自绘。

⚠️ 喜好清单来自真资源库（category + tags，只留至少覆盖 2 条资源的，取前 20）。
⚠️ 「恢复默认」必须把 customize_interests 清空并复位 customize_onboarded，否则下次仍判定为"已引导过"。
⚠️ settings_manager 可能是 None（老调用点），这时退化成内存字典，绝不能因此抛异常。
"""

from datetime import datetime

from PyQt5.QtCore import (QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer,
                          pyqtSignal)
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                             QScrollArea, QSizePolicy, QStackedWidget,
                             QVBoxLayout, QWidget)
from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon as FIF, InfoBar,
                            InfoBarPosition, MessageBox, PrimaryPushButton,
                            PushButton, SimpleCardWidget, StrongBodyLabel,
                            SubtitleLabel, isDarkTheme, themeColor)

from ..core.cloud_resource_source import resolve_resource_file
from ..core.language_manager import LanguageManager
from ..core.resource_loader import ResourceLoader
from ..core.settings_manager import SettingsManager
from ..utils.logger import log
from ..utils.smooth_scroll import install_smooth_scroll
from ..widgets import AppsIndexFramework
from ..widgets.chip_flow import ChipFlow
from ..widgets.filter_panel import chip_colors, reset_chip_color_cache
from .settings.theme import SIZES, tokens

# ---------- 设置的键 ----------
# ⚠️ 这两个键不在 constants.DEFAULT_SETTINGS 里；实测 update_setting() 对未知键照写不误，直接读写即可
SETTING_INTERESTS = "customize_interests"     # list[str]，用户勾的喜好名
SETTING_ONBOARDED = "customize_onboarded"     # bool，是否走完过"首次设置喜好"

# 一个喜好至少要覆盖几条资源才值得给用户选
MIN_RESOURCES_PER_INTEREST = 2
# 喜好清单最多给几个（按覆盖条数排序后截断，避免一屏几十个胶囊）
MAX_INTERESTS = 20
# 推荐列表最多显示几条（按得分排序后截断）
MAX_RECOMMENDATIONS = 24

# 打分权重：类别命中比标签命中"更准"，所以给得高
CATEGORY_WEIGHT = 3
TAG_WEIGHT = 1

# 类别字段里可能是 "工具,游戏" 这种多值，建清单和打分都要拆（⚠️ 不拆 "/"：「建筑/设计」是完整类别名）
_MULTI_SPLIT_CHARS = (",", "，", "、", ";", "；")

# 喜好卡片左右内边距（_build_onboard_card 和 _sync_content_width 都要用）
CARD_PADDING = 28

# 多语言字典的回退顺序（和 resource_loader.resolve_i18n 一致）
_I18N_KEYS = ("简体中文", "繁體中文", "English")


def _as_text_list(value) -> list:
    """把 字符串 / 列表 / 多语言字典 统一成"非空字符串列表"（空值一律返回空列表）。

    库里三种写法都出现过："category": "工具"、{"简体中文": "工具"}、["工具", {"简体中文": "官方"}]。
    ⚠️ 自己实现一份，不 import resource_detail_interface 的私有 _as_text_list（随时可能改名/改行为）。
    """
    if value is None:
        return []
    if isinstance(value, dict):
        for key in _I18N_KEYS:
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


def _split_multi(text: str) -> list:
    """把 "工具,游戏" 这种一格多值拆成多个（见 _MULTI_SPLIT_CHARS 的说明）"""
    parts = [str(text)]
    for char in _MULTI_SPLIT_CHARS:
        expanded = []
        for part in parts:
            expanded.extend(part.split(char))
        parts = expanded
    return [p.strip() for p in parts if p.strip()]


def _parse_listed_at(value):
    """把「上架时间」字符串解析成 datetime（认不出来返回 None）。

    制作器写的是 "2026-09-21 00:40:14"，也兼容带 T 的 ISO 写法。
    """
    text = str(value or "").strip().replace("T", " ")
    if not text:
        return None
    for fmt, width in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16),
                       ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:width], fmt)
        except ValueError:
            continue
    return None


def _code_of(data) -> str:
    """取一条资源的主键（编码优先，退回 id）——和框架里的叫法保持一致"""
    if not isinstance(data, dict):
        return ""
    return str(data.get("code") or data.get("id") or "")


def _interest_keys(item: dict):
    """一条资源覆盖到的 (类别列表, 标签列表)（都已拆多值 + 去重保序）"""
    cats, tags = [], []
    for value in _as_text_list((item or {}).get("category")):
        cats.extend(_split_multi(value))
    for value in _as_text_list((item or {}).get("tags")):
        tags.extend(_split_multi(value))
    return _dedup(cats), _dedup(tags)


def _dedup(values) -> list:
    """去重但保留原顺序"""
    seen, out = set(), []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


class _MemorySettings:
    """settings_manager 缺席时的内存兜底（老调用点 CustomizeInterface(language_manager)）。

    读要能拿到默认值、写要能记住（本页两个视图要能正常来回切），所以造一个最小的同形对象顶上。
    """

    def __init__(self):
        self.settings = {}

    def update_setting(self, key, value):
        self.settings[key] = value


class InterestChip(QLabel):
    """喜好胶囊（自绘）。

    四态：未选中 = 淡底 + 细描边（悬停时描边染强调色）；按下 = 底色深一档；
    选中 = 强调色实底 + 白字（深色主题黑字）+ ✓ + 加粗。

    ⚠️ 宽度一次算死（把 ✓ 和加粗的字宽都预留进去）：勾选时只重画、不重排，
    否则点一下整排胶囊会往右跳一格（筛选面板的 FilterChip 也是这么处理的）。
    """

    clicked = pyqtSignal()

    PADDING = 24        # 左右内边距
    CHECK_GAP = 6       # ✓ 和文字之间的间距
    CHECK = "✓"
    HOVER_ALPHA = 150   # 悬停描边的强调色透明度（0~255）
    HOVER_FILL = 28     # 悬停底色的强调色透明度（0~255）

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._checked = False
        self._hover = False
        self._pressed = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self.setAlignment(Qt.AlignCenter)
        # 选中态用粗体，字宽要按粗体算，否则加粗后 ✓ + 文字会超出定死的宽度被裁掉半截
        self._bold_font = QFont(self.font())
        self._bold_font.setBold(True)
        metrics = self.fontMetrics()
        bold_metrics = QFontMetrics(self._bold_font)
        width = max(metrics.horizontalAdvance(text),
                    bold_metrics.horizontalAdvance(f"{self.CHECK} {text}"))
        self.setFixedWidth(width + self.PADDING + self.CHECK_GAP)

    # ---------- 状态 ----------
    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self.update()

    # ---------- 交互 ----------
    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
        event.accept()      # 吃掉：别冒泡到滚动区/卡片

    def mouseReleaseEvent(self, event):
        was_pressed = self._pressed
        self._pressed = False
        self.update()
        if (was_pressed and event.button() == Qt.LeftButton
                and self.rect().contains(event.pos())):
            self.clicked.emit()
        event.accept()

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        colors = chip_colors(self._checked, self._hover)
        background = QColor(colors["bg"])
        border = QColor(colors["border"])
        if self._hover and not self._checked:
            # 悬停：描边和底色都带一点强调色（见类注释第 1 条）
            accent = QColor(themeColor())
            border = QColor(accent)
            border.setAlpha(self.HOVER_ALPHA)
            background = QColor(accent)
            background.setAlpha(self.HOVER_FILL)
        if self._pressed:
            # 选中时：再深一档；未选中时：直接拿描边色当底（一定看得出来）
            background = background.darker(112) if self._checked \
                else QColor(colors["border"])

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(border))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, rect.height() / 2.0, rect.height() / 2.0)

        painter.setPen(colors["text"])
        if self._checked:
            painter.setFont(self._bold_font)
            text = f"{self.CHECK} {self.text()}"
        else:
            text = self.text()
        painter.drawText(self.rect(), Qt.AlignCenter, text)
        painter.end()


class SelectionProgressBar(QWidget):
    """喜好设置的"还差几个"暗示条（自绘的一条细线）。

    自绘而不是用 qfluentwidgets 的 ProgressBar：这里只要一条 4px 的暗示条，自绘便宜得多，
    颜色也能直接跟强调色 token 对齐（和 InterestChip 不用 PillPushButton 同理）。
    ⚠️ 只做暗示、不做限制：选到 20 个也不拦着，条只是满了而已。
    """

    SUGGESTED = 5       # 建议至少选几个（条满 = 够用了）
    HEIGHT = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # ---------- 状态 ----------
    def count(self) -> int:
        return self._count

    def set_count(self, count: int):
        count = max(0, int(count or 0))
        if count != self._count:
            self._count = count
            self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        """⚠️ 自己画的东西一律包 try：画一半抛异常会让整页重绘卡在坏状态"""
        try:
            colors = tokens(isDarkTheme())
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            radius = self.height() / 2.0
            track = QRectF(self.rect())
            # 轨道色用卡片描边色（比 divider 明显一点，浅色下也看得见）
            painter.setBrush(QColor(colors["card_border"]))
            painter.drawRoundedRect(track, radius, radius)
            if self._count > 0:
                ratio = min(1.0, self._count / float(self.SUGGESTED))
                fill = QRectF(track)
                # 至少留一个圆点那么宽，选 1 个也看得见"进度动了"
                fill.setWidth(max(float(self.height()), track.width() * ratio))
                painter.setBrush(QColor(colors["accent"]))
                painter.drawRoundedRect(fill, radius, radius)
            painter.end()
        except Exception:
            pass


class CustomizeInterface(QWidget):
    """定制页（喜好设置 + 按喜好推荐）"""

    # 卡片被点击（完整摘要数据）——留给主窗口接到详情页，本页自己也会给个提示
    card_activated = pyqtSignal(dict)
    # 收藏状态变了（通知搜索页/收藏页刷新）
    favorites_changed = pyqtSignal()
    # 卡片上的「@给AI」被点击（名称, 编码）
    ai_mention_requested = pyqtSignal(str, str)

    def __init__(self, language_manager: LanguageManager = None,
                 settings_manager: SettingsManager = None,
                 favorites_manager=None, parent=None):
        super().__init__(parent)
        self.setObjectName("customizeInterface")
        self.lang = language_manager
        # ⚠️ 没有设置管理器时用内存兜底；后面所有读写都走 _read_setting / _write_setting
        self.settings_manager = settings_manager or _MemorySettings()
        self.favorites = favorites_manager

        # 资源库里的轻量摘要 + 由它算出来的喜好清单
        self.summaries: list = []
        self.interest_catalogue: list = []
        self.interest_chips: dict = {}
        self.selected_interests: set = set()
        # 分组种类 -> ChipFlow（建好喜好设置视图之后才有内容）
        self._flows: dict = {}
        # 当前推荐出来的数据（空状态判断 / 断言用）
        self.recommend_items: list = []

        # 界面是否建好了：没建好时所有公开方法直接返回，免得 setup_ui 半途出错后每个回调再炸一次
        self._ui_ready = False
        self._catalogue_loaded = False
        # 推荐数据是按哪一组喜好算的（喜好变了才重算）
        self._data_key = None
        self._fade_anim = None
        # 样式表"按深浅主题分别算好"，主题没变就不重复 setStyleSheet
        self._style_dark = None
        # 卡片视图模式（磁贴/网格）上次同步的值：变了要重造网格
        self._card_mode = None
        self._scrolled_timer = None

        try:
            self.setup_ui()
        except Exception as exc:
            log.err("定制", "setup_ui", f"定制页构建失败: {exc}")

    # ================= 界面 =================
    def setup_ui(self):
        """建两个视图（喜好设置 / 推荐）并决定先显示哪一个"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.stacked = QStackedWidget(self)
        outer.addWidget(self.stacked)

        self.onboard_page = QWidget(self.stacked)
        self.onboard_page.setObjectName("customizeOnboardPage")
        self.recommend_page = QWidget(self.stacked)
        self.recommend_page.setObjectName("customizeRecommendPage")
        self.stacked.addWidget(self.onboard_page)
        self.stacked.addWidget(self.recommend_page)

        # 先把资源库读进来，才建得出胶囊
        self._load_catalogue()

        self._build_onboard_page()
        self._build_recommend_page()
        self._sync_content_width()
        self._sync_card_view_mode()
        self._apply_styles(force=True)

        self._ui_ready = True
        # 构造时不加载卡片（这一页启动时用户未必会点进来，别占启动时间），首次加载交给 on_shown
        self._sync_view(load_data=False, animate=False)

    # ---------- 数据 ----------
    def _resource_file(self) -> str:
        """当前该读哪个资源索引文件（和搜索页同一套判断）"""
        try:
            return resolve_resource_file(self.settings_manager)
        except Exception:
            return ""

    def _load_catalogue(self):
        """读资源库 → 算出喜好清单（只保留"至少覆盖 2 条资源"的）。

        这一步很轻（读一次 JSON + 建两个 set），所以放在 setup_ui 里同步做。
        """
        self._catalogue_loaded = False
        self.summaries = []
        self.interest_catalogue = []
        try:
            language = getattr(self.lang, "current_language", "简体中文") \
                if self.lang else "简体中文"
            loader = ResourceLoader(self._resource_file() or None, language)
            if not loader.load_from_local():
                return
            self.summaries = loader.get_summaries()
            self.interest_catalogue = self._build_catalogue(self.summaries)
            self._catalogue_loaded = True
            log.op("定制", "catalogue",
                   interests=len(self.interest_catalogue),
                   resources=len(self.summaries))
        except Exception as exc:
            log.err("定制", "catalogue", f"喜好清单构建失败: {exc}")

    def _build_catalogue(self, summaries: list) -> list:
        """从摘要里统计喜好：类别 + 标签，按覆盖条数降序，截断到 MAX_INTERESTS"""
        covered: dict = {}      # 喜好名 -> 覆盖到的资源编码集合
        from_category: set = set()

        for item in summaries or []:
            code = _code_of(item)
            if not code:
                continue
            cats, tags = _interest_keys(item)
            for name in cats:
                covered.setdefault(name, set()).add(code)
                from_category.add(name)
            for name in tags:
                covered.setdefault(name, set()).add(code)

        rows = [{"name": name, "count": len(codes),
                 "kind": "category" if name in from_category else "tag"}
                for name, codes in covered.items()
                if len(codes) >= MIN_RESOURCES_PER_INTEREST]
        # 覆盖多的排前面；一样多就按名字（稳，不随字典顺序跳）
        rows.sort(key=lambda row: (-row["count"], row["name"]))
        return rows[:MAX_INTERESTS]

    # ---------- 喜好设置视图 ----------
    def _build_onboard_page(self):
        """喜好设置视图：一张卡片，水平 + 垂直都居中。

        外面套 QScrollArea：卡片比视口高时能滚；正常窗口里 widgetResizable=True 把内容控件撑到
        视口大小，上下两个等大的 stretch 于是把卡片顶到正中间（不用手算 y，改窗口大小也不会偏）。
        """
        page_layout = QVBoxLayout(self.onboard_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        self.onboard_scroll = QScrollArea(self.onboard_page)
        self.onboard_scroll.setWidgetResizable(True)
        self.onboard_scroll.setFrameShape(QFrame.NoFrame)
        self.onboard_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.onboard_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        content = QWidget()
        content.setObjectName("customizeScrollContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)
        content_layout.setSpacing(0)

        card = self._build_onboard_card(content)
        self.onboard_card = card
        # ⚠️ 宽度是在 resizeEvent 里算死的（见 _sync_content_width）：只靠 addStretch + addWidget(card, 1)
        #    的话三个拉伸因子一样大，卡片只分到 1/3 宽 —— 胶囊会被挤成窄窄一列堆在左边
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addStretch(1)
        wrap.addWidget(card, 0)
        wrap.addStretch(1)

        # 上下两个等大的 stretch = 垂直居中（左右见 wrap）
        content_layout.addStretch(1)
        content_layout.addLayout(wrap)
        content_layout.addStretch(1)

        self.onboard_scroll.setWidget(content)
        page_layout.addWidget(self.onboard_scroll, 1)

        install_smooth_scroll(self.onboard_scroll)

    def _build_onboard_card(self, parent) -> SimpleCardWidget:
        """喜好卡片：标题 → 副说明 → 进度条 → 分组胶囊 → 操作区。

        整块做成一张圆角卡（SimpleCardWidget）：四周有边界才像"一件独立的事"，居中之后也不显得空。
        标题/说明用 SubtitleLabel + BodyLabel 两级，分组标题用 CaptionLabel + 一条发丝线。
        """
        card = SimpleCardWidget(parent)
        card.setObjectName("customizeOnboardCard")
        # 圆角要和 _apply_styles 里 QSS 的圆角一致：库自己还会画一层默认 5px 圆角，两边不同会露出毛边
        try:
            card.setBorderRadius(SIZES["card_radius"])
        except Exception:
            pass

        layout = QVBoxLayout(card)
        layout.setContentsMargins(CARD_PADDING, 24, CARD_PADDING, 16)
        layout.setSpacing(0)

        # ---- 标题层级：主标题 + 副说明 ----
        self.onboard_title = SubtitleLabel(self.get_text("onboard_title"), card)
        layout.addWidget(self.onboard_title)

        layout.addSpacing(6)
        self.onboard_subtitle = BodyLabel(self.get_text("onboard_subtitle"), card)
        self.onboard_subtitle.setWordWrap(True)
        self.onboard_subtitle.setObjectName("customizeMuted")
        layout.addWidget(self.onboard_subtitle)

        # ---- 进度暗示条（数字在下面操作条里，这条只给"还差几个"的直觉）----
        layout.addSpacing(14)
        self.selection_progress = SelectionProgressBar(card)
        layout.addWidget(self.selection_progress)

        layout.addSpacing(20)

        # ---- 分组：小标题 + 一条发丝线，下面铺胶囊 ----
        self._flows = {}                # 分组种类 -> ChipFlow（kind: category / tag）
        self.interest_groups = []       # [(组标题, ChipFlow)]，留着给"重建清单"用
        for kind, key in (("category", "group_category"), ("tag", "group_tag")):
            names = [row for row in self.interest_catalogue if row["kind"] == kind]
            if not names:
                continue
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(10)
            group_title = CaptionLabel(self.get_text(key), card)
            group_title.setObjectName("customizeSectionTitle")
            head.addWidget(group_title)
            rule = QFrame(card)
            rule.setFixedHeight(1)
            rule.setObjectName("customizeSectionRule")
            head.addWidget(rule, 1)
            layout.addLayout(head)
            layout.addSpacing(10)
            flow = ChipFlow(card, spacing=8, row_spacing=8)
            layout.addWidget(flow)
            layout.addSpacing(18)
            self.interest_groups.append((group_title, flow))
            self._flows[kind] = flow

        self._fill_chips()

        # 资源库里一个可选的喜好都没有（空库 / 文件读不到）：给一句解释
        self.no_interest_label = BodyLabel(
            self.get_text("no_interests_in_library"), card)
        self.no_interest_label.setWordWrap(True)
        self.no_interest_label.setObjectName("customizeMuted")
        self.no_interest_label.setVisible(not self.interest_catalogue)
        layout.addWidget(self.no_interest_label)

        # ---- 操作区（和上面内容之间一条发丝线）----
        layout.addWidget(self._build_onboard_bar(card))
        return card

    def _build_onboard_bar(self, parent) -> QWidget:
        """卡片底部的操作区：左边「恢复默认」，右边「已选 N 个 + 全不选 + 开始/保存」。

        放在卡片里而不是做成整页宽的底栏：底栏拉通整页会把卡片切成上下两块，破坏"一整张卡"的观感。
        """
        bar = QWidget(parent)
        bar.setObjectName("customizeBar")
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.bar_divider = QFrame(bar)
        self.bar_divider.setFixedHeight(1)
        layout.addWidget(self.bar_divider)

        row_host = QWidget(bar)
        row = QHBoxLayout(row_host)
        row.setContentsMargins(0, 12, 0, 0)
        row.setSpacing(10)

        # 破坏性操作放最左边，离主按钮越远越好（避免误点）
        self.btn_reset = PushButton(self.get_text("btn_reset_interests"),
                                    row_host, FIF.DELETE)
        self.btn_reset.clicked.connect(self._on_reset_clicked)
        row.addWidget(self.btn_reset)

        row.addStretch(1)

        self.count_label = BodyLabel("", row_host)
        row.addWidget(self.count_label)

        self.btn_clear = PushButton(self.get_text("btn_clear"), row_host)
        self.btn_clear.clicked.connect(self._on_clear_clicked)
        row.addWidget(self.btn_clear)

        self.btn_primary = PrimaryPushButton(self.get_text("btn_start"), row_host)
        self.btn_primary.clicked.connect(self._on_primary_clicked)
        row.addWidget(self.btn_primary)

        layout.addWidget(row_host)
        self._update_selection_state()
        return bar

    def _fill_chips(self):
        """按清单把胶囊铺进各组的 ChipFlow（重算清单时会整个重建）"""
        self.interest_chips = {}
        flows = getattr(self, "_flows", {})
        for flow in flows.values():
            flow.clear()
        for kind, flow in flows.items():
            widgets = []
            for row in [r for r in self.interest_catalogue if r["kind"] == kind]:
                # ⚠️ 显示名按当前语言翻译，身份仍是 row["name"]（规范中文值）：要存进设置、还要和资源比对
                display = self._term(row["name"])
                chip = InterestChip(display, flow)
                # 覆盖条数放进 tooltip：鼠标一停就知道这个喜好底下有多少资源
                chip.setToolTip(f"{display} · {row['count']}")
                chip.clicked.connect(
                    lambda name=row["name"]: self._on_chip_clicked(name))
                widgets.append(chip)
                self.interest_chips[row["name"]] = chip
            flow.set_widgets(widgets)
        # 重建之后要把当前选中态补回去（编辑喜好时进来，之前选的要亮着）
        self._sync_chip_states()

    # ---------- 推荐视图 ----------
    def _build_recommend_page(self):
        page_layout = QVBoxLayout(self.recommend_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # 标题区不做居中的窄列：下面的卡片网格铺满整页宽度，标题用同样的 24px 边距才对齐
        # ⚠️ 这一块没有「定制页」小标题（需求要求页内那个小标题整个去掉）
        header = QWidget(self.recommend_page)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 22, 24, 10)
        header_layout.setSpacing(6)

        # 标题行：为你推荐 ……………………………………… [编辑喜好]
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        self.recommend_title = SubtitleLabel(
            self.get_text("recommend_title"), header)
        title_row.addWidget(self.recommend_title)
        title_row.addStretch(1)

        self.btn_edit = PushButton(self.get_text("btn_edit_interests"),
                                   header, FIF.EDIT)
        self.btn_edit.clicked.connect(self._on_edit_clicked)
        title_row.addWidget(self.btn_edit)
        header_layout.addLayout(title_row)

        # 依据行：根据你选的：…… ……………………………… 共 N 个推荐
        basis_row = QHBoxLayout()
        basis_row.setSpacing(12)
        self.basis_label = CaptionLabel("", header)
        self.basis_label.setObjectName("customizeMuted")
        basis_row.addWidget(self.basis_label)
        basis_row.addStretch(1)
        self.recommend_count_label = CaptionLabel("", header)
        self.recommend_count_label.setObjectName("customizeMuted")
        basis_row.addWidget(self.recommend_count_label)
        header_layout.addLayout(basis_row)

        self.recommend_header = header
        page_layout.addWidget(header)

        # 卡片网格（和搜索页同一个框架：滚动虚拟化 / 图标延迟加载都是现成的）
        self.scroll_area = QScrollArea(self.recommend_page)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        scroll_content = QWidget()
        scroll_content.setObjectName("customizeScrollContent")
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(24, 6, 24, 30)
        content_layout.setSpacing(0)

        self.apps_framework = AppsIndexFramework(scroll_content)
        self.apps_framework.set_empty_text(self.get_text("empty_no_match"))
        # 告诉框架"可视区域是谁"：它据此只给屏幕上那几张卡片加载图标
        self.apps_framework.set_viewport(self.scroll_area)
        self.apps_framework.card_clicked.connect(self._on_card_clicked)
        self.apps_framework.favorite_toggled.connect(self._on_favorite_toggled)
        self.apps_framework.ai_mention_requested.connect(
            self.ai_mention_requested.emit)
        content_layout.addWidget(self.apps_framework, 1)

        self.scroll_area.setWidget(scroll_content)
        page_layout.addWidget(self.scroll_area, 1)

        # 滚动：把位置同步给框架（虚拟化窗口靠它），停下来再补图标
        self._scrolled_timer = QTimer(self)
        self._scrolled_timer.setSingleShot(True)
        self._scrolled_timer.setInterval(60)
        self._scrolled_timer.timeout.connect(self._on_scroll_idle)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        install_smooth_scroll(self.scroll_area)

        # 空状态（没有喜好 / 喜好一个都没匹配上时顶掉网格）
        self.empty_panel = self._build_empty_panel()
        page_layout.addWidget(self.empty_panel, 1)
        self.empty_panel.setVisible(False)

    def _build_empty_panel(self) -> QWidget:
        """空状态：一句解释 + 一个回到喜好设置的按钮（居中）"""
        panel = QWidget(self.recommend_page)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)
        layout.addStretch(1)

        self.empty_title = StrongBodyLabel(self.get_text("empty_no_match"), panel)
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_title.setWordWrap(True)
        layout.addWidget(self.empty_title)

        self.empty_hint = CaptionLabel("", panel)
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setObjectName("customizeMuted")
        self.empty_hint.setWordWrap(True)
        layout.addWidget(self.empty_hint)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.btn_empty_action = PrimaryPushButton(
            self.get_text("empty_action"), panel, FIF.EDIT)
        self.btn_empty_action.clicked.connect(self._on_edit_clicked)
        button_row.addWidget(self.btn_empty_action)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addStretch(1)
        return panel

    # ================= 视图切换 =================
    def current_view(self) -> str:
        """当前是哪个视图（"onboard" / "recommend"）——给测试和外部判断用"""
        try:
            if self.stacked.currentWidget() is self.recommend_page:
                return "recommend"
        except Exception:
            pass
        return "onboard"

    def _has_interests(self) -> bool:
        return bool(self._stored_interests())

    def _stored_interests(self) -> list:
        """设置里存的喜好（只保留清单里还存在的那些：资源库换了也不会推荐出空结果）"""
        raw = self._read_setting(SETTING_INTERESTS, [])
        if not isinstance(raw, (list, tuple, set)):
            return []
        known = {row["name"] for row in self.interest_catalogue}
        out = []
        for name in raw:
            text = str(name or "").strip()
            if text and (not known or text in known) and text not in out:
                out.append(text)
        return out

    def _sync_view(self, load_data: bool = True, animate: bool = False):
        """按设置决定显示哪个视图：没选过喜好（或没走完首次设置）→ 喜好设置"""
        if not self._ui_ready:
            return
        onboarded = bool(self._read_setting(SETTING_ONBOARDED, False))
        interests = self._stored_interests()
        if interests and onboarded:
            self._show_recommend_view(load_data=load_data)
        else:
            self._show_onboard_view(animate=animate)

    def _show_onboard_view(self, animate: bool = False):
        """切到喜好设置（顺手把设置里的选中态补到胶囊上）"""
        self.selected_interests = set(self._stored_interests())
        self._sync_chip_states()
        self._update_selection_state()
        switched = self.current_view() != "onboard"
        try:
            self.stacked.setCurrentWidget(self.onboard_page)
        except Exception:
            return
        if animate and switched:
            self._fade_in(self.onboard_page)

    def _show_recommend_view(self, load_data: bool = True):
        try:
            self.stacked.setCurrentWidget(self.recommend_page)
        except Exception:
            return
        if load_data:
            self._refresh_recommendations(show_loading=True)

    # ================= 喜好设置交互 =================
    def _on_chip_clicked(self, name: str):
        self.toggle_interest(name)

    def toggle_interest(self, name: str) -> bool:
        """勾选 / 取消一个喜好（返回操作后它是不是选中态）"""
        try:
            name = str(name or "").strip()
            if not name:
                return False
            if name in self.selected_interests:
                self.selected_interests.discard(name)
            else:
                self.selected_interests.add(name)
            self._sync_chip_states()
            self._update_selection_state()
            return name in self.selected_interests
        except Exception as exc:
            log.err("定制", "toggle", f"勾选喜好失败: {exc}")
            return False

    def _sync_chip_states(self):
        """把 selected_interests 摊到胶囊上（不触发信号）"""
        for name, chip in getattr(self, "interest_chips", {}).items():
            try:
                chip.setChecked(name in self.selected_interests)
            except RuntimeError:
                continue

    def _update_selection_state(self):
        """刷新"已选 N 个"、进度暗示条和按钮可用状态。

        toggle_interest / _on_clear_clicked / save / reset 都会走这里，数量是活的。
        """
        if not self._ui_ready and not hasattr(self, "btn_primary"):
            return
        try:
            count = len(self.selected_interests)
            self.count_label.setText(
                self.get_text("selected_count").format(n=count))
            self.btn_primary.setEnabled(count > 0)
            self.btn_clear.setEnabled(count > 0)
            # 进度条跟数量走（它只做暗示，不拦人）
            progress = getattr(self, "selection_progress", None)
            if progress is not None:
                progress.set_count(count)
            # ⚠️ 「恢复默认」不在这里置灰：拦住误点的应该是确认框，置灰后点了没反应反而像坏了
            # 主按钮的文案：第一次进来是"开始"，之后是"保存"
            onboarded = bool(self._read_setting(SETTING_ONBOARDED, False))
            self.btn_primary.setText(
                self.get_text("btn_save" if onboarded else "btn_start"))
            # 数量为 0 时用次要文字色，选中之后变强调色（一眼看出"有东西了"）
            colors = tokens(isDarkTheme())
            self.count_label.setStyleSheet(
                f"color: {colors['accent'] if count else colors['text_secondary']};")
        except Exception as exc:
            log.err("定制", "selection_state", f"刷新选中状态失败: {exc}")

    def _on_clear_clicked(self):
        """全不选：清掉选择（**不落盘**，要按主按钮才算保存）"""
        try:
            self.selected_interests.clear()
            self._sync_chip_states()
            self._update_selection_state()
        except Exception as exc:
            log.err("定制", "clear", f"清空选中失败: {exc}")

    # ---------- 恢复默认（删除所有喜好）----------
    def _on_reset_clicked(self):
        """「恢复默认」按钮：先确认，再清（确认框自己失败就按"取消"处理）"""
        try:
            confirmed = bool(self._ask_reset_confirm())
        except Exception as exc:
            log.err("定制", "reset_confirm", f"确认框弹不出来（当作取消）: {exc}")
            return
        if confirmed:
            self.reset_interests()

    def _ask_reset_confirm(self) -> bool:
        """弹确认框（qfluentwidgets 的 MessageBox，和收藏页"删除收藏夹"同一套写法）。

        ⚠️ 单独抽成一个方法是有意的：脚本里替换成 lambda: True 就能直接走"确认之后"的分支。
        两个按钮的文字都必须自己设，否则中文界面里会蹦出库自带的英文 "OK / Cancel"。
        """
        box = MessageBox(self.get_text("btn_reset_interests"),
                         self.get_text("confirm_reset_interests"), self)
        box.yesButton.setText(self.get_text("btn_reset_interests"))
        box.cancelButton.setText(self.get_text("btn_cancel"))
        return bool(box.exec())

    def reset_interests(self, show_toast: bool = True) -> bool:
        """清空用户存的喜好，回到"还没选过"的默认状态。

        ⚠️ 两个键要一起清：customize_interests 清空 + customize_onboarded 复位，
        只清前者的话下次进来仍然判定为"已引导过"，会停在没有任何依据的推荐页上。
        """
        if not self._ui_ready:
            return False
        try:
            self.selected_interests.clear()
            self._sync_chip_states()
            self._write_setting(SETTING_INTERESTS, [])
            self._write_setting(SETTING_ONBOARDED, False)
            # 推荐结果是按旧喜好算出来的，一并作废（下次显示时 on_shown 会重算）
            self.recommend_items = []
            self._data_key = None
            # 留在喜好设置页：一个胶囊都不亮、主按钮重新变成不可点（见 _update_selection_state）
            self._show_onboard_view(animate=False)
            self._update_selection_state()
            if show_toast:
                self._toast(self.get_text("toast_interests_reset"), "success")
            log.op("定制", "reset_interests", cleared=SETTING_INTERESTS)
            return True
        except Exception as exc:
            log.err("定制", "reset", f"恢复默认喜好失败: {exc}")
            return False

    def _on_primary_clicked(self):
        self.save_interests()

    def save_interests(self, show_toast: bool = True) -> bool:
        """保存喜好并切到推荐视图（首次进入时这就是"开始"按钮）"""
        if not self._ui_ready:
            return False
        try:
            # 按清单顺序存（"根据你选的：…"那句读起来才顺，不随点击顺序跳）
            order = [row["name"] for row in self.interest_catalogue]
            chosen = [name for name in order if name in self.selected_interests]
            chosen += [name for name in self.selected_interests
                       if name not in chosen]
            if not chosen:
                self._toast(self.get_text("toast_need_interest"), "warning")
                return False

            self._write_setting(SETTING_INTERESTS, chosen)
            self._write_setting(SETTING_ONBOARDED, True)
            log.op("定制", "save_interests", count=len(chosen),
                   interests="、".join(chosen))
            if show_toast:
                self._toast(self.get_text("toast_saved"), "success")
            # 换视图 + 算推荐：set_data(show_loading=True) 先亮加载动画，下一拍再渲染卡片
            self._show_recommend_view(load_data=True)
            return True
        except Exception as exc:
            log.err("定制", "save", f"保存喜好失败: {exc}")
            return False

    # ================= 推荐 =================
    def _score_item(self, item: dict, interests: set) -> int:
        """打分：类别命中一条 +3，标签命中一条 +1（类别比标签准）"""
        cats, tags = _interest_keys(item)
        return (CATEGORY_WEIGHT * len(interests.intersection(cats))
                + TAG_WEIGHT * len(interests.intersection(tags)))

    def _rank_recommendations(self) -> list:
        """按喜好给资源打分排序（0 分丢掉、收藏过的排除）。

        排序：分数降序 → 上架时间降序 → 名称，最后截断到 MAX_RECOMMENDATIONS。
        没有随机分支，同一个喜好集合每次算出来的顺序完全一样。
        """
        interests = set(self._stored_interests())
        if not interests:
            return []
        favourites = set()
        if self.favorites is not None:
            try:
                favourites = {str(c) for c in self.favorites.all_codes()}
            except Exception:
                favourites = set()

        rows = []
        for item in self.summaries or []:
            if _code_of(item) in favourites:
                continue
            score = self._score_item(item, interests)
            if score <= 0:
                continue
            stamp = _parse_listed_at(item.get("listed_at"))
            try:
                listed = stamp.timestamp() if stamp else 0.0
            except Exception:
                listed = 0.0
            rows.append((score, listed, str(item.get("name") or ""), item))

        rows.sort(key=lambda row: (-row[0], -row[1], row[2]))
        return [row[3] for row in rows[:MAX_RECOMMENDATIONS]]

    def refresh_favorites(self):
        """别处改了收藏 → 推荐结果作废，下次显示时重算。

        ⚠️ 不能只重刷卡片上的图标：推荐是排除已收藏算出来的，收藏一变候选集就变了，
        光重画会留下"这张卡已经收藏了却还挂在推荐里"这种不一致。真正的重算交给 on_shown。
        """
        self.recommend_items = []
        self._data_key = None
        try:
            framework = getattr(self, "apps_framework", None)
            if framework is not None and self.favorites is not None:
                framework.set_favorites(self.favorites.all_codes())
        except Exception:
            pass

    def _refresh_recommendations(self, show_loading: bool = True):
        """算推荐并交给卡片框架渲染"""
        if not self._ui_ready:
            return
        try:
            picked = self._rank_recommendations()
            self.recommend_items = picked
            self._data_key = frozenset(self._stored_interests())

            self.apps_framework.set_favorites(
                self.favorites.all_codes() if self.favorites is not None else [])
            # sort_key="all" = 保持我们算好的顺序（分数降序），不要再排
            self.apps_framework.set_data(picked, sort_key="all",
                                         show_loading=show_loading)
            self._update_recommend_header()
            self._apply_recommend_result(picked)
            log.op("定制", "recommend", count=len(picked),
                   interests="、".join(sorted(self._data_key)))
        except Exception as exc:
            log.err("定制", "recommend", f"推荐计算失败: {exc}")

    def _update_recommend_header(self):
        """标题下的那行"根据你选的：…" + 共 N 个推荐"""
        names = self._stored_interests()
        sep = self.get_text("list_separator")
        shown = names[:5]
        # 喜好名（规范中文值）按当前语言显示，再拼成一句话
        text = sep.join(self._term(n) for n in shown)
        text += "…" if len(names) > len(shown) else ""
        try:
            self.basis_label.setText(
                self.get_text("recommend_basis").format(names=text))
            self.recommend_count_label.setText(
                self.get_text("recommend_count").format(n=len(self.recommend_items)))
        except Exception as exc:
            log.err("定制", "header", f"推荐标题刷新失败: {exc}")

    def _apply_recommend_result(self, picked: list):
        """有推荐就显示网格，没有就显示空状态（空状态也分"没选喜好"和"没匹配"）"""
        has_items = bool(picked)
        try:
            self.scroll_area.setVisible(has_items)
            self.empty_panel.setVisible(not has_items)
            if has_items:
                return
            if not self._stored_interests():
                # 一个喜好都没有（比如设置被清空过）：让用户先去挑
                self.empty_title.setText(self.get_text("empty_no_interests"))
            elif not self.interest_catalogue:
                # 喜好还在，但资源库里已经没有对应的标签了
                self.empty_title.setText(
                    self.get_text("no_interests_in_library"))
            else:
                self.empty_title.setText(self.get_text("empty_no_match"))
            # 副标题统一用"这一页是干什么的"，比重复一句"没匹配到"更有信息量
            self.empty_hint.setText(self.get_text("onboard_subtitle"))
        except Exception as exc:
            log.err("定制", "empty_state", f"空状态切换失败: {exc}")

    def _on_edit_clicked(self):
        """「编辑喜好」/ 空状态里的按钮：回到喜好设置（带一小段淡入）"""
        try:
            self._show_onboard_view(animate=True)
        except Exception as exc:
            log.err("定制", "edit", f"切换回喜好设置失败: {exc}")

    # ---------- 卡片 ----------
    def _on_card_clicked(self, data: dict):
        """卡片被点击：把数据抛给外面（主窗口可以接详情页）；没人接就给句提示"""
        try:
            data = data if isinstance(data, dict) else {}
            self.card_activated.emit(data)
            if not self.receivers(self.card_activated):
                self._toast(self.get_text("hint_open_in_search").format(
                    name=data.get("name", "")), "info")
            log.op("定制", "open_card", code=_code_of(data),
                   name=str(data.get("name") or ""))
        except Exception as exc:
            log.err("定制", "card", f"卡片点击处理失败: {exc}")

    def _on_favorite_toggled(self, code: str):
        """收藏按钮：写进收藏夹，并把状态同步回卡片 / 通知别的页面"""
        if self.favorites is None or not code:
            return
        try:
            state = self.favorites.toggle(code)
            codes = self.favorites.all_codes()
            self.apps_framework.set_favorites(codes)
            self.favorites_changed.emit()
            log.op("定制", "favorite", code=code,
                   state="已收藏" if state else "取消收藏")
        except Exception as exc:
            log.err("定制", "favorite", f"收藏切换失败: {exc}")

    # ================= 滚动（虚拟化窗口要位置） =================
    def _scroll_origin(self) -> int:
        """框架自己在滚动内容里的 y（上面还有标题区，两个坐标系差这个数）"""
        try:
            return int(self.apps_framework.y())
        except Exception:
            return 0

    def _sync_scroll_offset(self, value: int = None):
        framework = getattr(self, "apps_framework", None)
        if framework is None:
            return
        try:
            if value is None:
                value = self.scroll_area.verticalScrollBar().value()
            framework.set_scroll_offset(value, self._scroll_origin())
        except Exception:
            pass

    def _on_scrolled(self, value: int):
        """滚动位置一变就告诉框架；图标等停下来再补（滚动中读盘会掉帧）"""
        self._sync_scroll_offset(value)
        try:
            if not self._scrolled_timer.isActive():
                self._scrolled_timer.start()
        except Exception:
            pass

    def _on_scroll_idle(self):
        framework = getattr(self, "apps_framework", None)
        if framework is not None:
            try:
                framework.request_visible_icons()
            except Exception:
                pass

    # ================= 生命周期 =================
    def on_shown(self):
        """每次这一页被显示出来时调用（主窗口切页 / 本页 showEvent 都会走）"""
        if not self._ui_ready:
            return
        try:
            # 资源库没读进来（比如启动时文件还没准备好）→ 这里补一次；只重建胶囊，
            # ⚠️ 新冒出来的"组"不会新建一行（这种情况极少见，不值得为它整块重建）
            if not self._catalogue_loaded:
                self._load_catalogue()
                self._fill_chips()
                self.no_interest_label.setVisible(not self.interest_catalogue)
                self._update_selection_state()
                # 胶囊是刚刚才铺进去的 → 卡片宽度得按新内容重量一遍，否则会停在"没有喜好"时的兜底宽度上
                self._sync_content_width()

            onboarded = bool(self._read_setting(SETTING_ONBOARDED, False))
            interests = self._stored_interests()
            # 卡片尺寸跟着搜索页的"磁贴 / 网格"走；模式变了网格会被重造，所以下面必须重新渲染一次
            mode_changed = self._sync_card_view_mode()
            if interests and onboarded:
                self.stacked.setCurrentWidget(self.recommend_page)
                # 喜好变了 / 网格刚重造 / 还没算过 → 重新算推荐
                if (mode_changed or self._data_key != frozenset(interests)
                        or not self.recommend_items):
                    self._refresh_recommendations(show_loading=True)
                self._sync_scroll_offset()
                QTimer.singleShot(0, self.apps_framework.restore_icons)
            else:
                self._show_onboard_view(animate=False)
            self._apply_styles()
        except Exception as exc:
            log.err("定制", "on_shown", f"定制页显示处理失败: {exc}")

    def showEvent(self, event):
        """页面变可见：下一拍走一遍 on_shown（布局先跑完再量位置）"""
        super().showEvent(event)
        try:
            self._sync_content_width()
            QTimer.singleShot(0, self.on_shown)
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_content_width()

    def _sync_content_width(self):
        """把喜好卡片调成"按内容定宽 + 居中 + 最多 880px"。

        ⚠️ 不能卡死 880px：里面的胶囊是每行左对齐的，卡片比内容宽太多时右边会空出一大片，
        看上去像"内容缩在左上角"。宽度按"最宽的一行胶囊 + 内边距"定（有上下限）。
        """
        card = getattr(self, "onboard_card", None)
        if card is None:
            return
        try:
            width = self._natural_card_width()
            if card.width() != width:
                card.setFixedWidth(width)
        except Exception as exc:
            log.warn("定制", "layout", f"喜好卡片宽度同步失败（忽略）: {exc}")

    def _natural_card_width(self) -> int:
        """喜好卡片的自然宽度（最宽一行 + 内边距），并夹在页面宽度 / 880px 之内。

        ⚠️ 要多留一个行间距：ChipFlow 换行的判断是"下一颗的左边缘 + spacing + 宽度 > 可用宽度"，
        行尾还欠着一个 spacing。少了这 8px，最后那颗胶囊在收窄之后就会被挤到第二行去
        （实测最宽行 536 → 按 536 收窄 → 只剩 426，白空一大块、视觉重心又偏左）。
        """
        cap = min(SIZES["content_max_width"], max(300, self.width() - 48))
        # 可用宽度 = 卡片宽度 - 左右内边距 - QSS 那圈 1px 描边（两侧共 2px）
        cap_inner = max(160, cap - 2 * CARD_PADDING - 2)
        spacings = [flow.spacing for flow in getattr(self, "_flows", {}).values()]
        spacing = max(spacings) if spacings else 8
        widest = self._chip_block_width(cap_inner)
        if not widest:
            # 资源库里一个喜好都没有：给个能容下那几句说明的宽度就够
            return max(300, min(SIZES["content_max_width"], cap, 560))
        need = widest + spacing + 2 * CARD_PADDING + 2
        if need > cap:
            # 窗口本身就放不下最宽那一行：以窗口为准（这时候必然重排，窗口就那么大，没办法）
            need = cap
        return max(300, min(SIZES["content_max_width"], need))

    def _chip_block_width(self, limit: int) -> int:
        """按 ChipFlow 那套换行规则算出"最宽的一行"有多宽（一颗胶囊都没有就返回 0）。

        ⚠️ 在这儿复制这几行是不得已：ChipFlow 只提供"按当前宽度排好"的结果，没有"自然宽度"接口，
        而那个文件不在本次改动范围内。
        ⚠️ 不能照抄 _compute（算高度用的那份）：它把 x 记成"当前行的右边缘"、比较时又加了一次
        spacing，于是同一个宽度下它说"放得下"、_relayout 说"放不下"。布局真正听 _relayout，这里跟它对齐。
        """
        limit = max(1, int(limit))
        widest = 0
        for flow in getattr(self, "_flows", {}).values():
            widgets = flow.widgets()
            if not widgets:
                continue
            x = 0          # 下一颗胶囊的左边缘（和 ChipFlow._relayout 口径一致）
            for chip in widgets:
                w = chip.width() or chip.sizeHint().width()
                if x > 0 and x + flow.spacing + w > limit:
                    widest = max(widest, x - flow.spacing)
                    x = 0
                x += w + flow.spacing
            if x > 0:
                widest = max(widest, x - flow.spacing)
        return widest

    def hideEvent(self, event):
        """离开这一页：把图标资源放掉（卡片控件留着，回来复用）"""
        super().hideEvent(event)
        try:
            if self._scrolled_timer is not None:
                self._scrolled_timer.stop()
        except Exception:
            pass
        framework = getattr(self, "apps_framework", None)
        if framework is not None:
            try:
                framework.release_icons()
            except Exception:
                pass

    # ================= 主题 / 样式 =================
    def refresh_theme(self, force: bool = False):
        """主题（或"组件配色"）变了：重上样式、清胶囊配色缓存（必须轻，绝不重建卡片）。"""
        try:
            self._apply_styles(force=force)
        except Exception as exc:
            log.err("定制", "theme", f"定制页主题刷新失败: {exc}")
        try:
            reset_chip_color_cache()
            for chip in self.interest_chips.values():
                chip.update()
            # 进度条也是自绘的（颜色是当场从 token 取的，重画一次就够）
            progress = getattr(self, "selection_progress", None)
            if progress is not None:
                progress.update()
        except Exception:
            pass
        try:
            self._update_selection_state()
            self._update_recommend_header()
        except Exception:
            pass
        framework = getattr(self, "apps_framework", None)
        if framework is not None:
            try:
                framework.refresh_theme(force=force)
            except Exception as exc:
                log.err("定制", "theme", f"卡片重染色失败: {exc}")

    def _apply_styles(self, force: bool = False):
        """按深浅主题上样式（同一个主题下重复调用直接跳过）。

        ⚠️ setStyleSheet 会让 Qt 把整棵子树重新 polish，所以关键不是"写一次样式表"，
        而是"别在主题没变时反复写"（搜索页实测过一次 80~150ms）。
        样式分别挂在两个小容器上（喜好卡片 / 标题区），不挂整页 —— 整页下面还挂着卡片网格。
        """
        dark = isDarkTheme()
        if not force and self._style_dark == dark:
            return
        self._style_dark = dark
        colors = tokens(dark)

        # 文字色：只有"次要文字"和分组小标题这两类需要自己上色，其余交给 qfluentwidgets 自己的主题样式
        text_qss = (
            f"#customizeMuted {{ color: {colors['text_secondary']}; }}"
            f"#customizeSectionTitle {{ color: {colors['accent']}; }}"
            f"#customizeSectionRule {{ background-color: {colors['divider']}; }}"
        )

        # 喜好卡片：底色 + 描边 + 圆角（SimpleCardWidget 的标准写法）——库自己那层半透明底
        # 在灰底上看不出边界，必须按设计 token 显式给一层实色
        card = getattr(self, "onboard_card", None)
        if card is not None:
            try:
                card.setStyleSheet(
                    f"SimpleCardWidget#customizeOnboardCard {{"
                    f" background-color: {colors['card']};"
                    f" border: 1px solid {colors['card_border']};"
                    f" border-radius: {SIZES['card_radius']}px;"
                    f" }}"
                    + text_qss)
            except Exception:
                pass

        header = getattr(self, "recommend_header", None)
        if header is not None:
            try:
                header.setStyleSheet(text_qss)
            except Exception:
                pass

        try:
            self.empty_hint.setStyleSheet(
                f"color: {colors['text_secondary']};")
        except Exception:
            pass

        # 底部分隔线：跟着主题（浅色一条浅灰，深色一条深灰）
        divider = getattr(self, "bar_divider", None)
        if divider is not None:
            try:
                divider.setStyleSheet(
                    f"background-color: {colors['divider']};")
            except Exception:
                pass

        self._apply_scrollbar_style()

    def _apply_scrollbar_style(self):
        """细圆角滚动条（和插件中心 / 设置页同一套，直接照着抄的）"""
        dark = isDarkTheme()
        handle = "#555555" if dark else "#CCCCCC"
        qss = f"""
            QScrollArea {{ border: none; background-color: transparent; }}
            QWidget#customizeScrollContent {{ background-color: transparent; }}
            QScrollBar:vertical {{ background-color: transparent; width: 8px;
                margin: 0px; border-radius: 4px; }}
            QScrollBar::handle:vertical {{ background-color: {handle};
                min-height: 30px; border-radius: 4px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px; background: none; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none; }}
        """
        for area in (getattr(self, "onboard_scroll", None),
                     getattr(self, "scroll_area", None)):
            if area is None:
                continue
            try:
                area.setStyleSheet(qss)
            except Exception:
                pass

    def _sync_card_view_mode(self) -> bool:
        """让卡片尺寸跟上搜索页当前选的"磁贴 / 网格"视图（返回是否真的变了）。

        卡片尺寸是 widgets/app_card.py 里的模块级全局量，搜索页启动时会设好；用户在设置里改了
        之后本页会停在旧值上，所以发现模式变了就把网格槽位重造一次（调用方随后要重渲染）。
        """
        try:
            from ..widgets import app_card as card_module
            mode = str(self.settings_manager.settings.get("search_view", "tile"))
            if mode == self._card_mode:
                return False
            self._card_mode = mode
            card_module.apply_view_mode(mode)
            self.apps_framework.reset_pools()
            return True
        except Exception as exc:
            log.err("定制", "card_view", f"同步卡片视图失败: {exc}")
            return False

    # ================= 小工具 =================
    def _fade_in(self, widget, duration_ms: int = 180):
        """给切进来的视图做一小段淡入（不是硬跳）。

        ⚠️ 只给喜好设置页用（只有几十个胶囊，做透明度特效很便宜）；推荐页挂着卡片网格，
        套 QGraphicsOpacityEffect 等于每帧把整页离屏重绘一遍，那边走"先亮加载动画"那条路。
        """
        try:
            if widget is None or not widget.isVisible():
                return
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", widget)
            anim.setDuration(duration_ms)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(lambda w=widget: self._end_fade(w))
            self._fade_anim = anim
            anim.start()
            # 兜底：万一 finished 因为别的原因没来，也不能把这一页留在透明度 0
            QTimer.singleShot(duration_ms + 250,
                              lambda w=widget: self._end_fade(w))
        except Exception as exc:
            log.warn("定制", "fade", f"淡入动画失败（忽略）: {exc}")

    def _end_fade(self, widget):
        """把特效摘掉（留着的话这一页每次重绘都要离屏合成）"""
        try:
            anim = self._fade_anim
            self._fade_anim = None
            if anim is not None:
                anim.stop()
            widget.setGraphicsEffect(None)
        except Exception:
            pass

    def _toast(self, message: str, kind: str = "info"):
        """InfoBar 提示（成功的绿条 / 警告的黄条 / 普通信息）"""
        try:
            title = self.get_text("toast_success_title" if kind == "success"
                                  else "toast_info_title")
            kwargs = dict(orient=Qt.Horizontal, isClosable=True,
                          position=InfoBarPosition.TOP, duration=2200,
                          parent=self)
            if kind == "success":
                InfoBar.success(title=title, content=message, **kwargs)
            elif kind == "warning":
                InfoBar.warning(title=title, content=message, **kwargs)
            elif kind == "error":
                InfoBar.error(title=title, content=message, **kwargs)
            else:
                InfoBar.info(title=title, content=message, **kwargs)
        except Exception as exc:
            log.err("定制", "toast", f"提示条失败: {exc}")

    def _read_setting(self, key: str, default):
        """读一个设置（键不存在 → 默认值；管理器不在 / 结构不对也不抛）"""
        try:
            value = self.settings_manager.settings.get(key, default)
            return default if value is None else value
        except Exception:
            return default

    def _write_setting(self, key: str, value) -> bool:
        """写一个设置（对未知键也照写，见 SETTING_INTERESTS 的说明）"""
        try:
            self.settings_manager.update_setting(key, value)
            return True
        except Exception as exc:
            log.err("定制", "settings", f"写入 {key} 失败: {exc}")
            return False

    def _term(self, value: str) -> str:
        """资源库术语（类别 / 标签）的显示译名。

        ⚠️ 只改显示：设置里存的值、和资源比对用的键仍然是规范中文值。
        """
        try:
            from ..core.language_manager import translate_term
            return translate_term(value, self.lang)
        except Exception:
            return str(value or "")

    def get_text(self, key):
        """查 customize 语言段，查不到退回代码里的中文兜底（和搜索页一个写法）"""
        if self.lang:
            text = self.lang.get_text("customize", key)
            if text != key:
                return text
        defaults = {
            "onboard_title": "先选几个感兴趣的",
            "onboard_subtitle": "勾选你感兴趣的方向，我们照着你的喜好推荐资源；"
                                "以后随时可以点「编辑喜好」修改。",
            "group_category": "类别", "group_tag": "标签",
            "selected_count": "已选 {n} 个",
            "btn_start": "开始", "btn_save": "保存", "btn_clear": "全不选",
            "recommend_title": "为你推荐",
            "recommend_basis": "根据你选的：{names}",
            "btn_edit_interests": "编辑喜好",
            "recommend_count": "共 {n} 个推荐",
            "empty_no_match": "这几个喜好暂时没有匹配的资源，换几个试试。",
            "empty_no_interests": "还没有选择喜好，先挑几个吧。",
            "empty_action": "去设置喜好",
            "no_interests_in_library": "资源库里暂时没有可选的喜好标签。",
            "list_separator": "、",
            "toast_saved": "喜好已保存",
            "toast_success_title": "成功", "toast_info_title": "提示",
            "toast_need_interest": "请至少选择一个喜好",
            "hint_open_in_search": "在搜索页搜索「{name}」可以查看详情。",
            # 「恢复默认」相关（MessageBox 的默认按钮是库自带的英文 "OK / Cancel"，取消按钮也要本地化）
            "btn_reset_interests": "恢复默认",
            "btn_cancel": "取消",
            "confirm_reset_interests":
                "确定要删除所有喜好、恢复到默认状态吗？删除后推荐页会清空，"
                "需要重新挑一次。",
            "toast_interests_reset": "已恢复默认，请重新选择喜好",
        }
        return defaults.get(key, key)
