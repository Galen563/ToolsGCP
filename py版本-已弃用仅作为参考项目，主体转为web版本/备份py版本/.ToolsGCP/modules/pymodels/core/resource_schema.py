"""资源库 schema（唯一事实来源）：字段表 + 枚举 + normalize() + validate() + 访问器。

其它模块不再自己拆 category、不再自己拼 tags、不再写 `code or id`。

⚠️ 磁盘上的字段名不改；规范形态只改两件事：category 变成 list[str]、tags 不再重复
category 的值。normalize() / validate() 永不抛异常（资源库是用户手改过的数据）。
"""

# 资源库文件形态的版本：2.0.0 -> 2.1.0（category 变数组、tags 去重）
SCHEMA_VERSION = "2.1.0"

DEFAULT_LANGUAGE = "简体中文"
LANGUAGE_FALLBACK = ("简体中文", "繁體中文", "English")

# 一格多值的分隔符。
# ⚠️ 不含 `/`：库里真有「建筑/设计」这种名字带斜杠的类别，拆了就把正常类别拆没了。
# ⚠️ 也不按空格拆：标签里允许有空格（split_tags 写盘前才按空格拆输入框）。
CATEGORY_SPLIT_CHARS = (",", "，", "、", ";", "；")

# 适用系统（闭集）。`全平台` 是元值：表示覆盖全部平台，不是"同时是 Windows 和 macOS"。
# ⚠️ 顺序就是界面上的顺序（制作器胶囊、搜索页筛选项都用它）。
SYSTEMS = ("全平台", "Windows", "macOS", "Android", "iOS", "Linux", "web", "其他")

# CPU 架构（闭集）。
# ⚠️ `Apple Silicon` 和 `arm64` 语义有重叠但不合并：库里两者各有一批条目，
#    合并等于替用户改数据、还会改掉搜索页的筛选项。这里只统一大小写。
ARCHITECTURES = ("x64", "x86", "arm64", "arm", "Apple Silicon", "其他")

# 读进来的别名 -> 规范值（只归一大小写/常见写法，不改原意）；
# 认不出来的值原样保留，让 validate 报出来，不悄悄吞掉用户填的东西。
_SYSTEM_ALIASES = {
    "windows": "Windows", "win": "Windows", "win32": "Windows",
    "macos": "macOS", "mac os": "macOS", "osx": "macOS", "mac os x": "macOS",
    "mac": "macOS",
    "linux": "Linux", "gnu/linux": "Linux",
    "android": "Android",
    "ios": "iOS", "ipados": "iOS",
    "web": "web", "网页": "web", "web 版": "web",
    "全平台": "全平台", "all": "全平台", "cross-platform": "全平台",
    "其他": "其他", "other": "其他",
}

_ARCH_ALIASES = {
    "x64": "x64", "x86_64": "x64", "amd64": "x64", "64位": "x64",
    "x86": "x86", "i386": "x86", "i686": "x86", "32位": "x86",
    "arm64": "arm64", "aarch64": "arm64",
    "arm": "arm", "arm32": "arm", "armv7": "arm",
    "apple silicon": "Apple Silicon", "apple-silicon": "Apple Silicon",
    "m1": "Apple Silicon", "m2": "Apple Silicon", "m3": "Apple Silicon",
    "其他": "其他", "other": "其他",
}

