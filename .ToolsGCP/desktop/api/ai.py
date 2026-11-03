"""GCP-AI 域（`window.pywebview.api.ai`）—— 把原版 `ui/ai_chat_panel.py` 的**会话模型**搬到 Web 端。
========== 为什么要有这个后端域（而不是前端自己 fetch） ==========
Web 版早期是前端直接 `fetch(api_base + '/chat/completions')`，历史对话也写在前端
localStorage 里。结果是：
  1. **历史对话的粒度完全错了**：localStorage 里存的是"消息数组"，历史面板列出的是
     **每一条消息**；而原版（`core/ai/chat_store.py`）是 **一个会话 = 一个 json 文件**，
     历史面板列出的是**一个个对话页**（标题 = 第一句话、时间是会话的创建/更新时间）。
  2. 清除历史后前端只清了自己的 localStorage，列表要"重新进一次"才刷新。
  3. API Key 要送到前端才能发请求（前端 fetch 必须带 Authorization）。
所以这里把原版那套原封不动接回来：
  · 会话文件 `.ToolsGCP/config/chats/<id>.json`（**和 PyQt 版共用同一份数据**，
    在一边聊过的对话，另一边打开就能看到）；
  · 组装 messages 走 `pymodels.core.ai.prompt`（system 提示词 / 资源清单 / 上下文轮数）；
  · 发请求走 `pymodels.core.ai.client.chat`（永不抛异常，返回可读的错误说明）；
  · API Key 只在后端使用，不经过前端。
========== 历史对话不存储的成因与写入顺序约定 ==========
日志里 0 条 `[AI|chat]`、`<用户数据根>/config/chats/` 为空，不是存储坏了，而是
**根本就没走到存储**：
  · 用户设置里 `api_key` 与 `model_name` 都是空 → 前端 `aiSend()` 里有一道
    "先查 `settings.api_key_state`，没配 Key 就只往界面推两条气泡并 return"的早退，
    **压根没调 `ai.send`**（所以后端日志也不可能有记录）；
  · 后端 `send()` 若把 "没 Key/没模型" 放在**写盘之前**、且失败**不打日志**，
    就算某个调用方真的走到了这里，也同样是"什么都不留痕"。
本层的写入顺序（对齐 PyQt 版 `ai_chat_panel.send_message()`）：
  1. **用户消息先落盘**（不管后面发不发得出去，说过的话不能丢）；
  2. 没有 API Key / 模型名 → 落一条固定的引导回答再返回 `{ok:true, kind:"no_key", reply:…}`，
     和原版"给固定回答 + 都写进历史"完全一致；
  3. 每条失败路径都写日志（`no_key` / `no_model` / 请求失败 / 落盘失败），
     "历史不存储"这类问题能在日志里一句话定位；
  4. 落盘结果真的检查（`ChatStore.append()` 内部把 `save()` 的返回值丢了，
     这里补 `path_of()` 存在性校验 + 再 save 一次），失败会带 `persisted:false` 回前端。
⚠️ 前端那道早退（`aiSend` 里 no-key 直接 return）与后端策略要一致：
   要么删掉那道早退让后端来兜（推荐，历史就能存下来），
   要么接受"没配 Key 的提问不落历史"。
"""

import os
import re
import time

from pymodels.constants import APP_NAME, APP_VERSION


def _ok(**kwargs):
    payload = {"ok": True}
    payload.update(kwargs)
    return payload


def _fail(message, **kwargs):
    payload = {"ok": False, "error": str(message or "unknown error")}
    payload.update(kwargs)
    return payload


def _log(level: str, category_zh: str, category_en: str, message: str):
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)(category_zh, category_en, message)
    except Exception:
        pass


