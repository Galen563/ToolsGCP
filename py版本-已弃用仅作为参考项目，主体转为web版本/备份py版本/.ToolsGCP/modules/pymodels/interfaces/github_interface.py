"""GitHub 界面。"""

from ..utils.fonts import ui_font
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QGridLayout, QFrame, QStackedWidget, QScrollArea)
from PyQt5.QtGui import QFont, QPixmap, QColor, QCursor
from qfluentwidgets import SimpleCardWidget, PushButton
from PyQt5.QtWidgets import QGraphicsDropShadowEffect
import os
import sys
if sys.platform == 'win32':
    import winreg

from ..core.language_manager import LanguageManager
from ..core.settings_manager import SettingsManager
from ..ui.components.circle_avatar import CircleAvatar
from ..utils.logger import log
from ..utils.smooth_scroll import install_smooth_scroll
from ..utils.url_open import open_url
from ..constants import SCRIPT_DIR, APP_HOMEPAGE


# 语言文件缺失时的内嵌英文兜底
# ⚠️ 统一用英文：语言文件夹被移走时整个界面应当是完整英文，不能一半英文一半 key 名
_GITHUB_FALLBACK = {
    "github": "Repository",
    "avatar_alt": "Galen563",
    "close": "Back",
    "click_to_close": "Click anywhere on the image to close",
    "click_to_zoom": "Click to enlarge",
    # 「作者Github」= 作者主页链接的提示词；「Github」= 项目仓库链接的提示词
    "visit_github": "Author GitHub: ",
    "repo_link": "Github: ",
    "tools_intro_title": "About ToolsGCP:",
    "tools_intro_point1": "- Free and open-source tool collection",
    "tools_intro_point2": "- Solves daily computer software search problems",
    "tools_intro_point3": "- Provides software download, installation, introduction and usage methods",
    "tools_intro_point4": "- Prevents downloading pirated or adware software",
    "tools_intro_point5": "- Provides resource acquisition and other functions",
    # 赞助备注提示（需求："提示赞助时记得写上备注，包括昵称（必填）和实际金额"）
    "sponsor_note_title": "Please add a payment note",
    "sponsor_note": "When sponsoring, remember to put your nickname (required) "
                    "and the actual amount in the note — it helps the author "
                    "verify the payment and thank you properly.",
}

# 两个链接的地址：作者主页 / 项目仓库
AUTHOR_GITHUB_URL = "https://github.com/Galen563"

# 赞助二维码的显示尺寸（"点击放大图片"那行提示也按这个宽度居中）
QR_IMAGE_WIDTH = 190
QR_IMAGE_HEIGHT = 240
# 作者头像的尺寸（正方形）
AVATAR_SIZE = 96
# 卡片里的正文 / 链接字号（原来 9~10 号偏小，整块看着缩在左上角）
BODY_FONT_SIZE = 11

# 内容区最大宽度 + 卡片内边距 / 间距
# ⚠️ 不限宽的话窗口最大化到 1920 之后两块内容会被拉到屏幕两头（左边头像、右边二维码，中间空一大片）
CONTENT_MAX_WIDTH = 1280
CARD_PADDING = 26
COLUMN_GAP = 22
ROW_GAP = 22


