"""
搜索界面
"""

from datetime import datetime

from PyQt5.QtCore import (Qt, QSize, QTimer, QPoint, QPropertyAnimation,
                          QEasingCurve, pyqtSignal)
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
                             QScrollArea, QFrame, QSizePolicy)
from PyQt5.QtGui import QIcon, QTransform
from qfluentwidgets import (SearchLineEdit, PushButton, PrimaryPushButton, ComboBox, CaptionLabel,
                            BodyLabel, FluentIcon as FIF, SegmentedToolWidget, isDarkTheme)
from ..core.language_manager import LanguageManager
from ..core.settings_manager import SettingsManager
from ..core.cloud_resource_source import resolve_resource_file
from ..core.resource_loader import ResourceLoader
from ..core import resource_schema
from ..core.favorites_manager import display_folder_name
from ..utils.smooth_scroll import install_smooth_scroll
from ..widgets import AppsIndexFramework, FilterPanel, SelectionBar
from .resource_detail_interface import ResourceDetailInterface


def _parse_listed_at(value):
    """把「上架时间」字符串解析成 datetime（认不出来就返回 None）

    制作器写的是 "2026-09-21 00:40:14"；也兼容带 T 的 ISO 写法。
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


def tag_filter_options(items) -> list:
    """「标签」筛选行的选项：类别 ∪ 标签（去重后按名字排序）。

    ⚠️ 必须取并集：tags 里去掉了与类别重复的值，只取 tags 会凭空少掉「工具 / 游戏 / AI」这些最常见筛选项。
    """
    values = set()
    for item in items or []:
        for value in resource_schema.keywords_of(item):
            values.add(str(value))
    return sorted(values)


class SearchInterface(QWidget):
    """搜索页面（包含列表页和详情页）"""

    # 首屏内容渲染完成（转发自 AppsIndexFramework，供启动流程判断）
    ready = pyqtSignal()
    # 收藏状态发生变化（通知收藏页刷新）
    favorites_changed = pyqtSignal()
    # 勾选模式下确认要加入部署清单的编码列表
    apps_selected = pyqtSignal(list)
    # 卡片上的「@给AI」被点击（名称, 编码）—— 转发给主窗口，由它交给 AI 抽屉
    ai_mention_requested = pyqtSignal(str, str)

    def __init__(self, settings_manager: SettingsManager,
                 language_manager: LanguageManager = None,
                 favorites_manager=None):
        super().__init__()
        self.setObjectName("searchInterface")
        self.settings_manager = settings_manager
        self.lang = language_manager
        self.favorites = favorites_manager

        self._filter_expanded = False
        self._slide_anim = None
        # 换「组件配色」时如果这一页不可见，就先记个标记，等显示出来再重染图标
        self._accent_dirty = False
        # 滚动期间的"让路"：让 AI 悬浮球别在滚动帧里重算液面（见 _on_scroll_activity）
        self._ball_scroll_hook = False
        # 「更新时间 → 最新」筛出来的编码集合（按上架时间倒序取前 N 条）
        self._latest_codes = set()
        self._latest_n = 10

        # ⚠️ 视图模式和「显示 GitHub 按钮」必须在建卡片之前设好：卡片尺寸是 app_card 的模块级全局量
        from ..widgets import app_card as card_module
        card_module.apply_view_mode(
            self.settings_manager.settings.get("search_view", "tile"))
        card_module.apply_github_button_setting(
            self.settings_manager.settings.get("search_show_github", True))

        self._setup_pages()
        self._setup_search_page()
        self._setup_detail_page()

        # ⚠️ 启动时搜索框永远是空的（需求："删除搜索框记住上次关闭前输入框的内容"）；
        #    last_search 仍然会写，只是不再回填。
        self.search_box.clear()

        # 加载本地 JSON 索引并显示卡片
        self._load_resources()

        # 初始的「已搜索到 XXX 个相关内容」
        self._update_result_label(len(getattr(self, "_all_resources",
                                              self.apps_framework.items)))

        self.show_search_page()

    @property
    def is_ready(self) -> bool:
        """首屏内容是否已经渲染完成"""
        return self.apps_framework.is_ready

    def reload_resources(self, silent: bool = False):
        """按当前设置重新载入资源并重渲染（改卡片大小 / 换资源来源时用）。

        silent=True：不闪加载动画（数据没变、只是卡片尺寸变了时用）。
        """
        # 丢掉复用池：卡片尺寸可能变了，池里的网格记着旧尺寸
        if hasattr(self.apps_framework, "reset_pools"):
            self.apps_framework.reset_pools()
        self._load_resources(silent=silent)
        self.refresh_favorites()
        self._reload_filter_options()
        self._do_search()

    # ---------- 视图模式 / GitHub 按钮 ----------
    def _sync_view_segmented(self):
        """让工具栏上的视图切换按钮显示当前模式（回填时不触发信号）"""
        segmented = getattr(self, "view_segmented", None)
        if segmented is None:
            return
        from ..widgets import app_card as card_module
        try:
            segmented.blockSignals(True)
            segmented.setCurrentItem(card_module.view_mode())
        except Exception:
            pass
        finally:
            try:
                segmented.blockSignals(False)
            except Exception:
                pass

    def _on_view_segmented_changed(self, key: str):
        self.apply_view_mode(key)

    def apply_view_mode(self, key: str, persist: bool = True,
                        show_loading: bool = True):
        """切换磁贴 / 网格视图：重算卡片尺寸并重渲染（网格下卡片明显变小、只保留收藏按钮）。

        ⚠️ 这里要显示加载动画（silent=False）：重建 48 张卡片本身要一百多毫秒，转圈能让人知道"在干活"。
        设置页改「搜索页视图」也走这里，行为一致。
        """
        from ..widgets import app_card as card_module
        card_module.apply_view_mode(key)
        if persist and self.settings_manager:
            self.settings_manager.update_setting("search_view", card_module.view_mode())
        self._sync_view_segmented()
        if show_loading and hasattr(self.apps_framework, "show_loading_then"):
            # 先亮出中央那个加载动画（和切排序同一套），下一拍再做整页重建。
            # ⚠️ 不能只靠 reload_resources(silent=False)：它末尾的 _do_search() 会立刻把加载控件收掉
            self.apps_framework.show_loading_then(
                lambda: self.reload_resources(silent=True))
        else:
            self.reload_resources(silent=True)

    def apply_github_button_setting(self):
        """设置里改了「显示 GitHub 按钮」：重新渲染一次卡片"""
        from ..widgets import app_card as card_module
        card_module.apply_github_button_setting(
            bool(self.settings_manager.settings.get("search_show_github", True)))
        self.reload_resources(silent=True)

    def apply_view_switch_setting(self):
        """设置里改了「在搜索页显示视图切换按钮」：工具栏那个磁贴/网格按钮显示或隐藏。

        只藏这一个控件：工具栏是"弹簧 + 排序 + 视图"，视图一藏，弹簧自然把排序那一组顶到最右边。
        「搜索页视图」下拉框走 apply_view_mode，和这个开关无关，照旧能用。
        """
        show = bool(self.settings_manager.settings.get(
            "search_show_view_switch", True)) if self.settings_manager else True
        widget = getattr(self, "view_segmented", None)
        if widget is not None:
            widget.setVisible(show)

    def _resource_file(self) -> str:
        """当前该读哪个资源索引文件（云端缓存 or 用户指定的本地文件）"""
        try:
            return resolve_resource_file(self.settings_manager)
        except Exception:
            return ""

    def _load_resources(self, silent: bool = False):
        """从 ToolsGCP-Resources.json 加载资源（只载入轻量摘要数据）"""
        language = getattr(self.lang, "current_language", "简体中文") if self.lang else "简体中文"
        self._loader = ResourceLoader(self._resource_file() or None, language)
        if self._loader.load_from_local():
            # ⚠️ 先预热图标目录，再渲染卡片：预热让"卡片一绑上就有图"（命中缓存 0ms），
            #    需求要的就是"看到卡片 UI 的同时图标就已经在了"，不再等 1~2 秒。
            #    预热本身是分帧的（见 app_card.prewarm_icons_async），不会挡住这一屏。
            self._prewarm_icons()
            # 只传入卡片显示所需的轻量数据，排序键与数据一次性给出，只渲染一次
            summaries = self._loader.get_summaries()
            self.apps_framework.set_data(summaries, sort_key="category",
                                         show_loading=not silent)
            # 换了数据源就要同步刷新筛选/排序用的那份列表，否则它们会一直作用在旧数据上
            self._all_resources = list(summaries)
            self._refresh_latest_codes()
            self.refresh_favorites()
            self._reload_filter_options()

    def _prewarm_icons(self):
        """把资源库图标目录里的图提前解码进缓存（启动后一次；换图标目录会重来一次）"""
        try:
            from ..widgets import app_card as card_module
            icon_dir = getattr(self._loader, "icon_dir", "") if self._loader else ""
            if icon_dir:
                card_module.prewarm_icons_async(
                    icon_dir, size=card_module.ICON_PREWARM_SIZE)
        except Exception:
            pass

    # ---------- 收藏 ----------
    def folder_display_name(self, name: str) -> str:
        """收藏夹的显示名（默认收藏夹按当前语言翻译）"""
        language = getattr(self.lang, "current_language", "简体中文") if self.lang else "简体中文"
        return display_folder_name(name, language)

    def refresh_favorites(self):
        """把收藏状态同步到所有卡片上的收藏图标"""
        if self.favorites is None:
            return
        codes = self.favorites.all_codes()
        self.apps_framework.set_favorites(codes)
        if hasattr(self, "detail_page"):
            self.detail_page.set_favorite(self.detail_page.current_code() in codes)

    def _on_favorite_toggled(self, code: str):
        if self.favorites is None or not code:
            return
        state = self.favorites.toggle(code)
        self.refresh_favorites()
        self.favorites_changed.emit()

        name = code
        if hasattr(self, "_loader") and self._loader:
            resource = self._loader.get_by_code(code)
            if resource:
                name = resource.get("name", code)
        from ..utils.logger import log
        log.op("收藏", "toggle", code=code, name=name,
               state="已收藏" if state else "取消收藏")

    def _setup_pages(self):
        """初始化页面堆叠容器"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.stacked = QStackedWidget(self)
        outer.addWidget(self.stacked)

        self.search_page = QWidget(self.stacked)
        self.detail_page = ResourceDetailInterface(self.stacked, language_manager=self.lang)
        self.detail_page.back_requested.connect(self.show_search_page)
        self.detail_page.favorite_toggled.connect(self._on_favorite_toggled)

        self.stacked.addWidget(self.search_page)
        self.stacked.addWidget(self.detail_page)

    def _setup_search_page(self):
        """构建搜索主页面"""
        outer_layout = QVBoxLayout(self.search_page)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.scroll_area = QScrollArea(self.search_page)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        scroll_content = QWidget()
        scroll_content.setObjectName("searchScrollContent")
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(24, 30, 24, 30)
        layout.setSpacing(20)

        self.search_box = SearchLineEdit(scroll_content)
        placeholder = self.get_text("search_placeholder")
        self.search_box.setPlaceholderText(placeholder)
        # ⚠️ 需求：搜索页也要能"跟着窗口拉伸自适应" —— 老代码是 setFixedWidth(500)，
        #    窗口从 1280 拉到 2560 它都死死 500 宽（右边空一大块、缩放时还不跟着变）。
        #    改成"弹性"：给一个合理的上下限，剩下的交给布局按可用宽度伸缩。
        self.search_box.setMinimumWidth(320)
        self.search_box.setMaximumWidth(720)
        self.search_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # ⚠️ 需求：框选 @ 时每个 @ 必须是整体（框选一小部分就整体选中）。
        #    QLineEdit 是纯文本控件、没有原子片段，等价做法是让光标永远不能停在 @ 片段内部。
        self._mention_cursor_guard = False
        # ⚠️ 光标吸附和"选区扩展"会互相触发，共用一个标志会自己把自己挡住，所以两个守卫分开
        self._mention_select_guard = False
        self.search_box.cursorPositionChanged.connect(self._snap_cursor_out_of_mention)
        # 框选到 @ 的一部分 → 自动扩成整个 @（需求见 _expand_selection_to_mentions）
        self.search_box.selectionChanged.connect(self._expand_selection_to_mentions)
        search_container = QHBoxLayout()
        search_container.addStretch()
        search_container.addWidget(self.search_box)
        search_container.addStretch()
        layout.addLayout(search_container)

        # 工具栏：左侧 更多筛选 + 结果条数，右侧 排序
        # ⚠️ 需求：最右侧那颗图标用 CHEVRON_DOWN_MED（朝下），展开时顺时针转 180°、收起时
        #    逆时针转回来；"更多筛选"这四个字不变，且**图标大小 / 文字 / 图标与文字的间距**
        #    都要正常。这几件事都由 _build_more_filter_button() 统一处理。
        self.more_filter_btn = PushButton(self.get_text("more_filters"), scroll_content)
        self.more_filter_btn.setMinimumWidth(120)
        # 可勾选：面板展开时按钮保持按下态，反馈更明显（用的是 Fluent 自己的选中配色）
        self.more_filter_btn.setCheckable(True)
        self.more_filter_btn.setFixedHeight(34)
        self.more_filter_btn.clicked.connect(self._toggle_filter_icon)
        self._setup_more_filter_icon()
        # 图标按当前状态先摆好（收起态 = 朝下）
        self._update_filter_icon()

        # 结果条数：灰色小字，紧跟在按钮右边
        self.result_label = CaptionLabel("", scroll_content)
        self.result_label.setStyleSheet("color: #8A8A8A;")

        self.sort_combo = ComboBox(scroll_content)
        self.sort_combo.setMinimumWidth(160)
        # 顺序：全部 / 类别 / A-Z / Z-A
        sort_items = [
            ("all", self.get_text("sort_all")),
            ("category", self.get_text("sort_category")),
            ("az", self.get_text("sort_az")),
            ("za", self.get_text("sort_za")),
        ]
        for key, label in sort_items:
            self.sort_combo.addItem(label, userData=key)
        self.sort_combo.setCurrentIndex(1)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        toolbar.addWidget(self.more_filter_btn)
        toolbar.addWidget(self.result_label)
        toolbar.addStretch()

        # 视图切换：磁贴（一行 4 个大卡片）/ 网格（一行 6 个小卡片），和插件页的排版切换同一套控件
        self.view_segmented = SegmentedToolWidget(scroll_content)
        self.view_segmented.addItem("tile", FIF.TILES)
        self.view_segmented.addItem("grid", FIF.VIEW)
        for _key, _tip in (("tile", self.get_text("view_tile_tip")),
                           ("grid", self.get_text("view_grid_tip"))):
            try:
                self.view_segmented.items[_key].setToolTip(_tip)
            except Exception:
                pass
        self.view_segmented.setFixedSize(68, 30)
        self.view_segmented.currentItemChanged.connect(self._on_view_segmented_changed)
        self._sync_view_segmented()

        sort_label = BodyLabel(self.get_text("sort_label") + "：", scroll_content)
        toolbar.addWidget(sort_label)
        toolbar.addWidget(self.sort_combo)
        toolbar.addWidget(self.view_segmented)
        layout.addLayout(toolbar)

        # ---- 更多筛选面板（参考 B 站：一行一组，默认收起）----
        self.filter_panel = FilterPanel(scroll_content)
        self.filter_panel.set_title(self.get_text("filter_hint"))

        # 类别：顺序和分组显示保持一致
        # ⚠️ (值, 显示名) 分开给：值永远是资源库里的规范中文（筛选按它匹配），显示名按当前语言翻译
        category_options = [("", self.get_text("filter_all"))]
        for name in self._category_order():
            category_options.append((name, self._term(name)))
        self.filter_panel.add_row("category", self.get_text("filter_category"),
                                  category_options)

        self.filter_panel.add_row("tag", self.get_text("filter_tag"), [])

        self.filter_panel.add_row(
            "source", self.get_text("filter_source"),
            [("", self.get_text("filter_all")),
             ("site", self.get_text("source_site")),
             ("repo", self.get_text("source_repo")),
             ("download", self.get_text("source_download"))])

        self.filter_panel.add_row(
            "favorite", self.get_text("filter_favorite"),
            [("", self.get_text("filter_all")),
             ("only", self.get_text("favorite_only"))])

        # 更新时间：按资源的「上架时间」（listed_at）筛：全部 / 最新 / 10 天前 / 30 天前 / 半年前
        self.filter_panel.add_row(
            "updated", self.get_text("filter_updated"),
            [("", self.get_text("filter_all")),
             ("latest", self.get_text("updated_latest")),
             ("10d", self.get_text("updated_10d")),
             ("30d", self.get_text("updated_30d")),
             ("180d", self.get_text("updated_180d"))])

        # 适用系统：选项直接取自制作器的常量（唯一真源，别再手抄一份列表）
        # ⚠️ "web" 必须留着（制作器现在也能填 web），写死列表还会漏项 —— "macOS" 就漏抄过
        from .resource_maker_core import ARCHITECTURES, SYSTEM_PLATFORMS
        self.filter_panel.add_row(
            "system", self.get_text("filter_system"),
            [("", self.get_text("filter_all"))]
            + [(name, self._term(name)) for name in SYSTEM_PLATFORMS])

        # CPU 架构：选完系统之后一般还要挑一个（x64 / x86 / arm64 …）
        self.filter_panel.add_row(
            "arch", self.get_text("filter_arch"),
            [("", self.get_text("filter_all"))]
            + [(name, self._term(name)) for name in ARCHITECTURES])

        self.filter_panel.changed.connect(self._on_filter_changed)
        self.filter_panel.hide()
        layout.addWidget(self.filter_panel)

        # 勾选条（部署页"从搜索页选择"、收藏夹批量操作时才会出现）
        self.selection_bar = SelectionBar(scroll_content, self.get_text("select_all"))
        self.selection_bar.hide()
        self.selection_bar.toggled.connect(self._on_select_all_toggled)

        self.selection_fav_label = BodyLabel(self.get_text("from_folder"), scroll_content)
        self.selection_fav_label.hide()
        self.selection_fav_combo = ComboBox(scroll_content)
        self.selection_fav_combo.setFixedWidth(160)
        self.selection_fav_combo.hide()
        self.selection_fav_combo.currentIndexChanged.connect(self._on_favorites_folder_changed)
        # 插入顺序：后插的排在前面（见 SelectionBar.add_leading）
        self.selection_bar.add_leading(self.selection_fav_combo)
        self.selection_bar.add_leading(self.selection_fav_label)

        self.selection_cancel_btn = PushButton(self.get_text("cancel"), scroll_content)
        self.selection_cancel_btn.clicked.connect(self.end_selection)
        self.selection_bar.add_action(self.selection_cancel_btn)

        self.selection_confirm_btn = PrimaryPushButton(
            self.get_text("add_to_deploy"), scroll_content)
        self.selection_confirm_btn.clicked.connect(self._on_selection_confirmed)
        self.selection_bar.add_action(self.selection_confirm_btn)

        layout.addWidget(self.selection_bar)

        self.apps_framework = AppsIndexFramework(scroll_content)
        self.apps_framework.set_empty_text(self.get_text("empty_state"))
        # 告诉框架"可视区域是谁"：它据此只给屏幕上那几张卡片加载图标
        self.apps_framework.set_viewport(self.scroll_area)
        self.apps_framework.card_clicked.connect(self._on_card_clicked)
        self.apps_framework.favorite_toggled.connect(self._on_favorite_toggled)
        self.apps_framework.ai_mention_requested.connect(
            self.ai_mention_requested.emit)
        self.apps_framework.selection_toggled.connect(self._on_card_selection_changed)
        self.apps_framework.ready.connect(self.ready.emit)
        layout.addWidget(self.apps_framework, 1)

        self.scroll_area.setWidget(scroll_content)
        outer_layout.addWidget(self.scroll_area)

        # ---- 滚动：到底部附近补下一批卡片，停下来之后补图标；用 60ms 防抖（滚动中每动一像素都干活反而更卡）----
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(60)
        self._scroll_timer.timeout.connect(self._on_scroll_idle)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scrolled)

        self._apply_scrollbar_style()
        self._apply_search_box_style()
        install_smooth_scroll(self.scroll_area)

        # 滚动条 / 文字颜色的样式表已按深浅主题各应用过一次；记下当前主题，
        # 避免主题没变时重复 setStyleSheet（整棵子树重新 polish，一次 80ms 以上）
        self._scrollbar_style_dark = isDarkTheme()
        self._search_box_style_dark = isDarkTheme()

        # 搜索：自动搜索时防抖 300ms，非自动搜索时需按 Enter 或点击搜索按钮
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)
        self.search_box.textChanged.connect(self._on_search_text_changed)
        self.search_box.returnPressed.connect(self._do_search)
        self.search_box.searchSignal.connect(self._do_search)

        # 「在搜索页显示视图切换按钮」的设置（默认开）：启动时就要对上
        self.apply_view_switch_setting()

    def _is_auto_search(self) -> bool:
        """读取设置中的自动搜索开关（默认开启）"""
        if self.settings_manager:
            return self.settings_manager.settings.get("auto_search", True)
        return True

    # ---------- 搜索框里的 @ 片段（整体不可切开） ----------
    # @ 片段字符集：@ 后面跟字母/数字/下划线/横杠/点，到空格或标点为止（有固定字符集才知道片段在哪结束）
    MENTION_STOP_CHARS = set(" \t\u3000,，.。;；:：!！?？()（）[]【】<>《》\"'“”‘’、/\\|+=*&^%$#`~")

    def _mention_spans(self) -> list:
        """列出搜索框里所有 @ 片段的 (起, 止) 下标（止不含）"""
        text = self.search_box.text()
        spans = []
        i = 0
        while i < len(text):
            if text[i] == "@":
                j = i + 1
                while j < len(text) and text[j] not in self.MENTION_STOP_CHARS:
                    j += 1
                spans.append((i, j))
                i = j
            else:
                i += 1
        return spans

    def _snap_cursor_out_of_mention(self):
        """光标落在 @ 片段内部时吸附到最近的边界，保证框选结果永远是整个 @ 片段。"""
        if self._mention_cursor_guard:
            return
        spans = self._mention_spans()
        if not spans:
            return
        pos = self.search_box.cursorPosition()
        for start, end in spans:
            # 严格在内部才算"切开了"，正好在边界上（start/end）是允许的
            if start < pos < end:
                prev = getattr(self, "_last_mention_cursor", pos)
                # 往左走就吸附到片段开头，往右走吸附到片段结尾
                target = start if pos < prev else end
                self._mention_cursor_guard = True
                try:
                    self.search_box.setCursorPosition(target)
                finally:
                    self._mention_cursor_guard = False
                return
        self._last_mention_cursor = pos

    def _expand_selection_to_mentions(self):
        """框选到 @ 片段的任意一部分时，自动把整个 @ 片段都框上。

        ⚠️ 只做"光标吸附"不够：QLineEdit 没有原子片段概念，拖出半截 @ 再按删除会剩下 "@LocalS"；
        这里在选区碰到片段一部分时就把选区扩成完整的 @ 片段（跨多个片段扩到最外边界）。
        """
        if self._mention_select_guard:
            return
        try:
            if not self.search_box.hasSelectedText():
                return
            start = self.search_box.selectionStart()
            end = start + len(self.search_box.selectedText())
        except Exception:
            return

        new_start, new_end = start, end
        changed = False
        for span_start, span_end in self._mention_spans():
            if span_start < new_end and new_start < span_end:      # 有交集
                if span_start < new_start:
                    new_start = span_start
                    changed = True
                if span_end > new_end:
                    new_end = span_end
                    changed = True
        if not changed:
            return
        self._mention_select_guard = True
        try:
            self.search_box.setSelection(new_start, new_end - new_start)
        finally:
            self._mention_select_guard = False

    def _set_mention_cursor(self, pos: int):
        self._last_mention_cursor = int(pos)

    # ---------- 滚动：虚拟化窗口 + 补图标 ----------
    def _scroll_origin(self) -> int:
        """框架自己在滚动内容里的 y（搜索框 + 工具栏都在它上面）。

        ⚠️ 滚动条的 value 是"整页"坐标，框架算窗口用的是"自己"坐标，不传这个偏移滚到底会整页空白。
        """
        try:
            return int(self.apps_framework.y())
        except Exception:
            return 0

    def _sync_scroll_offset(self, value: int = None):
        """把滚动位置（整页坐标 + 框架自己的 y）同步给框架"""
        framework = getattr(self, "apps_framework", None)
        if framework is None:
            return
        if value is None:
            value = self.scroll_area.verticalScrollBar().value()
        framework.set_scroll_offset(value, self._scroll_origin())

    def _on_scrolled(self, value: int):
        """滚动位置一变就告诉框架"现在滚到哪了"。

        ⚠️ 框架内部会先判断"窗口变了没有"（行粒度），没变就原地返回，所以每像素都调也几乎不花时间。
        加载动画那会儿（还没渲染完）偏移量也要记下来，渲染时会用到，所以不做"有没有卡片"之类的过滤。

        滚动期间挂起图标加载（读盘/解码插在滚动帧里实测能把最差帧顶到 56ms）；
        _scroll_timer 用真正的尾随防抖（每次都 start 重启）—— 前沿防抖会让图标偏偏在滚动中加载。
        """
        self._sync_scroll_offset(value)
        framework = getattr(self, "apps_framework", None)
        if framework is not None:
            framework.set_scrolling(True)
        self._scroll_timer.start()

    def _on_scroll_idle(self):
        """滚动停下来了：解除"正在滚"、给刚进视口的卡片补图标。"""
        framework = getattr(self, "apps_framework", None)
        if framework is None:
            return
        framework.set_scrolling(False)
        framework.request_visible_icons()
        self._maybe_load_more()

    def _maybe_load_more(self):
        """（已被虚拟化取代）旧的分批补卡片逻辑；保留只是为了让外部结构不变（has_more() 恒为 False）。"""
        framework = getattr(self, "apps_framework", None)
        if framework is None or not framework.has_more():
            return
        bar = self.scroll_area.verticalScrollBar()
        if bar.maximum() <= 0:
            return
        margin = max(400, self.scroll_area.viewport().height())
        if bar.value() >= bar.maximum() - margin:
            framework.load_more()

    def hideEvent(self, event):
        """离开搜索页：停掉滚动防抖，并解除"正在滚"标记"""
        super().hideEvent(event)
        try:
            self._scroll_timer.stop()
        except Exception:
            pass
        framework = getattr(self, "apps_framework", None)
        if framework is not None:
            # 必须解除"正在滚"：不然这个标记会一直挂着，回来之后图标再也不加载
            try:
                framework.set_scrolling(False)
            except Exception:
                pass

    def mark_accent_dirty(self):
        """换"组件配色"时调用：先记一笔，等这一页真的被显示出来再重染。

        ⚠️ 卡片上按强调色染的图标有 48 张，当场全部重染要 400~600ms，而换配色时用户在设置页。
        """
        self._accent_dirty = True

    def showEvent(self, event):
        """回到搜索页：把当前的滚动偏移交给框架（图标不卸载，无需重新加载）"""
        super().showEvent(event)
        framework = getattr(self, "apps_framework", None)
        if framework is not None:
            # 回到这一页：先确认"正在滚"是解除状态（见 hideEvent 里的说明）
            try:
                framework.set_scrolling(False)
            except Exception:
                pass
            offset = self.scroll_area.verticalScrollBar().value()
            framework.set_scroll_offset(offset)
        if getattr(self, "_accent_dirty", False):
            self._accent_dirty = False
            QTimer.singleShot(0, lambda: self.refresh_theme(force=True))
        self._install_scroll_ball_hook()

    # ---------- 滚动时让悬浮球"让路" ----------
    def _install_scroll_ball_hook(self):
        """把滚动条的变化接到 AI 悬浮球的"暂停一会儿"上（只接一次）。

        ⚠️ 悬浮球每约 50ms 重算一次 64×64 的 metaball 液面（单帧 3~4ms），正好插在滚动帧里，
        就是那种"偶尔顿一下"的来源；滚动期间球在视野边缘，冻结 200ms 看不出来。
        """
        if getattr(self, "_ball_scroll_hook", False):
            return
        try:
            bar = self.scroll_area.verticalScrollBar()
        except Exception:
            return
        self._ball_scroll_hook = True
        bar.valueChanged.connect(lambda _v: self._pause_ball_for_scroll())

    def _pause_ball_for_scroll(self):
        ball = getattr(self.window(), "ai_floating_button", None)
        if ball is not None and hasattr(ball, "pause_for"):
            ball.pause_for(200)

    def _on_search_text_changed(self, text: str):
        """自动搜索时启动防抖定时器；非自动搜索时不触发"""
        if self._is_auto_search():
            self._search_timer.start(300)

    def _setup_detail_page(self):
        """详情页已在 _setup_pages 中初始化，无需额外操作"""
        pass

    def show_search_page(self):
        self.stacked.setCurrentWidget(self.search_page)

    # ---------- 勾选模式 ----------
    def begin_selection(self, purpose: str = "deploy", allow_favorites: bool = False):
        """进入勾选模式；purpose 目前只有 "deploy"，allow_favorites 决定是否显示「从收藏夹导入」下拉。"""
        self._selection_purpose = purpose
        self.apps_framework.set_selection_mode(True)
        self._update_result_label(len(self._all_resources))

        self.show_search_page()

        if allow_favorites and self.favorites is not None:
            self.selection_fav_combo.blockSignals(True)
            self.selection_fav_combo.clear()
            self.selection_fav_combo.addItem(self.get_text("choose_folder"))
            for name in self.favorites.folders():
                self.selection_fav_combo.addItem(
                    f"{self.folder_display_name(name)} ({self.favorites.count(name)})",
                    userData=name)
            self.selection_fav_combo.setCurrentIndex(0)
            self.selection_fav_combo.blockSignals(False)
            self.selection_fav_label.setVisible(True)
            self.selection_fav_combo.setVisible(True)
        else:
            self.selection_fav_label.setVisible(False)
            self.selection_fav_combo.setVisible(False)

        self.selection_confirm_btn.setText(self.get_text("add_to_deploy"))
        self.selection_bar.setVisible(True)
        self._update_selection_bar()

    def end_selection(self):
        """退出勾选模式"""
        self.apps_framework.set_selection_mode(False)
        self.selection_bar.setVisible(False)
        self.selection_fav_label.setVisible(False)
        self.selection_fav_combo.setVisible(False)

    def is_selecting(self) -> bool:
        return self.apps_framework.is_selection_mode()

    def _update_selection_bar(self):
        self.selection_bar.set_counts(*self.apps_framework.selection_counts())

    def _on_select_all_toggled(self, checked: bool):
        self.selection_bar.blockSignals(True)
        if checked:
            self.apps_framework.select_all()
        else:
            self.apps_framework.clear_selection()
        self.selection_bar.blockSignals(False)
        self._update_selection_bar()

    def _on_card_selection_changed(self, _code: str, _selected: bool):
        self._update_selection_bar()

    def _on_favorites_folder_changed(self, index: int):
        """选了某个收藏夹 → 直接把它里面的程序全部勾上"""
        if index <= 0:
            return
        name = self.selection_fav_combo.itemData(index)
        if not name or self.favorites is None:
            return
        codes = self.favorites.folder_items(name)
        self.apps_framework.set_selected(codes)
        self._update_selection_bar()
        self.show_message(f"{self.get_text('from_folder')}: {name} → {len(codes)}", "success")

    def _on_selection_confirmed(self):
        codes = self.apps_framework.selected_codes()
        if not codes:
            self.show_message(self.get_text("nothing_selected"), "warning")
            return
        purpose = getattr(self, "_selection_purpose", "deploy")
        self.end_selection()
        if purpose == "deploy":
            self.apps_selected.emit(codes)

    def show_search_page_hint(self, message: str):
        self.show_message(message, "warning")

    def show_message(self, message, msg_type="info"):
        from qfluentwidgets import InfoBar, InfoBarPosition
        # 标题走 common 模块，不再写死中文（见 plugin_interface.show_message 的说明）
        from ..core.language_manager import get_toast_title
        kwargs = dict(orient=Qt.Horizontal, isClosable=True,
                      position=InfoBarPosition.TOP, duration=2500, parent=self)
        if msg_type == "success":
            InfoBar.success(title=get_toast_title("success", self.lang),
                            content=message, **kwargs)
        elif msg_type == "error":
            InfoBar.error(title=get_toast_title("error", self.lang),
                          content=message, **kwargs)
        elif msg_type == "warning":
            InfoBar.warning(title=get_toast_title("warning", self.lang),
                            content=message, **kwargs)
        else:
            InfoBar.info(title=get_toast_title("info", self.lang),
                         content=message, **kwargs)

    def focus_search_box(self):
        """切回搜索页并把光标放进搜索框（托盘菜单/全局快捷键呼出时用）"""
        self._update_result_label(len(self._all_resources))

        self.show_search_page()
        self.search_box.setFocus(Qt.ShortcutFocusReason)
        self.search_box.selectAll()

    def show_detail_page(self, data: dict):
        self.detail_page.set_resource(data)
        if self.favorites is not None:
            self.detail_page.set_favorite(
                self.detail_page.current_code() in self.favorites.all_codes())
        self.stacked.setCurrentWidget(self.detail_page)
        self._play_slide_in()

    def _play_slide_in(self):
        """详情页从右往左滑入。

        动画期间我们直接 move 它；布局下一次被激活时会自己纠正回 (0, 0)，所以结束时要再摆正一次。
        """
        page = self.detail_page
        if page.width() <= 0:
            return
        if self._slide_anim is None:
            self._slide_anim = QPropertyAnimation(page, b"pos", self)
            self._slide_anim.setDuration(240)
            self._slide_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._slide_anim.stop()
        page.move(page.width(), 0)
        self._slide_anim.setStartValue(QPoint(page.width(), 0))
        self._slide_anim.setEndValue(QPoint(0, 0))
        self._slide_anim.start()

    def _on_card_clicked(self, data: dict):
        """点击卡片时按需从 loader 加载完整数据传给详情页"""
        rid = data.get("id")
        full_data = None
        if hasattr(self, "_loader") and self._loader:
            full_data = self._loader.get_by_id(rid)
        if full_data is None:
            full_data = data
        from ..utils.logger import log
        log.op("搜索", "open_card", code=full_data.get("code", ""),
               name=full_data.get("name", ""))
        self.show_detail_page(full_data)

    def refresh_theme(self, force: bool = False):
        """主题变化时由外部调用。

        ⚠️ 必须轻：真正需要"推一把"的只有滚动条、搜索框文字颜色和卡片上自绘的图标，绝不能重建卡片。
        force=True：设置里换"组件配色"时用（主题没变，但强调色变了）。
        """
        self._update_filter_icon()
        # ⚠️ 「更多筛选」的 padding 是**自己拼在 Fluent 整张样式表后面**的，覆盖之后就绕过了
        #    库的"主题变了自动重刷"。不在这里重拼的话，切深/浅主题后这颗按钮的底色和文字
        #    颜色会停在旧主题上（浅色主题下白底白字 = 看着像文字消失）。
        self._apply_more_filter_padding()
        self._apply_scrollbar_style(force=force)
        self._apply_search_box_style(force=force)
        if hasattr(self, "filter_panel"):
            # 筛选胶囊是自绘的（颜色按主题 / 强调色算），换主题或换"组件配色"都要让它重刷一次
            self.filter_panel.refresh_theme()
        if hasattr(self, "apps_framework"):
            self.apps_framework.refresh_theme(force=force)
        # 详情页的两个区块（应用介绍 / 详细信息）颜色是自己算的，不重刷的话切了主题还是旧配色
        if hasattr(self, "detail_page"):
            self.detail_page.refresh_theme(force=force)

    def _apply_scrollbar_style(self, force: bool = False):
        """应用滚动条样式（与设置页一致）。

        ⚠️ setStyleSheet 会让 Qt 把整个子树重新 polish（实测 80~150ms，滚动区下面挂着几百个卡片子控件）；
        样式只跟"深/浅"有关，所以同一个主题下重复调用直接跳过。
        """
        from qfluentwidgets import isDarkTheme
        is_dark = isDarkTheme()
        if not force and getattr(self, "_scrollbar_style_dark", None) == is_dark:
            return
        self._scrollbar_style_dark = is_dark
        scrollbar_bg = "transparent"
        handle_color = "#555555" if is_dark else "#CCCCCC"
        handle_hover = "#666666" if is_dark else "#AAAAAA"
        handle_pressed = "#777777" if is_dark else "#999999"

        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            QWidget#searchScrollContent {{
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background-color: {scrollbar_bg};
                width: 8px;
                margin: 0px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {handle_color};
                min-height: 30px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {handle_hover};
            }}
            QScrollBar::handle:vertical:pressed {{
                background-color: {handle_pressed};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)

    def _apply_search_box_style(self, force: bool = False):
        """修复搜索框和文本在深色主题下的文字颜色。

        ⚠️ 同样是"整棵子树重新 polish"的量级（又 80~150ms），而且是追加在滚动条样式后面的，
        重复调用会让样式表越来越长；主题没变就直接跳过。
        """
        from qfluentwidgets import isDarkTheme
        is_dark = isDarkTheme()
        if not force and getattr(self, "_search_box_style_dark", None) == is_dark:
            return
        self._search_box_style_dark = is_dark
        text_color = "#FFFFFF" if is_dark else "#1F2329"

        base = self.scroll_area.styleSheet()
        marker = "/* search-text */"
        if marker in base:
            base = base.split(marker)[0]
        self.scroll_area.setStyleSheet(
            base + marker + f"""
            SearchLineEdit, QLineEdit {{
                color: {text_color};
            }}
            BodyLabel {{
                color: {text_color};
            }}
        """
        )

    def _toggle_filter_icon(self):
        """展开 / 收起更多筛选面板（顺便让箭头转 180°）"""
        self._filter_expanded = not self._filter_expanded
        self.filter_panel.set_expanded(self._filter_expanded)
        self.more_filter_btn.setChecked(self._filter_expanded)
        # 展开：顺时针转 180°（箭头朝上）；收起：逆时针转回去
        self._animate_filter_icon(towards=self._filter_expanded)
        # 面板动画期间也让 AI 悬浮球让路（它每约 50ms 要 3~4ms 重算液面，正好叠在展开动画的帧上）
        try:
            ball = getattr(self.window(), "ai_floating_button", None)
            if ball is not None:
                ball.pause_for(260)
        except Exception:
            pass
        from ..utils.logger import log
        log.op("搜索", "filter_panel",
               state="展开" if self._filter_expanded else "收起")

    # 箭头动画：0° = 朝下（收起态），180° = 朝上（展开态）
    FILTER_ICON_ANGLES = (0, 180)
    # 「更多筛选」按钮上图标的大小（12 = 比工具栏文字小一档，需求："图标小一点"）
    FILTER_ICON_SIZE = 12
    # 图标与文字之间的间距
    FILTER_ICON_TEXT_GAP = 6

    def _setup_more_filter_icon(self):
        """给「更多筛选」按钮摆好"文字 + 图标在右"的版式（**只需做一次**）

        ⚠️ 老代码有四个问题叠在一起：
          1. `iconSize` 被砍到 5px（16//3）→ 图标只有几个像素，根本看不清；
          2. `setLayoutDirection(Qt.RightToLeft)` 想把图标放到右边，但 qfluentwidgets 的
             PushButton 只按 LTR 的 padding 算图标落点（左 36 / 右 12），RTL 只让 Qt 把
             文字换到右边 —— 结果图标落点算到 85..101，**和文字（52..108）叠在一起**；
          3. 于是"更多筛选"四个字被那颗小图标压住，看着就像文字消失了。

        这里改成：图标**留在右边**（用户要的"最右侧那个图标"），文字留在左边，两者之间
        用 padding 精确隔开 —— 见 _apply_more_filter_padding()。
        """
        button = self.more_filter_btn
        button.setIconSize(QSize(self.FILTER_ICON_SIZE, self.FILTER_ICON_SIZE))
        # 图标靠右：RightToLeft 让 Fluent 的图标落点公式算到右侧
        try:
            button.setLayoutDirection(Qt.RightToLeft)
        except Exception:
            pass
        self._apply_more_filter_padding()

    def _apply_more_filter_padding(self):
        """把「更多筛选」的 padding 调成"文字在左、图标在右"（左右各留出该留的位）

        ⚠️⚠️ 这里**必须带上 qfluentwidgets 原本那整张样式表**再追加自己那条：
            只写一条 `PushButton[hasIcon=true] { padding: … }` 的后果是 setStyleSheet()
            把库的样式整张**替换**掉（实测从 7631 字符掉到 56 字符）—— 按钮的底色、
            边框、文字颜色、按下/选中态全没了，深色主题下就是一块死灰的方块。
            所以先用 FluentStyleSheet.BUTTON.content(当前主题) 取回完整样式，再拼上
            自己那条 padding 规则。
        ⚠️ 覆盖了样式表就绕过了库的"主题变化自动重刷"，所以主题变了要重新拼一次
            （见 refresh_theme 里的 _apply_more_filter_padding(force=True)）。
        ⚠️ 同样不能每条都重设（setStyleSheet 会让控件重新 polish）——没变就跳过。
        """
        button = self.more_filter_btn
        # 左侧只留文字边距；右侧 = 边距 + 图标 + 间距（给图标留出完整的位置）
        left = 12
        right = 12 + self.FILTER_ICON_SIZE + self.FILTER_ICON_TEXT_GAP
        from qfluentwidgets import Theme, isDarkTheme
        from qfluentwidgets import FluentStyleSheet
        theme = Theme.DARK if isDarkTheme() else Theme.LIGHT
        key = (left, right, theme)
        if getattr(self, "_more_filter_padding_key", None) == key:
            return
        self._more_filter_padding_key = key
        try:
            base = FluentStyleSheet.BUTTON.content(theme)
        except Exception:
            base = ""
        try:
            button.setStyleSheet(
                base
                + "PushButton[hasIcon=true] {"
                  f"  padding: 5px {right}px 6px {left}px;"
                  "}"
            )
        except Exception:
            pass
        try:
            from PyQt5.QtWidgets import QApplication
            button.setStyle(QApplication.style())
        except Exception:
            pass

    def _animate_filter_icon(self, towards: bool):
        """把「更多筛选」的箭头转过去（0→180 的 QVariantAnimation 每帧生成旋转后的图标）。

        动画在角度值上跑，方向自然就对：展开 0→180（顺时针）、收起 180→0（逆时针）。
        图标只有 16px，每帧转一张的代价可以忽略（实测单帧 <0.05ms）。
        """
        start, end = self.FILTER_ICON_ANGLES
        if not towards:
            start, end = end, start
        anim = getattr(self, "_filter_icon_anim", None)
        if anim is None:
            from PyQt5.QtCore import QVariantAnimation
            anim = QVariantAnimation(self)
            anim.setDuration(180)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(self._on_filter_icon_angle)
            self._filter_icon_anim = anim
        anim.stop()
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        # 起点先画出来，避免第一帧还停在上一个角度
        self._on_filter_icon_angle(float(start))
        anim.start()

    def _on_filter_icon_angle(self, angle):
        """按角度取一颗旋转后的 CHEVRON_DOWN_MED（图标在左，和文字有间距）

        ⚠️ 角度必须取模到 0..360 再转：QVariantAnimation 从 0 到 180 没问题，但从
           180 回到 0 时每帧角度递减，transform 直接吃负角度会让旋转方向看起来
           反一下；统一取模后"顺时针 180 / 逆时针 180"都表现正确。
        """
        try:
            self.more_filter_btn.setIcon(
                self._rotated_icon(FIF.CHEVRON_DOWN_MED, float(angle) % 360.0))
        except Exception:
            pass

    def _update_filter_icon(self):
        """立刻把箭头摆到当前状态对应的角度（不做动画；切主题 / 初始化时用）"""
        angle = self.FILTER_ICON_ANGLES[1 if self._filter_expanded else 0]
        self._on_filter_icon_angle(float(angle))

    # ---------- 筛选 ----------
    @staticmethod
    def _category_order():
        return ["工具", "游戏", "平台", "编程", "游戏引擎",
                "视频平台", "建筑/设计", "AI", "个性化"]

    def _reload_filter_options(self):
        """资源库加载完后，把标签列表填进筛选面板。

        ⚠️ (值, 显示名) 分开：值是规范中文（筛选按它匹配），显示名按当前语言翻译。
        """
        options = [("", self.get_text("filter_all"))]
        options += [(t, self._term(t))
                    for t in tag_filter_options(self.apps_framework.items)]
        self.filter_panel.set_row_options("tag", options)

    def _term(self, value: str) -> str:
        """资源库术语（类别 / 标签 / 适用系统 / CPU 架构）的显示译名。

        只改显示：筛选匹配用的仍然是 `value` 本身。
        """
        from ..core.language_manager import translate_term
        return translate_term(value, self.lang)

    def _on_filter_changed(self):
        """筛选条件变了：先把"最新"那一档算出来，再刷新列表。

        ⚠️ 过滤 + update_data() 重建卡片是同步的（48 张一百多毫秒），期间界面完全不动、看着像卡住；
        所以先亮出中央那个加载动画，下一拍再真正过滤重排 —— 和切视图 / 切排序走的是同一套。
        """
        if hasattr(self.apps_framework, "show_loading_then"):
            self.apps_framework.show_loading_then(self._apply_filter_later)
        else:
            self._apply_filter_later()

    def _apply_filter_later(self):
        """真正的过滤动作（被 show_loading_then 调，或直接兜底调）"""
        self._refresh_latest_codes()
        self._apply_filters()

    def _passes_filters(self, item: dict, filters: dict) -> bool:
        """组内多选是「或」，组间是「与」"""
        categories = filters.get("category") or []
        # category 现在是列表（一条资源可以属于多个类别）：命中任意一个就算通过
        if categories and not set(resource_schema.categories_of(item)) & set(categories):
            return False

        tags = filters.get("tag") or []
        if tags:
            # 标签筛选看的是「类别 ∪ 标签」——和筛选行里列出来的选项同一套取值
            item_tags = [str(t) for t in resource_schema.keywords_of(item)]
            if not any(t in item_tags for t in tags):
                return False

        sources = filters.get("source") or []
        if sources:
            has_repo = bool(item.get("github"))
            has_download = bool(item.get("download_url")) or has_repo
            has_site = bool(item.get("url"))
            if not (("repo" in sources and has_repo)
                    or ("download" in sources and has_download)
                    or ("site" in sources and has_site)):
                return False

        if "only" in (filters.get("favorite") or []):
            if self.favorites is None or not self.favorites.is_favorite(item.get("code")):
                return False

        # 更新时间：按「上架时间」筛（listed_at）
        #   latest = 时间最新的前 10 条；10d / 30d / 180d = 最近 10 / 30 / 180 天内上架的
        updated = filters.get("updated") or []
        if updated:
            mode = updated[0]
            if mode == "latest":
                if self._latest_codes and str(item.get("code") or "") not in self._latest_codes:
                    return False
            else:
                days = {"10d": 10, "30d": 30, "180d": 180}.get(mode)
                if days is None:
                    return True
                stamp = _parse_listed_at(item.get("listed_at"))
                if stamp is None:
                    return False            # 没有上架时间的（老数据）不算"最近 N 天"
                if (datetime.now() - stamp).days > days:
                    return False

        # 适用系统 / CPU 架构：条目里存的是数组（systems / architectures），选了条件但这条没填时不算命中
        for key, field in (("system", "systems"), ("arch", "architectures")):
            wanted = filters.get(key) or []
            if not wanted:
                continue
            values = [str(v).strip().lower() for v in (item.get(field) or [])
                      if str(v).strip()]
            if not values:
                return False
            if not any(w.strip().lower() in values for w in wanted):
                return False
        return True

    def _refresh_latest_codes(self):
        """算出「最新」这一档是哪些条目：按上架时间倒序取前 10 条。

        （没有上架时间的老数据排在最后，不会被算成"最新"）
        """
        latest = getattr(self, "_latest_n", 10)
        rows = []
        for item in (self._all_resources if hasattr(self, "_all_resources") else []):
            stamp = _parse_listed_at(item.get("listed_at"))
            if stamp is not None:
                rows.append((stamp, str(item.get("code") or "")))
        rows.sort(reverse=True)
        self._latest_codes = {code for _stamp, code in rows[:latest]}

    def _apply_filters(self):
        """把「搜索关键词 + 更多筛选」一起作用到列表上"""
        if not hasattr(self, "_all_resources"):
            self._all_resources = self.apps_framework.items

        keyword = self.search_box.text().strip().lower()
        filters = self.filter_panel.values() if hasattr(self, "filter_panel") else {}

        # 编码搜索：TG-000015 / tg-15 / 15 都尽量能命中
        digits = "".join(ch for ch in keyword if ch.isdigit())

        def match_keyword(item) -> bool:
            if not keyword:
                return True
            code = str(item.get("code", "")).lower()
            if keyword in code:
                return True
            if digits and digits in "".join(ch for ch in code if ch.isdigit()):
                return True
            code_id = str(item.get("id", "")).lower()
            if code_id and keyword == code_id:
                return True
            if keyword in str(item.get("name", "")).lower():
                return True
            if keyword in str(item.get("description", "")).lower():
                return True
            # 关键词匹配 = 类别 ∪ 标签（理由同 tag_filter_options）
            return any(keyword in str(v).lower()
                       for v in resource_schema.keywords_of(item))

        matched = [i for i in self._all_resources
                   if match_keyword(i) and self._passes_filters(i, filters)]
        self.apps_framework.update_data(matched)

        # 结果条数写在按钮右边的灰色小字里（按钮本身只表示"展开/收起"）
        self._update_result_label(len(matched))
        return matched, keyword

    def _update_result_label(self, count: int):
        """更新「已搜索到 XXX 个相关内容」"""
        if not hasattr(self, "result_label"):
            return
        template = self.get_text("result_count")
        try:
            self.result_label.setText(template.format(n=count))
        except Exception:
            # ⚠️ 兜底也要跟着语言走（以前写死中文，英文/繁体用户走到这里就又是中文）
            self.result_label.setText(
                self.get_text("search_done").format(n=count))

    def _do_search(self):
        """执行搜索（关键词 + 更多筛选）"""
        text = self.search_box.text()
        # 仍然记下最后一次搜的关键词（配置项留着），但不再回填到搜索框：需求要的是"启动时搜索框是空的"
        if self.settings_manager:
            self.settings_manager.update_setting("last_search", text)

        matched, keyword = self._apply_filters()

        from ..utils.logger import log
        if keyword:
            log.op("搜索", "keyword", 关键词=text, 命中=len(matched),
                   总数=len(self._all_resources))
        else:
            log.op("搜索", "clear", 结果数=len(matched))

    def _rotated_icon(self, icon, angle):
        qicon = icon.icon()
        pixmap = qicon.pixmap(self.more_filter_btn.iconSize())
        rotated = pixmap.transformed(QTransform().rotate(angle), Qt.SmoothTransformation)
        return QIcon(rotated)

    def _on_sort_changed(self, index: int):
        key = self.sort_combo.itemData(index)
        if key:
            self.apps_framework.set_sort(key)
            from ..utils.logger import log
            log.op("排序", "change", 方式=self.sort_combo.currentText(), key=key)

    def get_text(self, key):
        if self.lang:
            text = self.lang.get_text("search", key)
            if text != key:
                return text
        defaults = {
            "select_all": "全选", "from_folder": "从收藏夹导入", "choose_folder": "选择收藏夹…",
            "add_to_deploy": "添加到部署清单", "cancel": "取消",
            "nothing_selected": "还没有勾选任何应用",
            "filter_hint": "点下面的条件筛选，同一行可以多选；点「全部」清空该行",
            "filter_all": "全部",
            "filter_category": "类别", "filter_tag": "标签",
            "filter_source": "来源", "filter_favorite": "收藏",
            "source_site": "有官网", "source_repo": "有代码仓库",
            "source_download": "可自动下载", "favorite_only": "仅看收藏",
            "filter_updated": "更新时间", "updated_latest": "最新",
            "updated_10d": "10 天前", "updated_30d": "30 天前",
            "updated_180d": "半年前",
            "filter_system": "适用系统", "filter_arch": "CPU 架构",
            "result_count": "已搜索到 {n} 个相关内容",
            "view_tile_tip": "磁贴视图：一行 4 个大卡片",
            "view_grid_tip": "网格视图：一行 6 个小卡片，只保留收藏按钮",
        }
        return defaults.get(key, key)
