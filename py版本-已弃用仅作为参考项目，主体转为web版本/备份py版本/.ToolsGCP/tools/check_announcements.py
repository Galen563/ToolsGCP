"""公告功能自检 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_announcements.py

检查拉取过滤、已读状态、界面截图与红点/弹窗行为。
⚠️ 全程不动用户真实数据：状态写临时目录，且设了 TOOLSGCP_NO_SETTINGS_WRITE。
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"
OUT_DIR = TOOLS_DIR / "_out"

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


# 故意混进"不该出现"的：路人的 Issue、作者本人发的 PR、没标题的碎内容；OWNER 的要保留。
FIXTURE = [
    {
        "id": 3001, "number": 12, "title": "v1.1.4 已发布：部署模式与插件页更新",
        "body": ("## 更新内容\n\n"
                 "- 部署页支持**一键导出**\n"
                 "- 插件页新增网格布局\n\n"
                 "> 注意：更新后请重启程序。\n\n"
                 "详情见 [发布页](https://github.com/Galen563/ToolsGCP/releases)\n"
                 "![截图](https://example.com/a.png)\n"),
        "user": {"login": "Galen563"}, "author_association": "OWNER",
        "html_url": "https://github.com/Galen563/ToolsGCP/issues/12",
        "created_at": "2026-10-07T04:31:00Z",
        "updated_at": "2026-10-07T04:31:00Z",
        "labels": [{"name": "公告"}],
    },
    {
        "id": 3002, "number": 11, "title": "镜像站不稳定的临时说明",
        "body": "`ghproxy.net` 最近不稳定，检查更新失败请在设置里换一个下载源。",
        "user": {"login": "helper-bot"}, "author_association": "OWNER",
        "html_url": "https://github.com/Galen563/ToolsGCP/issues/11",
        "created_at": "2026-10-06T12:00:00Z",
        "updated_at": "2026-10-06T12:00:00Z",
        "labels": [{"name": "公告"}],
    },
    {
        "id": 3003, "number": 10, "title": "我是一个路人发的公告",
        "body": "这条内容**不该**出现在客户端里。",
        "user": {"login": "random-user"}, "author_association": "NONE",
        "html_url": "https://github.com/Galen563/ToolsGCP/issues/10",
        "created_at": "2026-10-06T09:00:00Z",
        "updated_at": "2026-10-06T09:00:00Z",
        "labels": [{"name": "公告"}],
    },
    {
        "id": 3004, "number": 9, "title": "作者发的 PR（不是公告）",
        "body": "把更新器拆成两个文件。",
        "user": {"login": "Galen563"}, "author_association": "OWNER",
        "html_url": "https://github.com/Galen563/ToolsGCP/pull/9",
        "created_at": "2026-10-05T09:00:00Z",
        "updated_at": "2026-10-05T09:00:00Z",
        "labels": [{"name": "公告"}],
        "pull_request": {"url": "https://api.github.com/repos/Galen563/ToolsGCP/pulls/9"},
    },
    {
        "id": 3005, "number": 8, "title": "",
        "body": "只有正文没有标题的碎内容。",
        "user": {"login": "Galen563"}, "author_association": "OWNER",
        "html_url": "https://github.com/Galen563/ToolsGCP/issues/8",
        "created_at": "2026-10-04T09:00:00Z",
        "updated_at": "2026-10-04T09:00:00Z",
        "labels": [{"name": "公告"}],
    },
]


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeGitHub/1.0"

    def do_GET(self):                       # noqa: N802
        self.server.requested.append(self.path)
        if getattr(self.server, "error_code", 0):
            self.send_response(self.server.error_code)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        body = FIXTURE
        if getattr(self.server, "not_a_list", False):
            body = {"message": "Not Found"}
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):           # 不打印访问日志
        pass


def start_fake_github(error_code=0, not_a_list=False):
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.requested = []
    server.error_code = error_code
    server.not_a_list = not_a_list
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/issues"


def check_fetch(server, url):
    from pymodels.core.announcements import fetch_announcements, markdown_to_text

    items = fetch_announcements(sources=[url])
    titles = [item["title"] for item in items]

    check("只保留作者本人（或 OWNER）的 Issue",
                titles == ["v1.1.4 已发布：部署模式与插件页更新", "镜像站不稳定的临时说明"],
          f"实际: {titles}")
    check("路人发的 Issue 被丢掉",
          "我是一个路人发的公告" not in titles)
    check("PR 被丢掉（即使作者本人发的）",
          "作者发的 PR（不是公告）" not in titles)
    check("没有标题的碎内容被丢掉",
          all(item["title"] for item in items))
    check("按时间新 → 旧排序",
          [item["number"] for item in items] == [12, 11],
          f"实际: {[item['number'] for item in items]}")

    path = server.requested[-1] if server.requested else ""
    check("请求带上了 labels=公告（URL 编码）",
          "labels=%E5%85%AC%E5%91%8A" in path, path)
    check("请求带上了 state=open", "state=open" in path, path)
    check("请求带上了破缓存时间戳", "_=" in path, path)

    first = items[0] if items else {}
    check("正文里的 markdown 被擦成纯文本",
          "## " not in first.get("body", "")
          and "**" not in first.get("body", "")
          and "• 部署页支持一键导出" in first.get("body", ""),
          repr(first.get("body", ""))[:200])
    check("链接变成「文字 (地址)」",
          "发布页 (https://github.com/Galen563/ToolsGCP/releases)" in first.get("body", ""))
    check("图片只剩说明文字（不留 markdown 语法）",
          "截图" in first.get("body", "") and "![" not in first.get("body", ""))
    check("日期解析成本地时间文本",
          len(first.get("date", "")) == 16 and first["date"][4] == "-",
          first.get("date", ""))
    check("正文清洗函数对空输入安全",
          markdown_to_text(None) == "" and markdown_to_text("") == "")
    return items


def check_errors():
    """出错返回机器码，界面再按语言翻译（否则英文用户看到中文报错）"""
    from pymodels.core.announcements import (ERR_BAD_RESPONSE, ERR_NETWORK,
                                             ERR_RATE_LIMITED, ERR_REPO_NOT_FOUND,
                                             fetch_announcements)

    def code_of(**kwargs):
        server, url = start_fake_github(**kwargs)
        try:
            fetch_announcements(sources=[url], timeout=5)
            return ""
        except RuntimeError as exc:
            return str(exc)
        finally:
            server.shutdown()

    check("403/429 → 限流错误码", code_of(error_code=403) == ERR_RATE_LIMITED,
          code_of(error_code=429))
    check("404 → 仓库不存在错误码",
          code_of(error_code=404) == ERR_REPO_NOT_FOUND)
    check("500 → 带状态码的 HTTP_ 错误码", code_of(error_code=500) == "HTTP_500")
    check("返回的不是列表 → 响应格式错误码",
          code_of(not_a_list=True) == ERR_BAD_RESPONSE)
    check("连不上 → 网络错误码",
          _refused_code(fetch_announcements) == ERR_NETWORK)


def _refused_code(fetch):
    """连一个没人监听的端口：必须是 NETWORK 错误码"""
    try:
        fetch(sources=["http://127.0.0.1:9/issues"], timeout=3)
        return ""
    except RuntimeError as exc:
        return str(exc)


def check_store(items, tmp_dir):
    from pymodels.core.announcements import AnnouncementStore

    # 本检查要真实落盘，临时摘掉"不许写盘"开关
    saved = os.environ.pop("TOOLSGCP_NO_SETTINGS_WRITE", None)
    try:
        store = AnnouncementStore(data_dir=tmp_dir)
        store.update_items(items)
        check("新拉到的公告默认全是未读",
              store.unread_count() == len(items), f"{store.unread_count()}")

        added = store.mark_all_read()
        check("全部已读返回新增条数", added == len(items), f"{added}")
        check("全部已读之后未读数为 0", store.unread_count() == 0)
        check("重复点全部已读不会重复计数", store.mark_all_read() == 0)

        again = AnnouncementStore(data_dir=tmp_dir)
        check("重启后已读状态仍然保留", again.unread_count() == 0)
        check("重启后内容缓存仍然在", len(again.items) == len(items))

        fresh = AnnouncementStore(data_dir=tmp_dir)
        fresh.read_ids = []
        fresh.items = list(items)
        fresh.save()
        check("清掉已读记录后未读数 = 公告数",
              fresh.unread_count() == len(items), f"{fresh.unread_count()}")

        fresh.mark_all_read(fresh.items[:1])
        check("只标一条已读 → 未读少一条",
              fresh.unread_count() == len(items) - 1, f"{fresh.unread_count()}")

        reloaded = AnnouncementStore(data_dir=tmp_dir)
        check("重读后仍然只少那一条",
              reloaded.unread_count() == len(items) - 1,
              f"{reloaded.unread_count()}")
    finally:
        if saved is not None:
            os.environ["TOOLSGCP_NO_SETTINGS_WRITE"] = saved


def _boot(dark):
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.DARK if dark else Theme.LIGHT, lazy=False)
    apply_app_palette(dark)
    return app


def _pump(app, rounds=8, delay=80):
    from PyQt5.QtCore import QTimer
    for _ in range(rounds):
        QTimer.singleShot(delay, app.quit)
        app.exec_()


def _shot(widget, name, window_handle=False, app=None, backdrop=None):
    """截一张图存到 _out/ 下；backdrop 给透明页面垫底色，否则截图一片黑。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    pixmap = None
    if window_handle and app is not None:
        try:
            pixmap = app.primaryScreen().grabWindow(int(widget.winId()))
        except Exception:
            pixmap = None
    if pixmap is None or pixmap.isNull():
        pixmap = widget.grab()

    if backdrop:
        from PyQt5.QtGui import QColor, QPainter, QPixmap
        composed = QPixmap(pixmap.size())
        composed.fill(QColor(backdrop))
        painter = QPainter(composed)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        pixmap = composed

    pixmap.save(str(path))
    print(f"      · 截图 {path.name}  {pixmap.width()}x{pixmap.height()}")
    return path


