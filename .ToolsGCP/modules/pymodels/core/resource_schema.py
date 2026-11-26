"""资源库 schema（唯一事实来源）：字段表 + 枚举 + normalize() + validate() + 访问器。
其它模块不再自己拆 category、不再自己拼 tags、不再写 `code or id`。
⚠️ 磁盘上的字段名不改；规范形态只改这几件事：category 变成 list[str]、tags 原样保留（m07514：不再静默丢掉与 category 同名的标签）、links 整行清洗（协议白名单 / 行数上限 / 三语同值塌缩，见 normalize_links）、repos 逐行清洗并与 github 互填（task-26：多组开源仓库，见 normalize_repos / _sync_github_repos）。
normalize() / validate() 永不抛异常（资源库是用户手改过的数据）。
"""

# 资源库文件形态的版本：2.0.0 -> 2.1.0（category 变数组、tags 规范成 list）
SCHEMA_VERSION = "2.1.0"

DEFAULT_LANGUAGE = "简体中文"
LANGUAGE_FALLBACK = ("简体中文", "繁體中文", "English")

# 一格多值的分隔符。
# ⚠️ 不含 `/`：库里真有建筑/设计这种名字带斜杠的类别，拆了就把正常类别拆没了。
# ⚠️ 也不按空格拆：标签里允许有空格（split_tags 写盘前才按空格拆输入框）。
CATEGORY_SPLIT_CHARS = (",", "，", "、", ";", "；")

# 用户自定义链接（links 字段）：行数上限与网址协议白名单。
# 为什么限 20 行：制作器「添加」按钮可以无限加行，手改 JSON 更能塞进几百行；
# 详情页渲染和虚拟列表测高都会被拖垮。超出部分 normalize 截断、validate 报出来，
# 不静默吞用户的行。
LINKS_MAX_ROWS = 20

# ⚠️ 安全线：只放 http/https。javascript: / data: / file: 这类可执行或本地协议
#    会被 WebView2 当真链接打开（详情页「点击打开」走原生 shell），等于给一个
#    用户可任意填写的字段开了注入面 —— 所以做**白名单**而不是黑名单：normalize、
#    validate、resolve_links 三处统一用它，不合规的整行丢弃，绝不落盘。
URL_SCHEME_PREFIXES = ("http://", "https://")

# 多组开源仓库（repos 字段，task-26）：平台闭集 + 行数上限。
# ⚠️ platform 是**闭集**而不是自由文本：制作器「开源仓库」每行是下拉框
#    （GitHub / GitCode / Gitee / GitLab / 自定义），值域定死才能：
#      · 让「由 url 前缀反推平台」有唯一答案（否则同一家仓库各写各的）；
#      · 让详情页能按平台画图标、按平台走 Releases/下载分支。
#    认不出的 url 一律归 custom（「自定义」就是给这个兜底用的，不是非法值）。
#    "none" 不在集合里 —— 那是前端表单「不开源」的占位选项，normalize 见到
#    就整行丢弃（这种行没有 url，留着只会让 github 主仓库取到空串）。
REPOS_PLATFORMS = ("github", "gitcode", "gitee", "gitlab", "custom")

# 行数上限：与 LINKS_MAX_ROWS 同量级。为什么要限：制作器的「+」按钮可以无限加，
# 手改 JSON 更能塞进几百行；详情页逐行渲染与卡片按钮都会被拖垮。
# 超出部分 normalize 截断、validate 报出来（不静默吞用户的行，与 links 同一纪律）。
REPOS_MAX_ROWS = 20

# 仓库主机名 -> 平台。**按 host 判而不是按整串前缀判**，两个原因：
#  · http:// 与 https:// 都该认（库里真有老条目写 http://github.com/...）；
#  · www. 前缀、尾斜杠都不该影响判定。
# ⚠️ 只认官方站点（host 相等或是它的子域）：gitlab.example.com 这类私有化实例
#    归 custom，不硬猜成 gitlab —— 详情页/下载页会按平台去拼 API，猜错就是拿
#    用户私有实例的地址打公共 API（等于泄露地址）。
_REPO_HOST_PLATFORMS = (
    ("github.com", "github"),
    ("gitcode.com", "gitcode"),
    ("gitee.com", "gitee"),
    ("gitlab.com", "gitlab"),
)

