"""资源查询算法（搜索匹配 / 条件筛选 / 排序 / 分组）—— **纯 Python，零 Qt 依赖**
========== 这个模块为什么存在 ==========
这些算法原来压在两个 UI 文件里：
    · `interfaces/search_interface.py`  —— `_apply_filters` / `_passes_filters` /
      `_refresh_latest_codes` / `_parse_listed_at` / `tag_filter_options` / `_category_order`
    · `widgets/apps_index_framework.py` —— `_flat_groups` / `_category_groups` /
      `_letter_groups` / `_sort_items`
Web 版重写 UI 层时这两个文件会被删掉，但算法**一个字节都不许变**（红线：换皮不换骨）。
所以这里把它们逐行搬出来，只做两件事：
    1. 去掉 `self.`：需要外部状态的地方（收藏、当前关键词、筛选值）改成显式参数；
    2. 分组标题的翻译改成注入的 `translate` 回调（原来是 import language_manager 单例），
       这样本模块保持纯净，测试不需要 GUI、也不需要语言文件。
⚠️ 搬运原则：**只改"怎么拿到输入"，不改"怎么算"**。所有边界行为（空值、缺字段、
   时间解析失败、`latest` 集合为空、`updated[0]` 单选…）全部按原样保留，注释里会标出
   哪些是"看起来像 bug 但必须保留"的行为。
"""

from datetime import datetime

from . import resource_schema

# ---------- 分组顺序（原 search_interface._category_order 与
#            apps_index_framework._category_groups 里的 CATEGORY_ORDER 是同源常量，
#            这里合并成唯一一份，值与原样一致）----------
CATEGORY_ORDER = [
    "工具", "游戏", "平台", "编程", "游戏引擎",
    "视频平台", "建筑/设计", "AI", "个性化",
]

# 一条资源一个类别都没填时归到其他，免得它从分组视图里整个消失（原注释如此）
FALLBACK_CATEGORY = "其他"

# 最新这一档取前多少条（原 search_interface._latest_n = 10）
LATEST_N = 10

# 排序键（原 apps_index_framework.SORT_KEYS）
SORT_ALL = "all"
SORT_CATEGORY = "category"
SORT_AZ = "az"
SORT_ZA = "za"
SORT_KEYS = (SORT_ALL, SORT_CATEGORY, SORT_AZ, SORT_ZA)

# 更新时间筛选的档位 → 天数（原 _passes_filters 里的字面量字典）
UPDATED_DAYS = {"10d": 10, "30d": 30, "180d": 180}


def parse_listed_at(value):
    """把上架时间字符串解析成 datetime（认不出来就返回 None）
    制作器写的是 "2026-09-21 00:40:14"；也兼容带 T 的 ISO 写法。
    ⚠️ 三种格式按"从长到短"试，并**截断到对应长度**（原实现如此）：
       "2026-09-21T00:40:14.123+08:00" 会被截成前 19 位再解析。
    """
    text = str(value or "").strip().replace("T", " ")
    if not text:
        return None
    for fmt, width in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16),
                       ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:width], fmt)
        except ValueError:
            continue
    return None


def tag_filter_options(items) -> list:
    """标签筛选行的选项：类别 ∪ 标签（去重后按名字排序）
    ⚠️ 必须取并集：tags 里去掉了与类别重复的值，只取 tags 会凭空少掉
       工具 / 游戏 / AI这些最常见筛选项。
    """
    values = set()
    for item in items or []:
        for value in resource_schema.keywords_of(item):
            values.add(str(value))
    return sorted(values)


def latest_codes(items, n: int = LATEST_N) -> set:
    """算出最新这一档是哪些条目：按上架时间倒序取前 n 条
    （没有上架时间的老数据排在最后，不会被算成"最新"）
    ⚠️ 排序键是 `(stamp, code)` 二元组 —— 原实现就是这么排的，同秒条目按编码定序。
    """
    rows = []
    for item in items or []:
        stamp = parse_listed_at(item.get("listed_at"))
        if stamp is not None:
            rows.append((stamp, str(item.get("code") or "")))
    rows.sort(reverse=True)
    return {code for _stamp, code in rows[:int(n)]}


