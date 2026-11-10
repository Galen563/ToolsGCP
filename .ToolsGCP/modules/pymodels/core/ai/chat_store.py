"""GCP-AI 的历史对话存储：每个会话一个 json，放在 .ToolsGCP/config/chats/ 下。
⚠️ 新会话不立刻落盘（发出第一条消息才写），写盘用临时文件 + os.replace 原子替换，
否则写到一半被杀会留下半个 JSON。文件名只用数字和短横线，真标题存在 title 字段。
用法：
    store = ChatStore()
    session = store.new_session()
    store.append(session, "user", "帮我找个局域网传文件的工具")
"""

import json
import os
import uuid
from datetime import datetime

from ..constants import CHATS_DIR

SCHEMA_VERSION = "1.0.0"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"

# 会话标题长度上限（界面上一行放不下太长的标题）
TITLE_MAX = 24
# 历史列表最多返回多少个会话（防止目录里堆了几千个文件时卡启动）
LIST_LIMIT = 200


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(action: str, **fields):
    """记录操作日志；⚠️ 必须是三个点，`..utils` 会解析成不存在的 pymodels.core.utils，
    导入失败被吞掉，关键日志一条都不落盘"""
    try:
        from ...utils.logger import log
        log.op("AI", action, **fields)
    except Exception:
        pass


class ChatSession:
    """一个会话的内存表示（状态挂在对象上，比散在 dict 里清晰）"""

    def __init__(self, data: dict = None):
        data = data if isinstance(data, dict) else {}
        self.id = str(data.get("id") or "")
        self.title = str(data.get("title") or "")
        self.created_at = str(data.get("created_at") or "") or _now()
        self.updated_at = str(data.get("updated_at") or "") or self.created_at
        self.model = str(data.get("model") or "")
        self.api_base = str(data.get("api_base") or "")
        self.messages = [m for m in (data.get("messages") or [])
                         if isinstance(m, dict) and m.get("role") in
                         (ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM)]
        # 还没产生任何一条消息的新会话，磁盘上没有对应文件
        self.dirty = not bool(self.id)

    @property
    def is_empty(self) -> bool:
        return not self.messages

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "model": self.model,
            "api_base": self.api_base,
            # ⚠️ 消息原样存盘、不筛字段：variants / variant_index 等要跟着落盘，
            #    白名单拷贝在加字段时容易漏掉，导致"此前/下一版"丢失。
            "messages": self.messages,
        }


