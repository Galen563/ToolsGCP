# -*- coding: utf-8 -*-
"""task-11（需求3 + 需求4）无头探针：详情接口 tags/category 契约 + 三语同值塌缩等价性。

为什么要有这个探针：TG-000052 的卡片把「标签」渲染成了一串 JSON —— 详情接口把磁盘上的
三语言字典原样盖回 tags / category，而前端把它当 list[str] 用。修法不是"前端判类型"，
而是**把契约钉死**：tags / category 恒为 list[str]，原始形态改由 tags_i18n / category_i18n 携带。
本探针就是这个契约的守门人（沙箱里起不来真机 GUI，走无头真链路 detail()）。

覆盖（对应交付清单）：
  A) 真链路 detail：全库 54 条 × 3 种界面语言，tags / category 必须是 list[str]，
     序列化后不含 "{" / 语言键名 / 引号冒号这类 JSON 残迹；*_i18n 原样携带磁盘形态。
  B) 8 条「标签按语言分开存」的条目：三种语言各取自己那一份，跨语言并集不变。
  C) 5 条「三语同名」的条目（TG-000013/014/017/023/042）：磁盘是纯字符串，
     三种语言读回都有值（需求4 症状：保存后再编辑，繁中/英文两格空白）。
  D) 等价性（防复发的核心不变量）：把当前磁盘形态**重新展开**成"三语完全相同的字典"
     （= 本次迁移的逆运算），全库显示值 / 并集 / canonical / 摘要 / 关键词与筛选命中
     集合 / 分组必须一字不差 —— 证明"同值字典 ≡ 单份值"，不依赖外部快照，
     以后新增资源也不会假失败。
  E) 防复发：① 全库不许再存在"三语完全相同"的字典字段（数据不变量）；
     ② 制作器写盘链路 MakerDomain._normalize 对同值 name / tags 字典必须塌缩成单份值，
        规范值取**简体中文**那份（筛选/索引依赖规范中文）；真分语言的字典保留且键序稳定；
     ③ 详情装配层对脏数据（嵌套容器 / 整段 JSON 串 / 数字 / 布尔）不抛、只丢坏元素。
  F) 行为指纹：把 D 里的指标对**快照库**（fixtures/task11_library_snapshot.json）算 md5 冻结。
      为什么跑快照而不是真实资源库：真实库是用户能用制作器随时提交的活数据 —— 拿它
      冻结指纹等于"用户每提交一条软件就假红一次"。2026-11-14 就是这样：库里 54 -> 57 条
      （用户当天 17:29/17:45/17:57 用制作器提交了 Git / 微信 / QQ），tags 字典条目
      8 -> 17 条，六段指纹全 DIFF，而 D) 形状等价性一直全绿 —— 这种假红没有信息量。
      A/B/C/E 仍跑真实库（那些断言与数据量无关，正是为了守用户真数据）。
      要更新快照：python 本探针 --snapshot（刷快照 + 打印提示，核对后重跑取新指纹）。

只读真实资源库；不写盘、不碰用户数据（D/E 全在内存 load_from_data 里跑）。
"""
import copy
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # _devtest -> 项目资料-文档与开发测试 -> 项目根
if not os.path.isfile(os.path.join(ROOT, "ToolsGCP.pyw")):
    ROOT = os.getcwd()                                  # 兜底：与其他 _devtest 脚本口径一致
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                       # noqa: BLE001
    pass

from desktop.api import resources as res_mod           # noqa: E402
from desktop.api.maker import MakerDomain              # noqa: E402
from pymodels.core import resource_loader as rl        # noqa: E402
from pymodels.core import resource_query as rq         # noqa: E402
from pymodels.core import resource_schema as rs        # noqa: E402

LIB = os.path.join(ROOT, ".ToolsGCP", "ToolsGCP-Resources.json")
SNAP = os.path.join(HERE, "fixtures", "task11_library_snapshot.json")
# --snapshot：把当前真实库刷成快照并打印六段新指纹，供作者核对后粘进 BASELINE。
# 放在这里（而不是跑段里）是为了让"刷快照"这一步不依赖旧 BASELINE 是否匹配。
if "--snapshot" in sys.argv:
    data = open(LIB, encoding="utf-8").read()
    os.makedirs(os.path.dirname(SNAP), exist_ok=True)
    open(SNAP, "w", encoding="utf-8", newline="").write(data)
    print("快照已刷新: %s（%d 条）" % (SNAP, len(json.loads(data).get("resources") or [])))
    print("请核对这批数据确实只是内容变化（不是行为回归），再重跑本探针；仍红就按末尾提示取新指纹。")
    sys.exit(0)
