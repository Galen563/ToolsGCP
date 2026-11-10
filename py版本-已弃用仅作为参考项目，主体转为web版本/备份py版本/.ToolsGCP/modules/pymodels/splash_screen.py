"""
启动画面模块
"""

from .utils.fonts import ui_font
import sys
import os
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication, QGraphicsDropShadowEffect
from PyQt5.QtGui import QPixmap, QPainter, QColor, QFont

from .utils.logger import log


class SplashScreen(QWidget):
    """启动画面窗口"""
    
    finished = pyqtSignal()  # 启动画面结束信号
    
    def __init__(self, image_path, duration_ms=2000, parent=None):
        super().__init__(parent)
        
        self.duration_ms = duration_ms
        self.image_path = image_path
        
        # 无边框、置顶、居中
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.setup_ui()
        self.center_on_screen()
        
        # 定时关闭
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.close_splash)
        self.timer.setSingleShot(True)
        self.timer.start(duration_ms)
    
    def setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(0)
        
        # 图片标签
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        
        # 尝试加载图片
        image_loaded = False
        
        if self.image_path and os.path.exists(self.image_path):
            try:
                # 加载图片
                pixmap = QPixmap(self.image_path)
                
                if not pixmap.isNull():
                    # 限制最大尺寸为 300x300
                    max_size = 300
                    if pixmap.width() > max_size or pixmap.height() > max_size:
                        pixmap = pixmap.scaled(
                            max_size, max_size, 
                            Qt.KeepAspectRatio, 
                            Qt.SmoothTransformation
                        )
                    
                    # 设置图片
                    self.image_label.setPixmap(pixmap)
                    
                    # 设置窗口大小为图片大小加上边距
                    self.setFixedSize(pixmap.width() + 80, pixmap.height() + 80)
                    
                    # 添加阴影效果
                    shadow = QGraphicsDropShadowEffect()
                    shadow.setBlurRadius(30)
                    shadow.setColor(QColor(0, 0, 0, 120))
                    shadow.setOffset(0, 6)
                    self.image_label.setGraphicsEffect(shadow)
                    
                    image_loaded = True
                    log.info("启动", "splash",
                             f"启动画面图片加载成功: {pixmap.width()}x{pixmap.height()}")
                else:
                    log.warn("启动", "splash", "启动画面 QPixmap 为空，图片可能损坏")
                    
            except Exception as e:
                log.err("启动", "splash", f"启动画面图片加载异常: {e}")
        else:
            log.warn("启动", "splash", f"启动画面图片不存在: {self.image_path}")
        
        # 如果图片加载失败，显示备用文字
        if not image_loaded:
            self.setup_text_fallback()
        
        layout.addWidget(self.image_label, 0, Qt.AlignCenter)
    
    def setup_text_fallback(self):
        """图片加载失败时的备用显示"""
        self.image_label.setText("ToolsGCP")
        self.image_label.setFont(ui_font(36, bold=True))
        self.image_label.setStyleSheet("""
            color: #00D4FF;
            background-color: #2B2B2B;
            border-radius: 20px;
            padding: 40px;
        """)
        self.image_label.setFixedSize(200, 200)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.setFixedSize(280, 280)
    
    def center_on_screen(self):
        """居中显示"""
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2
        )
    
    def close_splash(self):
        """关闭启动画面"""
        self.finished.emit()
        self.close()
    
    def paintEvent(self, event):
        """绘制圆角背景"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制半透明背景
        painter.setBrush(QColor(43, 43, 43, 240))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 20, 20)
        
        super().paintEvent(event)


def show_splash_screen(image_path, duration_ms=2000):
    """
    显示启动画面并等待完成
    
    Args:
        image_path: 图片路径
        duration_ms: 显示时长（毫秒）
    
    Returns:
        SplashScreen实例
    """
    splash = SplashScreen(image_path, duration_ms)
    splash.show()
    splash.raise_()
    splash.activateWindow()
    
    # 处理事件确保显示
    QApplication.processEvents()
    
    return splash
