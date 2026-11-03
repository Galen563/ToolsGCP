"""日志页面：顶部「日志操作」卡片（导出日志 / 导出全部日志 / 打开日志目录 / 清理历史日志）
+ 底部「所有日志」列表（自绘 ListWidgetItem：渐变背景、悬停动画、圆角，当前项左侧高亮条）。

主题跟随：自动适配深色 / 浅色主题。
"""

from ..utils.fonts import ui_font
import os
from datetime import datetime

from PyQt5.QtCore import (Qt, QSize, QUrl, QPropertyAnimation, QEasingCurve,
                          QAbstractAnimation, pyqtProperty, pyqtSignal, QRect, QPoint)
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QFileDialog,
                             QMessageBox, QFrame, QDialog, QSpacerItem,
                             QSizePolicy, QGraphicsDropShadowEffect,
                             QGraphicsOpacityEffect, QApplication)
from PyQt5.QtGui import QFont, QColor, QDesktopServices, QPainter, QBrush, QLinearGradient, QPen

from qfluentwidgets import (SimpleCardWidget, PushButton, PrimaryPushButton,
                            FluentIcon as FIF, InfoBar, InfoBarPosition,
                            isDarkTheme)

from ..core.language_manager import LanguageManager
from ..utils.logger import log
from ..ui.log_viewer_window import open_log_window
from ..utils.theme_utils import is_dark_mode
from ..constants import LOGS_DIR, LOG_HISTORY_DIR, APP_NAME


# ========== 颜色（统一在这里改） ==========

# 列表项
COLOR_ITEM_BG_NORMAL = "transparent"
COLOR_ITEM_BG_HOVER = "rgba(64, 158, 255, 0.10)"
COLOR_ITEM_BG_SELECTED_START = "rgba(64, 158, 255, 0.32)"
COLOR_ITEM_BG_SELECTED_END = "rgba(64, 158, 255, 0.12)"
COLOR_ITEM_LEFT_BAR_SELECTED = "#409EFF"

# (当前) 项 - 蓝色渐变
COLOR_CURRENT_BG_START = "rgba(64, 158, 255, 0.20)"
COLOR_CURRENT_BG_END = "rgba(64, 158, 255, 0.06)"
COLOR_CURRENT_LEFT_BAR = "#409EFF"

# 文字色
COLOR_TEXT_TIME_LIGHT = "#FFFFFF"
COLOR_TEXT_TIME_DARK = "#1F2329"
COLOR_TEXT_PATH_LIGHT = "#909399"
COLOR_TEXT_PATH_DARK = "#606266"
COLOR_TEXT_TAG = "#409EFF"

# 危险色
COLOR_DANGER = "#F56C6C"
COLOR_DANGER_HOVER = "rgba(245, 108, 108, 0.10)"
COLOR_DANGER_PRESSED = "rgba(245, 108, 108, 0.20)"

# 弹窗
COLOR_DIALOG_BG_START = "#2C3E50"
COLOR_DIALOG_BG_END = "#1F2D3D"
COLOR_DIALOG_TEXT = "#FFFFFF"

# 分隔线
COLOR_DIVIDER_LIGHT = "rgba(255, 255, 255, 0.08)"
COLOR_DIVIDER_DARK = "rgba(0, 0, 0, 0.08)"


# ========== 自定义组件 ==========

