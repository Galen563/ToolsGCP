"""GCP-AI Agent 的运行时桥接：把 agent_tools 的注册表接到主窗口上（window.ai_agent）。
插件（plugins/gcp-ai-agent）只通过 enabled / set_enabled / tools / stats /
recent_actions / register_tool / unregister_source / ask / open_chat 打交道。
⚠️ 本模块不导入任何界面类（只用 getattr 摸主窗口已有属性），否则 core → ui 的
循环导入会把启动搞崩。
"""

import threading

from .agent_tools import get_registry, locale_of

# Agent 的总开关（插件页面 / 设置里都能改）
SETTING_KEY = "gcp_ai_agent_enabled"
# 被用户**关掉**的那些"手"（默认全开，所以这里只记关掉的）
TOOLS_OFF_KEY = "gcp_ai_agent_tools_off"
# 本插件自己的目录名（用来判断插件有没有被停用）
PLUGIN_ID = "gcp-ai-agent"

# ---------- 强制开启（契约 1.4） ----------
# 用户原话：「把 Agent 插件设置为强制开启无法关闭」→ 这个常量是**唯一判据**，
# 不要在任何地方再写一遍字面量 True/False（两处分开维护，迟早有一处忘了改，
# 表现就是"界面上锁了、后端还能关"）。
# ⚠️ 它与 desktop/api/plugins.py 的 LOCKED_PLUGIN_IDS 是同一件事的两个视角：
#    那边回答"这个插件目录能不能关/删"，这边回答"Agent 运行时要不要照做"。
LOCKED = True


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

    def is_locked(self) -> bool:
        """本插件是不是「强制开启」——判定口径只有桌面层那一份（lazy import）

        ⚠️ 为什么不在本模块顶层 import desktop.api.plugins：
           core 层是被 Web/PyQt 两条链路共用的，顶层 import 桌面外壳会让
           "屏蔽 PyQt5 后完整 import" 的自检目标变脆（也会拖进 plugins.py 的一堆依赖）。
           所以 lazy import + 兜底：拿不到桌面层就退回模块常量 LOCKED。
        """
        try:
            from desktop.api.plugins import is_locked_plugin
            return bool(is_locked_plugin(PLUGIN_ID))
        except Exception:
            return bool(LOCKED)

    def plugin_on(self) -> bool:
        """插件本身有没有被用户在插件中心关掉

        ⚠️⚠️ Web 宿主**没有** `window.plugin_manager` 这个属性（那是 py 版 Qt 主窗口上的），
        所以老实现里 `manager is None → return True` 等于"恒返回 True"：
        插件中心明明关了 Agent，这里却永远当它开着 —— 工具照样能执行。
        现在的判定顺序：
          ① 强制开启 → 恒 True（用户要求"无法关闭"）；
          ② 有 plugin_manager（py 版链路）→ 照旧看 info.status；
          ③ 没有（Web 宿主）→ 读该插件 manifest 里声明的 `enabled_setting` 的设置值，
             没有声明就按"没关"处理。
        """
        if self.is_locked():
            return True
        manager = getattr(self.window, "plugin_manager", None)
        if manager is not None:
            try:
                for info in manager.plugins:
                    if info.id == PLUGIN_ID:
                        return info.status == "ok"
            except Exception:
                pass
            return True
        # ③ Web 宿主：设置里的开关就是插件的启停状态（PluginsDomain.set_enabled 写它）
        settings = self._settings()
        if settings is None:
            return True
        try:
            from desktop.api.plugins import find_plugin_dir, _read_json
            import os as _os
            folder = find_plugin_dir(PLUGIN_ID)
            if folder:
                manifest = _read_json(_os.path.join(folder, "manifest.json"))
                key = str(manifest.get("enabled_setting") or "").strip()
                if key and key in settings.settings:
                    return bool(settings.settings.get(key))
        except Exception:
            pass
        return True

    def enabled(self) -> bool:
        """Agent 总开关：强制开启时**恒 True**；否则 = 设置值 且 插件没被停用

        ⚠️ 为什么锁定时直接返回 True 而不是只看 setting_on()：
           老用户配置里这个键还留着 False（上一版默认关闭），只看设置值会让
           "强制开启"在升级后立刻失效（界面锁着、AI 却没有手）。
           用户意图仍然可以从 `setting_on()` 读到（保留那个方法就是为了这个）。
        """
        if self.is_locked():
            return True
        return self.setting_on() and self.plugin_on()

    def set_enabled(self, on: bool):
        """设置总开关；**强制开启时忽略关闭**（写 op 日志说明原因）

        ⚠️ 不能静默 return：用户/日志里要能看到"我关了但它没关"是设计如此，
           不是坏了。所以锁定时照样记一条 op 日志。
        ⚠️ 锁定时即使传 True 也要把设置**写成 True**（自愈脏配置）。
        """
        settings = self._settings()
        if settings is None:
            return
        wanted = bool(on)
        if self.is_locked():
            if not wanted:
                self._log("agent_toggle_ignored_locked", on=False,
                          reason="强制开启，忽略关闭")
            if not bool(settings.settings.get(SETTING_KEY, True)):
                settings.update_setting(SETTING_KEY, True)
            return
        settings.update_setting(SETTING_KEY, wanted)
        self._log("agent_toggle", on=wanted)

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
        """这个工具的来源插件现在是启用状态吗

        ⚠️⚠️ 本轮关键改动（契约 2.3）：31 个"内置"工具的 source 已经从 "builtin"
        改成 AGENT_PLUGIN_SOURCE（= "gcp-ai-agent"）。所以这里**不再**把 "builtin"
        当"永远激活"，而是：
          · source 是 Agent 插件 → 看 Agent 是否启用（强制开启 ⇒ 恒 True）；
          · source 是空 / "builtin" → 主程序本体工具，永远算启用（真·内置的那类）；
          · 其它插件 → 有 plugin_manager 看状态，没有（Web 宿主）就按"启用"处理。
        为什么"其它插件"在 Web 宿主按启用：Web 版插件中心关掉的插件本就不该还在
        注册表里（关的时候 PluginsDomain.set_enabled → sync_plugin_resources →
        release_plugin_resources 会把模块摘掉），注册表里还有就说明它没被关。
        """
        try:
            tool = self.registry.get(name)
        except Exception:
            tool = None
        if tool is None:
            return False          # 已经不存在了，谈不上"可用"
        source = str(getattr(tool, "source", "") or "")
        # ① Agent 插件域的工具：随 Agent 开关（强制开启 ⇒ 恒 True，但仍走 enabled()
        #    以保留"万一 LOCKED 关掉"的语义，别写死 True）
        try:
            from .agent_tools import AGENT_PLUGIN_SOURCE
        except Exception:
            AGENT_PLUGIN_SOURCE = PLUGIN_ID
        if source and source == AGENT_PLUGIN_SOURCE:
            return bool(self.enabled())
        # ② 空 / 真·内置（主程序本体）—— 永远算启用
        if not source or source == "builtin":
            return True
        # ③ 第三方插件：py 版链路看 plugin_manager，Web 宿主按"在注册表里即启用"
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


