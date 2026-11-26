# -*- coding: utf-8 -*-
"""设置项的「值域 / 中文别名 / 生效方式」元数据 —— Agent 操作设置的唯一事实来源。

========== 为什么需要这个模块 ==========
用户原话：
  「我希望是设置中的所有内容agent都可以动的了」
  「例如我让他切换主体它切换成功了但是并没有立即生效的bug必须重启一下」
  「我跟他说我喜欢毛玻璃让他切换她说没有直接执行失败」

这三个问题指向同一件事：**Agent 只有 set_setting 这一个盲写入口**，
它不知道：
  ① 某个键的合法值是什么（theme_effect 存的是 mica/glass/acrylic，
     而界面上写的是 云母/毛玻璃/亚克力 —— 模型传"毛玻璃"就写进一个非法值）；
  ② 改完之后要不要通知界面（theme 改完必须立刻重画，否则要重启才看到）；
  ③ 哪些键是"派生/敏感/只读"的（api_key、ai_provider_profiles 之类不能乱动）。

本模块把这三件事做成**数据**，让 agent_web 的 set_setting / update_settings
先查表再写，写不进去就回一句"可选值是 X/Y/Z"，让模型自己纠正。

========== 设计原则 ==========
· **只描述，不执行**：纯数据 + 纯函数，不 import 任何 desktop 层 / 不碰 UI。
· **覆盖全部键**：没登记在 VALUES 里的键 = 自由值（字符串/数字/布尔自动类型转换），
  但仍然会过一遍 SECRET / READONLY 两道闸。
· **别名宁多勿少**：模型说"深色/暗色/dark/深色主题"都要能落到同一个值上。
"""

# ======================================================================
# 枚举型设置的合法值 + 中文别名
# ======================================================================
# 结构：key -> {"values": [合法值], "aliases": {别名: 合法值}, "apply": 生效方式}
# apply 取值：
#   "appearance" —— 写完后前端立刻重画主题/外观（不需要重启）
#   "language"   —— 写完后前端立刻切语言
#   "reload"     —— 写完需要重新加载数据（资源来源之类）
#   ""           —— 普通设置，落盘即可
_APPEARANCE = [
    "跟随系统", "浅色主题", "深色主题",
    "dark", "light", "system", "auto",
    "深色", "浅色", "暗色", "亮色", "黑色", "白色",
    "dark theme", "light theme", "follow system",
]

