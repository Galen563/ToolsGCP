"""设置页的卡片与回调（cards_ai：GCP-AI 开关 / API Key / 模型调用）。

通过 mixin 组合进 SettingsInterface，方法里用到的 self.xxx 都在主类里。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFrame, QScrollArea)
from PyQt5.QtGui import QFont, QIntValidator, QDoubleValidator
from qfluentwidgets import (SimpleCardWidget, ComboBox, EditableComboBox, SwitchButton,
                            LineEdit, PrimaryPushButton, BodyLabel, SubtitleLabel,
                            Slider, ToolTipFilter, ToolTipPosition, MessageBox,
                            InfoBar, InfoBarPosition, PushButton, CheckBox)
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
from ...ui.custom_widgets import CardHighlightOverlay
from ...constants import VALID_GCP_KEYS, DEV_KEYS, SPECIAL_KEYS, SOURCE_OPTIONS

from .texts import FALLBACK_TEXTS
from .common import (DISABLED_TEXT_COLOR, DEFAULT_TEXT_LIGHT, DEFAULT_TEXT_DARK,
                     PAGE_ORDER, HOTKEY_DEFAULTS)

# 上下文范围下拉框的选项：(存进设置的轮数, 语言文件里的键)；0 = 整个会话全发（默认，最长记忆）
_AI_CONTEXT_OPTIONS = (
    (0, "ai_context_full"),
    (10, "ai_context_10"),
    (20, "ai_context_20"),
    (30, "ai_context_30"),
)

# 回复模式下拉框的选项：(存进设置的值, 语言文件里的键)；值的含义见 core/ai/prompt.py 的 MODE_PROMPTS
_AI_MODE_OPTIONS = (
    ("standard", "ai_mode_standard"),
    ("concise", "ai_mode_concise"),
    ("professional", "ai_mode_professional"),
)


class SettingsCardsAiMixin:
    def _create_ai_card(self):
        """创建 AI 设置卡片：开启开关 + 上下文范围"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 开启 GCP-AI
        ai_enable_widget = QWidget()
        ai_enable_layout = QHBoxLayout(ai_enable_widget)
        ai_enable_layout.setContentsMargins(0, 0, 0, 0)
        ai_enable_label = BodyLabel(self.get_text("ai_enable"))
        ai_enable_label.setObjectName("whiteInDarkLabel")
        ai_enable_layout.addWidget(ai_enable_label)
        ai_enable_layout.addStretch()
        
        self.ai_enable_switch = SwitchButton()
        self.ai_enable_switch.setChecked(self.settings_manager.settings.get("ai_enabled", False))
        self.ai_enable_switch.checkedChanged.connect(self.change_ai_enabled)
        ai_enable_layout.addWidget(self.ai_enable_switch)
        layout.addWidget(ai_enable_widget)

        # 「改用侧边栏 AI 单独界面」只在 GCP-AI 打开时出现（关掉开关就隐藏这一行）
        self.ai_sidebar_widget = QWidget()
        sidebar_layout = QHBoxLayout(self.ai_sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_label = BodyLabel(self.get_text("ai_sidebar_mode"))
        sidebar_label.setObjectName("whiteInDarkLabel")
        sidebar_layout.addWidget(sidebar_label)
        sidebar_layout.addWidget(self._make_tip_icon(self.get_text("ai_sidebar_mode_tip")))
        sidebar_layout.addStretch()

        self.ai_sidebar_switch = SwitchButton()
        self.ai_sidebar_switch.setChecked(
            bool(self.settings_manager.settings.get("ai_sidebar_mode", False)))
        self.ai_sidebar_switch.checkedChanged.connect(self.change_ai_sidebar_mode)
        sidebar_layout.addWidget(self.ai_sidebar_switch)
        layout.addWidget(self.ai_sidebar_widget)
        # 开关为关 → 整行隐藏（"如果开关为关隐藏ui"）
        self.ai_sidebar_widget.setVisible(self.ai_enable_switch.isChecked())

        # AI 卡片：上下文范围 + 回复模式
        self.ai_context_combo = self._create_ai_context_row(layout)
        self.ai_mode_combo = self._create_ai_mode_row(layout)

        return card

    def _make_tip_icon(self, tooltip_text) -> QLabel:
        """ⓘ 图标 + 悬停提示（设置页里到处都是这个小东西，抽出来免得重复）"""
        icon = QLabel("ⓘ")
        icon.setObjectName("whiteInDarkIcon")
        icon.setToolTip(tooltip_text)
        icon.installEventFilter(ToolTipFilter(icon, 300, ToolTipPosition.TOP))
        return icon

    def _create_ai_mode_row(self, layout):
        """「回复模式」一行：简洁 / 标准 / 专业（直接决定回答的长短和细节，提示词见 core/ai/prompt.py）。"""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label = BodyLabel(self.get_text("ai_reply_mode"))
        label.setObjectName("whiteInDarkLabel")
        row_layout.addWidget(label)
        row_layout.addWidget(self._make_tip_icon(self.get_text("ai_reply_mode_tip")))
        row_layout.addStretch()

        combo = ComboBox()
        combo.setFixedWidth(220)
        for mode_id, text_key in _AI_MODE_OPTIONS:
            combo.addItem(self.get_text(text_key), userData=mode_id)
        combo.setCurrentIndex(self._index_of(
            _AI_MODE_OPTIONS, self.settings_manager.settings.get("ai_reply_mode", "standard")))
        combo.currentIndexChanged.connect(self._on_ai_mode_changed)
        row_layout.addWidget(combo)

        layout.addWidget(row)
        return combo

    @staticmethod
    def _index_of(options, value) -> int:
        """在 (值, 文案键) 表里找值的下标（找不到返回 0）"""
        for index, (option_value, _) in enumerate(options):
            if option_value == value:
                return index
        return 0

    def _on_ai_mode_changed(self, index):
        """回复模式改变：立刻保存"""
        if index < 0 or index >= len(_AI_MODE_OPTIONS):
            return
        mode = _AI_MODE_OPTIONS[index][0]
        self.settings_manager.update_setting("ai_reply_mode", mode)
        self.show_message(self.get_text("ai_reply_mode_saved"), "info")

    def _create_ai_context_row(self, layout):
        """「上下文范围」一行：说明 ⓘ + 下拉框（内部数值 0 = 整个会话全发，10/20/30 = 最近 N 轮）。

        ⚠️ 下拉框的下标和设置值不是一回事，统一走 _AI_CONTEXT_OPTIONS 这张表，别在别处硬编码下标。
        """
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label = BodyLabel(self.get_text("ai_context_window"))
        label.setObjectName("whiteInDarkLabel")
        row_layout.addWidget(label)
        row_layout.addWidget(self._make_tip_icon(self.get_text("ai_context_tip")))
        row_layout.addStretch()

        combo = ComboBox()
        combo.setFixedWidth(220)
        for rounds, text_key in _AI_CONTEXT_OPTIONS:
            combo.addItem(self.get_text(text_key), userData=rounds)
        combo.setCurrentIndex(self._ai_context_index(
            self.settings_manager.settings.get("ai_context_rounds", 0)))
        combo.currentIndexChanged.connect(self._on_ai_context_changed)
        row_layout.addWidget(combo)

        layout.addWidget(row)
        return combo

    @staticmethod
    def _ai_context_index(rounds) -> int:
        """把设置里的轮数换算成下拉框下标（认不出来的值就退回"整个会话"）"""
        try:
            value = int(rounds or 0)
        except (TypeError, ValueError):
            value = 0
        for index, (option_value, _) in enumerate(_AI_CONTEXT_OPTIONS):
            if option_value == value:
                return index
        return 0

    def _on_ai_context_changed(self, index):
        """上下文范围改变：立刻保存（下拉框本来就不需要额外点保存）"""
        if index < 0 or index >= len(_AI_CONTEXT_OPTIONS):
            return
        rounds = _AI_CONTEXT_OPTIONS[index][0]
        self.settings_manager.update_setting("ai_context_rounds", rounds)
        self.show_message(self.get_text("ai_context_saved"), "info")


    def change_ai_enabled(self, checked):
        """开启 GCP-AI 开关状态改变"""
        self.settings_manager.update_setting("ai_enabled", checked)
        # 「改用侧边栏」这一行跟着显示/隐藏（需求：开关为关就隐藏 ui）
        widget = getattr(self, "ai_sidebar_widget", None)
        if widget is not None:
            widget.setVisible(bool(checked))
        # ⚠️ 这里不再顺手把 ai_sidebar_mode 关掉：侧边栏模式是用户自己的选择，来回开关 GCP-AI 不能重置它；
        #    它存在 settings 里，下次启动照它恢复（见 main_window 启动流程）
        # 控制主窗口右下角的悬浮按钮（以及右侧的聊天抽屉）
        if self.main_window is not None and hasattr(self.main_window, "toggle_ai_floating_button"):
            try:
                self.main_window.toggle_ai_floating_button(checked)
            except Exception as e:
                from ...utils.logger import log
                log.err("AI", "ai", f"切换悬浮按钮失败: {e}")
        status = self.get_text("enabled") if checked else self.get_text("disabled")
        self.show_message(f"{self.get_text('ai_enable')}: {status}", "info")

    def change_ai_sidebar_mode(self, checked):
        """「改用侧边栏 AI 单独界面」开关：打开后悬浮球消失、左侧栏出现「AI」页，关闭后恢复。"""
        self.settings_manager.update_setting("ai_sidebar_mode", bool(checked))
        if self.main_window is not None and hasattr(self.main_window, "apply_ai_sidebar_mode"):
            try:
                self.main_window.apply_ai_sidebar_mode(bool(checked))
            except Exception as e:
                from ...utils.logger import log
                log.err("AI", "ai", f"切换侧边栏 AI 模式失败: {e}")
        status = self.get_text("enabled") if checked else self.get_text("disabled")
        self.show_message(f"{self.get_text('ai_sidebar_mode')}: {status}", "info")


    def _create_api_key_card(self):
        """创建 API Key 设置卡片：服务商 → 模型名称 → 接口地址 → API Key。

        两个下拉框都是可编辑的：清单里的选项只是常用值，用户可以自己敲。
        AI 抽屉里点蓝色 API Key 会滚到这里并让卡片整体闪两下（见 focus_api_key）。
        """
        from ...core.ai import providers as ai_providers

        card = SimpleCardWidget()
        # 保存引用：focus_api_key 要给这张卡片加高亮闪烁
        self._api_key_card = card
        self._api_key_overlay = None
        # 正在按程序逻辑联动设置控件（用于抑制"用户手动改了地址就不要再自动覆盖"）
        self._syncing_provider = False

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        api_key_widget = QWidget()
        api_key_layout = QVBoxLayout(api_key_widget)
        api_key_layout.setContentsMargins(0, 0, 0, 0)
        api_key_layout.setSpacing(10)

        # ---- 服务商行 ----
        provider_row = QHBoxLayout()
        provider_row.setSpacing(8)

        provider_label = BodyLabel(self.get_text("ai_provider"))
        provider_label.setObjectName("whiteInDarkLabel")
        provider_label.setFixedWidth(80)
        provider_row.addWidget(provider_label)
        provider_row.addWidget(self._make_tip_icon(self.get_text("ai_provider_tip")))

        self.ai_provider_combo = ComboBox()
        self.ai_provider_combo.setFixedHeight(35)
        self.ai_provider_combo.setMinimumWidth(240)
        for _pid, _label in ai_providers.provider_items():
            self.ai_provider_combo.addItem(_label, userData=_pid)

        # 当前该选中哪个：优先用存下来的 ai_provider；老配置没有这个字段时用接口地址 / 模型名反推
        # （见 guess_provider），否则用户会看到"地址是 Kimi 的，但服务商显示 DeepSeek"
        saved_provider = str(self.settings_manager.settings.get("ai_provider", "") or "")
        if ai_providers.get_provider(saved_provider) is None:
            saved_provider = ai_providers.guess_provider(
                self.settings_manager.settings.get("api_base", ""),
                self.settings_manager.settings.get("model_name", ""))
        self.ai_provider_combo.setCurrentIndex(
            self._index_of(ai_providers.provider_items(), saved_provider))
        self.ai_provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self.ai_provider_combo)
        provider_row.addStretch()
        api_key_layout.addLayout(provider_row)

        # ---- 模型名称行（可编辑下拉框：清单只是常用值，能自己敲） ----
        model_name_row = QHBoxLayout()
        model_name_row.setSpacing(8)

        model_name_label = BodyLabel(self.get_text("model_name"))
        model_name_label.setObjectName("whiteInDarkLabel")
        model_name_label.setFixedWidth(80)
        model_name_row.addWidget(model_name_label)
        model_name_row.addWidget(self._make_tip_icon(self.get_text("model_name_tip")))

        # ⚠️ qfluentwidgets 的 ComboBox 没有 setEditable()，"能选也能自己输"必须用 EditableComboBox。
        # 注意它是 LineEdit 的子类：有 currentText / setCurrentText / addItem，但没有 currentIndexChanged
        self.model_name_input = EditableComboBox()
        self.model_name_input.setFixedHeight(35)
        self.model_name_input.setPlaceholderText(self.get_text("model_name_placeholder"))
        self._fill_model_combo(saved_provider,
                               self.settings_manager.settings.get("model_name", ""))
        model_name_row.addWidget(self.model_name_input)
        api_key_layout.addLayout(model_name_row)

        # ---- 接口地址行 ----
        api_base_row = QHBoxLayout()
        api_base_row.setSpacing(8)

        api_base_label = BodyLabel(self.get_text("ai_api_base"))
        api_base_label.setObjectName("whiteInDarkLabel")
        api_base_label.setFixedWidth(80)
        api_base_row.addWidget(api_base_label)
        api_base_row.addWidget(self._make_tip_icon(self.get_text("ai_api_base_tip")))

        self.api_base_input = LineEdit()
        self.api_base_input.setFixedHeight(35)
        self.api_base_input.setPlaceholderText(self.get_text("ai_api_base_placeholder"))
        self.api_base_input.setText(
            str(self.settings_manager.settings.get("api_base", "") or ""))
        api_base_row.addWidget(self.api_base_input)
        api_key_layout.addLayout(api_base_row)

        # ---- API Key 行 ----
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        
        api_key_field_label = BodyLabel(self.get_text("api_key_section"))
        api_key_field_label.setObjectName("whiteInDarkLabel")
        api_key_field_label.setFixedWidth(80)
        input_row.addWidget(api_key_field_label)
        input_row.addWidget(self._make_tip_icon(self.get_text("api_key_tip")))
        
        self.api_key_input = LineEdit()
        self.api_key_input.setPlaceholderText(self.get_text("api_key_placeholder"))
        self.api_key_input.setFixedHeight(35)
        self.api_key_input.setEchoMode(LineEdit.Password)
        saved_api_key = self.settings_manager.get_api_key()
        if saved_api_key:
            self.api_key_input.setText(saved_api_key)
        input_row.addWidget(self.api_key_input)
        
        self.api_key_visibility_btn = PushButton(self.get_text("show"))
        self.api_key_visibility_btn.setFixedWidth(60)
        self.api_key_visibility_btn.clicked.connect(self.toggle_api_key_visibility)
        input_row.addWidget(self.api_key_visibility_btn)
        
        api_key_layout.addLayout(input_row)
        
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch()
        
        self.api_key_clear_btn = PushButton(self.get_text("clear"))
        self.api_key_clear_btn.setFixedWidth(80)
        self.api_key_clear_btn.clicked.connect(self.clear_api_key)
        button_row.addWidget(self.api_key_clear_btn)
        
        self.api_key_save_btn = PrimaryPushButton(self.get_text("save"))
        self.api_key_save_btn.setFixedWidth(80)
        self.api_key_save_btn.clicked.connect(self.save_api_key)
        button_row.addWidget(self.api_key_save_btn)
        
        api_key_layout.addLayout(button_row)
        layout.addWidget(api_key_widget)
        
        return card

    # ---------- 服务商 / 模型 / 地址的联动 ----------
    def _fill_model_combo(self, provider_id: str, current_model: str):
        """按服务商填充模型下拉框并选中合适的当前项（EditableComboBox 清空用 clear()，设值用 setCurrentText()）。"""
        from ...core.ai import providers as ai_providers

        self.model_name_input.clear()
        for model in ai_providers.models_of(provider_id):
            self.model_name_input.addItem(model)

        # 优先用配置里已有的模型名（哪怕它不在清单里也要显示出来，不能悄悄改掉用户的配置）
        target = str(current_model or "").strip() or ai_providers.default_model(provider_id)
        if target:
            self.model_name_input.setCurrentText(target)

    def _on_provider_changed(self, index):
        """换服务商：自动填它的接口地址 + 换成它的默认模型。

        ⚠️ 用户手改过接口地址就不要覆盖：当前地址不属于"任何服务商的标准地址"、又不为空，
        就认为是用户自己填的，换服务商时只换模型、保留地址（不做"改动即锁定"那种复杂状态机）。
        """
        from ...core.ai import providers as ai_providers

        provider_id = self.ai_provider_combo.currentData()
        if not provider_id:
            return

        self._syncing_provider = True
        try:
            standard_bases = {p["api_base"] for p in ai_providers.PROVIDERS if p["api_base"]}
            current_base = str(self.api_base_input.text() or "").strip()
            if current_base in standard_bases or not current_base:
                # 是标准地址（或空的）→ 跟着服务商走
                new_base = ai_providers.default_api_base(provider_id, current_base)
                if new_base:
                    self.api_base_input.setText(new_base)

            # 模型换成该服务商的默认模型
            self._fill_model_combo(provider_id, "")
        finally:
            self._syncing_provider = False

        self.settings_manager.update_setting("ai_provider", provider_id)


    def toggle_api_key_visibility(self):
        """切换 API Key 的显示/隐藏"""
        if self.api_key_input.echoMode() == LineEdit.Password:
            self.api_key_input.setEchoMode(LineEdit.Normal)
            self.api_key_visibility_btn.setText(self.get_text("hide"))
        else:
            self.api_key_input.setEchoMode(LineEdit.Password)
            self.api_key_visibility_btn.setText(self.get_text("show"))


    def save_api_key(self):
        """保存服务商、模型名称、接口地址与 API Key（API Key 会加密后落盘）。

        ⚠️ 下拉框可编辑，取值一律用 currentText()：用户可能敲了一个清单里没有的模型名，那时 currentData() 是空的。
        ⚠️ 接口地址先校验再保存：填错了不会马上报错，等用户去聊天时才发现"连不上"，那时很难联想到这里。
        """
        from ...core.ai.client import is_valid_api_base, normalize_api_base

        api_key = self.api_key_input.text().strip()
        model_name = self.model_name_input.currentText().strip()
        api_base = self.api_base_input.text().strip()
        provider = self.ai_provider_combo.currentData() or ""

        if not is_valid_api_base(api_base):
            self.show_message(self.get_text("ai_api_base_invalid"), "error")
            return
        if not model_name:
            self.show_message(self.get_text("model_name_required"), "error")
            return

        # 存的是规整后的地址（去尾斜杠、去掉用户多粘的 /chat/completions）
        normalized = normalize_api_base(api_base) if api_base else ""
        self.api_base_input.setText(normalized)

        self.settings_manager.set_api_key(api_key)
        self.settings_manager.update_setting("model_name", model_name)
        self.settings_manager.update_setting("api_base", normalized)
        if provider:
            self.settings_manager.update_setting("ai_provider", provider)

        # 让 AI 抽屉的标题跟着模型名变
        if self.main_window is not None and hasattr(self.main_window, "ai_chat_drawer"):
            try:
                self.main_window.ai_chat_drawer._update_title()
            except Exception:
                pass

        if api_key:
            self.show_message(self.get_text("model_name_saved"), "success")
        else:
            self.show_message(self.get_text("api_key_cleared"), "info")


    def clear_api_key(self):
        """仅清空 API Key（不影响模型名称与接口地址）"""
        self.api_key_input.clear()
        self.settings_manager.set_api_key("")
        self.show_message(self.get_text("api_key_cleared"), "info")


    def focus_api_key(self, flash: bool = True):
        """定位到 API Key 输入框：滚动到位 + 聚焦（可选：卡片闪两下）。

        flash 是给"跳转后补一次定位"用的：AI 抽屉跳过来时会调两次，两次都闪的话用户会看到连闪两轮。
        ⚠️ 整个方法包在 try 里：它被 QTimer 延迟调用，抛异常会变成孤立的报错，用户只看到"点了没反应"。
        """
        try:
            from PyQt5.QtWidgets import QApplication
            QApplication.processEvents()

            # 先切到「API Key」板块，再滚到输入框（保证它在视口里），最后闪卡片
            # ⚠️ 设置页改成"左列表 + 右内容"后，滚动区域不再是 self.scroll_area，而是板块那个 QScrollArea
            holder = None
            if hasattr(self, "ensure_section_visible"):
                holder = self.ensure_section_visible("api_key")
            if holder is not None and hasattr(self, "api_key_input"):
                holder.ensureWidgetVisible(self.api_key_input, 40, 120)
            QApplication.processEvents()

            if hasattr(self, "api_key_input") and self.api_key_input is not None:
                self.api_key_input.setFocus()

            if flash:
                self._flash_api_key_card()
        except Exception:
            pass


    def _flash_api_key_card(self):
        """让 API Key 卡片整体闪两下（亮 → 灭 → 亮 → 灭）。

        不用 setStyleSheet 改卡片背景（会触发整棵控件树重新 polish、和设置页主题样式表打架），
        改用一层不吃鼠标事件的透明覆盖层画描边 + 填充，动画结束就把覆盖层删掉。
        ⚠️ 进来先把上一次的覆盖层停掉并删掉再重播，否则第二次点会看不出来。
        """
        card = getattr(self, "_api_key_card", None)
        if card is None:
            return
        try:
            old = getattr(self, "_api_key_overlay", None)
            if old is not None:
                old.stop()
                old.deleteLater()
                self._api_key_overlay = None

            overlay = CardHighlightOverlay(card)
            overlay.start()
            self._api_key_overlay = overlay
        except Exception as e:
            from ...utils.logger import log
            log.err("AI", "highlight", f"API Key 卡片高亮失败: {e}")


    def _create_model_calling_card(self):
        """创建模型调用卡片（限制token输出 + 最小/最大token输入框）"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 限制token输出开关
        limit_widget = QWidget()
        limit_layout = QHBoxLayout(limit_widget)
        limit_layout.setContentsMargins(0, 0, 0, 0)

        limit_label = BodyLabel(self.get_text("limit_token_output"))
        limit_label.setObjectName("whiteInDarkLabel")
        limit_layout.addWidget(limit_label)
        limit_layout.addStretch()

        self.limit_token_switch = SwitchButton()
        self.limit_token_switch.setChecked(self.settings_manager.settings.get("limit_token_output", False))
        self.limit_token_switch.checkedChanged.connect(self._on_limit_token_changed)
        limit_layout.addWidget(self.limit_token_switch)
        layout.addWidget(limit_widget)

        # token 输入区域（开关关闭时隐藏）
        self.token_input_container = QWidget()
        token_layout = QHBoxLayout(self.token_input_container)
        token_layout.setContentsMargins(0, 0, 0, 0)
        token_layout.setSpacing(12)

        min_label = BodyLabel(self.get_text("min_token_placeholder") + ":")
        min_label.setObjectName("whiteInDarkLabel")
        min_label.setFixedWidth(90)
        token_layout.addWidget(min_label)

        self.min_token_input = LineEdit()
        self.min_token_input.setPlaceholderText(self.get_text("min_token_placeholder"))
        self.min_token_input.setFixedHeight(35)
        self.min_token_input.setValidator(QDoubleValidator(0.0, 1000000.0, 2))
        saved_min = self.settings_manager.settings.get("min_token", 0.5)
        if saved_min == 0:
            saved_min = 0.5
        self.min_token_input.setText(str(saved_min))
        token_layout.addWidget(self.min_token_input, 1)

        min_unit = QLabel(self.get_text("token_unit"))
        min_unit.setObjectName("whiteInDarkLabel")
        min_unit.setFixedWidth(50)
        token_layout.addWidget(min_unit)

        token_layout.addSpacing(20)

        max_label = BodyLabel(self.get_text("max_token_placeholder") + ":")
        max_label.setObjectName("whiteInDarkLabel")
        max_label.setFixedWidth(90)
        token_layout.addWidget(max_label)

        self.max_token_input = LineEdit()
        self.max_token_input.setPlaceholderText(self.get_text("max_token_placeholder"))
        self.max_token_input.setFixedHeight(35)
        self.max_token_input.setValidator(QIntValidator(0, 1000000))
        saved_max = self.settings_manager.settings.get("max_token", 4096)
        self.max_token_input.setText(str(saved_max))
        token_layout.addWidget(self.max_token_input, 1)

        max_unit = QLabel(self.get_text("token_unit"))
        max_unit.setObjectName("whiteInDarkLabel")
        max_unit.setFixedWidth(50)
        token_layout.addWidget(max_unit)

        layout.addWidget(self.token_input_container)

        self.token_input_container.setVisible(self.limit_token_switch.isChecked())

        self.min_token_input.textChanged.connect(self._save_token_settings)
        self.max_token_input.textChanged.connect(self._save_token_settings)

        return card


    def _on_limit_token_changed(self, checked):
        """限制token输出开关变化"""
        self.settings_manager.update_setting("limit_token_output", checked)
        self.token_input_container.setVisible(checked)
        status = self.get_text("enabled") if checked else self.get_text("disabled")
        self.show_message(f"{self.get_text('limit_token_output')}: {status}", "info")


    def _save_token_settings(self):
        """保存token设置"""
        try:
            min_val = float(self.min_token_input.text()) if self.min_token_input.text() else 0.5
        except ValueError:
            min_val = 0.5
        try:
            max_val = int(self.max_token_input.text()) if self.max_token_input.text() else 4096
        except ValueError:
            max_val = 4096
        self.settings_manager.update_setting("min_token", min_val)
        self.settings_manager.update_setting("max_token", max_val)

