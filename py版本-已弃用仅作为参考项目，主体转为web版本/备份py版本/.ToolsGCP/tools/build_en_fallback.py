"""重新生成「内嵌英文兜底表」—— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/build_en_fallback.py

什么时候要跑：
    往 `.ToolsGCP/modules/languages/*.json` 里**新增或修改**了 key 的
    "English" 值时，跑一次这个脚本，把改动同步进
    `.ToolsGCP/modules/pymodels/core/en_fallback.py`。

为什么需要这张表：
    语言文件夹是可以被移走 / 缺失 / 损坏的。没有这张表的话，界面会中英混杂：
    有的组件在 .py 里内嵌了中文兜底、有的直接把 `ui_font` 这种 key 名显示出来。
    有了它，`LanguageManager.get_text()` 查不到时统一返回英文（详见该模块注释）。

⚠️ 表必须**按模块分层**（EN_FALLBACK[module][key]），不能拍平成一张大表：
   不同模块会复用同名 key 但占位符不同。实测撞过：
       tools_gcp 的 "count" = "共 {n} 项"
       plugin   的 "count" = "共 {total} 个，已启用 {enabled} 个"
   拍平之后插件页会拿到 `{n}` 去 `.format(total=...)` → KeyError: 'n'。
"""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LANGUAGES_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules" / "languages"
OUTPUT = (PROJECT_ROOT / ".ToolsGCP" / "modules" / "pymodels" / "core"
          / "en_fallback.py")

# 模块名 -> 语言文件（必须和 core/language_manager.py 的 load_all_languages 一致）
MODULE_FILES = {
    "search": "search_language.json",
    "home": "home_language.json",
    "notice": "notice_language.json",
    "tools_gcp": "ToolsGCPcenter_language.json",
    "deploy": "deploy_language.json",
    "github": "github_language.json",
    "settings": "set_language.json",
    "log": "log_language.json",
    "feedback": "feedback_language.json",
    "nav": "nav_language.json",
    "privacy": "privacy_language.json",
    "plugin": "plugin_language.json",
    "maker": "maker_language.json",
    "customize": "customize_language.json",
    "common": "common_language.json",
}

HEADER = '''"""
内嵌英文兜底表（**自动生成，不要手改**）
========================================

生成命令（项目根目录）：
    python .ToolsGCP/tools/build_en_fallback.py

语言文件（.ToolsGCP/modules/languages/*.json）可以被移走 / 缺失 / 损坏。没有这张表
的话，界面会中英混杂：有的组件在 .py 里内嵌了中文兜底、有的直接把 key 名显示出来。
LanguageManager.get_text() 查不到时先来这张表捞英文。

查找优先级：语言文件 → 本表 → 返回 key 本身（方便排查）。

⚠️ 表必须**按模块分层**（EN_FALLBACK[module][key]），不能拍平成一张大表：
   不同模块会复用同名 key 但占位符不同。实测撞过：
       tools_gcp 的 "count" = "共 {n} 项"
       plugin   的 "count" = "共 {total} 个，已启用 {enabled} 个"
   拍平之后插件页会拿到 `{n}` 去 `.format(total=...)` → KeyError: 'n'。

数据来源：各语言 JSON 里每条 key 的 "English" 值，按模块归位。
"""

# module -> {key: 英文}
EN_FALLBACK = {
'''


def main():
    by_module = {}
    missing = []
    for module, filename in MODULE_FILES.items():
        path = LANGUAGES_DIR / filename
        if not path.exists():
            missing.append(filename)
            continue
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        table = {}
        for key, value in data.items():
            if isinstance(value, dict) and value.get("English"):
                table[key] = value["English"]
        by_module[module] = table

    for module, filename in MODULE_FILES.items():
        if module not in by_module:
            print(f"[警告] 语言文件不存在，该模块跳过: {filename}")

    lines = [HEADER]
    for module in sorted(by_module):
        lines.append(f"    # ---------- {module} ----------\n")
        lines.append(f"    {json.dumps(module, ensure_ascii=False)}: {{\n")
        for key in sorted(by_module[module]):
            lines.append(f"        {json.dumps(key, ensure_ascii=False)}: "
                         f"{json.dumps(by_module[module][key], ensure_ascii=False)},\n")
        lines.append("    },\n")
    lines.append("}\n")

    content = "".join(lines)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as handle:
        handle.write(content)

    total = sum(len(table) for table in by_module.values())
    print(f"已写入 {OUTPUT.relative_to(PROJECT_ROOT)}")
    print(f"  模块数:   {len(by_module)}")
    print(f"  条目总数: {total}")
    print(f"  体积:     {len(content.encode('utf-8')) / 1024:.0f} KB")
    if missing:
        print(f"  跳过的文件: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
