"""语言管理模块：按语言目录加载 languages/<locale>/<module>.json，按当前语言提供文案。
========== 语言目录结构（v1.1.4 起）==========
    .ToolsGCP/modules/languages/
    ├─ zh_CN/  <module>_language.json   简体中文
    ├─ zh_TW/  <module>_language.json   繁體中文
    └─ en_US/  <module>_language.json   English
每个 json 只有**一种语言**，内容是扁平字符串字典：{"tip_success": "Success"}。
（老版本是 languages/ 根目录下 15 个三语混合 json：{"tip_success": {"简体中文": …, "English": …}}，
 新结构不再混合，三种语言各放各的目录。）
拆分规则（当时一次性迁移完成，生成脚本按约定没有留在仓库里）：
    1. zh_CN 取原 "简体中文" 列；zh_TW 取 "繁體中文"；en_US 取 "English"。
    2. 某语言在源文件里缺失/为空 → 用**简体中文**的值兜底，保证三套文件 key 集合一致。
    3. 连简体中文都没有的 key → 整条跳过（三套文件都不写）。
    4. 文件名保持不变（search_language.json / set_language.json …），只是从根目录挪进语言目录。
    5. 隐私协议/用户协议全文等长文 key 不再落地（用户改成跳官网链接）。
取值回退链（LanguageManager.get_text）：
    当前语言 → zh_CN → en_fallback.EN_FALLBACK（内嵌英文）→ 返回 key 本身。
"""

import json
import os

from ..constants import LANGUAGES_DIR, CONFIG_DIR

# 内嵌英文兜底表（内容由 en_US/*.json 汇总而来，见 core/en_fallback.py 开头的说明）
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


# ========== 语言名 / 语言目录 ==========

# 三套语言各占一个目录，目录名就是 locale
LOCALES = ("zh_CN", "zh_TW", "en_US")

# 语言名 → 目录名。设置里/界面上存的一直是简体中文 / 繁體中文 / English，
# 目录名是新的，所以**全程序只维护这一份映射**，desktop/api 的 I18nDomain
# 直接 import 它（不要在那里再写一份，写歪了两边就取不到同一套文案）。
LANGUAGE_TO_LOCALE = {
    "简体中文": "zh_CN", "简体": "zh_CN", "zh_CN": "zh_CN", "zh-CN": "zh_CN", "zh_cn": "zh_CN",
    "繁體中文": "zh_TW", "繁体中文": "zh_TW", "zh_TW": "zh_TW", "zh-TW": "zh_TW", "zh_tw": "zh_TW",
    "English": "en_US", "en_US": "en_US", "en-US": "en_US", "en_us": "en_US",
}

# 目录名 → 标准语言名
LOCALE_TO_LANGUAGE = {"zh_CN": "简体中文", "zh_TW": "繁體中文", "en_US": "English"}

DEFAULT_LOCALE = "zh_CN"
DEFAULT_LANGUAGE = "简体中文"


def locale_for(language) -> str:
    """语言名 / 目录名 → locale 目录名；认不出来按简体中文（回退链的终点）"""
    text = str(language or "").strip()
    if not text:
        return DEFAULT_LOCALE
    if text in LANGUAGE_TO_LOCALE:
        return LANGUAGE_TO_LOCALE[text]
    normalized = text.lower().replace("-", "_")
    for name, locale in LANGUAGE_TO_LOCALE.items():
        if name.lower().replace("-", "_") == normalized:
            return locale
    return DEFAULT_LOCALE


def normalize_language(language) -> str:
    """任意写法 → 标准语言名（current_language 只存这三个之一）"""
    return LOCALE_TO_LANGUAGE[locale_for(language)]


# 模块 → 文件名（文件名沿用老版本，只是挪进了语言子目录）
# ⚠️ 新增语言模块要同时登记在这里 + I18nDomain.FILES（desktop 那一层给前端下发用）。
MODULE_FILES = {
    "search": "search_language.json",
    "notice": "notice_language.json",
    "tools_gcp": "ToolsGCPcenter_language.json",
    "deploy": "deploy_language.json",
    "github": "github_language.json",
    "settings": "set_language.json",
    "log": "log_language.json",
    "feedback": "feedback_language.json",
    "nav": "nav_language.json",
    "privacy": "privacy_language.json",
    "plugin": "plugin_language.json",
    "maker": "maker_language.json",
    "customize": "customize_language.json",
    # common：InfoBar 的四个标题 + 资源库类别/标签/适用系统/架构的显示译名
    "common": "common_language.json",
}


