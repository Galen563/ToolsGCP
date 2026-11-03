"""
ToolsGCP - 主入口文件
========== 是什么 ==========
PyQt5 单体重构为 **pywebview + Vue3 + Tailwind** 的第一阶段（外壳层）。
旧 PyQt 单机版已整体移到 `py版本-已弃用仅作为参考项目，主体转为web版本/`（只读参考）；
业务逻辑仍在 `.ToolsGCP/modules/pymodels/`（core / utils 被 web 版复用），前端在 `.ToolsGCP/webui/`、外壳在 `.ToolsGCP/desktop/`。
========== 启动顺序（**不能随便调**）==========
1. 更新模式（`--update` / `--cleanup`）：必须排在**所有东西之前**。
   更新器就是刚下载的新版自己，它以 `--update --pid <旧PID> --target <原exe>` 被拉起来。
   这时旧进程还没退、单实例互斥锁还在它手里 —— 走单实例检测会把自己判成"已有实例"然后自杀；
   也绝不能创建窗口/托盘（会锁住 exe 并弹一堆 UI）。而且这段不能依赖配置/UI 库。
2. 单实例检测（Windows Mutex）：已有实例就把它的窗口激活到前台，然后自己退出。
3. 数据目录 + 设置 + 崩溃护栏（必须在任何窗口之前）。
4. AppUserModelID（必须在建窗之前，否则任务栏显示 python 图标）。
5. 版本/路径/参数等启动日志（仿 PCL 风格，保持原版那几行）。
6. 主线程 `webview.start()`；启动画面在 worker 线程里跑原版 Qt 代码；
   两者都就绪才显示窗口（详见 .ToolsGCP/desktop/shell.py）。
⚠️ 本文件只做"装配"，不写业务：任何业务逻辑都应该落在 `.ToolsGCP/modules/pymodels/` 或
   `.ToolsGCP/desktop/` 里。这样以后换壳（比如 Tauri/Electron）时入口仍然很薄。
"""

import os
import sys

# ========== 0. 让 `.ToolsGCP/` 与 `.ToolsGCP/modules` 可 import（必须在任何 pymodels 之前）=====
# ⚠️ 本版目录结构（2026-10 整理）：**所有程序文件都在 `.ToolsGCP/` 里**，根目录只剩这个入口。
#       .ToolsGCP/desktop/   ← 桌面外壳（Python 包 `desktop`）
#       .ToolsGCP/webui/     ← 前端（index.html + js + css）
#       .ToolsGCP/modules/   ← 业务代码（Python 包 `pymodels`）与语言文件
#    所以 sys.path 要同时挂上 `.ToolsGCP`（为了 `import desktop`）和 `.ToolsGCP/modules`
#    （为了 `import pymodels`）。
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(CURRENT_DIR, ".ToolsGCP")
MODULES_PATH = os.path.join(CONFIG_DIR, "modules")
for _path in (MODULES_PATH, CONFIG_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)


# ========== 1. 更新模式（必须在任何东西之前） ==========
def _run_update_mode_if_needed() -> bool:
    """是更新模式就跑掉；返回 True 表示"更新做完了，别继续正常启动"
    ⚠️ 这段逻辑与原版 `ToolsGCP.pyw:18-55` **完全一致**（含异常时写临时日志后安静退出），
       只是把 sys.path 的准备提到模块顶部（原版也做同样的事，只是为了兼容"第一次 import
       pymodels 就在这个函数里"的写法才放在函数内）。
    """
    argv = sys.argv[1:]
    if "--update" not in argv and "--cleanup" not in argv:
        return False
    try:
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


# ========== 2. 单实例检测（必须在任何窗口创建之前） ==========
class SingleInstanceChecker:
    """单实例运行检查器 - 使用 Windows Mutex（与原版同名同实现，便于对照）"""

    def __init__(self, mutex_name="ToolsGCP_SingleInstance_Mutex_v1.0"):
        self.mutex_name = mutex_name
        self.mutex_handle = None
        self.already_running = False

    def check(self):
        """检查是否已有实例在运行
        Returns: True - 可以运行（当前唯一实例）, False - 已有实例在运行
        """
        import ctypes
        from ctypes import wintypes

        CREATE_MUTEX = 0x1F0001  # MUTEX_ALL_ACCESS
        ERROR_ALREADY_EXISTS = 183

        kernel32 = ctypes.windll.kernel32
        # ⚠️ 显式声明 restype：默认按 32 位 int 处理，64 位下句柄会被截断
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                          wintypes.LPCWSTR]
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
            import ctypes
            ctypes.windll.kernel32.ReleaseMutex(self.mutex_handle)
            ctypes.windll.kernel32.CloseHandle(self.mutex_handle)
            self.mutex_handle = None


instance_checker = SingleInstanceChecker()

