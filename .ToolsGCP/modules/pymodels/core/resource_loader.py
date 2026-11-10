"""资源索引加载器：读 ToolsGCP-Resources.json（本地或 URL），构建 id->resource 内存索引。
⚠️ 读进来的每一条都先过 resource_schema.normalize()（category 一律 list、tags 去重），
消费方不需要知道磁盘上以前长什么样；tag / category 索引惰性构建，不落盘。
    loader = ResourceLoader(); loader.load_from_local()
    loader.get_summaries()      # 卡片用的轻量数据
    loader.get_by_id("pcl2")    # 详情页用的完整数据
⚠️ 多语言字段（name/description/intro/supplement）在磁盘上是三语言字典，
   但 normalize() 会把它们压成"当前语言"的字符串 —— 这是**读时压平**，
   写盘链路（normalize_all）也要这个语义，所以**不能**改 normalize()。
   制作器（提交软件）需要三种语言，因此加载器**额外**留一份原始副本：
       loader.get_raw_i18n_by_id("pcl2")   # -> {"description": {简中, 繁中, English}, ...}
   只有这一条路拿字典，其余消费方（get_all / get_summaries / resource_query）
   拿到的仍然是字符串，零风险。
"""
import json
import os
from pathlib import Path
from typing import Optional

from . import resource_schema

# 默认索引文件（相对项目根目录）
DEFAULT_RESOURCE_FILE = ".ToolsGCP/ToolsGCP-Resources.json"

# 卡片显示所需的字段（不含 details / guide / related_info）：
# listed_at = 上架时间；supplement = 补充说明；intro = 应用介绍；
# systems / architectures = 适用系统与 CPU 架构（搜索页按这些筛）
SUMMARY_FIELDS = ("id", "code", "name", "description", "icon",
                  "category", "tags", "url", "github", "listed_at", "supplement",
                  "intro", "systems", "architectures")


# ⚠️ 哪些字段可以写成多语言的定义只有一处：resource_schema.FIELDS 里 kind="i18n"。


def resolve_i18n(value, language: str = "简体中文"):
    """把可能是多语言字典的字段解析成当前语言的字符串
    单语言字符串和多语言字典都支持；找不到语言依次回退简中/繁中/英文。
    ⚠️ 实现在 resource_schema.first_text()，这里只是保留同名入口。
    """
    if not isinstance(value, dict):
        return value
    return resource_schema.first_text(value, language)


