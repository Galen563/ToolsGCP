"""筛选面板

「更多筛选」用的可折叠面板：一行一组条件，每组是一排可点的胶囊按钮，**组内多选**（组内
"或"，组间"与"）。「全部」是特殊项：点它清空这一组，点其它项自动取消「全部」。

排版用自带的 ChipFlow（不用 FlowLayout），高度算得准，展开动画不会和卡片列表错位。
"""

from PyQt5.QtCore import (QEasingCurve, QPropertyAnimation, QAbstractAnimation,
                          QRectF, QTimer, Qt, pyqtSignal)
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, isDarkTheme, themeColor

from .chip_flow import ChipFlow

ALL_KEY = ""      # 「全部」用空字符串表示

_QWIDGETSIZE_MAX = 16777215

# 胶囊的三种配色（按 深色/浅色 × 选中/未选中 × 悬停 缓存，避免每帧重新配颜色）
_CHIP_COLOR_CACHE = {}


def chip_colors(checked: bool, hover: bool) -> dict:
    """当前主题下胶囊的 (底/边/字) 颜色

    ⚠️ 选中态文字色跟 qfluentwidgets 对齐：浅色主题=强调色底 + **白字**，深色主题=
       提亮后的强调色底 + **黑字**。按"底色亮度猜"字色会算错（亮青底配白字看不清）。
    """
    dark = isDarkTheme()
    key = (dark, bool(checked), bool(hover))
    cached = _CHIP_COLOR_CACHE.get(key)
    if cached is not None:
        return cached
    if checked:
        accent = QColor(themeColor())
        background = accent.lighter(115) if hover else QColor(accent)
        border = background
        # 深色主题黑字 / 浅色主题白字（和库里选中态一致）
        text = QColor(0, 0, 0) if dark else QColor(255, 255, 255)
    else:
        base = QColor(255, 255, 255) if dark else QColor(0, 0, 0)
        alpha = 26 if hover else 14
        background = QColor(base)
        background.setAlpha(alpha)
        border = QColor(base)
        border.setAlpha(34)
        text = QColor(224, 224, 224) if dark else QColor(64, 64, 64)
    colors = {"bg": background, "border": border, "text": text}
    _CHIP_COLOR_CACHE[key] = colors
    return colors


class FilterChip(QLabel):
    """筛选面板里的一颗胶囊（自己画，不用 qfluentwidgets 的 PillPushButton）

    ⚠️ PillPushButton 是"带样式表的 QPushButton"，每颗都要跑一遍 QStyleSheetStyle 且首次
       显示还要 polish；面板里上百颗，实测首次展开最慢一帧 102ms（Python 侧只占 5.8ms）。
    """

    clicked = pyqtSignal()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._checked = False
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(26)
        self.setAlignment(Qt.AlignCenter)
        # 宽度按文字算好并固定：勾选状态变化时不改尺寸，
        # 否则点一下整排会重排、位置"跳"到别处
        fm = self.fontMetrics()
        self.setFixedWidth(fm.horizontalAdvance(text) + 26)

    # ---------- 状态 ----------
    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self.update()

    # ---------- 交互 ----------
    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        event.accept()          # 吃掉按下，别冒泡到卡片/面板

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        event.accept()

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        colors = chip_colors(self._checked, self._hover)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(colors["border"]))
        painter.setBrush(colors["bg"])
        painter.drawRoundedRect(rect, rect.height() / 2.0, rect.height() / 2.0)
        painter.setPen(colors["text"])
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())
        painter.end()


def reset_chip_color_cache():
    """主题/配色变了要清一下这个缓存（颜色是按主题算的）"""
    _CHIP_COLOR_CACHE.clear()


