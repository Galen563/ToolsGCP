"""全局快捷键自检 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_hotkeys.py

覆盖：解析/回显 round-trip、错误码不抛异常、OEM 标点键、Caps/Num/Scroll 主键、
设置页默认值与 HOTKEY_DEFAULTS 一致。
"""

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("TOOLSGCP_NO_SETTINGS_WRITE", "1")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = []


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    if not condition:
        FAILURES.append(f"{label} {detail}".strip())
    print(f"[{mark}] {label}" + (f"  {detail}" if detail and not condition else ""))
    return bool(condition)


def main():
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QKeySequence
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])

    from pymodels.utils import global_hotkey as gh

    print("=" * 66)
    print("一、解析 / 回显（round-trip）")
    print("=" * 66)

    for text, expect in (("Ctrl+Q", "Ctrl+Q"), ("ctrl+alt+g", "Ctrl+Alt+G"),
                         ("Ctrl+Shift+S", "Ctrl+Shift+S"), ("Alt+F4", "Alt+F4"),
                         ("Ctrl+Space", "Ctrl+Space"), ("Ctrl+Caps", "Ctrl+Caps"),
                         ("F9", "F9")):
        check(f"归一化 {text!r} → {expect!r}",
              gh.normalize_sequence(text) == expect,
              f"实际 {gh.normalize_sequence(text)!r}")

    # OEM 标点键（VK 186~192，回显必须成字符而不是十六进制）
    oem = ((Qt.Key_Minus, "-"), (Qt.Key_Equal, "="), (Qt.Key_BracketLeft, "["),
           (Qt.Key_Semicolon, ";"), (Qt.Key_QuoteLeft, "`"), (Qt.Key_Comma, ","),
           (Qt.Key_Slash, "/"), (Qt.Key_Backslash, "\\"))
    for key, label in oem:
        qt_text = QKeySequence(Qt.ControlModifier | key).toString()
        candidate = "+".join(p for p in qt_text.replace("Meta", "Win").split("+") if p)
        normalized = gh.normalize_sequence(candidate)
        again = gh.normalize_sequence(normalized) if normalized else ""
        check(f"标点键 {label!r}：录制 → 归一 → 再解析都成立",
              bool(normalized) and normalized == again,
              f"qt={qt_text!r} 归一={normalized!r} 再解析={again!r}")
        check(f"标点键 {label!r} 回显成字符而不是十六进制",
              "0X" not in normalized.upper(), f"{normalized!r}")

    # 十六进制兜底解析（兼容老数据）
    check("十六进制写法仍然能解析（老数据不丢）",
          gh.parse_sequence("Ctrl+0xBD")[2] is None
          and gh.parse_sequence("Ctrl+0xBD")[1] == 0xBD)

    print()
    print("=" * 66)
    print("二、错误码（★ 以前这里会抛 TypeError）")
    print("=" * 66)

    for sequence in ("Ctrl+Foo", "Ctrl+0xZZ", "Ctrl+UnknownKey"):
        try:
            err = gh.parse_sequence(sequence)[2]
        except Exception as exc:                      # noqa: BLE001
            check(f"{sequence!r} 只给错误提示，不抛异常", False, repr(exc))
            continue
        check(f"{sequence!r} 给出「不支持的键」提示", bool(err), f"{err}")

    check("空快捷键给「键为空」提示",
          bool(gh.parse_sequence("")[2]) and bool(gh.parse_sequence("   ")[2]))
    check("只有修饰键 → 报「缺少主键」",
          "main" in str(gh.parse_sequence("Ctrl+Alt")[2]).lower()
          or bool(gh.parse_sequence("Ctrl+Alt")[2]),
          gh.parse_sequence("Ctrl+Alt")[2])
    check("两个主键 → 拒绝",
          bool(gh.parse_sequence("Ctrl+Q+W")[2]), gh.parse_sequence("Ctrl+Q+W")[2])
    check("裸字母（没有修饰键）→ 拒绝",
          bool(gh.parse_sequence("Q")[2]), gh.parse_sequence("Q")[2])
    check("F9 可以没有修饰键", gh.parse_sequence("F9")[2] is None)

    print()
    print("=" * 66)
    print("三、系统占用的主键（Caps / Num / Scroll）")
    print("=" * 66)

    check("Ctrl+Caps 被认出来", gh.unusable_main_key("Ctrl+Caps") == "Caps Lock",
          gh.unusable_main_key("Ctrl+Caps"))
    check("Ctrl+Num 被认出来", gh.unusable_main_key("Ctrl+NumLock") == "",
          "NumLock 不在键名表里时应当先被「不支持的键」拦下")
    # ⚠️ 裸 Caps 更早一步就被拦下（缺修饰键），这里认不出"系统占用"是对的。
    check("裸 Caps 走「缺少修饰键」这条更准确的路",
          gh.unusable_main_key("Caps") == "" and bool(gh.parse_sequence("Caps")[2]),
          f"{gh.unusable_main_key('Caps')!r} / {gh.parse_sequence('Caps')[2]!r}")
    check("正常的键不会被误判", gh.unusable_main_key("Ctrl+Q") == ""
          and gh.unusable_main_key("Ctrl+Alt+G") == "")

    print()
    print("=" * 66)
    print("四、设置页默认值 == HOTKEY_DEFAULTS（★ 以前两边不一致）")
    print("=" * 66)

    from pymodels.interfaces.settings.common import HOTKEY_DEFAULTS
    from pymodels.constants import DEFAULT_SETTINGS
    check("HOTKEY_DEFAULTS['ai'] 不再是 Caps 组合",
          "caps" not in HOTKEY_DEFAULTS["ai"][1].lower(),
          HOTKEY_DEFAULTS["ai"][1])
    for name in ("search", "ai"):
        setting_key, default = HOTKEY_DEFAULTS[name]
        check(f"DEFAULT_SETTINGS 里的 {setting_key} 和 HOTKEY_DEFAULTS 一致",
              str(DEFAULT_SETTINGS.get(setting_key)) == default,
              f"{DEFAULT_SETTINGS.get(setting_key)!r} != {default!r}")

    source = (PKG_DIR / "pymodels" / "interfaces" / "settings"
              / "cards_hotkey.py").read_text(encoding="utf-8")
    check("cards_hotkey.py 里没有写死的 Ctrl+Caps",
          "Ctrl+Caps" not in source)

    print()
    print("=" * 66)
    print("五、设置页那一行（录完失焦 / 恢复默认要变回去）")
    print("=" * 66)
    check_settings_row()

    print()
    if FAILURES:
        print(f"❌ {len(FAILURES)} 项没通过：")
        for item in FAILURES:
            print(f"   - {item}")
        return 1
    print("✅ 全部通过")
    return 0


