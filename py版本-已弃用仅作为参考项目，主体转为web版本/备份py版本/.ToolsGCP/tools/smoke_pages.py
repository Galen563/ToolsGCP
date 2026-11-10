"""全页面冒烟 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/smoke_pages.py

⚠️ 必须装 Qt 消息处理器：PyQt5 里槽函数抛异常不打印 traceback，而是 qFatal
   直接 abort（exit code 0xC0000409），而本项目逻辑大量挂在信号上。
"""

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
# ⚠️ 脚本会真的切主题/开侧边栏 AI，不设它会改掉用户真实的 toolsgcp_config.json
os.environ.setdefault("TOOLSGCP_NO_SETTINGS_WRITE", "1")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

ERRORS = []


def install_qt_handler():
    from PyQt5.QtCore import qInstallMessageHandler

    def handler(mode, ctx, message):
        text = str(message)
        if "Traceback" in text or "Error" in text or "error" in text:
            ERRORS.append(text)
            sys.stderr.write("QT-MSG: " + text + "\n")
            sys.stderr.flush()

    qInstallMessageHandler(handler)


def main():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    install_qt_handler()

    from pymodels.ui.main_window import MainWindow
    from pymodels.utils.fonts import apply_font

    window = MainWindow()
    window.resize(1280, 880)
    window.show()

    def pump(rounds=6, ms=70):
        for _ in range(rounds):
            QTimer.singleShot(ms, app.quit)
            app.exec_()

    pump(12)

    pages = [
        ("首页", "homeInterface"), ("搜索", "searchInterface"),
        ("GCP工坊", "workshopInterface"), ("收藏", "toolsGCPInterface"),
        ("AI 整页", "aiSidebarPage"), ("部署", "deployInterface"),
        ("Github", "githubInterface"), ("日志", "logInterface"),
        ("反馈", "feedbackInterface"), ("公告", "noticeInterface"),
        ("插件", "pluginInterface"), ("设置", "settingsInterface"),
    ]
    for label, attr in pages:
        page = getattr(window, attr, None)
        if page is None:
            print(f"[--] {label}: 页面不存在（跳过）")
            continue
        try:
            window.switchTo(page)
            on_shown = getattr(page, "on_shown", None)
            if callable(on_shown):
                on_shown()
            pump(5)
            print(f"[ok] {label}")
        except Exception as exc:  # noqa: BLE001
            ERRORS.append(f"{label}: {exc!r}")
            print(f"[!!] {label}: {exc!r}")

    # 提交软件
    try:
        maker = getattr(window, "resourceMakerInterface", None)
        if maker is None:
            from pymodels.interfaces.resource_maker_interface import \
                ResourceMakerInterface
            maker = ResourceMakerInterface(window.language_manager,
                                           window.settings_manager)
            window.resourceMakerInterface = maker
            window.stackedWidget.addWidget(maker)
        window.switchTo(maker)
        pump(8)
        for key in ("form", "browser", "batch", "help"):
            maker.show_section(key)
            pump(8)
            print(f"[ok] 提交软件/{key}")
    except Exception as exc:  # noqa: BLE001
        ERRORS.append(f"提交软件: {exc!r}")
        print(f"[!!] 提交软件: {exc!r}")

    # AI 抽屉开关
    try:
        window.open_ai_drawer(focus=True)
        pump(4)
        window.close_ai_drawer()
        pump(4)
        print("[ok] AI 抽屉开关")
    except Exception as exc:  # noqa: BLE001
        ERRORS.append(f"AI 抽屉: {exc!r}")
        print(f"[!!] AI 抽屉: {exc!r}")

    # 侧边栏 AI 模式：呼出AI 不能把悬浮球放出来
    try:
        ball = getattr(window, "ai_floating_button", None)
        window.settings_manager.update_setting("ai_sidebar_mode", True)
        if ball is not None:
            ball.detach()
        pump(4)
        window.show_ai()
        pump(8)
        ball_visible = bool(ball is not None and ball.isVisible())
        ai_page = getattr(window, "aiSidebarPage", None)
        on_ai_page = (window.stackedWidget.currentWidget() is ai_page)
        if ball_visible:
            print("[!!] 侧边栏 AI 模式下「呼出AI」把悬浮球放出来了")
            ERRORS.append("侧边栏 AI 模式下悬浮球不该出现")
        elif not on_ai_page:
            print("[!!] 侧边栏 AI 模式下「呼出AI」没有切到 AI 页")
            ERRORS.append("侧边栏 AI 模式下没有切到 AI 页")
        else:
            print("[ok] 侧边栏 AI 模式：呼出AI 切页且不放悬浮球")
        window.settings_manager.update_setting("ai_sidebar_mode", False)
        if ball is not None:
            ball.detach()
        pump(3)
    except Exception as exc:  # noqa: BLE001
        ERRORS.append(f"侧边栏 AI: {exc!r}")
        print(f"[!!] 侧边栏 AI: {exc!r}")

    # 托盘菜单：把每个回调都点一遍（退出那个跳过）+ 右键弹出这条路
    try:
        from PyQt5.QtWidgets import QSystemTrayIcon
        menu = getattr(window, "tray_menu", None)
        if menu is None:
            print("[!!] 托盘菜单没建出来")
            ERRORS.append("托盘菜单没建出来")
        else:
            actions = menu.actions()
            print(f"[ok] 托盘菜单 {len(actions)} 项: "
                  f"{[a.text() for a in actions]}")
            # ⚠️ 右键这条路必须显式测：没调 setContextMenu（会走 Windows 原生
            #    HMENU，样式表全失效），改成 activated(Context) 自己弹。
            window.on_tray_activated(QSystemTrayIcon.Context)
            pump(2)
            if menu.isVisible():
                print("[ok] 托盘右键菜单能弹出来")
            else:
                print("[!!] 托盘右键菜单没弹出来")
                ERRORS.append("托盘右键菜单没弹出来")
            menu.close()
            pump(2)
            for action in actions:
                if not action.text() or action.text() in ("退出", "Exit"):
                    continue
                action.trigger()
                pump(3)
                print(f"[ok] 托盘菜单项「{action.text()}」")
    except Exception as exc:  # noqa: BLE001
        ERRORS.append(f"托盘菜单: {exc!r}")
        print(f"[!!] 托盘菜单: {exc!r}")

    # 切主题（深 → 浅）
    try:
        window.settings_manager.update_setting("theme", "深色主题")
        pump(4)
        window.refresh_all_pages_theme()
        pump(6)
        window.settings_manager.update_setting("theme", "浅色主题")
        window.refresh_all_pages_theme()
        pump(6)
        print("[ok] 主题切换")
    except Exception as exc:  # noqa: BLE001
        ERRORS.append(f"主题: {exc!r}")
        print(f"[!!] 主题: {exc!r}")

    # 切字体（并且要真的换掉控件上的字体）
    try:
        before = window.title_label.font().families() if hasattr(window, "title_label") else []
        applied = apply_font("SimSun")
        pump(5)
        print(f"[ok] 字体切换 -> {applied}（原 {before}）")
        apply_font("微软雅黑")
        pump(4)
    except Exception as exc:  # noqa: BLE001
        ERRORS.append(f"字体: {exc!r}")
        print(f"[!!] 字体: {exc!r}")

    print()
    if ERRORS:
        print(f"[!!] {len(ERRORS)} 个问题：")
        for item in ERRORS[:20]:
            print("   -", str(item)[:400])
        return 1
    print("[OK] 全页面冒烟通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
