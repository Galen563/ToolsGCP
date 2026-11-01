"""详情页离屏自检 —— 只用来出图看排版，不参与程序运行
用法（在项目根目录执行）：
    python .ToolsGCP/tools/detail_preview.py
产物落在 .ToolsGCP/tools/_out/：detail_<主题>_<用例>.png 与 detail_<主题>_sheet.png。
⚠️ 平台插件必须用 `windows`：offscreen 插件字体库是空的（families() 返回 0），
   文字全画不出来；`windows` 下 grab()/render() 同样是离屏渲染，不弹窗口。
"""

import json
import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"
OUT_DIR = TOOLS_DIR / "_out"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

# ⚠️ constants.py 的 SCRIPT_DIR 取自 sys.argv[0]，必须在 import pymodels 前改掉
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")

sys.path.insert(0, str(PKG_DIR))


def fake_language_manager():
    """造一个只实现 get_text 的语言管理器（避开 LanguageManager 的 CONFIG_DIR 依赖）"""
    path = PKG_DIR / "languages" / "search_language.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    class _Lang:
        current_language = "简体中文"

        def get_text(self, module, key, language=None):
            entry = data.get(key)
            if isinstance(entry, dict):
                return entry.get(self.current_language,
                                 entry.get("简体中文", key))
            return key

    return _Lang()


def load_resources():
    """按主程序的方式规范化一遍资源（主要是把 icon 补成完整相对路径）"""
    from pymodels.core.resource_loader import ResourceLoader
    loader = ResourceLoader(language="简体中文")
    ok = loader.load_from_local(".ToolsGCP/ToolsGCP-Resources.json")
    print(f"[preview] 资源库载入: {ok} / {len(loader.get_all())} 条")
    return loader


def collect_cases(loader):
    """挑有代表性的用例：字段最全、最少、字段写法混乱的条目"""
    all_items = loader.get_all()
    by_id = {item.get("id"): item for item in all_items}

    def richest():
        def score(item):
            return (len(item.get("systems") or []) + len(item.get("architectures") or [])
                    + (1 if item.get("supplement") else 0)
                    + (1 if item.get("github") else 0))
        return max(all_items, key=score)

    cases = []
    cases.append(("full", richest()))
    for rid in ("trae", "class-widgets-2", "localsend", "steam"):
        if rid in by_id:
            cases.append((rid, by_id[rid]))
            break
    cases.append(("variants", by_id.get("trae") or richest()))
    # 汇总型条目：盯"详细信息里凭空多出空白行"那类回归
    for rid in ("deepseek", "godot"):
        if rid in by_id:
            cases.append((rid, by_id[rid]))
    # 只有名称的极端条目：详细信息整块应该自己隐藏
    cases.append(("minimal", {"id": "x", "code": "TG-999999", "name": "仅名称的资源",
                              "icon": "logo.png"}))
    # 字段取值不干净的真实条目：多语言字典 + 字符串写法 + 超长网址
    cases.append(("messy", {
        "id": "messy", "code": "TG-888888", "name": "字段写法混乱的条目",
        "category": {"简体中文": "工具", "English": "Tools"},
        "tags": ["工具", {"简体中文": "官方"}],
        "systems": "Windows",
        "architectures": ["x64", "arm64"],
        "description": "描述可以很长，" * 14,
        "supplement": "补充说明也要能换行显示，" * 10,
        "github": "https://github.com/RinLit-233-shiroko/Class-Widgets-2/tree/main/src/widgets",
        "url": "https://example.com/",
        "author_url": "https://space.bilibili.com/569522843",
        "listed_at": "2026-09-21 00:40:14",
    }))

    seen, out = set(), []
    for name, item in cases:
        if name in seen:
            continue
        seen.add(name)
        out.append((name, item))
    return out


def render_case(page, width, height, out_path):
    page.setFixedSize(width, height)
    page.show()
    from PyQt5.QtWidgets import QApplication
    QApplication.processEvents()
    page.resize(width, height)
    QApplication.processEvents()
    # 让 resizeEvent 里那个 singleShot 的居中边距先跑掉
    for _ in range(4):
        QApplication.processEvents()
    pixmap = page.grab()
    pixmap.save(str(out_path), "PNG")
    return pixmap


def stitch(pixmaps, out_path):
    """把多张截图纵向拼一张（留一点白边好分辨）"""
    from PyQt5.QtGui import QPainter, QPixmap, QColor
    from PyQt5.QtCore import Qt

    gap = 18
    width = max(pm.width() for pm in pixmaps)
    height = sum(pm.height() for pm in pixmaps) + gap * (len(pixmaps) - 1)
    sheet = QPixmap(width, height)
    sheet.fill(QColor("#101010"))
    painter = QPainter(sheet)
    y = 0
    for pm in pixmaps:
        painter.drawPixmap(0, y, pm)
        y += pm.height() + gap
    painter.end()
    sheet.save(str(out_path), "PNG")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)

    from qfluentwidgets import setTheme, Theme
    from pymodels.interfaces.resource_detail_interface import ResourceDetailInterface
    from pymodels.utils.theme_utils import apply_app_palette

    loader = load_resources()
    cases = collect_cases(loader)
    lang = fake_language_manager()

    width = int(os.environ.get("PREVIEW_WIDTH", "1180"))
    height = int(os.environ.get("PREVIEW_HEIGHT", "760"))

    for theme_name, theme, dark in (("dark", Theme.DARK, True),
                                    ("light", Theme.LIGHT, False)):
        setTheme(theme, lazy=False)
        # ⚠️ 必须连调色板一起换：只调 setTheme 页面底色还是浅色，图没法用。
        apply_app_palette(dark)
        from qfluentwidgets import isDarkTheme
        print(f"[preview] theme={theme_name} isDarkTheme={isDarkTheme()}")
        pixmaps = []
        for case_name, data in cases:
            page = ResourceDetailInterface(language_manager=lang)
            page.set_resource(data)
            page.refresh_theme(force=True)
            path = OUT_DIR / f"detail_{theme_name}_{case_name}.png"
            pm = render_case(page, width, height, path)
            pixmaps.append(pm)
            print(f"[preview] {theme_name:5s} {case_name:12s} "
                  f"{pm.width()}x{pm.height()} -> {path.name}")
            page.hide()
            page.deleteLater()
            app.processEvents()
        stitch(pixmaps, OUT_DIR / f"detail_{theme_name}_sheet.png")

    print(f"[preview] 产物目录: {OUT_DIR}")


if __name__ == "__main__":
    main()
