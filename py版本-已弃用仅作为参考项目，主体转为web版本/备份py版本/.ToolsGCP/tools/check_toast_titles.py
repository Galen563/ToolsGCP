"""提示条标题三语言自检 —— 不参与程序运行

用法：python .ToolsGCP/tools/check_toast_titles.py

逐条验每种语言下的四个标题，以及页面 show_message 是否真的用上了它。
"""

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
# ⚠️⚠️ argv[0] 必须指到 ToolsGCP.pyw：constants.py 按它算 CONFIG_DIR，
#    否则语言文件找不到，LanguageManager 全表落空、每种语言都误报英文。
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / ".ToolsGCP" / "modules"))

PROBLEMS = []
EXPECTED = {
    "简体中文": {"success": "成功", "error": "错误",
                 "warning": "提示", "info": "信息"},
    "繁體中文": {"success": "成功", "error": "錯誤",
                 "warning": "提示", "info": "資訊"},
    "English": {"success": "Success", "error": "Error",
                "warning": "Notice", "info": "Info"},
}


def check(ok, message):
    print(("[ok] " if ok else "[!!] ") + message)
    if not ok:
        PROBLEMS.append(message)


def main():
    from pymodels.core.language_manager import LanguageManager, get_toast_title

    lang = LanguageManager()
    for language, expected in EXPECTED.items():
        lang.set_language(language)
        got = {kind: get_toast_title(kind, lang) for kind in expected}
        check(got == expected,
              f"{language}: 四个标题 = {got}")

    check(get_toast_title("success", None) == "Success"
          and get_toast_title("info", None) == "Info",
          "没有语言管理器时退回英文（不是键名、也不是中文）")

    # 源码级检查：确保 show_message 真接上了
    import inspect
    from pymodels.interfaces import (plugin_interface, search_interface,
                                     tools_gcp_interface)
    for module in (plugin_interface, search_interface, tools_gcp_interface):
        source = inspect.getsource(module)
        check("get_toast_title" in source,
              f"{module.__name__.split('.')[-1]} 的 show_message 用了 get_toast_title")
        check('title="成功"' not in source and 'title="信息"' not in source,
              f"{module.__name__.split('.')[-1]} 里没有写死的中文标题")

    # ⚠️ 只有 common 段会被 get_toast_title 读（全程序一个口径）
    import json
    path = (PROJECT_ROOT / ".ToolsGCP" / "modules" / "languages"
            / "common_language.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in ("tip_success", "tip_error", "tip_warning", "tip_info")
               if k not in data]
    check(not missing, "common_language.json 里有四个提示条标题键")

    print()
    if PROBLEMS:
        print(f"[!!] {len(PROBLEMS)} 个问题")
        return 1
    print("[OK] 提示条标题三语言自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
