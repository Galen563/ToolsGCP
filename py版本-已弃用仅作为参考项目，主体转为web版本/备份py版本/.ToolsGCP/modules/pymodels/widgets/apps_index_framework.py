"""应用索引框架

加载 JSON 索引（开发阶段本地、正式阶段 GitHub），按指定排序把数据渲染成卡片网格：
先显示加载动画，程序页面启动后再异步渲染。

⚠️ 性能相关约定：
  1. **窗口化渲染**：只给"和视口相交的那一段"建/绑卡片，滚出窗口的卡片 hide() 收进本网格
     的闲置池复用，活着的 AppCard 数量是常数，滚动条行程按**全量条数**算。
     ⚠️ **卡片永远不换父级**：setParent(None) 会让控件在一瞬间变成顶层窗口。
  2. 图标**跟着卡片一起上屏**（_assign_card 里立刻 _load_icon()，本地图走工作线程解码）；
     被回收的卡片立刻 _unload_icon()；**主题切换不重建**，只重新染色（见 refresh_theme）。

分组（全部 / 类别 / 按字母）走同一套窗口：每组是「标题 + 网格」，组内条数可以为 0，
但高度照样参与计算。
"""

import os
import time

from PyQt5.QtCore import Qt, QTimer, QSize, QPoint, pyqtSignal
from PyQt5.QtGui import QPixmap, QTransform, QMovie
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
)
from qfluentwidgets import (
    CaptionLabel,
    BodyLabel,
    FluentIcon as FIF,
    isDarkTheme,
)

from ..constants import IMAGES_DIR
from ..core import resource_schema
from . import app_card as card_module
from .app_card import AppCard
from .responsive_grid import ResponsiveGrid


def _code_of(data: dict) -> str:
    """取一条资源的主键（编码优先，退回 id）"""
    if not isinstance(data, dict):
        return ""
    return str(data.get("code") or data.get("id") or "")


def _alive(widget) -> bool:
    """控件还活着吗（PyQt 里底层 C++ 对象被删掉后再访问会抛 RuntimeError）"""
    try:
        import sip
        return not sip.isdeleted(widget)
    except Exception:
        return True


# 旧版"分批加载"的批大小（窗口化后不再分批，has_more() 恒为 False，仅兼容旧调用）
PAGE_SIZE = 35

# 网格中一张卡片的最小宽度：低于它就减一列
MIN_CARD_WIDTH = card_module.CARD_WIDTH

# 页面已经显示时，先让加载动画露个面再渲染卡片
LOADING_DELAY_MS = 150

# 首屏"保持"时间：先让加载动画顶着，把这一屏卡片 + 图标都备好再一次性显示（否则卡片先
# 出来、图标一个个蹦上去）；ready 压在这之后，最多等 FIRST_PAINT_HOLD_MS
FIRST_PAINT_HOLD_MS = 700
FIRST_PAINT_POLL_MS = 30

# 加载 UI 的**硬上限**：正常情况下等"卡片 + 图标都就位"就收（通常几十到两三百毫秒）。
# ⚠️ 这只是防止极端情况（比如图标目录坏掉、某个网格量不出高度）让转圈永远转下去的安全网，
#    不是"到点就撤"—— 真正决定何时撤的是 _poll_first_paint 里的完成判断（需求 R3）。
LOADING_MAX_WAIT_MS = 8000

# 窗口上下各多留几屏的卡片（配合"位移半屏才重排"的阈值，滚动中看不到空白格）
BUFFER_SCREENS = 1.8

# 滚动"停顿"这么久之后才真正重排窗口（毫秒）：反复重启定时器，手一停就排一次
WINDOW_SETTLE_MS = 90

# ⚠️ 安全垫：窗口已铺到"离锚点这么多屏"时不能再推迟了 —— 再滚就要露白。上下各铺
#    BUFFER_SCREENS 屏，取 1.5 屏留了余量，够分帧绑定在露白之前补齐
WINDOW_URGENT_RATIO = 1.5

# 一次重排里最多"绑定"多少张卡片（新建 + 复用闲置卡一起算，整轮重排共享预算）
MAX_ASSIGN_PER_PASS = 4

# 闲置卡片总量上限：滚出窗口的卡片藏在自己网格里等复用，翻遍整个库后不能无限堆积
MAX_IDLE_CARDS = 120

# 图标：数据一绑到卡片上就**立刻**请求（_assign_card / request_visible_icons）。
# ⚠️ 这里删掉了旧的"延迟 + 25ms 一小口"排队（DROP_INTERVAL_MS / DROP_BATCH /
#    ICON_BUDGET_MS / ICON_PRELOAD_SCREENS / SCROLL_ICON_BUDGET_MS）：那套限流会让卡片先出来、
#    图标再一张张蹦上去（肉眼可见地等 1~2 秒）。本地图的读盘 + 解码 + 缩放是在**工作线程**里做的
#    （见 app_card._request_icon_async），界面线程只做 QPixmap.fromImage，本来就挡不住绘制。

# 加载动画使用的 GIF（相对 .ToolsGCP/images）
LOADING_GIF_NAME = "load.gif"


def _code_of(data: dict) -> str:
    """取一条数据的资源编码（没有 code 就退化成 id）"""
    return str((data or {}).get("code") or (data or {}).get("id") or "")


