"""Skill 技能规则 —— 本插件的**内部组件**，不是另一个插件
这里是Skill 技能的**唯一真源**：开关有哪些、默认值是什么、生成的提示词长什么样、
要产出哪些文件，全部只写在这里。界面只负责画出开关、原样发送提示词。
⚠️ 三条约定：
1) 内部组件：不单独进插件列表、没有自己的开关界面。
2) **用户意愿永远优先**：这些规则只是默认加强项，用户明确说了别的就以用户为准，
   提示词里明写了这条优先级（先规则、后用户要求、最后声明谁说了算）。
3) 开关存在 ToolsGCP 设置里，键 `gcp_plugin_maker_options`（dict）。⚠️ constants.py
   里该键的默认值是 `{}`，所以**缺键就按这里 DEFAULTS 的默认值走** —— 两边要一起改。
开关（顺序＝界面上开关的顺序＝RULES 的顺序）：require_readme / readme_strict /
three_languages 默认开，readme_lang_zh_TW / readme_lang_en_US 默认关（README 默认只有
中文一份）。options 里还存着一个不是开关的配置 `default_language`（新插件的默认开发
语言）：它不是 bool，所以不进 DEFAULTS，由 normalize() 单独洗成 LANGUAGES 里的一员，
认不出来就 Python。
"""

# 设置里的键名（和 constants.py 对齐）
ENABLED_KEY = "gcp_plugin_maker_enabled"        # 总开关，默认 False
OPTIONS_KEY = "gcp_plugin_maker_options"        # Skill 规则开关，一个 dict

# 规则开关的默认值（界面、提示词、落盘全按它来）
# ⚠️ 只放 bool 开关：掺进一个字符串（比如开发语言）会被当成"开关"洗成 True/False。
DEFAULTS = {
    "require_readme": True,
    "readme_strict": True,
    "three_languages": True,
    "readme_lang_zh_TW": False,
    "readme_lang_en_US": False,
}

# 默认开发语言：options 里的第六个键，**不是** bool 开关（界面上是下拉框）
# 顺序就是下拉框里的顺序，认不出来一律退回 DEFAULT_LANGUAGE
LANGUAGE_KEY = "default_language"
LANGUAGES = ["Python", "JavaScript", "TypeScript", "C#", "Go", "Rust"]
DEFAULT_LANGUAGE = "Python"

# 界面上的规则清单：i18n 键 + 选项键，这里的顺序就是界面上开关的顺序。
# ⚠️ label/desc 存的是 **i18n 键**而不是文案（文案一律在 lang/*.json 里）。
RULES = [
    {"key": "require_readme", "label": "skill_require_readme",
     "desc": "skill_require_readme_desc"},
    {"key": "readme_strict", "label": "skill_readme_strict",
     "desc": "skill_readme_strict_desc"},
    {"key": "three_languages", "label": "skill_three_languages",
     "desc": "skill_three_languages_desc"},
    {"key": "readme_lang_zh_TW", "label": "skill_readme_zh_TW",
     "desc": "skill_readme_zh_TW_desc"},
    {"key": "readme_lang_en_US", "label": "skill_readme_en_US",
     "desc": "skill_readme_en_US_desc"},
]

# 支持的语言 → 语言文件里的名字（生成 lang/ 和 README 都用它）
LOCALE_NAMES = {
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
    "en_US": "English",
}
# 三套语言的固定顺序（生成 / 显示都按它）
ALL_LOCALES = ["zh_CN", "zh_TW", "en_US"]

# ⚠️ 两套名字别混：locale（zh_CN…）是 lang/<locale>.json 的**文件名**，
#    language（简体中文…）是设置里存的**值**，也是宿主 manifest 多语言字典用的键。
LOCALE_TO_LANGUAGE = {
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
    "en_US": "English",
}
LANGUAGE_TO_LOCALE = {
    "简体中文": "zh_CN",
    "繁體中文": "zh_TW",
    "English": "en_US",
}
# 用户可能写的英文名 → 也是这些取值
LANGUAGE_ALIASES = {
    "simplified chinese": "简体中文",
    "traditional chinese": "繁體中文",
    "english": "English",
}

