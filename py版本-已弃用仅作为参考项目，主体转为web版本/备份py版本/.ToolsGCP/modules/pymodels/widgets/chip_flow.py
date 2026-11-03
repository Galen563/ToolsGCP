"""自动换行的标签容器

⚠️ 不用 qfluentwidgets 的 FlowLayout：它的 takeAt() 返回控件而非 QLayoutItem（清理会抛
   "no attribute 'widget'"），且宽度未知时 sizeHint() 会把每个控件当成独占一行、高度算成
   真实值的十几倍。这里自己按可用宽度算列数，高度永远精确。
"""

from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QWidget


class ChipFlow(QWidget):
    """按宽度自动换行排列一组小控件（标签/胶囊按钮）"""

    def __init__(self, parent=None, spacing: int = 8, row_spacing: int = 6):
        super().__init__(parent)
        self.spacing = int(spacing)
        self.row_spacing = int(row_spacing)
        self._widgets: list = []
        self._rows = 0
        self._row_height = 0

    # ---------- 内容 ----------
    def set_widgets(self, widgets):
        for widget in self._widgets:
            if widget not in widgets and widget.parent() is self:
                widget.setParent(None)
        self._widgets = list(widgets)
        for widget in self._widgets:
            widget.setParent(self)
            widget.show()
        self._relayout()

    def clear(self, delete: bool = True):
        for widget in self._widgets:
            widget.setParent(None)
            widget.hide()
            if delete:
                widget.deleteLater()
        self._widgets = []
        self._rows = 0
        self.setFixedHeight(0)

    def widgets(self) -> list:
        return list(self._widgets)

    def rows(self) -> int:
        return self._rows

    # ---------- 尺寸 ----------
    def sizeHint(self) -> QSize:
        return QSize(self.width(), self.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.height())

    def heightForWidth(self, width: int) -> int:
        """给定宽度返回需要的高度（父布局算高度时会问）"""
        return self._compute(width)[2]

    def hasHeightForWidth(self) -> bool:
        return True

    # ---------- 排布 ----------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event):
        super().showEvent(event)
        self._relayout()

    def _compute(self, width: int):
        """返回 (每行放几个, 行高, 总高)"""
        if not self._widgets:
            return 0, 0, 0
        row_height = max(w.height() or w.sizeHint().height() for w in self._widgets)
        width = max(width, 1)

        rows = 1
        x = 0
        for widget in self._widgets:
            w = widget.width() or widget.sizeHint().width()
            if x > 0 and x + self.spacing + w > width:
                rows += 1
                x = w
            else:
                x += (self.spacing if x > 0 else 0) + w

        total = rows * row_height + max(0, rows - 1) * self.row_spacing
        return rows, row_height, total

    def _relayout(self):
        if not self._widgets:
            self._rows = 0
            self.setFixedHeight(0)
            return

        width = max(self.width(), 1)
        row_height = max(w.height() or w.sizeHint().height() for w in self._widgets)

        x = 0
        y = 0
        rows = 1
        for widget in self._widgets:
            w = widget.width() or widget.sizeHint().width()
            if x > 0 and x + self.spacing + w > width:
                rows += 1
                x = 0
                y += row_height + self.row_spacing
            if widget.x() != x or widget.y() != y:
                widget.move(x, y)
            x += w + self.spacing

        self._rows = rows
        self._row_height = row_height
        total = rows * row_height + max(0, rows - 1) * self.row_spacing
        if total != self.height():
            self.setFixedHeight(total)
