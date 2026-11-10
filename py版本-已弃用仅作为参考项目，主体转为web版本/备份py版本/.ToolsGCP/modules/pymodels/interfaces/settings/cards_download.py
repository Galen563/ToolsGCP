"""设置页的卡片与回调（资源来源 / 下载）。

「资源来源」：云端 = 用作者上传的最新资源索引（默认）；本地 = 用磁盘上自己指定的 ToolsGCP-Resources.json，
选「本地」时下方会出现一个选择文件夹的组件。具体取值逻辑见 core/cloud_resource_source.py。
"""

from ...utils.fonts import ui_font
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFrame, QScrollArea, QFileDialog)
from PyQt5.QtGui import QFont, QIntValidator
from qfluentwidgets import (SimpleCardWidget, ComboBox, SwitchButton, LineEdit,
                            PrimaryPushButton, BodyLabel, SubtitleLabel, Slider,
                            ToolTipFilter, ToolTipPosition, MessageBox, InfoBar,
                            InfoBarPosition, PushButton, CheckBox,
                            FluentIcon as FIF)
from datetime import datetime
import os
import sys
if sys.platform == 'win32':
    import winreg

from ...core.language_manager import LanguageManager
from ...core.settings_manager import SettingsManager
from ...core.cloud_resource_source import (DEFAULT_LOCAL_DIR, RESOURCE_FILE_NAME,
                                           local_dir_from_settings,
                                           resolve_resource_file)
from ...core.updater import update_channel
from ...ui.hotkey_edit import HotkeyEdit
from ...ui.key_display_window import KeyDisplayWindow
from ...utils.smooth_scroll import install_smooth_scroll
from ...utils.system_utils import (set_windows_autostart, restart_program,
                                   detect_system_theme, detect_system_language)
from ...utils.theme_utils import is_dark_mode, apply_app_palette
from ...constants import (VALID_GCP_KEYS, DEV_KEYS, SPECIAL_KEYS, SOURCE_OPTIONS,
                          UPDATE_CHANNEL_ALL, UPDATE_CHANNEL_STABLE,
                          UPDATE_CHANNEL_BETA)

from .texts import FALLBACK_TEXTS
from .common import (DISABLED_TEXT_COLOR, DEFAULT_TEXT_LIGHT, DEFAULT_TEXT_DARK,
                     PAGE_ORDER, HOTKEY_DEFAULTS)
from .widgets import install_wheel_step