# README 语言开关 → 额外生成的文件名
README_EXTRA = {
    "readme_lang_zh_TW": "README.zh_TW.md",
    "readme_lang_en_US": "README.en_US.md",
}

# 内部备注键：只记"插件名字用户自己填过没有"（放在 options 里一起存，省一个设置项）
COMMENT_NAME_KEY = "_name"


def normalize_language(text: str) -> str:
    """把语言名洗成规范值（简中 / 繁中 / English）；认不出来当**简体中文**
    ⚠️ 别和 normalize_develop_language() 搞混：那是"用什么语言写代码"。
    """
    value = str(text or "").strip()
    if not value:
        return "简体中文"
    if value in LANGUAGE_TO_LOCALE:
        return value
    alias = LANGUAGE_ALIASES.get(value.lower())
    if alias:
        return alias
    lowered = value.lower()
    if lowered in ("zh_cn", "zh-cn", "zhcn", "zh", "chinese", "chs", "cn"):
        return "简体中文"
    if lowered in ("zh_tw", "zh-tw", "zhtw", "cht", "tw"):
        return "繁體中文"
    if lowered in ("en_us", "en-us", "en", "us"):
        return "English"
    return "简体中文"

# 预览里最多显示多少字符（界面上的只读预览框，太长没人看）
PREVIEW_MAX_CHARS = 6000


def normalize_develop_language(value) -> str:
    """把默认开发语言洗成 LANGUAGES 里的一员（认不出来就是 Python）
    ⚠️ 别和上面的 normalize_language() 搞混：那个管"插件界面支持哪几种语言"
       （简中 / 繁中 / English），这个管"生成的插件用什么语言写代码"。
       两件事，两套取值，互不相干。
    """
    text = str(value or "").strip()
    for name in LANGUAGES:
        if text.lower() == name.lower():
            return name
    return DEFAULT_LANGUAGE


# ---------- 开关的读 / 写 ----------
def normalize(raw) -> dict:
    """把设置里读到的原始值洗成"规则键都是 bool + 一个开发语言"的完整字典
    ⚠️ 玩家手改配置 / 老版本遗留 / 键被删过都会走到这里：不认识的类型一律退回默认值，
       绝不抛异常；`_name` 备注键原样保留。返回值里一定有 LANGUAGE_KEY。
    """
    result = dict(DEFAULTS)
    # 开发语言不是 bool 开关，先给默认值
    result[LANGUAGE_KEY] = DEFAULT_LANGUAGE
    if not isinstance(raw, dict):
        return result
    for key, default in DEFAULTS.items():
        if key not in raw:
            continue                     # 缺键 = 用默认值（不是"关掉"）
        value = raw.get(key)
        if isinstance(value, bool):
            result[key] = value
        elif isinstance(value, (int, float, str)):
            # 容忍 "true" / 1 / "0" 这类手改出来的值
            text = str(value).strip().lower()
            if text in ("true", "1", "yes", "on"):
                result[key] = True
            elif text in ("false", "0", "no", "off", ""):
                result[key] = False
            else:
                result[key] = bool(default)
        else:
            result[key] = bool(default)
    # 备注键：只留字符串，截一下
    name = raw.get(COMMENT_NAME_KEY)
    if isinstance(name, str) and name.strip():
        result[COMMENT_NAME_KEY] = name.strip()[:80]
    # 默认开发语言：认不出来的值一律退回 Python，绝不把它变成 bool
    result[LANGUAGE_KEY] = normalize_develop_language(raw.get(LANGUAGE_KEY))
    return result


def load_options(context) -> dict:
    """从设置里读 Skill 开关；⚠️ settings_manager / settings 可能是 None，读不到用默认值"""
    raw = None
    try:
        manager = getattr(context, "settings_manager", None)
        settings = getattr(manager, "settings", None)
        if isinstance(settings, dict):
            raw = settings.get(OPTIONS_KEY)
    except Exception:
        raw = None
    return normalize(raw)