# 适用系统（闭集）。`全平台` 是元值：表示覆盖全部平台，不是"同时是 Windows 和 macOS"。
# ⚠️ 顺序就是界面上的顺序（制作器胶囊、搜索页筛选项都用它）。
# ⚠️ 需求 m04188 第④项扩充：用户说「在适用系统那里增加 Apple watch 等常用的」，
#    他指的其实是**系统名**而不是设备（原话也承认"也许我说的是系统而不是什么小天才手表"），
#    所以加的是 watchOS / tvOS / iPadOS / visionOS 这类**真操作系统**，
#    外加 ChromeOS（Chromebook）与 HarmonyOS（鸿蒙）这两个问得最多的。
#    取值一律用官方英文写法：中文界面也直接显示英文专名（"watchOS"没人写成"手表OS"），
#    所以不必再往 common_language.json 加 term_* 键。
SYSTEMS = ("全平台", "Windows", "macOS", "Linux", "Android", "iOS",
           "iPadOS", "watchOS", "tvOS", "visionOS", "HarmonyOS", "ChromeOS",
           "web", "其他")

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
    "ios": "iOS",
    # ⚠️ "ipados" 以前归一到 "iOS"，本轮 iPadOS 成了独立枚举，再归到 iOS 就把用户
    #    明确写的数据改成另一个系统了。历史数据里没有过 "ipados" 写法（资源库只用过
    #    iOS/Android 这类），所以这次改归一目标不会动到既有 52 条中的任何一条。
    "ipados": "iPadOS", "ipad": "iPadOS", "ipad os": "iPadOS",
    "watchos": "watchOS", "watch os": "watchOS", "apple watch": "watchOS",
    "tvos": "tvOS", "tv os": "tvOS", "apple tv": "tvOS",
    "visionos": "visionOS", "vision os": "visionOS", "vision pro": "visionOS",
    "harmonyos": "HarmonyOS", "harmony": "HarmonyOS", "鸿蒙": "HarmonyOS",
    "hongmeng": "HarmonyOS", "harmony os": "HarmonyOS",
    "chromeos": "ChromeOS", "chrome os": "ChromeOS", "chromebook": "ChromeOS",
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
#   links      用户自定义「标签+链接」行 [{label,url}]；label/url 可写纯字符串或
#              三语言字典——行内字典**不压平**（前端切语言要用），与 i18n 是两种语义
#doc 是给人看的：docs/resources-schema.md 里逐字段的说明就是这份表。
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
        "doc": "**主仓库**地址 = repos 里第一行有效仓库的 url（task-26 语义收紧）。",
    },
    # task-26：一条资源可以同时挂多个开源仓库（国内镜像 / 国际主仓 / 自托管）。
    # ⚠️ 为什么保留 github 而不删：卡片仓库按钮、下载部署、AI 工具、插件清单
    #    全都读 github 这个**单值** —— 删掉等于一次改动波及全部读取方。
    #    normalize() 维持 github ⇄ repos 互填不变量（见 _normalize_repos 下方），
    #    老数据（只有 github）读出来 repos 自动有一行，新数据 github 取首行有效 url,
    #    两边都零改动。
    "repos": {
        "kind": "repos", "required": False,
        "doc": "开源仓库组：[{platform,url}]；platform ∈ " + "/".join(REPOS_PLATFORMS) +
               "；url 非 http/https 或 platform 无效的行整行丢弃；行数上限 20，超出截断",
    },
    "download_url": {
        "kind": "text", "required": False,
        "doc": "直接下载地址；留空时部署页退回用 github",
    },
    "download_page_url": {
        "kind": "text", "required": False,
        "doc": "下载**页面**的网址（表单里的「下载地址」= 下载页的网页地址，不是安装包直链）。"
               "与 download_url（直链）是两种语义，别混用。",
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
    # ⚠️ links 故意不用 kind="i18n"：那是**顶层文本字段**的按语言压平机制，
    #    I18N_FIELDS 也是按 kind=="i18n" 推导的 —— 若误标成 i18n，loader 读一次
    #    就把每行的 label/url 字典压成单一语言，前端切语言时 links 全变同一种文字。
    #    独立 kind 走 normalize_links：只做结构清洗 + 「三语完全相同 → 塌成字符串」，
    #    其余字典原样保留（行内 label/url 是前端语言分段切换的数据源）。
    "links": {
        "kind": "links", "required": False,
        "doc": "用户自定义「标签+链接」行（详情页·详细信息里逐行渲染）：[{label,url}]；"
               "label/url 可写纯字符串或三语言字典；无标签或 url 非 http/https 的行整行丢弃；"
               "行数上限 20，超出截断",
    },
}

# 落盘时的字段顺序（读起来有固定次序，diff 也好看）。表里没有的字段按原顺序追加在后面。
FIELD_ORDER = tuple(FIELDS.keys())

