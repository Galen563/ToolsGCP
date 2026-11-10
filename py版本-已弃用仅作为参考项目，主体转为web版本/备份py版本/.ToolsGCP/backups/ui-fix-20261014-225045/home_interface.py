"""首页界面（左侧栏「首页」，在「搜索」上方）：轮播图 + 推荐插件。

⚠️ 海报放在 .ToolsGCP/images/posters/，第 4、5 张留空占位，要加图丢进目录再往 SLIDES 追加一条。
轮播用 QStackedWidget + QTimer 自实现（不用 CarouselLabel），且只在页面可见时跑。
"""

import os

from PyQt5.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QPainterPath, QPixmap
from PyQt5.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
                             QStackedWidget, QVBoxLayout, QWidget)
from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon as FIF, PipsPager,
                            PushButton, SimpleCardWidget, StrongBodyLabel,
                            SubtitleLabel, isDarkTheme)

from ..core.language_manager import LanguageManager
from ..core.plugin_manager import (HOME_HIDDEN_PLUGIN_IDS, STATUS_DISABLED,
                                   STATUS_ERROR, STATUS_OK)
from ..constants import IMAGES_DIR
from ..utils.smooth_scroll import install_smooth_scroll
from ..widgets.app_card import themed_icon

# 轮播图配置
SLIDE_COUNT = 5          # 圆点分页一共 5 个
SLIDE_INTERVAL_MS = 3000  # 每 3 秒换下一张
SLIDE_MIN_HEIGHT = 200   # 轮播（图片区）的高度 —— 需求："大小我没让你改动，恢复原样"

# 鼠标停在轮播图上滚滚轮 = 翻页
WHEEL_STEP = 120          # 攒够 120 单位（普通滚轮一格）才翻一张
WHEEL_DEBOUNCE_MS = 180   # 一次翻页后这段时间内不再翻，避免"一格跳过好几张"

# 海报图片目录（英文目录名）：.ToolsGCP/images/posters/
POSTERS_DIR = os.path.join(IMAGES_DIR, "posters")

# ⚠️ 顺序即文件名顺序：poster1 → poster2 → poster3；要加图丢进 posters/ 再往这里追加一条
SLIDES = [
    {"image": os.path.join(POSTERS_DIR, f"poster{i}.png"), "title": "", "subtitle": ""}
    for i in (1, 2, 3)
]
SLIDES += [{"image": "", "title": "", "subtitle": ""}
           for _ in range(max(0, SLIDE_COUNT - len(SLIDES)))]

# 推荐插件区域的列数（宽屏 3 列，窄了会少放）
PLUGIN_COLUMNS = 3


