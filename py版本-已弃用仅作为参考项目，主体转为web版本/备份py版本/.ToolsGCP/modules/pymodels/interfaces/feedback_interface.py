"""反馈页面：引导用户前往 GitHub 提交反馈。"""

from ..utils.fonts import ui_font
import os

from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFrame, QApplication, QScrollArea, QShortcut,
                             QStackedWidget)
from PyQt5.QtGui import (QFont, QPixmap, QPainter, QPainterPath, QKeySequence)
from qfluentwidgets import (SimpleCardWidget, PrimaryPushButton, PushButton,
                            FluentIcon as FIF,
                            InfoBar, InfoBarPosition, isDarkTheme)

from ..core.language_manager import LanguageManager
from ..utils.logger import log
from ..utils.theme_utils import is_dark_mode
from ..utils.url_open import ctrl_active, open_url, watch_ctrl
from ..widgets.app_card import themed_icon
from ..constants import FEEDBACK_URL, IMAGES_DIR

# 两个 QQ 群的群号 + 对应图片（图片放在 .ToolsGCP/images/qq/ 下）
# ⚠️ 顺序 = 界面上的左右顺序：改进建议群在左、投诉举报群在右
QQ_GROUPS = [
    {"key": "qq_group_label", "number": "312751713",
     "image": os.path.join(IMAGES_DIR, "qq", "ToolsGCP-改进建议群.jpg")},
    {"key": "qq_report_label", "number": "973961899",
     "image": os.path.join(IMAGES_DIR, "qq", "ToolsGCP-投诉举报群.jpg")},
]
# 加群图片的展示宽度（两张并排，窄窗口按比例缩小）
# 340 → 280（约 −18%）：两张并排居中，但不再一屏占满、把下面的内容全顶下去
QQ_IMAGE_WIDTH = 280
# 两张图之间的空隙（需求："它们之间稍微空余一点空间"）
QQ_ROW_GAP = 36


