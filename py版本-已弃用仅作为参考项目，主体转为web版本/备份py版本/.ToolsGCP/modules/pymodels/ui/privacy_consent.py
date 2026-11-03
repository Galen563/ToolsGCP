"""隐私政策同意机制：对话框、条款查看器、哈希校验。"""

from ..utils.fonts import ui_font
import os
import json
import hashlib
from datetime import datetime

from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QSize
from PyQt5.QtWidgets import (
    QDialog, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QApplication, QGraphicsDropShadowEffect, QWidget
)
from PyQt5.QtGui import QFont, QColor, QPainter, QBrush, QLinearGradient

from qfluentwidgets import PushButton, PrimaryPushButton

from ..core.language_manager import LanguageManager
from ..utils.theme_utils import is_dark_mode


COLOR_DANGER = "#F56C6C"
COLOR_DANGER_HOVER = "rgba(245, 108, 108, 0.10)"
COLOR_DANGER_PRESSED = "rgba(245, 108, 108, 0.20)"

COLOR_LINK = "#5B8DEF"
COLOR_LINK_HOVER = "#6E9BFF"

COLOR_DIALOG_BG_START_DARK = "#2C3E50"
COLOR_DIALOG_BG_END_DARK = "#1F2D3D"
COLOR_DIALOG_BG_START_LIGHT = "#FFFFFF"
COLOR_DIALOG_BG_END_LIGHT = "#F5F7FA"
COLOR_DIALOG_TEXT_DARK = "#FFFFFF"
COLOR_DIALOG_TEXT_LIGHT = "#1A1A1A"
COLOR_DIALOG_LINE_DARK = "rgba(255,255,255,0.10)"
COLOR_DIALOG_LINE_LIGHT = "rgba(0,0,0,0.10)"

# 内置防篡改校验密钥
_PRIVACY_HASH_SALT = "ToolsGCP_PrivacyConsent_Salt_v1.0"


