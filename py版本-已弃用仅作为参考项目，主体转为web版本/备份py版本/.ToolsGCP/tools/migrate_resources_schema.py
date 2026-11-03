"""资源库 schema 迁移（一次性脚本）

把资源库改成规范形态：category 由逗号字符串变 list，去掉与 category 重复的 tags，
字段顺序按 resource_schema.FIELD_ORDER。先备份再写、幂等、绝不丢字段。

用法：
    python .ToolsGCP/tools/migrate_resources_schema.py            # 正式迁移
    python .ToolsGCP/tools/migrate_resources_schema.py --dry-run  # 只看会改什么
    python .ToolsGCP/tools/migrate_resources_schema.py --file <别的资源库>
"""

import io
import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "modules"))

from pymodels.core import resource_schema as rs        # noqa: E402

DEFAULT_RESOURCE_FILE = ".ToolsGCP/ToolsGCP-Resources.json"
BACKUP_DIR = ".ToolsGCP/backups"

# 允许被迁移改写的字段，其余字段必须原样不变
TRANSFORMED_FIELDS = {
    "category", "tags", "systems", "architectures",
    "name", "description", "intro", "supplement", "variants", "default_variant",
}


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load(path: str) -> dict:
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def dump(path: str, data: dict):
    """原子写：先写 .tmp 再替换"""
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def backup(path: str) -> str:
    folder = os.path.join(project_root(), BACKUP_DIR)
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(folder, f"ToolsGCP-Resources.backup-{stamp}.json")
    n = 2
    while os.path.exists(dest):                      # 同一秒内跑两次也不会互相覆盖
        dest = os.path.join(folder, f"ToolsGCP-Resources.backup-{stamp}-{n}.json")
        n += 1
    shutil.copyfile(path, dest)
    return dest


def lost_fields(raw_items: list, new_items: list) -> list:
    """核对有没有字段被弄丢，返回 [(标识, 字段, 原值), ...]（空表示安全）"""
    lost = []
    for raw, new in zip(raw_items, new_items):
        if not isinstance(raw, dict):
            continue
        if not isinstance(new, dict):
            lost.append((rs.code_of(raw), "<整条>", "条目变成非对象"))
            continue
        raw_cats = set(rs.categories_of(raw))
        for key, value in raw.items():
            if value in ("", [], {}, None):
                continue                          # 空值本来就不落盘，不算丢
            if key == "tags":
                kept = set(rs.tags_of(new))
                for tag in rs.tags_of(raw):
                    if tag not in kept and tag not in raw_cats:
                        lost.append((rs.code_of(raw), "tags", tag))
                continue
            if key == "category":
                if sorted(rs.categories_of(new)) != sorted(raw_cats):
                    lost.append((rs.code_of(raw), "category",
                                 f"{sorted(raw_cats)} -> {sorted(rs.categories_of(new))}"))
                continue
            if key not in new:
                lost.append((rs.code_of(raw), key, value))
            elif key not in TRANSFORMED_FIELDS and new[key] != value:
                lost.append((rs.code_of(raw), key, f"{value!r} -> {new[key]!r}"))
    return lost


def migrate(path: str, dry_run: bool = False) -> int:
    data = load(path)
    raw_items = data.get("resources") or []
    metadata = data.get("metadata")
    metadata = dict(metadata) if isinstance(metadata, dict) else {}

    split_count = 0
    dup_count = 0
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        raw_cat = item.get("category")
        cats = rs.categories_of(item)
        if isinstance(raw_cat, str) and len(cats) > 1:
            split_count += 1
        dup_count += len([t for t in rs.tags_of(item) if t in cats])

    new_items = [rs.normalize(item) if isinstance(item, dict) else item
                 for item in raw_items]

    # 核对不通过就中止（不写盘）
    lost = lost_fields(raw_items, new_items)
    if lost:
        print("❌ 中止：迁移会导致字段丢失，资源库没有被改动")
        for row in lost[:20]:
            print(f"   · {row}")
        return 1

    new_metadata = dict(metadata)
    new_metadata["total_count"] = len(new_items)
    new_data = dict(data)
    new_data["resources"] = new_items
    new_data["metadata"] = new_metadata
    new_data["schema_version"] = rs.SCHEMA_VERSION

    # 幂等：内容一致就什么都不做
    old_schema = str(data.get("schema_version") or "")
    changed = (new_items != raw_items
               or old_schema != rs.SCHEMA_VERSION
               or metadata.get("total_count") != len(new_items))
    if not changed:
        print("✅ 已经是规范形态，无需改动（文件保持字节级不变）")
        print(f"   schema_version : {old_schema}")
        print(f"   资源数         : {len(new_items)}")
        return 0

    if not dry_run:
        new_metadata["updated_at"] = \
            datetime.now().astimezone().replace(microsecond=0).isoformat()

    print(f"资源库      : {path}")
    print(f"schema      : {old_schema} -> {rs.SCHEMA_VERSION}")
    print(f"条目数      : {len(raw_items)}")
    print(f"类别拆多值  : {split_count} 条（\"工具,游戏\" -> [\"工具\", \"游戏\"]）")
    print(f"删除重复标签: {dup_count} 个（标签里与类别重名的值）")
    print(f"标签总数    : {sum(len(rs.tags_of(i)) for i in raw_items if isinstance(i, dict))}"
          f" -> {sum(len(i.get('tags') or []) for i in new_items if isinstance(i, dict))}")

    if dry_run:
        print("\n（--dry-run：没有写盘，也没有备份）")
        return 0

    dest = backup(path)
    print(f"备份        : {dest}")
    dump(path, new_data)
    print("已写回规范形态 ✅")
    return 0


def main(argv: list) -> int:
    path = os.path.join(project_root(), DEFAULT_RESOURCE_FILE)
    dry_run = "--dry-run" in argv
    if "--file" in argv:
        path = argv[argv.index("--file") + 1]
        if not os.path.isabs(path):
            path = os.path.join(project_root(), path)
    if not os.path.exists(path):
        print(f"❌ 找不到资源库: {path}")
        return 1
    return migrate(path, dry_run)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
