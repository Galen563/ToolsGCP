"""聊天气泡排版自检 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_chat_bubbles.py

检查：空会话无气泡、用户气泡靠右/AI 靠左、气泡宽度贴内容且不被折行。
"""

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = []


def check(ok, label, detail=""):
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


class FakeMainWindow:
    def __init__(self):
        from pymodels.core.language_manager import LanguageManager
        from pymodels.core.settings_manager import SettingsManager
        self.language_manager = LanguageManager()
        self.settings_manager = SettingsManager()


def pump(app, rounds=6, ms=70):
    from PyQt5.QtCore import QTimer
    for _ in range(rounds):
        QTimer.singleShot(ms, app.quit)
        app.exec_()


def check_short_bubbles(app, drawer):
    """⚠️ 很短的消息也必须贴着自己那一边（列宽被操作栏撑宽会让短气泡偏左）"""
    from pymodels.ui.ai_chat_panel import ChatBubble

    drawer.session.messages = [
        {"role": "user", "content": "1", "ts": ""},
        {"role": "assistant", "content": "能。", "ts": ""},
        {"role": "user", "content": "帮我找个局域网传文件的工具", "ts": ""},
        {"role": "assistant", "content": "推荐 LocalSend。", "ts": ""},
    ]
    drawer._render_session()
    pump(app, 8)
    drawer.sync_bubble_width()
    pump(app, 4)

    bubbles = drawer.message_host.findChildren(ChatBubble)
    users = [b for b in bubbles if b._is_user]
    ais = [b for b in bubbles if not b._is_user]
    row_left = 14                              # message_layout 的左内边距
    row_right = drawer._row_width() + 14       # 右内边距 → 行的右边界
    if not users or not ais:
        check(False, "短消息气泡建出来了", f"users={len(users)} ais={len(ais)}")
        return
    for bubble, tag in ((users[0], "用户气泡"), (ais[0], "AI 气泡")):
        pos = bubble.label.mapTo(drawer, bubble.label.rect().topLeft())
        right_gap = row_right - (pos.x() + bubble.label.width())
        left_gap = pos.x() - row_left
        if bubble._is_user:
            check(abs(right_gap) <= 4, f"很短的{tag}要贴右（不能停在半路）",
                  f"右边空 {right_gap}px（行右边界 {row_right}）")
        else:
            check(abs(left_gap) <= 4, f"很短的{tag}要贴左",
                  f"左边空 {left_gap}px")

    bubble = users[0]
    drawer._edit_bubble(bubble)
    pump(app, 8)
    drawer.sync_bubble_width()
    pump(app, 4)
    editor = getattr(bubble, "inline_edit", None)
    if editor is None or not bubble.is_editing():
        check(False, "短消息气泡能进内联编辑态")
        return
    pos = editor.mapTo(drawer, editor.rect().topLeft())
    right_gap = row_right - (pos.x() + editor.width())
    check(abs(right_gap) <= 8, "内联编辑框也贴在行右边界内",
          f"编辑框 x={pos.x()} w={editor.width()} 右边空 {right_gap}px")
    check(pos.x() >= row_left - 4, "内联编辑框没有顶出行左边界",
          f"编辑框 x={pos.x()}")
    drawer._cancel_inline_edit()
    pump(app, 6)
    # 退出编辑后气泡要收回正文宽度
    pos = bubble.label.mapTo(drawer, bubble.label.rect().topLeft())
    right_gap = row_right - (pos.x() + bubble.label.width())
    check(abs(right_gap) <= 4, "退出编辑后短气泡仍然贴右",
          f"右边空 {right_gap}px")

    # 正文换内容后宽度也要重算，否则气泡停在旧宽度上
    drawer._set_bubble_text(bubble, "改成一句长一点的话，看看宽度会不会自己跟上")
    pump(app, 6)
    drawer.sync_bubble_width()
    pump(app, 4)
    pos = bubble.label.mapTo(drawer, bubble.label.rect().topLeft())
    right_gap = row_right - (pos.x() + bubble.label.width())
    check(abs(right_gap) <= 4, "正文换内容之后气泡仍然贴右",
          f"右边空 {right_gap}px，气泡宽 {bubble.label.width()}")


def main():
    from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget

    app = QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.LIGHT, lazy=False)
    apply_app_palette(False)

    from pymodels.ui.ai_chat_panel import AIChatDrawer, ChatBubble, BUBBLE_PAD_V

    holder = QWidget()
    holder.resize(420, 760)
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    drawer = AIChatDrawer(FakeMainWindow(), holder, embedded=True)
    layout.addWidget(drawer)
    holder.show()
    pump(app, 8)
    drawer.sync_bubble_width()
    pump(app, 4)

    bubbles = drawer.message_host.findChildren(ChatBubble)
    check(len(bubbles) == 0, "空会话不该有任何气泡（默认对话已删除）",
          f"实际 {len(bubbles)} 条")

    drawer._add_bubble("帮我找个局域网传文件的工具", is_user=True, index=0)
    drawer._add_bubble("推荐 LocalSend：跨平台、开源、免登录，手机和电脑在同一个 "
                       "Wi-Fi 下就能直接互传。", is_user=False, index=1)
    pump(app, 6)
    drawer.sync_bubble_width()
    pump(app, 4)

    bubbles = drawer.message_host.findChildren(ChatBubble)
    users = [b for b in bubbles if b._is_user]
    ais = [b for b in bubbles if not b._is_user]
    check(len(users) == 1 and len(ais) == 1, "两条气泡都建出来了",
          f"users={len(users)} ais={len(ais)}")

    row_width = drawer._row_width()
    user, ai = users[0], ais[0]

    left_gap = ai.label.mapTo(drawer.message_host, ai.label.rect().topLeft()).x()
    user_right = user.label.mapTo(drawer.message_host,
                                  user.label.rect().topRight()).x()
    check(left_gap <= 24, "AI 气泡应当贴左", f"左边距 {left_gap}")
    check(abs(user_right - row_width) <= 24, "用户气泡应当贴右",
          f"气泡右边 x={user_right} 行右边界 x={row_width}")

    user_lines = user.label.heightForWidth(user.label.width())
    check(user.label.width() < 260, "短句气泡应当贴着内容（没有多余空白）",
          f"label 宽 {user.label.width()}")
    # ⚠️ "有没有折行"要拿单行该有的高度比：heightForWidth 里算进了 QSS 上下 padding
    from PyQt5.QtGui import QFontMetrics
    one_line = (QFontMetrics(user.label.font()).lineSpacing()
                + 2 * BUBBLE_PAD_V)
    check(user_lines <= one_line + 4, "一行放得下的用户短句不该被折行",
          f"label 高 {user_lines}（单行应约 {one_line}）")

    ai_w = ai.label.width()
    check(ai_w >= 300, "AI 长消息应当用足可用宽度", f"label 宽 {ai_w}")
    check(ai_w <= ai._max_width + 1, "AI 气泡不该超过最大宽度",
          f"label 宽 {ai_w} 上限 {ai._max_width}")

    print(f"\n[..] 抽屉行宽={row_width}  用户气泡宽={user.label.width()}  "
          f"AI 气泡宽={ai.label.width()}  上限={ai._max_width}")

    check_short_bubbles(app, drawer)

    if FAILURES:
        print(f"\n[!!] {len(FAILURES)} 项失败")
        return 1
    print("\n[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