class FilterChipRow(QWidget):
    """一行筛选条件：标题 + 一排可多选的胶囊"""

    changed = pyqtSignal()

    def __init__(self, title: str, options=None, parent=None):
        super().__init__(parent)
        self._options = []
        self._buttons = {}
        self._selected = set()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        self.title_label = CaptionLabel(title, self)
        self.title_label.setFixedWidth(52)
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        outer.addWidget(self.title_label, 0, Qt.AlignTop)

        self.chips = ChipFlow(self, spacing=8, row_spacing=6)
        outer.addWidget(self.chips, 1)

        if options:
            self.set_options(options)

    # ---------- 选项 ----------
    def set_options(self, options):
        """options: [(key, label), ...]，第一项一般是 ("", "全部")"""
        self._buttons = {}
        self._options = list(options)
        self._selected = set()

        widgets = []
        for key, label in self._options:
            button = FilterChip(label, self.chips)
            button.clicked.connect(lambda _c=False, k=key: self._toggle(k))
            widgets.append(button)
            self._buttons[key] = button

        self.chips.set_widgets(widgets)
        self._sync_buttons()

    # ---------- 选择 ----------
    def _toggle(self, key):
        if key == ALL_KEY:
            self._selected.clear()
        elif key in self._selected:
            self._selected.discard(key)
        else:
            self._selected.add(key)
        self._sync_buttons()
        self.changed.emit()

    def _sync_buttons(self):
        for key, button in self._buttons.items():
            if key == ALL_KEY:
                button.setChecked(not self._selected)
            else:
                button.setChecked(key in self._selected)

    # ---------- 取值 ----------
    def value(self) -> list:
        return [k for k in self._selected]

    def reset(self):
        self._selected.clear()
        self._sync_buttons()
        self.changed.emit()