class SlideCard(QFrame):
    """轮播里的一"张图"：有 image 就贴海报，没有就只画一块带边框的空白区。"""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config or {}
        self.setMinimumHeight(SLIDE_MIN_HEIGHT)

        # ⚠️ 图片只读一次：海报是 1MB 级 PNG，每次 paintEvent 都解码会卡住界面线程
        self._pixmap = None
        self._pixmap_loaded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(6)

        self.title_label = StrongBodyLabel(self._config.get("title", ""), self)
        self.subtitle_label = CaptionLabel(self._config.get("subtitle", ""), self)
        layout.addStretch(1)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addStretch(1)

        # 没有文字就不显示
        show_text = bool(self._config.get("title") or self._config.get("subtitle"))
        self.title_label.setVisible(show_text)
        self.subtitle_label.setVisible(show_text)

        self.apply_theme()

    def _image_path(self) -> str:
        return str(self._config.get("image") or "").strip()

    def _image(self) -> QPixmap:
        """海报图（只读一次盘 + 缓存缩放结果给当前尺寸用）"""
        if not self._pixmap_loaded:
            self._pixmap_loaded = True
            path = self._image_path()
            self._pixmap = QPixmap(path) if path else QPixmap()
        return self._pixmap

    def image_aspect(self) -> float:
        """海报的高 / 宽（没有图就返回 0）；留着给需要按比例排版的地方用"""
        pixmap = self._image()
        if pixmap is None or pixmap.isNull() or pixmap.width() <= 0:
            return 0.0
        return pixmap.height() / float(pixmap.width())

    def apply_theme(self):
        """空白占位块：浅色下一块浅灰，深色下一块深灰（都能看出"这里有一张图"）"""
        if isDarkTheme():
            background, border, radius = "rgba(255,255,255,0.05)", "rgba(255,255,255,0.08)", 12
        else:
            background, border, radius = "rgba(0,0,0,0.035)", "rgba(0,0,0,0.06)", 12
        self._radius = radius
        self.setStyleSheet(f"""
            SlideCard {{
                background: {background};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
        """)

    def paintEvent(self, event):
        """先让样式表把底/边框画出来，再往上贴图片（如果有）"""
        super().paintEvent(event)
        pixmap = self._image()
        if pixmap is None or pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        # 圆角裁切：不裁的话图片会盖住样式表画的圆角，四个角看着是方的
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
        painter.setClipPath(path)
        # ⚠️ 尺寸不跟图片比例走；图比区域大时按 (宽-图宽)/2、(高-图高)/2 居中绘制，
        #    用 drawPixmap(0, 0, ...) 会从右下角切掉，看着像海报下半部分被遮挡
        scaled = pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation)
        painter.drawPixmap((self.width() - scaled.width()) // 2,
                           (self.height() - scaled.height()) // 2, scaled)
        painter.end()


class BannerCarousel(QWidget):
    """轮播区：叠放的 SlideCard + 底部圆点分页 + 自动翻页。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._index = 0
        self._count = max(1, len(SLIDES))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.stack = QStackedWidget(self)
        self.stack.setMinimumHeight(SLIDE_MIN_HEIGHT)
        self._slides = []
        for config in SLIDES:
            slide = SlideCard(config, self.stack)
            self.stack.addWidget(slide)
            self._slides.append(slide)
        layout.addWidget(self.stack, 1)

        # 圆点分页：5 个点，当前页高亮
        pager_row = QHBoxLayout()
        pager_row.setContentsMargins(0, 0, 0, 0)
        pager_row.addStretch(1)
        self.pager = PipsPager(self)
        self.pager.setPageNumber(self._count)
        self.pager.setVisibleNumber(self._count)
        self.pager.currentIndexChanged.connect(self._on_pager_clicked)
        pager_row.addWidget(self.pager)
        pager_row.addStretch(1)
        layout.addLayout(pager_row)

        self._timer = QTimer(self)
        self._timer.setInterval(SLIDE_INTERVAL_MS)
        self._timer.timeout.connect(self.next_slide)

        # 滚轮翻页：攒角度增量 + 短暂冷却，见 wheelEvent
        self._wheel_accum = 0
        self._wheel_ready = True
        self._wheel_cooldown = QTimer(self)
        self._wheel_cooldown.setSingleShot(True)
        self._wheel_cooldown.setInterval(WHEEL_DEBOUNCE_MS)
        self._wheel_cooldown.timeout.connect(self._on_wheel_cooldown)

        self._sync_pager()

    # ---------- 翻页 ----------
    def next_slide(self):
        """下一张；到最后一张之后**回到第一张**（取模）"""
        self.go_to(self._index + 1)

    def previous_slide(self):
        """上一张；第一张再往前回到最后一张（go_to 里是取模，负数也对）"""
        self.go_to(self._index - 1)

    def go_to(self, index: int, restart_timer: bool = False):
        """跳到指定页（index 会自动取模，所以越界也不会出错）"""
        if self._count <= 0:
            return
        self._index = int(index) % self._count
        self.stack.setCurrentIndex(self._index)
        self._sync_pager()
        if restart_timer and self._timer.isActive():
            # 手动操作之后重新计时：否则刚点完圆点可能立刻又被自动翻走
            self._timer.start()

    def _sync_pager(self):
        """让圆点跟上当前页（不回发信号，避免自己触发自己）"""
        try:
            self.pager.blockSignals(True)
            self.pager.setCurrentIndex(self._index)
        finally:
            self.pager.blockSignals(False)

    def _on_pager_clicked(self, index: int):
        self.go_to(index, restart_timer=True)

    # ---------- 滚轮翻页 ----------
    def wheelEvent(self, event):
        """鼠标停在轮播图上滚滚轮 = 翻页（下滚下一张 / 上滚上一张）。

        ⚠️ Qt 的 angleDelta().y() 往上为正、往下为负，所以 delta < 0 才是下一张；
        攒够 WHEEL_STEP 才翻一张并进冷却，翻完必须 accept 事件，否则外层页面会跟着滚。
        """
        delta = event.angleDelta().y()
        if not delta:
            # 触摸板有时只给 pixelDelta，按 120 一格的估算折算
            delta = int(event.pixelDelta().y() * 4)

        if self._count <= 1 or not delta:
            # 只有一张（或没有增量）时不抢滚轮，交给外面的页面自己滚
            event.ignore()
            return

        if not self._wheel_ready:
            event.accept()
            return

        self._wheel_accum += delta
        if abs(self._wheel_accum) >= WHEEL_STEP:
            # 只吃掉一格的量，剩下的留给下一次（慢慢滚也不会攒出一大堆）
            self._wheel_accum -= WHEEL_STEP if self._wheel_accum > 0 else -WHEEL_STEP
            # ⚠️ 方向坑：angleDelta().y() 往下滚是负数 → delta < 0 是下一张；越界由 go_to 取模兜住
            self.go_to(self._index + (1 if delta < 0 else -1), restart_timer=True)
            self._wheel_accum = 0
            self._wheel_ready = False
            self._wheel_cooldown.start()

        event.accept()

    def _on_wheel_cooldown(self):
        self._wheel_ready = True

    # ---------- 播放控制 ----------
    def start(self):
        if self._count > 1 and not self._timer.isActive():
            self._timer.start()

    def stop(self):
        self._timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self.start()

    def hideEvent(self, event):
        """离开这一页就停掉定时器：没必要在后台一直翻"""
        self.stop()
        super().hideEvent(event)

    def apply_theme(self):
        for slide in self._slides:
            slide.apply_theme()


class PluginMinicard(SimpleCardWidget):
    """推荐插件用的小卡片：图标 + 名称 + 版本/作者 + 简介（只展示，点击去插件页）。"""

    clicked = pyqtSignal()

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.setFixedHeight(96)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(38, 38)
        self.icon_label.setPixmap(self._make_icon())
        layout.addWidget(self.icon_label, 0, Qt.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        self.name_label = StrongBodyLabel(info.name or info.id, self)
        text_box.addWidget(self.name_label)

        sub = " · ".join(x for x in [f"v{info.version}" if info.version else "",
                                     info.author] if x)
        self.sub_label = CaptionLabel(sub or info.id, self)
        text_box.addWidget(self.sub_label)

        self.desc_label = CaptionLabel(info.description or "", self)
        self.desc_label.setWordWrap(True)
        text_box.addWidget(self.desc_label)
        layout.addLayout(text_box, 1)

    def _make_icon(self) -> QPixmap:
        """插件图标：插件目录里的图片 > FluentIcon 名字 > 默认图标"""
        pixmap = QPixmap(38, 38)
        pixmap.fill(Qt.transparent)
        icon = None
        name = str(self.info.icon or "").strip()
        candidate = os.path.join(self.info.dir, name) if name else ""
        if candidate and os.path.exists(candidate):
            from PyQt5.QtGui import QIcon
            icon = QIcon(candidate)
        elif name and hasattr(FIF, name):
            icon = themed_icon(getattr(FIF, name), 34)
        else:
            icon = themed_icon(FIF.APPLICATION, 34)
        painter = QPainter(pixmap)
        icon.paint(painter, 2, 2, 34, 34)
        painter.end()
        return pixmap

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class HomeInterface(QWidget):
    """首页：轮播图 + 推荐插件。

    信号：plugin_center_requested() —— 点了推荐卡片/按钮，主窗口切到插件页。
    """

    plugin_center_requested = pyqtSignal()

    def __init__(self, language_manager: LanguageManager = None,
                 plugin_manager=None, parent=None):
        super().__init__(parent)
        self.setObjectName("homeInterface")
        self.lang = language_manager
        self.plugin_manager = plugin_manager
        self._minicards = []
        self.setup_ui()

    # ---------- 文案 ----------
    def get_text(self, key: str, default: str = "") -> str:
        if self.lang is not None:
            try:
                text = self.lang.get_text("home", key)
                if text and text != key:
                    return text
            except Exception:
                pass
        fallback = {
            "home_title": "Custom",
            "recommend_plugins": "Recommended Plugins",
            "recommend_plugins_tip": "These are the plugins in your local plugins/ folder",
            "no_plugins": "No plugins installed yet. Drop a plugin folder into plugins/ and it shows up here.",
            "no_recommend_plugins": "Nothing to recommend yet. The built-in plugins are all in the Plugin Center, ready to switch on or off.",
            "open_plugin_center": "Open Plugin Center",
        }
        return fallback.get(key, default or key)

    # ---------- 界面 ----------
    def setup_ui(self):
        if self.layout():
            while self.layout().count():
                item = self.layout().takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.layout().deleteLater()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        # 留个引用：`_apply_page_background()` 要去掉它的"背景填充色"（见那里说明）
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("homeScrollContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 24, 30, 30)
        layout.setSpacing(18)

        # ---- 轮播图 ----
        self.carousel = BannerCarousel(content)
        layout.addWidget(self.carousel)

        # ---- 推荐插件 ----
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.addWidget(SubtitleLabel(self.get_text("recommend_plugins"), content))
        self.count_label = CaptionLabel("", content)
        title_row.addWidget(self.count_label)
        title_row.addStretch()
        self.more_btn = PushButton(self.get_text("open_plugin_center"), content)
        self.more_btn.setIcon(themed_icon(FIF.APPLICATION, 16))
        self.more_btn.clicked.connect(self.plugin_center_requested.emit)
        title_row.addWidget(self.more_btn)
        layout.addLayout(title_row)

        self.plugin_host = QWidget(content)
        self.plugin_grid = QGridLayout(self.plugin_host)
        self.plugin_grid.setContentsMargins(0, 0, 0, 0)
        self.plugin_grid.setSpacing(12)
        layout.addWidget(self.plugin_host)

        self.empty_label = BodyLabel(self.get_text("no_plugins"), content)
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        layout.addStretch()
        scroll.setWidget(content)
        install_smooth_scroll(scroll)
        outer.addWidget(scroll)

        self.refresh_plugins()
        # 整页底色（浅/深各一套）—— 构造时就铺上，否则首页会透出窗口的深色背景
        self._apply_page_background()

    def refresh_plugins(self):
        """按当前插件列表重建"推荐插件"那一块。

        ⚠️ 过滤掉 HOME_HIDDEN_PLUGIN_IDS：只是首页不展示，插件中心照旧。
        """
        while self.plugin_grid.count():
            item = self.plugin_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._minicards = []

        infos = []
        if self.plugin_manager is not None:
            infos = [info for info in self.plugin_manager.plugins
                     if info.status in (STATUS_OK, STATUS_DISABLED, STATUS_ERROR)
                     and info.id not in HOME_HIDDEN_PLUGIN_IDS]

        self.count_label.setText(f"（{len(infos)}）" if infos else "")
        if infos:
            self.empty_label.setVisible(False)
        else:
            # ⚠️ 两种"空"要分开说：一个插件都没有 vs 插件全被上面的隐藏名单滤掉了
            has_any = bool(self.plugin_manager is not None
                           and self.plugin_manager.plugins)
            self.empty_label.setText(self.get_text(
                "no_recommend_plugins" if has_any else "no_plugins"))
            self.empty_label.setVisible(True)

        for index, info in enumerate(infos):
            card = PluginMinicard(info, self.plugin_host)
            card.clicked.connect(self.plugin_center_requested.emit)
            self.plugin_grid.addWidget(card, index // PLUGIN_COLUMNS,
                                       index % PLUGIN_COLUMNS)
            self._minicards.append(card)

    def apply_theme(self):
        """主题变化时刷新自绘部分 + 整页底色。"""
        self._apply_page_background()
        self.carousel.apply_theme()
        self.more_btn.setIcon(themed_icon(FIF.APPLICATION, 16))
        for card in self._minicards:
            card.icon_label.setPixmap(card._make_icon())

    def _apply_page_background(self):
        """清掉首页的底色（透明）。

        ⚠️ 光把 HomeInterface 设透明不够：QScrollArea 本体和它的 viewport() 会用调色板
        Base/Window 填色，三处（页面 + 滚动区 + 视口）都要清。
        """
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.setStyleSheet(
            "HomeInterface { background: transparent; }\n"
            "QWidget#homeScrollContent { background-color: transparent; }")

        scroll = getattr(self, "_scroll", None)
        if scroll is None:
            return
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }\n"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setAutoFillBackground(False)
        try:
            viewport = scroll.viewport()
            viewport.setAutoFillBackground(False)
            viewport.setStyleSheet("background: transparent;")
        except Exception:
            pass

    def refresh_theme(self):
        """给主窗口的主题刷新用的别名。

        ⚠️ 主窗口 refresh_all_pages_theme() 调的是 refresh_theme，别只留 apply_theme。
        """
        self.apply_theme()
