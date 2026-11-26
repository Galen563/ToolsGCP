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
    io.open(os.path.join(DEV, "_t24_%%s.txt" %% mode), "w", encoding="utf-8").write(text)
    print(text)

    if mode == "dry":
        print("DRY-RUN only（--apply 落盘 / --verify 复跑并刷新报告）；变更=%%d 待自决=%%d 残留命中=%%d"
              %% (len(changes), len(undecided), len(rescan)))
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
        print("已落盘 %%d 处；滚动备份 = %%s" %% (len(changes), dst))
        hist_new = {"applied_changes": len(changes), "dryrun_table": text, "rolling_backup": dst,
                    "sha_before": before_sha, "applied_at": time.strftime("%%Y-%%m-%%d %%H:%%M:%%S")}
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
    print("幂等复跑：二次变更=%%d 二次待自决=%%d 残留命中=%%d 字节级一致=%%s"
          %% (len(ch2), len(un2), len(rescan2), byte_identical))
    for c in ch2:
        print("   !! 二次变更 %%s.%%s %%s -> %%s"
              %% (c["code"], c["field"], jdump(c["before"]), jdump(c["after"])))

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

    ctx = {"generated_at": time.strftime("%%Y-%%m-%%d %%H:%%M:%%S"),
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
        ctx["audit"] = "RESULT: %%s（可自动修桶=%%d 待自决桶=%%d 结构差异=%%d 显示层差异=%%d）" %% (
            a.get("verdict", "?"), a.get("fixable_hits", -1), a.get("held_hits", -1),
            a.get("unexpected_struct", -1), a.get("unexpected_display", -1))
    probe = os.path.join(DEV, "probe_task24_canonical.out.txt")
    if os.path.exists(probe):
        tail = [l for l in io.open(probe, encoding="utf-8").read().split("\n") if l.startswith("RESULT")]
        ctx["probe"] = tail[-1] if tail else "（未见 RESULT 行）"
    write_report(ctx)
    print("报告已写 %%s" %% REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