# ========== 全程序的"小词"（InfoBar 标题 / 资源库术语）==========
# 只需要一张扁平译名表，现在放在 common_language.json 里（三个语言目录各一份）。

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
    ⚠️ 每 new 一个都会重新读三套 json（一共几十 KB，很快），所以全程序只应有一个实例
    （主窗口建的），别的模块通过 get_current_manager() 拿它，别自己 new 一个空壳。
    数据结构：
        self.translations = {locale: {module: {key: 文案}}}
    三种语言在启动时**一起**载入，切语言只改 current_language，不用重新读盘。
    """

    def __init__(self, config_dir=None):
        # 语言文件是"随程序发布"的资源，固定跟程序目录走（constants.LANGUAGES_DIR）；
        # config_dir 只为测试保留（临时造一套语言目录），行为与老版本一致：
        # <config_dir>/modules/languages。
        self.config_dir = config_dir or CONFIG_DIR
        if config_dir:
            self.languages_dir = os.path.join(config_dir, "modules", "languages")
        else:
            self.languages_dir = LANGUAGES_DIR
        self.current_language = DEFAULT_LANGUAGE
        self.translations = {locale: {} for locale in LOCALES}
        self.load_all_languages()
        set_current_manager(self)

    # ---------- 加载 ----------
    def load_all_languages(self):
        """读三套语言目录：translations[locale][module] = {key: 文案}"""
        translations = {locale: {} for locale in LOCALES}
        for locale in LOCALES:
            locale_dir = os.path.join(self.languages_dir, locale)
            if not os.path.isdir(locale_dir):
                self._log_warn(f"语言目录不存在: {locale_dir}（该语言只能走 en_fallback）")
                continue
            missing = []
            for module, filename in MODULE_FILES.items():
                filepath = os.path.join(locale_dir, filename)
                entry = {}
                if not os.path.isfile(filepath):
                    missing.append(filename)
                else:
                    try:
                        with open(filepath, "r", encoding="utf-8") as handle:
                            raw = json.load(handle)
                        if isinstance(raw, dict):
                            # 新结构是扁平字符串字典；万一有人写回三语混合结构，
                            # 这里会跳过 dict 值（宁可走 en_fallback，也不把 dict 塞给界面）
                            entry = {str(key): str(value)
                                     for key, value in raw.items() if isinstance(value, str)}
                        else:
                            self._log_warn(f"语言文件结构不是扁平字典: {filepath}")
                    except Exception as exc:              # noqa: BLE001
                        self._log_err(f"加载语言文件失败 {filepath}: {exc}")
                translations[locale][module] = entry
            if missing:
                # 一个语言目录缺好几个文件时只报一条，别刷屏（正常发布不会缺）
                self._log_warn(f"{locale} 缺 {len(missing)} 个语言文件: {', '.join(missing)}")
        self.translations = translations

    # ---------- 取词 ----------
    def get_text(self, module, key, language=None):
        """取一条文案：当前语言 → 简体中文 → en_fallback 英文 → key 本身
        ⚠️ 判断"有没有这条 key"看键在不在、值是不是非空字符串，不能看
           "取出来的文字等不等于 key"：maker 里有上百条 key 本身就是中文原文，
           两者相等会被误判成没找到（老版本踩过这个坑）。
        """
        if language is None:
            language = self.current_language
        locale = locale_for(language)
        # 回退链：该语言 → 简体中文。拆分时已经用简体中文补过缺失值的空白，
        # 这里再兜一次，覆盖"整个文件缺失 / 中间有人手工删了 key"的极端情况。
        candidates = (locale,) if locale == DEFAULT_LOCALE else (locale, DEFAULT_LOCALE)
        for candidate in candidates:
            text = self.translations.get(candidate, {}).get(module, {}).get(key)
            if isinstance(text, str) and text:
                return text
        # 三套语言文件都没有这条 key → 内嵌英文兜底（再没有才返回 key 本身，方便排查）
        # ⚠️ 按**模块**查：不同模块会复用同名 key 但占位符不同（见 en_fallback.py 开头）
        return EN_FALLBACK.get(module, {}).get(key, key)

    def locale(self, language=None) -> str:
        """当前（或指定）语言对应的目录名，给 I18nDomain / 前端 lang 属性用"""
        if language is None:
            language = self.current_language
        return locale_for(language)

    def toast_title(self, kind: str = "info") -> str:
        """InfoBar 的标题（成功 / 错误 / 提示 / 信息），按当前语言（统一从 common 模块取）"""
        return get_toast_title(kind, self)

    def term(self, value: str) -> str:
        """资源库里的"类别 / 标签 / 适用系统 / CPU 架构"显示译名（存盘值不变）"""
        return translate_term(value, self)

    # ---------- 切换 ----------
    def set_language(self, language):
        """设置当前语言（三套已预载，只切指针，不需要 reload）
        ⚠️ 统一存标准语言名（简体中文/繁體中文/English）：plugin_manager 会拿
           current_language 去比插件 manifest 里的语言键，存成 "zh_CN" 就匹配不上。
        """
        self.current_language = normalize_language(language)

    def reload(self):
        """重新读三套语言目录（改语言文件后热更新用）"""
        self.load_all_languages()

    # ---------- 日志（延迟导入，避免与 logger 成环） ----------
    @staticmethod
    def _log_warn(message: str):
        try:
            from ..utils.logger import log
            log.warn("语言", "language", message)
        except Exception:
            pass

    @staticmethod
    def _log_err(message: str):
        try:
            from ..utils.logger import log
            log.err("语言", "language", message)
        except Exception:
            pass