# 所有"可以写成多语言字典"的字段名（FIELDS 里 kind == "i18n" 的那几个）。
# ⚠️ 唯一事实来源就是上面 FIELDS 的 kind，**别在别处再硬编码一份**。
#    用途：资源库里这些字段在磁盘上是 {简体中文, 繁體中文, English} 字典，
#    而 normalize() 会把它们压成"当前语言"的字符串；制作器需要把**原始字典**取回来
#    才能把三种语言都灌进表单（见 resource_loader.get_raw_by_id 与
#    desktop/api/resources.py 的 detail）。读/写两条路因此要分开：
#    · 读（loader / resource_query / ai）拿字符串；
#    · 写（normalize_all / maker 写盘）压成单语言。
I18N_FIELDS = tuple(k for k, spec in FIELDS.items() if spec.get("kind") == "i18n")

# 可以写成「按语言字典、每个语言是一组值」的字段（kind=categories/tags）。
# ⚠️ 与 I18N_FIELDS 区分开：那四个字段的字典值是**一句话**（first_text 压平），
#    这两个字段的字典值是 **list[str] / 逗号串**（一格多数组，必须整份按语言取，
#    见 _collect_text 的 dict 分支）。标注独立 kind 而不是改 kind=="i18n"，
#    是为了 normalize 对文本字段继续走 first_text、对这两个走多值口径。
LANG_LIST_FIELDS = tuple(k for k, spec in FIELDS.items()
                         if spec.get("kind") in ("categories", "tags"))

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


def is_i18n_dict(value) -> bool:
    """判断一个值是不是"多语言字典"（至少命中一个语言键）
    ⚠️ 判定标准：字典里**存在** `LANGUAGE_FALLBACK`（简中/繁中/英文）里的某个键。
       这样 {"key": "value"} 这种普通字典（不是多语言）不会被误认成多语言，
       也不会把一个普通的空字典 {} 当成多语言（它对制作器没有任何意义）。
    """
    if not isinstance(value, dict) or not value:
        return False
    return any(key in value for key in LANGUAGE_FALLBACK)


def is_http_url(value) -> bool:
    """是否 http(s) 网址：去首尾空白后按协议**白名单**匹配（大小写不敏感）。
    links 的 normalize / validate / resolve_links 三处共用，口径必须一致：
    `javascript:`、`data:` 这类可执行协议在写盘阶段就被拒，不依赖前端转义。
    """
    text = _text(value).lower()
    return bool(text) and text.startswith(URL_SCHEME_PREFIXES)


def raw_i18n_of(item: dict) -> dict:
    """取一条**原始**条目里所有多语言字段的原始字典：{字段名: {语言: 文本}}
    ⚠️ 只认"确实是多语言字典"的字段（见 is_i18n_dict）：磁盘上写成纯字符串的字段
       原样跳过，由调用方决定回退策略（前端回退到简体中文）。
    为什么需要它：`normalize()` 会把多语言字典压成"当前语言"的字符串（读时压平），
    制作器（提交软件）要把三种语言都灌进表单，就必须拿**没被压过**的原始字典。
    """
    out: dict = {}
    if not isinstance(item, dict):
        return out
    for field in I18N_FIELDS + LANG_LIST_FIELDS:
        value = item.get(field)
        if is_i18n_dict(value):
            out[field] = value
    return out


def _collect_text(value, language: str, out: list):
    if value is None:
        return
    if isinstance(value, dict):
        # 按语言取「该语言那一份**子值**」，再对子值整体递归展开。
        # ⚠️ 不能图省事调 first_text：那是「取一个字符串」的语义，list 子值里第二个及
        #    之后的元素会被洗掉（task-4 lead 实测：{"English":["工具","网络"]}
        #    经 categories_of(..., "English") 只读到 ["工具"] —— 一格多数组的字段
        #    走这条就是数据丢失）。
        # ⚠️ 回退链与 first_text 完全一致：当前语言 → 简中 → 繁中 → 英文 → 第一个
        #    能展开出文本的值；某语言子值展开后一个文本都没有就继续往后回退。
        #    标量文本字段（name/description 走 as_text_list 时）行为不变：子值是
        #    字符串，展开仍是一个文本。
        for key in (language,) + LANGUAGE_FALLBACK:
            if key and key in value:
                before = len(out)
                _collect_text(value[key], language, out)
                if len(out) > before:
                    return
        for sub in value.values():
            before = len(out)
            _collect_text(sub, language, out)
            if len(out) > before:
                return
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


