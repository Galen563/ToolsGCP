"""GCP-AI Agent：给 GCP-AI 装上"操作 ToolsGCP 的手"（工具注册表 + 执行，不碰界面）。
省 token 的手段（别破坏）：工具清单只有一行的紧凑格式；Agent 关着时不发提示词；
工具返回值先压再截断到 MAX_RESULT_CHARS；一次往返最多 MAX_ROUNDS 轮。
协议用纯文本，不依赖服务端 function calling：
    模型 → 程序：  [TOOL] {"name": "search_resources", "args": {"query": "局域网"}}
    程序 → 模型：  [TOOL_RESULT] {"tool": "...", "ok": true, "data": "..."}
⚠️ 谁来调、怎么把结果塞回 messages 由 ui/ai_chat_panel.py 决定（它跑在主线程）。
"""

import json
import os
import re
import sys

# 常量（根目录、程序目录）
from ... import constants
# 资源库字段的唯一事实来源
from .. import resource_schema

# ---------- 协议标记 ----------
TOOL_TAG = "[TOOL]"
RESULT_TAG = "[TOOL_RESULT]"

# 一次往返里最多跑几轮工具（建目录 → 写文件 → 验证 → 自检 → 回话本来就要好几轮）
MAX_ROUNDS = 6
# 单轮最多执行几个工具调用（智能体团推成员最多一次性可调用2个；
# 和 AGENT_PROMPT_FOOTER 里写的"一轮最多 2 个调用"必须一致，别只改提示词不改这里）
MAX_CALLS_PER_ROUND = 2
# 回给模型的工具结果最多多少字符（超了截断，省 token 第一）
MAX_RESULT_CHARS = 1200
# 单个字段的字符上限
MAX_FIELD_CHARS = 160

# ---------- 语言 ----------
# 主程序的语言名 → 本模块用的 locale
LANGUAGE_TO_LOCALE = {
    "简体中文": "zh_CN",
    "繁體中文": "zh_TW",
    "English": "en_US",
}
DEFAULT_LOCALE = "zh_CN"


def locale_of(language: str) -> str:
    return LANGUAGE_TO_LOCALE.get(str(language or ""), DEFAULT_LOCALE)


def _pick(text, locale: str) -> str:
    """多语言字段取值（dict → 按 locale 取，依次回退 zh_CN / en_US）"""
    if isinstance(text, dict):
        for key in (locale, "zh_CN", "en_US"):
            value = text.get(key)
            if value:
                return str(value)
        return ""
    return str(text or "")


# ---------- 工具定义 ----------
class AITool:
    """一个可以被模型调用的工具"""

    __slots__ = ("name", "description", "parameters", "handler", "source", "danger")

    def __init__(self, name: str, description, handler, parameters: str = "",
                 source: str = "builtin", danger: bool = False):
        self.name = str(name or "").strip()
        # description 可以是 str 或 {locale: text}
        self.description = description
        self.parameters = str(parameters or "").strip()
        self.handler = handler
        self.source = str(source or "builtin")
        self.danger = bool(danger)

    def spec(self, locale: str = DEFAULT_LOCALE) -> str:
        """压成一行清单文本（省 token 就靠它）：`name(params) — 描述`，没参数则不带括号"""
        desc = _pick(self.description, locale)
        if self.parameters:
            return f"{self.name}({self.parameters}) — {desc}"
        return f"{self.name} — {desc}"

    def to_dict(self, locale: str = DEFAULT_LOCALE) -> dict:
        return {
            "name": self.name,
            "description": _pick(self.description, locale),
            "parameters": self.parameters,
            "source": self.source,
            "danger": self.danger,
        }


# ---------- 注册表 ----------
class ToolRegistry:
    """工具注册表（进程内单例，见 get_registry）"""

    def __init__(self):
        self._tools = {}
        # 最近动作流水（给插件页面显示"AI 刚刚做了什么"，只留内存里最近 N 条）
        self._actions = []
        self._max_actions = 60
        self._counters = {}

    # ---------- 注册 ----------
    def register(self, tool: AITool) -> bool:
        if not isinstance(tool, AITool) or not tool.name or not callable(tool.handler):
            return False
        self._tools[tool.name] = tool
        return True

    def register_tool(self, name, description, handler, parameters: str = "",
                      source: str = "builtin", danger: bool = False) -> bool:
        return self.register(AITool(name, description, handler, parameters,
                                    source=source, danger=danger))

    def unregister(self, name: str) -> bool:
        return self._tools.pop(str(name or ""), None) is not None

    def unregister_source(self, source: str) -> int:
        """卸掉某个来源的全部工具（插件被停用/卸载时用）"""
        source = str(source or "")
        doomed = [n for n, t in self._tools.items() if t.source == source]
        for name in doomed:
            self._tools.pop(name, None)
        return len(doomed)

    def clear(self):
        self._tools.clear()

    # ---------- 查询 ----------
    def names(self) -> list:
        return sorted(self._tools.keys())

    def get(self, name: str) -> AITool:
        return self._tools.get(str(name or ""))

    def all(self) -> list:
        return [self._tools[n] for n in self.names()]

    def to_dicts(self, locale: str = DEFAULT_LOCALE) -> list:
        return [t.to_dict(locale) for t in self.all()]

    def spec_text(self, locale: str = DEFAULT_LOCALE) -> str:
        """整段清单文本（塞进 system 提示词）"""
        lines = [t.spec(locale) for t in self.all()]
        return "\n".join(lines)

    def count(self) -> int:
        return len(self._tools)

    # ---------- 执行 ----------
    def execute(self, name: str, args, agent=None) -> dict:
        """跑一个工具，永不抛异常：出错也返回 {"ok": false, "error": ...}
        （模型能看到"失败了、为什么"，然后换个做法，而不是整条链路崩掉）"""
        tool = self.get(name)
        if tool is None:
            result = {"ok": False, "error": f"没有名为 {name} 的工具"}
            self.note(name, "未知工具", ok=False)
            return result
        try:
            data = tool.handler(agent, args if isinstance(args, dict) else {})
        except Exception as exc:                       # noqa: BLE001 - 故意兜底
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            self.note(name, str(exc), ok=False)
            return result
        if isinstance(data, dict) and "ok" in data:
            result = data
        else:
            result = {"ok": True, "data": data}
        self._counters[name] = self._counters.get(name, 0) + 1
        self.note(name, _short_summary(result), ok=bool(result.get("ok", True)))
        return result

    def stats(self) -> dict:
        return {"tools": self.count(), "calls": dict(self._counters),
                "total": sum(self._counters.values())}

    # ---------- 流水 ----------
    def note(self, tool: str, detail: str, ok: bool = True):
        try:
            import time
            self._actions.append({
                "tool": str(tool or ""),
                "detail": str(detail or "")[:200],
                "ok": bool(ok),
                "ts": time.strftime("%H:%M:%S"),
            })
            if len(self._actions) > self._max_actions:
                del self._actions[: len(self._actions) - self._max_actions]
        except Exception:
            pass

    def recent_actions(self, limit: int = 20) -> list:
        limit = max(1, int(limit or 20))
        return list(reversed(self._actions[-limit:]))

    def clear_actions(self):
        self._actions = []
        self._counters = {}


_registry = None


def get_registry() -> ToolRegistry:
    """取进程内的工具注册表（第一次调用时建，并装入内置工具）"""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        register_builtin_tools(_registry)
    return _registry


# ---------- 工具结果的压缩与协议解析 ----------
def _short_summary(result: dict) -> str:
    """从工具结果里抠一句短摘要（写进流水，给插件页面看）"""
    if not isinstance(result, dict):
        return ""
    if not result.get("ok", True):
        return str(result.get("error") or "失败")[:120]
    data = result.get("data")
    if isinstance(data, str):
        return data[:120]
    if isinstance(data, list):
        return f"{len(data)} 条结果"
    if isinstance(data, dict):
        for key in ("summary", "name", "title", "count", "text"):
            if key in data:
                return f"{key}={str(data[key])[:80]}"
        return "、".join(list(data.keys())[:6])
    return str(data)[:120]


def _compact(value, depth: int = 0):
    """把工具返回值压成"短键 + 短值"（省 token 的核心）：字符串超 MAX_FIELD_CHARS 截断、
    字典丢空值、列表最多 12 条"""
    if depth > 3:
        return str(value)[:40]
    if isinstance(value, str):
        text = " ".join(value.split())
        return text if len(text) <= MAX_FIELD_CHARS else text[:MAX_FIELD_CHARS] + "…"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            compacted = _compact(item, depth + 1)
            if compacted in ("", None, [], {}):
                continue
            out[str(key)[:24]] = compacted
        return out
    if isinstance(value, (list, tuple)):
        return [_compact(v, depth + 1) for v in list(value)[:12]]
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if value is None:
        return ""
    return _compact(str(value), depth + 1)


def format_result(name: str, result: dict) -> str:
    """把工具结果格式化成一行回给模型（带标记、带长度上限）"""
    payload = {
        "tool": str(name or ""),
        "ok": bool(result.get("ok", True)),
    }
    if payload["ok"]:
        payload["data"] = _compact(result.get("data", ""))
    else:
        payload["error"] = _compact(str(result.get("error") or "执行失败"))
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "…(已截断)}"
    return f"{RESULT_TAG} {text}"


# 匹配 [TOOL] 后面那一行
_TOOL_LINE_RE = re.compile(r"\[TOOL\]\s*(\{.*?\})\s*(?=\n|\[TOOL\]|$)", re.S)