# ⚠️ 必须把资源库路径钉死到仓库里这一份：pymodels/constants.py 的 SCRIPT_DIR 是按
#    **sys.argv[0] 所在目录** 算的（真程序是仓库根的 ToolsGCP.pyw），探针从 _devtest/ 起跑就会算成
#    _devtest/.ToolsGCP/ToolsGCP-Resources.json，detail 跟着找不到资源（只打 WARN、不报错），
#    结论变成「全部 None」。ResourcesDomain 只在 _LibraryCache.loader 里调这一个函数，
#    patch 掉它才能让 A/B/C 走完整真链路（metrics() 自己 load_from_data，不受影响）。
res_mod.resolve_resource_file = lambda *a, **k: LIB
LANGS = tuple(rs.LANGUAGE_FALLBACK)                    # ("简体中文", "繁體中文", "English")
# 需求3 点名条目 + 8 条「标签按语言分开存」的条目（并集/回退都靠它们做样本）
TAG_DICT_CODES = ["TG-000016", "TG-000022", "TG-000041", "TG-000044",
                  "TG-000048", "TG-000050", "TG-000052", "TG-000053"]
# 需求4：本次迁移塌缩掉的 5 条"三语同名"
SAME_NAME = {"TG-000013": "Unity", "TG-000014": "Godot", "TG-000017": "SJMCL",
             "TG-000023": "Memreduct", "TG-000042": "LightC"}
# F) 行为指纹（对 fixtures/task11_library_snapshot.json 算，与真实库今后的增长无关）。
# 2026-11-15 重新冻结（task-26 多组开源仓库）：display / canonical / summaries 三段指纹变了，
#   归因**已隔离验证**（不是行为回归）：
#     · 把 normalize 输出里的 "repos" 键去掉后，display 与 canonical 的指纹**精确回到旧基线**
#       ⇒ 这两段的漂移 100% 来自「repos 进 normalize 输出」这一契约变更；
#     · summaries 除了 normalize 那条路径还多一层：resource_loader.SUMMARY_FIELDS 新增了
#       "repos"（摘要接口要带上多组仓库），所以去掉 normalize 的 repos 键它仍与旧基线不同。
#   快照数据本身没动（仍是 2026-11-14 刷的 57 条），A/B/C/D/E 全部为绿后才允许换基线。
# 2026-11-14 那次重新冻结的漂移归因（同样不是行为回归）——
#   1) 用户当天 17:29/17:45/17:57 用制作器提交 TG-000055 Git / TG-000056 微信 / TG-000057 QQ；
#   2) tags 三语字典条目 8 -> 17 条（用户编辑条目时按语言分别填标签，属正当数据变化；
#      E①「不许存在三语完全相同的字典」仍为 0 命中，说明不是写盘链路把同值铺成字典）；
#   3) 五轮需求③补录了 6 个 term 键、本轮补 term_社交 —— 只影响译名显示，不影响本探针
#      （metrics 不调 translate_term，标签显示由前端 term() 负责）。
# 冻结前 D) 形状等价性、A/B/C/E 全部为绿，才允许换基线。
BASELINE = {
    "display": "3845a214841220937653c66af15faa84",
    "all_of": "43afaf4f0159a5dfb05ef55a8334ce66",
    "canonical": "41f6c40c65b3d525c431535c489cc1d2",
    "summaries": "06fb1058b25a1ac699a8266c23e1d639",
    "queries": "ffcabf6985e3e21eba100eed48a57693",
    "groups": "f808e85d00cb7da860bd55e8bb4b42fd",
}

results = []


def add(name, ok, detail=None):
    results.append((name, bool(ok)))
    print(("  OK    " if ok else "  FAIL  ") + name
          + ("" if ok or detail is None else "   <- " + str(detail)[:400]))