SETTING_VALUES = {
    # ---------- 外观 ----------
    "theme": {
        "values": ["跟随系统", "浅色主题", "深色主题"],
        "aliases": {
            "dark": "深色主题", "深色": "深色主题", "暗色": "深色主题", "黑色": "深色主题",
            "dark theme": "深色主题", "深色模式": "深色主题",
            "light": "浅色主题", "浅色": "浅色主题", "亮色": "浅色主题", "白色": "浅色主题",
            "light theme": "浅色主题", "浅色模式": "浅色主题",
            "auto": "跟随系统", "system": "跟随系统", "follow system": "跟随系统",
            "跟随": "跟随系统", "系统": "跟随系统", "自动": "跟随系统",
        },
        "apply": "appearance",
    },
    "theme_effect": {
        "values": ["mica", "glass", "acrylic"],
        "aliases": {
            "mica": "mica", "云母": "mica", "云母材质": "mica", "磨砂": "mica",
            "glass": "glass", "毛玻璃": "glass", "玻璃": "glass", "玻璃效果": "glass",
            "毛玻璃效果": "glass", "blur": "glass", "模糊": "glass",
            "acrylic": "acrylic", "亚克力": "acrylic", "压克力": "acrylic",
            "亚克力材质": "acrylic",
        },
        "apply": "appearance",
    },
    "accent_color": {
        "values": ["blue", "purple", "orange"],
        "aliases": {
            "blue": "blue", "蓝": "blue", "蓝色": "blue", "蓝色系": "blue",
            "purple": "purple", "紫": "purple", "紫色": "purple", "紫罗兰": "purple",
            "violet": "purple",
            "orange": "orange", "橙": "orange", "橙色": "orange", "claude橙": "orange",
            "claude": "orange",
        },
        "apply": "appearance",
    },
    # ⚠️ 这份清单必须和前端 FONT_PREFERED（webui/js/app.js）**完全一致**：
    #    前端下拉框里有 9 个字体，这里少一个 → 用户（或 agent）选到那个字体，
    #    后端就报「ui_font_family 不接受「X」」（用户报"agent 改字体失败"）。
    #    2026-11 补齐：FangSong / Consolas / JetBrains Mono。
    "ui_font_family": {
        "values": ["微软雅黑", "等线", "Segoe UI", "SimSun", "SimHei", "KaiTi",
                   "FangSong", "Consolas", "JetBrains Mono"],
        "aliases": {
            "微软雅黑": "微软雅黑", "雅黑": "微软雅黑", "yahei": "微软雅黑",
            "microsoft yahei": "微软雅黑", "默认": "微软雅黑",
            "等线": "等线", "dengxian": "等线",
            "segoe ui": "Segoe UI", "segoe": "Segoe UI",
            "simsun": "SimSun", "宋体": "SimSun",
            "simhei": "SimHei", "黑体": "SimHei",
            "kaiti": "KaiTi", "楷体": "KaiTi",
            # 仿宋
            "fangsong": "FangSong", "仿宋": "FangSong",
            # 等宽字体（agent / 代码场景常用）
            "consolas": "Consolas", "康雅": "Consolas",
            "jetbrains mono": "JetBrains Mono", "jetbrainsmono": "JetBrains Mono",
            "jetbrains": "JetBrains Mono",
        },
        "apply": "appearance",
    },
    "ui_animation": {
        "values": ["on", "reduced", "off"],
        "aliases": {
            "on": "on", "开": "on", "开启": "on", "打开": "on",
            "reduced": "reduced", "减少": "reduced", "减弱": "reduced", "低": "reduced",
            "off": "off", "关": "off", "关闭": "off", "无": "off", "禁用": "off",
        },
        "apply": "appearance",
    },
    # ---------- 语言 ----------
    "language": {
        "values": ["跟随系统", "简体中文", "繁體中文", "English"],
        "aliases": {
            "跟随系统": "跟随系统", "auto": "跟随系统", "system": "跟随系统", "跟随": "跟随系统",
            "简体中文": "简体中文", "中文": "简体中文", "简中": "简体中文",
            "zh_cn": "简体中文", "zh-cn": "简体中文", "chinese": "简体中文",
            "简体": "简体中文", "chi_sim": "简体中文",
            "繁體中文": "繁體中文", "繁体中文": "繁體中文", "繁中": "繁體中文",
            "zh_tw": "繁體中文", "zh-tw": "繁體中文", "cht": "繁體中文", "繁体": "繁體中文",
            "english": "English", "en_us": "English", "en-us": "English",
            "英语": "English", "英文": "English", "en": "English",
        },
        "apply": "language",
    },
    # ---------- 提示 ----------
    "toast_position": {
        "values": ["top", "top_right", "bottom_right", "top_left", "bottom_left"],
        "aliases": {
            "top": "top", "顶部": "top", "上": "top", "上方": "top", "顶端": "top",
            "top_right": "top_right", "右上": "top_right", "右上角": "top_right",
            "bottom_right": "bottom_right", "右下": "bottom_right", "右下角": "bottom_right",
            "top_left": "top_left", "左上": "top_left", "左上角": "top_left",
            "bottom_left": "bottom_left", "左下": "bottom_left", "左下角": "bottom_left",
        },
        "apply": "",
    },
    "close_mode": {
        "values": ["彻底退出", "最小化到托盘"],
        "aliases": {
            "彻底退出": "彻底退出", "退出": "彻底退出", "关闭程序": "彻底退出",
            "最小化到托盘": "最小化到托盘", "托盘": "最小化到托盘", "最小化": "最小化到托盘",
        },
        "apply": "",
    },
    # ---------- 搜索 / 卡片 ----------
    "search_card_size": {
        "values": ["small", "medium", "large"],
        "aliases": {
            "small": "small", "小": "small", "小卡": "small",
            "medium": "medium", "中": "medium", "中卡": "medium",
            "large": "large", "大": "large", "大卡": "large",
        },
        "apply": "reload",
    },
    "search_view": {
        "values": ["tile", "grid"],
        "aliases": {
            "tile": "tile", "平铺": "tile", "瓦片": "tile",
            "grid": "grid", "网格": "grid", "井字": "grid",
        },
        "apply": "reload",
    },
    "plugin_view": {
        "values": ["grid", "list"],
        "aliases": {
            "grid": "grid", "井字": "grid", "网格": "grid",
            "list": "list", "列表": "list",
        },
        "apply": "reload",
    },
    # ---------- 资源来源 ----------
    "resource_source": {
        "values": ["cloud", "local"],
        "aliases": {
            "cloud": "cloud", "云端": "cloud", "在线": "cloud",
            "local": "local", "本地": "local", "离线": "local",
        },
        "apply": "reload",
    },
    "releases_source": {
        "values": ["official", "mirror"],
        "aliases": {
            "official": "official", "官方": "official",
            "mirror": "mirror", "镜像": "mirror",
        },
        "apply": "",
    },
    "update_auto_check": {
        "values": ["corner", "off", "notify"],
        "aliases": {
            "corner": "corner", "角落": "corner", "角标": "corner",
            "off": "off", "关": "off", "关闭": "off",
            "notify": "notify", "提示": "notify",
        },
        "apply": "",
    },
    "update_channel": {
        "values": ["all", "stable", "beta"],
        "aliases": {
            "all": "all", "全部": "all",
            "stable": "stable", "稳定": "stable", "正式": "stable",
            "beta": "beta", "测试": "beta",
        },
        "apply": "",
    },
}

