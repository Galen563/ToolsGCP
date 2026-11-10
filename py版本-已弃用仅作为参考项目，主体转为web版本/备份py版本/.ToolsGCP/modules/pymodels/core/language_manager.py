"""语言管理模块：加载 languages/*.json，按当前语言提供文案。"""

import json
import os
from ..constants import LANGUAGES_DIR, CONFIG_DIR

# 内嵌英文兜底表（自动生成，见 core/en_fallback.py 开头的说明）
from .en_fallback import EN_FALLBACK


# 全程序唯一的"当前语言管理器"
_current_manager = None


def set_current_manager(manager):
    """登记当前语言管理器（LanguageManager.__init__ 会自动调）"""
    global _current_manager
    _current_manager = manager


def get_current_manager():
    """拿当前语言管理器（可能还没有，返回 None）"""
    return _current_manager


# ========== 全程序的"小词"（InfoBar 标题 / 资源库术语）==========
# 只需要一张扁平译名表，放在 common_language.json 里。

# 提示条类型 -> common 模块里的 key
_TOAST_KEYS = {
    "success": "tip_success",
    "error": "tip_error",
    "warning": "tip_warning",
    "info": "tip_info",
}

# 语言文件整个缺失时的英文兜底（和 get_text 的兜底口径一致）
_TOAST_EN = {
    "success": "Success",
    "error": "Error",
    "warning": "Notice",
    "info": "Info",
}


def get_toast_title(kind: str = "info", manager=None) -> str:
    """InfoBar 的标题（成功 / 错误 / 提示 / 信息），按当前语言

    没有语言管理器的独立控件（如日志窗口）也能直接调。
    """
    kind = str(kind or "info").strip().lower()
    key = _TOAST_KEYS.get(kind, _TOAST_KEYS["info"])
    if manager is None:
        manager = _current_manager
    if manager is not None:
        try:
            text = manager.get_text("common", key)
        except Exception:
            text = ""
        if text and text != key:
            return str(text)
    return _TOAST_EN.get(kind, _TOAST_EN["info"])


def translate_term(value: str, manager=None) -> str:
    """资源库里"类别 / 标签 / 适用系统 / CPU 架构"的显示译名

    ⚠️ 只改显示：存盘、筛选、收藏夹、部署清单匹配用的仍是磁盘上那个规范值。
    查不到译名（用户自己输入的新类别）时原样返回，绝不吞掉。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if manager is None:
        manager = _current_manager
    if manager is None:
        return text
    key = f"term_{text}"
    try:
        translated = manager.get_text("common", key)
    except Exception:
        return text
    if translated and translated != key:
        return str(translated)
    return text


class LanguageManager:
    """语言管理器

    ⚠️ 每 new 一个都会重新读一遍所有 json，所以全程序只应有一个实例（主窗口建的），
    别的模块通过 get_current_manager() 拿它，别自己 new 一个空壳。
    """
    
    def __init__(self, config_dir=None):
        if config_dir is None:
            config_dir = CONFIG_DIR
        self.config_dir = config_dir
        self.languages_dir = os.path.join(config_dir, "modules", "languages")
        self.current_language = "简体中文"
        self.translations = {}
        self.load_all_languages()
        set_current_manager(self)
    
    def load_all_languages(self):
        """加载所有语言文件"""
        language_files = {
            "search": "search_language.json",
            "home": "home_language.json",
            "notice": "notice_language.json",
            "tools_gcp": "ToolsGCPcenter_language.json",
            "deploy": "deploy_language.json",
            "github": "github_language.json",
            "settings": "set_language.json",
            "log": "log_language.json",
            "feedback": "feedback_language.json",
            "nav": "nav_language.json",
            "privacy": "privacy_language.json",
            # ⚠️ 新增模块也要登记在这里，否则 get_text 找不到文件，只能退回代码里的兜底文案
            "plugin": "plugin_language.json",
            "maker": "maker_language.json",
            "customize": "customize_language.json",
            # common：InfoBar 的四个标题 + 资源库类别/标签/适用系统/架构的显示译名
            "common": "common_language.json",
        }
        
        for module, filename in language_files.items():
            filepath = os.path.join(self.languages_dir, filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        self.translations[module] = json.load(f)
                except Exception as e:
                    from ..utils.logger import log
                    log.err("语言", "language", f"加载语言文件失败 {filename}: {e}")
                    self.translations[module] = {}
            else:
                from ..utils.logger import log
                log.warn("语言", "language", f"语言文件不存在: {filepath}")
                self.translations[module] = {}
    
    def get_text(self, module, key, language=None):
        """获取指定语言文本

        ⚠️ 语言文件缺失 / 没有这条 key 时返回内嵌英文（EN_FALLBACK），不是 key 名。
        ⚠️ 判断"有没有这条 key"看键在不在，不能看"取出来的文字等不等于 key"：
        maker_language.json 里有上百条 key 本身就是中文原文，两者相等会被误判成没找到。
        """
        if language is None:
            language = self.current_language

        entry = None
        if module in self.translations:
            entry = self.translations[module].get(key)
        if isinstance(entry, dict):
            text = entry.get(language) or entry.get("简体中文")
            if text:
                return text

        # 语言文件里没有这条 key → 英文兜底（查不到才返回 key 本身，方便排查）
        # ⚠️ 按**模块**查：不同模块会复用同名 key 但占位符不同（见 en_fallback.py 开头）
        return EN_FALLBACK.get(module, {}).get(key, key)
    
    def toast_title(self, kind: str = "info") -> str:
        """InfoBar 的标题（成功 / 错误 / 提示 / 信息），按当前语言（统一从 common 模块取）"""
        return get_toast_title(kind, self)

    def term(self, value: str) -> str:
        """资源库里的"类别 / 标签 / 适用系统 / CPU 架构"显示译名（存盘值不变）"""
        return translate_term(value, self)

    def set_language(self, language):
        """设置当前语言"""
        self.current_language = language
    
    def reload(self):
        """重新加载语言文件"""
        self.load_all_languages()