def match_keyword(item: dict, keyword: str, digits: str = None) -> bool:
    """关键词匹配（原 search_interface._apply_filters 的内嵌 match_keyword）
    命中顺序（任一即算命中）：
      1. `keyword` 是 `code` 的子串（"tg-15" 命中 "TG-000015"）；
      2. keyword 里的**数字**是 code 里数字的子串（"15" / "0015" 命中 TG-000015）；
      3. keyword **完全等于** id（没有 code 的老条目靠这条命中）；
      4. `keyword` 是 name 的子串；
      5. `keyword` 是 description 的子串；
      6. keyword 命中 类别 ∪ 标签 里的任意一项。
    ⚠️ 第 2 条与第 3 条的边界必须原样保留：digits 为空串时该分支被短路；
       id 用的是**完全相等**而不是子串包含。
    """
    keyword = str(keyword or "").strip().lower()
    if not keyword:
        return True
    if digits is None:
        digits = "".join(ch for ch in keyword if ch.isdigit())
    code = str(item.get("code", "")).lower()
    if keyword in code:
        return True
    if digits and digits in "".join(ch for ch in code if ch.isdigit()):
        return True
    code_id = str(item.get("id", "")).lower()
    if code_id and keyword == code_id:
        return True
    if keyword in str(item.get("name", "")).lower():
        return True
    if keyword in str(item.get("description", "")).lower():
        return True
    # 关键词匹配 = 类别 ∪ 标签（理由同 tag_filter_options）
    return any(keyword in str(v).lower()
               for v in resource_schema.keywords_of(item))


def passes_filters(item: dict, filters: dict, latest=None, is_favorite=None) -> bool:
    """更多筛选的判定：**组内多选是或，组间是与**
    `filters` 取值（与原 FilterPanel.values() 同形）：
        {"category": [...], "tag": [...], "source": [...], "favorite": [...],
         "updated": [...], "system": [...], "arch": [...]}
    `latest`      = `latest_codes()` 的结果（"最新"这一档的编码集合）
    `is_favorite` = 判定是否为收藏的回调（None = 没有收藏能力，"仅看收藏"必然不通过）
    ⚠️⚠️ 下面这三处是**故意保留的原版行为**，看着像 bug，但不许"顺手修"：
      a. `updated` 只读 `updated[0]`（UI 是多选但代码只认第一个）；
      b. `latest` 分支里，当 `latest` 为空集合时**不过滤**（空库=全通过）；
      c. `days is None` 时直接 `return True` —— 这会让后面的 system/arch 检查被跳过。
         只有 `updated[0]` 是未知值时才会走到这条（UI 只会给 fixed 的四档），
         所以线上触发不到，但行为必须一致。
    """
    filters = filters or {}
    latest = latest if latest is not None else set()

    categories = filters.get("category") or []
    # category 现在是列表（一条资源可以属于多个类别）：命中任意一个就算通过
    if categories and not set(resource_schema.categories_of(item)) & set(categories):
        return False

    tags = filters.get("tag") or []
    if tags:
        # 标签筛选看的是类别 ∪ 标签——和筛选行里列出来的选项同一套取值
        item_tags = [str(t) for t in resource_schema.keywords_of(item)]
        if not any(t in item_tags for t in tags):
            return False

    sources = filters.get("source") or []
    if sources:
        has_repo = bool(item.get("github"))
        has_download = bool(item.get("download_url")) or has_repo
        has_site = bool(item.get("url"))
        if not (("repo" in sources and has_repo)
                or ("download" in sources and has_download)
                or ("site" in sources and has_site)):
            return False

    if "only" in (filters.get("favorite") or []):
        if not callable(is_favorite) or not is_favorite(item.get("code")):
            return False

    # 更新时间：按上架时间筛（listed_at）
    #   latest = 时间最新的前 10 条；10d / 30d / 180d = 最近 10 / 30 / 180 天内上架的
    updated = filters.get("updated") or []
    if updated:
        mode = updated[0]
        if mode == "latest":
            if latest and str(item.get("code") or "") not in latest:
                return False
        else:
            days = UPDATED_DAYS.get(mode)
            if days is None:
                return True            # （原版行为，见 docstring 的 c）
            stamp = parse_listed_at(item.get("listed_at"))
            if stamp is None:
                return False           # 没有上架时间的（老数据）不算"最近 N 天"
            if (datetime.now() - stamp).days > days:
                return False

    # 适用系统 / CPU 架构：条目里存的是数组（systems / architectures），
    # 选了条件但这条没填时不算命中
    for key, field in (("system", "systems"), ("arch", "architectures")):
        wanted = filters.get(key) or []
        if not wanted:
            continue
        values = [str(v).strip().lower() for v in (item.get(field) or [])
                  if str(v).strip()]
        if not values:
            return False
        if not any(w.strip().lower() in values for w in wanted):
            return False
    return True