if not instance_checker.check():
    # 已有实例在运行：把它的窗口激活到前台，然后退出自己
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        activated = {"hit": False}

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
                        activated["hit"] = True
                        return False               # 停止枚举
            return True

        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                             wintypes.LPARAM)
        user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)

        # ⚠️「启动时最小化到托盘」生效时**找不到任何可见窗口**（主窗口从未 show 过、
        #    托盘窗口是 WS_POPUP 也不可见）→ 上面那条 EnumWindows 白跑，用户双击图标
        #    就表现为"程序没反应"（其实是藏在托盘里）。
        #    兜底：按托盘窗口类名找到它，投一条"唤醒"消息（= 托盘菜单的「显示主窗口」）。
        #    ⚠️ 数值 0x8000 + 3 = WM_APP+3，与 desktop/native/tray.py 的 WM_TRAY_WAKE
        #       是同一个约定；改一边必须改另一边（这里不能 import desktop，启动太早）。
        if not activated["hit"]:
            # ⚠️ 显式声明原型（和本文件单实例 Mutex 那段同一个理由）：默认按 32 位
            #    int 取返回值，64 位下 HWND 会被截断 → 唤醒消息投给一个假句柄。
            user32.FindWindowW.restype = ctypes.c_void_p
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user32.PostMessageW.restype = wintypes.BOOL
            user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                            wintypes.WPARAM, wintypes.LPARAM]
            tray_hwnd = user32.FindWindowW("ToolsGCP_TrayWindow", None)
            if tray_hwnd:
                user32.PostMessageW(tray_hwnd, 0x8000 + 3, 0, 0)
                print("[ToolsGCP] 已有实例藏在托盘里，已发送唤醒请求")

    except Exception as e:                        # noqa: BLE001
        print(f"[警告] 激活已有窗口失败: {e}")

    print("[ToolsGCP] 检测到已有实例在运行，正在激活...")
    sys.exit(0)


# ========== 3. 数据目录 / 设置 / 崩溃护栏 ==========
# 先准备好数据目录（.ToolsGCP/config）。必须在任何 Manager 之前：
# 它们一构造就会去读配置和收藏夹。
from pymodels.core.data_dir import ensure_data_dir              # noqa: E402
ensure_data_dir()

from pymodels.core.settings_manager import SettingsManager      # noqa: E402

# 全局崩溃护栏必须赶在任何窗口、任何事件回调之前装：原版装它是为了躲 PyQt5 的 qFatal()，
# 现在这个壳同样需要 —— WinForms 的窗口过程/定时器回调里逃出去的异常会直接带走进程。
from pymodels.utils.crash_guard import install_crash_guard      # noqa: E402
install_crash_guard()

settings_manager = SettingsManager()
splash_enabled = settings_manager.settings.get("splash_screen_enabled", True)
splash_duration_ms = settings_manager.get_splash_screen_duration_ms() if splash_enabled else 0

# 启动画面用的图标（与原版同一个路径：.ToolsGCP/logo.png）
APP_ICON_PATH = os.path.join(CURRENT_DIR, ".ToolsGCP", "logo.png")

# ========== 4. AppUserModelID（必须在创建任何窗口之前） ==========
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Galen563.ToolsGCP.v1")
    except Exception as _e:                       # noqa: BLE001
        print(f"[警告] 设置 AppUserModelID 失败（任务栏图标可能显示为 Python 图标）: {_e}")


# ========== 5. 启动日志（仿 PCL：版本/路径/系统等基本信息） ==========
def _write_startup_log():
    """写启动环境信息（排查问题时日志第一屏必须能看懂"谁、在哪、什么系统、什么壳"）
    日志审计：
      · `系统版本: win32` 太模糊 → 改成 Windows 版本号 + 架构 + Python 版本；
      · 原来最后一行写主窗口 启动成功，但这一行执行时窗口**还没创建**
        （webview.start() 在后面），属于不准确信息 → 改成"开始创建主窗口"，
        真正的显示成功由 shell.py 记录（含尺寸/位置/图标/补丁状态）。
      · 补一行"数据根"，因为配置/日志/会话都在那里，排错第一件事就是确认路径。
    """
    import platform

    from pymodels.constants import APP_NAME, APP_VERSION, USER_DATA_ROOT
    from pymodels.utils.logger import log

    log.info("启动", "startup", f"版本: {APP_NAME} {APP_VERSION}")
    log.info("启动", "startup", f"程序目录: {CURRENT_DIR}")
    log.info("启动", "startup",
             f"命令行参数: {sys.argv[1:] if len(sys.argv) > 1 else '[]'}")
    log.info("启动", "startup",
             f"运行环境: {platform.platform()} / Python {platform.python_version()} "
             f"({platform.machine()}, {8 * __import__('struct').calcsize('P')} 位)")
    log.info("启动", "startup", f"数据根: {USER_DATA_ROOT}")
    log.info("启动", "startup",
             f"界面外壳: pywebview {_webview_version()}（WebView2，无边框窗口）")
    log.info("启动", "startup",
             f"启动动画: {'开' if splash_enabled else '关'}，时长 {splash_duration_ms} ms")
    log.info("启动", "startup", "启动参数准备完成，开始创建主窗口")