class SettingsCardsDownloadMixin:
    # ==================== 资源来源（下载卡片最上面） ====================
    def _build_resource_source_section(self, card, layout):
        """把「资源来源」这一块加进下载卡片的最上面（它属于"下载/资源"这一组，以前单独一张卡看着像两回事）。"""
        divider = QFrame(card)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: rgba(128,128,128,70);")

        layout.addWidget(SubtitleLabel(self.get_text("resource_source"), card))

        tip = BodyLabel(self.get_text("resource_source_tip"), card)
        tip.setWordWrap(True)
        layout.addWidget(tip)

        # ---- 云端 / 本地 ----
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(BodyLabel(self.get_text("resource_source_mode"), card))
        row.addStretch()          # 下拉框靠右，和其它设置项的排布一致

        self.resource_source_combo = ComboBox(card)
        self.resource_source_combo.addItem(self.get_text("source_cloud"), userData="cloud")
        self.resource_source_combo.addItem(self.get_text("source_local"), userData="local")
        current = str(self.settings_manager.settings.get("resource_source") or "cloud")
        self.resource_source_combo.setCurrentIndex(1 if current == "local" else 0)
        self.resource_source_combo.setMinimumWidth(170)
        self.resource_source_combo.currentIndexChanged.connect(
            self.change_resource_source)
        row.addWidget(self.resource_source_combo)
        layout.addLayout(row)

        # ---- 本地目录（只在选「本地」时出现）----
        self.local_dir_row = QWidget(card)
        dir_layout = QHBoxLayout(self.local_dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(8)
        dir_layout.addWidget(BodyLabel(self.get_text("local_dir"), self.local_dir_row))

        self.local_dir_edit = LineEdit(self.local_dir_row)
        self.local_dir_edit.setText(local_dir_from_settings(self.settings_manager))
        self.local_dir_edit.setPlaceholderText(DEFAULT_LOCAL_DIR)
        self.local_dir_edit.setMinimumWidth(300)
        self.local_dir_edit.editingFinished.connect(self.on_local_dir_changed)
        dir_layout.addWidget(self.local_dir_edit, 1)

        self.local_dir_btn = PushButton(self.get_text("choose_dir"),
                                        self.local_dir_row, FIF.FOLDER)
        self.local_dir_btn.clicked.connect(self.choose_local_dir)
        dir_layout.addWidget(self.local_dir_btn)
        layout.addWidget(self.local_dir_row)

        self.local_dir_status = BodyLabel("", card)
        self.local_dir_status.setWordWrap(True)
        layout.addWidget(self.local_dir_status)

        # ⚠️ 临时提示：这个功能还没成熟，先在这儿提醒
        # 等本地资源目录稳定之后，把下面这几行连同语言文件里的 "local_dir_temp_notice" 一起删掉
        self.local_dir_notice = BodyLabel(self.get_text("local_dir_temp_notice"), card)
        self.local_dir_notice.setWordWrap(True)
        self.local_dir_notice.setStyleSheet("color: #E8A33D;")
        layout.addWidget(self.local_dir_notice)
        # ⬆️ 临时提示结束

        self.update_local_dir_visibility()
        # 和下面的下载设置之间加条分割线
        layout.addSpacing(4)
        layout.addWidget(divider)
        layout.addSpacing(4)
        return divider

    def change_resource_source(self, index: int):
        """切换云端 / 本地"""
        mode = self.resource_source_combo.itemData(index) or "cloud"
        self.settings_manager.update_setting("resource_source", mode)
        self.update_local_dir_visibility()
        label = (self.get_text("source_cloud") if mode == "cloud"
                 else self.get_text("source_local"))
        self.show_message(f"{self.get_text('resource_source_mode')}：{label}", "info")

    def update_local_dir_visibility(self):
        """选「云端」时把本地目录那一行藏起来"""
        mode = str(self.settings_manager.settings.get("resource_source") or "cloud")
        visible = (mode == "local")
        self.local_dir_row.setVisible(visible)
        self.local_dir_status.setVisible(visible)
        self.local_dir_notice.setVisible(visible)
        if visible:
            self.refresh_local_dir_status()

    def refresh_local_dir_status(self):
        """显示当前实际会读哪个索引文件、在不在"""
        path = resolve_resource_file(self.settings_manager)
        exists = os.path.exists(path)
        text = f"{self.get_text('current_index_file')}：{path}"
        if not exists:
            text += "  ⚠️ " + self.get_text("index_file_missing")
        self.local_dir_status.setText(text)
        self.local_dir_status.setStyleSheet("" if exists else "color: #E06C75;")

    def on_local_dir_changed(self):
        directory = self.local_dir_edit.text().strip() or DEFAULT_LOCAL_DIR
        self.settings_manager.update_setting("local_resource_dir", directory)
        self.refresh_local_dir_status()

    def choose_local_dir(self):
        """选一个放着 ToolsGCP-Resources.json 的文件夹"""
        start = self.local_dir_edit.text().strip() or DEFAULT_LOCAL_DIR
        directory = QFileDialog.getExistingDirectory(
            self, self.get_text("choose_dir"), start)
        if not directory:
            return
        self.local_dir_edit.setText(directory)
        self.on_local_dir_changed()
        self.show_message(f"{self.get_text('choose_dir')}：{directory}", "success")

    # ==================== 下载 ====================
    def _create_download_card(self):
        """创建下载配置卡片（最上面先放「资源来源」）"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 资源来源属于这一组，直接放在卡片内部最上面
        self._build_resource_source_section(card, layout)

        # 搜索源：下拉框里是「Github + 镜像站」（镜像站排在 GitHub 下面）
        search_source_widget = QWidget()
        search_source_layout = QHBoxLayout(search_source_widget)
        search_source_layout.setContentsMargins(0, 0, 0, 0)

        search_source_label = BodyLabel(self.get_text("search_source"))
        search_source_label.setObjectName("whiteInDarkLabel")
        search_source_layout.addWidget(search_source_label)

        # ⓘ 里放的就是截图里那段提示（需求：把如图的提示做成提示）
        search_source_tip = QLabel("ⓘ")
        search_source_tip.setObjectName("whiteInDarkIcon")
        search_source_tip.setToolTip(self.get_text("github_mirror_hint"))
        search_source_tip.installEventFilter(
            ToolTipFilter(search_source_tip, 300, ToolTipPosition.TOP))
        search_source_layout.addWidget(search_source_tip)
        search_source_layout.addStretch()

        self.search_source_combo = ComboBox()
        self._fill_source_combo(self.search_source_combo)
        self._select_source(self.search_source_combo, "search_source")
        self.search_source_combo.setFixedWidth(180)
        self.search_source_combo.currentIndexChanged.connect(self.change_search_source)
        search_source_layout.addWidget(self.search_source_combo)
        layout.addWidget(search_source_widget)

        # 下载源（同上）
        download_source_widget = QWidget()
        download_source_layout = QHBoxLayout(download_source_widget)
        download_source_layout.setContentsMargins(0, 0, 0, 0)

        download_source_label = BodyLabel(self.get_text("download_source"))
        download_source_label.setObjectName("whiteInDarkLabel")
        download_source_layout.addWidget(download_source_label)

        download_source_tip = QLabel("ⓘ")
        download_source_tip.setObjectName("whiteInDarkIcon")
        download_source_tip.setToolTip(self.get_text("github_mirror_hint"))
        download_source_tip.installEventFilter(
            ToolTipFilter(download_source_tip, 300, ToolTipPosition.TOP))
        download_source_layout.addWidget(download_source_tip)
        download_source_layout.addStretch()

        self.download_source_combo = ComboBox()
        self._fill_source_combo(self.download_source_combo)
        self._select_source(self.download_source_combo, "download_source")
        self.download_source_combo.setFixedWidth(180)
        self.download_source_combo.currentIndexChanged.connect(self.change_download_source)
        download_source_layout.addWidget(self.download_source_combo)
        layout.addWidget(download_source_widget)

        # 更新下载渠道：决定「检查更新」愿意接受哪种发布（正式版 / Beta 版）
        # ⚠️ 这一项只管程序自身的更新，和上面的「下载源」不是一回事（下载源决定"东西从哪个站下"）
        update_channel_widget = QWidget()
        update_channel_layout = QHBoxLayout(update_channel_widget)
        update_channel_layout.setContentsMargins(0, 0, 0, 0)

        update_channel_label = BodyLabel(self.get_text("update_channel"))
        update_channel_label.setObjectName("whiteInDarkLabel")
        update_channel_layout.addWidget(update_channel_label)

        update_channel_tip = QLabel("ⓘ")
        update_channel_tip.setObjectName("whiteInDarkIcon")
        update_channel_tip.setToolTip(self.get_text("update_channel_tip"))
        update_channel_tip.installEventFilter(
            ToolTipFilter(update_channel_tip, 300, ToolTipPosition.TOP))
        update_channel_layout.addWidget(update_channel_tip)
        update_channel_layout.addStretch()

        self.update_channel_combo = ComboBox()
        self.update_channel_combo.addItem(self.get_text("update_channel_all"),
                                          userData=UPDATE_CHANNEL_ALL)
        self.update_channel_combo.addItem(self.get_text("update_channel_stable"),
                                          userData=UPDATE_CHANNEL_STABLE)
        self.update_channel_combo.addItem(self.get_text("update_channel_beta"),
                                          userData=UPDATE_CHANNEL_BETA)
        self._select_update_channel()
        self.update_channel_combo.setFixedWidth(180)
        self.update_channel_combo.currentIndexChanged.connect(
            self.change_update_channel)
        update_channel_layout.addWidget(self.update_channel_combo)
        layout.addWidget(update_channel_widget)
        
        # 下载限速 - 第一行：标题和复选框（右对齐，与上方ComboBox对齐）
        speed_limit_header_widget = QWidget()
        speed_limit_header_layout = QHBoxLayout(speed_limit_header_widget)
        speed_limit_header_layout.setContentsMargins(0, 0, 0, 0)
        
        speed_limit_title = BodyLabel(self.get_text("download_speed_limit"))
        speed_limit_title.setObjectName("whiteInDarkLabel")
        speed_limit_header_layout.addWidget(speed_limit_title)
        speed_limit_header_layout.addStretch()
        
        speed_limit_enabled = self.settings_manager.settings.get("download_speed_limit_enabled", False)
        speed_limit_value = self.settings_manager.settings.get("download_speed_limit", 100)
        
        # 右侧容器：固定宽度180px（与ComboBox对齐），内容右对齐
        checkbox_container = QWidget()
        checkbox_container.setFixedWidth(180)  # 固定宽度与ComboBox对齐
        checkbox_layout = QHBoxLayout(checkbox_container)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setSpacing(6)
        checkbox_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # 右对齐
        
        # 状态文本（动态显示）
        self.speed_limit_status_label = QLabel()
        self.speed_limit_status_label.setObjectName("whiteInDarkLabel")
        self.speed_limit_status_label.setFont(ui_font(9))
        self.update_speed_limit_status_text(speed_limit_enabled, speed_limit_value)
        
        # 复选框（使用Fluent风格，不设置任何样式表）
        self.speed_limit_checkbox = CheckBox()
        self.speed_limit_checkbox.setChecked(speed_limit_enabled)
        self.speed_limit_checkbox.stateChanged.connect(self.change_speed_limit_enabled)
        
        checkbox_layout.addWidget(self.speed_limit_status_label)
        checkbox_layout.addWidget(self.speed_limit_checkbox)
        
        speed_limit_header_layout.addWidget(checkbox_container)
        layout.addWidget(speed_limit_header_widget)
        
        # 下载限速 - 第二行：滑动条（缩进显示，表示是分支）
        slider_widget = QWidget()
        slider_layout = QHBoxLayout(slider_widget)
        slider_layout.setContentsMargins(20, 0, 0, 0)  # 左侧缩进20px
        slider_layout.setSpacing(8)
        
        # 限速速度标签（缩进）- 保存为实例变量以便更新状态
        self.speed_limit_label = BodyLabel(self.get_text("limit_speed"))
        self.speed_limit_label.setObjectName("whiteInDarkLabel")
        slider_layout.addWidget(self.speed_limit_label)
        slider_layout.addStretch()
        
        self.speed_limit_slider = Slider(Qt.Horizontal)
        self.speed_limit_slider.setRange(1, 300)
        self.speed_limit_slider.setValue(speed_limit_value)
        self.speed_limit_slider.setFixedWidth(250)
        self.speed_limit_slider.valueChanged.connect(self.on_speed_limit_slider_changed)

        self.speed_limit_input = LineEdit()
        self.speed_limit_input.setText(str(speed_limit_value))
        self.speed_limit_input.setFixedWidth(50)
        self.speed_limit_input.setAlignment(Qt.AlignCenter)
        self.speed_limit_input.setValidator(QIntValidator(1, 300))
        self.speed_limit_input.textChanged.connect(self.on_speed_limit_input_changed)
        
        self.speed_limit_unit_label = QLabel("MB/s")
        self.speed_limit_unit_label.setObjectName("whiteInDarkLabel")
        
        slider_layout.addWidget(self.speed_limit_slider)
        slider_layout.addWidget(self.speed_limit_input)
        slider_layout.addWidget(self.speed_limit_unit_label)
        layout.addWidget(slider_widget)
        # ⚠️ 需求："设置中的下载限速未选中则关联的限速那行不显示，如果勾选了则显示。"
        #    以前这一行"一直在、只是灰掉"，用户看不出它算不算生效；这里存成属性由 update_speed_limit_state 整体 show/hide
        self.speed_limit_row = slider_widget

        # ⚠️ 滚轮一格只 ±1 MB/s：Qt 默认滚一格跳 3、数字框完全不响应滚轮，两边都接管掉
        install_wheel_step(self.speed_limit_slider, self._nudge_speed_limit)
        install_wheel_step(self.speed_limit_input, self._nudge_speed_limit)
        
        self.update_speed_limit_state(speed_limit_enabled)
        
        return card


    def update_speed_limit_status_text(self, enabled, value):
        """更新限速状态文本"""
        if enabled:
            self.speed_limit_status_label.setText(f"{value} MB/s")
        else:
            self.speed_limit_status_label.setText(self.get_text("unlimited"))


    def update_speed_limit_state(self, enabled):
        """更新限速控件状态：没勾选就整行藏起来，勾了才显示（以前始终占着位置、只是变灰，用户会以为限速还生效）。"""
        enabled = bool(enabled)
        row = getattr(self, "speed_limit_row", None)
        if row is not None:
            row.setVisible(enabled)
        # 使用setEnabled控制控件状态，不直接修改样式表，避免触发全局样式重计算
        self.speed_limit_slider.setEnabled(enabled)
        self.speed_limit_input.setEnabled(enabled)

        # 同步"限速"及其单位标签的颜色：禁用时灰色，启用时跟随主题
        self.set_label_disabled(self.speed_limit_label, not enabled)
        self.set_label_disabled(self.speed_limit_unit_label, not enabled)

        current_value = self.speed_limit_slider.value()
        self.update_speed_limit_status_text(enabled, current_value)


    def change_speed_limit_enabled(self, state):
        """限速开关状态改变"""
        enabled = (state == Qt.Checked)
        self.settings_manager.update_setting("download_speed_limit_enabled", enabled)
        self.update_speed_limit_state(enabled)
        
        if enabled:
            self.show_message(f"{self.get_text('download_speed_limit')}: {self.get_text('enabled')}", "success")
        else:
            self.show_message(f"{self.get_text('download_speed_limit')}: {self.get_text('disabled')} ({self.get_text('unlimited')})", "info")


    def on_speed_limit_slider_changed(self, value):
        """限速滑动条值改变"""
        self.speed_limit_input.setText(str(value))
        # 拖动过程中不落盘，停手后再写（否则每动一步都要写一遍配置 + 一条日志）
        self._saver.set("download_speed_limit", value)
        if self.speed_limit_checkbox.isChecked():
            self.update_speed_limit_status_text(True, value)


    def _nudge_speed_limit(self, delta):
        """滚轮微调：一格 ±1 MB/s（夹在 1~300 之间）。

        同启动时长那边：只改滑块，输入框同步和落盘由 on_speed_limit_slider_changed 负责。
        """
        try:
            current = int(self.speed_limit_slider.value())
        except Exception:
            return
        target = max(1, min(300, current + int(delta)))
        if target != current:
            self.speed_limit_slider.setValue(target)


    def on_speed_limit_input_changed(self, text):
        """限速输入框值改变"""
        if text:
            try:
                value = int(text)
                if value < 1:
                    value = 1
                    self.speed_limit_input.setText("1")
                elif value > 300:
                    value = 300
                    self.speed_limit_input.setText("300")
                self.speed_limit_slider.setValue(value)
                # 拖动过程中不落盘，停手后再写
                self._saver.set("download_speed_limit", value)
                if self.speed_limit_checkbox.isChecked():
                    self.update_speed_limit_status_text(True, value)
            except ValueError:
                pass


    def change_search_source(self, index):
        source = self.search_source_combo.itemData(index) or "Github"
        self.settings_manager.update_setting("search_source", source)
        self.show_message(f"{self.get_text('search_source')}: {self.search_source_combo.currentText()}", "success")


    def change_download_source(self, index):
        source = self.download_source_combo.itemData(index) or "Github"
        self.settings_manager.update_setting("download_source", source)
        self.show_message(f"{self.get_text('download_source')}: {self.download_source_combo.currentText()}", "success")


    # ========== 更新下载渠道（正式版 / Beta 版） ==========
    def _select_update_channel(self):
        """按配置选中对应项；值非法（老配置/被手改）落到第一项「正式版和Beta版」"""
        value = update_channel(self.settings_manager)
        for index in range(self.update_channel_combo.count()):
            if self.update_channel_combo.itemData(index) == value:
                self.update_channel_combo.setCurrentIndex(index)
                return
        self.update_channel_combo.setCurrentIndex(0)


    def change_update_channel(self, index):
        """切换更新渠道：决定「检查更新」时愿不愿意接受 Beta 版"""
        value = self.update_channel_combo.itemData(index) or UPDATE_CHANNEL_ALL
        self.settings_manager.update_setting("update_channel", value)
        self.show_message(
            f"{self.get_text('update_channel')}: "
            f"{self.update_channel_combo.currentText()}", "success")


    # ========== 源下拉框（Github + 镜像站） ==========
    def _fill_source_combo(self, combo):
        """把「GitHub 官方 + 公益镜像站」填进下拉框（镜像站就排在 GitHub 下面）。

        镜像站是下拉框里的选项，下拉框下面原来那两段说明文字已删除，提示保留在 ⓘ 悬停提示里。
        """
        for option in SOURCE_OPTIONS:
            if option == "Github":
                combo.addItem(self.get_text("github_source"), userData=option)
            else:
                # 镜像站直接显示域名，方便一眼认出来
                combo.addItem(option, userData=option)

    def _select_source(self, combo, setting_key: str):
        """按配置里的值选中对应项；老配置（"国内源"等）自动落到 Github"""
        self._migrate_source_setting(setting_key)
        value = str(self.settings_manager.settings.get(setting_key, "") or "")
        index = 0
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                index = i
                break
        combo.setCurrentIndex(index)

    def _migrate_source_setting(self, key: str):
        """老配置里的 "国内源" 现在没有对应选项了，统一迁到 "Github"。

        （不迁的话界面会显示空的下拉框，而且 source 存的是个已经不存在的值。）
        """
        try:
            value = str(self.settings_manager.settings.get(key, "") or "")
            if value and value not in SOURCE_OPTIONS:
                self.settings_manager.update_setting(key, "Github")
        except Exception:
            pass


