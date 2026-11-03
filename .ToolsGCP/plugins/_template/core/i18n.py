"""多语言系统
文案放在 lang/<locale>.json（zh_CN / zh_TW / en_US），平铺的键值对；
带 {占位符} 的用 i18n.t("hello", name="小明") 替换。
找不到当前语言的键时依次回退 zh_CN → en_US → 键名本身。
"""

import json
import os

# 回退顺序
FALLBACK_ORDER = ["zh_CN", "en_US"]


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
        """取一条文案；带 {占位符} 的话用 kwargs 替换"""
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
