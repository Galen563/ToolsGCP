"""开关文字（On/Off）三语言自检 —— 不参与程序运行

用法：python .ToolsGCP/tools/check_switch_texts.py

qfluentwidgets 的 SwitchButton 把 "On" / "Off" 写死，要靠事件过滤器改成当前语言。
"""

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("TOOLSGCP_NO_SETTINGS_WRITE", "1")
# ⚠️ 必须把 argv[0] 指到 ToolsGCP.pyw：constants.py 按它算 CONFIG_DIR
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / ".ToolsGCP" / "modules"))

PROBLEMS = []
EXPECTED = {
    "简体中文": ("开", "关"),
    "繁體中文": ("開", "關"),
    "English": ("On", "Off"),
}


def check(ok, message):
    print(("[ok] " if ok else "[!!] ") + message)
    if not ok:
        PROBLEMS.append(message)


def main():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])

    from qfluentwidgets import SwitchButton
    from pymodels.core.language_manager import LanguageManager
    from pymodels.utils.i18n_widgets import (apply_switch_text,
                                             install_switch_text_i18n)

    lang = LanguageManager()

    # 1) 工具函数（⚠️ onText/offText 是属性，不是方法）
    for language, expected in EXPECTED.items():
        lang.set_language(language)
        switch = SwitchButton()
        apply_switch_text(switch)
        got = (switch.onText, switch.offText)
        check(got == expected, f"{language}: 开关文字 = {got}")

    lang.set_language("简体中文")
    blank = SwitchButton()
    blank.setOnText("")
    blank.setOffText("")
    apply_switch_text(blank)
    check((blank.onText, blank.offText) == ("", ""),
          "本来就留空的开关不会被补文字")

    install_switch_text_i18n(app)
    from pymodels.core.settings_manager import SettingsManager
    from pymodels.ui.main_window import MainWindow

    settings = SettingsManager()
    settings.settings["language"] = "简体中文"

    window = MainWindow()
    window.resize(1100, 780)
    window.show()
    for _ in range(12):
        QTimer.singleShot(80, app.quit)
        app.exec_()
    window.switchTo(window.settingsInterface)
    for _ in range(6):
        QTimer.singleShot(80, app.quit)
        app.exec_()

    switches = window.settingsInterface.findChildren(SwitchButton)
    # ⚠️ 只看当前可见的开关：藏起来的收不到 Show 事件，显示时自会补上，不是漏改。
    visible = [s for s in switches if s.isVisible()]
    pairs = {(s.onText, s.offText) for s in visible}
    check(bool(visible) and pairs == {("开", "关")},
          f"真实窗口里可见的 {len(visible)}/{len(switches)} 个开关都用中文"
          f"（实际 {pairs}）")

    window.close()
    for _ in range(2):
        QTimer.singleShot(60, app.quit)
        app.exec_()

    print()
    if PROBLEMS:
        print(f"[!!] {len(PROBLEMS)} 个问题")
        return 1
    print("[OK] 开关文字三语言自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
