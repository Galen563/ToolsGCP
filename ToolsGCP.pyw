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


# ========== 1.5 清理 %TEMP% 里 ToolsGCP 的残留 ==========
def _start_temp_cleanup(delay_s: float = None, allow_full: bool = True) -> None:
    """启动早期顺手清掉 `%TEMP%\` 里 ToolsGCP 的更新残留
    ⚠️⚠️ 为什么放在**这个位置**（单实例检测之前）：
       更新流程是"旧进程退出 → 替换脚本换掉 exe → 新版进程启动"。新版进程启动时，
       旧进程的互斥锁已经没了，所以正常情况下这里就是唯一实例；但万一旧进程
       没退干净，新版会被单实例检测拦下来直接 `sys.exit(0)` —— 那时**这一行代码
       还没机会跑**，替换残留就永远留在 temp 里。所以清理必须放在**退出之前**。
    ⚠️⚠️ 为什么用 daemon 线程 + 延迟，而不是当场同步删：
       · 替换脚本 `apply_update.cmd` 可能**正在自删**，文件句柄还没释放
         （表现就是"temp 里东西还在"）→ 延迟几秒成功率最高；
       · 清理要读磁盘（可能几十 MB 的更新包），同步做会拖慢启动；
       · 线程是 daemon 的：主线程退出时它直接被丢掉，不会吊住进程。
    ⚠️ 判据在**线程里**做（tempclean.cleanup_on_startup 内部负责）：
       有 `.replace-pending` 标记 = 上次替换流程已经走过（无论成不成功）
       → 允许连根删 `<temp>\ToolsGCP\`；没有标记 = 从没触发过更新
       → **只清残留，绝不删掉用户还没应用的更新包**。
    ⚠️ allow_full=False：“已有实例、我即将退出”那条路径用。那时别的实例
       可能正在下更新包（或刚写过替换标记、替换正在进行中）
       ——这时候绝不能连根删整个目录，只能清残留。
    ⚠️ 这个函数**绝不能抛**：清理失败最多是 temp 里多点文件，不该让程序起不来。
    """
    try:
        from desktop import tempclean

        if delay_s is None:
            delay_s = tempclean.DEFAULT_CLEANUP_DELAY_S
        tempclean.cleanup_on_startup(reason="startup", delay_s=delay_s,
                                      allow_full=allow_full)
    except Exception as exc:                    # noqa: BLE001
        # 清理模块自己出问题也不影响启动（这里只能 print：logger 那会儿还没初始化）
        print(f"[ToolsGCP] 临时目录清理未执行（不影响启动）: {exc}")


_start_temp_cleanup()


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

# ========== 2.5 重启接力：等旧实例先退出，再做单实例检测 ==========
# ⚠️ 这是"设置 → 存储迁移完成后点『立即重启』但程序没重启"的根治点。
#    shell.restart() 的时序是 `Popen(新进程)` → 0.25s 后旧进程才走退出流程 →
#    main() 的 finally 里才 release() 互斥锁。新进程跑得更快，在旧进程还攥着
#    ToolsGCP_SingleInstance_Mutex 时就 check() → ERROR_ALREADY_EXISTS →
#    "激活已有实例"然后**自己退出** —— 两个都活不成新的，用户看到的就是没重启。
#    （和 --update --pid 那条是同一个坑，见文件头启动顺序第 1 条。）
#    修法：重启时旧进程会带 `--restart <旧PID>` 拉起我们；这里先等那个 PID 消失
#    （最多 10 秒，超时也放行——最坏退回老行为），互斥锁必然已释放，检测才公平。
def _wait_for_restart_parent():
    argv = sys.argv[1:]
    if "--restart" not in argv:
        return
    try:
        idx = argv.index("--restart")
        pid = int(argv[idx + 1]) if idx + 1 < len(argv) else 0
    except (ValueError, IndexError):
        return
    if pid <= 0:
        return
    try:
        import ctypes
        from ctypes import wintypes
        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0x00000000
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return                      # 旧进程已经没了（或 PID 已回收），直接继续
        kernel32.WaitForSingleObject(handle, 10000)   # 最多等 10 秒
        kernel32.CloseHandle(handle)
    except Exception as exc:            # noqa: BLE001
        # 等不到也别把启动卡死：继续走后面的单实例检测（最坏退回老行为）
        print(f"[ToolsGCP] 等待重启父进程退出失败（继续启动）: {exc}")


