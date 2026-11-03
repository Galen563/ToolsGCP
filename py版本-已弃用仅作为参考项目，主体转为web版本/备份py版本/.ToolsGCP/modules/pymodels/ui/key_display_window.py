"""密钥显示窗口"""

from ..utils.fonts import ui_font
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QApplication)
from PyQt5.QtGui import QFont
from qfluentwidgets import SimpleCardWidget, PrimaryPushButton, ToolButton, FluentIcon as FIF, InfoBar, InfoBarPosition


# 语言文件缺失时的英文兜底（统一英文，避免中英混杂）
_SETTINGS_FALLBACK = {
    "settings": "Settings",
    "available_keys": "Available GCP License Keys",
    "close": "Back",
}


class KeyDisplayWindow(QWidget):
    """密钥显示窗口"""
    
    def __init__(self, keys, is_dark_theme=False, language_manager=None, 
                 admin_name=None, window_title=None):
        super().__init__()
        self.is_dark_theme = is_dark_theme
        self.lang = language_manager
        self.keys = keys
        self.admin_name = admin_name
        
        if window_title:
            self.setWindowTitle(window_title)
        else:
            self.setWindowTitle(self.get_text("available_keys"))
            
        self.resize(600, 400)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
        
        self.setup_ui()
        self.apply_window_theme()
        self.center_on_screen()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        title = QLabel(self.windowTitle())
        title.setFont(ui_font(14, bold=True))
        title.setObjectName("whiteInDarkLabel")
        layout.addWidget(title)
        
        card = SimpleCardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 15, 15, 15)
        card_layout.setSpacing(10)
        
        for key_info in self.keys:
            if isinstance(key_info, dict):
                key = key_info.get("key", "")
                admin = key_info.get("admin", "")
                if admin:
                    display_text = f"{key}  ({admin})"
                else:
                    display_text = key
            else:
                key = key_info
                display_text = key
            
            item_layout = QHBoxLayout()
            key_label = QLabel(display_text)
            key_label.setFont(QFont("Consolas", 11))
            key_label.setObjectName("whiteInDarkLabel")
            
            if self.is_dark_theme:
                key_label.setStyleSheet("""
                    padding: 5px; background-color: #3A3A3A; border-radius: 5px;
                    color: #FFFFFF; border: 1px solid #555555;
                """)
            else:
                key_label.setStyleSheet("""
                    padding: 5px; background-color: #F5F5F5; border-radius: 5px;
                    color: #000000; border: 1px solid #DDDDDD;
                """)
            
            item_layout.addWidget(key_label)
            copy_btn = ToolButton(FIF.COPY, self)
            copy_btn.setFixedSize(30, 30)
            copy_btn.clicked.connect(lambda checked, k=key: self.copy_key(k))
            item_layout.addWidget(copy_btn)
            card_layout.addLayout(item_layout)
        
        layout.addWidget(card)
        layout.addStretch()
        
        close_btn = PrimaryPushButton(self.get_text("close"))
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn, 0, Qt.AlignCenter)
    
    def get_text(self, key):
        if self.lang:
            text = self.lang.get_text("settings", key)
            if text and text != key:
                return text
        return _SETTINGS_FALLBACK.get(key, key)
    
    def apply_window_theme(self):
        if self.is_dark_theme:
            self.setStyleSheet("""
                QWidget { background-color: #2A2A2A; }
                QLabel#whiteInDarkLabel { color: #FFFFFF; }
                SimpleCardWidget { background-color: #2A2A2A; }
                PrimaryPushButton { color: #FFFFFF; }
            """)
        else:
            self.setStyleSheet("""
                QWidget { background-color: #FFFFFF; }
                QLabel#whiteInDarkLabel { color: #000000; }
                SimpleCardWidget { background-color: #FFFFFF; }
            """)
    
    def copy_key(self, key):
        """复制密钥到剪贴板（按要求不再弹"复制成功"顶部提示）"""
        clipboard = QApplication.clipboard()
        clipboard.setText(key)
    
    def center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move((screen.width() - self.width()) // 2, 
                 (screen.height() - self.height()) // 2)