class GithubInterface(QWidget):
    """GitHub页面"""
    
    def __init__(self, language_manager: LanguageManager = None, 
                 settings_manager: SettingsManager = None):
        super().__init__()
        self.setObjectName("githubInterface")
        self.lang = language_manager
        self.settings_manager = settings_manager
        self.is_dark_theme = False
        # 卡片上需要跟着主题重新上色的东西（在 create_content_page 之前初始化）
        self._dividers = []       # 卡片标题下面那条 1px 分隔线
        self._note_panels = []    # 赞助备注面板 (面板, 标题, 正文)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack)
        
        self.content_page = self.create_content_page()
        self.stack.addWidget(self.content_page)
        
        self.image_page = self.create_image_page()
        self.stack.addWidget(self.image_page)

        # ⚠️ 凡是有左上角退出按钮的页面都要保证 Esc 返回上级（大图页就是「← 关闭」→ 回内容页）
        #    QShortcut 必须存成属性：只写局部变量的话 Python 一回收，快捷键就跟着失效
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._esc_shortcut.activated.connect(self._on_escape)

        self.apply_theme()

    def _on_escape(self):
        """Esc：正在看大图就退回内容页（已经在内容页时什么都不做）"""
        try:
            if self.stack.currentIndex() == 1:
                self.show_content_page()
        except RuntimeError:
            pass
    
    def create_content_page(self):
        """创建内容页面：上半「作者 | 赞助」两块等宽并排，下半「ToolsGCP 介绍」跨满整行。

        两块内容各自装进一张卡片（自带背景和描边，分界一眼可见）；整页限宽 CONTENT_MAX_WIDTH 并居中。
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 使用QScrollArea作为滚动容器，添加同款滚动条样式
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area = scroll

        # 应用同款滚动条样式
        self._apply_scrollbar_style(scroll)
        install_smooth_scroll(scroll)

        # 居中容器：外层左右各一个弹簧，里层钉死最大宽度
        holder = QWidget()
        # ⚠️ 给容器起个名字，主题样式表里就能只把它刷成透明，而不是用 QWidget{...} 把卡片底色也一起刷没
        holder.setObjectName("githubContentHolder")
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(44, 36, 44, 36)
        holder_layout.setSpacing(0)
        holder_layout.addStretch(1)

        self.content_box = QWidget(holder)
        self.content_box.setMaximumWidth(CONTENT_MAX_WIDTH)
        # 弹性给到内容本身，窗口变窄时它跟着缩（最大宽度只是上限）
        # ⚠️ 同时钉成 AlignTop：不然内容框会被拉满整个视口高度，最后那张卡片底下会拖出一大片空白
        holder_layout.addWidget(self.content_box, 12, Qt.AlignTop)

        holder_layout.addStretch(1)

        grid = QGridLayout(self.content_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(COLUMN_GAP)
        grid.setVerticalSpacing(ROW_GAP)

        left_top = self._create_author_card()       # 作者信息 + 两个链接
        right_top = self._create_sponsor_card()     # 赞助二维码 + 备注提示
        bottom = self._create_tools_intro_card()    # ToolsGCP 介绍（整行）

        grid.addWidget(left_top, 0, 0)
        grid.addWidget(right_top, 0, 1)
        grid.addWidget(bottom, 1, 0, 1, 2)

        # 两行都按内容高度走（不给行高弹性）：窗口拉高时不会把某一块撑成一张空卡片
        grid.setRowStretch(0, 0)
        grid.setRowStretch(1, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        scroll.setWidget(holder)
        layout.addWidget(scroll)

        return page

    def _make_card(self, title_key, title_size=18):
        """一张内容卡片：标题 + 1px 分隔线 + 内容布局。

        统一走 qfluentwidgets 的卡片控件（深浅主题、圆角、描边由它负责），三张卡片口径一致。
        """
        card = SimpleCardWidget(self.content_box)
        card.setBorderRadius(10)
        box = QVBoxLayout(card)
        box.setContentsMargins(CARD_PADDING, CARD_PADDING - 2,
                               CARD_PADDING, CARD_PADDING - 2)
        box.setSpacing(12)

        if title_key:
            title = QLabel(self.get_text(title_key))
            title.setFont(ui_font(title_size, bold=True))
            title.setObjectName("whiteInDarkLabel")
            box.addWidget(title)

            divider = QFrame(card)
            divider.setFixedHeight(1)
            divider.setObjectName("githubCardDivider")
            self._dividers.append(divider)
            box.addWidget(divider)
        return card, box
    
    def _apply_scrollbar_style(self, scroll_area):
        """应用同款滚动条样式"""
        is_dark = self.is_dark_theme
        
        scrollbar_bg = "transparent"
        handle_color = "#555555" if is_dark else "#CCCCCC"
        handle_hover = "#666666" if is_dark else "#AAAAAA"
        handle_pressed = "#777777" if is_dark else "#999999"
        
        scrollbar_style = f"""
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background-color: {scrollbar_bg};
                width: 8px;
                margin: 0px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {handle_color};
                min-height: 30px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {handle_hover};
            }}
            QScrollBar::handle:vertical:pressed {{
                background-color: {handle_pressed};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """
        scroll_area.setStyleSheet(scrollbar_style)
    
    def _create_author_card(self):
        """左上：作者信息卡片（标题 + 头像 + 开发者信息 + 两条链接）。

        三处弹簧把多余的高度均分到"标题 / 头像行 / 链接"之间 —— 这张卡片被右边那张二维码撑高后，
        内容才不会全挤在左上角。
        """
        card, box = self._make_card("github_title", 20)

        box.addStretch(1)

        header_widget = QWidget(card)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(18)

        avatar_path = os.path.join(SCRIPT_DIR, ".ToolsGCP", "images", "Galen563 png.png")
        if os.path.exists(avatar_path):
            avatar = CircleAvatar(avatar_path, size=AVATAR_SIZE, lang_manager=self.lang)
            header_layout.addWidget(avatar)
        else:
            avatar_label = QLabel(self.get_text("avatar_alt"))
            avatar_label.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
            avatar_label.setAlignment(Qt.AlignCenter)
            avatar_label.setStyleSheet(
                f"background-color: #00D4FF; border-radius: {AVATAR_SIZE // 2}px;"
                " color: white; font-weight: bold;")
            header_layout.addWidget(avatar_label)

        dev_info = QLabel(f"{self.get_text('developer')}\n{self.get_text('dev_team')}")
        dev_info.setFont(ui_font(BODY_FONT_SIZE))
        dev_info.setObjectName("whiteInDarkLabel")
        dev_info.setWordWrap(True)
        header_layout.addWidget(dev_info, 1)
        box.addWidget(header_widget)

        box.addStretch(1)

        # 两条链接：作者Github / 项目仓库 Github
        links = QWidget(card)
        links_box = QVBoxLayout(links)
        links_box.setContentsMargins(0, 0, 0, 0)
        links_box.setSpacing(10)
        links_box.addWidget(self._create_link_label("visit_github", AUTHOR_GITHUB_URL))
        links_box.addWidget(self._create_link_label("repo_link", APP_HOMEPAGE))
        box.addWidget(links)
        box.addStretch(1)
        return card

    def _create_link_label(self, text_key, url):
        """一条「提示词 + 可点链接」的文字（两条链接共用同一套样式）。

        ⚠️ 必须关掉 setOpenExternalLinks：打开时 Qt 会自己用 QDesktopServices 打开链接，
        绕过 utils/url_open（没有 Ctrl+左键逻辑，也没有外链日志）。
        """
        label = QLabel(
            f'{self.get_text(text_key)}'
            f'<a href="{url}" style="color: #00D4FF;">{url}</a>')
        label.setFont(ui_font(BODY_FONT_SIZE))
        label.setObjectName("whiteInDarkLabel")
        label.setOpenExternalLinks(False)
        label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        label.linkActivated.connect(self._on_external_link)
        return label

    def _create_tools_intro_card(self):
        """下半：ToolsGCP 介绍（整行一张卡片）"""
        card, box = self._make_card("tools_intro_title", 18)

        intro_points = [
            self.get_text("tools_intro_point1"),
            self.get_text("tools_intro_point2"),
            self.get_text("tools_intro_point3"),
            self.get_text("tools_intro_point4"),
            self.get_text("tools_intro_point5"),
        ]

        body = QWidget(card)
        body_box = QVBoxLayout(body)
        body_box.setContentsMargins(0, 0, 0, 0)
        body_box.setSpacing(10)
        for point in intro_points:
            label = QLabel(point)
            label.setFont(ui_font(BODY_FONT_SIZE))
            label.setObjectName("whiteInDarkLabel")
            label.setWordWrap(True)
            body_box.addWidget(label)
        box.addWidget(body)

        box.addStretch(1)
        return card

    def _create_sponsor_card(self):
        """右上：赞助卡片（标题 + 二维码 + 放大提示 + 备注提示）。

        二维码在卡片里居中，"点击放大图片"紧跟其下（宽度钉成二维码宽度）；备注提示单独放一块有底色的面板。
        """
        card, box = self._make_card("sponsor_title", 18)

        self.qr_path = os.path.join(SCRIPT_DIR, ".ToolsGCP", "images",
                                    "微信Galen563的ToolsGCP项目赞助.jpg")
        if os.path.exists(self.qr_path):
            self.qr_label = QLabel(card)
            self.qr_label.setAlignment(Qt.AlignCenter)
            self.qr_label.setCursor(QCursor(Qt.PointingHandCursor))
            self.qr_label.setFixedSize(QR_IMAGE_WIDTH, QR_IMAGE_HEIGHT)

            pixmap = QPixmap(self.qr_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(QR_IMAGE_WIDTH - 20, QR_IMAGE_HEIGHT - 20,
                                       Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.qr_label.setPixmap(scaled)

                shadow = QGraphicsDropShadowEffect()
                shadow.setBlurRadius(8)
                shadow.setColor(QColor(0, 0, 0, 80))
                shadow.setOffset(2, 2)
                self.qr_label.setGraphicsEffect(shadow)

                self.qr_label.mousePressEvent = lambda e: self.show_full_image()

            box.addWidget(self.qr_label, 0, Qt.AlignHCenter)

            click_tip = QLabel(self.get_text("click_to_zoom"), card)
            click_tip.setFont(ui_font(BODY_FONT_SIZE - 1))
            click_tip.setObjectName("whiteInDarkLabel")
            click_tip.setStyleSheet("color: gray;")
            # 宽度钉成二维码宽度 + 居中：这样它永远是"图片正下方居中"，不会随着卡片宽度飘走
            click_tip.setAlignment(Qt.AlignCenter)
            click_tip.setFixedWidth(QR_IMAGE_WIDTH)
            box.addWidget(click_tip, 0, Qt.AlignHCenter)

        box.addWidget(self._create_sponsor_note(card))
        box.addStretch(1)
        return card

    def _create_sponsor_note(self, parent):
        """赞助备注提示面板（标题 + 一句正文）。

        面板自己的底色要跟着深浅主题走（见 apply_theme），不然浅色下会变成"深色面板 + 黑字"。
        """
        panel = QFrame(parent)
        panel.setObjectName("githubSponsorNote")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 14, 16, 14)
        panel_layout.setSpacing(6)

        title = QLabel(self.get_text("sponsor_note_title"), panel)
        title.setObjectName("githubSponsorNoteTitle")
        title.setFont(ui_font(BODY_FONT_SIZE, bold=True))
        title.setWordWrap(True)
        panel_layout.addWidget(title)

        body = QLabel(self.get_text("sponsor_note"), panel)
        body.setObjectName("githubSponsorNoteBody")
        body.setFont(ui_font(BODY_FONT_SIZE - 1))
        body.setWordWrap(True)
        panel_layout.addWidget(body)

        self._note_panels.append((panel, title, body))
        return panel
    
    def create_image_page(self):
        """创建图片全屏页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        back_btn = PushButton("← " + self.get_text("close"))
        back_btn.setFixedWidth(90)
        back_btn.clicked.connect(self.show_content_page)
        header_layout.addWidget(back_btn)
        header_layout.addStretch()
        
        layout.addWidget(header)
        
        self.full_image_label = QLabel()
        self.full_image_label.setAlignment(Qt.AlignCenter)
        self.full_image_label.setCursor(QCursor(Qt.PointingHandCursor))
        self.full_image_label.mousePressEvent = lambda e: self.show_content_page()
        
        layout.addWidget(self.full_image_label, 1)
        
        tip = QLabel(self.get_text("click_to_close"))
        tip.setAlignment(Qt.AlignCenter)
        tip.setStyleSheet("color: gray; font-size: 11px;")
        tip.setObjectName("whiteInDarkLabel")
        layout.addWidget(tip)
        
        return page
    
    def show_full_image(self):
        """显示全屏图片"""
        if hasattr(self, 'qr_path') and os.path.exists(self.qr_path):
            pixmap = QPixmap(self.qr_path)
            if not pixmap.isNull():
                self.original_pixmap = pixmap
                self.stack.setCurrentIndex(1)
                self.update_image_size()
                log.info("GitHub", "github", "查看赞助二维码")
    
    def update_image_size(self):
        """更新图片大小（大图页里让二维码尽量铺满可用区域）"""
        if hasattr(self, 'original_pixmap') and self.original_pixmap and not self.original_pixmap.isNull():
            available_width = self.width() - 200
            available_height = self.height() - 220
            
            scaled = self.original_pixmap.scaled(
                available_width, available_height, 
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.full_image_label.setPixmap(scaled)
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.stack.currentIndex() == 1:
            self.update_image_size()
    
    def _on_external_link(self, url: str):
        """页面上那些外链文字被点了：统一走 utils/url_open（左键 = 浏览器到前台；Ctrl+左键 = 浏览器打开但不切走）。"""
        open_url(str(url or ""), "GitHub 页面")

    def show_content_page(self):
        """返回内容页面"""
        self.stack.setCurrentIndex(0)
    
    def get_text(self, key):
        if self.lang:
            text = self.lang.get_text("github", key)
            if text and text != key:
                return text
        # 语言文件缺失 / 没有这条 key → 用内嵌英文兜底（而不是把 key 名显示给用户）
        return _GITHUB_FALLBACK.get(key, key)
    
    def _detect_dark(self) -> bool:
        """当前是不是深色：以程序实际用的主题为准（qfluentwidgets 的 isDarkTheme()）。

        ⚠️ 只读设置 + 注册表会和程序实际渲染的主题对不上（浅色界面下标签被刷成白字 → 白底白字）；
        注册表那条路留作兜底：库还没初始化时也能给出一个答案。
        """
        try:
            from qfluentwidgets import isDarkTheme
            return bool(isDarkTheme())
        except Exception:
            pass
        if self.settings_manager:
            theme = self.settings_manager.settings.get("theme", "跟随系统")
            if theme == "深色主题":
                return True
            if theme == "浅色主题":
                return False
        try:
            if sys.platform == 'win32':
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                winreg.CloseKey(key)
                return value == 0
        except Exception:
            pass
        return False

    def apply_theme(self):
        """应用主题（卡片分隔线 / 备注面板底色都跟着切）。

        ⚠️ 两块东西分开刷：标签颜色可以让父级样式表按 objectName 管（QLabel 的颜色规则能从祖先继承）；
        但 QFrame 的底色必须 setStyleSheet 到它自己身上 —— 祖先样式表里的 QFrame#xxx { background }
        对 QFrame 不生效（不会因此打上 WA_StyledBackground，表现是分隔线和备注面板一点底色都没有）。
        所以这里拿着建卡片时登记的两张清单逐个上色。
        """
        self.is_dark_theme = self._detect_dark()

        if self.is_dark_theme:
            divider_color = "rgba(255,255,255,0.10)"
            note_bg = "rgba(0, 212, 255, 0.10)"
            note_border = "rgba(0, 212, 255, 0.28)"
            label_color = "#FFFFFF"
        else:
            divider_color = "rgba(0,0,0,0.08)"
            note_bg = "rgba(0, 150, 190, 0.08)"
            note_border = "rgba(0, 150, 190, 0.24)"
            label_color = "#000000"

        self.setStyleSheet(f"""
            QWidget#githubInterface, QWidget#githubContentHolder,
            QScrollArea, QWidget#qt_scrollarea_viewport {{
                background-color: transparent;
            }}
            QLabel#whiteInDarkLabel {{ color: {label_color}; }}
            QLabel#githubSponsorNoteTitle {{ color: {'#4DD8FF' if self.is_dark_theme else '#00708A'}; }}
            QLabel#githubSponsorNoteBody {{
                color: {'rgba(255,255,255,0.86)' if self.is_dark_theme else 'rgba(0,0,0,0.78)'};
            }}
        """)

        for divider in self._dividers:
            try:
                divider.setStyleSheet(f"background-color: {divider_color}; border: none;")
            except RuntimeError:
                pass
        for panel, _title, _body in self._note_panels:
            try:
                panel.setStyleSheet(
                    f"QFrame#githubSponsorNote {{ background-color: {note_bg};"
                    f" border: 1px solid {note_border}; border-radius: 8px; }}")
            except RuntimeError:
                pass


    
    def refresh_theme(self):
        """刷新主题"""
        self.apply_theme()
        # 刷新滚动条样式
        if hasattr(self, 'content_page'):
            scroll = self.content_page.findChild(QScrollArea)
            if scroll:
                self._apply_scrollbar_style(scroll)
