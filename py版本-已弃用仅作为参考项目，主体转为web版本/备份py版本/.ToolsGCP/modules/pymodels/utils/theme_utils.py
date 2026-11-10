"""主题工具模块。"""

import sys
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme, isDarkTheme

if sys.platform == 'win32':
    import winreg


def apply_app_palette(dark: bool):
    """把 QApplication 的调色板一起切到深/浅色

    ⚠️ qfluentwidgets 只维护自己的样式表、**不动 QPalette** —— 按调色板绘制的原生控件
       （典型是 QScrollArea 的视口）在深色主题下会仍按浅色绘制，出现一大片白底。
    """
    app = QApplication.instance()
    if app is None:
        return
    if not dark:
        app.setPalette(app.style().standardPalette())
        return

    palette = QPalette()
    window = QColor(32, 32, 32)
    base = QColor(27, 27, 27)
    text = QColor(255, 255, 255)

    palette.setColor(QPalette.Window, window)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, base)
    palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, window)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.BrightText, QColor(255, 80, 80))
    palette.setColor(QPalette.ToolTipBase, QColor(43, 43, 43))
    palette.setColor(QPalette.ToolTipText, text)
    palette.setColor(QPalette.Highlight, QColor(0, 159, 170))
    palette.setColor(QPalette.HighlightedText, text)
    palette.setColor(QPalette.PlaceholderText, QColor(150, 150, 150))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(128, 128, 128))
    app.setPalette(palette)


def make_scroll_areas_opaque(root, color=None):
    """⚠️ 已废弃，**不要再调用**：会造成滚动拖影

    给滚动区视口设 WA_OpaquePaintEvent（"不用先擦背景"）后，透明内容的旧像素擦不掉，
    表现就是"所有东西都有动画拖影滞留"。保留成空函数是为了不动调用点。
    """
    return 0


def is_dark_mode(theme_setting):
    """判断是否为深色模式"""
    if theme_setting == "深色主题":
        return True
    elif theme_setting == "跟随系统":
        try:
            if sys.platform == 'win32':
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                winreg.CloseKey(key)
                return value == 0
        except:
            pass
    return False


def apply_theme(theme_name):
    """应用主题"""
    if theme_name == "跟随系统":
        actual_theme = detect_system_theme()
    else:
        actual_theme = theme_name
    
    # ⚠️ lazy=True：只立刻重刷当前可见的控件，藏着的等第一次被画出来时补刷。
    #    不加这个的话 setTheme 会把全程序每个注册控件重刷一遍（实测 ~550ms）。
    if actual_theme == "浅色主题":
        setTheme(Theme.LIGHT, lazy=True)
    else:
        setTheme(Theme.DARK, lazy=True)
    apply_app_palette(actual_theme != "浅色主题")

    return actual_theme


def detect_system_theme():
    """检测系统主题"""
    if sys.platform != 'win32':
        return "浅色主题"
    
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "深色主题" if value == 0 else "浅色主题"
    except Exception:
        return "浅色主题"


def fix_dark_theme_titlebar():
    """修复深色主题标题栏（lazy=True：只重刷可见控件）"""
    setTheme(Theme.LIGHT, lazy=True)
    QTimer.singleShot(50, lambda: setTheme(Theme.DARK, lazy=True))