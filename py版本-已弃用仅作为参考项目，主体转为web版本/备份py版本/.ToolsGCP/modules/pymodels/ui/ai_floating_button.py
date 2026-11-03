"""GCP-AI 悬浮球：主窗口右下角那颗常驻圆形按钮，点它开关右侧 AI 抽屉。

球内部是一团缓慢流动的液体（metaball）：在离屏画布上累加 Σ r²/d² 场，做一次
高斯模糊再按阈值取等值线 —— 因为取的是"场的等值线"，两滴靠近时轮廓会互相融合，
看起来才是液面在流动，而不是各自独立的色斑。
动画只在球可见时跑（_start_anim / _stop_anim）。
"""

from ..utils.fonts import ui_font
import time
from math import sin, cos, pi

from PyQt5.QtCore import (Qt, QTimer, QPropertyAnimation, QEasingCurve, QEvent,
                          QElapsedTimer, QObject, QRectF, pyqtProperty)
from PyQt5.QtGui import (QBrush, QColor, QFont, QPainter, QPen, QPixmap,
                         QRadialGradient, QImage)
from PyQt5.QtWidgets import (QApplication, QDialog, QGraphicsBlurEffect,
                             QGraphicsPixmapItem, QGraphicsScene,
                             QGraphicsDropShadowEffect, QWidget)

try:
    from qfluentwidgets import isDarkTheme
except Exception:
    def isDarkTheme():
        return False

from ..utils.logger import log

# ---------- 按钮尺寸与配色 ----------
BUTTON_SIZE = 64
# 球体外圈留一点边距，给投影和发光让位
INSET = 3

COLOR_BTN_START = "#5B8DEF"
COLOR_BTN_END = "#8A6BEF"
COLOR_BTN_HOVER_START = "#6E9BFF"
COLOR_BTN_HOVER_END = "#9B7FFF"
COLOR_BTN_PRESSED_START = "#4A7AD9"
COLOR_BTN_PRESSED_END = "#7858DF"

# ---------- 液体参数（想调手感就动这几个数） ----------
# 动画帧间隔：25ms(≈40fps)。每帧都要重算 metaball 场 + 一次高斯模糊，
# 58fps 时会占掉小半个 CPU 核并让界面滚动偶发卡顿，40fps 肉眼没区别。
ANIM_INTERVAL_MS = 25
# 液面缓存的相位步长（弧度）：约两帧重算一次缓存
LIQUID_PHASE_STEP = 0.035
# 液体流动速度（弧度/秒）：一个完整循环 = 2π / PHASE_SPEED，0.75 → 8.4 秒一圈。
# ⚠️ 必须按"弧度/秒"按真实时间换算，写成"每帧增量"会慢到看不出在动。
PHASE_SPEED = 0.75
BLOB_COUNT = 3
BLOB_RADIUS = 0.42         # 每滴液滴的影响半径（相对球半径）
FIELD_THRESHOLD = 1.25     # 等值线阈值：越大液面收得越紧（球越小）
# 阈值之上的柔化区间（决定球内部看得出多少层次）：
# ⚠️ 场是 Σ r²/d²，量级可到几十上百；给小了会糊成一个纯色圆盘看不出流动，
#    给大了（8.0）高光又会糊成一团。
FIELD_SOFT = 4.0
DRIFT_RANGE = 0.45         # 液滴漂移幅度（相对球半径）
# 液滴绕球心公转的幅度（相对 2π）：只靠漂移是原地晃动，加上公转才像液体翻涌
SWIRL_RANGE = 0.30
BLUR_RADIUS = 4.0          # 高斯模糊半径：越大越"糊"，融合感越强
EDGE_FEATHER = 0.16        # 边缘羽化宽度（相对球内强度），避免出现锯齿硬边

# 液体亮色（球内部高光色），按品牌色系取
LIQUID_BRIGHT = "#7FD4FF"
LIQUID_DEEP = "#6C5CE7"

