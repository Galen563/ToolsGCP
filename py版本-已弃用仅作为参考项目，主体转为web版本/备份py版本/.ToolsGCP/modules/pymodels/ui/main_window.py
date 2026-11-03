"""主窗口"""

import sys
import os
import locale
import time
import ctypes
from PyQt5.QtCore import Qt, QEvent, QTimer, QPoint, pyqtSignal
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction
from PyQt5.QtGui import QIcon
from qfluentwidgets import (FluentWindow, NavigationInterface,
                           NavigationItemPosition, setTheme, Theme,
                           FluentIcon as FIF, InfoBar, InfoBarPosition,
                           InfoBadge, InfoBadgePosition,
                           RoundMenu, isDarkTheme)

from ..core.language_manager import LanguageManager
from ..core.settings_manager import SettingsManager
from ..core.favorites_manager import FavoritesManager
from ..core.plugin_manager import PluginManager
from ..constants import (IS_AUTOSTART, OPEN_SETTINGS, SCRIPT_DIR, DATA_DIR,
                         APP_NAME, APP_VERSION)
from ..interfaces.search_interface import SearchInterface
from ..interfaces.customize_interface import CustomizeInterface
from ..interfaces.home_interface import HomeInterface
from ..interfaces.notice_interface import NoticeInterface
from ..interfaces.tools_gcp_interface import ToolsGCPInterface
from ..interfaces.gcp_workshop_interface import GCPWorkshopInterface
from .ai_sidebar_page import AISidebarPage
from ..interfaces.deploy_interface import DeployInterface
from ..interfaces.github_interface import GithubInterface
from ..interfaces.log_interface import LogInterface
from ..interfaces.feedback_interface import FeedbackInterface
from ..interfaces.settings import SettingsInterface
from ..interfaces.plugin_interface import PluginInterface
from ..utils.theme_utils import detect_system_theme, fix_dark_theme_titlebar, apply_app_palette
from ..utils.logger import log
from ..utils.system_utils import set_windows_autostart
from ..utils.global_hotkey import GlobalHotkeyManager, unusable_main_key
from .ai_floating_button import AIFloatingButton
from .ai_chat_panel import AIChatDrawer
from .announcement_dialog import AnnouncementDialog
from .privacy_consent import PrivacyManager, PrivacyConsentDialog, PrivacyMaskOverlay


# 首屏内容加载的最长等待时间（毫秒），超时就先显示窗口
UI_READY_TIMEOUT_MS = 6000

# 打开 AI 抽屉后延迟聚焦输入框（毫秒）：等滑动动画把控件摆到位
SLIDE_FOCUS_DELAY_MS = 300

# 启动后多久去拉公告（毫秒）：等窗口和首屏都站稳，免得和启动动画/隐私弹窗抢镜头
ANNOUNCEMENT_FETCH_DELAY_MS = 1200

# 拉到公告后延迟多久弹「新公告」（毫秒）：让窗口先画完一帧再盖遮罩
ANNOUNCEMENT_POPUP_DELAY_MS = 700

# 窗口还没显示出来时的重试间隔（毫秒）/ 最多重试几次
ANNOUNCEMENT_POPUP_RETRY_MS = 800
ANNOUNCEMENT_POPUP_MAX_RETRY = 12

# 左侧栏「公告」未读红点的颜色（两个主题各一套）
UNREAD_BADGE_LIGHT = "#FA5151"
UNREAD_BADGE_DARK = "#F74C4C"
# ⚠️ 红点尺寸自己算：高度固定，宽度按文字量 —— 一位数是正圆，两位/99+ 才是胶囊
UNREAD_BADGE_FONT_PX = 9
UNREAD_BADGE_HEIGHT = 13
UNREAD_BADGE_MIN_WIDTH = 13
UNREAD_BADGE_TEXT_PAD = 8

# 这些属性对应的页面都算"可滚动页面"（主题刷新 / 滚动优化要遍历它们）
PAGE_ATTRS = (
    "searchInterface", "homeInterface", "customizeInterface",
    "toolsGCPInterface", "deployInterface", "githubInterface",
    "logInterface", "feedbackInterface", "noticeInterface",
    "pluginInterface", "settingsInterface",
)


