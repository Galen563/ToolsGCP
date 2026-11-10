"""设置界面（组装层）：把各板块拼成一整页（左侧列表是页内锚点），并处理主题 / 语言 / 文案 / 提示等全局逻辑。

具体卡片怎么画、点了怎么处理看同目录：cards_ui.py（外观/启动/搜索/快捷键）、cards_download.py（下载源与限速）、
cards_ai.py（AI / API Key / 模型调用）、cards_misc.py（功能/开发者/关于）。
卡片与回调按类别放在 4 个 mixin 里，mixin 之间通过 self 互相调用，所以不要在 mixin 里定义 __init__。

⚠️ 左侧列表的配色一律取自 .theme 的 token（页面底色 + 强调色浅底），不给它单独一套颜色。
"""

from PyQt5.QtCore import (Qt, QEvent, QPoint, QPropertyAnimation, QEasingCurve,
                          QTimer)
from PyQt5.QtGui import QFont, QIntValidator
from PyQt5.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout,
                             QLabel, QLineEdit, QScrollArea, QSizePolicy,
                             QVBoxLayout, QWidget)
from qfluentwidgets import (SimpleCardWidget, ComboBox, SwitchButton, LineEdit,
                            PrimaryPushButton, BodyLabel, SubtitleLabel, Slider,
                            ToolTipFilter, ToolTipPosition, MessageBox, InfoBar,
                            InfoBarPosition, PushButton, CheckBox)
from datetime import datetime
import sys
if sys.platform == 'win32':
    import winreg

from ...core.language_manager import LanguageManager
from ...core.settings_manager import SettingsManager
from ...ui.hotkey_edit import HotkeyEdit
from ...ui.key_display_window import KeyDisplayWindow
from ...utils.smooth_scroll import install_smooth_scroll, stop_smooth_scroll
from ...utils.system_utils import (set_windows_autostart, restart_program,
                                   detect_system_theme, detect_system_language)
from ...utils.theme_utils import is_dark_mode, apply_app_palette
from ...constants import VALID_GCP_KEYS, DEV_KEYS, SPECIAL_KEYS, SOURCE_OPTIONS

from .texts import FALLBACK_TEXTS
from .common import (DISABLED_TEXT_COLOR, DEFAULT_TEXT_LIGHT, DEFAULT_TEXT_DARK,
                     PAGE_ORDER, HOTKEY_DEFAULTS, SettingsSaveDebouncer)
from .theme import SIZES, apply_accent_color, panel_stylesheet, tokens
from .widgets import (SettingCard, SettingPage, SettingRow, TipIcon,
                      UnsavedChangesDialog)
from .cards_ui import SettingsCardsUiMixin
from .cards_hotkey import SettingsCardsHotkeyMixin
from .cards_download import SettingsCardsDownloadMixin
from .cards_ai import SettingsCardsAiMixin
from .cards_misc import SettingsCardsMiscMixin
from .cards_storage import SettingsCardsStorageMixin


# 板块之间的间距（比卡片间距大，用来拉开层级）
SECTION_GAP = SIZES["section_gap"]
# 锚点跳转的动画时长
ANCHOR_DURATION_MS = 320
# 判定"当前在哪个板块"时，允许标题落在视口上方多少像素以内
SECTION_DETECT_OFFSET = 60


def _widget_text_blob(widget) -> str:
    """把一个控件（含所有子控件）里"看得见的文字"拼成一串，供设置搜索匹配。

    下拉框的选项也要收：用户搜 "github" 时界面上其实没有写着 github 的标签，它是「下载源」里的一个选项。
    ⚠️ qfluentwidgets 的 ComboBox 不是 QComboBox（它是 QPushButton 的子类），只能按
    "有 itemText(i) + count()" 的鸭子类型认；EditableComboBox 是 QLineEdit 子类，会被 QLineEdit 分支收到。
    """
    if widget is None:
        return ""
    parts = []
    try:
        for label in widget.findChildren(QLabel):
            text = label.text()
            if text:
                parts.append(text)
        for button in widget.findChildren(QAbstractButton):
            text = button.text()
            if text:
                parts.append(text)
        for edit in widget.findChildren(QLineEdit):
            parts.append(edit.text())
            parts.append(edit.placeholderText())
        # 各种下拉框（含 qfluentwidgets 的 ComboBox）的全部选项
        for child in widget.findChildren(QWidget):
            item_text = getattr(child, "itemText", None)
            counter = getattr(child, "count", None)
            if not (callable(item_text) and callable(counter)):
                continue
            try:
                for index in range(int(counter())):
                    parts.append(str(item_text(index)))
            except Exception:
                continue
    except RuntimeError:
        # 控件刚好被销毁（主题切换/重建时可能发生），当作没有文字
        return ""
    return " ".join(p for p in parts if p)