class ResourceLoader:
    """资源索引加载器"""

    def __init__(self, resource_file: str = None, language: str = "简体中文"):
        """resource_file: 要读的索引文件，不传就用默认的；language: 当前界面语言
        搜索页会按设置里的资源来源（云端 / 本地）算出路径再传进来。
        """
        self.resource_file = resource_file or DEFAULT_RESOURCE_FILE
        self.language = language or "简体中文"
        self._resources: list[dict] = []
        self._id_map: dict[str, dict] = {}
        # ⚠️ （路线 A）：**原始条目**副本（没被 normalize 压平的多语言字典）。
        #    背景：磁盘上 name/description/intro/supplement 是
        #    {简体中文, 繁體中文, English} 字典，但 normalize()（唯一读数入口）会把它们
        #    压成"当前语言"的字符串 —— 于是"提交软件"页（制作器）再也拿不到繁中/英文，
        #    多语言字段不加载繁体中文和英文的内容。
        #    为什么不动 normalize()：它同时是**写盘**链路的规范器（normalize_all），
        #    而且 resource_query / ai / 收藏 / 部署全都在吃它的字符串形态。
        #    改它 = 改动面巨大、风险高。
        #    所以这里只**额外**留一份原始副本，只有制作器这一条路会取它；
        #    其余消费方（get_all / get_summaries / resource_query）拿到的仍然是字符串。
        self._raw_by_id: dict[str, dict] = {}
        self._raw_by_code: dict[str, dict] = {}
        # 标签/类别索引惰性构建：只有真正调用 by_tag / by_category 时才建立
        self._tag_index: Optional[dict[str, set[str]]] = None
        self._category_index: Optional[dict[str, set[str]]] = None
        self._icon_dir: str = ""
        self.schema_version: str = ""
        # 上一次成功加载的来源文件 + 它的 mtime（`reload_if_changed()` 用）
        self._source_path: str = ""
        self._source_mtime: float = 0.0
        self._project_root: str = self._detect_project_root()

    @staticmethod
    def _detect_project_root() -> str:
        """探测项目根目录（ToolsGCP.pyw 所在目录）"""
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "ToolsGCP.pyw").exists():
                return str(parent)
            # 兼容 .ToolsGCP 在根目录下的结构
            if (parent / ".ToolsGCP").is_dir():
                return str(parent)
        return str(current.parents[2])  # 默认回退

    # ---------- 加载 ----------
    def load_from_local(self, relative_path: str = None) -> bool:
        """加载索引 JSON（路径可以是相对项目根的，也可以是绝对路径）"""
        path = relative_path or self.resource_file
        full_path = path if os.path.isabs(path) else os.path.join(self._project_root, path)
        if not os.path.exists(full_path):
            from ..utils.logger import log
            log.warn("资源库", "load", f"索引文件不存在: {full_path}")
            return False
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            from ..utils.logger import log
            log.err("资源库", "load", f"索引文件解析失败: {full_path} - {e}")
            return False
        self._build_indexes(data)
        # 记下"这份索引是从哪个文件、什么时候读的" —— 云端缓存被后台刷新后，
        #      `reload_if_changed()` 靠它判断要不要重载（不用上层自己记 mtime）。
        self._source_path = full_path
        try:
            self._source_mtime = os.path.getmtime(full_path)
        except Exception:
            self._source_mtime = 0.0
        from ..utils.logger import log
        log.info("资源库", "load", f"已载入 {len(self._resources)} 条资源: {full_path}")
        return True

    def reload_if_changed(self) -> bool:
        """磁盘上的索引文件变了就重载；返回是否真的重载了
        用途：云端资源库的缓存文件会被**后台线程**替换（atomically），
        消费方（搜索页 / 资源详情）不用知道什么时候变的，调一下这里就能拿到新数据。
        ⚠️ 读盘失败时**保留**上一次的数据并返回 False（和 load_from_local 的语义一致）。
        """
        source = str(getattr(self, "_source_path", "") or self.resource_file or "")
        if not source:
            return False
        full_path = source if os.path.isabs(source) else os.path.join(self._project_root, source)
        try:
            if not os.path.exists(full_path):
                return False
            mtime = os.path.getmtime(full_path)
        except Exception:
            return False
        if mtime and mtime == float(getattr(self, "_source_mtime", 0.0) or 0.0):
            return False
        return bool(self.load_from_local(full_path))

    def load_from_url(self, url: str) -> bool:
        """从 URL 加载 JSON（预留，后续接入 GitHub 时使用）"""
        # 后续可替换为 requests / urllib 实现
        raise NotImplementedError("URL 加载暂未实现")

    def load_from_data(self, data: dict) -> bool:
        """直接从已解析的字典构建索引（便于测试与远程加载复用）"""
        if not isinstance(data, dict):
            return False
        self._build_indexes(data)
        return True

    def _build_indexes(self, data: dict):
        """构建内存索引"""
        metadata = data.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        self.schema_version = str(data.get("schema_version") or "")
        self._icon_dir = str(metadata.get("icon_dir") or "").strip("/\\")

        self._resources = []
        self._id_map = {}
        # ⚠️ 原始副本索引与规范形态索引**同时**建（路线 A）。
        #    规范形态（字符串）给所有既有消费方；原始副本（多语言字典）只给制作器。
        self._raw_by_id = {}
        self._raw_by_code = {}
        self._tag_index = None
        self._category_index = None

        for item in data.get("resources", []):
            if not isinstance(item, dict):
                continue
            # ⚠️ 唯一的读数入口：磁盘上任何历史形态先规范化再进内存，消费方不必各自
            #    再写一遍 split / 去重 / code or id。
            canonical = resource_schema.normalize(item, self.language)
            rid = canonical.get("id")
            if not rid or rid in self._id_map:
                continue
            self._apply_loader_defaults(canonical)
            self._resources.append(canonical)
            self._id_map[rid] = canonical
            # 原始条目：只保留多语言字段的**原样字典**（磁盘上没写多语言就取不到，
            # 前端会回退到"当前语言字符串"的老行为）。
            raw_i18n = resource_schema.raw_i18n_of(item)
            if raw_i18n:
                raw_entry = dict(raw_i18n)
                raw_code = str(item.get("code") or "").strip()
                if raw_code:
                    self._raw_by_code[raw_code.upper()] = raw_entry
                self._raw_by_id[rid] = raw_entry

    def _apply_loader_defaults(self, item: dict):
        """补上"只有加载器知道"的两件事（就地修改）
        1. icon 只写文件名时补上 metadata.icon_dir（目录来自 metadata，schema 管不着）；
        2. 有 variants（例如 Trae 的国际版/国内版）时，把"默认变体"的
           url / github / download_url 提升到顶层，这样卡片、部署页等
           按老字段读取的地方完全不用改。
        """
        icon = item.get("icon")
        if icon and self._icon_dir and isinstance(icon, str):
            if "/" not in icon and "\\" not in icon:
                item["icon"] = f"{self._icon_dir}/{icon}"

        variants = item.get("variants")
        if isinstance(variants, list) and variants:
            default_key = item.get("default_variant")
            chosen = None
            for v in variants:
                if isinstance(v, dict) and v.get("key") == default_key:
                    chosen = v
                    break
            if chosen is None:
                chosen = next((v for v in variants if isinstance(v, dict)), None)
            if chosen:
                for field in ("url", "github", "download_url", "author_url", "chat_url"):
                    if not item.get(field) and chosen.get(field):
                        item[field] = chosen[field]

    @staticmethod
    def resolve_variant(item: dict, key: str = None) -> dict:
        """取出某个变体（不存在时返回默认变体，再不行返回 None）"""
        variants = item.get("variants") if isinstance(item, dict) else None
        if not isinstance(variants, list) or not variants:
            return None
        if key:
            for v in variants:
                if isinstance(v, dict) and v.get("key") == key:
                    return v
        default_key = item.get("default_variant")
        for v in variants:
            if isinstance(v, dict) and v.get("key") == default_key:
                return v
        return next((v for v in variants if isinstance(v, dict)), None)

    # ---------- 惰性索引 ----------
    def _ensure_category_index(self) -> dict[str, set[str]]:
        if self._category_index is None:
            index: dict[str, set[str]] = {}
            for item in self._resources:
                # category 是列表：一条资源可以同时属于多个类别，每个都要进索引
                for category in resource_schema.categories_of(item):
                    index.setdefault(category, set()).add(item["id"])
            self._category_index = index
        return self._category_index

    def _ensure_tag_index(self) -> dict[str, set[str]]:
        if self._tag_index is None:
            index: dict[str, set[str]] = {}
            for item in self._resources:
                # 和搜索页的标签筛选同一套取值（类别 ∪ 标签）：tags 去重之后
                # 只索引 tags 会让 by_tag("工具") 查不到东西。
                for tag in resource_schema.keywords_of(item):
                    index.setdefault(tag, set()).add(item["id"])
            self._tag_index = index
        return self._tag_index

    # ---------- 查询 ----------
    def get_all(self) -> list[dict]:
        """获取全部资源"""
        return list(self._resources)

    def get_summaries(self) -> list[dict]:
        """获取轻量资源列表（仅卡片显示所需字段，不含 details/guide/related_info）"""
        return [
            {field: item.get(field) for field in SUMMARY_FIELDS}
            for item in self._resources
        ]

    def get_by_id(self, rid: str) -> Optional[dict]:
        """通过 id 获取资源"""
        return self._id_map.get(rid)

    def get_by_code(self, code: str) -> Optional[dict]:
        """通过资源编码（如 TG-0001）获取资源"""
        if not code:
            return None
        wanted = str(code).strip().upper()
        for item in self._resources:
            if str(item.get("code", "")).upper() == wanted:
                return item
        return None

    # ---------- 原始多语言（路线 A）----------
    @staticmethod
    def _copy_raw_i18n(entry: dict) -> dict:
        """复制一份原始多语言条目（**深拷贝**：里面的语言字典也要复制）
        ⚠️ 为什么必须深拷贝：`dict(entry)` 只是浅拷贝 —— 里面的
        `{语言: 文本}` 还是**同一批字典对象**，调用方改一下就污染了内存索引
        （下次再取拿到的就是被改过的内容）。制作器那边会把取到的文本塞进表单、
        随用户编辑写回，深拷贝能保证"内存里的资源库"永远不被表单操作影响。
        """
        if not entry:
            return {}
        out = {}
        for key, value in entry.items():
            out[key] = dict(value) if isinstance(value, dict) else value
        return out

    def get_raw_i18n_by_id(self, rid: str) -> dict:
        """取一条资源**原始**的多语言字段：{字段名: {语言: 文本}}
        ⚠️ 这是给提交软件（制作器）用的**唯一**入口：
           磁盘上 name/description/intro/supplement 是三语言字典，而 get_by_id /
           get_by_code 返回的是 normalize() 压平后的**当前语言字符串**，
           制作器拿不到繁中/英文 → 用户报多语言字段不加载繁体中文和英文。
        ⚠️ 返回的是**深拷贝**（调用方随便改都不会污染内存索引）。
        ⚠️ 取不到就返回 {} —— 调用方据此回退到"只灌当前语言"的老行为。
        """
        entry = self._raw_by_id.get(str(rid or ""))
        return self._copy_raw_i18n(entry)

    def get_raw_i18n_by_code(self, code: str) -> dict:
        """按资源编码取**原始**多语言字段（见 get_raw_i18n_by_id）"""
        if not code:
            return {}
        entry = self._raw_by_code.get(str(code).strip().upper())
        return self._copy_raw_i18n(entry)

    def by_tag(self, tag: str) -> list[dict]:
        """按关键词查找（类别 ∪ 标签 —— 和搜索页标签筛选的取值一致）"""
        return [self._id_map[rid] for rid in self._ensure_tag_index().get(tag, ())]

    def by_category(self, category: str) -> list[dict]:
        """按类别查找"""
        return [self._id_map[rid] for rid in self._ensure_category_index().get(category, ())]

    def search(self, keyword: str) -> list[dict]:
        """按关键字搜索名称、简介、关键词（类别 + 标签）、详情"""
        keyword = str(keyword).lower()
        results = []
        for item in self._resources:
            haystack = " ".join(
                str(v)
                for v in (
                    item.get("name", ""),
                    item.get("description", ""),
                    item.get("details", ""),
                    # ⚠️ 用 keywords_of（类别 ∪ 标签）：以前类别是抄一份进 tags 的，
                    #    只看 tags 恰好等价；现在 tags 去掉了重复值，必须显式带上类别。
                    " ".join(resource_schema.keywords_of(item)),
                )
            ).lower()
            if keyword in haystack:
                results.append(item)
        return results

    @property
    def is_loaded(self) -> bool:
        return len(self._resources) > 0

    @property
    def icon_dir(self) -> str:
        """资源图标的**绝对目录**（metadata.icon_dir 相对项目根解析出来）
        给"图标预热"用：启动后把这个目录里的图提前解码进缓存，卡片一绑上就有图，
        用户不会再看到"卡片先出来、图标等 1~2 秒". 没配 icon_dir 时返回空串。
        """
        directory = str(self._icon_dir or "").strip()
        if not directory:
            return ""
        if os.path.isabs(directory):
            return directory
        return os.path.join(self._project_root, directory)
