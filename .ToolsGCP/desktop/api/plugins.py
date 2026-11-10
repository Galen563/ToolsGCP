"""插件域（`window.pywebview.api.plugins`）+ 插件制作辅助的纯 Python 桥。
========== 一、为什么需要这个域 ==========
前端插件中心（`app.js` 的 `loadPlugins()`）调的是 `plugins.list` —— 后端此前**没有这个域**，
`tryCall` 拿到 `null` 就退回写死的三个 id（`gcp-ai-agent / gcp-plugin-maker / plugin-showcase`）：
用户自己用 AI 生成的新插件、手动丢进 `plugins/` 的插件，在插件中心里根本不会出现
（确保插件功能完全和 py 版本一致能用）。
这里按 py 版 `core/plugin_manager.py` 的扫描规则把真实目录列出来。
========== 二、为什么不直接用 `PluginManager.discover()` ==========
`PluginManager.__init__` 会做**插件目录迁移**（把老位置 `plugins/` 搬进 `.ToolsGCP/plugins/`），
而 `load_all()` 更会 import 插件的 `app.py`（**会 import PyQt5，主线程必崩**）。
本域只想"列出目录"，所以：
  · 目录/保留名规则**复用** `PluginManager.is_reserved_folder()`（纯静态方法，不碰 Qt/不读盘）；
  · 只读 `manifest.json`（`utf-8-sig`，记事本另存带 BOM 也能读），不加载任何插件代码。
========== 三、插件制作辅助（gcp-plugin-maker）的桥 ==========
`gcp-plugin-maker` 在 py 版里通过 `context.register_chat_hint()` / `context.register_ai_tool()`
往宿主登记两样东西：`/plugin` 悬浮提示 + `create_plugin` 工具。Web 版没有那套 Qt 上下文，
所以由本模块在**后端**直接做等价的事：
  · `hint_payload()`  —— 读插件 `lang/<locale>.json` 的 `hint_label` / `hint_prompt`，
    用 `core/skill.py` 的 `normalize()` / `rule_lines()` / `LANGUAGE_KEY` 把
    `{rules}` / `{language}` 填好（和 py 版 `ui/page.py：_hint_prompt` 逐字段对齐）；
  · `execute_create_plugin()` —— 直接调 `core/maker.py：generate()` 把插件骨架写进
    `plugins/<id>/`（和 py 版 `ui/page.py：_handle_create_plugin` 同一套参数与错误口径）。
⚠️⚠️ **绝不 import 插件的 `app.py` / `ui/`**：它们 `from PyQt5...` 进主线程会让 WebView2 崩
（AGENTS.md 第 7/8 节）。`core/` 下的 `maker.py` / `skill.py` / `i18n.py` / `config.py` 都是
纯标准库，这里用 `importlib` 把 `core/` 当成一个**合成包**加载（相对导入 `from . import skill`
才解析得到），合成包名带前缀，不会和宿主/插件自己的包名撞车。
⚠️ 所有函数**都不抛**：读不到/坏 JSON/插件缺失一律返回 `{}` / 省略 / `{ok:False,error}`，
   调用方（AiDomain / 前端）拿到的永远是 JSON 可序列化的东西。
"""

import importlib
import importlib.util
import json
import os
import shutil
import sys
import threading

from pymodels.constants import CONFIG_DIR

from . import _fail, _log, _ok

# ---------- 目录常量（和 py 版 core/plugin_manager.py 对齐） ----------
PLUGINS_DIR_NAME = "plugins"
TEMPLATE_DIR_NAME = "_template"
SHOWCASE_DIR_NAME = "plugin-showcase"
# 预留/受保护目录（和 py 版 RESERVED_DIR_NAMES 的超集，规则保持一致）
RESERVED_DIR_NAMES = (TEMPLATE_DIR_NAME, SHOWCASE_DIR_NAME, "_t", "_archive")

# 内置/受保护插件：py 版靠 `PluginInfo.protected`（manifest 里的 builtin）判定；
# 这里再写死一份官方插件 id —— 就算有人把 manifest 里的 builtin 删了，
# 插件制作辅助GCP-AI Agent也不允许被删（删了用户就再也生成不了插件了）。
PROTECTED_PLUGIN_IDS = ("gcp-ai-agent", "gcp-plugin-maker", "plugin-showcase")

MANIFEST_NAME = "manifest.json"
LEGACY_MANIFEST_NAME = "plugin.json"

# ---------- 插件制作辅助 ----------
MAKER_PLUGIN_ID = "gcp-plugin-maker"
# 合成包名（加载插件 core/ 用）：带前缀，避免污染 sys.modules 里的常规名字
MAKER_CORE_PACKAGE = "_toolsgcp_plugin_maker_core"
# 和 py 版 ui/page.py 的常量逐一对齐
HINT_ID = "gcp-plugin-maker"
HINT_INSERT = "/plugin"
HINT_PRIORITY = 20
TOOL_NAME = "create_plugin"

