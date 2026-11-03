"""输入框的圆角右键菜单（全程序统一一套）。

做法：在 QApplication 上装一个事件过滤器，拦下 QLineEdit / QTextEdit /
QPlainTextEdit 的 ContextMenu 事件，换成 qfluentwidgets 的 RoundMenu。

⚠️ 快捷键提示要用 QKeySequence(...).toString()，不要写死 "Ctrl+C"（各平台不一样）。
⚠️ 可用状态按控件自己的能力问（hasSelectedText / isUndoAvailable / canPaste），不要自己猜。
"""

from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QLineEdit, QPlainTextEdit, QTextEdit

try:
    from qfluentwidgets import Action, RoundMenu
except Exception:                                   # pragma: no cover - 兜底
    Action = None
    RoundMenu = None

# 参与本菜单的输入控件类型
TEXT_INPUT_TYPES = (QLineEdit, QTextEdit, QPlainTextEdit)

# 兜底文案（拿不到语言管理器时用）
FALLBACK = {
    "menu_copy": "Copy",
    "menu_paste": "Paste",
    "menu_cut": "Cut",
    "menu_undo": "Undo",
}


class InputContextMenuFilter(QObject):
    """把文本输入控件的右键菜单换成圆角 Fluent 菜单

    ⚠️ 必须沿父链往上找真正的文本控件：QTextEdit / QPlainTextEdit 是
    QAbstractScrollArea，鼠标事件先落到内部 viewport 子控件上，
    只判 isinstance(obj, QTextEdit) 会漏掉。
    """

    def __init__(self, translate=None, parent=None):
        super().__init__(parent)
        # translate(key) -> str；拿不到就用兜底文案
        self._translate = translate

    def _t(self, key: str) -> str:
        """查一次界面语言（三种语言都支持）

        ⚠️ 每次弹菜单都现查，不要缓存：注入的 lambda 通常绑在当时的那个主窗口上，
        窗口重建后会一直停在旧语言。
        """
        try:
            from ..core.language_manager import get_current_manager
            manager = get_current_manager()
            if manager is not None:
                for module in ("settings", "plugin", "search"):
                    try:
                        text = manager.get_text(module, key)
                    except Exception:
                        text = key
                    if text and text != key:
                        return str(text)
        except Exception:
            pass
        if callable(self._translate):
            try:
                text = self._translate(key)
                if text and text != key:
                    return str(text)
            except Exception:
                pass
        return FALLBACK.get(key, key)

    # ---------- 事件 ----------
    @staticmethod
    def _resolve(widget):
        """把"事件落在谁身上"解析成真正的文本输入控件（找不到返回 None）"""
        node = widget
        for _ in range(3):
            if node is None:
                return None
            if isinstance(node, TEXT_INPUT_TYPES):
                return node
            try:
                node = node.parentWidget()
            except Exception:
                return None
        return None

    def eventFilter(self, obj, event):
        try:
            if event.type() != QEvent.ContextMenu:
                return False
            widget = self._resolve(obj)
            if widget is None:
                return False
            # 只读框只给"复制"
            readonly = bool(widget.isReadOnly()) if hasattr(widget, "isReadOnly") else False
            self._popup(widget, event.globalPos(), readonly)
            event.accept()
            return True
        except Exception as exc:
            # ⚠️ 必须记日志：菜单弹不出来时静默放行，表现就是"用户右键还是系统默认菜单"，
            #    原因无从排查
            try:
                from ..utils.logger import log
                log.err("输入框菜单", "input_menu", f"右键菜单弹不出来，退回默认菜单: {exc!r}")
            except Exception:
                pass
            return False

    # ---------- 组装 ----------
    @staticmethod
    def _state(widget) -> dict:
        """问控件自己：能不能复制 / 剪切 / 粘贴 / 撤回"""
        has_selection = False
        can_undo = False
        try:
            if isinstance(widget, QLineEdit):
                has_selection = bool(widget.hasSelectedText())
                can_undo = bool(widget.isUndoAvailable())
            else:
                has_selection = bool(widget.textCursor().hasSelection())
                can_undo = bool(widget.document().isUndoAvailable())
        except Exception:
            pass
        try:
            can_paste = bool(widget.canPaste())
        except Exception:
            can_paste = True
        return {"selection": has_selection, "undo": can_undo, "paste": can_paste}

    def _popup(self, widget, global_pos, readonly: bool):
        state = self._state(widget)
        if RoundMenu is None or Action is None:
            # qfluentwidgets 不在：抛异常让 eventFilter 退回系统默认菜单
            raise RuntimeError("no qfluentwidgets")

        menu = RoundMenu(parent=widget)

        def shortcut_text(key) -> str:
            """快捷键的显示文字（括号里那部分）

            ⚠️ QKeySequence.Copy 等是 StandardKey 枚举，没有 toString()；必须先用它
            造一个 QKeySequence 再取字符串，否则菜单构建抛异常、退回系统默认菜单。
            """
            try:
                return QKeySequence(key).toString(QKeySequence.NativeText)
            except Exception:
                return ""

        def add(key: str, standard, enabled: bool, handler):
            label = self._t(key)
            shortcut = shortcut_text(standard)
            text = f"{label} ({shortcut})" if shortcut else label
            action = Action(menu)
            try:
                action.setText(text)
                action.setEnabled(bool(enabled))
                action.triggered.connect(handler)
            except Exception:
                pass
            menu.addAction(action)

        # ⚠️ 顺序固定：复制 粘贴 剪切 撤回
        add("menu_copy", QKeySequence.Copy, state["selection"],
            lambda: widget.copy())
        add("menu_paste", QKeySequence.Paste, state["paste"] and not readonly,
            lambda: widget.paste())
        add("menu_cut", QKeySequence.Cut, state["selection"] and not readonly,
            lambda: widget.cut())
        add("menu_undo", QKeySequence.Undo, state["undo"] and not readonly,
            lambda: widget.undo())
        menu.exec(global_pos, ani=True)


_installed = False


def install_input_context_menus(app, translate=None) -> bool:
    """给整个程序装上"输入框圆角右键菜单"（重复调用无副作用）"""
    global _installed
    if _installed or app is None:
        return _installed
    try:
        flt = InputContextMenuFilter(translate, app)
        app.installEventFilter(flt)
        # 保住引用，防止被 GC
        app._input_context_menu_filter = flt
        _installed = True
        return True
    except Exception:
        return False


__all__ = ["install_input_context_menus", "InputContextMenuFilter"]
