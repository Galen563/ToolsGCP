"""设置页的卡片与回调（关于 / 检查更新 / 自替换）。

通过 mixin 组合进 SettingsInterface，方法里用到的 self.xxx 都在主类里。
"""

from ...utils.fonts import ui_font
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFrame, QScrollArea, QDialog, QApplication)
from PyQt5.QtGui import QFont, QIntValidator
from qfluentwidgets import (SimpleCardWidget, ComboBox, SwitchButton, LineEdit,
                            PrimaryPushButton, BodyLabel, SubtitleLabel, Slider,
                            ToolTipFilter, ToolTipPosition, MessageBox, InfoBar,
                            InfoBarPosition, PushButton, CheckBox,
                            IndeterminateProgressRing)
from datetime import datetime
import os
import sys
if sys.platform == 'win32':
    import winreg

from ...core.language_manager import LanguageManager
from ...core.settings_manager import SettingsManager
from ...core.updater import (UpdateCheckWorker, UpdateDownloadWorker,
                             build_download_urls, default_download_dir,
                             update_channel)
from ...core.self_update import (launch_updater, replacement_blockers,
                                 replacement_target, staging_exe_path)
from ...ui.hotkey_edit import HotkeyEdit
from ...ui.key_display_window import KeyDisplayWindow
from ...ui.update_dialog import (UpdateAvailableDialog, UpdateProgressDialog,
                                 UpdateReplaceFailedDialog, describe_error,
                                 describe_warning, logo_pixmap,
                                 reveal_in_explorer)
from ...utils.downloader import safe_filename
from ...utils.smooth_scroll import install_smooth_scroll
from ...utils.system_utils import (set_windows_autostart, restart_program,
                                   detect_system_theme, detect_system_language)
from ...utils.theme_utils import is_dark_mode, apply_app_palette
from ...constants import (VALID_GCP_KEYS, DEV_KEYS, SPECIAL_KEYS, SOURCE_OPTIONS,
                          APP_NAME, APP_VERSION, APP_CHANNEL, APP_ASSET_NAME)
from .texts import FALLBACK_TEXTS
from .common import (DISABLED_TEXT_COLOR, DEFAULT_TEXT_LIGHT, DEFAULT_TEXT_DARK,
                     PAGE_ORDER, HOTKEY_DEFAULTS)

# 「检查更新」的兜底超时：网络卡住时进度环不能无限转下去（下载线程自己有 15 秒 socket 超时）
UPDATE_CHECK_TIMEOUT_MS = 20000
# 关于卡片里 logo 显示多大（正方形，等比缩放）
ABOUT_LOGO_SIZE = 72
# 版本区与"检查更新"之间那条分割线左右各留多少像素（需求："不要完全连接左右两端"）
ABOUT_DIVIDER_INSET = 12


