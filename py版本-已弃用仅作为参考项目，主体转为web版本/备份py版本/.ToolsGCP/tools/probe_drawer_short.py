"""悬浮球（右侧抽屉）短对话气泡探针 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/probe_drawer_short.py [drawer|page]

起真主窗口灌入极短对话，截图并量每条气泡的位置/尺寸（相对抽屉原点）。
"""

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"
OUT_DIR = TOOLS_DIR / "_out"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
# 自检脚本不许改用户真实设置
os.environ.setdefault("TOOLSGCP_NO_SETTINGS_WRITE", "1")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

DEMO = [
    {"role": "user", "content": "你好", "ts": ""},
    {"role": "assistant", "content": "你好！有什么可以帮你的？", "ts": ""},
    {"role": "user", "content": "1", "ts": ""},
    {"role": "assistant", "content": "好", "ts": ""},
    {"role": "user", "content": "帮我找个局域网传文件的工具", "ts": ""},
    {"role": "assistant", "content": "推荐 LocalSend：跨平台、开源、免登录。", "ts": ""},
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

    window.settings_manager.update_setting("ai_enabled", True)
    window.settings_manager.update_setting("ai_sidebar_mode", mode == "page")
    window.show_ai()
    pump(14)

    from pymodels.ui.ai_chat_panel import ChatBubble
    if mode == "page":
        drawer = window.aiSidebarPage.drawer
    else:
        drawer = window.ai_chat_drawer

    real = os.environ.get("PROBE_SESSION", "").strip()
    if real:
        loaded = drawer.store.load(real)
        if loaded is not None:
            drawer.session = loaded
            print(f"[..] 载入真实会话 {real}: {len(loaded.messages)} 条")
    if not real or loaded is None:
        drawer.session.messages = [dict(m) for m in DEMO]
    drawer._render_session()
    pump(10)
    drawer.sync_bubble_width()
    pump(8)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shot = app.primaryScreen().grabWindow(int(window.winId()))
    full = OUT_DIR / f"short_{mode}_full.png"
    shot.save(str(full))

    # 只留抽屉/页面那一块
    top_left = drawer.mapTo(window, drawer.rect().topLeft())
    crop = shot.copy(top_left.x(), top_left.y(),
                     min(drawer.width(), shot.width() - top_left.x()),
                     min(drawer.height(), shot.height() - top_left.y()))
    path = OUT_DIR / f"short_{mode}.png"
    crop.save(str(path))
    print(f"[ok] {full}")
    print(f"[ok] {path} {crop.width()}x{crop.height()}")

    vp = drawer.scroll.viewport()
    print(f"[..] 抽屉={drawer.width()}x{drawer.height()} "
          f"视口={vp.width()}x{vp.height()} 行宽={drawer._row_width()} "
          f"上限={drawer._bubble_width()}")
    for bubble in drawer.message_host.findChildren(ChatBubble):
        label = bubble.label
        text = bubble.plain_text().replace("\n", "⏎")
        pos = label.mapTo(drawer, label.rect().topLeft())
        hfw = label.heightForWidth(max(1, label.width()))
        host = bubble._text_stack_host
        host_pos = host.mapTo(drawer, host.rect().topLeft())
        act = bubble.actions
        act_pos = act.mapTo(drawer, act.rect().topLeft()) if act is not None else None
        frame_pos = bubble.mapTo(drawer, bubble.rect().topLeft())
        print(f"[{'用户' if bubble._is_user else 'AI '}] {text[:20]!r}")
        print(f"    frame  x={frame_pos.x()} w={bubble.width()} h={bubble.height()}")
        print(f"    host   x={host_pos.x()} w={host.width()} sizeHint={host.sizeHint().width()}")
        if act is not None:
            print(f"    action x={act_pos.x()} w={act.width()} "
                  f"右边界={act_pos.x() + act.width()}")
        print(f"    label  x={pos.x()} y={pos.y()} w={label.width()} "
              f"h={label.height()} 正文需要={hfw} 多出={label.height() - hfw}")
        print(f"    自然宽={bubble._natural_text_width()} 行宽={bubble._row_width} "
              f"右边界={pos.x() + label.width()} "
              f"（行右边界应={drawer._row_width() + 14}）")

    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