class LogItemWidget(QFrame):
    """日志列表的单条目 widget - 圆角 + 渐变 + 悬停动画"""

    # 双击：在独立窗口里打开这条日志（参数是文件路径）
    double_clicked = pyqtSignal(str, str)

    def __init__(self, timestamp_text, file_path, is_current, parent=None,
                 current_tag_text="（当前）", is_dark=True):
        super().__init__(parent)
        self.is_current = is_current
        self._selected = False
        self._hover_progress = 0.0
        self._is_dark = is_dark
        self._current_tag_text = current_tag_text
        self._list_widget = None  # 由 LogInterface 注入
        self._file_path = file_path
        self._display_name = timestamp_text
        # ⚠️ 悬停提示不在这里写死：这个控件是独立小部件、拿不到语言管理器，由 LogInterface 建完它之后设一次
        self.setToolTip("")

        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)
        # 设置对象名 & 初始样式
        self.setObjectName("logItem")
        self.setMinimumHeight(64)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(4)

        # 顶行：时间 + (当前) 标签
        top = QHBoxLayout()
        top.setSpacing(8)
        top.setContentsMargins(0, 0, 0, 0)

        self.time_label = QLabel(timestamp_text)
        self.time_label.setFont(ui_font(10, bold=True))
        top.addWidget(self.time_label)

        if is_current:
            self.tag_label = QLabel(self._current_tag_text)
            self.tag_label.setFont(ui_font(9))
            self.tag_label.setStyleSheet(
                f"color: {COLOR_TEXT_TAG}; background: transparent;"
            )
            top.addWidget(self.tag_label)

        top.addStretch()
        layout.addLayout(top)

        self.path_label = QLabel(file_path)
        self.path_label.setFont(QFont("Consolas", 9))
        self.path_label.setWordWrap(False)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.path_label)

        # 让子 label 的点击事件也同步到 frame（保证点时间/路径也能选中）
        self.time_label.installEventFilter(self)
        self.path_label.installEventFilter(self)

        self._apply_shadow()

        self._update_text_colors()
        self._update_style()

    def _apply_shadow(self):
        if self.is_current:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(12)
            shadow.setOffset(0, 2)
            shadow.setColor(QColor(64, 158, 255, 60))
            self.setGraphicsEffect(shadow)

    def set_dark_mode(self, is_dark):
        """设置主题模式"""
        self._is_dark = is_dark
        self._update_text_colors()
        self._update_style()

    def _update_text_colors(self):
        """根据主题更新文字颜色"""
        time_color = COLOR_TEXT_TIME_LIGHT if self._is_dark else COLOR_TEXT_TIME_DARK
        path_color = COLOR_TEXT_PATH_LIGHT if self._is_dark else COLOR_TEXT_PATH_DARK
        self.time_label.setStyleSheet(
            f"color: {time_color}; background: transparent;"
        )
        self.path_label.setStyleSheet(
            f"color: {path_color}; background: transparent;"
        )

    def enterEvent(self, event):
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        """双击 → 让 LogInterface 打开独立阅读窗口"""
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit(self._file_path, self._display_name)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        # 日志项不可选中 - 吞掉事件防止 list 选中（列表本身就是 NoSelection）
        event.ignore()

    def eventFilter(self, obj, event):
        """子 label 的点击 - 让 label 自己处理（可继续选中文字），但不影响列表项选中"""
        # 因为 list 已经是 NoSelection 模式，子 label 点击也不会触发任何选中状态
        return super().eventFilter(obj, event)

    def _animate_hover(self, target):
        if not hasattr(self, '_hover_anim') or self._hover_anim is None:
            self._hover_anim = QPropertyAnimation(self, b"hoverProgress")
            self._hover_anim.setDuration(200)
            self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
            self._hover_anim.valueChanged.connect(self._update_style)
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def get_hover_progress(self):
        return self._hover_progress

    def set_hover_progress(self, value):
        self._hover_progress = value
        self._update_style()

    hoverProgress = pyqtProperty(float, get_hover_progress, set_hover_progress)

    def _update_style(self):
        """根据当前状态更新样式 - 日志项不可选中，只有 hover 动画"""
        divider = COLOR_DIVIDER_LIGHT if self._is_dark else COLOR_DIVIDER_DARK

        if self.is_current:
            # (当前) 项 - 蓝色渐变 + 左侧高亮条 + 阴影
            self.setStyleSheet(f"""
                QFrame#logItem {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {COLOR_CURRENT_BG_START},
                        stop:1 {COLOR_CURRENT_BG_END});
                    border: none;
                    border-bottom: 1px solid {divider};
                    border-left: 3px solid {COLOR_CURRENT_LEFT_BAR};
                    border-radius: 8px;
                }}
            """)
        elif self._hover_progress > 0.01:
            # 悬停项 - 淡蓝色（与 (当前) 区分）
            alpha = 0.06 + 0.10 * self._hover_progress
            bg = f"rgba(64, 158, 255, {alpha:.3f})"
            self.setStyleSheet(f"""
                QFrame#logItem {{
                    background: {bg};
                    border: none;
                    border-bottom: 1px solid {divider};
                    border-radius: 8px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame#logItem {{
                    background: {COLOR_ITEM_BG_NORMAL};
                    border: none;
                    border-bottom: 1px solid {divider};
                    border-radius: 8px;
                }}
            """)

    def set_selected(self, selected):
        """保留接口但不做任何事 - 日志项不可选中"""
        self._selected = False  # 永远不被选中
        # 不调用 _update_style() 因为 _selected 不影响样式了