# lang/<locale>.json 的三套语言（＝插件自带语言，缺哪份就按 zh_CN → en_US 回退）
LANG_LOCALES = ("zh_CN", "zh_TW", "en_US")
DEFAULT_LOCALE = "zh_CN"
# locale → 语言名：manifest 里的多语言字段（name / description）用的是**语言名**做键
# （{"简体中文": ..., "English": ...}），不是 locale 名 —— 和 py 版
# `PluginManager._localized()` 的取值顺序保持一致（先语言名、再 locale 名）。
LANGUAGE_FOR_LOCALE = {"zh_CN": "简体中文", "zh_TW": "繁體中文", "en_US": "English"}

# 默认开发语言里这些值表示"让插件自己定"，必须转成空串（否则会生成奇怪的语言名）
LANGUAGE_PLACEHOLDERS = {
    "", "自述（默认）", "自述(默认)", "自述", "默认", "默认（自述）", "其他", "其它",
    "default", "auto", "other", "none",
}

_maker_lock = threading.RLock()
_maker_cache = {}          # {"key": core_dir, "maker": module, "skill": module}
_lang_cache = {}           # lang 文件缓存：{path: (mtime, dict)}


# ======================================================================
# 路径（⚠️ 插件有**两个**根目录，两处都要扫描加载 —— 见下面的推导）
# ======================================================================
#   ① 内置根：`<程序目录>\.ToolsGCP\plugins\`
#      随程序发布的官方插件（gcp-ai-agent / gcp-plugin-maker / _template）在这里。
#   ② 用户根：`<数据根>\plugins\`（默认 `<用户主目录>\.ToolsGCP\plugins\`，会自动创建）
#      ⚠️ 为什么必须有它：**exe 打包后 ① 被塞进了 exe 本体所在目录**，那里可能只读
#      （装在 Program Files、或受 UAC 虚拟化影响），而且程序升级会整体覆盖 ——
#      开发者/用户做好的插件根本放不进去。② 在用户可写的数据根里，
#      并且跟着「设置 → 存储」的数据根迁移一起走。
#   ⚠️ 顺序 = 优先级：② 在前、① 在后。同名插件（同目录名）**用户目录那份生效**，
#      这样开发者可以覆盖内置插件做调试；内置那份仍然照常加载，只是被"遮住"。
#   ⚠️ 两处都加载，不是"只认其中一边"。新增任何"找插件目录"的代码时**不要**再写死
#      `CONFIG_DIR/plugins`，一律走 `plugins_dirs()` / `find_plugin_dir()`。
def user_plugins_dir() -> str:
    """用户可写的插件根目录：`<数据根>\\plugins`（自动创建，失败也只记日志不抛）"""
    try:
        from pymodels.constants import USER_DATA_ROOT
        root = os.path.join(str(USER_DATA_ROOT), PLUGINS_DIR_NAME)
    except Exception:
        return ""
    try:
        os.makedirs(root, exist_ok=True)
    except Exception as exc:
        _log("warn", "插件", "plugin", f"创建用户插件目录失败 {root}: {exc}")
    return root


def plugins_dirs() -> list:
    """全部插件根目录（**按优先级排序**：用户目录在前，内置目录在后）。
    永远至少返回内置那一份；用户目录拿不到时只返回内置，绝不返回空表。
    """
    roots = []
    for fn in (user_plugins_dir, plugins_dir):
        try:
            path = fn()
        except Exception:
            path = ""
        if path and path not in roots:
            roots.append(path)
    return roots or [plugins_dir()]


def find_plugin_dir(rel_folder: str) -> str:
    """按目录名找插件目录的**绝对路径**，优先返回用户目录里那一份。
    找不到返回空串。⚠️ rel_folder 只允许是"第一层目录名"，含路径分隔符一律拒绝
    （这个函数会被删除/读文件路径拼接用到，防目录穿越）。
    """
    name = str(rel_folder or "").strip()
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return ""
    for root in plugins_dirs():
        candidate = os.path.join(root, name)
        if os.path.isdir(candidate):
            return candidate
    return ""


def plugins_dir() -> str:
    """内置插件根目录：`.ToolsGCP/plugins`（程序目录旁，随程序发布，永不搬）
    ⚠️ 这只表示**内置那一份**。要"所有插件目录"请用 `plugins_dirs()`；
       要"某个插件到底在哪"请用 `find_plugin_dir(id)`。
    """
    return os.path.join(CONFIG_DIR, PLUGINS_DIR_NAME)


def maker_dir() -> str:
    """插件制作辅助自己的目录：`.ToolsGCP/plugins/gcp-plugin-maker`"""
    return os.path.join(plugins_dir(), MAKER_PLUGIN_ID)


def template_dir() -> str:
    """新插件的模板目录：`.ToolsGCP/plugins/_template`（图标从它的 assets/ 拿）"""
    return os.path.join(plugins_dir(), TEMPLATE_DIR_NAME)