# ============ 字段表 ============
# kind 的含义：
#   text       单行/多行文本            i18n       可写成三语言字典的文本
#   categories 类别（规范形态 list[str]） tags       补充标签 list[str]
#   text_list  普通字符串数组           enum_list  闭集字符串数组（读入时归一大小写）
#   variants   多版本列表 [{key,label,url}]         raw        原样保留（绝不丢字段）
#
# doc 是给人看的：docs/resources-schema.md 里逐字段的说明就是这份表。
FIELDS = {
    "id": {
        "kind": "text", "required": True,
        "doc": "英文 slug 主键（小写字母/数字/连字符），如 localsend。详情页、图标名按它定位",
    },
    "code": {
        "kind": "text", "required": True,
        "doc": "系统分配的资源编码 TG-000001。收藏夹、部署清单、AI 工具都拿它当主键",
    },
    "name": {
        "kind": "i18n", "required": True,
        "doc": "名称：卡片标题、详情页标题。可写成三语言字典",
    },
    "category": {
        "kind": "categories", "required": False,
        "doc": "类别列表：搜索页「按类别排序」的分组依据、类别筛选的依据、定制页喜好的来源",
    },
    "tags": {
        "kind": "tags", "required": False,
        "doc": "补充标签（不含 category 里已有的值）：详情页胶囊、搜索页标签筛选、AI 检索词",
    },
    "icon": {
        "kind": "text", "required": False,
        "doc": "图标文件名（如 localsend.png）；所在目录见 metadata.icon_dir，加载时补成相对路径",
    },
    "url": {
        "kind": "text", "required": False,
        "doc": "官网 / 官方下载页地址",
    },
    "github": {
        "kind": "text", "required": False,
        "doc": "开源仓库完整地址（GitHub / GitCode / Gitee / GitLab 都写这里）",
    },
    "download_url": {
        "kind": "text", "required": False,
        "doc": "直接下载地址；留空时部署页退回用 github",
    },
    "chat_url": {
        "kind": "text", "required": False,
        "doc": "交流群 / 社区地址（Discord、QQ 群等）",
    },
    "author_url": {
        "kind": "text", "required": False,
        "doc": "作者主页地址",
    },
    "description": {
        "kind": "i18n", "required": False,
        "doc": "简介：卡片上那一行、详情页标题下的小字。**一句话，≤100 字**",
    },
    "intro": {
        "kind": "i18n", "required": False,
        "doc": "应用介绍：详情页「应用介绍」区块的正文，可以写几段。留空时退回 description",
    },
    "supplement": {
        "kind": "i18n", "required": False,
        "doc": "补充说明：接在「应用介绍」正文后面那一段（注意事项、平台差异等）",
    },
    "listed_at": {
        "kind": "text", "required": False,
        "doc": "上架时间 \"YYYY-MM-DD HH:MM:SS\"；搜索页「更新时间」筛选按它算",
    },
    "systems": {
        "kind": "enum_list", "required": False, "enum": SYSTEMS,
        "doc": "适用系统：可多选，取值见 SYSTEMS。" + "/".join(SYSTEMS),
    },
    "architectures": {
        "kind": "enum_list", "required": False, "enum": ARCHITECTURES,
        "doc": "CPU 架构：可多选，取值见 ARCHITECTURES。" + "/".join(ARCHITECTURES),
    },
    "variants": {
        "kind": "variants", "required": False,
        "doc": "多版本（如 Trae 的国内版/国际版）：[{key,label,url}]；配合 default_variant 使用",
    },
    "default_variant": {
        "kind": "text", "required": False,
        "doc": "默认版本 key：加载时把它的 url/github/... 提升到顶层，老读取方不用改",
    },
}

# 落盘时的字段顺序（读起来有固定次序，diff 也好看）。表里没有的字段按原顺序追加在后面。
FIELD_ORDER = tuple(FIELDS.keys())

# 必填字段（缺了就是真问题：id 决定条目身份，code 是收藏/部署/AI 的主键，name 要显示）
REQUIRED_FIELDS = tuple(k for k, spec in FIELDS.items() if spec.get("required"))

# 三个文本字段的职责对照：专门导出，给文档和制作器表单提示复用
TEXT_ROLES = {
    "description": "一句话简介：卡片上显示的那一行（≤100 字）",
    "intro": "应用介绍：详情页正文，可以写几段；留空时详情页退回显示简介",
    "supplement": "补充说明：接在应用介绍后面的一段（注意事项、平台差异等）",
}


