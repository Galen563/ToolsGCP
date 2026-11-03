"""ToolsGCP 自制 UI 组件。

ToggleSwitch：滑动开关（来自仓库根目录 开关按钮.pyw，PyQt6 写法改成了 PyQt5）。
CardHighlightOverlay：让某张卡片闪两下，把注意力拽过去（动画结束自己销毁）。
"""

from PyQt5.QtCore import (QEvent, QPoint, QPropertyAnimation, QSize, Qt,
                          QVariantAnimation, pyqtProperty, pyqtSignal)
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen
from PyQt5.QtWidgets import QWidget

import math


class ToggleSwitch(QWidget):
    """滑动式开关（自制样式）

    width / height 尺寸；bg_color 关闭底色；circle_color 圆点色；
    active_color 打开底色；animation_speed 动画时长（毫秒）。
    """

    toggled = pyqtSignal(bool)

    def __init__(self, parent=None, width: int = 52, height: int = 28,
                 bg_color: str = "#CCCCCC", circle_color: str = "#FFFFFF",
                 active_color: str = "#4CAF50", animation_speed: int = 100,
                 checked: bool = False):
        super().__init__(parent)
        self.setFixedSize(QSize(width, height))
        self.setMinimumSize(QSize(width, height))

        self.bg_color = bg_color
        self.circle_color = circle_color
        self.active_color = active_color
        self.disabled_bg_color = "#BDBDBD"
        self.disabled_active_color = "#A5D6A7"

        self._checked = bool(checked)
        self._locked = False
        self._circle_position = self._on_position() if checked else self._off_position()

        self.animation = QPropertyAnimation(self, b"circle_position", self)
        self.animation.setDuration(animation_speed)

        self.setCursor(Qt.PointingHandCursor)

    # ---------- 尺寸 ----------
    def _off_position(self) -> int:
        return 3

    def _on_position(self) -> int:
        return self.width() - self.height() + 3

    def resizeEvent(self, event):
        """尺寸变了要把圆点摆回正确位置"""
        self._circle_position = self._on_position() if self._checked else self._off_position()
        super().resizeEvent(event)

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        enabled = self.isEnabled()
        bg_rect = self.rect().adjusted(2, 2, -2, -2)
        if self._checked:
            color = QColor(self.active_color if enabled else self.disabled_active_color)
        else:
            color = QColor(self.bg_color if enabled else self.disabled_bg_color)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(bg_rect, bg_rect.height() / 2, bg_rect.height() / 2)

        circle_size = self.height() - 8
        circle_x = self._circle_position
        circle_y = (self.height() - circle_size) // 2
        painter.setBrush(QBrush(QColor(self.circle_color)))
        painter.setPen(QPen(QColor("#AAAAAA"), 1))
        # PyQt5 的 drawEllipse 需要 QPoint 或整数坐标
        painter.drawEllipse(QPoint(circle_x + circle_size // 2, circle_y + circle_size // 2),
                            circle_size // 2, circle_size // 2)
        painter.end()

    # ---------- 交互 ----------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled() and not self._locked:
            self.toggle()

    def toggle(self):
        """切换一次（会带动画并发 toggled 信号）"""
        self._checked = not self._checked
        if self._checked:
            self.animation.setStartValue(self._off_position())
            self.animation.setEndValue(self._on_position())
        else:
            self.animation.setStartValue(self._on_position())
            self.animation.setEndValue(self._off_position())
        self.animation.start()
        self.toggled.emit(self._checked)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, emit: bool = False):
        """设置状态；emit=False（默认）时不发信号，适合刷新界面时回填"""
        checked = bool(checked)
        if checked == self._checked:
            return
        if emit:
            self.toggle()
            return
        self._checked = checked
        self.animation.stop()
        self._circle_position = self._on_position() if checked else self._off_position()
        self.update()

    def setLocked(self, locked: bool):
        """锁定后点不动（例如插件加载失败时）"""
        self._locked = bool(locked)
        self.setCursor(Qt.ArrowCursor if locked else Qt.PointingHandCursor)

    def isLocked(self) -> bool:
        return self._locked

    # ---------- 颜色（跟随主题） ----------
    def setColors(self, bg_color: str = None, active_color: str = None,
                  circle_color: str = None):
        if bg_color:
            self.bg_color = bg_color
        if active_color:
            self.active_color = active_color
        if circle_color:
            self.circle_color = circle_color
        self.update()

    def apply_theme(self, dark: bool = None, accent: str = None):
        """按当前深浅色主题重新上色（外面在切主题时调一次）"""
        if dark is None:
            try:
                from qfluentwidgets import isDarkTheme
                dark = bool(isDarkTheme())
            except Exception:
                dark = False
        if dark:
            self.bg_color = "#4A4A4A"            # 关闭底色
            self.disabled_bg_color = "#3A3A3A"
            self.circle_color = "#E8E8E8"
            self.active_color = accent or "#4CC46A"
            self.disabled_active_color = "#2F5B3A"
        else:
            self.bg_color = "#CCCCCC"            # 关闭底色
            self.disabled_bg_color = "#BDBDBD"
            self.circle_color = "#FFFFFF"
            self.active_color = accent or "#4CAF50"
            self.disabled_active_color = "#A5D6A7"
        self.update()

    # ---------- 动画属性 ----------
    @pyqtProperty(int)
    def circle_position(self):
        return self._circle_position

    @circle_position.setter
    def circle_position(self, pos):
        self._circle_position = pos
        self.update()


class CardHighlightOverlay(QWidget):
    """盖在某个控件上、闪两下的高亮层

    用独立覆盖层而不是改卡片样式表：setStyleSheet 会触发整棵控件树重新 polish，
    还会被主题样式表覆盖回去。动画结束就 deleteLater()，不要只 hide()。

    ⚠️ 覆盖层设了 WA_TransparentForMouseEvents，绝不能吃鼠标事件，
    否则动画期间卡片上的输入框/按钮会点不动。
    """

    def __init__(self, target: QWidget, color: str = "#5B8DEF"):
        super().__init__(target)
        self._target = target
        self._color = QColor(color)
        self._opacity = 0.0
        self._animation = None

        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._sync_geometry()
        # 父控件尺寸变化时跟着贴上去
        target.installEventFilter(self)

    # ---------- 几何 ----------
    def _sync_geometry(self):
        try:
            self.setGeometry(self._target.rect())
        except Exception:
            pass

    def eventFilter(self, obj, event):
        if obj is self._target and event.type() in (QEvent.Resize, QEvent.Show):
            self._sync_geometry()
        return super().eventFilter(obj, event)

    # ---------- 动画 ----------
    def start(self, blinks: int = 2, duration_ms: int = 300):
        """开始闪烁：默认"亮→灭→亮→灭"

        duration_ms 是单次明暗的时长，闪两下总共约 1.2 秒。
        """
        self.show()
        self.raise_()
        self._sync_geometry()

        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(duration_ms * blinks * 2)
        animation.setLoopCount(1)

        # 用余弦在 t=0..1 上映射出 0→1→0→1→0；线性映射在"亮起"瞬间会跳变，像闪灯
        import math

        def _update(value):
            value = float(value)
            self._opacity = 0.5 - 0.5 * math.cos(value * math.pi * 2 * blinks)
            self.update()

        animation.valueChanged.connect(_update)
        animation.finished.connect(self._on_finished)
        animation.start()
        self._animation = animation

    def _on_finished(self):
        try:
            self._target.removeEventFilter(self)
        except Exception:
            pass
        self.hide()
        self.deleteLater()

    def stop(self):
        """外部要立刻取消闪烁时调用"""
        if self._animation is not None:
            try:
                self._animation.stop()
            except Exception:
                pass
        try:
            self._target.removeEventFilter(self)
        except Exception:
            pass
        self.hide()

    @pyqtProperty(float)
    def highlight_opacity(self):
        return self._opacity

    @highlight_opacity.setter
    def highlight_opacity(self, value):
        self._opacity = float(value)
        self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        if self._opacity <= 0.001:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(1, 1, -2, -2)

        # 淡填充：让整张卡片"亮起来"，而不是只有一圈线
        fill = QColor(self._color)
        fill.setAlpha(int(38 * self._opacity))
        painter.setBrush(QBrush(fill))

        pen = QColor(self._color)
        pen.setAlpha(int(210 * self._opacity))
        painter.setPen(QPen(pen, 2))
        painter.drawRoundedRect(rect, 10, 10)
        painter.end()