def save_options(context, options: dict) -> bool:
    """把 Skill 开关写回设置，返回是否写成功；⚠️ 写设置也可能抛，调用方要判返回值"""
    try:
        manager = getattr(context, "settings_manager", None)
        if manager is None:
            return False
        manager.update_setting(OPTIONS_KEY, normalize(options))
        return True
    except Exception:
        return False


def save_enabled(context, enabled: bool) -> bool:
    """总开关落盘（同样判返回值，不抛）"""
    try:
        manager = getattr(context, "settings_manager", None)
        if manager is None:
            return False
        manager.update_setting(ENABLED_KEY, bool(enabled))
        return True
    except Exception:
        return False


def load_enabled(context) -> bool:
    """读总开关；读不到就是**关**（默认不开启）"""
    try:
        manager = getattr(context, "settings_manager", None)
        settings = getattr(manager, "settings", None)
        if isinstance(settings, dict):
            return bool(settings.get(ENABLED_KEY, False))
    except Exception:
        pass
    return False


# ---------- 规则内容：从这里算出"要生成什么" ----------
def readme_extra_files(options: dict) -> list:
    """按 README 语言开关算出额外要生成的 README 文件（顺序固定）"""
    options = normalize(options)
    return [filename for key, filename in README_EXTRA.items() if options.get(key)]


def active_rule_keys(options: dict) -> list:
    """当前**开着**的规则键（界面/日志里用来告诉用户"技能在管哪些事"）"""
    options = normalize(options)
    return [rule["key"] for rule in RULES if options.get(rule["key"])]


def rule_lines(options: dict) -> list:
    """把开关翻译成提示词里的"硬规矩"清单（一行一条）；⚠️ 只有开着的规则才出现"""
    options = normalize(options)
    lines = []

    if options["require_readme"]:
        lines.append("必须生成 README.md，不许省略、不许留空。")
    if options["readme_strict"]:
        lines.append(
            "README.md 要写得**缜密**：核心功能、安装与使用方法、目录结构说明、"
            "配置项、常见坑、二次开发指引 —— 每一项都要有，不许一句话敷衍。")
    if options["three_languages"]:
        lines.append(
            "插件本体自带 简体中文 / 繁體中文 / English 三套语言，用户能随时切换："
            "所有界面文案都来自 lang/*.json，三个文件的键名必须完全一致，"
            "代码里不许出现写死的中文或英文句子。")
    if options["readme_lang_zh_TW"]:
        lines.append("额外生成 README.zh_TW.md（繁體中文版 README，内容与中文版一一对应）。")
    if options["readme_lang_en_US"]:
        lines.append("额外生成 README.en_US.md（English README，内容与中文版一一对应）。")

    if not lines:
        # 一条规则都没开：明确告诉 AI"没有额外要求"，别留一段空白让它瞎猜
        lines.append("本次没有额外的强制要求，按用户说的话做即可。")
    return lines


def language_lines(options: dict) -> list:
    """插件本体的多语言要求（three_languages 关掉时给一句"听用户的"）"""
    options = normalize(options)
    if options["three_languages"]:
        return [
            "lang/zh_CN.json（简体中文，**兜底语言**，这个文件里的键最全）",
            "lang/zh_TW.json（繁體中文）",
            "lang/en_US.json（English）",
            "⚠️ 三个语言文件的键名必须完全一致；少翻译一句没关系（会回退到 zh_CN），"
            "但 key 不能缺、不能拼错。",
        ]
    return [
        "本次**没有强制**三语言：用户指定了语言就按用户说的做，"
        "用户没说就至少保留 lang/zh_CN.json（宿主靠它取文案）。",
    ]