# ======================================================================
# 对话模式（Chat / Agent）
# ======================================================================
# 用户原话：「在GCP-AI页面或者右侧窗这个模型选择左侧新增一个一样的ui…只有一个
#   Chat和Agent选项，Chat只能聊天也是默认选项，Agent则可以调用AI Agent获取可以
#   行动起来的能力…（这两个模式切换也出储存在配置里面）」。
CHAT_MODE_KEY = "ai_chat_mode"
CHAT_MODE_CHAT = "chat"
CHAT_MODE_AGENT = "agent"


def chat_mode(window=None) -> str:
    """当前对话模式："chat"（默认，纯聊天）或 "agent"（可以动手）

    ⚠️ 认不出来的值一律当 "chat"：宁可少动手，也不要因为一个脏配置
       让 AI 突然开始改用户的设置/收藏。
    """
    try:
        manager = getattr(window, "settings_manager", None)
        value = str((manager.settings if manager is not None else {}).get(
            CHAT_MODE_KEY, CHAT_MODE_CHAT) or "").strip().lower()
    except Exception:
        value = CHAT_MODE_CHAT
    return CHAT_MODE_AGENT if value == CHAT_MODE_AGENT else CHAT_MODE_CHAT


def set_chat_mode(window, mode: str) -> str:
    """切换对话模式并**落盘**（用户要求"这两个模式切换也出储存在配置里面"）"""
    want = CHAT_MODE_AGENT if str(mode or "").strip().lower() == CHAT_MODE_AGENT \
        else CHAT_MODE_CHAT
    try:
        manager = getattr(window, "settings_manager", None)
        if manager is not None:
            manager.update_setting(CHAT_MODE_KEY, want)
    except Exception:
        pass
    return want


def get_bridge(window) -> AgentBridge:
    """取主窗口上的 AgentBridge（懒建，挂在 window.ai_agent 上）

    ⚠️ 必须用 `isinstance` 判、不能用 `getattr(...) is not None`：
       Web 宿主上 window 自己可能就有个叫 ai_agent 的属性（别的东西），
       拿错对象会让后面所有调用静默走偏。
    """
    bridge = getattr(window, "ai_agent", None)
    if isinstance(bridge, AgentBridge):
        return bridge
    bridge = AgentBridge(window)
    try:
        window.ai_agent = bridge
    except Exception:
        pass
    try:
        # 反查缓存（释放资源时可能拿不到 window 参数，见 release_agent_resources）
        _remember_window(window)
    except Exception:
        pass
    return bridge