def is_reserved_folder(name: str) -> bool:
    """这个文件夹名要不要当成插件（下划线/点开头一律跳过，再显式排掉保留名）
    ⚠️ 规则必须和 py 版 `PluginManager.is_reserved_folder()` 一致：
       否则 py 版能看到的插件在 Web 版看不到（或反过来），用户会以为"插件丢了"。
    """
    text = str(name or "")
    if not text or text.startswith(("_", ".")):
        return True
    return text.lower() in {n.lower() for n in RESERVED_DIR_NAMES}


# ======================================================================
# 小工具
# ======================================================================
def _read_json(path: str) -> dict:
    """读 JSON（utf-8-sig：兼容记事本另存的 BOM）；坏文件/不存在返回 {}，绝不抛"""
    try:
        if not path or not os.path.isfile(path):
            return {}
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception as exc:                              # noqa: BLE001
        _log("warn", "插件", "plugin", f"读取 JSON 失败 {path}: {type(exc).__name__}: {exc}")
        return {}


def _pick_locale(value, locale: str) -> str:
    """多语言字段取值（和 py 版 `PluginManager._localized()` 同序）
    manifest 里 name/description 允许写成 `{"简体中文": "...", "English": "..."}`
    —— 键是**语言名**；也兼容写 locale 名（zh_CN/zh_TW/en_US）的插件。
    取值顺序：当前语言名 → 当前 locale → 简体中文 → zh_CN → en_US → 任一非空值。
    """
    if isinstance(value, dict):
        for key in (LANGUAGE_FOR_LOCALE.get(locale, ""), locale,
                    "简体中文", "zh_CN", "en_US"):
            if key and value.get(key):
                return str(value[key])
        for item in value.values():            # 最后兜底：别让插件名字退化成 id
            if item:
                return str(item)
        return ""
    return str(value or "")


def _fill(template: str, **kwargs) -> str:
    """把指令模板里的 {占位符} 替换掉；模板坏了（少占位符 / 多个裸 {}）退回原文，不抛
    ⚠️ 和 py 版 `ui/page.py：_fill` 同一语义：宁可发出带 `{rules}` 原文的指令，
       也不能因为模板里多一个花括号就整条提示没有。
    """
    try:
        return str(template).format(**kwargs)
    except Exception:
        return str(template)


# ======================================================================
# 插件制作辅助：读 lang / 读设置
# ======================================================================
def maker_lang(locale: str = DEFAULT_LOCALE) -> dict:
    """读插件文案（`lang/<locale>.json`），带 zh_CN → en_US 回退；读不到返回 {}"""
    locale = str(locale or DEFAULT_LOCALE)
    candidates = [locale] + [code for code in LANG_LOCALES if code != locale]
    for code in candidates:
        path = os.path.join(maker_dir(), "lang", f"{code}.json")
        try:
            if not os.path.isfile(path):
                continue
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0
        cached = _lang_cache.get(path)
        if cached and cached[0] == mtime:
            data = cached[1]
        else:
            data = _read_json(path)
            _lang_cache[path] = (mtime, data)
        if data:
            return data
    return {}


def maker_text(locale: str = DEFAULT_LOCALE, key: str = "") -> str:
    """取一条插件文案（找不到返回空串）"""
    return str(maker_lang(locale).get(str(key or "")) or "")


def _strict_on(value) -> bool:
    """设置值的严格布尔判定
    为什么不用 `bool(value)`：旧配置里这个键可能被存成字符串 `"false"` / `"0"`，
    `bool("false")` 是 **True** —— 于是"用户明明关着插件制作辅助，敲 / 却照样冒提示"。
    前端 `app.js：settingOn()` 用的是同一套口径，两边必须一致，否则提示条和后端注入会打架。
    """
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return False


def maker_enabled(settings_manager) -> bool:
    """设置里的总开关（README：默认关；读不到/异常也当关）"""
    try:
        settings = getattr(settings_manager, "settings", None)
        if isinstance(settings, dict):
            return _strict_on(settings.get("gcp_plugin_maker_enabled", False))
    except Exception:
        pass
    return False


def maker_raw_options(settings_manager) -> dict:
    """设置里的 Skill 原始选项（未经 normalize；坏值当空 dict）"""
    try:
        settings = getattr(settings_manager, "settings", None)
        if isinstance(settings, dict):
            raw = settings.get("gcp_plugin_maker_options")
            if isinstance(raw, dict):
                return dict(raw)
    except Exception:
        pass
    return {}