def query(items, keyword: str = "", filters: dict = None, favorites=None,
          latest: set = None):
    """把搜索关键词 + 更多筛选一起作用到列表上（原 _apply_filters）
    参数：
        items       = 全部资源（`ResourceLoader.get_all()` 的结果）
        keyword     = 搜索框里的原文
        filters     = FilterPanel.values() 同形
        favorites   = 收藏管理器（可空；只影响"仅看收藏"）
        latest      = 最新这一档的编码集合
    ⚠️⚠️ `latest` **必须由调用方先算好**（`latest_codes(items)`），本函数不自己算。
        这是原版的真实语义，别"顺手改成自动算"：
            原流程 = `_refresh_latest_codes(); _apply_filters()`（见
                     search_interface._apply_filter_later，只在"筛选变化"时走）
            直接搜索（Enter / 搜索按钮）走 `_do_search` → `_apply_filters()`，
            **不带**刷新 —— 于是"最新"用的是上一次筛选变化时算出来的集合，
            从没算过时就是空集合，而空集合会让 `latest` 分支**完全不过滤**。
        差分自检就是靠这一点抓出来的（`query(keyword, {"updated":["latest"]})` 在
        没有先刷新时，原版返回全量 52 条，自动算的版本返回 10 条 —— 两者不一致）。
        所以前端要严格按原版顺序调用：
            latest = api.resources.latest_codes()      # 等价 _refresh_latest_codes()
            result = api.resources.query(keyword, filters, latest=latest)
    返回 `(matched, keyword_used)`：
        matched 是按 `items` 原顺序过滤出来的列表；**不做排序、不分组**
        （排序/分组交给 `group_items`，与原版分工一致）。
    """
    items = list(items or [])
    keyword = str(keyword or "")
    filters = filters or {}
    latest = latest if latest is not None else set()

    digits = "".join(ch for ch in keyword.strip().lower() if ch.isdigit())
    is_favorite = None
    if favorites is not None:
        is_favorite = favorites.is_favorite

    matched = [
        item for item in items
        if match_keyword(item, keyword, digits)
        and passes_filters(item, filters, latest=latest, is_favorite=is_favorite)
    ]
    return matched, keyword


# ============ 排序 / 分组 ============

def sort_items(items, key: str = SORT_ALL) -> list:
    """排序（原 apps_index_framework._sort_items）
    ⚠️ `all` **保持输入顺序**（不是 A-Z）—— UI 上写"全部"指的就是"不排序"，
       这是原版行为，别改成按名字排（Q37 已定调"原样保留"）。
    """
    if key == SORT_AZ:
        return sorted(items, key=lambda x: str(x.get("name", "")).lower())
    if key == SORT_ZA:
        return sorted(items, key=lambda x: str(x.get("name", "")).lower(),
                      reverse=True)
    return list(items)