# ============ 多语言「并集」口径（task-6）============
# ⚠️ 为什么需要并集：制作器里类别/标签是**三个独立语言池**（简体中文/繁體中文/English
#    各填各的），值一律存**规范中文**（English 池存 ["工具","网络"]，不是 ["Tools"]）。
#    用户定夺：「卡片显示 + 筛选都按界面语言取自己那份，且各语言值都能被搜到」。
#    → 显示：按界面语言取那一份（categories_of/tags_of 传 language 即可）；
#    → 筛选：必须认**全部语言出现过的值**的并集，否则"只在 English 池里填了「网络」"
#      的条目在简体中文界面下既搜不到、也点不出来。
#    → 索引同理（loader 的 by_category/by_tag 建在并集上）。
# ⚠️ 顺序：固定按 简体中文 → 繁體中文 → English 的池序拼接，同一份数据两次调用
#    必须完全一致（否则 filter_options 的候选顺序会抖）。
LANG_POOL_ORDER = ("简体中文", "繁體中文", "English")


def _all_pool_values(raw, language: str = DEFAULT_LANGUAGE) -> list:
    """一个 category/tags 字段里**所有语言**的值的并集（规范值、去重保序）。

    · 老形态（list[str] / 逗号串 / 纯字符串）→ 只有一份，等于它自己（**零变化**）；
    · 新形态（{语言: list[str]}）→ 按 LANG_POOL_ORDER 逐语言取，再拼起来。
    ⚠️ 取某个语言那一份时仍走 split_multi（它内部按 language 回退），
    所以"某个语言没写"会自动回退到别的语言 —— 与前端 poolsFromRaw 的回退链一致。
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        out: list = []
        for lang in LANG_POOL_ORDER:
            one = raw.get(lang)
            if one is None:
                continue
            out.extend(split_multi(one, lang))
        if out:
            return dedup(out)
        # 字典里没有认识的语言键（脏数据）→ 退���按整体展开，别把内容丢了
        return split_multi(raw, language)
    return split_multi(raw, language)


def categories_all_of(item: dict, language: str = DEFAULT_LANGUAGE) -> list:
    """一条资源**所有语言**的类别并集（规范值、去重保序）

    ⚠️ 优先用 loader 预先算好的 "category_all" 字段：
       canonical 条目的 category 已被 normalize() 按界面语言压成"那一份"，
       从它身上算并集只能得到同一份（我第一版的错）。
       loader 在 normalize 之前用**磁盘原始条目**算好并集写进 canonical，
       这里直接取；老数据/未预计算的条目（磁盘原始条目本身）再回退到现算。
    """
    if not isinstance(item, dict):
        return []
    pre = item.get("category_all")
    if isinstance(pre, list) and pre:
        return dedup([str(v) for v in pre if str(v).strip()])
    return _all_pool_values(item.get("category"), language)


def tags_all_of(item: dict, language: str = DEFAULT_LANGUAGE) -> list:
    """一条资源**所有语言**的标签并集（规范值、去重保序）

    ⚠️ 同 categories_all_of：优先用 loader 预算的 "tags_all"。
    """
    if not isinstance(item, dict):
        return []
    pre = item.get("tags_all")
    if isinstance(pre, list) and pre:
        return dedup([str(v) for v in pre if str(v).strip()])
    return _all_pool_values(item.get("tags"), language)


def keywords_all_of(item: dict, language: str = DEFAULT_LANGUAGE) -> list:
    """检索词并集 = 所有语言的（类别 ∪ 标签）

    ⚠️ 与 keywords_of 的区别：keywords_of 只看**一个**语言那一份；
       这个是三个池的并集 —— 给筛选索引、关键词匹配、AI 检索词用，
       这样"只在某个语言池里写过的词"不会对用户隐身。
    """
    if not isinstance(item, dict):
        return []
    return dedup(categories_all_of(item, language) + tags_all_of(item, language))


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
# ⚠️ 加了 download_page_url（下载**页面**的网址），排在 download_url 后面。
LINK_FIELDS = ("url", "github", "download_url", "download_page_url", "author_url", "chat_url")


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


def resolve_links(item, language: str = DEFAULT_LANGUAGE) -> list:
    """按语言取一条资源的用户自定义链接：[{label, url}]（两个值都是纯字符串）
    给前端详情页 / 其它模块用：纯函数、无 IO、永不抛异常。
    · 取值与回退顺序和其它文本字段完全一致（first_text：当前语言→简中→繁中→英文→第一个非空），
      所以 `繁體中文` 只有英文值时拿到的是英文 —— 与前端 langTextOf 同一套规则；
    · label 为空、或该行 url 解析出来不是 http/https 的，**不返回**（安全线 + 没标签显示不了行）；
    · 对原始形态（三语字典没塌缩、混着脏行）和 normalize 之后的形态都可用，调用方不用关心清洗过没有。
    """
    out: list = []
    rows = item.get("links") if isinstance(item, dict) else None
    if not isinstance(rows, list):
        return out
    for row in rows[:LINKS_MAX_ROWS]:
        if not isinstance(row, dict):
            continue
        label = first_text(row.get("label"), language)
        url = first_text(row.get("url"), language)
        if not label or not is_http_url(url):
            continue
        out.append({"label": label, "url": url})
    return out


# ============ 规范化（写）============
def normalize(item, language: str = DEFAULT_LANGUAGE) -> dict:
    """把任何历史形态的一条资源压成规范形态（永不抛异常，绝不丢字段）
    · 字段名一个不改，不认识的字段原样保留，落盘顺序按 FIELD_ORDER（幂等）；
    · category 一律 list[str]；tags 原样保留（**不再**去掉与 category 同名的值，m07514）；
    · links 逐行清洗（坏行丢弃 / 三语同值塌缩 / 超 20 行截断），行内多语言字典**不压平**；
    · 其余多语言字典按 language 解析；空的可选字段不写，必填字段恒在。
    """
    if not isinstance(item, dict):
        return {}

    values: dict = {}
    for field in FIELD_ORDER:
        if field not in item:
            continue
        spec = FIELDS[field]
        values[field] = _normalize_value(spec["kind"], item.get(field), language, spec)

    # task-26：github ⇄ repos 互填。必须在**建 out 之前**改 values，
    # 这样 repos 才会按 FIELD_ORDER 落在 github 后面（写完直接 append 到 out 末尾
    # 会让 git diff 每一行都多出一个跑到文件段尾部的 repos，噪音极大）。
    _sync_github_repos(values)

    # ⚠️ m07514 用户报：「类别里有这个选项，我在标签里输入同一个名称，点保存后就不保存」。
    #    真因：这里曾经把「与类别同名的标签」**静默丢掉**（老约定：tags 不能重复 category），
    #    用户敲的标签凭空消失、看起来像"没保存"。
    #    现在**照写照存**：用户手填的标签一律保留（同名也保留）。
    #    检索侧取「类别 ∪ 标签」并集（keywords_of / tag_filter_options），重复一个词无副作用。
    #    validate() 里那条「tags 重复了 category」降级成**提示性**问题（仍不阻断写入）。

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
    # ⚠️ categories/tags 传 **language**（当前界面语言），不是 DEFAULT_LANGUAGE。
    #    为什么改了（task-6，用户定夺「卡片显示 + 筛选都按界面语言取自己那份」）：
    #  · 磁盘上这两个字段可能是三语字典（制作器三个独立语言池），取值应当
    #    跟随**界面语言** —— 英文界面下卡片就该显示 English 那一份；
    #  · 值本身恒为**规范中文**（English 池存 ["工具","网络"] 而不是 ["Tools"]），
    #    所以"跟着界面语言走"不会让筛选值变成英文，筛选/分组/索引口径依旧统一；
    #  · 旧数据（list[str] / 逗号串）只有一份，取值与改动前完全一致（零回归）。
    # ⚠️ 但**筛选索引**要认全部语言出现过的值（并集）：见 categories_all_of /
    #    keywords_all_of 与 loader 的索引构建 —— 否则"只在 English 池里填了「网络」"
    #    的条目在中文界面下搜不到。
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
    if kind == "links":
        # 不传 language：links 的行内字典是给前端切语言用的，压平成单语言就废了；
        # 只清洗结构（丢坏行）+ 三语同值塌缩（无损）。见 normalize_links。
        return normalize_links(raw)
    if kind == "repos":
        # 同 links：逐行清洗（坏行丢弃 / 平台归一 / 超 20 行截断 / 去重）。
        # github 单值不在这里算 —— 由 normalize() 里的 _sync_github_repos 统一兜，
        # 否则「repos 无效行全被丢光」这条路径就没机会回退到 github 了。
        return normalize_repos(raw)
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


def _i18n_text(value):
    """links 行内 label/url 的取值 -> (存储形态, 全部非空语言值列表)
    · 三语言字典：各语言值去首尾空白、丢掉空语言；清洗后**值全部相同**（含只剩一种
      语言有内容）→ 塌成纯字符串，否则保留字典 —— 与 maker._merge_i18n 对顶层
      i18n 字段的口径一致，磁盘上就不会出现"三种语言写了三遍同一个词"的字典；
    · 普通字典（没命中任何语言键）：按空处理 —— 语义不明的值宁可丢行，不猜测入库；
    · 标量：走 _text。
    """
    if isinstance(value, dict):
        if not is_i18n_dict(value):
            return "", []
        texts: dict = {}
        for key, sub in value.items():
            clean = _text(sub)
            if clean:
                texts[key] = clean
        if not texts:
            return "", []
        if len(set(texts.values())) == 1:
            only = next(iter(texts.values()))
            return only, [only]
        return texts, list(texts.values())
    text = _text(value)
    return text, ([text] if text else [])


def _links_row(row):
    """清洗一行 links -> (写盘形态或 None, 问题列表)；None 表示整行丢弃。
    ⚠️ 只原位覆盖 label/url 两个键：其它键与整行键序**一概不动**（需求：不重排数据）。
    丢弃规则都有理由：
    · 没有 label → 丢：没有标签的链接在详情页「详细信息」里渲染不出一行；
    · 没有 url → 丢：点了没反应的死行；
    · 任一语言的 url 不是 http/https → **整行**丢：只删坏语言会留下"半行字典"，
      而且危险协议宁可不存，也不赌每个读取方都会再过滤一遍（安全线）。
    """
    if not isinstance(row, dict):
        return None, [f"条目不是对象（{type(row).__name__}）：丢弃"]
    label, label_texts = _i18n_text(row.get("label"))
    url, url_texts = _i18n_text(row.get("url"))
    if not label_texts:
        return None, ["缺少标签：链接在详情页无法显示，整行丢弃"]
    if not url_texts:
        return None, ["缺少 url：整行丢弃"]
    for text in url_texts:
        if not is_http_url(text):
            brief = text if len(text) <= 40 else text[:40] + "…"
            return None, [f"url 不是 http/https 网址（{brief}）：危险协议不落盘，整行丢弃"]
    out = dict(row)
    out["label"] = label
    out["url"] = url
    return out, []


def normalize_links(raw) -> list:
    """links 字段 -> 写盘形态的行列表（幂等；normalize(kind="links") 与 maker 写盘共用）
    null / "字符串" / {} / 数字一律当"没有链接"返回 []（资源库是用户手改的数据，
    形态再离谱也不能抛）；行数超 LINKS_MAX_ROWS 截断（validate 负责把它报出来）。
    """
    if not isinstance(raw, list):
        return []
    out: list = []
    for row in raw[:LINKS_MAX_ROWS]:
        kept, _problems = _links_row(row)
        if kept is not None:
            out.append(kept)
    return out


def _repo_host_of(url: str) -> str:
    """从网址里抠出小写 host（去掉 www. 前缀与端口/路径）；拿不到返回空串。"""
    text = str(url or "").strip()
    for scheme in URL_SCHEME_PREFIXES:
        if text.lower().startswith(scheme):
            text = text[len(scheme):]
            break
    host = text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.rsplit("@", 1)[-1].split(":", 1)[0].strip().lower()
    return host[4:] if host.startswith("www.") else host


def _repo_platform_of(url: str) -> str:
    """由仓库网址反推 platform（task-26 契约：命中官方站点取对应 key，否则 custom）。

    给「老数据只有 github、没有 repos」那条反推路径用：github 字段历史上
    什么都写（GitHub / GitCode / Gitee / GitLab 都塞在同一个字段里，见 git 记录），
    反推一次就能让 repos 那一行带上正确的平台，前端下拉框才能显示对的名字。
    """
    host = _repo_host_of(url)
    if not host:
        return "custom"
    for site, platform in _REPO_HOST_PLATFORMS:
        # 相等 或 是官方站点的子域（如 cn.gitee.com）都算命中
        if host == site or host.endswith("." + site):
            return platform
    return "custom"


def _repos_row(row):
    """清洗一行 repos -> (写盘形态或 None, 问题列表)；None 表示整行丢弃。
    丢弃规则与 _links_row 同一套「不静默、有理由」纪律：
    · platform 是 "none"（前端「不开源」占位）/ 空 / 不在闭集里 → 丢：
      无效平台会让详情页按平台拼 API 时拿不到分支；不在闭集的值原样写盘等于把脏数据扩散出去。
      注：platform 缺失但 url 是官方站点时**先反推再留行**，不因前端漏填就丢掉用户的仓库。
    · url 不是 http/https → 丢（安全线：javascript:/data: 这类可执行协议绝不落盘，同 links）。
    """
    if not isinstance(row, dict):
        return None, [f"条目不是对象（{type(row).__name__}）：丢弃"]
    url = _text(row.get("url"))
    if not url:
        return None, ["缺少仓库地址：整行丢弃"]
    if not is_http_url(url):
        brief = url if len(url) <= 40 else url[:40] + "…"
        return None, [f"仓库地址不是 http/https 网址（{brief}）：危险协议不落盘，整行丢弃"]
    platform = _text(row.get("platform")).strip().lower()
    if platform == "none":
        # 契约定死的「不开源」占位值：整行无效。⚠️ 不能像空值那样反推保留 ——
        # 前端「不开源」是把 platform 选成 none 提交的，反推等于把用户明确
        # 声明「这条没有仓库」的意图改写成「有仓库」，github 也会被这次改写带偏。
        return None, ["platform 为 none（不开源）：整行丢弃"]
    if not platform:
        platform = _repo_platform_of(url)          # 漏填（手改 JSON / 老写入方）：按网址反推
    if platform not in REPOS_PLATFORMS:
        return None, [f"平台「{platform}」不在允许范围（{'/'.join(REPOS_PLATFORMS)}）：整行丢弃"]
    # 行内其它键（作者手加的备注之类）**原样保留、键序不动** —— 同 _links_row 的规矩：
    # 只覆盖我们负责清洗的 platform/url，不重排用户的数据，git diff 才干净。
    merged = dict(row)
    merged["platform"] = platform
    merged["url"] = url
    return merged, []


def normalize_repos(raw) -> list:
    """repos 字段 -> 写盘形态的行列表（幂等；normalize(kind="repos") 与 validate 共用）。
    null / "字符串" / {} / 数字一律当「没有仓库」返回 []（资源库是用户手改的数据，
    形态再离谱也不能抛）；行数超 REPOS_MAX_ROWS 截断（validate 负责把它报出来）。
    去重：同一 platform + 同一 url 只留第一条（前端「+」手滑多点两次很常见，
    重复行会让详情页出现两行一模一样的仓库）。
    """
    if not isinstance(raw, list):
        return []
    out: list = []
    seen: set = set()
    for row in raw[:REPOS_MAX_ROWS]:
        kept, _problems = _repos_row(row)
        if kept is None:
            continue
        token = (kept["platform"], kept["url"].rstrip("/"))
        if token in seen:
            continue
        seen.add(token)
        out.append(kept)
    return out


def repos_of(item) -> list:
    """取一条资源的仓库组：[{platform,url}]（两个值都是纯字符串）。

    ⚠️ 对「原始形态」和「normalize 之后」都可用，且**自动补齐**只有 github 的老数据：
       loader 读进来的是 normalize 过的（已经带 repos），但调用方也常直接拿磁盘原文 /
       变体那份来问「这条有哪些仓库」，这里兜一次就不用每个消费方自己写一遍。
    """
    rows = normalize_repos(item.get("repos") if isinstance(item, dict) else None)
    if rows:
        return rows
    github = _text((item or {}).get("github")) if isinstance(item, dict) else ""
    if github and is_http_url(github):
        return [{"platform": _repo_platform_of(github), "url": github}]
    return []


def _sync_github_repos(out: dict):
    """normalize() 的 github ⇄ repos 互填不变量（task-26 契约第 2 条）。

    为什么必须在 normalize 里做，而不是让每个写入方自己记得：
    · 前端 buildEntry 会同时写 repos 和 github，但**云端镜像 / 老数据 / 手改 JSON**
      都只有一份 —— 任何一份缺了，另一份就是唯一真相，得把它补出来；
    · 所有读 github 单值的旧代码（卡片仓库按钮 / 下载部署 / AI 工具 / 插件清单）
      要「零改动」，前提是 github 恒等于主仓库；
    · 反过来 repos 也必须恒有值，否则前端多组仓库那一栏会显示成空白，
      看起来像「仓库丢了」。

    规则：
      1) repos 有有效行 → github = 第一行的 url；
      2) repos 空而 github 是 http(s) → 反推补一行 {platform: 由 url 判, url: github}；
      3) 两边都没有 → 两个字段都不写（空的可选字段不落盘，与 normalize 一致）。
    幂等：第 1 条把 github 定成首行 url，再跑一次 repos 不变、github 也不变。
    """
    rows = normalize_repos(out.get("repos"))
    github = _text(out.get("github"))
    if rows:
        first = rows[0]["url"]
        out["repos"] = rows
        out["github"] = first
        return
    if github and is_http_url(github):
        out["repos"] = [{"platform": _repo_platform_of(github), "url": github}]
        out["github"] = github
        return
    out.pop("repos", None)
    # github 是个不合规的字符串时**留着别动**：validate 会报「不是完整网址」，
    # normalize 不该在这里替用户悄悄删掉他写的东西。


def normalize_lang_list(value):
    """category/tags 的「按语言字典」写盘规范化（task-4 新增能力；口径唯一事实来源）。

    输入是磁盘/表单送来的原值，返回三种结果之一：
      · None      —— 不是多语言字典（老形态 list[str]/逗号串），调用方继续用
                      normalize() 的压平结果即可；
      · list[str] —— 各语言清洗后**非空的池**内容完全相同（或只有一种语言非空）：
                      塌缩成单份列表，与 52 条老数据同形、资源库保持紧凑；
      · dict      —— 真的分语言不同：{语言: list[str]}，只写非空语言、
                      按 LANGUAGE_FALLBACK 顺序（每个语言各自 split_multi 拆列表 + 去重）。

    ⚠️ 比较只看**非空**的语言池、按原顺序比（"工具, 系统" ≠ "系统, 工具"）——
       与前端 poolsForEntry / applyI18nToEntry 三方一致；前端 buildEntry 只在真的
       不同才写字典，后端这里再塌缩同值字典**不是重复劳动**，而是兜住老数据 /
       云端镜像 / 别的写入方送来的同值字典，防磁盘上出现"三遍同一个词"。
    ⚠️ 值一律按规范中文口径原样收发：canonicalTerm（译名还原）是前端的职责，
       后端不翻译、不改写用户自造的类别/标签词。
    """
    if not is_i18n_dict(value):
        return None
    per_lang: dict = {}
    for lang in LANGUAGE_FALLBACK:
        if lang not in value:
            continue
        one = split_multi(value.get(lang))
        if one:
            per_lang[lang] = one
    if not per_lang:
        return None                      # 所有语言全空 = 「没有值」：交回调用方按空处理
    lists = list(per_lang.values())
    if all(items == lists[0] for items in lists):
        return lists[0]                  # 同值 → 塌缩成单份 list（老形态）
    return per_lang                      # 真分语言 → 字典形态（只含非空语言）


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
            # 提示性：m07514 起同名标签**照写照存**，这一条不再代表数据有错，
            # 只是告诉用户"这个标签和类别重名"（检索侧取并集，不影响使用）。
            problems.append("提示：tags 里有和 category 同名的值（不影响保存）：" + "、".join(dup))

        for field in ("url", "github", "download_url", "author_url", "chat_url"):
            value = _text(item.get(field))
            if value and not value.lower().startswith(("http://", "https://")):
                problems.append(f"{field} 不是完整网址：{value}")

        if isinstance(item.get("category"), (int, float, bool)):
            problems.append(f"category 类型可疑：{type(item['category']).__name__}")

        # 用户自定义链接：缺键 / null 都是"没有链接"，不报；其余逐行给出丢弃原因，
        # 让用户知道自己手改的那行为什么没显示（normalize 会静默丢行，这里必须吭声）。
        links = item.get("links")
        if links is not None:
            if not isinstance(links, list):
                problems.append(f"links 应为数组：{type(links).__name__}（读取时按空处理）")
            else:
                if len(links) > LINKS_MAX_ROWS:
                    problems.append(
                        f"links 行数 {len(links)} 超过上限 {LINKS_MAX_ROWS}："
                        "超出的行写入时会被截断")
                for index, row in enumerate(links):
                    _kept, row_problems = _links_row(row)
                    for text in row_problems:
                        problems.append(f"links[{index}]：{text}")

        # 多组开源仓库（task-26）：与 links 同一纪律 —— normalize 静默丢坏行，
        # validate 必须吭声，否则用户手改的那行仓库「凭空消失」比报错更难查。
        repos = item.get("repos")
        if repos is not None:
            if not isinstance(repos, list):
                problems.append(f"repos 应为数组：{type(repos).__name__}（读取时按空处理）")
            else:
                if len(repos) > REPOS_MAX_ROWS:
                    problems.append(
                        f"repos 行数 {len(repos)} 超过上限 {REPOS_MAX_ROWS}："
                        "超出的行写入时会被截断")
                for index, row in enumerate(repos):
                    _kept, row_problems = _repos_row(row)
                    for text in row_problems:
                        problems.append(f"repos[{index}]：{text}")
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
    "LINKS_MAX_ROWS", "URL_SCHEME_PREFIXES",
    "REPOS_PLATFORMS", "REPOS_MAX_ROWS",
    "normalize_repos", "repos_of",
    "I18N_FIELDS", "LANG_LIST_FIELDS", "is_i18n_dict", "raw_i18n_of", "is_http_url",
    "first_text", "as_text_list", "split_multi", "dedup",
    "parse_categories", "categories_of", "tags_of", "keywords_of",
    "systems_of", "architectures_of",
    "id_of", "code_of", "name_of", "summary_of", "links_of", "resolve_links",
    "normalize", "normalize_links", "normalize_lang_list", "normalize_all",
    "validate", "validate_all",
]
