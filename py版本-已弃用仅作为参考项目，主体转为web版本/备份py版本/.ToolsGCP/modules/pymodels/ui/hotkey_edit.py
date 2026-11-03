"""快捷键录制输入框：点击后按下组合键即可录制，如 Ctrl+Q、F9。

Esc 取消录制，Backspace / Delete 清空。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import LineEdit

from ..utils.global_hotkey import normalize_sequence

# Qt 修饰键 → 文本
_QT_MODIFIERS = [
    (Qt.ControlModifier, "Ctrl"),
    (Qt.AltModifier, "Alt"),
    (Qt.ShiftModifier, "Shift"),
    (Qt.MetaModifier, "Win"),
]

# Qt 键值 → 名称（覆盖常用键）
_QT_KEYS = {}
for _c in range(ord("A"), ord("Z") + 1):
    _QT_KEYS[getattr(Qt, f"Key_{chr(_c)}")] = chr(_c)
for _d in range(ord("0"), ord("9") + 1):
    _QT_KEYS[getattr(Qt, f"Key_{chr(_d)}")] = chr(_d)
for _i in range(1, 25):
    _QT_KEYS[getattr(Qt, f"Key_F{_i}")] = f"F{_i}"
_QT_KEYS.update({
    Qt.Key_Space: "Space", Qt.Key_Tab: "Tab", Qt.Key_Return: "Enter",
    Qt.Key_Enter: "Enter", Qt.Key_Home: "Home", Qt.Key_End: "End",
    Qt.Key_PageUp: "PageUp", Qt.Key_PageDown: "PageDown",
    Qt.Key_Insert: "Insert", Qt.Key_Delete: "Delete",
    Qt.Key_Left: "Left", Qt.Key_Up: "Up", Qt.Key_Right: "Right", Qt.Key_Down: "Down",
})
if hasattr(Qt, "Key_CapsLock"):
    _QT_KEYS[Qt.Key_CapsLock] = "Caps"

_MODIFIER_KEYS = {
    Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta,
    Qt.Key_AltGr, Qt.Key_unknown,
}


class HotkeyEdit(LineEdit):
    """只读的快捷键录制框"""

    sequenceChanged = pyqtSignal(str)

    DEFAULT_PLACEHOLDER = "点击这里，然后按下组合键"

    def __init__(self, sequence: str = "", parent=None):
        super().__init__(parent)
        self._sequence = normalize_sequence(sequence) if sequence else ""
        self.setReadOnly(True)
        self.setPlaceholderText(self.DEFAULT_PLACEHOLDER)
        self.setFixedWidth(200)
        self._refresh_text()

    # ---------- 取值 ----------
    def sequence(self) -> str:
        return self._sequence

    def setSequence(self, sequence: str):
        new = normalize_sequence(sequence) if sequence else ""
        if new == self._sequence:
            return
        self._sequence = new
        self._refresh_text()
        self.sequenceChanged.emit(self._sequence)

    def clearSequence(self):
        self.setSequence("")

    # ---------- 录制 ----------
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        if key == Qt.Key_Escape:
            self.clearFocus()
            return

        if key in (Qt.Key_Backspace, Qt.Key_Delete):
            self.clearSequence()
            return

        # 只按了修饰键，继续等主键
        if key in _MODIFIER_KEYS:
            return

        name = _QT_KEYS.get(key)
        if name is None:
            # 尝试用 QKeySequence 兜底（标点等）
            text = QKeySequence(mods | key).toString()
            parts = [p for p in text.replace("Meta", "Win").split("+") if p]
            name = parts[-1] if parts else None
        if not name:
            return

        parts = [label for mask, label in _QT_MODIFIERS if mods & mask]
        parts.append(name)
        candidate = "+".join(parts)

        normalized = normalize_sequence(candidate)
        if normalized:
            self.setSequence(normalized)
            # ⚠️ 录完必须失焦，否则用户随后按下的键会被再录一遍
            self.clearFocus()
        else:
            QApplication.beep()

    # ---------- 显示 ----------
    def _refresh_text(self):
        self.setText(self._sequence)
        self.setToolTip(self._sequence or self.DEFAULT_PLACEHOLDER)
