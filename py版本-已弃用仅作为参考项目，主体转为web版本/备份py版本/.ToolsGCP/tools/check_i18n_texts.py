"""界面文案国际化体检 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_i18n_texts.py

找出直接写死传给界面控件的中文（切了语言不会变）。
判定：控件文本参数是中文字面量而非 get_text/_t/变量；通过标准 0 处。
"""

import ast
import re
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG = PROJECT_ROOT / ".ToolsGCP" / "modules" / "pymodels"

# 字符串参数即界面文案的方法/构造函数
UI_METHODS = {
    "setText", "setToolTip", "setPlaceholderText", "setWindowTitle",
    "setTitle", "addItem", "addItems", "setMessage",
}
UI_CLASSES = {
    "BodyLabel", "CaptionLabel", "SubtitleLabel", "StrongBodyLabel", "TitleLabel",
    "PushButton", "PrimaryPushButton", "TransparentToolButton", "ToolButton",
    "QLabel", "CheckBox", "SwitchButton", "LineEdit", "SearchLineEdit",
    "PlainTextEdit", "MessageBox", "InfoBar", "ToolTipFilter",
}
CJK = re.compile(r"[\u4e00-\u9fff]")
MAX_LEN = 200


def scan(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None)
        if name not in UI_METHODS and name not in UI_CLASSES:
            continue
        for arg in list(node.args) + [k.value for k in node.keywords]:
            if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                continue
            text = arg.value
            if not CJK.search(text) or len(text) > MAX_LEN:
                continue
            hits.append((node.lineno, name, text.replace("\n", "\\n")[:70]))
    return hits


def main():
    total = 0
    for path in sorted(PKG.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        hits = scan(path)
        if not hits:
            continue
        total += len(hits)
        print(f"\n=== {path.relative_to(PROJECT_ROOT)} ({len(hits)}) ===")
        for lineno, name, text in hits:
            print(f"  {lineno:5d} {name:20s} {text}")
    print()
    if total:
        print(f"[!!] 还有 {total} 处写死的界面文案 —— 请改走语言文件"
              f"（get_text / _t / translate_term）")
        return 1
    print("[OK] 没有写死的界面文案")
    return 0


if __name__ == "__main__":
    sys.exit(main())
