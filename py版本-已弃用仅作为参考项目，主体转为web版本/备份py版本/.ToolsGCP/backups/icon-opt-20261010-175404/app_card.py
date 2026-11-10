"""应用卡片。"""

import os
import weakref
import webbrowser
from pathlib import Path

# 外链打开统一走 utils/url_open（带 Ctrl+左键"静默打开"逻辑）
from ..utils.url_open import open_url, watch_ctrl
from PyQt5.QtCore import (Qt, QSize, QVariantAnimation, QEasingCurve, QEvent,
                          QObject, QRunnable, QThreadPool, pyqtSignal)
from PyQt5.QtGui import (QPixmap, QIcon, QImage, QPainter, QColor, QFont,
                         QFontMetrics, QMovie)
from PyQt5.QtWidgets import (QApplication, QVBoxLayout, QHBoxLayout, QWidget,
                             QLabel)
from qfluentwidgets import (
    SimpleCardWidget,
    StrongBodyLabel,
    CaptionLabel,
    CheckBox,
    FluentIcon as FIF,
    ToolTipFilter,
    ToolTipPosition,
    TransparentToolButton,
    isDarkTheme,
    themeColor,
)


def _load_local_icon(path: str, size: int) -> QPixmap:
    """加载本地图片并缩放到指定尺寸（同步版，只在主线程兜底路径上用）"""
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return QPixmap()
    return pixmap.scaled(
        size,
        size,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )


# ---------- 卡片上显示的标签 ----------

def card_tag_values(data: dict) -> list:
    """卡片底部那一行要显示的标签值（规范中文，交给上层翻译成显示名）

    ⚠️ 有条目只填了「类别」、没填 tags，直接取 tags 会让标签行整个空掉：
       有标签就只用标签，一个都没有才退回显示类别。
    """
    data = data or {}
    tags = [str(t) for t in (data.get("tags") or []) if str(t).strip()]
    if tags:
        return tags
    try:
        from ..core import resource_schema
        return [str(c) for c in resource_schema.categories_of(data)
                if str(c).strip()]
    except Exception:
        cats = data.get("category") or []
        if isinstance(cats, (str, dict)):
            cats = [cats]
        return [str(c) for c in cats if str(c).strip()]


# ---------- 图标解码：放到工作线程里 ----------
# "读盘 + 解码 + 缩放"冷加载一张要 6~9ms，一批 4 张就掉帧。解法是**解码（QImage）挪到
# 工作线程**，主线程只做 QPixmap.fromImage（约 0.1ms）—— QPixmap 只能在 GUI 线程创建。
_ICON_POOL = None
_ICON_SIGNALS = None
# 主线程成品缓存：(绝对路径, 尺寸) -> QPixmap
_ICON_PIXMAP_CACHE: dict = {}
# 正在解码的请求（避免同一张图被重复解码）
_ICON_INFLIGHT: set = set()
# 等待某张图的卡片（弱引用，卡片被销毁不影响）
_ICON_WAITERS: dict = {}


class _IconDecodeSignals(QObject):
    """工作线程 → 主线程的信号出口（必须在主线程创建）"""

    done = pyqtSignal(str, int, object)      # path, size, QImage | None


