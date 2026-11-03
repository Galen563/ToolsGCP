"""多语言系统

文案放在 lang/<locale>.json（zh_CN / zh_TW / en_US），平铺的键值对；带 {占位符} 的用
t("key", name="x") 替换。找不到当前语言的键时依次回退 zh_CN → en_US → 键名本身。

⚠️ 三种语言的键必须完全一致：zh_CN 是兜底语言，某个键只在 zh_CN 里有的话，英文用户
   看到的就是中文。
"""

import json
import os

# 回退顺序
FALLBACK_ORDER = ["zh_CN", "en_US"]

# 插件自带的三种语言（＝ lang/ 下的三个文件名）。
# ⚠️ 宿主有些接口要的是**多语言字典**而不是一句当前语言的文案：聊天提示的
#    label / prompt、AI 工具的 description。它自己按用户当前语言挑一条，
#    所以插件必须把三份都递过去（见 locale_dict）。
LANG_LOCALES = ["zh_CN", "zh_TW", "en_US"]


class I18n:
    """插件文案翻译器"""

    def __init__(self, plugin_dir: str, locale: str = "zh_CN", lang_dir: str = "lang"):
        self.lang_dir = os.path.join(plugin_dir, lang_dir)
        self.locale = locale or "zh_CN"
        self._cache = {}

    def _load(self, locale: str) -> dict:
        if locale in self._cache:
            return self._cache[locale]
        path = os.path.join(self.lang_dir, f"{locale}.json")
        data = {}
        if os.path.exists(path):
            try:
                # utf-8-sig：兼容带 BOM 的文件
                with open(path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        self._cache[locale] = data
        return data

    def available_locales(self) -> list:
        """lang/ 目录里都有哪些语言"""
        if not os.path.isdir(self.lang_dir):
            return []
        return sorted(fn[:-5] for fn in os.listdir(self.lang_dir)
                      if fn.endswith(".json"))

    def t(self, key: str, **kwargs) -> str:
        """取一条文案；带 {占位符} 的话用 kwargs 替换

        ⚠️ 只对模板做 format：填进去的值里带 {} 也不会再被解析一遍。
        """
        text = self._find(key)
        if kwargs and isinstance(text, str):
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    def _find(self, key: str) -> str:
        for locale in [self.locale] + [x for x in FALLBACK_ORDER if x != self.locale]:
            value = self._load(locale).get(key)
            if value:
                return str(value)
        return key

    def all(self) -> dict:
        """当前语言的完整文案表（想整体遍历时用）"""
        merged = {}
        for locale in reversed([self.locale] + FALLBACK_ORDER):
            merged.update(self._load(locale))
        return merged

    def locale_dict(self, key: str) -> dict:
        """把一条文案取成 {zh_CN: ..., zh_TW: ..., en_US: ...} 三语言字典

        宿主的 register_chat_hint / register_ai_tool 要的就是这种字典，
        它按用户当前语言自己挑一条，插件不用管现在是什么语言。

        ⚠️ 三个键一定都在、都不是空串：某一语言缺这条文案就退回当前语言的取法，
           免得宿主拿到空字典直接判定"这条提示无效"而拒绝注册。
        """
        result = {}
        for locale in LANG_LOCALES:
            text = ""
            try:
                text = str(self._load(locale).get(key) or "")
            except Exception:
                text = ""
            result[locale] = text or self.t(key)
        return result