def parse_tool_calls(text: str):
    """从模型回答里抠出工具调用；返回 (calls, cleaned)
    ⚠️ 不做严格的 JSON 一票否决：模型常多写逗号或多套一层 args，逐个 {...} 块尝试、
    解析失败只跳过那一块。
    """
    raw = str(text or "")
    if TOOL_TAG not in raw:
        return [], raw

    calls = []
    for match in re.finditer(r"\[TOOL\]\s*", raw):
        start = match.end()
        chunk = raw[start:start + 800]
        payload = _first_json_object(chunk)
        if not payload:
            continue
        name = str(payload.get("name") or payload.get("tool") or "").strip()
        if not name:
            continue
        args = payload.get("args")
        if not isinstance(args, dict):
            args = payload.get("arguments")
        if not isinstance(args, dict):
            args = {k: v for k, v in payload.items()
                    if k not in ("name", "tool", "args", "arguments")}
        calls.append({"name": name, "args": args})
        if len(calls) >= MAX_CALLS_PER_ROUND:
            break

    cleaned = _TOOL_LINE_RE.sub("", raw)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return calls, cleaned


def _first_json_object(text: str):
    """从一段文本里取出**第一个配平的 JSON 对象**（配平不了就返回 None）"""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = text[start:index + 1]
                try:
                    return json.loads(blob)
                except Exception:
                    return None
    return None


# ---------- 系统提示词片段 ----------
AGENT_PROMPT_HEADER = {
    "zh_CN": (
        "\n【操作 ToolsGCP（GCP-AI Agent 已开启）】\n"
        "你有一双「手」，可以直接操作 ToolsGCP 本体。需要动手时，"
        "**单独输出一行**工具调用（不要解释、不要放进代码块）：\n"
        '[TOOL] {"name":"工具名","args":{"参数":"值"}}\n'
        "系统会把执行结果用 [TOOL_RESULT] 回给你，你再决定继续调用还是给出最终回答。\n"
        "\n可用工具：\n"
    ),
    "zh_TW": (
        "\n【操作 ToolsGCP（GCP-AI Agent 已開啟）】\n"
        "你有一雙「手」，可以直接操作 ToolsGCP 本體。需要動手時，"
        "**單獨輸出一行**工具呼叫（不要解釋、不要放進程式碼區塊）：\n"
        '[TOOL] {"name":"工具名","args":{"參數":"值"}}\n'
        "系統會用 [TOOL_RESULT] 把執行結果回給你，你再決定繼續呼叫或給出最終回答。\n"
        "\n可用工具：\n"
    ),
    "en_US": (
        "\n【Operating ToolsGCP (GCP-AI Agent is ON)】\n"
        "You have \"hands\": you can operate ToolsGCP itself. When you need to act, "
        "print the tool call **on its own line** (no explanation, no code fence):\n"
        '[TOOL] {"name":"tool_name","args":{"param":"value"}}\n'
        "The app replies with [TOOL_RESULT]; then decide whether to call again or answer.\n"
        "\nAvailable tools:\n"
    ),
}

AGENT_PROMPT_FOOTER = {
    "zh_CN": (
        "\n调用规则（都是为了省 token 和**别说假话**，请严格遵守）：\n"
        "· 一轮最多 2 个调用；能在一次调用里问清的就不要分几次。\n"
        "· 只有确实需要读取或改动 ToolsGCP 状态时才调用；纯聊天、纯推荐不要调用。\n"
        "· ⚠️ **绝对不要在没有真的调用工具的情况下声称「已经帮你做了」**。"
        "你想做的每一件事都必须先输出 [TOOL] 行；没调用就说没调用。\n"
        "· 工具报错时，把**工具给的错误原文**转述给用户（别自己编一个理由），"
        "并告诉用户下一步能怎么做。\n"
        "· 说「没有这个能力」之前先看一遍上面的工具清单：清单里有就去做，"
        "别因为名字不完全一样就说做不到（例如收藏夹相关的有 "
        "list_favorites / set_favorite / create_favorite_folder / move_favorite）。\n"
        "· 拿到结果后用一两句话给用户结论，不要复述原始 JSON、不要贴字段名。\n"
    ),
    "zh_TW": (
        "\n呼叫規則（都是為了節省 token 和**別說假話**，請嚴格遵守）：\n"
        "· 一輪最多 2 個呼叫；能在一次呼叫裡問清的就不要分幾次。\n"
        "· 只有確實需要讀取或改動 ToolsGCP 狀態時才呼叫；純聊天、純推薦不要呼叫。\n"
        "· ⚠️ **絕對不要在沒有真的呼叫工具的情況下聲稱「已經幫你做了」**。\n"
        "· 工具報錯時，把**工具給的錯誤原文**轉述給使用者，並說明下一步。\n"
        "· 說「沒有這個能力」之前先看一遍上面的工具清單，清單裡有就去做。\n"
        "· 拿到結果後用一兩句話給使用者結論，不要複述原始 JSON。\n"
    ),
    "en_US": (
        "\nRules (all to save tokens and to **never lie** — follow strictly):\n"
        "· At most 2 calls per turn; if one call can answer it, do not split it.\n"
        "· Only call tools when you actually need to read or change ToolsGCP state.\n"
        "· ⚠️ **Never claim you did something without actually emitting the "
        "[TOOL] call.** If you did not call a tool, say so.\n"
        "· When a tool errors, relay the **tool's own error text** and say what "
        "the user can do next.\n"
        "· Before saying \"I can't do that\", re-read the tool list above — if a "
        "tool covers it, use it.\n"
        "· After results, answer in one or two sentences; never echo raw JSON.\n"
    ),
}


def build_agent_prompt(locale: str = DEFAULT_LOCALE, registry: ToolRegistry = None,
                       allowed=None) -> str:
    """拼出塞进 system 的 Agent 段（Agent 关着时不要调它）
    allowed 为启用的工具名集合（None = 全部），被关掉的手连清单都不发。
    """
    registry = registry or get_registry()
    tools = registry.all()
    if allowed is not None:
        allowed = set(allowed)
        tools = [t for t in tools if t.name in allowed]
    if not tools:
        return ""
    header = AGENT_PROMPT_HEADER.get(locale, AGENT_PROMPT_HEADER[DEFAULT_LOCALE])
    footer = AGENT_PROMPT_FOOTER.get(locale, AGENT_PROMPT_FOOTER[DEFAULT_LOCALE])
    return header + "\n".join(t.spec(locale) for t in tools) + footer


# ---------- Agent **关着**时给模型的那一句："你没有手" ----------
# 和"没配 API Key"那条一样：不给模型自由发挥的空间，直接告诉它原样回这一句
# （含一个 toolsgcp://plugin/gcp-ai-agent 链接，点了会跳到插件页并把卡片闪两下）。
AGENT_OFF_LINK = "toolsgcp://plugin/gcp-ai-agent"

AGENT_OFF_PROMPT = {
    "zh_CN": (
        "\n【关于操作 ToolsGCP】\n"
        "你现在**没有**操作 ToolsGCP 的能力（内置插件「GCP-AI Agent」没有开启），"
        "只能正常聊天：可以回答问题、推荐资源、解释概念。\n"
        "如果用户要求你操作 ToolsGCP（搜索并打开某个页面、切换页面、加收藏、"
        "改设置、装插件、替他动手做什么），**不要假装做了、也不要编造结果**，"
        "直接原样输出下面这一段（不要改写、不要加别的话）：\n"
    ),
    "zh_TW": (
        "\n【關於操作 ToolsGCP】\n"
        "你現在**沒有**操作 ToolsGCP 的能力（內建外掛「GCP-AI Agent」沒有開啟），"
        "只能正常聊天。\n"
        "如果使用者要求你操作 ToolsGCP（搜尋並開啟某個頁面、切換頁面、加收藏、"
        "改設定、裝外掛、替他動手做什麼），**不要假裝做了、也不要編造結果**，"
        "直接原樣輸出下面這一段（不要改寫、不要加別的話）：\n"
    ),
    "en_US": (
        "\n【About operating ToolsGCP】\n"
        "You currently have **no** ability to operate ToolsGCP (the built-in "
        "'GCP-AI Agent' plugin is off). You can chat normally only.\n"
        "If the user asks you to operate ToolsGCP (search and open a page, switch "
        "pages, add favorites, change settings, install plugins, or do anything on "
        "their behalf), **do not pretend you did it and do not invent results** — "
        "output the following block verbatim (do not rewrite, add nothing):\n"
    ),
}


def build_agent_off_prompt(locale: str = DEFAULT_LOCALE) -> str:
    """Agent 关着时塞进 system 的那一段（含要模型原样回复的固定文案）
    ⚠️ 固定文案必须和界面那条链接完全一致，跳转能力来自 ui 层对 toolsgcp:// 的解析。
    """
    text = AGENT_OFF_PROMPT.get(locale, AGENT_OFF_PROMPT[DEFAULT_LOCALE])
    return text + agent_off_reply(locale) + "\n"


