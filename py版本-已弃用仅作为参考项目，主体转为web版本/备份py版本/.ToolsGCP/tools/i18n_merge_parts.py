"""把翻译分片合并回 ToolsGCP-Resources.json —— 一次性工具，合并完可以删

用法（项目根目录）：
    python .ToolsGCP/tools/_merge_i18n_parts.py --dry-run
    python .ToolsGCP/tools/_merge_i18n_parts.py

四个文本字段改写成三语言字典；译文不齐就不写盘。
⚠️ category / tags / systems / architectures 不动：规范枚举值，显示时靠译名表翻。
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
LIBRARY = PROJECT_ROOT / ".ToolsGCP" / "ToolsGCP-Resources.json"
PARTS_DIR = TOOLS_DIR / "_i18n"
BACKUP_DIR = PROJECT_ROOT / ".ToolsGCP" / "backups"
FIELDS = ("name", "description", "intro", "supplement")
LANGS = ("简体中文", "繁體中文", "English")


def as_zh(value):
    if isinstance(value, dict):
        return str(value.get("简体中文") or next(
            (v for v in value.values() if str(v or "").strip()), "") or "")
    return str(value or "")


def main(argv):
    dry_run = "--dry-run" in argv

    data = json.loads(LIBRARY.read_text(encoding="utf-8"))
    resources = data.get("resources") or []
    by_id = {str(item.get("id") or ""): item for item in resources}

    # 同一 id 在多个分片里出现时后面的覆盖前面的
    translations = {}
    for path in sorted(PARTS_DIR.glob("out*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("items") or []:
            rid = str(row.get("id") or "")
            if not rid:
                continue
            translations[rid] = row
    print(f"读到 {len(translations)} 条译文（分片 {len(list(PARTS_DIR.glob('out*.json')))} 个）")

    problems = []
    merged = 0
    for rid, item in by_id.items():
        row = translations.get(rid)
        if row is None:
            problems.append(f"{rid}: 没有任何译文")
            continue
        for field in FIELDS:
            zh = as_zh(item.get(field))
            if not zh:
                continue
            entry = row.get(field)
            if not isinstance(entry, dict):
                problems.append(f"{rid}.{field}: 译文缺失（原文 {len(zh)} 字）")
                continue
            tw = str(entry.get("繁體中文") or "").strip()
            en = str(entry.get("English") or "").strip()
            if not tw:
                problems.append(f"{rid}.{field}: 缺繁體中文")
            if not en:
                problems.append(f"{rid}.{field}: 缺 English")
            # ⚠️ name 常是品牌名（三语言本来就一样），只有正文类字段才把"两译都等于原文"当问题
            if field != "name" and tw == zh and en == zh:
                problems.append(f"{rid}.{field}: 两种译文都和原文一模一样（疑似没翻）")
                continue
            value = {"简体中文": zh, "繁體中文": tw, "English": en}
            item[field] = value
            merged += 1

    print(f"合并字段数: {merged}")
    if problems:
        print(f"[!!] {len(problems)} 个问题，**不写盘**：")
        for text in problems[:40]:
            print("   -", text)
        return 1

    if dry_run:
        print("[dry-run] 校验通过，没有写盘")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"ToolsGCP-Resources.backup-{stamp}.json"
    shutil.copyfile(LIBRARY, backup)
    print(f"已备份: {backup.relative_to(PROJECT_ROOT)}")

    data.setdefault("metadata", {})["updated_at"] = \
        datetime.now().astimezone().replace(microsecond=0).isoformat()
    tmp = LIBRARY.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(LIBRARY)
    print(f"已写入: {LIBRARY.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
