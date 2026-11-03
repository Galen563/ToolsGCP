"""托盘右键菜单（TrayMenu）：QQ 风格的竖长方形圆角卡片。

⚠️ 圆角要三条同时成立：FramelessWindowHint + WA_TranslucentBackground +
样式表里的 border-radius，少一条就退化成直角方块。
图标必须用 themed_icon：FIF.XXX.icon() 在建菜单那刻就把颜色定死，切主题后图标会看不见。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMenu

from qfluentwidgets import FluentIcon as FIF, isDarkTheme

from ..widgets.app_card import themed_icon

# 圆角半径
MENU_RADIUS = 12
# 菜单左右内边距 / 行高
MENU_PADDING = 6
ITEM_HEIGHT = 30
ICON_SIZE = 14
# 图标、文字的左内边距（文字要躲开图标）
ICON_LEFT = 10
TEXT_LEFT = 30
# 文字右边留白
ITEM_RIGHT_PADDING = 10
# 菜单项最小宽度：跟着最长文案走就够，给太大时短文案右边会空一片
ITEM_MIN_WIDTH = 92


class TrayMenu(QMenu):
    """托盘右键菜单：QQ 风格的竖长方形圆角卡片

    顺序（上→下）：呼出主窗口 / 呼出搜索框 / 呼出AI / 分隔线 / 退出。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        # ⚠️ 窗口标志必须在第一次显示之前设好
        self.setWindowFlags(self.windowFlags()
                            | Qt.FramelessWindowHint
                            | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.refresh_theme()

    # ---------- 构建 ----------
    def add_item(self, icon, text, callback):
        """加一条带图标的菜单项，返回 QAction（图标由 refresh_theme 重新上色）"""
        action = self.addAction(text)
        action.setIcon(themed_icon(icon, ICON_SIZE))
        if callback is not None:
            action.triggered.connect(lambda _checked=False, cb=callback: cb())
        self._items.append((action, icon))
        return action

    def add_separator(self):
        return super().addSeparator()

    # ---------- 主题 ----------
    def refresh_theme(self, dark: bool = None):
        """按当前主题重刷样式表和图标（切主题后由主窗口调用）"""
        if dark is None:
            dark = bool(isDarkTheme())

        if dark:
            background = "rgba(43, 43, 43, 0.98)"
            border = "rgba(255, 255, 255, 0.10)"
            text = "#E8E8E8"
            hover = "rgba(255, 255, 255, 0.10)"
            separator = "rgba(255, 255, 255, 0.10)"
        else:
            background = "rgba(252, 252, 253, 0.98)"
            border = "rgba(0, 0, 0, 0.08)"
            text = "#1F2329"
            hover = "rgba(0, 0, 0, 0.06)"
            separator = "rgba(0, 0, 0, 0.08)"

        self.setStyleSheet(f"""
            QMenu {{
                background-color: {background};
                border: 1px solid {border};
                border-radius: {MENU_RADIUS}px;
                padding: {MENU_PADDING}px;
                color: {text};
            }}
            QMenu::item {{
                background: transparent;
                border-radius: 8px;
                padding: 0px {ITEM_RIGHT_PADDING}px 0px {TEXT_LEFT}px;
                margin: 0px 1px;
                min-width: {ITEM_MIN_WIDTH}px;
                height: {ITEM_HEIGHT}px;
                color: {text};
            }}
            QMenu::item:selected {{
                background-color: {hover};
                color: {text};
            }}
            QMenu::item:disabled {{
                color: rgba(150, 150, 150, 0.8);
            }}
            QMenu::icon {{
                left: {ICON_LEFT}px;
                width: {ICON_SIZE}px;
                height: {ICON_SIZE}px;
            }}
            QMenu::separator {{
                height: 1px;
                background: {separator};
                margin: 4px 8px;
            }}
        """)

        # 图标重新按主题取色
        for action, icon in self._items:
            try:
                action.setIcon(themed_icon(icon, ICON_SIZE, dark=dark))
            except Exception:
                pass


def make_tray_menu(language_manager, handlers: dict, parent=None) -> TrayMenu:
    """按固定顺序装好菜单

    handlers: {"home": cb, "search": cb, "ai": cb, "exit": cb}
    """
    def text(key, fallback):
        if language_manager is not None:
            try:
                value = language_manager.get_text("nav", key)
                if value and value != key:
                    return value
            except Exception:
                pass
        return fallback

    menu = TrayMenu(parent)
    menu.add_item(FIF.HOME, text("show_main_window", "Show Main Window"),
                  handlers.get("home"))
    menu.add_item(FIF.SEARCH, text("show_search_box", "Open Search Box"),
                  handlers.get("search"))
    menu.add_item(FIF.ROBOT, text("show_ai_search", "Open AI"),
                  handlers.get("ai"))
    menu.add_separator()
    menu.add_item(FIF.EMBED, text("exit", "Exit"), handlers.get("exit"))
    return menu