class ClearHistoryDialog(QDialog):
    """清理历史日志的自定义确认弹窗 - 圆角 + 渐入动画 + 缩放动画 + 屏幕居中"""

    def __init__(self, parent=None, lang=None):
        super().__init__(parent)
        self.lang = lang
        self._scale_anim = None

        self.setWindowTitle(self._t("log_clear_history", "Clear History Logs"))
        # 弹窗总大小 = 容器 + 阴影留白（让阴影能完整渲染，避免四个角出现硬边）
        self.SHADOW_MARGIN = 20  # 阴影留白
        self.CONTENT_W = 420
        self.CONTENT_H = 200
        self.setFixedSize(self.CONTENT_W + self.SHADOW_MARGIN * 2,
                          self.CONTENT_H + self.SHADOW_MARGIN * 2)
        # 无边框 + 透明背景
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # 容器 - 真正显示内容的 frame（居中，留出阴影空间）
        self.container = QFrame(self)
        self.container.setObjectName("dialogContainer")
        self.container.setGeometry(
            self.SHADOW_MARGIN, self.SHADOW_MARGIN,
            self.CONTENT_W, self.CONTENT_H,
        )

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(0)

        self.title = QLabel(self._t("log_clear_history", "Clear History Logs"))
        self.title.setFont(ui_font(14, bold=True))
        self.title.setStyleSheet(f"color: {COLOR_DANGER}; background: transparent;")
        layout.addWidget(self.title)

        layout.addSpacing(10)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {COLOR_DANGER}; border: none;")
        layout.addWidget(line)

        layout.addSpacing(20)

        # ⚠️ 必须开 wordWrap：确认文案较长，不换行的话文字会从固定宽度 420 的容器里横着顶出去被裁掉
        self.body = QLabel(self._t("log_clear_confirm_body", "Delete all history logs?"))
        self.body.setFont(ui_font(11))
        self.body.setWordWrap(True)
        self.body.setStyleSheet(f"color: {COLOR_DIALOG_TEXT}; background: transparent;")
        layout.addWidget(self.body)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        self.cancel_btn = PushButton(self._t("log_cancel", "Cancel"))
        self.cancel_btn.setMinimumWidth(80)
        self.cancel_btn.clicked.connect(self.reject)

        self.ok_btn = PushButton(self._t("log_confirm", "Confirm"))
        self.ok_btn.setMinimumWidth(80)
        self.ok_btn.setStyleSheet(f"""
            PushButton {{
                color: {COLOR_DANGER};
                border: 1px solid {COLOR_DANGER};
                background: transparent;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
            }}
            PushButton:hover {{ background: {COLOR_DANGER_HOVER}; }}
            PushButton:pressed {{ background: {COLOR_DANGER_PRESSED}; }}
        """)
        self.ok_btn.clicked.connect(self.accept)

        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.ok_btn)
        layout.addLayout(btn_row)

        # 容器样式 - 圆角 + 渐变背景
        self.container.setStyleSheet(f"""
            QFrame#dialogContainer {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {COLOR_DIALOG_BG_START},
                    stop:1 {COLOR_DIALOG_BG_END});
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
            }}
        """)

        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.container.setGraphicsEffect(shadow)

    def showEvent(self, event):
        """显示时居中到主窗口 - 先定位再启动动画"""
        super().showEvent(event)
        self._center_on_main_window()
        self._play_open_animation()

    def _center_on_main_window(self):
        """居中到主窗口（QApplication.activeWindow）或屏幕"""
        main_win = None
        if self.parent():
            p = self.parent()
            while p is not None:
                if p.isWindow():
                    main_win = p
                    break
                p = p.parent()

        if main_win is None:
            app = QApplication.instance()
            if app:
                main_win = app.activeWindow()

        if main_win is not None:
            # 用主窗口的 frameGeometry（含标题栏）来居中
            frame = main_win.frameGeometry()
            x = frame.x() + (frame.width() - self.width()) // 2
            y = frame.y() + (frame.height() - self.height()) // 2
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.x() + (screen.width() - self.width()) // 2
            y = screen.y() + (screen.height() - self.height()) // 2

        self.move(x, y)

    def _play_open_animation(self):
        """打开动画 - 渐入（透明度）"""
        self.setWindowOpacity(0.0)
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self._opacity_anim.setDuration(220)
        self._opacity_anim.setStartValue(0.0)
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._opacity_anim.start()

    def _t(self, key, default=None):
        if self.lang:
            try:
                result = self.lang.get_text("log", key)
                if result and result != key:
                    return result
            except Exception:
                pass
        return default if default is not None else key