def flat_groups(items, key: str = SORT_ALL) -> list:
    """不分组的单一分组（原 _flat_groups）：`[(None, items)]`
    ⚠️ 为了和 `category_groups` / `letter_groups` **同形**（都返回 3 元组
       `(canonical, display, items)`），这里补一个 `display=None` —— 前端拿到
       `None` 就表示"这一组不画分组标题"（原版 flat 模式也确实没有标题）。
       身份仍然是 `None`，与原版 `[(None, items)]` 完全等价。
    """
    return [(None, None, sort_items(items, key))]


def category_groups(items, translate=None) -> list:
    """按类别分组（原 _category_groups）
    - 固定类别顺序 `CATEGORY_ORDER`，未知类别按"首次出现顺序"追加到末尾；
    - `category` 是列表：一条资源属于多个类别时**在每个类别下都出现一次**；
    - 一个类别都没填的条目归到其他，免得从分组视图里整个消失。
    ⚠️ 分组标题只是**显示**用的：分组身份仍是规范中文值（筛选、收藏都按它走）。
       所以这里返回 `(canonical_key, display_title, items)` 三元组，
       原版只返回了 display_title（前端只需要标题），**多加的 canonical 是给前端做
       v-for 的稳定 key 用的**，不改变任何匹配行为。
    返回 `[(canonical, display, items), ...]`。
    """
    groups: dict = {}
    for item in items or []:
        for cat in resource_schema.categories_of(item) or [FALLBACK_CATEGORY]:
            groups.setdefault(cat, []).append(item)

    ordered = [c for c in CATEGORY_ORDER if c in groups]
    ordered += [c for c in groups if c not in CATEGORY_ORDER]
    display = translate if callable(translate) else (lambda value: value)
    return [(c, display(c), groups[c]) for c in ordered]


def letter_groups(items, key: str = SORT_ALL, translate=None) -> list:
    """按首字母分组（原 _letter_groups）
    A-Z 每个字母一组，非字母开头归到 `"#"` 并**永远排在最后**；
    `za` 时字母序反转、**组内也反转**（原实现如此）。
    返回 `[(letter, letter, items), ...]`（字母本身就是身份，display 与 canonical 相同，
    保持与 category_groups 同形，前端可以统一处理）。
    """
    groups: dict = {}
    for item in items or []:
        name = str(item.get("name", "")).strip()
        letter = name[:1].upper() if name else "#"
        if len(letter) != 1 or not ("A" <= letter <= "Z"):
            letter = "#"
        groups.setdefault(letter, []).append(item)

    reverse = key == SORT_ZA
    letters = sorted(k for k in groups if k != "#")
    if reverse:
        letters.reverse()
    if "#" in groups:
        letters.append("#")

    for letter_key in groups:
        groups[letter_key].sort(key=lambda x: str(x.get("name", "")).lower(),
                                reverse=reverse)
    return [(letter, letter, groups[letter]) for letter in letters]


def group_items(items, key: str = SORT_ALL, translate=None) -> list:
    """统一的入口：按排序键决定分组形态（与原框架的三个分支一一对应）
        all                → 单组，保持原顺序
        category（默认）    → 按类别分组
        az / za            → 按首字母分组
    返回 `[(canonical, display, items), ...]`。
    """
    if key == SORT_CATEGORY:
        return category_groups(items, translate=translate)
    if key in (SORT_AZ, SORT_ZA):
        return letter_groups(items, key=key, translate=translate)
    return flat_groups(items, key=key)


__all__ = [
    "CATEGORY_ORDER", "FALLBACK_CATEGORY", "LATEST_N", "UPDATED_DAYS",
    "SORT_ALL", "SORT_CATEGORY", "SORT_AZ", "SORT_ZA", "SORT_KEYS",
    "parse_listed_at", "tag_filter_options", "latest_codes", "match_keyword",
    "passes_filters", "query", "sort_items", "flat_groups", "category_groups",
    "letter_groups", "group_items",
]
