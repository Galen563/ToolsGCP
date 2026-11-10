"""插件制作辅助的配置界面（**只有开关和下拉框**）
四张卡片、三种控件（开关 / 下拉框 / 文字）：标题 / 总开关（**默认关**）/ Skill 技能
（五条生成规则 + 默认开发语言下拉框）/ 怎么用（开总开关 → 在聊天框按 /plugin →
说需求）。⚠️ 这一页没有也不会有任何输入框：用户要写的东西全部在 GCP-AI 聊天框里说。
⚠️ 插件真正怎么被用起来：__init__ 里往宿主的聊天提示注册表登记一条 /plugin 悬浮提示，
   用户点一下命令就填进输入框；他真的发了 /plugin 开头的消息时，登记的那段 prompt 才
   被追加进这次请求的 system，里面带着**当前开着的** Skill 规则（来自 core/skill.py），
   所以界面开关一改指令正文跟着变。同时无条件登记 create_plugin 这个 AI 工具
   （只有 Agent 开着时才会被调用）。
三条硬规矩：
    ⚠️ 总开关关着时页面照样要能开、不能崩，动作只给一句"生成功能已关闭"的提示。
    ⚠️ 落盘的脏活全在 core/maker.py；规则文字的唯一真源是 core/skill.py。
    ⚠️ 回调不许让异常逃出去；ai_agent 可能是 None，register_* 在老宿主可能不存在。
文案全部走 i18n（lang/*.json），界面里没有一个写死的句子。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, InfoBar, InfoBarPosition,
    SimpleCardWidget, StrongBodyLabel, SubtitleLabel, SwitchButton,
)

from ..core import maker, skill

# ---------- 登记给宿主的两样东西 ----------
HINT_ID = "gcp-plugin-maker"        # 注册表里的唯一 id（卸载时按它注销）
HINT_INSERT = "/plugin"             # 点一下插进输入框、也是要敲的命令（必须就是它）
HINT_PRIORITY = 20                  # 数字大的排前面

# 给 GCP-AI 的那只"手"：模型调它才能真正把插件写进 plugins/
TOOL_NAME = "create_plugin"
TOOL_PARAMS = "id,name,idea,language"

# 状态色：主题里没有"开/关/警告"这种语义色，只用在几行小标签上，直接写死
COLOR_ON = "#0f7b0f"
COLOR_OFF = "#8a8886"
COLOR_WARN = "#c42b1c"

# "怎么用"卡片里的三行说明（i18n 键）
HOW_LINES = ("how_line1", "how_line2", "how_line3")

# 最近一个把 /plugin 提示登记出去的页面实例。
# ⚠️ 宿主重扫插件时会**重建所有插件页面**：新页面登记同一条提示（注册表里覆盖成新的），
#    旧页面随后被回收，它的 destroyed 会回调到这里。没有这个"谁是当前主人"的判断，
#    旧页面就会把新页面刚登记的提示卸掉（表现为"生成完一个插件，/plugin 提示就没了"）。
_PAGE_OWNER = None


def _fill(template: str, **kwargs) -> str:
    """把指令模板里的 {占位符} 替换掉；模板坏了（少占位符 / 多个裸 {}）退回原文，不抛"""
    try:
        return str(template).format(**kwargs)
    except Exception:
        return str(template)


def _mark_page_owner(page) -> None:
    """把自己记成"当前登记着 /plugin 提示的那个页面"（见 _PAGE_OWNER 的说明）"""
    global _PAGE_OWNER
    _PAGE_OWNER = page


class PluginMakerPage(QWidget):
    """插件制作辅助的配置界面：总开关 + Skill 规则 + 默认开发语言（没有任何输入框）"""

    def __init__(self, context, config, i18n, parent=None):
        super().__init__(parent)
        self.context = context
        self.config = config
        self.i18n = i18n

        # Skill 开关的内存副本（唯一真源在 core/skill.py + 设置里）
        self.options = skill.load_options(context)
        # 总开关的镜像：读设置失败一律当"关"
        self.enabled = skill.load_enabled(context)

        # 控件引用先给 None：卡片没建起来时 refresh() 要能判空跳过
        self.switch = None
        self.switch_hint = None
        self.rule_switches = {}          # 选项键 → SwitchButton
        self.language_combo = None       # 默认开发语言下拉框

        # 刷新 / 重画期间别让控件信号回头再写一次设置（否则每次刷新都写盘）
        self._syncing = False
        # 上次真正注册出去的那段指令：没变就不重复注册，免得聊天栏提示条被反复重建
        self._registered_prompt = None
        # create_plugin 工具注册成功过就不再重复注册（宿主没准备好时会重试）
        self._tool_registered = False

        try:
            # objectName 带上插件 id：主题刷新时主程序靠它认页面
            self.setObjectName(f"plugin_{context.id}")
        except Exception:
            pass

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # 横向不滚动：文字按宽度换行，压扁的布局里 qfluentwidgets 卡片会画错
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        for builder in (self._build_header, self._build_switch_card,
                        self._build_skill_card, self._build_how_card):
            self._build_safely(builder, content, layout)

        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # 登记 /plugin 悬浮提示 + 指令，和 create_plugin 工具：插件的真正入口
        self._register_chat_hint()
        self._register_ai_tool()
        # 登记完把自己记成"当前主人"（见 _PAGE_OWNER）
        _mark_page_owner(self)

        try:
            self.destroyed.connect(self._on_destroyed)
        except Exception:
            pass

        self.refresh()

    # ---------- 通用小工具 ----------
    def _log(self, message: str, level: str = "info"):
        """写日志：日志本身出问题也不能影响界面"""
        try:
            self.context.log(str(message), level=level)
        except Exception:
            pass

    def _build_safely(self, builder, parent, layout):
        """建一张卡片：出错就记日志跳过，绝不让异常逃出去"""
        try:
            widget = builder(parent)
            if widget is not None:
                layout.addWidget(widget)
        except Exception as exc:
            self._log(f"构建卡片 {getattr(builder, '__name__', builder)} 失败: {exc}", "err")

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

    def _toast(self, level: str, text: str):
        """弹一条 InfoBar 提示；界面还没挂到主窗口上时可能弹不出来（兜住，不抛）"""
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

    def _plugins_dir(self) -> str:
        """新插件要写进哪个 plugins/ 目录（拿不到就退回 maker 自己的猜法）"""
        try:
            root = getattr(self.context, "plugins_dir", None)
            if root:
                return str(root)
        except Exception:
            pass
        try:
            return maker._default_plugins_dir(self.context)
        except Exception:
            return ""

    # ---------- 卡片：标题 ----------
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

    # ---------- 卡片：总开关 ----------
    def _build_switch_card(self, parent):
        card, layout = self._new_card(parent, "sec_switch", "sec_switch_desc")

        row = QHBoxLayout()
        row.setSpacing(12)

        switch = SwitchButton(card)
        switch.setOnText(self.i18n.t("switch_on"))
        switch.setOffText(self.i18n.t("switch_off"))
        switch.checkedChanged.connect(self._on_switch_changed)
        row.addWidget(switch)
        self.switch = switch

        # 旁边补一句"现在会怎样"
        hint = CaptionLabel("", card)
        hint.setWordWrap(True)
        row.addWidget(hint, 1)
        self.switch_hint = hint

        layout.addLayout(row)
        return card

    def _refresh_switch(self):
        """读一次总开关（判空 + 兜异常都在这）"""
        if self.switch is None:
            return
        try:
            on = skill.load_enabled(self.context)
        except Exception as exc:
            # 界面上给一句"读取失败"，日志里留完整原因
            self._log(f"读总开关失败: {exc}", "err")
            on = False
        self.enabled = bool(on)

        # ⚠️ setChecked 会发 checkedChanged，不挡信号就会自己回写设置
        self._syncing = True
        self.switch.blockSignals(True)
        try:
            self.switch.setChecked(on)
        finally:
            self.switch.blockSignals(False)
            self._syncing = False

        self._set_hint(self.i18n.t("switch_hint_on" if on else "switch_hint_off"),
                       COLOR_ON if on else COLOR_OFF)

    def _set_hint(self, text: str, color: str):
        if self.switch_hint is None:
            return
        try:
            self.switch_hint.setText(str(text or ""))
            self.switch_hint.setStyleSheet(f"color: {color};")
        except Exception as exc:
            self._log(f"更新开关提示失败: {exc}", "err")

    def _on_switch_changed(self, checked: bool):
        """用户拨了总开关：写进设置，再按"真实读回来的状态"重画一遍"""
        if self._syncing:
            return
        try:
            ok = skill.save_enabled(self.context, checked)
            if not ok:
                self._toast("warn", self.i18n.t("switch_save_failed"))
            else:
                self._log(f"用户切换总开关: {bool(checked)}")
        except Exception as exc:
            self._log(f"保存总开关失败: {exc}", "err")
            self._toast("warn", self.i18n.t("switch_save_failed"))
        self._refresh_switch()

    # ---------- 卡片：Skill 技能（五条规则开关 + 一个开发语言下拉框） ----------
    def _build_skill_card(self, parent):
        card, layout = self._new_card(parent, "sec_skill", "sec_skill_desc")

        for rule in skill.RULES:
            key = rule["key"]
            try:
                layout.addWidget(self._rule_row(card, rule))
            except Exception as exc:
                self._log(f"建规则行 {key} 失败: {exc}", "err")

        layout.addSpacing(4)
        try:
            layout.addWidget(self._language_row(card))
        except Exception as exc:
            self._log(f"建开发语言行失败: {exc}", "err")
        return card

    def _rule_row(self, card, rule: dict) -> QWidget:
        """一条 Skill 规则 = 左边"名字 + 说明"，右边一个开关"""
        key = rule["key"]
        row = QWidget(card)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        text_box = QWidget(row)
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(BodyLabel(self.i18n.t(rule["label"]), text_box))
        desc = CaptionLabel(self.i18n.t(rule["desc"]), text_box)
        desc.setWordWrap(True)
        text_layout.addWidget(desc)
        row_layout.addWidget(text_box, 1)

        switch = SwitchButton(row)
        switch.setOnText(self.i18n.t("switch_on"))
        switch.setOffText(self.i18n.t("switch_off"))
        # 用默认参数把 key 绑进回调，免得闭包抓到最后一个 key
        switch.checkedChanged.connect(
            lambda checked, k=key: self._on_rule_changed(k, checked))
        row_layout.addWidget(switch)
        self.rule_switches[key] = switch
        return row

    def _language_row(self, card) -> QWidget:
        """默认开发语言：**下拉框**（这一页唯一的选择型配置，不是输入框）"""
        row = QWidget(card)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        text_box = QWidget(row)
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(BodyLabel(self.i18n.t("skill_default_language"), text_box))
        desc = CaptionLabel(self.i18n.t("skill_default_language_desc"), text_box)
        desc.setWordWrap(True)
        text_layout.addWidget(desc)
        row_layout.addWidget(text_box, 1)

        combo = ComboBox(row)
        combo.addItems(list(skill.LANGUAGES))
        combo.setMinimumWidth(140)
        combo.currentIndexChanged.connect(self._on_language_changed)
        row_layout.addWidget(combo, 0, Qt.AlignVCenter)
        self.language_combo = combo
        return row

    def _refresh_rule_switches(self):
        """把内存里的开关状态画到界面上（挡信号，免得画一次写一次盘）"""
        self._syncing = True
        try:
            for key, switch in self.rule_switches.items():
                if switch is None:
                    continue
                switch.blockSignals(True)
                try:
                    switch.setChecked(bool(self.options.get(key)))
                finally:
                    switch.blockSignals(False)
        finally:
            self._syncing = False

    def _refresh_language_combo(self):
        """把 options 里的默认开发语言画到下拉框上（认不出来的值退回第一项）"""
        if self.language_combo is None:
            return
        wanted = str(self.options.get(skill.LANGUAGE_KEY) or skill.DEFAULT_LANGUAGE)
        self._syncing = True
        self.language_combo.blockSignals(True)
        try:
            index = self.language_combo.findText(wanted)
            self.language_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.language_combo.blockSignals(False)
            self._syncing = False

    def _on_rule_changed(self, key: str, checked: bool):
        """用户拨了一条 Skill 规则：写设置 + 重新登记一次 /plugin 的指令"""
        if self._syncing:
            return
        try:
            self.options[key] = bool(checked)
            ok = skill.save_options(self.context, self.options)
            if not ok:
                self._toast("warn", self.i18n.t("switch_save_failed"))
            self._log(f"Skill 规则 {key} = {bool(checked)}")
        except Exception as exc:
            self._log(f"保存 Skill 规则失败: {exc}", "err")
            self._toast("warn", self.i18n.t("switch_save_failed"))
        # 规则变了 → 指令正文跟着变（内容没变时不会重复注册）
        self._register_chat_hint()

    def _on_language_changed(self, index: int = -1):
        """用户换了下拉框：写进同一个 options 字典（键 default_language）"""
        if self._syncing:
            return
        try:
            if self.language_combo is None:
                return
            language = skill.normalize_develop_language(self.language_combo.currentText())
            self.options[skill.LANGUAGE_KEY] = language
            ok = skill.save_options(self.context, self.options)
            if not ok:
                self._toast("warn", self.i18n.t("switch_save_failed"))
            self._log(f"默认开发语言 = {language}")
        except Exception as exc:
            self._log(f"保存默认开发语言失败: {exc}", "err")
            self._toast("warn", self.i18n.t("switch_save_failed"))
        # 指令正文里写着默认开发语言，换了也要重新登记
        self._register_chat_hint()

    # ---------- 卡片：怎么用（纯说明，没有任何控件） ----------
    def _build_how_card(self, parent):
        card, layout = self._new_card(parent, "sec_how")
        for key in HOW_LINES:
            caption = CaptionLabel(self.i18n.t(key), card)
            caption.setWordWrap(True)
            layout.addWidget(caption)
        return card

    # ---------- 聊天命令 + 悬浮提示：插件真正的使用入口 ----------
    def _hint_prompt(self) -> dict:
        """组装 /plugin 命令追加到 system 的那段指令；⚠️ "规矩"直接来自 skill.rule_lines()"""
        options = skill.normalize(self.options)
        try:
            rules = "\n".join(f"· {line}" for line in skill.rule_lines(options))
        except Exception as exc:
            self._log(f"组装 Skill 规则失败: {exc}", "err")
            rules = ""
        language = str(options.get(skill.LANGUAGE_KEY) or skill.DEFAULT_LANGUAGE)

        prompts = {}
        try:
            templates = self.i18n.locale_dict("hint_prompt")
        except Exception as exc:
            self._log(f"读 /plugin 指令文案失败: {exc}", "err")
            templates = {}
        for locale in skill.ALL_LOCALES:
            template = templates.get(locale) or ""
            prompts[locale] = _fill(template, rules=rules, language=language)
        return prompts

    def _register_chat_hint(self) -> bool:
        """把 /plugin 悬浮提示登记到宿主的聊天提示注册表
        ⚠️ 老宿主可能没这个方法，没有就安静跳过。
        ⚠️ 指令正文没变就不重复注册：注册表每注册一次版本号 +1、聊天栏跟着重画，
           而 refresh() 会被反复调用。
        """
        try:
            register = getattr(self.context, "register_chat_hint", None)
            if not callable(register):
                self._log("宿主没有 register_chat_hint，跳过 /plugin 悬浮提示注册")
                return False

            prompt = self._hint_prompt()
            if prompt == self._registered_prompt:
                return True

            label = self.i18n.locale_dict("hint_label")
            ok = bool(register(HINT_ID, label, HINT_INSERT, prompt, HINT_PRIORITY))
            if ok:
                self._registered_prompt = prompt
                self._log(f"已登记聊天提示 {HINT_INSERT}")
            else:
                # 宿主还没准备好（注册表拿不到）—— 下次 refresh 会再试一遍
                self._log("聊天提示登记失败（宿主可能还没准备好）", "err")
            return ok
        except Exception as exc:
            self._log(f"登记聊天提示失败: {exc}", "err")
            return False

    def teardown(self):
        """页面被销毁时，把登记出去的聊天提示收回来
        ⚠️ 注册表是全局的，老宿主没有 unregister_chat_hint 就跳过。
        ⚠️ 只有"当前主人"才有资格卸（见 _PAGE_OWNER），否则会把新页面刚登记的抹掉。
        """
        global _PAGE_OWNER
        try:
            if _PAGE_OWNER is not None and _PAGE_OWNER is not self:
                return
            _PAGE_OWNER = None
        except Exception:
            pass
        self._registered_prompt = None
        try:
            unregister = getattr(self.context, "unregister_chat_hint", None)
            if callable(unregister):
                unregister(HINT_ID)
                self._log(f"已注销聊天提示 {HINT_INSERT}")
        except Exception as exc:
            self._log(f"注销聊天提示失败: {exc}", "err")

    def _on_destroyed(self, *_args):
        """QObject.destroyed 的回调（信号带一个 QObject 参数，用 *args 吃掉）"""
        try:
            self.teardown()
        except Exception:
            pass

    # ---------- create_plugin：GCP-AI 真正用来落盘的那只手 ----------
    def _register_ai_tool(self) -> bool:
        """登记 create_plugin 工具（**无条件登记**）
        ⚠️ 工具只有 Agent 开着时才会被调用，要不要干活由 handler 里的总开关判定；
           没准备好时返回 False，下次 refresh() 再试。
        """
        if self._tool_registered:
            return True
        try:
            register = getattr(self.context, "register_ai_tool", None)
            if not callable(register):
                self._log("宿主没有 register_ai_tool，跳过 create_plugin 注册")
                return False
            description = self.i18n.locale_dict("tool_desc")
            ok = bool(register(TOOL_NAME, description,
                               self._handle_create_plugin, TOOL_PARAMS))
            if ok:
                self._tool_registered = True
                self._log(f"已登记 AI 工具 {TOOL_NAME}")
            return ok
        except Exception as exc:
            self._log(f"登记 AI 工具失败: {exc}", "err")
            return False

    def _enabled_now(self) -> bool:
        """现读一次总开关（每次执行前都读设置，而不是信内存里的镜像）"""
        try:
            return bool(skill.load_enabled(self.context))
        except Exception as exc:
            self._log(f"读总开关失败: {exc}", "err")
            return False

    def _handle_create_plugin(self, agent, args) -> dict:
        """create_plugin 工具的实现（模型在用户发了 /plugin 之后调它）
        ⚠️ 契约：**绝不抛异常**，失败也返回 {"ok": False, "error": ...}。
        args：id（先过 maker.validate_id）/ name / idea / language（可省略 → 设置里的
        default_language → Python）
        """
        try:
            # 1) 总开关：关着就拒绝执行（注册无条件，运行要过开关）
            if not self._enabled_now():
                return {"ok": False, "error": self.i18n.t("tool_disabled")}

            args = args if isinstance(args, dict) else {}
            plugin_id = str(args.get("id") or "").strip()
            plugin_name = str(args.get("name") or "").strip() or plugin_id
            idea = str(args.get("idea") or "").strip()

            # 2) 开发语言：参数 → 设置里的默认值 → Python
            options = skill.load_options(self.context)
            language = (str(args.get("language") or "").strip()
                        or str(options.get(skill.LANGUAGE_KEY) or "")
                        or skill.DEFAULT_LANGUAGE)

            # 3) id 校验：不合法就地拦住，一个字节都不写
            valid, reason = maker.validate_id(plugin_id)
            if not valid:
                return {"ok": False, "error": reason}

            # 4) 落盘（真正的活在 core/maker.py 里，它也不抛异常）
            result = maker.generate(self.context, plugin_id, plugin_name, idea,
                                    language, options,
                                    plugins_dir=self._plugins_dir())
            if not result.ok:
                # 原样返回 error（包括"plugins/xxx/ 已经存在了"），由模型转达给用户
                return {"ok": False, "error": str(result.error or "生成失败")}

            # 5) 让新插件立刻出现在插件中心（不用重启）
            reloaded = -1
            try:
                reloaded = int(self.context.reload_plugins())
            except Exception as exc:
                # ⚠️ 重载失败不算生成失败：文件已经写好了，重启一样能看到
                self._log(f"reload_plugins 失败: {exc}", "err")

            self._log(f"AI 生成插件 {plugin_id}: {result.summary()}")
            try:
                # 记一笔（写 context.data_dir，不要写只读的插件目录）
                self.config.bump("generated")
            except Exception as exc:
                self._log(f"记录生成次数失败: {exc}", "err")

            return {"ok": True, "data": {
                "id": plugin_id,
                "folder": plugin_id,
                "folder_path": str(result.folder or ""),
                "files_written": len(result.written),
                "files": list(result.written)[:20],
                "reloaded": reloaded,
            }}
        except Exception as exc:
            # ⚠️ 兜底：上面任何一步出意外都收口成一句 error，绝不抛给工具注册表
            self._log(f"create_plugin 失败: {exc}", "err")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # ---------- 对外钩子 ----------
    def refresh(self):
        """重新读一遍设置，并把界面 / 登记项重画一次
        宿主打开插件时会按 on_show → refresh 的顺序找钩子并调用，所以这里就是
        "页面被切过来时"要做的全部事情。⚠️ 逐个 try，异常绝不能逃给宿主。
        """
        for name, fn in (("switch", self._refresh_switch),
                         ("options", self._refresh_options),
                         ("rules", self._refresh_rule_switches),
                         ("language", self._refresh_language_combo),
                         ("hint", self._register_chat_hint),
                         ("tool", self._register_ai_tool)):
            try:
                fn()
            except Exception as exc:
                self._log(f"刷新 {name} 失败: {exc}", "err")

    def _refresh_options(self):
        """从设置里重新读 Skill 选项（用户可能在别处改过，或手改了配置文件）"""
        self.options = skill.load_options(self.context)

    # 宿主按 ("on_show", "refresh", "refresh_theme") 找第一个能调的钩子，两种叫法指向同一次刷新
    on_show = refresh