class CopyNumberButton(PushButton):
    """「复制群号 [copy]」按钮 —— 文字和图标是**一个整体**。

    ⚠️ 不要用 TransparentToolButton，也不要在按钮内部再摆一层"文字 + 图标"的布局：
    两者会各自被居中、叠在同一个位置（就是用户看到的"叠加在一起"）。PushButton 自带
    setText + setIcon，图标默认就在文字左侧、整体居中。

    状态：常态「复制群号 [copy]」；点过「已复制 [accept]」并禁用 2 秒。
    样式按需求复刻 AI 界面那颗 IconButton 的皮（常态透明、悬停浮出淡圆角底），只换皮，逻辑没动。
    """

    COPIED_MS = 2000
    # 和 AI 操作栏按钮同高（app_card.ACTION_BTN_SIZE = 28）
    HEIGHT = 28
    RADIUS = 6

    def __init__(self, parent, number: str, copy_text: str, copied_text: str,
                 copy_tip: str = "", copied_tip: str = ""):
        super().__init__(parent)
        self._number = str(number or "")
        self._copy_text = copy_text
        self._copied_text = copied_text
        # ⚠️ 两个 tooltip 由调用方按当前语言传进来（原来写死中文），没传就退回按钮本身那句文案
        self._copy_tip = copy_tip or str(copy_text or "")
        self._copied_tip = copied_tip or str(copied_text or "")
        self._dark = bool(isDarkTheme())
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.COPIED_MS)
        self._timer.timeout.connect(self._restore)

        # 图标在文字左边、整体居中（PushButton 默认行为，不要动布局）
        self.setIcon(themed_icon(FIF.COPY, 14, dark=self._dark))
        self.setIconSize(QSize(14, 14))
        self.setText(self._copy_text)
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        # ⚠️ 点完不要留焦点框（需求："点击后会有边框，我不要这个边框"）。
        #    NoFocus = 鼠标点它也不会成为键盘焦点，于是那圈 focus 描边根本不会画
        self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip(f"复制群号 {self._number}")
        self.setFont(ui_font(9))
        self.apply_theme(self._dark)
        self.clicked.connect(self._copy)

    def apply_theme(self, dark: bool = None):
        """按主题刷"AI copy 按钮同款"的皮（常态透明 + 悬停淡底）。

        ⚠️⚠️ 必须用 qfluentwidgets 的 setCustomStyleSheet，不能直接 self.setStyleSheet：
        后者会把库给这个控件的那份样式表整个顶掉 —— 库靠 [hasIcon=true] { padding-left } 给图标留位置，
        被顶掉之后图标会被画在文字身上（实测"复制群号"四个字和图标叠在一起）。
        setCustomStyleSheet 是把我们的规则追加在库那份后面（深度合并），其余照旧。
        """
        if dark is None:
            dark = bool(isDarkTheme())
        self._dark = bool(dark)
        text = "#E8EAF0" if dark else "#1F2329"
        hover = ("rgba(255, 255, 255, 0.11)" if dark
                 else "rgba(0, 0, 0, 0.07)")
        pressed = ("rgba(255, 255, 255, 0.16)" if dark
                   else "rgba(0, 0, 0, 0.11)")
        disabled = "rgba(255, 255, 255, 0.36)" if dark else "rgba(0, 0, 0, 0.36)"

        def rules(background: str, text_color: str, hover_bg: str,
                  pressed_bg: str, radius: int = 6) -> str:
            # ⚠️⚠️ 需求："复制群号点击后的边框删除。"
            #    每个状态（含 hover / pressed / focus / disabled）都必须显式写 border: none：
            #    点击后会进入 disabled，"已复制"那 2 秒里 :disabled 的优先级高于普通
            #    PushButton 规则，漏一个状态库里的 1px 描边就又冒出来。
            return f"""
                PushButton {{
                    background: {background};
                    border: none;
                    border-radius: {radius}px;
                    color: {text_color};
                    outline: none;
                }}
                PushButton:hover {{ background: {hover_bg}; border: none; }}
                PushButton:pressed {{ background: {pressed_bg}; border: none; }}
                PushButton:focus {{ border: none; outline: none; }}
                PushButton:disabled {{ background: transparent; border: none;
                                       color: {disabled}; outline: none; }}
            """

        light = rules("transparent", "#1F2329",
                      "rgba(0, 0, 0, 0.07)", "rgba(0, 0, 0, 0.11)")
        dark_qss = rules("transparent", "#E8EAF0",
                         "rgba(255, 255, 255, 0.11)",
                         "rgba(255, 255, 255, 0.16)")
        try:
            from qfluentwidgets import setCustomStyleSheet
            setCustomStyleSheet(self, light, dark_qss)
        except Exception:
            # 兜底：老版本库没有这个 API 时退化成"在库样式后面追加"
            self.setStyleSheet(self.styleSheet() + (dark_qss if dark else light))

    def _copy(self):
        try:
            QApplication.clipboard().setText(self._number)
        except Exception:
            return
        self.setText(self._copied_text)
        self.setIcon(themed_icon(FIF.ACCEPT, 14, dark=self._dark))
        self.setToolTip(self._copied_tip)
        self.setEnabled(False)
        self._timer.start()

    def _restore(self):
        self.setText(self._copy_text)
        self.setIcon(themed_icon(FIF.COPY, 14, dark=self._dark))
        self.setToolTip(self._copy_tip)
        self.setEnabled(True)

    def refresh_icon(self, force: bool = False):
        """主题切换后重取图标 + 重刷按钮的皮"""
        self.apply_theme()
        self.setIcon(themed_icon(FIF.ACCEPT if not self.isEnabled() else FIF.COPY,
                                 14, dark=self._dark))