def check_ui(items, tmp_dir):
    from pymodels.core.announcements import AnnouncementStore

    for dark, tag in ((False, "light"), (True, "dark")):
        app = _boot(dark)
        tag_name = "暗色" if dark else "亮色"

        from pymodels.core.language_manager import LanguageManager
        from pymodels.interfaces.notice_interface import NoticeInterface

        store = AnnouncementStore(data_dir=tmp_dir)
        store.read_ids = []
        store.items = list(items)
        page = NoticeInterface(LanguageManager(), None, store)
        page.resize(1180, 800)
        page.show()
        _pump(app)

        check(f"[{tag_name}] 一条公告一张卡片",
              len(page._cards) == len(items), f"{len(page._cards)}/{len(items)}")
        check(f"[{tag_name}] 未读数 = 未读公告数",
              page.unread_count() == len(items), f"{page.unread_count()}")
        check(f"[{tag_name}] 「全部已读」按钮默认可用",
              page.mark_all_btn.isEnabled())
        check(f"[{tag_name}] 未读小标签显示条数",
              page.unread_label.isVisible()
              and str(len(items)) in page.unread_label.text(),
              page.unread_label.text())

        from PyQt5.QtWidgets import QLabel
        labels = [w.text() for card in page._cards
                  for w in card.findChildren(QLabel) if w.text()]
        check(f"[{tag_name}] 卡片渲染出标题",
              any(items[0]["title"] in t for t in labels))
        check(f"[{tag_name}] 卡片渲染出正文",
              any("部署页支持一键导出" in t for t in labels), f"{labels[:6]}")
        # 公告页不铺底色（透明），单独截它要垫一层背景色
        _shot(page, f"announcement_page_{tag}.png",
              backdrop="#202020" if dark else "#F3F3F3")

        page.mark_all_read()
        _pump(app, 3)
        check(f"[{tag_name}] 点全部已读后未读归零", page.unread_count() == 0)
        check(f"[{tag_name}] 点全部已读后按钮置灰",
              not page.mark_all_btn.isEnabled())
        check(f"[{tag_name}] 点全部已读后未读标签隐藏",
              not page.unread_label.isVisible())
        _shot(page, f"announcement_page_read_{tag}.png",
              backdrop="#202020" if dark else "#F3F3F3")
        page.close()

        # ⚠️ 主窗口会按配置里存的主题重设一次，建窗口前必须钉住本次的目标主题。
        from pymodels.core import settings_manager as _sm
        from pymodels.ui.main_window import MainWindow
        original_init = _sm.SettingsManager.__init__

        def _forced_theme_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self.settings["theme"] = "深色主题" if dark else "浅色主题"
            # 全局快捷键一个进程只能注册一次：关掉，免得第二个窗口弹提示条遮住截图。
            self.settings["hotkey_enabled"] = False

        _sm.SettingsManager.__init__ = _forced_theme_init
        try:
            window = MainWindow()
        finally:
            _sm.SettingsManager.__init__ = original_init
        window.resize(1280, 880)
        window.show()
        _pump(app, 12, 90)

        # 灌假数据，走和真拉回来同一条路径
        window.noticeInterface.store = AnnouncementStore(data_dir=tmp_dir)
        window.noticeInterface.store.read_ids = []
        window.noticeInterface.store.items = list(items)
        window.noticeInterface.refresh()
        _pump(app, 4)

        check(f"[{tag_name}] 左侧栏红点数字 = 未读数",
              window._notice_unread == len(items), f"{window._notice_unread}")
        check(f"[{tag_name}] 左侧栏红点真的画出来了",
              window.notice_badge is not None and window.notice_badge.width() > 0)
        # 红点要比库默认小一号：库默认量出来是 17x15
        badge = window.notice_badge
        check(f"[{tag_name}] 未读红点比库默认小一号",
              badge.height() <= 13 and badge.width() <= 15,
              f"{badge.width()}x{badge.height()}")
        check(f"[{tag_name}] 一位数的红点是正圆",
              badge.width() == badge.height(),
              f"{badge.width()}x{badge.height()}")

        window.switchTo(window.noticeInterface)
        _pump(app, 6, 90)
        _shot(window, f"announcement_window_{tag}.png", window_handle=True, app=app)
        _shot(window.navigationInterface.panel, f"announcement_badge_{tag}.png",
              backdrop="#202020" if dark else "#F3F3F3")

        try:
            panel = window.navigationInterface.panel
            panel.expand()
            _pump(app, 8, 80)
            badge = window.notice_badge
            check(f"[{tag_name}] 侧栏展开后红点仍在面板内",
                  badge is not None and badge.width() > 0
                  and 0 <= badge.x() <= panel.width(),
                  f"x={badge.x() if badge else '?'} panel={panel.width()}")
            _shot(panel, f"announcement_badge_expanded_{tag}.png",
                  backdrop="#202020" if dark else "#F3F3F3")
            panel.collapse()
            _pump(app, 6, 80)
        except Exception as exc:
            check(f"[{tag_name}] 侧栏展开时红点跟随", False, str(exc))

        from PyQt5.QtWidgets import QLabel as _QLabel

        from pymodels.ui.announcement_dialog import AnnouncementDialog
        unread = window.noticeInterface.unread_items()
        # ⚠️ 弹窗只吃最新那一条（需求）
        dialog = AnnouncementDialog(window, window._notice_dialog_text, unread[0],
                                    len(unread))
        dialog.show()
        _pump(app, 6, 70)
        check(f"[{tag_name}] 弹窗标题是「新公告」",
              dialog.titleLabel.text() == window._notice_dialog_text("notice_dialog_title"),
              dialog.titleLabel.text())
        dialog_texts = [w.text() for w in dialog.findChildren(_QLabel) if w.text()]
        check(f"[{tag_name}] 弹窗里就是最新那一条公告",
              any(unread[0]["title"] in t for t in dialog_texts),
              f"{dialog_texts[:6]}")
        check(f"[{tag_name}] 弹窗里没有第二条公告",
              not any(unread[1]["title"] in t for t in dialog_texts)
              if len(unread) > 1 else True)
        check(f"[{tag_name}] 弹窗提示还有几条没读",
              any(window._notice_dialog_text("notice_dialog_more").format(n=len(unread) - 1) in t
                  for t in dialog_texts),
              f"{dialog_texts[-4:]}")
        check(f"[{tag_name}] 弹窗按钮排成 [稍后][全部已读][查看公告]",
              [dialog.cancelButton.text(), dialog.markButton.text(),
               dialog.yesButton.text()] == [
                  window._notice_dialog_text("notice_btn_later"),
                  window._notice_dialog_text("notice_mark_all_read"),
                  window._notice_dialog_text("notice_btn_view")],
              f"{dialog.cancelButton.text()}|{dialog.markButton.text()}|{dialog.yesButton.text()}")
        _shot(dialog, f"announcement_dialog_{tag}.png", window_handle=True, app=app)
        dialog.close()
        _pump(app, 2)

        # 传整个列表进去也只弹第一条（口径在弹窗自己身上）
        dialog_list = AnnouncementDialog(window, window._notice_dialog_text, unread,
                                         len(unread))
        list_texts = [w.text() for w in dialog_list.findChildren(_QLabel) if w.text()]
        check(f"[{tag_name}] 就算传一串进去也只展示第一条",
              any(unread[0]["title"] in t for t in list_texts)
              and not any(unread[1]["title"] in t for t in list_texts)
              if len(unread) > 1 else True)
        dialog_list.deleteLater()

        dialog2 = AnnouncementDialog(window, window._notice_dialog_text, unread[0],
                                     len(unread))
        dialog2._on_mark_all_read()
        check(f"[{tag_name}] 弹窗点全部已读会回传 read 动作",
              dialog2.action == "read", dialog2.action)
        dialog2.deleteLater()

        from pymodels.interfaces import notice_interface as notice_mod

        class _FakeSignal:
            def __init__(self):
                self.slots = []

            def connect(self, slot):
                self.slots.append(slot)

            def emit(self, *args):
                for slot in list(self.slots):
                    slot(*args)

        class _FakeWorker:
            """假拉取线程：只把信号挂上，不起线程、不打网络"""

            def __init__(self, *args, **kwargs):
                self.fetched = _FakeSignal()
                self.failed = _FakeSignal()

            def start(self):
                pass

            def isRunning(self):
                return False

        page = window.noticeInterface
        original_worker = notice_mod.AnnouncementFetchWorker
        notice_mod.AnnouncementFetchWorker = _FakeWorker
        try:
            page.start_fetch(force=True)
        finally:
            notice_mod.AnnouncementFetchWorker = original_worker

        check(f"[{tag_name}] 点刷新后按钮里出现进度环",
              getattr(page, "_refresh_ring", None) is not None)
        check(f"[{tag_name}] 转圈时按钮图标先收起来（不叠在一起）",
              page.refresh_btn.icon().isNull())
        check(f"[{tag_name}] 转圈时按钮不可再点", not page.refresh_btn.isEnabled())
        # ⚠️ 进度环是动画，必须跑几帧才看得到圆弧 —— 截图前先转一会儿。
        _pump(app, 8, 60)
        _shot(page, f"announcement_refresh_ring_{tag}.png",
              backdrop="#202020" if dark else "#F3F3F3")
        page._on_fetched(list(items))
        _pump(app, 3)
        check(f"[{tag_name}] 结果回来后进度环收掉",
              getattr(page, "_refresh_ring", None) is None)
        check(f"[{tag_name}] 结果回来后图标恢复",
              not page.refresh_btn.icon().isNull())
        check(f"[{tag_name}] 结果回来后按钮可以再点", page.refresh_btn.isEnabled())

        window.noticeInterface.mark_all_read()
        _pump(app, 4)
        check(f"[{tag_name}] 全部已读后红点尺寸归零（画不出来）",
              window.notice_badge is not None
              and window.notice_badge.width() == 0)
        _shot(window.navigationInterface.panel,
              f"announcement_badge_read_{tag}.png",
              backdrop="#202020" if dark else "#F3F3F3")
        from PyQt5.QtCore import QTimer

        from pymodels.core.announcements import popup_pending

        # ⚠️ 带父窗口的 QDialog 不在 topLevelWidgets() 里，只能在 exec_ 上挂钩子记录实例。
        def popup_once(click=None):
            """跑一次 _maybe_show_announcement_popup，返回真弹出来的弹窗列表"""
            opened = []
            original_exec = AnnouncementDialog.exec_

            def _recording_exec(self):
                opened.append(self)
                return original_exec(self)

            def _click():
                if opened and click is not None:
                    click(opened[-1])

            def _force_close():
                """兜底：没点上也要避免卡死在模态循环里"""
                for dialog in opened:
                    try:
                        if dialog.isVisible():
                            dialog.reject()
                    except Exception:
                        pass

            AnnouncementDialog.exec_ = _recording_exec
            try:
                QTimer.singleShot(600, _click)
                QTimer.singleShot(2500, _force_close)
                window._maybe_show_announcement_popup()
            finally:
                AnnouncementDialog.exec_ = original_exec
            _pump(app, 3)
            return opened

        def drain_popups(ms=1300):
            """消化已排上队的延时弹窗（开了立刻关）

            ⚠️ 必须做：否则 700ms 后的弹窗会在某个 _pump 里抢跑，顺手标成"弹过"。
            """
            import time as _time

            original_exec = AnnouncementDialog.exec_
            auto = []

            def _exec_and_close(self):
                auto.append(self)
                QTimer.singleShot(50, self.reject)
                return original_exec(self)

            AnnouncementDialog.exec_ = _exec_and_close
            try:
                deadline = _time.time() + ms / 1000.0
                while _time.time() < deadline:
                    QTimer.singleShot(60, app.quit)
                    app.exec_()
            finally:
                AnnouncementDialog.exec_ = original_exec
            return auto

        def reopen_unread():
            """擦掉已读、清空本会话"弹过"记录，等价于刚启动那一刻"""
            window.noticeInterface.store.read_ids = []
            window.noticeInterface.refresh()
            window._announcement_popped_ids = set()
            window._announcement_popup_retry = 0
            _pump(app, 2)
            drain_popups()

        # ③.5 排下的延时弹窗要先消化掉，否则会抢在 ④b 前标成"弹过"。
        drain_popups()
        reopen_unread()
        check(f"[{tag_name}] 重新灌回未读后红点又亮起来",
              window._notice_unread == len(items)
              and window.notice_badge.width() > 0,
              f"unread={window._notice_unread}")

        window.settings_manager.settings["notify_enabled"] = False
        check(f"[{tag_name}] 关掉通知开关就不弹公告窗", not popup_once())
        window.settings_manager.settings["notify_enabled"] = True

        hit = {"title": "", "item_title": ""}

        def _mark_all(dialog):
            hit["title"] = dialog.titleLabel.text()
            hit["item_title"] = str(dialog.item.get("title") or "")
            dialog.markButton.click()

        opened = popup_once(click=_mark_all)
        check(f"[{tag_name}] 有未读时会自动弹「新公告」窗", bool(opened))
        if opened:
            check(f"[{tag_name}] 自动弹的是公告窗（标题对得上）",
                  hit["title"] == window._notice_dialog_text("notice_dialog_title"),
                  hit["title"])
            check(f"[{tag_name}] 别人发的公告不会混进弹窗",
                  "路人" not in hit["title"])
            newest = window.noticeInterface.store.items[0]["title"]
            check(f"[{tag_name}] 自动弹的永远是最新发布的那一条",
                  hit["item_title"] == newest,
                  f"{hit['item_title']!r} != {newest!r}")
        check(f"[{tag_name}] 弹窗点「全部已读」后未读归零",
              window.noticeInterface.unread_count() == 0,
              f"{window.noticeInterface.unread_count()}")
        check(f"[{tag_name}] 弹窗点「全部已读」后红点归零",
              window.notice_badge is not None and window.notice_badge.width() == 0)

        reopen_unread()
        first = popup_once(click=lambda d: d.reject())
        check(f"[{tag_name}] 未读时会弹", len(first) == 1, f"{len(first)}")
        second = popup_once(click=lambda d: d.reject())
        check(f"[{tag_name}] 同一条公告在本会话里不会重复弹（用户反馈的"
              f"『弹过就再也不弹』只该在**没新内容**时成立）",
              not second, f"又弹了 {len(second)} 次")

        # ④d ★ 刷新拉到新公告必须再弹：造条更晚的灌进 store，再走真实回调。
        newer = dict(items[0])
        newer.update({"id": 9999, "number": 999,
                      "title": "刚刚发布的新公告（刷新才拿到的）",
                      "created_at": "2026-10-07T23:59:00Z"})
        window.noticeInterface.store.update_items([newer] + list(items))
        window.noticeInterface.refresh()
        _pump(app, 2)
        refreshed = popup_once(click=lambda d: d.reject())
        check(f"[{tag_name}] ★ 刷新拉到新公告时会弹出公告窗（本轮修的）",
              len(refreshed) == 1, f"{len(refreshed)}")
        if refreshed:
            check(f"[{tag_name}] ★ 弹的正是那条新公告",
                  refreshed[0].item.get("id") == 9999,
                  f"{refreshed[0].item.get('id')}")

        # ④e ★ 重启后（"弹过"记录清空）未读还会再弹。
        window._announcement_popped_ids = set()
        window.noticeInterface.refresh()
        _pump(app, 2)
        again = popup_once(click=lambda d: d.reject())
        check(f"[{tag_name}] ★ 重启后未读的公告还会再弹（用户反馈的第 2 条）",
              len(again) == 1, f"{len(again)}")

        sample = [{"id": 1}, {"id": 2}, {"id": 3}]
        check("[逻辑] 没弹过 → 全是待弹", len(popup_pending(sample, set())) == 3)
        check("[逻辑] 弹过 1、3 → 只剩 2",
              [it["id"] for it in popup_pending(sample, {1, 3})] == [2])
        check("[逻辑] 全弹过 → 一条都不弹",
              popup_pending(sample, {1, 2, 3}) == [])
        check("[逻辑] 脏数据（没有 id / 不是 dict）不会炸",
              popup_pending([{"id": 1}, {}, "x", {"id": None}], set()) == [{"id": 1}])
        check("[逻辑] 保持新→旧的原有顺序",
              [it["id"] for it in popup_pending(sample, set())] == [1, 2, 3])

        empty_store = AnnouncementStore(data_dir=tmp_dir)
        empty_store.items = []
        empty_store.read_ids = []
        fail_page = NoticeInterface(LanguageManager(), None, empty_store)
        fail_page._on_failed("NETWORK")
        _pump(app, 3)
        check(f"[{tag_name}] 拉不到公告时给出失败提示",
              fail_page.empty_hint.text() == fail_page.get_text("notice_load_failed"),
              fail_page.empty_hint.text())
        fail_page.close()

        try:
            window.hotkey_manager.unregister_all()
        except Exception:
            pass
        window.close()
        _pump(app, 2)

    return True


def _state_dir():
    """自检用的临时状态目录

    ⚠️ 放 _out/ 内：有的沙箱允许建目录但不允许写文件，用系统临时目录会假失败。
    """
    directory = OUT_DIR / "_check_state"
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("announcements.json", "announcements.json.tmp"):
        try:
            (directory / name).unlink()
        except FileNotFoundError:
            pass
    return str(directory)


def main():
    server, url = start_fake_github()
    tmp_dir = _state_dir()
    try:
        print("=" * 66)
        print("一、拉取 + 过滤（本地假 GitHub）")
        print("=" * 66)
        items = check_fetch(server, url)

        print()
        print("=" * 66)
        print("二、已读 / 未读状态（临时目录，不动用户数据）")
        print("=" * 66)
        check_store(items, tmp_dir)

        print()
        print("=" * 66)
        print("三、界面（公告页 / 弹窗 / 左侧栏红点）")
        print("=" * 66)
        check_ui(items, tmp_dir)
    finally:
        server.shutdown()

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