# ======================================================================
# 敏感项 / 只读项（Agent 一律不许改）
# ======================================================================
# ⚠️ 为什么必须挡：api_key 一旦被模型改写，用户就登不上他的服务商；
#   *_profiles / *_migrated 是程序内部状态，改了会让档案系统错乱。
READONLY_KEYS = {
    "api_key", "api_key_enc", "license_key", "dev_mode_key", "dev_mode_admin",
    "ai_provider_profiles", "ai_profiles_migrated", "ai_profile_id",
    "ai_thinking_level", "gcp_ai_agent_tools_off", "gcp_plugin_maker_options",
    "local_resource_dir", "download_save_dir", "last_search",
    "_migrated_show_github_default", "update_muted_tag",
    "open_settings_on_restart", "debug_info_enabled_Galen563", "debug_info_enabled_Cyric373",
}

# 前缀判定（按服务商分槽的 Key：api_key_enc_deepseek 之类）
READONLY_PREFIXES = ("api_key", "dev_mode_", "debug_info_enabled_", "_")


def is_readonly(key: str) -> bool:
    """这个键 Agent 能不能改"""
    name = str(key or "").strip()
    if not name:
        return True
    if name in READONLY_KEYS:
        return True
    return any(name.startswith(p) for p in READONLY_PREFIXES)


# 布尔型设置（"on/off" 之外的那些开关）
BOOL_KEYS = {
    "ai_enabled", "ai_polish_enabled", "ai_sidebar_mode", "auto_search",
    "deploy_mode", "dev_mode_enabled", "download_speed_limit_enabled",
    "gcp_ai_agent_enabled", "gcp_plugin_maker_enabled", "hotkey_enabled",
    "limit_token_output", "minimize_to_tray", "nav_hover_expand",
    "nav_indicator_bounce", "notify_enabled", "scroll_inertia",
    "search_show_github", "search_show_view_switch", "splash_screen_enabled",
    "startup_with_windows",
}


# ======================================================================
# 解析 / 校验
# ======================================================================
def _norm(text) -> str:
    """别名匹配用的归一化：小写 + 去空白（中文不动）"""
    return str(text if text is not None else "").strip().lower()


def resolve_value(key: str, value):
    """把一个"用户/模型说的人话"解析成**该设置项的合法值**

    返回 (ok, resolved, hint)：
      · ok=True  → resolved 是可以直接写进设置的值；
      · ok=False → hint 给模型看的一句话（"可选值是 云母 / 毛玻璃 / 亚克力"）。

    ⚠️⚠️ 这就是修「我说喜欢毛玻璃，它说没有、直接执行失败」的地方：
       模型传 "毛玻璃" → 别名表命中 → 落成 "glass" → 写入成功。
    """
    name = str(key or "").strip()
    spec = SETTING_VALUES.get(name)
    if not spec:
        # 没登记的键：不当枚举处理，交给调用方按旧值类型转换
        return True, value, ""

    values = spec.get("values") or []
    aliases = spec.get("aliases") or {}
    raw = _norm(value)

    if not raw:
        return False, None, ("%s 需要一个值，可选：%s"
                             % (name, " / ".join(values)))

    # ① 已经是合法值（含大小写差异）
    for v in values:
        if _norm(v) == raw:
            return True, v, ""

    # ② 别名表
    if raw in aliases:
        return True, aliases[raw], ""

    # ③ 值里"包含"某个别名（模型爱说"切成毛玻璃效果"这种长句）
    for alias, target in aliases.items():
        a = _norm(alias)
        if a and a in raw:
            return True, target, ""

    # ④ 都不中：如实告诉模型可选项
    readable = " / ".join(values)
    cn = [f"{v}（{k}）" for k, v in aliases.items() if len(_norm(k)) <= 6][:6]
    return False, None, ("%s 不接受「%s」。可选值：%s"
                         % (name, value, readable)
                         + (("；也认这些说法：%s" % "、".join(cn)) if cn else ""))