class AiDomain:
    """GCP-AI 会话 / 历史 / 发送"""

    def __init__(self, shell):
        self._shell = shell

    # ---------- 基础 ----------
    @property
    def store(self):
        from pymodels.core.ai.chat_store import ChatStore
        return ChatStore()

    @property
    def settings_manager(self):
        return getattr(self._shell, "settings_manager", None)

    def _setting(self, key: str, fallback=None):
        manager = self.settings_manager
        if manager is None:
            return fallback
        value = manager.settings.get(key)
        return fallback if value in (None, "") else value

    def _language(self) -> str:
        try:
            value = self._setting("language", "简体中文")
            if value and value != "跟随系统":
                return str(value)
        except Exception:
            pass
        return "简体中文"

    def _locale(self) -> str:
        """当前界面语言 → locale（zh_CN / zh_TW / en_US）
        ⚠️ 优先问 shell：设置里存跟随系统时只有 `shell.current_language()` 才知道
           用户到底是什么语言（`_language()` 那条路会硬退回简体中文）。
           `/plugin` 的悬浮提示和注入指令都按它取文案，否则英文系统下会冒出中文提示。
        """
        language = ""
        try:
            language = str(self._shell.current_language() or "")
        except Exception:
            language = ""
        if not language:
            language = self._language()
        try:
            from pymodels.core.language_manager import locale_for
            return locale_for(language)
        except Exception:
            return "zh_CN"

    # ---------- 输入框 "/" 悬浮提示（插件制作辅助） ----------
    def chat_hints(self):
        """前端输入框上方的悬浮提示：**只在插件制作辅助开启时**才有条目
        契约（`app.js` 的 `loadAiHints()`）：
            `{ok:true, hints:[{id,label,insert,prompt,priority}], locale}`
            `{ok:false, error}` → 前端会退回它内置的兜底提示（所以失败也要回 ok=false，
            不要用"空 hints 的 ok=true"把前端兜底也一起堵死）。
        行为约定：/plugin 悬浮提示只在 GCP-AI 的**任意界面**输入 `/` 时跳出，
        且只有"插件制作辅助"**开启**时才有反应 —— 所以关着的时候必须**一条都不给**。
        """
        try:
            from .plugins import hint_payload, maker_enabled
            manager = self.settings_manager
            if not maker_enabled(manager):
                return _ok(hints=[], locale=self._locale(), enabled=False)
            locale = self._locale()
            hint = hint_payload(manager, locale)
            if not hint:
                return _fail("插件制作辅助的提示文案不可用（插件可能缺失或 lang/*.json 损坏）",
                             hints=[], locale=locale, enabled=True)
            return _ok(hints=[hint], locale=locale, enabled=True)
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "AI", "hint", f"组装 /plugin 悬浮提示失败: {exc}")
            return _fail(exc, hints=[])

    def _plugin_prompt(self, content: str):
        """这条消息是不是 `/plugin` 命令；是且插件制作辅助开着 → (是否命令, 注入指令)
        返回 `(is_plugin_command, prompt)`：
            · 插件制作辅助关着 → `(False, "")`：按**普通消息**处理
              （只有开启后输入 `/` 才会有反应）；
            · 开着但插件缺失/文案坏了 → `(False, "")`：宁可当普通消息，也不给它一个
              半截指令让模型瞎调工具。
        """
        text = str(content or "").lstrip()
        if not text.lower().startswith("/plugin"):
            return False, ""
        try:
            from .plugins import hint_payload, maker_enabled
            manager = self.settings_manager
            if not maker_enabled(manager):
                return False, ""
            hint = hint_payload(manager, self._locale())
            prompt = str((hint or {}).get("prompt") or "")
            if not prompt:
                return False, ""
            return True, prompt
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "AI", "hint", f"读取 /plugin 指令失败（按普通消息处理）: {exc}")
            return False, ""

    # ---------- 会话列表（历史面板） ----------
    @staticmethod
    def _preview(session) -> str:
        """历史卡片的一行摘要（原版 HistoryCard._preview_text 的同款语义）"""
        for message in reversed(session.messages or []):
            text = " ".join(str(message.get("content") or "").split())
            if text:
                return text[:60] + ("…" if len(text) > 60 else "")
        return ""

    def sessions(self, limit: int = 100):
        """历史对话列表：**一条 = 一个对话页**（不是一条消息）"""
        try:
            store = self.store
            rows = []
            for session in store.list_sessions()[:max(1, int(limit or 100))]:
                rows.append({
                    "id": session.id,
                    "title": session.title or "新对话",
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                    "count": len(session.messages or []),
                    "preview": self._preview(session),
                })
            return _ok(sessions=rows, count=len(rows))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def session(self, session_id: str = ""):
        """读一个会话的全部内容；session_id 为空则返回最近一个（没有就新建）"""
        try:
            store = self.store
            target = str(session_id or "").strip()
            loaded = store.load(target) if target else None
            if loaded is None:
                if target:
                    return _fail("这个对话已经不存在了")
                loaded = store.latest_session()
            return _ok(session={"id": loaded.id, "title": loaded.title,
                                "created_at": loaded.created_at,
                                "updated_at": loaded.updated_at,
                                "messages": [self._message_view(m)
                                             for m in (loaded.messages or [])]})
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def new_session(self):
        """新建一个空会话（不落盘，直到发出第一条消息）"""
        try:
            session = self.store.new_session()
            return _ok(session={"id": session.id, "title": "", "messages": []})
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def delete_session(self, session_id: str = ""):
        """删掉一个对话页"""
        try:
            target = str(session_id or "").strip()
            if not target:
                return _fail("没有指定要删除的对话")
            ok = self.store.delete(target)
            _log("op", "AI", "session", f"删除历史对话 {target} ok={ok}")
            return _ok(deleted=bool(ok), id=target)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def clear(self):
        """清空全部历史对话（返回删掉的**对话页**数量），前端立即重新拉列表"""
        try:
            count = self.store.clear()
            _log("op", "AI", "session", f"清空历史对话 {count} 个")
            return _ok(cleared=count)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    # ---------- 发送 ----------
    def _resources(self):
        """资源清单（system 提示词里要用的；拿不到就给空列表，不影响聊天）
        ⚠️ 复用 ResourcesDomain 那份**已经加载好**的 loader（它按设置里的资源来源算路径、
           还带缓存）。不要在这里另 new 一个 ResourceLoader —— 那会再读一遍 JSON。
        """
        try:
            api = getattr(self._shell, "api", None)
            domain = getattr(api, "resources", None)
            if domain is not None:
                items = domain._all_items()
                if items:
                    return list(items)
        except Exception:
            pass
        return []

    # ---------- 工具循环（create_plugin） ----------
    def _execute_tool(self, name: str, args: dict, locale: str) -> dict:
        """执行一个 [TOOL] 调用，返回工具结果信封（**绝不抛**）
        ⚠️ 只执行 `create_plugin`：内置 Agent 工具（search_resources / open_page…）
           全都依赖 py 版 Qt 主窗口对象，Web 版既没有也不该在乱动界面 ——
           模型要是凭记忆硬写一个名字过来，就明确告诉它"不支持"，让它直接回答用户。
        """
        tool = str(name or "").strip()
        if tool == "create_plugin":
            try:
                from .plugins import execute_create_plugin
                return execute_create_plugin(self.settings_manager, args, locale=locale)
            except Exception as exc:                      # noqa: BLE001
                _log("err", "AI", "agent_tool", f"create_plugin 执行异常: {exc}")
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": False,
                "error": f"本轮不支持工具 {tool}（只支持 create_plugin）；请直接用文字回答用户。"}

    def _chat_with_tools(self, messages: list, api_key: str, model: str, api_base: str,
                         locale: str = "zh_CN", allow_tools: bool = False):
        """请求模型；回答里带 [TOOL] 就执行、把结果塞回去再问一轮
        返回 `(result, rounds, created_plugins)`：
            result —— 最后一次 `ChatResult`（ok=False 表示失败，调用方照原样转成 error）；
            rounds —— 实际跑了几个工具轮（0 = 一次就答完）；
            created_plugins —— 这轮生成的插件 id（给前端决定要不要刷新插件列表）。
        ⚠️⚠️ `allow_tools=False`（普通聊天）时**一次就返回**：不解析、不执行任何工具。
            py 版是靠 `AgentBridge.enabled()`（GCP-AI Agent 开关）决定要不要跑工具；
            Web 版的内置 Agent 工具全都依赖 Qt 主窗口对象，只有 `/plugin` 指令
            才允许调 `create_plugin`。普通聊天里模型就算写了 `[TOOL]`，也当普通文本。
        协议与 py 版 `ui/ai_chat_panel.py：_agent_try_continue` 完全一致：
            模型 → 程序  `[TOOL] {"name": "create_plugin", "args": {...}}`
            程序 → 模型  `[TOOL_RESULT] {"tool": "...", "ok": true, "data": "..."}`
        轮数上限 `agent_tools.MAX_ROUNDS`（6）、单轮调用上限 `MAX_CALLS_PER_ROUND`（2）
        都由 `parse_tool_calls()` 负责，这里只守 MAX_ROUNDS。
        ⚠️⚠️ `scratch`（工具调用 + 结果的往返消息）**只活在这次请求里**，绝不写进
            chat_store：历史里只留"用户问 → 最终回答"，否则历史面板会被一堆 JSON 淹掉。
        ⚠️ 这是 js_api 的工作线程，同步阻塞是预期行为（前端显示"正在思考…"），
            但最多 6 轮，不会无限转。
        """
        from pymodels.core.ai import agent_tools
        from pymodels.core.ai import client as ai_client

        created = []
        scratch = []
        rounds = 0
        result = ai_client.chat(messages, api_key, model, api_base)
        if not allow_tools:
            return result, rounds, created
        while True:
            if not getattr(result, "ok", False):
                return result, rounds, created
            content = str(getattr(result, "content", "") or "")
            if rounds >= int(getattr(agent_tools, "MAX_ROUNDS", 6)):
                _log("warn", "AI", "agent",
                     f"工具轮数到达上限 {getattr(agent_tools, 'MAX_ROUNDS', 6)}，按普通回答收尾")
                return result, rounds, created
            try:
                calls, _cleaned = agent_tools.parse_tool_calls(content)
            except Exception as exc:                      # noqa: BLE001
                _log("warn", "AI", "agent", f"解析工具调用失败（按普通回答处理）: {exc}")
                return result, rounds, created
            if not calls:
                return result, rounds, created

            results = []
            for call in calls:
                name = str(call.get("name") or "")
                args = call.get("args") if isinstance(call.get("args"), dict) else {}
                try:
                    outcome = self._execute_tool(name, args, locale)
                except Exception as exc:                  # noqa: BLE001
                    outcome = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                if name == "create_plugin" and outcome.get("ok"):
                    created_id = str((outcome.get("data") or {}).get("id") or "")
                    if created_id:
                        created.append(created_id)
                _log("op", "AI", "agent_tool",
                     f"工具 {name} ok={bool(outcome.get('ok'))} "
                     f"args={list(args.keys())[:6]}")
                try:
                    results.append(agent_tools.format_result(name, outcome))
                except Exception:                         # noqa: BLE001
                    results.append(f"{getattr(agent_tools, 'RESULT_TAG', '[TOOL_RESULT]')} "
                                   f'{{"tool":"{name}","ok":false}}')
            scratch.append({"role": "assistant", "content": content})
            scratch.append({"role": "user", "content": "\n".join(results)})
            rounds += 1
            result = ai_client.chat(messages + scratch, api_key, model, api_base)

    @staticmethod
    def _clean_reply(text: str) -> str:
        """最终回答里如果还残留 [TOOL] 标记就抠掉（工具轮数到上限时会这样）
        ⚠️ 不能写 `cleaned or raw`：模型整条回答只有一个 `[TOOL] {...}` 时，
           `parse_tool_calls` 抠出来的 cleaned 恰恰是**空串**，那样又会把原始标记fallback 回来。
           这里改成"认出了调用就用 cleaned（哪怕为空）"。
        """
        raw = str(text or "")
        if "[TOOL]" not in raw:
            return raw.strip()
        try:
            from pymodels.core.ai import agent_tools
            calls, cleaned = agent_tools.parse_tool_calls(raw)
            if calls:
                return str(cleaned or "").strip()
            return raw.strip()
        except Exception:
            return raw.strip()

    def _persist_message(self, store, session, role: str, content: str,
                         extra: dict = None) -> bool:
        """追加一条消息并**确认真的写到磁盘**，返回是否成功
        ⚠️ 为什么要多此一举：`ChatStore.append()` 内部有 `self.save(session)` 但**丢掉了
           返回值**（它永远 return True）。于是"目录不可写 / 磁盘满 / 权限不够"这类失败
           在调用方完全看不出来 —— 用户以为聊过的话丢了，日志里也是干净的。
           这里补两层确认：① append 之后检查会话文件是否真的存在；② 不存在就再
           `store.save()` 一次；③ 仍然没有 → 记 err 日志并让上层把 persisted:false 告诉前端。
        ⚠️ `extra`：报错气泡要带 `{"error": True, "kind": ...}`，历史面板才能原样还原。
        """
        try:
            accepted = store.append(session, role, content, persist=True, extra=extra)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "chat", f"追加 {role} 消息异常: {type(exc).__name__}: {exc}")
            return False
        if not accepted:
            _log("warn", "AI", "chat", f"追加 {role} 消息被拒绝（内容为空或角色非法）")
            return False
        try:
            path = store.path_of(session.id)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "chat", f"取会话文件路径失败: {exc}")
            return False
        try:
            if not os.path.isfile(path):
                store.save(session)                    # 兜底再写一次（原子写，幂等）
            if os.path.isfile(path):
                return True
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "chat", f"保存会话失败: {type(exc).__name__}: {exc}")
            return False
        _log("err", "AI", "chat",
             f"保存会话失败：{path} 不存在（会话目录可能不可写）")
        return False

    def _describe_config(self, api_base: str = "", model: str = "",
                         key_tail: str = "") -> str:
        """失败提示里附一行“当时用的是哪套配置”，用户一眼能看出 Key/模型/地址对不对。
        只显示 Key 尾号，绝不回传明文。
        """
        parts = []
        try:
            from pymodels.core.ai import providers as ai_providers
            pid = str(self._setting("ai_provider", "deepseek") or "deepseek").strip().lower()
            parts.append("服务商："
                         + (ai_providers.provider_label(pid)
                            if ai_providers.get_provider(pid) else pid))
        except Exception:                                # noqa: BLE001
            parts.append("服务商：?")
        if model:
            parts.append(f"模型：{model}")
        if api_base:
            parts.append(f"接口：{api_base}")
        if key_tail:
            parts.append(f"Key 尾号：{key_tail}")
        return "，".join(parts)

    def send(self, session_id: str = "", text: str = "", reply_mode: str = "",
             resend: bool = False):
        """发一条消息：落盘用户消息 → 组装 messages → 请求 → 追加回答（全部落盘）
        返回 `{ok, reply, session_id, session}`；失败时 `error` 是可读说明。
        额外返回：
            `tool_rounds` / `created_plugins` / `plugin_command`（见 _chat_with_tools）
            `persisted`   —— 这次的消息有没有真的写进磁盘（false = 历史里看不到，前端可提示）
            `kind`        —— "no_key" / "no_model" / 请求失败的分类
        ⚠️ `resend=True`（前端「重新生成」）：先把上一条 assistant 回答（含报错气泡）
           从会话里摘掉，再**不重复落**同一条用户消息 —— 否则历史里会出现两条一模一样的
           提问、旧回答也残留，而前端现在以磁盘为准重建气泡，会把这些都显示出来。
        ⚠️⚠️ **顺序和 PyQt 版 `ai_chat_panel.send_message()` 一致：先落盘、再判断能不能发。**
           以前是"先查 Key/模型 → 不满足就直接 return"：既没落盘、也没打日志，
           用户看到的就是"历史对话不存储 + 日志里什么都没有"（ 的根因之一）。
           现在：
             ① 用户消息先写进 chats/<id>.json；
             ② 没配 Key / 模型名 → 落一条固定的引导回答，返回 `{ok:true, kind:"no_key"}`，
                和原版"给一条固定回答、两个气泡都进历史"完全一致；
             ③ 每条失败路径都写日志（no_key / no_model / 请求失败 / 落盘失败）；
             ④ 落盘失败会在返回值里带 `persisted:false`，前端能提示"对话没保存"。
        ⚠️ 这是**同步阻塞**调用（js_api 在工作线程里跑，不会卡界面）：
           前端在 await 期间显示"正在思考…"气泡。
        """
        session = None
        try:
            from pymodels.core.ai import client as ai_client
            from pymodels.core.ai import prompt as ai_prompt

            content = str(text or "").strip()
            if not content:
                _log("warn", "AI", "chat", "空消息，已忽略")
                return _fail("消息是空的")

            store = self.store
            target = str(session_id or "").strip()
            session = store.load(target) if target else None
            if session is None:
                session = store.new_session()
                _log("info", "AI", "chat", f"新建会话 {session.id}")
            else:
                _log("dbg", "AI", "chat", f"续聊会话 {session.id}")

            # ① 用户消息**先落盘**（说过的话不能丢；即使后面发不出去也要留在历史里）
            #    ⚠️ resend（重新生成）：先摘掉上一条 assistant 回答/报错气泡，
            #       再跳过“重复落用户消息”（最后一条就是同一条提问）。
            if resend:
                while session.messages and session.messages[-1].get("role") == "assistant":
                    session.messages.pop()
            is_dup = (resend and session.messages
                      and session.messages[-1].get("role") == "user"
                      and str(session.messages[-1].get("content") or "") == content)
            if is_dup:
                # 用户消息已在磁盘上；仍要确认文件在（防止极端情况目录被清）
                user_saved = os.path.isfile(store.path_of(session.id))
                if not user_saved:
                    user_saved = self._persist_message(store, session, "user", content)
            else:
                user_saved = self._persist_message(store, session, "user", content)
            if not user_saved:
                return _fail("对话没能保存到磁盘（检查会话目录是否可写）",
                             kind="storage", session_id=session.id,
                             session=self._dump(session), persisted=False)

            # ② 能不能发？不能发就给一条固定引导回答（同样落盘）—— 对齐 PyQt 版行为
            manager = self.settings_manager
            api_key = ""
            if manager is not None:
                try:
                    api_key = manager.get_api_key() or ""
                except Exception as exc:                  # noqa: BLE001
                    _log("warn", "AI", "chat", f"读取 API Key 失败: {exc}")
                    api_key = ""
            model = str(self._setting("model_name", "") or "").strip()
            display_model = model          # 界面显示名（描述/返回值用，不发给 API）
            # ⚠️ 模型名以用户设置/下拉为准，程序不替用户改“值”；但发送前必须把
            #    界面显示名解析成官方 API 模型名（deepseek-v4.1-flash → deepseek-flash），
            #    否则服务端 400（官方文档确认 API 名是 deepseek-flash，由 V4.1 提供服务）。
            try:
                from pymodels.core.ai import providers as ai_providers
                pid = str(self._setting("ai_provider", "deepseek")
                          or "deepseek").strip().lower()
                model = ai_providers.resolve_api_model(pid, model)
            except Exception:                              # noqa: BLE001
                pass
            api_base = str(self._setting("api_base", "") or "").strip()
            missing = []
            if not str(api_key).strip():
                missing.append("API Key")
            if not model:
                missing.append("模型名称")
            if missing:
                hint = ("还没有配置" + " 和 ".join(missing)
                        + "。打开设置里的 GCP-AI 板块填好再聊。\n"
                          "（这条对话已经保存到历史里，配置好之后可以接着聊）")
                saved = self._persist_message(store, session, "assistant", hint)
                _log("op", "AI", "chat_no_key",
                     f"会话 {session.id} 缺 {'/'.join(missing)}，已保存对话并给出引导回答")
                return _ok(reply=hint, kind="no_key",
                           session_id=session.id, session=self._dump(session),
                           missing=missing, persisted=bool(saved),
                           tool_rounds=0, created_plugins=[], plugin_command=False)

            # ③ 组装 messages（system 提示词 / 资源清单 / 上下文轮数全走原版实现）
            rounds = 0
            try:
                rounds = int(self._setting("ai_context_rounds", 0) or 0)
            except Exception:
                rounds = 0
            mode = str(reply_mode or self._setting("ai_reply_mode", "standard") or "standard")
            try:
                keyword = ai_prompt.extract_keyword(content)
            except Exception:
                keyword = ""
            messages = ai_prompt.build_messages(
                session.messages, self._resources(), self._language(),
                context_rounds=rounds, keyword=keyword, mode=mode)

            # ④ `/plugin`：把插件制作辅助的 Skill 指令追加到 system 末尾
            #    ⚠️ 只改**第一条 system**的内容（build_messages 保证 system 永远第一条且只有一条），
            #       不新增第二条 system：有些网关/模型对多 system 的处理不一致，
            #       而 py 版也是"追加到同一条 system"。
            locale = self._locale()
            plugin_command, plugin_prompt = self._plugin_prompt(content)
            if plugin_prompt:
                if messages and str(messages[0].get("role")) == "system":
                    messages[0]["content"] = (str(messages[0].get("content") or "")
                                              + "\n\n" + plugin_prompt)
                else:
                    messages.insert(0, {"role": "system", "content": plugin_prompt})
                _log("info", "AI", "hint",
                     f"用户输入 /plugin：已注入插件制作辅助指令（{len(plugin_prompt)} 字）")

            # ⑤ 请求（含工具循环；client.chat 永不抛异常）
            #    ⚠️ 只有 `/plugin` 指令才允许跑工具（见 _chat_with_tools 的说明）
            result, tool_rounds, created = self._chat_with_tools(
                messages, api_key, model, api_base, locale=locale,
                allow_tools=plugin_command)

            if not getattr(result, "ok", False):
                kind = getattr(result, "kind", "") or ""
                message = getattr(result, "message", "") or "请求失败"
                key_tail = ""
                if manager is not None:
                    try:
                        key_tail = manager.key_tail() or ""
                    except Exception:                     # noqa: BLE001
                        key_tail = ""
                config = self._describe_config(api_base, display_model, key_tail)
                error_text = f"{message}\n当前配置：{config}" if config else message
                # ⚠️ 报错也要落盘（带 error 标记）：这就是“从历史点进来对话没了”的根因修复，
                #   以前失败分支只 return，前端只在内存里推一个气泡。
                saved = self._persist_message(store, session, "assistant", error_text,
                                              {"error": True, "kind": kind})
                _log("err", "AI", "chat",
                     f"请求失败 kind={kind} {message}"
                     f"（错误已落盘={saved}，会话 {session.id}）")
                return _fail(error_text, kind=kind,
                             session_id=session.id, session=self._dump(session),
                             tool_rounds=tool_rounds, created_plugins=created,
                             persisted=bool(saved))

            reply = self._clean_reply(str(getattr(result, "content", "") or ""))
            if not reply:
                reply = ("AI 反复调用工具但没有给出最终回答，请把你的需求说得更具体一点，"
                         "或者直接告诉它插件的 id。" if tool_rounds
                         else "模型没有返回内容，换个说法再试一次。")
            reply_saved = self._persist_message(store, session, "assistant", reply)
            if not reply_saved:
                _log("err", "AI", "chat",
                     f"回答写盘失败（会话 {session.id}）：本次回答只显示在界面上")
            _log("op", "AI", "chat",
                 f"会话 {session.id} 收到回答 {len(reply)} 字"
                 + (f"（工具轮 {tool_rounds}，生成插件 {', '.join(created)}）"
                    if tool_rounds else "")
                 + ("" if reply_saved else "（写盘失败）"))
            return _ok(reply=reply, session_id=session.id, session=self._dump(session),
                       tool_rounds=tool_rounds, created_plugins=created,
                       plugin_command=bool(plugin_command),
                       persisted=bool(reply_saved))
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "chat", f"发送异常: {type(exc).__name__}: {exc}")
            extra = {}
            try:
                if session is not None:
                    extra = {"session_id": session.id, "session": self._dump(session)}
                    # 兜底：异常路径也尽量把报错落盘（用户消息已写过盘的话，对话就完整了）
                    try:
                        if store is not None and session.messages:
                            error_text = (f"发送异常：{type(exc).__name__}: {exc}")
                            self._persist_message(store, session, "assistant",
                                                  error_text, {"error": True})
                            extra = {"session_id": session.id,
                                     "session": self._dump(session)}
                    except Exception:
                        pass
            except Exception:
                extra = {}
            return _fail(exc, **extra)

    # ---------- 输入框润色按钮 ----------
    # 需求：GCP-AI 输入框最右侧、发送键左边放一个 AI 图标按钮，对当前输入做润色；
    #   设置 → GCP-AI 里可关，关掉后按钮消失。
    # 设计取舍：
    #   · **不走 ai.send**、不落盘到历史对话：用户只是想把这句话说顺，不是一次提问；
    #   · 只改措辞，不回答、不推荐资源、不新增事实（避免模型"抢答"）；
    #   · 失败返回 ok:false + error，前端 toast 提示，绝不假装成功；
    #   · 用同步非流式请求（js_api 在工作线程里跑，不会卡界面）。
    POLISH_SYSTEM_PROMPT = (
        "你是 ToolsGCP 内 GCP-AI 输入框的「文本润色助手」。"
        "用户会给你一句他准备发给 AI 的话，请把它改写得更有条理、更清晰、更具体。"
        "硬性要求：保留原意与原有信息，不添加新的事实、链接、资源名称或结论；"
        "不要回答问题、不要推荐软件、不要解释你在做什么；"
        "只输出润色后的文本本身，不要引号、不要 Markdown、不要“润色后：”之类的前缀；"
        "如果原句已经通顺，就做最小改动；用原句的语言输出。"
    )

    @staticmethod
    def _clean_polished(text: str) -> str:
        """清掉模型偶尔带出来的包装（代码块/引号/前缀），只留润色后的正文"""
        value = str(text or "").strip()
        if not value:
            return ""
        # ```...``` 代码块
        if value.startswith("```"):
            value = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", value)
            value = re.sub(r"\s*```$", "", value).strip()
        # 常见前缀（模型很喜欢加）
        value = re.sub(r"^(润色(后|结果|版本)?\s*[：:]\s*)", "", value)
        value = re.sub(r"^(polished(\s+text)?\s*[：:]\s*)", "", value, flags=re.I)
        # 成对包裹的引号/书名号（只剥一层）
        pairs = (('"', '"'), ("'", "'"), ("“", "”"), ("「", "」"), ("『", "』"))
        for left, right in pairs:
            if len(value) >= 2 and value.startswith(left) and value.endswith(right):
                inner = value[len(left):len(value) - len(right)].strip()
                if inner:
                    value = inner
                break
        return value.strip()

    def polish(self, text: str = ""):
        """润色输入框文本：返回 `{ok:true, text, original}` / `{ok:false, error}`
        ⚠️ 不落盘、不创建会话；没有配置 Key/模型时直接给出可读原因（前端 toast）。
        """
        content = str(text or "").strip()
        if not content:
            return _fail("输入框是空的，没有可润色的内容")
        if len(content) > 6000:
            return _fail("这段话太长了（超过 6000 字），先缩短一点再润色")
        try:
            from pymodels.core.ai import client as ai_client
            manager = self.settings_manager
            api_key = ""
            if manager is not None:
                try:
                    api_key = manager.get_api_key() or ""
                except Exception as exc:                  # noqa: BLE001
                    _log("warn", "AI", "polish", f"读取 API Key 失败: {exc}")
            model = str(self._setting("model_name", "") or "").strip()
            # ⚠️ 同 send：发送前把界面显示名解析成官方 API 模型名
            try:
                from pymodels.core.ai import providers as ai_providers
                pid = str(self._setting("ai_provider", "deepseek")
                          or "deepseek").strip().lower()
                model = ai_providers.resolve_api_model(pid, model)
            except Exception:                              # noqa: BLE001
                pass
            api_base = str(self._setting("api_base", "") or "").strip()
            missing = []
            if not api_key:
                missing.append("API Key")
            if not model:
                missing.append("模型名称")
            if missing:
                return _fail("还没有配置" + " 和 ".join(missing) + "，先在设置里填好再润色",
                             kind="no_key", missing=missing)
            max_tokens = 0
            if bool(self._setting("limit_token_output", False)):
                try:
                    max_tokens = int(str(self._setting("max_token", "") or 0) or 0)
                except Exception:
                    max_tokens = 0
            messages = [
                {"role": "system", "content": self.POLISH_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ]
            result = ai_client.chat(messages, api_key, model, api_base,
                                    max_tokens=max_tokens, temperature=0.3)
            if not getattr(result, "ok", False):
                message = getattr(result, "message", "") or "润色请求失败"
                _log("warn", "AI", "polish",
                     f"润色失败 kind={getattr(result, 'kind', '')} {message}")
                return _fail(message, kind=getattr(result, "kind", ""))
            polished = self._clean_polished(str(getattr(result, "content", "") or ""))
            if not polished:
                return _fail("模型没有返回可用的润色结果，请再试一次")
            _log("op", "AI", "polish",
                 f"润色完成：{len(content)} 字 → {len(polished)} 字")
            return _ok(text=polished, original=content)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "polish", f"润色异常: {type(exc).__name__}: {exc}")
            return _fail(exc)

    # ---------- 测试连接（设置页「测试连接」按钮） ----------
    def test_connection(self, provider: str = "", model: str = "",
                        api_base: str = "", api_key: str = ""):
        """用当前（或设置页草稿里的）配置发一次最小请求，验证 Key/模型/地址能不能用。
        参数为空时回退到已保存的设置；前端在「测试连接」前会先把草稿传进来，
        这样测的就是“用户马上要保存的”那套配置，而不是落盘后再测。
        返回：`{ok, kind, message, status, model, api_base, provider, key_tail, latency_ms}`
        只回 Key 尾号，绝不回传明文。
        """
        try:
            from pymodels.core.ai import client as ai_client
            manager = self.settings_manager
            pid = str(provider or "").strip().lower() \
                or str(self._setting("ai_provider", "deepseek") or "deepseek").strip().lower()
            model = str(model or "").strip() or str(self._setting("model_name", "") or "").strip()
            display_model = model          # 界面显示名（返回给前端用，不发给 API）
            # ⚠️ 同 send：测试连接发送前把界面显示名解析成官方 API 模型名
            try:
                from pymodels.core.ai import providers as ai_providers
                model = ai_providers.resolve_api_model(pid, model)
            except Exception:                              # noqa: BLE001
                pass
            base = str(api_base or "").strip() or str(self._setting("api_base", "") or "").strip()
            key = str(api_key or "").strip() \
                or (manager.get_api_key(pid) if manager is not None else "")
            missing = []
            if not key:
                missing.append("API Key")
            if not model:
                missing.append("模型名称")
            if missing:
                return _fail("还没有配置" + " 和 ".join(missing)
                             + "，先在设置里填好再测",
                             kind="no_key", provider=pid, model=display_model,
                             api_base=base or ai_client.DEFAULT_API_BASE,
                             key_tail="", latency_ms=0)
            start = time.time()
            result = ai_client.chat(
                [{"role": "user", "content": "ping"}], key, model, base,
                max_tokens=1, temperature=0, timeout=30)
            latency_ms = int((time.time() - start) * 1000)
            tail = ("****" + key[-4:]) if len(key) >= 4 else ("*" * len(key))
            base_used = ai_client.normalize_api_base(base)
            if not getattr(result, "ok", False):
                return _fail(getattr(result, "message", "") or "请求失败",
                             kind=getattr(result, "kind", "") or "",
                             status=getattr(result, "status", 0),
                             model=display_model, api_base=base_used, provider=pid,
                             key_tail=tail, latency_ms=latency_ms)
            return _ok(kind="ok", message="连接正常",
                       status=getattr(result, "status", 200),
                       model=display_model, api_base=base_used, provider=pid,
                       key_tail=tail, latency_ms=latency_ms)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "test", f"测试连接异常: {type(exc).__name__}: {exc}")
            return _fail(exc, latency_ms=0)

    @staticmethod
    def _message_view(m) -> dict:
        """给前端的一条消息（历史还原用）：
        ⚠️ 报错气泡必须带 error/kind，前端才能把它画成“报错样式”，
           并且 prompt 组装上下文时后端靠 error 字段跳过它。
        """
        return {"role": m.get("role"), "content": m.get("content"),
                "ts": m.get("ts", ""),
                "error": bool(m.get("error")), "kind": m.get("kind", "")}

    @staticmethod
    def _dump(session) -> dict:
        return {"id": session.id, "title": session.title,
                "created_at": session.created_at, "updated_at": session.updated_at,
                "messages": [AiDomain._message_view(m) for m in (session.messages or [])]}

    def provider_models(self, provider: str = ""):
        """某个服务商的模型候选（设置页"刷新模型列表"用；纯本地表，不联网）"""
        try:
            from pymodels.core.ai import providers as ai_providers
            pid = str(provider or "").strip() or self._setting("ai_provider", "deepseek")
            return _ok(provider=pid, models=ai_providers.models_of(pid),
                       api_base=ai_providers.default_api_base(pid),
                       model=ai_providers.default_model(pid))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def info(self):
        """自检用：会话目录、会话数、是否配了 key（不回传明文）
        ⚠️ `chats_dir` 用 **store 自己算出来的目录**（而不是直接甩模块常量）：
           排查"历史不存储"时这两个值必须对得上；store 被指到别处（迁移 / 改数据根 /
           测试）也要如实反映。取不到才退回常量。
        """
        try:
            from pymodels.constants import CHATS_DIR
            store = self.store
            chats_dir = str(getattr(store, "chats_dir", "") or CHATS_DIR)
            manager = self.settings_manager
            provider = str(self._setting("ai_provider", "deepseek") or "deepseek").strip().lower()
            configured = bool(manager and manager.get_api_key(provider))
            key_tail = manager.key_tail(provider) if manager is not None else ""
            return _ok(app=APP_NAME, version=APP_VERSION, chats_dir=chats_dir,
                       dir_exists=bool(os.path.isdir(chats_dir)),
                       sessions=len(store.list_sessions()),
                       provider=provider, model_name=self._setting("model_name", ""),
                       api_base=self._setting("api_base", ""),
                       configured=configured, key_tail=key_tail,
                       ts=time.time())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    # ---------- 插件配置界面用的 Agent 状态（：把 py 版配置页搬到 Web） ----------
    # 背景：GCP-AI Agent 的配置页里有更多模块最近动作统计三大块，
    # 数据源是 pymodels.core.ai.agent_runtime.AgentBridge。Web 版之前没有把这层
    # 暴露给前端，插件 config.html 只能显示一个总开关（用户说的"空壳 UI"）。
    # 这里把 AgentBridge 的只读/开关能力按 JSON 信封暴露出去；AgentBridge 本身
    # 只依赖 window 上的 settings_manager / language_manager / plugin_manager，
    # 缺失的（plugin_manager）它会自己按"插件没被停用"处理，不会抛。
    def _agent_bridge(self):
        from pymodels.core.ai.agent_runtime import get_bridge
        return get_bridge(self._shell)

    def agent_state(self):
        """Agent 配置页一次拉全：开关 / 全部模块 / 统计 / 最近动作"""
        try:
            bridge = self._agent_bridge()
            return _ok(enabled=bool(bridge.enabled()),
                       setting_on=bool(bridge.setting_on()),
                       tools=bridge.tools(),
                       stats=bridge.stats(),
                       actions=bridge.recent_actions(20),
                       language=self._language())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def set_agent_enabled(self, on: bool = False):
        """Agent 总开关（和设置里的 gcp_ai_agent_enabled 是同一个键）
        联动（和前端 saveSetting / togglePlugin 同一口径）：关闭 AI Agent 时
        **一并关闭插件制作辅助**；启用制作辅助 → Agent 由前端 manifest.companion 带开。
        """
        try:
            bridge = self._agent_bridge()
            on = bool(on)
            bridge.set_enabled(on)
            if not on:
                manager = self.settings_manager
                if manager is not None:
                    try:
                        if bool(manager.settings.get("gcp_plugin_maker_enabled", False)):
                            manager.update_setting("gcp_plugin_maker_enabled", False)
                            try:
                                self._shell.push_event("settings-changed",
                                    {"key": "gcp_plugin_maker_enabled", "new": False})
                            except Exception:
                                pass
                    except Exception as exc:                  # noqa: BLE001
                        _log("warn", "AI", "agent",
                             f"关闭 Agent 时同步关闭插件制作辅助失败: {exc}")
            return _ok(enabled=bool(bridge.setting_on()))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def set_agent_tool(self, name: str = "", on: bool = False):
        """打开/关掉某一项手；关掉的会写进 gcp_ai_agent_tools_off"""
        try:
            bridge = self._agent_bridge()
            bridge.set_tool_on(str(name or ""), bool(on))
            return _ok(tools=bridge.tools())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def set_all_agent_tools(self, on: bool = False):
        """一键全开 / 全关（配置页更多模块的总控）"""
        try:
            bridge = self._agent_bridge()
            bridge.set_all_tools_on(bool(on))
            return _ok(tools=bridge.tools())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def clear_agent_actions(self):
        """清空最近动作"""
        try:
            bridge = self._agent_bridge()
            bridge.clear_actions()
            return _ok(actions=bridge.recent_actions(20))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)