class _IconDecodeTask(QRunnable):
    """在**工作线程**里把图片解码并缩放到目标尺寸（只产出 QImage，不碰 QPixmap）"""

    def __init__(self, path: str, size: int, signals: _IconDecodeSignals):
        super().__init__()
        self._path = path
        self._size = int(size)
        self._signals = signals

    def run(self):
        image = None
        try:
            image = QImage(self._path)
            if image.isNull():
                image = None
            else:
                image = image.scaled(self._size, self._size,
                                     Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:
            image = None
        try:
            self._signals.done.emit(self._path, self._size, image)
        except RuntimeError:
            # 程序正在退出（信号宿主已经被销毁）：丢掉就行
            pass


def _icon_loader():
    """惰性创建解码线程池 + 信号宿主"""
    global _ICON_POOL, _ICON_SIGNALS
    if _ICON_POOL is None:
        # 挂到 QApplication 上：线程池销毁时会等所有解码任务跑完
        pool = QThreadPool(QApplication.instance())
        # 2 个线程够了：解码是短任务，开多了只是白占内存
        pool.setMaxThreadCount(2)
        _ICON_POOL = pool
        _ICON_SIGNALS = _IconDecodeSignals()
        _ICON_SIGNALS.done.connect(_on_icon_decoded)
    return _ICON_POOL, _ICON_SIGNALS


def _request_icon_async(card, path: str, size: int):
    """请求一张本地图标（命中缓存立刻上屏，否则丢给线程池）"""
    key = (path, int(size))
    cached = _ICON_PIXMAP_CACHE.get(key)
    if cached is not None:
        card._set_icon_pixmap(cached)
        return

    _ICON_WAITERS.setdefault(key, []).append(weakref.ref(card))
    if key in _ICON_INFLIGHT:
        return
    _ICON_INFLIGHT.add(key)
    pool, signals = _icon_loader()
    pool.start(_IconDecodeTask(path, int(size), signals))


def _on_icon_decoded(path: str, size: int, image):
    """（主线程）解码完成：转成 QPixmap 并喂给还在等这张图的卡片"""
    key = (path, int(size))
    _ICON_INFLIGHT.discard(key)
    try:
        pixmap = QPixmap.fromImage(image) if image is not None and not image.isNull() \
            else QPixmap()
    except Exception:
        pixmap = QPixmap()
    _ICON_PIXMAP_CACHE[key] = pixmap

    for ref in _ICON_WAITERS.pop(key, []):
        card = ref()
        if card is None:
            continue
        try:
            card._set_icon_pixmap(pixmap)
        except RuntimeError:
            continue      # 卡片已经被销毁


# 类级别图标缓存: path -> QIcon，避免重复加载同一图片文件
_icon_cache: dict = {}

# 收藏状态用小图标上色缓存: (icon_name, color_name) -> QIcon
_tinted_cache: dict = {}

# 跟随主题的图标缓存: (icon_name, color_name, size) -> QIcon（见 themed_icon）
_themed_cache: dict = {}

# 卡片尺寸（宽度由 ResponsiveGrid 按可用宽度算，这里只定义基准和高度）
CARD_WIDTH = 272          # 基准宽度 / 最小宽度参考
CARD_HEIGHT = 196
ICON_SIZE = 64
DESC_LINES = 2
NAME_DELTA = 4            # 名称字号比默认大多少
CARD_PADDING = 16         # 卡片内边距
PAGE_MARGIN = 24          # 页面左右留白（左右一致）
CARD_SPACING = 14         # 卡片之间的间距
# 网格（小卡片）视图的最小宽度：1280 页宽时内容区约 1184px → (1184+12)//(168+12) = 6 列
GRID_MIN_WIDTH = 168
GRID_SPACING = 12

# 设置里「搜索页卡片大小」的三档预设，改这里就能整体调节卡片
CARD_PRESETS = {
    "small": {"height": 168, "icon": 48, "lines": 2, "name_delta": 3},
    "medium": {"height": 196, "icon": 64, "lines": 2, "name_delta": 4},
    "large": {"height": 240, "icon": 80, "lines": 3, "name_delta": 5},
}
DEFAULT_CARD_SIZE = "medium"

# ---------- 视图模式 ----------
# tile = 磁贴（默认，一行 4 个大卡片，按钮齐全）；grid = 网格（一行 6 个小卡片，只留收藏）
VIEW_TILE = "tile"
VIEW_GRID = "grid"
_view_mode = VIEW_TILE
_card_size_key = DEFAULT_CARD_SIZE

# 搜索页卡片上是否显示 GitHub 按钮（**默认开启**，设置里可以关掉）
_show_github_button = True

# ---------- 两种视图的**列数下限**与**卡片最宽** ----------
# 卡片宽度保持在合理区间（auto-fit）：下限是 ResponsiveGrid 的 min_item_width（窗口窄就
# 少放几列），上限是 MAX_CARD_WIDTH（窗口继续变宽就**多开一列**，而不是把那几列撑胖 ——
# 只有固定列数上限时，2560 宽的屏幕上每张卡片会有 600+ 像素、被横向拉扁）。
TILE_BASE_COLUMNS = 4     # 磁贴视图：设计上"一行 4 个大卡片"（作为下限）
GRID_BASE_COLUMNS = 6     # 网格视图：设计上"一行 6 个小卡片"（作为下限）
TILE_MAX_CARD_WIDTH = 400   # 磁贴卡片超过这个宽度就该多开一列
GRID_MAX_CARD_WIDTH = 240   # 网格卡片同理


def max_columns(avail: int = None) -> int:
    """当前视图允许的最多列数（ResponsiveGrid 每次布局都会问它一次；avail 是可用宽度）"""
    base = GRID_BASE_COLUMNS if is_compact_view() else TILE_BASE_COLUMNS
    if avail is None:
        return base
    try:
        avail = int(avail)
    except (TypeError, ValueError):
        return base
    if avail <= 0:
        return base
    limit = GRID_MAX_CARD_WIDTH if is_compact_view() else TILE_MAX_CARD_WIDTH
    # 向上取整：宁可多一列（卡片略窄），也不要让卡片超出最宽
    needed = -(-avail // limit)
    return max(base, int(needed))


def apply_card_size(key: str):
    """套用一档卡片尺寸（改的是全局量，之后创建的卡片生效；调用方要重渲染列表）"""
    global _card_size_key
    _card_size_key = str(key or "").strip() or DEFAULT_CARD_SIZE
    if _card_size_key not in CARD_PRESETS:
        _card_size_key = DEFAULT_CARD_SIZE
    _recompute_sizes()


def apply_view_mode(key: str):
    """切换搜索页视图（tile 磁贴 / grid 网格），并重算卡片尺寸"""
    global _view_mode
    _view_mode = VIEW_GRID if str(key or "").strip() == VIEW_GRID else VIEW_TILE
    _recompute_sizes()


def view_mode() -> str:
    return _view_mode


# Ctrl+左键提示的兜底文案（真值在 search_language.json 的 card_link_tip）
# ⚠️ 兜底一律用**英文**：语言文件缺失时整界面应当是统一的英文，不能中英混杂
CTRL_TIP_FALLBACK = "Ctrl+click: open quietly without switching away"


def _card_text(key: str, default: str = "") -> str:
    """卡片上的文案查一次当前语言（search 段优先，再退 settings，最后用兜底）"""
    try:
        from ..core.language_manager import get_current_manager
        manager = get_current_manager()
        if manager is None:
            return default
        for module in ("search", "settings"):
            try:
                text = manager.get_text(module, key)
            except Exception:
                text = key
            if text and text != key:
                return str(text)
    except Exception:
        pass
    return default


def is_compact_view() -> bool:
    """是不是"小卡片"视图（网格）"""
    return _view_mode == VIEW_GRID


def apply_github_button_setting(enabled: bool):
    """搜索页卡片要不要显示 GitHub 按钮（**默认显示**）"""
    global _show_github_button
    _show_github_button = bool(enabled)


def github_button_enabled() -> bool:
    return _show_github_button


def _recompute_sizes():
    """按「卡片大小 + 视图模式」算出这套全局尺寸

    ⚠️ 宽度（列数）由 ResponsiveGrid 按可用宽度算，这里只给最小宽度（网格视图用更小的
       168，让一屏挤出 6 列）并同步收小高度/图标/字号。
    """
    global CARD_HEIGHT, ICON_SIZE, DESC_LINES, NAME_DELTA, CARD_MIN_WIDTH, CARD_SPACING
    preset = CARD_PRESETS[_card_size_key]
    if _view_mode == VIEW_GRID:
        CARD_MIN_WIDTH = GRID_MIN_WIDTH
        CARD_SPACING = GRID_SPACING
        CARD_HEIGHT = max(120, int(round(preset["height"] * 0.76)))
        ICON_SIZE = max(30, int(round(preset["icon"] * 0.62)))
        DESC_LINES = preset["lines"]
        NAME_DELTA = max(1, preset["name_delta"] - 2)
    else:
        CARD_MIN_WIDTH = CARD_WIDTH
        CARD_SPACING = 14
        CARD_HEIGHT = preset["height"]
        ICON_SIZE = preset["icon"]
        DESC_LINES = preset["lines"]
        NAME_DELTA = preset["name_delta"]


# 卡片的最小宽度（ResponsiveGrid 用它算列数）
CARD_MIN_WIDTH = CARD_WIDTH
_recompute_sizes()


def current_card_size() -> str:
    """反查当前是哪一档（设置页回显用）"""
    for key, preset in CARD_PRESETS.items():
        if (preset["height"] == CARD_HEIGHT and preset["icon"] == ICON_SIZE
                and preset["lines"] == DESC_LINES):
            return key
    return DEFAULT_CARD_SIZE


def enlarge_font(font, delta: int):
    """把字体放大 delta

    ⚠️ 有的标签用 pointSize、有的用 pixelSize：pointSize() 在后者返回 -1，两种都要兼容。
    """
    result = QFont(font)
    if result.pointSize() > 0:
        result.setPointSize(result.pointSize() + delta)
    elif result.pixelSize() > 0:
        result.setPixelSize(result.pixelSize() + delta)
    else:
        result.setPointSize(12)
    return result


def _adjust_alpha(color: QColor, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


def tooltip_style() -> str:
    """qfluentwidgets 风格的 tooltip 样式（深色/浅色各一套）

    ⚠️ 只能给普通 QWidget / QLabel：给 TransparentToolButton 之类库控件 setStyleSheet
       会把它画成白底方块，那些按钮的悬浮提示统一走库自带的 ToolTipFilter。
    """
    if isDarkTheme():
        return (
            "QToolTip {"
            "  background-color: #2B2B2B;"
            "  color: #FFFFFF;"
            "  border: 1px solid #3E3E3E;"
            "  border-radius: 6px;"
            "  padding: 6px 10px;"
            "  font-size: 12px;"
            "}"
        )
    return (
        "QToolTip {"
        "  background-color: #FFFFFF;"
        "  color: #000000;"
        "  border: 1px solid #E0E0E0;"
        "  border-radius: 6px;"
        "  padding: 6px 10px;"
        "  font-size: 12px;"
        "}"
    )


def attach_fluent_tooltip(widget, text: str):
    """挂上 qfluentwidgets 原生悬浮提示（圆角、跟随主题，和程序其它地方一致）"""
    widget.setToolTip(text)
    widget.installEventFilter(ToolTipFilter(widget, 300, ToolTipPosition.TOP))


def icon_color(dark: bool = None) -> QColor:
    """当前主题下"图标该用什么颜色"

    ⚠️ FluentIcon 取 `.icon()` 时颜色按**取的那一刻**的主题定死：深色下建卡 → 切浅色
       → 白色字形留在白卡片上（像"按钮消失了"）。主题变化时都要用这个颜色重取一遍。
    """
    if dark is None:
        dark = isDarkTheme()
    return QColor("#FFFFFF") if dark else QColor("#1F2329")


# ⚠️ 私有别名：只要有调用方拿 `icon_color` 当参数名，全局函数就会被遮住（RecursionError 爆栈）
_icon_color = icon_color


def themed_icon(icon, size: int = 16, dark: bool = None) -> QIcon:
    """按当前主题取一个"跟随主题"的单色图标（Qt 控件用）

    ⚠️ 结果按 (图标, 颜色, 尺寸) 缓存：`FluentIcon.icon(color=...)` 内部要生成 SVG
       再渲染，一次接近 1ms。QIcon 隐式共享，缓存这份只被 setIcon / pixmap 读。
    """
    if dark is None:
        dark = isDarkTheme()
    color = QColor("#FFFFFF") if dark else QColor("#1F2329")
    key = (str(icon), color.name(), int(size))
    cached = _themed_cache.get(key)
    if cached is not None:
        return cached
    try:
        result = icon.icon(color=color)
    except TypeError:
        # 老版本 FluentIcon 不支持 color 参数：退回"取图后再染色"
        result = tinted_icon(icon, color, size)
    _themed_cache[key] = result
    return result


class ThemedIconMixin:
    """让"图标是自绘/一次性取色"的控件在主题切换时自动重新取图标

    Qt 在全局样式变化时会给每个控件发 StyleChange，这里只挂一个很轻的守卫：
    **事件号变了才重取**，正常绘制/滚动路径上不做多余的事。
    """

    def _themed_icon_guard(self):
        """在 __init__ 里调一次即可"""
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self and event.type() == QEvent.StyleChange:
            self._reapply_themed_icons()
        return super().eventFilter(obj, event)

    def _reapply_themed_icons(self):
        """子类覆盖：把图标按当前主题重新取一遍"""


def tinted_icon(icon, color: QColor, size: int = 16) -> QIcon:
    """把单色图标染成指定颜色（用于收藏按钮的选中态）"""
    key = (str(icon), color.name(), size)
    if key in _tinted_cache:
        return _tinted_cache[key]
    pixmap = icon.icon().pixmap(QSize(size, size))
    if pixmap.isNull():
        return icon.icon()
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), color)
    painter.end()
    result = QIcon(pixmap)
    _tinted_cache[key] = result
    return result


class TagLabel(QLabel):
    """标签小部件：圆角框背景，「官方」用金色

    ⚠️ 文字宽高和颜色都要缓存（按 主题 × 是否官方）：滚动时每帧重绘，一屏 40 张卡片、
       每张好几个标签，每次现算 isDarkTheme() + 新建 QColor 是纯浪费。
    """

    _COLOR_CACHE = {}

    @classmethod
    def colors(cls, official: bool) -> tuple:
        """当前主题下这个标签的 (底色, 文字色)"""
        dark = isDarkTheme()
        key = (dark, bool(official))
        cached = cls._COLOR_CACHE.get(key)
        if cached is not None:
            return cached
        if official:
            # 官方标签: 金色
            bg = QColor(255, 215, 0, 38)
            fg = QColor(212, 175, 55)
        elif dark:
            bg = _adjust_alpha(QColor(255, 255, 255), 45)
            fg = QColor(220, 220, 220)
        else:
            bg = _adjust_alpha(QColor(0, 0, 0), 25)
            fg = QColor(60, 60, 60)
        cls._COLOR_CACHE[key] = (bg, fg)
        return bg, fg

    def __init__(self, text: str, parent=None, official: bool = None):
        super().__init__(text, parent)
        self.setWordWrap(False)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(tooltip_style())
        # ⚠️ "是不是官方标签"**不能用显示文字去比**：切英文后标签显示成 "Official"，比对就
        #    永远不成立、金色变灰。所以由调用方按**规范值**传进来，没传才退回按文字判断。
        self._official = (str(text) == "官方") if official is None else bool(official)
        font = self.font()
        self._fm = QFontMetrics(font)
        self._text_rect = self._fm.boundingRect(text)

    def paintEvent(self, event):
        painter = QPainter(self)

        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = 10

        bg, fg = self.colors(self._official)

        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(bg)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, radius, radius)

        painter.setPen(fg)
        text_rect = self._text_rect
        x = (self.width() - text_rect.width()) // 2
        y = (self.height() + self._fm.ascent() - self._fm.descent()) // 2
        painter.drawText(x, y, self.text())

    def sizeHint(self):
        return QSize(self._text_rect.width() + 20, self._text_rect.height() + 8)