# ======================================================================
# 中文显示名 → 设置键名
# ======================================================================
# ⚠️⚠️ 为什么必须有这张表（用户实测的失败）：
#   用户说「通知位置改成右下角」，AI 去查 notification_position / notify_position /
#   通知 / 弹窗 / corner —— 一个都查不到，最后如实回"设置里根本没有这一项"。
#   而实际上设置里明明有（键名 toast_position，界面上显示"提示框位置"）。
#   根因：模型只看到 toast_position 这个英文键，不知道它对应界面上的哪一行；
#   用户说的是"通知位置"，模型就自己编了一堆同义词去碰运气。
#   修法：① 这张中英对照表（人话 → 键名）；
#         ② list_settings 每项带上 label（界面显示名），模型一看就知道对应关系。
KEY_LABELS = {
    # "主题"这个短词必须有：用户/AI 常说"把主题改成深色"，而 label_to_key 的包含
    # 匹配是 "label in raw"（"主题模式" 不是 "主题" 的子串）→ 旧表解析"主题"会失败。
    # 说全"主题效果/主题模式"时靠**最长匹配**仍然落到更具体的那一项，不会抢。
    "theme": ("主题模式", "主题", "theme mode"),
    "theme_effect": ("主题效果", "材质效果", "theme effect"),
    # ⚠️ 用户实测的失败（agent 回"没有名为 配色 的设置项"）：模型直接把界面上的
    #   关键词说成"配色"，而这里只有"组件配色"/"强调色" —— label_to_key 的包含匹配是
    #   "label in raw"，"组件配色"不是"配色"的子串，于是解析失败。别名宁多勿少。
    # ⚠️ 用户实测的失败（agent 回"没有名为 配色 的设置项"）：模型直接把界面上的
    #   关键词说成"配色"，而这里只有"组件配色"/"强调色" —— label_to_key 的包含匹配是
    #   "label in raw"，"组件配色"不是"配色"的子串，于是解析失败。别名宁多勿少。
    #   "主题颜色"要单独列：只有"主题色"时，"把主题颜色改成橙色"里 主题色 不连续命中，
    #   会被更短的"主题"抢走 → 落到 theme 上（值还不合法）。
    "accent_color": ("组件配色", "强调色", "配色", "主题色", "主题颜色", "组件颜色", "颜色",
                     "accent color", "accent"),
    "ui_font_family": ("字体", "界面字体", "font"),
    "ui_animation": ("UI 动画", "动画", "animation"),
    "language": ("语言", "界面语言", "language"),
    "toast_position": ("提示框位置", "通知位置", "通知框位置", "提示位置", "toast position"),
    "close_mode": ("关闭行为", "关闭窗口", "close mode"),
    "search_card_size": ("卡片大小", "card size"),
    "search_view": ("卡片排版", "视图", "view"),
    "plugin_view": ("插件排版", "plugin view"),
    "resource_source": ("资源来源", "resource source"),
    "releases_source": ("Releases 来源", "release source"),
    "update_auto_check": ("自动检查更新", "update check"),
    "update_channel": ("更新渠道", "update channel"),
    "startup_with_windows": ("开机自启", "开机启动", "autostart"),
    "minimize_to_tray": ("最小化到托盘", "minimize to tray"),
    "notify_enabled": ("启用提示", "通知开关", "notifications"),
    "hotkey_enabled": ("全局热键", "快捷键开关", "hotkey"),
    "hotkey_search": ("搜索热键", "search hotkey"),
    "hotkey_ai": ("AI 热键", "ai hotkey"),
    "hotkey_browser": ("浏览器热键", "browser hotkey"),
    "auto_search": ("自动搜索", "auto search"),
    "search_show_github": ("Github 按钮", "github button"),
    "search_show_view_switch": ("视图切换按钮", "view switch"),
    "splash_screen_enabled": ("启动动画", "splash"),
    "scroll_inertia": ("滚动惯性", "惯性", "scroll inertia"),
    "scroll_inertia_strength": ("滚动惯性强度", "inertia strength"),
    "nav_hover_expand": ("侧栏悬停展开", "nav hover expand"),
    "nav_indicator_bounce": ("侧栏指示器回弹", "nav indicator bounce"),
    "dev_mode_enabled": ("开发者模式", "dev mode"),
    "deploy_mode": ("部署模式", "deploy mode"),
    "download_threads": ("下载线程数", "download threads"),
    "download_retry_count": ("下载重试次数", "download retry"),
    "download_speed_limit_enabled": ("限速开关", "speed limit"),
    "download_speed_limit": ("下载限速", "speed limit value"),
    "download_source": ("下载来源", "download source"),
    "ai_enabled": ("开启 GCP-AI", "ai enabled"),
    "ai_polish_enabled": ("启用润色", "ai polish"),
    "ai_sidebar_mode": ("侧边栏 AI", "ai sidebar"),
    "ai_reply_mode": ("回复模式", "reply mode"),
    "ai_reply_language": ("回复语言", "reply language"),
    "ai_context_rounds": ("上下文轮数", "context rounds"),
    "ai_thinking": ("思考档位", "thinking"),
    "ai_chat_mode": ("对话模式", "chat mode"),
    "gcp_ai_agent_enabled": ("AI Agent 总开关", "agent enabled"),
    "gcp_plugin_maker_enabled": ("插件制作辅助", "plugin maker"),
}

