"""把一批 i18n 文案批量写进语言文件

用法：python add_i18n_keys.py <language.json> <keys.json>
已存在的 key 默认**不覆盖**，除非带 --force。
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def dump_i18n(path: Path, data: dict):
    lines = ["{\n"]
    keys = list(data.keys())
    for index, key in enumerate(keys):
        value = data[key]
        lines.append(f"  {json.dumps(key, ensure_ascii=False)}: {{\n")
        inner = list(value.items())
        for j, (lang, text) in enumerate(inner):
            comma = "," if j < len(inner) - 1 else ""
            lines.append(f"    {json.dumps(lang, ensure_ascii=False)}: "
                         f"{json.dumps(text, ensure_ascii=False)}{comma}\n")
        comma = "," if index < len(keys) - 1 else ""
        lines.append(f"  }}{comma}\n")
    lines.append("}\n")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("".join(lines))


def main(argv):
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    target = Path(argv[0])
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    source = Path(argv[1])
    if not source.is_absolute():
        source = PROJECT_ROOT / source

    with open(target, encoding="utf-8") as handle:
        data = json.load(handle)
    with open(source, encoding="utf-8") as handle:
        new = json.load(handle)

    added, skipped = [], []
    for key, value in new.items():
        if key in data and not force:
            skipped.append(key)
            continue
        data[key] = value
        added.append(key)
    dump_i18n(target, data)
    print(f"{target.name}: 新增 {len(added)} 条, 跳过 {len(skipped)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
