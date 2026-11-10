"""GCP-AI 历史对话载入 + 编辑重发自检 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_ai_history.py

覆盖：真鼠标点历史卡片载入、编辑重发的前后版 UI / 落盘 / 重新载入、坏数据修复。
"""

import json
import os
import shutil
import sys
import tempfile
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


def _make_fake_window_class():
    """假主窗口必须是真 QWidget（历史抽屉会拿它当 parent）"""
    from PyQt5.QtWidgets import QWidget

    class FakeMainWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.titleBar = QWidget(self)
            from pymodels.core.language_manager import LanguageManager
            from pymodels.core.settings_manager import SettingsManager
            self.language_manager = LanguageManager()
            self.settings_manager = SettingsManager()

    return FakeMainWindow


def pump(app, rounds=6, ms=60):
    from PyQt5.QtCore import QTimer
    for _ in range(rounds):
        QTimer.singleShot(ms, app.quit)
        app.exec_()


def bubble_texts(drawer):
    from pymodels.ui.ai_chat_panel import ChatBubble
    result = []
    for bubble in drawer.message_host.findChildren(ChatBubble):
        result.append(("我" if bubble._is_user else "AI", bubble.plain_text()))
    return result


def main():
    from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget

    app = QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.LIGHT, lazy=False)
    apply_app_palette(False)

    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from pymodels.core.ai.chat_store import ChatStore
    from pymodels.ui.ai_chat_panel import AIChatDrawer, ChatBubble

    # ⚠️ 临时目录必须放在**工作区里**：系统临时目录在沙箱下会被拒（os.listdir 报 WinError 5）
    tmp = str(TOOLS_DIR / "_out" / "ai_history_tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    try:
        store = ChatStore(tmp)
        wanted = {}
        for i in range(3):
            session = store.new_session()
            store.append(session, "user", f"第{i}个问题")
            store.append(session, "assistant", f"第{i}个回答")
            wanted[session.id] = (f"第{i}个问题", f"第{i}个回答")

        holder = QWidget()
        holder.resize(420, 760)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        drawer = AIChatDrawer(_make_fake_window_class()(), holder, embedded=True)
        drawer.store = store
        layout.addWidget(drawer)
        holder.show()
        pump(app, 8)

        # refresh 会重建卡片，所以每点一张都要重新打开抽屉
        loaded_ids = []
        for session_id in list(wanted.keys()):
            drawer.open_history()
            pump(app, 5)
            history = drawer.history_drawer
            card = next((c for c in history._cards if c.session_id == session_id),
                        None)
            if card is None:
                check(False, f"历史列表里应当有 {session_id[-6:]} 这张卡片")
                continue
            QTest.mouseClick(card, Qt.LeftButton, pos=card.rect().center())
            pump(app, 6)
            loaded_ids.append(session_id)
            texts = bubble_texts(drawer)
            expected = wanted.get(session_id)
            ok = (drawer.session is not None and drawer.session.id == session_id
                  and texts == [("我", expected[0]), ("AI", expected[1])])
            check(ok, f"点历史卡片 {session_id[-6:]} 应当载入该对话",
                  f"当前会话={getattr(drawer.session, 'id', None)} 气泡={texts}")

        check(len(set(loaded_ids)) == 3, "三张卡片应当对应三个不同会话",
              str(loaded_ids))

        regen = store.new_session()
        store.append(regen, "user", "重新生成测试")
        store.append(regen, "assistant", "回答B")
        regen.messages[1]["variants"] = ["回答A", "回答B"]
        regen.messages[1]["variant_index"] = 1
        store.save(regen)
        drawer.load_session(regen.id)
        pump(app, 8)
        ai_bubbles = [b for b in drawer.message_host.findChildren(ChatBubble)
                      if not b._is_user]
        check(len(ai_bubbles) == 1, "重新生成过的会话应当只有一条 AI 气泡",
              str(len(ai_bubbles)))
        ai_bubble = ai_bubbles[0]
        check(ai_bubble.plain_text() == "回答B",
              "载入后应当显示当前选中的那一版", f"实际={ai_bubble.plain_text()!r}")
        ai_pager = ai_bubble.actions.pager if ai_bubble.actions else None
        check(ai_pager is not None and not ai_pager.isHidden(),
              "载入带版本的历史对话后，翻页器必须可见（2 版以上）")
        drawer._switch_variant(ai_bubble, 0)
        pump(app, 5)
        check(ai_bubble.plain_text() == "回答A",
              "载入后翻到上一版应当显示旧回答",
              f"实际={ai_bubble.plain_text()!r}")

        broken_id = "20261003-175448-e760cc"
        broken = {
            "schema_version": "1.0.0", "id": broken_id, "title": "你好",
            "created_at": "2026-10-03 17:54:48",
            "updated_at": "2026-10-04 22:28:54",
            "model": "deepseek-v4-flash",
            "api_base": "https://api.deepseek.com/v1",
            "messages": [
                {"role": "user", "content": "你好11122222你好",
                 "ts": "2026-10-03 17:56:21",
                 "variants": ["你好111"], "variant_index": 0},
                {"role": "assistant", "content": "还没配置 API Key，填好就能聊。",
                 "ts": "2026-10-04 22:28:54"},
            ],
        }
        with open(store.path_of(broken_id), "w", encoding="utf-8") as f:
            json.dump(broken, f, ensure_ascii=False, indent=2)

        drawer.load_session(broken_id)
        pump(app, 8)
        broken_user = [b for b in drawer.message_host.findChildren(ChatBubble)
                       if b._is_user][0]
        check(broken_user.plain_text() == "你好11122222你好",
              "坏数据的历史对话要能正常载入（显示最新正文）",
              f"实际={broken_user.plain_text()!r}")
        broken_pager = broken_user.actions.pager if broken_user.actions else None
        check(broken_pager is not None and not broken_pager.isHidden(),
              "坏数据载入后应被修好：正文补进版本表 → 翻页器可见")
        with open(store.path_of(broken_id), "r", encoding="utf-8") as f:
            fixed = json.load(f)["messages"][0]
        check(fixed.get("variants") == ["你好111", "你好11122222你好"]
              and fixed.get("variant_index") == 1,
              "修好的版本表要写回磁盘", f"磁盘={fixed.get('variants')}")

        target_id = loaded_ids[0]
        drawer.load_session(target_id)
        pump(app, 6)
        user_bubbles = [b for b in drawer.message_host.findChildren(ChatBubble)
                        if b._is_user]
        check(len(user_bubbles) == 1, "应当只有一条用户气泡", str(len(user_bubbles)))
        bubble = user_bubbles[0]

        drawer._edit_bubble(bubble)
        pump(app, 4)
        check(bubble.is_editing(), "点 edit 之后这条气泡应当进入编辑态")
        bubble.inline_edit.setPlainText("改过之后的问题")
        pump(app, 3)
        # 点对勾（内联编辑态下 copy 按钮就是 accept）
        drawer._inline_edit_accept(bubble)
        pump(app, 8)

        messages = drawer.session.messages
        first = messages[0] if messages else {}
        check(first.get("content") == "改过之后的问题",
              "编辑后会话里的那条用户消息应当被替换",
              f"实际={first.get('content')!r}")
        variants = first.get("variants")
        check(isinstance(variants, list) and len(variants) >= 2
              and variants[0] == "第0个问题" and variants[-1] == "改过之后的问题",
              "「改之前 / 改之后」两版都要留在 variants 里", f"variants={variants}")
        check(first.get("variant_index") == len(variants) - 1,
              "当前应当停在最新那一版", f"variant_index={first.get('variant_index')}")

        new_user = [b for b in drawer.message_host.findChildren(ChatBubble)
                    if b._is_user][0]
        pager = new_user.actions.pager if new_user.actions else None
        check(pager is not None and not pager.isHidden(),
              "编辑重发之后用户气泡应当出现前后版翻页器")

        path = store.path_of(target_id)
        with open(path, "r", encoding="utf-8") as f:
            disk = json.load(f)
        disk_first = disk["messages"][0]
        check(disk_first.get("variants") == variants
              and disk_first.get("variant_index") == first.get("variant_index"),
              "variants / variant_index 必须写进历史 json",
              f"磁盘={ {k: disk_first.get(k) for k in ('content', 'variant_index')} }")

        drawer._reset_variants()
        drawer.load_session(target_id)
        pump(app, 8)
        reloaded_user = [b for b in drawer.message_host.findChildren(ChatBubble)
                         if b._is_user][0]
        pager2 = reloaded_user.actions.pager if reloaded_user.actions else None
        check(pager2 is not None and not pager2.isHidden(),
              "重新载入之后翻页器应当还在")
        drawer._switch_variant(reloaded_user, 0)
        pump(app, 4)
        # ⚠️ 必须重新取一次气泡：用户消息翻页走 _switch_user_branch，会整屏重排
        #    （_render_session），手里的旧气泡已被 deleteLater，拿它断言只会假失败。
        fresh_users = [b for b in drawer.message_host.findChildren(ChatBubble)
                       if b._is_user]
        check(len(fresh_users) == 1, "翻页重排后还应当只有一条用户气泡",
              f"实际 {len(fresh_users)}")
        check(fresh_users and fresh_users[0].plain_text() == "第0个问题",
              "翻到上一版应当显示改之前的内容",
              f"实际={fresh_users[0].plain_text()!r}" if fresh_users else "没有气泡")

        if FAILURES:
            print(f"\n[!!] {len(FAILURES)} 项失败")
            return 1
        print("\n[OK] 全部通过")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
