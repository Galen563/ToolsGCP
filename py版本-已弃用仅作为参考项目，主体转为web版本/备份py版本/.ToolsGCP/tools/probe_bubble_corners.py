"""聊天气泡圆角 / 空白宽度诊断 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/probe_bubble_corners.py

单独渲染单条气泡采样四角像素（圆角没生效时角上会被涂成底色），再量正文右侧空白。
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


def main():
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.LIGHT, lazy=False)
    apply_app_palette(False)

    from pymodels.ui.ai_chat_panel import ChatBubble

    samples = [
        ("user", True, "帮我找个局域网传文件的工具"),
        ("ai_short", False, "打开就能用，两端都装好之后会自动互相发现。"),
        ("ai_long", False,
         "推荐 **LocalSend**：跨平台、开源、免登录，手机和电脑在同一个 Wi-Fi 下"
         "就能直接互传。\n\n它的特点是：\n1. 不需要服务器中转；\n2. 支持 Windows / "
         "macOS / Linux / Android / iOS；\n3. 传输走的是局域网，速度取决于路由器。"),
    ]

    for name, is_user, text in samples:
        bubble = ChatBubble(text, is_user, False, max_width=760)
        bubble.resize(400, 200)
        bubble.show()
        for _ in range(4):
            QTimer.singleShot(50, app.quit)
            app.exec_()
        bubble.apply_max_width(760, 1112)
        bubble._apply_bubble_width()
        for _ in range(4):
            QTimer.singleShot(50, app.quit)
            app.exec_()

        label = bubble.label
        image = label.grab().toImage()
        w, h = image.width(), image.height()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        image.save(str(OUT_DIR / f"bubble_{name}.png"))

        def px(x, y):
            color = image.pixelColor(x, y)
            return (color.red(), color.green(), color.blue(), color.alpha())

        center = px(w // 2, h // 2)
        print(f"\n[{name}] label={w}x{h} 中心={center}")
        for cx, cy, tag in ((0, 0, "左上"), (w - 1, 0, "右上"),
                            (0, h - 1, "左下"), (w - 1, h - 1, "右下")):
            corner = px(cx, cy)
            same = corner[:3] == center[:3] and corner[3] == center[3]
            print(f"    {tag}角 ={corner} {'← 方角（圆角没生效）' if same else '← 圆角 OK'}")

        natural = bubble._natural_text_width()
        print(f"    自然宽度={natural} 气泡宽度={label.width()} "
              f"上限={bubble._max_width} 行高={label.heightForWidth(label.width())}")
        bubble.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
