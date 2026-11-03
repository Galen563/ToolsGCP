"""平滑（惯性）滚动支持
给 QScrollArea 加上滚动惯性：滚轮停止后画面带着动量继续滑动、逐渐减速停下。
用法：install_smooth_scroll(self.scroll_area)
"""

from PyQt5.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt
from PyQt5.QtWidgets import QScrollArea


class SmoothScrollFilter(QObject):
    """滚轮 → 平滑减速滚动
    滚轮事件到达滚动区域就拦截下来自己做动画：曲线 OutCubic（起步快、收尾慢）；连续滚动
    时目标位置累加，停手后仍会滑行一段（动量）；按住 Ctrl/Shift/Alt 或滚到边界时不拦截。
    """

    # 一格滚轮（120 单位）对应的滚动距离
    STEP_PX = 110.0
    # 动画时长随距离变化，距离越远滑得越久
    # ⚠️ 时长别调大：滚动条动的每一帧都要重画整屏卡片，惯性拖得越长越卡
    MIN_DURATION_MS = 150
    MAX_DURATION_MS = 380

    def __init__(self, area: QScrollArea):
        super().__init__(area)
        self._area = area
        self._target = None

        bar = area.verticalScrollBar()
        self._anim = QPropertyAnimation(bar, b"value", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        # 动画自然结束后清空目标值，避免下次滚动从过期的目标位置起算
        self._anim.finished.connect(self._reset)

    # ---------- 事件过滤 ----------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            return self._on_wheel(event)
        return False

    def _on_wheel(self, event):
        if event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier):
            return False

        # 触摸板/高精度设备给的是像素增量，普通滚轮给的是角度增量
        pixels = event.pixelDelta().y()
        delta = event.angleDelta().y()
        if not pixels and not delta:
            return False

        area = self._area
        bar = area.verticalScrollBar()
        if bar.maximum() <= bar.minimum():
            return False

        # 已经滚到边界：放行，交给外层（可能是嵌套的滚动区域）处理
        if (delta > 0 and bar.value() <= bar.minimum()) or \
           (delta < 0 and bar.value() >= bar.maximum()):
            self._reset()
            return False

        step = float(pixels) if pixels else (delta / 120.0) * self.STEP_PX

        base = self._target if self._target is not None else bar.value()
        target = max(bar.minimum(), min(bar.maximum(), base - step))
        if target == bar.value():
            self._target = target
            event.accept()
            return True

        self._animate(bar.value(), target)
        event.accept()
        return True

    # ---------- 动画 ----------
    def _animate(self, start: int, end: int):
        self._target = end
        duration = int(min(self.MAX_DURATION_MS,
                           self.MIN_DURATION_MS + abs(end - start) * 0.9))
        self._anim.stop()
        self._anim.setDuration(duration)
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

    def _reset(self):
        self._anim.stop()
        self._target = None


def stop_smooth_scroll(area):
    """中断平滑滚动的滑行动画
    ⚠️ 程序自己要"跳到某个位置"时必须先调它（比如聊天窗口跳到最底部），否则正在进行的
       惯性动画会在几十毫秒后把滚动条又拉回它算出的目标位置（"跳到最底了又被弹回来"）。
    """
    if area is None:
        return
    flt = getattr(area, "_smoothScrollFilter", None)
    if flt is None:
        return
    try:
        flt._reset()
    except Exception:
        pass


def install_smooth_scroll(area):
    """为 QScrollArea 安装平滑滚动（重复调用无副作用）"""
    if area is None or area.property("_smoothScrollInstalled"):
        return getattr(area, "_smoothScrollFilter", None)

    flt = SmoothScrollFilter(area)
    # 视口负责接收"子控件未处理而冒泡上来"的滚轮事件；
    # 滚动区域本身负责接收直接投递到它身上的滚轮事件。
    area.viewport().installEventFilter(flt)
    area.installEventFilter(flt)
    area._smoothScrollFilter = flt
    area.setProperty("_smoothScrollInstalled", True)
    return flt