class FakeSettings:
    """resource_source=local：探针必须读程序自带的资源库。
    ⚠️ 不设置就会走默认的 "cloud"，读到用户数据目录里的云端镜像（只有 52 条、数据陈旧），
       探针结论就跟这份仓库文件无关了。"""

    def __init__(self):
        self.settings = {"resource_source": "local"}


class FakeShell:
    """只提供 ResourcesDomain 需要的两样东西：设置管理器 + 当前界面语言"""

    def __init__(self):
        self.settings_manager = FakeSettings()
        self.language = "简体中文"

    def current_language(self):
        return self.language


DOMAIN = res_mod.ResourcesDomain(FakeShell())
SHELL = DOMAIN._shell


def detail_of(lang, key):
    """走真链路：前端 bridge.tryCall('resources.detail', code) 落到的就是这个函数"""
    SHELL.language = lang
    DOMAIN._cache.invalidate()                 # loader 按语言重建，换语言必须清缓存
    r = DOMAIN.detail(key, by="code")
    if not isinstance(r, dict) or r.get("ok") is not True:
        return None
    return r.get("item") or {}


def ser(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def json_residue(values):
    """detail 出口残留检查：tags / category 序列化后不许带任何 JSON 形态"""
    text = json.dumps(values, ensure_ascii=False)
    bad = []
    if "{" in text or "}" in text:
        bad.append("花括号")
    if '":' in text:
        bad.append("键值冒号")
    for lang in LANGS:
        if lang in text:
            bad.append("语言键" + lang)
    for v in values:
        s = str(v).strip()
        if s[:1] in ("{", "[") or s[-1:] in ("}", "]"):
            bad.append("元素像JSON:" + s[:40])
    return bad


def pool_expect(disk_dict, lang):
    """按契约**手算**一遍期望值：请求语言 -> 简体中文 -> 繁體中文 -> English，取第一个非空池。
    故意不复用 split_multi：探针要独立实现一遍规则，否则实现错了也一起错。"""
    for probe in (lang,) + LANGS:
        value = disk_dict.get(probe)
        if isinstance(value, str):
            cleaned = [p.strip() for p in value.split(",") if p.strip()]
        elif isinstance(value, (list, tuple)):
            cleaned = [str(v).strip() for v in value if str(v or "").strip()]
        else:
            cleaned = []
        if cleaned:
            return cleaned
    return []


def metrics(doc):
    """全库"行为指纹"：只与用户看到什么 / 搜得到什么有关，与磁盘形态无关"""
    raw_items = doc.get("resources") or []
    codes = [str(it.get("code") or it.get("id")) for it in raw_items]
    m = {"display": {}, "all_of": {}, "canonical": {}, "summaries": {},
         "queries": {}, "groups": {}, "raw_i18n": {}}
    for it in raw_items:
        code = str(it.get("code") or it.get("id"))
        m["display"][code] = {lang: ser(rs.normalize(dict(it), lang)) for lang in LANGS}
        m["all_of"][code] = {"cat": rs.categories_all_of(it), "tags": rs.tags_all_of(it),
                             "kw": sorted(rs.keywords_all_of(it))}
    terms = set()
    for it in raw_items:
        terms |= {str(t) for t in rs.categories_all_of(it)}
        terms |= {str(t) for t in rs.tags_all_of(it)}
        terms |= {str(t) for t in rs.keywords_all_of(it)}
    terms |= {"", " ", "工具", "启动器", "管理", "Clipboard", "G", "g", "1", "0015",
              "tg-000052", "TG-000013", "unity", "Godot", "SJ", "Memreduct", "LightC",
              "不存在的东西xyz", "服务器", "摳圖", "抠图"}
    cat_terms = sorted({str(t) for it in raw_items for t in rs.categories_all_of(it)})
    tag_terms = sorted({str(t) for it in raw_items for t in rs.tags_all_of(it)})
    for lang in LANGS:
        ld = rl.ResourceLoader(LIB, lang)
        if not ld.load_from_data(copy.deepcopy(doc)):      # 深拷贝：loader 会改写条目
            m["loader_ok_" + lang] = False
            continue
        items = ld.get_all()
        m["canonical"][lang] = {str(x.get("code") or x.get("id")): ser(x) for x in items}
        m["summaries"][lang] = {str(x.get("code") or x.get("id")): ser(x)
                                for x in ld.get_summaries()}
        m.setdefault("loader_count", {})[lang] = len(items)
        q = {}
        for kw in sorted(terms):
            matched, _ = rq.query(items, kw)
            q["kw:" + kw] = [str(x.get("code") or x.get("id")) for x in matched]
        for t in cat_terms:
            matched, _ = rq.query(items, "", {"category": [t]})
            q["cat:" + t] = [str(x.get("code") or x.get("id")) for x in matched]
        for t in tag_terms:
            matched, _ = rq.query(items, "", {"tag": [t]})
            q["tag:" + t] = [str(x.get("code") or x.get("id")) for x in matched]
            matched, _ = rq.query(items, t)
            q["kwt:" + t] = [str(x.get("code") or x.get("id")) for x in matched]
        for fl in ({"source": ["site"]}, {"source": ["repo"]}, {"source": ["download"]},
                   {"system": ["Windows"]}, {"category": ["工具", "系统"]},
                   {"tag": ["知名", "官方"]}, {"category": ["不存在的类别"]}, {}):
            matched, _ = rq.query(items, "", fl)
            q["fl:" + json.dumps(fl, ensure_ascii=False, sort_keys=True)] = \
                [str(x.get("code") or x.get("id")) for x in matched]
        for key in rq.SORT_KEYS:
            q["sort:" + key] = [str(x.get("code") or x.get("id")) for x in rq.sort_items(items, key)]
        q["tagopts"] = sorted(str(t) for t in rq.tag_filter_options(items))
        q["catindex"] = sorted(ld._ensure_category_index().keys())
        q["tagindex"] = sorted(ld._ensure_tag_index().keys())
        m["queries"][lang] = q
        m["groups"][lang] = {
            name: [[str(g[0]), str(g[1]), sorted(str(x.get("code") or x.get("id")) for x in g[2])]
                   for g in fn]
            for name, fn in (("category", rq.category_groups(items)),
                             ("all", rq.group_items(items, "all")),
                             ("az", rq.group_items(items, "az")),
                             ("letter", rq.letter_groups(items, "az")))}
        m["raw_i18n"][lang] = {c: ser(ld.get_raw_i18n_by_code(c)) for c in codes}
    return m


def expand_to_lang_dicts(doc):
    """迁移的逆运算：把单份值重新铺成"三语完全相同"的字典（D 用它证明两者等价）"""
    grown = copy.deepcopy(doc)
    for it in grown.get("resources") or []:
        for field in rs.I18N_FIELDS:                       # name / description / intro / supplement
            value = it.get(field)
            if isinstance(value, str) and value.strip():
                it[field] = {lang: value for lang in LANGS}
        for field in rs.LANG_LIST_FIELDS:                  # category / tags
            value = it.get(field)
            if isinstance(value, list) and value:
                it[field] = {lang: list(value) for lang in LANGS}
            elif isinstance(value, str) and value.strip():
                it[field] = {lang: value for lang in LANGS}
    return grown


def same_value_dict_fields(doc):
    """数据不变量：全库（含 schema 之外的字段）不许再有"三语完全相同"的字典"""
    hits = []
    for it in doc.get("resources") or []:
        code = str(it.get("code") or it.get("id"))
        for field, value in it.items():
            if not isinstance(value, dict) or not any(l in value for l in LANGS):
                continue
            vals = [v for v in value.values() if str(v or "").strip()]
            if len(vals) >= 2 and len(vals) == len(value) \
                    and len({ser(v) for v in vals}) == 1:
                hits.append((code, field))
    return hits


# ================= 跑 =================
doc = json.load(open(LIB, encoding="utf-8"))
items_disk = doc.get("resources") or []
codes = [str(it.get("code") or it.get("id")) for it in items_disk]

print("== A) 真链路 detail：tags / category 恒为 list[str]（%d 条 × 3 语言）==" % len(codes))
bad_type, bad_residue, missing, no_i18n = [], [], [], []
for lang in LANGS:
    for code in codes:
        item = detail_of(lang, code)
        if item is None:
            missing.append((lang, code))
            continue
        for field in ("tags", "category"):
            value = item.get(field)
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                bad_type.append((lang, code, field, value))
                continue
            residue = json_residue(value)
            if residue:
                bad_residue.append((lang, code, field, residue, value))
            if field + "_i18n" not in item:
                no_i18n.append((lang, code, field))
add("detail 全部取到（ok=True）", not missing, missing[:4])
add("tags / category 全是纯字符串数组", not bad_type, bad_type[:3])
add("序列化后不含 JSON 残迹（花括号 / 键值冒号 / 语言键）", not bad_residue, bad_residue[:3])
add("每条都带 tags_i18n / category_i18n", not no_i18n, no_i18n[:3])
tg52 = detail_of("简体中文", "TG-000052") or {}
add("TG-000052（需求3 事故条目）tags 是标签数组、不是 JSON",
    isinstance(tg52.get("tags"), list) and tg52.get("tags") == ["服务器部署", "管理"],
    tg52.get("tags"))
add("name / description / intro / supplement 形状未被改动（仍按磁盘原形态）",
    isinstance((detail_of("English", "TG-000016") or {}).get("description"), dict)
    and isinstance((detail_of("English", "TG-000013") or {}).get("name"), str))

print("== B) 按语言分开存的标签：各取自己那份 + 并集不变 ==")
# 这里原来断言「正是已知 8 条」：把某一刻的数据量当成了契约。用户用制作器编辑条目
# 会正当地把某条 tags 拆成三语字典（2026-11-14 实测已涨到 17 条，且没有一条是同值
# 字典 —— E① 不变量仍成立）⇒ 换成"已知样本必须仍是字典"这条取样前提，下面逐条真跑三语。
dict_tag_codes = sorted(str(it.get("code")) for it in items_disk if isinstance(it.get("tags"), dict))
# ⚠️ 取样前提不能写死 code 名单：task-24 迁移按用户口径把其中 7 条落成了**规范中文的纯数组**
#    （那是用户拍板的迁移结果，不是回归），「这 8 个 code 仍是字典」已不成立。
#    改成**动态取磁盘上确实是字典的条目**（B 组真正要测的就是这些），并要求至少还有一条样本。
missing_samples = [c for c in TAG_DICT_CODES if c not in dict_tag_codes]
add("磁盘上仍有三语字典样本可测（B 组取样前提）", bool(dict_tag_codes),
    {"字典条目": dict_tag_codes, "已迁移成纯数组的历史样本": missing_samples})
print("   磁盘上 tags 为字典的条目共 %d 条（信息项，不参与判定）" % len(dict_tag_codes))
wrong_pool, union_bad, wrong_raw = [], [], []
for it in items_disk:
    if not isinstance(it.get("tags"), dict):
        continue
    code = str(it.get("code"))
    union_seen = set()
    for lang in LANGS:
        item = detail_of(lang, code) or {}
        expect = pool_expect(it["tags"], lang)
        if item.get("tags") != expect:
            wrong_pool.append((code, lang, item.get("tags"), expect))
        union_seen |= set(expect)
        if item.get("tags_i18n") != it["tags"]:
            wrong_raw.append((code, lang, item.get("tags_i18n")))
    if union_seen != {str(t) for t in rs.tags_all_of(it)}:
        union_bad.append((code, sorted(union_seen), rs.tags_all_of(it)))
add("三种界面语言下各取自己那一份", not wrong_pool, wrong_pool[:3])
add("tags_i18n 原样携带磁盘字典（制作器灌池拿得到三语）", not wrong_raw, wrong_raw[:3])
add("三种语言的并集 == tags_all_of（筛选 / 索引候选不变）", not union_bad, union_bad[:3])
tg52_tw = detail_of("繁體中文", "TG-000052") or {}
tg52_en = detail_of("English", "TG-000052") or {}
# ⚠️ 期望值随 task-24 迁移改了：磁盘上的 tags 现在是**规范中文的纯数组**
#    ["服务器部署","管理"]（迁移前是三语字典，繁中/英文各有各的写法）。
#    现在要验的是「缺某种语言时按回退链取到同一份值，而不是空白/残迹」。
add("TG-000052 繁中/英文按回退链取到同一份规范标签（非空、非 JSON 残迹）",
    tg52_tw.get("tags") == ["服务器部署", "管理"]
    and tg52_en.get("tags") == ["服务器部署", "管理"],
    {"繁": tg52_tw.get("tags"), "英": tg52_en.get("tags")})
tg53 = detail_of("繁體中文", "TG-000053") or {}     # 字典里没有繁體中文 -> 必须回退简体中文
add("缺某种语言时按回退链取到值而不是空白", tg53.get("tags") == ["管理器"], tg53.get("tags"))

print("== C) 三语同名的 5 条：磁盘纯字符串、三语读回都有值 ==")
shape_bad, val_bad = [], []
for code, want in SAME_NAME.items():
    disk = next((it for it in items_disk if str(it.get("code")) == code), None)
    if disk is None or not isinstance(disk.get("name"), str) or disk.get("name") != want:
        shape_bad.append((code, disk and disk.get("name")))
        continue
    for lang in LANGS:
        if str(rs.normalize(dict(disk), lang).get("name") or "").strip() != want:
            val_bad.append((code, lang, "normalize"))
        if str((detail_of(lang, code) or {}).get("name") or "").strip() != want:
            val_bad.append((code, lang, "detail"))
        if "name" in (rs.raw_i18n_of(disk) or {}):
            val_bad.append((code, lang, "raw_i18n 仍带字典"))
add("5 条 name 在磁盘上是纯字符串", not shape_bad, shape_bad)
add("三种语言读回都有值且等于规范值（需求4 症状消失）", not val_bad, val_bad[:4])

print("== D) 等价性：单份值 <-> 三语同值字典（行为指纹，跑快照库）==")
if not os.path.isfile(SNAP):
    add("快照库存在（fixtures/task11_library_snapshot.json）", False,
        "缺失：先跑 python 本探针 --snapshot 生成")
    print("\n==== task-11 探针：快照缺失 ====\n")
    sys.exit(1)
snap_doc = json.load(open(SNAP, encoding="utf-8"))
print("   快照 %d 条 / 真实库 %d 条（真实库被用户写过属正常，指纹只对快照算）"
      % (len(snap_doc.get("resources") or []), len(codes)))
base = metrics(snap_doc)
alt = metrics(expand_to_lang_dicts(snap_doc))
segs = ["display", "all_of", "canonical", "summaries", "queries", "groups"]
diffs = [s for s in segs if ser(base.get(s)) != ser(alt.get(s))]
add("重新展开成三语同值字典后，显示值/并集/canonical/摘要/筛选命中/分组一字不差",
    not diffs, diffs)
add("原始副本段（raw_i18n）如预期不同 —— 展开后确实变成字典",
    ser(base.get("raw_i18n")) != ser(alt.get("raw_i18n")))
add("三种语言 loader 都建索引成功且条目数 == 磁盘条数",
    all(base.get("loader_ok_" + l, True) is True for l in LANGS)
    and all(len(base["canonical"].get(l) or {}) == len(codes) for l in LANGS)
    and len(base["display"]) == len(codes),
    {l: len(base["canonical"].get(l) or {}) for l in LANGS})
print("   查询用例数: " + ser({l: len(base["queries"][l]) for l in LANGS}))

print("== E) 防复发 ==")
add("全库不再存在「三语完全相同」的字典字段", not same_value_dict_fields(doc),
    same_value_dict_fields(doc)[:4])
out = MakerDomain._normalize({"id": "probe", "code": "TG-900999",
                              "name": {"English": "Unity", "简体中文": "Unity", "繁體中文": "Unity"},
                              "description": {l: "同一句话" for l in LANGS},
                              "tags": {"English": ["服务器部署", "管理"],
                                       "简体中文": ["服务器部署", "管理"],
                                       "繁體中文": ["服务器部署", "管理"]},
                              "category": {l: ["工具"] for l in LANGS},
                              "url": "https://example.com"})
add("制作器写盘：同值 name / description 塌缩成纯字符串",
    out.get("name") == "Unity" and out.get("description") == "同一句话",
    {"name": out.get("name"), "description": out.get("description")})
add("制作器写盘：同值 tags / category 塌缩成 list[str]（规范值取简体中文那份）",
    out.get("tags") == ["服务器部署", "管理"] and out.get("category") == ["工具"],
    {"tags": out.get("tags"), "category": out.get("category")})
out2 = MakerDomain._normalize({"id": "probe2", "code": "TG-900998",
                               "name": {"English": "B", "简体中文": "A", "繁體中文": "C"},
                               "tags": {"English": ["b"], "简体中文": ["a"], "繁體中文": ["c"]},
                               "url": "https://example.com"})
add("真分语言的字典保留、且键序按 LANGUAGE_FALLBACK（反复保存不抖字节）",
    list(out2.get("name") or {}) == list(LANGS) and (out2.get("name") or {}).get("简体中文") == "A"
    and list(out2.get("tags") or {}) == list(LANGS), out2.get("name"))
# 脏数据：嵌套容器、"整段字典被序列化成字符串"、数字、布尔混在一起 —— 要求不抛、也不漏 JSON。
# 脏污放在哪一种语言池里，就得按那种语言的面板去读（契约：只取自己那份，不拼接）。
dirty = {"id": "d1", "code": "TG-900997", "name": "脏数据", "url": "https://x",
         "tags": {"简体中文": [{"a": 1}, "好", "", 7, True],
                  "繁體中文": ["唔該"],
                  "English": ["好", '{"简体中文": "坏"}', 9]},
         "category": '[{"x": 1}]', "description": "d"}
zh = res_mod._merge_raw_i18n(rs.normalize(dict(dirty), "简体中文"),
                             rs.raw_i18n_of(dirty), "简体中文")
en = res_mod._merge_raw_i18n(rs.normalize(dict(dirty), "English"),
                             rs.raw_i18n_of(dirty), "English")
print("   观察到：简中=%r 英文=%r category=%r"
      % (zh.get("tags"), en.get("tags"), zh.get("category")))
add("脏数据不抛、元素全是字符串、正常标签保住、无 JSON 残迹",
    isinstance(zh.get("tags"), list) and all(isinstance(v, str) for v in zh["tags"])
    and "好" in zh["tags"] and not json_residue(zh["tags"])
    and isinstance(zh.get("category"), list) and not json_residue(zh["category"])
    and not json_residue(en.get("tags") or []),
    {"简中": zh.get("tags"), "英文": en.get("tags"), "category": zh.get("category")})
add("字典被泡成 JSON 字符串塞进标签数组时解一层捞回文字（不漏花括号）",
    en.get("tags") == ["好", "坏", "9"], en.get("tags"))
merged_none = res_mod._merge_raw_i18n({"code": "TG-900996", "name": "无标签",
                                       "tags": "工具,系统", "category": None}, {}, "繁體中文")
add("逗号串老写法照样拆成数组；字段缺失给空数组而不是 None",
    merged_none.get("tags") == ["工具", "系统"] and merged_none.get("category") == [],
    merged_none)
# detail 走的是"浅拷贝 + 改几个字段"，绝不能把 *_i18n 或字典形态写回内存索引：
# 搜索页 / 筛选 / AI 提示词全都直接吃这份 canonical
SHELL.language = "简体中文"                    # 上一个用例停在 English，这里显式钉回简中再比
DOMAIN._cache.invalidate()
DOMAIN.detail("TG-000052", by="code")         # 先跑一次 detail（可疑污染源），再去看索引
canon = DOMAIN._loader().get_by_code("TG-000052") or {}
add("detail 未污染内存索引（canonical 里没有 *_i18n、tags 仍是 list）",
    not any(k.endswith("_i18n") for k in canon) and isinstance(canon.get("tags"), list)
    and canon.get("tags") == ["服务器部署", "管理"], canon)

print("== F) 行为指纹基线（防以后改出行为漂移）==")
for seg in segs:
    digest = hashlib.md5(ser(base.get(seg)).encode("utf-8")).hexdigest()
    add("指纹一致:%s" % seg, BASELINE.get(seg) == digest,
        "实际=%s 基线=%s（数据有正常变更时按脚本末尾说明重新冻结）" % (digest, BASELINE.get(seg)))

fails = [n for n, ok in results if not ok]
print("\n==== task-11 探针 %d/%d 通过 ====" % (len(results) - len(fails), len(results)))
if fails:
    for n in fails:
        print("  FAIL:", n)
    print("先跑 python 本探针 --snapshot 刷快照；若刷完仍红才取新指纹（粘进 BASELINE）：python -c \"exec(open(r'%s',encoding='utf-8').read().split('# ================= 跑')[0]);"
          " doc=json.load(open(SNAP,encoding='utf-8'));"
          " print({s: hashlib.md5(ser(metrics(doc)[s]).encode()).hexdigest() for s in %s})\""
          % (os.path.abspath(__file__), segs))
sys.exit(1 if fails else 0)
