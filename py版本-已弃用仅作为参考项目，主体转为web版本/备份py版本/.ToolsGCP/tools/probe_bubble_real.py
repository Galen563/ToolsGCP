"""在**真实聊天面板**里量气泡：圆角 + 多余空白 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/probe_bubble_real.py

逐条打印：气泡本体尺寸 vs 正文需要的高度、自然宽度、label 四角像素（判断圆角）。
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

MESSAGES = [
    ("user", "帮我找个局域网传文件的工具"),
    ("assistant", "推荐 LocalSend：跨平台、开源、免登录，手机和电脑在同一个 Wi-Fi 下"
                  "就能直接互传。\n\n它的特点是：\n1. 不需要服务器中转；\n"
                  "2. 支持 Windows / macOS / Linux / Android / iOS；\n"
                  "3. 传输走的是局域网，速度取决于路由器。"),
    ("user", "好"),
    ("assistant", "打开就能用，两端都装好之后会自动互相发现。"),
    # ⚠️ 用户真实会话里的那两条（无 API Key 时的固定回答，带 <a> 链接）
    ("user", "你好11122222你好"),
    ("assistant", '还没配置 <a href="toolsgcp://api_key">API Key</a>，填好就能聊。'),
]


def main():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget

    app = QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.LIGHT, lazy=False)
    apply_app_palette(False)

    from pymodels.core.language_manager import LanguageManager
    from pymodels.core.settings_manager import SettingsManager
    from pymodels.ui.ai_chat_panel import AIChatDrawer, ChatBubble

    class Fake(QWidget):
        def __init__(self):
            super().__init__()
            self.titleBar = QWidget(self)
            self.language_manager = LanguageManager()
            self.settings_manager = SettingsManager()

    holder = QWidget()
    holder.resize(1180, 800)
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(32, 32, 8, 16)
    drawer = AIChatDrawer(Fake(), holder, embedded=True)
    layout.addWidget(drawer)
    drawer.session.messages = [{"role": role, "content": text, "ts": ""}
                               for role, text in MESSAGES]
    drawer._render_session()
    holder.show()
    for _ in range(12):
        QTimer.singleShot(80, app.quit)
        app.exec_()
    drawer.sync_bubble_width()
    drawer._apply_bubble_width()
    for _ in range(4):
        QTimer.singleShot(80, app.quit)
        app.exec_()

    print(f"行宽={drawer._row_width()} 上限={drawer._bubble_width()}")
    for bubble in drawer.message_host.findChildren(ChatBubble):
        label = bubble.label
        if not bubble._is_user and "推荐" in bubble.plain_text():
            # AI 气泡下方还挂着操作栏，frame 会更高；这里只量正文那一格
            pass
        hfw = label.heightForWidth(max(1, label.width()))
        natural = bubble._natural_text_width()
        print(f"\n[{'用户' if bubble._is_user else 'AI'}] "
              f"frame={bubble.width()}x{bubble.height()} "
              f"label={label.width()}x{label.height()} "
              f"host={bubble._text_stack_host.width()}x{bubble._text_stack_host.height()}")
        print(f"    正文需要高度={hfw}  气泡实际高度={label.height()}  "
              f"多出来={label.height() - hfw}")
        print(f"    正文自然宽={natural}  气泡宽={label.width()}  "
              f"横向多出={label.width() - min(natural, bubble._max_width)}")
        image = label.grab().toImage()
        w, h = image.width(), image.height()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        name = "user" if bubble._is_user else "ai"
        image.save(str(OUT_DIR / f"real_bubble_{name}_{w}.png"))

        def px(x, y):
            c = image.pixelColor(x, y)
            return (c.red(), c.green(), c.blue())

        center = px(w // 2, h // 2)
        corners = {tag: px(*pos) for pos, tag in
                   (((0, 0), "左上"), ((w - 1, 0), "右上"),
                    ((0, h - 1), "左下"), ((w - 1, h - 1), "右下"))}
        square = [tag for tag, value in corners.items() if value == center]
        print(f"    中心={center} 角={corners}")
        print(f"    → {'方角：' + '/'.join(square) if square else '四个角都是圆角'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