# ============ 基础取值工具（永不抛异常）============
def _text(value) -> str:
    """任何值 -> 去掉首尾空白的字符串（None -> ""）"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).strip()


def first_text(value, language: str = DEFAULT_LANGUAGE) -> str:
    """从"可能是多语言字典 / 列表 / 标量"的值里取一个字符串

    按 当前语言 → 简中 → 繁中 → 英文 → 第一个非空值 的顺序回退。
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in (language,) + LANGUAGE_FALLBACK:
            if key and key in value:
                text = first_text(value.get(key), language)
                if text:
                    return text
        for item in value.values():
            text = first_text(item, language)
            if text:
                return text
        return ""
    if isinstance(value, (list, tuple, set)):
        for item in value:
            text = first_text(item, language)
            if text:
                return text
        return ""
    return _text(value)


def as_text_list(value, language: str = DEFAULT_LANGUAGE) -> list:
    """任何值 -> 非空字符串列表（递归展开多语言字典 / 嵌套列表，去重保序）"""
    out: list = []
    _collect_text(value, language, out)
    return out


def _collect_text(value, language: str, out: list):
    if value is None:
        return
    if isinstance(value, dict):
        # 多语言字典：只取当前语言那一份（取不到再回退），不要把三种语言都当成值
        text = first_text(value, language)
        if text:
            out.append(text)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_text(item, language, out)
        return
    text = _text(value)
    if text:
        out.append(text)


def split_multi(text, language: str = DEFAULT_LANGUAGE) -> list:
    """把 "工具,游戏" 这种一格多值拆成多个（分隔符见 CATEGORY_SPLIT_CHARS）"""
    out: list = []
    for value in as_text_list(text, language):
        parts = [value]
        for char in CATEGORY_SPLIT_CHARS:
            expanded: list = []
            for part in parts:
                expanded.extend(part.split(char))
            parts = expanded
        out.extend(p.strip() for p in parts if p.strip())
    return dedup(out)


def dedup(values) -> list:
    """去重但保留原顺序"""
    seen, out = set(), []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _parse_enums(value, aliases: dict, allowed) -> list:
    """枚举数组：字符串/数组都收，按别名表归一，认不出来的原样留下"""
    out = []
    for raw in as_text_list(value):
        key = raw.strip().lower()
        out.append(aliases.get(key, raw))
    return dedup([v for v in out if v])


# ============ 解析（读）============
def parse_categories(value, language: str = DEFAULT_LANGUAGE) -> list:
    """任何历史形态的 category -> 规范形态 list[str]（"工具,游戏" / 列表 / 多语言都收）"""
    return split_multi(value, language)


def categories_of(item: dict, language: str = DEFAULT_LANGUAGE) -> list:
    """取一条资源的类别列表（规范/历史形态都能读）"""
    if not isinstance(item, dict):
        return []
    return parse_categories(item.get("category"), language)


def tags_of(item: dict, language: str = DEFAULT_LANGUAGE) -> list:
    """取一条资源的标签列表

    ⚠️ 取的是原样（历史数据可能含与类别重复的值）；要干净标签请先 normalize()，
    validate() 才能靠它把重复项报出来。
    """
    if not isinstance(item, dict):
        return []
    return split_multi(item.get("tags"), language)


def keywords_of(item: dict, language: str = DEFAULT_LANGUAGE) -> list:
    """检索词 = 类别 ∪ 标签（搜索页筛选、AI 清单、关键词匹配都该用这一份）
    （以前类别是抄在 tags 里的，拆开后必须看并集，否则会漏筛）"""
    return dedup(categories_of(item, language) + tags_of(item, language))


def systems_of(item: dict, language: str = DEFAULT_LANGUAGE) -> list:
    """取适用系统列表（已归一大小写）"""
    if not isinstance(item, dict):
        return []
    return _parse_enums(item.get("systems"), _SYSTEM_ALIASES, SYSTEMS)


