"""侧边栏 AI 界面：把聊天面板整页嵌到左侧栏。

⚠️ 面板用 AIChatDrawer(embedded=True) 复用，本页只负责摆位置、转发生命周期，
业务一律调 drawer 的方法。
"""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QWidget

# 页面四周留白（和详情页 / 工坊页同一套：上左下 32、右 8 给滚动条）
PAGE_MARGIN = 32
PAGE_SCROLLBAR_MARGIN = 8


class AISidebarPage(QWidget):
    """左侧栏的 AI 整页界面（内部就是一份 embedded 的聊天面板）"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.setObjectName("aiSidebarPage")
        self.main_window = main_window
        self._drawer = None
        # 本页不画背景，跟搜索页一样透出主窗口底色
        self.setStyleSheet(
            "QWidget#aiSidebarPage, QWidget#aiSidebarHost { background: transparent; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN,
                                 PAGE_SCROLLBAR_MARGIN, 16)
        layout.setSpacing(0)

        self._host = QWidget(self)
        self._host.setObjectName("aiSidebarHost")
        host_layout = QVBoxLayout(self._host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        layout.addWidget(self._host, 1)
        self._host_layout = host_layout

    @property
    def drawer(self):
        """首次访问才建聊天面板（控件树很大，启动时没必要建）"""
        if self._drawer is None:
            self._drawer = self._create_drawer()
        return self._drawer

    def _create_drawer(self):
        """建 embedded 聊天面板，并把抽屉本体放进本页布局。

        ⚠️ 必须放抽屉本体，只搬 container 尺寸链会断；addWidget 重新 parent 后
        控件会被自动 hide()，而隐藏控件不参与父布局分配，所以放完必须再 show()。
        """
        from .ai_chat_panel import AIChatDrawer
        drawer = AIChatDrawer(self.main_window, embedded=True)
        drawer.apply_theme()
        self._host_layout.addWidget(drawer)
        drawer.show()
        return drawer

    def is_built(self) -> bool:
        return self._drawer is not None

    # ---------- 生命周期 ----------
    def on_shown(self):
        """切到本页时：建面板 + 确保它可见 + 聚焦输入框 + 按真实宽度重排气泡"""
        drawer = self.drawer
        # 切页时控件可能被隐藏过，隐藏控件不参与布局，所以每次切回都确认可见
        try:
            drawer.show()
        except Exception:
            pass
        try:
            drawer.apply_theme()
        except Exception:
            pass
        # ⚠️ 先接上悬浮球抽屉正在聊的同一段对话再显示
        try:
            drawer.sync_shared_session()
        except Exception:
            pass
        try:
            drawer.focus_input()
        except Exception:
            pass
        # 刚建出来时视口宽度还是 0，等布局跑完这一拍再按真实宽度重排气泡
        QTimer.singleShot(0, self._sync_bubble_width)

    def _sync_bubble_width(self):
        drawer = self._drawer
        if drawer is not None:
            try:
                drawer.sync_bubble_width()
            except Exception:
                pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_bubble_width)

    def on_hidden(self):
        """离开本页：收掉正在跑的请求（切走了还在烧 token）"""
        drawer = self._drawer
        if drawer is None:
            return
        try:
            drawer.on_close()
        except Exception:
            pass

    def refresh_theme(self, force: bool = False):
        drawer = self._drawer
        if drawer is not None:
            try:
                drawer.apply_theme()
            except Exception:
                pass

    def refresh_texts(self):
        drawer = self._drawer
        if drawer is not None:
            try:
                drawer.refresh_texts()
            except Exception:
                pass

    # ---------- 对外接口 ----------
    def new_chat(self):
        return self.drawer.new_chat()

    def insert_mention(self, name: str, code: str = ""):
        """搜索页卡片的「@给AI」：切到本页并把 @名称(编码) 追加进输入框"""
        drawer = self.drawer
        try:
            drawer.insert_mention(name, code)
        except Exception:
            pass

    def send_message(self, text: str):
        """外部（比如详情页）直接发一条消息"""
        drawer = self.drawer
        try:
            drawer.input_edit.setPlainText(text)
            drawer.on_send_clicked()
        except Exception:
            pass