class FilterPanel(QWidget):
    """多行筛选条件组成的面板（带展开/收起动画）

    ⚠️ 动画只压外层面板的 maximumHeight，里层 `_content`（提示 + 各行）的高度**锁死**成
       展开后的真实高度：直接压 self 的话 Qt 会把里面的行一起压扁/互相叠。
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = {}
        self._expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 里层：整块内容的容器（高度由 set_expanded / resizeEvent 锁死）
        self._content = QWidget(self)
        self._content.setObjectName("filterPanelContent")
        outer.addWidget(self._content)

        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(10)

        self.hint = CaptionLabel("", self._content)
        self.hint.setWordWrap(True)
        self._layout.addWidget(self.hint)
        self._layout.addSpacing(2)

        self._rows_host = QVBoxLayout()
        self._rows_host.setSpacing(8)
        self._layout.addLayout(self._rows_host)

        self._anim = QPropertyAnimation(self, b"maximumHeight", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)

        self.setMaximumHeight(0)
        self.hide()
        self._apply_style()

    def _apply_style(self):
        """面板底色和页面区分开

        ⚠️ 只给面板自己和内容容器上色，**不要**写 `QWidget { … }` 通配规则：那会让面板里
           上百个子控件都重新解析一遍样式表（实测首次展开最慢一帧 138ms 就是这次 polish）。
        """
        from qfluentwidgets import isDarkTheme
        bg = "rgba(255, 255, 255, 0.045)" if isDarkTheme() else "rgba(0, 0, 0, 0.035)"
        self.setStyleSheet(f"""
            FilterPanel {{ background-color: {bg}; border-radius: 8px; }}
            QWidget#filterPanelContent {{ background-color: transparent; }}
        """)

    def refresh_theme(self):
        self._apply_style()
        # 胶囊颜色是按主题算的（见 chip_colors），换主题/配色要清缓存重画
        reset_chip_color_cache()
        for row in self.rows.values():
            for chip in row.chips.widgets():
                chip.update()
        self.update()

    # ---------- 高度 ----------
    def natural_height(self) -> int:
        """精确算出展开后应该有真实多高

        ⚠️ 不能用 layout().sizeHint()：宽度没确定时它会把 ChipFlow 的高度算成十几倍。
        ⚠️ 提示语那一行也不能用 `self.hint.height()`：布局会把多余空间分给这个可换行标签
           （实测被撑到 304px，而它只需要 34px），得按**当前宽度**重新问它。
        """
        margins = self._layout.contentsMargins()
        total = margins.top() + margins.bottom()
        total += self._hint_height() + 2
        total += self._layout.spacing() * 2

        for index, row in enumerate(self.rows.values()):
            total += max(row.chips.height(), row.chips.sizeHint().height(), 26)
            if index:
                total += self._rows_host.spacing()
        return max(total, 48)

    def _hint_height(self) -> int:
        """提示语在**当前宽度**下需要多高

        ⚠️ 不能用 `QLabel.heightForWidth()`：它会把结果夹到 minimumSize().height()，而这个
           标签被 setFixedHeight() 过，于是"第一次锁成多高就永远多高"。所以逐字累加算行数。
        """
        fm = self.hint.fontMetrics()
        line_h = max(12, fm.height())
        text = str(self.hint.text() or "")
        if not text:
            return line_h + 2
        margins = self._layout.contentsMargins()
        width = self.width() or self._content.width()
        width = max(40, width - margins.left() - margins.right())
        lines, current = 1, 0
        for ch in text:
            advance = fm.horizontalAdvance(ch)
            if current and current + advance > width:
                lines += 1
                current = advance
            else:
                current += advance
        return lines * line_h + 2

    def _lock_hint_height(self):
        """把提示语的高度按当前宽度**定死**（否则多余空间会被这个可换行标签吃掉）"""
        try:
            self.hint.setFixedHeight(self._hint_height())
        except Exception:
            pass

    # ---------- 展开 / 收起 ----------
    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, animate: bool = True):
        expanded = bool(expanded)
        if expanded == self._expanded and self.isVisible():
            return
        self._expanded = expanded
        self._anim.stop()

        if not animate:
            self.setVisible(expanded)
            self.setMaximumHeight(_QWIDGETSIZE_MAX if expanded else 0)
            if expanded:
                self._content.setFixedHeight(self.natural_height())
            return

        if expanded:
            self.setVisible(True)
            self.setMaximumHeight(0)
            # 先按真实宽度重排一次，保证 natural_height 拿到的是最终高度
            self._relayout_rows()
            height = self.natural_height()
            # ⚠️ 把里层高度**锁死**：动画压的是外层的 maximumHeight，
            #    里层不受影响，露出来的过程就是"整块揭开"而不是"把行压扁"。
            self._content.setFixedHeight(height)
            self._anim.setStartValue(0)
            self._anim.setEndValue(height)
            # 布局真正落定之后再校一次（首次展开时宽度可能还没算好）
            QTimer.singleShot(0, self._reflow_after_layout)
        else:
            self._anim.setStartValue(max(self.height(), 1))
            self._anim.setEndValue(0)
        self._anim.start()

    def _relayout_rows(self):
        """让每行的 ChipFlow 按当前宽度重排（高度才有意义）"""
        self._lock_hint_height()
        for row in self.rows.values():
            row.chips._relayout()

    def _reflow_after_layout(self):
        """布局落定后校正一次里层高度（首次展开时宽度可能还没算好）"""
        if not self._expanded:
            return
        self._relayout_rows()
        self._content.setFixedHeight(self.natural_height())
        if self._anim.state() != QAbstractAnimation.Running:
            self.setMaximumHeight(_QWIDGETSIZE_MAX)

    def _on_anim_finished(self):
        if self._expanded:
            self.setMaximumHeight(_QWIDGETSIZE_MAX)
            self._content.setFixedHeight(self.natural_height())
        else:
            self.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # ⚠️ 展开/收起动画期间**不要**重排：动画压的是高度，宽度一帧都没变，
        #    而行重排（7 条 ChipFlow + 重算自然高度）是这里最贵的一步，
        #    原来它每一帧都跑一遍。
        if self._anim.state() == QAbstractAnimation.Running:
            return
        # 宽度变了 → 重新算每行高度（换行数可能变了）
        self._relayout_rows()
        if self._expanded:
            self._content.setFixedHeight(self.natural_height())
            self.setMaximumHeight(_QWIDGETSIZE_MAX)

    def toggle(self):
        self.set_expanded(not self._expanded)

    # ---------- 行 ----------
    def set_title(self, text: str):
        self.hint.setText(text)

    def add_row(self, key: str, title: str, options):
        row = FilterChipRow(title, options, self._content)
        row.changed.connect(self.changed.emit)
        self.rows[key] = row
        self._rows_host.addWidget(row)
        return row

    def set_row_options(self, key: str, options):
        row = self.rows.get(key)
        if row is not None:
            row.set_options(options)

    # ---------- 取值 ----------
    def values(self) -> dict:
        return {key: row.value() for key, row in self.rows.items()}

    def active_count(self) -> int:
        return len([v for v in self.values().values() if v])

    def reset(self):
        for row in self.rows.values():
            row._selected.clear()
            row._sync_buttons()
        self.changed.emit()
