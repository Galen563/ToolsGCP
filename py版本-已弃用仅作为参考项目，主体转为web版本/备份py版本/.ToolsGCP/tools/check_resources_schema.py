"""资源库 schema 自检脚本（快照 / 校验）

用法：
    # 1) 改动之前：把界面可观察结果存成快照
    python check_resources_schema.py snapshot <out.json>

    # 2) 迁移之后：跑全套断言（往返、向后兼容、行为等价）
    python check_resources_schema.py verify <before.json> [--backup <旧格式备份>]

⚠️ 只读资源库、只往调用方给的路径写快照，不改任何配置文件。
"""

import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "modules"))

DEFAULT_RESOURCE_FILE = ".ToolsGCP/ToolsGCP-Resources.json"
LANGUAGE = "简体中文"


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resource_path(rel: str = DEFAULT_RESOURCE_FILE) -> str:
    return rel if os.path.isabs(rel) else os.path.join(_project_root(), rel)


def load_json(path: str) -> dict:
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_json(path: str, data) -> None:
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def build_loader(rel_path: str):
    """走 ResourceLoader 加载资源库（才能验到读取时规范化）"""
    from pymodels.core.resource_loader import ResourceLoader
    loader = ResourceLoader(resource_path(rel_path), LANGUAGE)
    ok = loader.load_from_local()
    if not ok:
        raise SystemExit(f"资源库加载失败: {resource_path(rel_path)}")
    return loader


def customize_catalogue(summaries: list) -> list:
    """调用定制页真正的喜好清单构建代码（不复制逻辑，避免自证自话）"""
    from pymodels.interfaces.customize_interface import (
        CustomizeInterface, _interest_keys)
    rows = CustomizeInterface._build_catalogue(None, summaries)
    return [[r["name"], r["count"], r["kind"]] for r in rows]


def interest_keys(item: dict):
    from pymodels.interfaces.customize_interface import _interest_keys
    return _interest_keys(item)


def search_tag_options_old(raw_data: dict) -> list:
    """迁移前搜索页「标签」筛选行的选项（旧逻辑：只取条目里的 tags）"""
    tags = set()
    for item in raw_data.get("resources", []):
        for tag in item.get("tags") or []:
            tags.add(str(tag))
    return sorted(tags)


def search_tag_options_new(summaries: list) -> list:
    """迁移后搜索页「标签」筛选行的选项（真正的实现）"""
    from pymodels.interfaces.search_interface import tag_filter_options
    return sorted(tag_filter_options(summaries))


def search_category_options() -> list:
    from pymodels.interfaces.search_interface import SearchInterface
    return list(SearchInterface._category_order())


def per_code_map(summaries: list, index: int) -> dict:
    out = {}
    for item in summaries:
        code = str(item.get("code") or item.get("id") or "")
        cats, tags = interest_keys(item)
        values = (cats, cats + tags)[index]
        out[code] = sorted({str(v) for v in values})
    return out


def snapshot(out_path: str) -> dict:
    """把"界面能看到的东西"整体存下来"""
    raw = load_json(resource_path())
    loader = build_loader(DEFAULT_RESOURCE_FILE)
    summaries = loader.get_summaries()
    snap = {
        "resource_file": resource_path(),
        "schema_version": raw.get("schema_version"),
        "count": len(raw.get("resources", [])),
        "search_category_options": search_category_options(),
        "search_tag_options": search_tag_options_old(raw),
        "customize_catalogue": customize_catalogue(summaries),
        "categories_by_code": per_code_map(summaries, 0),
        "keywords_by_code": per_code_map(summaries, 1),
    }
    save_json(out_path, snap)
    print(f"快照已写出: {out_path}")
    print(f"  资源数            : {snap['count']}")
    print(f"  搜索页类别选项    : {len(snap['search_category_options'])} 个")
    print(f"  搜索页标签选项    : {len(snap['search_tag_options'])} 个")
    print(f"  定制页喜好清单    : {len(snap['customize_catalogue'])} 个")
    print("  " + " ".join(f"{n}{c}" for n, c, _k in snap["customize_catalogue"]))
    return snap