class LoadingWidget(QWidget):
    """加载动画：优先播放 images/load.gif，缺失或损坏时回退为旋转图标 + 省略号文字"""

    GIF_SIZE = 110              # load.gif 的显示尺寸（原图 500x500）
    FALLBACK_ICON_SIZE = 48
    LOADING_TEXT = "正在加载"    # 下面那行动态文字的前缀
    DOT_INTERVAL_MS = 130       # 点号切换间隔（.→..→... 循环，要快一点才灵动）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._dot_count = 0
        self._base_pixmap = None
        self._movie = None
        self.text_label = None
        self._rotate_timer = None
        self._dot_timer = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(16)

        self.icon_label = QLabel(self)
        self.icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_label, 0, Qt.AlignCenter)

        if not self._start_gif():
            self._setup_fallback()

    # ---------- 加载动画 ----------
    def _start_gif(self) -> bool:
        """播放 load.gif，成功返回 True"""
        gif_path = os.path.join(IMAGES_DIR, LOADING_GIF_NAME)
        if not os.path.exists(gif_path):
            return False
        movie = QMovie(gif_path)
        if not movie.isValid():
            return False
        movie.setScaledSize(QSize(self.GIF_SIZE, self.GIF_SIZE))
        self.icon_label.setFixedSize(self.GIF_SIZE, self.GIF_SIZE)
        self.icon_label.setMovie(movie)
        movie.start()
        self._movie = movie
        # GIF 下面也要有动态点号文字
        self._setup_text()
        return True

    def _setup_fallback(self):
        """GIF 不可用时的备用动画：旋转的同步图标 + 省略号文字"""
        self._base_pixmap = FIF.SYNC.icon().pixmap(
            QSize(self.FALLBACK_ICON_SIZE, self.FALLBACK_ICON_SIZE)
        )
        self.icon_label.setFixedSize(self.FALLBACK_ICON_SIZE, self.FALLBACK_ICON_SIZE)
        self.icon_label.setPixmap(self._base_pixmap)

        self._setup_text()

        # 旋转定时器（每 30ms 旋转 10 度）
        self._rotate_timer = QTimer(self)
        self._rotate_timer.timeout.connect(self._rotate)
        self._rotate_timer.start(30)

    def _setup_text(self):
        """「正在加载.」→「正在加载..」→「正在加载...」循环"""
        self._dot_count = 1
        self.text_label = QLabel(self.LOADING_TEXT + ".", self)
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setStyleSheet(self._text_style())
        self.layout().addWidget(self.text_label, 0, Qt.AlignCenter)

        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._update_dots)
        self._dot_timer.start(self.DOT_INTERVAL_MS)

    def _text_style(self) -> str:
        color = "#FFFFFF" if isDarkTheme() else "#1F2329"
        return f"color: {color}; font-size: 14px; background: transparent;"

    def _rotate(self):
        self._angle = (self._angle + 10) % 360
        rotated = self._base_pixmap.transformed(
            QTransform().rotate(self._angle), Qt.SmoothTransformation
        )
        self.icon_label.setPixmap(rotated)

    def _update_dots(self):
        """点号在 . / .. / ... 之间循环（不出现 0 个点，否则会闪一下空的）"""
        self._dot_count = self._dot_count % 3 + 1
        self.text_label.setText(self.LOADING_TEXT + "." * self._dot_count)

    def refresh_theme(self):
        if self.text_label is not None:
            self.text_label.setStyleSheet(self._text_style())

    def stop(self):
        """停止所有动画（组件即将被回收）"""
        for timer in (self._rotate_timer, self._dot_timer):
            if timer is not None:
                timer.stop()
        if self._movie is not None:
            self._movie.stop()
            self._movie = None
            self.icon_label.setMovie(None)


# 分帧建卡两批之间的间隔（毫秒）：让 Qt 有机会把已经摆好的卡片画出来
FILL_CHUNK_DELAY_MS = 6