_LABEL_TO_KEY = None


def label_to_key(text: str):
    """把用户/AI 说的人话（中文名/英文名）解析成设置键名；认不出返回空串

    ⚠️ 这是"通知位置"能不能被听懂的关键。
    """
    global _LABEL_TO_KEY
    if _LABEL_TO_KEY is None:
        table = {}
        for key, labels in KEY_LABELS.items():
            table[_norm(key)] = key
            for label in labels:
                table[_norm(label)] = key
        _LABEL_TO_KEY = table
    raw = _norm(text)
    if not raw:
        return ""
    if raw in _LABEL_TO_KEY:
        return _LABEL_TO_KEY[raw]
    # 包含命中（"把通知位置改成右下" ⊃ "通知位置"）—— 取**最长**匹配，避免短词误中
    best = ""
    best_len = 0
    for label, key in _LABEL_TO_KEY.items():
        if len(label) >= 2 and label in raw and len(label) > best_len:
            best, best_len = key, len(label)
    return best


def key_label(key: str) -> str:
    """设置键 → 界面上的中文显示名（给 list_settings 用）"""
    labels = KEY_LABELS.get(str(key or ""))
    return labels[0] if labels else ""


def is_enum(key: str) -> bool:
    return str(key or "") in SETTING_VALUES


def apply_hint(key: str) -> str:
    """这个键改完之后前端要怎么生效（空串 = 落盘即可）"""
    spec = SETTING_VALUES.get(str(key or ""))
    return str((spec or {}).get("apply") or "")


def coerce(key: str, value, old):
    """按旧值类型把值转成正确类型（布尔/整数/浮点/字符串）"""
    try:
        if is_enum(key):
            return value
        if isinstance(old, bool):
            return _to_bool(value)
        if isinstance(old, int) and not isinstance(old, bool):
            return int(value)
        if isinstance(old, float):
            return float(value)
        return str(value) if value is not None else ""
    except (TypeError, ValueError):
        return value


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "开", "开启", "是", "启用")


# 布尔开关的中文说法（set_setting 收到"打开热键"这类值时用）
BOOL_TRUE_WORDS = ("开", "开启", "打开", "启用", "是", "yes", "on", "true", "1", "勾选")
BOOL_FALSE_WORDS = ("关", "关闭", "禁用", "否", "no", "off", "false", "0", "取消")


__all__ = [
    "SETTING_VALUES", "READONLY_KEYS", "BOOL_KEYS",
    "is_readonly", "is_enum", "resolve_value", "apply_hint", "coerce",
    "KEY_LABELS", "label_to_key", "key_label",
]