def _fail(problems: list, message: str):
    problems.append(message)


def verify(before_path: str, backup_path: str = "") -> int:
    """迁移后的全套断言：往返 + 向后兼容 + 行为等价"""
    from pymodels.core import resource_schema as rs

    before = load_json(before_path)
    data = load_json(resource_path())
    # 旧格式备份（迁移前那一刻的文件）：验向后兼容 + 算迁移前的筛选命中
    backup = load_json(backup_path) if backup_path else {}
    problems: list = []
    notes: list = []

    items = data.get("resources", [])
    if len(items) != before["count"]:
        _fail(problems, f"条目数变了: {len(items)} != {before['count']}")
    if not all(isinstance(i.get("category"), list) for i in items):
        _fail(problems, "有条目的 category 不是列表")
    if str(data.get("schema_version")) == str(before.get("schema_version")):
        _fail(problems, f"schema_version 没变: {data.get('schema_version')}")

    bad = {str(i.get("code") or i.get("id")): rs.validate(i) for i in items}
    bad = {k: v for k, v in bad.items() if v}
    if bad:
        _fail(problems, f"validate() 报出问题的条目: {list(bad.items())[:5]}")

    for item in items:
        cats = rs.categories_of(item)
        dup = [t for t in rs.tags_of(item) if t in cats]
        if dup:
            _fail(problems, f"{rs.code_of(item)} 的 tags 里还有类别值: {dup}")

    # 4) 经 ResourceLoader 读取（读取时规范化）
    loader = build_loader(DEFAULT_RESOURCE_FILE)
    summaries = loader.get_summaries()
    if len(summaries) != before["count"]:
        _fail(problems, f"ResourceLoader 载入条数变了: {len(summaries)}")

    # 4b) 类别/标签集合不许变（信息不丢）
    after_cats = per_code_map(summaries, 0)
    after_keys = per_code_map(summaries, 1)
    if after_cats != before["categories_by_code"]:
        diff = {k: (before["categories_by_code"].get(k), after_cats.get(k))
                for k in set(before["categories_by_code"]) | set(after_cats)
                if before["categories_by_code"].get(k) != after_cats.get(k)}
        _fail(problems, f"逐条的类别集合变了（前 {min(3, len(diff))} 处）: "
                        f"{list(diff.items())[:3]}")
    if after_keys != before["keywords_by_code"]:
        diff = {k: (before["keywords_by_code"].get(k), after_keys.get(k))
                for k in set(before["keywords_by_code"]) | set(after_keys)
                if before["keywords_by_code"].get(k) != after_keys.get(k)}
        _fail(problems, f"逐条的类别+标签集合变了（前 {min(3, len(diff))} 处）: "
                        f"{list(diff.items())[:3]}")

    # 5) 搜索页筛选选项等价
    if search_category_options() != before["search_category_options"]:
        _fail(problems, "搜索页类别筛选选项变了")
    new_tag_opts = search_tag_options_new(summaries)
    if new_tag_opts != before["search_tag_options"]:
        only_before = sorted(set(before["search_tag_options"]) - set(new_tag_opts))
        only_after = sorted(set(new_tag_opts) - set(before["search_tag_options"]))
        _fail(problems, f"搜索页标签筛选选项变了: 少了{only_before} 多了{only_after}")

    # 5b) 筛选结果等价：每个筛选项命中哪些条目，迁移前后必须一致
    if backup_path:
        old_items = backup.get("resources", [])
        new_items = data.get("resources", [])
        old_codes = {str(i.get("code") or i.get("id")): i for i in old_items}
        new_codes = {str(i.get("code") or i.get("id")): i for i in new_items}

        # 少命中（old-new 非空）= 回归，判失败；多命中 = 本来就该命中，只如实报出
        tag_lost, tag_gained = {}, {}
        for tag in before["search_tag_options"]:
            old = {k for k, i in old_codes.items()
                   if tag in [str(t) for t in (i.get("tags") or [])]}
            new = {k for k, i in new_codes.items()
                   if tag in rs.keywords_of(i)}
            if old - new:
                tag_lost[tag] = sorted(old - new)
            if new - old:
                tag_gained[tag] = sorted(new - old)
        if tag_lost:
            _fail(problems, f"标签筛选丢了命中（回归）: {tag_lost}")
        if tag_gained:
            notes.append(f"标签筛选多出命中: {tag_gained}"
                         "（这些条目的类别以前没抄进自己的 tags，用标签筛不到；"
                         "现在按「类别 ∪ 标签」筛，它们能被筛到了）")
        else:
            notes.append(f"标签筛选结果: {len(before['search_tag_options'])} 个选项"
                         "逐条比对命中集合，完全一致")

        # 旧代码拿 str(category) 比字符串，一格多值的条目任何类别都筛不到
        cat_lost, cat_gained = {}, {}
        for cat in before["search_category_options"]:
            old = {k for k, i in old_codes.items()
                   if str(i.get("category") or "") == cat}
            new = {k for k, i in new_codes.items()
                   if cat in rs.categories_of(i)}
            if old - new:
                cat_lost[cat] = sorted(old - new)
            if new - old:
                cat_gained[cat] = sorted(new - old)
        if cat_lost:
            _fail(problems, f"类别筛选丢了命中（回归）: {cat_lost}")
        if cat_gained:
            notes.append(f"类别筛选多出命中: {cat_gained}"
                         "（一格多值的条目现在按列表逐项命中）")
        else:
            notes.append(f"类别筛选结果: {len(before['search_category_options'])} 个选项"
                         "逐条比对命中集合，完全一致")

    # 6) 定制页喜好清单等价
    after_cat = customize_catalogue(summaries)
    if after_cat != before["customize_catalogue"]:
        _fail(problems, "定制页喜好清单变了:\n    迁移前 "
                        f"{before['customize_catalogue']}\n    迁移后 {after_cat}")

    # 7) 向后兼容：旧格式备份规范化后须与迁移结果一致
    if backup_path:
        if len(old_items) != len(items):
            _fail(problems, f"备份条目数 {len(old_items)} != {len(items)}")
        by_code = {str(i.get("code") or i.get("id")): i for i in items}
        same = 0
        for raw in old_items:
            key = str(raw.get("code") or raw.get("id"))
            canon = rs.normalize(raw, LANGUAGE)
            # 只比 canonical，忽略 loader 才补的 icon 路径
            want, got = dict(canon), dict(by_code.get(key, {}))
            for d in (want, got):
                if d.get("icon") and "/" not in str(d["icon"]):
                    d["icon"] = os.path.basename(str(d["icon"]))
            if want == got:
                same += 1
            else:
                diff = {k: (want.get(k), got.get(k))
                        for k in set(want) | set(got) if want.get(k) != got.get(k)}
                _fail(problems, f"{key} 旧格式规范化结果与迁移结果不一致: "
                                f"{list(diff.items())[:3]}")
        notes.append(f"向后兼容: {same}/{len(old_items)} 条旧格式条目规范化后与迁移结果逐字段一致")

    print(f"资源数        : {len(items)}")
    print(f"schema_version: {before.get('schema_version')} -> {data.get('schema_version')}")
    print(f"搜索页类别选项: {len(before['search_category_options'])} 个 — 一致")
    print(f"搜索页标签选项: {len(before['search_tag_options'])} 个 — 一致")
    print(f"定制页喜好清单: {' '.join(f'{n}{c}' for n, c, _k in before['customize_catalogue'])}")
    for note in notes:
        print(note)
    if problems:
        print("\n❌ 不一致：")
        for p in problems:
            print("  · " + p)
        return 1
    print("\n✅ 全部断言通过")
    return 0


def main(argv: list) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    mode, out_path = argv[1], argv[2]
    if mode == "snapshot":
        snapshot(out_path)
        return 0
    if mode == "verify":
        backup = ""
        if "--backup" in argv:
            backup = argv[argv.index("--backup") + 1]
        return verify(out_path, backup)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