class MainWindow(FluentWindow):
    """主窗口：ui_ready 信号在首屏内容全部渲染完成后发出，启动流程据此决定何时显示窗口。"""
    ui_ready = pyqtSignal()

    def __init__(self):
        super().__init__()
        
        os.chdir(SCRIPT_DIR)
        
        self.settings_manager = SettingsManager()
        self.language_manager = LanguageManager()

        # 按"开机自启 + 最小化到托盘"决定同步策略，把"开关是开、系统侧未生效"的状态对齐；
        # 托盘同步延后到 check_startup_minimize（需要窗口图标已就绪）
        autostart_on = bool(self.settings_manager.settings.get("startup_with_windows", True))
        tray_on = bool(self.settings_manager.settings.get("minimize_to_tray", False))
        self._startup_tray_sync_needed = False

        log.info("启动", "startup", f"启动同步检查: 开机自启={'开' if autostart_on else '关'}, 启动时最小化到托盘={'开' if tray_on else '关'}")

        if not autostart_on:
            log.info("启动", "startup", "开机自启已关闭 → 跳过开机自启同步、跳过托盘同步")
        else:
            log.info("启动", "startup", "开机自启已开启 → 执行开机自启同步（确保注册表项存在）")
            try:
                success, err = set_windows_autostart(True)
                if success:
                    log.info("启动", "startup", "开机自启同步完成")
                else:
                    log.err("启动", "startup", f"开机自启同步失败: {err}")
            except Exception as e:
                log.err("系统", "system", f"自动同步开机自启动异常: {e}")

            if tray_on:
                log.info("启动", "startup", "托盘已开启 → 标记需要执行托盘同步（将在窗口就绪后建托盘图标）")
                self._startup_tray_sync_needed = True
            else:
                log.info("启动", "startup", "托盘已关闭 → 跳过托盘同步（不论是否 autostart 启动都不会隐藏）")

        saved_lang = self.settings_manager.settings.get("language", "跟随系统")
        if saved_lang == "跟随系统":
            try:
                system_lang = locale.getlocale()[0]
                if system_lang and ("Chinese (Simplified)" in system_lang or "zh_CN" in system_lang):
                    saved_lang = "简体中文"
                elif system_lang and ("Chinese (Traditional)" in system_lang or "zh_TW" in system_lang or "zh_HK" in system_lang):
                    saved_lang = "繁體中文"
                else:
                    saved_lang = "English"
            except Exception:
                saved_lang = "简体中文"
        self.language_manager.set_language(saved_lang)
        
        self._theme_fixed = False
        self.tray_icon = None
        self._privacy_checked = False
        self._privacy_mask = None
        # 启动计时起点（_on_search_ready 里用来算启动耗时）
        self._startup_t0 = time.perf_counter()
        # 全屏前记住的窗口几何，退出全屏时恢复用
        self._normal_geometry = None
        self._was_maximized = False
        self._tracking_fullscreen = False
        self._immersive = False          # 全屏态：顶部标题栏藏起来了
        self._drag_origin = None
        self._drag_from_fullscreen = False
        self._restoring_geometry = False
        self._ui_ready_emitted = False
        self._hide_after_first_show = False
        # 用户是否在设置里关掉了 AI 悬浮球（见 toggle_ai_floating_button）
        self._ai_ball_suppressed = False
        # 关闭窗口时的"API Key 未保存"提示是否已经问过
        self._closing_confirmed = False
        # 公告未读红点（左侧栏「公告」条目）
        self.notice_badge = None          # qfluentwidgets 的 InfoBadge，建导航时才存在
        self._notice_unread = 0           # 当前未读条数（红点显示的数字）
        # 「新公告」弹窗的重试计数（窗口还没显示时用）
        self._announcement_popup_retry = 0
        # ⚠️ 本会话内已弹过的公告 id（只在内存里）：同一条不重复弹，出现新 id 仍会弹，重启清空
        self._announcement_popped_ids = set()
        # 公告只在窗口第一次显示后拉一次（showEvent 可能被调多次）
        self._announcements_started = False
        # 隐私协议弹窗挡在前面时，公告弹窗往后让（别抢镜头）
        self._privacy_prompt_active = False

        self.privacy_manager = PrivacyManager(
            SCRIPT_DIR, self.language_manager, self.settings_manager
        )
        
        # ⚠️ 界面字体必须在建任何控件前设好，否则先建的控件还是旧字体；配置缺失/失效时用默认字体
        try:
            from ..utils.fonts import apply_font, dark_default_family
            applied_font = apply_font(str(
                self.settings_manager.settings.get("ui_font_family", "") or ""))
            log.info("启动", "startup",
                     f"界面字体: {applied_font or dark_default_family() or '默认'}")
        except Exception as exc:
            log.err("启动", "startup", f"应用界面字体失败: {exc}")

        # 应用主题（lazy 的含义见 utils/theme_utils.apply_theme）
        saved_theme = self.settings_manager.settings.get("theme", "跟随系统")
        actual_theme = self.get_actual_theme(saved_theme)
        if actual_theme == "深色主题":
            setTheme(Theme.DARK, lazy=True)
        else:
            setTheme(Theme.LIGHT, lazy=True)
        # qfluentwidgets 不管 QPalette，必须自己切，否则滚动区视口等原生控件是白底
        apply_app_palette(actual_theme == "深色主题")
        # 强调色统一成品牌色（库默认青色打架）。⚠️ 先读"组件配色"档位再灌强调色（见 ACCENT_PRESETS）
        try:
            from ..interfaces.settings.theme import (apply_accent_color,
                                                     set_accent_key)
            set_accent_key(str(self.settings_manager.settings.get("accent_color")
                               or "blue"))
            apply_accent_color(actual_theme == "深色主题")
        except Exception as exc:
            log.err("启动", "startup", f"应用强调色失败: {exc}")
        log.info("启动", "startup",
                 f"主题: 设置={saved_theme} 实际={actual_theme} isDarkTheme={isDarkTheme()}")
        
        icon_path = os.path.join(SCRIPT_DIR, ".ToolsGCP", "logo.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            self.setWindowIcon(FIF.APPLICATION.icon())
        
        self.setMinimumSize(1000, 660)
        
        # 卡片尺寸是 AppCard 里的全局量，必须在建卡片之前先设好
        from ..widgets.app_card import apply_card_size as _apply_card_size
        _apply_card_size(self.settings_manager.settings.get("search_card_size", "medium"))

        # ⚠️ 全局崩溃护栏：必须在建任何界面/装事件过滤器之前装好 —— PyQt5 默认把槽函数里
        #    逃出去的异常升级成 qFatal()（直接 abort，无提示），装了它才变成"写日志 + 打堆栈"。
        try:
            from ..utils.crash_guard import install_crash_guard
            install_crash_guard()
        except Exception:
            pass

        # ⚠️ 输入框的圆角右键菜单（全程序一套）：在这里装一次就够了
        try:
            from .input_menu import install_input_context_menus
            install_input_context_menus(
                QApplication.instance(),
                translate=lambda key: self.language_manager.get_text("settings", key))
        except Exception:
            pass

        # ⚠️ Ctrl+左键观察器必须在这里装：等第一次点链接才懒装，触发这次打开的按下事件早过去了
        try:
            from ..utils.url_open import install_ctrl_watcher
            install_ctrl_watcher()
        except Exception:
            pass

        # ⚠️ 开关上的 "On"/"Off" 是库写死的英文，用应用级事件过滤器在控件显示时补文字（懒建页面也覆盖）
        try:
            from ..utils.i18n_widgets import install_switch_text_i18n
            install_switch_text_i18n(QApplication.instance())
        except Exception:
            pass

        self.favorites_manager = FavoritesManager()
        self.searchInterface = SearchInterface(self.settings_manager, self.language_manager,
                                               self.favorites_manager)
        # 首页的"推荐插件"要读插件列表，先建页面，等插件加载完再刷新
        self.homeInterface = HomeInterface(self.language_manager, None)
        # 定制页需要设置和收藏（推荐里排除已收藏）才能干活
        self.customizeInterface = CustomizeInterface(
            self.language_manager, self.settings_manager, self.favorites_manager)
        self.noticeInterface = NoticeInterface(self.language_manager,
                                               self.settings_manager)
        # 公告：未读数 → 左侧栏红点；拉到新公告 → 决定是否弹窗
        self.noticeInterface.unread_changed.connect(self._update_notice_badge)
        self.noticeInterface.announcements_fetched.connect(
            self._on_announcements_fetched)
        self.noticeInterface.fetch_failed.connect(self._on_announcements_failed)
        self.noticeInterface.marked_all_read.connect(
            self._on_announcements_marked_read)
        self.toolsGCPInterface = ToolsGCPInterface(self.language_manager,
                                                   self.favorites_manager)
        self.toolsGCPInterface.detail_opener = self._open_resource_detail
        # GCP工坊：内置工具入口墙，点卡片切到对应页面，很轻就一起建了
        self.workshopInterface = GCPWorkshopInterface(self.language_manager)
        # 侧边栏 AI 整页界面：懒建，内部四千多行的聊天面板要等真正用到才建
        self.aiSidebarPage = AISidebarPage(self)
        self.deployInterface = DeployInterface(self.language_manager, self.settings_manager, self)
        self.githubInterface = GithubInterface(self.language_manager, self.settings_manager)
        self.logInterface = LogInterface(self.language_manager, self.settings_manager)
        self.feedbackInterface = FeedbackInterface(self.language_manager, self.settings_manager)
        self.plugin_manager = PluginManager(
            SCRIPT_DIR, DATA_DIR,
            settings_manager=self.settings_manager,
            favorites_manager=self.favorites_manager,
            language_manager=self.language_manager)
        # 插件要摸到主窗口：内置插件「GCP-AI Agent」用它拿 AgentBridge（见 PluginContext.ai_agent）
        self.plugin_manager.main_window = self
        self.pluginInterface = PluginInterface(self.plugin_manager, self.language_manager)
        self.homeInterface.plugin_manager = self.plugin_manager
        self.homeInterface.plugin_center_requested.connect(self._open_plugin_center)
        self.settingsInterface = SettingsInterface(self.settings_manager, self.language_manager, self)

        # 收藏改动双向同步
        self.searchInterface.favorites_changed.connect(
            self.toolsGCPInterface.on_favorites_changed)
        self.toolsGCPInterface.favorites_changed.connect(
            self.searchInterface.refresh_favorites)
        # 定制页也跟着收藏走：一边改了收藏，另一边的卡片状态/推荐结果要同步
        self.customizeInterface.favorites_changed.connect(
            self.searchInterface.refresh_favorites)
        self.customizeInterface.favorites_changed.connect(
            self.toolsGCPInterface.on_favorites_changed)
        self.searchInterface.favorites_changed.connect(
            self.customizeInterface.refresh_favorites)
        self.toolsGCPInterface.favorites_changed.connect(
            self.customizeInterface.refresh_favorites)
        # 点推荐卡片 → 打开资源详情（与搜索页同一入口）
        self.customizeInterface.card_activated.connect(self._open_resource_detail)
        self.customizeInterface.ai_mention_requested.connect(self.mention_to_ai)
        # 搜索页勾选完 → 加进部署清单
        self.searchInterface.apps_selected.connect(
            self.deployInterface.add_codes)
        # 卡片「@给AI」→ 打开 AI 抽屉并在输入框末尾追加 @名称
        self.searchInterface.ai_mention_requested.connect(self.mention_to_ai)
        
        self.init_navigation()
        
        self.setWindowTitle('ToolsGCP')
        self.resize(1280, 880)

        self._hook_max_button()
        self._install_titlebar_filter()

        # 加载插件（放最后：插件写崩了也不影响主程序启动）
        try:
            self.plugin_manager.load_all()
            self.pluginInterface.refresh_list()
            self.homeInterface.refresh_plugins()
            loaded = [p.name for p in self.plugin_manager.plugins if p.ok]
            if loaded:
                log.info("插件", "plugin", f"已加载 {len(loaded)} 个插件: {', '.join(loaded)}")
        except Exception as e:
            log.err("插件", "plugin", f"插件加载流程异常: {e}")

        # 首屏就绪跟踪：所有延迟加载的页面渲染完成后才允许显示窗口
        self._track_ui_ready()

        # GCP-AI：右下角悬浮球 + 右侧聊天抽屉（球开关抽屉，抽屉负责对话）
        self.ai_floating_button = AIFloatingButton(self, parent=self)
        self.ai_floating_button.on_clicked_callback = self.toggle_ai_drawer
        self.ai_chat_drawer = AIChatDrawer(self, parent=self)
        # ⚠️ 只有"开了 AI 且没开侧边栏 AI 模式"才挂悬浮球，否则会和左侧栏 AI 页同时存在
        #    （apply_ai_sidebar_mode 会 detach，但这里先 attach 已经闪了一下，别的路径还会放回来）。
        if self.settings_manager.settings.get("ai_enabled", False) \
                and not self.settings_manager.settings.get("ai_sidebar_mode", False):
            self.ai_floating_button.attach()
        # 空闲时预热 AI 抽屉的"滑动快照"（首次 grab 约 100ms），放在启动 2.5 秒后，第一次点开就不卡
        if self.settings_manager.settings.get("ai_enabled", False):
            from PyQt5.QtCore import QTimer as _QTimer
            _QTimer.singleShot(2500, self.ai_chat_drawer.prewarm_slide)
            # 全局事件过滤器：滚动/拖动时让悬浮球让路（见 eventFilter）
            try:
                QApplication.instance().installEventFilter(self)
            except Exception:
                pass

        # 全局快捷键（Ctrl+Q 呼出搜索框、Ctrl+Alt+G 呼出 GCP-AI）
        self._hotkey_error = None
        self.hotkey_manager = GlobalHotkeyManager(QApplication.instance(), self)
        self.hotkey_manager.activated.connect(self._on_hotkey_activated)
        try:
            from .log_viewer_window import refresh_open_window
            refresh_open_window()
        except Exception:
            pass

        self.apply_hotkey_settings(notify=False)

        # 窗口内快捷键（Ctrl+J）：必须在这里调一次，否则 new_ai_chat 用到的 ai_chat_drawer 还没建
        self._install_ai_shortcuts()

        # 启动日志（仿 PCL：版本/路径/系统等基本信息）
        log.info("启动", "startup", f"版本: {APP_NAME} {APP_VERSION}")
        log.info("启动", "startup", f"路径: {SCRIPT_DIR}")
        log.info("启动", "startup", f"命令行参数: {sys.argv[1:] if len(sys.argv) > 1 else '[]'}")
        log.info("启动", "startup", f"系统版本: {sys.platform}")
        log.info("启动", "startup", "主窗口 启动成功")


        
        self.center_window()
        
        self.check_startup_minimize()
        self.check_open_settings()
    
    def init_navigation(self):
        """初始化导航：顶部 首页→搜索→定制页→收藏→部署（GCP工坊紧跟收藏），
        底部 公告→Github→更多→设置；⚠️ 反馈/查看日志/插件/部署 的入口收进「更多」菜单。
        """
        self.addSubInterface(self.homeInterface, FIF.HOME,
                           self.language_manager.get_text("nav", "home"),
                           NavigationItemPosition.TOP)

        self.addSubInterface(self.searchInterface, FIF.SEARCH, 
                           self.language_manager.get_text("nav", "search"), 
                           NavigationItemPosition.TOP)

        # 定制页：位置在搜索下面、收藏上面，页面内容留空
        self.addSubInterface(self.customizeInterface, FIF.PALETTE,
                           self.language_manager.get_text("nav", "customize"),
                           NavigationItemPosition.TOP)
        
        self.addSubInterface(self.toolsGCPInterface, FIF.TAG,
                           self.language_manager.get_text("nav", "tools_gcp"))

        # GCP工坊：紧跟「收藏」下面，只是工具入口墙。⚠️ 图标用 DEVELOPER_TOOLS，本版本没有 FIF.TOOLS
        self.addSubInterface(self.workshopInterface, FIF.DEVELOPER_TOOLS,
                           self.language_manager.get_text("nav", "gcp_workshop"),
                           NavigationItemPosition.TOP)

        # AI 页默认**不显示**，只有开了「改用侧边栏 AI 单独界面」才出现（位置固定在 GCP工坊下面）；
        # ⚠️ 这里不调 addSubInterface，只塞进 stackedWidget 注册路由键，侧栏条目由它按需插入。
        if self.stackedWidget.indexOf(self.aiSidebarPage) < 0:
            self.stackedWidget.addWidget(self.aiSidebarPage)
        
        # ⚠️「应用部署」也不占左侧栏条目，改在「更多」菜单里；页面仍需进 stackedWidget（下面循环补）
        
        self.navigationInterface.addSeparator()

        # 公告保留在左侧栏；⚠️ 接住 addSubInterface 的返回值（侧栏条目控件），下面要挂未读红点
        self.notice_nav_item = self.addSubInterface(
            self.noticeInterface, FIF.MEGAPHONE,
            self.language_manager.get_text("nav", "notice"),
            NavigationItemPosition.BOTTOM)
        self._create_notice_badge(self.notice_nav_item)

        self.addSubInterface(self.githubInterface, FIF.GITHUB,
                           self.language_manager.get_text("nav", "github"),
                           NavigationItemPosition.BOTTOM)

        # ---- 「更多」：不切页面，只弹圆角菜单；⚠️ selectable 必须为 True，否则菜单里各页
        #      在左侧栏都没有高亮，点了「更多 → 查看日志」看起来像没跳过去。
        self.more_nav_item = self.navigationInterface.addItem(
            "moreToolsGCP",
            FIF.MORE,
            self.language_manager.get_text("nav", "more"),
            onClick=lambda _checked=False: self.show_more_menu(),
            selectable=True,
            position=NavigationItemPosition.BOTTOM,
            tooltip=self.language_manager.get_text("nav", "more_tip"))

        self.addSubInterface(self.settingsInterface, FIF.SETTING,
                           self.language_manager.get_text("nav", "settings"),
                           NavigationItemPosition.BOTTOM)

        # ⚠️ 这三页不再用 addSubInterface 注册，但**页面仍要进 stackedWidget**，否则 switchTo
        #    会切到不在栈里的控件（表现是"点菜单没反应"）；路由键用页面自己的 objectName()。
        for _icon, _text, _page in self.more_menu_pages():
            if self.stackedWidget.indexOf(_page) < 0:
                self.stackedWidget.addWidget(_page)

        default_page = self.settings_manager.settings.get("default_page", "搜索")
        page_map = {
            "首页": self.homeInterface,
            "搜索": self.searchInterface,
            # 「定制页」现在是独立的留空页面；老配置里存过这个键的用户会落到这里
            "定制页": self.customizeInterface,
            "收藏": self.toolsGCPInterface,
            "部署": self.deployInterface,
            # 这几项已不在「默认启动页面」下拉框里，只为兼容老配置保留
            "Github": self.githubInterface,
            "查看日志": self.logInterface,
            "公告": self.noticeInterface,
            "反馈": self.feedbackInterface,
            "设置": self.settingsInterface
        }
        
        if default_page in page_map:
            target_interface = page_map[default_page]
            self.switchTo(target_interface)
            self.navigationInterface.setCurrentItem(target_interface.objectName())
        else:
            self.switchTo(self.searchInterface)
            self.navigationInterface.setCurrentItem(self.searchInterface.objectName())
        
        self.navigationInterface.setExpandWidth(240)
        # 强制导航栏走覆盖层（flyout）：阈值 = minimumExpandWidth + expandWidth - 322 = 1418 > 窗口宽
        self.navigationInterface.setMinimumExpandWidth(1500)

        # 启动时按配置把"侧边栏 AI 模式"摆好（默认关，什么都不做）
        if self.settings_manager.settings.get("ai_sidebar_mode", False):
            try:
                self.apply_ai_sidebar_mode(True)
            except Exception as exc:
                log.err("启动", "startup", f"应用侧边栏 AI 模式失败: {exc}")

    # ========== 公告（GitHub Issue）==========
    # 公告 = 仓库里带「公告」标签、作者发的 Issue（见 core/announcements.py）：这里只管
    # 左侧栏未读红点 + 启动时拉到未读公告就弹窗提示。

    def _create_notice_badge(self, item_widget):
        """在左侧栏「公告」条目上挂一个微信那样的红色数字圆点：⚠️ 父对象必须是**导航
        条目所在的那个面板**（条目 geometry() 相对它算），用窗口当父对象红点会偏到
        别处去；颜色也要用自定义红才有"未读红"。
        """
        self.notice_badge = None
        if item_widget is None:
            return
        try:
            badge = InfoBadge.custom(
                "0", UNREAD_BADGE_LIGHT, UNREAD_BADGE_DARK,
                parent=self.navigationInterface.panel,
                target=item_widget,
                position=InfoBadgePosition.NAVIGATION_ITEM)
        except Exception as exc:
            log.err("公告", "announcement", f"创建未读红点失败: {exc}")
            return
        self.notice_badge = badge
        self._compact_notice_badge(badge)
        self._update_notice_badge(self._notice_unread)

    def _compact_notice_badge(self, badge):
        """把未读红点配置成"微信那种小红点"：库自带样式偏大（11px + padding "1px 3px"），
        深色主题下还是黑字，所以这里整条覆盖。
        """
        try:
            font = badge.font()
            font.setPixelSize(UNREAD_BADGE_FONT_PX)
            badge.setFont(font)
            badge.setStyleSheet("InfoBadge { padding: 0px; color: #FFFFFF; }")
            badge.setAlignment(Qt.AlignCenter)
        except Exception as exc:
            log.err("公告", "announcement", f"缩小未读红点失败: {exc}")

    def _notice_badge_size(self, badge, text):
        """红点该多大：(宽, 高) —— 高度固定，宽度 = 文字宽 + 内边距且不小于高度
        （一位数是正圆，99+ 才是胶囊）。
        """
        try:
            advance = badge.fontMetrics().horizontalAdvance(str(text))
        except Exception:
            advance = UNREAD_BADGE_MIN_WIDTH
        width = max(UNREAD_BADGE_MIN_WIDTH, int(advance) + UNREAD_BADGE_TEXT_PAD)
        return width, UNREAD_BADGE_HEIGHT

    def _update_notice_badge(self, count=None):
        """更新左侧栏红点上的数字（未读为 0 时它是"不可见"的）：⚠️ 不能简单用 hide()，
        库每次重排都会 setVisible(target.isVisible()) 把红点重新显示出来，所以"没有未读"
        用的是"文字清空 + 尺寸归零"。
        """
        if count is None:
            count = self._notice_unread
        try:
            self._notice_unread = max(0, int(count))
        except (TypeError, ValueError):
            self._notice_unread = 0

        badge = self.notice_badge
        if badge is None:
            return
        try:
            if self._notice_unread <= 0:
                badge.setText("")
                badge.setFixedSize(0, 0)
                return
            # 从"归零态"恢复：按文字重新算尺寸
            badge.setText("99+" if self._notice_unread > 99
                          else str(self._notice_unread))
            width, height = self._notice_badge_size(badge, badge.text())
            badge.setFixedSize(width, height)
            if getattr(badge, "manager", None) is not None:
                badge.move(badge.manager.position())
            badge.show()
            badge.raise_()
        except RuntimeError:
            pass        # C++ 对象已经销毁（窗口正在关闭），不用管

    def start_announcements(self):
        """启动后拉一次公告（由 showEvent 里延时触发）"""
        # ⚠️ 自检 / 截图脚本设了 TOOLSGCP_NO_SETTINGS_WRITE 就不打网络（同 settings_manager 的约定）
        if os.environ.get("TOOLSGCP_NO_SETTINGS_WRITE"):
            return
        try:
            self.noticeInterface.start_fetch()
        except Exception as exc:
            log.err("公告", "announcement", f"启动拉取公告失败: {exc}")

    def _on_announcements_fetched(self, items):
        """拉到公告了：有未读就（这个会话第一次）弹「新公告」窗口"""
        unread = self.noticeInterface.unread_count()
        log.info("公告", "announcement",
                 f"拉到 {len(items or [])} 条公告，未读 {unread} 条")
        if not items or unread <= 0:
            return
        QTimer.singleShot(ANNOUNCEMENT_POPUP_DELAY_MS,
                          self._maybe_show_announcement_popup)

    def _on_announcements_failed(self, code):
        """拉不到就安静算了：页面上仍显示上次的缓存，只写日志不弹错误提示"""
        log.warn("公告", "announcement", f"拉取公告失败: {code}")

    def _on_announcements_marked_read(self, added):
        """点了「全部已读」→ 弹个提示条（红点这时已经归零了）"""
        InfoBar.success(
            title=self.language_manager.get_text("common", "tip_success"),
            content=self.language_manager.get_text("notice",
                                                   "notice_all_read_done"),
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self)

    def _maybe_show_announcement_popup(self):
        """弹「新公告」前的几道检查（通知开着 / 窗口可见 / 还有没弹过的）：⚠️ 判定基准是
        "这条公告还没弹过吗"，不是"这个会话弹过没有" —— id 记在 _announcement_popped_ids
        （只在内存里），所以刷新拉到的新公告照样弹。
        """
        if getattr(self, "_privacy_prompt_active", False):
            # 隐私协议挡在前面：这里不等（重试只会白耗次数），协议处理完会回来叫一次
            return
        if not bool(self.settings_manager.settings.get("notify_enabled", True)):
            return
        pending = self._pending_popup_items()
        if not pending:
            return
        if not self.isVisible():
            # 窗口还没显示（启动画面没播完 / 已最小化到托盘）：过一会儿再试，绝不弹在看不见的地方
            if self._announcement_popup_retry >= ANNOUNCEMENT_POPUP_MAX_RETRY:
                return
            self._announcement_popup_retry += 1
            QTimer.singleShot(ANNOUNCEMENT_POPUP_RETRY_MS,
                              self._maybe_show_announcement_popup)
            return
        self._show_announcement_popup(pending)

    def _pending_popup_items(self):
        """还没弹过的未读公告（新→旧，和公告列表同序）："未读"来自公告状态文件的
        read_ids（删掉那个 json 就等于全部重新变未读），"弹过"只记在内存里；判定走
        core.announcements.popup_pending 这个纯函数。
        """
        try:
            from ..core.announcements import popup_pending
        except Exception:
            return list(self.noticeInterface.unread_items())
        return popup_pending(self.noticeInterface.unread_items(),
                             self._announcement_popped_ids)

    def _show_announcement_popup(self, items):
        """用「检查更新」那套**窗口内弹窗**把**最新那一条**公告摆给用户看：父对象是主
        窗口自己，遮罩才会盖住整个窗口（含左侧导航栏）；⚠️ 只取 `items[0]`（列表本来
        就是新→旧），未读总数另外传进去显示"还有 N 条"。
        """
        newest = items[0] if items else {}
        # 这一批（含"还有 N 条"里那些）都算弹过：要用全部 id，否则下次刷新第二新的又会再弹一次
        for item in items:
            try:
                self._announcement_popped_ids.add(int(item.get("id")))
            except (TypeError, ValueError):
                continue
        log.info("公告", "popup",
                 f"弹出公告弹窗：{newest.get('title') or ''}",
                 unread=self.noticeInterface.unread_count(),
                 popped=len(self._announcement_popped_ids))

        count = self.noticeInterface.unread_count()
        dialog = AnnouncementDialog(self, self._notice_dialog_text, newest, count)
        dialog.exec_()
        action = dialog.action
        try:
            dialog.deleteLater()
        except Exception:
            pass
        if action == "read":
            self.noticeInterface.mark_all_read()
        elif action == "view":
            self.switchTo(self.noticeInterface)
            self.navigationInterface.setCurrentItem(
                self.noticeInterface.objectName())

    def _notice_dialog_text(self, key):
        """弹窗文案：和公告页同一个模块（notice_language.json，三种语言）"""
        return self.language_manager.get_text("notice", key)

    def _track_ui_ready(self):
        """窗口外壳一就绪就发 ui_ready（**首屏内容不再拖着窗口不让显示**）：外壳建好立刻
        发信号；搜索页顶着和切类别同一个加载动画，卡片和图标都就位后动画一撤，内容一次性
        出现（见 AppsIndexFramework 的 FIRST_PAINT_HOLD_MS）。
        """
        # 内容就绪只记一条日志（不再决定窗口什么时候显示）
        self.searchInterface.ready.connect(self._on_search_ready)
        if self.searchInterface.is_ready:
            self._on_search_ready()
        # 放到下一个事件循环再发：让 __init__ 里剩下的收尾工作先做完
        QTimer.singleShot(0, self._emit_ui_ready)
        # 兜底诊断：首屏迟迟没就绪就记一条 WARN（不拦启动）
        QTimer.singleShot(UI_READY_TIMEOUT_MS, self._warn_search_slow)

    def _warn_search_slow(self):
        """首屏内容超过 UI_READY_TIMEOUT_MS 还没就绪：记一条 WARN 方便排查"""
        try:
            if not self.searchInterface.is_ready:
                log.warn("启动", "startup",
                         f"搜索页首屏加载超过 {UI_READY_TIMEOUT_MS} ms 仍未就绪")
        except Exception:
            pass

    def _on_search_ready(self):
        """搜索页首屏真的渲染完了（只记日志，供排查启动耗时）"""
        try:
            elapsed = time.perf_counter() - self._startup_t0
            log.info("启动", "startup", f"搜索页首屏内容就绪（启动后 {elapsed:.2f}s）")
        except Exception:
            log.info("启动", "startup", "搜索页首屏内容就绪")

    def _emit_ui_ready(self):
        if self._ui_ready_emitted:
            return
        self._ui_ready_emitted = True
        log.info("启动", "startup", "首屏内容加载完成")
        # 各页面滚动区视口标成不透明（少一次合成，见 apply_opaque_scrolls）
        try:
            self.apply_opaque_scrolls()
        except Exception:
            pass
        self.ui_ready.emit()

    # ========== 卡片尺寸 ==========
    def apply_card_size(self, size_key: str = None):
        """套用搜索页卡片大小并重新渲染列表（尺寸是 AppCard 里的全局量，必须重建卡片）"""
        from ..widgets.app_card import apply_card_size as _apply
        key = size_key or self.settings_manager.settings.get("search_card_size", "medium")
        _apply(key)
        if hasattr(self, "searchInterface"):
            self.searchInterface.reload_resources()
        log.op("设置", "card_size", value=key)

    # ========== 全屏 ==========
    def keyPressEvent(self, event):
        """F11 = 全屏 / 退出全屏；Esc 也能退出"""
        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self._immersive:
            self.toggle_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def _set_immersive(self, on: bool):
        """全屏态：隐藏顶部标题栏，保留左侧导航条 —— 收起 FluentTitleBar，并把
        stackedWidget 上边那 48px 留白（top margin）去掉。
        """
        self._immersive = bool(on)
        try:
            self.titleBar.setVisible(not on)
        except Exception:
            pass
        try:
            margins = self.widgetLayout.contentsMargins()
            # 顶部留白本来就是给标题栏让位的，全屏时归零
            self.widgetLayout.setContentsMargins(
                margins.left(), 0 if on else 48, margins.right(), margins.bottom())
        except Exception:
            pass

    def toggle_fullscreen(self):
        """切换全屏（F11）：盖住整个屏幕 + 隐藏顶部标题栏（导航栏还在）。⚠️ 退出时必须
        还原进入前的尺寸、位置和"是否最大化"：只调 showNormal() 会退回默认尺寸，只用
        setGeometry 又会在"全屏尺寸恰好等于屏幕尺寸"时像没生效。
        """
        if self.isFullScreen():
            was_maximized = self._was_maximized
            geometry = self._normal_geometry
            self.setWindowState(self.windowState()
                                & ~Qt.WindowFullScreen
                                | Qt.WindowNoState)
            self._set_immersive(False)
            if was_maximized:
                self.showMaximized()
            else:
                self.showNormal()
                if geometry is not None:
                    self.setGeometry(geometry)
                    # showNormal 之后再设一次，确保位置和大小都落到位
                    QTimer.singleShot(0, lambda: self.setGeometry(geometry))
            self._tracking_fullscreen = False
            self._sync_max_button()
            log.op("窗口", "fullscreen", state="退出全屏",
                   geometry=self._geometry_text(),
                   maximized=was_maximized)
        else:
            self._was_maximized = self.isMaximized()
            # 最大化时 geometry() 是最大化后的尺寸，normalGeometry() 才是还原后的尺寸，优先用它
            self._normal_geometry = (self.normalGeometry()
                                     if self._was_maximized else self.geometry())
            self._tracking_fullscreen = True
            self._set_immersive(True)
            self.showFullScreen()
            self._sync_max_button()
            log.op("窗口", "fullscreen", state="进入全屏（隐藏顶部栏）",
                   geometry=self._geometry_text(),
                   maximized=self._was_maximized)

    def _install_titlebar_filter(self):
        """给标题栏装事件过滤器，用来实现：全屏时拖动标题栏就退出全屏"""
        try:
            self.titleBar.installEventFilter(self)
        except Exception:
            pass

    def _hook_max_button(self):
        """接管标题栏的"最大化"按钮：⚠️ 必须先把框架自己连的槽**断开**，否则两个处理器
        同时跑（框架先 showNormal()，我们紧接着判断 isFullScreen() 已为 False）→ 误以为
        要进全屏，表现是"要点两次才恢复"。
        """
        button = getattr(self.titleBar, "maxBtn", None)
        if button is None:
            return
        try:
            button.clicked.disconnect()          # 断开框架自带的 toggleMaxState
        except Exception:
            pass
        try:
            button.clicked.connect(self._on_max_button_clicked)
        except Exception:
            pass

    def _on_max_button_clicked(self):
        """标题栏那个按钮：全屏时退出全屏，否则最大化/还原"""
        if self.isFullScreen():
            self.toggle_fullscreen()
            return
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._sync_max_button()

    # ---------- 全屏状态下拖动窗口 = 退出全屏 ----------
    def eventFilter(self, obj, event):
        """全局事件守卫：① 标题栏拖动（全屏时一拖就退出全屏）；② 滚动/拖动时让 AI 悬浮球
        "让路"（球每约 50ms 重算 metaball 液面，单帧 3~4ms）。
        ⚠️ 同一个类里不能有两个 eventFilter：后定义的那个会把先定义的整个覆盖掉。
        """
        try:
            if obj is self.titleBar:
                if event.type() == QEvent.MouseButtonPress:
                    self._drag_origin = event.globalPos()
                    self._drag_from_fullscreen = self.isFullScreen()
                elif (event.type() == QEvent.MouseMove
                      and getattr(self, "_drag_from_fullscreen", False)
                      and self._drag_origin is not None):
                    moved = (event.globalPos() - self._drag_origin).manhattanLength()
                    if moved > 8:
                        self._exit_fullscreen_by_drag(event.globalPos())
        except Exception:
            pass
        # 滚动 / 拖动 → 悬浮球安静一会儿（只认这几种事件，别的直接放行）
        try:
            etype = event.type()
            if etype == QEvent.Wheel or etype == QEvent.Scroll or (
                    etype == QEvent.MouseMove and (event.buttons() & Qt.LeftButton)):
                ball = getattr(self, "ai_floating_button", None)
                if ball is not None and hasattr(ball, "pause_for"):
                    ball.pause_for(200)
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _exit_fullscreen_by_drag(self, global_pos):
        """全屏时拖动标题栏：变成窗口模式，并让窗口跟着鼠标位置"""

        self._drag_from_fullscreen = False
        geometry = self._normal_geometry
        self.showNormal()
        if geometry is not None:
            self.setGeometry(geometry)
        # 窗口横向跟着鼠标，纵向保持在顶部，跟常见浏览器行为一致
        try:
            width = self.width()
            self.move(int(global_pos.x() - width / 2), max(0, int(global_pos.y()) - 16))
        except Exception:
            pass
        self._sync_max_button()
        log.op("窗口", "fullscreen", state="拖动退出全屏",
               geometry=self._geometry_text())

    def _sync_max_button(self):
        """让标题栏右上角的按钮跟着状态变（全屏时显示"两个正方形叠加"的还原图标）"""
        try:
            button = self.titleBar.maxBtn
        except Exception:
            return
        maximized = bool(self.isMaximized() or self.isFullScreen())
        try:
            # setMaxState 就是切换那个图标（True = 两个正方形叠加）
            button.setMaxState(maximized)
            button.update()
        except Exception:
            pass

        # 标题栏也会响应窗口状态变化，可能之后又把图标改回去，下个事件循环再确认
        def _confirm():
            try:
                if button.isMaximized() != maximized:
                    button.setMaxState(maximized)
                    button.update()
            except Exception:
                pass
        QTimer.singleShot(0, _confirm)

    def changeEvent(self, event):
        """窗口状态一变（最大化/还原/全屏）就同步标题栏按钮 —— 兜底：只要不是全屏了，
        就把进入全屏前记下的尺寸恢复回去（Win+方向键、系统把窗口踢出全屏等情况）。
        """
        super().changeEvent(event)
        if event.type() != QEvent.WindowStateChange:
            return
        self._sync_max_button()

        was_full = getattr(self, "_tracking_fullscreen", False)
        now_full = self.isFullScreen()
        if was_full and not now_full:
            # 已经退出全屏，且不是最大化 → 恢复原尺寸
            self._set_immersive(False)          # 顺带把顶部标题栏显回来
            geometry = self._normal_geometry
            if geometry is not None and not self.isMaximized() \
                    and not getattr(self, "_restoring_geometry", False):
                self._restoring_geometry = True
                try:
                    self.setGeometry(geometry)
                finally:
                    QTimer.singleShot(0, lambda: setattr(self, "_restoring_geometry", False))
        self._tracking_fullscreen = now_full

    def _geometry_text(self) -> str:
        g = self.geometry()
        return f"{g.width()}x{g.height()}+{g.x()}+{g.y()}"

    @property
    def is_ui_ready(self) -> bool:
        """首屏内容是否已经加载完成"""
        return self._ui_ready_emitted

    def check_open_settings(self):
        """检查是否需要打开设置页面"""
        if OPEN_SETTINGS or self.settings_manager.settings.get("open_settings_on_restart", False):
            self.settings_manager.update_setting("open_settings_on_restart", False)
            self.switchTo(self.settingsInterface)
            self.navigationInterface.setCurrentItem(self.settingsInterface.objectName())
    
    def check_startup_minimize(self):
        """启动时同步 + 最小化判断：托盘图标**无条件创建**（它是"把窗口叫回来 / 退出"的
        入口，藏起来等于拿掉入口），但只在"确实是 autostart 启动 且 开了最小化到托盘"时
        才隐藏主窗口。
        """
        log.info("启动", "startup", "创建常驻托盘图标")
        self.show_tray_icon()
        if self.tray_icon is not None:
            log.info("启动", "startup", "托盘图标已创建")
        else:
            log.err("启动", "startup", "托盘图标未创建（系统可能不支持托盘）")

        if getattr(self, "_startup_tray_sync_needed", False) and IS_AUTOSTART:
            log.info("启动", "startup", "本次为 autostart 启动 → 窗口首次显示后隐藏到托盘")
            self._hide_after_first_show = True
        else:
            log.info("启动", "startup", "主窗口保持显示，托盘已就绪可右键操作")
    
    def show_tray_icon(self):
        """显示托盘图标（幂等：已经有了就只确保它处于可见状态）：⚠️ 图标必须是**和任务栏
        同一个 QIcon**（self.windowIcon()），否则没设 AppUserModelID 时 Windows 会把窗口
        归到 python.exe 名下，托盘就跟着"没图标"。
        """
        if self.tray_icon is None:
            self.tray_icon = QSystemTrayIcon(self)
            icon = self.windowIcon()
            if icon is None or icon.isNull():
                # 兜底：窗口图标没准备好时直接从 logo.png 再取一次
                try:
                    from ..constants import SCRIPT_DIR as _ROOT
                    fallback = os.path.join(str(_ROOT), ".ToolsGCP", "logo.png")
                    if os.path.exists(fallback):
                        icon = QIcon(fallback)
                except Exception:
                    pass
            self.tray_icon.setIcon(icon)
            self.tray_icon.setToolTip("ToolsGCP")

            # 菜单：QQ 风格竖长方形圆角卡片（见 ui/tray_menu.py），自上而下：呼出主窗口 /
            # 呼出搜索框 / 呼出 AI search / ──── / 退出
            from .tray_menu import make_tray_menu
            self.tray_menu = make_tray_menu(
                self.language_manager,
                {"home": self.show_main_window,
                 "search": self.show_search_box,
                 "ai": self.show_ai,
                 "exit": self.quit_app},
                self)
            # ⚠️ 这里**故意不调** `setContextMenu(self.tray_menu)`，改用 activated(Context) 自己弹：
            #    Windows 上托盘菜单会被转成**原生 HMENU**（写在 QMenu 上的圆角 / 悬停底色全失效），
            #    而 activated(Context) 是无条件发出来的，不设 contextMenu 反而能拿到右键事件。
            self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()
    
    def on_tray_activated(self, reason):
        """托盘图标激活事件：右键弹自定义菜单，双击呼出主窗口（见 show_tray_icon）"""
        if reason == QSystemTrayIcon.Context:
            self._show_tray_menu()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.show_main_window()

    def _show_tray_menu(self):
        """在托盘图标旁边弹出自定义菜单（贴着任务栏那一侧往上/往下弹）：⚠️ 位置必须自己
        算 —— 默认 popup(QCursor.pos()) 会让菜单压在光标右下角、任务栏在底部时只露出一半；
        这里拿 tray_icon.geometry()（Qt 5.15+）按"图标在屏幕下半边就往上弹"摆。
        """
        menu = getattr(self, "tray_menu", None)
        if menu is None:
            return
        try:
            menu.refresh_theme()            # 主题可能刚变过，弹之前重刷一次
        except Exception:
            pass

        from PyQt5.QtGui import QCursor
        pos = QCursor.pos()
        try:
            geometry = self.tray_icon.geometry()
            screen = QApplication.screenAt(geometry.center()) \
                or QApplication.primaryScreen()
            if geometry.isValid() and not geometry.isNull() and screen is not None:
                available = screen.availableGeometry()
                size = menu.sizeHint()
                x = geometry.center().x() - size.width() // 2
                if geometry.center().y() > available.center().y():
                    y = geometry.top() - size.height() - 6      # 任务栏在下面 → 往上弹
                else:
                    y = geometry.bottom() + 6                   # 任务栏在上面 → 往下弹
                x = max(available.left() + 8,
                        min(x, available.right() - size.width() - 8))
                y = max(available.top() + 8,
                        min(y, available.bottom() - size.height() - 8))
                pos = QPoint(x, y)
        except Exception as exc:
            log.err("窗口", "tray", f"托盘菜单位置计算失败（退回光标位置）: {exc}")
        menu.popup(pos)
    
    def show_main_window(self):
        """显示主窗口（**不管它现在在哪儿、被压在谁的下面，都要抬到最前面**）：⚠️ 只写
        show() + raise_() + activateWindow() 不够（activateWindow() 在本进程不在前台时会被
        前台锁忽略，raise_() 又只管 Qt 自己的 z 序），所以走 _bring_to_front()。
        """
        self._bring_to_front()

    def show_ai_via_tray(self):
        """托盘「呼出 AI search」：把窗口抬到最前并滑出 AI 抽屉"""
        self.show_ai()

    # ========== 全局快捷键 / 呼出搜索框 ==========
    # ⚠️ HOTKEYS 第四个元素是**语言键**（settings 段），不是写死的名字（会显示给用户）。
    HOTKEYS = (
        ("search", "hotkey_search", "Ctrl+Q", "hotkey_search"),
        ("ai", "hotkey_ai", "Ctrl+Alt+G", "hotkey_ai"),
    )

    def _hotkey_label(self, text_key: str) -> str:
        """热键的显示名（按当前语言）"""
        text = self.language_manager.get_text("settings", text_key)
        return text if text and text != text_key else text_key

    def apply_hotkey_settings(self, notify=True):
        """按设置注册或注销全部全局快捷键，返回 (是否全部成功, 第一条错误)。每个热键单独
        注册：某个键被别的软件占用时只有它自己失败，不带下其它热键。⚠️ 结果顺手同步给
        设置页，用户最需要知道的就是"这个键到底生效了没有"。
        """
        enabled = bool(self.settings_manager.settings.get("hotkey_enabled", True))
        self._hotkey_error = None
        status = {}

        if not enabled:
            self.hotkey_manager.unregister_all()
            log.info("快捷键", "hotkey", "全局快捷键已关闭")
            self._push_hotkey_status(status)
            return True, None

        first_error = None
        for name, key, default, label_key in self.HOTKEYS:
            label = self._hotkey_label(label_key)
            sequence = str(self.settings_manager.settings.get(key, default) or "").strip()
            # ⚠️ 迁移：老版本把 GCP-AI 默认键写成 Ctrl+Caps，而 RegisterHotKey 拿 Caps Lock
            #    做主键**必然失败**（错误码 1409）；这里认出来就换默认值并落盘。
            bad_key = unusable_main_key(sequence)
            if bad_key:
                log.err("快捷键", "hotkey",
                        f"{label} 的 {sequence} 用了 {bad_key} 做主键，系统不允许"
                        f"（RegisterHotKey 会失败）→ 已自动换成 {default}")
                sequence = default
                self.settings_manager.update_setting(key, default)
                if hasattr(self.settingsInterface, "sync_hotkey_edits"):
                    self.settingsInterface.sync_hotkey_edits()
            if not sequence:
                self.hotkey_manager.unregister(name)
                status[name] = (False, self._hotkey_label("hotkey_status_unset"))
                continue
            ok, err = self.hotkey_manager.register(name, sequence)
            if ok:
                log.info("快捷键", "hotkey",
                         f"{label} 已注册: {self.hotkey_manager.sequence(name)}")
                status[name] = (True, self.hotkey_manager.sequence(name))
            else:
                log.err("快捷键", "hotkey", f"{label} 注册失败: {err}")
                status[name] = (False, err)
                if first_error is None:
                    first_error = f"{label}：{err}"

        self._push_hotkey_status(status)
        if first_error:
            self._hotkey_error = first_error
            if notify and self.isVisible():
                self._notify_hotkey_error()
            return False, first_error
        return True, None

    def _push_hotkey_status(self, status: dict):
        """把每个热键的注册结果同步到设置页那两行（任务：快捷键要看得见是否生效）"""
        setter = getattr(getattr(self, "settingsInterface", None),
                         "set_hotkey_status", None)
        if callable(setter):
            try:
                setter(status)
            except Exception as exc:
                log.err("快捷键", "hotkey", f"刷新快捷键状态失败: {exc}")

    # ========== 主题切换：只刷当前可见的页 ==========
    def apply_opaque_scrolls(self, pages=None):
        """把各页面里滚动区的**视口**标成"不透明"（滚动时少合成一层）：视口默认透明，
        滚动时 Qt 得连它下面那层（窗口背景 / 亚克力模糊）一起重画，标成不透明后直接跳过
        —— 实测 16.0 → 12.3ms/步。⚠️ 只处理**页面**，不碰 AI 抽屉那种自带底色的滚动区。
        """
        try:
            from ..utils.theme_utils import make_scroll_areas_opaque
        except Exception:
            return
        if pages is None:
            pages = [getattr(self, name, None) for name in PAGE_ATTRS]
            maker = getattr(self, "resourceMakerInterface", None)
            if maker is not None:
                pages.append(maker)
        count = 0
        for page in pages:
            if page is None:
                continue
            count += make_scroll_areas_opaque(page)
        return count

    def refresh_all_pages_theme(self):
        """主题变了以后刷新各页面 —— 但**只立刻刷当前看得见的那一页**：同步刷每一页才是
        大头（日志页 ~180ms、搜索页 ~180ms…），而用户当时只看得到设置页。所以其余页记成
        "主题脏"，等 switchTo 切过去时再刷。
        """
        pages = [getattr(self, name, None) for name in PAGE_ATTRS]
        current = None
        if getattr(self, "stackedWidget", None) is not None:
            current = self.stackedWidget.currentWidget()

        dirty = set()
        for page in pages:
            if page is None:
                continue
            refresh = getattr(page, "refresh_theme", None)
            if not callable(refresh):
                continue
            if page is current:
                try:
                    refresh()
                except Exception as exc:
                    log.err("主题", "theme", f"当前页主题刷新失败: {exc}")
            else:
                dirty.add(id(page))
        self._theme_dirty_pages = dirty

        # ⚠️ 顺手把各页面滚动区视口标成"不透明"（见 make_scroll_areas_opaque；填充色走调色板，幂等）
        self.apply_opaque_scrolls(pages)

        # 上面只覆盖 PAGE_ATTRS 里的页面，这里再补一遍整个窗口（含后来才建的插件页等）
        try:
            from ..utils.theme_utils import make_scroll_areas_opaque
            make_scroll_areas_opaque(self)
        except Exception:
            pass

        # 资源制作器是懒加载的，存在才刷
        maker = getattr(self, "resourceMakerInterface", None)
        refresh = getattr(maker, "refresh_theme", None)
        if callable(refresh) and maker is current:
            try:
                refresh()
            except Exception:
                pass
        elif maker is not None:
            dirty.add(id(maker))

        # AI 抽屉和悬浮球是自绘 / 内联样式，必须跟着换（很便宜，~10ms）
        try:
            if hasattr(self, "ai_chat_drawer"):
                self.ai_chat_drawer.apply_theme()
            if hasattr(self, "ai_floating_button"):
                self.ai_floating_button.refresh_theme()
        except Exception as exc:
            log.err("主题", "theme", f"AI 面板主题刷新失败: {exc}")

        # 托盘右键菜单也是自绘样式表 + 按主题取色的图标（见 ui/tray_menu.py）
        try:
            menu = getattr(self, "tray_menu", None)
            if menu is not None:
                menu.refresh_theme()
        except Exception as exc:
            log.err("主题", "theme", f"托盘菜单主题刷新失败: {exc}")

    def _refresh_page_theme_if_dirty(self, page):
        """切到某个页面时，如果它欠着一次"主题刷新"，在这里补上"""
        dirty = getattr(self, "_theme_dirty_pages", None)
        if not dirty or page is None:
            return
        if id(page) not in dirty:
            return
        dirty.discard(id(page))
        refresh = getattr(page, "refresh_theme", None)
        if callable(refresh):
            try:
                refresh()
            except Exception as exc:
                log.err("主题", "theme", f"页面主题刷新失败: {exc}")

    def _on_hotkey_activated(self, name: str):
        """收到全局热键"""
        if name == "ai":
            self.show_ai()
        else:
            self.show_search_box()

    def show_ai(self):
        """呼出 GCP-AI（全局快捷键 / 托盘「呼出AI」）：把窗口拉到最前，再按**当前模式**打开。
        ⚠️ 不能无条件 attach 悬浮球：侧边栏 AI 模式下球本来就隐藏，再挂一次就会凭空冒出
        一个球，所以侧边栏模式只切到 AI 整页界面，普通模式才挂球 + 滑出抽屉。
        """
        self._bring_to_front()
        button = getattr(self, "ai_floating_button", None)

        # 没开启过就先打开开关，保证按了键一定看得见
        if not self.settings_manager.settings.get("ai_enabled", False):
            self.settings_manager.update_setting("ai_enabled", True)
            if hasattr(self.settingsInterface, "ai_enable_switch"):
                self.settingsInterface.ai_enable_switch.blockSignals(True)
                self.settingsInterface.ai_enable_switch.setChecked(True)
                self.settingsInterface.ai_enable_switch.blockSignals(False)

        sidebar_mode = bool(self.settings_manager.settings.get(
            "ai_sidebar_mode", False))
        if sidebar_mode:
            # 侧边栏模式：切到 AI 整页界面并把光标送进输入框，不碰悬浮球
            page = getattr(self, "aiSidebarPage", None)
            if page is not None:
                self.switchTo(page)
                on_shown = getattr(page, "on_shown", None)
                if callable(on_shown):
                    QTimer.singleShot(80, on_shown)
            return

        if button is None:
            return
        # 按了热键说明用户现在要用，把"被关掉"的标记清掉（否则球不会再出现）
        self._ai_ball_suppressed = False
        button.attach()
        # 等窗口置前 + 球挂好，再滑出抽屉并聚焦输入框
        QTimer.singleShot(80, lambda: self.open_ai_drawer(focus=True))

    def toggle_ai_drawer(self):
        """悬浮球点击：抽屉开着就收起，收着就展开（球始终留在右下角）"""
        drawer = getattr(self, "ai_chat_drawer", None)
        if drawer is None:
            return
        if drawer.is_open():
            drawer.close_drawer()
        else:
            self.open_ai_drawer(focus=True)

    def _install_ai_shortcuts(self):
        """窗口内快捷键：用 QShortcut（窗口级）而不是全局热键，Ctrl+J 只该在 ToolsGCP 前台时
        生效。⚠️ QShortcut 的父对象必须是窗口且要保留引用，不保存的话对象会被回收、快捷键失效。
        """
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence

        self._shortcuts = []
        for keys, handler in (
            ("Ctrl+J", self.new_ai_chat),          # 新建 AI 对话
            ("Ctrl+Shift+J", self.open_ai_drawer),  # 顺手：只把抽屉叫出来
        ):
            try:
                shortcut = QShortcut(QKeySequence(keys), self)
                shortcut.activated.connect(handler)
                self._shortcuts.append(shortcut)
            except Exception as e:
                log.err("快捷键", "shortcut", f"注册 {keys} 失败: {e}")

    def open_ai_drawer(self, focus: bool = True):
        """滑出 AI 抽屉：打开时把悬浮球藏起来（露着会跟界面打架），收起时由抽屉的 on_close
        钩子把球放回来（球是开抽屉的唯一入口）。⚠️ 顺序是特意排的：apply_theme() 会给整棵
        控件树 setStyleSheet（全局 polish，几十毫秒起步），排在动画前就会"点下去先顿一下"。
        """
        drawer = getattr(self, "ai_chat_drawer", None)
        if drawer is None:
            return
        # ⚠️ 侧边栏 AI 模式开着时不能滑出抽屉（会"悬浮球/抽屉/整页界面"三者并存），改成切到 AI 页
        if self.settings_manager.settings.get("ai_sidebar_mode", False):
            self._open_ai_sidebar_page()
            return
        drawer.sync_geometry()
        drawer.open_drawer()
        drawer.raise_()
        QTimer.singleShot(0, drawer.apply_theme)
        if focus:
            QTimer.singleShot(SLIDE_FOCUS_DELAY_MS, drawer.focus_input)

    def close_ai_drawer(self):
        drawer = getattr(self, "ai_chat_drawer", None)
        if drawer is not None and drawer.is_open():
            drawer.close_drawer()

    def toggle_ai_floating_button(self, enabled):
        """设置 → AI 开关改变时调用，控制悬浮球（以及抽屉）的显示"""
        if not hasattr(self, "ai_floating_button"):
            return
        # ⚠️ 顺序很关键：先记下"用户要的开关状态"再动球 —— 收起抽屉的延时回调会问窗口
        #    "现在该不该显示球"，而那时设置可能还没写盘，只信 settings 就会"功能关了球又冒出来"。
        self._ai_ball_suppressed = not bool(enabled)
        if enabled:
            # 侧边栏 AI 模式下一律不挂球（那个模式的设计就是"没有悬浮球"）
            if not self.settings_manager.settings.get("ai_sidebar_mode", False):
                self.ai_floating_button.attach()
        else:
            # 关掉 GCP-AI 时，抽屉也要跟着收起，否则会留下一个开着却打不开的面板
            self.close_ai_drawer()
            self.ai_floating_button.detach()

    def _set_ai_ball_visible(self, visible: bool):
        """显示 / 隐藏悬浮球（抽屉开关时会调）：⚠️ `_ai_ball_suppressed`（用户刚把 AI 关掉）
        和 settings 的 ai_enabled 都为"开"才显示球；侧边栏 AI 模式打开时永远不显示球。
        """
        if not hasattr(self, "ai_floating_button"):
            return
        if visible:
            if getattr(self, "_ai_ball_suppressed", False):
                return
            if not self.settings_manager.settings.get("ai_enabled", False):
                return
            if self.settings_manager.settings.get("ai_sidebar_mode", False):
                self.ai_floating_button.hide()
                return
            # 从隐藏状态回来就播一次出现动画，不然是"啪"一下蹦出来
            if not self.ai_floating_button.isVisible():
                self.ai_floating_button.attach()
            else:
                self.ai_floating_button.show()
                self.ai_floating_button.raise_()
        else:
            self.ai_floating_button.hide()

    # ---------- 侧边栏 AI 模式 ----------
    def apply_ai_sidebar_mode(self, enabled: bool):
        """打开 / 关闭「改用侧边栏 AI 单独界面」：打开后左侧栏出现「AI」页（固定在 GCP工坊
        下面），悬浮球消失、抽屉不再是入口。
        """
        enabled = bool(enabled)
        page = getattr(self, "aiSidebarPage", None)
        if page is None:
            return

        route = page.objectName()
        # 1) 侧栏条目：显示 / 隐藏，第一次开启时按"紧跟 GCP工坊"插进去。⚠️ `NavigationInterface.items`
        #    是要时才建的内部字典，取不到工坊条目会返回 -1 把页面插到最顶部，所以先插末尾再挪。
        item = getattr(self, "ai_nav_item", None)
        if item is None:
            try:
                item = self.navigationInterface.addItem(
                    route, FIF.ROBOT,
                    self.language_manager.get_text("nav", "ai_page"),
                    onClick=lambda _checked=False: self._open_ai_sidebar_page(),
                    selectable=True,
                    position=NavigationItemPosition.TOP,
                    tooltip=self.language_manager.get_text("nav", "ai_page"))
                self.ai_nav_item = item
                self._move_ai_item_below_workshop()
            except Exception as exc:
                log.err("AI", "sidebar", f"插入侧栏 AI 条目失败: {exc}")
                return
        item.setVisible(enabled)

        # 2) 悬浮球：这个模式下一律不显示
        if enabled:
            try:
                self.ai_floating_button.detach()
            except Exception:
                pass
            # 抽屉正开着就先收起来，避免和整页界面同时出现
            drawer = getattr(self, "ai_chat_drawer", None)
            if drawer is not None and drawer.is_open():
                drawer.close_drawer()
        else:
            # 关掉这个模式：按当前配置把球放回来
            self._set_ai_ball_visible(True)

        log.op("AI", "sidebar_mode", 状态="开启" if enabled else "关闭")

    def _move_ai_item_below_workshop(self):
        """把左边栏里的 AI 条目挪到「GCP工坊」**下面**：`addItem` 只会往末尾追加，所以改用
        `insertItem` 按工坊下标插入；下标拿不到时用"顶部区末尾"兜底 —— AI 是最后加进去的，
        落点同样在 GCP工坊下面。
        """
        nav = self.navigationInterface
        item = getattr(self, "ai_nav_item", None)
        page = getattr(self, "aiSidebarPage", None)
        if item is None or page is None:
            return
        key = page.objectName()
        try:
            items = getattr(nav, "items", None)
            keys = list(items.keys()) if isinstance(items, dict) else []
            workshop = self.workshopInterface.objectName()
            if workshop in keys:
                index = keys.index(workshop) + 1
            else:
                index = len(keys)                     # 找不到工坊：放末尾
            # insertItem 会替换掉同 routeKey 的旧条目，所以先移除再加回
            if key in keys:
                nav.removeWidget(nav.widget(key))
            nav.insertItem(
                index, key, FIF.ROBOT,
                self.language_manager.get_text("nav", "ai_page"),
                onClick=lambda _checked=False: self._open_ai_sidebar_page(),
                selectable=True,
                position=NavigationItemPosition.TOP,
                tooltip=self.language_manager.get_text("nav", "ai_page"))
            self.ai_nav_item = nav.widget(key)
        except Exception as exc:
            log.err("AI", "sidebar", f"调整 AI 条目位置失败: {exc}")

    def _workshop_nav_index(self) -> int:
        """「GCP工坊」在顶部导航里的下标（找不到就返回 -1）：⚠️ `NavigationInterface.items`
        是要时才建的内部字典，**不要直接点它**（没建过就没这个属性，实测 AttributeError）。
        """
        items = getattr(self.navigationInterface, "items", None)
        if not isinstance(items, dict):
            return -1
        key = self.workshopInterface.objectName()
        keys = list(items.keys())
        if key not in keys:
            return -1
        return keys.index(key)

    def _open_ai_sidebar_page(self):
        """切到左侧栏那个 AI 整页界面"""
        page = getattr(self, "aiSidebarPage", None)
        if page is None:
            return
        if self.stackedWidget.indexOf(page) < 0:
            self.stackedWidget.addWidget(page)
        self.switchTo(page)
        try:
            page.on_shown()
        except Exception as exc:
            log.err("AI", "sidebar", f"打开 AI 页失败: {exc}")

    def new_ai_chat(self):
        """Ctrl+J：开一个新对话（AI 抽屉没开就先打开）"""
        drawer = getattr(self, "ai_chat_drawer", None)
        if drawer is None:
            return
        if not drawer.is_open():
            self.open_ai_drawer(focus=True)
        drawer.new_chat()

    def _open_plugin_center(self):
        """首页的"推荐插件"卡片 / 「打开插件中心」按钮 → 切到插件页"""
        self.switchTo(self.pluginInterface)
        self.navigationInterface.setCurrentItem(self.pluginInterface.objectName())

    # ========== 左侧栏「更多」菜单 ==========
    def more_menu_pages(self) -> list:
        """「更多」菜单里的页面条目：[(图标, 文案, 页面), ...]，顺序即菜单从上到下。要加新
        条目只改这一处（菜单构建、点击跳转、图标取用都读它）。⚠️「应用部署」已不在左侧栏，
        改成这里的一条；「提交软件」走懒建分支，不在这里。
        """
        nav = self.language_manager.get_text
        return [
            (FIF.FEEDBACK, nav("nav", "feedback"), self.feedbackInterface),
            (FIF.DOCUMENT, nav("nav", "log"), self.logInterface),
            (FIF.LIBRARY, nav("nav", "deploy"), self.deployInterface),
            (FIF.APPLICATION, nav("nav", "plugins"), self.pluginInterface),
        ]

    def more_menu_entries(self) -> list:
        """「更多」菜单的完整条目：[(图标, 文案, 打开函数), ...]，「提交软件」固定在最下面"""
        entries = [(icon, text, (lambda p=page: self._open_more_page(p)))
                   for icon, text, page in self.more_menu_pages()]
        entries.append((
            FIF.UP,
            self.language_manager.get_text("nav", "submit_software"),
            self._open_resource_maker))
        return entries

    def show_more_menu(self):
        """弹「更多」圆角菜单（RoundMenu；条目 = 图标 + 文字，点它跳到对应页面）"""
        menu = RoundMenu(parent=self)
        for icon, text, opener in self.more_menu_entries():
            action = QAction(icon.icon(), text, menu)
            action.triggered.connect(lambda _checked=False, fn=opener: fn())
            menu.addAction(action)

        # 贴着「更多」按钮的**右侧**弹出（左侧栏是竖条，往左会顶到屏幕外）
        pos = self._more_menu_position(menu)
        menu.exec_(pos, ani=True)

    def _more_menu_position(self, menu):
        """算出菜单该弹在哪个屏幕坐标：⚠️ 用"窗口左上角的屏幕坐标 + 条目在窗口内的坐标"
        自己加，不要对导航条目调 mapToGlobal() —— 条目在滚动容器里，某些状态下会给出明显
        不合理的结果。
        """
        menu.adjustSize()
        item = self.more_nav_item
        origin = self.mapToGlobal(QPoint(0, 0))
        base_x = origin.x() + item.x() + item.width() - 4
        base_y = origin.y() + item.y()

        screen = QApplication.primaryScreen()
        if screen is None:
            return QPoint(base_x, base_y)
        avail = screen.availableGeometry()
        x = min(base_x, avail.right() - menu.width() - 12)
        y = min(base_y, avail.bottom() - menu.height() - 12)
        return QPoint(max(avail.left() + 12, x), max(avail.top() + 12, y))

    def _more_page_set(self) -> set:
        """「更多」菜单底下那些页面（它们共用左侧栏「更多」那一条高亮）"""
        pages = set()
        for _icon, _text, page in self.more_menu_pages():
            pages.add(id(page))
        page = getattr(self, "resourceMakerInterface", None)
        if page is not None:
            pages.add(id(page))
        return pages

    def _sync_more_indicator(self, interface):
        """切到「更多」里的任意页面时，把左侧栏的高亮**钉在「更多」上**：⚠️ 菜单里的页面在
        导航栏里**没有自己的条目**，setCurrentItem 查不到 routeKey 会直接返回、不改高亮，
        所以在这里显式把高亮挪到「更多」按钮上。
        """
        if interface is None:
            return
        try:
            if id(interface) in self._more_page_set():
                self.navigationInterface.setCurrentItem("moreToolsGCP")
        except Exception:
            pass

    def _open_more_page(self, page):
        """「更多」菜单里点了一项：切到那一页（和点左侧栏是同一条路径）"""
        if page is None:
            return
        self._show_more_page(page)

    def _show_more_page(self, page):
        """把某个「更多」页面放到前台：兜底 —— 页面不在 stackedWidget 里就先补进去再切，
        否则 switchTo 会静默失败。
        """
        if self.stackedWidget.indexOf(page) < 0:
            self.stackedWidget.addWidget(page)
        self.switchTo(page)
        # ⚠️ 切页可能被"API Key 未保存"拦下；那种情况页面没换，就不要再把侧栏高亮往「更多」挪
        if self.stackedWidget.currentWidget() is not page:
            return
        self._sync_more_indicator(page)
        # 页面自己想在"被打开时"刷新一下（比如重新读一遍资源库）
        on_shown = getattr(page, "on_shown", None)
        if callable(on_shown):
            try:
                on_shown()
            except Exception as exc:
                log.err("页面", "switch", f"页面 on_shown 失败: {exc}")

    def resource_maker_page(self):
        """「提交软件」页面（资源制作器）：第一次用到才建 —— 它带着一整套投稿表单、资源表格、
        批量合成面板，而用户可能一整轮都不点它。
        """
        page = getattr(self, "resourceMakerInterface", None)
        if page is not None:
            return page
        try:
            from ..interfaces.resource_maker_interface import ResourceMakerInterface
        except Exception as exc:
            log.err("启动", "startup", f"资源制作器页面加载失败: {exc}")
            return None
        try:
            page = ResourceMakerInterface(self.language_manager,
                                          self.settings_manager, self)
        except Exception as exc:
            log.err("启动", "startup", f"资源制作器页面创建失败: {exc}")
            return None
        page.setObjectName("resourceMakerInterface")
        self.resourceMakerInterface = page
        if self.stackedWidget.indexOf(page) < 0:
            self.stackedWidget.addWidget(page)
        # 这一页是懒建的：建完立刻补一次"滚动视口不透明"（见 apply_opaque_scrolls）
        try:
            self.apply_opaque_scrolls([page])
        except Exception:
            pass
        return page

    def _open_resource_maker(self):
        """左侧栏「更多 → 提交软件」：打开资源制作器页面"""
        page = self.resource_maker_page()
        if page is None:
            InfoBar.warning(
                title=self.language_manager.get_text("nav", "submit_software"),
                content=self.language_manager.get_text(
                    "nav", "resource_maker_load_failed"),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self)
            return
        self._show_more_page(page)

    def add_plugin_to_home(self):
        """插件装好/删掉之后，让首页的推荐列表跟上（插件页调它）"""
        try:
            if hasattr(self, "homeInterface"):
                self.homeInterface.refresh_plugins()
        except Exception as exc:
            log.err("插件", "home", f"刷新首页推荐插件失败: {exc}")

    def mention_to_ai(self, name: str, code: str = ""):
        """卡片上的「@给AI」：把 @名称(编码) 追加到 AI 输入框末尾（GCP-AI 关着也能用，顺手把
        开关打开）。⚠️ 两种入口都要照顾：普通模式开右侧抽屉，侧边栏 AI 模式切到 AI 整页界面。
        """
        if not self.settings_manager.settings.get("ai_enabled", False):
            self.settings_manager.update_setting("ai_enabled", True)
            if hasattr(self.settingsInterface, "ai_enable_switch"):
                self.settingsInterface.ai_enable_switch.blockSignals(True)
                self.settingsInterface.ai_enable_switch.setChecked(True)
                self.settingsInterface.ai_enable_switch.blockSignals(False)

        # 侧边栏 AI 模式：切到 AI 页并把 @ 文本写进去
        if self.settings_manager.settings.get("ai_sidebar_mode", False):
            page = getattr(self, "aiSidebarPage", None)
            if page is not None:
                self._open_ai_sidebar_page()
                QTimer.singleShot(0, lambda: page.insert_mention(name, code))
                return

        self._ai_ball_suppressed = False
        if hasattr(self, "ai_floating_button"):
            self.ai_floating_button.attach()

        drawer = getattr(self, "ai_chat_drawer", None)
        if drawer is None:
            return
        self.open_ai_drawer(focus=False)
        # 等抽屉滑到位再把 @ 文本写进输入框，否则聚焦会被动画打断
        QTimer.singleShot(SLIDE_FOCUS_DELAY_MS,
                          lambda: drawer.insert_mention(name, code))

    def _notify_hotkey_error(self):
        """把注册失败的原因告诉用户（窗口显示后再弹，避免启动瞬间弹在空窗口上）"""
        if not self._hotkey_error:
            return
        message = self._hotkey_error
        self._hotkey_error = None
        InfoBar.warning(
            title=self.language_manager.get_text("settings", "hotkey_register_failed"),
            content=message,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self
        )

    def show_search_box(self):
        """呼出搜索框：把主窗口拉到最前，切到搜索页并聚焦输入框"""
        self._bring_to_front()
        self.switchTo(self.searchInterface)
        self.navigationInterface.setCurrentItem(self.searchInterface.objectName())
        # 窗口从后台切到前台、页面切换都需要一点时间，补几次聚焦确保一定命中
        for delay in (0, 60, 160):
            QTimer.singleShot(delay, self.searchInterface.focus_search_box)

    def _open_resource_detail(self, data: dict):
        """从其它页面（如收藏页）点卡片时，切到搜索页并打开详情"""
        self.switchTo(self.searchInterface)
        self.navigationInterface.setCurrentItem(self.searchInterface.objectName())
        self.searchInterface.show_detail_page(data or {})

    def switchTo(self, interface):
        """切页面（统一在这里记一条操作日志，任何入口切换都会被记到）：⚠️ 这里不再调
        `_confirm_leave_settings`（那个拦切页的弹窗已按需求删除，关闭程序时的提示仍保留，
        见 closeEvent），但要兜住 _sync_more_indicator。
        """
        result = None
        try:
            name = interface.objectName() if interface is not None else "?"
            if getattr(self, "stackedWidget", None) is not None \
                    and self.stackedWidget.currentWidget() is interface:
                result = super().switchTo(interface)
                self._sync_more_indicator(interface)
                return result
            log.op("页面", "switch", page=self._page_name(name))
        except Exception:
            pass

        try:
            result = super().switchTo(interface)
        except Exception:
            raise

        self._sync_more_indicator(interface)
        # 这一页如果欠着一次"主题刷新"（切主题时它没在台前），在这里补上
        self._refresh_page_theme_if_dirty(interface)
        return result

    def _confirm_leave_settings(self, interface) -> bool:
        """离开设置页之前，检查 API Key 有没有"改了没保存"，返回 False = 留在设置页。⚠️ 已经
        不再被 switchTo 调用（那个拦截弹窗已按需求删除），方法留着是为了以后恢复拦截时有
        现成逻辑，以及工具 / 自检脚本按名字找它。
        """
        settings = getattr(self, "settingsInterface", None)
        if settings is None or interface is None or interface is settings:
            return True
        try:
            if self.stackedWidget.currentWidget() is not settings:
                return True     # 本来就不在设置页，没什么可拦的
            confirm = getattr(settings, "confirm_leave_api_key", None)
            if not callable(confirm) or not settings.api_key_unsaved():
                return True
            return bool(confirm(self))
        except Exception:
            return True

    @staticmethod
    def _page_name(object_name: str) -> str:
        return {
            "searchInterface": "搜索",
            "homeInterface": "首页",
            "customizeInterface": "定制页",
            "toolsGCPInterface": "收藏",
            "deployInterface": "应用部署",
            "githubInterface": "Github",
            "logInterface": "查看日志",
            "feedbackInterface": "反馈",
            "settingsInterface": "设置",
            "pluginInterface": "插件",
            "resourceMakerInterface": "提交软件",
        }.get(object_name, object_name)

    def _bring_to_front(self):
        """把窗口恢复到前台，并且**真的抬到所有普通窗口之上**：⚠️ 光有 activateWindow() 不够
        —— `raise_()` 管不着别的进程，`SetForegroundWindow` 在调用进程不是前台进程时会被
        Windows 的**前台锁**拒绝（错误码 0）。下面 ShowWindow 还原 + AttachThreadInput 骗过
        前台锁 + SetWindowPos(TOPMOST→NOTOPMOST)，三招缺一不可。
        """
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = int(self.winId())

            SW_RESTORE = 9
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_SHOWWINDOW = 0x0040
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW

            user32.ShowWindow(hwnd, SW_RESTORE)

            # 前台锁：把输入队列挂到当前前台线程上再请求前台
            foreground = user32.GetForegroundWindow()
            target_thread = user32.GetWindowThreadProcessId(foreground, None)
            current_thread = kernel32.GetCurrentThreadId()
            attached = False
            if target_thread and target_thread != current_thread:
                attached = bool(user32.AttachThreadInput(
                    target_thread, current_thread, True))

            # 先置顶再取消置顶 = 抬到普通窗口的最上面（不留永久置顶的副作用）
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)

            if attached:
                user32.AttachThreadInput(target_thread, current_thread, False)
        except Exception as e:
            log.err("窗口", "window", f"窗口置前失败: {e}")
    
    def quit_app(self):
        """退出应用"""
        try:
            self.hotkey_manager.unregister()
        except Exception:
            pass
        if self.tray_icon:
            self.tray_icon.hide()
        QApplication.quit()
    
    def get_actual_theme(self, theme_setting):
        """获取实际主题"""
        if theme_setting == "跟随系统":
            return detect_system_theme()
        return theme_setting
    
    def showEvent(self, event):
        super().showEvent(event)

        # 开机自启 + 托盘：等窗口真正显示出来之后再收起，避免提前隐藏导致窗口再也不出现
        if self._hide_after_first_show:
            self._hide_after_first_show = False
            log.info("启动", "startup", "窗口已显示 → 收起主窗口到托盘")
            QTimer.singleShot(0, self.hide)

        if not self._theme_fixed:
            self._theme_fixed = True
            saved_theme = self.settings_manager.settings.get("theme", "跟随系统")
            actual_theme = self.get_actual_theme(saved_theme)
            if actual_theme == "深色主题":
                QTimer.singleShot(100, fix_dark_theme_titlebar)

        # 全局快捷键注册失败的原因，等窗口真正显示出来再提示
        if self._hotkey_error:
            QTimer.singleShot(600, self._notify_hotkey_error)

        # 首次显示后检查隐私政策同意
        if not self._privacy_checked:
            self._privacy_checked = True
            QTimer.singleShot(200, self._check_privacy_consent)

        # 拉一次公告（窗口站稳之后；只排一次，showEvent 可能被多次调用）
        if not self._announcements_started:
            self._announcements_started = True
            QTimer.singleShot(ANNOUNCEMENT_FETCH_DELAY_MS,
                              self.start_announcements)

    def _check_privacy_consent(self):
        """检查隐私政策同意状态，未同意则弹窗"""
        data = self.privacy_manager.load_or_create()
        if self.privacy_manager.is_consent_valid(data):
            return

        # 未同意：显示遮罩 + 弹窗
        self._show_privacy_mask()
        # 协议窗开着的时候，公告弹窗先让路（它俩都是遮罩式弹窗，叠一起很难看）
        self._privacy_prompt_active = True
        dlg = PrivacyConsentDialog(self.privacy_manager, self)
        result = dlg.exec_()
        self._privacy_prompt_active = False
        self._destroy_privacy_mask()

        # 协议处理完了：如果之前因为它在场而没弹成「新公告」，这里补一次
        self._announcement_popup_retry = 0
        QTimer.singleShot(ANNOUNCEMENT_POPUP_DELAY_MS,
                          self._maybe_show_announcement_popup)

        if result == PrivacyConsentDialog.Accepted:
            # 同意后重新应用 qfluentwidgets 主题，修复模态对话框导致的组件颜色异常
            saved_theme = self.settings_manager.settings.get("theme", "跟随系统")
            actual_theme = self.get_actual_theme(saved_theme)
            setTheme(Theme.DARK if actual_theme == "深色主题" else Theme.LIGHT,
                     lazy=True)
        else:
            # 拒绝并退出
            log.info("启动", "startup", "用户拒绝隐私协议 → 退出程序")
            QTimer.singleShot(100, self.quit_app)

    def _show_privacy_mask(self):
        """显示半透明变暗遮罩"""
        self._destroy_privacy_mask()
        self._privacy_mask = PrivacyMaskOverlay(self)
        self._privacy_mask.setGeometry(self.rect())
        self._privacy_mask.raise_()
        self._privacy_mask.show()

    def _destroy_privacy_mask(self):
        """彻底销毁遮罩层，避免任何视觉残留"""
        if self._privacy_mask is not None:
            self._privacy_mask.hide()
            self._privacy_mask.deleteLater()
            self._privacy_mask = None
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "ai_floating_button") and self.ai_floating_button.isVisible():
            self.ai_floating_button.update_position()
        # 抽屉跟着窗口大小走（宽度固定，高度和位置要重算）
        drawer = getattr(self, "ai_chat_drawer", None)
        if drawer is not None:
            drawer.sync_geometry()
    
    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "ai_floating_button") and self.ai_floating_button.isVisible():
            self.ai_floating_button.update_position()
    
    def handle_search(self, text):
        """处理搜索（只记关键词 + 弹提示，不回填到搜索框）"""
        if text:
            self.settings_manager.update_setting("last_search", text)
            log.info("搜索", "search", f"用户输入关键词: {text}")
            InfoBar.info(
                title=self.language_manager.get_text("search", "search_title"),
                content=f'{self.language_manager.get_text("search", "searching")}: {text}',
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=1500,
                parent=self
            )
    
    def center_window(self):
        """窗口居中"""
        screen = QApplication.primaryScreen().availableGeometry()
        size = self.geometry()
        self.move((screen.width() - size.width()) // 2, 
                 (screen.height() - self.height()) // 2)
    
    def closeEvent(self, event):
        """关闭事件：⚠️ 先拦一道 —— 设置页 API Key 改了没保存要提示，用户选留下就不关"""
        settings = getattr(self, "settingsInterface", None)
        if settings is not None and not self._closing_confirmed:
            try:
                if settings.api_key_unsaved():
                    confirm = getattr(settings, "confirm_leave_api_key", None)
                    if callable(confirm) and not confirm(self):
                        event.ignore()
                        return
                    self._closing_confirmed = True
            except Exception:
                pass

        close_mode = self.settings_manager.settings.get("close_mode", "彻底退出")

        # 公告还在后台拉的话等它一下：线程没结束就跟着窗口被析构，Qt 会直接 abort（关窗口时崩一下）
        try:
            self.noticeInterface.shutdown()
        except Exception:
            pass

        if close_mode == "隐藏到托盘中":
            log.info("窗口", "window", "关闭窗口 -> 隐藏到托盘")
            self.hide()
            if self.tray_icon is None:
                self.show_tray_icon()
            self.tray_icon.showMessage("ToolsGCP",
                                     self.language_manager.get_text("nav", "hidden_to_tray"),
                                     QSystemTrayIcon.Information, 2000)
            event.ignore()
        else:
            log.info("窗口", "window", "关闭窗口 -> 彻底退出")
            if self.tray_icon:
                self.tray_icon.hide()
            super().closeEvent(event)