class PrivacyManager:
    """隐私政策同意状态管理 + 哈希校验"""

    def __init__(self, base_dir, language_manager: LanguageManager = None, settings_manager=None):
        self.base_dir = base_dir
        # ⚠️ 需求：隐私政策/免责声明的同意记录属于"程序自动生成的配置文件"，要跟其它配置一起
        #    存在**用户主目录的 .ToolsGCP** 下（不再是程序目录旁）。位置由 data_root 统一解析，
        #    用户在设置里改了存储位置后这里也跟着走。
        try:
            from ..core.data_root import resolve_data_root
            # ⚠️ 注意是 **config/ 子目录**：constants.DATA_DIR 就是 <数据根>/config，
            #    所有"程序写出来的配置文件"（含 privacy_policy.json）都在那儿，不在数据根直属目录下。
            self.privacy_dir = os.path.join(resolve_data_root(), "config")
        except Exception:
            self.privacy_dir = os.path.join(base_dir, ".ToolsGCP", "config")
        self.privacy_file = os.path.join(self.privacy_dir, "privacy_policy.json")
        self.lang = language_manager
        self.settings_manager = settings_manager

        self._is_dark = self._detect_dark_mode()

    def _detect_dark_mode(self):
        if self.settings_manager:
            theme = self.settings_manager.settings.get("theme", "跟随系统")
            return is_dark_mode(theme)
        try:
            from ..utils.theme_utils import isDarkTheme
            return isDarkTheme()
        except Exception:
            return True

    @property
    def is_dark(self):
        return self._is_dark

    def _ensure_dir(self):
        if not os.path.exists(self.privacy_dir):
            os.makedirs(self.privacy_dir, exist_ok=True)

    def _compute_hash(self, consent_given, consent_version, consent_timestamp):
        """根据关键字段计算哈希（timestamp 参与计算）"""
        raw = f"{_PRIVACY_HASH_SALT}|{consent_given}|{consent_version}|{consent_timestamp}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _get_default_data(self):
        cur_lang = self.lang.current_language if self.lang else "简体中文"
        return {
            "_comment_zh-CN": "【重要说明】consent_given 为 false 表示您尚未同意用户协议与隐私政策，将无法使用本软件；consent_given 为 true 表示您已同意，可正常使用全部功能。",
            "_comment_zh-TW": "【重要說明】consent_given 為 false 表示您尚未同意用戶協議與隱私政策，將無法使用本軟體；consent_given 為 true 表示您已同意，可正常使用全部功能。",
            "_comment_en": "【Important Notice】If consent_given is false, you have not agreed to the User Agreement and Privacy Policy and will not be able to use this software. If consent_given is true, you have agreed and may use all features normally.",
            "consent_given": False,
            "consent_version": "V1.0",
            "consent_timestamp": "",
            "consent_hash": ""
        }

    def load_or_create(self):
        """加载隐私状态；文件不存在则创建默认值并返回"""
        self._ensure_dir()
        if not os.path.exists(self.privacy_file):
            data = self._get_default_data()
            try:
                with open(self.privacy_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return data

        try:
            with open(self.privacy_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 补齐缺失字段
            default = self._get_default_data()
            for k, v in default.items():
                if k not in data:
                    data[k] = v
            return data
        except Exception:
            # 文件损坏则重建
            data = self._get_default_data()
            try:
                with open(self.privacy_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return data

    def is_consent_valid(self, data=None):
        """检查同意状态是否有效（true 且哈希匹配）"""
        if data is None:
            data = self.load_or_create()
        if not data.get("consent_given"):
            return False
        expected = self._compute_hash(
            data.get("consent_given", False),
            data.get("consent_version", ""),
            data.get("consent_timestamp", "")
        )
        return data.get("consent_hash", "") == expected

    def record_consent(self):
        """记录用户同意：写入 JSON + 哈希"""
        self._ensure_dir()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        version = "V1.0"
        h = self._compute_hash(True, version, ts)
        data = self.load_or_create()
        data["consent_given"] = True
        data["consent_version"] = version
        data["consent_timestamp"] = ts
        data["consent_hash"] = h
        try:
            with open(self.privacy_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False


class PrivacyViewerDialog(QDialog):
    """条款内容查看窗口 - 只读、无边框、圆角阴影"""

    def __init__(self, title, content_text, is_dark=True, parent=None):
        super().__init__(parent)
        self._title_text = title
        self._content_text = content_text
        self._is_dark = is_dark

        self.SHADOW_MARGIN = 20
        self.CONTENT_W = 560
        self.CONTENT_H = 520

        self.setWindowTitle(title)
        self.setFixedSize(self.CONTENT_W + self.SHADOW_MARGIN * 2,
                          self.CONTENT_H + self.SHADOW_MARGIN * 2)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._build_ui()

    def _colors(self):
        if self._is_dark:
            return {
                "bg_start": COLOR_DIALOG_BG_START_DARK,
                "bg_end": COLOR_DIALOG_BG_END_DARK,
                "text": COLOR_DIALOG_TEXT_DARK,
                "line": COLOR_DIALOG_LINE_DARK,
                "edit_bg": "rgba(255,255,255,0.05)",
                "edit_border": "rgba(255,255,255,0.10)",
            }
        else:
            return {
                "bg_start": COLOR_DIALOG_BG_START_LIGHT,
                "bg_end": COLOR_DIALOG_BG_END_LIGHT,
                "text": COLOR_DIALOG_TEXT_LIGHT,
                "line": COLOR_DIALOG_LINE_LIGHT,
                "edit_bg": "rgba(0,0,0,0.02)",
                "edit_border": "rgba(0,0,0,0.10)",
            }

    def _build_ui(self):
        c = self._colors()

        self.container = QFrame(self)
        self.container.setObjectName("viewerContainer")
        self.container.setGeometry(
            self.SHADOW_MARGIN, self.SHADOW_MARGIN,
            self.CONTENT_W, self.CONTENT_H,
        )

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(0)

        # 标题栏
        title_row = QHBoxLayout()
        title_row.setSpacing(0)

        self.title_label = QLabel(self._title_text)
        self.title_label.setFont(ui_font(14, bold=True))
        self.title_label.setStyleSheet(f"color: {c['text']}; background: transparent;")
        title_row.addWidget(self.title_label)
        title_row.addStretch()

        # 关闭按钮
        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {c['text']};
                border: none;
                border-radius: 6px;
                font-size: 18px;
                font-weight: bold;
                padding: 0px;
            }}
            QPushButton:hover {{ background: rgba(128,128,128,0.2); }}
            QPushButton:pressed {{ background: rgba(128,128,128,0.3); }}
        """)
        self.close_btn.clicked.connect(self.accept)
        title_row.addWidget(self.close_btn)

        layout.addLayout(title_row)
        layout.addSpacing(10)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {c['line']}; border: none;")
        layout.addWidget(line)
        layout.addSpacing(12)

        # 内容（只读滚动）
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(self._content_text)
        self.text_edit.setFont(ui_font(10))
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background: {c['edit_bg']};
                color: {c['text']};
                border: 1px solid {c['edit_border']};
                border-radius: 8px;
                padding: 10px 12px;
                selection-background-color: {COLOR_LINK};
            }}
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 6px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(128,128,128,0.35);
                border-radius: 3px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background: rgba(128,128,128,0.55); }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        """)
        layout.addWidget(self.text_edit)

        self.container.setStyleSheet(f"""
            QFrame#viewerContainer {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {c['bg_start']},
                    stop:1 {c['bg_end']});
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }}
        """)

        # 阴影
        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.container.setGraphicsEffect(shadow)

    def showEvent(self, event):
        super().showEvent(event)
        self._center_on_main_window()
        self._play_open_animation()

    def _center_on_main_window(self):
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
            frame = main_win.frameGeometry()
            x = frame.x() + (frame.width() - self.width()) // 2
            y = frame.y() + (frame.height() - self.height()) // 2
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.x() + (screen.width() - self.width()) // 2
            y = screen.y() + (screen.height() - self.height()) // 2
        self.move(x, y)

    def _play_open_animation(self):
        self.setWindowOpacity(0.0)
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self._opacity_anim.setDuration(200)
        self._opacity_anim.setStartValue(0.0)
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._opacity_anim.start()


class PrivacyConsentDialog(QDialog):
    """隐私政策同意对话框 - 与清理历史日志窗口同风格"""

    def __init__(self, privacy_manager: PrivacyManager, parent=None):
        super().__init__(parent)
        self.pm = privacy_manager
        self._is_dark = privacy_manager.is_dark
        self._opacity_anim = None

        self.SHADOW_MARGIN = 20
        self.CONTENT_W = 460
        self.CONTENT_H = 220

        self.setWindowTitle(self._t("privacy_dialog_title", "User Agreement & Privacy Policy"))
        self.setFixedSize(self.CONTENT_W + self.SHADOW_MARGIN * 2,
                          self.CONTENT_H + self.SHADOW_MARGIN * 2)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._build_ui()

    def _t(self, key, default=None):
        if self.pm.lang:
            try:
                result = self.pm.lang.get_text("privacy", key)
                if result and result != key:
                    return result
            except Exception:
                pass
        return default if default is not None else key

    def _colors(self):
        if self._is_dark:
            return {
                "bg_start": COLOR_DIALOG_BG_START_DARK,
                "bg_end": COLOR_DIALOG_BG_END_DARK,
                "text": COLOR_DIALOG_TEXT_DARK,
                "line": COLOR_DIALOG_LINE_DARK,
                "title_color": COLOR_LINK,
            }
        else:
            return {
                "bg_start": COLOR_DIALOG_BG_START_LIGHT,
                "bg_end": COLOR_DIALOG_BG_END_LIGHT,
                "text": COLOR_DIALOG_TEXT_LIGHT,
                "line": COLOR_DIALOG_LINE_LIGHT,
                "title_color": COLOR_LINK,
            }

    def _build_ui(self):
        c = self._colors()

        self.container = QFrame(self)
        self.container.setObjectName("consentContainer")
        self.container.setGeometry(
            self.SHADOW_MARGIN, self.SHADOW_MARGIN,
            self.CONTENT_W, self.CONTENT_H,
        )

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(0)

        # 标题
        self.title = QLabel(self._t("privacy_dialog_title"))
        self.title.setFont(ui_font(14, bold=True))
        self.title.setStyleSheet(f"color: {c['title_color']}; background: transparent;")
        layout.addWidget(self.title)

        layout.addSpacing(10)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {c['title_color']}; border: none;")
        layout.addWidget(line)

        layout.addSpacing(18)

        # 正文（带蓝色可点击链接）
        self.body = QLabel()
        self.body.setFont(ui_font(11))
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextBrowserInteraction | Qt.LinksAccessibleByMouse)
        self.body.setOpenExternalLinks(False)
        self.body.linkActivated.connect(self._on_link_clicked)
        self.body.setStyleSheet(f"""
            QLabel {{
                color: {c['text']};
                background: transparent;
                line-height: 1.6;
            }}
            QLabel a {{
                color: {COLOR_LINK};
                text-decoration: underline;
            }}
            QLabel a:hover {{
                color: {COLOR_LINK_HOVER};
            }}
        """)
        self._update_body_text()
        layout.addWidget(self.body)

        layout.addStretch()

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        self.agree_btn = PrimaryPushButton(self._t("privacy_agree_btn", "Agree"))
        self.agree_btn.setMinimumWidth(100)
        self.agree_btn.clicked.connect(self._on_agree)
        btn_row.addWidget(self.agree_btn)

        self.reject_btn = PushButton(self._t("privacy_reject_btn", "Decline & Exit"))
        self.reject_btn.setMinimumWidth(120)
        self.reject_btn.setStyleSheet(f"""
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
        self.reject_btn.clicked.connect(self._on_reject)
        btn_row.addWidget(self.reject_btn)

        layout.addLayout(btn_row)

        self.container.setStyleSheet(f"""
            QFrame#consentContainer {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {c['bg_start']},
                    stop:1 {c['bg_end']});
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }}
        """)

        # 阴影
        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.container.setGraphicsEffect(shadow)

    def _update_body_text(self):
        """构造带链接的正文 HTML"""
        full_text = self._t("privacy_consent_text",
                           "I have read and agree to the ToolsGCP User Agreement and Privacy Policy & Disclaimer.")
        user_link_text = self._t("privacy_link_user_agreement", "User Agreement")
        privacy_link_text = self._t("privacy_link_privacy_policy", "Privacy Policy & Disclaimer")

        html = full_text
        # 替换用户使用协议
        html = html.replace(
            f"《{user_link_text}》",
            f'<a href="user_agreement" style="color:{COLOR_LINK}; text-decoration: underline;">《{user_link_text}》</a>'
        )
        # 替换隐私政策及免责声明
        html = html.replace(
            f"《{privacy_link_text}》",
            f'<a href="privacy_policy" style="color:{COLOR_LINK}; text-decoration: underline;">《{privacy_link_text}》</a>'
        )
        self.body.setText(html)

    def _on_link_clicked(self, link):
        """点击蓝色链接 → 弹出条款查看窗口"""
        if link == "user_agreement":
            title = self._t("privacy_viewer_user_title", "User Agreement")
            content = self._t("privacy_user_agreement_text", "")
        elif link == "privacy_policy":
            title = self._t("privacy_viewer_privacy_title", "Privacy Policy & Disclaimer")
            content = self._t("privacy_privacy_policy_text", "")
        else:
            return

        viewer = PrivacyViewerDialog(title, content, self._is_dark, self)
        viewer.exec_()

    def _on_agree(self):
        """点击同意 → 写入同意状态 → 关闭对话框"""
        self.pm.record_consent()
        self.accept()

    def _on_reject(self):
        self.reject()

    def showEvent(self, event):
        super().showEvent(event)
        self._center_on_main_window()
        self._play_open_animation()

    def _center_on_main_window(self):
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
            frame = main_win.frameGeometry()
            x = frame.x() + (frame.width() - self.width()) // 2
            y = frame.y() + (frame.height() - self.height()) // 2
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.x() + (screen.width() - self.width()) // 2
            y = screen.y() + (screen.height() - self.height()) // 2
        self.move(x, y)

    def _play_open_animation(self):
        self.setWindowOpacity(0.0)
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self._opacity_anim.setDuration(220)
        self._opacity_anim.setStartValue(0.0)
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._opacity_anim.start()

    def keyPressEvent(self, event):
        """屏蔽 Esc 关闭，必须点按钮选择"""
        if event.key() == Qt.Key_Escape:
            return
        super().keyPressEvent(event)


class PrivacyMaskOverlay(QWidget):
    """半透明变暗遮罩 - 覆盖在主窗口上，对话框在遮罩之上"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: rgba(0, 0, 0, 150);")

    def resizeEvent(self, event):
        if self.parent():
            self.setGeometry(self.parent().rect())
        super().resizeEvent(event)
