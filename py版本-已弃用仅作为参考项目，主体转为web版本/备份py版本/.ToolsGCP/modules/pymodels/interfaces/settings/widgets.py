"""设置页的行 / 卡片 / 页头组件（TipIcon / SettingRow / SettingCard / SettingPage）。

用法：card.add_row(SettingRow("主题", combo, desc="跟随系统"))，再加进 SettingPage。

⚠️ 尺寸和颜色一律从 .theme 取（tokens / SIZES），不要在这里写新的颜色字面量。
"""

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy,
                             QVBoxLayout, QWidget)
from qfluentwidgets import (FluentIcon as FIF, IconWidget, isDarkTheme,
                            themeColor, BodyLabel, MessageBoxBase,
                            PushButton, SubtitleLabel, ToolTipFilter,
                            ToolTipPosition)

from .theme import CONTROL_WIDTH, SIZES, tokens


class WheelStepFilter(QObject):
    """把"滚轮滚一格"翻译成恰好一步（+1 / -1）。

    ⚠️ QAbstractSlider 默认一格走 singleStep × 系统行数（Windows 通常是 3），所以必须
    接管并吃掉滚轮事件，否则数值会跳、事件还会冒泡去滚整页设置。
    """

    def __init__(self, step_callback, parent=None):
        super().__init__(parent)
        self._step = step_callback

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta == 0:
                return False
            try:
                self._step(1 if delta > 0 else -1)
            except Exception:
                return False
            event.accept()
            return True
        return False


def install_wheel_step(widget, step_callback):
    """给一个控件装上"滚轮一格 = 一步"；step_callback 收到 +1（上滚）/ -1（下滚）。"""
    if widget is None or not callable(step_callback):
        return None
    flt = WheelStepFilter(step_callback, widget)
    widget.installEventFilter(flt)
    # 保住引用便于排查（父子关系已经保证了生命周期）
    widget._wheel_step_filter = flt
    return flt



class TipIcon(QLabel):
    """设置项右边那个小小的 ⓘ 提示图标（矢量 INFO，不用字符 ⓘ：缺字形、也对不齐）。"""

    ICON_SIZE = 16

    def __init__(self, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
        self.setCursor(Qt.WhatsThisCursor)
        self._icon = IconWidget(self)
        self._icon.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._icon)
        if tooltip:
            self.setToolTip(tooltip)
        self.apply_theme()

    def apply_theme(self, dark: bool = None):
        if dark is None:
            dark = bool(isDarkTheme())
        color = tokens(dark)["text_secondary"]
        self._icon.setIcon(FIF.INFO.icon(color=color))


