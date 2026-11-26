"""资源制作器（提交软件）的写盘域 —— `window.pywebview.api.maker`。
========== 为什么需要它 ==========
提交软件页（`.ToolsGCP/webui/index.html` 的 maker 段）本来只是一个**表单**：
它把用户填的内容组装成一条资源，然后调 `maker.append_entry` 写进
`.ToolsGCP/ToolsGCP-Resources.json`。但后端一直**没有这个域**，前端只能降级成
"导出一个合并后的 JSON 让用户自己放回去" —— 页面上看起来能填，实际写不进资源库。
这里补上最小可用的写盘能力（不依赖 PyQt，也不 import 原版 `interfaces/`）：
    maker.info()                    正在用的资源库路径 / 条目数 / schema
    maker.append_entry(entry, opts) 新增或按 id 覆盖一条（写盘前自动备份）
    maker.append_entries(items, opts) 批量合并（追加模式 / 新建模式，重复条目策略）
约定：
  · 条目先过 `pymodels.core.resource_schema.normalize()`，保证和原版写得一样；
  · 写盘用临时文件 + os.replace 原子替换，写之前把旧文件**滚动备份**成固定名的一份
    `<用户数据根>\\backups\\ToolsGCP-Resources.prev.json`（每次覆盖它，不再攒一堆时间戳文件）；
  · 任何异常都转成 `{ok: False, error}`，绝不把半截 JSON 留在盘上。
"""

import base64
import json
import os
import re
import shutil
import time
from urllib.parse import quote

from pymodels.constants import CONFIG_DIR, IMAGES_DIR
# 图标解析的三层口径（用户导入 / 云端 / 内置）统一走 cloud_icon_source：
# webhost 路由取图用的就是它，制作器这边判存在 / 找源文件必须**同口径**，
# 否则会出现"页面显示得出来、写回资源库却被裁掉"的分裂行为。
from pymodels.core.cloud_icon_source import (
    ensure_user_icons_dir, icon_file, migrate_user_icons, user_icons_dir)


def _ok(**kwargs):
    payload = {"ok": True}
    payload.update(kwargs)
    return payload


def _fail(message, **kwargs):
    payload = {"ok": False, "error": str(message or "unknown error")}
    payload.update(kwargs)
    return payload


def _log(level: str, category_zh: str, category_en: str, message: str):
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)(category_zh, category_en, message)
    except Exception:
        pass


DEFAULT_FILE = os.path.join(CONFIG_DIR, "ToolsGCP-Resources.json")
# 滚动备份的文件名：固定名、永远只有 1 份，见 rolling_backup_file()
BACKUP_FILE_NAME = "ToolsGCP-Resources.prev.json"
# 图标目录（web 版重构后的位置）：/res/image/icon/<name> 就是这里的文件。
# ⚠️ 不要再用旧的 `.ToolsGCP/Icon/`：webhost 的路由只认 images/icon。
ICON_DIR = os.path.join(IMAGES_DIR, "icon")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp", ".svg")
MAX_ICON_BYTES = 16 * 1024 * 1024


def rolling_backup_file() -> str:
    """滚动备份的目标路径：`<用户数据根>\\backups\\ToolsGCP-Resources.prev.json`。

    三个"为什么"：
    · 为什么还要留一份备份：覆盖用户唯一的资源库是破坏性操作（AGENTS.md §7 要求有护栏），
      写盘前那一份副本就是"改坏了还能手工还原"的兜底，备份失败必须中止写入。
    · 为什么改成固定名 1 份：以前每次写盘都生成一个
      `ToolsGCP-Resources.backup-<时间戳>.json`（还要轮换保留 20 个），用户明确反馈
      「我要的是改 ToolsGCP-Resources.json，不是给我攒一堆备份文件」。
    · 为什么放在用户数据根、而不是资源库同目录：`USER_DATA_ROOT` 才是程序自己产出文件的
      地方（AGENTS.md 第 9 条）；资源库同目录属于**随程序发布的资源目录**，打包成 exe 后
      多半只读、升级还会被覆盖，把备份堆在那儿等于污染用户看到的资源库目录。
      ⚠️ 绝不能指向 `py版本-已弃用仅作为参考项目，主体转为web版本/` 那种只读归档目录。
    运行时读 `constants.USER_DATA_ROOT`（不是 import 时的快照）：数据根可能被用户在
    "设置 → 存储"里搬走，自测脚本也要能把它指到临时目录。
    """
    from pymodels import constants
    return os.path.join(constants.USER_DATA_ROOT, "backups", BACKUP_FILE_NAME)


