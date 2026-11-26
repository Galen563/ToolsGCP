
# -*- coding: utf-8 -*-
"""task-24 存量迁移：把 ToolsGCP-Resources.json 里 category / tags 上的**显示文本**反查回规范中文。

⚠️ 脏形态是直接写在 category / tags 字段上的三语字典（**不是** *_i18n 字段）；
   扫 e[f + "_i18n"] 会得到 0 个，别按那个口径改脚本。

口径（lead 定夺，逐条对应）：
  1. 只统一「同一条内容的不同语言写法」→ 反查后三池同值就塌缩成扁平 list[str]（与库里
     44 条老数据同形；显示译名由读侧 translate_term 现算，塌缩不丢信息）。
  2. 三池内容**本来就不一致**（例：TG-000016 简体多一个「知名」）→ 一个字都不改，
     只写进报告的「三池不一致（待用户自决）」，附三池现值 + 建议。
  3. TG-000055 的 category 用户明确要「都改为编程」→ 非默认值赢，覆盖规则 2。
  4. TG-000027 用户已自己改好 → 禁动（HARD_SKIP）。
默认 dry-run，只打印 (code, 字段, 语言池, before→after) 全表；--apply 才落盘，
落盘前调 maker.rolling_backup_file() 生成滚动备份，并另存快照到 _devtest/_bak/。
"""
import hashlib
import io
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEV = os.path.dirname(os.path.abspath(__file__))
# 为什么改 argv[0]：pymodels.constants 用 dirname(abspath(sys.argv[0])) 定位资源根，
# 脚本放在 _devtest 下会把 CONFIG_DIR / LANGUAGES_DIR 算成 _devtest\.ToolsGCP（不存在），
# 于是语言表全空、术语反查原样返回 —— 看起来就像"迁移跑了但一个脏值都没变"。
sys.argv[0] = os.path.join(ROOT, "ToolsGCP.pyw")
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]

try:                                    # 控制台是 GBK：中文打印必须先降级成 replace，别抛 UnicodeEncodeError
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

from desktop.api import maker            # 写侧兜底（canonicalize_*）与 rolling_backup_file 的**同一份实现**
from pymodels.core import resource_schema

LIB = os.path.join(ROOT, ".ToolsGCP", "ToolsGCP-Resources.json")
SNAPSHOT = os.path.join(DEV, "_bak", "ToolsGCP-Resources.before_task24.json")
REPORT = os.path.join(DEV, "task24_migration_report.txt")
FIELDS = ("category", "tags")


def entries(data):
    """资源库条目列表：顶层键是 resources（历史/别的写入方可能叫 items，兼容一下不报错）"""
    for key in ("resources", "items"):
        if isinstance(data.get(key), list):
            return data[key]
    raise SystemExit("看不懂的资源库结构：顶层键 = %s" % list(data.keys()))

# 规则 3：用户点名要覆盖「三池不一致不自动改」的条目 —— {(code, field): 目标值}
MANUAL_OVERRIDE = {("TG-000055", "category"): ["编程"]}
# 规则 4：用户已自改，禁动
HARD_SKIP = {"TG-000027"}
# 规则 2 的补充（执行中发现任务书自相矛盾，lead 已于 2026-11-14 23:1x 定夺）：TG-000022 曾被同时
# 列进"已确认脏值"和"三池不一致⇒不自动改"两个互斥桶。实测三池内容**一致**（[实用,系统,粘贴板] 的
# 三种语言写法），"多了系统"这个前提不成立 ⇒ 按用户口径「只统一同一条内容的不同语言写法」应当改。
# 名单清空保留在案，是为了提醒：往后再遇到"同一桶冲突"，判据是**实测内容**，不是任务书举例。
PENDING_LEAD = set()


