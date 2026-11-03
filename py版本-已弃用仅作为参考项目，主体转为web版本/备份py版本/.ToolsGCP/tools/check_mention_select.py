"""@ 提及"整体框选"自检 —— 不参与程序运行

用法：python .ToolsGCP/tools/check_mention_select.py

框选 @提及 的任意一段都要扩成整条，删掉后不能残留半截 @。
"""

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = []


def check(ok, label, detail=""):
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def main():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.LIGHT, lazy=False)
    apply_app_palette(False)

    from pymodels.core.settings_manager import SettingsManager
    from pymodels.core.favorites_manager import FavoritesManager
    from pymodels.core.language_manager import LanguageManager
    from pymodels.interfaces.search_interface import SearchInterface

    page = SearchInterface(SettingsManager(), LanguageManager(), FavoritesManager())
    page.resize(1180, 800)

    box = page.search_box
    text = "看看 @LocalSend 怎么样"
    box.setText(text)
    app.processEvents()

    spans = page._mention_spans()
    check(spans == [(3, 13)], "@ 片段定位正确（@LocalSend）", f"spans={spans}")
    span_start, span_end = spans[0]

    # 只选末尾 3 个字符（@LocalS|end|）
    box.setSelection(span_end - 3, 3)
    app.processEvents()

    selected = box.selectedText()
    check(selected == "@LocalSend",
          "框选片段尾部后应自动扩成整条 @LocalSend", f"实际选中={selected!r}")

    box.del_()
    app.processEvents()
    rest = box.text()
    check("@" not in rest, "删除整条 @ 后不应残留半截 @", f"剩余={rest!r}")

    # 反向：从前 4 个字符（@Loc）往左选也要扩成整条
    box.setText(text)
    app.processEvents()
    box.setSelection(span_start, 4)
    app.processEvents()
    check(box.selectedText() == "@LocalSend",
          "框选片段头部后应自动扩成整条 @LocalSend",
          f"实际选中={box.selectedText()!r}")

    # 跨两条提及：从第一条中间拖到第二条中间
    two = "@Alpha 和 @Beta 都在"
    box.setText(two)
    app.processEvents()
    spans2 = page._mention_spans()
    check(len(spans2) == 2, "两条提及都能被识别", f"spans={spans2}")
    box.setSelection(spans2[0][0] + 2, spans2[1][1] - spans2[0][0] - 2)
    app.processEvents()
    check(box.selectedText() == two[:spans2[1][1]],
          "跨两条提及应扩到最外边界",
          f"实际选中={box.selectedText()!r} 期望={two[:spans2[1][1]]!r}")

    plain = "普通 文本 框选"
    box.setText(plain)
    app.processEvents()
    box.setSelection(0, 2)
    app.processEvents()
    check(box.selectedText() == "普通", "不含 @ 的框选不应被改动",
          f"实际选中={box.selectedText()!r}")

    QTimer.singleShot(0, app.quit)
    app.exec_()

    if FAILURES:
        print(f"\n[!!] {len(FAILURES)} 项失败")
        return 1
    print("\n[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
