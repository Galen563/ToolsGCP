"""崩溃护栏：别让槽函数里逃出去的异常把整个程序带走

PyQt5 从 5.5 起，Python 异常从槽函数逃出去时会先打堆栈、再 qFatal() 直接
abort 进程（无弹窗、无提示，窗口一闪就没）。装上自己的 sys.excepthook 之后
PyQt 只调 hook、不再 abort，异常变成"记日志 + 打堆栈"，程序继续活着。

用法（越早越好）：
    from pymodels.utils.crash_guard import install_crash_guard
    install_crash_guard()
"""

import sys
import traceback

_installed = False


def install_crash_guard() -> bool:
    """装一次全局异常护栏（重复调用无副作用；装上返回 True）"""
    global _installed
    if _installed:
        return True
    try:
        sys.excepthook = _hook
        _installed = True
        return True
    except Exception:
        return False


def _hook(exc_type, exc_value, exc_tb):
    """替代默认 excepthook：完整堆栈进日志 + 打 stderr，绝不 abort"""
    # Ctrl+C / 主动退出交回默认处理（这两个本来就该结束进程）
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        from .logger import log
        log.err("崩溃", "unhandled", "槽函数里逃出去的异常（已拦住，程序继续运行）：\n" + text)
    except Exception:
        pass
    try:
        sys.stderr.write(text)
        sys.stderr.flush()
    except Exception:
        pass


__all__ = ["install_crash_guard"]