class ChatStore:
    """会话的读写门面（面板只跟它打交道，不直接碰文件）"""

    def __init__(self, chats_dir: str = None):
        # 留参数是为了测试时能把整个 store 指到临时目录
        self.chats_dir = chats_dir or CHATS_DIR

    # ---------- 目录 ----------
    def _ensure_dir(self) -> bool:
        try:
            os.makedirs(self.chats_dir, exist_ok=True)
            return True
        except Exception as exc:
            _log("ensure_dir_failed", error=str(exc))
            return False

    def path_of(self, session_id: str) -> str:
        return os.path.join(self.chats_dir, f"{session_id}.json")

    # ---------- 新建 / 载入 ----------
    def new_session(self) -> ChatSession:
        """新建一个空会话（不落盘，等第一条消息）"""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session = ChatSession({
            "id": f"{stamp}-{uuid.uuid4().hex[:6]}",
            "created_at": _now(),
        })
        session.dirty = True     # 有 id、还没写文件 → 第一次 append 时落盘
        return session

    def load(self, session_id: str) -> ChatSession:
        """按 id 载入会话；读不到就返回 None（调用方负责兜底）"""
        path = self.path_of(session_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            # 文件坏了不抛异常，让界面继续能用
            _log("load_failed", file=os.path.basename(path), error=str(exc))
            return None
        if not isinstance(data, dict):
            return None
        session = ChatSession(data)
        session.id = session.id or session_id
        session.dirty = False
        return session

    # ---------- 保存 ----------
    def save(self, session: ChatSession) -> bool:
        """原子写盘：必须先写 xxx.tmp 再 os.replace，直接 open(path, "w") 会先把原文件
        截成 0 字节，此时崩溃/断电就整段对话没了"""
        if not self._ensure_dir():
            return False
        path = self.path_of(session.id)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            session.dirty = False
            return True
        except Exception as exc:
            _log("save_failed", file=os.path.basename(path), error=str(exc))
            # 落盘失败时清掉残留临时文件，别在 chats/ 里留垃圾
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            return False

    # ---------- 追加消息 ----------
    def append(self, session: ChatSession, role: str, content: str,
               persist: bool = True, extra: dict = None) -> bool:
        """往会话里加一条消息并落盘（persist=False 用于"先插占位气泡、等模型回完再更新"）
        ⚠️ `extra` 是消息的附加字段（如报错气泡的 `error:True, kind:'auth'`）：
           历史面板要靠它们把“报错气泡”原样还原，且 prompt 组装上下文时要跳过它们。
        """
        if role not in (ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM):
            return False
        content = str(content or "")
        if not content and role != ROLE_ASSISTANT:
            return False

        message = {"role": role, "content": content, "ts": _now()}
        if isinstance(extra, dict):
            for key, value in extra.items():
                if key not in ("role", "content", "ts"):
                    message[key] = value
        session.messages.append(message)
        session.updated_at = _now()

        # 第一条用户消息顺便当标题
        if role == ROLE_USER and not session.title:
            session.title = self._make_title(content)

        if persist:
            self.save(session)
        return True

    def replace_last(self, session: ChatSession, role: str, content: str,
                     persist: bool = True) -> bool:
        """覆盖最后一条消息（用于把"正在思考…"换成真正的回答）"""
        if not session.messages:
            return self.append(session, role, content, persist)
        if session.messages[-1].get("role") != role:
            return self.append(session, role, content, persist)
        session.messages[-1]["content"] = str(content or "")
        session.messages[-1]["ts"] = _now()
        session.updated_at = _now()
        if persist:
            self.save(session)
        return True

    # ---------- 历史列表 ----------
    def list_sessions(self) -> list:
        """列出磁盘上的历史会话（按更新时间倒序）；返回只填了元信息 + messages 的对象"""
        if not os.path.isdir(self.chats_dir):
            return []
        sessions = []
        for name in os.listdir(self.chats_dir):
            if not name.endswith(".json"):
                continue
            path = os.path.join(self.chats_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue                      # 坏文件跳过，不拦着其它会话
            if not isinstance(data, dict):
                continue
            session = ChatSession(data)
            session.id = session.id or os.path.splitext(name)[0]
            session.dirty = False
            sessions.append(session)

        # ⚠️ 时间戳只精确到秒，同一秒建的会话 updated_at 相同，只按它排序结果不确定
        # （输入顺序来自 os.listdir）。用带时间前缀的 id 兜底，最近的在最上。
        sessions.sort(key=lambda s: (s.updated_at, s.id), reverse=True)
        return sessions[:LIST_LIMIT]

    def delete(self, session_id: str) -> bool:
        """删掉一个会话文件"""
        path = self.path_of(session_id)
        try:
            if os.path.exists(path):
                os.remove(path)
                _log("delete_session", id=session_id)
            return True
        except Exception as exc:
            _log("delete_failed", id=session_id, error=str(exc))
            return False

    def clear(self) -> int:
        """清空全部历史对话，返回删掉的文件数（给设置页/调试用）"""
        count = 0
        for session in self.list_sessions():
            if self.delete(session.id):
                count += 1
        return count

    # ---------- 辅助 ----------
    @staticmethod
    def _make_title(text: str) -> str:
        """把第一句话压成一行标题（换行/连续空格压成单个空格，太长截断加省略号）"""
        line = " ".join(str(text or "").split())
        if len(line) > TITLE_MAX:
            line = line[:TITLE_MAX] + "…"
        return line or "新对话"

    def latest_session(self) -> ChatSession:
        """取最近一次会话（没有就新建一个）"""
        sessions = self.list_sessions()
        if sessions:
            loaded = self.load(sessions[0].id)
            if loaded is not None:
                return loaded
        return self.new_session()
