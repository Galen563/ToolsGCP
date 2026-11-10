"""JSON 小工具：按项目既有风格读写语言 / 资源文件

用法（项目根目录）：
    python .ToolsGCP/tools/json_edit.py normalize <file>...
    python .ToolsGCP/tools/json_edit.py set <file> <key> <zh_CN> <zh_TW> <en>
    python .ToolsGCP/tools/json_edit.py get <file> <key>

⚠️ 不要用 PowerShell ConvertTo-Json 来回读写这些文件：缩进会变成 4 空格、键序会被重排。
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump(path: Path, data: dict):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def dump_i18n(path: Path, data: dict):
    """语言文件：每个 key 是 {简体中文, 繁體中文, English} 三行，紧凑一点更好看"""
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


def resolve(name: str) -> Path:
    path = Path(name)
    if not path.is_absolute():
        path = PROJECT_ROOT / name
    if not path.exists():
        raise SystemExit(f"文件不存在: {path}")
    return path


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    command = argv[0]
    if command == "normalize":
        for name in argv[1:]:
            path = resolve(name)
            dump_i18n(path, load(path))
            print(f"已规范化: {path}")
        return 0
    if command == "set":
        name, key, zh_cn, zh_tw, en = argv[1], argv[2], argv[3], argv[4], argv[5]
        path = resolve(name)
        data = load(path)
        data[key] = {"简体中文": zh_cn, "繁體中文": zh_tw, "English": en}
        dump_i18n(path, data)
        print(f"已写入 {key}: {path}")
        return 0
    if command == "get":
        path = resolve(argv[1])
        data = load(path)
        print(json.dumps(data.get(argv[2]), ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
