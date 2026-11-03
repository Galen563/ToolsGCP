"""GitHub 页自检 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_github_page.py

查删掉的文案不再出现、两条链接行为一致，亮/暗主题各截图到 tools/_out/。
"""

import json
import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"
OUT_DIR = TOOLS_DIR / "_out"
LANG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules" / "languages"

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


def check_language_files():
    path = LANG_DIR / "github_language.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    check("语言文件里没有 author_intro_title", "author_intro_title" not in data)
    check("语言文件里没有 author_intro_text", "author_intro_text" not in data)
    check("语言文件里没有 sponsor_text（那句「赞助一下吧…」）",
          "sponsor_text" not in data)
    check("语言文件里还留着赞助二维码那一块要用的 sponsor_title",
          "sponsor_title" in data)

    for module, key, expected in (
        ("github", "visit_github", "作者Github"),
        ("github", "repo_link", "Github"),
    ):
        entry = data.get(key) or {}
        for language in ("简体中文", "繁體中文", "English"):
            check(f"{key} 有 {language} 文案", bool(entry.get(language)),
                  f"{entry}")

    # 兜底表（core/en_fallback.py）是自动生成的，也必须跟着更新
    from pymodels.core.en_fallback import EN_FALLBACK
    github = EN_FALLBACK.get("github", {})
    check("英文兜底表里也没有 author_intro_text", "author_intro_text" not in github)
    check("英文兜底表里也没有 sponsor_text", "sponsor_text" not in github)
    check("英文兜底表里有 repo_link", "repo_link" in github)


def _boot(dark):
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.DARK if dark else Theme.LIGHT, lazy=False)
    apply_app_palette(dark)
    return app


def _pump(app, rounds=8, delay=70):
    from PyQt5.QtCore import QTimer
    for _ in range(rounds):
        QTimer.singleShot(delay, app.quit)
        app.exec_()


def check_page():
    from PyQt5.QtWidgets import QLabel
    from pymodels.core.language_manager import LanguageManager
    from pymodels.interfaces import github_interface as gh

    opened = []
    original_open_url = gh.open_url
    gh.open_url = lambda url, *a, **kw: opened.append(url)

    try:
        for dark, tag in ((False, "light"), (True, "dark")):
            app = _boot(dark)
            tag_name = "亮色" if dark else "暗色"
            page = gh.GithubInterface(LanguageManager(), None)
            page.resize(1180, 800)
            page.show()
            _pump(app)

            labels = [w for w in page.findChildren(QLabel) if w.text()]
            texts = [w.text() for w in labels]

            forbidden = {
                "作者介绍": "作者介绍",
                "作者介绍正文": "ToolsGCP最初构思起源2024年",
                "赞助那句": "赞助一下吧",
            }
            for name, needle in forbidden.items():
                check(f"[{tag_name}] 页面上没有{name}",
                      not any(needle in text for text in texts),
                      f"{[t[:40] for t in texts if needle in t]}")

            link_labels = [w for w in labels
                           if "<a href=" in w.text()]
            check(f"[{tag_name}] 页面正好两条链接（作者 + 仓库）",
                  len(link_labels) == 2, f"{[w.text() for w in link_labels]}")
            hrefs = " ".join(w.text() for w in link_labels)
            check(f"[{tag_name}] 有作者主页链接",
                  "https://github.com/Galen563\"" in hrefs or
                  'href="https://github.com/Galen563"' in hrefs, hrefs)
            check(f"[{tag_name}] 有项目仓库链接",
                  'href="https://github.com/Galen563/ToolsGCP"' in hrefs, hrefs)
            check(f"[{tag_name}] 链接文字是「作者Github：」",
                  any("作者Github" in w.text() for w in link_labels))
            check(f"[{tag_name}] 链接文字里有「Github：」",
                  any(w.text().startswith("Github：") for w in link_labels))
            check(f"[{tag_name}] 两条链接都关掉了 setOpenExternalLinks（走我们自己的 open_url）",
                  all(not w.openExternalLinks() for w in link_labels))

            # 点第一条链接：必须走 utils/url_open，而不是 Qt 自己开浏览器
            opened.clear()
            link_labels[0].linkActivated.emit("https://github.com/Galen563")
            check(f"[{tag_name}] 点链接会经过 utils/url_open",
                  opened == ["https://github.com/Galen563"], f"{opened}")

            # 源码页（大图）要还能打开，Esc 能回来
            if getattr(page, "qr_label", None) is not None:
                page.show_full_image()
                check(f"[{tag_name}] 点二维码能进大图页", page.stack.currentIndex() == 1)
                page._on_escape()
                check(f"[{tag_name}] 大图页按 Esc 能回内容页",
                      page.stack.currentIndex() == 0)

            hint = [w for w in labels if w.text() == page.get_text("click_to_zoom")]
            qr = getattr(page, "qr_label", None)
            if hint and qr is not None:
                hint_label = hint[0]
                same_column = abs(hint_label.x() - qr.x()) < 60
                below = hint_label.y() > qr.y()
                check(f"[{tag_name}] 「点击放大图片」在二维码正下方",
                      same_column and below,
                      f"hint=({hint_label.x()},{hint_label.y()}) "
                      f"qr=({qr.x()},{qr.y()})")
                check(f"[{tag_name}] 那行提示的宽度和图片对齐（居中在图片下方）",
                      abs(hint_label.width() - qr.width()) <= 2,
                      f"{hint_label.width()} vs {qr.width()}")
            else:
                check(f"[{tag_name}] 找得到二维码和「点击放大图片」",
                      False, f"hint={len(hint)} qr={qr}")

            OUT_DIR.mkdir(parents=True, exist_ok=True)
            path = OUT_DIR / f"github_page_{tag}.png"
            page.grab().save(str(path))
            print(f"      · 截图 {path.name}")
            page.close()
            _pump(app, 2)
    finally:
        gh.open_url = original_open_url


def main():
    print("=" * 66)
    print("一、语言文件（删掉的 + 新增的）")
    print("=" * 66)
    check_language_files()

    print()
    print("=" * 66)
    print("二、页面本身（亮 / 暗）")
    print("=" * 66)
    check_page()

    print()
    if FAILURES:
        print(f"❌ {len(FAILURES)} 项没通过：")
        for item in FAILURES:
            print(f"   - {item}")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
