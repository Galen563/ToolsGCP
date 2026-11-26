# -*- coding: utf-8 -*-
"""老数据零回归的**正确**验证方式。

⚠️ 不能断言 "normalize(磁盘条目) == 磁盘条目"：
   resource_schema.normalize() 的语义是「读时把多语言字段压平成当前语言」，
   磁盘上 name/description/intro/supplement 存的是三语字典，
   所以 normalize 的结果**本来就不等于**磁盘原文 —— 这是设计如此（v1.1.4 起一直如此）。

⚠️ 上一版这里还多卡了一条**不成立的前提**（本轮修正）：
   它假设「整个资源库的 category/tags 都是老形态（list / 逗号串）」，
   于是要求 normalize 前后 category/tags **一字不差**。
   制作器支持「按语言独立填写」之后，真实资源库里已经出现了新形态
   （{语言: [...]} 字典，例如 TG-000002 / TG-000005 / TG-000016 的 tags
   只有简体池带「知名」）—— 那是**正常数据**，把它压平成「当前语言那一份」
   正是本轮的设计目标，所以「一字不差」对这类条目本身就是错的断言。
   ⇒ 现在拆成两条各自成立的不变量：B1 只管老形态条目（零回归），
      B2 管新形态条目（压平与并集都要符合契约）。

该断言的是这几件事：
  A.  normalize 自身幂等：normalize(normalize(x)) == normalize(x)
  B1. 老形态条目：本轮改动没有改变 normalize 对它的输出（category/tags 一字不差，
      且并集 == 显示值 ⇒ 与改动前完全等价）
  B2. 新形态条目：按语言取到的是**该语言那一份池**；并集恰好等于所有池的并
  C.  三条写盘路径都保留三语字典
  D.  读侧按语言取整份 + 老形态读法不变
"""
import json, os, sys
# Windows 控制台默认 GBK：断言名里的 ⇒ ⊆ ⚠️ 等字符 print 时会 UnicodeEncodeError 打断脚本，
#   把真实退出码变成 1（本轮实测复现）。errors="replace" 只影响显示，不改变判定。
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
sys.path[:0] = [os.path.join(os.getcwd(), ".ToolsGCP"),
                os.path.join(os.getcwd(), ".ToolsGCP", "modules")]
from pymodels.core import resource_schema as rs      # noqa: E402

lib = json.load(open(".ToolsGCP/ToolsGCP-Resources.json", encoding="utf-8"))["resources"]
res = []
def add(name, ok, detail=None):
    res.append((name, bool(ok)))
    print(("  OK    " if ok else "  FAIL  ") + name + ("" if detail is None else "   <- " + str(detail)))

print("== A) normalize 幂等 ==")
twice = [it.get("code") for it in lib
         if rs.normalize(rs.normalize(dict(it))) != rs.normalize(dict(it))]
add("normalize(normalize(x)) == normalize(x) 全条通过", not twice, twice[:5])

print("== B) category/tags 按形态分开卡不变量 ==")
I18N_ONLY = set(rs.I18N_FIELDS)
LANG_KEYS = set(rs.LANGUAGE_FALLBACK)

def is_lang_dict(value):
    """是不是「按语言字典」形态（命中任一语言键才算，脏字典不算）"""
    return isinstance(value, dict) and any(k in LANG_KEYS for k in value)

old_bad, new_bad, union_bad = [], [], []
new_form = []
for it in lib:
    n = rs.normalize(dict(it))
    for field in ("category", "tags"):
        disk = it.get(field)
        out = n.get(field)
        if is_lang_dict(disk):
            new_form.append((it.get("code"), field))
            # B2-1 按语言取：该语言有池就取那一份（值恒为规范中文）
            for lang, pool in disk.items():
                if lang not in LANG_KEYS:
                    continue
                # ⚠️ 必须拿**磁盘原始条目 it** 取：n 已经按默认语言压平了，
                #    从压平结果里再要「繁体那一份」只会拿回默认语言的值（探针自身错误）。
                got = (rs.categories_of(it, lang) if field == "category"
                       else rs.tags_of(it, lang))
                want = rs.split_multi(pool, lang)
                if got != want:
                    new_bad.append((it.get("code"), field, lang, got, want))
            # B2-2 并集：必须恰好等于所有池拼起来去重（不丢值、也不凭空造值）
            joined = []
            for lang in rs.LANG_POOL_ORDER:
                if disk.get(lang) is not None:
                    joined.extend(rs.split_multi(disk[lang], lang))
            expect_union = rs.dedup(joined)
            got_union = (rs.categories_all_of(it) if field == "category"
                         else rs.tags_all_of(it))
            if got_union != expect_union:
                union_bad.append((it.get("code"), field, got_union, expect_union))
        else:
            # B1 老形态：一字不差，且并集 == 显示值
            if out != disk:
                old_bad.append((it.get("code"), field, disk, out))
            got_union = (rs.categories_all_of(it) if field == "category"
                         else rs.tags_all_of(it))
            if got_union != rs.split_multi(disk, "简体中文"):
                union_bad.append((it.get("code"), field + "(老形态)", got_union, None))