def _webview_version() -> str:
    """pywebview 版本（`webview.__version__` 在 6.2.1 里不存在，会记成 unknown）
    日志审计：启动日志里出现pywebview unknown等于没写版本，改成先读包元数据。
    """
    try:
        from importlib.metadata import version
        return str(version("pywebview") or "unknown")
    except Exception:
        pass
    try:
        import webview
        return str(getattr(webview, "__version__", "") or "unknown")
    except Exception:
        return "unknown"


# ========== 6. WebView2 启动参数（必须在 webview.start 之前设） ==========
def _merge_browser_args(existing: str, extra: str) -> str:
    """把 extra 并进已有启动参数；已经包含就不重复追加（保证可重复调用）"""
    existing = str(existing or "").strip()
    extra = str(extra or "").strip()
    if not extra or extra in existing:
        return existing
    return (existing + " " + extra).strip()


def _prepare_webview2():
    """给 WebView2 加两条启动参数（**都在 webview.start 之前**生效）
    1. `--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection`
       与 `--disable-background-timer-throttling`
       —— 前台窗口的后台节流会让"虚拟列表滚动时的 rAF"变慢，桌面程序不需要那套省电逻辑。
    2. 关闭 GPU 合成的"低延迟"路径不可控项（保持 WebView2 默认，不动）。
    ⚠️⚠️ **只能改已存在的键**（修的 bug B）：pywebview 6.x 的 `webview.settings` 是
       `webview/util.py:55-70` 的 `ImmutableDict`，它的 `__setitem__` 对**新键**直接抛
       `KeyError: Cannot add new key 'xxx'. Only existing keys can be modified.`
       （日志原文：设置 WebView2 启动参数失败（不影响启动）: "Cannot add new key
       'additional_browser_args'. ..."）。所以：
         · 三个已知键先 `if key in settings` 再写，缺了就跳过（不抛）；
         · 浏览器参数**没有**对应的 settings 键 —— pywebview 6.2.1 把
           `props.AdditionalBrowserArguments` 写死成 `--disable-features=ElasticOverscroll`
           （webview/platforms/edgechromium.py:82），根本不读我们的键。所以改走 WebView2
           运行时自己的环境变量 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`。
    ⚠️ 诚实记日志：如果 pywebview 用显式 `AdditionalBrowserArguments` 覆盖了环境变量，
       这批参数**实际不会生效** —— 那种情况会打印一条说明（stdout），不谎报成功。
    ⚠️ 全程不抛：任何失败都只是"少几条启动参数"，绝不影响启动。
    """
    extra = ("--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection "
             "--disable-background-timer-throttling "
             "--disable-renderer-backgrounding")
    try:
        import webview
        settings = getattr(webview, "settings", None)
        if settings is None:
            return
        # ① 只写**已存在**的键（ImmutableDict 加新键会抛 KeyError）
        wanted = {
            "ALLOW_FILE_URLS": False,                  # 我们走本地 HTTP，不用 file://
            "OPEN_EXTERNAL_LINKS_IN_BROWSER": True,    # 外链交给系统浏览器
            "OPEN_DEVTOOLS_IN_DEBUG": False,
        }
        skipped = []
        for key, value in wanted.items():
            try:
                if key in settings:
                    settings[key] = value
                else:
                    skipped.append(key)
            except Exception as exc:                   # noqa: BLE001
                skipped.append(f"{key}({exc})")
        if skipped:
            print(f"[提示] 这些 pywebview 设置项当前版本不存在，已跳过: {', '.join(skipped)}")

        # ② 浏览器参数：优先用（若将来版本提供）settings 键，否则走 WebView2 环境变量
        arg_key = next((k for k in ("additional_browser_args", "BROWSER_ARGS",
                                    "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS")
                        if k in settings), None)
        if arg_key:
            settings[arg_key] = _merge_browser_args(settings.get(arg_key), extra)
            print(f"[提示] 浏览器启动参数已写入 pywebview 设置项 {arg_key}")
        else:
            os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = _merge_browser_args(
                os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"), extra)
            # ⚠️ 如实说明：pywebview 6.2.1 自己会设 AdditionalBrowserArguments（写死），
            #    而 WebView2 的规则是"显式属性覆盖环境变量" → 这些参数很可能不生效。
            print("[提示] pywebview 当前版本没有浏览器参数设置项，已改用环境变量 "
                  "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS；若该版本显式设置了 "
                  "AdditionalBrowserArguments，则本批参数实际不生效（不影响启动）")
    except Exception as exc:                          # noqa: BLE001
        print(f"[警告] 设置 WebView2 启动参数失败（不影响启动）: {exc}")


# ========== 7. 主函数 ==========
def main():
    """主函数：等"启动画面播完"和"前端首屏就绪"都完成后再显示窗口"""
    from desktop.shell import AppShell

    _prepare_webview2()
    _write_startup_log()

    shell = AppShell(settings_manager,
                     splash_enabled=splash_enabled,
                     splash_duration_ms=splash_duration_ms)
    try:
        return shell.run()
    finally:
        # ⚠️ 只有真正走到"退出"才释放互斥锁（关闭到托盘时 close 事件被取消，不会到这）
        instance_checker.release()


if __name__ == "__main__":
    sys.exit(main())
