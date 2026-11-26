# -*- coding: utf-8 -*-
"""第五轮需求③「更多筛选里很多只有简体中文」的契约探针（离线，不起服务）。

症状根因：筛选候选 = 资源库三条语言池的并集**原样**取值，而术语表一个概念只登记
「规范简体中文值」一个键 => 同一概念的 游戏平台 / 遊戲平台 / Game platform 三项并列，
且两种非简体界面语言下都原样显示简体中文（用户看到的「只有简体中文」）。

修法（本探针逐条卡住）：
  * 术语表只登记规范值键（给别名也建键会让前端 canonicalIn 反查把别名当规范值，
    候选反而合不成一项）=> 合并方向恒为「任意写法 -> 规范值」。
  * language_manager.canonical_term 负责还原；translate_term 未命中键时先还原再查，
    所以别名写法的显示也不会漏翻译。
  * resource_query 靠**注入的 canonical 回调**做规范化，不传时原样返回：
    本模块「测试不需要语言文件」的红线（见其文件头 docstring）必须保住。
  * resource_query 是纯函数模块，所以端到端走 ResourcesDomain（本探针用 __new__ +
    假 shell 直接跑真 filter_options / query，不碰磁盘、不碰用户数据）。
"""
import json, os, sys, threading
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
# ⚠️ ROOT 用 __file__ 反推，不再依赖「从仓库根跑」这个口头约定。
#    （之前写 os.getcwd()，从 _devtest/ 里跑就会把 ROOT 指到 _devtest/，
#     后面 language_manager 找不到语言包 ⇒ 术语表只剩 en_fallback ⇒ 规范化恒等、
#     候选折叠那一组断言直接失效。）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# ⚠️ 必须钉 sys.argv[0]：constants.SCRIPT_DIR = dirname(abspath(sys.argv[0]))，
#    不钉的话 LANGUAGES_DIR 会指向 _devtest/.ToolsGCP/...（不存在），
#    language_manager 静默只加载 en_fallback —— 探针会「全绿但什么都没测」。
sys.argv[0] = os.path.join(ROOT, "ToolsGCP.pyw")
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]

from pymodels.core import language_manager as lm        # noqa: E402
from pymodels.core import resource_query as rq          # noqa: E402
from pymodels.core import resource_schema as rs         # noqa: E402
from desktop.api.resources import ResourcesDomain       # noqa: E402

RES = []


def add(name, ok, detail=None):
    RES.append((name, bool(ok)))
    print(("  OK    " if ok else "  FAIL  ") + name +
          ("" if detail is None else "   <- " + str(detail)))


# 探针脚本的 argv[0] 不在仓库根，constants.SCRIPT_DIR(=dirname(sys.argv[0])) 会算歪
# => 语言目录必须显式给 config_dir，否则术语表读不到、整个探针在测 en_fallback
MGR = lm.LanguageManager(config_dir=os.path.join(ROOT, ".ToolsGCP"))
LANGS = ("简体中文", "繁體中文", "English")
# 一个概念 -> 三种语言写法（本轮补的 11 个 + 既有键两个当对照）
CONCEPTS = {
    "游戏平台": ["游戏平台", "遊戲平台", "Game platform"],
    "轻量": ["轻量", "輕量", "Lightweight"],
    "粘贴板": ["粘贴板", "粘貼板", "Clipboard"],
    "教学辅助": ["教学辅助", "教學輔助", "Teaching aid"],
    "文件转换": ["文件转换", "文件轉換", "FileConverter"],
    "抠图": ["抠图", "摳圖", "Image matting"],
    "服务器部署": ["服务器部署", "伺服器部署", "Server deployment"],
    "管理": ["管理", "管理", "Management"],
    "管理器": ["管理器", "管理器", "Manager"],
    "AI原生浏览器": ["AI原生浏览器", "AI原生瀏覽器", "AI-native browser"],
    "工具集": ["工具集", "工具集", "Toolkit"],
    "工具": ["工具", "工具", "Tools"],
    "游戏引擎": ["游戏引擎", "遊戲引擎", "Game engines"],
}

print("== A) 三份术语表结构不变量 ==")
tables = {}
for locale in ("zh_CN", "zh_TW", "en_US"):
    path = os.path.join(ROOT, ".ToolsGCP", "modules", "languages", locale, "common_language.json")
    tables[locale] = json.load(open(path, encoding="utf-8"))
keysets = [frozenset(t) for t in tables.values()]
add("三份 common_language.json 键集完全一致", keysets[0] == keysets[1] == keysets[2])
for locale, table in tables.items():
    term_keys = [k for k in table if str(k).startswith("term_")]
    first = min((i for i, k in enumerate(table) if str(k).startswith("term_")), default=None)
    contiguous = first is not None and all(
        str(k).startswith("term_") for k in list(table)[first:first + len(term_keys)])
    add("%s: term_ 段连续（首键 %s，共 %d 键）" % (locale, first, len(term_keys)), contiguous)
    add("%s: term_ 键按 codepoint 升序" % locale, term_keys == sorted(term_keys))
    seen, dup = {}, []
    for k in term_keys:
        v = str(table[k]).strip()
        if v in seen:
            dup.append((v, seen[v], k))
        else:
            seen[v] = k
    # 同一 locale 内两个概念共用一个译名 => 反查表会把两个概念折叠成一个，
    # 候选合并就会误伤（术语表撞车属于数据 bug），所以硬卡
    add("%s: 同 locale 内译名值不撞车" % locale, not dup, dup[:4])