class IconButton(ThemedIconMixin, QLabel):
    """卡片右上角/右下角用的小图标按钮

    ⚠️ 不用 qfluentwidgets 的 TransparentToolButton：它自带样式表，绘制要过一遍
       Qt 样式表引擎（一张卡片 3 个、40 张就是 120 个，滚动掉帧），而且给它
       setStyleSheet 设 tooltip 会把按钮画成白方块。
    """

    clicked = pyqtSignal()

    def __init__(self, icon, tooltip: str, size: int = 26, icon_size: int = 16, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setStyleSheet(tooltip_style())
        self._icon_size = icon_size
        self._pixmap = QPixmap()
        self._hover = False
        self._themed_source = None      # 记下"跟随主题"的原始图标，主题变了用它重取
        self._glyph = ""                # 文字类按钮（"@"）记下字符，主题变了重画
        # 按下那一刻有没有按住 Ctrl（见 mousePressEvent 的说明）
        self._press_ctrl = False
        self.set_icon(icon)
        self._themed_icon_guard()

    # ⚠️ 参数**不能**叫 `icon_color`（会遮住模块级的同名函数，一路递归到 RecursionError 爆栈）
    def setThemedIcon(self, icon):
        """设置一个**跟随主题**的图标（把原始 FluentIcon 记下来，主题变化时重新取色）"""
        self._themed_source = icon
        if icon is None:
            self.set_icon(None)
            return
        self.set_icon(themed_icon(icon, self._icon_size))

    def _reapply_themed_icons(self):
        """主题变了：按新主题重新取图标（ThemedIconMixin 的钩子）"""
        if self._themed_source is not None:
            self.set_icon(themed_icon(self._themed_source, self._icon_size))
        elif self._glyph:
            # 文字按钮（比如卡片右上角的 "@"）：重新按当前主题上色
            self.set_glyph(self._glyph)

    def set_icon(self, icon):
        """设置图标：QIcon / FluentIcon 枚举（有 .icon()）/ None（清空）

        ⚠️ 颜色由图标自己带，这里不重新着色 —— 换色要传 `icon.icon(color=...)`。
        """
        if icon is None:
            self._pixmap = QPixmap()
        elif isinstance(icon, QIcon):
            self._pixmap = icon.pixmap(QSize(self._icon_size, self._icon_size))
        elif hasattr(icon, "icon"):
            self._pixmap = icon.icon().pixmap(QSize(self._icon_size, self._icon_size))
        else:
            self._pixmap = QPixmap()
        self._glyph = ""
        QLabel.setText(self, "")
        self.update()

    def set_glyph(self, char: str, bold: bool = False):
        """按钮上直接显示一个**文字**（卡片右上角的 "@" 用它）

        ⚠️ 文字是**自己在 paintEvent 里画**的：本类重写了 paintEvent 且没调
           QLabel.paintEvent，交给 QLabel 的文字画不出来。
        """
        self._glyph = str(char or "")
        self._themed_source = None
        self._pixmap = QPixmap()            # 用文字，不用图
        QLabel.setText(self, self._glyph)
        font = QFont(self.font())
        font.setPixelSize(max(11, int(self._icon_size * 0.82)))
        font.setBold(bool(bold))
        self.setFont(font)
        self._apply_glyph_color()
        self.update()

    def _apply_glyph_color(self):
        """文字按钮的颜色：**只跟随主题**，悬停时不变色（和其他按钮一致）

        ⚠️ setStyleSheet 自己会触发 StyleChange，而 StyleChange 会走守卫 → 又回到这里。
           所以按"当前该用什么颜色"去重：颜色没变就什么都不做，递归断在第一次。
        """
        if not self._glyph:
            return
        color = _icon_color()
        self._glyph_color = QColor(color)     # paintEvent 画文字用它
        if getattr(self, "_glyph_color_name", None) == color.name():
            return              # 颜色没变 → 不再 setStyleSheet（断开递归）
        self._glyph_color_name = color.name()
        self.setStyleSheet(
            tooltip_style()
            + f"QLabel {{ color: {color.name()}; background: transparent; }}")

    def set_tooltip(self, text: str):
        self.setToolTip(text)
        self.setStyleSheet(tooltip_style())

    def enterEvent(self, event):
        self._hover = True
        self.update()                  # 悬停只画一层底色，颜色不变（和其他按钮一致）
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._apply_glyph_color()
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        # 禁用态（比如翻页器到了头/尾）先整体压暗，再做正常绘制
        if not self.isEnabled():
            painter.setOpacity(0.35)
        # ⚠️ 抗锯齿必须无条件打开（只在悬停那一支开的话平时画的 "@" 是锯齿字），
        #    文字还要单独开 TextAntialiasing
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing |
                               QPainter.SmoothPixmapTransform)
        if self._hover and self.isEnabled():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 28) if isDarkTheme()
                             else QColor(0, 0, 0, 18))
            painter.drawRoundedRect(self.rect(), 5, 5)
        if not self._pixmap.isNull():
            x = (self.width() - self._pixmap.width()) // 2
            y = (self.height() - self._pixmap.height()) // 2
            painter.drawPixmap(x, y, self._pixmap)
        elif self._glyph:
            # 文字按钮（"@"）在这里自己居中画（**必须自己画**：本类重写了 paintEvent 且没调
            # QLabel.paintEvent，交给 QLabel 的文字永远画不出来）
            painter.setPen(getattr(self, "_glyph_color", None) or _icon_color())
            font = QFont(self.font())
            font.setPixelSize(max(12, int(self._icon_size * 0.86)))
            font.setBold(False)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, self._glyph)
        painter.end()

    def setEnabled(self, enabled: bool):
        """禁用时同时把鼠标手势改回箭头（配合 paintEvent 里的压暗）"""
        super().setEnabled(enabled)
        if enabled:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self._hover = False
            self.setCursor(Qt.ArrowCursor)
        self.update()

    def mousePressEvent(self, event):
        # 必须吃掉按下事件，否则会冒泡到卡片上触发"进入详情页"
        # ⚠️ 顺便记下"按下这一刻有没有按住 Ctrl"：clicked 是**松开**时才发的，那时再问
        #    修饰键在连点/抢焦点的时序里经常已经不准了
        try:
            self._press_ctrl = bool(event.modifiers() & Qt.ControlModifier)
        except Exception:
            self._press_ctrl = False
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled() \
                and self.rect().contains(event.pos()):
            self.clicked.emit()
        event.accept()