class SettingRow(QWidget):
    """一行设置项：左标题(+副说明/ⓘ) + 右控件（统一宽度、右对齐）。

    control=None 表示这行只有文字；control_width 传 None（开关类）时用控件原始宽度。
    """

    def __init__(self, title: str, control: QWidget = None, desc: str = "",
                 hint: str = "",
                 tip: str = "", control_width: int = CONTROL_WIDTH,
                 parent=None):
        super().__init__(parent)
        self.title_text = str(title or "")
        self.control = control
        self._dark = bool(isDarkTheme())

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        # ---- 左：标题 +（可选）ⓘ + 副说明 ----
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self.title_label = QLabel(self.title_text, self)
        self.title_label.setProperty("role", "rowTitle")
        title_row.addWidget(self.title_label)
        if tip:
            title_row.addWidget(TipIcon(tip, self))
        # hint 走鼠标悬浮 tooltip（和 TipIcon 同一套机制，只是触发区域是整个标题）
        if hint:
            self.title_label.setToolTip(str(hint))
            self.title_label.installEventFilter(
                ToolTipFilter(self.title_label, 300, ToolTipPosition.TOP))
        title_row.addStretch(1)
        left.addLayout(title_row)

        self.desc_label = None
        if desc:
            self.desc_label = QLabel(str(desc), self)
            self.desc_label.setProperty("role", "rowDesc")
            self.desc_label.setWordWrap(False)
            left.addWidget(self.desc_label)
        # 让左半边吃掉行内的多余宽度（标题靠左、控件靠右）
        row.addLayout(left, 1)

        # ---- 右：控件（统一宽度 + 垂直居中）----
        if control is not None:
            control.setParent(self)
            if control_width:
                control.setFixedWidth(int(control_width))
            row.addWidget(control, 0, Qt.AlignVCenter)

        self.setMinimumHeight(SIZES["row_height_with_desc"] if desc
                              else SIZES["row_height"])
        self.apply_theme()

    def apply_theme(self, dark: bool = None):
        """刷新这一行的颜色（主题切换时由卡片统一调）。

        ⚠️ 这里故意什么都不做：配色改由页面级样式表的属性选择器负责，逐行 setStyleSheet
        会让几百个控件各带一份样式表，布局和重绘明显变慢。
        """
        if dark is not None:
            self._dark = bool(dark)

    # ---------- 外部常用操作 ----------
    def set_control_enabled(self, enabled: bool):
        """联动置灰：控件和文字一起变灰/恢复。

        ⚠️ 文字配色同样走属性选择器（QLabel[disabledText="true"]），不塞内联样式表。
        """
        enabled = bool(enabled)
        if self.control is not None:
            self.control.setEnabled(enabled)
        for label in (self.title_label, self.desc_label):
            if label is None:
                continue
            if bool(label.property("disabledText")) == (not enabled):
                continue
            label.setProperty("disabledText", not enabled)
            # 动态属性变了必须重新 polish，样式表里的属性选择器才会重新生效
            label.style().unpolish(label)
            label.style().polish(label)


class SettingCard(QWidget):
    """一张设置卡片：若干 SettingRow +（可选）行间分隔线。

    ⚠️ 分隔线自己画：最后一行不该有，逐行带 border 的话每张卡片都要特判。divider=False 即不画。
    """

    def __init__(self, parent=None, divider: bool = True):
        super().__init__(parent)
        self._show_divider = bool(divider)
        from qfluentwidgets import SimpleCardWidget
        self._card = SimpleCardWidget(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._card)

        self.box = QVBoxLayout(self._card)
        pad = SIZES["card_padding"]
        self.box.setContentsMargins(pad, pad - 4, pad, pad - 4)
        self.box.setSpacing(0)
        self.rows = []

    def add_row(self, row: SettingRow) -> SettingRow:
        if self.rows and self._show_divider:
            line = QFrame(self._card)
            line.setFixedHeight(1)
            line.setProperty("role", "rowDivider")
            line.setStyleSheet(
                f"background: {tokens(isDarkTheme())['divider']};")
            self.box.addWidget(line)
            self._dividers = getattr(self, "_dividers", [])
            self._dividers.append(line)
        self.box.addWidget(row)
        self.rows.append(row)
        row.apply_theme()
        return row

    def add_widget(self, widget: QWidget) -> QWidget:
        """塞一个不是 SettingRow 的东西（比如一行小标题、一个按钮排）"""
        self.box.addWidget(widget)
        return widget

    def apply_theme(self, dark: bool = None):
        if dark is None:
            dark = bool(isDarkTheme())
        for row in self.rows:
            row.apply_theme(dark)
        for line in getattr(self, "_dividers", []):
            line.setStyleSheet(f"background: {tokens(dark)['divider']};")


