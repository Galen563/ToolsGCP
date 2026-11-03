"""开机自启（注册表 Run 项）—— 去掉 PyQt5 的等价实现。
原版在 `pymodels/utils/system_utils.py`，但那个模块顶层 `from PyQt5.QtWidgets import
QApplication`，无 Qt 环境下 import 就炸。这里按**同样的路径与同样的值**重写一份：
    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
    值名 "ToolsGCP"
    .pyw 源码运行时 → "<pythonw.exe>" "<script.pyw>" --autostart
    exe 运行时      → "<sys.executable>" "<script>" --autostart
⚠️ 值名与命令格式必须和原版一字不差：老用户机器上已经有这条注册表项，
   格式不一致会导致"开过一次自启之后被新版本写坏"或"关闭自启时删不掉"。
"""

import os
import sys

from . import win32

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "ToolsGCP"


def _log(level: str, message: str):
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)("系统", "autostart", message)
    except Exception:
        pass


def command_line() -> str:
    """开机自启要写的命令行（与原版 `set_windows_autostart` 完全一致）"""
    script_path = os.path.abspath(sys.argv[0])
    if script_path.lower().endswith(".pyw"):
        python_dir = os.path.dirname(sys.executable)
        pythonw_path = os.path.join(python_dir, "pythonw.exe")
        if not os.path.exists(pythonw_path):
            pythonw_path = sys.executable
        return f'"{pythonw_path}" "{script_path}" --autostart'
    return f'"{sys.executable}" "{script_path}" --autostart'


def is_enabled() -> bool:
    if not win32.IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(str(value or "").strip())
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_enabled(enabled: bool):
    """开/关开机自启，返回 (是否成功, 错误信息)"""
    if not win32.IS_WINDOWS:
        return False, "仅支持Windows系统"
    try:
        import winreg
        if enabled:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                     winreg.KEY_WRITE)
            except FileNotFoundError:
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY)
            with key:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command_line())
            _log("info", f"已添加开机自启动: {command_line()}")
            return True, ""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_WRITE) as key:
                winreg.DeleteValue(key, APP_NAME)
            _log("info", "已移除开机自启动")
        except FileNotFoundError:
            pass
        return True, ""
    except Exception as exc:                               # noqa: BLE001
        _log("err", f"开机自启动设置失败: {exc}")
        return False, str(exc)
