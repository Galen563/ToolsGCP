"""GCP-AI Agent 的运行时桥接：把 agent_tools 的注册表接到主窗口上（window.ai_agent）。
插件（plugins/gcp-ai-agent）只通过 enabled / set_enabled / tools / stats /
recent_actions / register_tool / unregister_source / ask / open_chat 打交道。
⚠️ 本模块不导入任何界面类（只用 getattr 摸主窗口已有属性），否则 core → ui 的
循环导入会把启动搞崩。
"""

from .agent_tools import get_registry, locale_of

# Agent 的总开关（插件页面 / 设置里都能改）
SETTING_KEY = "gcp_ai_agent_enabled"
# 被用户**关掉**的那些"手"（默认全开，所以这里只记关掉的）
TOOLS_OFF_KEY = "gcp_ai_agent_tools_off"
# 本插件自己的目录名（用来判断插件有没有被停用）
PLUGIN_ID = "gcp-ai-agent"


class AgentBridge:
    """主窗口 ↔ 工具注册表之间的那一层"""

    def __init__(self, window):
        self.window = window

    # ---------- 开关 ----------
    def _settings(self):
        return getattr(self.window, "settings_manager", None)

    def has_setting(self) -> bool:
        settings = self._settings()
        return settings is not None and SETTING_KEY in settings.settings

    def setting_on(self) -> bool:
        settings = self._settings()
        if settings is None:
            return False
        return bool(settings.settings.get(SETTING_KEY, True))

    def plugin_on(self) -> bool:
        """插件本身有没有被用户在插件中心关掉"""
        manager = getattr(self.window, "plugin_manager", None)
        if manager is None:
            # 没有插件系统（测试/精简模式）时按"没关"处理
            return True
        try:
            for info in manager.plugins:
                if info.id == PLUGIN_ID:
                    return info.status == "ok"
        except Exception:
            pass
        return True

    def enabled(self) -> bool:
        """Agent 总开关：插件没被停用 **且** 设置里 gcp_ai_agent_enabled 为真（默认关闭）"""
        return self.setting_on() and self.plugin_on()

    def set_enabled(self, on: bool):
        settings = self._settings()
        if settings is None:
            return
        settings.update_setting(SETTING_KEY, bool(on))
        self._log("agent_toggle", on=bool(on))

    # ---------- 工具 ----------
    @property
    def registry(self):
        return get_registry()

    def locale(self) -> str:
        language = "简体中文"
        try:
            language = self.window.language_manager.current_language
        except Exception:
            pass
        return locale_of(language)

    # ---------- 单个"手"的开关 ----------
    # 只记被关掉的那些（默认全开，新工具自动是开的），和总开关完全独立：
    # 总开关来回拨不会动到每一项的状态。
    def tools_off(self) -> set:
        settings = self._settings()
        if settings is None:
            return set()
        raw = settings.settings.get(TOOLS_OFF_KEY)
        if isinstance(raw, dict):
            # 兼容早期可能写过的字典形态
            return {str(k) for k, v in raw.items() if not v}
        if isinstance(raw, (list, tuple, set)):
            return {str(x) for x in raw}
        return set()

    def tool_on(self, name: str) -> bool:
        """这一只"手"现在能用吗（用户逐项开关 + 来源插件还开着）
        ⚠️ 来源插件必须一起看：插件停用后页面还留着（用户能进去再打开），
        但它的工具绝不能还能用，否则"插件关了 AI 照样干活"。
        """
        name = str(name or "")
        if not name:
            return False
        # 工具根本不在注册表里（插件停用时会把它撤掉）→ 当然不能用
        try:
            if self.registry.get(name) is None:
                return False
        except Exception:
            pass
        if name in self.tools_off():
            return False
        return self.source_active(name)

    def source_active(self, name: str) -> bool:
        """这个工具的来源插件现在是启用状态吗（主程序内置的工具永远算启用）"""
        try:
            tool = self.registry.get(name)
        except Exception:
            tool = None
        if tool is None:
            return False          # 已经不存在了，谈不上"可用"
        source = str(getattr(tool, "source", "") or "")
        if not source or source == "builtin":
            return True
        manager = getattr(self.window, "plugin_manager", None)
        if manager is None:
            return True
        try:
            for info in manager.plugins:
                if info.id == source:
                    return info.status == "ok"
        except Exception:
            pass
        return True

    def set_tool_on(self, name: str, on: bool):
        """打开 / 关掉某一项"手"（关掉的不会进 system 清单，也不会被执行）"""
        name = str(name or "").strip()
        settings = self._settings()
        if not name or settings is None:
            return
        off = self.tools_off()
        if on:
            off.discard(name)
        else:
            off.add(name)
        settings.update_setting(TOOLS_OFF_KEY, sorted(off))
        self._log("agent_tool_toggle", tool=name, on=bool(on))

    def set_all_tools_on(self, on: bool):
        """一键全开 / 全关（配置界面上的总控）"""
        settings = self._settings()
        if settings is None:
            return
        if on:
            settings.update_setting(TOOLS_OFF_KEY, [])
        else:
            settings.update_setting(TOOLS_OFF_KEY,
                                    sorted(t["name"] for t in self.registry.to_dicts()))

    def tools(self) -> list:
        """全部工具（每项带 enabled / active 字段，给配置界面的开关用）
        · enabled = 用户在这一项上的开关（存 gcp_ai_agent_tools_off）
        · active  = 现在**真的能用**（enabled 且来源插件开着）
        """
        off = self.tools_off()
        out = []
        for item in self.registry.to_dicts(self.locale()):
            item = dict(item)
            on = item.get("name") not in off
            item["enabled"] = on
            item["active"] = bool(on and self.source_active(item.get("name")))
            out.append(item)
        return out

    def active_tools(self) -> list:
        """真正启用中的工具（拼提示词 / 执行时用）"""
        return [t for t in self.tools() if t.get("active")]

    def stats(self) -> dict:
        return self.registry.stats()

    def recent_actions(self, limit: int = 20) -> list:
        return self.registry.recent_actions(limit)

    def clear_actions(self):
        self.registry.clear_actions()

    def register_tool(self, name, description, handler, parameters: str = "",
                      source: str = PLUGIN_ID, danger: bool = False) -> bool:
        """给 AI 加一只手（插件用）
        description 可以直接给 {"zh_CN":..., "zh_TW":..., "en_US":...} 三种语言。
        """
        return self.registry.register_tool(name, description, handler,
                                           parameters=parameters,
                                           source=source, danger=danger)

    def unregister_source(self, source: str = PLUGIN_ID) -> int:
        return self.registry.unregister_source(source)

    def prompt_section(self) -> str:
        """给 system 提示词用的那一段（Agent 关着时返回空串，连"你没有手"都不发，省 token）"""
        if not self.enabled():
            return ""
        from .agent_tools import build_agent_prompt
        return build_agent_prompt(self.locale(), self.registry,
                                  allowed=self.enabled_tool_names())

    def enabled_tool_names(self) -> set:
        """当前启用的工具名集合（拼提示词、执行校验都用它）"""
        return {t["name"] for t in self.active_tools()}

    # ---------- 跟聊天面板对接 ----------
    def sidebar_mode(self) -> bool:
        """现在是不是"侧边栏 AI 单独界面"那种形态"""
        try:
            return bool(self.window.settings_manager.settings.get(
                "ai_sidebar_mode", False))
        except Exception:
            return False

    def chat(self):
        """当前生效的聊天抽屉：普通模式是右侧抽屉，侧边栏 AI 模式是内嵌的那个"""
        if self.sidebar_mode():
            page = getattr(self.window, "aiSidebarPage", None)
            inner = getattr(page, "_drawer", None) if page is not None else None
            if inner is not None:
                return inner
        return getattr(self.window, "ai_chat_drawer", None)

    def open_chat(self):
        """把 AI 界面打开（不开新的会话）"""
        window = self.window
        if self.sidebar_mode():
            opener = getattr(window, "_open_ai_sidebar_page", None)
            if callable(opener):
                try:
                    opener()
                    return self.chat()
                except Exception:
                    pass
        opener = getattr(window, "open_ai_drawer", None)
        if callable(opener):
            try:
                opener(focus=True)
            except TypeError:
                opener()
        return self.chat()

    def ask(self, text: str) -> bool:
        """把一句话交给 GCP-AI 并发送（插件页面的"交给 AI"按钮走这里）
        ⚠️ 要用 QTimer 推迟：抽屉得先滑出来、输入框才存在。
        """
        text = str(text or "").strip()
        if not text:
            return False
        try:
            from PyQt5.QtCore import QTimer
        except Exception:
            return False

        self.open_chat()

        def _send():
            drawer = self.chat()
            if drawer is None:
                return
            try:
                drawer.input_edit.setPlainText(text)
                drawer.on_send_clicked()
            except Exception as exc:
                self._log("agent_ask_failed", error=str(exc))

        QTimer.singleShot(120, _send)
        self._log("agent_ask", chars=len(text))
        return True

    # ---------- 日志 ----------
    def _log(self, action: str, **fields):
        try:
            # ⚠️ 三个点：本模块在 core/ai/ 下，`..utils` 会解析成不存在的
            #    pymodels.core.utils，导入失败被 except 吞掉，日志一条都不落盘。
            from ...utils.logger import log
            log.op("AI-Agent", action, **fields)
        except Exception:
            pass


def get_bridge(window) -> AgentBridge:
    """取主窗口上的 AgentBridge（懒建，挂在 window.ai_agent 上）"""
    bridge = getattr(window, "ai_agent", None)
    if isinstance(bridge, AgentBridge):
        return bridge
    bridge = AgentBridge(window)
    try:
        window.ai_agent = bridge
    except Exception:
        pass
    return bridge


__all__ = ["AgentBridge", "get_bridge", "SETTING_KEY", "TOOLS_OFF_KEY", "PLUGIN_ID"]