# 弹窗开着时，球多久重新核对一次弹窗状态（单位：帧，约 0.75 秒）
DIALOG_RECHECK_TICKS = 30

# 触发"重新核对弹窗状态"的事件类型。
# ⚠️ QEvent.Destroy 在 PyQt5 里不存在（Qt6 才有），直接引用会 AttributeError，
# 所以按名字取、取不到就跳过。
_DIALOG_EVENT_TYPES = tuple(
    event_type for event_type in (
        getattr(QEvent, name, None)
        for name in ("Show", "Hide", "Close", "DeferredDelete", "Destroy")
    ) if event_type is not None
)


class _DialogWatcher(QObject):
    """盯着"主窗口上有没有弹窗"，有就通知悬浮球先别重绘

    ⚠️ 必须这么做：qfluentwidgets 的 MessageBox 是主窗口上的子控件而不是独立窗口，
    球的高频重绘会让弹窗区域反复重新合成，跑几秒后 QDialog::exec() 的嵌套事件循环
    会自己退出 —— 表现为"删除确认框自己把自己确认掉"。弹窗开着时只跳过重绘。
    """

    def __init__(self, button):
        super().__init__(button)
        self._button = button

    def eventFilter(self, obj, event):
        # 只在弹窗显示/隐藏/销毁时重算，平时零开销
        if event.type() in _DIALOG_EVENT_TYPES and isinstance(obj, QDialog):
            self._button.refresh_dialog_state()
        return False