print("== B) canonical_term：任意写法 -> 规范值 ==")
for canon, spellings in CONCEPTS.items():
    bad = [(sp, lm.canonical_term(sp, MGR)) for sp in spellings
           if lm.canonical_term(sp, MGR) != canon]
    add("%s: 三种写法都归一到规范值" % canon, not bad, bad)
add("规范值归一后仍是自己（反查表自反）",
    all(lm.canonical_term(c, MGR) == c for c in CONCEPTS))
add("未知自定义值原样返回（用户自己输入的类别绝不被吞）",
    lm.canonical_term("我自己造一个类别", MGR) == "我自己造一个类别")
_saved = lm._current_manager
lm._current_manager = None
add("无 manager 时 canonical_term 原样返回（resource_query 纯函数性质的地基）",
    lm.canonical_term("遊戲平台") == "遊戲平台")
lm._current_manager = _saved

print("== C) translate_term：别名写法在三种语言下都有本地化 label ==")
for lang in LANGS:
    MGR.set_language(lang)
    idx = LANGS.index(lang)
    bad = []
    for canon, spellings in CONCEPTS.items():
        want = spellings[idx]
        for sp in spellings:
            got = lm.translate_term(sp, MGR)
            if got != want:
                bad.append((canon, sp, got, want))
    add("%s: %d 个概念的三种写法 label 全对" % (lang, len(CONCEPTS)), not bad, bad[:4])
MGR.set_language("English")
add("translate_term(canonical_term(v)) == translate_term(v)（往返一致）",
    all(lm.translate_term(lm.canonical_term(sp, MGR), MGR) == lm.translate_term(sp, MGR)
        for sps in CONCEPTS.values() for sp in sps))
add("查不到的值原样返回，绝不吞（用户新类别）",
    lm.translate_term("我自己造一个类别", MGR) == "我自己造一个类别")

print("== D) 真实资源库：候选合并 + 三语 label（走真 filter_options）==")


class _StubShell:
    """只给 filter_options / query 用到的那几个口子，绝不碰磁盘/用户数据"""

    def __init__(self, items, manager):
        self.language_manager = manager
        self.favorites_manager = None
        self._items = items

    def current_language(self):
        return "简体中文"


LIB = json.load(open(os.path.join(ROOT, ".ToolsGCP", "ToolsGCP-Resources.json"),
                     encoding="utf-8"))["resources"]
# loader 读盘时预算了 category_all/tags_all；这里用同一套函数现算，候选口径与线上一致
ITEMS = []
for it in LIB:
    one = dict(it)
    one["category_all"] = rs.categories_all_of(it)
    one["tags_all"] = rs.keywords_all_of(it)
    ITEMS.append(one)


def make_domain(items):
    rd = ResourcesDomain.__new__(ResourcesDomain)   # 绕开 __init__（它会起缓存/云同步）
    rd._shell = _StubShell(items, MGR)
    rd._all_items = lambda: items
    rd._latest = set()
    rd._latest_lock = threading.Lock()
    return rd


RD = make_domain(ITEMS)
per_lang = {}
for lang in LANGS:
    # 真机切换语言时 shell 会同步 language_manager.current_language，探针必须照做：
    # filter_options(language=) 那个参数只进信封（以及收藏夹显示名），候选 label 走的是
    # manager 的当前语言（_translate_term 的唯一事实来源）。不同步就会拿到上一轮循环的语言。
    MGR.set_language(lang)
    payload = RD.filter_options(language=lang)
    if not payload.get("ok"):
        print("filter_options(%s) 失败: %s" % (lang, payload.get("error")))
        sys.exit(2)
    per_lang[lang] = payload

vals = dict((lang, [o["value"] for o in per_lang[lang]["tag"]]) for lang in LANGS)
labels = dict((lang, dict((o["value"], o["label"]) for o in per_lang[lang]["tag"])) for lang in LANGS)
add("三种界面语言下候选 value 集合完全相同（值恒规范中文）",
    vals["简体中文"] == vals["繁體中文"] == vals["English"],
    [len(vals[l]) for l in LANGS])
# 繁简体同字是常态（工具 / 管理 / 管理器 / 工具集 三种写法完全一样），所以别名集合必须
# 先扣掉各概念的规范值本身，否则会把规范值误报成「没折叠干净的别名」。
alias_set = (set(sp for sps in CONCEPTS.values() for sp in sps)
             - set(sps[0] for sps in CONCEPTS.values()))
alias_in = [v for v in vals["简体中文"] if v in alias_set]
add("候选里没有别名写法（一个概念只留规范值那一项）", not alias_in, alias_in)
dupv = [v for v in set(vals["简体中文"]) if vals["简体中文"].count(v) > 1]
add("候选 value 列表无重复项", not dupv, dupv)

