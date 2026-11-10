"""圆形头像组件。"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel
from PyQt5.QtGui import QPixmap, QPainter, QImage, QCursor


# 语言文件缺失时的内嵌英文兜底
_AVATAR_FALLBACK = {
    "github": "Repository",
    "avatar_alt": "Galen563",
}


class CircleAvatar(QLabel):
    
    def __init__(self, image_path, size=120, parent=None, lang_manager=None):
        super().__init__(parent)
        self.lang = lang_manager
        self.setFixedSize(size, size)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            self.setPixmap(self.create_circle_pixmap(pixmap, size))
        else:
            text = self.get_text("avatar_alt") if self.lang else "Galen563"
            self.setText(text)
            self.setAlignment(Qt.AlignCenter)
            self.setStyleSheet("background-color: #00D4FF; border-radius: 60px; color: white; font-weight: bold;")
    
    def get_text(self, key):
        if self.lang:
            text = self.lang.get_text("github", key)
            if text and text != key:
                return text
        return _AVATAR_FALLBACK.get(key, key)
    
    def create_circle_pixmap(self, pixmap, size):
        scaled = pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        
        circle_image = QImage(size, size, QImage.Format_ARGB32)
        circle_image.fill(Qt.transparent)
        
        painter = QPainter(circle_image)
        painter.setRenderHint(QPainter.Antialiasing)
        
        painter.setBrush(Qt.white)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, size, size)
        
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        
        x = (size - scaled.width()) // 2
        y = (size - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        
        painter.end()
        
        return QPixmap.fromImage(circle_image)