class AIFloatingButton(QWidget):
    """GCP-AI 悬浮球

    职责：贴在主窗口右下角、画流动的液体、处理点击（on_clicked_callback）、
    出现/消失动画。聊天本身全在抽屉那边（ai_chat_panel）。
    """

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._hover = False
        self._pressed = False
        self._scale = 1.0
        self._opacity = 0.0
        self._phase = 0.0
        # 液面 pixmap 缓存（按相位量化值复用）
        self._liquid_cache = None
        self._liquid_key = None
        self.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        # ⚠️ 悬停提示要跟界面语言走
        self.setToolTip(self._tip_text())
        self.hide()

        # 球的柔和投影
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(36)
        self._shadow.setOffset(0, 8)
        self._shadow.setColor(QColor(91, 141, 239, 100))
        self.setGraphicsEffect(self._shadow)

        # 动画定时器（只在可见时跑）
        self._timer = QTimer(self)
        self._timer.setInterval(ANIM_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)
        self._animating = False
        # 真实时间基准：动画恒速靠它
        self._clock = QElapsedTimer()
        # 「让路」截止时间（time.monotonic 秒）：滚动/拖拽期间不重绘
        self._pause_until = 0.0

        # 弹窗守卫：弹窗盖在界面上时先不重绘
        self._dialog_open = False
        self._dialog_tick = 0
        self._dialog_watcher = _DialogWatcher(self)
        self._dialog_watcher_installed = False

        # 点击回调（由主窗口设置：点击 → 开/关抽屉）
        self.on_clicked_callback = None

    # ---------- 绘制 ----------
    def _tip_text(self) -> str:
        """悬浮球的悬停提示（按当前界面语言）"""
        fallback = "GCP-AI (click to open / close; the shortcut can be changed in Settings)"
        try:
            lang = getattr(self.main_window, "language_manager", None)
            if lang is not None:
                text = lang.get_text("nav", "ai_ball_tip")
                if text and text != "ai_ball_tip":
                    return str(text)
        except Exception:
            pass
        return fallback

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 缩放 + 透明度（出现/消失动画用）
        center = self.rect().center()
        painter.translate(center)
        painter.scale(self._scale, self._scale)
        painter.translate(-center)
        painter.setOpacity(self._opacity)

        rect = QRectF(self.rect().adjusted(INSET, INSET, -INSET, -INSET))
        colors = self._palette()

        try:
            self._paint_glow(painter, rect, colors)
            self._paint_liquid(painter, rect, colors)
            self._paint_highlight(painter, rect)
            self._paint_border(painter, rect)
            self._paint_letter(painter, rect)
        except Exception as exc:
            # ⚠️ 自绘控件里抛异常会打断整个窗口的绘制，严重时白屏；这里退化成纯色圆
            log.err("AI", "paint", f"悬浮球绘制失败: {exc}")
            from ..interfaces.settings.theme import ball_gradient
            painter.setBrush(QBrush(QColor(ball_gradient()[0])))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(rect)
        painter.end()

    def _palette(self) -> dict:
        """按交互状态选配色（按下 > 悬停 > 常态）

        ⚠️ 颜色恒定，不跟"组件配色"档位变；从 theme 模块现取只是为了一处统一的色值定义。
        """
        from ..interfaces.settings.theme import (ball_gradient,
                                                 ball_liquid_colors)
        if self._pressed:
            start, end = ball_gradient(pressed=True)
        elif self._hover:
            start, end = ball_gradient(hover=True)
        else:
            start, end = ball_gradient()
        bright, deep = ball_liquid_colors()
        return {
            "start": QColor(start),
            "end": QColor(end),
            "bright": QColor(bright),
            "deep": QColor(deep),
            "key": (start, end),
        }

    def _paint_glow(self, painter, rect, colors):
        """球外的一圈柔光（呼吸感）"""
        breath = 0.5 + 0.5 * sin(self._phase * 1.6)
        glow = QColor(colors["start"])
        glow.setAlpha(int(18 + 22 * breath))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(rect.adjusted(-2, -2, 2, 2))

    def _paint_liquid(self, painter, rect, colors):
        """画球体：底色 + 流动的液面（核心）"""
        base = QColor(colors["end"]).darker(125)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(base))
        painter.drawEllipse(rect)

        liquid = self._render_liquid_pixmap(rect, colors)
        painter.drawPixmap(rect.topLeft(), liquid)

    def _render_liquid_pixmap(self, rect: QRectF, colors) -> QPixmap:
        """把液面渲染成一张带透明通道的 pixmap：算 metaball 场 → 高斯模糊 → 裁回圆形。

        ⚠️ QImage 必须用 Format_ARGB32_Premultiplied 并自己预乘，否则模糊会糊出黑边。
        结果按"相位量化值 + 配色 + 尺寸"缓存，约两帧重算一次。
        """
        size = BUTTON_SIZE
        key = (int(self._phase / LIQUID_PHASE_STEP),
               colors.get("key"), int(rect.width()))
        if self._liquid_cache is not None and self._liquid_key == key:
            return self._liquid_cache

        radius = rect.width() / 2.0
        cx = cy = size / 2.0

        # 液滴位置 = 公转 + 各自的正弦漂移
        # ⚠️ 相位系数要错开（0.3~0.5）：同频画出来是整块平移像果冻，错开才有融合分离
        swirl = self._phase * 0.3
        blobs = []
        for i in range(BLOB_COUNT):
            base = i * (2 * pi / BLOB_COUNT) + swirl
            # 液滴沿"绕着球心的小圆"漂移（半径随自身相位缓慢呼吸）
            orbit = radius * DRIFT_RANGE * (0.75 + 0.25 * sin(self._phase * 0.5 + i))
            bx = cx + orbit * cos(base)
            by = cy + orbit * sin(base) * 0.85      # 纵向压一点，避免上下顶到边
            # 再叠一层慢速抖动，打散完全规则的圆周运动
            bx += radius * 0.10 * sin(self._phase * 0.83 + i * 2.1)
            by += radius * 0.10 * cos(self._phase * 0.67 + i * 1.7)
            blobs.append((bx, by, (radius * BLOB_RADIUS) ** 2))

        bright = colors["bright"]
        deep = colors["deep"]

        # ⚠️ 必须按内存布局往 bytearray 写字节再一次性构造 QImage：逐像素
        #    setPixelColor 是 4096 次 Python→C++ 调用，会明显拖慢帧率。
        #    布局是小端序 BGRA，且**必须自己预乘**（RGB × alpha/255），
        #    不预乘的话后面那步高斯模糊会把半透明边缘糊出黑边。
        stride = size * 4
        buf = bytearray(size * size * 4)
        b_right, b_green, b_blue = bright.red(), bright.green(), bright.blue()
        d_right, d_green, d_blue = deep.red(), deep.green(), deep.blue()

        for y in range(size):
            row_base = y * stride
            yc = y + 0.5
            for x in range(size):
                # metaball 场：各液滴在这个点的"势"之和
                field = 0.0
                xc = x + 0.5
                for bx, by, r2 in blobs:
                    dx = xc - bx
                    dy = yc - by
                    d2 = dx * dx + dy * dy
                    if d2 < 1e-3:
                        field += 1e6
                    else:
                        field += r2 / d2
                if field <= FIELD_THRESHOLD:
                    continue

                # 等值线内侧：离阈值越远越"满"
                strength = (field - FIELD_THRESHOLD) / FIELD_SOFT
                if strength > 1.0:
                    strength = 1.0
                inv = 1.0 - strength

                # 边缘羽化，避免等值线出现锯齿
                if strength < EDGE_FEATHER:
                    alpha = int(255 * (strength / EDGE_FEATHER))
                else:
                    alpha = 255
                if alpha <= 0:
                    continue

                # 颜色：靠中心偏亮蓝，靠边缘偏深紫，模拟液体厚度
                red = int(b_right * strength + d_right * inv)
                green = int(b_green * strength + d_green * inv)
                blue = int(b_blue * strength + d_blue * inv)

                factor = alpha / 255.0
                index = row_base + x * 4
                buf[index] = int(blue * factor)
                buf[index + 1] = int(green * factor)
                buf[index + 2] = int(red * factor)
                buf[index + 3] = alpha

        # ⚠️ QImage 引用这块内存（不拷贝），data 必须活到模糊/裁切之后
        data = bytes(buf)
        image = QImage(data, size, size, stride,
                       QImage.Format_ARGB32_Premultiplied)

        pixmap = QPixmap.fromImage(image)
        # ⚠️ 必须 DPR=1：主程序开了 HighDpi，>1 的 DPR 会在绘制时再缩放一次，液体糊出球外
        pixmap.setDevicePixelRatio(1.0)
        pixmap = self._blur_pixmap(pixmap, BLUR_RADIUS)
        result = self._clip_to_circle(pixmap, size)
        self._liquid_cache = result
        self._liquid_key = key
        return result

    @staticmethod
    def _blur_pixmap(pixmap: QPixmap, radius: float) -> QPixmap:
        """用 QGraphicsBlurEffect 做一次高斯模糊（没有现成的 blur(pixmap) API）

        搭一个临时场景把图项渲染一遍；64×64 这点开销比手写卷积小得多。
        """
        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(pixmap)
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(radius)
        blur.setBlurHints(QGraphicsBlurEffect.QualityHint)
        item.setGraphicsEffect(blur)
        scene.addItem(item)

        result = QImage(pixmap.size(), QImage.Format_ARGB32_Premultiplied)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        scene.render(painter)
        painter.end()
        blurred = QPixmap.fromImage(result)
        blurred.setDevicePixelRatio(1.0)
        return blurred

    @staticmethod
    def _clip_to_circle(pixmap: QPixmap, size: int) -> QPixmap:
        """把模糊后溢出的部分裁回圆形

        ⚠️ 必做，否则球看起来毛茸茸的还带一圈灰边。用 DestinationIn 只留圆内像素。
        """
        result = QPixmap(size, size)
        result.setDevicePixelRatio(1.0)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(0, 0, pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.setBrush(QBrush(QColor(0, 0, 0, 255)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(INSET, INSET, size - INSET * 2, size - INSET * 2))
        painter.end()
        return result

    @staticmethod
    def _paint_highlight(painter, rect):
        """顶部玻璃高光：让球看起来是"玻璃球里装着液体"而不是一块塑料"""
        gradient = QRadialGradient(rect.center().x(), rect.top() + rect.height() * 0.22,
                                   rect.width() * 0.62)
        gradient.setColorAt(0.0, QColor(255, 255, 255, 70))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(rect)

    @staticmethod
    def _paint_border(painter, rect):
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 55), 1.2))
        painter.drawEllipse(rect)

    @staticmethod
    def _paint_letter(painter, rect):
        """球中心的 "G"（带一点投影，压在液体上也看得清）"""
        painter.setFont(ui_font(19, bold=True))
        shadow_rect = QRectF(rect)
        shadow_rect.translate(0, 1)
        painter.setPen(QColor(0, 0, 0, 80))
        painter.drawText(shadow_rect, Qt.AlignCenter, "G")
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(rect, Qt.AlignCenter, "G")

    # ---------- 位置 ----------
    def update_position(self):
        """贴到主窗口右下角（留 24px 边距）

        父级是主窗口时用相对坐标，是独立顶层窗口时用屏幕坐标。
        """
        if self.main_window is None:
            return
        margin = 24
        if self.parent() is self.main_window:
            x = self.main_window.width() - self.width() - margin
            y = self.main_window.height() - self.height() - margin
            self.move(max(0, x), max(0, y))
        else:
            geo = self.main_window.geometry()
            x = geo.x() + geo.width() - self.width() - margin
            y = geo.y() + geo.height() - self.height() - margin
            self.move(x, y)
        self.raise_()

    # ---------- 显示 / 隐藏 ----------
    def attach(self):
        """挂到主窗口上并播出现动画"""
        if self.parent() is not self.main_window:
            self.setParent(self.main_window)
        self.update_position()
        self.show()
        self.raise_()
        self._play_appear()
        self._start_anim()

    def detach(self):
        """淡出并隐藏（关掉 GCP-AI 时）"""
        self._stop_anim()
        self._play_disappear()

    # ---------- 动画 ----------
    def _start_anim(self):
        if not self._animating:
            self._animating = True
            self._install_dialog_watcher()
            self.refresh_dialog_state()
            # ⚠️ 必须先把计时基准归零：_stop_anim 只停了 QTimer，QElapsedTimer 还在走，
            # 重启后第一帧的 dt 会是整段停摆时间，相位一次跳掉好几圈。
            try:
                self._clock.restart()
            except Exception:
                pass
            self._timer.start()

    def _stop_anim(self):
        self._animating = False
        self._timer.stop()
        # 作废计时基准，保证停摆期间不累计时间
        try:
            self._clock.invalidate()
        except Exception:
            pass
        self._remove_dialog_watcher()

    # ---------- 弹窗守卫 ----------
    def _install_dialog_watcher(self):
        app = QApplication.instance()
        if app is None or self._dialog_watcher is None or self._dialog_watcher_installed:
            return
        app.installEventFilter(self._dialog_watcher)
        self._dialog_watcher_installed = True

    def _remove_dialog_watcher(self):
        app = QApplication.instance()
        if app is None or not self._dialog_watcher_installed:
            return
        app.removeEventFilter(self._dialog_watcher)
        self._dialog_watcher_installed = False

    def refresh_dialog_state(self):
        """重算"现在有没有弹窗盖在主窗口上"

        ⚠️ 只在弹窗显示/隐藏/销毁时调（外加每 30 帧兜底一次），不在每帧里做 ——
        findChildren 要遍历上千个控件。
        """
        opened = False
        try:
            app = QApplication.instance()
            if app is not None and app.activeModalWidget() is not None:
                opened = True
            window = self.main_window
            if not opened and window is not None:
                for dialog in window.findChildren(QDialog):
                    if dialog.isVisible():
                        opened = True
                        break
        except RuntimeError:
            opened = False        # 控件正在销毁，当作没有弹窗
        self._dialog_open = opened

    def _on_tick(self, dt_ms: float = None):
        """每一帧按真实经过的时间推进相位

        按真实时间算才是恒速（固定增量在掉帧时会忽快忽慢）；dt_ms 参数只给测试用。
        ⚠️ 相位到 2π 就绕回来：一直涨下去 float 精度会变差，跑几小时后动画会跳帧。
        """
        if dt_ms is None:
            if not self._clock.isValid():
                self._clock.start()
            dt_ms = self._clock.restart()
        # ⚠️ 夹住单帧时长：卡顿/断点/唤醒后 dt 可能是好几秒，不夹相位会一次跳掉一大截
        try:
            dt_ms = max(0.0, min(float(dt_ms), 100.0))
        except (TypeError, ValueError):
            dt_ms = 0.0

        # 「让路」守卫：滚动/拖拽期间先不画
        if self._pause_until > 0 and time.monotonic() < self._pause_until:
            return

        # 弹窗守卫：只跳过重绘（定时器照跑），每 30 帧兜底重算一次
        self._dialog_tick += 1
        if self._dialog_tick >= DIALOG_RECHECK_TICKS:
            self._dialog_tick = 0
            self.refresh_dialog_state()
        if self._dialog_open:
            return

        self._phase += PHASE_SPEED * (float(dt_ms) / 1000.0)
        # 取模而不是减一次 2π：dt 再大相位也不会失控
        if self._phase > 2 * pi or self._phase < 0:
            self._phase %= 2 * pi
        self.update()

    def pause_for(self, ms: int = 200):
        """让球安静一会儿（毫秒）：滚动 / 拖拽这类"用户正在动"的时候调

        ⚠️ 球单帧要 3~4ms，插在滚动帧里就是"偶尔顿一下"；滚动时它本来就在视野边缘。
        """
        try:
            self._pause_until = time.monotonic() + max(0, int(ms)) / 1000.0
        except Exception:
            pass

    @staticmethod
    def cycle_seconds() -> float:
        """液体走完一个完整循环需要多少秒（给测试和调参用）"""
        return 2 * pi / PHASE_SPEED

    def _play_appear(self):
        self._opacity = 0.0
        self._scale = 0.6
        fade = QPropertyAnimation(self, b"aiOpacity")
        fade.setDuration(260)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        fade.start()
        self._fade_anim = fade

        grow = QPropertyAnimation(self, b"aiScale")
        grow.setDuration(260)
        grow.setStartValue(0.6)
        grow.setEndValue(1.0)
        grow.setEasingCurve(QEasingCurve.OutBack)
        grow.start()
        self._scale_anim = grow

    def _play_disappear(self):
        fade = QPropertyAnimation(self, b"aiOpacity")
        fade.setDuration(200)
        fade.setStartValue(self._opacity)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.InCubic)
        # finished 里再 hide：动画结束时控件可能已被销毁，要判一下
        fade.finished.connect(lambda: self.isVisible() and self.hide())
        fade.start()
        self._fade_anim = fade

    # ---------- 动画属性 ----------
    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, value):
        self._opacity = value
        self.update()

    aiOpacity = pyqtProperty(float, _get_opacity, _set_opacity)

    def _get_scale(self):
        return self._scale

    def _set_scale(self, value):
        self._scale = value
        self.update()

    aiScale = pyqtProperty(float, _get_scale, _set_scale)

    # ---------- 鼠标 ----------
    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = False
            self.update()
            # 只有"按下去又抬起来都在球上"才算点击（跟普通按钮一致）
            if self.rect().contains(event.pos()):
                self._emit_clicked()
        super().mouseReleaseEvent(event)

    def _emit_clicked(self):
        """点击 → 交给主窗口去开关抽屉

        用回调而不是 Qt 信号：只有一个消费者，回调更直接。
        """
        if callable(self.on_clicked_callback):
            try:
                self.on_clicked_callback()
            except Exception as exc:
                log.err("AI", "toggle", f"打开 AI 抽屉失败: {exc}")

    def refresh_theme(self):
        """主题切换后重画

        液体是品牌蓝紫、不跟主题变色；但顶部高光/内边框在深色下观感差一点，所以重绘一次。
        """
        self._last_palette = None
        self.update()