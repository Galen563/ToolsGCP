"""勾选条

批量操作时用的那一行：左边是「全选」勾选框 + 勾选数量/总数，右边放操作按钮。

用法：
    bar = SelectionBar(parent)
    bar.toggled.connect(on_select_all)
    bar.set_counts(3, 40)
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CheckBox


class SelectionBar(QWidget):
    """全选 + 勾选数量/总数"""

    toggled = pyqtSignal(bool)

    def __init__(self, parent=None, select_all_text: str = "全选"):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.checkbox = CheckBox(select_all_text, self)
        self.checkbox.stateChanged.connect(self._on_state)
        layout.addWidget(self.checkbox)

        self.count_label = BodyLabel("0 / 0", self)
        layout.addWidget(self.count_label)
        layout.addStretch()

        self._total = 0
        self._selected = 0

    # ---------- 数据 ----------
    def set_counts(self, selected: int, total: int):
        self._selected, self._total = selected, total
        self.count_label.setText(f"{selected} / {total}")
        self.checkbox.blockSignals(True)
        if total > 0 and selected == total:
            self.checkbox.setChecked(True)
        elif selected == 0:
            self.checkbox.setChecked(False)
        else:
            # 部分勾选：CheckBox 没有三态，取消勾选即可
            self.checkbox.setChecked(False)
        self.checkbox.blockSignals(False)
        self.checkbox.setEnabled(total > 0)

    def is_all_checked(self) -> bool:
        return self._total > 0 and self._selected == self._total

    def _on_state(self, state):
        self.toggled.emit(bool(state))

    # ---------- 操作区 ----------
    def add_action(self, widget, stretch_before: bool = False):
        """把操作控件加到最后（右对齐）"""
        layout = self.layout()
        if stretch_before:
            layout.addStretch()
        layout.addWidget(widget)

    def add_leading(self, widget):
        """把控件插到「勾选数量」右边（stretch 之前）"""
        self.layout().insertWidget(2, widget)
