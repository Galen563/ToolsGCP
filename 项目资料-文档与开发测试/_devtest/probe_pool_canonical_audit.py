#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_pool_canonical_audit.py · 资源库 category/tags 规范值审计（**只读**，不改任何文件）

为什么常驻这个脚本
    本轮修的那类缺陷（制作器落盘时把「显示文本」当成规范值写进资源库）只在磁盘上
    看得见：前端探针走 mock、后端单测走 normalize，都不覆盖"已经写坏的历史数据"。
    以前每次排查都要临时手写一遍反查脚本，固化成探针之后，任何一次批量改写跑一下
    就能判定有没有新脏值。

口径（与前端 canonicalTerm、后端 task-24 写侧兜底保持一致）
    · 三语译名表 = desktop.api.I18nDomain._read_all_terms()，它的 locale 键是
      **zh_CN / zh_TW / en_US**（不是中文语言名，写成"简体中文"会 KeyError）；
    · 资源条目的语言池键是中文语言名 简体中文 / 繁體中文 / English，两边要映射；
    · 规范值 = 译名表的键（简体中文原文）。池里存的是某一语言的显示文本
      （例：English 池写 "Clipboard"，规范值是「粘贴板」）=> 判脏；
    · 译名表认不出的值 = 用户自定义标签，原样保留，**不算脏**（不许猜、不许丢）；
    · 三池"规范化后仍不同" = 内容本身就不一致，脚本不替你决定，只列进
      「待用户自决」清单（最终汇报里那条清单就来自这里）。

用法
    python -X utf8 项目资料-文档与开发测试/_devtest/probe_pool_canonical_audit.py
    （从任何目录跑都行：脚本自己把 sys.argv[0] 钉回仓库根的 ToolsGCP.pyw，见下面注释）

退出码
    0 = 没有脏值（自定义值除外）；1 = 有脏值待处理；2 = 环境不对（译名表读空）。
    缺语言键 / 空池 / category 与 tags 形状不对称只打印，不影响退出码
    —— 它们不是缺陷，只是数据形态值得知道。