# ---------- 内置术语「显示文本 → 规范中文」反查（写侧兜底，task-24）--------
#
# 为什么必须有这一段：category / tags 在磁盘上的**值口径**是规范简体中文（见
# resource_schema 的 LANG_LIST_FIELDS），但前端制作器把三个语言池当自由文本框，
# 用户从下拉里挑到的往往是**当前界面语言的那份显示值**（English 界面下就是 "Clipboard"）。
# 旧写法只调 normalize_lang_list —— 它只管形状不管值，于是显示值被当成规范值原样落盘，
# 脏值通道就是这么来的（库里 57 条里 15 条中枪）。后果不只是难看：类别筛选/分组走
# _collect_text 那套按值精确匹配、不做术语反查，"Clipboard" 既筛不进「粘贴板」那一组，
# 又让同一个内置类别在库里同时存在两种写法。
# 读侧早就有这道反查（desktop/api/resources.py 的 _canonical_term →
# language_manager.canonical_term），落盘侧一直是空白，这里补上：进门就还原成规范值。


def _term_manager():
    """取当前语言管理器实例（术语反查表挂在它身上，见 language_manager._term_reverse）。

    为什么要自己兜底 new 一个：主链路里 desktop.shell 会建好实例并登记成"当前实例"，
    但 _normalize 也会被自测脚本 / 无窗口路径直接调用，那时没有当前实例，
    canonical_term 拿不到管理器就**原样返回** —— 表现是"兜底跑了一遍、一个脏值都没变"，
    极难查（_devtest/probe_task24_canonical.py 就是这么踩到的）。语言表只是三个小 json，
    兜底建一次的成本可忽略；反查表由 LanguageManager 缓存，随 translations 一起作废。
    """
    try:
        from pymodels.core import language_manager as _lm
    except Exception:
        return None
    try:
        manager = _lm.get_current_manager()
        if manager is None:
            manager = _lm.LanguageManager()
        return manager
    except Exception:
        return None


def canonicalize_term(value, manager=None):
    """单个 category / tags 元素：内置术语的任意语言写法 → 规范简体中文；认不出的一律原样。

    口径（lead 定死，别越界）：
      ① 简体中文 / 繁體中文 / English 三种写法都认，且**与当前界面语言无关**
         （English 界面下收到 "Clipboard" 也要还原成「粘贴板」）；
      ② 反查不到 = 用户自定义值，绝不猜、绝不丢；
      ③ 幂等：规范值在反查表里是「键→键」自等，再进一次不变。

    为什么要自己取管理器而不依赖 canonical_term 的默认值：它只在"当前实例"已登记时才能
    反查，无窗口脚本 / 单测直接调这个函数时 _current_manager 还是 None，表现是**所有值
    原样返回**（探针第一版就这么挂了一批）。这里显式兜底，调用方永远不用操心传 manager。
    """
    if manager is None:
        manager = _term_manager()
    if not isinstance(value, str):
        return value                      # dict / int 这类脏元素不猜类型，原样交回
    text = value.strip()
    if not text:
        return ""
    try:
        from pymodels.core.language_manager import canonical_term
        got = canonical_term(text, manager)
    except Exception:
        return text                       # 语言层挂了不能连累落盘：宁可留脏值，不可丢数据
    return str(got) if got else text


def _canonicalize_pool(values, manager):
    """一个语言池（list）→ 逐项反查 + 去空去重

    为什么必须去重：反查会把「粘贴板 / 粘貼板 / Clipboard」并成同一个规范值，
    不去重就留下 ["粘贴板", "粘贴板"] 这种自己跟自己重复的池子。
    """
    out = []
    for item in values:
        text = canonicalize_term(item, manager)
        if isinstance(text, str):
            if not text or text in out:
                continue
        out.append(text)
    return out


def canonicalize_lang_list(value, manager=None):
    """category / tags 落盘前的**值**兜底：形态保持（list[str] 与 {语言: list[str]} 都覆盖），
    每个元素过一遍 canonical_term；反查后三池同值 → 塌缩成扁平 list[str]。

    为什么塌缩：库里绝大多数老数据就是扁平 list[str]（规范中文），显示译名由
    translate_term 在**取用时**生成（resources.py 的 _canonical_term / DETAIL_* 那套读侧契约），
    所以「三池写同一个规范值」与「扁平一份」信息等价；留三份副本反而多三个再次写脏的口子。
    为什么三池内容不一致时保持字典原样交回：lead 口径「只统一同一条内容的不同语言写法，
    不合并本来就不同的内容」——那种情况不自动改，进迁移报告的「待用户自决」段落。
    """
    if manager is None:
        manager = _term_manager()
    if isinstance(value, (list, tuple)):
        return _canonicalize_pool(list(value), manager)
    if not isinstance(value, dict):
        return value                      # 字符串等历史脏形态：交给 normalize 的压平结果，不在这儿猜
    try:
        order = list(getattr(resource_schema, "LANGUAGE_FALLBACK", ()) or ())
    except Exception:
        order = []
    langs = [lang for lang in order if lang in value]
    langs += [lang for lang in value if lang not in langs]   # 未知语言键也要处理，不静默丢字段
    pools = {}
    for lang in langs:
        raw = value[lang]
        items = _canonicalize_pool(list(raw) if isinstance(raw, (list, tuple)) else [raw], manager)
        if items:                         # 与 normalize_lang_list 同规则：空池不写字段
            pools[str(lang)] = items
    if not pools:
        return value                      # 全语言皆空（非字符串脏形态）→ 原样，行为与改动前一致
    first = next(iter(pools.values()))
    if all(items == first for items in pools.values()):
        return first                      # 反查后三池同值 → 塌缩
    return pools


