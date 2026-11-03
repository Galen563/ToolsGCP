"""资源库三语言自检 —— 不参与程序运行

用法：python .ToolsGCP/tools/check_resources_i18n.py
"""

import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
sys.path.insert(0, str(PROJECT_ROOT / ".ToolsGCP" / "modules"))

PROBLEMS = []
FIELDS = ("name", "description", "intro", "supplement")
LANGS = ("简体中文", "繁體中文", "English")


def check(ok, message):
    print(("[ok] " if ok else "[!!] ") + message)
    if not ok:
        PROBLEMS.append(message)


def main():
    from pymodels.core import resource_schema as rs
    from pymodels.core.resource_loader import ResourceLoader

    path = PROJECT_ROOT / ".ToolsGCP" / "ToolsGCP-Resources.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["resources"]

    check(len(items) == data["metadata"]["total_count"],
          f"条目数与 metadata.total_count 一致（{len(items)}）")
    check(not rs.validate_all(items), "schema 校验零问题")

    bad = []
    for item in items:
        for field in FIELDS:
            value = item.get(field)
            if value is None:
                continue
            if not isinstance(value, dict):
                bad.append(f"{item['id']}.{field} 不是多语言字典")
                continue
            for lang in LANGS:
                if not str(value.get(lang) or "").strip():
                    bad.append(f"{item['id']}.{field} 缺 {lang}")
    check(not bad, f"四个文本字段三语言齐全（问题 {len(bad)} 个）")
    for text in bad[:5]:
        print("   -", text)

    weird = [it["id"] for it in items
             if any(not isinstance(v, str) for v in (it.get("category") or []))
             or any(not isinstance(v, str) for v in (it.get("tags") or []))]
    check(not weird, f"category / tags 仍是字符串列表（异常 {len(weird)} 条）")

    names = {}
    for lang in LANGS:
        loader = ResourceLoader(str(path), lang)
        loader.load_from_local()
        rows = {it["id"]: it for it in loader.get_all()}
        names[lang] = rows
    sample = "localsend"
    desc = {lang: str(names[lang][sample].get("description") or "") for lang in LANGS}
    check(len(set(desc.values())) == 3,
          "同一份资源在三种语言下读出的简介互不相同")
    check(desc["English"].startswith("A cross-platform"),
          f"英文简介取到的是英文（{desc['English'][:40]}…）")

    # 检索词是规范值，不能被翻译破坏
    loader = ResourceLoader(str(path), "English")
    loader.load_from_local()
    hits = loader.search("工具")
    check(len(hits) >= 20, f"英文界面下按规范关键词「工具」仍能搜到（{len(hits)} 条）")

    lang_file = (PROJECT_ROOT / ".ToolsGCP" / "modules" / "languages"
                 / "common_language.json")
    terms = json.loads(lang_file.read_text(encoding="utf-8"))
    missing = set()
    for item in items:
        for value in (rs.keywords_of(item) + rs.systems_of(item)
                      + rs.architectures_of(item)):
            key = f"term_{value}"
            if key not in terms:
                missing.add(value)
    check(not missing, f"译名表覆盖全部术语（缺 {sorted(missing)}）")

    print()
    if PROBLEMS:
        print(f"[!!] {len(PROBLEMS)} 个问题")
        return 1
    print("[OK] 资源库三语言自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
