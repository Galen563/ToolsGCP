"""聊天输入框上方的"悬浮提示 + 命令"注册表。
插件或主程序用 register() 登记一条提示；界面在输入框上方画一条等宽圆角小条列出它们，
点一下把 insert 填进输入框；消息以某条 insert 开头时，把对应 prompt 追加进本次 system。
⚠️ 纯数据、不认识 Qt，所以放 core 而不是 ui（插件 import ui 会引入循环导入与打包问题）。
"""

import time

# 语言 → locale（和 agent_tools 保持一致）
LANGUAGE_TO_LOCALE = {
    "简体中文": "zh_CN",
    "繁體中文": "zh_TW",
    "English": "en_US",
}
DEFAULT_LOCALE = "zh_CN"


def _pick(text, locale: str) -> str:
    """多语言字段取值（dict → 按 locale 取，依次回退 zh_CN / en_US）"""
    if isinstance(text, dict):
        for key in (locale, "zh_CN", "en_US"):
            value = text.get(key)
            if value:
                return str(value)
        return ""
    return str(text or "")


class ChatHint:
    """一条输入框上方的提示（同时也可以是一条"命令"）"""

    __slots__ = ("id", "label", "insert", "prompt", "priority", "source", "_stamp")

    def __init__(self, hint_id: str, label, insert: str = "",
                 prompt="", priority: int = 0, source: str = ""):
        self.id = str(hint_id or "").strip()
        self.label = label
        self.insert = str(insert or "").strip()
        self.prompt = prompt
        self.priority = int(priority or 0)
        # 登记它的插件 id，主界面据此判断插件是否还开着
        self.source = str(source or "").strip()
        self._stamp = time.time()

    def label_for(self, locale: str = DEFAULT_LOCALE) -> str:
        return _pick(self.label, locale)

    def prompt_for(self, locale: str = DEFAULT_LOCALE) -> str:
        return _pick(self.prompt, locale)

    def matches(self, text: str) -> bool:
        """这条提示的命令是不是被用上了（消息开头就是它）
        ⚠️ 大小写不敏感，且只在开头匹配：正文里提到 "/plugin" 不算命令。
        """
        if not self.insert:
            return False
        line = str(text or "").lstrip()
        return line.lower().startswith(self.insert.lower())

    def signature(self):
        return (self.id, _pick(self.label, "zh_CN"), self.insert,
                self.priority, self.source, self._stamp)

    def to_dict(self, locale: str = DEFAULT_LOCALE) -> dict:
        return {"id": self.id, "label": self.label_for(locale),
                "insert": self.insert, "priority": self.priority,
                "source": self.source}


class ChatHintRegistry:
    """提示注册表（进程内单例，见 get_hint_registry）"""

    def __init__(self):
        self._hints = {}
        self._version = 0        # 每次变动 +1，界面据此决定要不要重画

    # ---------- 注册 ----------
    def register(self, hint_id: str, label, insert: str = "",
                 prompt="", priority: int = 0, source: str = "") -> bool:
        hint = ChatHint(hint_id, label, insert, prompt, priority, source)
        if not hint.id or not hint.label_for(DEFAULT_LOCALE):
            return False
        self._hints[hint.id] = hint
        self._version += 1
        return True

    def unregister(self, hint_id: str) -> bool:
        gone = self._hints.pop(str(hint_id or ""), None) is not None
        if gone:
            self._version += 1
        return gone

    def unregister_prefix(self, prefix: str) -> int:
        """批量卸掉（插件停用时用；按 id 前缀匹配）"""
        prefix = str(prefix or "")
        doomed = [k for k in self._hints if k.startswith(prefix)]
        for key in doomed:
            self._hints.pop(key, None)
        if doomed:
            self._version += 1
        return len(doomed)

    def clear(self):
        self._hints.clear()
        self._version += 1

    # ---------- 查询 ----------
    @property
    def version(self) -> int:
        return self._version

    def all(self) -> list:
        return sorted(self._hints.values(), key=lambda h: (-h.priority, h.id))

    def count(self) -> int:
        return len(self._hints)

    def to_dicts(self, locale: str = DEFAULT_LOCALE) -> list:
        return [h.to_dict(locale) for h in self.all()]

    def matching(self, text: str):
        """消息命中的提示（没有就返回 None）"""
        for hint in self.all():
            if hint.matches(text):
                return hint
        return None

    def prompt_for_text(self, text: str, locale: str = DEFAULT_LOCALE) -> str:
        """这条消息要不要额外带一段 system 指令（返回空串 = 不带）"""
        hint = self.matching(text)
        return hint.prompt_for(locale) if hint is not None else ""


_registry = None


def get_hint_registry() -> ChatHintRegistry:
    global _registry
    if _registry is None:
        _registry = ChatHintRegistry()
    return _registry


def locale_of(language: str) -> str:
    return LANGUAGE_TO_LOCALE.get(str(language or ""), DEFAULT_LOCALE)


__all__ = ["ChatHint", "ChatHintRegistry", "get_hint_registry", "locale_of"]