def clean_develop_language(value) -> str:
    """把默认开发语言洗成能直接生成的值；"自述（默认）/其他/空"一律返回空串
    为什么单独洗：插件 config.html 的下拉框最前面是 `自述（默认）`、最后是 `其他`
    （那是"让 AI 自己看着办"的两个选项），而 `maker.generate()` 拿到非空 language 就
    原样写进 manifest/app.py —— 直接把"自述（默认）"传下去会生成一门不存在的语言，
    README 里还会出现开发语言：自述（默认）。所以这两个值必须转成空串，
    由 maker 用它自己的默认值（Python）。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower() in {v.lower() for v in LANGUAGE_PLACEHOLDERS}:
        return ""
    return text[:40]


def maker_skill():
    """只加载插件的 `core/skill.py`（组提示词用；不碰 maker，省一次 import）"""
    return _load_maker_core()[1]


def maker_options(settings_manager) -> dict:
    """设置里的 Skill 选项，已过 `skill.normalize()`（规则键都是 bool + 一个开发语言）"""
    try:
        skill = maker_skill()
        return skill.normalize(maker_raw_options(settings_manager))
    except Exception as exc:                              # noqa: BLE001
        _log("warn", "插件", "maker", f"读 Skill 选项失败（按默认值）: {type(exc).__name__}: {exc}")
        return {}


def _load_maker_core():
    """把插件的 `core/` 当一个**合成包**加载，返回 (maker, skill)
    ⚠️ 只加载 core/，因为 `core/maker.py` 里 `from . import skill` 是**相对导入**：
       必须先把 `core/__init__.py` 当成包执行（带 submodule_search_locations），
       再用 importlib.import_module 取子模块，否则相对导入无处可解。
    ⚠️ 绝不 import 插件的 `app.py` / `ui/`（PyQt5 会在主线程崩）。
    ⚠️ 失败抛异常由调用方兜（本模块所有公开函数都会兜），这样"插件没装"能被明确区分。
    """
    core_dir = os.path.join(maker_dir(), "core")
    init_path = os.path.join(core_dir, "__init__.py")
    if not os.path.isfile(init_path):
        raise FileNotFoundError(f"找不到插件制作辅助的核心模块: {init_path}")
    with _maker_lock:
        if _maker_cache.get("key") == core_dir and _maker_cache.get("maker"):
            return _maker_cache["maker"], _maker_cache["skill"]
        package = sys.modules.get(MAKER_CORE_PACKAGE)
        if package is None or getattr(package, "__path__", None) != [core_dir]:
            spec = importlib.util.spec_from_file_location(
                MAKER_CORE_PACKAGE, init_path, submodule_search_locations=[core_dir])
            if spec is None or spec.loader is None:
                raise ImportError(f"无法为 {core_dir} 建立模块规格")
            package = importlib.util.module_from_spec(spec)
            sys.modules[MAKER_CORE_PACKAGE] = package
            try:
                spec.loader.exec_module(package)
            except Exception:
                sys.modules.pop(MAKER_CORE_PACKAGE, None)
                raise
        maker = importlib.import_module(f"{MAKER_CORE_PACKAGE}.maker")
        skill = importlib.import_module(f"{MAKER_CORE_PACKAGE}.skill")
        _maker_cache["key"] = core_dir
        _maker_cache["maker"] = maker
        _maker_cache["skill"] = skill
        _log("info", "插件", "maker", f"已加载插件制作辅助核心模块: {core_dir}")
        return maker, skill


# ======================================================================
# 插件制作辅助：/plugin 悬浮提示
# ======================================================================
def hint_payload(settings_manager, locale: str = DEFAULT_LOCALE):
    """组装一条 `/plugin` 提示；未开启/插件缺失/文案缺失一律返回 None
    返回结构与前端（`app.js` 的 `loadAiHints()`）约定一致：
        {id, label, insert, prompt, priority}
    · label  —— 当前语言的 `hint_label`（"AI帮你制作插件"）
    · insert —— 固定 `/plugin`（点一下插进输入框，也是要敲的命令）
    · prompt —— `hint_prompt` 模板填好 `{rules}` / `{language}` 后的**完整指令**
    · priority —— 20（和 py 版 HINT_PRIORITY 一致，数字大的排前面）
    与 py 版 `ui/page.py：_hint_prompt()` 的对应关系：
        rules    = "\n".join(f"· {line}" for line in skill.rule_lines(options))
        language = options[skill.LANGUAGE_KEY] or skill.DEFAULT_LANGUAGE
    ⚠️ language 取的是**洗过**的值：用户在 config.html 里选了自述（默认）时
       normalize() 会把它变成 Python（认不出来一律退回 Python），提示词里就写 Python，
       正好是"用户没指定时生成的默认语言"。
    """
    if not maker_enabled(settings_manager):
        return None
    try:
        skill = maker_skill()
    except Exception as exc:                              # noqa: BLE001
        _log("warn", "插件", "maker",
             f"加载插件制作辅助核心失败（/plugin 提示不可用）: {type(exc).__name__}: {exc}")
        return None
    lang = maker_lang(locale)
    template = str(lang.get("hint_prompt") or "")
    label = str(lang.get("hint_label") or "")
    if not template or not label:
        _log("warn", "插件", "maker",
             f"插件制作辅助缺少 hint_prompt/hint_label 文案（locale={locale}）")
        return None
    try:
        options = skill.normalize(maker_raw_options(settings_manager))
        rules = "\n".join(f"· {line}" for line in skill.rule_lines(options))
    except Exception as exc:                              # noqa: BLE001
        _log("warn", "插件", "maker", f"组装 Skill 规则失败: {type(exc).__name__}: {exc}")
        rules = ""
    language = (clean_develop_language(maker_raw_options(settings_manager).get(
        getattr(skill, "LANGUAGE_KEY", "default_language")))
        or str(getattr(skill, "DEFAULT_LANGUAGE", "Python") or "Python"))
    prompt = _fill(template, rules=rules, language=language)
    return {
        "id": HINT_ID,
        "label": label,
        "insert": HINT_INSERT,
        "prompt": prompt,
        "priority": HINT_PRIORITY,
    }


# ======================================================================
# 插件制作辅助：create_plugin 工具
# ======================================================================
class _MakerLog:
    """给 `maker.generate(context, ...)` 用的最小 context
    maker 内部只从 context 上取 `log()`（目录我们显式传了 plugins_dir / template_dir），
    其它属性缺失它会判空，所以这个壳就够；写日志统一走宿主日志器。
    """

    __slots__ = ("log",)

    def __init__(self):
        self.log = self._log

    @staticmethod
    def _log(message, level: str = "info"):
        try:
            _log("err" if str(level).lower() in ("err", "error") else "info",
                 "插件", "maker", str(message or ""))
        except Exception:
            pass


def execute_create_plugin(settings_manager, args, locale: str = DEFAULT_LOCALE) -> dict:
    """执行 `create_plugin` 工具（AI 在用户发了 /plugin 之后调它）
    返回 JSON 信封 `{ok: True, data: {...}}` / `{ok: False, error: "…"}`（**绝不抛**）。
    参数（和 py 版 ui/page.py：_handle_create_plugin 一致）：
        id        插件 id（先过 maker.validate_id，不合法一个字节都不写）
        name      显示名（空就用 id）
        idea      一句话说明它干什么
        language  开发语言（可省略 → 设置里的默认开发语言 → Python）
    安全：
        · 总开关关着直接拒绝（和 py 版同样的文案 tool_disabled）；
        · **永不覆盖**已存在的插件目录（overwrite 固定 False）—— AI 换个 id 就行，
          否则用户手改过的插件被 AI 一次调用抹掉，是不可接受的破坏性操作。
    """
    try:
        if not maker_enabled(settings_manager):
            # 文案在 lang/*.json 的 tool_disabled（三语齐）
            return {"ok": False,
                    "error": maker_text(locale, "tool_disabled") or
                             "插件制作辅助没有开启（请先在插件配置界面打开总开关）"}
        try:
            maker, skill = _load_maker_core()
        except Exception as exc:                          # noqa: BLE001
            _log("err", "插件", "maker", f"加载插件制作辅助核心失败: {exc}")
            return {"ok": False,
                    "error": f"插件制作辅助的核心模块加载失败（插件可能在 plugins/ 下缺失）: {exc}"}

        params = args if isinstance(args, dict) else {}
        plugin_id = str(params.get("id") or "").strip()
        plugin_name = str(params.get("name") or "").strip() or plugin_id
        idea = str(params.get("idea") or "").strip()

        raw_options = maker_raw_options(settings_manager)
        options = skill.normalize(raw_options)
        # 开发语言：工具参数 → 设置里的默认开发语言 → 空串（让 maker 用自己的默认值 Python）
        language = clean_develop_language(params.get("language"))
        if not language:
            language = clean_develop_language(raw_options.get(
                getattr(skill, "LANGUAGE_KEY", "default_language")))

        valid, reason = maker.validate_id(plugin_id)
        if not valid:
            return {"ok": False, "error": str(reason or "插件 id 不合法")}

        # ⚠️ 生成目标 = **用户可写的插件根**（`<数据根>\plugins`），不是程序目录那一份：
        #    exe 打包后程序目录旁的 .ToolsGCP 常常只读（装在 Program Files 时），
        #    写到那里会静默失败 —— 这正是"插件做好了放不进原生插件文件夹"的根因。
        #    用户根在数据根下，配合 plugins_dirs() 的优先级（用户在前），
        #    新建的插件立刻就能在插件中心看到，且升级程序不会把它覆盖掉。
        root = user_plugins_dir() or plugins_dir()
        if not root:
            return {"ok": False, "error": "拿不到可写的插件目录（数据根不可写）"}
        _log("info", "插件", "maker", f"create_plugin 写入目录: {root}")
        result = maker.generate(
            _MakerLog(), plugin_id, plugin_name, idea, language, options,
            overwrite=False,                 # ⚠️ 永不覆盖（见 docstring 安全说明）
            plugins_dir=root, template_dir=template_dir())

        if not getattr(result, "ok", False):
            error = str(getattr(result, "error", "") or "生成失败")
            _log("warn", "插件", "maker", f"create_plugin {plugin_id} 失败: {error}")
            return {"ok": False, "error": error}

        written = list(getattr(result, "written", []) or [])
        folder = str(getattr(result, "folder", "") or "")
        _log("op", "插件", "maker",
             f"create_plugin 成功: id={plugin_id} 名称={plugin_name} "
             f"语言={language or '默认'} 目录={folder} 写入 {len(written)} 个文件")
        return {"ok": True, "data": {
            "id": plugin_id,
            "name": plugin_name,
            "language": language or "Python",
            # 正斜杠相对路径，模型/前端都能直接看
            "folder": f"plugins/{plugin_id}/",
            "folder_path": folder,
            "files_written": len(written),
            "files": written[:20],
            # 这句是给模型看的：新插件默认停用，需要用户手动开启（py 版提示词第 4 条同款）
            "next_step": "插件已安装但默认停用，需要用户在插件中心手动开启后才能使用。",
        }}
    except Exception as exc:                              # noqa: BLE001
        _log("err", "插件", "maker", f"create_plugin 异常: {type(exc).__name__}: {exc}")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ======================================================================
# 域
# ======================================================================
class PluginsDomain:
    """`api.plugins.*`：插件目录列表 + 删除
    · `list()`   —— 前端插件中心据此去 `/res/plugins/<id>/manifest.json` 取详情；
    · `delete()` —— 前端删除按钮（内置/受保护插件在这里拦下）。
    ⚠️ 两个方法都只碰 `.ToolsGCP/plugins/` 第一层目录，**不加载插件代码**
       （import app.py 会拉 PyQt5 到主线程）。
    """

    def __init__(self, shell):
        self._shell = shell

    # ---------- 基础 ----------
    def _language(self) -> str:
        """当前界面语言（shell 会把跟随系统解析成三选一；拿不到就给空串）"""
        try:
            return str(self._shell.current_language() or "")
        except Exception:
            return ""

    def _locale_safe(self) -> str:
        """当前语言 → locale（zh_CN / zh_TW / en_US），认不出来按简体中文"""
        try:
            from pymodels.core.language_manager import locale_for
            return locale_for(self._language())
        except Exception:
            return DEFAULT_LOCALE

    def list(self):
        """枚举**两个插件根目录**下真正的插件目录（用户目录在前、内置目录在后）
        返回 `{ok, plugins:[{id, folder, name, version, builtin, has_manifest, error,
                              source, source_dir, overridable}], dirs, dir, count}`
        **排除**：`_` / `.` 开头的目录、`_template`、`plugin-showcase`、`_t`、`_archive`、
        非目录（和 py 版 `PluginManager.discover()` 的规则一致）。
        ⚠️ 只读 manifest.json，**不加载插件代码**（import app.py 会拉 PyQt5）。
        ⚠️ 目录不存在时返回空列表（不是错误）：全新安装本来就没有第三方插件。
        ⚠️⚠️ 同名（同目录名）插件**只出一条**，取用户目录那一份（优先级见 plugins_dirs()），
           并给它带上 `overridable: true` + `shadowed`（被它遮住的内置插件绝对路径），
           前端据此提示"这份覆盖了内置版本"。其余条目 `source` 标明来自哪一层。
        """
        try:
            roots = plugins_dirs()
            locale = self._locale_safe()
            rows = []
            seen = {}
            for root in roots:
                if not os.path.isdir(root):
                    continue
                for name in sorted(os.listdir(root)):
                    folder = os.path.join(root, name)
                    try:
                        if not os.path.isdir(folder) or is_reserved_folder(name):
                            continue
                    except OSError:
                        continue
                    if name in seen:
                        # 已经从高优先级的根里收过了：这条是被遮住的那个（内置同名插件），
                        # 只给"覆盖者"补一个 shadowed 字段，不再重复出一条
                        winner = seen[name]
                        winner.setdefault('shadowed', folder)
                        continue
                    row = self._describe(folder, name, locale)
                    if not row:
                        continue
                    row['source'] = ('user' if root == roots[0] else 'builtin')
                    row['source_dir'] = root
                    seen[name] = row
                    rows.append(row)
            return _ok(plugins=rows,
                       dirs=roots,
                       # dir 保留给老前端（它只认一个目录）：指向用户可写的那个
                       dir=(roots[0] if roots else ''),
                       user_dir=(roots[0] if roots else ''),
                       builtin_dir=plugins_dir(),
                       count=len(rows))
        except Exception as exc:                          # noqa: BLE001
            _log("err", "插件", "plugin", f"枚举插件目录失败: {exc}")
            return _fail(f"枚举插件目录失败: {exc}")

    def _describe(self, folder: str, folder_name: str, locale: str):
        """读一个插件目录的 manifest，压成一行给前端（读不到也给 id，别让它消失）"""
        try:
            manifest_path = os.path.join(folder, MANIFEST_NAME)
            if not os.path.isfile(manifest_path):
                legacy = os.path.join(folder, LEGACY_MANIFEST_NAME)
                if os.path.isfile(legacy):
                    manifest_path = legacy
                else:
                    return {"id": folder_name, "folder": folder_name,
                            "name": folder_name, "version": "", "builtin": False,
                            "has_manifest": False, "error": f"缺少 {MANIFEST_NAME}"}
            manifest = _read_json(manifest_path)
            if not manifest:
                return {"id": folder_name, "folder": folder_name, "name": folder_name,
                        "version": "", "builtin": False, "has_manifest": True,
                        "error": f"{MANIFEST_NAME} 解析失败或为空"}
            return {
                "id": str(manifest.get("id") or folder_name),
                "folder": folder_name,
                "name": _pick_locale(manifest.get("name"), locale) or str(manifest.get("id") or folder_name),
                "version": str(manifest.get("version") or ""),
                "builtin": bool(manifest.get("builtin")),
                "has_manifest": True,
                "error": "",
            }
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "插件", "plugin", f"读取插件 {folder_name} 失败: {exc}")
            return {"id": folder_name, "folder": folder_name, "name": folder_name,
                    "version": "", "builtin": False, "has_manifest": False,
                    "error": str(exc)}

    # ---------- 删除 ----------
    def delete(self, plugin_id: str = ""):
        """删掉一个插件目录（`plugins.delete`：前端插件中心的删除按钮）
        返回 `{ok:true, deleted:true, id, path}` / `{ok:false, error}`。
        ⚠️⚠️ 破坏性操作，四条硬约束（每一条都对应一种真实会发生的误删）：
          ① **只删 plugins/ 第一层**：id 非空、不含 `/` `\\`、不是 `.` / `..`；
             拼出来的绝对路径 + realpath 都必须正好落在 `<plugins>/<id>`，
             防止 `delete("../../config")` 这种路径穿越把用户数据删掉；
          ② **内置/受保护插件拒绝**：manifest 里 `builtin`/`protected` 为真，
             或目录名是官方插件（gcp-ai-agent / gcp-plugin-maker / plugin-showcase），
             一律不动 —— 删掉插件制作辅助，用户就再也用不了 AI 生成插件；
          ③ **保留目录拒绝**：`_template` 这类（`is_reserved_folder`）不是插件，
             删了会把新建插件的模板弄没；
          ④ 删除**前**先记 OP 日志（id + 绝对路径），`shutil.rmtree` 失败时
             如实返回错误 —— 不允许"只删了一半还回 ok"。
        ⚠️ 二次确认由前端负责（`app.js` 的 `deletePlugin()` 已经弹了 danger 确认框）；
           这里只做"能不能删"的判定，不弹窗。
        ⚠️ 不做"先停用再删"：插件的启停状态存在 config/plugins.json 里（id 集合），
           删掉目录后那个 id 留在集合里也没有任何影响（discover 扫不到它）。
        """
        try:
            folder_name = str(plugin_id or "").strip()
            if not folder_name:
                return _fail("没有指定要删除的插件")
            # ① 只接受"插件目录名"，不接受任何路径成分
            if folder_name in (".", "..") or "/" in folder_name or "\\" in folder_name:
                _log("warn", "插件", "plugin",
                     f"拒绝删除：插件 id 含路径成分 {folder_name!r}")
                return _fail(f"插件 id 不合法: {folder_name}")
            if folder_name.startswith((".", "_")) or is_reserved_folder(folder_name):
                return _fail(f"「{folder_name}」是保留目录（模板/示例），不能删除")

            # ⚠️ 插件现在有两个根：内置目录（exe 打包后多半只读）+ 用户数据根目录。
            #    所以这里**逐个根**尝试定位并删除；找到第一个真能删的就收工
            #    （同名插件优先用户目录那份，与 list()/find_plugin_dir() 一致）。
            roots = plugins_dirs()
            candidates = []
            for root in roots:
                root = os.path.abspath(root)
                target = os.path.abspath(os.path.join(root, folder_name))
                if os.path.normcase(os.path.dirname(target)) != os.path.normcase(root):
                    _log("warn", "插件", "plugin",
                         f"拒绝删除：目标不在插件目录第一层 {target}")
                    return _fail(f"插件 id 不合法: {folder_name}")
                candidates.append((root, target))
            hit = [(r, t) for r, t in candidates if os.path.isdir(t)]
            if not hit:
                return _fail(f"插件不存在: {folder_name}")
            root, target = hit[0]
            real_root = os.path.realpath(root)
            real_target = os.path.realpath(target)
            if os.path.normcase(os.path.dirname(real_target)) != os.path.normcase(real_root):
                # 目录是个链接（junction/symlink）指向 plugins/ 之外：删链接本身也许没事，
                # 但 rmtree 在某些实现对 junction 的行为不一致，直接拒绝最安全
                _log("warn", "插件", "plugin",
                     f"拒绝删除：插件目录指向别处 {target} → {real_target}")
                return _fail(f"「{folder_name}」不是 plugins 下的真实目录，拒绝删除")

            # ② 内置 / 受保护
            manifest = _read_json(os.path.join(target, MANIFEST_NAME))
            if not manifest.get("id"):
                legacy = _read_json(os.path.join(target, LEGACY_MANIFEST_NAME))
                if legacy:
                    manifest = legacy
            pid = str(manifest.get("id") or folder_name)
            builtin = bool(manifest.get("builtin") or manifest.get("protected"))
            # ⚠️ 保护只针对**内置目录**里那一份：用户在用户目录放的"同名覆盖版"
            #    （开发者调试内置插件时就是这么干的）必须能删掉 —— 否则他改完
            #    永远回不到官方版本，而这正是双根目录存在的意义之一。
            in_builtin_dir = os.path.normcase(os.path.dirname(real_target)) == \
                os.path.normcase(os.path.realpath(plugins_dir()))
            if in_builtin_dir and (builtin or folder_name in PROTECTED_PLUGIN_IDS
                                   or pid in PROTECTED_PLUGIN_IDS):
                _log("warn", "插件", "plugin",
                     f"拒绝删除内置插件: id={pid} 目录={folder_name}")
                return _fail(f"「{pid}」是内置插件，不能删除")
            if not in_builtin_dir and (folder_name in PROTECTED_PLUGIN_IDS
                                       or pid in PROTECTED_PLUGIN_IDS):
                # 用户目录里的同名覆盖版：允许删，但要留痕（删掉后自动回落到内置版本）
                _log("op", "插件", "plugin",
                     f"删除用户目录里的内置插件覆盖版: id={pid} 目录={target}"
                     f"（删后回落到内置版本）")

            # ④ 先记日志再动手（出问题时能查到删了什么、删到哪）
            _log("op", "插件", "plugin",
                 f"删除插件: id={pid} 名称={_pick_locale(manifest.get('name'), self._locale_safe()) or pid} "
                 f"目录={target}")
            shutil.rmtree(target)
            if os.path.isdir(target):
                return _fail(f"删除失败：目录仍然存在（可能被占用）: {target}")
            _log("op", "插件", "plugin", f"插件已删除: id={pid} 目录={target}")
            return _ok(deleted=True, id=pid, path=target)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "插件", "plugin",
                 f"删除插件 {plugin_id!r} 失败: {type(exc).__name__}: {exc}")
            return _fail(f"删除插件失败: {exc}")

    # ---------- 插件目录（给"把插件装进去"用） ----------
    def dirs(self):
        """两个插件根目录的路径 + 是否存在/可写（前端"打开插件目录"用）
        返回 `{ok, user_dir, builtin_dir, dirs:[{path, kind, exists, writable}], count}`
        ⚠️ 只读信息，不建目录（自动创建由 data_root._ensure_subdirs 在启动时完成）。
        """
        try:
            user = user_plugins_dir()
            builtin = plugins_dir()
            rows = []
            for path, kind in ((user, "user"), (builtin, "builtin")):
                if not path:
                    continue
                exists = os.path.isdir(path)
                rows.append({
                    "path": path,
                    "kind": kind,
                    "exists": exists,
                    # 用 os.access 实测，**不要**按 kind 硬判：源码运行时内置目录本来就可写
                    # （开发者就该能直接往里放），exe 装在 Program Files 时才只读 ——
                    # 前端据此决定"能不能手动放插件进去"的提示文案。
                    "writable": bool(exists and os.access(path, os.W_OK)),
                })
            return _ok(user_dir=user, builtin_dir=builtin, dirs=rows, count=len(rows))
        except Exception as exc:                          # noqa: BLE001
            return _fail(f"读取插件目录失败: {exc}")

    def open_dir(self, kind: str = "user"):
        """在资源管理器里打开插件目录（kind: user=用户可写目录 / builtin=内置目录）
        ⚠️ 打开**用户目录**时如果它还不存在就先建出来 —— 否则 explorer 打开一个
           不存在的路径会弹系统错误框。
        """
        try:
            which = str(kind or "user").strip().lower()
            path = plugins_dir() if which == "builtin" else user_plugins_dir()
            if not path:
                return _fail("拿不到插件目录")
            os.makedirs(path, exist_ok=True)
            os.startfile(path)                            # noqa: S606 - Windows 专用
            _log("info", "插件", "plugin", f"打开插件目录({which}): {path}")
            return _ok(path=path)
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "插件", "plugin", f"打开插件目录失败: {exc}")
            return _fail(f"打开插件目录失败: {exc}")


__all__ = [
    "PluginsDomain",
    "plugins_dir", "user_plugins_dir", "plugins_dirs", "find_plugin_dir",
    "maker_dir", "template_dir", "is_reserved_folder",
    "maker_lang", "maker_text", "maker_enabled", "maker_raw_options",
    "maker_options", "maker_skill", "clean_develop_language", "hint_payload",
    "execute_create_plugin",
    "HINT_ID", "HINT_INSERT", "HINT_PRIORITY", "TOOL_NAME",
]