add("B1 老形态条目 normalize 前后一字不差（本轮零回归）", not old_bad, old_bad[:5])
add("B2 新形态条目按语言取到自己那一份", not new_bad, new_bad[:5])
add("B2 并集恰好等于所有语言池之并（不丢值/不造值）", not union_bad, union_bad[:5])
print("     （库里新形态 category/tags 条目：%s）" % (new_form or "无"))

# 差异字段仍然只允许落在 i18n 字段 + 新形态的 category/tags 上
only_i18n = []
for it in lib:
    n = rs.normalize(dict(it))
    diff = set(k for k in set(list(n) + list(it)) if n.get(k) != it.get(k))
    legal = set(I18N_ONLY)
    for field in ("category", "tags"):
        if is_lang_dict(it.get(field)):
            legal.add(field)
    # task-26：老数据只有 github 时 normalize 会补出一个 repos 键（多组开源仓库的互填不变量，
    # 见 resource_schema._sync_github_repos）。这是**契约要求**的差异，不是回归 ⇒ 合法。
    if "repos" in diff and "github" in it:
        legal.add("repos")
    if not diff <= legal:
        only_i18n.append((it.get("code"), sorted(diff - legal)))
add("差异字段 ⊆ i18n 字段 ∪ 新形态的 category/tags", not only_i18n, only_i18n[:5])

print("== C) 三条写盘路径都保留三语字典 ==")
cat = {"简体中文": ["工具"], "繁體中文": ["工具"], "English": ["工具", "网络"]}
tags = {"简体中文": ["官方"], "English": ["官方", "知名"]}
from desktop.api.maker import MakerDomain            # noqa: E402
entry = {"id": "p", "code": "TG-9", "name": "P", "category": cat, "tags": tags}
m = MakerDomain._normalize(dict(entry))
add("append_entry 路径（_normalize）保留字典",
    m.get("category") == cat and m.get("tags") == tags,
    {"category": m.get("category"), "tags": m.get("tags")})
for fname in ["append_entries", "save_standalone"]:
    src = open(".ToolsGCP/desktop/api/maker.py", encoding="utf-8").read()
    i = src.find("def " + fname)
    body = src[i:i + 2600] if i >= 0 else ""
    add("%s 也经过 _normalize/_merge_i18n" % fname,
        "_normalize(" in body or "_merge_i18n(" in body,
        body.count("_normalize(") + body.count("_merge_i18n("))

print("== D) 读侧按语言取整份（回归保险） ==")
add("categories_of English == [工具, 网络]",
    rs.categories_of({"category": cat}, "English") == ["工具", "网络"],
    rs.categories_of({"category": cat}, "English"))
add("老形态（数组）仍按原样读",
    rs.categories_of({"category": ["工具", "网络"]}, "English") == ["工具", "网络"],
    rs.categories_of({"category": ["工具", "网络"]}, "English"))
add("逗号串老形态仍拆得开",
    rs.categories_of({"category": "工具,游戏"}, "简体中文") == ["工具", "游戏"],
    rs.categories_of({"category": "工具,游戏"}, "简体中文"))
add("i18n 字段读语义未被改动（first_text 仍取一句话）",
    rs.first_text({"简体中文": "甲", "English": "A"}, "English") == "A",
    rs.first_text({"简体中文": "甲", "English": "A"}, "English"))

fails = [n for n, ok in res if not ok]
print("\n==== %d/%d 通过 ====" % (len(res) - len(fails), len(res)))
sys.exit(1 if fails else 0)