# ======================================================================
# Agent 域资源：加载 / 释放（契约 2.2）
# ======================================================================
# 背景（用户原话）：「我给插件的定义是只要属于插件里的东西开关都可以控制，
# 所以你说的 31 个内置 Agent 工具之类的都要释放都要做好」。
# 41 个工具注册在**进程内单例** ToolRegistry 上，插件关掉后如果只清设置不清注册表，
# 它们照样能被模型调用（提示词里也照样列着）—— 这就是"关了还在"。
# 所以插件的开关必须真的把工具注册表 / 动作流水 / 窗口上的桥一起动。

def load_agent_resources(window=None) -> dict:
    """加载 Agent 域资源：重新把内置工具注册进注册表 + 恢复动作流水/计数器容器。

    幂等：已经注册过就不重复注册（`register_builtin_tools` 是"同名覆盖"语义，
    重复调用不会产生两份；但我们先看 count 再说，省一次全量重建）。
    返回 `{"ok": True, "tools": N, "registered": bool}`，永不抛。
    """
    result = {"ok": True, "tools": 0, "registered": False}
    try:
        from . import agent_tools
        registry = get_registry()
        source = str(getattr(agent_tools, "AGENT_PLUGIN_SOURCE", PLUGIN_ID) or PLUGIN_ID)
        existing = [t for t in registry.all() if str(getattr(t, "source", "")) == source]
        if not existing:
            # 注册表被释放过（或首次启动）：整组重新装回来
            agent_tools.register_builtin_tools(registry)
            result["registered"] = True
        result["tools"] = len([t for t in registry.all()
                               if str(getattr(t, "source", "")) == source])
        if window is not None:
            # 桥：释放时被摘掉了，这里"不"主动重建 —— get_bridge() 是懒建的，
            # 重建会把一个可能已经该丢弃的旧桥重新钉在窗口上。
            pass
        _log_static("agent", f"加载 Agent 域资源: 工具 {result['tools']} 个",
                    action="agent_resources_load")
        return result
    except Exception as exc:                              # noqa: BLE001
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        _log_static("agent", f"加载 Agent 域资源失败: {exc}",
                    action="agent_resources_load_failed")
        return result


def release_agent_resources(window=None) -> dict:
    """释放 Agent 域资源（插件关掉 / 插件被删时调用）。

    三件事，缺一件就等于没释放：
      ① `registry.unregister_source(AGENT_PLUGIN_SOURCE)` —— 31 个工具全部下架，
         提示词清单（enabled_tool_names→build_agent_prompt）与执行同时失效；
      ② `registry.clear_actions()` —— 动作流水与每工具计数器属于 Agent 域，
         留着就还在内存里累积（也泄露出"之前干过什么"）；
      ③ 从 window 上摘掉 `ai_agent` 桥 —— 下次 get_bridge 会重建，
         不会攥着一个已失效的桥（它的 tools()/enabled() 都读注册表）。
    返回 `{"ok": True, "tools_removed": N}`，永不抛。
    """
    tools_removed = 0
    try:
        from . import agent_tools
        registry = get_registry()
        source = str(getattr(agent_tools, "AGENT_PLUGIN_SOURCE", PLUGIN_ID) or PLUGIN_ID)
        tools_removed = registry.unregister_source(source)
        try:
            registry.clear_actions()
        except Exception:                                 # noqa: BLE001
            pass
        target = window
        if target is None:
            # 调用方没给窗口（设置页/删除插件两条链路都拿不到"当前窗口"的其他引用）：
            # 从进程内登记的桥反查一个窗口 —— 桥是自己挂在窗口上的，反向能找到。
            target = _window_of_bridge()
        if target is not None:
            try:
                if isinstance(getattr(target, "ai_agent", None), AgentBridge):
                    delattr(target, "ai_agent")
            except Exception:                             # noqa: BLE001
                pass
        _log_static("agent",
                    f"释放 Agent 域资源: 下架工具 {tools_removed} 个",
                    action="agent_resources_release")
        return {"ok": True, "tools_removed": tools_removed}
    except Exception as exc:                              # noqa: BLE001
        _log_static("agent", f"释放 Agent 域资源失败: {exc}",
                    action="agent_resources_release_failed")
        return {"ok": False, "tools_removed": tools_removed,
                "error": f"{type(exc).__name__}: {exc}"}


_bridge_lock = threading.Lock()
_bridge_ref = {"ref": None}


