"""设置页的卡片与回调（cards_ui：外观 / 启动 / 搜索 / 快捷键）。

通过 mixin 组合进 SettingsInterface，方法里用到的 self.xxx 都在主类里。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFrame, QScrollArea)
from PyQt5.QtGui import QFont, QIntValidator
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
from ...utils.smooth_scroll import install_smooth_scroll
from ...utils.system_utils import (set_windows_autostart, restart_program,
                                   detect_system_theme, detect_system_language)
from ...utils.theme_utils import is_dark_mode, apply_app_palette
from ...constants import VALID_GCP_KEYS, DEV_KEYS, SPECIAL_KEYS, SOURCE_OPTIONS

from .texts import FALLBACK_TEXTS
from .common import (DISABLED_TEXT_COLOR, DEFAULT_TEXT_LIGHT, DEFAULT_TEXT_DARK,
                     PAGE_ORDER, HOTKEY_DEFAULTS)
from .theme import CONTROL_WIDTH
from .widgets import (SettingCard, SettingRow, install_wheel_step)


class SettingsCardsUiMixin:
    def _create_appearance_card(self):
        """创建外观设置卡片（不画行间分割线；说明文字改成标题悬浮提示）。

        需求：外观区域去除所有提示和分割线，提示和别的区域一样鼠标悬浮阅读，不搞特例。
        """
        card = SettingCard(divider=False)

        self.theme_combo = ComboBox()
        self.theme_combo.addItems(self.get_theme_options())
        saved_theme = self.settings_manager.settings.get("theme", "跟随系统")
        theme_value_map = {"跟随系统": 0, "浅色主题": 1, "深色主题": 2}
        self.theme_combo.setCurrentIndex(theme_value_map.get(saved_theme, 0))
        self.theme_combo.setFixedWidth(CONTROL_WIDTH)
        self.theme_combo.currentIndexChanged.connect(self.change_theme)
        card.add_row(SettingRow(self.get_text("theme_mode"), self.theme_combo,
                                hint=self.get_text("theme_mode_desc")))

        # 组件配色（蓝 / 紫 / Claude 橙）：改的是"强调色 + 品牌渐变"，位置在主题模式和语言之间
        self.accent_combo = ComboBox()
        self.accent_combo.addItem(self.get_text("accent_blue"), userData="blue")
        self.accent_combo.addItem(self.get_text("accent_purple"), userData="purple")
        self.accent_combo.addItem(self.get_text("accent_orange"), userData="orange")
        self.accent_combo.setFixedWidth(CONTROL_WIDTH)
        self.sync_accent_combo()
        self.accent_combo.currentIndexChanged.connect(self.change_accent_color)
        card.add_row(SettingRow(self.get_text("accent_color"), self.accent_combo,
                                hint=self.get_text("accent_color_desc")))

        self.language_combo = ComboBox()
        self.language_combo.addItems(self.get_language_options())
        saved_lang = self.settings_manager.settings.get("language", "跟随系统")
        lang_value_map = {"跟随系统": 0, "简体中文": 1, "繁體中文": 2, "English": 3}
        self.language_combo.setCurrentIndex(lang_value_map.get(saved_lang, 0))
        self.language_combo.setFixedWidth(CONTROL_WIDTH)
        self.language_combo.currentIndexChanged.connect(self.change_language)
        card.add_row(SettingRow(self.get_text("language"), self.language_combo,
                                hint=self.get_text("language_desc")))

        # 字体：列表来自系统已安装字体（见 utils/fonts.py），选中后立刻铺到全程序
        # ⚠️ 已经没有"跟随系统"这一项：默认就是候选表里第一个装得上的无衬线字体（微软雅黑 → 等线 → Segoe UI）
        from ...utils.fonts import (apply_font, available_fonts,
                                    dark_default_family)
        self.font_combo = ComboBox()
        for value, label in available_fonts():
            self.font_combo.addItem(label, userData=value)
        # 默认选中"默认字体"那一条：userData 存的是**族名**，不是显示文字
        self._font_index = max(0, self.font_combo.findData(dark_default_family()))
        self.font_combo.setCurrentIndex(self._font_index)
        # ⚠️ 字体下拉框和同卡片里其它控件一样宽（CONTROL_WIDTH，200px）
        self.font_combo.setFixedWidth(CONTROL_WIDTH)
        # 下拉框里字体很多（上百个），给个搜索/限高，别铺成一整屏
        self.font_combo.setMaxVisibleItems(14)
        self.font_combo.currentIndexChanged.connect(self.change_font)
        card.add_row(SettingRow(self.get_text("ui_font"), self.font_combo,
                                hint=self.get_text("ui_font_desc")))

        self.splash_enable_switch = SwitchButton()
        splash_enabled = self.settings_manager.settings.get("splash_screen_enabled", True)
        self.splash_enable_switch.setChecked(splash_enabled)
        self.splash_enable_switch.checkedChanged.connect(self.change_splash_screen_enabled)
        card.add_row(SettingRow(self.get_text("splash_screen"),
                                self.splash_enable_switch,
                                hint=self.get_text("splash_screen_tip"),
                                control_width=None))

        # 启动动画时长（与开关联动：关闭时锁起来）
        try:
            splash_duration_raw = self.settings_manager.settings.get("splash_screen_duration", 2)
            splash_duration_value = int(splash_duration_raw)
            if splash_duration_value < 1:
                splash_duration_value = 1
            elif splash_duration_value > 5:
                splash_duration_value = 5
        except (ValueError, TypeError):
            splash_duration_value = 2
            self.settings_manager.update_setting("splash_screen_duration", 2)

        duration_box = QWidget()
        duration_layout = QHBoxLayout(duration_box)
        duration_layout.setContentsMargins(0, 0, 0, 0)
        duration_layout.setSpacing(8)

        self.splash_duration_slider = Slider(Qt.Horizontal)
        self.splash_duration_slider.setRange(1, 5)
        self.splash_duration_slider.setValue(splash_duration_value)
        self.splash_duration_slider.setFixedWidth(150)
        self.splash_duration_slider.valueChanged.connect(self.on_splash_duration_slider_changed)
        duration_layout.addWidget(self.splash_duration_slider)

        self.splash_duration_input = LineEdit()
        self.splash_duration_input.setText(str(splash_duration_value))
        self.splash_duration_input.setFixedWidth(46)
        self.splash_duration_input.setAlignment(Qt.AlignCenter)
        self.splash_duration_input.setValidator(QIntValidator(1, 5))
        self.splash_duration_input.textChanged.connect(self.on_splash_duration_input_changed)
        duration_layout.addWidget(self.splash_duration_input)

        self.splash_duration_second_label = QLabel(self.get_text("seconds"))
        self.splash_duration_second_label.setObjectName("whiteInDarkLabel")
        duration_layout.addWidget(self.splash_duration_second_label)

        self.splash_duration_row = SettingRow(
            self.get_text("splash_screen_duration"), duration_box,
            hint=self.get_text("splash_screen_duration_tip"), control_width=None)
        card.add_row(self.splash_duration_row)

        # ⚠️ 滚轮一格只 ±1：滑块和右边的数字框都要装 —— Qt 默认滚一格跳 3（singleStep × 系统行数），
        #    而数字框干脆不响应滚轮
        install_wheel_step(self.splash_duration_slider,
                           self._nudge_splash_duration)
        install_wheel_step(self.splash_duration_input,
                           self._nudge_splash_duration)

        # 根据开关初始状态设置时长控件可用性
        self.update_splash_duration_state(splash_enabled)

        # ⚠️ 「搜索页卡片大小」这一项已按需求删除；卡片尺寸仍由 widgets/app_card.py 的 CARD_PRESETS 控制，
        #    搜索页现在提供的是"磁贴 / 网格"两种视图切换

        return card


    def _create_startup_card(self):
        """创建启动设置卡片"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        autostart_widget = QWidget()
        self.autostart_widget = autostart_widget
        autostart_layout = QHBoxLayout(autostart_widget)
        autostart_layout.setContentsMargins(0, 0, 0, 0)
        autostart_label = BodyLabel(self.get_text("startup_with_windows"))
        autostart_label.setObjectName("whiteInDarkLabel")
        autostart_layout.addWidget(autostart_label)
        autostart_layout.addStretch()
        
        self.autostart_switch = SwitchButton()
        self.autostart_switch.setChecked(self.settings_manager.settings.get("startup_with_windows", True))
        self.autostart_switch.checkedChanged.connect(self.change_autostart)
        autostart_layout.addWidget(self.autostart_switch)
        layout.addWidget(autostart_widget)
        
        tray_widget = QWidget()
        self.tray_widget = tray_widget
        tray_layout = QHBoxLayout(tray_widget)
        tray_layout.setContentsMargins(0, 0, 0, 0)
        
        self.tray_label = BodyLabel(self.get_text("minimize_to_tray"))
        self.tray_label.setObjectName("whiteInDarkLabel")
        
        self.tray_info_icon = QLabel("ⓘ")
        self.tray_info_icon.setObjectName("whiteInDarkIcon")
        self.tray_info_icon.setToolTip(self.get_text("minimize_to_tray_tip"))
        self.tray_info_icon.installEventFilter(ToolTipFilter(self.tray_info_icon, 300, ToolTipPosition.TOP))
        
        tray_layout.addWidget(self.tray_label)
        tray_layout.addWidget(self.tray_info_icon)
        tray_layout.addStretch()
        
        self.tray_switch = SwitchButton()
        self.tray_switch.setChecked(self.settings_manager.settings.get("minimize_to_tray", False))
        self.tray_switch.checkedChanged.connect(self.change_minimize_to_tray)
        tray_layout.addWidget(self.tray_switch)
        layout.addWidget(tray_widget)
        
        # 托盘开关跟随"开机自启动"：自启动关闭时整行置灰
        self.update_tray_state(self.autostart_switch.isChecked())
        
        page_widget = QWidget()
        page_layout = QHBoxLayout(page_widget)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_label = BodyLabel(self.get_text("default_page"))
        page_label.setObjectName("whiteInDarkLabel")
        page_layout.addWidget(page_label)
        page_layout.addStretch()
        
        self.page_combo = ComboBox()
        # 顺序与左侧导航栏一致，也必须和 common.PAGE_ORDER 逐项对应（下面用 PAGE_ORDER.index 回填，
        # 错一个位置就会选错页）
        self.page_combo.addItems([
            self.get_text("home_page_title"),
            self.get_text("search_title"),
            self.get_text("home_title"),
            self.get_text("tools_gcp_title"),
            self.get_text("deploy_title"),
            self.get_text("settings_title")
        ])

        # 下拉框顺序 → 配置中保存的页面键（内部键保持"部署"不变，兼容旧配置）
        saved_page = self.settings_manager.settings.get("default_page", "搜索")
        if saved_page in PAGE_ORDER:
            self.page_combo.setCurrentIndex(PAGE_ORDER.index(saved_page))
        else:
            self.page_combo.setCurrentIndex(0)
        self.page_combo.setFixedWidth(180)
        self.page_combo.currentIndexChanged.connect(self.change_default_page)
        page_layout.addWidget(self.page_combo)
        layout.addWidget(page_widget)

        return card


    def change_close_mode(self, index):
        mode = "彻底退出" if index == 0 else "隐藏到托盘中"
        self.settings_manager.update_setting("close_mode", mode)
        mode_text = self.close_mode_combo.currentText()
        self.show_message(f"{self.get_text('close_mode')}: {mode_text}", "success")


    def change_autostart(self, checked):
        self.settings_manager.update_setting("startup_with_windows", checked)
        self.update_tray_state(checked)
        
        if sys.platform == 'win32':
            success, error = set_windows_autostart(checked)
            if success:
                self.show_message(
                    self.get_text("autostart_enabled") if checked else self.get_text("autostart_disabled"), 
                    "success"
                )
            else:
                self.show_message(f"{self.get_text('autostart_failed')}: {error}", "error")
                self.autostart_switch.setChecked(not checked)


    def update_tray_state(self, enabled):
        """「启动时最小化到托盘」跟随「开机自启动」：关掉自启时整行隐藏（以前只是置灰，那行还杵在那儿）。"""
        self._sync_startup_rows()


    def change_minimize_to_tray(self, checked):
        self.settings_manager.update_setting("minimize_to_tray", checked)
        # 托盘开关关掉时把这一行的说明整块收起来（没有子行，淡出 / 恢复由 refresh 处理）
        self._sync_startup_rows()
        self.show_message(self.get_text("tray_enabled") if checked else self.get_text("tray_disabled"), "info")

    def _sync_startup_rows(self):
        """「启动时最小化到托盘」整行的可见性跟着「开机自启」联动。

        托盘那行只在"开机自启打开"时才有意义，自启关着就隐藏它，避免留一个看着能改却不会生效的开关。
        """
        autostart_on = bool(getattr(self, "autostart_switch", None)
                            and self.autostart_switch.isChecked())
        # 整行（含外面的容器）一起隐藏，避免留一条空白
        widget = getattr(self, "tray_widget", None)
        if widget is not None:
            widget.setVisible(autostart_on)
        for child in (getattr(self, "tray_label", None),
                      getattr(self, "tray_info_icon", None),
                      getattr(self, "tray_switch", None)):
            if child is not None:
                child.setVisible(autostart_on)
                child.setEnabled(True)


    def change_default_page(self, index):
        page = PAGE_ORDER[index] if 0 <= index < len(PAGE_ORDER) else "搜索"
        self.settings_manager.update_setting("default_page", page)
        self.show_message(f"{self.get_text('default_page')}: {self.page_combo.currentText()}", "success")


    # ---------- 字体（外观卡片） ----------
    def change_font(self, index):
        """换了界面字体：存配置 + 立刻铺到全程序。

        ⚠️ QApplication.setFont 只影响之后用默认字体创建 / 绘制的控件；已经建好的控件会在下一次
        style polish / 重绘时跟上（Qt 会给所有顶层窗口发 FontChange），所以不用重建任何页面。
        """
        from ...utils.fonts import apply_font
        family = self.font_combo.itemData(index)
        if family is None:
            family = ""
        self.settings_manager.update_setting("ui_font_family", family)
        applied = apply_font(family)
        name = self.font_combo.currentText()
        self.show_message(f"{self.get_text('ui_font')}: {name}", "success")
        try:
            from ...utils.logger import log
            log.op("设置", "font", 选择=name, 实际=applied or "跟随系统")
        except Exception:
            pass

    # ---------- 组件配色（外观卡片） ----------
    def sync_accent_combo(self):
        """把「组件配色」下拉框拨到配置里那一档（回填时不触发信号）"""
        combo = getattr(self, "accent_combo", None)
        if combo is None:
            return
        from .theme import DEFAULT_ACCENT_KEY
        key = str(self.settings_manager.settings.get("accent_color")
                  or DEFAULT_ACCENT_KEY)
        index = combo.findData(key)
        combo.blockSignals(True)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def change_accent_color(self, index):
        """换了组件配色（蓝 / 紫 / Claude 橙）。

        改两样东西：给 qfluentwidgets 的强调色（开关 / 下拉框 / 滑块 / 勾选框…）和本程序的品牌渐变
        （AI 悬浮球、用户气泡、发送按钮）；改完必须立刻刷到界面上，否则会"设置页变了、悬浮球还是旧的"。
        """
        from .theme import DEFAULT_ACCENT_KEY, apply_accent_color, set_accent_key
        key = self.accent_combo.itemData(index) or DEFAULT_ACCENT_KEY
        self.settings_manager.update_setting("accent_color", key)
        set_accent_key(key)

        dark = self.is_dark_mode()
        # lazy=True：只立刻重刷当前可见的控件，藏着的等画出来再补（省几百毫秒）
        apply_accent_color(dark, lazy=True)
        self.refresh_accent_everywhere(dark)

        self.show_message(f"{self.get_text('accent_color')}: "
                          f"{self.accent_combo.currentText()}", "success")

    def refresh_accent_everywhere(self, dark: bool = None):
        """把新的组件配色推到所有"已经建出来、又跟颜色有关"的地方"""
        if dark is None:
            dark = self.is_dark_mode()
        # 1) 设置页自己：左侧选中项 / 卡片徽标 / 行内强调色都取 token
        try:
            self.refresh_theme_styles()
        except Exception:
            pass

        window = self.main_window
        if window is None:
            return

        # 2) 聊天抽屉（气泡 / 发送按钮 / 链接色）
        #    ⚠️ AI 悬浮球不在这里了：需求要它"主题不变"（恒定蓝紫），换配色时不用重刷
        drawer = getattr(window, "ai_chat_drawer", None)
        if drawer is not None and hasattr(drawer, "apply_theme"):
            try:
                drawer.apply_theme(dark)
            except Exception:
                pass

        # 3) 搜索页卡片上"按强调色染的"图标（收藏图标）
        #    ⚠️ 只有搜索页正显示着才当场重染，否则记一个标记等它下次显示再刷（48 张重染实测 400~600ms）
        search = getattr(window, "searchInterface", None)
        if search is not None and hasattr(search, "refresh_theme"):
            try:
                if search.isVisible():
                    search.refresh_theme(force=True)
                elif hasattr(search, "mark_accent_dirty"):
                    search.mark_accent_dirty()
            except Exception:
                pass

        # 4) 其它页面的自制控件（插件页徽章 / 备注图标、首页按钮、收藏页）
        for name in ("pluginInterface", "homeInterface", "toolsGCPInterface",
                     "resourceMakerInterface"):
            page = getattr(window, name, None)
            fn = getattr(page, "refresh_theme", None) if page is not None else None
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass


    def change_splash_screen_enabled(self, checked):
        """启动动画开关状态改变"""
        self.settings_manager.update_setting("splash_screen_enabled", checked)
        self.update_splash_duration_state(checked)
        status = self.get_text("enabled") if checked else self.get_text("disabled")
        self.show_message(f"{self.get_text('splash_screen')}: {status}", "info")


    def update_splash_duration_state(self, enabled):
        """启动动画开关：关掉时把"启动动画时长"整行藏起来，开了再显示。

        ⚠️ 以前是置灰（set_control_enabled），现在改成真正的隐藏 —— 置灰那行还占着位置、像坏掉的控件。
        """
        row = getattr(self, "splash_duration_row", None)
        if row is not None:
            row.setVisible(bool(enabled))
        # 控件本身也一起置灰/启用，避免"行藏起来但值还能被键盘改"这类边界情况
        for widget in (self.splash_duration_slider,
                       self.splash_duration_input,
                       self.splash_duration_second_label):
            widget.setEnabled(bool(enabled))
            widget.setVisible(bool(enabled))


    def on_splash_duration_slider_changed(self, value):
        """启动动画时长滑动条值改变"""
        self.splash_duration_input.setText(str(value))
        # 同上：拖动时防抖，停手后再落盘
        self._saver.set("splash_screen_duration", value)


    def _nudge_splash_duration(self, delta):
        """滚轮微调：一格 ±1 秒（夹在 1~5 之间）。

        只改滑块的值就够了 —— setValue 会触发 on_splash_duration_slider_changed，输入框文字和落盘
        都在那条路径里（写两遍迟早对不上）。
        """
        try:
            current = int(self.splash_duration_slider.value())
        except Exception:
            return
        target = max(1, min(5, current + int(delta)))
        if target != current:
            self.splash_duration_slider.setValue(target)


    def on_splash_duration_input_changed(self, text):
        """启动动画时长输入框值改变"""
        if text:
            try:
                value = int(text)
                if value < 1:
                    value = 1
                    self.splash_duration_input.setText("1")
                elif value > 5:
                    value = 5
                    self.splash_duration_input.setText("5")
                self.splash_duration_slider.setValue(value)
                # 同上：拖动时防抖，停手后再落盘
                self._saver.set("splash_screen_duration", value)
            except ValueError:
                pass