class ClickableLabel(QLabel):
    """点一下就发信号的 QLabel（"看大图"页里点图片返回用它）。

    QLabel 没有 clicked 信号；运行时给它挂 mousePressEvent 这种"打补丁"的写法在控件重建后会失效，所以做个子类。
    """

    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class QQImageCard(QFrame):
    """一张 QQ 加群图片（圆角裁切，按控件尺寸缓存缩放结果）。

    ⚠️ 刻意不自绘 pixmap，而是把缩放好的图交给内部 QLabel 画：自绘版本
    （QPainter + setClipPath + drawPixmap）在"原图 1284×2283、展示 260×462"时，
    paintEvent 第一次进入就再也不返回，事件循环整个被饿死（实测两次）。

    两层缓存：解码后立刻按展示宽度的 2 倍降采样（_source，不再持有原图）；按当前控件尺寸的
    缩放结果也缓存（_scaled），尺寸没变就直接 setPixmap。
    """

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self._path = str(image_path or "")
        self._source = None
        self._scaled = None
        self._scaled_for = None
        self._loaded = False
        self._radius = 12
        # 点一下整张图 → 进"放大查看"页（由外面接上）
        self.clicked = None
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(120)

        # 内部用 QLabel 承载图片（见类说明）
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setScaledContents(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._label)

    def _load(self) -> QPixmap:
        """解码 + **立刻降采样**（原图 1284×2283，留着它每次缩放都很贵）"""
        if self._loaded:
            return self._source
        self._loaded = True
        if not self._path or not os.path.exists(self._path):
            self._source = QPixmap()
            return self._source
        pixmap = QPixmap(self._path)
        if pixmap.isNull():
            self._source = QPixmap()
            return self._source
        target_w = max(200, QQ_IMAGE_WIDTH * 2)
        if pixmap.width() > target_w:
            pixmap = pixmap.scaledToWidth(target_w, Qt.SmoothTransformation)
        self._source = pixmap
        return self._source

    def _image(self) -> QPixmap:
        return self._load()

    def _refresh_pixmap(self):
        """把"按当前尺寸缩放好的图"交给内部 QLabel（尺寸没变就什么都不做）"""
        source = self._load()
        if source is None or source.isNull():
            return
        size = self.size()
        key = (size.width(), size.height())
        if self._scaled is not None and self._scaled_for == key:
            return
        self._scaled = source.scaled(size, Qt.KeepAspectRatioByExpanding,
                                     Qt.SmoothTransformation)
        self._scaled_for = key
        self._label.setPixmap(self._scaled)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_pixmap()

    def mouseReleaseEvent(self, event):
        """点一下整张图 → 交给外面进"放大查看"页"""
        if event.button() == Qt.LeftButton and callable(self.clicked):
            try:
                self.clicked()
            except Exception:
                pass
            return
        super().mouseReleaseEvent(event)

    def has_image(self) -> bool:
        pixmap = self._load()
        return pixmap is not None and not pixmap.isNull()

    def aspect_ratio(self) -> float:
        """图片的高 / 宽（没有图返回 0，调用方自己挑默认高度）"""
        pixmap = self._load()
        if pixmap is None or pixmap.isNull() or pixmap.width() <= 0:
            return 0.0
        return pixmap.height() / float(pixmap.width())