class SettingsCardsMiscMixin:
    def _create_function_card(self):
        """创建功能设置卡片"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # GCP License Key
        license_widget = QWidget()
        license_layout = QVBoxLayout(license_widget)
        license_layout.setContentsMargins(0, 0, 0, 0)
        license_layout.setSpacing(10)
        
        license_header = QHBoxLayout()
        license_label = BodyLabel(self.get_text("gcp_license_key"))
        license_label.setObjectName("whiteInDarkLabel")
        self.info_icon = QLabel("ⓘ")
        self.info_icon.setObjectName("whiteInDarkIcon")
        self.info_icon.setToolTip(self.get_text("gcp_key_tip"))
        self.info_icon.installEventFilter(ToolTipFilter(self.info_icon, 300, ToolTipPosition.TOP))
        license_header.addWidget(license_label)
        license_header.addWidget(self.info_icon)
        license_header.addStretch()
        license_layout.addLayout(license_header)
        
        license_input_layout = QHBoxLayout()
        self.license_input = LineEdit()
        self.license_input.setPlaceholderText(self.get_text("input_gcp_key"))
        self.license_input.setFixedHeight(35)
        saved_key = self.settings_manager.settings.get("license_key", "")
        if saved_key:
            self.license_input.setText(saved_key)
        license_input_layout.addWidget(self.license_input)
        
        self.update_btn = PrimaryPushButton(self.get_text("verify"))
        self.update_btn.setFixedWidth(80)
        self.update_btn.clicked.connect(self.update_license)
        license_input_layout.addWidget(self.update_btn)
        license_layout.addLayout(license_input_layout)
        
        layout.addWidget(license_widget)
        
        notify_widget = QWidget()
        notify_layout = QHBoxLayout(notify_widget)
        notify_layout.setContentsMargins(0, 0, 0, 0)
        notify_label = BodyLabel(self.get_text("enable_notification"))
        notify_label.setObjectName("whiteInDarkLabel")
        notify_layout.addWidget(notify_label)
        notify_layout.addStretch()
        
        self.notify_switch = SwitchButton()
        self.notify_switch.setChecked(self.settings_manager.settings.get("notify_enabled", True))
        self.notify_switch.checkedChanged.connect(self.change_notify)
        notify_layout.addWidget(self.notify_switch)
        layout.addWidget(notify_widget)
        
        close_mode_widget = QWidget()
        close_mode_layout = QHBoxLayout(close_mode_widget)
        close_mode_layout.setContentsMargins(0, 0, 0, 0)
        
        close_mode_label = BodyLabel(self.get_text("close_mode"))
        close_mode_label.setObjectName("whiteInDarkLabel")
        
        close_mode_info_icon = QLabel("ⓘ")
        close_mode_info_icon.setObjectName("whiteInDarkIcon")
        close_mode_info_icon.setToolTip(self.get_text("close_mode_tip"))
        close_mode_info_icon.installEventFilter(ToolTipFilter(close_mode_info_icon, 300, ToolTipPosition.TOP))
        
        close_mode_layout.addWidget(close_mode_label)
        close_mode_layout.addWidget(close_mode_info_icon)
        close_mode_layout.addStretch()
        
        self.close_mode_combo = ComboBox()
        close_options = [
            self.get_text("close_mode_exit"),
            self.get_text("close_mode_tray")
        ]
        self.close_mode_combo.addItems(close_options)
        saved_close_mode = self.settings_manager.settings.get("close_mode", "彻底退出")
        if saved_close_mode == "彻底退出":
            self.close_mode_combo.setCurrentIndex(0)
        else:
            self.close_mode_combo.setCurrentIndex(1)
        self.close_mode_combo.setFixedWidth(180)
        self.close_mode_combo.currentIndexChanged.connect(self.change_close_mode)
        close_mode_layout.addWidget(self.close_mode_combo)
        layout.addWidget(close_mode_widget)
        
        return card


    def update_license(self):
        key = self.license_input.text().strip()
        self.settings_manager.update_setting("license_key", key)
        
        if key == "Galen563-ToolsGCP":
            self.show_gcp_keys_window()
            return
        
        if key:
            if key in VALID_GCP_KEYS:
                self.show_message(self.get_text("key_valid"), "success")
            else:
                self.show_message(self.get_text("key_invalid"), "error")
        else:
            self.show_message(self.get_text("key_empty"), "warning")


    def change_notify(self, checked):
        self.settings_manager.update_setting("notify_enabled", checked)
        self.show_message(self.get_text("notification_enabled") if checked else self.get_text("notification_disabled"), "info")


    def _create_dev_card(self):
        """创建开发者功能卡片"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        dev_token_widget = QWidget()
        dev_token_layout = QHBoxLayout(dev_token_widget)
        dev_token_layout.setContentsMargins(0, 0, 0, 0)
        
        dev_token_label = BodyLabel(self.get_text("developer_identity_token"))
        dev_token_label.setObjectName("whiteInDarkLabel")
        
        dev_tip_icon = QLabel("ⓘ")
        dev_tip_icon.setObjectName("whiteInDarkIcon")
        dev_tip_icon.setToolTip(self.get_text("dev_mode_tip"))
        dev_tip_icon.installEventFilter(ToolTipFilter(dev_tip_icon, 300, ToolTipPosition.TOP))
        
        dev_token_layout.addWidget(dev_token_label)
        dev_token_layout.addWidget(dev_tip_icon)
        dev_token_layout.addStretch()
        
        layout.addWidget(dev_token_widget)
        
        self.dev_input_container = QWidget()
        self.dev_input_layout = QVBoxLayout(self.dev_input_container)
        self.dev_input_layout.setContentsMargins(0, 0, 0, 0)
        self.dev_input_layout.setSpacing(10)
        
        dev_enabled = self.settings_manager.settings.get("dev_mode_enabled", False)
        dev_admin = self.settings_manager.settings.get("dev_mode_admin", "")
        dev_verify_time = self.settings_manager.settings.get("dev_mode_verify_time", "")
        
        if dev_enabled and dev_admin:
            self.show_dev_verified_status(dev_admin, dev_verify_time)
        else:
            self.show_dev_input_field()
        
        layout.addWidget(self.dev_input_container)
        
        return card


    def show_dev_input_field(self):
        """显示开发者密钥输入框"""
        while self.dev_input_layout.count():
            item = self.dev_input_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        input_row = QWidget()
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        
        self.dev_input = LineEdit()
        self.dev_input.setPlaceholderText(self.get_text("input_dev_key"))
        self.dev_input.setFixedHeight(35)
        
        self.dev_verify_btn = PrimaryPushButton(self.get_text("verify"))
        self.dev_verify_btn.setFixedWidth(80)
        self.dev_verify_btn.clicked.connect(self.verify_dev_key)
        
        input_layout.addWidget(self.dev_input)
        input_layout.addWidget(self.dev_verify_btn)
        
        self.dev_input_layout.addWidget(input_row)


    def show_dev_verified_status(self, admin_name, verify_time):
        """显示已验证状态"""
        while self.dev_input_layout.count():
            item = self.dev_input_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        admin_label = QLabel(f"{admin_name}{self.get_text('admin_verified')}")
        admin_label.setObjectName("whiteInDarkLabel")
        admin_label.setFont(ui_font(10, bold=True))
        admin_label.setStyleSheet("padding: 5px;")
        
        exit_btn = PushButton(self.get_text("exit"))
        exit_btn.setFixedWidth(80)
        exit_btn.clicked.connect(lambda: self.logout_dev_mode())
        
        status_layout.addWidget(admin_label)
        status_layout.addStretch()
        status_layout.addWidget(exit_btn)
        
        self.dev_input_layout.addWidget(status_row)
        
        time_label = QLabel(f"{self.get_text('verify_time')}: {verify_time}")
        time_label.setObjectName("whiteInDarkLabel")
        time_label.setStyleSheet("color: gray; font-size: 11px;")
        self.dev_input_layout.addWidget(time_label)
        
        debug_widget = QWidget()
        debug_layout = QHBoxLayout(debug_widget)
        debug_layout.setContentsMargins(0, 10, 0, 0)
        
        debug_label = BodyLabel(self.get_text("debug_info"))
        debug_label.setObjectName("whiteInDarkLabel")
        
        debug_tip_icon = QLabel("ⓘ")
        debug_tip_icon.setObjectName("whiteInDarkIcon")
        debug_tip_icon.setToolTip(self.get_text("debug_info_tip"))
        debug_tip_icon.installEventFilter(ToolTipFilter(debug_tip_icon, 300, ToolTipPosition.TOP))
        
        debug_layout.addWidget(debug_label)
        debug_layout.addWidget(debug_tip_icon)
        debug_layout.addStretch()
        
        self.debug_info_switch = SwitchButton()
        debug_enabled = self.settings_manager.get_debug_info_enabled(admin_name)
        self.debug_info_switch.setChecked(debug_enabled)
        self.debug_info_switch.checkedChanged.connect(lambda checked: self.change_debug_info(checked, admin_name))
        debug_layout.addWidget(self.debug_info_switch)
        
        self.dev_input_layout.addWidget(debug_widget)


    def change_debug_info(self, checked, admin_name):
        """调试信息开关状态改变"""
        self.settings_manager.set_debug_info_enabled(admin_name, checked)
        status = "开启" if checked else "关闭"
        self.show_message(f"调试信息已{status} ({admin_name})", "info")


    def verify_dev_key(self):
        """验证开发者密钥"""
        key = self.dev_input.text().strip()

        if not key:
            self.show_message(self.get_text("dev_key_empty"), "warning")
            return

        if key in SPECIAL_KEYS:
            self.show_dev_keys_window()
            return

        if key in DEV_KEYS:
            admin_name = DEV_KEYS[key]
            verify_time = datetime.now().strftime("%Y年%m月%d日 %H时%M分%S秒")

            self.settings_manager.update_setting("dev_mode_enabled", True)
            self.settings_manager.update_setting("dev_mode_admin", admin_name)
            self.settings_manager.update_setting("dev_mode_verify_time", verify_time)
            self.settings_manager.update_setting("dev_mode_key", key)

            self.show_dev_verified_status(admin_name, verify_time)
            self.show_message(f"{admin_name} {self.get_text('dev_verify_success')}", "success")
        else:
            self.show_message(self.get_text("dev_key_invalid"), "error")


    def logout_dev_mode(self):
        """退出开发者模式"""
        admin_name = self.settings_manager.settings.get("dev_mode_admin", "")
        
        if self.debug_info_switch and admin_name:
            self.settings_manager.set_debug_info_enabled(admin_name, self.debug_info_switch.isChecked())
        
        self.settings_manager.update_setting("dev_mode_enabled", False)
        self.settings_manager.update_setting("dev_mode_admin", "")
        self.settings_manager.update_setting("dev_mode_verify_time", "")
        self.settings_manager.update_setting("dev_mode_key", "")
        
        self.show_dev_input_field()
        self.show_message(self.get_text("dev_logout"), "info")


    def show_gcp_keys_window(self):
        """显示GCP密钥窗口（用于GCP License Key区域的Galen563-ToolsGCP）"""
        is_dark = self.is_dark_mode()
        
        # 4个GCP密钥，不带管理员名称
        keys_info = [
            {"key": "GCP-74G2-N052-8X42", "admin": ""},
            {"key": "GCP-N228-45G0-Y728", "admin": ""},
            {"key": "GCP-054N-2G82-4Z27", "admin": ""},
            {"key": "GCP-G782-N402-5K20", "admin": ""}
        ]
        
        # 使用GCP License Key的标题
        window_title = self.get_text("available_keys")
        self.key_window = KeyDisplayWindow(keys_info, is_dark, self.lang, window_title=window_title)
        self.key_window.show()


    def show_dev_keys_window(self):
        """显示开发者密钥窗口（用于开发者功能区域的Galen563-ToolsGCP）"""
        is_dark = self.is_dark_mode()
        
        # 2个开发者密钥，带管理员名称
        keys_info = [
            {"key": "GCP-G756-23L4-N375", "admin": "Galen563"},
            {"key": "GCP-76C2-P081-5Y60", "admin": "Cyric373"}
        ]
        
        # 使用开发者密钥的标题，不是GCP License Key
        window_title = self.get_text("available_dev_keys")
        self.key_window = KeyDisplayWindow(keys_info, is_dark, self.lang, window_title=window_title)
        self.key_window.show()


    # ==================== 关于（程序信息 + 检查更新） ====================

    def _create_about_card(self):
        """创建关于卡片：竖着居中排「ToolsGCP / logo / 版本号 / 分割线 / 检查更新按钮」。"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        layout.addLayout(self._build_about_header(card))

        # ---- 分割线（放在"版本号"和"检查更新"之间）----
        layout.addWidget(self._build_about_divider(card))

        # ---- 检查更新行 ----
        update_widget = QWidget(card)
        update_layout = QHBoxLayout(update_widget)
        update_layout.setContentsMargins(0, 0, 0, 0)

        update_label = BodyLabel(self.get_text("check_update"), update_widget)
        update_label.setObjectName("whiteInDarkLabel")
        update_layout.addWidget(update_label)
        update_layout.addStretch()

        self.check_update_btn = PrimaryPushButton(
            self.get_text("check_update_btn"), update_widget)
        self.check_update_btn.setFixedWidth(120)
        self.check_update_btn.clicked.connect(self._on_check_update)
        update_layout.addWidget(self.check_update_btn)

        layout.addWidget(update_widget)
        return card

    def _build_about_divider(self, card):
        """版本区和"检查更新"之间的细分割线（外面套一层带左右边距的容器，线不顶到两端）。"""
        holder = QWidget(card)
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(ABOUT_DIVIDER_INSET, 0,
                                         ABOUT_DIVIDER_INSET, 0)
        holder_layout.setSpacing(0)

        line = QFrame(holder)
        line.setFixedHeight(1)
        # 中灰 + 半透明：深浅主题下都看得见且不抢眼，所以不用按主题分两套颜色
        line.setStyleSheet("background-color: rgba(140,140,140,90);")
        holder_layout.addWidget(line)
        return holder

    def _build_about_header(self, card):
        """关于卡片顶上那块：程序名 / 图标 / 版本号，全部水平居中"""
        column = QVBoxLayout()
        column.setSpacing(8)

        name_label = SubtitleLabel(APP_NAME, card)
        name_label.setAlignment(Qt.AlignCenter)
        column.addWidget(name_label)

        # 图标取 .ToolsGCP/logo.png（走 logo_pixmap → constants.resource_path，程序目录和 onefile 打包都能找到）
        logo = QLabel(card)
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedHeight(ABOUT_LOGO_SIZE)
        pixmap = logo_pixmap(ABOUT_LOGO_SIZE)
        if pixmap is not None:
            logo.setPixmap(pixmap)
        column.addWidget(logo)

        self.about_version_label = BodyLabel(self._about_version_text(), card)
        self.about_version_label.setAlignment(Qt.AlignCenter)
        self.about_version_label.setObjectName("whiteInDarkLabel")
        column.addWidget(self.about_version_label)

        return column

    def _about_version_text(self):
        """界面上的版本号（带 v，和 Release 页面上的 tag 对得上）；只有版本号本身看不出预发布时才补 " Beta"。"""
        text = str(APP_VERSION)
        if text[:1] not in ("v", "V"):
            text = f"v{text}"
        if str(APP_CHANNEL).lower() == "beta" and "-" not in text:
            text += " Beta"
        return text

    # ---------- 检查更新 ----------

    def _on_check_update(self):
        """检查更新：按钮里转进度环 → 去 GitHub 问 → 有新版就弹窗。

        ⚠️ 真正的请求跑在 UpdateCheckWorker 线程里：网络绝不能放在 UI 线程上，否则点一下界面就假死。
        """
        button = getattr(self, "check_update_btn", None)
        if button is None or getattr(self, "_update_ring", None) is not None:
            return
        if getattr(self, "_update_worker", None) is not None:
            return                              # 上一次还没回来，别叠着发

        self._start_check_update_ring(button)

        # worker 挂 self 当父对象（同 deploy_interface 的 DownloadWorker）：由 Qt 管生命周期，
        # 线程还在跑时不会被 Python 回收（那会直接崩）；「搜索源」也传进去，镜像设置才对它生效
        worker = UpdateCheckWorker(channel=update_channel(self.settings_manager),
                                   current_version=APP_VERSION,
                                   search_source=self._update_search_source(),
                                   parent=self)
        worker.found.connect(self._on_update_found)
        worker.latest.connect(self._on_update_latest)
        worker.failed.connect(self._on_update_failed)
        self._update_worker = worker
        self._update_check_seq = getattr(self, "_update_check_seq", 0) + 1
        sequence = self._update_check_seq
        worker.start()

        # 兜底超时：线程自己也有 15 秒 socket 超时，这里再兜一层，保证进度环无论如何都会停
        QTimer.singleShot(UPDATE_CHECK_TIMEOUT_MS,
                          lambda: self._on_check_update_timeout(sequence))

    def _start_check_update_ring(self, button):
        """按钮文字清空 + 中间转一个不确定进度环（PyQt-Fluent-Widgets 那个 demo 的做法）"""
        ring = IndeterminateProgressRing(button)
        size = 18
        ring.setFixedSize(size, size)
        try:
            ring.setStrokeWidth(2.2)
        except Exception:
            pass
        ring.move(max(0, (button.width() - size) // 2),
                  max(0, (button.height() - size) // 2))
        ring.show()
        ring.raise_()
        self._update_ring = ring
        self._update_button_text = button.text()
        button.setText("")
        button.setEnabled(False)

    def _finish_check_update(self):
        """收掉进度环、把按钮文字和可点状态恢复"""
        ring = getattr(self, "_update_ring", None)
        self._update_ring = None
        if ring is not None:
            try:
                if hasattr(ring, "stop"):
                    ring.stop()
                ring.hide()
                ring.deleteLater()
            except RuntimeError:
                pass
        button = getattr(self, "check_update_btn", None)
        if button is not None:
            button.setText(getattr(self, "_update_button_text", "")
                           or self.get_text("check_update_btn"))
            button.setEnabled(True)

    def _claim_update_result(self):
        """这次请求还作数吗？作数就顺手收环（用来丢掉超时后才回来的、以及上一次点击残留的信号）。"""
        if getattr(self, "_update_worker", None) is None:
            return False
        self._update_worker = None
        # 序号往前走一格 → 那个还在排队的超时回调自己会失效
        self._update_check_seq = getattr(self, "_update_check_seq", 0) + 1
        self._finish_check_update()
        return True

    def _on_check_update_timeout(self, sequence):
        """兜底超时：线程还挂着就直接收环报错，别让用户对着转圈干等"""
        if sequence != getattr(self, "_update_check_seq", 0):
            return
        if getattr(self, "_update_worker", None) is None:
            return
        self._update_worker = None
        self._update_check_seq = sequence + 1
        self._finish_check_update()
        self.show_message(describe_error(self.get_text, "TIMEOUT"), "error")

    def _on_update_found(self, info):
        """有新版本：在窗口内部弹遮罩窗，说清楚「版本 / 版本信息 / 文件名称 / 文件大小」。

        ⚠️ 父对象必须是顶层窗口（self.window()）：MessageBoxBase 是"遮罩式"弹窗，会铺满父对象
        并加一层半透明蒙版；传设置页那个小部件的话蒙版只盖住设置页一块，左边导航栏还是亮的。
        """
        if not self._claim_update_result():
            return
        dialog = UpdateAvailableDialog(self._dialog_parent(), self.get_text, info)
        accepted = dialog.exec_() == QDialog.Accepted
        # 显式删掉这个弹窗：它挂着父对象不会被 Python 提前回收，反复点「检查更新」会一个个攒着
        dialog.deleteLater()
        if accepted:
            self._start_update_download(info)

    def _on_update_latest(self, info):
        """已经是最新版本"""
        if not self._claim_update_result():
            return
        self.show_message(
            f"{self.get_text('update_is_latest')}（{self._about_version_text()}）",
            "success")

    def _on_update_failed(self, code):
        """查不到：按错误码给一句人话（错误码 → 语言键，三种语言都覆盖）"""
        if not self._claim_update_result():
            return
        self.show_message(describe_error(self.get_text, code), "error")

    # ---------- 更新用到的设置 / 工具 ----------

    def _dialog_parent(self):
        """遮罩弹窗的父对象：优先顶层窗口（MessageBoxBase 会按 parent 尺寸铺满，不能是 None）。"""
        try:
            window = self.window()
            if window is not None and window.width() > 0:
                return window
        except Exception:
            pass
        return self

    def _update_search_source(self):
        """设置里的「搜索源」——决定去哪儿问版本号"""
        try:
            return str(self.settings_manager.settings.get("search_source") or "")
        except Exception:
            return ""

    def _update_download_source(self):
        """设置里的「下载源」——决定从哪儿下更新包"""
        try:
            return str(self.settings_manager.settings.get("download_source") or "")
        except Exception:
            return ""

    # ---------- 下载更新包 ----------

    def _start_update_download(self, info):
        """把更新包下到 %TEMP%\\ToolsGCP_new.exe，然后交给它自己去替换（下载 → 校验 → 启动更新器 → 主程序退出）。

        剩下的复制 / 回滚 / 清理都在更新器里做（见 core/self_update）；当前环境换不了的时候
        （源码运行且没有 exe 等），弹窗给「查看原因」，点了列清楚可能导致替换失败的原因。
        """
        # 「下载源」生效点：镜像优先，官方兜底（镜像挂了会自动换下一个）
        urls = build_download_urls(info.get("asset_url") or "",
                                   self._update_download_source())
        if not urls:
            self.show_message(self.get_text("update_err_no_asset"), "error")
            return

        # 目标路径写死成 %TEMP%\ToolsGCP_new.exe（启动参数要和它对上），已存在就直接覆盖
        directory, fell_back = default_download_dir()
        filename = safe_filename(info.get("asset_name") or APP_ASSET_NAME)
        try:
            dest = staging_exe_path()
        except Exception:
            dest = os.path.join(directory, filename)
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except Exception:
            pass

        # 能不能自动替换要到"下载完"那一刻才算（目录里有没有那个 exe 前后是两个答案），所以 allow_replace 传 None
        dialog = UpdateProgressDialog(self._dialog_parent(), self.get_text,
                                      filename, info.get("asset_size") or 0,
                                      allow_replace=None)
        worker = UpdateDownloadWorker(urls, dest,
                                      info.get("sha256") or "", parent=self)
        worker.progressed.connect(dialog.update_progress)
        worker.failed.connect(dialog.finish_error)
        dialog.cancelled.connect(worker.cancel)

        self._download_result = ""
        self._download_warning = ""
        # ⚠️ succeeded 不直接连 dialog.finish_ok：中间要过一道我们的槽，在那一刻重算 blockers 再驱动完成态
        worker.succeeded.connect(self._on_download_succeeded)

        self._update_download_worker = worker
        self._update_dialog = dialog
        worker.start()
        dialog.exec_()
        # ⚠️ 先读按钮意图再 deleteLater（读在删之前总是更稳）
        restart_requested = bool(getattr(dialog, "restart_requested", False))
        reasons_requested = bool(getattr(dialog, "reasons_requested", False))
        blockers = list(getattr(dialog, "blockers", None) or [])
        dialog.deleteLater()
        self._update_download_worker = None
        self._update_dialog = None

        if fell_back:
            self.show_message(self.get_text("update_dir_fallback"), "warning")

        if reasons_requested:
            # 用户想知道"为什么不能自动替换"
            self._show_replace_reasons(blockers)
            return

        if self._download_result and not blockers and not reasons_requested:
            # ★ 能自动替换 → 问都不问直接换掉并重启（需求："不带弹窗提示的，直接重启替换"）；
            #   弹窗倒计时结束也走同一条路，这里再兜一次（弹窗被 Esc / 点遮罩关掉时照样替换）
            self._apply_downloaded_update(self._download_result)
            return

        if restart_requested and self._download_result:
            # 用户点了「立即重启并更新」（或倒计时自动触发）：换掉自己并启动新版
            self._apply_downloaded_update(self._download_result)
            return

        if self._download_result and blockers:
            # 下好了但换不了：把原因列清楚，别让用户以为更新成功了
            warning = describe_warning(self.get_text, self._download_warning)
            if warning:
                self.show_message(f"{warning}　{self._download_result}", "warning")
            self._show_replace_reasons(blockers)
            return

        # 走到这里 = 没下成（取消 / 失败）：弹窗自己已经说过原因了，不再补提示条

    def _remember_download_result(self, path, warning=""):
        """记下成功路径和警告码，好在弹窗关掉之后再补一条 InfoBar"""
        self._download_result = str(path or "")
        self._download_warning = str(warning or "")

    def _on_download_succeeded(self, path, warning=""):
        """下载成功：此刻再算一次能不能自动替换，然后驱动弹窗的完成态。

        ⚠️ 非要等到这一刻：「程序目录里有没有那个 exe」只有下载落地之后才有确定答案，
        在下载前算会把结果钉死成「查看原因」，用户点了也换不了。
        算出来的原因码同时喂给弹窗（决定亮哪个按钮）和后面的统一提示。
        """
        self._remember_download_result(path, warning)
        blockers = replacement_blockers()
        dialog = getattr(self, "_update_dialog", None)
        if dialog is not None:
            try:
                dialog.set_replace_blockers(blockers)
                dialog.finish_ok(path, warning)
                return
            except RuntimeError:
                pass
        # 拿不到弹窗（被提前关掉/回收了）：至少别让这次下载结果丢掉
        try:
            from ...utils.logger import log
            log.op("更新", "download", file=str(path or ""),
                   warning=str(warning or ""))
        except Exception:
            pass

    # ---------- 自替换（换掉 ToolsGCP.exe → 启动新版） ----------

    def _apply_downloaded_update(self, new_exe):
        """把下载好的新版交给"临时更新器"去替换，然后真正退出程序。

        成功 = 更新器已经拉起来（它在按 PID 等我们消失）；失败 = 弹统一提示，把可能的原因列清楚。
        """
        directory, exe_name, _running = replacement_target()
        target = os.path.join(directory, exe_name)
        blockers = replacement_blockers()
        if blockers:
            self._show_replace_reasons(blockers)
            return

        ok, info = launch_updater(new_exe, target)
        if not ok:
            self._show_replace_reasons(info if isinstance(info, list) else None)
            return
        try:
            from ...utils.logger import log
            log.op("更新", "replace", new=new_exe, target=target,
                   updater=str(info))
        except Exception:
            pass
        # 更新器在按 PID 等我们消失：这里必须走**真正的退出流程**（先摘托盘），只关窗口的话进程还活着
        self._quit_for_update()

    def _show_replace_reasons(self, detected=None):
        """统一提示：这次没能自动替换，可能是哪几种原因"""
        dialog = UpdateReplaceFailedDialog(self._dialog_parent(), self.get_text,
                                           detected, self._download_result)
        dialog.exec_()
        open_folder = bool(getattr(dialog, "open_folder_requested", False))
        dialog.deleteLater()
        if open_folder and self._download_result:
            reveal_in_explorer(self._download_result)

    def _quit_for_update(self):
        """为更新而退出：优先走主窗口的 quit_app（它会先注销热键、摘掉托盘图标）"""
        window = self.window()
        quit_app = getattr(window, "quit_app", None)
        try:
            if callable(quit_app):
                quit_app()
                return
        except Exception:
            pass
        QApplication.quit()

