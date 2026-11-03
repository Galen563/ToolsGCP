"""把资源库切成若干"待翻译"分片 —— 一次性工具，翻译完就可以删

用法（项目根目录）：
    python .ToolsGCP/tools/_split_i18n_parts.py [每个分片几条，默认 5]

产出 .ToolsGCP/tools/_i18n/partNN.json，每片只放要翻的原文。
⚠️ 只搬 name / description / intro / supplement：category / tags / systems /
   architectures 是规范枚举值，存盘不变，显示时由译名表翻。
"""

import json
import shutil
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
LIBRARY = PROJECT_ROOT / ".ToolsGCP" / "ToolsGCP-Resources.json"
OUT_DIR = TOOLS_DIR / "_i18n"
FIELDS = ("name", "description", "intro", "supplement")


def as_zh(value):
    if isinstance(value, dict):
        return str(value.get("简体中文") or next(
            (v for v in value.values() if str(v or "").strip()), "") or "")
    return str(value or "")


def main(argv):
    size = int(argv[0]) if argv else 5
    data = json.loads(LIBRARY.read_text(encoding="utf-8"))
    resources = data.get("resources") or []

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    parts = []
    for start in range(0, len(resources), size):
        chunk = resources[start:start + size]
        items = []
        for item in chunk:
            row = {"id": str(item.get("id") or item.get("code") or "")}
            for field in FIELDS:
                text = as_zh(item.get(field))
                if text:
                    row[field] = text
            items.append(row)
        parts.append({"part": len(parts) + 1, "items": items})

    for part in parts:
        path = OUT_DIR / f"part{part['part']:02d}.json"
        path.write_text(json.dumps(part, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    total_chars = sum(len(v) for p in parts for it in p["items"]
                      for k, v in it.items() if k != "id")
    print(f"共 {len(resources)} 条资源，切成 {len(parts)} 个分片"
          f"（每片 {size} 条），待翻原文 {total_chars} 字")
    print(f"输出目录: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