for lang in ("繁體中文", "English"):
    idx = LANGS.index(lang)
    wrong = []
    for canon, spellings in CONCEPTS.items():
        if canon in labels[lang] and labels[lang][canon] != spellings[idx]:
            wrong.append((canon, labels[lang][canon], spellings[idx]))
    add("%s: 命中概念的 label 全部本地化" % lang, not wrong, wrong)

zh_common = MGR.translations.get("zh_CN", {}).get("common", {})
no_term = [v for v in vals["简体中文"]
           if not zh_common.get("term_" + str(lm.canonical_term(v, MGR)))]
add("库里每个候选值都查得到术语键（没有只剩简体中文的漏网项）", not no_term, no_term)

print("== E) 只有非简体语言池的条目也能被规范值筛中 ==")
EN_ONLY = [{"code": "TG-900001", "name": "OnlyEnglish",
            "category_all": ["Game platform"], "tags_all": ["Toolkit", "Lightweight"]}]
RD2 = make_domain(EN_ONLY + ITEMS)
# ResourcesDomain.query 返回 _ok 信封字典（不是元组）：res["ok"] / res["items"]
res = RD2.query("", {"category": ["游戏平台"]})
matched = res.get("items") or []
add("选规范值『游戏平台』能筛中只在 English 池填过的条目（两侧同口径规范化）",
    any(m["code"] == "TG-900001" for m in matched), [m["code"] for m in matched][:3])
res2 = RD2.query("", {"tag": ["工具集"]})
matched2 = res2.get("items") or []
add("标签同理（工具集 / Toolkit 折叠成一项）",
    any(m["code"] == "TG-900001" for m in matched2))
POOL = EN_ONLY + ITEMS
old_hits = [it for it in POOL if rq.passes_filters(it, {"category": ["游戏平台"]})]
new_hits = [it for it in POOL
            if rq.passes_filters(it, {"category": ["游戏平台"]}, canonical=MGR.canonical_term)]
add("不传 canonical = 老口径零改变（纯函数性质保住）",
    all(it["code"] != "TG-900001" for it in old_hits) and
    any(it["code"] == "TG-900001" for it in new_hits))

print("== F) 老数据零回归 ==")
OLD_SHAPE = [{"code": "TG-900002", "name": "老形态",
              "category_all": ["工具"], "tags_all": ["工具", "网络"]}]
a = rq.tag_filter_options(OLD_SHAPE)
b = rq.tag_filter_options(OLD_SHAPE, MGR.canonical_term)
add("全是规范值时规范化前后候选一字不差", a == b == ["工具", "网络"], (a, b))
raw_uniq = rq.tag_filter_options(ITEMS)                  # 老口径：别名各占一项
folded_expect = sorted(set(lm.canonical_term(v, MGR) for v in raw_uniq))   # 期望的新口径
# ⚠️ 原来这条还要求「确实折叠掉了几项」（len(folded) < len(raw)）。
#    那条前提在 task-24 迁移之后已经不成立：真实库的类别/标签已全部落成**规范中文**，
#    库里根本不存在别名写法 ⇒ 规范化是恒等的，折叠自然一项都折不掉。
#    「折叠真的会发生」必须用**合成数据**验证（见下一条），拿真实库去量是量错了对象。
add("候选 == 老口径逐项规范化后的集合（候选恒为规范值）",
    vals["简体中文"] == folded_expect,
    (len(raw_uniq), len(folded_expect)))
# 用合成数据证明折叠真的会做：同一概念的三种语言写法（别名）要并成一项。
# 用 CONCEPTS 里登记的**真实三语写法**当别名（手写繁体容易写错字形，那就测不到折叠）。
SYNTH = [{"code": "TG-900003", "name": "synthetic",
         "category_all": CONCEPTS["\u6e38\u620f\u5e73\u53f0"],
         "tags_all": CONCEPTS["\u6e38\u620f\u5e73\u53f0"]}]
synth_raw = rq.tag_filter_options(SYNTH)
synth_folded = rq.tag_filter_options(SYNTH, MGR.canonical_term)
add("合成数据：别名写法确实被折叠成一项（游戏平台/遊戲平台/Game platform -> 游戏平台）",
    synth_folded == ["\u6e38\u620f\u5e73\u53f0"] and len(synth_folded) < len(synth_raw),
    (synth_raw, synth_folded))

print("== G) 关键词搜索口径不变（第一轮用户定夺）==")
kw = [it for it in POOL if rq.match_keyword(it, "Game platform", "")]
add("各语言写法仍能被关键词搜到（match_keyword 未被规范化影响）",
    any(it["code"] == "TG-900001" for it in kw))
kw2 = [it for it in POOL + [{"code": "TG-900002", "name": "x",
                             "category_all": ["工具"], "tags_all": ["工具"]}]
       if rq.match_keyword(it, "工具", "")]
add("中文关键词照旧命中", any(it["code"] == "TG-900002" for it in kw2))

print()
ok = sum(1 for _n, v in RES if v)
print("结果: %d/%d 通过" % (ok, len(RES)))
sys.exit(0 if ok == len(RES) else 1)