# ---------- 提示词：组装完整的一段话交给 AI ----------
def build_prompt(plugin_id: str, plugin_name: str, idea: str, language: str,
                 options: dict, plugins_dir: str, locale_names=None) -> str:
    """组装交给 AI 的完整提示词
    结构固定七段：任务 / 现状 / 用户的要求 / 生成规则（Skill）/ 优先级（用户的明确
    要求 > 生成规则）/ 实现要求 / 验收 —— 别打乱，用户是照着这个顺序读的。
    ⚠️ 这段会**原样**发给 AI，也会原样给用户看：不许塞"删文件 / 改别人的插件"之类的
       越界指令。
    """
    options = normalize(options)
    locale_names = locale_names or LOCALE_NAMES
    plugins_dir = str(plugins_dir or "plugins").replace("\\", "/")

    language = str(language or "").strip() or "Python"
    plugin_name = str(plugin_name or "").strip() or plugin_id
    idea = str(idea or "").strip() or "（用户没写功能想法，按插件 id 和名字推断一个合理的用途）"

    target_dir = f"{plugins_dir}/{plugin_id}/"

    # 已生成的骨架文件清单（和 maker.py 真正写出去的东西对齐）
    skeleton = [
        "manifest.json         插件元信息（id / name / description / version / author / entry / icon，"
        "以及 Web 版真正读的 config_page / enabled_setting / default_disabled）",
        "config.html           ★ **Web 版唯一真正加载的界面**（iframe）：配置项 / 开关都写在这一页里",
        "app.py                入口：create_page(context) 已经能跑，串起 core/ 和 ui/（**只有 py 版会执行**）",
        "core/__init__.py      模块包标记",
        "core/config.py        插件自己的配置读写（写 context.data_dir）",
        "core/i18n.py          多语言（lang/*.json，回退顺序 zh_CN → en_US）",
        "ui/__init__.py        模块包标记",
        "ui/page.py            真正要你改的界面文件（现在是能跑的起始页）",
        "assets/icon.png       图标（宿主插件卡片用）",
    ]
    if options["require_readme"]:
        skeleton.append("README.md             说明文档（按规则的要求写缜密）")
    if options["three_languages"]:
        skeleton.append("lang/zh_CN.json / lang/zh_TW.json / lang/en_US.json  三套语言文案")
    for extra in readme_extra_files(options):
        skeleton.append(f"{extra}             额外语言的 README")

    parts = []
    parts.append("【任务】")
    parts.append(
        f"请把 ToolsGCP 的新插件 `{plugin_id}`（名称：{plugin_name}）实现完整。")
    parts.append(
        "所谓 ToolsGCP 插件，就是 `plugins/<插件id>/` 下的一个文件夹。"
        "⚠️ 它现在跑在 **Web 版**宿主里，宿主只认两样东西："
        "`manifest.json`（要含 `config_page` / `enabled_setting` / `default_disabled`）"
        "和那个 `config_page` 指向的 **config.html**（HTML + JS，用 iframe 打开）。")
    parts.append(
        "`app.py` 里的 `create_page(context) -> QWidget` 那套是**旧 py(QuQt) 版**的约定："
        "留着兼容可以，但 **Web 版一行都不会执行它**（主线程 import PyQt5 会让 WebView2 崩溃）。"
        "所以**用户能看见、能用的功能必须写在 config.html 里**，只改 Python 的话插件在界面上是空的。")
    parts.append(
        "config.html 里读写设置走宿主接口：`window.parent.pywebview.api.settings.get(key)` / "
        "`settings.set(key, value)`（iframe 内没有自己的 window.pywebview，必须回退 parent）；"
        "返回的是 `{ok: ...}` 信封，⚠️ 别把 `ok` 当业务字段名。"
        "主题跟宿主 postMessage 的 `toolsgcp-theme` 走，关闭本页发 `toolsgcp-close-plugin`。"
        "骨架里的 config.html 已经把这几条都实现好了，照着加行就行。")
    parts.append(
        f"`{target_dir}` 下**已经生成了可加载的骨架**（见下），你的任务是把功能填进去，"
        "不是从零新建目录，也不要重写骨架里那些已经正确的部分。")

    parts.append("")
    parts.append("【已经生成好的文件（照着改，别重复造）】")
    parts.extend(skeleton)

    parts.append("")
    parts.append("【用户本次的要求（最优先）】")
    parts.append(idea)
    parts.append(f"开发语言：{language}"
                 "（界面主体是 config.html 的 HTML + JS；只有要兼容旧 py 版时才写 Python + PyQt5）。")

    parts.append("")
    parts.append("【生成规则 · Skill 技能（内部技能的辅助要求，不是命令）】")
    parts.extend(rule_lines(options))

    parts.append("")
    parts.append("【优先级 · 必须遵守】")
    parts.append(
        "用户在【用户本次的要求】里**明确说了**的做法，优先于上面任何一条生成规则。")
    parts.append(
        "例如用户说「不要 README」，那就不要 README，规则里那几条 README 要求自动作废；"
        "用户说「用 JavaScript 写」，那就用 JavaScript，不要硬套 Python 模板；"
        "用户说「README 写成英文」，就以用户说的为准。")
    parts.append(
        "只有用户**没说**的地方，才用【生成规则】去补足。"
        "两条规则互相打架时，以更靠前的那条为准，并在回复里说明你为什么这么选。")

    parts.append("")
    parts.append("【实现要求】")
    if options["three_languages"]:
        names = " / ".join(locale_names[x] for x in ALL_LOCALES)
        parts.append(f"1. 插件原生支持这些语言：{names} —— "
                     "所有界面文案走 i18n，键名三份文件保持一致。")
    else:
        parts.append("1. 语言以用户要求为准；没要求就至少保留 lang/zh_CN.json。")
    parts.extend(f"   · {line}" for line in language_lines(options))
    parts.append(
        "2. **功能必须落在 config.html 里**（Web 版宿主只加载这一页）：纯 HTML + 原生 JS，"
        "自带样式、不联网、不引外部库、不要构建步骤；设置读写只走 host 的 "
        "settings.get/set。骨架里那一页已经是能跑的样子，照着扩展就行。")
    parts.append(
        "3. 如果要同时兼容旧 py 版：Python 那边只用 PyQt5 + qfluentwidgets，"
        "**不许引入任何新依赖**；Python 3.13。只做 Web 版的话这条忽略。")
    parts.append(
        "4. 代码风格照抄骨架（以及同目录的 gcp-ai-agent）：中文注释解释「为什么」、"
        "插件内部模块用相对导入（from .core.config import Config）、"
        "插件自己的数据写 context.data_dir（不要往插件目录写）。")
    parts.append(
        "5. 异常纪律：create_page、每个按钮回调、refresh() / on_show() 里都不许让异常逃出去；"
        "context.ai_agent 可能是 None，每次用都要判空。")
    parts.append(
        "6. 只改这个插件自己的文件夹，不许动 plugins/ 下的其他插件，也不许改程序本体文件。")

    parts.append("")
    parts.append("【验收】")
    parts.append("把改完的文件路径和关键代码贴出来，并说明：")
    parts.append("  · 插件的核心功能怎么用（点哪里、看到什么）")
    parts.append("  · 三套语言怎么切换（或按用户要求的语言方案）")
    parts.append("  · README 里写了哪些章节")

    return "\n".join(parts)


def preview_text(plugin_id: str, plugin_name: str, idea: str, language: str,
                 options: dict, plugins_dir: str, locale_names=None) -> str:
    """给界面看的只读预览（就是真正会发出去的那段提示词，过长截断）"""
    text = build_prompt(plugin_id, plugin_name, idea, language, options,
                        plugins_dir, locale_names=locale_names)
    if len(text) <= PREVIEW_MAX_CHARS:
        return text
    return text[:PREVIEW_MAX_CHARS] + "\n\n…（预览已截断，实际发给 AI 的是完整内容）"


def describe(options: dict) -> str:
    """一行字说明"技能现在管着哪几件事"（开关变化时刷新，给用户一个即时反馈）"""
    keys = active_rule_keys(options)
    if not keys:
        return "off"
    return ",".join(keys)
