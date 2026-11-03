"""在**真主窗口**里截 GCP-AI 界面 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/probe_ai_real_window.py [drawer|page]

用用户自己那份会话当素材截 drawer / page 两种界面，并量气泡尺寸与四角渲染像素。
"""

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"
OUT_DIR = TOOLS_DIR / "_out"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

DEMO = [
    {"role": "user", "content": "你好11122222你好", "ts": ""},
    {"role": "assistant",
     "content": '还没配置 <a href="toolsgcp://api_key">API Key</a>，填好就能聊。',
     "ts": ""},
    {"role": "user", "content": "帮我找个局域网传文件的工具", "ts": ""},
    {"role": "assistant",
     "content": "推荐 LocalSend：跨平台、开源、免登录，手机和电脑在同一个 Wi-Fi 下"
                "就能直接互传。\n\n它的特点是：\n1. 不需要服务器中转；\n"
                "2. 支持 Windows / macOS / Linux / Android / iOS；\n"
                "3. 传输走的是局域网，速度取决于路由器。", "ts": ""},
]


def main():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    mode = sys.argv[1] if len(sys.argv) > 1 else "drawer"
    app = QApplication(sys.argv[:1])

    from pymodels.ui.main_window import MainWindow
    window = MainWindow()
    window.resize(1280, 880)
    window.show()

    def pump(rounds=10, ms=90):
        for _ in range(rounds):
            QTimer.singleShot(ms, app.quit)
            app.exec_()

    pump(14)

    from pymodels.ui.ai_chat_panel import ChatBubble
    if mode == "page":
        window.settings_manager.update_setting("ai_sidebar_mode", True)
        window.show_ai()
        pump(14)
        drawer = window.aiSidebarPage.drawer
    else:
        window.settings_manager.update_setting("ai_sidebar_mode", False)
        window.show_ai()
        pump(14)
        drawer = window.ai_chat_drawer

    drawer.session.messages = [dict(m) for m in DEMO]
    drawer._render_session()
    pump(10)
    drawer.sync_bubble_width()
    pump(6)

    shot = app.primaryScreen().grabWindow(int(window.winId()))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"ai_real_{mode}.png"
    shot.save(str(path))
    print(f"[ok] {path} {shot.width()}x{shot.height()}")

    print(f"[..] 消息区视口={drawer.scroll.viewport().width()}x"
          f"{drawer.scroll.viewport().height()} 行宽={drawer._row_width()}")
    for bubble in drawer.message_host.findChildren(ChatBubble):
        label = bubble.label
        hfw = label.heightForWidth(max(1, label.width()))
        natural = bubble._natural_text_width()
        text = bubble.plain_text()
        print(f"\n[{'用户' if bubble._is_user else 'AI'}] {text[:24]!r}")
        print(f"    label={label.width()}x{label.height()} hfw={hfw} "
              f"多出高度={label.height() - hfw}")
        print(f"    自然宽={natural} 气泡宽={label.width()} "
              f"上限={bubble._max_width}")
        # 真实渲染坐标 → 屏幕像素
        top_left = label.mapTo(window, label.rect().topLeft())
        image = shot.toImage()
        def px(dx, dy):
            c = image.pixelColor(top_left.x() + dx, top_left.y() + dy)
            return (c.red(), c.green(), c.blue())
        center = px(label.width() // 2, label.height() // 2)
        corners = {tag: px(*pos) for pos, tag in
                   (((0, 0), "左上"), ((label.width() - 1, 0), "右上"),
                    ((0, label.height() - 1), "左下"),
                    ((label.width() - 1, label.height() - 1), "右下"))}
        square = [tag for tag, v in corners.items() if v == center]
        print(f"    真实渲染 中心={center} 角={corners}")
        print(f"    → {'方角: ' + '/'.join(square) if square else '四个角都是圆角'}")

    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
