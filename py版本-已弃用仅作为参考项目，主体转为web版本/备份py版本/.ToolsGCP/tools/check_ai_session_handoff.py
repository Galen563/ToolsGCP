"""两个 AI 界面之间"当前对话"交接自检 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_ai_session_handoff.py

检查：悬浮球抽屉与侧栏 AI 整页界面来回切换时看到的是同一段对话（含新建对话）。
"""

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
# 自检脚本不许改用户真实设置
os.environ.setdefault("TOOLSGCP_NO_SETTINGS_WRITE", "1")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = []


def check(ok, label, detail=""):
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""),
          flush=True)
    if not ok:
        FAILURES.append(label)


def main():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    from pymodels.ui.main_window import MainWindow
    from pymodels.ui.ai_chat_panel import ChatBubble

    window = MainWindow()
    window.resize(1280, 880)
    window.show()

    def pump(rounds=8, ms=80):
        for _ in range(rounds):
            QTimer.singleShot(ms, app.quit)
            app.exec_()

    pump(14)

    def bubbles_of(drawer):
        return [b for b in drawer.message_host.findChildren(ChatBubble)]

    window.settings_manager.update_setting("ai_enabled", True)
    window.settings_manager.update_setting("ai_sidebar_mode", False)
    window.show_ai()
    pump(10)
    drawer = window.ai_chat_drawer
    check(drawer.is_open(), "悬浮球抽屉已打开")

    # 1) 抽屉里聊到一半
    drawer.session.messages = [
        {"role": "user", "content": "你好", "ts": ""},
        {"role": "assistant", "content": "你好！有什么可以帮你的？", "ts": ""},
        {"role": "user", "content": "帮我找个局域网传文件的工具", "ts": ""},
        {"role": "assistant", "content": "推荐 LocalSend。", "ts": ""},
    ]
    drawer._render_session()
    drawer._publish_session()
    pump(8)
    check(len(bubbles_of(drawer)) == 4, "抽屉里 4 条气泡",
          f"实际 {len(bubbles_of(drawer))}")
    draw_session = drawer.session

    # 打开侧边栏 AI 单独界面
    window.settings_manager.update_setting("ai_sidebar_mode", True)
    window.apply_ai_sidebar_mode(True)
    pump(6)
    window._open_ai_sidebar_page()
    pump(10)
    page = window.aiSidebarPage
    pdrawer = page.drawer
    check(pdrawer.session is draw_session or
          getattr(pdrawer.session, "id", "") == getattr(draw_session, "id", ""),
          "侧栏页接上了抽屉那段对话",
          f"侧栏={getattr(pdrawer.session, 'id', None)} "
          f"抽屉={getattr(draw_session, 'id', None)}")
    check(len(bubbles_of(pdrawer)) == 4, "侧栏页画出了同样的 4 条气泡",
          f"实际 {len(bubbles_of(pdrawer))}")

    # 2) 在侧栏页里又聊了一句
    pdrawer._add_bubble("还有别的吗？", is_user=True,
                        index=len(pdrawer.session.messages))
    pdrawer.session.messages.append({"role": "user", "content": "还有别的吗？",
                                     "ts": ""})
    pdrawer._add_bubble("没有了。", is_user=False,
                        index=len(pdrawer.session.messages))
    pdrawer.session.messages.append({"role": "assistant", "content": "没有了。",
                                     "ts": ""})
    pump(8)
    check(len(bubbles_of(pdrawer)) == 6, "侧栏页现在 6 条气泡",
          f"实际 {len(bubbles_of(pdrawer))}")

    window.settings_manager.update_setting("ai_sidebar_mode", False)
    window.apply_ai_sidebar_mode(False)
    pump(4)
    window.settings_manager.update_setting("ai_sidebar_mode", False)
    window.open_ai_drawer(focus=False)
    pump(12)
    check(drawer.is_open(), "抽屉重新打开")
    check(len(bubbles_of(drawer)) == 6,
          "抽屉里跟着显示出侧栏页新加的两条（同一段对话）",
          f"实际 {len(bubbles_of(drawer))}")

    # 3) 抽屉里点"新对话"，侧栏页要跟着换
    drawer.new_chat()
    pump(4)
    new_id = drawer.session.id
    window.settings_manager.update_setting("ai_sidebar_mode", True)
    window.apply_ai_sidebar_mode(True)
    pump(4)
    window._open_ai_sidebar_page()
    pump(10)
    check(getattr(pdrawer.session, "id", "") == new_id,
          "侧栏页跟着换成了抽屉里新建的那个对话",
          f"侧栏={getattr(pdrawer.session, 'id', None)} 抽屉={new_id}")
    check(len(bubbles_of(pdrawer)) == 0, "新对话是空的（一条气泡都没有）",
          f"实际 {len(bubbles_of(pdrawer))}")

    window.close()

    if FAILURES:
        print(f"\n[!!] {len(FAILURES)} 项失败")
        return 1
    print("\n[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