def agent_off_reply(locale: str = DEFAULT_LOCALE) -> str:
    """那条固定回复本身（三语言）"""
    if locale == "zh_TW":
        return (f"我現在只能陪你聊天，還沒法操作 ToolsGCP。"
                f"想要我幫你動手（搜尋、開頁面、改設定、裝外掛…），"
                f"請先開啟內建外掛 <a href=\"{AGENT_OFF_LINK}\">GCP-AI Agent</a>。")
    if locale == "en_US":
        return (f"I can only chat right now — I can't operate ToolsGCP yet. "
                f"To let me do things (search, open pages, change settings, "
                f"install plugins…), turn on the built-in plugin "
                f"<a href=\"{AGENT_OFF_LINK}\">GCP-AI Agent</a>.")
    return (f"我现在只能陪你聊天，还没法操作 ToolsGCP。"
            f"想让我帮你动手（搜索、打开页面、改设置、装插件……），"
            f"请先开启内置插件 <a href=\"{AGENT_OFF_LINK}\">GCP-AI Agent</a>。")


# ---------- 内置工具（真正"动手"的那部分） ----------
def _window(agent):
    """取主窗口（工具全都要通过它操作界面）
    ⚠️ 必须排掉可调用对象：`QWidget.window()` 是方法，绑定方法看着像值其实不可用，
    会让所有操作界面的工具静默失败。
    """
    win = getattr(agent, "main_window", None)
    if win is not None:
        return win
    win = getattr(agent, "window", None)
    if win is None or callable(win):
        return None
    return win


def _apply_ui_action(window, action, on: bool):
    """拨了某个界面开关之后，把界面本身也跟着动一下
    ⚠️ 只改设置不够：这些开关都有配套的"立即应用"函数，不调它们用户会看到
    "设置改了但界面没变"。每一项独立 try，失败不能影响别的。
    """
    if window is None or not action:
        return

    def _try(fn, *a):
        try:
            if callable(fn):
                fn(*a)
        except Exception:
            pass

    if action == "ball":
        _try(getattr(window, "toggle_ai_floating_button", None), bool(on))
    elif action == "sidebar":
        _try(getattr(window, "apply_ai_sidebar_mode", None), bool(on))
    elif action == "ai_enable":
        # ⚠️ 主窗口没有 apply_ai_enabled："开启 GCP-AI"那个开关真正做的事就是
        #    toggle_ai_floating_button（见 cards_ai.change_ai_enabled）。
        _try(getattr(window, "toggle_ai_floating_button", None), bool(on))
        # 侧边栏 AI 那一行也要跟着显示/隐藏
        try:
            settings_page = getattr(window, "settingsInterface", None)
            widget = getattr(settings_page, "ai_sidebar_widget", None)
            if widget is not None:
                widget.setVisible(bool(on))
        except Exception:
            pass
    elif action == "hotkey":
        _try(getattr(window, "apply_hotkey_settings", None), False)
    elif action == "autostart":
        # 开机自启是 utils/system_utils 里的模块级函数，不是主窗口的方法
        try:
            from ...utils.system_utils import set_windows_autostart
            set_windows_autostart(bool(on))
        except Exception:
            pass
    elif action == "github":
        interface = getattr(window, "searchInterface", None)
        _try(getattr(interface, "apply_github_button_setting", None))
    elif action == "view_switch":
        interface = getattr(window, "searchInterface", None)
        _try(getattr(interface, "apply_view_switch_setting", None))


def _apply_setting_side_effects(window, key: str, value):
    """批量改设置之后，为"需要联动"的那几项补一次界面刷新（单键 set_setting 只写值）"""
    if window is None:
        return
    if key == "theme":
        try:
            window.refresh_all_pages_theme()
        except Exception:
            pass
    elif key == "ai_enabled":
        _apply_ui_action(window, "ai_enable", bool(value))
    elif key == "ai_sidebar_mode":
        _apply_ui_action(window, "sidebar", bool(value))
    elif key == "search_show_github":
        _apply_ui_action(window, "github", bool(value))
    elif key == "search_show_view_switch":
        _apply_ui_action(window, "view_switch", bool(value))
    elif key == "search_card_size":
        try:
            from ...widgets.app_card import apply_card_size
            apply_card_size(value)
        except Exception:
            pass
    elif key == "hotkey_enabled":
        _apply_ui_action(window, "hotkey", bool(value))


def _describe_resource(item: dict, full: bool = False) -> dict:
    """把一条资源压成给模型看的短字典"""
    if not isinstance(item, dict):
        return {}
    out = {
        "code": str(item.get("code") or item.get("id") or ""),
        "name": str(item.get("name") or ""),
        # ⚠️ category 是列表：直接 str() 会得到 "['工具']"，模型会照着它搜"带方括号的分类"。
        "category": "/".join(resource_schema.categories_of(item)),
        "desc": str(item.get("description") or ""),
    }
    tags = item.get("tags") or []
    if isinstance(tags, list) and tags:
        out["tags"] = "/".join(str(t) for t in tags[:6])
    if item.get("url"):
        out["url"] = str(item["url"])
    if item.get("github"):
        out["github"] = str(item["github"])
    if full:
        for key in ("version", "author", "platform", "size", "download_url"):
            if item.get(key):
                out[key] = str(item[key])
    return {k: v for k, v in out.items() if v}


