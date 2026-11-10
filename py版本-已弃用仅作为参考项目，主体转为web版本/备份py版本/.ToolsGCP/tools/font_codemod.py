"""把写死字体族的 QFont(...) 换成按当前字体走的 ui_font(...) —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/font_codemod.py          # 只看会改什么（dry-run）
    python .ToolsGCP/tools/font_codemod.py --write  # 真改

⚠️ 只动 Microsoft YaHei / 微软雅黑：Consolas 等宽那类有意写死，不能跟着界面字体走。
"""

import re
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules" / "pymodels"

FONT_FAMILIES = r"(?:Microsoft YaHei|Microsoft YaHei UI|微软雅黑)"
PATTERN = re.compile(
    r"QFont\(\s*[\"']" + FONT_FAMILIES + r"[\"']"
    r"(?:\s*,\s*(\d+))?"
    r"(?:\s*,\s*QFont\.([A-Za-z]+))?"
    r"\s*\)"
)

BOLD_WEIGHTS = {"Bold", "DemiBold", "Black", "ExtraBold"}


def import_line_for(path: Path) -> str:
    rel = path.relative_to(PKG_DIR)
    depth = len(rel.parts) - 1          # 相对 pymodels 的层数
    dots = "." * (depth + 1)
    return f"from {dots}utils.fonts import ui_font"


def convert(text: str):
    changes = []

    def repl(match):
        size = match.group(1)
        weight = match.group(2)
        args = []
        if size:
            args.append(size)
        if weight and weight in BOLD_WEIGHTS:
            args.append("bold=True")
        elif weight and weight not in ("Normal",):
            args.append(f"weight=QFont.{weight}")
        call = f"ui_font({', '.join(args)})"
        changes.append((match.group(0), call))
        return call

    new_text = PATTERN.sub(repl, text)
    return new_text, changes


def main():
    write = "--write" in sys.argv
    total = 0
    files = 0
    for path in sorted(PKG_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if path.name == "fonts.py":
            continue
        original = path.read_text(encoding="utf-8")
        new_text, changes = convert(original)
        if not changes:
            continue
        files += 1
        total += len(changes)
        print(f"\n{path.relative_to(PROJECT_ROOT)}  ({len(changes)})")
        for old, new in changes:
            print(f"    {old}  ->  {new}")
        if write:
            if "ui_font" not in original:
                line = import_line_for(path)
                lines = new_text.splitlines(keepends=True)
                insert_at = 0
                for i, ln in enumerate(lines):
                    if ln.startswith("from ") or ln.startswith("import "):
                        insert_at = i
                        break
                lines.insert(insert_at, line + "\n")
                new_text = "".join(lines)
            path.write_text(new_text, encoding="utf-8")
            print("    [written]")

    print(f"\n{total} 处，{files} 个文件" + ("" if write else "（dry-run，加 --write 才落盘）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