def architectures_of(item: dict, language: str = DEFAULT_LANGUAGE) -> list:
    """取 CPU 架构列表（已归一大小写）"""
    if not isinstance(item, dict):
        return []
    return _parse_enums(item.get("architectures"), _ARCH_ALIASES, ARCHITECTURES)


def id_of(item: dict) -> str:
    """取标识 id（slug）"""
    return _text(item.get("id")) if isinstance(item, dict) else ""


def code_of(item: dict) -> str:
    """取资源编码（收藏/部署/AI 的主键）；没有 code 的老条目退回 id"""
    if not isinstance(item, dict):
        return ""
    return _text(item.get("code")) or _text(item.get("id"))


def name_of(item: dict, language: str = DEFAULT_LANGUAGE) -> str:
    """取名称（多语言字典按当前语言）"""
    return first_text(item.get("name"), language) if isinstance(item, dict) else ""


def summary_of(item: dict, language: str = DEFAULT_LANGUAGE) -> str:
    """取"一句话简介"：description 优先，没填就退回 intro 的第一句（卡片和 AI 清单用它）"""
    if not isinstance(item, dict):
        return ""
    text = first_text(item.get("description"), language)
    if text:
        return text
    intro = first_text(item.get("intro"), language)
    if intro:
        for sep in ("。", "！", "？", ".", "!", "?"):
            head = intro.split(sep)[0].strip()
            if head:
                return head + sep
        return intro
    return ""


# 链接字段的展示顺序（官网 -> 仓库 -> 下载 -> 作者 -> 交流）
LINK_FIELDS = ("url", "github", "download_url", "author_url", "chat_url")


def links_of(item: dict) -> list:
    """取一条资源的全部链接：[{field, url}]，顺序固定

    变体里的链接也算进来（field 写成 `variants[<key>].url`）。
    """
    if not isinstance(item, dict):
        return []
    out = []
    for field in LINK_FIELDS:
        url = _text(item.get(field))
        if url:
            out.append({"field": field, "url": url})
    variants = item.get("variants")
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            key = _text(variant.get("key")) or "?"
            for field in ("url", "download_url", "github"):
                url = _text(variant.get(field))
                if url:
                    out.append({"field": f"variants[{key}].{field}", "url": url})
    return out


# ============ 规范化（写）============
def normalize(item, language: str = DEFAULT_LANGUAGE) -> dict:
    """把任何历史形态的一条资源压成规范形态（永不抛异常，绝不丢字段）

    · 字段名一个不改，不认识的字段原样保留，落盘顺序按 FIELD_ORDER（幂等）；
    · category 一律 list[str]；tags 去掉与 category 重复的值；
    · 多语言字典按 language 解析；空的可选字段不写，必填字段恒在。
    """
    if not isinstance(item, dict):
        return {}

    values: dict = {}
    for field in FIELD_ORDER:
        if field not in item:
            continue
        spec = FIELDS[field]
        values[field] = _normalize_value(spec["kind"], item.get(field), language, spec)

    # ⚠️ 这一步是本次重构的核心：tags 不能重复 category 的值。放在字段循环之后算，
    #    类别先解析出来才能拿它去比。
    if "tags" in values:
        cats = set(values.get("category") or [])
        values["tags"] = [t for t in values["tags"] if t not in cats]

    out: dict = {}
    for field in FIELD_ORDER:
        if field not in values:
            continue
        spec = FIELDS[field]
        if values[field] or spec.get("required"):
            out[field] = values[field]
    # 未知字段：原样保留（顺序也按原来的，保证幂等）
    for key, value in item.items():
        if key not in FIELDS:
            out[key] = value
    return out


def _normalize_value(kind: str, raw, language: str, spec: dict):
    if kind == "text":
        return _text(raw)
    if kind == "i18n":
        return first_text(raw, language)
    if kind == "categories":
        return parse_categories(raw, language)
    if kind == "tags":
        return split_multi(raw, language)
    if kind == "text_list":
        return as_text_list(raw, language)
    if kind == "enum_list":
        aliases = _SYSTEM_ALIASES if spec.get("enum") is SYSTEMS else _ARCH_ALIASES
        return _parse_enums(raw, aliases, spec.get("enum") or ())
    if kind == "variants":
        return _normalize_variants(raw, language)
    return raw


