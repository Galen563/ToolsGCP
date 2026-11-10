"""「提交软件」三语言提交自检 —— 不参与程序运行

用法：python .ToolsGCP/tools/check_maker_i18n.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("TOOLSGCP_NO_SETTINGS_WRITE", "1")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

PROBLEMS = []


def check(ok, message):
    print(("[ok] " if ok else "[!!] ") + message)
    if not ok:
        PROBLEMS.append(message)


def main():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])

    from pymodels.core.language_manager import LanguageManager
    from pymodels.core.settings_manager import SettingsManager
    from pymodels.interfaces.resource_maker_pages import FormPage

    lang = LanguageManager()
    settings = SettingsManager()

    class Host:
        project_root = str(PROJECT_ROOT)

        def get_text(self, key):
            text = lang.get_text("maker", key)
            return text if text != key else key

        def library_path(self):
            return str(Path(tempfile.gettempdir()) / "_maker_i18n_probe.json")

        def show_message(self, *_a, **_k):
            pass

        def is_dark(self):
            return False

        def apply_theme(self, *_a, **_k):
            pass

    page = FormPage(Host())
    # build_steps() 只返回步骤，要自己调用
    for _name, step in page.build_steps():
        step()
    page.finish_build()
    check(bool(getattr(page, "i18n_edits", None)), "多语言卡片建出来了")
    check(page.i18n_enabled(), "多语言开关**默认开启**（要求三语言提交）")
    check(sorted(page.i18n_edits.keys()) == ["English", "简体中文", "繁體中文"],
          f"三种语言的键是规范名（实际 {sorted(page.i18n_edits.keys())}）")
    check(len(page.i18n_edits["English"]) == 4,
          "每种语言都有 名称/简介/应用介绍/补充说明 四个格子")

    # 填一条：三语言
    page.name_edit.setText("本地发送")
    page.id_edit.setText("localsend-x")
    page._set_plain_text(page.i18n_edits["简体中文"][1], "跨平台局域网文件传输工具")
    page._set_plain_text(page.i18n_edits["简体中文"][2], "这是一个很长的应用介绍")
    page._set_plain_text(page.i18n_edits["简体中文"][3], "补充说明一段")
    page.i18n_edits["简体中文"][0].setText("本地发送")
    page.i18n_edits["繁體中文"][0].setText("本機傳送")
    page.i18n_edits["English"][0].setText("LocalSend")
    page.i18n_edits["English"][1].setText("Cross-platform LAN file transfer")
    page._set_plain_text(page.i18n_edits["English"][2], "A longer about text")
    page._set_plain_text(page.i18n_edits["English"][3], "Extra notes")

    entry = page.build_entry()
    name = entry.get("name")
    check(isinstance(name, dict), f"name 落盘是带语言键的对象（实际 {type(name).__name__}）")
    if isinstance(name, dict):
        check(name.get("English") == "LocalSend" and name.get("繁體中文") == "本機傳送",
              "三种语言的名称都写进去了")
    desc = entry.get("description")
    check(isinstance(desc, dict) and desc.get("English"),
          "简介也写成了多语言对象")
    check(isinstance(entry.get("intro"), dict) and entry["intro"].get("English")
          == "A longer about text", "应用介绍写成了多语言对象")
    check(isinstance(entry.get("supplement"), dict),
          "补充说明写成了多语言对象")

    page.i18n_switch.setChecked(False)
    entry2 = page.build_entry()
    check(isinstance(entry2.get("name"), str),
          "关掉多语言开关时退回单语言字符串")

    page.i18n_switch.setChecked(True)
    page.load_i18n_from_entry({
        "name": {"简体中文": "甲", "English": "Alpha"},
        "description": {"English": "desc"},
        "category": ["工具"],
        "tags": ["官方"],
    })
    check(page.i18n_edits["English"][0].text() == "Alpha",
          "载入时英文名称回填正确")
    check(page.i18n_edits["简体中文"][0].text() == "甲",
          "载入时简中名称回填正确")

    # 英文界面下选类别也要存中文规范值
    lang.set_language("English")
    check(page._term("工具") == "Tools", f"英文下「工具」显示成 Tools（实际 {page._term('工具')}）")
    check(page._canonical_term("Tools") == "工具",
          "英文界面下选中的类别会被还原成规范值「工具」")
    check(page._canonical_term("我自己起的类别") == "我自己起的类别",
          "用户自建的类别原样保留")
    lang.set_language("简体中文")

    print()
    if PROBLEMS:
        print(f"[!!] {len(PROBLEMS)} 个问题")
        return 1
    print("[OK] 提交软件三语言自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