def register_builtin_tools(registry: ToolRegistry):
    """装入 ToolsGCP 自带的那组工具
    ⚠️ 数量刻意压在 20 个以内：每多一个工具，每次请求都要多花十几个 token，模型也更容易选错。
    """

    # ---------- 资源库 ----------
    def tool_search(agent, args):
        resources = _all_resources(agent)
        query = str(args.get("query") or args.get("q") or "").strip().lower()
        category = str(args.get("category") or "").strip().lower()
        try:
            limit = int(args.get("limit") or 8)
        except (TypeError, ValueError):
            limit = 8
        limit = max(1, min(20, limit))

        hits = []
        for item in resources:
            if not isinstance(item, dict):
                continue
            haystack = " ".join((
                str(item.get("name") or ""),
                # 关键词 = 类别 ∪ 标签（理由同 prompt._haystack）
                " ".join(resource_schema.keywords_of(item)),
                str(item.get("description") or ""),
                str(item.get("code") or ""), str(item.get("id") or ""),
            )).lower()
            # category 参数按"落在任意一个类别里"匹配（一条资源可有多个类别）
            if category and not any(category in c.lower()
                                    for c in resource_schema.categories_of(item)):
                continue
            if query and query not in haystack:
                continue
            hits.append(item)
            if len(hits) >= limit:
                break
        return {"ok": True, "data": {
            "count": len(hits),
            "items": [_describe_resource(i) for i in hits],
        }}

    def tool_get(agent, args):
        code = str(args.get("code") or args.get("id") or "").strip()
        item = _find_resource(agent, code)
        if item is None:
            return {"ok": False, "error": f"资源库里没有 {code}"}
        return {"ok": True, "data": _describe_resource(item, full=True)}

    def tool_open(agent, args):
        """打开某条资源的详情页（会真的切页面）"""
        window = _window(agent)
        code = str(args.get("code") or args.get("id") or "").strip()
        item = _find_resource(agent, code)
        if item is None:
            return {"ok": False, "error": f"资源库里没有 {code}"}
        if window is None or not hasattr(window, "_open_resource_detail"):
            return {"ok": False, "error": "当前界面不支持打开资源详情"}
        window._open_resource_detail(item)
        return {"ok": True, "data": f"已在界面上打开「{item.get('name')}」的详情页"}

    def tool_stats(agent, args):
        resources = _all_resources(agent)
        categories = {}
        for item in resources:
            if isinstance(item, dict):
                # 一条资源可能属于多个类别：每个类别各记一次
                for name in resource_schema.categories_of(item):
                    categories[name] = categories.get(name, 0) + 1
        top = sorted(categories.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
        return {"ok": True, "data": {
            "total": len(resources),
            "categories": len(categories),
            "top": [f"{k}:{v}" for k, v in top],
        }}

    def tool_list_all(agent, args):
        """返回资源库**全部**条目（需求 5：根治"列举所有只给一两条/随机"）。

        ⚠️ items 不做 limit 截断：总数 N 就返回 N 条；MAX_RESULT_CHARS 截断时带
        truncated 标记，模型据此**继续分页取**而不是"凑合列几条"。
        ⚠️ 本 Web 版的工具执行在 desktop/api/ai.py 侧，资源清单由调用方通过
        agent 上下文注入（_all_resources），和 search_resources 同一数据源。
        """
        resources = [r for r in _all_resources(agent) if isinstance(r, dict)]
        try:
            offset = max(0, int(args.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        try:
            page_size = int(args.get("page_size") or 0)
        except (TypeError, ValueError):
            page_size = 0
        # ⚠️ 分页大小是被 MAX_RESULT_CHARS(1200) 逼出来的：每条紧凑一行约 90~100 字符，
        #    10 条 + 信封刚好不超预算 —— 超了 format_result 会把 JSON **拦腰截断**，
        #    模型拿到的就是坏 JSON，比只给一两条更糟。52 条 ≈ 6 页 = 3 轮（每轮 2 调用），
        #    在 MAX_ROUNDS 之内。条目多时模型按 offset 续页，拿齐 total 条再回答 ——
        #    分页只是取数策略，不影响"必须列完 N 条"。
        limit = page_size if page_size > 0 else 10
        items = []
        for idx, item in enumerate(resources[offset:offset + limit], start=offset + 1):
            items.append({
                "no": idx,
                "name": resource_schema.name_of(item),
                "code": resource_schema.code_of(item) or resource_schema.id_of(item),
                "category": "/".join(resource_schema.categories_of(item)),
                "desc": resource_schema.summary_of(item)[:24],
            })
        return {"ok": True, "data": {
            "total": len(resources),
            "offset": offset,
            "returned": len(items),
            "complete": offset + len(items) >= len(resources),
            "items": items,
        }}

    # ---------- 收藏 ----------
    # ⚠️ 模型常把资源名当编码传进来 → 统一走 _resolve_code 认名字/编码/id；
    # set_favorite 支持直接指定文件夹，一次调用就能"收藏并放进某个夹"。
    def tool_favorites(agent, args):
        """列收藏夹和里面的资源（**连文件夹一起列**，模型才知道有哪些夹）"""
        manager = _favorites(agent)
        if manager is None:
            return {"ok": False, "error": "收藏功能不可用"}
        folders = []
        for name in manager.folders()[:12]:
            codes = list(manager.folder_items(name))[:20]
            names = []
            for code in codes:
                item = _find_resource(agent, code)
                names.append(str(item.get("name")) if item else str(code))
            folders.append({"folder": str(name), "count": manager.count(name),
                            "items": names})
        return {"ok": True, "data": {"total": len(manager.all_codes()),
                                     "folders": folders}}

    def tool_favorite_set(agent, args):
        """收藏 / 取消收藏；可以直接指定要放进哪个收藏夹"""
        manager = _favorites(agent)
        if manager is None:
            return {"ok": False, "error": "收藏功能不可用"}
        raw = args.get("code") or args.get("name") or args.get("id")
        code, err = _resolve_code(agent, raw)
        if err:
            return {"ok": False, "error": err}
        on = args.get("on")
        on = True if on is None else bool(on)
        folder = str(args.get("folder") or "").strip()
        if on:
            if folder and folder not in manager.folders():
                ok, _ = manager.create_folder(folder)
                if not ok:
                    return {"ok": False, "error": f"新建收藏夹「{folder}」失败"}
            manager.add(code, folder or None)
            where = f"收藏夹「{folder}」" if folder else "收藏夹"
            text = f"已把 {_code_name(agent, code)} 放进{where}"
        else:
            manager.remove(code)
            text = f"已把 {_code_name(agent, code)} 移出收藏"
        _refresh_favorites(agent)
        return {"ok": True, "data": {"result": text, "code": code,
                                     "folders": manager.folders()[:12]}}

    def tool_favorite_folder(agent, args):
        """新建一个收藏夹"""
        manager = _favorites(agent)
        if manager is None:
            return {"ok": False, "error": "收藏功能不可用"}
        name = str(args.get("name") or args.get("folder") or "").strip()
        if not name:
            return {"ok": False, "error": "缺少 name 参数（收藏夹名称）"}
        ok, info = manager.create_folder(name)
        if not ok:
            return {"ok": False, "error": str(info)}
        _refresh_favorites(agent)
        # 顺便把资源放进去（一次调用就能"新建并放入"）
        raw = args.get("code") or args.get("name_or_code")
        moved = ""
        if raw:
            code, err = _resolve_code(agent, raw)
            if err:
                return {"ok": True, "data": {"folder": name,
                                             "warning": f"收藏夹建好了，但{err}"}}
            manager.add(code, name)
            _refresh_favorites(agent)
            moved = f"，并把 {_code_name(agent, code)} 放了进去"
        return {"ok": True, "data": {"folder": name,
                                     "result": f"已新建收藏夹「{name}」{moved}"}}

    def tool_favorite_move(agent, args):
        """把一条已收藏的资源移动到另一个收藏夹（夹不存在会自动建）"""
        manager = _favorites(agent)
        if manager is None:
            return {"ok": False, "error": "收藏功能不可用"}
        code, err = _resolve_code(agent, args.get("code") or args.get("name"))
        if err:
            return {"ok": False, "error": err}
        folder = str(args.get("folder") or args.get("to") or "").strip()
        if not folder:
            return {"ok": False, "error": "缺少 folder 参数（目标收藏夹名称）"}
        if folder not in manager.folders():
            ok, info = manager.create_folder(folder)
            if not ok:
                return {"ok": False, "error": str(info)}
        current = manager.folder_of(code)
        if current == folder:
            return {"ok": True, "data": f"{_code_name(agent, code)} 本来就在「{folder}」里"}
        if current:
            manager.move(code, current, folder)
        else:
            manager.add(code, folder)
        _refresh_favorites(agent)
        return {"ok": True, "data": {
            "result": f"已把 {_code_name(agent, code)} 从「{current or '未收藏'}」移到「{folder}」",
            "folders": manager.folders()[:12]}}

    # ---------- 界面导航 ----------
    def tool_goto(agent, args):
        window = _window(agent)
        page = str(args.get("page") or "").strip()
        target = _resolve_page(window, page)
        if target is None:
            return {"ok": False,
                    "error": f"没有名为 {page} 的页面（可用："
                             f"{'、'.join(PAGE_ALIASES.keys())}）"}
        window.switchTo(target)
        try:
            window.navigationInterface.setCurrentItem(target.objectName())
        except Exception:
            pass
        return {"ok": True, "data": f"已切换到「{page}」页面"}

    def tool_notify(agent, args):
        window = _window(agent)
        text = str(args.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "缺少 text 参数"}
        try:
            from qfluentwidgets import InfoBar, InfoBarPosition
            from PyQt5.QtCore import Qt
            InfoBar.info(title="GCP-AI", content=text, orient=Qt.Horizontal,
                         isClosable=True, position=InfoBarPosition.TOP,
                         duration=4000, parent=window)
        except Exception:
            return {"ok": False, "error": "当前环境无法弹提示"}
        return {"ok": True, "data": "提示已显示给用户"}

    # ---------- 设置 ----------
    def tool_get_setting(agent, args):
        window = _window(agent)
        settings = getattr(window, "settings_manager", None) if window else None
        if settings is None:
            return {"ok": False, "error": "设置不可用"}
        key = str(args.get("key") or "").strip()
        if not key:
            return {"ok": False, "error": "缺少 key 参数"}
        if key not in settings.settings:
            return {"ok": False, "error": f"没有名为 {key} 的设置项"}
        return {"ok": True, "data": {key: settings.settings.get(key)}}

    def tool_set_setting(agent, args):
        window = _window(agent)
        settings = getattr(window, "settings_manager", None) if window else None
        if settings is None:
            return {"ok": False, "error": "设置不可用"}
        key = str(args.get("key") or "").strip()
        if not key:
            return {"ok": False, "error": "缺少 key 参数"}
        if key not in settings.settings:
            return {"ok": False, "error": f"没有名为 {key} 的设置项"}
        value = args.get("value")
        old = settings.settings.get(key)
        # 按旧值的类型转一下，避免把 bool 写成字符串导致开关失效
        try:
            if isinstance(old, bool):
                value = str(value).strip().lower() in ("1", "true", "yes", "on", "开")
            elif isinstance(old, int) and not isinstance(old, bool):
                value = int(value)
            elif isinstance(old, float):
                value = float(value)
            elif isinstance(old, str):
                value = str(value)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"值 {value!r} 不适合设置项 {key}"}
        settings.update_setting(key, value)
        return {"ok": True, "data": f"{key}: {old} → {value}"}

    # ---------- 插件 ----------
    def tool_plugins(agent, args):
        window = _window(agent)
        manager = getattr(window, "plugin_manager", None) if window else None
        if manager is None:
            return {"ok": False, "error": "插件系统不可用"}
        items = []
        for info in manager.plugins:
            items.append({
                "id": info.id,
                "name": info.name,
                "on": info.status == "ok",
                "builtin": bool(info.protected),
            })
        return {"ok": True, "data": {"count": len(items), "items": items}}

    # ---------- 批量改设置 / 开关 ----------
    SENSITIVE_KEYS = ("api_key", "api_key_enc", "license_key", "dev_mode_key",
                      "dev_mode_admin")

    def _coerce(old, value):
        """按旧值的类型转一下（bool 写成字符串会让开关失效）"""
        if isinstance(old, bool):
            return str(value).strip().lower() in ("1", "true", "yes", "on", "开",
                                                  "开启", "是")
        if isinstance(old, int) and not isinstance(old, bool):
            return int(value)
        if isinstance(old, float):
            return float(value)
        if isinstance(old, str):
            return str(value)
        return value

    def tool_list_settings(agent, args):
        """列出设置项（模型不知道有哪些 key 时用它自己找）"""
        window = _window(agent)
        settings = getattr(window, "settings_manager", None) if window else None
        if settings is None:
            return {"ok": False, "error": "设置不可用"}
        needle = str(args.get("keyword") or "").strip().lower()
        items = {}
        for key, value in settings.settings.items():
            if str(key).startswith("_"):
                continue                      # 内部迁移标记，不给模型看
            if needle and needle not in str(key).lower():
                continue
            if str(key) in SENSITIVE_KEYS:
                value = "（已隐藏）"
            items[str(key)] = value
        return {"ok": True, "data": {"count": len(items), "settings": items}}

    def tool_update_settings(agent, args):
        """一次改多项设置（避免模型为了改几项来回好几轮）"""
        window = _window(agent)
        settings = getattr(window, "settings_manager", None) if window else None
        if settings is None:
            return {"ok": False, "error": "设置不可用"}
        changes = args.get("settings")
        if not isinstance(changes, dict) or not changes:
            return {"ok": False,
                    "error": "settings 要是一个对象，例如 {\"theme\":\"深色\"}"}
        done, failed = {}, []
        for key, value in changes.items():
            key = str(key)
            if key not in settings.settings:
                failed.append(f"{key}: 没有这个设置项")
                continue
            if key in SENSITIVE_KEYS:
                failed.append(f"{key}: 出于安全不允许由 AI 修改")
                continue
            old = settings.settings.get(key)
            try:
                value = _coerce(old, value)
            except (TypeError, ValueError):
                failed.append(f"{key}: 值 {value!r} 类型不对")
                continue
            try:
                settings.update_setting(key, value)
                _apply_setting_side_effects(window, key, value)
                done[key] = f"{old} → {value}"
            except Exception as exc:
                failed.append(f"{key}: {exc}")
        data = {"changed": done}
        if failed:
            data["failed"] = failed
        return {"ok": bool(done), "data": data,
                "error": "" if done else "；".join(failed)}

    # 界面开关表：模型给一个好念的名字，这里翻成真正的设置键 + 额外动作
    UI_SWITCHES = {
        "floating_ball": ("ai_floating_button", "ball"),
        "ai_ball": ("ai_floating_button", "ball"),
        "sidebar_ai": ("ai_sidebar_mode", "sidebar"),
        "ai_enabled": ("ai_enabled", "ai_enable"),
        "auto_search": ("auto_search", None),
        "github_button": ("search_show_github", "github"),
        "view_switch": ("search_show_view_switch", "view_switch"),
        "startup_with_windows": ("startup_with_windows", "autostart"),
        "autostart": ("startup_with_windows", "autostart"),
        "minimize_to_tray": ("minimize_to_tray", "tray"),
        "hotkey_enabled": ("hotkey_enabled", "hotkey"),
        "splash_screen": ("splash_screen_enabled", None),
        "dev_mode": ("dev_mode_enabled", None),
        "deploy_mode": ("deploy_mode", None),
        "notify": ("notify_enabled", None),
    }

    def tool_ui_switch(agent, args):
        """按名字打开/关闭界面上的各种开关"""
        window = _window(agent)
        settings = getattr(window, "settings_manager", None) if window else None
        if settings is None or window is None:
            return {"ok": False, "error": "设置不可用"}
        raw = str(args.get("name") or "").strip()
        names = "、".join(sorted(UI_SWITCHES))
        if not raw:
            return {"ok": False, "error": "缺少 name；可用：" + names}
        entry = UI_SWITCHES.get(raw) or UI_SWITCHES.get(raw.lower())
        if entry is None:
            return {"ok": False, "error": f"没有叫「{raw}」的开关；可用：" + names}
        key, action = entry
        on = bool(args.get("on", True))
        if key not in settings.settings:
            return {"ok": False, "error": f"设置里没有 {key}"}
        old = settings.settings.get(key)
        settings.update_setting(key, on)
        _apply_ui_action(window, action, on)
        return {"ok": True, "data": f"{raw}（{key}）: {old} → {on}"}

    def tool_set_theme(agent, args):
        """换主题：浅色 / 深色 / 跟随系统

        ⚠️ 必须写**规范简体全名**（浅色主题 / 深色主题 / 跟随系统），和设置页下拉框
           （app.js optionsFor 的 value）、splash.resolve_splash_dark、前端 isDark
           完全同一套字符串。以前这里写的是短形式 "浅色"/"深色"：
           前端 isDark 只认 `=== '浅色主题'`，旧 splash 也只认全名，
           于是"用 AI 说'切到浅色'之后界面/启动画面根本没跟着变浅"，
           而且落进配置后连 splash 都读不出来（回退深色）——
           正是用户报的"浅色主题下启动画面仍是深色"的一条真实来源。
           （splash.resolve_splash_dark 现在也兼容短形式，作为双保险。）
        """
        window = _window(agent)
        settings = getattr(window, "settings_manager", None) if window else None
        if settings is None or window is None:
            return {"ok": False, "error": "设置不可用"}
        raw = str(args.get("mode") or "").strip()
        table = {"light": "浅色主题", "浅色": "浅色主题", "浅色主题": "浅色主题",
                 "dark": "深色主题", "深色": "深色主题", "深色主题": "深色主题",
                 "system": "跟随系统", "auto": "跟随系统", "跟随系统": "跟随系统"}
        value = table.get(raw) or table.get(raw.lower())
        if not value:
            return {"ok": False, "error": "mode 只能是 浅色 / 深色 / 跟随系统"}
        settings.update_setting("theme", value)
        try:
            window.refresh_all_pages_theme()
        except Exception:
            pass
        return {"ok": True, "data": f"主题已切换为「{value}」"}

    def tool_set_language(agent, args):
        """换界面语言（要重启程序才完全生效）"""
        window = _window(agent)
        settings = getattr(window, "settings_manager", None) if window else None
        if settings is None:
            return {"ok": False, "error": "设置不可用"}
        raw = str(args.get("language") or "").strip()
        table = {"zh": "简体中文", "zh_cn": "简体中文", "简体中文": "简体中文",
                 "zh_tw": "繁體中文", "繁體中文": "繁體中文", "繁体中文": "繁體中文",
                 "en": "English", "en_us": "English", "english": "English",
                 "system": "跟随系统", "跟随系统": "跟随系统"}
        value = table.get(raw) or table.get(raw.lower())
        if not value:
            return {"ok": False,
                    "error": "language 只能是 简体中文 / 繁體中文 / English / 跟随系统"}
        settings.update_setting("language", value)
        return {"ok": True,
                "data": f"界面语言已设为「{value}」，**要重启 ToolsGCP 才完全生效**，"
                        f"请提醒用户重启。"}

    # ---------- 插件（开关 / 进配置页） ----------
    def _find_plugin(manager, raw):
        """按 id 或名字找插件（名字允许模糊）"""
        needle = str(raw or "").strip().lower()
        if not needle:
            return None, "缺少 id 参数（插件 id 或名字都行）"
        for info in manager.plugins:
            if str(info.id).lower() == needle:
                return info, ""
        for info in manager.plugins:
            if needle in str(info.name).lower() or needle in str(info.id).lower():
                return info, ""
        return None, f"没有找到叫「{raw}」的插件。现有的：" + "、".join(
            f"{i.name}({i.id})" for i in manager.plugins)

    def tool_set_plugin_enabled(agent, args):
        """启用 / 停用某个插件"""
        window = _window(agent)
        manager = getattr(window, "plugin_manager", None) if window else None
        if manager is None:
            return {"ok": False, "error": "插件系统不可用"}
        info, err = _find_plugin(manager, args.get("id"))
        if info is None:
            return {"ok": False, "error": err}
        on = bool(args.get("on", True))
        try:
            manager.set_enabled(info, on)
            manager.reload_plugin(info)
            # 插件中心那个开关也要同步总开关设置（和用户手点时一致）
            interface = getattr(window, "pluginInterface", None)
            if interface is not None:
                interface._sync_enabled_setting(info, on)
                try:
                    interface.refresh_list()
                except Exception:
                    pass
        except Exception as exc:
            return {"ok": False, "error": f"{info.name} 开关失败: {exc}"}
        return {"ok": True,
                "data": f"{info.name}({info.id}) 已{'启用' if on else '停用'}"}

    def tool_open_plugin_config(agent, args):
        """打开某个插件的配置界面"""
        window = _window(agent)
        manager = getattr(window, "plugin_manager", None) if window else None
        if manager is None:
            return {"ok": False, "error": "插件系统不可用"}
        info, err = _find_plugin(manager, args.get("id"))
        if info is None:
            return {"ok": False, "error": err}
        if info.page is None:
            return {"ok": False, "error": f"{info.name} 没有配置界面（或没加载成功）"}
        try:
            interface = getattr(window, "pluginInterface", None)
            window.switchTo(interface)
            interface.open_config(info)
        except Exception as exc:
            return {"ok": False, "error": f"打开配置界面失败: {exc}"}
        return {"ok": True, "data": f"已打开「{info.name}」的配置界面"}

    # ---------- 搜索页视图 ----------
    def tool_search_view(agent, args):
        """切搜索页的卡片大小 / 磁贴与网格视图"""
        window = _window(agent)
        settings = getattr(window, "settings_manager", None) if window else None
        interface = getattr(window, "searchInterface", None) if window else None
        if settings is None:
            return {"ok": False, "error": "设置不可用"}
        done = []
        size = str(args.get("card_size") or "").strip().lower()
        if size in ("small", "medium", "large", "小", "中", "大"):
            size = {"小": "small", "中": "medium", "大": "large"}.get(size, size)
            settings.update_setting("search_card_size", size)
            try:
                from ...widgets.app_card import apply_card_size
                apply_card_size(size)
            except Exception:
                pass
            done.append(f"卡片大小={size}")
        view = str(args.get("view") or "").strip().lower()
        if view in ("tile", "grid", "磁贴", "网格"):
            view = {"磁贴": "tile", "网格": "grid"}.get(view, view)
            settings.update_setting("search_view", view)
            done.append(f"视图={view}")
        if not done:
            return {"ok": False,
                    "error": "至少给一个：card_size=small|medium|large，"
                             "view=tile|grid"}
        if interface is not None:
            for name in ("refresh_view", "reload_cards", "refresh", "reload"):
                fn = getattr(interface, name, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
                    break
        return {"ok": True, "data": "、".join(done)}

    # ---------- 部署 ----------
    def tool_deploy_list(agent, args):
        """看部署/导出列表里现在有哪些资源"""
        window = _window(agent)
        if window is None:
            return {"ok": False, "error": "主窗口不可用"}
        interface = None
        for attr in ("deployInterface", "exportInterface"):
            interface = getattr(window, attr, None)
            if interface is not None:
                break
        if interface is None:
            for attr in dir(window):
                try:
                    obj = getattr(window, attr)
                except Exception:
                    continue
                name = obj.__class__.__name__.lower() if obj is not None else ""
                if name.startswith("deploy") or name.startswith("export"):
                    interface = obj
                    break
        if interface is None:
            return {"ok": False, "error": "找不到部署页"}
        codes = []
        for attr in ("selected_codes", "deploy_codes", "codes", "items"):
            value = getattr(interface, attr, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    value = None
            if isinstance(value, (list, tuple, set)):
                codes = [str(x) for x in value]
                break
        return {"ok": True, "data": {"count": len(codes), "codes": codes[:50]}}

    # ---------- 日志 ----------
    def tool_read_logs(agent, args):
        """读最近的运行日志（排查问题时用）"""
        # ⚠️ LOG_CURRENT_FILE 是**文件名**不是完整路径（完整路径 = LOGS_DIR + 它），
        #    优先问日志器要 current_path，拿不到再自己拼。
        path = ""
        try:
            from ...utils.logger import log as _logger
            path = str(getattr(_logger, "current_path", "") or "")
        except Exception:
            path = ""
        if not path:
            try:
                from ...constants import LOGS_DIR, LOG_CURRENT_FILE
                path = os.path.join(LOGS_DIR, LOG_CURRENT_FILE)
            except Exception:
                return {"ok": False, "error": "拿不到日志路径"}
        if not os.path.exists(path):
            return {"ok": True,
                    "data": {"path": path, "total_lines": 0, "lines": [],
                             "note": "这一轮还没有写过日志文件"}}
        try:
            limit = int(args.get("limit") or 30)
        except (TypeError, ValueError):
            limit = 30
        limit = max(1, min(limit, 200))
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
        except Exception as exc:
            return {"ok": False, "error": f"读日志失败: {exc}"}
        tail = [line.rstrip("\n") for line in lines[-limit:]]
        return {"ok": True,
                "data": {"path": path, "total_lines": len(lines), "lines": tail}}

    # ---------- 其它动作 ----------
    def tool_open_url(agent, args):
        """用系统默认浏览器打开一个网址"""
        url = str(args.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return {"ok": False, "error": "url 必须以 http:// 或 https:// 开头"}
        try:
            # 统一走 utils/url_open（日志口径一致；工具侧固定前台打开）
            from ...utils.url_open import open_url
            open_url(url, "AI 工具", background=False)
        except Exception as exc:
            return {"ok": False, "error": f"打开失败: {exc}"}
        return {"ok": True, "data": f"已在浏览器打开 {url}"}

    def tool_new_chat(agent, args):
        """开一段新的 AI 对话"""
        window = _window(agent)
        drawer = getattr(window, "ai_chat_drawer", None) if window else None
        if drawer is None:
            return {"ok": False, "error": "AI 聊天界面不可用"}
        try:
            drawer.new_chat()
        except Exception as exc:
            return {"ok": False, "error": f"新建对话失败: {exc}"}
        return {"ok": True, "data": "已经开了一段新对话"}

    # ---------- 像"正常 agent"那样干活：读写文件 / 跑代码 / 自检 ----------
    # ⚠️ 安全边界：路径 realpath 后做前缀判断、禁止 .. 穿越；只允许程序目录与用户主目录
    # 及其桌面/下载/文档；系统目录一律拒绝；跑代码用独立子进程 + 超时，绝不 import 执行。
    WORKSPACE_LIMIT_CHARS = 20000

    def _allowed_paths():
        """允许读写的根目录（全部 realpath 过）"""
        home = os.path.expanduser("~")
        roots = []
        for candidate in (getattr(constants, "SCRIPT_DIR", ""), home,
                          os.path.join(home, "Desktop"),
                          os.path.join(home, "Downloads"),
                          os.path.join(home, "Documents")):
            if candidate and os.path.isdir(candidate):
                roots.append(os.path.realpath(candidate))
        return roots

    def _resolve_path(raw, must_exist=False):
        """把模型给的路径解析成绝对路径；越界/不合法时抛 ValueError"""
        text = str(raw or "").strip().strip('"')
        if not text:
            raise ValueError("缺少 path 参数")
        # 允许相对路径 —— 相对程序目录（这是最自然的口径）
        if not os.path.isabs(text):
            text = os.path.join(getattr(constants, "SCRIPT_DIR", os.getcwd()), text)
        resolved = os.path.realpath(os.path.abspath(text))
        if must_exist and not os.path.exists(resolved):
            raise ValueError(f"路径不存在: {resolved}")
        for root in _allowed_paths():
            if resolved == root or resolved.startswith(root + os.sep):
                return resolved
        raise ValueError("出于安全，只能读写这些目录下的文件："
                         + "、".join(_allowed_paths()))

    def tool_list_dir(agent, args):
        """列目录（像 ls / dir）"""
        try:
            path = _resolve_path(args.get("path") or ".", must_exist=True)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not os.path.isdir(path):
            return {"ok": False, "error": f"{path} 不是目录"}
        try:
            names = sorted(os.listdir(path))
        except Exception as exc:
            return {"ok": False, "error": f"读目录失败: {exc}"}
        items = []
        for name in names[:200]:
            full = os.path.join(path, name)
            try:
                size = os.path.getsize(full) if os.path.isfile(full) else None
            except Exception:
                size = None
            items.append({"name": name,
                          "type": "dir" if os.path.isdir(full) else "file",
                          "size": size})
        return {"ok": True, "data": {"path": path, "count": len(names),
                                     "items": items}}

    def tool_read_file(agent, args):
        """读文本文件（自动截断，避免一次吃掉几万 token）"""
        try:
            path = _resolve_path(args.get("path"), must_exist=True)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if os.path.isdir(path):
            return {"ok": False, "error": f"{path} 是目录，用 list_dir 看它"}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read(WORKSPACE_LIMIT_CHARS + 1)
        except Exception as exc:
            return {"ok": False, "error": f"读文件失败: {exc}"}
        truncated = len(text) > WORKSPACE_LIMIT_CHARS
        if truncated:
            text = text[:WORKSPACE_LIMIT_CHARS]
        return {"ok": True,
                "data": {"path": path, "content": text, "truncated": truncated}}

    def tool_write_file(agent, args):
        """写文本文件（不存在就新建；append=true 追加）"""
        try:
            path = _resolve_path(args.get("path"))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        content = args.get("content")
        if content is None:
            return {"ok": False, "error": "缺少 content 参数"}
        append = bool(args.get("append", False))
        try:
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(path, "a" if append else "w", encoding="utf-8") as handle:
                handle.write(str(content))
        except Exception as exc:
            return {"ok": False, "error": f"写文件失败: {exc}"}
        try:
            size = os.path.getsize(path)
        except Exception:
            size = None
        return {"ok": True,
                "data": f"{'追加' if append else '写入'} {path}（{size} 字节）"}

    def tool_run_python(agent, args):
        """跑一小段 Python 代码，把 stdout / stderr 拿回来
        ⚠️ 用子进程（`sys.executable -c`）而不是 exec()：死循环/段错误只弄死子进程，
        超时还能直接杀。超时默认 20 秒、最多 60 秒。
        """
        code = str(args.get("code") or "")
        if not code.strip():
            return {"ok": False, "error": "缺少 code 参数"}
        try:
            timeout = int(args.get("timeout") or 20)
        except (TypeError, ValueError):
            timeout = 20
        timeout = max(1, min(timeout, 60))
        import subprocess
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=timeout,
                cwd=getattr(constants, "SCRIPT_DIR", None) or None,
                encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"代码跑了超过 {timeout} 秒，已强行结束"}
        except Exception as exc:
            return {"ok": False, "error": f"启动失败: {exc}"}
        out = (proc.stdout or "")[-4000:]
        err = (proc.stderr or "")[-2000:]
        return {"ok": proc.returncode == 0,
                "data": {"returncode": proc.returncode, "stdout": out,
                         "stderr": err},
                "error": "" if proc.returncode == 0 else f"退出码 {proc.returncode}"}

    def tool_self_check(agent, args):
        """自检：汇总收藏夹 / 插件开关 / 资源库 / 关键设置 / 最近调用
        不改任何东西，让模型基于事实回答，而不是凭印象说"已经帮你弄好了"。
        """
        window = _window(agent)
        if window is None:
            return {"ok": False, "error": "主窗口不可用"}
        report = {}
        try:
            manager = _favorites(agent)
            report["favorites"] = {
                "folders": manager.folders() if manager else [],
                "count": len(manager.all_codes()) if manager else 0,
            }
        except Exception as exc:
            report["favorites"] = {"error": str(exc)}
        try:
            plugin_manager = getattr(window, "plugin_manager", None)
            report["plugins"] = [
                {"id": i.id, "name": i.name, "on": i.status == "ok"}
                for i in (plugin_manager.plugins if plugin_manager else [])
            ]
        except Exception as exc:
            report["plugins"] = {"error": str(exc)}
        try:
            report["resources"] = {"count": len(_all_resources(agent) or [])}
        except Exception as exc:
            report["resources"] = {"error": str(exc)}
        try:
            settings = getattr(window, "settings_manager", None)
            report["settings_sample"] = {
                key: settings.settings.get(key) for key in
                ("ai_enabled", "gcp_ai_agent_enabled", "theme", "language")
            } if settings else {}
        except Exception as exc:
            report["settings_sample"] = {"error": str(exc)}
        try:
            report["recent_tool_calls"] = get_registry().recent_actions(5)
        except Exception:
            report["recent_tool_calls"] = []
        return {"ok": True, "data": report}

    # ---------- 注册 ----------
    registry.register_tool(
        "search_resources",
        {"zh_CN": "在 ToolsGCP 资源库里搜索程序/网站（返回编码、名称、简介、链接）",
         "zh_TW": "在 ToolsGCP 資源庫裡搜尋程式/網站（回傳編碼、名稱、簡介、連結）",
         "en_US": "Search ToolsGCP's resource library (code, name, summary, links)"},
        tool_search, "query,category,limit")
    registry.register_tool(
        "get_resource",
        {"zh_CN": "按编码取一条资源的完整信息（含版本、平台、下载直链）",
         "zh_TW": "依編碼取一筆資源的完整資訊（含版本、平台、下載直鏈）",
         "en_US": "Get full info of one resource by code (version, platform, direct link)"},
        tool_get, "code")
    registry.register_tool(
        "open_resource",
        {"zh_CN": "在界面上打开某条资源的详情页（用户能直接看到）",
         "zh_TW": "在介面上開啟某筆資源的詳細頁（使用者能直接看到）",
         "en_US": "Open a resource's detail page in the UI"},
        tool_open, "code")
    registry.register_tool(
        "resource_stats",
        {"zh_CN": "资源库统计：总数、类别数、各类别条数",
         "zh_TW": "資源庫統計：總數、類別數、各類別筆數",
         "en_US": "Resource library stats: total, categories, top categories"},
        tool_stats)
    registry.register_tool(
        "list_all_resources",
        {"zh_CN": "列出资源库**全部**条目（total=N；默认一页 10 条，返回 complete=false 时"
                  "必须用 offset 继续翻页直到取满 N 条）。回答「有哪些/列举所有/多少个」类"
                  "问题**必须调用它并以完整结果作答**：一条不落列完 N 条，不许只给示例、"
                  "不许凭记忆答",
         "zh_TW": "列出資源庫**全部**條目（total=N；預設一頁 10 筆，complete=false 時必須用 "
                  "offset 續頁直到取滿 N 筆）。回答「有哪些/列舉所有」類問題必須呼叫它以完整結果作答",
         "en_US": "List ALL resources (total=N; 10 per page — when complete=false keep "
                  "paging with offset until you have all N). For any 'list all / how many / "
                  "what resources' question you MUST call it and answer with the complete "
                  "list — never examples, never memory."},
        tool_list_all, "offset,page_size")
    registry.register_tool(
        "list_favorites",
        {"zh_CN": "列出收藏夹（含每个夹里的资源）",
         "zh_TW": "列出收藏夾（含每個夾裡的資源）",
         "en_US": "List favorite folders and the resources inside them"},
        tool_favorites)
    registry.register_tool(
        "set_favorite",
        {"zh_CN": "收藏/取消收藏一条资源；folder 可以指定放进哪个收藏夹（不存在会自动新建）",
         "zh_TW": "收藏/取消收藏一筆資源；folder 可指定放進哪個收藏夾（不存在會自動新建）",
         "en_US": "Add/remove a resource to favorites; folder picks the folder"},
        tool_favorite_set, "code,folder,on")
    registry.register_tool(
        "create_favorite_folder",
        {"zh_CN": "新建一个收藏夹；带上 code 可以顺便把资源放进去",
         "zh_TW": "新增一個收藏夾；帶上 code 可以順便把資源放進去",
         "en_US": "Create a favorite folder; pass code to also put a resource in it"},
        tool_favorite_folder, "name,code")
    registry.register_tool(
        "move_favorite",
        {"zh_CN": "把一条资源移动到另一个收藏夹（夹不存在会自动新建）",
         "zh_TW": "把一筆資源移動到另一個收藏夾（夾不存在會自動新建）",
         "en_US": "Move a resource to another favorite folder (created if missing)"},
        tool_favorite_move, "code,folder")
    registry.register_tool(
        "goto_page",
        {"zh_CN": "切换到主界面的某个页面",
         "zh_TW": "切換到主介面的某個頁面",
         "en_US": "Switch the main window to a page"},
        tool_goto, "page")
    registry.register_tool(
        "notify_user",
        {"zh_CN": "在界面上给用户弹一条提示",
         "zh_TW": "在介面上給使用者彈一則提示",
         "en_US": "Show a short toast to the user"},
        tool_notify, "text")
    registry.register_tool(
        "get_setting",
        {"zh_CN": "读取一项 ToolsGCP 设置（如 model_name、splash_screen_enabled）",
         "zh_TW": "讀取一項 ToolsGCP 設定（如 model_name、splash_screen_enabled）",
         "en_US": "Read one ToolsGCP setting (e.g. model_name)"},
        tool_get_setting, "key")
    registry.register_tool(
        "set_setting",
        {"zh_CN": "修改一项 ToolsGCP 设置（会立即生效并保存）",
         "zh_TW": "修改一項 ToolsGCP 設定（會立即生效並儲存）",
         "en_US": "Change one ToolsGCP setting (applies and saves immediately)"},
        tool_set_setting, "key,value", danger=True)
    registry.register_tool(
        "list_plugins",
        {"zh_CN": "列出已安装的插件及启用状态（用 goto_page 打开插件中心看界面）",
         "zh_TW": "列出已安裝的外掛及啟用狀態（用 goto_page 開啟外掛中心看介面）",
         "en_US": "List installed plugins and whether they are on"},
        tool_plugins)
    # ---------- 扩展：查全部设置 / 按名字拨开关 / 主题 / 语言 / 插件 ----------
    registry.register_tool(
        "list_settings",
        {"zh_CN": "列出 ToolsGCP 的全部设置项和当前值（可带 keyword 过滤）；不知道 key 就先调它",
         "zh_TW": "列出 ToolsGCP 的全部設定項和目前值（可帶 keyword 過濾）",
         "en_US": "List all ToolsGCP settings and their current values (optional keyword filter)"},
        tool_list_settings, "keyword")
    registry.register_tool(
        "update_settings",
        {"zh_CN": "一次修改多项设置，settings 是对象如 {\"theme\":\"深色\",\"auto_search\":true}",
         "zh_TW": "一次修改多項設定，settings 是物件如 {\"theme\":\"深色\"}",
         "en_US": "Change several settings at once; settings is an object like {\"theme\":\"dark\"}"},
        tool_update_settings, "settings", danger=True)
    registry.register_tool(
        "ui_switch",
        {"zh_CN": "打开/关闭界面开关：floating_ball 悬浮球、sidebar_ai 侧边栏AI、ai_enabled、"
                   "auto_search、github_button、view_switch、autostart 开机自启、"
                   "minimize_to_tray、hotkey_enabled、splash_screen、dev_mode、deploy_mode、notify",
         "zh_TW": "開啟/關閉介面開關：floating_ball、sidebar_ai、ai_enabled、auto_search、"
                  "github_button、view_switch、autostart、minimize_to_tray、hotkey_enabled…",
         "en_US": "Toggle a UI switch by name: floating_ball, sidebar_ai, ai_enabled, "
                  "auto_search, github_button, view_switch, autostart, minimize_to_tray, "
                  "hotkey_enabled, splash_screen, dev_mode, deploy_mode, notify"},
        tool_ui_switch, "name,on")
    registry.register_tool(
        "set_theme",
        {"zh_CN": "切换主题（浅色 / 深色 / 跟随系统）",
         "zh_TW": "切換主題（淺色 / 深色 / 跟隨系統）",
         "en_US": "Switch the theme (light / dark / system)"},
        tool_set_theme, "mode")
    registry.register_tool(
        "set_language",
        {"zh_CN": "切换界面语言（简体中文 / 繁體中文 / English / 跟随系统）；要重启程序才完全生效",
         "zh_TW": "切換介面語言（简体中文 / 繁體中文 / English / 跟隨系統）；要重啟才完全生效",
         "en_US": "Switch the UI language (zh_CN / zh_TW / en_US); needs a restart to fully apply"},
        tool_set_language, "language")
    registry.register_tool(
        "set_plugin_enabled",
        {"zh_CN": "启用或停用某个插件（按 id 或名字），会同步插件配置界面里的总开关",
         "zh_TW": "啟用或停用某個外掛（依 id 或名稱），會同步外掛設定介面裡的總開關",
         "en_US": "Enable or disable a plugin by id or name (syncs its master switch)"},
        tool_set_plugin_enabled, "id,on")
    registry.register_tool(
        "open_plugin_config",
        {"zh_CN": "打开某个插件的配置界面（插件开着或关着都能打开）",
         "zh_TW": "開啟某個外掛的設定介面（外掛開著或關著都能開啟）",
         "en_US": "Open a plugin's configuration screen (works whether it is on or off)"},
        tool_open_plugin_config, "id")
    registry.register_tool(
        "search_view",
        {"zh_CN": "调整搜索页外观：card_size 卡片大小(small/medium/large)、view 视图(tile 磁贴 / grid 网格)",
         "zh_TW": "調整搜尋頁外觀：card_size(small/medium/large)、view(tile/grid)",
         "en_US": "Adjust the search page: card_size (small/medium/large), view (tile/grid)"},
        tool_search_view, "card_size,view")
    registry.register_tool(
        "deploy_list",
        {"zh_CN": "看部署/导出列表里现在有哪些资源编码",
         "zh_TW": "看部署/匯出清單裡現在有哪些資源編碼",
         "en_US": "Show which resource codes are in the deploy/export list"},
        tool_deploy_list)
    registry.register_tool(
        "read_logs",
        {"zh_CN": "读最近的运行日志（排查报错时用），limit 默认 30 行",
         "zh_TW": "讀最近的執行日誌（排查錯誤時用），limit 預設 30 行",
         "en_US": "Read the most recent log lines (for troubleshooting); limit defaults to 30"},
        tool_read_logs, "limit")
    registry.register_tool(
        "open_url",
        {"zh_CN": "用系统默认浏览器打开一个网址（http/https）",
         "zh_TW": "用系統預設瀏覽器開啟一個網址（http/https）",
         "en_US": "Open a URL in the system browser (http/https)"},
        tool_open_url, "url")
    registry.register_tool(
        "new_chat",
        {"zh_CN": "开一段新的 AI 对话（清空当前上下文）",
         "zh_TW": "開一段新的 AI 對話（清空目前上下文）",
         "en_US": "Start a new AI conversation (clears the current context)"},
        tool_new_chat)
    # ---------- 正常 agent 的"手脚"：文件 / 代码 / 自检 ----------
    registry.register_tool(
        "list_dir",
        {"zh_CN": "列出某个目录里的文件（像 ls/dir）；path 省略时用程序目录",
         "zh_TW": "列出某個目錄裡的檔案（像 ls/dir）",
         "en_US": "List the files in a directory (like ls/dir)"},
        tool_list_dir, "path")
    registry.register_tool(
        "read_file",
        {"zh_CN": "读一个文本文件的内容（会截断，最多 2 万字）",
         "zh_TW": "讀一個文字檔的內容（會截斷，最多 2 萬字）",
         "en_US": "Read a text file (truncated to 20k characters)"},
        tool_read_file, "path")
    registry.register_tool(
        "write_file",
        {"zh_CN": "写一个文本文件（不存在就新建；append=true 表示追加）。只能写程序目录、"
                   "主目录和桌面/下载/文档",
         "zh_TW": "寫一個文字檔（不存在就新建；append=true 表示附加）",
         "en_US": "Write a text file (append=true to append). Only inside the app dir, "
                  "home, Desktop, Downloads or Documents"},
        tool_write_file, "path,content,append", danger=True)
    registry.register_tool(
        "run_python",
        {"zh_CN": "在独立子进程里跑一小段 Python 代码并把输出拿回来（最多 60 秒）；"
                   "适合算数、验证想法、处理文本",
         "zh_TW": "在獨立子程序裡跑一小段 Python 程式碼並取回輸出（最多 60 秒）",
         "en_US": "Run a short Python snippet in a separate process and return its output "
                  "(60s max)"},
        tool_run_python, "code,timeout", danger=True)
    registry.register_tool(
        "self_check",
        {"zh_CN": "自检：汇总收藏夹 / 插件开关 / 资源库 / 关键设置 / 最近调用过的工具。"
                   "动手之后**先调它核对**，再决定怎么说，别凭印象回答",
         "zh_TW": "自檢：彙總收藏夾 / 外掛開關 / 資源庫 / 關鍵設定 / 最近呼叫過的工具",
         "en_US": "Self-check: summarize favorites, plugins, library, key settings and "
                  "recent tool calls before you answer"},
        tool_self_check)


def _favorites(agent):
    """取收藏管理器（拿不到返回 None）"""
    window = _window(agent)
    return getattr(window, "favorites_manager", None) if window else None


def _code_name(agent, code: str) -> str:
    """把编码翻译成人看的名字（找不到就用编码本身）"""
    item = _find_resource(agent, code)
    if item:
        return f"{item.get('name')}（{code}）"
    return str(code)


def _resolve_code(agent, value):
    """把模型给的"资源名 / 编码 / id"统一解析成编码
    ⚠️ 模型常把名字当 code 传进来，直接写进收藏夹会多出一条谁也认不出来的条目
    （用户看到的是"收藏夹毫无变化"）。返回 (code, error)。
    """
    raw = str(value or "").strip()
    if not raw:
        return "", "缺少 code / name 参数（要哪条资源？给名称或编码都行）"

    item = _find_resource(agent, raw)
    if item is not None:
        code = str(item.get("code") or item.get("id") or "").strip()
        if code:
            return code, ""
    # 已经是收藏夹里的一条（用户直接给了编码，但资源库被人删了）
    manager = _favorites(agent)
    if manager is not None and raw in manager.all_codes():
        return raw, ""
    # 认不出来：给个候选清单，让模型自己去纠正，而不是"默默失败"
    candidates = []
    needle = raw.lower()
    for res in _all_resources(agent):
        if not isinstance(res, dict):
            continue
        name = str(res.get("name") or "")
        if needle and needle in name.lower():
            candidates.append(f"{name}（{res.get('code') or res.get('id')}）")
        if len(candidates) >= 5:
            break
    hint = ("，可能是：" + "、".join(candidates)) if candidates else ""
    return "", f"资源库里找不到「{raw}」{hint}。可以先用 search_resources 查准确名称/编码"


def _refresh_favorites(agent):
    """收藏变了之后把收藏页刷新一遍（不刷的话用户看到的还是旧的）"""
    window = _window(agent)
    page = getattr(window, "toolsGCPInterface", None) if window else None
    if page is None:
        return
    for name in ("reload_folders", "refresh_items", "reload", "refresh"):
        fn = getattr(page, name, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
            break
    # 搜索页卡片上的收藏心形也要跟着变
    search = getattr(window, "searchInterface", None) if window else None
    fn = getattr(search, "refresh_favorites", None) if search is not None else None
    if callable(fn):
        try:
            fn()
        except Exception:
            pass


# ---------- 工具内部用的小工具 ----------
# 页面名 → 主窗口属性名（模型只需要记这些"人话"名字）
# ⚠️ 首页（homeInterface，海报轮播页）已随首页整体删除 —— 这里不再认 "home" / "首页"，
#    否则模型会以为有这一页、跳过去拿不到对象再回一句"没有这个页面"。
PAGE_ALIASES = {
    "search": "searchInterface",
    "搜索": "searchInterface",
    "customize": "customizeInterface",
    "定制页": "customizeInterface",
    "favorites": "toolsGCPInterface",
    "收藏": "toolsGCPInterface",
    "deploy": "deployInterface",
    "部署": "deployInterface",
    "workshop": "workshopInterface",
    "gcp工坊": "workshopInterface",
    "notice": "noticeInterface",
    "公告": "noticeInterface",
    "github": "githubInterface",
    "log": "logInterface",
    "日志": "logInterface",
    "feedback": "feedbackInterface",
    "反馈": "feedbackInterface",
    "plugins": "pluginInterface",
    "插件": "pluginInterface",
    "settings": "settingsInterface",
    "设置": "settingsInterface",
}


def _resolve_page(window, name: str):
    """把模型给的人话页面名解析成真实页面对象"""
    if window is None:
        return None
    key = str(name or "").strip()
    if not key:
        return None
    attr = PAGE_ALIASES.get(key) or PAGE_ALIASES.get(key.lower())
    if attr:
        page = getattr(window, attr, None)
        if page is not None:
            return page
    # 兜底：直接按属性名 / objectName 找
    page = getattr(window, key, None)
    if page is not None and hasattr(page, "objectName"):
        return page
    try:
        for child in window.findChildren(object):
            if getattr(child, "objectName", lambda: "")() == key:
                return child
    except Exception:
        pass
    return None


def _all_resources(agent) -> list:
    """取资源库（优先用聊天面板已经缓存好的那份，省一次读盘）"""
    # agent 既可能是聊天抽屉本身，也可能是持有它的 AgentBridge
    drawer = getattr(agent, "drawer", None) or agent
    getter = getattr(drawer, "_resources", None)
    if callable(getter):
        try:
            items = getter()
            if items:
                return list(items)
        except Exception:
            pass
    window = _window(agent)
    manager = getattr(window, "plugin_manager", None) if window else None
    if manager is not None:
        try:
            return list(manager.get_resources() or [])
        except Exception:
            pass
    try:
        from ..resource_loader import ResourceLoader
        loader = ResourceLoader()
        loader.load_from_local()
        return list(loader.get_all())
    except Exception:
        return []


def _find_resource(agent, code: str):
    drawer = getattr(agent, "drawer", None) or agent
    finder = getattr(drawer, "_find_resource", None)
    code = str(code or "").strip()
    if callable(finder) and code:
        try:
            found = finder(code)
            if found:
                return found
        except Exception:
            pass
    needle = code.upper()
    for item in _all_resources(agent):
        if not isinstance(item, dict):
            continue
        if str(item.get("code") or "").strip().upper() == needle:
            return item
        if str(item.get("id") or "").strip().upper() == needle:
            return item
    return None


__all__ = [
    "AITool", "ToolRegistry", "get_registry",
    "TOOL_TAG", "RESULT_TAG", "MAX_ROUNDS", "MAX_CALLS_PER_ROUND",
    "parse_tool_calls", "format_result", "build_agent_prompt",
    "build_agent_off_prompt", "agent_off_reply", "AGENT_OFF_LINK",
    "register_builtin_tools", "locale_of",
]