def _normalize_variants(raw, language: str) -> list:
    """变体列表：已知字段转字符串，认不出的键原样留着"""
    if not isinstance(raw, list):
        if isinstance(raw, dict):
            raw = [raw]          # 只有一个变体却写成了字典：包一层，别丢
        else:
            return []
    out = []
    for variant in raw:
        if not isinstance(variant, dict):
            continue
        row = {}
        for key, value in variant.items():
            # 变体都是平的 {key,label,url}；值一律取文本（多语言字典按当前语言）
            row[key] = first_text(value, language)
        if row:
            out.append(row)
    return out


def normalize_all(items, language: str = DEFAULT_LANGUAGE) -> list:
    """批量规范化（保留非字典项，交给 validate 去报）"""
    return [normalize(item, language) for item in (items or [])]


# ============ 校验 ============
def validate(item) -> list:
    """校验一条资源，返回人类可读的问题列表（永不抛异常，没问题就是 []）

    对原始形态和规范形态都能用：取值全走宽容访问器，拿历史数据调也能报出"标签混了类别"。
    """
    problems: list = []
    try:
        if not isinstance(item, dict):
            return [f"条目不是对象：{type(item).__name__}"]

        for field in REQUIRED_FIELDS:
            if not _text(item.get(field)):
                problems.append(f"缺少必填字段：{field}")

        rid, code = _text(item.get("id")), _text(item.get("code"))
        if rid and code and rid.lower() == code.lower():
            problems.append(f"id 与 code 相同（{rid}）：两种标识分不开，收藏/部署会指错")

        cats = categories_of(item)
        for field, values, aliases, allowed, label in (
                ("systems", systems_of(item), _SYSTEM_ALIASES, SYSTEMS, "适用系统"),
                ("architectures", architectures_of(item), _ARCH_ALIASES,
                 ARCHITECTURES, "CPU 架构")):
            for value in values:
                if value in allowed or value.strip().lower() in aliases:
                    continue
                problems.append(
                    f"{field} 的值「{value}」不在允许范围（{label}）：{'/'.join(allowed)}")

        dup = [t for t in tags_of(item) if t in cats]
        if dup:
            problems.append("tags 里重复了 category 的值：" + "、".join(dup))

        for field in ("url", "github", "download_url", "author_url", "chat_url"):
            value = _text(item.get(field))
            if value and not value.lower().startswith(("http://", "https://")):
                problems.append(f"{field} 不是完整网址：{value}")

        if isinstance(item.get("category"), (int, float, bool)):
            problems.append(f"category 类型可疑：{type(item['category']).__name__}")
    except Exception as exc:                      # 兜底：校验自己绝不能把程序带崩
        problems.append(f"校验时出现意外错误：{exc}")
    return problems


def validate_all(items) -> dict:
    """批量校验，返回 {条目标识: [问题]}（只含真有问题的条目）"""
    out = {}
    for index, item in enumerate(items or []):
        problems = validate(item)
        if problems:
            key = code_of(item) or id_of(item) or f"#{index}"
            out[key] = problems
    return out


__all__ = [
    "SCHEMA_VERSION", "DEFAULT_LANGUAGE", "LANGUAGE_FALLBACK",
    "CATEGORY_SPLIT_CHARS", "SYSTEMS", "ARCHITECTURES",
    "FIELDS", "FIELD_ORDER", "REQUIRED_FIELDS", "TEXT_ROLES", "LINK_FIELDS",
    "first_text", "as_text_list", "split_multi", "dedup",
    "parse_categories", "categories_of", "tags_of", "keywords_of",
    "systems_of", "architectures_of",
    "id_of", "code_of", "name_of", "summary_of", "links_of",
    "normalize", "normalize_all", "validate", "validate_all",
]