class AppCard(SimpleCardWidget):
    """应用/工具卡片

    字段(与 JSON 索引一致)：name / code(收藏、部署清单用) / category / description /
    icon(FIF 枚举名或 URL 或本地路径) / url(「官网」按钮) / github(「GitHub」按钮)
    信号：card_clicked(data) 点卡片进详情；favorite_toggled(code) 点收藏图标
    """

    card_clicked = pyqtSignal(dict)
    favorite_toggled = pyqtSignal(str)
    selection_toggled = pyqtSignal(str, bool)
    # 「@给AI」按钮：参数是 (名称, 资源编码)
    ai_mention_requested = pyqtSignal(str, str)

    def __init__(self, data: dict, parent=None, is_favorite: bool = False):
        super().__init__(parent)
        self.data = data
        self._favorite = bool(is_favorite)
        self._hover = False
        self._hover_alpha = 0.0
        self._selection_mode = False
        self._selected = False
        self._divider_dark = None
        self._card_width = CARD_MIN_WIDTH

        self.setFixedSize(CARD_MIN_WIDTH, CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

        # 悬浮高亮动画
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(140)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_value)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING - 2,
                                  CARD_PADDING, CARD_PADDING - 2)
        layout.setSpacing(0)

        # ---- 第一行: 图标 + 名称 + 右上角收藏 ----
        upper = QHBoxLayout()
        upper.setSpacing(12)

        # 图标延迟加载：读盘 + 解码 + 缩放（GIF 还要起 QMovie）几十张堆在渲染那一帧里会卡，
        # 所以先放空占位控件，等卡片"进入视口"时由 AppsIndexFramework 排队调 _load_icon()
        self._icon_loaded = False
        self._gif_movie = None
        self.icon_widget = QLabel(self)
        self.icon_widget.setFixedSize(ICON_SIZE, ICON_SIZE)
        self.icon_widget.setAlignment(Qt.AlignCenter)
        upper.addWidget(self.icon_widget, 0, Qt.AlignVCenter)

        # 名称：字号加大 + 单行省略，和图标垂直居中对齐
        self.name_label = StrongBodyLabel("", self)
        self.name_label.setWordWrap(False)
        self.name_label.setFont(enlarge_font(self.name_label.font(), NAME_DELTA))
        self.name_label.setFixedHeight(self.name_label.fontMetrics().height() + 4)
        upper.addWidget(self.name_label, 1)

        # ---- 右上角两个小按钮：@ 在左、收藏在右（@ 给 20px：「@」笔画多，18px 以下会糊）----
        self.mention_button = IconButton(
            None, _card_text("ai_mention_tip", "Mention this entry to GCP-AI"), 28, 20, self)
        self.mention_button.set_glyph("@")
        # ⚠️ 给 AI 抽屉留一个"这是 @ 按钮"的标记：抽屉那个"点其它位置就收起"的全局守卫
        #    （见 ai_chat_panel._outside_close_filter）会把这颗按钮也算成"点外面"、面板闪一下
        self.mention_button.setProperty("gcpAiMentionTrigger", True)
        self.mention_button.clicked.connect(
            lambda: self.ai_mention_requested.emit(
                str(self.data.get("name") or ""), self.resource_code()))
        upper.addWidget(self.mention_button, 0, Qt.AlignTop)

        # 收藏按钮固定在卡片右上角
        self.favorite_button = self._make_favorite_button()
        upper.addWidget(self.favorite_button, 0, Qt.AlignTop)

        # 选择模式用的勾选框（和收藏按钮占同一个位置，二选一显示）
        self.select_checkbox = CheckBox("", self)
        self.select_checkbox.setFixedSize(28, 28)
        self.select_checkbox.stateChanged.connect(self._on_checkbox_changed)
        self.select_checkbox.hide()
        upper.addWidget(self.select_checkbox, 0, Qt.AlignTop)
        layout.addLayout(upper)
        layout.addSpacing(10)

        # ---- 第二行: 简介（整行宽，最多两行，超出省略）----
        self.desc_label = CaptionLabel("", self)
        self.desc_label.setWordWrap(True)
        self.desc_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        desc_font = self.desc_label.fontMetrics()
        self.desc_label.setFixedHeight(desc_font.height() * DESC_LINES + 2)
        layout.addWidget(self.desc_label)
        layout.addStretch()
        self._refresh_texts()

        # 分割线(跟随主题色)
        self.divider = QWidget(self)
        self.divider.setFixedHeight(1)
        self.divider.setStyleSheet(self._divider_style())
        layout.addSpacing(10)
        layout.addWidget(self.divider)
        layout.addSpacing(10)

        # 底部：标签区 + GitHub / 官网（GitHub 在左，官网在最右）
        self.bottom = QHBoxLayout()
        self.bottom.setContentsMargins(0, 0, 0, 0)
        self.bottom.setSpacing(6)
        self.bottom.setAlignment(Qt.AlignVCenter)
        self._fill_bottom()
        layout.addLayout(self.bottom)
        # 网格（小卡片）视图：只留收藏，其它快捷按钮收起来
        self._apply_view_mode()

    def _fill_bottom(self):
        """（重新）填充底部一行：标签 + GitHub / 官网按钮"""
        # 先清空旧的（复用卡片时会走这里）
        while self.bottom.count():
            item = self.bottom.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.github_button = None
        self.url_button = None

        # 小卡片视图里标签只留两个：再挤下去整行就只剩标签了
        max_tags = 2 if is_compact_view() else 4
        from ..core.language_manager import translate_term
        for tag in card_tag_values(self.data)[:max_tags]:
            raw = str(tag)
            # 显示名按当前语言；「官方」的金色按**规范值**判断
            self.bottom.addWidget(TagLabel(translate_term(raw), self,
                                           official=(raw == "官方")))
        self.bottom.addStretch()

        # 「@给AI」按钮在右上角（见 __init__），这里只保留 GitHub / 官网两个外链按钮。
        # ⚠️ GitHub 按钮默认显示（设置里可关）；网格视图里两个都不显示（直接不创建更省）
        if not is_compact_view():
            if _show_github_button:
                self.github_button = self._make_quick_button(
                    self.data.get("github"), FIF.GITHUB,
                    _card_text("card_open_repo", "Open repository"))
                if self.github_button is not None:
                    self.bottom.addWidget(self.github_button)

            self.url_button = self._make_quick_button(
                self.data.get("url"), FIF.GLOBE,
                _card_text("card_open_site", "Open website"))
            if self.url_button is not None:
                self.bottom.addWidget(self.url_button)

    def _apply_view_mode(self):
        """按当前视图模式决定"哪些按钮显示、收藏按钮多大"（网格视图只留收藏）"""
        compact = is_compact_view()
        for name in ("mention_button", "github_button", "url_button"):
            button = getattr(self, name, None)
            if button is None:
                continue
            # 选择模式本来就要把快捷按钮全收起来，这里不要把它又显回来
            button.setVisible((not compact) and (not self._selection_mode))

        size = 22 if compact else 26
        icon_size = 14 if compact else 16
        button = getattr(self, "favorite_button", None)
        if button is not None:
            button._icon_size = icon_size
            button.setFixedSize(size, size)
            self._update_favorite_button()

    # ---------- 复用 ----------
    @staticmethod
    def _signature(data: dict) -> tuple:
        """卡片内容指纹：一样就不用刷"""
        data = data or {}
        return (str(data.get("code") or ""), str(data.get("name") or ""),
                str(data.get("description") or ""), str(data.get("icon") or ""),
                str(data.get("url") or ""), str(data.get("github") or ""),
                tuple(card_tag_values(data)))

    @staticmethod
    def _bottom_signature(data: dict) -> tuple:
        """底部那一行的指纹：标签 + 两个外链按钮的地址

        ⚠️ 底部按钮/标签重建一次要销毁再新建四五个 QWidget（比换文字贵十倍），
           所以只有指纹变了才真的重建。
        """
        data = data or {}
        return (tuple(card_tag_values(data)[:4]),
                str(data.get("url") or ""), str(data.get("github") or ""),
                bool(is_compact_view()))

    def set_data(self, data: dict):
        """就地更新卡片内容（复用卡片，避免反复创建销毁）

        卡片本身的控件树不动，只换文字/图标/按钮，比重建快一个数量级；内容一样时直接返回。
        """
        if self._signature(data) == self._signature(self.data):
            return
        old_icon = str((self.data or {}).get("icon") or "")
        old_bottom = self._bottom_signature(self.data)
        self.data = data or {}
        new_icon = str(self.data.get("icon") or "")

        # 图标变了就重新加载（GIF ↔ 静态图要换控件类型；换个静态图则要重读文件）
        if old_icon != new_icon:
            self._replace_icon_widget()

        self._refresh_texts()
        if old_bottom != self._bottom_signature(self.data):
            self._fill_bottom()
            # 底部按钮是刚重建的，视图模式要重新套一遍（网格视图要藏掉它们）
            self._apply_view_mode()
        if self._selection_mode:
            self.set_selection_mode(True)

    def _replace_icon_widget(self):
        """图标类型变了（GIF ↔ 静态图）时把旧的图卸掉（不销毁重建控件，重建会牵动布局）

        ⚠️ 这里**不重新加载图标**：那张卡很可能是刚被"复用"过来的、isVisible() 为 True，
           每复用一个就同步读一次盘（实测一次远距离滚动 ~150ms）。图标统一交给
           AppsIndexFramework 的延迟队列按节奏加载。
        """
        self._unload_icon()

    # ---------- 图标：延迟加载 / 释放 ----------
    def _load_icon(self):
        """真正把图标画上去（本地图片走工作线程解码 / GIF 起 QMovie / FIF 直接取图）

        由 AppsIndexFramework 在卡片"进入视口"时调用，重复调用无副作用。
        """
        if self._icon_loaded:
            return
        self._icon_loaded = True

        icon_path = self.data.get("icon")
        icon_size = ICON_SIZE
        if isinstance(icon_path, str) and icon_path.lower().endswith(".gif"):
            gif_path = icon_path
            if not os.path.isabs(gif_path):
                project_root = Path(__file__).resolve().parents[4]
                gif_path = os.path.join(str(project_root), gif_path)
            self._gif_movie = QMovie(gif_path)
            self._gif_movie.setScaledSize(QSize(icon_size, icon_size))
            self.icon_widget.setMovie(self._gif_movie)
            self._gif_movie.start()
            return

        # 本地图片文件：交给工作线程解码（读盘 + 解码 + 缩放都不占界面线程），
        # 解完由 _on_icon_decoded 回调上屏
        local = self._local_icon_path(icon_path)
        if local:
            _request_icon_async(self, local, icon_size)
            return

        icon = self._resolve_icon(icon_path, icon_size)
        if hasattr(icon, "icon"):          # FluentIcon 枚举
            icon = icon.icon()
        pixmap = icon.pixmap(QSize(icon_size, icon_size)) if isinstance(icon, QIcon) \
            else QPixmap()
        self.icon_widget.setPixmap(pixmap)

    @staticmethod
    def _local_icon_path(icon) -> str:
        """图标字段指向本地图片文件时返回它的绝对路径，否则返回空串

        和 `_resolve_icon` 里的候选路径规则一致（相对路径按"程序根目录"找）。
        """
        if not isinstance(icon, str) or not icon:
            return ""
        if not any(icon.lower().endswith(ext) for ext in
                   (".png", ".jpg", ".jpeg", ".svg", ".webp", ".bmp")):
            return ""
        candidates = [icon]
        if not os.path.isabs(icon):
            project_root = Path(__file__).resolve().parents[4]
            candidates.append(os.path.join(str(project_root), icon))
        for path in candidates:
            if os.path.isfile(path):
                return path
        return ""

    def _set_icon_pixmap(self, pixmap: QPixmap):
        """（解码回调 / 缓存命中）把图贴到图标控件上

        ⚠️ 两道校验：卡片可能在这几十毫秒里被**回收复用**成别的资源，或者已经离开
           搜索页把图标卸了 —— 那种情况下不能再贴，否则会显示成"上一条资源的图标"。
        """
        if not self._icon_loaded or self._gif_movie is not None:
            return
        if pixmap is None or pixmap.isNull():
            # 解码失败：退回默认图标（和 _resolve_icon 的兜底一致）
            fallback = FIF.APPLICATION.icon()
            self.icon_widget.setPixmap(fallback.pixmap(QSize(ICON_SIZE, ICON_SIZE)))
            return
        self.icon_widget.setPixmap(pixmap)

    def _unload_icon(self):
        """把图标资源丢掉（GIF 停播、pixmap 清空）

        离开搜索页 / 卡片被复用调走时调用。**只丢图，不销毁控件**（卡片留着复用）。
        """
        if not self._icon_loaded:
            return
        self._icon_loaded = False
        if self._gif_movie is not None:
            try:
                self._gif_movie.stop()
            except Exception:
                pass
            self._gif_movie = None
        try:
            self.icon_widget.setMovie(None)
            self.icon_widget.clear()
        except RuntimeError:
            pass

    def is_icon_loaded(self) -> bool:
        return bool(self._icon_loaded)

    # ---------- 快捷按钮 ----------
    # ---------- 尺寸 / 文字 ----------
    def set_card_width(self, width: int):
        """由 ResponsiveGrid 调用：按算出来的列宽调整卡片"""
        width = int(width)
        if width == self._card_width or width <= 0:
            return
        self._card_width = width
        self.setFixedWidth(width)
        self._refresh_texts()

    def _refresh_texts(self):
        """按当前卡片宽度重新做省略（宽度变了必须重算，否则文字会溢出）

        ⚠️ 省略是**按实际宽度算出来**的：卡片被挤窄（网格视图一行 6 个）时，
           名称/简介放不下的部分会自动变成 "…"。
        """
        inner = self._card_width - CARD_PADDING * 2
        if is_compact_view():
            # 小卡片右上角只剩收藏按钮
            reserved = 12 + 22 + 4
            gap = 10
        else:
            # 整行 - 图标 - 间距 - 右上角两个按钮（@ 和 收藏）
            reserved = 12 + 28 * 2 + 6
            gap = 12
        name_width = inner - ICON_SIZE - gap - reserved
        self.name_label.setText(self._elide(
            str(self.data.get("name", "")), self.name_label.fontMetrics(), name_width))
        self.desc_label.setText(self._elide_multiline(
            str(self.data.get("description", "")), self.desc_label.fontMetrics(),
            inner, DESC_LINES))

    def _elide(self, text: str, fm: QFontMetrics, width: int) -> str:
        """单行省略"""
        if width <= 0 or not text:
            return text
        return fm.elidedText(text, Qt.ElideRight, width)

    def _elide_multiline(self, text: str, fm: QFontMetrics, width: int,
                         lines: int = 2) -> str:
        """把文字按宽度切成最多 lines 行，放不下就在最后一行加省略号

        中文没有空格，所以按字符逐个累加算宽度，比按词切更准。
        """
        text = str(text or "").replace("\n", " ").strip()
        if not text or width <= 0:
            return ""

        rows = []
        current = ""
        consumed = 0
        for ch in text:
            if fm.horizontalAdvance(current + ch) > width:
                rows.append(current)
                current = ch
                if len(rows) == lines:
                    break
            else:
                current += ch
            consumed += 1

        if len(rows) < lines and current:
            rows.append(current)
            consumed = len(text)

        if consumed < len(text) and rows:
            last = rows[-1]
            while last and fm.horizontalAdvance(last + "…") > width:
                last = last[:-1]
            rows[-1] = last + "…"

        return "\n".join(rows)

    def _make_quick_button(self, url, icon, tooltip):
        """创建卡片右下角的小图标按钮（没地址就不创建）"""
        url = str(url or "").strip()
        if not url.startswith(("http://", "https://")):
            return None
        button = IconButton(None, f"{tooltip}\n{url}\n"
                                  f"{_card_text('card_link_tip', CTRL_TIP_FALLBACK)}",
                            26, 16, self)        # 用跟随主题的方式设图标：主题一变它自己会重取
        button.setThemedIcon(icon)
        # ⚠️ 三路取或（见 _open_link）：控件按下时记的 / 全局观察器记的 / 此刻还按着的 ——
        #    只要能证明用户按住过 Ctrl 就静默打开，宁可多静默一次
        button.clicked.connect(
            lambda u=url, t=tooltip, b=button: self._open_link(u, t, b._press_ctrl))
        return button

    def _open_link(self, url: str, label: str, ctrl_at_press: bool = False):
        """打开卡片上的外部链接（同时记一条操作日志）

        左键 = 浏览器到前台；Ctrl+左键 = 浏览器打开但不切走当前程序。
        """
        # ctrl_at_press=True 就直接强制后台；否则交给 open_url 自己判断
        open_url(url, label, background=True if ctrl_at_press else None)

    def _make_favorite_button(self):
        """收藏按钮（便签/标签图标，收藏后变为主题色）"""
        button = IconButton(None, _card_text("card_favorite_add", "Add to favorites"), 26, 16, self)
        button.clicked.connect(lambda: self.favorite_toggled.emit(self.resource_code()))
        self._update_favorite_button(button)
        return button

    def _update_favorite_button(self, button=None):
        button = button or getattr(self, "favorite_button", None)
        if button is None:
            return
        if self._favorite:
            button.set_icon(tinted_icon(FIF.TAG, QColor(themeColor()), 16))
            button.set_tooltip(_card_text("card_favorite_added", "Saved (click to remove)"))
        else:
            # ⚠️ 未收藏时也要显式染色：直接用 FIF.TAG 的话颜色按当前主题定死，主题一变
            #    （尤其深→浅）就留在旧颜色上、在卡片上几乎看不见
            button.set_icon(tinted_icon(FIF.TAG, icon_color(), 16))
            button.set_tooltip(_card_text("card_favorite_add", "Add to favorites"))

    def resource_code(self) -> str:
        """本卡片对应的资源编码（优先 code，没有就退化成 id）"""
        return str(self.data.get("code") or self.data.get("id") or "")

    def is_favorite(self) -> bool:
        return self._favorite

    def set_favorite(self, value: bool):
        """外部同步收藏状态（不发送信号）"""
        value = bool(value)
        if value == self._favorite:
            return
        self._favorite = value
        self._update_favorite_button()

    # ---------- 选择模式 ----------
    def set_selection_mode(self, enabled: bool):
        """选择模式：右上角换成勾选框，官网/GitHub 按钮隐藏，点卡片即勾选"""
        enabled = bool(enabled)
        self._selection_mode = enabled
        self.favorite_button.setVisible(not enabled)
        self.select_checkbox.setVisible(enabled)
        for button in (self.github_button, self.url_button,
                       getattr(self, "mention_button", None)):
            if button is not None:
                button.setVisible(not enabled)
        if not enabled:
            self.set_selected(False)
            # 退出选择模式时按当前视图决定谁该显示（网格视图里它们本来就该藏着）
            self._apply_view_mode()

    def is_selection_mode(self) -> bool:
        return self._selection_mode

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, value: bool):
        value = bool(value)
        if value == self._selected:
            return
        self._selected = value
        self.select_checkbox.blockSignals(True)
        self.select_checkbox.setChecked(value)
        self.select_checkbox.blockSignals(False)

    def _on_checkbox_changed(self, state):
        self._selected = bool(state)
        self.selection_toggled.emit(self.resource_code(), self._selected)

    def toggle_selected(self):
        self.set_selected(not self._selected)
        self.selection_toggled.emit(self.resource_code(), self._selected)

    # ---------- 悬浮反馈 ----------
    def _on_hover_value(self, value):
        self._hover_alpha = float(value)
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def _animate_hover(self, target: float):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_alpha)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def paintEvent(self, event):
        """先画卡片本体，再叠一层中性灰高亮 —— 保留 qfluentwidgets 原本的圆角/边框

        用灰色而不是主题色：卡片悬浮是"变亮一点"的反馈，涂主题青色会显得很跳。
        """
        super().paintEvent(event)
        if self._hover_alpha <= 0.01:
            return
        dark = isDarkTheme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 深色主题：叠一层白 → 卡片比原色更亮更灰；浅色主题：叠一层黑 → 压暗
        color = QColor(255, 255, 255) if dark else QColor(0, 0, 0)
        color.setAlpha(int(self._hover_alpha * (34 if dark else 20)))
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 8, 8)
        painter.end()

    def _divider_style(self) -> str:
        """根据当前主题返回分割线样式"""
        if isDarkTheme():
            return "background-color: rgba(255, 255, 255, 130);"
        return "background-color: rgba(0, 0, 0, 25);"

    def _apply_divider_style(self, force: bool = False):
        """只在主题真的变了才重设样式表（setStyleSheet 会触发整棵子树 polish，滚动时掉帧）"""
        if not hasattr(self, "divider"):
            return
        dark = isDarkTheme()
        if not force and dark == self._divider_dark:
            return
        self._divider_dark = dark
        self.divider.setStyleSheet(self._divider_style())

    def changeEvent(self, event):
        """主题切换时重新应用分割线颜色和图标颜色"""
        super().changeEvent(event)
        self._apply_divider_style()
        self.refresh_theme()

    def showEvent(self, event):
        """显示时重新确认分割线颜色, 避免初始化时主题未生效"""
        super().showEvent(event)
        self._apply_divider_style()
        self.refresh_theme()

    def refresh_theme(self, force: bool = False):
        """按当前主题重新给卡片上的图标染色

        ⚠️ 主题变化时**必须**调它，否则图标会保持建卡时的颜色（深色下建卡 → 切浅色 →
           白色图标留在白卡片上，等于消失）。force=True 绕过去重，用于换"组件配色"。
        """
        dark = isDarkTheme()
        if not force and getattr(self, "_icons_dark", None) == dark:
            return
        self._icons_dark = dark

        self._update_favorite_button()
        # 外链按钮和 @ 按钮内部会自己按主题重取（setThemedIcon + 守卫），这里推它们一把
        for name in ("github_button", "url_button", "mention_button"):
            button = getattr(self, name, None)
            if button is not None:
                button._reapply_themed_icons()

    def mousePressEvent(self, event):
        if self._selection_mode:
            # 选择模式下点卡片 = 勾选，不进详情
            self.toggle_selected()
            event.accept()
            return
        self.card_clicked.emit(self.data)
        super().mousePressEvent(event)

    def _resolve_icon(self, icon, size: int):
        """根据 icon 字段解析: 本地图片路径 > FIF 枚举名 > 关键字映射 > 默认 APP"""
        if icon is None:
            return FIF.APPLICATION
        if hasattr(icon, "icon"):
            return icon
        if isinstance(icon, str):
            # 本地图片路径
            if any(icon.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".svg", ".webp", ".bmp", ".gif")):
                # 检查缓存
                cache_key = icon
                if cache_key in _icon_cache:
                    return _icon_cache[cache_key]

                candidate_paths = [icon]
                if not os.path.isabs(icon):
                    project_root = Path(__file__).resolve().parents[4]
                    candidate_paths.append(os.path.join(str(project_root), icon))

                for path in candidate_paths:
                    pixmap = _load_local_icon(path, size)
                    if not pixmap.isNull():
                        result = QIcon(pixmap)
                        _icon_cache[cache_key] = result
                        return result
                return FIF.APPLICATION

            # FIF 枚举名
            if hasattr(FIF, icon):
                return getattr(FIF, icon)
            mapping = {
                "github": FIF.GITHUB,
                "web": FIF.GAME,
                "tool": FIF.TOOLS,
                "app": FIF.APPLICATION,
                "code": FIF.CODE,
                "download": FIF.DOWNLOAD,
                "search": FIF.SEARCH,
                "setting": FIF.SETTING,
            }
            return mapping.get(icon.lower(), FIF.APPLICATION)
        return FIF.APPLICATION