class SettingPage(QWidget):
    """一个板块页：页头（板块名 + 右侧动作）+ 若干卡片。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title_text = str(title or "")
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(SIZES["card_gap"])

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        self.title_label = QLabel(self.title_text, self)
        self.title_label.setProperty("role", "sectionTitle")
        head.addWidget(self.title_label)
        head.addStretch(1)
        self.head_actions = head
        box.addLayout(head)

        self.cards = []
        self._box = box
        # ⚠️ 这里不能再 addStretch：弹性由外层滚动区宿主负责，否则本页 sizeHint 变高，
        #    卡片拿到多余纵向空间会把每一行撑开（行距忽大忽小、分隔线忽隐忽现）

    def add_card(self, card: QWidget) -> QWidget:
        """加一张卡片。

        ⚠️ 兼容旧的 SimpleCardWidget 卡片：它们没有 apply_theme / searchable_rows，下面都做了能力判断。
        """
        # 没有弹簧了（见 __init__），卡片高度由自身 sizeHint 决定
        self._box.addWidget(card)
        self.cards.append(card)
        return card

    def add_gap(self, height: int = SIZES["card_gap"]):
        spacer = QWidget(self)
        spacer.setFixedHeight(int(height))
        self._box.addWidget(spacer)

    def add_action(self, widget: QWidget):
        """往页头右边塞一个动作控件（例如「恢复默认」按钮）"""
        self.head_actions.addWidget(widget)
        return widget

    def apply_theme(self, dark: bool = None):
        if dark is None:
            dark = bool(isDarkTheme())
        c = tokens(dark)
        self.title_label.setStyleSheet(
            f"color: {c['text']}; font-size: 20px; font-weight: 600;"
            " background: transparent;")
        for card in self.cards:
            apply = getattr(card, "apply_theme", None)
            if callable(apply):
                try:
                    apply(dark)
                except Exception:
                    pass

    # ---------- 搜索用 ----------
    def searchable_rows(self) -> list:
        """这一页所有可搜索的行 → [(行, "标题 副说明"), ...]。

        旧卡片没有 rows，退化成"整张卡片 + 卡片里的文字"。
        """
        out = []
        for card in self.cards:
            rows = getattr(card, "rows", None)
            if rows:
                for row in rows:
                    parts = [getattr(row, "title_text", "")]
                    if getattr(row, "desc_label", None) is not None:
                        parts.append(row.desc_label.text())
                    out.append((row, " ".join(p for p in parts if p)))
                continue
            texts = [w.text() for w in card.findChildren(QLabel) if w.text()]
            if texts:
                out.append((card, " ".join(texts)))
        return out


class UnsavedChangesDialog(MessageBoxBase):
    """「还有修改没保存」的三选一弹窗：保存并继续 / 放弃修改 / 留在这里。

    用法：dialog = UnsavedChangesDialog(parent, title, body)；看 dialog.choice（CANCEL/SAVE/DISCARD）。
    """

    CANCEL = 0      # 留在当前界面（默认：直接关掉窗口就是这个结果）
    SAVE = 1        # 保存并继续
    DISCARD = 2     # 放弃修改并继续

    def __init__(self, parent=None, title: str = "", body: str = "",
                 save_text: str = "保存并继续", discard_text: str = "放弃修改",
                 cancel_text: str = "留在当前界面"):
        super().__init__(parent)
        self.choice = self.CANCEL

        self.titleLabel = SubtitleLabel(str(title or ""), self)
        self.viewLayout.addWidget(self.titleLabel)

        text = BodyLabel(str(body or ""), self)
        text.setWordWrap(True)
        self.viewLayout.addWidget(text)

        self.yesButton.setText(save_text)
        self.cancelButton.setText(cancel_text)
        self.discardButton = PushButton(discard_text, self.buttonGroup)
        # 插到最左边，"放弃"这种破坏性动作不该是离鼠标最近的那个
        self.buttonLayout.insertWidget(0, self.discardButton, 1, Qt.AlignVCenter)
        self.discardButton.clicked.connect(self._on_discard)

        self.widget.setMinimumWidth(460)

    def _on_discard(self):
        self.choice = self.DISCARD
        self.accept()

    def validate(self) -> bool:
        """点「保存并继续」：先记下意图，真正存不存得下由调用方再判定。

        ⚠️ 允许先关掉对话框，否则用户填了非法接口地址会卡在这个弹窗里出不去。
        """
        self.choice = self.SAVE
        return True


__all__ = ["TipIcon", "SettingRow", "SettingCard", "SettingPage",
           "UnsavedChangesDialog", "WheelStepFilter", "install_wheel_step"]