def pools_of(value):
    """{语言: list} 或扁平 list → [(语言或 None, 该份 list)]，供逐池打印"""
    if isinstance(value, dict):
        rows = []
        for lang in list(resource_schema.LANGUAGE_FALLBACK) + [k for k in value
                                                              if k not in resource_schema.LANGUAGE_FALLBACK]:
            if lang in value:
                rows.append((lang, value[lang] if isinstance(value[lang], list) else [value[lang]]))
        return rows
    if isinstance(value, list):
        return [(None, value)]
    return []


def dirty_in(value):
    """该值里还留着多少「显示文本当规范值」的元素 -> [(语言, 现值, 规范值)]"""
    hits = []
    for lang, items in pools_of(value):
        for it in items:
            canon = maker.canonicalize_term(it)
            if isinstance(it, str) and canon != it:
                hits.append((lang, it, canon))
    return hits


def plan_for(entry):
    """一条条目 -> 每个字段的处置；返回 (changes, undecided, notes)"""
    changes, undecided = [], []
    code = str(entry.get("code") or entry.get("id") or "?")
    for field in FIELDS:
        if field not in entry:
            continue
        value = entry[field]
        if code in HARD_SKIP:
            continue
        if not isinstance(value, (list, dict)):
            if value is not None:
                undecided.append({"code": code, "field": field, "kind": "其它形态",
                                  "before": value, "why": "非 list/dict 的历史形态，"
                                            "本次口径只覆盖语言池字典与扁平 list，不自动改",
                                  "suggest": None})
            continue
        if (code, field) in MANUAL_OVERRIDE:
            # ⚠️ 幂等硬伤（第一次 --apply 后复跑报告"二次仍有变更：TG-000055.category
            # ["编程"] -> ["编程"]"就是这个分支造成的）：手工覆盖表**无条件**产出一条 change，
            # 磁盘上已经是目标值时也会再报一次"变更"，只是 before == after 看着像没变。
            # 规划器必须先看一眼现值，等于目标值就当无事发生 —— 否则「幂等复跑必须 0 变更」
            # 这道验收闸门永远关不掉，下次真不幂等也会被这条已知噪声掩盖。
            if value == MANUAL_OVERRIDE[(code, field)]:
                continue
            changes.append({"code": code, "field": field, "kind": "用户指定覆盖",
                            "before": value, "after": MANUAL_OVERRIDE[(code, field)],
                            "detail": "lead 明确要「都改为编程」⇒ 非默认值赢（三池不一致也不自动合，"
                                      "这条按用户指定写扁平 list[str]）"})
            continue
        pools_can = {lang: [maker.canonicalize_term(x) for x in items]
                     for lang, items in pools_of(value) if items}
        if (code, field) in PENDING_LEAD:
            undecided.append({"code": code, "field": field, "kind": "待 lead 定夺",
                              "before": value,
                              "why": "任务书把它列为「三池多了『系统』⇒ 不自动改」的例子，但实测三池内容"
                                     "一致（反查后都是 %s）⇒ 前提不成立；已请 lead 定夺，未答复前不动盘"
                                     % jdump(next(iter(pools_can.values()), [])),
                              "suggest": pools_can})
            continue
        after = maker.canonicalize_lang_list(value)
        # 「三池不一致」的判定口径 = **反查后各池内容仍不相等**（与"值有没有变"无关）：
        # TG-000016 那种"简体多一个知名"本来就一个脏值都没有，但 lead 要求它在待自决清单里，
        # 所以必须按内容判，不能只按 diff 判。
        vals = list(pools_can.values())
        inconsistent = isinstance(value, dict) and any(v != vals[0] for v in vals[1:])
        if inconsistent:
            # 用户口径是两件事，必须分开执行：**不合并本来就不同的内容**（三池各留自己那几项，
            # 保持字典、不塌缩）＋**统一同一条内容的不同语言写法**（把 摳圖→抠图 这类还原成规范中文）。
            # 以前这里整字段 continue，把两件事混成一件 ⇒ TG-000050 的 摳圖/去背/AI圖像/
            # Background Removal/AI Cutout 五个显示文本被"内容不一致"豁免，永远留在盘上。
            # canonicalize_lang_list 对内容不一致的字典正好只做「逐池反查、不塌缩」（maker.py:193-196），
            # 所以直接用它，不自己另写一套池循环。
            if after != value:
                changes.append({"code": code, "field": field, "kind": "逐池反查（内容仍不一致⇒不塌缩）",
                                "before": value, "after": after,
                                "detail": "只统一语言写法，不合并内容；三池差异原样保留"})
            undecided.append({"code": code, "field": field, "kind": "三池不一致",
                              "before": value,
                              "why": "各语言池内容不相等（反查回规范中文后仍不相等）⇒ 属于「内容本来就不同」，"
                                     "按口径不自动合并"
                                     + ("；同一项的语言写法已还原成规范中文" if after != value
                                        else "；本字段没有可还原的写法，值原样未动"),
                              "suggest": pools_can})
            continue
        if after == value:
            continue
        if isinstance(value, dict):
            kind = "塌缩+反查" if dirty_in(value) else "纯形状塌缩（值未变）"
        else:
            kind = "扁平 list 反查"
        changes.append({"code": code, "field": field, "kind": kind,
                        "before": value, "after": after, "detail": ""})
    return changes, undecided