# ========== 主页面 ==========

class LogInterface(QWidget):
    """日志页面"""

    def __init__(self, language_manager: LanguageManager = None,
                 settings_manager=None):
        super().__init__()
        self.setObjectName("logInterface")
        self.lang = language_manager
        self.settings_manager = settings_manager
        self._items = []
        self._widgets = []

        # 同步 logger 语言
        if self.lang:
            log.set_language(self.lang.current_language)

        self._is_dark = self._detect_dark_mode()

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(40, 30, 40, 30)
        self.main_layout.setSpacing(18)

        self._build_actions_card()
        self._build_logs_list_card()

        self._apply_theme_styles()
        self.refresh_list()

    # ---------- 工具 ----------

    def _t(self, key, default=None):
        if self.lang:
            try:
                result = self.lang.get_text("log", key)
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
        self._is_dark = self._detect_dark_mode()
        text_color = "#FFFFFF" if self._is_dark else "#1F2329"
        self.setStyleSheet(f"""
            QWidget#logInterface {{
                background: transparent;
            }}
            QLabel#logTitle {{
                color: {text_color};
                background: transparent;
            }}
            QLabel#logListTitle {{
                color: {text_color};
                background: transparent;
            }}
        """)

    def refresh_theme(self):
        """主题变化时由外部调用"""
        self._apply_theme_styles()
        # 通知所有 widget 更新主题
        for w in self._widgets:
            if hasattr(w, 'set_dark_mode'):
                w.set_dark_mode(self._is_dark)
        # 重建列表（确保时间/路径颜色正确） + 滚动条配色
        if self._items:
            self.refresh_list()
        # 即便没 items 也要刷新滚动条样式
        self.list_widget.setStyleSheet(self._build_list_style())

    def refresh_language(self):
        """语言变化时由外部调用 - 重新同步 logger 语言并刷新列表"""
        if self.lang:
            log.set_language(self.lang.current_language)
        self.refresh_list()

    # ---------- UI 构建 ----------

    def _build_actions_card(self):
        """顶部"日志操作"卡片"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = QLabel(self._t("log_operations", "Log Operations"))
        title.setFont(ui_font(14, bold=True))
        title.setObjectName("logTitle")
        layout.addWidget(title)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        # 导出日志 - 主要按钮（始终可用）
        self.btn_export = PrimaryPushButton(
            self._t("log_export_current", "Export Log"), self, FIF.SAVE
        )
        self.btn_export.setMinimumWidth(120)
        self.btn_export_all = PushButton(
            self._t("log_export_all", "Export All Logs"), self, FIF.SAVE
        )
        self.btn_export_all.setMinimumWidth(120)
        self.btn_open_dir = PushButton(
            self._t("log_open_dir", "Open Log Folder"), self, FIF.FOLDER
        )
        self.btn_open_dir.setMinimumWidth(120)

        # 清理历史日志 - 红色危险按钮
        self.btn_clear = PushButton(
            self._t("log_clear_history", "Clear History Logs"), self, FIF.DELETE
        )
        self.btn_clear.setMinimumWidth(120)
        self.btn_clear.setStyleSheet(f"""
            PushButton {{
                color: {COLOR_DANGER};
                border: 1px solid {COLOR_DANGER};
                background: transparent;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
            }}
            PushButton:hover {{
                background: {COLOR_DANGER_HOVER};
                border: 1px solid {COLOR_DANGER};
            }}
            PushButton:pressed {{
                background: {COLOR_DANGER_PRESSED};
                border: 1px solid {COLOR_DANGER};
            }}
            PushButton:disabled {{
                color: rgba(245, 108, 108, 0.4);
                border: 1px solid rgba(245, 108, 108, 0.4);
                background: transparent;
            }}
        """)

        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_export_all)
        btn_layout.addWidget(self.btn_open_dir)
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)

        self.btn_export.clicked.connect(self.on_export_current)
        self.btn_export_all.clicked.connect(self.on_export_all)
        self.btn_open_dir.clicked.connect(self.on_open_dir)
        self.btn_clear.clicked.connect(self.on_clear_history)

        self.main_layout.addWidget(card)

    def _build_logs_list_card(self):
        """底部日志列表卡片"""
        card = SimpleCardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        self.list_title = QLabel(self._t("log_all_logs", "All Logs"))
        self.list_title.setFont(ui_font(12, bold=True))
        self.list_title.setObjectName("logListTitle")
        layout.addWidget(self.list_title)

        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(380)
        self.list_widget.setSelectionMode(QListWidget.NoSelection)  # 不可选中
        self.list_widget.setFrameShape(QFrame.NoFrame)
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list_widget.setFocusPolicy(Qt.NoFocus)  # 不接受焦点，避免虚线框
        self.list_widget.setStyleSheet(self._build_list_style())

        layout.addWidget(self.list_widget, 1)

        self.main_layout.addWidget(card, 1)

    # ---------- 列表 ----------

    def _build_list_style(self):
        """构建 QListWidget 样式 - 自定义滚动条（细长、圆角、主题感知）"""
        # 滚动条配色 - 跟当前主题走
        if self._is_dark:
            track_color = "rgba(255, 255, 255, 0.03)"
            handle_color = "rgba(255, 255, 255, 0.20)"
            handle_hover = "rgba(64, 158, 255, 0.65)"
            handle_pressed = "rgba(64, 158, 255, 0.90)"
        else:
            track_color = "rgba(0, 0, 0, 0.04)"
            handle_color = "rgba(0, 0, 0, 0.20)"
            handle_hover = "rgba(64, 158, 255, 0.65)"
            handle_pressed = "rgba(64, 158, 255, 0.90)"

        return f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: 0;
            }}
            QListWidget::item {{
                border: none;
                padding: 0;
                margin: 4px 0;
            }}
            QListWidget::item:hover {{ background: transparent; }}
            QListWidget::item:selected {{ background: transparent; }}
            QListWidget::item:focus {{ outline: none; }}

            /* 垂直滚动条 - 细长圆角 */
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 4px 2px 4px 0;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {handle_color};
                min-height: 40px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {handle_hover};
            }}
            QScrollBar::handle:vertical:pressed {{
                background: {handle_pressed};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0;
                background: none;
                border: none;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: {track_color};
                border-radius: 4px;
            }}

            /* 水平滚动条 - 几乎用不到，但保留统一样式 */
            QScrollBar:horizontal {{
                background: transparent;
                height: 8px;
                margin: 0 4px 2px 4px;
                border: none;
            }}
            QScrollBar::handle:horizontal {{
                background: {handle_color};
                min-width: 40px;
                border-radius: 4px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {handle_hover};
            }}
            QScrollBar::handle:horizontal:pressed {{
                background: {handle_pressed};
            }}
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {{
                width: 0;
                background: none;
                border: none;
            }}
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {{
                background: {track_color};
                border-radius: 4px;
            }}

            /* 角落 */
            QScrollBar::corner {{
                background: transparent;
                border: none;
            }}
        """

    def refresh_list(self):
        """刷新日志列表"""
        self.list_widget.clear()
        self._widgets.clear()
        self._items = log.list_logs()
        current_tag = self._t("log_current_tag", "(Current)")

        if not self._items:
            empty = QListWidgetItem(self._t("log_no_logs", "No logs yet"))
            empty.setFlags(Qt.NoItemFlags)
            empty.setTextAlignment(Qt.AlignCenter)
            empty.setFont(ui_font(11))
            self.list_widget.addItem(empty)
            self.btn_export.setEnabled(False)
            self.btn_export_all.setEnabled(False)
            self.btn_clear.setEnabled(False)
            return

        for item in self._items:
            li = QListWidgetItem(self.list_widget)
            li.setSizeHint(QSize(0, 68))
            li.setData(Qt.UserRole, item)
            self.list_widget.addItem(li)

            # 时间显示（如果是 current，不再拼接 "(当前)/(Current)"，由 widget 的 tag 标签处理）
            display_name = item["name"]
            for suffix in (" (当前)", " (Current)"):
                if item["is_current"] and display_name.endswith(suffix):
                    display_name = display_name[:-len(suffix)]
                    break

            w = LogItemWidget(
                display_name, item["path"], item["is_current"],
                current_tag_text=current_tag, is_dark=self._is_dark,
            )
            # ⚠️ 悬停提示原来写死在 LogItemWidget 里（注释说"由 LogInterface 覆盖"，其实没那一步），这里补上
            try:
                w.setToolTip(self._t("open_in_window_tip",
                                     "Double-click to open this log in a window"))
            except Exception:
                pass
            w._list_widget = self.list_widget
            w.double_clicked.connect(self.open_log_in_window)
            self._widgets.append(w)
            self.list_widget.setItemWidget(li, w)

        # 清除选中 - 不要默认选中任何日志
        self.list_widget.setCurrentRow(-1)
        self.btn_export.setEnabled(True)
        self.btn_export_all.setEnabled(True)
        has_history = any(not it["is_current"] for it in self._items)
        self.btn_clear.setEnabled(has_history)

    # ---------- 按钮行为 ----------

    # ---------- 双击打开独立阅读窗口 ----------
    def open_log_in_window(self, path: str, display_name: str):
        """在独立窗口（浏览器式多标签）里打开一份日志"""
        try:
            import os as _os
            created = not open_log_window(path, _os.path.basename(path),
                                          language_manager=self.lang)
            log.op("日志", "open_window", file=path,
                   state="新建标签" if created else "切到已开标签")
        except Exception as e:
            log.err("日志", "open_window", f"打开日志窗口失败: {e}")

    def _get_system_log_path(self):
        return log.current_path

    def on_export_current(self):
        """导出日志：打包 system_log.log（始终可用）"""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{APP_NAME}_Log_{stamp}.zip"

        path, _ = QFileDialog.getSaveFileName(
            self, self._t("log_export_current", "Export Log"),
            os.path.join(os.path.expanduser("~"), "Desktop", default_name),
            "ZIP (*.zip)",
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"

        system_log = self._get_system_log_path()
        if not os.path.isfile(system_log):
            self._toast(self._t("log_no_logs", "No logs yet"), InfoBar.warning)
            return

        try:
            log.export_zip(path, [system_log])
            log.info("日志", "log", f"已导出 system_log.log: {path}")
            self._toast(self._t("log_export_success", "Export successful"), InfoBar.success)
        except Exception as e:
            log.err("日志", "log", f"导出失败: {e}")
            self._toast(self._t("log_export_failed", "Export failed"), InfoBar.error)

    def on_export_all(self):
        """导出全部日志：system_log.log + 所有历史日志"""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{APP_NAME}_AllLogs_{stamp}.zip"

        path, _ = QFileDialog.getSaveFileName(
            self, self._t("log_export_all", "Export All Logs"),
            os.path.join(os.path.expanduser("~"), "Desktop", default_name),
            "ZIP (*.zip)",
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"

        files_to_export = []
        system_log = self._get_system_log_path()
        if os.path.isfile(system_log):
            files_to_export.append(system_log)
        if os.path.isdir(LOG_HISTORY_DIR):
            for fn in os.listdir(LOG_HISTORY_DIR):
                fp = os.path.join(LOG_HISTORY_DIR, fn)
                if os.path.isfile(fp) and fn.lower().endswith(".log"):
                    files_to_export.append(fp)

        if not files_to_export:
            self._toast(self._t("log_no_logs", "No logs yet"), InfoBar.warning)
            return

        try:
            log.export_zip(path, files_to_export)
            log.info("日志", "log", f"已导出全部日志 ({len(files_to_export)} 个): {path}")
            self._toast(self._t("log_export_success", "Export successful"), InfoBar.success)
        except Exception as e:
            log.err("日志", "log", f"导出全部失败: {e}")
            self._toast(self._t("log_export_failed", "Export failed"), InfoBar.error)

    def on_open_dir(self):
        """打开日志目录"""
        if not os.path.isdir(LOGS_DIR):
            self._toast(self._t("log_no_logs", "No logs yet"), InfoBar.warning)
            return
        try:
            os.startfile(LOGS_DIR)
            log.info("日志", "log", f"打开日志目录: {LOGS_DIR}")
        except Exception as e:
            log.err("日志", "log", f"打开目录失败: {e}")
            self._toast(self._t("log_export_failed", "Export failed"), InfoBar.error)

    def on_clear_history(self):
        """清理历史日志：只删 history/ 下的归档，当前 system_log.log 一个字都不动。

        （需求："清理日志但不要把当前日志内容清除了" —— 以前会把正在查的现场一起删掉。）
        """
        has_history = any(not it["is_current"] for it in self._items)
        if not has_history:
            self._toast(self._t("log_no_history", "No history logs to clear"),
                        InfoBar.warning)
            return

        dlg = ClearHistoryDialog(self, self.lang)
        if dlg.exec_() != QDialog.Accepted:
            return

        try:
            count = log.clear_history()
            log.info("日志", "log", f"已清理 {count} 条历史日志（当前日志已保留）")
            self.refresh_list()
            self._toast(
                self._t("log_clear_success", "Cleared {n} history logs").format(n=count),
                InfoBar.success,
            )
        except Exception as e:
            log.err("日志", "log", f"清理失败: {e}")
            self._toast(self._t("log_export_failed", "Export failed"), InfoBar.error)

    # ---------- 工具 ----------

    def _toast(self, content, bar_type=InfoBar.info):
        bar_type(
            title=self._t("log_toast_title", "Log"),
            content=content,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self,
        )