class AppsIndexFramework(QWidget):
    """应用索引框架

    用法：set_data(items, sort_key="category") / set_sort("all")
    信号：card_clicked(data) 卡片被点击；ready() 首次内容渲染完成。
    """

    card_clicked = pyqtSignal(dict)
    favorite_toggled = pyqtSignal(str)
    selection_toggled = pyqtSignal(str, bool)
    # 「@给AI」按钮（参数：名称, 资源编码）—— 在这里原样往上传
    ai_mention_requested = pyqtSignal(str, str)
    ready = pyqtSignal()

    # 排序选项
    SORT_KEYS = ("all", "category", "az", "za")

    # 一次窗口重排最多**新建**多少张卡片（剩下的分帧继续）：一帧里最贵的就是新建卡片
    # （一张 3~4ms）+ 喂网格，实测那一帧 33~45ms
    MAX_CARDS_PER_PASS = 2

    # 一次窗口重排最多**绑定**多少张卡片（新建 + 复用闲置卡，整轮共享）。⚠️ 复用闲置卡的
    # _assign_card 以前不限量，实测单帧 18ms（够掉一帧），现在两种一起限流
    MAX_ASSIGN_PER_PASS = MAX_ASSIGN_PER_PASS

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list = []
        self._sort_key: str = "all"
        # 分帧建卡的"代"：窗口一重排就 +1，上一代没建完的任务自动作废
        self._fill_generation: int = 0
        self._loading_widget: LoadingWidget = None
        self._ready = False
        self._favorites: set = set()
        self._selection_mode = False
        self._selected: set = set()
        # 编码 -> 卡片：**只作调试记录**（窗口化后同一张卡片会先后绑定不同的资源）
        self._card_map: dict = {}
        # 槽位（每组一个标题 + 一个网格），按位置长期复用
        self._title_slots: list = []
        self._grid_slots: list = []
        # 窗口内卡片列表（旧字段名，兼容外部读取）
        self._pooled_cards: list = []

        # ---- 窗口化渲染的状态 ----
        # 当前铺出来的分组：[(标题, [数据...]), ...]
        self._groups: list = []
        # 槽位 -> {下标: 卡片}：**窗口内**的卡片（卡片从生到死都是那个网格的孩子）
        self._grid_cards: dict = {}
        # 槽位 -> [闲置卡片]：滚出窗口的卡片藏在这儿等着复用
        self._idle: dict = {}
        # 槽位 -> 上一次喂给网格的窗口签名 (start, end, 下标元组)：没变就跳过 set_items
        self._grid_signature: dict = {}
        # 槽位 -> 这一轮窗口要求的 [start, end)：判断"视口内的格子是不是都绑上卡片了"
        # （需求 R3：加载 UI 必须等这些格子全绑好才允许消失）
        self._grid_window: dict = {}
        # 还有多少个"分帧续建"任务没跑完（>0 说明屏幕上的卡片还没铺完）
        self._fill_pending_count: int = 0
        # 上一次排窗口时的视口顶端位置：滚动位移不到半屏就不重排（见 _maybe_apply_window）
        self._window_anchor = None
        # 推迟重排用的"滚动停顿"定时器（见 _maybe_apply_window）
        self._window_timer = QTimer(self)
        self._window_timer.setSingleShot(True)
        self._window_timer.setInterval(WINDOW_SETTLE_MS)
        self._window_timer.timeout.connect(self._apply_window_deferred)
        # 滚动偏移（由页面注入，见 set_scroll_offset）
        self._scroll_offset = 0
        # 框架自己在滚动内容里的 y（滚动条 value 是整页坐标，要减掉它）
        self._content_origin = 0

        # ---- 图标状态 ----
        # 视口（由 SearchInterface 注入）：用来判断"哪些卡片真的看得见"
        self._viewport_widget = None
        self._icons_released = False
        # 用户是不是正在滚（只作为状态记录：图标不再因为滚动而挂起）
        self._scrolling = False
        # 首屏"保持加载动画"的状态（见 _refresh / _poll_first_paint）
        self._hold_first_render = False
        self._first_deadline = 0.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 内容容器（支持分组和平铺两种渲染模式）
        # 注意：这里不能带 parent 构造，否则会重复给 self 设置布局
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(16)
        self.content_layout.setAlignment(Qt.AlignTop)

        outer.addLayout(self.content_layout, 1)

        # 空状态
        self.empty_label = CaptionLabel("", self)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.hide()
        outer.addWidget(self.empty_label)

    # ================= 虚拟化窗口 / 图标加载 =================
    def set_viewport(self, widget):
        """告诉框架"可视区域是谁"（SearchInterface 的 QScrollArea），用于算哪些卡片可见"""
        self._viewport_widget = widget

    def release_icons(self):
        """把**所有**卡片的图标资源放掉（离开搜索页时调）：GIF 停播、pixmap 清空，控件留着复用"""
        self._icons_released = True
        for card in self._all_cards():
            try:
                card._unload_icon()
            except RuntimeError:
                pass

    def restore_icons(self):
        """回到搜索页：重新允许加载图标，并把视口里那几张立刻补上"""
        self._icons_released = False
        self.request_visible_icons()

    def request_visible_icons(self):
        """把"进入视口"的卡片图标**立刻**加载（不排队、不按节奏一小口一小口来）

        ⚠️ 判断依据用**卡片在视口坐标系里的位置**，不能用 isVisible()：页面没显示、
           控件被父级藏着时 isVisible() 一律是 False，那就一张图都不会加载。
        ⚠️ 这里只是"发请求"：本地图的读盘 + 解码 + 缩放都在工作线程里（见
           app_card._request_icon_async），命中缓存的图直接上屏。
        """
        if self._icons_released:
            return
        viewport = self._viewport_widget
        cards = self._all_cards()
        if not cards:
            return
        if viewport is None:
            # 没有视口信息（比如测试脚本单独用框架）→ 全部加载
            for card in cards:
                if not card.is_icon_loaded():
                    self._load_card_icon(card)
            return

        try:
            rect = viewport.viewport().rect()
            target = viewport.viewport()
        except Exception:
            rect, target = None, None

        for card in cards:
            if card.is_icon_loaded():
                continue
            if rect is None:
                self._load_card_icon(card)
                continue
            try:
                if card.isHidden():
                    continue
                if rect.contains(card.mapTo(target, QPoint(0, 0))):
                    self._load_card_icon(card)
            except (RuntimeError, TypeError):
                continue

    @staticmethod
    def _load_card_icon(card):
        """给一张卡片发图标请求（卡片已经销毁就算了）"""
        try:
            card._load_icon()
        except RuntimeError:
            pass

    def set_scrolling(self, scrolling: bool):
        """记录"用户正在滚"这个状态

        ⚠️ 旧版这里会**挂起**图标加载（滚动中一张不加载，停下来才慢慢喂），结果是滚动时
           新滚进视口的卡片一直是空白、要等 1~2 秒。现在图标在卡片绑定那一刻就请求了，
           工作线程解码 + 命中缓存直接上屏，这里只留状态位（_apply_window 会读它）。
        """
        self._scrolling = bool(scrolling)

    def _load_visible_icons_now(self):
        """把当前视口里还没图标的卡片立刻补上（保留旧接口名）"""
        self.request_visible_icons()

    # ---------- 就绪状态 ----------
    @property
    def is_ready(self) -> bool:
        """首次内容是否已经渲染完成"""
        return self._ready

    @property
    def items(self) -> list:
        """当前承载的完整数据列表（搜索过滤时用作原始数据源）"""
        return list(self._items)

    # ---------- 数据 ----------
    def set_data(self, items: list, sort_key: str = None, show_loading: bool = True):
        """设置数据并异步加载（先显示加载动画）

        sort_key 与数据一起给出时只渲染一次，避免"设数据 + 设排序"重复渲染。
        ⚠️ show_loading=False：不显示转圈动画，直接同步刷新 —— 数据没变、只是卡片尺寸
           变了（搜索页"磁贴 ⇄ 网格"切换）时弹加载 GIF 纯属噪音。
        """
        self._items = list(items) if items else []
        self._reset_batch()
        if sort_key is not None and sort_key in self.SORT_KEYS:
            self._sort_key = sort_key
        if show_loading:
            self._show_loading()
        else:
            self._refresh()

    def update_data(self, items: list):
        """静默更新数据（不显示加载动画）：窗口外的卡片本来就不存在，窗口内按位置重绑，
        内容没变的卡片 set_data 会直接返回，所以点筛选不会卡
        """
        self._items = list(items) if items else []
        self._reset_batch()
        self._refresh()

    def _reset_batch(self):
        """换了一批数据（搜索/筛选/换排序）：窗口和图标状态都从头来"""
        self._window_anchor = None
        self._icons_released = False

    def set_sort(self, sort_key: str):
        """设置排序键：all / category / az / za"""
        if sort_key not in self.SORT_KEYS:
            sort_key = "all"
        if sort_key == self._sort_key:
            return
        self._sort_key = sort_key
        self._reset_batch()
        self._show_loading()

    def show_loading_then(self, callback, delay_ms: int = None):
        """先亮出"中央加载动画"，过 delay_ms 再执行 callback（再干重活，用于整页重建）

        ⚠️ 整段重活必须交给 callback：_refresh() 一进来就会把加载控件收掉，外面再补一次
           刷新的话加载动画会"刚建好就被拆"。
        """
        self._show_loading(callback=callback, delay_ms=delay_ms)

    def _show_loading(self, callback=None, delay_ms: int = None):
        """显示加载动画，延迟刷新以让 UI 先渲染

        callback 为空时默认刷新自己；传了 callback 就由调用方负责干完活再收尾。
        ⚠️⚠️ 加载动画**不进布局**，而是"盖在滚动视口上"：content_layout 的高度 = 全部
           卡片的总高度（虚拟化下三五千像素），加进布局居中的话转圈会被摆在**整个内容
           的正中间**，而视口在第一屏、根本看不到它。
        """
        # 槽位（标题 + 网格）是长期复用的，只把它们藏起来；不能清布局，清了会把卡片带走
        for slot in self._title_slots + self._grid_slots:
            try:
                slot.hide()
            except RuntimeError:
                pass
        self._hide_loading_widget()
        parent = None
        try:
            viewport = self._viewport_widget
            parent = viewport.viewport() if viewport is not None else None
        except Exception:
            parent = None
        self._loading_widget = LoadingWidget(parent if parent is not None else self)
        # 记下"这次转圈从什么时候开始"：_poll_first_paint 用它算 LOADING_MAX_WAIT_MS 安全网
        self._loading_since = time.perf_counter()
        self._place_loading_widget()
        self._loading_widget.show()
        self._loading_widget.raise_()
        work = callback if callback is not None else self._refresh
        if delay_ms is None:
            # 窗口还没显示（启动预加载阶段）时立即执行，不必等待；
            # 页面已经显示时延迟一下，让用户看到加载动画。
            delay_ms = LOADING_DELAY_MS if self.isVisible() else 0
        QTimer.singleShot(delay_ms, work)

    def _place_loading_widget(self):
        """把加载动画摆到**看得见的那块区域**正中（见 _show_loading 的说明）

        ⚠️ 需求："切排序 / 切视图时加载动画只盖下面一堆卡片，上方的搜索框和工具栏不能藏"。
           所以这里铺的是**框架自己那一块**（apps_framework 从工具栏下方开始），
           而不是整个 scroll viewport —— 铺满 viewport 会把搜索框、排序、视图按钮一起盖掉。
        """
        widget = self._loading_widget
        if widget is None:
            return
        try:
            if widget.parent() is not self:
                # 父控件是滚动视口：只铺"框架自己"在视口里的那一块（搜索框/工具栏留在上面）
                host = widget.parent()
                rect = self._region_in_viewport(host)
                widget.setGeometry(*rect)
                return
            viewport = self._viewport_widget
            if viewport is None:
                widget.setGeometry(0, 0, self.width(), max(1, self.height()))
                return
            # 父控件是 self：用**自己的整块**（不含页面上方的搜索框/工具栏）
            widget.setGeometry(0, 0, max(1, self.width()), max(1, self.height()))
        except Exception:
            pass

    def _region_in_viewport(self, viewport) -> tuple:
        """算出"框架自己"在视口坐标系里占的那块矩形（返回 (x, y, w, h)）

        ⚠️ 必须用 mapTo(视口)：滚动内容整体被挪负，直接拿 self.y() 会带上滚动量。
        ⚠️ 高度按**框架当前铺出来的部分**算（min(自身高度, 视口剩余空间)）：虚拟化下
           content_layout 的高度是全部卡片的总高（三千多像素），照搬会把浮层撑到屏幕外；
           同时也不能小到只剩几像素，那样转圈看不见 —— 至少给加载控件一个"够放下自己"的高度。
        """
        top_left = self.mapTo(viewport, self.rect().topLeft())
        x = max(0, int(top_left.x()))
        y = max(0, int(top_left.y()))
        width = max(1, min(int(self.width()), int(viewport.width()) - x))
        # 视口里从 y 往下还剩多少（浮层不该越过视口底边）
        remaining = max(1, int(viewport.height()) - y)
        height = max(1, min(int(self.height()), remaining))
        # 兜底：框架还没量出高度（比如首屏保持期间网格被藏起来）时，铺满剩余视口，
        # 保证转圈有地方待、也保证它盖住的正是"卡片该出现的那块区域"
        if height < 120:
            height = remaining
        return x, y, width, height


    def _detach_pooled_cards(self):
        """把上一轮渲染的卡片从旧网格里摘出来，挂回 self 交给复用池保管

        ⚠️ 挂回 self 而不是 setParent(None)：后者会让卡片变成顶层窗口，失去引用后被 GC
           销毁，之后复用会抛 "wrapped C/C++ object of type AppCard has been deleted"。
        """
        for card in getattr(self, "_pooled_cards", []):
            try:
                card.setParent(self)
                card.hide()
            except RuntimeError:
                pass

    def _hide_loading_widget(self):
        """把加载动画收掉（复用槽位时只藏不清）"""
        if self._loading_widget is not None:
            self._loading_widget.stop()
            try:
                # 它不在布局里（盖在视口上），先 hide() 再 deleteLater()；
                # **不要** setParent(None)，那会让正在显示的转圈控件瞬间变成顶层窗口闪一下
                self._loading_widget.hide()
                self._loading_widget.deleteLater()
            except RuntimeError:
                pass
            self._loading_widget = None

    def _clear_layout(self, layout):
        """清空布局中的所有项（只 hide() + deleteLater，不 setParent(None)）"""
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
            else:
                sub = item.layout()
                if sub is not None:
                    self._clear_layout(sub)

    def _refresh(self):
        """按当前数据和排序刷新视图

        ⚠️ 渲染本身只做"窗口内"的那一屏卡片；图标在卡片绑定那一刻就请求（_assign_card），
           本地图由工作线程解码，界面线程不等它。
        """
        first = not self._ready
        # ⚠️ **有加载动画在场时就保持住**：等这一屏卡片 + 看得见的那几张图标都备好再一次性
        #     显示，否则撤掉动画的那一瞬间屏幕上是一排没有图标的空卡片。
        self._hold_first_render = bool(first or self._loading_widget is not None)
        if not self._hold_first_render and self._loading_widget is not None:
            self._hide_loading_widget()

        # 加载动画那会儿布局被设成居中，这里要改回顶部对齐（居中会让网格只按 sizeHint
        # 取宽，一行只剩 1 列）。
        # ⚠️ 保持期间**不能改**：那会儿 content_layout 的对齐就是转圈动画的位置；真正的
        #    AlignTop 由 _poll_first_paint 在"铺窗口"那一步补上。
        if not self._hold_first_render:
            self.content_layout.setAlignment(Qt.AlignTop)

        if not self._items:
            self.empty_label.show()
            self._render([])
        else:
            self.empty_label.hide()
            if self._sort_key == "category":
                self._render(self._category_groups())
            elif self._sort_key in ("az", "za"):
                self._render(self._letter_groups())
            else:
                self._render(self._flat_groups())

        if self._hold_first_render:
            self._first_deadline = time.perf_counter() + FIRST_PAINT_HOLD_MS / 1000.0
            QTimer.singleShot(FIRST_PAINT_POLL_MS, self._poll_first_paint)
            return

        # 图标：只给"真的在视口里"的卡片排队加载
        self.request_visible_icons()
        self._mark_ready()

    # ---------- 保持加载动画：一次性显示 ----------

    def _poll_first_paint(self):
        """保持期间的轮询：先把这一屏铺出来，再等**看得见的那几张图标**就位

        ⚠️ 分两步是为了躲开一个 Qt 细节：隐藏的控件不参与布局（量出来是 0），所以
           "铺窗口"（要量每个网格的 y）必须发生在网格重新显示之后。
        """
        if self._hold_first_render:
            self._hold_first_render = False
            if self._loading_widget is None and self._ready:
                # 没有加载动画、首屏也早就好了（不该走到这里）→ 直接收工
                return
            for index, (title_text, items) in enumerate(self._groups):
                if index >= len(self._grid_slots):
                    break
                # ⚠️⚠️ 标题必须在这里**显式 show() 回来**：_render 在"保持期间"把标题和网格
                #    都藏起来过（屏幕上不能同时出现加载动画和半截图卡），而这里以前只
                #    show() 了网格 —— 于是分组视图（默认就是「类别」）**永远没有分组标题**，
                #    用户看到的就是"搜索页的 text 消失了（工具 / 游戏 这些组名没了）"。
                self._set_slot_title(index, title_text, bool(items))
                grid = self._grid_slots[index]
                if grid.isHidden():
                    grid.show()
            self._window_anchor = None
            self._apply_window()

        # ⚠️⚠️ 需求 R3：加载 UI **必须等这一屏真的显示好了才隐藏**。
        #   老逻辑只看"视口里的图标有没有贴上"，但**还没绑上卡片的空格子它扫不到**（卡都不存在），
        #   于是 700ms 兜底一到就撤动画 —— 用户看到的就是"加载 UI 没了，可还有一部分卡片正在载入"。
        #   现在必须同时满足下面三条才允许收：
        #     (a) 分帧续建任务已经全部跑完（_fill_pending_count == 0）；
        #     (b) 视口窗口要求的格子都绑上了卡片（_has_unbound_visible_cells）；
        #     (c) 视口里已绑卡片的图标都已真正贴上去（_has_visible_pending_icons）。
        #   兜底时间到点**不再强行隐藏**，只把轮询放慢继续等；真出异常（错过时机）还有
        #   LOADING_MAX_WAIT_MS 的硬上限兜着，不会永远转圈。
        if (self._fill_pending_count > 0
                or self._has_unbound_visible_cells()
                or self._has_visible_pending_icons()):
            waited = time.perf_counter() - getattr(self, "_loading_since", 0.0)
            if waited < LOADING_MAX_WAIT_MS / 1000.0:
                QTimer.singleShot(FIRST_PAINT_POLL_MS, self._poll_first_paint)
                return

        self._hide_loading_widget()
        self.content_layout.setAlignment(Qt.AlignTop)
        self._mark_ready()

    def _has_unbound_visible_cells(self) -> bool:
        """视口窗口里还有没有"该有卡片、但还没绑上"的格子

        ⚠️ 这是 R3 的关键：只扫已有卡片（_has_visible_pending_icons）永远发现不了空格子，
           必须反过来问"这一轮窗口要求摆 [start, end)，其中哪些下标还没在 _grid_cards 里"。
        """
        for slot, window in getattr(self, "_grid_window", {}).items():
            try:
                start, end = window
            except Exception:
                continue
            bound = self._grid_cards.get(slot) or {}
            for index in range(int(start), int(end)):
                if index not in bound:
                    return True
        return False

    def _has_visible_pending_icons(self) -> bool:
        """视口里还有没有"图已经请求了、但还没真的贴上去"的卡片

        ⚠️ 看的是 _icon_painted 而不是 _icon_loaded：本地图是**工作线程**解码的，
           _load_icon() 一返回 _icon_loaded 就是 True 了，但它其实还在排队解码。
        """
        viewport = self._viewport_widget
        if viewport is None:
            return False
        try:
            rect = viewport.viewport().rect()
            target = viewport.viewport()
        except Exception:
            return False
        for card in self._all_cards():
            try:
                if card.isHidden() or not card.is_icon_loaded() or card.is_icon_painted():
                    continue
            except RuntimeError:
                continue
            try:
                if rect.contains(card.mapTo(target, QPoint(0, 0))):
                    return True
            except (RuntimeError, TypeError):
                continue
        return False

    def _mark_ready(self):
        """宣布"首屏内容加载完成"（只发一次）"""
        if self._ready:
            return
        self._ready = True
        self.ready.emit()

    # ================= 渲染：窗口化（卡片不换父级） =================
    #   · 每个网格自己持有一小撮卡片，出窗口就 hide()（收进闲置池），要腾内存也只
    #     deleteLater() 自己的孩子 —— 全程不 setParent（它会瞬间产生顶层窗口）；
    #   · 槽位位置交给 Qt 布局：框架只把网格的固定高度设成"这一组一共多少条"；
    #   · 滚动带阈值：位移不到半屏不重排，窗口上下各多留 BUFFER_SCREENS 屏。
    def _render(self, groups):
        """铺出 groups，并且只给"和视口相交"的那一段条目建卡片"""
        groups = [(title, list(items)) for title, items in (groups or [])]
        self._groups = groups
        # 内容换代了：每个网格上一次的窗口签名全部作废（否则会被当成"没变"跳过 set_items）
        self._grid_signature = {}
        count = len(groups)
        self._ensure_slots(count)
        self._hide_unused_slots(count)

        for index, (title_text, items) in enumerate(groups):
            self._set_slot_title(index, title_text, bool(items))
            # ⚠️ 必须把网格 show() 回来：_show_loading() 会把**所有**槽位 hide() 掉，而 show()
            # 只有这里补 —— 少这一句，换一次排序整页就塌成空白（滚动条行程变 0）。
            # ⚠️⚠️ 首屏保持期间相反：标题和网格都要**显式藏起来**，否则 _ensure_slots() 才 new
            #    出来的网格会跟着父控件一起显示（屏幕上同时出现加载动画和半截图卡）；也不能
            #    只靠"不调用 show()"，因为 _set_slot_title 里有 title.show()。
            grid = self._grid_slots[index]
            if self._hold_first_render:
                self._title_slots[index].hide()
                grid.hide()
            elif grid.isHidden():
                grid.show()
            # 先把"这一组一共多少条"告诉网格：高度立刻按全量算出来，滚动条行程才完整
            self._reset_grid_window(index, len(items))

        # 内容换代了：窗口里的下标不再代表同一批东西，锚点作废、强制重算
        self._window_anchor = None
        # 布局跑完（Qt 把尺寸落实下去）之后才量得到每个网格真正的 y
        if not self._hold_first_render:
            QTimer.singleShot(0, self._apply_window)

    def resizeEvent(self, event):
        """宽度变了：列数/条宽/行高全都要重算，窗口也跟着重设"""
        super().resizeEvent(event)
        self._window_anchor = None
        # 加载动画是绝对定位的（盖在视口上），跟着重新摆一次
        self._place_loading_widget()
        QTimer.singleShot(0, self._apply_window)

    def showEvent(self, event):
        """从隐藏变可见时重算一次（页面在 QStackedWidget 里藏着时宽度不保证已更新）"""
        super().showEvent(event)
        self._window_anchor = None
        self._place_loading_widget()
        QTimer.singleShot(0, self._apply_window)

    # ---------- 窗口 ----------
    def set_scroll_offset(self, y: int, origin: int = None):
        """注入滚动偏移（QScrollArea 的垂直滚动条 value）

        ⚠️ 滚动过程中**不当场重排窗口**（实测重排那一帧要 30~51ms）：位移不到半屏什么都
           不做；到了半屏就等滚动停下来再排；只有快滚出已铺好的范围才立刻排。
        """
        self._scroll_offset = max(0, int(y or 0))
        if origin is not None:
            self._content_origin = max(0, int(origin))
        self._maybe_apply_window()

    def scroll_offset(self) -> int:
        """滚动条的原始 value（整页坐标）"""
        return self._scroll_offset

    def refresh_window(self):
        """外部（拖动滚动条 / 结果集变化）之后强制重算一次窗口"""
        self._window_anchor = None
        self._stop_window_timer()
        self._apply_window()

    def _stop_window_timer(self):
        try:
            self._window_timer.stop()
        except Exception:
            pass

    def _maybe_apply_window(self):
        """滚动防抖：不到半屏直接返回；够半屏也先"等滚动停下来"再排

        出口：安全垫用完（离锚点超过 WINDOW_URGENT_RATIO 屏）必须立刻排，否则再滚就
        看见空白；其它情况交给 WINDOW_SETTLE_MS 的定时器。
        """
        viewport = self._viewport_widget
        if viewport is None or not self._groups:
            return
        top = self._viewport_top()
        anchor = self._window_anchor
        if anchor is None:
            self._apply_window()
            return

        height = max(1, viewport.viewport().height())
        step = max(60, height // 2)
        if abs(top - anchor) < step:
            return                       # 还没到半屏：连定时器都不用起

        if abs(top - anchor) >= height * WINDOW_URGENT_RATIO:
            # 快滚出已经铺好的范围了：立刻排（分帧绑定会保证单帧不炸）
            self._stop_window_timer()
            self._apply_window()
            return

        # 安全垫还很足：等滚动停下来再排（反复滚动会不断重启这个定时器）
        if not os.environ.get("GCP_NO_DEFER"):
            self._window_timer.start()
        else:
            self._apply_window()

    def _apply_window_deferred(self):
        """滚动停顿之后的那一次重排"""
        if self._viewport_widget is None or not self._groups:
            return
        self._apply_window()

    def _viewport_top(self) -> int:
        """视口顶端在**框架坐标系**里的 y（已减掉框架自己在滚动内容里的偏移）"""
        if self._viewport_widget is None:
            return 0
        try:
            value = self._viewport_widget.verticalScrollBar().value()
        except Exception:
            value = self._scroll_offset
        return int(value) - int(self._content_origin)

    def _own_origin(self) -> int:
        """量一次"自己在滚动内容控件里的 y"（量不到就沿用页面传进来的 origin）

        ⚠️ 直接 mapTo(内容控件) 最稳；不能拿"viewport 里的位置 + 滚动量"凑 ——
           QScrollArea 是把内容控件整体挪负的，加错原点会变成两倍滚动量。
        """
        viewport = self._viewport_widget
        if viewport is None:
            return self._content_origin
        try:
            content = viewport.widget()
            if content is None or content is self:
                return self._content_origin
            pos = self.mapTo(content, QPoint(0, 0))
            if pos.y() >= 0:
                self._content_origin = int(pos.y())
        except Exception:
            pass
        return self._content_origin

    def _apply_window(self):
        """按当前滚动位置决定每一组要显示哪一段（窗口上下各多留 BUFFER_SCREENS 屏）"""
        if not self._groups:
            return
        self._trim_idle()
        # 每一轮窗口重排都算"新的一代"：上一轮没建完的分帧任务自动作废
        self._fill_generation = getattr(self, "_fill_generation", 0) + 1
        # 这一轮重新计数：下面每个槽位真需要续建时会 +1（见 _fill_slot_window）
        self._fill_pending_count = 0
        # ⚠️ 建卡 / 绑卡的预算是**整轮重排共享**的：搜索页按类别排有十来组，若每组都能
        #    新建几张，最坏就是三十张卡挤在同一帧里
        self._pass_created = 0
        self._pass_assigned = 0

        viewport = self._viewport_widget
        if viewport is None:
            # 没有视口信息（探针 / 独立使用）：全部显示，兜底
            for index, (_title, items) in enumerate(self._groups):
                self._fill_slot_window(index, items, 0, len(items))
            self.request_visible_icons()
            return

        height = max(1, viewport.viewport().height())
        top = self._viewport_top()
        bottom = top + height
        buffer_px = int(height * BUFFER_SCREENS)

        for index, (_title, items) in enumerate(self._groups):
            if not items:
                self._release_grid_window(index, 0)
                continue
            grid = self._grid_slots[index]
            metrics = grid.layout_metrics(total_items=len(items))
            columns = max(1, int(metrics["columns"] or 1))
            row_h = max(1, int(metrics["row_height"]) + grid.spacing)
            try:
                grid_y = grid.mapTo(self, QPoint(0, 0)).y()
            except Exception:
                grid_y = 0
            first_row = int((top - buffer_px - grid_y) // row_h)
            last_row = int((bottom + buffer_px - grid_y) // row_h)
            start = max(0, first_row) * columns
            end = min(len(items), (max(0, last_row) + 1) * columns)
            if end <= start or start >= len(items):
                self._release_grid_window(index, len(items))
                continue
            self._fill_slot_window(index, items, start, end)

        self._window_anchor = top
        # 兜底：这一轮窗口里还有没图标的卡片（比如刚被复用、图标已被换掉）就地补上。
        # ⚠️ 新绑定的卡片在 _assign_card 里就已经请求过图标了，这里通常什么都不用做。
        self.request_visible_icons()

    def _fill_slot_window(self, slot: int, items: list, start: int, end: int):
        """把 slot 这一段 [start, end) 的条目摆出来（卡片只在本网格里复用）"""
        grid = self._grid_slots[slot]
        bound = self._grid_cards.setdefault(slot, {})
        idle = self._idle.setdefault(slot, [])

        # 1) 出窗口的卡片：隐藏并收进本网格的闲置池（**不搬家、不删**）
        for index in [i for i in bound if i < start or i >= end]:
            card = bound.pop(index)
            try:
                card.hide()
            except RuntimeError:
                continue
            idle.append(card)

        # 2) 窗口里缺的下标：优先用闲置的，其次新建
        # ⚠️ 必须分帧：滚回顶部 / 拖滚动条跳一大段时可能一次缺几十张卡片，同步全建要
        #    200ms+；而且**新建和复用一起限流**（复用闲置卡的 _assign_card 写文字 / 取
        #    图标 / 定收藏态才是大头）。没绑上的格子暂时空着，但都在缓冲垫里看不到。
        created = 0
        assigned = 0
        pending = False
        for index in range(start, end):
            if index in bound:
                continue
            # 预算按"整轮重排"算（见 _apply_window），所有分组共享
            if (getattr(self, "_pass_assigned", 0) >= self.MAX_ASSIGN_PER_PASS
                    or getattr(self, "_pass_created", 0) >= self.MAX_CARDS_PER_PASS):
                pending = True
                break
            card = idle.pop() if idle else None
            if card is None:
                card = self._make_card(items[index], grid)
                created += 1
                self._pass_created = getattr(self, "_pass_created", 0) + 1
            else:
                card.show()
            self._assign_card(card, items[index])
            bound[index] = card
            assigned += 1
            self._pass_assigned = getattr(self, "_pass_assigned", 0) + 1

        cards = [bound[i] for i in range(start, end) if i in bound]
        # ⚠️ `ResponsiveGrid.set_items` 单次最贵 16ms（逐个 show() + 重排 + 触发父布局），
        #    而滚动途中绝大多数重排这一段压根没变（只是窗口边界挪了一格），不用动网格
        signature = (start, end, tuple(i for i in range(start, end) if i in bound))
        if signature != self._grid_signature.get(slot):
            self._grid_signature[slot] = signature
            grid.set_items(cards, start, len(items))
        # 记下"这一格视口里要求摆哪一段"（见 _has_unbound_visible_cells）
        self._grid_window[slot] = (start, end)
        if pending:
            # 继续建下一批（同一"代"才继续：期间用户又滚了就别管这一批了）
            gen = self._fill_generation
            self._fill_pending_count = getattr(self, "_fill_pending_count", 0) + 1
            # 延迟几毫秒再继续：0ms 会被并进同一次 processEvents，等于没分帧
            QTimer.singleShot(
                FILL_CHUNK_DELAY_MS, lambda s=slot, it=items, a=start, b=end, g=gen:
                self._continue_fill(s, it, a, b, g))

    def _continue_fill(self, slot: int, items: list, start: int, end: int,
                       generation: int):
        """分帧建卡的下一批（中途换过窗口/数据就作废）"""
        if generation != getattr(self, "_fill_generation", 0):
            return
        # 这一次是一帧独立的续建：预算重新给满（见 _apply_window 里共享预算的说明）
        self._pass_created = 0
        self._pass_assigned = 0
        try:
            self._fill_slot_window(slot, items, start, end)
        except RuntimeError:
            return
        finally:
            # ⚠️ 这一批跑完了（_fill_slot_window 里如果还要续建会再 +1）：
            #    减掉自己这一份，计数归零就代表"屏幕上的卡片真的铺完了"
            self._fill_pending_count = max(
                0, getattr(self, "_fill_pending_count", 0) - 1)

    def _assign_card(self, card, data: dict):
        """把一条数据绑到一张卡片上（含收藏 / 勾选态）"""
        code = _code_of(data)
        try:
            card.set_data(data)
            card.set_favorite(code in self._favorites)
            card.set_selection_mode(self._selection_mode)
            if self._selection_mode:
                card.set_selected(code in self._selected)
            else:
                card.set_selected(False)
            # ⚠️ **图标跟卡片一起上屏**：绑定的这一刻就把图标请求发出去，不再等
            #    "进入视口"、"滚动停下来"或 25ms 一小口的排队节奏。
            #    之前那套排队会让卡片先出来、图标要等 1~2 秒才一张张蹦上去（用户可见的空白）。
            #    这里只发请求：本地图仍然是**工作线程解码**（见 app_card._request_icon_async），
            #    界面线程不会被读盘/解码挡住；GIF 也只多一个 QMovie。
            #    ⚠️ 页面明确"放掉图标"期间（release_icons，见「自定义」页离开时的处理）不加载，
            #       那会儿由 restore_icons 统一恢复。
            if not self._icons_released:
                card._load_icon()
        except RuntimeError:
            return
        self._card_map[code] = card

    def _reset_grid_window(self, slot: int, total_items: int):
        """内容换代 / 这一组不在视口附近：把窗口整个收掉，只留"一共多少条"这个高度"""
        grid = self._grid_slots[slot]
        bound = self._grid_cards.setdefault(slot, {})
        idle = self._idle.setdefault(slot, [])
        for card in list(bound.values()):
            try:
                card.hide()
            except RuntimeError:
                continue
            idle.append(card)
        bound.clear()
        # 网格内容被清空了：上一次记的"签名"作废，下次填窗口必须真的调 set_items
        self._grid_signature.pop(slot, None)
        grid.set_items([], 0, total_items)

    def _release_grid_window(self, slot: int, total_items: int):
        """这一组滚远了：收掉卡片（高度仍然按全量算，滚动条不会跳）"""
        self._reset_grid_window(slot, total_items)

    def _drop_grid_cards(self, slot: int):
        """把一个槽位的卡片全部删掉（都是这个网格自己的孩子，删除是安全的）"""
        self._grid_signature.pop(slot, None)
        for card in list(self._grid_cards.pop(slot, {}).values()):
            try:
                card.hide()
                card.deleteLater()
            except RuntimeError:
                pass
        for card in self._idle.pop(slot, []):
            try:
                card.hide()
                card.deleteLater()
            except RuntimeError:
                pass

    def _trim_idle(self):
        """闲置卡片总量封顶：超了就把"闲置最多"的槽位里的删掉（翻遍整个库后也有界）"""
        total = sum(len(v) for v in self._idle.values())
        if total <= MAX_IDLE_CARDS:
            return
        for slot in sorted(self._idle, key=lambda s: -len(self._idle[s])):
            while total > MAX_IDLE_CARDS and self._idle[slot]:
                card = self._idle[slot].pop()
                try:
                    card.hide()
                    card.deleteLater()
                except RuntimeError:
                    pass
                total -= 1

    def loaded_count(self) -> int:
        """当前一共活着的卡片数（窗口内的 + 闲置的）"""
        return len(self._all_cards())

    def has_more(self) -> bool:
        """窗口化之后"全部数据"永远可达，没有"还没加载的批次"（保留以兼容旧调用）"""
        return False

    def load_more(self) -> bool:
        """兼容旧接口：窗口化之后不需要分批，恒返回 False"""
        return False

    def _rendered_cards(self) -> list:
        """当前**在窗口里**的卡片（用户看得见的那批）"""
        cards = []
        for bound in self._grid_cards.values():
            cards.extend(bound.values())
        return [c for c in cards if _alive(c)]

    def _all_cards(self) -> list:
        """所有还活着的卡片（窗口内的 + 闲置的）

        ⚠️ 直接 findChildren(AppCard)：卡片从生到死都是某个网格的孩子，这样既准确又不用
           维护"全局池 + 引用计数"那本账。
        """
        return [c for c in self.findChildren(AppCard) if _alive(c)]

    def window_debug(self) -> dict:
        """给探针用的窗口快照（不参与业务逻辑）"""
        return {
            "groups": [(len(items), self._grid_slots[i].total_items())
                       for i, (_t, items) in enumerate(self._groups)],
            "cards": len(self._all_cards()),
            "visible": len(self._rendered_cards()),
            "scroll_top": self._viewport_top(),
            "anchor": self._window_anchor,
        }

    # ---------- 槽位 ----------
    def _ensure_slots(self, count: int):
        """保证有 count 组「标题 + 网格」，不够就补（多了由 _hide_unused_slots 处理）"""
        while len(self._title_slots) < count:
            title = BodyLabel("", self)
            font = title.font()
            font.setBold(True)
            title.setFont(font)
            title.hide()
            self.content_layout.addWidget(title)
            grid = ResponsiveGrid(self, min_item_width=card_module.CARD_MIN_WIDTH,
                                  spacing=card_module.CARD_SPACING, margin=0,
                                  item_height=card_module.CARD_HEIGHT,
                                  # ⚠️ 列数上限：没有它的话窗口越宽列数越多、每张卡片反而
                                  #    越窄，卡片里的文字就永远卡在同一处被省略
                                  max_columns=card_module.max_columns)
            self.content_layout.addWidget(grid)

            self._title_slots.append(title)
            self._grid_slots.append(grid)
        return count

    def _hide_unused_slots(self, used: int):
        """把这一轮没用到的槽位清空

        ⚠️ 网格**不 hide()**：隐藏会让它的几何变成旧值、把组位置的测量搞坏；这一组不用了
           就直接删掉它的卡片，不存在挂在别处等复用的状态。
        """
        for index in range(used, len(self._title_slots)):
            self._title_slots[index].hide()
            self._drop_grid_cards(index)
            self._grid_slots[index].set_items([], 0, 0)

    def _set_slot_title(self, index: int, title_text, has_items: bool):
        """设置某一组的标题（没有内容就不显示，免得出现"有标题没内容"的空块）"""
        title = self._title_slots[index]
        if title_text is None or not has_items:
            title.hide()
            return
        # ⚠️ 标题后面那个分隔符也要跟语言走：中文用全角「：」，英文用半角「: 」
        suffix = "："
        try:
            from ..core.language_manager import get_current_manager
            manager = get_current_manager()
            if manager is not None:
                text = manager.get_text("common", "group_suffix")
                if text and text != "group_suffix":
                    suffix = str(text)
        except Exception:
            pass
        text = f"{title_text}{suffix}"
        if title.text() != text:
            title.setText(text)
        if title.isHidden():
            title.show()

    def _make_card(self, data: dict, host: QWidget) -> AppCard:
        """新建一张卡片并接好信号（卡片从此就是 host 的孩子，直到被删除）"""
        code = _code_of(data)
        card = AppCard(data, host, is_favorite=code in self._favorites)
        card.card_clicked.connect(self.card_clicked.emit)
        card.favorite_toggled.connect(self.favorite_toggled.emit)
        card.ai_mention_requested.connect(self.ai_mention_requested.emit)
        card.selection_toggled.connect(self._on_card_selection)
        self._card_map[code] = card
        return card

    # ---------- 选择模式 ----------
    # ⚠️ 虚拟化之后这些接口只作用于**窗口内那几十张卡片**：勾选了哪些编码由
    #    self._selected 这份集合说了算，滚进来的卡片由 _assign_card 补上勾选态。
    def set_selection_mode(self, enabled: bool):
        """切换选择模式：所有卡片右上角变成勾选框，官网/GitHub 按钮隐藏"""
        enabled = bool(enabled)
        self._selection_mode = enabled
        if not enabled:
            self._selected.clear()
        for card in self._rendered_cards():
            card.set_selection_mode(enabled)
            if enabled:
                card.set_selected(card.resource_code() in self._selected)
            else:
                card.set_selected(False)

    def is_selection_mode(self) -> bool:
        return self._selection_mode

    def selected_codes(self) -> list:
        """按当前显示顺序返回被勾选的编码"""
        order = [_code_of(item) for item in self._items]
        picked = [c for c in order if c in self._selected]
        # 兜底：有勾选但不在当前显示列表里的，也带上
        picked += [c for c in self._selected if c not in picked]
        return picked

    def selectable_codes(self) -> list:
        return [_code_of(item) for item in self._items]

    def set_selected(self, codes):
        self._selected = {str(c) for c in (codes or [])}
        for card in self._rendered_cards():
            card.set_selected(card.resource_code() in self._selected)

    def select_all(self):
        self._selected = set(self.selectable_codes())
        for card in self._rendered_cards():
            card.set_selected(True)

    def clear_selection(self):
        self._selected.clear()
        for card in self._rendered_cards():
            card.set_selected(False)

    def selection_counts(self):
        selected = self.selectable_codes()
        return len([c for c in selected if c in self._selected]), len(selected)

    def _on_card_selection(self, code: str, selected: bool):
        """卡片上的勾选框被点了"""
        if selected:
            self._selected.add(code)
        else:
            self._selected.discard(code)
        self.selection_toggled.emit(code, selected)

    def set_favorites(self, codes):
        """同步收藏状态（只刷**窗口内**那批用户看得见的卡片，比 findChildren 全量刷更省）"""
        self._favorites = {str(c) for c in (codes or [])}
        for card in self._rendered_cards():
            try:
                card.set_favorite(card.resource_code() in self._favorites)
            except RuntimeError:
                continue


    # ---------- 数据 → 分组 ----------
    def _flat_groups(self):
        return [(None, self._sort_items(self._items, self._sort_key))]

    def _category_groups(self):
        """按类别分组（固定类别顺序，未知类别追加到末尾）

        ⚠️ `category` 是列表：一条资源属于多个类别时在每个类别下都出现一次；一个类别都
           没填的条目归到「其他」，免得从分组视图里整个消失。
        """
        CATEGORY_ORDER = [
            "工具", "游戏", "平台", "编程", "游戏引擎",
            "视频平台", "建筑/设计", "AI", "个性化",
        ]
        groups = {}
        for item in self._items:
            for cat in resource_schema.categories_of(item) or ["其他"]:
                groups.setdefault(cat, []).append(item)

        ordered = [c for c in CATEGORY_ORDER if c in groups]
        ordered += [c for c in groups if c not in CATEGORY_ORDER]
        # ⚠️ 分组标题只是**显示**用的：分组身份仍是规范中文值（筛选/收藏都按它走），
        #    这里按当前语言翻译一下，否则切到英文分组标题还是「工具 / 游戏」
        from ..core.language_manager import translate_term
        return [(translate_term(c), groups[c]) for c in ordered]

    def _letter_groups(self):
        """按首字母分组：A-Z 每个字母一类，非字母开头归到 "#" 并排在最后"""
        groups = {}
        for item in self._items:
            name = str(item.get("name", "")).strip()
            letter = name[:1].upper() if name else "#"
            if len(letter) != 1 or not ("A" <= letter <= "Z"):
                letter = "#"
            groups.setdefault(letter, []).append(item)

        reverse = self._sort_key == "za"
        letters = sorted(k for k in groups if k != "#")
        if reverse:
            letters.reverse()
        if "#" in groups:
            letters.append("#")

        for key in groups:
            groups[key].sort(key=lambda x: str(x.get("name", "")).lower(), reverse=reverse)
        return [(letter, groups[letter]) for letter in letters]

    def _make_card_grid(self) -> ResponsiveGrid:
        """单独造一个网格（重置复用池时用）"""
        return ResponsiveGrid(self, min_item_width=card_module.CARD_MIN_WIDTH,
                              spacing=card_module.CARD_SPACING, margin=0,
                              item_height=card_module.CARD_HEIGHT)

    def reset_pools(self):
        """把槽位和卡片全部丢掉（改卡片尺寸这类会影响布局的设置时用）"""
        self._reset_batch()
        for grid in self._grid_slots:
            try:
                self.content_layout.removeWidget(grid)
                grid.setParent(None)
                grid.deleteLater()
            except RuntimeError:
                pass
        for title in self._title_slots:
            try:
                self.content_layout.removeWidget(title)
                title.setParent(None)
                title.deleteLater()
            except RuntimeError:
                pass
        for card in self._all_cards():
            try:
                # 只 deleteLater()：它们是网格的孩子，跟着一起销毁，别 setParent(None)
                card.hide()
                card.deleteLater()
            except RuntimeError:
                pass
        self._grid_slots = []
        self._title_slots = []
        self._card_map = {}
        # 网格全删了：窗口签名一起作废
        self._grid_signature = {}
        # 窗口状态也一起归零：卡片没了，窗口映射和分组都得重新算
        self._groups = []
        self._grid_cards = {}
        self._idle = {}
        self._window_anchor = None


    def _sort_items(self, items: list, key: str) -> list:
        if key == "az":
            return sorted(items, key=lambda x: str(x.get("name", "")).lower())
        if key == "za":
            return sorted(items, key=lambda x: str(x.get("name", "")).lower(), reverse=True)
        # all：保持原序
        return list(items)

    def set_empty_text(self, text: str):
        """设置"没有内容"时显示的文案"""
        self.empty_label.setText(str(text or ""))

    def refresh_theme(self, force: bool = False):
        """主题变化时只给**现有卡片**重新染色（绝不重建）

        ⚠️ 不能走 _refresh()（"把整页重新渲染一遍"）：主题一换就要重绑所有卡片、重走布局，
           实测要等三四秒。卡片自己的 StyleChange 已能处理大部分颜色，这里只推一把"自己画
           的"那部分（图标重取 + 分割线）。

        force=True：连去重也绕过去，用于换"组件配色"（收藏图标按强调色染）。
        """
        for card in self._rendered_cards():
            try:
                card.refresh_theme(force=force)
            except TypeError:
                card.refresh_theme()
            except RuntimeError:
                continue
        if self._loading_widget:
            self._loading_widget.refresh_theme()
