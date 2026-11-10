#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验「官方」标签在深/浅两套主题下最终生效的背景色/文字色。

为什么要写这个脚本：
    「官方」标签金色在浅色主题下失效，根因是**特异性**而不是加载顺序。
    肉眼看 CSS 容易漏掉后面文件里同名的 .tag 规则，所以这里按 index.html
    里真实的 <link> 顺序收集所有能命中 .tag 的规则，算出 (id, 类, 元素)
    三元组特异性，模拟浏览器"同特异性后写者胜"的判定，再按主题过滤
    （带 :root[data-theme="light"] 的规则只在浅色主题生效），打印最终结论。
    用法：python check_official_tag.py
"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# _devtest → 项目资料-文档与开发测试 → 仓库根，再进 .ToolsGCP/webui
WEBUI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                     ".ToolsGCP", "webui")

# index.html 里 <link rel="stylesheet"> 的真实加载顺序（手工同步，改 HTML 时要同步这里）
LOAD_ORDER = [
    "variables.css", "base.css", "components.css", "layout.css",
    "animations.css", "overlays.css", "fav-fixes.css", "settings-fixes.css",
    "download-fixes.css", "r22-fixes.css", "r24-fixes.css", "download-ui.css",
]

# 我们关心的两条属性：背景色 + 文字色
PROPS = ("background", "color")


def split_compounds(selector):
    """把选择器拆成 compound（compound 之间是后代/子代/兄弟关系）。"""
    return [c for c in re.split(r"\s*[>+~]\s*|\s+", selector.strip()) if c]


def has_class(compound, name):
    """compound 里是否带某个类（`.is-official` 算一个类，`.tag.is-official` 带两个类）。"""
    return bool(re.search(r"\.%s(?![\w-])" % re.escape(name), compound))


def specificity(selector):
    """按 CSS 规范算 (id, 类/属性/伪类, 元素/伪元素) 三元组。"""
    ids = classes = elements = 0
    for comp in split_compounds(selector):
        # 去掉该 compound 里的属性选择器和伪类，剩下的裸名字才是元素选择器
        bare = re.sub(r"\[[^\]]*\]", "", comp)
        bare = re.sub(r":(?!:)[a-zA-Z-]+(\([^)]*\))?", "", bare)
        bare = re.sub(r"::[a-zA-Z-]+", "", bare)
        ids += len(re.findall(r"#[\w-]+", bare))
        classes += len(re.findall(r"\.[\w-]+", bare))
        classes += len(re.findall(r"\[[^\]]+\]", comp))
        classes += len(re.findall(r"(?<!:):(?!:)[a-zA-Z-]+", comp))
        elements += len(re.findall(r"(?<![\w.#-])[a-zA-Z][\w-]*", bare))
    return (ids, classes, elements)


def classify(selector):
    """返回 'official' / 'plain' / None。

    · official —— 会命中带 is-official 的 .tag 元素
    · plain    —— 只命中普通 .tag（不含 is-official / release-badge）
    只看结构，不看属性值；伪类/后代链一律按"能命中"算（保守，宁可多报）。
    """
    comps = split_compounds(selector)
    if not comps:
        return None
    if any("release-badge" in c for c in comps):
        return None
    has_tag = any(has_class(c, "tag") for c in comps)
    if not has_tag:
        return None
    if any(has_class(c, "is-official") for c in comps):
        return "official"
    return "plain"


def light_only(selector):
    """规则是否只在浅色主题生效（选择器里带 [data-theme="light"]）。"""
    return bool(re.search(r'\[data-theme=["\']?light', selector))


def parse_css(text):
    """抽出一级规则（忽略 @media/@supports 内部），返回 (选择器, 声明字典)。"""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        sel_raw, body = m.group(1), m.group(2)
        if sel_raw.strip().startswith("@"):
            continue
        decls = {}
        for d in body.split(";"):
            if ":" not in d:
                continue
            k, v = d.split(":", 1)
            k = k.strip().lower()
            if k in PROPS:
                decls.setdefault(k, v.strip())
        if not decls:
            continue
        for sel in sel_raw.split(","):
            sel = sel.strip()
            if sel:
                out.append((sel, decls))
    return out


def collect():
    """按加载顺序收集所有命中 .tag 的规则。"""
    rules = []
    order = 0
    for file_idx, css in enumerate(LOAD_ORDER):
        path = os.path.join(WEBUI, "css", css)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        for sel, decls in parse_css(text):
            kind = classify(sel)
            if kind is None:
                continue
            order += 1
            rules.append({
                "file": css, "file_idx": file_idx, "order": order,
                "sel": sel, "kind": kind, "decls": decls,
                "spec": specificity(sel), "light_only": light_only(sel),
            })
    return rules


def winner(rules, kind, prop, theme):
    """模拟浏览器：只考虑该主题下生效的规则，特异性高者胜，同特异性后写者胜。"""
    cand = []
    for r in rules:
        if r["kind"] != kind or prop not in r["decls"]:
            continue
        if theme == "dark" and r["light_only"]:
            continue
        cand.append(r)
    if not cand:
        return None
    best = None
    for r in cand:
        if best is None or (r["spec"], r["order"]) >= (best["spec"], best["order"]):
            best = r
    return best


def main():
    rules = collect()
    print("== 按 index.html 真实加载顺序，命中的 .tag 规则 ==")
    for r in rules:
        tag = "官方" if r["kind"] == "official" else "普通"
        light = " [仅浅色]" if r["light_only"] else ""
        print("  %-22s %-45s %s%s"
              % (r["file"], r["sel"], r["spec"], light))

    print()
    ok = True
    for theme in ("dark", "light"):
        print("== %s主题下「官方」标签的最终取值 ==" % ("深色" if theme == "dark" else "浅色"))
        for prop in PROPS:
            w = winner(rules, "official", prop, theme)
            g = winner(rules, "plain", prop, theme)
            if w is None:
                print("  %-10s 无命中规则" % prop)
                ok = False
                continue
            print("  %-10s = %-34s  来自 %s"
                  % (prop, w["decls"][prop], w["sel"]))
            if g is not None and w["spec"][:2] <= g["spec"][:2] and w["order"] < g["order"]:
                print("     ❌ 没有压过普通 .tag 规则：%s %s" % (g["sel"], g["spec"]))
                ok = False
        print()

    # 硬断言：浅色下必须是深金，深色下必须还是原来的 #d4af37
    light_color = winner(rules, "official", "color", "light")["decls"]["color"]
    dark_color = winner(rules, "official", "color", "dark")["decls"]["color"]
    checks = [
        ("浅色主题用深金（不是 #d4af37）", light_color != "#d4af37"),
        ("深色主题仍是 #d4af37", dark_color == "#d4af37"),
        ("浅色主题仍是金色系", re.search(r"#(8a6100|a87900|b8860b|9a6f00)", light_color) is not None),
    ]
    for desc, passed in checks:
        print(("✅ " if passed else "❌ ") + desc)
        ok = ok and passed
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
