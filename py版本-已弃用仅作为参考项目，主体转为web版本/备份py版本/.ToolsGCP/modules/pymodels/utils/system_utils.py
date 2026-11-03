"""系统工具模块。"""

import sys
import subprocess
import os
import locale
from PyQt5.QtWidgets import QApplication

from .logger import log

if sys.platform == 'win32':
    import winreg


def restart_program(open_settings=False):
    """重启程序"""
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
    
    QApplication.quit()


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