"""
import io
import json
import os
import sys

# Windows 控制台默认 GBK：print 中文或箭头会 UnicodeEncodeError 直接把脚本打断（本轮真实踩过）
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

SCRIPT = os.path.abspath(__file__)
# _devtest -> 项目资料-文档与开发测试 -> 仓库根
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT)))
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]

# ⚠️ 关键坑（本轮踩到、且是静默假绿）：pymodels.constants.SCRIPT_DIR =  dirname(abspath(sys.argv[0]))
#    （constants.py:76-83），CONFIG_DIR/LANGUAGES_DIR 都由它拼出来。探针放在 _devtest 里跑时
#    argv[0] 就是探针自己 ⇒ SCRIPT_DIR 变成 _devtest，LANGUAGES_DIR 指错，
#    _read_common_module 的 os.path.isfile 为假直接返回 {} —— 译名表变空表，
#    审计于是"一个脏值都查不出来"却打印 PASS。所以先把 argv[0] 钉回程序入口再 import。
sys.argv[0] = os.path.join(ROOT, "ToolsGCP.pyw")

from desktop.api import I18nDomain  # noqa: E402

POOLS = ["简体中文", "繁體中文", "English"]
POOL_TO_LOCALE = {"简体中文": "zh_CN", "繁體中文": "zh_TW", "English": "en_US"}
RES_JSON = os.path.join(ROOT, ".ToolsGCP", "ToolsGCP-Resources.json")


def load_terms():
    """_read_all_terms 是实例方法但不碰 self，用 __new__ 绕开需要窗口的构造函数。"""
    return I18nDomain.__new__(I18nDomain)._read_all_terms()


def build_reverse(terms):
    """(locale, 文本) -> 规范中文键。同一个表里既登记"译名->键"也登记"键->键"，
    这样简体池写规范值得到命中（干净），繁/英池写译名也得到命中（判脏）。"""
    rev = {}
    for locale, mapping in terms.items():
        for canonical, display in mapping.items():
            k = str(canonical).strip()
            v = str(display).strip()
            rev[(locale, v)] = k
            rev[(locale, k)] = k
    return rev


def name_of(entry):
    nm = entry.get("name")
    if isinstance(nm, dict):
        nm = nm.get("简体中文") or (list(nm.values())[0] if nm else "")
    return str(nm)


def main():
    terms = load_terms()
    rev = build_reverse(terms)
    with io.open(RES_JSON, encoding="utf-8") as f:
        data = json.load(f)
    items = data["resources"] if isinstance(data, dict) and isinstance(data.get("resources"), list) else data

    dirty, inconsistent, missing_key, empty_pool, shape_diff = [], [], [], [], []

    for e in items:
        code = str(e.get("code") or e.get("id") or "?")
        nm = name_of(e)
        for field in ("category", "tags"):
            v = e.get(field)
            if isinstance(v, dict):
                have = [p for p in POOLS if p in v]
                if len(have) != 3:
                    missing_key.append("%s %s | %s 缺池 %s（只有 %s）" % (
                        code, nm, field, ",".join(p for p in POOLS if p not in v) or "-", ",".join(have) or "-"))
                pools = {}
                for p in have:
                    pools[p] = [str(x).strip() for x in (v[p] or []) if str(x).strip()]
                    if not pools[p]:
                        empty_pool.append("%s %s | %s[%s] 是空池" % (code, nm, field, p))
                for p in have:
                    locale = POOL_TO_LOCALE[p]
                    for x in pools[p]:
                        canon = rev.get((locale, x))
                        if canon is None:
                            continue                      # 自定义值：原样保留，不算脏
                        if canon != x:
                            dirty.append("%s %s | %s[%s]=%s -> 规范值 %s" % (code, nm, field, p, x, canon))
                norm = {p: sorted(rev.get((POOL_TO_LOCALE[p], x), x) for x in pools[p]) for p in pools}
                if len(set(tuple(v2) for v2 in norm.values())) > 1:
                    cur = " / ".join("%s=[%s]" % (p, ", ".join(pools[p])) for p in POOLS if p in pools)
                    aft = " / ".join("%s=[%s]" % (p, ", ".join(norm[p])) for p in POOLS if p in norm)
                    inconsistent.append("%s %s | %s | 现值 %s | 规范后 %s" % (code, nm, field, cur, aft))
            elif isinstance(v, list):
                vals = [str(x).strip() for x in v if str(x).strip()]
                if not vals:
                    empty_pool.append("%s %s | %s 是空 list" % (code, nm, field))
                for x in vals:
                    if x in terms.get("zh_CN", {}):
                        continue                          # 已经是规范中文
                    hit = None
                    for locale in ("zh_CN", "zh_TW", "en_US"):
                        if (locale, x) in rev:
                            hit = rev[(locale, x)]
                            break
                    if hit:
                        dirty.append("%s %s | %s=%s -> 规范值 %s（扁平 list 形态）" % (code, nm, field, x, hit))

        ca, ta = e.get("category"), e.get("tags")
        if ca is not None and ta is not None and isinstance(ca, dict) != isinstance(ta, dict):
            shape_diff.append("%s %s | category=%s / tags=%s" % (code, nm, type(ca).__name__, type(ta).__name__))

    lens = {k: len(v) for k, v in terms.items()}
    print("条目总数 %d ｜ 译名表 %s" % (len(items), " ".join("%s:%d" % (k, v) for k, v in sorted(lens.items()))))
    if not any(lens.values()):
        # 译名表为空时"没有脏值"是假的：反查表根本没法建立，绝不能当成通过
        print("RESULT: ERROR（译名表读空——检查 sys.argv[0] 是否被钉回程序入口、"
              "LANGUAGES_DIR 是否指向 .ToolsGCP/modules/languages）")
        return 2
    print("== 脏值（显示文本被当规范值落盘） %d 处" % len(dirty))
    for x in dirty:
        print("   " + x)
    print("== 三池规范化后仍不一致（要用户自己定） %d 处" % len(inconsistent))
    for x in inconsistent:
        print("   " + x)
    print("== 缺语言池 %d 处" % len(missing_key))
    for x in missing_key:
        print("   " + x)
    print("== 空池 %d 处" % len(empty_pool))
    for x in empty_pool:
        print("   " + x)
    print("== category 与 tags 形状不对称 %d 处（不是缺陷，仅形态）" % len(shape_diff))
    for x in shape_diff:
        print("   " + x)
    print("RESULT: " + ("PASS" if not dirty else "FAIL"))
    return 0 if not dirty else 1


if __name__ == "__main__":
    sys.exit(main())