def jdump(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=False)


def build(data):
    """跑一遍规划：返回 (报告行, 变更数, 待自决列表, 应用函数)"""
    all_changes, all_undecided = [], []
    for entry in entries(data):
        ch, un = plan_for(entry)
        all_changes += ch
        all_undecided += un
    return all_changes, all_undecided


def apply_changes(data, changes):
    idx = {str(e.get("code") or e.get("id") or "?"): e for e in entries(data)}
    for ch in changes:
        idx[ch["code"]][ch["field"]] = ch["after"]



def dumps(data):
    """与落盘**逐字节同构**的序列化（同 indent / ensure_ascii / 结尾一个换行）。
    幂等验收要回答的是"再写一遍有没有变化"，所以跟磁盘原文比，而不是比 Python 对象。"""
    buf = io.StringIO()
    json.dump(data, buf, ensure_ascii=False, indent=2)
    buf.write("\n")
    return buf.getvalue()


def write_report(ctx):
    """迁移报告：改了哪些条哪些值 / 幂等复跑 / 三池不一致待自决 / 剩余脏值命中（分两桶）

    ctx 带的是**本次真实落盘**的信息；--verify 复用 _t24_apply.json 里存档的落盘全表，
    这样"报告"描述的始终是那次实际发生的写入，而不是复跑时那个空计划。
    """
    undecided, rescan = ctx["undecided"], ctx["rescan"]
    pending_keys = {(u["code"], u["field"]) for u in undecided}
    fixable = [r for r in rescan if (r[0], r[1]) not in pending_keys]
    held = [r for r in rescan if (r[0], r[1]) in pending_keys]
    L = []
    L.append("=" * 78)
    L.append("task-24 迁移报告 · ToolsGCP-Resources.json 里 category/tags 的显示文本 → 规范中文")
    L.append("=" * 78)
    L.append("生成时间      = %s" % ctx["generated_at"])
    L.append("资源库        = %s" % LIB)
    L.append("条目数        = %d" % ctx["n_entries"])
    L.append("滚动备份      = %s" % ctx["backup"])
    L.append("任务前快照    = %s" % SNAPSHOT)
    L.append("落盘前 sha256 = %s" % ctx["sha_before"])
    L.append("落盘后 sha256 = %s" % ctx["sha_after"])
    L.append("当前 sha256   = %s" % hashlib.sha256(io.open(LIB, "rb").read()).hexdigest())
    L.append("")
    L.append("── 一、本次改动的条目与值（共 %d 处；before→after，逐语言池列出）──" % ctx["n_changes"])
    L.append("")
    L.append(ctx["applied_table"].rstrip())
    L.append("")
    L.append("── 二、幂等复跑结果 ──")
    L.append("")
    L.append("重新规划：二次变更 = %d 处（验收要求 0）；二次待自决 = %d 处（应与落盘前同一批）"
             % (len(ctx["ch2"]), len(ctx["un2"])))
    for c in ctx["ch2"]:
        L.append("    !! 二次仍有变更：%s.%s %s -> %s"
                 % (c["code"], c["field"], jdump(c["before"]), jdump(c["after"])))
    L.append("按现盘内容重新序列化，与磁盘字节比较：%s（一致 ⇒ 复跑不再产生任何写入）"
             % ("字节级一致" if ctx["byte_identical"] else "!! 有差异"))
    L.append("")
    L.append("── 三、三池不一致（待用户自决，未合并内容）：%d 处 ──" % len(undecided))
    L.append("")
    if not undecided:
        L.append("（无）")
    for u in undecided:
        L.append("[%s] %s.%s" % (u["kind"], u["code"], u["field"]))
        L.append("    现值 = %s" % jdump(u["before"]))
        L.append("    原因 = %s" % u["why"])
        if u["suggest"]:
            L.append("    建议 = %s" % jdump(u["suggest"]))
            for lang, items in pools_of(u["before"]):
                hits = [(x, maker.canonicalize_term(x)) for x in items
                        if isinstance(x, str) and maker.canonicalize_term(x) != x]
                if hits:
                    L.append("      %s 池残留显示文本：%s" % (lang, "、".join("%s→%s" % h for h in hits)))
        L.append("    处置 = 内容差异保留原样；要合并请用户在制作器里重填该条")
        L.append("")
    L.append("── 四、剩余脏值命中数 ──")
    L.append("")
    L.append("可自动修桶（验收要求 = 0）      ：%d 处" % len(fixable))
    for r in fixable:
        L.append("    !! %s.%s [%s] %s -> %s" % (r[0], r[1], r[2], r[3], r[4]))
    L.append("待用户自决桶（第三节那些，不修）：%d 处" % len(held))
    for r in held:
        L.append("    -- %s.%s [%s] %s -> %s" % (r[0], r[1], r[2], r[3], r[4]))
    L.append("口径说明：\"脏值命中\" = category/tags 里某元素经内置术语表反查后不等于自身，")
    L.append("          即「显示文本被当成规范值存着」。待自决那一桶是**内容差异**（不是译名")
    L.append("          问题），自动合并会丢用户的自定义内容，所以留给人工，不计入必须归 0 那桶。")
    L.append("")
    L.append("── 五、写侧兜底（防新增脏数据，A 部分）──")
    L.append("")
    L.append(".ToolsGCP/desktop/api/maker.py：新增模块级 _term_manager / canonicalize_term /")
    L.append("_canonicalize_pool / canonicalize_lang_list，并在 _merge_i18n 的 category/tags 分支")
    L.append("之后、links 之前对 LANG_LIST_FIELDS 逐个反查兜底。落库三条路径（append_entry /")
    L.append("save_standalone / append_entries）都过 _normalize ⇒ 全覆盖；反查不到原样保留；")
    L.append("只动 category/tags，links 与其它 i18n 字段口径不变；幂等。")
    L.append("验证：probe_task24_canonical.py → %s" % ctx.get("probe", "见探针输出"))
    L.append("审计：audit_task24_dirty.py → %s" % ctx.get("audit", "见审计输出"))
    L.append("")
    L.append("── 六、复核命令 ──")
    L.append("")
    L.append("python \"项目资料-文档与开发测试\\_devtest\\migrate_task24_category_tags.py\"             # dry-run 全表")
    L.append("python \"项目资料-文档与开发测试\\_devtest\\migrate_task24_category_tags.py\" --verify  # 复跑并刷新报告（不写库）")
    L.append("python \"项目资料-文档与开发测试\\_devtest\\probe_task24_canonical.py\"                  # 兜底探针")
    L.append("python \"项目资料-文档与开发测试\\_devtest\\audit_task24_dirty.py\"                    # 脏值/差异/显示层审计")
    L.append("python -m compileall -q \".ToolsGCP\\desktop\" \".ToolsGCP\\modules\"                    # 语法")
    io.open(REPORT, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
    return "\n".join(L)


def applied_table_of(text):
    """从落盘那次存档的规划全文里只取「将自动修正」段，作为报告第一节"""
    lines = text.split("\n")
    try:
        a = next(i for i, l in enumerate(lines) if l.startswith("── 将自动修正"))
    except StopIteration:
        return text
    b = next((i for i, l in enumerate(lines) if l.startswith("── 三池不一致")), len(lines))
    return "\n".join(lines[a:b])


def scan_current(data):
    """当前盘上：残留脏值命中（含待自决条目）+ 形态统计"""
    rescan, shapes = [], {}
    for e in entries(data):
        for f in FIELDS:
            if f in e and isinstance(e[f], (list, dict)):
                key = "dict" if isinstance(e[f], dict) else "list"
                shapes[key] = shapes.get(key, 0) + 1
                rescan += [(e.get("code"), f) + h for h in dirty_in(e[f])]
    return rescan, shapes


def main():
    mode = ("apply" if "--apply" in sys.argv else
            "verify" if "--verify" in sys.argv else "dry")
    raw = io.open(LIB, encoding="utf-8").read()
    data = json.loads(raw)
    before_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    changes, undecided = build(data)
    rescan, shapes = scan_current(data)

    L = ["task-24 迁移规划（%s 模式）：code / 字段 / 语言池 / before→after" % mode,
         "资源库 = %s" % LIB,
         "条目数 = %d，schema = %s，形态统计 = %s"
         % (len(entries(data)), data.get("schema_version"), jdump(shapes)),
         "", "── 将自动修正：%d 处 ──" % len(changes)]
    for ch in changes:
        L.append("")
        L.append("[%s] %s  (%s)" % (ch["kind"], ch["code"] + "." + ch["field"],
                                    ch["detail"] or "反查后三池同值"))
        for lang, items in pools_of(ch["before"]):
            after_pool = (ch["after"] if lang is None else
                          (ch["after"].get(lang) if isinstance(ch["after"], dict) else ch["after"]))
            L.append("    语言池 %-10s before=%s" % (lang or "扁平list", jdump(items)))
            L.append("    %22s after =%s" % ("", jdump(after_pool)))
        L.append("    => 落盘值 %s" % jdump(ch["after"]))
    L.append("")
    L.append("── 三池不一致（待用户自决，不合并内容）：%d 处 ──" % len(undecided))
    for un in undecided:
        L.append("")
        L.append("[%s] %s.%s" % (un["kind"], un["code"], un["field"]))
        L.append("    现值   = %s" % jdump(un["before"]))
        L.append("    原因   = %s" % un["why"])
        if un["suggest"]:
            L.append("    建议   = %s" % jdump(un["suggest"]))
        for lang, items in pools_of(un["before"]):
            hits = [(x, maker.canonicalize_term(x)) for x in items
                    if isinstance(x, str) and maker.canonicalize_term(x) != x]
            if hits:
                L.append("      %s 残留显示文本: %s" % (lang, "; ".join("%s→%s" % h for h in hits)))
    text = "\n".join(L) + "\n"
    io.open(os.path.join(DEV, "_t24_%s.txt" % mode), "w", encoding="utf-8").write(text)
    print(text)

    if mode == "dry":
        print("DRY-RUN only（--apply 落盘 / --verify 复跑并刷新报告）；变更=%d 待自决=%d 残留命中=%d"
              % (len(changes), len(undecided), len(rescan)))
        return 0

    dst = maker.rolling_backup_file()
    if mode == "apply" and changes:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(LIB, dst)
        os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
        # 快照必须是"任务开始前"那一份：复跑无条件覆盖就会把唯一的全量回退点刷成迁移后状态。
        if os.path.exists(SNAPSHOT):
            print("快照已存在，保留不落新 = %s" % SNAPSHOT)
        else:
            shutil.copy2(LIB, SNAPSHOT)
            print("快照新落 = %s" % SNAPSHOT)
        apply_changes(data, changes)
        tmp = LIB + ".task24.tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(dumps(data))                 # 与 maker._write 同格式：缩进 2 + 结尾一个换行
        os.replace(tmp, LIB)
        print("已落盘 %d 处；滚动备份 = %s" % (len(changes), dst))
        hist_new = {"applied_changes": len(changes), "dryrun_table": text, "rolling_backup": dst,
                    "sha_before": before_sha, "applied_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    else:
        print(mode == "apply" and "无待落盘变更（已是幂等状态），不写库不覆盖备份"
              or "--verify：只复跑校验，不写库")
        hist_new = {}

    # ---- 复跑校验（apply / verify 都走这里，只读不写库）----
    data2 = json.load(io.open(LIB, encoding="utf-8"))
    ch2, un2 = build(data2)
    rescan2, shapes2 = scan_current(data2)
    now = io.open(LIB, encoding="utf-8").read()
    byte_identical = (dumps(data2) == now)
    print("幂等复跑：二次变更=%d 二次待自决=%d 残留命中=%d 字节级一致=%s"
          % (len(ch2), len(un2), len(rescan2), byte_identical))
    for c in ch2:
        print("   !! 二次变更 %s.%s %s -> %s"
              % (c["code"], c["field"], jdump(c["before"]), jdump(c["after"])))

    hist_path = os.path.join(DEV, "_t24_apply.json")
    hist = json.loads(io.open(hist_path, encoding="utf-8").read()) if os.path.exists(hist_path) else {}
    if hist_new:
        hist = dict(hist, **hist_new)
        hist["sha_after"] = hashlib.sha256(io.open(LIB, "rb").read()).hexdigest()
    io.open(hist_path, "w", encoding="utf-8").write(json.dumps({
        "mode": mode, "second_pass_changes": len(ch2), "second_pass_undecided": len(un2),
        "residual_hits": len(rescan2), "residual": [list(x) for x in rescan2],
        "shapes": shapes2, "byte_identical": byte_identical, "snapshot": SNAPSHOT,
        "history": hist,
    }, ensure_ascii=False, indent=2))

    ctx = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "n_entries": len(entries(data2)),
           "backup": hist.get("rolling_backup", dst),
           "sha_before": hist.get("sha_before", before_sha),
           "sha_after": hist.get("sha_after", hashlib.sha256(io.open(LIB, "rb").read()).hexdigest()),
           "n_changes": hist.get("applied_changes", len(changes)),
           "applied_table": applied_table_of(hist.get("dryrun_table", text)),
           "ch2": ch2, "un2": un2, "undecided": un2, "rescan": rescan2,
           "byte_identical": byte_identical}
    audit = os.path.join(DEV, "_t24_audit.json")
    if os.path.exists(audit):
        a = json.loads(io.open(audit, encoding="utf-8").read())
        ctx["audit"] = "RESULT: %s（可自动修桶=%d 待自决桶=%d 结构差异=%d 显示层差异=%d）" % (
            a.get("verdict", "?"), a.get("fixable_hits", -1), a.get("held_hits", -1),
            a.get("unexpected_struct", -1), a.get("unexpected_display", -1))
    probe = os.path.join(DEV, "probe_task24_canonical.out.txt")
    if os.path.exists(probe):
        tail = [l for l in io.open(probe, encoding="utf-8").read().split("\n") if l.startswith("RESULT")]
        ctx["probe"] = tail[-1] if tail else "（未见 RESULT 行）"
    write_report(ctx)
    print("报告已写 %s" % REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
