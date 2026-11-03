"""设置页的卡片与回调（搜索 / 快捷键）：快捷键相关的控件和回调都在这里。

通过 mixin 组合进 SettingsInterface。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from qfluentwidgets import (SimpleCardWidget, ComboBox, SwitchButton, LineEdit,
                            PrimaryPushButton, BodyLabel, SubtitleLabel,
                            ToolTipFilter, ToolTipPosition, PushButton, CheckBox)

from ...utils.smooth_scroll import install_smooth_scroll
from ...utils.global_hotkey import unusable_main_key
from ...ui.hotkey_edit import HotkeyEdit

from .common import HOTKEY_DEFAULTS


class SettingsCardsHotkeyMixin:
    def _create_hotkey_card(self):
        """创建快捷键卡片"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 总开关
        enable_widget = QWidget()
        enable_layout = QHBoxLayout(enable_widget)
        enable_layout.setContentsMargins(0, 0, 0, 0)

        enable_label = BodyLabel(self.get_text("hotkey_enable"))
        enable_label.setObjectName("whiteInDarkLabel")
        enable_layout.addWidget(enable_label)

        enable_tip = QLabel("ⓘ")
        enable_tip.setObjectName("whiteInDarkIcon")
        enable_tip.setToolTip(self.get_text("hotkey_enable_tip"))
        enable_tip.installEventFilter(ToolTipFilter(enable_tip, 300, ToolTipPosition.TOP))
        enable_layout.addWidget(enable_tip)
        enable_layout.addStretch()

        self.hotkey_switch = SwitchButton()
        self.hotkey_switch.setChecked(self.settings_manager.settings.get("hotkey_enabled", True))
        self.hotkey_switch.checkedChanged.connect(self.change_hotkey_enabled)
        enable_layout.addWidget(self.hotkey_switch)
        layout.addWidget(enable_widget)

        # 从属项：呼出搜索框 / 呼出 GCP-AI
        # ⚠️ 默认值统一从 HOTKEY_DEFAULTS 取，不要在这里再写一份字面量：这里原来写的坏默认值
        # （Caps Lock 做主键，RegisterHotKey 必然失败）会让缺这个键的配置显示一个根本注册不上的快捷键
        self.hotkey_edits = {}
        for key, label_key, tip_key in (
                ("search", "hotkey_search", "hotkey_search_tip"),
                ("ai", "hotkey_ai", "hotkey_ai_tip")):
            setting_key, default = HOTKEY_DEFAULTS[key]
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(20, 0, 0, 0)   # 左侧缩进，表示是从属项
            row_layout.setSpacing(8)

            label = BodyLabel(self.get_text(label_key))
            label.setObjectName("whiteInDarkLabel")
            row_layout.addWidget(label)

            tip = QLabel("ⓘ")
            tip.setObjectName("whiteInDarkIcon")
            tip.setToolTip(self.get_text(tip_key))
            tip.installEventFilter(ToolTipFilter(tip, 300, ToolTipPosition.TOP))
            row_layout.addWidget(tip)
            row_layout.addStretch()

            edit = HotkeyEdit(self.settings_manager.settings.get(setting_key, default))
            # 占位提示跟着界面语言走（HotkeyEdit 里的默认值是中文，在这里覆盖掉）
            try:
                edit.setPlaceholderText(self.get_text("hotkey_placeholder"))
            except Exception:
                pass
            edit.sequenceChanged.connect(
                lambda seq, k=key: self.change_hotkey(k, seq))

            # 注册状态小字：用户最想知道的就是"这个键到底生效了没有"（只在启动时弹一条会消失的 InfoBar
            # 不够 —— 键没注册上时界面上看不出任何异常）。
            # ⚠️ 位置按需求挪到输入框左边、宽度自适应，输入框就紧挨着「恢复默认」了
            # （原来它占着输入框和「恢复默认」之间那 150px，注册成功时是空的，看着就是莫名其妙的空隙）
            status_label = QLabel("")
            status_label.setStyleSheet("color: gray; font-size: 11px;")
            row_layout.addWidget(status_label)

            row_layout.addWidget(edit)

            reset_btn = PushButton(self.get_text("hotkey_reset"))
            reset_btn.setFixedWidth(90)
            reset_btn.clicked.connect(lambda _c=False, k=key: self.reset_hotkey(k))
            row_layout.addWidget(reset_btn)

            layout.addWidget(row_widget)

            self.hotkey_labels = getattr(self, "hotkey_labels", {})
            self.hotkey_labels[key] = (label, tip, reset_btn)
            self.hotkey_edits[key] = edit
            self.hotkey_status_labels = getattr(self, "hotkey_status_labels", {})
            self.hotkey_status_labels[key] = status_label

        hint = QLabel(self.get_text("hotkey_hint"))
        hint.setObjectName("whiteInDarkLabel")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        self.update_hotkey_state(self.hotkey_switch.isChecked())
        return card

    def update_hotkey_state(self, enabled):
        """快捷键总开关关闭时，把下面这几行整体置灰"""
        for edit in getattr(self, "hotkey_edits", {}).values():
            edit.setEnabled(enabled)
        for label, tip, reset_btn in getattr(self, "hotkey_labels", {}).values():
            reset_btn.setEnabled(enabled)
            self.set_label_disabled(label, not enabled)
            self.set_label_disabled(tip, not enabled)
        if not enabled:
            for status in getattr(self, "hotkey_status_labels", {}).values():
                status.setText("")

    def set_hotkey_status(self, status: dict):
        """显示每个热键的注册结果：只提示"没生效"（红色）。

        status 形如 {"search": (True, "Ctrl+Q"), "ai": (False, "……占用")}，由 MainWindow.apply_hotkey_settings 推过来。
        ⚠️ 注册成功不再显示绿色的"已注册"（正常情况本来就该如此，写在那里只是噪音）；只有失败才留一行红字。
        """
        colors = self._hotkey_status_colors()
        for name, label in getattr(self, "hotkey_status_labels", {}).items():
            entry = (status or {}).get(name)
            if not entry or entry[0]:
                label.setText("")
                label.setStyleSheet("color: gray; font-size: 11px;")
                label.setToolTip("")
                continue
            label.setText(f"✕ {self.get_text('hotkey_failed')}")
            label.setStyleSheet(f"color: {colors['bad']}; font-size: 11px;")
            label.setToolTip(str(entry[1] or ""))

    def _hotkey_status_colors(self) -> dict:
        """状态小字的颜色（取自设置页色板，深浅色各一套）"""
        from .theme import tokens
        c = tokens(self.is_dark_mode())
        return {"bad": c["danger"]}

    def sync_hotkey_edits(self):
        """把两个输入框里的值重新读一遍配置（启动时迁移过默认值之后要用）"""
        for name, edit in getattr(self, "hotkey_edits", {}).items():
            setting_key, default = HOTKEY_DEFAULTS[name]
            value = str(self.settings_manager.settings.get(setting_key, default) or "")
            try:
                edit.blockSignals(True)
                edit.setSequence(value)
            except Exception:
                pass
            finally:
                try:
                    edit.blockSignals(False)
                except Exception:
                    pass

    def change_hotkey_enabled(self, checked):
        """全局快捷键开关状态改变"""
        self.settings_manager.update_setting("hotkey_enabled", checked)
        self.update_hotkey_state(checked)

        ok, err = self._apply_hotkey()

        if checked and not ok:
            # 注册不上就回滚开关，避免"显示开着但实际没生效"
            self.hotkey_switch.blockSignals(True)
            self.hotkey_switch.setChecked(False)
            self.hotkey_switch.blockSignals(False)
            self.settings_manager.update_setting("hotkey_enabled", False)
            self.update_hotkey_state(False)
            self.show_message(err, "error")
            return

        status = self.get_text("enabled") if checked else self.get_text("disabled")
        self.show_message(f"{self.get_text('hotkey_enable')}: {status}", "info")

    def change_hotkey(self, name: str, sequence: str):
        """用户录入了新的快捷键（「恢复默认」也走这里）"""
        if not sequence:
            return
        setting_key, default = HOTKEY_DEFAULTS[name]
        old = self.settings_manager.settings.get(setting_key, default)
        if sequence == old:
            # ⚠️ 值没变也要同步输入框：否则录了和配置相同的键、或「恢复默认」时，框里停在旧文字上像没生效
            self._sync_edit(name, sequence)
            return

        # ⚠️ Caps Lock / Num Lock / Scroll Lock 不能做主键：RegisterHotKey 会直接失败（错误码 1409）。
        # 报错必须说清原因，否则用户只会看到"已被其它程序占用，请换一个"，然后一遍遍去换别的软件
        bad_key = unusable_main_key(sequence)
        if bad_key:
            self._sync_edit(name, old)
            self.show_message(
                self.get_text("hotkey_err_system_key",
                              "{key} cannot be the main key of a shortcut "
                              "(the system reserves it) — please pick another "
                              "combination").format(key=bad_key),
                "error")
            return

        self.settings_manager.update_setting(setting_key, sequence)
        if not self.hotkey_switch.isChecked():
            self._sync_edit(name, sequence)
            self.show_message(f"{self.get_text('hotkey_' + name)}: {sequence}", "success")
            return

        ok, err = self._apply_hotkey()
        if ok:
            # ★ 注册成功也必须把输入框同步成真正生效的那个值（以前只有失败分支才回写，点「恢复默认」时框里不变）
            self._sync_edit(name, sequence)
            self.show_message(f"{self.get_text('hotkey_' + name)}: {sequence}", "success")
        else:
            # 新键注册失败：回滚到原来的键
            self.settings_manager.update_setting(setting_key, old)
            self._sync_edit(name, old)
            self._apply_hotkey()
            self.show_message(err, "error")

    def _sync_edit(self, name: str, sequence: str):
        """把输入框的内容同步成 sequence（并顺手让它失焦）。

        ⚠️ 录完 / 恢复默认后要 clearFocus()：录制框是"点一下进入录键状态"，不失焦的话用户随便按个键就又录一遍。
        ⚠️ 要把真正生效的键写回框里（以前点「恢复默认」输入框没变回去）。
        """
        edit = self.hotkey_edits.get(name)
        if edit is None:
            return
        try:
            edit.blockSignals(True)
            edit.setSequence(sequence)
        except Exception:
            pass
        finally:
            try:
                edit.blockSignals(False)
            except Exception:
                pass
        try:
            edit.clearFocus()
        except Exception:
            pass

    def reset_hotkey(self, name: str):
        """恢复默认快捷键"""
        self.change_hotkey(name, HOTKEY_DEFAULTS[name][1])

    def _apply_hotkey(self):
        """让主窗口按当前设置重新注册快捷键"""
        if self.main_window is not None and hasattr(self.main_window, "apply_hotkey_settings"):
            return self.main_window.apply_hotkey_settings(notify=False)
        return True, None

    def _create_search_card(self):
        """创建搜索配置卡片"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # ⚠️ 卡片里不再重复写板块名：页头（左列表 + 页面标题）已经写过一遍，再写就是"搜索 / 搜索"这种重复

        # 自动搜索
        auto_search_widget = QWidget()
        auto_search_layout = QHBoxLayout(auto_search_widget)
        auto_search_layout.setContentsMargins(0, 0, 0, 0)

        auto_search_label = BodyLabel(self.get_text("auto_search"))
        auto_search_label.setObjectName("whiteInDarkLabel")
        auto_search_layout.addWidget(auto_search_label)

        auto_search_tip = QLabel("ⓘ")
        auto_search_tip.setObjectName("whiteInDarkIcon")
        auto_search_tip.setToolTip(self.get_text("auto_search_tip"))
        auto_search_tip.installEventFilter(ToolTipFilter(auto_search_tip, 300, ToolTipPosition.TOP))
        auto_search_layout.addWidget(auto_search_tip)
        auto_search_layout.addStretch()

        self.auto_search_switch = SwitchButton()
        auto_search_enabled = self.settings_manager.settings.get("auto_search", True)
        self.auto_search_switch.setChecked(auto_search_enabled)
        self.auto_search_switch.checkedChanged.connect(self.change_auto_search)
        auto_search_layout.addWidget(self.auto_search_switch)
        layout.addWidget(auto_search_widget)

        # 显示 GitHub 按钮：默认开启（不想看的用户自己来设置里关掉）
        github_widget = QWidget()
        github_layout = QHBoxLayout(github_widget)
        github_layout.setContentsMargins(0, 0, 0, 0)

        github_label = BodyLabel(self.get_text("show_github_button"))
        github_label.setObjectName("whiteInDarkLabel")
        github_layout.addWidget(github_label)

        github_tip = QLabel("ⓘ")
        github_tip.setObjectName("whiteInDarkIcon")
        github_tip.setToolTip(self.get_text("show_github_button_tip"))
        github_tip.installEventFilter(ToolTipFilter(github_tip, 300, ToolTipPosition.TOP))
        github_layout.addWidget(github_tip)
        github_layout.addStretch()

        self.github_button_switch = SwitchButton()
        self.github_button_switch.setChecked(
            self.settings_manager.settings.get("search_show_github", True))
        self.github_button_switch.checkedChanged.connect(self.change_github_button)
        github_layout.addWidget(self.github_button_switch)
        layout.addWidget(github_widget)

        # 在搜索页显示"视图切换按钮"（磁贴 / 网格那个小分段控件）
        # 默认开启；关闭时搜索页隐藏这个控件、排序 ui 自动右移补齐位置，而「搜索页视图」下拉框照旧能用
        view_switch_widget = QWidget()
        view_switch_layout = QHBoxLayout(view_switch_widget)
        view_switch_layout.setContentsMargins(0, 0, 0, 0)

        view_switch_label = BodyLabel(self.get_text("show_view_switch"))
        view_switch_label.setObjectName("whiteInDarkLabel")
        view_switch_layout.addWidget(view_switch_label)

        view_switch_tip = QLabel("ⓘ")
        view_switch_tip.setObjectName("whiteInDarkIcon")
        view_switch_tip.setToolTip(self.get_text("show_view_switch_tip"))
        view_switch_tip.installEventFilter(
            ToolTipFilter(view_switch_tip, 300, ToolTipPosition.TOP))
        view_switch_layout.addWidget(view_switch_tip)
        view_switch_layout.addStretch()

        self.view_switch_button = SwitchButton()
        self.view_switch_button.setChecked(
            self.settings_manager.settings.get("search_show_view_switch", True))
        self.view_switch_button.checkedChanged.connect(self.change_view_switch)
        view_switch_layout.addWidget(self.view_switch_button)
        layout.addWidget(view_switch_widget)

        # 搜索页视图：磁贴（默认，一行 4 个大卡片）/ 网格（一行 6 个小卡片）
        view_widget = QWidget()
        view_layout = QHBoxLayout(view_widget)
        view_layout.setContentsMargins(0, 0, 0, 0)

        view_label = BodyLabel(self.get_text("search_view_mode"))
        view_label.setObjectName("whiteInDarkLabel")
        view_layout.addWidget(view_label)

        view_tip = QLabel("ⓘ")
        view_tip.setObjectName("whiteInDarkIcon")
        view_tip.setToolTip(self.get_text("search_view_mode_tip"))
        view_tip.installEventFilter(ToolTipFilter(view_tip, 300, ToolTipPosition.TOP))
        view_layout.addWidget(view_tip)
        view_layout.addStretch()

        self.search_view_combo = ComboBox()
        self.search_view_combo.addItem(self.get_text("search_view_tile"), userData="tile")
        self.search_view_combo.addItem(self.get_text("search_view_grid"), userData="grid")
        self.search_view_combo.setFixedWidth(180)
        self.search_view_combo.setCurrentIndex(
            0 if str(self.settings_manager.settings.get("search_view") or "tile") == "tile" else 1)
        self.search_view_combo.currentIndexChanged.connect(self.change_search_view)
        view_layout.addWidget(self.search_view_combo)
        layout.addWidget(view_widget)

        return card

    def change_github_button(self, checked):
        """搜索页卡片上的 GitHub 按钮显示开关"""
        self.settings_manager.update_setting("search_show_github", bool(checked))
        if self.main_window is not None:
            search = getattr(self.main_window, "searchInterface", None)
            if search is not None and hasattr(search, "apply_github_button_setting"):
                search.apply_github_button_setting()
        status = self.get_text("enabled") if checked else self.get_text("disabled")
        self.show_message(f"{self.get_text('show_github_button')}: {status}", "info")

    def change_view_switch(self, checked):
        """「在搜索页显示视图切换按钮」开关。

        关掉只是把搜索页工具栏上那个分段控件藏起来（排序会右移补齐位置）；「搜索页视图」下拉框照旧能用。
        """
        self.settings_manager.update_setting("search_show_view_switch", bool(checked))
        if self.main_window is not None:
            search = getattr(self.main_window, "searchInterface", None)
            if search is not None and hasattr(search, "apply_view_switch_setting"):
                search.apply_view_switch_setting()
        status = self.get_text("enabled") if checked else self.get_text("disabled")
        self.show_message(f"{self.get_text('show_view_switch')}: {status}", "info")

    def change_search_view(self, index: int):
        """切换搜索页视图（磁贴 / 网格）"""
        key = self.search_view_combo.itemData(index) or "tile"
        self.settings_manager.update_setting("search_view", key)
        if self.main_window is not None:
            search = getattr(self.main_window, "searchInterface", None)
            if search is not None and hasattr(search, "apply_view_mode"):
                search.apply_view_mode(key, persist=False)
        self.show_message(f"{self.get_text('search_view_mode')}："
                          f"{self.search_view_combo.currentText()}", "success")

    def sync_search_controls(self):
        """把设置页里两个搜索相关的控件刷新成当前配置值。

        搜索页工具栏上也有一个视图切换按钮，两边改的是同一个设置；回到设置页时重读一次，免得显示旧的那一档。
        """
        try:
            key = str(self.settings_manager.settings.get("search_view") or "tile")
            combo = getattr(self, "search_view_combo", None)
            if combo is not None:
                combo.blockSignals(True)
                combo.setCurrentIndex(0 if key == "tile" else 1)
                combo.blockSignals(False)
            switch = getattr(self, "github_button_switch", None)
            if switch is not None:
                switch.blockSignals(True)
                switch.setChecked(
                    bool(self.settings_manager.settings.get("search_show_github", True)))
                switch.blockSignals(False)
            view_switch = getattr(self, "view_switch_button", None)
            if view_switch is not None:
                view_switch.blockSignals(True)
                view_switch.setChecked(
                    bool(self.settings_manager.settings.get(
                        "search_show_view_switch", True)))
                view_switch.blockSignals(False)
        except Exception:
            pass

    def change_auto_search(self, checked):
        """自动搜索开关状态改变"""
        self.settings_manager.update_setting("auto_search", checked)
        status = self.get_text("enabled") if checked else self.get_text("disabled")
        self.show_message(f"{self.get_text('auto_search')}: {status}", "info")

    # ⚠️ change_card_size 已随「搜索页卡片大小」一起删掉；卡片尺寸/排版现在由「搜索页视图」决定