def check_settings_row():
    """建出「快捷键」那张卡片，验证：录完要失焦、恢复默认要把输入框变回去"""
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QKeyEvent
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])

    from pymodels.core.language_manager import LanguageManager
    from pymodels.core.settings_manager import SettingsManager
    from pymodels.interfaces.settings.cards_hotkey import SettingsCardsHotkeyMixin
    from pymodels.interfaces.settings.common import HOTKEY_DEFAULTS
    from pymodels.ui.hotkey_edit import HotkeyEdit

    class Host(SettingsCardsHotkeyMixin):
        """只装出快捷键卡片需要的那几样东西（不建整个设置页）"""

        def __init__(self):
            self.settings_manager = SettingsManager()
            self.lang = LanguageManager()
            self.main_window = None
            self.messages = []

        def get_text(self, key, default=""):
            text = self.lang.get_text("settings", key)
            return text if text and text != key else (default or key)

        def show_message(self, message, kind="info"):
            self.messages.append((str(message), str(kind)))

        def set_label_disabled(self, label, disabled):
            return label

        def _apply_hotkey(self):
            # 自检环境不真去 RegisterHotKey（否则会抢走用户真实的 Ctrl+Q）
            return True, None

    host = Host()
    card = host._create_hotkey_card()
    check("快捷键卡片建出来了", card is not None and bool(host.hotkey_edits))
    edit = host.hotkey_edits["search"]
    check("卡片里的默认值来自 HOTKEY_DEFAULTS",
          edit.sequence() == HOTKEY_DEFAULTS["search"][1],
          f"{edit.sequence()!r} vs {HOTKEY_DEFAULTS['search'][1]!r}")

    host.change_hotkey("search", "Ctrl+W")
    check("录入后输入框显示新键", edit.sequence() == "Ctrl+W", edit.sequence())

    host.reset_hotkey("search")
    check("★ 点「恢复默认」后输入框变回默认键",
          edit.sequence() == HOTKEY_DEFAULTS["search"][1], repr(edit.sequence()))
    check("★ 点「恢复默认」后设置里也是默认键",
          host.settings_manager.settings.get(HOTKEY_DEFAULTS["search"][0])
          == HOTKEY_DEFAULTS["search"][1])

    recorder = HotkeyEdit("Ctrl+Q")
    recorder.show()
    recorder.setFocus()
    app.processEvents()
    check("录制框可以先获得焦点（点一下进入录制状态）", recorder.hasFocus())
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_T,
                      Qt.ControlModifier | Qt.ShiftModifier, "T")
    recorder.keyPressEvent(event)
    app.processEvents()
    check("★ 录完之后输入框自己失焦（不然随便按个键就又被录一遍）",
          not recorder.hasFocus())
    check("录下来的组合键正确", recorder.sequence() == "Ctrl+Shift+T",
          recorder.sequence())
    recorder.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_K,
                                     Qt.NoModifier, "K"))
    check("非法组合（裸字母）不会被写进去", recorder.sequence() == "Ctrl+Shift+T",
          recorder.sequence())
    recorder.close()


if __name__ == "__main__":
    sys.exit(main())
