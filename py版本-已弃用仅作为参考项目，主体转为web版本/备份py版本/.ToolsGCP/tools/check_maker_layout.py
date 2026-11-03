"""提交软件（资源制作器）四节版面一致性自检 —— 不参与程序运行

用法：python .ToolsGCP/tools/check_maker_layout.py

把四个分节依次切一遍，量 root / 页头 / stack 的几何，四节必须完全一样。
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


def pump(app, rounds=10, ms=60):
    from PyQt5.QtCore import QTimer
    for _ in range(rounds):
        QTimer.singleShot(ms, app.quit)
        app.exec_()


def snapshot(page):
    from PyQt5.QtCore import QPoint
    data = {"root": page.root.geometry().getRect()}
    for name in ("title_label", "subtitle_label", "segmented", "stack"):
        widget = getattr(page, name, None)
        if widget is None:
            continue
        top_left = widget.mapTo(page, QPoint(0, 0))
        data[name] = (top_left.x(), top_left.y(),
                      widget.width(), widget.height())
    current = page.stack.currentWidget()
    if current is not None and current is not page._placeholders.get(page._current_key):
        top_left = current.mapTo(page, QPoint(0, 0))
        data["page"] = (top_left.x(), top_left.y(), current.width())
    return data


def main():
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.LIGHT, lazy=False)
    apply_app_palette(False)

    from pymodels.core.language_manager import LanguageManager
    from pymodels.core.settings_manager import SettingsManager
    from pymodels.interfaces.resource_maker_interface import (ResourceMakerInterface,
                                                              SECTIONS)

    page = ResourceMakerInterface(LanguageManager(), SettingsManager())
    page.resize(1280, 880)
    page.show()
    pump(app, 16)

    results = {}
    for key, _text, _icon in SECTIONS:
        page.show_section(key)
        pump(app, 10)
        results[key] = snapshot(page)
        print(f"[..] {key}: root={results[key]['root']} "
              f"stack={results[key].get('stack')}")

    base_key = SECTIONS[0][0]
    base = results[base_key]
    for key, _text, _icon in SECTIONS[1:]:
        now = results[key]
        for field in ("root", "title_label", "subtitle_label", "segmented", "stack"):
            if field not in base or field not in now:
                continue
            check(base[field] == now[field],
                  f"「{key}」的 {field} 应当和投稿表单一致",
                  f"{base[field]} vs {now[field]}")

    # 四节内容页左边界也要一致（不能一节靠左一节居中）
    lefts = {k: v.get("page", (None,))[0] for k, v in results.items()}
    values = [x for x in lefts.values() if x is not None]
    check(len(set(values)) <= 1, "四节内容页的左边界应当一致", str(lefts))

    if FAILURES:
        print(f"\n[!!] {len(FAILURES)} 项失败")
        return 1
    print("\n[OK] 四节版面完全一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
