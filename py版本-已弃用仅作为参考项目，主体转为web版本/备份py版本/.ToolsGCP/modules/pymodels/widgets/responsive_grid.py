"""自适应卡片网格：列数按可用宽度算、每列宽度平均分配剩余空间（左右留白相等）、
高度由内容算出来，放进 QScrollArea 里滚动范围刚好合适。

虚拟化：`layout_metrics()` 是纯算术（不建控件），把它传给 set_items 的 `metrics` 参数，
网格里就只放窗口内那十几张卡片，而高度仍按 total_items 算。
"""

from PyQt5.QtCore import QSize, QTimer
from PyQt5.QtWidgets import QWidget


class ResponsiveGrid(QWidget):
    """按可用宽度自动分列的卡片网格"""

    def __init__(self, parent=None, min_item_width: int = 260,
                 spacing: int = 14, margin: int = 0, item_height: int = 0,
                 max_columns=None):
        super().__init__(parent)
        self.min_item_width = int(min_item_width)
        self.spacing = int(spacing)
        self.margin = int(margin)
        self.item_height = int(item_height)
        # 最多排几列（0 / None = 不限制）。可以是 int，也可以是返回 int 的函数
        # （搜索页两种视图的列数上限不一样，而网格是复用的，所以每次布局现算）。
        #
        # ⚠️ 有上限之后，窗口继续变宽就只会让卡片变宽：只按 min_item_width 算列数的话，
        #    窗口越宽列数越多、每张卡片反而越窄，卡片文字永远卡在同一处被截断。
        self.max_columns = max_columns

        self._items: list = []
        self._columns = 0
        self._item_width = 0
        # 虚拟化：本网格承载的是 [start_index, start_index + len(_items)) 这一段，
        # 完整列表一共 total_items 条（高度按它算）
        self._start_index = 0
        self._total_items = 0
        # 布局缓存：按"算它时的可用宽度 + 条目总数"记账，两者都没变才沿用（见 cached_metrics）
        self._metrics = None
        self._metrics_width = -1
        self._metrics_items = -1

    # ---------- 内容 ----------
    def set_items(self, widgets, start_index: int = 0, total_items: int = None,
                  metrics: dict = None):
        """整体替换网格内容

        ⚠️ 已经不属于本网格的控件只是 hide()，**绝不 setParent(None)**：后者会让控件在
           一瞬间变成顶层窗口（屏幕上冒出一堆小窗口又立刻消失）。卡片由谁创建就永远挂在
           谁下面，是本项目的一条硬规矩。

        start_index / total_items 供窗口化用：卡片按 start_index + i 定行列，高度却按
        total_items 算；metrics 可由 layout_metrics() 预先算好传进来。
        """
        widgets = list(widgets)
        for widget in list(self._items):
            if widget in widgets:
                continue
            if widget.parent() is self:
                widget.hide()
        self._items = widgets
        # ⚠️ "这一段在整张列表里的位置"变了才需要重算几何/通知父布局 ——
        #    滚动途中大量重排的两个区间是同一段，去重能省一次 updateGeometry()。
        previous_window = (self._start_index, self._total_items)
        self._start_index = max(0, int(start_index or 0))
        if total_items is None:
            total_items = self._start_index + len(widgets)
        # 总条数不能比"已经放进来的那段"还小，否则最后几张会被算到网格外面
        self._total_items = max(int(total_items), self._start_index + len(widgets))
        for widget in self._items:
            # setParent() 会把控件标记成"显式隐藏"，这里必须 show() 一下，
            # 否则它永远处于隐藏状态，看起来就像卡片凭空消失了。
            # ⚠️ 只 show 真正藏着的：对着几十张本来就可见的卡片逐个 show() 是白花的钱。
            if not widget.isVisible():
                widget.show()
        # 传进来的 metrics 不一定是"当前这个宽度"下算的（框架用的是借来的宽度），
        # 对不上就重算，否则卡片会被摆到错误的列上、高度也跟着错。
        if metrics is not None and not self._metrics_matches(metrics):
            metrics = None
        self._relayout(metrics, window_changed=previous_window !=
                       (self._start_index, self._total_items))

    def _metrics_matches(self, metrics: dict) -> bool:
        """这份 metrics 是按"当前可用宽度"算出来的吗（对不上就作废重算）"""
        width = self._usable_width()
        if width <= 0:
            return True
        avail = max(0, width - self.margin * 2)
        if avail <= 0:
            return True
        columns = max(1, (avail + self.spacing) // (self.min_item_width + self.spacing))
        cap = self._column_cap(avail)
        if cap > 0:
            columns = max(1, min(columns, cap))
        if columns != metrics.get("columns"):
            return False
        return (avail - self.spacing * (columns - 1)) // columns == metrics.get("item_width")

    def add_item(self, widget):
        widget.setParent(self)
        widget.show()
        self._items.append(widget)
        self._total_items = max(self._total_items, self._start_index + len(self._items))
        return widget

    def drop_card(self, widget, relayout: bool = True) -> bool:
        """把某个控件从本网格里摘掉（不删、不隐藏）

        ⚠️ 卡片被 setParent 搬走后**本网格的 _items 里还留着它**（setParent 不通知旧父级），
           会一直拖着一张属于别处的卡片、多出幽灵格子。relayout=False 用于"马上要挂到
           别的网格去"的场景。
        """
        for index, item in enumerate(self._items):
            # 用 id 比对：PyQt 每次取包装对象可能是不同的 Python 对象
            if item is widget or id(item) == id(widget):
                del self._items[index]
                if relayout:
                    self._relayout()
                return True
        return False

    def clear(self, delete: bool = True):
        for widget in self._items:
            # 同上：只处理还挂在自己下面的（别人家的卡片别动）
            if widget.parent() is not self:
                continue
            # ⚠️ 只 hide()，不 setParent(None)（后者会让控件瞬间变成顶层窗口闪现）
            widget.hide()
            if delete:
                widget.deleteLater()
        self._items = []
        self._columns = 0
        self._item_width = 0
        self._start_index = 0
        self._total_items = 0
        self._metrics = None
        self._metrics_width = -1
        self._metrics_items = -1
        self.setFixedHeight(0)

    def items(self) -> list:
        return list(self._items)

    def start_index(self) -> int:
        """本网格第一张卡片在整个列表里的下标（虚拟化用）"""
        return self._start_index

    def total_items(self) -> int:
        """高度是按多少条算出来的（虚拟化用）"""
        return self._total_items

    def columns(self) -> int:
        """当前排了几列（测试/调试用）"""
        return self._columns

    def item_width(self) -> int:
        """当前每张卡片的宽度（所有卡片相同）"""
        return self._item_width

    # ---------- 排布 ----------
    def layout_metrics(self, avail_width: int = None, total_items: int = None) -> dict:
        """纯算术地算出"这个宽度下会排成什么样"：{columns, item_width, row_height,
        height, rows}，**一张卡片都不用建**，所以框架能在渲染之前就把整页滚动范围算出来。

        total_items 给 None 时用本网格当前承载的条数；avail_width 给 None 时用自身宽度。
        """
        if total_items is None:
            total_items = self._total_items or len(self._items)
        total_items = max(0, int(total_items))

        if avail_width is None:
            avail_width = self._usable_width()
        avail = max(0, int(avail_width) - self.margin * 2)

        if avail <= 0 or total_items <= 0:
            # 宽度还没确定 / 没有内容：返回 0，调用方据此知道"现在算不出布局"
            return {"columns": 0, "item_width": 0, "row_height": 0,
                    "height": 0, "rows": 0}

        # 能放几列：n 张卡片 + (n-1) 个间距 不超过可用宽度
        # ⚠️ 这里**不能**再用 min(columns, len(items)) 夹一下 —— 那样只有 1、2 张
        #    卡片时列数会退化成 1、2 列，卡片被拉成一整行宽。列数只由宽度决定，
        #    没放满的行右边留空即可。
        columns = max(1, (avail + self.spacing) // (self.min_item_width + self.spacing))
        # 再按上限夹一次（上限本身会随宽度涨，见 max_columns）
        cap = self._column_cap(avail)
        if cap > 0:
            columns = max(1, min(columns, cap))

        # 剩余宽度平均分给每一列。
        # 除不尽的余数（最多列数-1 个像素）摊到**间距**里而不是卡片宽度里，
        # 这样：所有卡片一样宽 + 左右留白精确相等，两个目标同时满足。
        usable = avail - self.spacing * (columns - 1)
        item_width = usable // columns
        remainder = usable - item_width * columns

        # 行高：优先用构造时给定的 item_height（卡片网格都给，是固定值）；
        # 没给就按现有卡片自己的 sizeHint 取最大。
        # ⚠️ 一段卡片都没有时不能去 max() 空序列，回退到 1 只是兜底。
        if self.item_height:
            row_height = self.item_height
        else:
            row_height = max([w.sizeHint().height() for w in self._items] or [1])
        rows = (total_items + columns - 1) // columns
        height = (self.margin * 2 + rows * row_height
                  + max(0, rows - 1) * self.spacing)
        return {"columns": columns, "item_width": item_width,
                "row_height": row_height, "height": height, "rows": rows,
                "remainder": remainder}

    def _column_cap(self, avail: int = None) -> int:
        """当前允许的最多列数（0 = 不限制）

        ⚠️ max_columns 可以是函数且接**可用宽度**：搜索页两种视图上限不同、网格又是复用的，
           只能每次布局现问；上限必须随宽度涨，否则 2560 宽的屏幕上每张卡片 600+ 像素、
           被横向拉扁（拿不到宽度时退回无参调用，保持兼容）。
        """
        cap = self.max_columns
        if callable(cap):
            try:
                cap = cap(avail) if avail is not None else cap()
            except TypeError:
                # 老的、不接参数的函数：退回无参调用
                try:
                    cap = cap()
                except Exception:
                    cap = 0
            except Exception:
                cap = 0
        try:
            return int(cap or 0)
        except (TypeError, ValueError):
            return 0

    def cached_metrics(self, metrics: dict = None) -> dict:
        """记住 / 取出"这个宽度**和这个条数**下算好的布局"

        ⚠️ 缓存是给"Qt 布局延迟"兜底的：网格刚 reparent 或页面还藏着时 width() 是 0，
           紧接着 Qt 会用那个 0 宽度触发 _relayout()，重新按 0 算的话列数会塌成 1 列、
           高度翻几倍。**并且必须连条数一起比**：只认宽度的话，条目从 48 换成 3000 时
           高度还是旧的那份，滚动条就没有行程了。
        """
        wanted_items = self._total_items or len(self._items)
        if metrics is not None:
            self._metrics_width = self._usable_width()
            self._metrics_items = wanted_items
            self._metrics = metrics
            return metrics
        if (self._metrics is not None
                and self._metrics_width == self._usable_width()
                and self._metrics_items == wanted_items):
            return self._metrics
        return None

    def sizeHint(self) -> QSize:
        if not self._items:
            return QSize(0, 0)
        return QSize(self.width(), self.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event):
        """从隐藏变可见时也重排一次（页面藏在 QStackedWidget 里时宽度不保证已更新）"""
        super().showEvent(event)
        self._relayout()

    def _usable_width(self) -> int:
        """可用宽度：自身宽度，还是 0 就借父控件的（控件刚 reparent 时宽度是 0）"""
        width = self.width()
        if width > 0:
            return width
        parent = self.parentWidget()
        if parent is not None and parent.width() > 0:
            return parent.width()
        return 0

    def _relayout(self, metrics: dict = None, window_changed: bool = True):
        # 注意：这里**不按 isHidden() 过滤** —— 卡片刚 setParent 过来时可能还是隐藏
        # 状态，过滤掉会让网格高度算成 0，之后宽度不变就再也不会重算、卡片就"消失"了。
        # 想隐藏某张卡片，请用 clear()/set_items() 把它移出网格。
        items = list(self._items)

        # 条数为 0 但"这一段属于一个更大的列表"时也要算出高度：虚拟化下滚到某一组
        # 外面时这组一张卡片都没有，但它**必须**还占着 total_items 那么高。
        if not items and not self._total_items:
            self._columns = 0
            self._item_width = 0
            self.setFixedHeight(0)
            return

        if metrics is None:
            # 先看缓存：这份布局是给"当前这个宽度"算的，就直接沿用
            metrics = self.cached_metrics()
            if metrics is None:
                metrics = self.layout_metrics(total_items=self._total_items or len(items))
                metrics = self.cached_metrics(metrics)
        if metrics["columns"] <= 0:
            # 宽度还没确定（控件刚被 reparent / 所在页面还藏着）。
            # ⚠️ 这里**绝对不能**直接 return —— 那样高度会一直停在 0，而且只要宽度
            #    之后不再变化，resizeEvent 就不会再触发，卡片会永远"消失"。
            QTimer.singleShot(0, self._relayout)
            return

        columns = metrics["columns"]
        item_width = metrics["item_width"]
        row_height = metrics["row_height"]
        remainder = metrics.get("remainder", 0)

        self._columns = columns
        self._item_width = item_width

        start = self._start_index
        for offset, widget in enumerate(items):
            # 行列按"在整个列表里的下标"算，不是按在这一段里的偏移 ——
            # 否则窗口往下挪一格，卡片位置就整体错位
            absolute = start + offset
            column = absolute % columns
            row = absolute // columns
            x = self.margin + column * (item_width + self.spacing) \
                + min(column, remainder)
            y = self.margin + row * (row_height + self.spacing)
            # 尺寸没变就不要重复 setFixedSize —— 每次都会触发一次 resize 事件
            if widget.width() != item_width or widget.height() != row_height:
                widget.setFixedSize(item_width, row_height)
            if widget.x() != x or widget.y() != y:
                widget.move(x, y)
            # ⚠️⚠️ 一定要把"你现在的宽度是多少"告诉卡片：卡片里的标题/简介结尾那个
            #    "…" 是按宽度算的（见 app_card.AppCard._refresh_texts），它认的是自己的
            #    `_card_width` —— 以前网格只 setFixedSize、不通知，于是 `_card_width`
            #    永远停在初始值，窗口怎么拉伸文字都在同一处被截断。
            #    这个方法自带去重（宽度没变直接返回），放在循环里不亏。
            notify = getattr(widget, "set_card_width", None)
            if callable(notify):
                try:
                    notify(item_width)
                except Exception:
                    pass

        if metrics["height"] != self.height():
            self.setFixedHeight(metrics["height"])
        # ⚠️ updateGeometry() 会让父布局整条链重跑；窗口区间没变时（滚动途中大多数
        #    重排都是这种），几何没变就不用再通知一次。
        if window_changed:
            self.updateGeometry()