_wait_for_restart_parent()

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

    # ⚠️⚠️ 重要：这里即将 sys.exit(0)，而启动时启的那个
    #    daemon 清理线程还在 sleep 延迟期里 → 进程一退它就被丢掉了，
    #    清理根本不会执行。所以在退出前**同步清一次**（不延迟）：
    #    清不掉的部分（文件被占用）tempclean 会登记成"重启后删除"，
    #    不会因为退出快而永久残留。
    # ⚠️ allow_full=False：已有实例正在跑，它自己可能正在下更新包
    #    （或刚写过替换标记、替换正在进行中）——这时候绝不能连根删
    #    `<temp>\ToolsGCP\`，只能清残留。
    _start_temp_cleanup(delay_s=0.0, allow_full=False)

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

# 启动画面用的图标（与原版同一个路径：.ToolsGCP/logo.png）
APP_ICON_PATH = os.path.join(CURRENT_DIR, ".ToolsGCP", "logo.png")

# ========== 3.5 立刻顶起启动画面（本轮需求："先出画面，再开始正常启动流程"） =====
# ⚠️⚠️ 为什么必须在**这个位置**、而不是挪到 desktop/shell.py 的 run() 里：
#    需求原话是「启动动画开启后应该启动程序后立马先显示这个ui然后才开始正常流程
#    启动ToolsGCP」。而 `import desktop.shell` 会连带拉起 pywebview / pythonnet
#    (clr) / bottle / WebView2 那一大坨，慢机器上光 import 就要几百毫秒到数秒 ——
#    画面如果在那之后才建，用户看到的就是"双击图标 → 什么都没发生 → 画面闪一下
#    → 还没界面"。所以这里只依赖 pymodels 的常量和设置（已经 import 完了），
#    用纯 Win32 分层窗口先把画面顶起来，再把控制器对象交给外壳管生命周期。
#    `desktop.splash` 实测 import 43ms、不会拉进 pywebview，也不会拉进 PyQt5。
# ⚠️ 「开机自启 + 启动时最小化到托盘」这次不顶画面：主窗口都不出现，
#    弹个独立小窗等于自启还是在打扰用户（外壳里那层判断继续保留，两边口径一致）。
#    法律协议还没同意时外壳会把窗口放出来要用户同意 —— 那种情况下画面最多白顶一会儿，
#    由外壳在"主窗口显示"后统一收掉，不会留在桌面上。
splash_controller = None
if splash_enabled:
    try:
        from pymodels.constants import IS_AUTOSTART

        quiet_start = bool(IS_AUTOSTART and settings_manager.settings.get(
            "minimize_to_tray", True))
        if quiet_start:
            _splash_skip_reason = "本次是开机自启的静默启动"
        else:
            from desktop.splash import SplashController

            splash_controller = SplashController(APP_ICON_PATH, enabled=True)
            splash_controller.start()
    except Exception as _splash_exc:                  # noqa: BLE001
        # 启动画面起不来绝不能挡住程序本体：吞掉异常，外壳那边按"没有画面"继续跑
        splash_controller = None
        _splash_skip_reason = f"启动画面创建失败（不影响启动）: {_splash_exc!r}"
else:
    _splash_skip_reason = "设置里关闭了启动动画"

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
             f"启动动画: {'开' if splash_enabled else '关'}"
             f"（显示到主窗口出现为止，不再有固定时长）"
             + ("" if splash_controller else f"，本次未显示：{_splash_skip_reason}"))
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
                     splash=splash_controller)
    try:
        return shell.run()
    except Exception:
        # 外壳没跑起来（导入失败/建窗异常…）：画面必须当场收掉，
        # 否则桌面上会留一块永远点不动的置顶小窗（它活到"主窗口显示"为止，
        # 而主窗口根本不会显示）。
        try:
            if splash_controller is not None:
                splash_controller.stop(timeout=2.0)
        except Exception:                              # noqa: BLE001
            pass
        raise
    finally:
        # ⚠️ 只有真正走到"退出"才释放互斥锁（关闭到托盘时 close 事件被取消，不会到这）
        instance_checker.release()


if __name__ == "__main__":
    sys.exit(main())
