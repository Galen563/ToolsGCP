"""
ToolsGCP - 主入口文件
"""

import sys
import os
import ctypes
from ctypes import wintypes


# ========== 更新模式（必须在任何东西之前） ==========
#
# 更新器就是刚下载下来的新版自己（%TEMP%\ToolsGCP_new.exe），它以
# `--update --pid <旧PID> --target <原exe路径>` 被拉起来。这时候旧进程还没退出，
# 单实例互斥锁还在它手里 —— 走单实例检测会把自己判成"已有实例"然后直接退出；
# 也绝不能创建 QApplication / 窗口 / 托盘（那会锁住 exe、还弹一堆 UI）。
# 所以这一段必须排在最前面，且不依赖 Qt / 配置。
def _run_update_mode_if_needed() -> bool:
    """是更新模式就跑掉；返回 True 表示"更新做完了，别继续正常启动" """
    argv = sys.argv[1:]
    if "--update" not in argv and "--cleanup" not in argv:
        return False
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        modules_path = os.path.join(current_dir, ".ToolsGCP", "modules")
        if os.path.isdir(modules_path) and modules_path not in sys.path:
            sys.path.insert(0, modules_path)
        from pymodels.core.self_update import (cleanup_after_update,
                                              run_update_mode)  # pyright: ignore
    except Exception as exc:                      # noqa: BLE001
        # 连更新模块都导入不了：写一行到临时日志，安静退出（不弹窗）
        try:
            import tempfile
            path = os.path.join(tempfile.gettempdir(), "ToolsGCP_update.log")
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(f"[update] 导入自更新模块失败: {exc!r}\n")
        except Exception:
            pass
        return True
    if "--cleanup" in argv:
        # 更新之后的第一次启动：清掉 %TEMP% 里那两个临时文件（失败也不管）
        try:
            cleanup_after_update(sys.argv)
        except Exception:
            pass
        return False            # 清理完继续正常启动
    try:
        code = run_update_mode(sys.argv)
    except Exception:
        code = 1
    sys.exit(code)


if _run_update_mode_if_needed():
    sys.exit(0)


# ========== 单实例检测（必须在任何窗口创建之前） ==========
class SingleInstanceChecker:
    """单实例运行检查器 - 使用 Windows Mutex"""

    def __init__(self, mutex_name="ToolsGCP_SingleInstance_Mutex_v1.0"):
        self.mutex_name = mutex_name
        self.mutex_handle = None
        self.already_running = False

    def check(self):
        """检查是否已有实例在运行

        Returns: True - 可以运行（当前唯一实例）, False - 已有实例在运行
        """
        # Windows API 常量
        CREATE_MUTEX = 0x1F0001  # MUTEX_ALL_ACCESS
        ERROR_ALREADY_EXISTS = 183

        kernel32 = ctypes.windll.kernel32
        self.mutex_handle = kernel32.CreateMutexW(
            None,                  # 默认安全属性
            wintypes.BOOL(False),  # 不立即拥有
            self.mutex_name
        )

        if not self.mutex_handle:
            return True            # 创建失败就放行，别拦着用户
        last_error = kernel32.GetLastError()
        if last_error == ERROR_ALREADY_EXISTS:
            self.already_running = True
            return False
        return True

    def release(self):
        """释放互斥锁"""
        if self.mutex_handle:
            ctypes.windll.kernel32.ReleaseMutex(self.mutex_handle)
            ctypes.windll.kernel32.CloseHandle(self.mutex_handle)
            self.mutex_handle = None


instance_checker = SingleInstanceChecker()

if not instance_checker.check():
    # 已有实例在运行：把它的窗口激活到前台，然后退出自己
    try:
        user32 = ctypes.windll.user32

        def enum_windows_callback(hwnd, extra):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, length + 1)
                    window_text = buffer.value
                    if "ToolsGCP" in window_text:
                        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        user32.SetForegroundWindow(hwnd)
                        return False               # 停止枚举
            return True

        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)

    except Exception as e:
        print(f"[警告] 激活已有窗口失败: {e}")

    print("[ToolsGCP] 检测到已有实例在运行，正在激活...")
    sys.exit(0)

# ========== 正常启动流程 ==========

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# 模块路径：modules/pymodels
MODULES_PATH = os.path.join(CURRENT_DIR, ".ToolsGCP", "modules")
sys.path.insert(0, MODULES_PATH)

# 先准备好数据目录（.ToolsGCP/config）。必须在任何 Manager 之前：
# 它们一构造就会去读配置和收藏夹。
from pymodels.core.data_dir import ensure_data_dir # pyright: ignore[reportMissingImports]
ensure_data_dir()

from pymodels.core.settings_manager import SettingsManager # pyright: ignore[reportMissingImports]

# 全局崩溃护栏必须赶在任何窗口、任何事件过滤器之前装：PyQt5 会把槽函数里逃出去的
# 异常升级成 qFatal()（进程直接 abort，没有弹窗也没有提示），装了它之后只记日志。
from pymodels.utils.crash_guard import install_crash_guard # pyright: ignore[reportMissingImports]
install_crash_guard()

settings_manager = SettingsManager()
splash_enabled = settings_manager.settings.get("splash_screen_enabled", True)

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

# 创建应用（必须在创建任何窗口之前）
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)
app = QApplication(sys.argv)

app.setApplicationName("ToolsGCP")
app.setApplicationDisplayName("ToolsGCP")

# ⚠️ AppUserModelID 必须在创建任何窗口之前设，否则 Windows 会把进程归到 python.exe
#    名下，任务栏（以及"固定到任务栏"）显示的是 Python 的图标。
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            u"Galen563.ToolsGCP.v1")
    except Exception as _e:
        print(f"[警告] 设置 AppUserModelID 失败（任务栏图标可能显示为 Python 图标）: {_e}")

_APP_ICON_PATH = os.path.join(CURRENT_DIR, ".ToolsGCP", "logo.png")
if os.path.exists(_APP_ICON_PATH):
    from PyQt5.QtGui import QIcon
    app.setWindowIcon(QIcon(_APP_ICON_PATH))

splash = None
splash_duration_ms = settings_manager.get_splash_screen_duration_ms() if splash_enabled else 0

if splash_enabled:
    from pymodels.splash_screen import show_splash_screen # pyright: ignore[reportMissingImports]

    icon_path = os.path.join(CURRENT_DIR, ".ToolsGCP", "logo.png")
    splash = show_splash_screen(icon_path, splash_duration_ms)

from pymodels.ui.main_window import MainWindow # pyright: ignore[reportMissingImports]


def main():
    """主函数：等"启动画面播完"和"首屏内容加载完"都完成后再显示窗口"""
    window = MainWindow()

    # 窗口标题要能被上面的单实例检测找到
    window.setWindowTitle("ToolsGCP")

    state = {"ui": window.is_ui_ready, "splash": splash is None}

    def try_show():
        if state["ui"] and state["splash"]:
            window.show()

    def on_ui_ready():
        state["ui"] = True
        try_show()

    def on_splash_finished():
        state["splash"] = True
        try_show()

    window.ui_ready.connect(on_ui_ready)
    if splash is not None:
        splash.finished.connect(on_splash_finished)
    try_show()

    exit_code = app.exec_()

    instance_checker.release()

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