class FeedbackInterface(QWidget):
    """反馈页面"""

    def __init__(self, language_manager: LanguageManager = None,
                 settings_manager=None):
        super().__init__()
        self.setObjectName("feedbackInterface")
        self.lang = language_manager
        self.settings_manager = settings_manager

        # 两层页面：0 = 反馈内容，1 = "看整张图"（点加群图能进单独页面看大图）
        self.page_stack = QStackedWidget(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.page_stack)

        content_page = QWidget()
        content_page.setObjectName("feedbackContentPage")
        self.main_layout = QVBoxLayout(content_page)
        self.main_layout.setContentsMargins(40, 30, 40, 30)
        self.main_layout.setSpacing(15)
        self.main_layout.setAlignment(Qt.AlignTop)
        self.page_stack.addWidget(content_page)
        self.page_stack.addWidget(self._build_image_page())
        self._full_pixmap = None

        self._build_feedback_card()
        self._apply_theme_styles()

        # ⚠️ 凡是有左上角退出按钮的页面都要保证 Esc 返回上级（这一页就是「← 返回」）；
        #    做成属性：QShortcut 只存局部变量会被 Python 回收、快捷键随即失效
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._esc_shortcut.activated.connect(self._on_escape)

    def _on_escape(self):
        """Esc：正在看大图就退回反馈内容页（已经在内容页时什么都不做）"""
        try:
            if self.page_stack.currentIndex() == 1:
                self.show_content_page()
        except RuntimeError:
            pass

    # ---------- 工具 ----------

    def _t(self, key, default=None):
        if self.lang:
            try:
                result = self.lang.get_text("feedback", key)
                if result and result != key:
                    return result
            except Exception:
                pass
        return default if default is not None else key

    def _detect_dark_mode(self):
        if self.settings_manager:
            theme = self.settings_manager.settings.get("theme", "跟随系统")
            return is_dark_mode(theme)
        return isDarkTheme()

    def _apply_theme_styles(self):
        """根据主题应用样式 - 解决白色文字在浅色模式下变黑的问题"""
        is_dark = self._detect_dark_mode()
        title_color = "#FFFFFF" if is_dark else "#1F2329"
        body_color = "#DDDDDD" if is_dark else "#333333"
        hint_color = "#9AA0A6" if is_dark else "#666666"
        self.setStyleSheet(f"""
            QWidget#feedbackInterface {{
                background: transparent;
            }}
            QLabel#feedbackTitle {{
                color: {title_color};
                background: transparent;
            }}
            QLabel#feedbackBody1 {{
                color: {body_color};
                background: transparent;
            }}
            QLabel#feedbackBody2 {{
                color: {hint_color};
                background: transparent;
            }}
            QLabel#feedbackQQGroup, QLabel#feedbackQQReport {{
                color: {body_color};
                background: transparent;
            }}
        """)

    def refresh_theme(self):
        """主题变化时由外部调用"""
        self._apply_theme_styles()
        # 复制按钮的图标是 pixmap、按主题取的，切主题要重取一次
        for button in getattr(self, "qq_copy_buttons", ()):
            try:
                button.refresh_icon(force=True)
            except Exception:
                pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 大图页开着时，窗口变了要重新等比缩放
        if getattr(self, "page_stack", None) is not None \
                and self.page_stack.currentIndex() == 1:
            self._fit_full_image()

    # ---------- UI 构建 ----------

    def _build_feedback_card(self):
        """反馈卡片 - 单张大卡片，内含标题、说明、按钮"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel(self._t("feedback_title", "Feedback"))
        title.setFont(ui_font(15, bold=True))
        title.setObjectName("feedbackTitle")
        layout.addWidget(title)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background: #E81123; border: none;")
        layout.addWidget(line)

        # 主体说明 - 第一段
        body1 = QLabel(self._t(
            "feedback_body_1",
            "Before submitting feedback, please check for duplicates. If a duplicate exists, please do not submit again to avoid burdening the maintainer."
        ))
        body1.setFont(ui_font(11))
        body1.setWordWrap(True)
        body1.setObjectName("feedbackBody1")
        layout.addWidget(body1)

        # 主体说明 - 第二段（提示）
        body2 = QLabel(self._t(
            "feedback_body_2",
            "Note: All feedback is listed at the end of this page. For more, please visit GitHub."
        ))
        body2.setFont(ui_font(10))
        body2.setWordWrap(True)
        body2.setObjectName("feedbackBody2")
        layout.addWidget(body2)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        self.btn_go = PrimaryPushButton(
            self._t("feedback_go", "Go to Feedback")
        )
        self.btn_go.setMinimumWidth(140)
        # ⚠️ 凡是"左键点开浏览器"的地方都要补 Ctrl+左键逻辑（这颗按钮以前直接 QDesktopServices 打开）
        self._go_ctrl = watch_ctrl(self.btn_go)
        self.btn_go.setToolTip(self._t("ctrl_open_tip", "Ctrl+click: open quietly without switching away"))
        self.btn_go.clicked.connect(self.on_go_feedback)
        btn_row.addWidget(self.btn_go)

        layout.addLayout(btn_row)

        self.main_layout.addWidget(card)

        # ---- QQ 加群：两个群并排（图片在 .ToolsGCP/images/qq/ 下）----
        # 原来那两行纯文字群号已删除，改成"每张图片上方一行：文字 + 复制群号按钮"
        self._build_qq_row()

    def _build_qq_row(self):
        """两张加群图片并排，各自顶部一行「复制群号」按钮。

        ⚠️ 用独立容器控件承载这一行，而不是往 main_layout 里直接 addLayout：嵌套 layout
        在"固定尺寸图片 + 顶部按钮行"的组合下，Qt 的尺寸协商会反复触发重绘，
        实测第一次 paintEvent 就再也不返回（事件循环被饿死，连定时器都跑不到）。
        """
        container = QWidget(self)
        container.setObjectName("feedbackQQRow")
        # ⚠️ 需求："2张图片都要居中并列摆放 它们之间稍微空余一点空间……按钮位置在各自图片的居中位置"：
        #      · 整行居中（两端各来一个 stretch）；
        #      · 两张图之间留出 QQ_ROW_GAP 的空隙；按钮放在图片正上方居中，不再和图片叠在一起
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(QQ_ROW_GAP)
        row.addStretch(1)

        self.qq_cards = []
        self.qq_copy_buttons = []
        for group in QQ_GROUPS:
            column = QWidget(container)
            col = QVBoxLayout(column)
            col.setContentsMargins(0, 0, 0, 0)
            # 按钮和图片之间留一点竖向距离，避免贴在一起又被看成"重叠"
            col.setSpacing(10)
            col.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

            # 顶部一行：按钮水平居中（对齐到下面图片的中间）
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.addStretch(1)
            button = CopyNumberButton(
                self,
                group["number"],
                self._t("qq_copy_number", "Copy group number"),
                self._t("qq_copied", "Copied"),
                copy_tip=self._t("qq_copy_tip", "Copy group number {number}").format(
                    number=group["number"]),
                copied_tip=self._t("qq_copied", "Copied"))
            head.addWidget(button)
            head.addStretch(1)
            col.addLayout(head)

            image = QQImageCard(group["image"], column)
            ratio = image.aspect_ratio()
            width = QQ_IMAGE_WIDTH
            height = max(120, int(width * ratio)) if ratio else 200
            # ⚠️ 用 setFixedSize 一次定死宽高：只 setFixedWidth + setFixedHeight 会让布局在
            # "宽高比 + minimumHeight"之间反复协商（见上面那段说明）
            image.setFixedSize(width, height)
            # 点图片 → 进"看整张图"的单独页面（需求：像 github 页面微信图片放大那样）
            image.clicked = lambda g=group: self.show_full_image(g["image"])
            col.addWidget(image, 0, Qt.AlignHCenter)

            row.addWidget(column, 0, Qt.AlignTop)
            self.qq_cards.append(image)
            self.qq_copy_buttons.append(button)

        row.addStretch(1)
        self.main_layout.addWidget(container, 0, Qt.AlignHCenter)

    # ---------- 图片放大查看页 ----------
    def _build_image_page(self):
        """"看整张图"的单独页面（一个 QStackedWidget：第 0 页是反馈内容，第 1 页是整张图 + 返回按钮）。

        ⚠️ QScrollArea 的视口默认会用调色板填充底色（浅色主题下是一块白底），光把外层 QWidget
        设成 transparent 去不掉 —— 必须连 QScrollArea、它的 viewport() 和承载图片的 QLabel 一起设透明。
        """
        page = QWidget()
        page.setObjectName("feedbackImageView")
        page.setAttribute(Qt.WA_StyledBackground, True)
        page.setStyleSheet("QWidget#feedbackImageView { background: transparent; }")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.back_btn = PushButton("← " + self._t("feedback_back", "Back"))
        self.back_btn.setFixedWidth(100)
        self.back_btn.clicked.connect(self.show_content_page)
        header.addWidget(self.back_btn)
        header.addStretch()
        layout.addLayout(header)

        # 用可滚动的区域装大图：图比窗口大时可以拖着看
        self.image_scroll = QScrollArea(page)
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setFrameShape(QFrame.NoFrame)
        self.image_scroll.setAlignment(Qt.AlignCenter)
        # ⚠️ 背景填充色在这里去掉（视口 + 滚动区本体，两层都要）
        self.image_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        self.image_scroll.viewport().setAutoFillBackground(False)
        self.image_scroll.viewport().setStyleSheet("background: transparent;")
        self.image_scroll.setAutoFillBackground(False)
        # ⚠️ 需求："QQ图片点击进入后可以再次点击图片进行退出"：承载大图的 label 换成 ClickableLabel；
        #    图片四周的空白（滚动区视口）也接上同一个动作 —— 等比缩放后四周一定有留白
        self.full_image_label = ClickableLabel()
        self.full_image_label.setAlignment(Qt.AlignCenter)
        self.full_image_label.setCursor(Qt.PointingHandCursor)
        self.full_image_label.setStyleSheet("background: transparent;")
        self.full_image_label.setAutoFillBackground(False)
        self.full_image_label.clicked.connect(self.show_content_page)
        self.full_image_label.setToolTip(self._t("feedback_click_to_close",
                                                 "Click the image to go back"))
        self.image_scroll.setWidget(self.full_image_label)
        layout.addWidget(self.image_scroll, 1)

        # 视口上的点击（图片四周的空白）也返回；用事件过滤器，别给 QScrollArea 打补丁
        self.image_scroll.viewport().installEventFilter(self)
        self._image_view_active = False

        tip = QLabel(self._t("feedback_click_to_close", "Click the image to go back"))
        tip.setAlignment(Qt.AlignCenter)
        tip.setStyleSheet("color: gray; font-size: 11px; background: transparent;")
        layout.addWidget(tip)

        return page

    def eventFilter(self, obj, event):
        """看大图时，点图片四周的空白也返回反馈页"""
        if getattr(self, "_image_view_active", False):
            try:
                if obj is self.image_scroll.viewport() \
                        and event.type() == event.MouseButtonRelease \
                        and event.button() == Qt.LeftButton:
                    self.show_content_page()
                    return True
            except RuntimeError:
                pass
        return super().eventFilter(obj, event)

    def show_full_image(self, image_path: str):
        """进入"看整张图"页：按窗口大小等比缩放到最大。

        ⚠️ 必须先切页、再缩放：切页之前这张页面还从没被真正布局过，viewport().size() 拿到的是
        默认值（100×30 之类），先缩放第一次一定缩成一个随机小图（用户报的"第一次进来大小不对，
        第二次就正常了"）。这里先切页、再缩放，并在下一拍（布局完成后）补一次 —— 第一次进来就是对的。
        """
        pixmap = QPixmap(str(image_path or ""))
        if pixmap.isNull():
            return
        self._full_pixmap = pixmap
        self._image_view_active = True
        self.page_stack.setCurrentIndex(1)
        # ① 先按当前已知尺寸放一张，避免切过去的一瞬间是空白
        self._fit_full_image()
        # ② 布局/视口尺寸稳定后再算一次（第一次进来时靠这一步拿到正确大小）
        QTimer.singleShot(0, self._fit_full_image)

    def _fit_full_image(self):
        """把大图按当前可视区等比缩放（窗口变大也要跟着变）。

        ⚠️ 视口还没布局好（尺寸是默认值）时不要拿它去缩放 —— 那正是"第一次进来图特别小"的来源。
        """
        pixmap = getattr(self, "_full_pixmap", None)
        if pixmap is None or pixmap.isNull():
            return
        try:
            area = self.image_scroll.viewport().size()
        except Exception:
            return
        if area.width() <= 40 or area.height() <= 40:
            # 视口还没排好版：退回本页尺寸减去四周留白
            area = self.image_scroll.size()
        if area.width() <= 40 or area.height() <= 40:
            area = self.size()
        if area.width() <= 40 or area.height() <= 40:
            return
        self.full_image_label.setPixmap(
            pixmap.scaled(area, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def show_content_page(self):
        """从大图页返回反馈内容页"""
        self._image_view_active = False
        self.page_stack.setCurrentIndex(0)

    # ---------- 行为 ----------

    def on_go_feedback(self):
        """打开反馈页：左键 → 浏览器到前台；Ctrl+左键 → 浏览器打开但不抢走当前程序的焦点。"""
        # 不传 background：交给 open_url 自己判断 Ctrl
        # 不传 background：交给 open_url 自己判断 Ctrl（按下时记的 或 此刻按着的）
        background = ctrl_active()
        ok = open_url(FEEDBACK_URL, "反馈")
        if ok:
            log.info("反馈", "feedback",
                     f"打开反馈链接: {FEEDBACK_URL}（{'后台' if background else '前台'}）")
            self._toast(self._t("feedback_opened", "Opened in browser"), InfoBar.success)
        else:
            log.err("反馈", "feedback", f"打开反馈链接失败: {FEEDBACK_URL}")
            self._toast(self._t("feedback_failed", "Failed to open, please check your default browser"),
                        InfoBar.error)

    def _toast(self, content, bar_type=InfoBar.info):
        bar_type(
            title=self._t("feedback_toast_title", "Feedback"),
            content=content,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self,
        )