def _remember_window(window):
    """记住"最近一次挂桥的窗口"，只为释放时能反查到它

    ⚠️⚠️ 必须用**弱引用**：这是个纯粹的反查缓存，绝不能延长窗口寿命 ——
       外壳退出时窗口本该被回收，这里再攥一个强引用就变成新的泄漏源
       （而且 WebView2 已经销毁的窗口被拉住，退出时会抛已释放对象异常）。
    """
    if window is None:
        return
    try:
        import weakref
        with _bridge_lock:
            _bridge_ref["ref"] = weakref.ref(window)
    except TypeError:
        # 窗口不可弱引用（测试用假对象）：干脆不记，功能不受影响
        pass


def _window_of_bridge():
    """反查"最近一次挂桥的窗口"（释放时可能拿不到 window 参数），拿到已回收则给 None"""
    with _bridge_lock:
        ref = _bridge_ref.get("ref")
    if ref is None:
        return None
    try:
        return ref()
    except Exception:
        return None


def _log_static(category: str, message: str, action: str = ""):
    """模块级日志（没有 bridge 实例时用；失败静默，日志永远不该影响主链路）"""
    try:
        from ...utils.logger import log
        if action:
            log.op("AI-Agent", action, detail=str(message or ""))
        else:
            log.info("AI-Agent", category, str(message or ""))
    except Exception:
        pass


# ======================================================================
# 前端回值容器（契约 4.3 / 4.5：agent.ui 里"需要回值"的 op，如 deploy_list）
# ======================================================================
# 后端要"动界面"时推事件；需要界面回值的（拿到部署清单）走这里：
#   后端 new_agent_request() → push_event("agent.ui", {op, reqId}) → wait_agent_reply(reqId)
#   前端处理完 → bridge.tryCall("ai.agent_reply", reqId, payload) → provide_agent_reply()
# ⚠️ 为什么容器放本模块而不是 desktop/api/ai.py：agent_web.py（工具实现）
#    在 core 层，它要能**不 import 桌面外壳**就拿到同一份等待表；
#    api 层只做转发（见 AiDomain.agent_reply）。
_reply_lock = threading.Lock()
_reply_slots = {}          # reqId -> {"event": Event, "payload": dict}
_reply_seq = [0]


def new_agent_request(timeout: float = 0.0) -> str:
    """生成一个新的回值请求 id（形如 "u-3"），并登记等待槽；永不抛

    `timeout` 目前只用于文档语义（等待超时由 wait_agent_reply 决定）；
    保留参数是为了以后能有"过期清理"而不改调用点。
    """
    try:
        with _reply_lock:
            _reply_seq[0] += 1
            req_id = f"u-{_reply_seq[0]}"
            # 顺手清理太老的槽（界面不回应时不要让字典无限长）
            if len(_reply_slots) > 64:
                for name in list(_reply_slots.keys())[:32]:
                    _reply_slots.pop(name, None)
            _reply_slots[req_id] = {"event": threading.Event(), "payload": {}}
        return req_id
    except Exception:
        return ""


def wait_agent_reply(req_id: str, timeout: float = 15.0) -> dict:
    """阻塞等前端回值；超时返回 `{}`（永不抛）

    ⚠️ 必须有限超时：界面关了 / 前端没实现 / 用户切走页面都可能永远不回应，
       无上限的 wait 会把工具执行线程（AI 发送线程）钉死，整个聊天卡在"正在思考"。
    """
    key = str(req_id or "")
    if not key:
        return {}
    try:
        with _reply_lock:
            slot = _reply_slots.get(key)
        if slot is None:
            return {}
        got = slot["event"].wait(max(0.1, float(timeout or 0.1)))
        with _reply_lock:
            _reply_slots.pop(key, None)
        return dict(slot.get("payload") or {}) if got else {}
    except Exception:
        return {}


def provide_agent_reply(req_id: str, payload=None) -> bool:
    """前端回包入口（`AiDomain.agent_reply` 调它）：唤醒等待中的工具调用

    返回是否找到了等待中的请求（找不到 = 已超时或 id 不对，属正常情况）。
    """
    key = str(req_id or "")
    if not key:
        return False
    try:
        with _reply_lock:
            slot = _reply_slots.get(key)
            if slot is None:
                return False
            slot["payload"] = payload if isinstance(payload, dict) else {"value": payload}
        slot["event"].set()
        return True
    except Exception:
        return False


__all__ = [
    "AgentBridge", "get_bridge", "SETTING_KEY", "TOOLS_OFF_KEY", "PLUGIN_ID",
    "LOCKED",
    "load_agent_resources", "release_agent_resources",
    "new_agent_request", "wait_agent_reply", "provide_agent_reply",
    "CHAT_MODE_KEY", "CHAT_MODE_CHAT", "CHAT_MODE_AGENT",
    "chat_mode", "set_chat_mode",
]
