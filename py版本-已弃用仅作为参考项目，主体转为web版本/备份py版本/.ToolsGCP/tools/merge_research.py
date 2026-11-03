"""把 4 组调研结果并回资源库 —— 一次性合并脚本

用法（项目根目录，先干跑看 diff 再落盘）：
    python .ToolsGCP/tools/merge_research.py            # 只打印 diff，不写盘
    python .ToolsGCP/tools/merge_research.py --apply    # 备份 + 原子写盘

字段顺序照 resource_maker_core.FIELD_ORDER，写盘前备份 + 临时文件替换（幂等）。
"""

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
RESEARCH_DIR = PROJECT_ROOT / ".ToolsGCP" / "research"
LIBRARY = PROJECT_ROOT / ".ToolsGCP" / "ToolsGCP-Resources.json"
BACKUP_DIR = PROJECT_ROOT / ".ToolsGCP" / "backups"
BACKUP_KEEP = 20

FIELD_ORDER = [
    "id", "code", "name", "category", "tags", "icon", "url", "github",
    "download_url", "chat_url", "author_url", "description",
    "supplement", "listed_at", "systems", "architectures",
]

# 复核确认"条目本身写错了"的修正，证据见 verify-tiez.md / group-*.json
OVERRIDES = {
    # TieZ 官网无"在线工具集合"栏目，原描述与事实不符
    "tiez": {
        "name": "TieZ",
        "description": "跨平台剪贴板管理工具，支持历史记录、搜索标签、局域网传输与 WebDAV 云同步。",
        "systems": ["Windows", "macOS", "Android"],
        "architectures": ["x64", "x86", "Apple Silicon"],
        "github": "https://github.com/jimuzhe/tiez-clipboard",
    },
    # memreduct.org 是粉丝站不是官网，换成官方仓库
    "memreduct": {
        "url": None,                      # None = 删掉这个字段
        "github": "https://github.com/henrypp/memreduct",
    },
    # mctier 官网自述是通用组网工具，明确否认是 Minecraft 专用工具
    "mctier": {
        "description": "虚拟局域网通用组网工具，把电脑和手机连进同一个大厅，支持语音、文件与屏幕共享。",
    },
    # pyisland 官网自述是 Windows 桌面灵动岛，不是 Python 学习平台
    "pyisland": {
        "description": "Windows 桌面灵动岛，显示系统状态并提供快捷操作、内置 AI 助手。",
    },
    # class-widgets-2 原简介只有「课程表」三个字，按官方自述补全
    "class-widgets-2": {
        "description": "把课表做成桌面小组件，支持多周课表切换与考试倒计时。",
    },
}


def load_groups():
    merged = {}
    for key in "abcd":
        path = RESEARCH_DIR / f"group-{key}.json"
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data["items"]:
            rid = item["id"]
            assert rid not in merged, f"id 重复: {rid}"
            merged[rid] = item
    return merged


def ordered(item: dict) -> dict:
    """按 FIELD_ORDER 重排字段；顺序之外的键原样接在后面"""
    out = {}
    for field in FIELD_ORDER:
        if field in item:
            out[field] = item[field]
    for field, value in item.items():
        if field not in out:
            out[field] = value
    return out


def main():
    apply = "--apply" in sys.argv

    with open(LIBRARY, "r", encoding="utf-8") as f:
        library = json.load(f)
    resources = library["resources"]
    by_id = {item["id"]: item for item in resources}

    research = load_groups()
    print(f"资源库 {len(resources)} 条 / 调研 {len(research)} 条")

    missing = [rid for rid in by_id if rid not in research]
    extra = [rid for rid in research if rid not in by_id]
    if missing:
        print(f"[!] 调研里缺少这些 id（保持原样）: {missing}")
    if extra:
        print(f"[!] 调研里有资源库没有的 id: {extra}")

    changed = []
    for rid, item in by_id.items():
        info = research.get(rid)
        if info is None:
            continue
        before = dict(item)

        for field in ("systems", "architectures", "supplement", "intro"):
            value = info.get(field)
            if value in (None, "", []):
                # 空值不写进 JSON（和制作器约定一致）
                item.pop(field, None)
            else:
                item[field] = value

        for field, value in OVERRIDES.get(rid, {}).items():
            if value is None:
                item.pop(field, None)
            else:
                item[field] = value

        diff = {k: (before.get(k), item.get(k))
                for k in set(before) | set(item) if before.get(k) != item.get(k)}
        if diff:
            # 记下改前的字段名集合，打印时用来区分"新增"和"被删"
            changed.append((rid, diff, set(before)))

    print(f"\n=== 变更 {len(changed)} 条 ===")
    for rid, diff, before_keys in changed:
        print(f"\n* {rid}")
        for field, (old_value, new_value) in sorted(diff.items()):
            if field not in before_keys:
                print(f"    {field}: (新增) -> {new_value!r}")
            elif new_value is None:
                print(f"    {field}: {old_value!r} -> (删除该字段)")
            else:
                print(f"    {field}: {old_value!r} -> {new_value!r}")

    if not apply:
        print("\n（干跑结束；加 --apply 才写盘）")
        return 0

    # 备份 + 原子写
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"ToolsGCP-Resources.backup-{stamp}.json"
    shutil.copy2(LIBRARY, backup)
    print(f"\n已备份: {backup.name}")

    library["resources"] = [ordered(item) for item in resources]
    library.setdefault("metadata", {})["total_count"] = len(resources)
    library["metadata"]["updated_at"] = datetime.now().astimezone().replace(
        microsecond=0).isoformat()

    tmp = LIBRARY.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(library, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, LIBRARY)
    print(f"已写盘: {LIBRARY}")

    backups = sorted(BACKUP_DIR.glob("ToolsGCP-Resources.backup-*.json"))
    for old in backups[:-BACKUP_KEEP]:
        old.unlink()
    print(f"备份保留 {min(len(backups), BACKUP_KEEP)} 份")
    return 0


if __name__ == "__main__":
    sys.exit(main())