def _first_label_text(widget, fallback: str = "") -> str:
    """取控件里第一个非空标签文字（搜索结果列表里当标题用）"""
    if widget is None:
        return fallback
    for label in widget.findChildren(QLabel):
        text = str(label.text() or "").strip()
        if text:
            return text
    return fallback


class SettingsInterface(SettingsCardsUiMixin,
                        SettingsCardsHotkeyMixin,
                        SettingsCardsDownloadMixin,
                        SettingsCardsAiMixin,
                        SettingsCardsMiscMixin,
                        SettingsCardsStorageMixin,
                        QWidget):
    """设置页面。

    卡片与回调按类别放在 4 个 mixin 里，这里只负责组装和全局逻辑。
    ⚠️ 不要在 mixin 里定义 __init__：mixin 之间通过 self 互相调用。
    """

    def __init__(self, settings_manager: SettingsManager,
                 language_manager: LanguageManager = None,
                 main_window=None):
        super().__init__()
        self.setObjectName("settingsInterface")
        self.settings_manager = settings_manager
        self.lang = language_manager
        self.main_window = main_window
        self.current_theme = settings_manager.settings.get("theme", "跟随系统")
        # 板块字典：key -> {"page": SettingPage, "wrapper": QWidget, "label": str}
        self._sections = {}
        self._page_order = []
        # 旧的 page_stack 属性留着但不使用（老代码/测试脚本可能还会摸它）
        self.page_stack = None
        # 滑块连续拖动时合并落盘（避免每动一下都写文件 + 记日志）
        self._saver = SettingsSaveDebouncer(self, self.settings_manager)
        # 样式表指纹：没变就不重复设置整页样式
        self._style_key = None
        # 锚点滚动动画（点左侧列表时用；动画期间不要用滚动位置反推当前板块）
        self._anchor_anim = None
        self._anchor_target = None
        # 设置搜索：当前命中的条目 [(板块key, 控件, 文本), ...]
        self._search_entries = []
        # 搜索用的"全页可搜索条目"缓存（见 _collect_search_entries）
        self._search_entry_cache = None
        # 左侧列表"点一下会连发两个信号"的去重标记（见 _on_section_row_changed）
        self._row_changed_by_click = False

        self.dev_input = None
        self.dev_verify_btn = None
        self.debug_info_switch = None

        self.setup_ui()
        self.apply_theme_colors(self.current_theme)


    def get_language_options(self):
        """动态获取语言选项"""
        follow_system = self.get_text("follow_system")
        return [follow_system, "简体中文", "繁體中文", "English"]


    def get_theme_options(self):
        """动态获取主题选项"""
        return [
            self.get_text("follow_system"),
            self.get_text("light_theme"),
            self.get_text("dark_theme")
        ]


    def get_source_options(self):
        """获取源选项。

        ⚠️ 只剩 GitHub 了（需求："设置中的搜索源和下载源中的国内源删除"）。
        """
        return [self.get_text("github_source")]


    def get_default_source_for_current_language(self):
        """根据当前语言获取默认源"""
        current_lang = self.lang.current_language if self.lang else "简体中文"
        return self.settings_manager.get_default_source_by_language(current_lang)


    def is_dark_mode(self):
        """判断当前是否为深色模式"""
        return is_dark_mode(self.current_theme)


    @staticmethod
    def set_label_disabled(label, disabled):
        """统一切换标签的"联动置灰"状态。

        ⚠️ FluentLabelBase 系列（BodyLabel 等）会把自己的颜色写进样式表、并在每次主题变化时重写，
        优先级高于父级样式表，所以对它走自己的 setTextColor，普通 QLabel 才走父级属性选择器。
        """
        if label is None:
            return
        disabled = bool(disabled)

        set_text_color = getattr(label, "setTextColor", None)
        if callable(set_text_color):
            if disabled:
                set_text_color(DISABLED_TEXT_COLOR, DISABLED_TEXT_COLOR)
            else:
                set_text_color(DEFAULT_TEXT_LIGHT, DEFAULT_TEXT_DARK)
            return

        if bool(label.property("disabledText")) == disabled:
            return
        label.setProperty("disabledText", disabled)
        # 动态属性变化后必须重新 polish，样式表里的属性选择器才会生效
        label.style().unpolish(label)
        label.style().polish(label)


    # ================= 结构 =================
    def setup_ui(self):
        """设置 UI：左「板块列表」+ 右「一整页（所有板块都在里面）」。

        ⚠️ 所有板块一次性建出来：单页结构要算锚点位置就绕不开"每块都有真实高度"，
        实测多花的时间只有 200ms 左右（第 2 个板块往后一共 518 个子控件），换来的是一滚到底。
        """
        if self.layout():
            while self.layout().count():
                item = self.layout().takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.layout().deleteLater()

        self._sections = {}
        self._page_order = []
        self._search_entry_cache = None

        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        main.addWidget(self._create_sidebar())
        main.addWidget(self._create_content(), 1)

        self._select_section(self._page_order[0], scroll=False) if self._page_order else None
        self.refresh_theme_styles()

    def _create_content(self) -> QScrollArea:
        """右侧：一整页滚动区（所有板块自上而下排在一起）"""
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("settingsScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        host = QWidget()
        host.setObjectName("settingsHost")
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        # ⚠️ 限宽靠 content 自己（居中 + 880 上限）：直接塞进 QScrollArea 会让它缩到 sizeHint，必须隔一层 host
        self.content = QWidget()
        self.content.setObjectName("settingsContent")
        self.content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, SIZES["content_margin"], 0, 40)
        self.content_layout.setSpacing(SECTION_GAP)

        for key, label_key, builders in self._section_definitions():
            wrapper = self._build_section_widget(key, label_key, builders)
            self.content_layout.addWidget(wrapper)
            self._page_order.append(key)

        host_layout.addWidget(self.content, 0, Qt.AlignHCenter | Qt.AlignTop)
        host_layout.addStretch(1)
        self.scroll_area.setWidget(host)

        install_smooth_scroll(self.scroll_area)
        # 滚动到哪儿，左侧列表的高亮就跟到哪儿
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self.scroll_area.viewport().installEventFilter(self)
        return self.scroll_area

    def _build_section_widget(self, key: str, label_key: str, builders: list) -> QWidget:
        """建一个板块（页头 + 若干卡片），装进 wrapper 里以便锚点定位"""
        label = self.get_text(label_key)
        page = SettingPage(label)
        for builder in builders:
            card = builder()
            if card is not None:
                page.add_card(card)

        wrapper = QWidget()
        wrapper.setObjectName(f"settingsSection_{key}")
        box = QVBoxLayout(wrapper)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(page)

        self._sections[key] = {"page": page, "wrapper": wrapper, "label": label}
        return wrapper

    # ---------- 板块定义 ----------
    def _section_definitions(self) -> list:
        """板块列表：(内部键, 语言键, [构建函数, ...])，顺序 = 左侧列表和页面里从上到下的顺序。

        ⚠️ AI 开关 / API Key / 模型调用合成一个「GCP-AI」板块里的三张卡片（本来就是同一件事）；
        老键名（api_key / model）保留在 _SECTION_ALIASES 里，外部跳转不会失效。
        """
        return [
            ("appearance", "appearance", [self._create_appearance_card]),
            ("startup", "startup", [self._create_startup_card]),
            ("search", "search_settings", [self._create_search_card]),
            ("hotkey", "hotkey_section", [self._create_hotkey_card]),
            ("download", "download", [self._create_download_card]),
            ("functions", "functions", [self._create_function_card]),
            ("storage", "storage_section", [self._create_storage_card]),
            ("ai", "ai_section", [self._create_ai_card,
                                  self._create_api_key_card,
                                  self._create_model_calling_card]),
            ("dev", "developer_functions", [self._create_dev_card]),
            ("about", "about", [self._create_about_card]),
        ]

    # 老键名 → 现在的板块键（合并板块后外部跳转还能用）
    _SECTION_ALIASES = {
        "api_key": "ai",
        "model": "ai",
        "api": "ai",
    }

    def _resolve_section_key(self, key: str) -> str:
        key = str(key or "")
        return self._SECTION_ALIASES.get(key, key)

    # ---------- 左侧栏 ----------
    def _create_sidebar(self) -> QWidget:
        """左侧板块列表：标题 + 搜索框 + （板块列表 / 搜索结果二选一）"""
        from PyQt5.QtWidgets import QAbstractItemView
        from qfluentwidgets import ListWidget, SearchLineEdit

        side = QWidget(self)
        side.setObjectName("settingsSidebar")
        side.setFixedWidth(SIZES["sidebar_width"])
        box = QVBoxLayout(side)
        box.setContentsMargins(16, SIZES["content_margin"], 8, 16)
        box.setSpacing(12)

        self.sidebar_title = SubtitleLabel(self.get_text("settings_title"), side)
        self.sidebar_title.setObjectName("settingsTitle")
        box.addWidget(self.sidebar_title)

        self.settings_search = SearchLineEdit(side)
        self.settings_search.setPlaceholderText(self.get_text("settings_search_hint"))
        self.settings_search.textChanged.connect(self._on_settings_search)
        self.settings_search.searchSignal.connect(self._on_settings_search)
        self.settings_search.returnPressed.connect(self._on_search_return)
        box.addWidget(self.settings_search)

        self.section_list = ListWidget(side)
        self.section_list.setObjectName("settingsSectionList")
        self.section_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.section_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for key, label_key, _builders in self._section_definitions():
            self.section_list.addItem(self.get_text(label_key))
        self.section_list.setCurrentRow(0)
        self.section_list.currentRowChanged.connect(self._on_section_row_changed)
        self.section_list.itemClicked.connect(self._on_section_item_clicked)
        box.addWidget(self.section_list, 1)

        # 搜索结果列表（和板块列表占同一个位置，搜索时才显示）
        # 需求："有时搜索他有 2 个（命中）并不会让你选择，而是默认给你导航到第一个" —— 所以全部列出来
        self.search_results = ListWidget(side)
        self.search_results.setObjectName("settingsSearchResults")
        self.search_results.setSelectionMode(QAbstractItemView.SingleSelection)
        self.search_results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.search_results.itemClicked.connect(self._on_search_result_clicked)
        self.search_results.hide()
        box.addWidget(self.search_results, 1)
        return side

    def _on_section_row_changed(self, row: int):
        # ⚠️ 点一行会连着发两个信号（先 currentRowChanged、再 itemClicked）；两边都跳就是重复滚动 + 重复记日志。
        # 这里用一个"刚由换行处理过"的标记把第二次挡掉。
        self._row_changed_by_click = True
        QTimer.singleShot(0, lambda: setattr(self, "_row_changed_by_click", False))
        if 0 <= row < len(self._page_order):
            self._select_section(self._page_order[row])

    def _on_section_item_clicked(self, _item):
        """点左侧列表：即使点的就是当前项，也要重新滚回去（用户可能滚远了）。

        只有"重复点同一行"才会走到这里 —— 换行的情况已经由 currentRowChanged 处理。
        """
        if getattr(self, "_row_changed_by_click", False):
            return
        row = self.section_list.currentRow()
        if 0 <= row < len(self._page_order):
            self._select_section(self._page_order[row])

    def _select_section(self, key: str, scroll: bool = True, force: bool = False) -> bool:
        """切到某个板块 = 滚到它在页面里的位置（不再是切页）。

        ⚠️ 页内换板块不再拦截"API Key 没保存"：只有真的要离开设置页时才问（那道拦截在 MainWindow.switchTo 里）。
        """
        key = self._resolve_section_key(key)
        info = self._sections.get(key)
        if info is None:
            return False
        target_row = self._page_order.index(key)
        if self.section_list.currentRow() != target_row:
            self.section_list.blockSignals(True)
            self.section_list.setCurrentRow(target_row)
            self.section_list.blockSignals(False)
        if scroll:
            self._scroll_to_widget(info["wrapper"])
        self._current_section_key = key
        try:
            from ...utils.logger import log
            log.op("设置", "section", section=key)
        except Exception:
            pass
        return True

    def _restore_section_row(self):
        """把左侧列表的选中项拨回"当前所在的板块"（拦截后调用）"""
        key = getattr(self, "_current_section_key", None)
        if key not in self._page_order:
            return
        row = self._page_order.index(key)
        if self.section_list.currentRow() == row:
            return
        self.section_list.blockSignals(True)
        self.section_list.setCurrentRow(row)
        self.section_list.blockSignals(False)

    # ---------- 锚点滚动 ----------
    def _scroll_to_widget(self, widget, extra_top: int = 6):
        """把某个控件滚到视口顶部（带一点上边距）"""
        if widget is None or self.scroll_area is None:
            return
        bar = self.scroll_area.verticalScrollBar()
        try:
            target = widget.mapTo(self.content, QPoint(0, 0)).y() - extra_top
        except Exception:
            return
        target = max(bar.minimum(), min(bar.maximum(), int(target)))
        self._animate_scroll(bar, target)

    def _animate_scroll(self, bar, target: int):
        """滚动条动画（点左侧列表时用）。

        ⚠️ 必须先把"惯性滚动"停掉：它自己也有一条 value 动画，两边同时跑会互相抢位置。
        """
        stop_smooth_scroll(self.scroll_area)
        if self._anchor_anim is not None:
            try:
                self._anchor_anim.stop()
            except Exception:
                pass
        if bar.value() == target:
            return
        anim = QPropertyAnimation(bar, b"value", self)
        anim.setDuration(ANCHOR_DURATION_MS)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(bar.value())
        anim.setEndValue(target)
        anim.finished.connect(self._on_anchor_finished)
        self._anchor_anim = anim
        self._anchor_target = target
        anim.start()

    def _on_anchor_finished(self):
        self._anchor_anim = None
        self._anchor_target = None
        self._sync_section_from_scroll(force=True)

    def _on_scroll_changed(self, _value: int):
        """用户滚动页面：左侧列表的高亮跟着走（动画期间不跟，免得打架）"""
        if self._anchor_anim is not None:
            return
        self._sync_section_from_scroll()

    def _sync_section_from_scroll(self, force: bool = False):
        if not self._page_order or self.scroll_area is None:
            return
        bar = self.scroll_area.verticalScrollBar()
        value = bar.value()
        # 滚到底部时，直接高亮最后一块 —— 否则最后一块高度太矮就永远轮不到它
        if bar.maximum() > 0 and value >= bar.maximum() - 2:
            key = self._page_order[-1]
        else:
            key = self._page_order[0]
            for candidate in self._page_order:
                wrapper = self._sections[candidate]["wrapper"]
                if wrapper.y() <= value + SECTION_DETECT_OFFSET:
                    key = candidate
                else:
                    break
        if not force and getattr(self, "_current_section_key", None) == key:
            return
        self._current_section_key = key
        row = self._page_order.index(key)
        if self.section_list.currentRow() != row:
            self.section_list.blockSignals(True)
            self.section_list.setCurrentRow(row)
            self.section_list.blockSignals(False)

    def _apply_content_width(self):
        """给内容页限宽 + 居中（880px 上限，两侧自动留白）。

        不限宽的话行宽能到 1200px+，标签在最左、控件在最右，视线要横跨整屏才能把两者对起来。
        """
        if self.scroll_area is None or not hasattr(self, "content"):
            return
        max_width = SIZES["content_max_width"]
        try:
            available = self.scroll_area.viewport().width() - SIZES["content_margin"] * 2
            width = max(320, min(max_width, available))
            if self.content.width() != width or self.content.maximumWidth() != width:
                self.content.setFixedWidth(width)
        except Exception:
            pass

    def eventFilter(self, obj, event):
        """内容区尺寸变了就重算限宽/居中"""
        if event.type() == QEvent.Resize and self.scroll_area is not None \
                and obj is self.scroll_area.viewport():
            self._apply_content_width()
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        # 首次显示时视口宽度才是真实的，补算一次限宽
        QTimer.singleShot(0, self._apply_content_width)
        QTimer.singleShot(60, self._apply_content_width)
        # 搜索页工具栏那边也能切视图，回到设置页时把控件刷新成最新值
        if hasattr(self, "sync_search_controls"):
            self.sync_search_controls()
        # 组件配色同理（理论上只有本页在改，但配置可能被别处写过）
        if hasattr(self, "sync_accent_combo"):
            self.sync_accent_combo()

    # ================= 设置搜索 =================
    def _section_entries(self, key: str) -> list:
        """某个板块里所有"可以当作搜索目标"的条目：[(控件, 可匹配文字), ...]。

        粒度优先取"行"（SettingCard 的 rows，或旧卡片里的直接子控件），实在拆不开就退化成整张卡片。
        """
        info = self._sections.get(key)
        if info is None:
            return []
        out = []
        page = info["page"]
        # 板块名本身也是一条：搜「API Key」这种板块名应该能直接跳过去
        out.append((page.title_label, info["label"]))
        for card in page.cards:
            rows = getattr(card, "rows", None)
            if rows:
                for row in rows:
                    text = getattr(row, "title_text", "") or ""
                    desc_label = getattr(row, "desc_label", None)
                    if desc_label is not None:
                        text += " " + desc_label.text()
                    text += " " + _widget_text_blob(row)
                    out.append((row, text))
                continue
            children = card.findChildren(QWidget, "", Qt.FindDirectChildrenOnly)
            found = False
            for child in children:
                text = _widget_text_blob(child)
                if not str(text).strip():
                    continue
                out.append((child, text))
                found = True
            if not found:
                out.append((card, _widget_text_blob(card)))
        return out

    def _collect_search_entries(self) -> list:
        """全页可搜索条目：[(板块key, 控件, 显示标题, 匹配文字), ...]。

        ⚠️ 结果要缓存：它要把 600 多个子控件的文字全读一遍（每敲一个字都会调），不缓存打字会一顿一顿的。
        板块是一次性建好的，所以缓存不会过期；setup_ui 里会把它清掉。
        """
        if self._search_entry_cache is not None:
            return self._search_entry_cache
        entries = []
        for key in self._page_order:
            info = self._sections[key]
            for widget, text in self._section_entries(key):
                title = _first_label_text(widget, info["label"]) or info["label"]
                entries.append((key, widget, title, text))
        self._search_entry_cache = entries
        return entries

    def _on_settings_search(self, text: str):
        """设置搜索：把所有命中项列出来让用户自己挑（不再"默认跳到第一个"）。

        多命中时直接跳第一个，用户根本不知道还有别的地方也匹配，等于把信息藏起来了。
        """
        keyword = str(text or "").strip().lower()
        if not keyword:
            self._search_entries = []
            self.search_results.clear()
            self.search_results.hide()
            self.section_list.show()
            return

        entries = self._collect_search_entries()
        hits = [entry for entry in entries if keyword in str(entry[3]).lower()]
        self._search_entries = hits

        self.search_results.clear()
        if not hits:
            self.search_results.addItem(self.get_text("settings_search_none"))
            self.section_list.hide()
            self.search_results.show()
            return

        for key, _widget, title, _text in hits:
            label = self._sections[key]["label"]
            self.search_results.addItem(f"{label} · {title}")
        self.section_list.hide()
        self.search_results.show()
        self.search_results.setCurrentRow(0)

    def _on_search_return(self):
        """搜索框里按 Enter：跳到第一条命中（想挑别的就点列表）"""
        if self._search_entries:
            self._jump_to_search_entry(0)

    def _on_search_result_clicked(self, item):
        row = self.search_results.row(item)
        self._jump_to_search_entry(row)

    def _jump_to_search_entry(self, index: int):
        if not (0 <= index < len(self._search_entries)):
            return
        key, widget, _title, _text = self._search_entries[index]
        # 先滚到板块，再滚到具体那一行（两次滚动合成一次目标位置）
        if not self._select_section(key, scroll=False):
            return      # 被"API Key 未保存"拦下了
        self._scroll_to_widget(widget, extra_top=80)
        QTimer.singleShot(ANCHOR_DURATION_MS + 40, lambda w=widget: self._flash_row(w))

    def _flash_row(self, row):
        """把命中的那一行闪一下（复用卡片高亮层，不碰布局）"""
        try:
            from ...ui.custom_widgets import CardHighlightOverlay
            overlay = CardHighlightOverlay(row, tokens(self.is_dark_mode())["accent"])
            overlay.start()
        except Exception:
            pass

    def _clear_search_highlight(self):
        pass

    # ================= 给"跳转到某个设置项"用的口子 =================
    def ensure_section_visible(self, key: str):
        """切到某个板块并返回滚动区域（外部要"滚到某个控件"时用）。

        典型用法：holder = settings.ensure_section_visible("api_key")，再 holder.ensureWidgetVisible(控件, 40, 120)。
        ⚠️ 返回的是整页那个 QScrollArea（单页结构下只有一个），它的 ensureWidgetVisible 照样能把目标控件滚进视野。
        """
        key = self._resolve_section_key(key)
        self._select_section(key)
        return self.scroll_area

    def section_of_widget(self, widget) -> str:
        """反查一个控件属于哪个板块（找不到就返回当前板块）"""
        if widget is not None:
            for key, info in getattr(self, "_sections", {}).items():
                wrapper = info["wrapper"]
                try:
                    if wrapper is widget or wrapper.isAncestorOf(widget):
                        return key
                except Exception:
                    continue
        return getattr(self, "_current_section_key", None) or (
            self._page_order[0] if self._page_order else "")

    def current_scroll_area(self):
        """当前滚动区域（老代码里 self.scroll_area 的替代品）"""
        return getattr(self, "scroll_area", None)

    def build_all_sections(self):
        """公开入口：立刻构建所有板块。

        ⚠️ 单页结构下所有板块在 setup_ui 里就建好了，这个方法只是保留给老脚本 / 测试用，返回 self。
        """
        return self

    # ================= API Key 未保存拦截 =================
    def api_key_unsaved(self) -> bool:
        """API Key / 模型 / 接口地址是否有"改了但没保存"的内容。

        判断方式是拿界面上的值和配置里的值对比，而不是记录"用户改过"：改完再改回去、或点过保存，
        状态会自动回到"没有未保存内容"，不需要维护一套容易出错的状态机。
        """
        if not hasattr(self, "api_key_input"):
            return False
        try:
            from ...core.ai.client import normalize_api_base
            current = (
                str(self.ai_provider_combo.currentData() or ""),
                self.model_name_input.currentText().strip(),
                normalize_api_base(self.api_base_input.text().strip()),
                self.api_key_input.text().strip(),
            )
            saved_base = str(self.settings_manager.settings.get("api_base", "") or "").strip()
            saved = (
                str(self.settings_manager.settings.get("ai_provider", "") or ""),
                str(self.settings_manager.settings.get("model_name", "") or "").strip(),
                normalize_api_base(saved_base) if saved_base else "",
                str(self.settings_manager.get_api_key() or "").strip(),
            )
        except Exception:
            return False
        return current != saved

    def confirm_leave_api_key(self, parent=None) -> bool:
        """有未保存内容时问用户；返回 True 表示"可以离开"。

        改过 API Key 没保存就"去其他界面 / 去其他设置目录"要提示并拦在原地；关程序也要提示。
        """
        if not self.api_key_unsaved():
            return True
        dialog = UnsavedChangesDialog(
            parent or self.window() or self,
            title=self.get_text("api_unsaved_title"),
            body=self.get_text("api_unsaved_body"))
        dialog.exec_()
        if dialog.choice == UnsavedChangesDialog.DISCARD:
            # 放弃修改：把界面上的值还原成配置里的值，然后放行
            self._reload_api_key_fields()
            return True
        if dialog.choice == UnsavedChangesDialog.SAVE:
            self.save_api_key()
            return not self.api_key_unsaved()
        return False

    def _reload_api_key_fields(self):
        """把 API Key 卡片的控件恢复成配置里的值（用于"放弃修改"）"""
        try:
            from ...core.ai import providers as ai_providers
            provider = str(self.settings_manager.settings.get("ai_provider", "") or "")
            self.ai_provider_combo.blockSignals(True)
            self.ai_provider_combo.setCurrentIndex(
                self._index_of(ai_providers.provider_items(), provider))
            self.ai_provider_combo.blockSignals(False)
            self.model_name_input.setCurrentText(
                str(self.settings_manager.settings.get("model_name", "") or ""))
            self.api_base_input.setText(
                str(self.settings_manager.settings.get("api_base", "") or ""))
            self.api_key_input.setText(str(self.settings_manager.get_api_key() or ""))
        except Exception:
            pass


    # ================= 主题 =================
    def refresh_theme_styles(self, force: bool = False):
        """刷新主题样式。

        给整页设一次样式表会触发整棵控件树重新 polish，代价不小；这里用「深浅色 + 界面语言」做指纹，
        没变化就直接跳过（启动时 setup_ui 和 apply_theme_colors 会各调一次）。
        ⚠️ 颜色全部来自 .theme 的 token，左侧板块列表也一样 —— 它只是"页面的一部分"。
        """
        style_key = (self.is_dark_mode(), getattr(self.lang, "current_language", ""))
        if not force and style_key == self._style_key:
            return
        self._style_key = style_key

        is_dark = self.is_dark_mode()
        self.setStyleSheet(panel_stylesheet(is_dark))

        handle_color = "#555555" if is_dark else "#CCCCCC"
        handle_hover = "#666666" if is_dark else "#AAAAAA"
        handle_pressed = "#777777" if is_dark else "#999999"
        scrollbar_style = f"""
            QScrollBar:vertical {{
                background-color: transparent;
                width: 8px;
                margin: 0px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {handle_color};
                min-height: 30px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{ background-color: {handle_hover}; }}
            QScrollBar::handle:vertical:pressed {{ background-color: {handle_pressed}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px; background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """
        if self.scroll_area is not None:
            self.scroll_area.setStyleSheet(scrollbar_style)

        # 已经建出来的板块页跟着换色
        for info in getattr(self, "_sections", {}).values():
            page = info.get("page")
            if page is not None:
                page.apply_theme(is_dark)

        # 左侧两个列表：底色/文字/选中态全部来自 token
        # ⚠️ 选中项的文字用主文字色、不用强调色（需求："我要和之前一样的配色而不是现在的全蓝"）
        c = tokens(is_dark)
        list_qss = f"""
            ListWidget#settingsSectionList, ListWidget#settingsSearchResults {{
                background: transparent; border: none; outline: none;
                font-size: 14px;
            }}
            ListWidget#settingsSectionList::item,
            ListWidget#settingsSearchResults::item {{
                height: 38px; border-radius: 8px; padding-left: 10px;
                color: {c['text']};
            }}
            ListWidget#settingsSectionList::item:hover,
            ListWidget#settingsSearchResults::item:hover {{
                background: {c['hover']};
            }}
            ListWidget#settingsSectionList::item:selected,
            ListWidget#settingsSearchResults::item:selected {{
                background: {c['accent_soft']}; color: {c['text']};
            }}
        """
        from qfluentwidgets import setCustomStyleSheet
        for widget in (getattr(self, "section_list", None),
                       getattr(self, "search_results", None)):
            if widget is not None:
                setCustomStyleSheet(widget, list_qss, list_qss)
        if hasattr(self, "sidebar_title"):
            self.sidebar_title.setStyleSheet(
                f"color: {tokens(is_dark)['text']}; background: transparent;")


    def get_text(self, key):
        """获取文案：先查语言文件，查不到用兜底表（兜底表是模块级常量，不再每次重建）"""
        if self.lang:
            result = self.lang.get_text("settings", key)
            if result != key:
                return result
        return FALLBACK_TEXTS.get(key, key)


    def apply_theme_colors(self, theme_name):
        self.current_theme = theme_name
        self.refresh_theme_styles()


    def change_theme(self, index):
        theme_map = {0: "跟随系统", 1: "浅色主题", 2: "深色主题"}
        theme_name = theme_map.get(index, "跟随系统")
        self.settings_manager.update_setting("theme", theme_name)
        self.current_theme = theme_name

        self.refresh_theme_styles()

        if theme_name == "跟随系统":
            actual_theme = detect_system_theme()
            msg_suffix = f" ({actual_theme})"
        else:
            actual_theme = theme_name
            msg_suffix = ""

        from qfluentwidgets import setTheme, Theme
        from ...utils.theme_utils import apply_app_palette
        # ⚠️ lazy=True 是这里的关键：不加的话 setTheme 会把全程序每个注册控件的样式表都重刷一遍
        # （实测 ~550ms），加上 apply_accent_color 那一次（~520ms）就占了一秒多；
        # lazy 只立刻重刷当前可见的控件，藏着的等被画出来时由库自己补刷（外观完全一样）
        if actual_theme == "浅色主题":
            setTheme(Theme.LIGHT, lazy=True)
        else:
            setTheme(Theme.DARK, lazy=True)
        # 调色板也要跟着切，否则滚动区域视口之类的原生控件在深色下会变白
        apply_app_palette(actual_theme != "浅色主题")
        # ⚠️ 强调色也要跟着主题换（浅色 #4F7BF7 / 深色 #6E93FF）：这一句把 qfluentwidgets 默认的
        # 青色强调色（SwitchButton 打开态、ComboBox 选中项、Slider、CheckBox 都是它）换成品牌蓝
        apply_accent_color(actual_theme != "浅色主题")

        self.show_message(f"{self.get_text('theme_changed')}: {self.theme_combo.currentText()}{msg_suffix}", "success")

        if self.main_window:
            # ⚠️ 交给主窗口统一处理：它只立刻刷新当前可见的那一页，其余页记成"主题脏"，
            # 等用户真切过去时再刷（原来把每一页都同步刷了一遍，全是在用户看不见的地方白干）
            refresh_all = getattr(self.main_window, "refresh_all_pages_theme", None)
            if callable(refresh_all):
                refresh_all()
            else:
                # 兜底：没有这个方法（老版本主窗口）时按老办法逐页刷
                self.main_window.githubInterface.refresh_theme()
                for name in ("logInterface", "feedbackInterface", "searchInterface",
                             "pluginInterface", "resourceMakerInterface"):
                    page = getattr(self.main_window, name, None)
                    if page is not None and hasattr(page, "refresh_theme"):
                        page.refresh_theme()
                if hasattr(self.main_window, 'ai_chat_drawer'):
                    self.main_window.ai_chat_drawer.apply_theme()
                if hasattr(self.main_window, 'ai_floating_button'):
                    self.main_window.ai_floating_button.refresh_theme()


    def change_language(self, index):
        language_name = self.get_language_options()[index]

        lang_display_map = {
            self.get_text("follow_system"): "跟随系统",
            "简体中文": "简体中文",
            "繁體中文": "繁體中文",
            "English": "English"
        }
        actual_lang = lang_display_map.get(language_name, "跟随系统")

        display_lang = actual_lang
        if actual_lang == "跟随系统":
            display_lang = detect_system_language()

        self.settings_manager.update_setting("language", actual_lang)
        self.settings_manager.update_setting("open_settings_on_restart", True)

        box = MessageBox(
            self.get_text("restart_required"),
            f"{'Language switched to ' + display_lang if display_lang == 'English' else '语言已切换为 ' + display_lang}\n\n程序将自动重启以应用更改...",
            self
        )
        box.yesButton.setText(self.get_text("restart_now"))
        box.cancelButton.setText(self.get_text("restart_later"))

        if box.exec():
            restart_program(open_settings=True)


    def show_message(self, message, msg_type="info"):
        """显示消息提示"""
        kwargs = {
            'orient': Qt.Horizontal,
            'isClosable': True,
            'position': InfoBarPosition.TOP,
            'duration': 2000 if msg_type != "info" else 1500,
            'parent': self
        }
        titles = {
            "success": self.get_text("success"),
            "error": self.get_text("error"),
            "warning": self.get_text("warning"),
            "info": self.get_text("info")
        }
        if msg_type == "success":
            InfoBar.success(title=titles["success"], content=message, **kwargs)
        elif msg_type == "error":
            InfoBar.error(title=titles["error"], content=message, **kwargs)
        elif msg_type == "warning":
            InfoBar.warning(title=titles["warning"], content=message, **kwargs)
        else:
            InfoBar.info(title=titles["info"], content=message, **kwargs)
