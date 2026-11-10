"""系统工具模块。

⚠️ **本模块不再在顶层 import PyQt5**（原来有一句 `from PyQt5.QtWidgets import QApplication`）。
   原因：Web 版（主体）会**惰性调用**本模块 —— `pymodels/core/ai/agent_tools.py` 的
   "设置开机自启"工具就是 `from ...utils.system_utils import set_windows_autostart`
   （见该文件 L537 附近）。顶层 import Qt 会让这条工具在没装 PyQt5 的机器上直接
   ImportError，而 CLI/打包版恰恰不该依赖 Qt。
   Qt 只在**旧 PyQt 界面**的 `restart_program()` 里才需要（要 QApplication.quit()），
   所以改成函数内 import：那条路径本来只有旧界面会走，Web 版有自己的重启流程
   （`desktop/api/__init__.py` 的 shell 域）。
"""

import sys
import subprocess
import os
import locale

from .logger import log

if sys.platform == 'win32':
    import winreg


def restart_program(open_settings=False):
    """重启程序（⚠️ 仅旧 PyQt 界面用；Web 版走 shell 域自己的重启流程）"""
    args = []

    if getattr(sys, 'frozen', False):
        # 已打包为 exe：sys.executable 即为程序本身
        args.append(sys.executable)
    else:
        script = os.path.abspath(sys.argv[0])
        args = [sys.executable, script]

    if open_settings:
        args.append("--open-settings")

    subprocess.Popen(args)

    # ⚠️ 惰性 import：没有 PyQt5（Web 版/打包版）时这里不该炸，只是没事件循环可退出
    try:
        from PyQt5.QtWidgets import QApplication
        QApplication.quit()
    except Exception:
        pass


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


def detect_system_language():
    """检测系统语言"""
    try:
        system_lang = locale.getlocale()[0]
        if system_lang:
            if "Chinese (Simplified)" in system_lang or "zh_CN" in system_lang:
                return "简体中文"
            elif "Chinese (Traditional)" in system_lang or "zh_TW" in system_lang or "zh_HK" in system_lang:
                return "繁體中文"
        return "English"
    except Exception:
        return "English"


def set_windows_autostart(enabled):
    """设置Windows开机自启动"""
    if sys.platform != 'win32':
        return False, "仅支持Windows系统"
    
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "ToolsGCP"
        
        script_path = os.path.abspath(sys.argv[0])
        
        if script_path.endswith('.pyw'):
            python_dir = os.path.dirname(sys.executable)
            pythonw_path = os.path.join(python_dir, 'pythonw.exe')
            if not os.path.exists(pythonw_path):
                pythonw_path = sys.executable
            
            exe_path = f'"{pythonw_path}" "{script_path}" --autostart'
        else:
            exe_path = f'"{sys.executable}" "{script_path}" --autostart'
        
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
        except FileNotFoundError:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        
        if enabled:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
            log.info("系统", "autostart", f"已添加开机自启动: {exe_path}")
        else:
            try:
                winreg.DeleteValue(key, app_name)
                log.info("系统", "autostart", "已移除开机自启动")
            except FileNotFoundError:
                pass
        
        winreg.CloseKey(key)
        return True, ""
        
    except Exception as e:
        log.err("系统", "autostart", f"开机自启动设置失败: {e}")
        return False, str(e)
