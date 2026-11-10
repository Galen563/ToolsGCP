"""日志阅读窗口：双击日志列表里的一条，在独立窗口里打开（多标签、正文可选中复制）。

窗口标题 ToolsGCP-<日志文件名>；再次打开已开着的日志就切到那个标签。
全程序只有一个这样的窗口（open_log_window 里的单例），关掉之后再双击才重建。
"""

import os

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import (
    QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    FluentIcon as FIF, IndeterminateProgressRing, InfoBar, InfoBarPosition,
    PlainTextEdit, TabBar, TabCloseButtonDisplayMode, TransparentToolButton,
    isDarkTheme,
)

# 一次最多读多少字符（超大日志截断显示，避免卡死）
MAX_CHARS = 2_000_000

# 窗口标题前缀：ToolsGCP-<文件名>
WINDOW_TITLE_PREFIX = "ToolsGCP-"

# 刷新时进度环至少转这么久，否则一闪而过看不出来
MIN_SPIN_MS = 420


class LogViewerWindow(QWidget):
    """独立的日志阅读窗口"""

    def __init__(self, parent=None, language_manager=None):
        super().__init__(parent)
        self.setObjectName("logViewerWindow")
        self.setWindowTitle("ToolsGCP")
        self.resize(1000, 740)
        self.setMinimumSize(640, 440)

        # ⚠️ 独立窗口拿不到页面上的语言管理器，由 open_log_window 塞进来；
        #    没有就退回全局那个，否则窗口里的提示永远是中文
        self.lang = language_manager

        # ⚠️ TabBar 的 currentChanged / tabCloseRequested 发出来的是索引 int，
        #    不是 routeKey，所以自己维护一份"索引 → routeKey"顺序表
        self._order = []       # 标签顺序，元素是 routeKey
        self._paths = {}       # routeKey -> 文件路径
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.bar_host = QWidget(self)
        self.bar_host.setObjectName("logTabBarHost")
        bar_layout = QHBoxLayout(self.bar_host)
        bar_layout.setContentsMargins(10, 8, 12, 8)
        bar_layout.setSpacing(10)

        self.tab_bar = TabBar(self.bar_host)
        self.tab_bar.setCloseButtonDisplayMode(TabCloseButtonDisplayMode.ALWAYS)
        self.tab_bar.setMovable(True)
        # 不要那个按钮：日志只能从列表里双击打开
        self.tab_bar.setAddButtonVisible(False)
        self.tab_bar.currentChanged.connect(self._on_tab_index_changed)
        self.tab_bar.tabCloseRequested.connect(self.close_tab_at)
        bar_layout.addWidget(self.tab_bar, 1)

        # 刷新：点下去按钮变成不确定进度环
        self.reload_btn = TransparentToolButton(FIF.SYNC, self.bar_host)
        self.reload_btn.setFixedSize(32, 32)
        self.reload_btn.setToolTip(self._t("log_viewer_reload_tip", "Reload this log"))
        self.reload_btn.clicked.connect(self.reload_current)
        bar_layout.addWidget(self.reload_btn)

        self.progress_ring = IndeterminateProgressRing(self.bar_host)
        self.progress_ring.setFixedSize(24, 24)
        self.progress_ring.setStrokeWidth(3)
        self.progress_ring.hide()
        bar_layout.addWidget(self.progress_ring)

        layout.addWidget(self.bar_host)

        self.stack = QStackedWidget(self)
        self.stack.setObjectName("logViewerStack")
        layout.addWidget(self.stack, 1)

        self._busy_timer = QTimer(self)
        self._busy_timer.setSingleShot(True)
        self._busy_timer.timeout.connect(self._end_busy)

        self.refresh_theme()

    # ---------- 主题 ----------
    def refresh_theme(self):
        """整个窗口的配色跟着当前主题走"""
        dark = isDarkTheme()
        bg = "#1F1F1F" if dark else "#FAFAFA"
        bar_bg = "#2B2B2B" if dark else "#FFFFFF"
        border = "#3D3D3D" if dark else "#E0E0E0"

        self.setStyleSheet(f"""
            QWidget#logViewerWindow {{ background-color: {bg}; }}
            QWidget#logTabBarHost {{
                background-color: {bar_bg};
                border-bottom: 1px solid {border};
            }}
            QStackedWidget#logViewerStack {{ border: none; }}
        """)
        for editor in self._editors():
            editor.setStyleSheet(self._editor_style())

    @staticmethod
    def _editor_style() -> str:
        dark = isDarkTheme()
        color = "#E6E6E6" if dark else "#1F2329"
        bg = "#1B1B1B" if dark else "#FFFFFF"
        return (f"PlainTextEdit {{ background-color: {bg}; color: {color};"
                f" border: none; padding: 12px; }}")

    def _editors(self):
        return [self.stack.widget(i) for i in range(self.stack.count())]

    # ---------- 文案 ----------
    def _lang(self):
        """当前语言管理器（优先用构造时塞进来的那份，没有就用全局的）"""
        if self.lang is not None:
            return self.lang
        try:
            from ..core.language_manager import get_current_manager
            return get_current_manager()
        except Exception:
            return None

    def _t(self, key: str, fallback: str = "") -> str:
        """按当前语言取文案（查不到用 fallback，不会变成键名）"""
        manager = self._lang()
        if manager is not None:
            try:
                text = manager.get_text("log", key)
                if text and text != key:
                    return str(text)
            except Exception:
                pass
        return fallback or key

    def _title(self, kind: str = "info") -> str:
        """InfoBar 标题（成功 / 错误 / 提示 / 信息）"""
        from ..core.language_manager import get_toast_title
        return get_toast_title(kind, self._lang())

    # ---------- 打开日志 ----------
    def open_log(self, path: str, title: str = "") -> bool:
        """打开一个日志文件；已经开着就切过去。返回是否新建了标签"""
        path = os.path.abspath(str(path or ""))
        if not path or not os.path.isfile(path):
            self._warn(self._t("log_viewer_missing",
                               "Log file not found: {path}").format(path=path))
            return False

        for key, opened in self._paths.items():
            if os.path.abspath(opened) == path:
                index = self._order.index(key) if key in self._order else 0
                self.tab_bar.setCurrentIndex(index)
                self._refresh_title(key)
                return False

        name = title or os.path.basename(path)
        name = self._pretty_name(path)
        if not name:
            name = os.path.basename(path)
        key = f"log_{len(self._paths)}_{abs(hash(path)) % 100000}"
        self._paths[key] = path
        self._order.append(key)

        editor = PlainTextEdit(self.stack)
        editor.setReadOnly(True)
        editor.setLineWrapMode(PlainTextEdit.NoWrap)
        editor.setStyleSheet(self._editor_style())
        editor.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        editor.setPlainText(self._read(path))
        self.stack.addWidget(editor)

        self.tab_bar.addTab(key, name, FIF.DOCUMENT)
        self.tab_bar.setCurrentIndex(self._order.index(key))
        self._on_tab_changed(key)
        return True

    def _read(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read(MAX_CHARS + 1)
        except Exception as e:
            return self._t("log_viewer_read_failed",
                           "(Could not read: {error})").format(error=e)
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + "\n\n" + self._t(
                "log_viewer_truncated",
                "… (file is large; only the first {n} characters are shown)"
            ).format(n=MAX_CHARS)
        return text

    # ---------- 标签操作 ----------
    def _key_at(self, index: int) -> str:
        """索引 → routeKey"""
        if 0 <= index < len(self._order):
            return self._order[index]
        return ""

    def _on_tab_index_changed(self, index: int):
        self._on_tab_changed(self._key_at(index))

    def _on_tab_changed(self, key: str):
        editor = self._editor_of(key)
        if editor is not None:
            self.stack.setCurrentWidget(editor)
        self._refresh_title(key)

    def _editor_of(self, key: str):
        if key not in self._paths:
            return None
        index = list(self._paths.keys()).index(key)
        if 0 <= index < self.stack.count():
            return self.stack.widget(index)
        return None

    def close_tab_at(self, index: int):
        """关掉第 index 个标签（TabBar 信号传来的就是索引）"""
        self.close_tab(self._key_at(index))

    def close_tab(self, key: str):
        """关掉一个标签；全关完就关窗口"""
        if not key:
            return
        index = self._order.index(key) if key in self._order else -1
        editor = self._editor_of(key)
        if editor is not None:
            self.stack.removeWidget(editor)
            editor.deleteLater()
        try:
            if index >= 0:
                self.tab_bar.removeTab(index)
        except Exception:
            pass
        self._paths.pop(key, None)
        if key in self._order:
            self._order.remove(key)

        if not self._paths:
            self.close()
            return
        self._on_tab_changed(self._key_at(self.tab_bar.currentIndex()))

    def _refresh_title(self, key: str):
        """窗口标题：ToolsGCP-<日志文件名>

        文件名自带 "ToolsGCP-"，先去掉再拼前缀，否则会出现两遍。
        """
        path = self._paths.get(key, "")
        name = self._pretty_name(path)
        self.setWindowTitle(WINDOW_TITLE_PREFIX + (name or ""))

    @staticmethod
    def _pretty_name(path: str) -> str:
        """从日志文件路径得到干净的显示名

        去掉文件名里任何位置的 ToolsGCP- / -ToolsGCP，避免和窗口标题前缀重复。
        """
        name = os.path.basename(str(path or ""))
        if not name:
            return ""
        for token in ("ToolsGCP-", "-ToolsGCP", "ToolsGCP_", "_ToolsGCP"):
            name = name.replace(token, "")
        name = name.lstrip("-_ ")
        return name or os.path.basename(str(path or ""))

    # ---------- 刷新（带不确定进度环）----------
    def reload_current(self):
        """重新读一遍当前标签的文件（日志还在写的时候很有用）"""
        if self._busy:
            return
        key = self._key_at(self.tab_bar.currentIndex())
        path = self._paths.get(key)
        editor = self._editor_of(key)
        if not path or editor is None:
            return

        self._begin_busy()
        QTimer.singleShot(30, lambda: self._do_reload(key, path, editor))

    def _begin_busy(self):
        self._busy = True
        self.reload_btn.hide()
        self.progress_ring.show()
        self.progress_ring.start()
        self._busy_timer.start(MIN_SPIN_MS)

    def _end_busy(self):
        self._busy = False
        self.progress_ring.stop()
        self.progress_ring.hide()
        self.reload_btn.show()

    def _do_reload(self, key, path, editor):
        pos = editor.verticalScrollBar().value()
        text = self._read(path)
        editor.setPlainText(text)
        editor.verticalScrollBar().setValue(pos)
        self._refresh_title(key)
        message = self._t("log_viewer_refreshed",
                          "Reloaded: {name}").format(name=os.path.basename(path))
        if self._busy_timer.isActive():
            QTimer.singleShot(self._busy_timer.remainingTime(),
                              lambda: self._info(message))
        else:
            self._info(message)

    # ---------- 提示 ----------
    def _warn(self, message: str):
        InfoBar.warning(title=self._title("warning"), content=message, orient=Qt.Horizontal,
                        isClosable=True, position=InfoBarPosition.TOP,
                        duration=3000, parent=self)

    def _info(self, message: str):
        InfoBar.success(title=self._title("success"), content=message, orient=Qt.Horizontal,
                        isClosable=True, position=InfoBarPosition.TOP,
                        duration=2000, parent=self)

    # ---------- 关闭 ----------
    def closeEvent(self, event):
        global _window
        if _window is self:
            _window = None
        super().closeEvent(event)


# 单例入口

_window: LogViewerWindow = None


def open_log_window(path: str, title: str = "",
                    language_manager=None) -> LogViewerWindow:
    """打开（或复用）日志阅读窗口（全程序共用一个，关掉后才新建）

    language_manager：独立窗口自己拿不到，由调用方（log_interface）传进来，
    标题 / 提示才会跟着界面语言走。
    """
    global _window
    if _window is None:
        _window = LogViewerWindow(language_manager=language_manager)
    elif language_manager is not None:
        _window.lang = language_manager
    _window.refresh_theme()      # 主程序切过主题的话，这里跟着变
    _window.open_log(path, title)
    _window.show()
    _window.setWindowState(_window.windowState() & ~Qt.WindowMinimized
                           | Qt.WindowActive)
    _window.raise_()
    _window.activateWindow()
    return _window


def refresh_open_window():
    """主程序切主题时调用：让已经打开的日志窗口跟着换色"""
    if _window is not None:
        _window.refresh_theme()
