"""详情页集成冒烟测试 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/smoke_detail.py

真建一个 SearchInterface（不弹窗口），把资源库每条都送进详情页逐条检查，
再反复切换资源确认没有控件残留。

⚠️ 收藏夹/设置指向项目内真实目录，只用只读接口（all_codes / folders）。
"""

import os
import re
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

# ⚠️ 见 detail_preview.py：不改 sys.argv[0] 会在脚本目录再造一份 .ToolsGCP
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")

sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = []


def check(ok, label, detail=""):
    mark = "OK  " if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(f"{label} {detail}".strip())


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])

    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.DARK, lazy=False)
    apply_app_palette(True)

    from pymodels.core.settings_manager import SettingsManager
    from pymodels.core.favorites_manager import FavoritesManager
    from pymodels.core.language_manager import LanguageManager
    from pymodels.interfaces.search_interface import SearchInterface

    settings = SettingsManager()
    favorites = FavoritesManager()
    lang = LanguageManager()
    page = SearchInterface(settings, lang, favorites)
    page.resize(1180, 800)
    print(f"[..] SearchInterface 构建成功，资源 {len(page.apps_framework.items)} 条")

    loader = page._loader
    assert loader is not None, "loader 没建起来"

    dirty_pattern = re.compile(r"^\s*[\{\[]")
    checked = 0
    for item in loader.get_all():
        page.detail_page.set_resource(item)
        app.processEvents()
        detail = page.detail_page

        name = item.get("name")
        rid = item.get("id")

        # 1) 有 systems 就必须渲染出「适用系统」行
        systems = item.get("systems") or []
        keys = [label.text() for label in detail._key_labels]
        if systems:
            check("适用系统" in keys, f"{rid}: systems 有值但没有渲染该行", str(keys))

        # 2) 详细信息一行都没有时必须隐藏
        if not keys:
            check(not detail.detail_section.isVisible(),
                  f"{rid}: 详细信息无内容却仍然可见")

        # 3) 键名 / 值里不能出现 dict 的原文
        texts = list(keys)
        for label in detail.detail_card.findChildren(type(detail.intro_label)):
            texts.append(label.text())
        for text in texts:
            if dirty_pattern.match(str(text)):
                check(False, f"{rid}: 渲染出了脏文本", repr(text)[:80])

        # 4) 介绍区块必须有内容（没描述时要有兜底文案）
        check(bool(detail.intro_label.text().strip()),
              f"{rid}: 应用介绍是空的（兜底文案没生效）")

        checked += 1

    # 5) 只有名称的资源：详细信息整块必须隐藏。
    #    ⚠️ 光遍历资源库测不到这条分支，这里专门造一条只有名称的资源压这条路径。
    page.detail_page.set_resource({"id": "only-name", "code": "TG-000000",
                                  "name": "只有名称的资源"})
    app.processEvents()
    detail = page.detail_page
    check(len(detail._key_labels) == 0,
          "只有名称的条目不该渲染出任何详细信息行",
          f"keys={[l.text() for l in detail._key_labels]}")
    check(not detail.detail_section.isVisible(),
          "详细信息一行都没有时整块必须隐藏")
    check(bool(detail.intro_label.text().strip()),
          "没有 description 时「应用介绍」要有兜底文案")

    # 6) 反复切换资源，检查控件残留
    first = loader.get_all()[0]
    for _ in range(6):
        page.detail_page.set_resource(first)
        page.detail_page.set_resource(loader.get_all()[-1])
        app.processEvents()
    page.detail_page.set_resource(first)
    app.processEvents()
    grid_rows = page.detail_page.detail_grid.rowCount()
    expected = len(page.detail_page._key_labels)
    check(grid_rows <= expected + 1,
          "反复切换后详细信息网格行数异常（控件残留）",
          f"grid rowCount={grid_rows}, keys={expected}")

    # 7) 主题重刷不炸
    try:
        page.refresh_theme(force=True)
        page.detail_page.refresh_theme(force=True)
        check(True, "refresh_theme 正常")
    except Exception as e:  # noqa: BLE001
        check(False, "refresh_theme 抛异常", repr(e))

    print(f"\n[..] 逐条检查了 {checked} 条资源")
    if FAILURES:
        print(f"[!!] {len(FAILURES)} 项失败：")
        for line in FAILURES:
            print("   -", line)
        return 1
    print("[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