class MakerDomain:
    """资源库写盘（提交软件 / 批量合成共用）"""

    def __init__(self, shell):
        self._shell = shell
        # 第 28 轮②（m06556）：图标写读都回到程序目录，旧版落在
        # <数据根>/config/icons 的那几张先搬回来（幂等、失败只记日志，绝不拦启动）
        self._migrate_old_icons()

    # ---------- 路径 ----------
    def library_path(self) -> str:
        """制作器**写入**的目标资源库：固定是本地资源库，绝不跟着设置里的"资源来源"走。

        ⚠️ 为什么不能用 `cloud_resource_source.resolve_resource_file()`（本次修复的核心）：
           那个函数是给**读取**（搜索页 / 资源详情）按设置挑文件用的；当设置
           `resource_source=cloud` 时它返回的是从网络下载的**只读镜像缓存**
           `<用户数据根>\\config\\cloud\\ToolsGCP-Resources.json`。制作器要是照它写盘，
           会连踩两个坑：① 程序库 `.ToolsGCP\\ToolsGCP-Resources.json` 一个字节都没改，
           用户点"追加到本机资源库 / 保存到原列表"之后根本看不到自己提交的东西；
           ② 云端缓存会被下一次网络刷新整份覆盖，用户提交的条目**静默消失**、连错都不报。
           所以写盘目标必须锁死本地资源库。读取侧分两条路，别混为一谈：
           · 搜索页/详情页（`ResourcesDomain`）继续走 resolve_resource_file（跟设置里的来源）；
           · 制作器「资源浏览」走本文件的 `browse()`（跟界面下拉选的本地/云端，与设置无关）。
        · 尊重用户在"设置 → 资源库"里自定义的本地目录（`local_resource_dir`）：那个目录下
          已经有资源库文件就用它；没有就回退程序自带的 DEFAULT_FILE（否则用户会以为库空了）。
        · 任何异常也回退 DEFAULT_FILE：写盘目标不能因为设置读不出来而悬空。
        """
        try:
            from pymodels.core.cloud_resource_source import (
                RESOURCE_FILE_NAME,
                local_dir_from_settings,
            )
            manager = getattr(self._shell, "settings_manager", None)
            candidate = os.path.join(local_dir_from_settings(manager), RESOURCE_FILE_NAME)
            if os.path.isfile(candidate):
                return candidate
        except Exception:
            pass
        return DEFAULT_FILE

    # ---------- 读 ----------
    @staticmethod
    def _read(path: str):
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return {"schema_version": "2.1.0", "resources": data}, data
        if not isinstance(data, dict):
            raise ValueError("资源库不是 JSON 对象或数组")
        items = data.get("resources")
        if not isinstance(items, list):
            items = []
            data["resources"] = items
        return data, items

    # ---------- 写（原子 + 滚动备份） ----------
    @staticmethod
    def _write(path: str, data: dict):
        # ① 写盘前把旧文件滚动备份成**固定名的 1 份**：`<用户数据根>\backups\ToolsGCP-Resources.prev.json`
        #    （每次都覆盖它，不再在资源库同目录攒一串 ToolsGCP-Resources.backup-<时间戳>.json）
        #    ⚠️ 备份失败就**中止写入**（对齐 py 的 backup_library 失败即 abort）：
        #       宁可这次不写，也不能把用户唯一的一份资源库覆盖掉。
        try:
            if os.path.isfile(path):
                backup = rolling_backup_file()
                parent = os.path.dirname(backup)
                if parent:
                    os.makedirs(parent, exist_ok=True)   # 用户数据目录可能还没建 backups/
                shutil.copy2(path, backup)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "资源库", "maker", f"备份资源库失败，已中止写入: {exc}")
            raise RuntimeError(f"资源库备份失败，已中止写入（原文件没有改动）：{exc}") from exc
        # ② 临时文件 + os.replace（写到一半崩溃也不会毁掉原文件）
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, path)

    # ---------- 归一化 ----------
    @staticmethod
    def _normalize(entry: dict) -> dict:
        """把前端传来的条目规范化（字段顺序 / 空值过滤 / tags 原样保留 / 类别转 list / links 塌缩清洗）
        ⚠️ **多语言字段必须在 normalize 之后合并**。
           `resource_schema.normalize()` 会把 kind="i18n" 的字段按**当前语言**压成一句话
           （first_text），所以前端送来的 `{简体中文, 繁體中文, English}` 字典
           会在这一步被压扁成**一种语言** —— 写回资源库时繁中/英文就没了。
           对齐 py 版 `resource_maker_pages.py:1579-1582` 的做法：
               normalized = resource_schema.normalize(entry)
               return self.apply_i18n_to_entry(normalized)
           ⚠️ 这也是 py 版注释里写的提交不了三语言的根因之一。
           （之前 web 版只做了第一步，所以用户从制作器写回一次就丢一次多语言。）
        """
        try:
            from pymodels.core import resource_schema
            normalized = resource_schema.normalize(dict(entry or {}))
            return MakerDomain._merge_i18n(entry or {}, normalized)
        except Exception:
            return dict(entry or {})

    @staticmethod
    def _merge_i18n(raw: dict, normalized: dict) -> dict:
        """把**多语言字典**合并回规范化后的条目（normalize 之后做）
        ⚠️ 规则（对齐 py 版 apply_i18n_to_entry）：
          · 字段是"多语言字典"且至少一种语言有内容 → 保留字典形态写盘；
          · 三种语言内容**完全相同** → 不写字典，写成纯字符串（和前端
            applyI18nToEntry 的行为一致，避免资源库里出现无意义的同内容字典）；
          · 字典里只有一种语言有内容 → 也写成纯字符串（更紧凑，语义等价）。
        ⚠️ 只处理 kind=="i18n" 的字段（name/description/intro/supplement），
           其余字段照常走 normalize 的规范化。
        ⚠️ links（kind=="links"）不在 I18N_FIELDS 里，但它的行内 label/url 也可能是
           三语言字典 —— 上面的顶层循环够不着列表内部，塌缩在下面用 schema 的
           normalize_links 单独做（append_entry / append_entries / save_standalone
           三条写盘路径都经过这里，一处补齐三条全覆盖）。
        """
        try:
            from pymodels.core import resource_schema
        except Exception:
            return normalized
        fields = getattr(resource_schema, "I18N_FIELDS", ())
        if not fields:
            return normalized
        out = dict(normalized or {})
        for field in fields:
            value = (raw or {}).get(field)
            if not isinstance(value, dict) or not value:
                continue
            texts = {}
            for lang, text in value.items():
                clean = str(text or "").strip()
                if clean:
                    texts[str(lang)] = clean
            if not texts:
                continue
            # 语言键按 LANGUAGE_FALLBACK 归一排序（简体中文在前）：
            #   · 规范值必须是简体中文那份 —— 筛选 / 索引 / 云端镜像都按规范中文算，
            #     取"字典里恰好排第一的"会在某些前端送法下把英文值当规范值写出去；
            #   · 键序稳定后，同一份内容反复保存不会产生字节抖动（少一类无意义 diff）。
            order = list(getattr(resource_schema, "LANGUAGE_FALLBACK", ()))
            langs = [lang for lang in order if lang in texts]
            langs += [lang for lang in texts if lang not in langs]
            # 三种（或 N 种）语言内容全一样 → 写成纯字符串（需求4：同值不占三份资源；
            # 读侧靠 _collect_text / first_text 的回退链，纯字符串三种语言都能取到值）
            if len(set(texts.values())) == 1:
                out[field] = texts[langs[0]]
            else:
                out[field] = {lang: texts[lang] for lang in langs}
        # —— category / tags：按语言字典的写盘合并（task-4）——
        # normalize() 已经把这两个字段压成「简体中文那份 list[str]」——那是**读取/筛选**
        # 口径（索引必须规范中文）；制作器送来的三语字典必须在这一步原样写回去，
        # 否则「English 填了 工具, 网络」保存一次就被洗成 ["工具"]（lead 实测的数据丢失）。
        # 磁盘形态口径（与前端 poolsForEntry / applyI18nToEntry 三方一致）：
        #   · 每个语言各自 split_multi 拆成 list、各自去重（值的口径 = 规范简体中文；
        #     显示文本 → 规范值的反查见下面的 task-24 兜底段 ——
        #     原先这里写的是「canonicalTerm 是前端职责，后端不翻译」，而实测前端会送
        #     当前界面语言那份显示值（English 界面 → "Clipboard"），原样落盘就是脏值通道）；
        #   · **非空的语言**内容完全相同（或只有一种语言非空）→ 塌缩成单份 list[str]，
        #     与 52 条老数据同形、资源库保持紧凑；
        #   · 真的分语言不同 → 写 {语言: list[str]} 字典（只写非空语言，按
        #     LANGUAGE_FALLBACK 顺序）。
        # 前端 buildEntry 只在真的不同才写字典；这里再塌缩同值字典**不是重复劳动**，
        # 而是兜住老数据 / 云端镜像 / 别的写入方送来的同值字典，防"三遍同一个词"。
        norm_fn = getattr(resource_schema, "normalize_lang_list", None)
        if norm_fn is not None:
            for field in getattr(resource_schema, "LANG_LIST_FIELDS", ()):
                value = (raw or {}).get(field)
                if not isinstance(value, dict) or not value:
                    continue                  # 非字典形态：normalize 的压平结果就是最终值
                merged = norm_fn(value)
                if merged is None:
                    # 全语言皆空 = 「没有类别/标签」：normalize 已按空可选字段丢弃，别再写回
                    continue
                out[field] = merged           # list[str]（同值塌缩）或 {语言: list[str]} 字典
        # —— task-24 写侧兜底：值反查（显示文本 → 规范中文）——
        # 上面只归一了"形状"，值还可能是前端语言框送来的**显示文本**，这里补上反查：
        #  · 字典池和扁平 list 两种形态都要过（前端可能送 {"English": ["Clipboard"]}，
        #    也可能直接送 "粘贴板,Clipboard" 这种逗号串被 normalize 压平成 list）；
        #  · 反查后三池同值 → 塌缩成扁平 list[str]；三池内容本来就不同 → 保持字典原样，
        #    不自动改（lead 口径：只统一语言写法，不合并不同内容，剩下的写进迁移报告）；
        #  · 认不出的一律原样保留（用户自定义值），绝不猜、绝不丢；跑第二遍零 diff（幂等）。
        for field in getattr(resource_schema, "LANG_LIST_FIELDS", ()):
            if field in out:
                out[field] = canonicalize_lang_list(out[field])
        # —— 嵌套列表的多语言：links 行内 label/url 的三语字典塌缩 ——
        # 口径必须和读侧（resource_schema.normalize 的 kind=="links" 分支）用**同一个**
        # normalize_links，否则写进去的形态和 loader 读出来的形态会分叉。
        if "links" in (raw or {}):
            links = resource_schema.normalize_links(raw.get("links"))
            if links:
                out["links"] = links
            else:
                # 全被丢弃（空数组 / 坏协议 / 没标签）＝"没有链接"：
                # 不落 `"links": []`，与 normalize 对空可选字段的丢弃规则保持一致。
                out.pop("links", None)
        return out

    @staticmethod
    def _key_of(item: dict) -> str:
        return str(item.get("id") or "").strip() or str(item.get("code") or "").strip()

    # ---------- 图标 ----------
    def icon_dir(self) -> str:
        """内置图标目录（`.ToolsGCP/images/icon/`，`/res/image/icon/<name>` 的兜底层）
        ⚠️ save_icon 的**落盘处已改到用户导入层** `<数据根>/config/icons`
           （cloud_icon_source.user_icons_dir）；这里仍是"内置那份"的展示口径，
           返回值保持 ICON_DIR 不动（icon_path / 前端旧调用不受影响）。
        """
        return ICON_DIR

    def icon_dirs(self, name: str = "") -> dict:
        """图标到底落在哪一层 —— 给前端「打开图标文件夹」用（m06170 第 6 项）。

        ⚠️⚠️ 第 28 轮（m06454 第②项）改口：图标的**写入与读取都以程序目录为准**
           （`.ToolsGCP\\images\\icon`）。旧版本（第 24/26 轮）把用户导入的图写进了
           `<数据根>\\config\\icons`，用户按老路径找不到自己的图 —— 现在那些旧文件
           会被 `migrate_user_icons()` 搬进程序目录，用户层退为**最后兜底**。
           所以现在给前端的口径是：
          · bundled <程序目录>\\.ToolsGCP\\images\\icon   **制作器导入的新图落在这里**
          · cloud   <数据根>\\config\\cloud\\icons       云端镜像（官方那份）
          · user    <数据根>\\config\\icons            旧版本遗留 / 程序目录写不进去时的兜底
        current = 图标**实际生效**的那一层（icon_file 命中哪层就给哪层）；解析不到时
        退回程序目录（那才是现在的落点）。只读，不建目录。
        """
        try:
            from pymodels.core import cloud_icon_source as cis
            base = os.path.basename(str(name or "").strip().replace("\\", "/"))
            resolved = icon_file(base) if base else ""
            user = user_icons_dir()
            return _ok(
                current=os.path.dirname(resolved) if resolved else cis.bundled_icons_dir(),
                resolved=resolved or "",
                user=user,
                bundled=cis.bundled_icons_dir(),
                cloud=cis.icons_dir(),
            )
        except Exception as exc:
            return _fail(exc)

    @staticmethod
    def _safe_icon_name(name, ext_hint: str = "") -> str:
        """把任意文件名洗成"图标目录里能用的文件名"。
        ⚠️ 规则和 py 的 copy_into_icon_dir 不同：那边**保留中文**（Windows 允许），
           所以这里也只去掉 Windows 非法字符 + 目录部分，不做 ASCII 化 ——
           否则用户导入微信.png会被改名叫 icon.png，在资源库里对不上。
        """
        raw = str(name or "").replace("\\", "/")
        base = os.path.basename(raw)
        base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", base).strip()
        stem, ext = os.path.splitext(base)
        ext = (ext or ext_hint or ".png").lower()
        if ext not in IMAGE_EXTS:
            ext = ".png"
        stem = stem.strip() or "icon"
        return stem + ext

    def icon_path(self, name: str) -> str:
        return os.path.join(self.icon_dir(), self._safe_icon_name(name))

    def _icon_name_if_exists(self, name) -> str:
        """资源库里的 icon 字段 -> 真实存在的文件名；不存在返回空串（绝不写悬空引用）
        ⚠️ 存在性判断走 icon_file() 的**三层合并视图**（用户导入 → 云端 → 内置），
           与 webhost 路由完全同口径：用户新导入的图只落在用户层，若还按老逻辑
           只查内置 ICON_DIR，append_entry 会把刚导入的图标判成"不存在"而从
           资源库里删掉 icon 字段 —— "页面显示得出来、写回资源库却被裁掉"。
           cloud_icon_source 万一出异常时退回老口径（只认内置目录），保主流程。
        """
        base = self._safe_icon_name(name) if name else ""
        if not base:
            return ""
        try:
            return base if icon_file(base) else ""
        except Exception:
            return base if os.path.isfile(os.path.join(self.icon_dir(), base)) else ""

    def _copy_icon_to(self, name, dest_dir: str, stem: str) -> str:
        """把图标目录里的某个文件复制到 dest_dir，返回最终文件名（失败/不存在 → 空串）。
        命名优先用 <stem><ext>（stem 已按 py copy_icon 的规则 ASCII 化）；
        同名且内容相同 → 复用；冲突 → 加时间戳，绝不覆盖别人的图片。
        """
        source_name = self._icon_name_if_exists(name)
        if not source_name:
            return ""
        # 源文件同样按三层视图解析（用户导入层优先）：用户的新图只存在于
        # <数据根>/config/icons，若还只从内置 ICON_DIR 取，save_standalone 会在
        # 下面的 copyfile 处抛 FileNotFoundError（整个独立库导出失败）。
        # ⚠️ 仅改"源在哪"；复制到 Icon 文件夹后的命名/去重/冲突规则一字未动。
        try:
            source = icon_file(source_name) or os.path.join(self.icon_dir(), source_name)
        except Exception:
            source = os.path.join(self.icon_dir(), source_name)
        os.makedirs(dest_dir, exist_ok=True)
        _, ext = os.path.splitext(source_name)
        safe_stem = re.sub(r"[^A-Za-z0-9_\-]+", "", str(stem or "")) or \
            re.sub(r"[^A-Za-z0-9_\-]+", "", os.path.splitext(source_name)[0]) or "icon"
        for candidate in (f"{safe_stem}{ext}", source_name):
            dest = os.path.join(dest_dir, candidate)
            if not os.path.isfile(dest):
                shutil.copyfile(source, dest)
                return candidate
            try:
                with open(dest, "rb") as a, open(source, "rb") as b:
                    if a.read() == b.read():
                        return candidate
            except Exception:
                pass
        candidate = f"{safe_stem}-{time.strftime('%H%M%S')}{ext}"
        shutil.copyfile(source, os.path.join(dest_dir, candidate))
        return candidate

    def save_icon(self, name="", data=""):
        """把前端导入的图片**真正落盘**到**程序目录**：`.ToolsGCP/images/icon`
        ⚠️ 落点口径（第 28 轮 m06556 第②项，用户明确要求）：
           · 用户原话："修复我让他保存到当前文件夹的 .ToolsGCP\\images\\icon，
             本地资源读取也是这里"；那个 `<数据根>/config/icons` 是前几轮我自己
             挪过去的，用户从没主动创建过它 ⇒ 回滚。
           · 程序目录装进 Program Files / 只读 exe 时可能写不进去 ⇒ 那时才退回旧
             用户层（`ensure_user_icons_dir()`）并记一条 warn，否则那种环境里
             导入图片会直接失败。
        ⚠️ 同名 = 整张覆盖（tmp + os.replace），不生成 xxx(1).png ——
           资源库引用的是固定文件名，重复导入同一工具就该把旧图换掉。
        ⚠️ 为什么必须有这一步：前端 `pickIcon` 只把文件读成 dataURL 放在内存里，
           以前"追加到本机资源库"直接写 `icon: <文件名>` —— 那个文件在磁盘上根本不存在，
           资源库/搜索页的图标永远是坏的（= 假装成功）。这里补上真正的写文件。
        参数：
            name  期望文件名（前端用 code 命名，如 TG-000053.png；非图标扩展名会兜底成 .png）
            data  data URL（`data:image/png;base64,...`）或裸 base64
        返回：`{ok, name, path, url, bytes}` —— 口径不变；url 仍是 `/res/image/icon/<name>`，
           由路由按三层顺序解析（前端**不需要**加版本参数：webhost 每个响应都带
           no-store，WebView2 不会用磁盘缓存回本图）。
        """
        try:
            payload = str(data or "")
            if payload.startswith("data:"):
                _head, _sep, payload = payload.partition(",")
            if not payload:
                return _fail("图片内容是空的")
            raw = base64.b64decode(payload, validate=False)
            if not raw:
                return _fail("图片内容是空的")
            if len(raw) > MAX_ICON_BYTES:
                return _fail(f"图片太大（{len(raw) // 1024} KB > "
                             f"{MAX_ICON_BYTES // 1024} KB），请换一张小一点的")
            want = self._safe_icon_name(name)
            # ★ 落点 = 程序目录 `.ToolsGCP/images/icon`（用户指定的位置）。
            #   写不进去（只读安装目录）才退回旧用户层，并让日志说清楚落在哪。
            folder = self.icon_dir()
            try:
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, want)
                tmp = path + ".tmp"
                with open(tmp, "wb") as handle:
                    handle.write(raw)
                os.replace(tmp, path)
            except OSError as exc:
                folder = ensure_user_icons_dir()
                path = os.path.join(folder, want)
                tmp = path + ".tmp"
                with open(tmp, "wb") as handle:
                    handle.write(raw)
                os.replace(tmp, path)
                _log("warn", "资源库", "maker",
                     f"程序目录写不进图标（{exc}），已改存用户数据目录：{path}")
            _log("op", "资源库", "maker", f"已导入图标 {want}（{len(raw)} 字节）")
            return _ok(name=want, path=path, bytes=len(raw),
                       url="/res/image/icon/" + quote(want))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    # ---------- 对外接口 ----------
    def _migrate_old_icons(self):
        """把旧版落在 `<数据根>/config/icons` 的图标搬进程序目录（第 28 轮②的收尾）

        ⚠️ 为什么在构造时做：老用户的资源库 `icon` 字段指着那些文件名，搬晚一步
           （比如等用户点到那一页）卡片就先闪成首字母兜底。这里只做文件拷贝 +
           一次日志，不碰资源库；`moved` 为空就什么都不记（日常启动零噪音）。
        """
        try:
            moved = migrate_user_icons(self.icon_dir())
            if moved:
                _log("op", "资源库", "maker",
                     f"已把 {len(moved)} 个旧图标迁回程序目录 images/icon："
                     + "、".join(moved[:6]) + ("…" if len(moved) > 6 else ""))
            return moved
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "资源库", "maker", f"迁移旧图标失败（不影响使用）: {exc}")
            return []

    def info(self):
        """让页面知道"正在写到哪个文件、现在有多少条" """
        try:
            path = self.library_path()
            data, items = self._read(path)
            return _ok(path=path, count=len(items),
                       schema_version=data.get("schema_version", ""))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def browse(self, source: str = ""):
        """资源浏览按界面下拉选来源读：source='cloud' 读云端镜像，其余一律读本地资源库。

        ⚠️ 为什么不能用 `resources.all()`：那条链路走的是设置项 `resource_source`
           （cloud/local）生效来源；浏览下拉的语义是「**临时**越 over 设置看一眼另一份」，
           它既不该读设置、更不该写设置（需求：这个选择永远不落盘、永远默认本地）。
        ⚠️ 本方法**只读**：绝不调用 `_write`、不产生备份、也不触发
           `ensure_background_refresh` —— 拉取云端是设置页的职责，浏览只看已缓存的
           镜像；自测脚本据此断言"整个调用零文件写入"。
        · source='cloud' 且镜像不存在/损坏 → 回退本地那份并返回 mirrored=False，
          让前端明说"现在显示的是本地兜底"，而不是假装读到了云端。
        · 非法/空 source 一律按本地 —— 默认永远是本地。
        返回：{ok, items（磁盘原始 dict，三语言字段原样保留，由前端 mapItem 挑选）,
              path（本次实际读的文件）, source（回显请求值）, mirrored, count}
        """
        try:
            wanted = str(source or "").strip().lower()
            mirrored = True
            path = ""
            if wanted == "cloud":
                from pymodels.core.cloud_resource_source import CloudResourceSource
                # get_index_path() 纯本地读取：文件存在、能解析、resources 非空才返回路径
                path = CloudResourceSource().get_index_path()
                if not path:
                    path = self.library_path()    # 镜像没缓存：回退本地，绝不自己打网络
                    mirrored = False
            else:
                path = self.library_path()
            _data, items = self._read(path)
            return _ok(items=items, path=path,
                       source="cloud" if wanted == "cloud" else "local",
                       mirrored=mirrored, count=len(items))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def append_entry(self, entry=None, options=None):
        """新增一条；同 id（或同 code）已存在时**覆盖**
        options.confirm：前端已经弹过"覆盖确认"时为 True（保留字段，后端不做二段确认）
        对齐 py `append_to_library` 的几件"必须真做"的事：
          · 每次从**磁盘**重读资源库（不拿前端的旧副本覆盖别人的改动）；
          · 覆盖时保留原条目的 listed_at（改内容不算重新上架）；
          · icon 字段必须指向图标目录里**真实存在**的文件，否则删掉这个字段
            （绝不写悬空引用 —— 那会让搜索页显示坏图标）；
          · 写完更新 metadata.updated_at / total_count。
        """
        try:
            path = self.library_path()
            data, items = self._read(path)
            item = self._normalize(entry or {})
            key = self._key_of(item)
            if not key:
                return _fail("这条资源没有 id 或 code，无法写入")
            if not item.get("name"):
                return _fail("资源名称不能为空")

            # 图标：只认图标目录里真实存在的文件名
            icon_name = self._icon_name_if_exists(item.get("icon"))
            if icon_name:
                item["icon"] = icon_name
            else:
                item.pop("icon", None)

            action = "add"
            for index, existing in enumerate(items):
                if self._key_of(existing) == key:
                    # 覆盖：保留原上架时间（前端没显式给就沿用旧的）
                    if not item.get("listed_at"):
                        item["listed_at"] = existing.get("listed_at", "")
                    items[index] = item
                    action = "update"
                    break
            else:
                items.append(item)
            if not item.get("listed_at"):
                item["listed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

            data["resources"] = items
            metadata = data.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
                data["metadata"] = metadata
            metadata["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            metadata["total_count"] = len(items)
            self._write(path, data)
            _log("op", "资源库", "maker",
                 f"{'覆盖' if action == 'update' else '新增'}资源 {key}（{item.get('name')}）")
            return _ok(action=action, id=key, code=item.get("code", ""),
                       name=item.get("name", ""), total=len(items), path=path,
                       entry=item)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def save_standalone(self, entry=None, options=None):
        """另存为**独立资源库**：系统另存为对话框 + 写一个合法的资源库 JSON。
        对齐 py `save_standalone`：
          · 用户在系统对话框里点取消 → `{ok:true, canceled:true}`（静默，不报错）；
          · 图标如果真实存在，复制到 `目标目录/Icon/<名字>` 并改写 entry.icon，
            metadata.icon_dir 写 "Icon"（这样把这个 JSON 发给别人也能直接用）；
          · 图标不存在就删掉 icon 字段，绝不引一个不存在的文件；
          · 先写 `.tmp` 再 os.replace（半截写成不会留下坏 JSON）。
        """
        try:
            opts = options or {}
            item = self._normalize(entry or {})
            key = self._key_of(item)
            if not key:
                return _fail("这条资源没有 id 或 code，无法另存")
            if not item.get("name"):
                return _fail("资源名称不能为空")

            default_name = str(opts.get("default_name") or "ToolsGCP-Resources.json")
            picked = self._shell.pick_save_path(default_name=default_name,
                                                file_type="JSON 文件 (*.json)")
            if not picked:
                _log("info", "资源库", "maker", "用户取消了另存为独立资源库")
                return _ok(canceled=True, saved=False, path="")

            path = os.path.abspath(str(picked))
            if not os.path.splitext(path)[1]:
                path += ".json"
            parent = os.path.dirname(path) or os.getcwd()
            os.makedirs(parent, exist_ok=True)

            icon_dir = os.path.join(parent, "Icon")
            icon_name = self._copy_icon_to(item.get("icon"), icon_dir, key)
            if icon_name:
                item["icon"] = icon_name
            else:
                item.pop("icon", None)

            payload = {
                "schema_version": "2.1.0",
                "metadata": {
                    "name": "ToolsGCP Resources",
                    "description": "ToolsGCP 资源索引文件",
                    "icon_dir": "Icon",
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "total_count": 1,
                },
                "resources": [item],
            }
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp, path)
            size = os.path.getsize(path)
            _log("op", "资源库", "maker",
                 f"另存为独立资源库: {path}（{size} 字节，图标 {item.get('icon') or '无'}）")
            return _ok(canceled=False, saved=True, path=path,
                       name=os.path.basename(path), bytes=int(size),
                       count=1, icon=item.get("icon", ""))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def append_entries(self, entries=None, options=None):
        """批量合并
        options.mode = "append"（追加进现有资源库，默认）/ "new"（合并成一个新文件）
        options.duplicate = "skip"（默认）/ "overwrite"
        options.output = new 模式下的输出文件名（写到资源库同目录）
        """
        try:
            opts = options or {}
            mode = str(opts.get("mode") or "append").lower()
            dup = str(opts.get("duplicate") or "skip").lower()
            source = [self._normalize(e) for e in (entries or []) if isinstance(e, dict)]
            if not source:
                return _fail("没有可合并的条目")

            if mode == "new":
                base_path = os.path.join(os.path.dirname(self.library_path()),
                                         str(opts.get("output") or "ToolsGCP-Resources-merged.json"))
                data = {"schema_version": "2.1.0",
                        "metadata": {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                        "resources": []}
                items = data["resources"]
            else:
                base_path = self.library_path()
                data, items = self._read(base_path)

            existing_keys = {}
            for index, item in enumerate(items):
                existing_keys[self._key_of(item)] = index

            added = updated = skipped = 0
            for item in source:
                key = self._key_of(item)
                if not key:
                    skipped += 1
                    continue
                if key in existing_keys:
                    if dup == "overwrite":
                        items[existing_keys[key]] = item
                        updated += 1
                    else:
                        skipped += 1
                    continue
                existing_keys[key] = len(items)
                items.append(item)
                added += 1

            data["resources"] = items
            self._write(base_path, data)
            _log("op", "资源库", "maker",
                 f"批量合成（{mode}/{dup}）：新增 {added}，覆盖 {updated}，跳过 {skipped}")
            return _ok(path=base_path, added=added, updated=updated, skipped=skipped,
                       total=len(items), mode=mode)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)
