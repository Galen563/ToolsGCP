"""GCP-AI Agent 的配置界面
⚠️ 只是配置界面，不是聊天窗口：聊天一律在 GCP-AI 自己的界面里进行（右侧抽屉，或
   左侧栏那页整页 AI）。开启后用户在那边说话，AI 就能动手操作 ToolsGCP。
页面结构（一个 QStackedWidget 两页）：
    页 0配置  标题 / 总开关 / 更多模块入口 / 最近动作 / 统计
    页 1更多模块  返回 + 全部开启-关闭，每项"手"一行：名字 + 说明 + 开关
⚠️ 三条硬规矩：
    1. `context.ai_agent` 可能是 None，所有读 Agent 的地方都要判空并退回"暂时不可用"。
    2. AgentBridge 的每个方法都要 try/except 包住，任何一个不稳都不该把界面刷崩。
    3. 文案全部走 i18n，界面上没有一个写死的中文/英文句子。
⚠️ 每个模块的开关存在 ToolsGCP 设置里（`gcp_ai_agent_tools_off`，只记**关掉的**），
   所以总开关来回拨不会影响它们。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, FluentIcon as FIF, InfoBar, InfoBarPosition,
    PushButton, SimpleCardWidget, StrongBodyLabel,
    SubtitleLabel, SwitchButton,
)

MONO_FAMILIES = ["Consolas", "Cascadia Mono", "JetBrains Mono", "Menlo", "monospace"]

# 状态色：主题里没有"开/关/警告"这种语义色，只用在几行小标签上，直接写死
COLOR_ON = "#0f7b0f"
COLOR_OFF = "#8a8886"
COLOR_WARN = "#c42b1c"

# 统计行最多列几个调用明细
MAX_CALL_ITEMS = 8


def _mono_font() -> QFont:
    """等宽字体：取不到就退回系统默认，不让它抛异常"""
    font = QFont()
    try:
        font.setFamilies(MONO_FAMILIES)      # Qt 5.13+ 才有多字体回退列表
    except Exception:
        font.setFamily(MONO_FAMILIES[0])
    return font


class AgentPage(QWidget):
    """插件的配置界面：总开关 + 更多模块 + 最近动作 + 统计"""

    PAGE_MAIN = 0
    PAGE_MODULES = 1

    def __init__(self, context, config, i18n, parent=None):
        super().__init__(parent)
        self.context = context
        self.config = config
        self.i18n = i18n

        self.stack = None
        self.switch = None
        self.switch_hint = None
        self.modules_count = None
        self.modules_box = None
        self.modules_layout = None
        self.actions_box = None
        self.actions_layout = None
        self.stats_label = None
        # 模块行缓存：工具名 → SwitchButton
        self._module_rows = {}
        # 刷新期间别让开关的信号回头再写一次设置
        self._syncing = False

        try:
            # objectName 带上插件 id：主题刷新时主程序靠它认页面
            self.setObjectName(f"plugin_{context.id}")
        except Exception:
            pass

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack)

        self.stack.addWidget(self._build_main_page())
        self.stack.addWidget(self._build_modules_page())

        self.refresh()

    # ---------- 通用小工具 ----------
    def _log(self, message: str, level: str = "info"):
        """写日志：日志本身出问题也不能影响界面"""
        try:
            self.context.log(str(message), level=level)
        except Exception:
            pass

    def _agent(self):
        """安全地取 context.ai_agent；⚠️ 它是属性，可能是 None，访问还可能抛异常"""
        try:
            return getattr(self.context, "ai_agent", None)
        except Exception as exc:
            self._log(f"取 ai_agent 失败: {exc}", "err")
            return None

    def _scroll_page(self) -> tuple:
        """建一个"可滚动的一页"，返回 (page, 内容 layout)"""
        page = QWidget(self.stack)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # 横向不滚动：文字按宽度换行，压扁的布局里 qfluentwidgets 卡片会画错
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        layout.addStretch(1)
        scroll.setWidget(content)
        # ⚠️ 让宿主套上主程序同款（细圆角 + 惯性滚动）的滚动条；老宿主没这个方法
        #    就保持原样，绝不能因此崩掉。
        try:
            style = getattr(self.context, "style_scroll_area", None)
            if callable(style):
                style(scroll)
        except Exception as exc:
            self._log(f"滚动条样式没装上（不影响使用）: {exc}", "warn")
        outer.addWidget(scroll)
        return page, layout

    def _new_card(self, parent, title_key: str, desc_key: str = ""):
        """统一风格的卡片：标题 + 一句说明 + 由调用方往 layout 里塞内容"""
        card = SimpleCardWidget(parent)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel(self.i18n.t(title_key), card))
        if desc_key:
            desc = CaptionLabel(self.i18n.t(desc_key), card)
            desc.setWordWrap(True)
            layout.addWidget(desc)
        return card, layout

    def _hint(self, parent, text) -> CaptionLabel:
        """一行灰色提示（空列表 / 出错 / 不可用都用它）"""
        label = CaptionLabel(str(text or ""), parent)
        label.setWordWrap(True)
        return label

    @staticmethod
    def _clear_layout(layout):
        """把布局里的控件全部拆掉并交给 Qt 销毁；⚠️ 必须 deleteLater，只摘不删会漏控件"""
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            child = item.layout()
            if child is not None:
                AgentPage._clear_layout(child)

    def _toast(self, level: str, text: str):
        """弹一条 InfoBar 提示；界面没挂到主窗口上时可能弹不出来（兜住，不抛）"""
        try:
            content = str(text or "")
            if level == "ok":
                InfoBar.success(self.i18n.t("title"), content, duration=2500,
                                position=InfoBarPosition.TOP_RIGHT, parent=self)
            else:
                InfoBar.warning(self.i18n.t("title"), content, duration=3500,
                                position=InfoBarPosition.TOP_RIGHT, parent=self)
        except Exception as exc:
            self._log(f"显示提示失败: {exc}", "err")

    # ---------- 页 0：配置 ----------
    def _build_main_page(self) -> QWidget:
        page, layout = self._scroll_page()
        for builder in (self._build_header, self._build_switch_card,
                        self._build_actions_card):
            try:
                widget = builder(page)
                if widget is not None:
                    # 插在末尾的弹簧之前
                    layout.insertWidget(layout.count() - 1, widget)
            except Exception as exc:
                self._log(f"构建卡片 {getattr(builder, '__name__', builder)} 失败: {exc}",
                          "err")
        return page

    def _build_header(self, parent):
        box = QWidget(parent)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(SubtitleLabel(self.i18n.t("title"), box))
        intro = BodyLabel(self.i18n.t("intro"), box)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        return box

    def _build_switch_card(self, parent):
        """总开关 + 模块计数 + 统计：合成一张卡（页面收敛成三块，观感更简洁）"""
        card, layout = self._new_card(parent, "sec_switch", "sec_switch_desc")

        row = QHBoxLayout()
        row.setSpacing(12)

        switch = SwitchButton(card)
        switch.setOnText(self.i18n.t("switch_on"))
        switch.setOffText(self.i18n.t("switch_off"))
        switch.checkedChanged.connect(self._on_switch_changed)
        row.addWidget(switch)
        self.switch = switch

        hint = CaptionLabel("", card)
        hint.setWordWrap(True)
        row.addWidget(hint, 1)
        self.switch_hint = hint
        layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.modules_count = CaptionLabel("", card)
        self.modules_count.setWordWrap(True)
        row2.addWidget(self.modules_count, 1)

        open_btn = PushButton(self.i18n.t("btn_open_modules"), card, FIF.SETTING)
        open_btn.clicked.connect(lambda: self.show_modules(True))
        open_btn.setMinimumWidth(150)
        row2.addWidget(open_btn)
        layout.addLayout(row2)

        self.stats_label = CaptionLabel("", card)
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)
        return card

    def _refresh_switch(self):
        """读一次 Agent 的开关状态（判空 + 兜异常都在这）"""
        if self.switch is None:
            return
        agent = self._agent()
        if agent is None:
            self._set_switch_unavailable(self.i18n.t("switch_unavailable"))
            return
        try:
            on = bool(agent.enabled())
        except Exception as exc:
            # 界面上给一句"读取失败"，日志里留完整原因
            self._log(f"读 Agent 开关失败: {exc}", "err")
            self._set_switch_unavailable(self.i18n.t("refresh_failed", error=exc))
            return

        # ⚠️ setChecked 会发 checkedChanged，不挡信号就会自己回写设置
        self._syncing = True
        self.switch.blockSignals(True)
        try:
            self.switch.setChecked(on)
        finally:
            self.switch.blockSignals(False)
            self._syncing = False
        self.switch.setEnabled(True)
        self._set_hint(self.i18n.t("switch_hint_on" if on else "switch_hint_off"),
                       COLOR_ON if on else COLOR_OFF)

    def _set_switch_unavailable(self, message: str):
        """Agent 不可用：开关禁用 + 一行警告，而不是崩掉"""
        if self.switch is not None:
            self._syncing = True
            self.switch.blockSignals(True)
            try:
                self.switch.setChecked(False)
                self.switch.setEnabled(False)
            finally:
                self.switch.blockSignals(False)
                self._syncing = False
        self._set_hint(message, COLOR_WARN)

    def _set_hint(self, text: str, color: str):
        if self.switch_hint is None:
            return
        try:
            self.switch_hint.setText(str(text or ""))
            self.switch_hint.setStyleSheet(f"color: {color};")
        except Exception as exc:
            self._log(f"更新开关提示失败: {exc}", "err")

    def _on_switch_changed(self, checked: bool):
        """用户拨了开关：写进设置，然后把界面按真实状态重画一遍"""
        if self._syncing:
            return
        agent = self._agent()
        if agent is None:
            self._toast("warn", self.i18n.t("switch_unavailable"))
            self._refresh_switch()
            return
        try:
            agent.set_enabled(bool(checked))
            self._log(f"用户切换总开关: {bool(checked)}")
        except Exception as exc:
            self._log(f"切换总开关失败: {exc}", "err")
            self._toast("warn", self.i18n.t("switch_toggle_failed", error=exc))
        # 按真实读回来的状态显示，免得开关和实际不一致
        self._refresh_switch()

    # ---------- 页 0：模块计数（入口按钮并进了"总开关"那张卡） ----------
    def _refresh_modules_count(self):
        """入口卡片上那行"已开启 n / 共 m 项" """
        if self.modules_count is None:
            return
        agent = self._agent()
        if agent is None:
            self.modules_count.setText(self.i18n.t("switch_unavailable"))
            return
        try:
            tools = [t for t in (agent.tools() or []) if isinstance(t, dict)]
        except Exception as exc:
            self._log(f"读模块列表失败: {exc}", "err")
            self.modules_count.setText(self.i18n.t("refresh_failed", error=exc))
            return
        on = len([t for t in tools if t.get("enabled")])
        try:
            self.modules_count.setText(self.i18n.t(
                "modules_enabled_count", on=on, total=len(tools)))
        except Exception as exc:
            self._log(f"更新模块计数失败: {exc}", "err")

    # ---------- 页 1：更多模块（每一项一个开关） ----------
    def _build_modules_page(self) -> QWidget:
        page, layout = self._scroll_page()

        head = QWidget(page)
        head_layout = QVBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)
        back_btn = PushButton(self.i18n.t("btn_back"), head, FIF.RETURN)
        back_btn.clicked.connect(lambda: self.show_modules(False))
        row.addWidget(back_btn)
        row.addStretch(1)

        all_on = PushButton(self.i18n.t("btn_all_on"), head, FIF.ACCEPT)
        all_on.clicked.connect(lambda: self._set_all_modules(True))
        row.addWidget(all_on)

        all_off = PushButton(self.i18n.t("btn_all_off"), head, FIF.CLOSE)
        all_off.clicked.connect(lambda: self._set_all_modules(False))
        row.addWidget(all_off)
        head_layout.addLayout(row)

        head_layout.addWidget(SubtitleLabel(self.i18n.t("modules_title"), head))
        desc = CaptionLabel(self.i18n.t("modules_desc"), head)
        desc.setWordWrap(True)
        head_layout.addWidget(desc)
        layout.insertWidget(layout.count() - 1, head)

        box = QWidget(page)
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(10)
        layout.insertWidget(layout.count() - 1, box)
        self.modules_box = box
        self.modules_layout = box_layout

        return page

    def show_modules(self, show: bool):
        """在"配置"和"更多模块"两页之间切"""
        if self.stack is None:
            return
        try:
            self.stack.setCurrentIndex(self.PAGE_MODULES if show else self.PAGE_MAIN)
        except Exception:
            pass
        if show:
            self._render_modules()

    def _refresh_modules(self):
        """从 AgentBridge 读一遍模块清单，再画出来"""
        if self.modules_layout is None:
            return
        self._clear_layout(self.modules_layout)
        self._module_rows = {}

        agent = self._agent()
        if agent is None:
            self.modules_layout.addWidget(
                self._hint(self.modules_box, self.i18n.t("switch_unavailable")))
            return
        try:
            tools = [t for t in (agent.tools() or []) if isinstance(t, dict)]
        except Exception as exc:
            self._log(f"读模块清单失败: {exc}", "err")
            self.modules_layout.addWidget(self._hint(
                self.modules_box, self.i18n.t("refresh_failed", error=exc)))
            return

        if not tools:
            self.modules_layout.addWidget(
                self._hint(self.modules_box, self.i18n.t("modules_empty")))
            return

        for tool in tools:
            try:
                self.modules_layout.addWidget(self._module_row(tool))
            except Exception as exc:
                self._log(f"画模块行失败: {exc}", "err")
        self.modules_layout.addStretch(1)

    def _module_row(self, tool: dict) -> QWidget:
        """一个模块 = 一张小卡片：名字(+参数+标记) 一行，说明一行，右边一个开关"""
        name = str(tool.get("name") or "")
        card = SimpleCardWidget(self.modules_box)
        outer = QHBoxLayout(card)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(12)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)

        head = QHBoxLayout()
        head.setSpacing(6)
        name_label = StrongBodyLabel(name, card)
        name_label.setFont(_mono_font())
        head.addWidget(name_label)

        params = str(tool.get("parameters") or "").strip()
        if params:
            head.addWidget(CaptionLabel(
                self.i18n.t("module_params", params=params), card))
        if tool.get("danger"):
            danger = CaptionLabel(self.i18n.t("module_danger"), card)
            danger.setStyleSheet(f"color: {COLOR_WARN};")
            head.addWidget(danger)
        source = str(tool.get("source") or "").strip()
        if source:
            head.addWidget(CaptionLabel(
                self.i18n.t("module_source", source=source), card))
        head.addStretch(1)
        text_box.addLayout(head)

        desc = CaptionLabel(str(tool.get("description") or ""), card)
        desc.setWordWrap(True)
        text_box.addWidget(desc)
        outer.addLayout(text_box, 1)

        switch = SwitchButton(card)
        switch.setOffText("")
        switch.setOnText("")
        switch.setFixedWidth(52)
        switch.setChecked(bool(tool.get("enabled", True)))
        switch.checkedChanged.connect(
            lambda checked, n=name: self._on_module_toggled(n, checked))
        outer.addWidget(switch, 0, Qt.AlignVCenter)

        self._module_rows[name] = switch
        return card

    def _on_module_toggled(self, name: str, checked: bool):
        """某一项被拨动：写进设置（持久化），并刷新入口卡片上的计数"""
        if self._syncing:
            return
        agent = self._agent()
        if agent is None:
            self._toast("warn", self.i18n.t("switch_unavailable"))
            return
        try:
            agent.set_tool_on(name, bool(checked))
            self._log(f"模块 {name} → {'开' if checked else '关'}")
        except Exception as exc:
            self._log(f"切换模块 {name} 失败: {exc}", "err")
            self._toast("warn", self.i18n.t("module_toggle_failed", error=exc))
        self._refresh_modules_count()

    def _set_all_modules(self, on: bool):
        """全部开启 / 全部关闭"""
        agent = self._agent()
        if agent is None:
            self._toast("warn", self.i18n.t("switch_unavailable"))
            return
        try:
            agent.set_all_tools_on(bool(on))
        except Exception as exc:
            self._log(f"批量切换模块失败: {exc}", "err")
            self._toast("warn", self.i18n.t("module_toggle_failed", error=exc))
            return
        self._toast("ok", self.i18n.t("modules_all_on" if on else "modules_all_off"))
        self._render_modules()
        self._refresh_modules_count()

    def _render_modules(self):
        """按当前清单重建模块行（并把开关状态同步成真实值）"""
        self._refresh_modules()
        # 按真实值再同步一次开关：用户在别处改过也要能反映出来
        agent = self._agent()
        if agent is None:
            return
        try:
            tools = {t.get("name"): bool(t.get("enabled"))
                     for t in (agent.tools() or []) if isinstance(t, dict)}
        except Exception:
            return
        self._syncing = True
        try:
            for name, switch in self._module_rows.items():
                if name in tools and switch.isChecked() != tools[name]:
                    switch.blockSignals(True)
                    switch.setChecked(tools[name])
                    switch.blockSignals(False)
        finally:
            self._syncing = False

    # ---------- 最近动作 ----------
    def _build_actions_card(self, parent):
        card, layout = self._new_card(parent, "sec_actions", "sec_actions_desc")

        row = QHBoxLayout()
        row.setSpacing(8)
        refresh_btn = PushButton(self.i18n.t("btn_refresh"), card, FIF.SYNC)
        refresh_btn.clicked.connect(self.refresh)
        row.addWidget(refresh_btn)

        clear_btn = PushButton(self.i18n.t("btn_clear"), card, FIF.DELETE)
        clear_btn.clicked.connect(self._on_clear_actions)
        row.addWidget(clear_btn)
        row.addStretch(1)
        layout.addLayout(row)

        box = QWidget(card)
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(6)
        layout.addWidget(box)
        self.actions_box = box
        self.actions_layout = box_layout
        return card

    def _refresh_actions(self):
        """读最近的动作流水（最新的一条在最上面）"""
        if self.actions_layout is None:
            return
        self._clear_layout(self.actions_layout)

        agent = self._agent()
        if agent is None:
            self.actions_layout.addWidget(self._hint(self.actions_box,
                                                      self.i18n.t("switch_unavailable")))
            return
        try:
            actions = agent.recent_actions(limit=15) or []
        except Exception as exc:
            self._log(f"读 Agent 动作流水失败: {exc}", "err")
            self.actions_layout.addWidget(self._hint(
                self.actions_box, self.i18n.t("refresh_failed", error=exc)))
            return

        rows = [a for a in actions if isinstance(a, dict)]
        if not rows:
            self.actions_layout.addWidget(self._hint(self.actions_box,
                                                      self.i18n.t("actions_empty")))
            return

        for item in rows:
            try:
                ok = bool(item.get("ok", True))
                line = self.i18n.t(
                    "action_line",
                    ts=str(item.get("ts") or ""),
                    mark=self.i18n.t("mark_ok" if ok else "mark_fail"),
                    tool=str(item.get("tool") or ""),
                    detail=str(item.get("detail") or ""))
                label = BodyLabel(line, self.actions_box)
                label.setWordWrap(True)
                label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                self.actions_layout.addWidget(label)
            except Exception as exc:
                self._log(f"画动作行失败: {exc}", "err")

    def _on_clear_actions(self):
        agent = self._agent()
        if agent is None:
            self._toast("warn", self.i18n.t("switch_unavailable"))
            return
        try:
            agent.clear_actions()
            self._toast("ok", self.i18n.t("actions_cleared"))
        except Exception as exc:
            self._log(f"清空动作流水失败: {exc}", "err")
            self._toast("warn", self.i18n.t("actions_clear_failed", error=exc))
        self._refresh_actions()
        self._refresh_stats()

    # ---------- 统计（标签控件在"总开关"那张卡里） ----------
    def _refresh_stats(self):
        """一行统计：模块数 / 累计调用次数 / 各模块分别调了多少次"""
        if self.stats_label is None:
            return
        agent = self._agent()
        if agent is None:
            self.stats_label.setText(self.i18n.t("switch_unavailable"))
            return
        try:
            stats = agent.stats() or {}
        except Exception as exc:
            self._log(f"读 Agent 统计失败: {exc}", "err")
            self.stats_label.setText(self.i18n.t("refresh_failed", error=exc))
            return

        tools_n = _as_int(stats.get("tools"))
        total = _as_int(stats.get("total"))
        text = self.i18n.t("stats_line", tools=tools_n, total=total)

        calls = stats.get("calls")
        if isinstance(calls, dict) and calls:
            try:
                # 调得多的排前面；次数转不成 int 的排后面，不抛异常
                items = sorted(calls.items(),
                               key=lambda kv: (-_as_int(kv[1]), str(kv[0])))
                detail = ", ".join(f"{k}×{_as_int(v)}" for k, v in
                                   items[:MAX_CALL_ITEMS])
                text = f"{text} · {self.i18n.t('stats_calls', calls=detail)}"
            except Exception as exc:
                self._log(f"拼统计明细失败: {exc}", "err")
        self.stats_label.setText(text)

    # ---------- 对外钩子 ----------
    def refresh(self):
        """重新读一遍开关 / 模块 / 流水 / 统计
        宿主打开插件时会按 on_show → refresh 的顺序找钩子并调用，所以这里就是
        "配置界面被切过来时"要做的全部事情。⚠️ 逐个 try，异常绝不能逃给宿主。
        """
        for name, fn in (("switch", self._refresh_switch),
                         ("modules_count", self._refresh_modules_count),
                         ("modules", self._refresh_modules),
                         ("actions", self._refresh_actions),
                         ("stats", self._refresh_stats)):
            try:
                fn()
            except Exception as exc:
                self._log(f"刷新 {name} 失败: {exc}", "err")
        # 刷新完切回"配置"首页，下次进来看到的是总开关
        try:
            if self.stack is not None:
                self.stack.setCurrentIndex(self.PAGE_MAIN)
        except Exception:
            pass

    # 宿主按 ("on_show", "refresh", "refresh_theme") 找第一个能调的钩子，两种叫法指向同一次刷新
    on_show = refresh


def _as_int(value) -> int:
    """把统计里的次数转成整数；转不了就按 0 算（统计数据坏掉不该让页面崩）"""
    try:
        return int(value or 0)
    except Exception:
        return 0
