"""主窗口外壳：把 pywebview 窗口、无边框补丁、托盘、热键、启动画面、前端 ready 组装起来。
========== 启动时序（与原版 `ToolsGCP.pyw:189-213` 一一对应）==========
    主线程                          worker 线程
    ───────                         ───────────
    1. 建 pywebview 窗口（hidden + **屏幕外**）  2. Qt 启动画面开播（desktop/splash.py）
    3. webview.start()（进入主线程消息循环）
    4. 前端加载完成 → api.app.ready() 上报        ← 前端 ready
    5. 启动画面 finished 回调        ← 启动画面结束
    6. 两件都完成 → 移回工作区居中 → 打补丁 → show() 一次
⚠️ 窗口一开始必须 `hidden=True`：原版是"启动画面播完 + 首屏内容加载完"才 show，
   提前显示会看到白屏/半成品（原版注释："启动流程据此决定何时显示窗口"）。
⚠️ 打补丁（WS_THICKFRAME + NCCALCSIZE）必须在 show 之前：先显示再改样式会闪一下边框。
⚠️⚠️ **为什么还要"建在屏幕外"**：
    pywebview 6.2.1 对 `hidden=True` 的实现是（webview/platforms/winforms.py:777-781）：
        browser.Opacity = 0
        browser.Show()          # ← 建窗阶段**真的 Show 了一次**
        browser.Hide()
        browser.Opacity = 1
    它指望 Opacity=0 让这次 Show 不可见。但 WebView2 是在自己的子窗口/合成表面里渲染的，
    父窗口的 WS_EX_LAYERED alpha 未必盖得住它 —— 于是用户看到的就是"先闪出一个和主窗口
    一样大的空窗口，4 秒后才切到真正的主窗口"。
    本机离屏渲染实测的采样结果：
        · `window.events.shown` 在建窗阶段确实触发了一次（证明上面那次 Show 真的发生了）；
        · 那一刻窗口状态是 `visible=true, layered=true, alpha=0`（说明 Opacity 路径确实设上了，
          但"设上了"≠"用户看不见"—— 泄漏与否取决于 WebView2 表面，这个我们控制不了）。
    对策（不依赖 Opacity 是否好用）：
        1. 建窗时把 x/y 放到虚拟桌面之外（OFFSCREEN_X/Y）→ 任何"提前的 Show"都看不见；
           （实测采样：建窗阶段所有 visible 采样都在屏幕外）
        2. 双条件 ready 之后，**先**把窗口移回工作区正中，**再**第一次 show()；
           （实测采样：第一次"可见且在屏幕上"的那一帧
             已经就是最终尺寸 + 居中位置，没有"先显示再移动/改大小"的跳变）
    这样从头到尾只有一次用户可见的显示动作，且那一次已经带齐尺寸/位置/无边框补丁/图标。
========== 关闭行为（对应原版 `MainWindow.closeEvent`）==========
    · close_mode == "隐藏到托盘中" → hide + 托盘气泡"程序已隐藏到托盘"
    · 否则 → 隐藏托盘 + 真正关闭窗口
⚠️ pywebview 的 `closing` 事件返回 True 可以**取消**关闭（Event(self, True) 是同步执行并
   收集返回值的，见 webview/event.py:29-63）。这是实现"关闭到托盘"的唯一正确入口。
========== 退出闸门（必须存在的原因）==========
    `WebView2` 比顶层窗口先销毁。窗口关掉之后任何 `window.evaluate_js(...)` 都会在
    pywebview 里抛 `System.ObjectDisposedException: 无法访问已释放的对象。对象名:"WebView2"`
    （webview/platforms/edgechromium.py:152）并打出一大段 "[pywebview] Error occurred in script"。
    所以本文件维护一个 `_teardown_started` 闸门：
        · `_on_closing`（真退出）/`quit_app`/`_shutdown` 第一件事就是置位它；
        · 所有"后端 → 前端"的脚本执行统一走 `eval_js_safe()`（`push_event` 内部就用它）：
          发起时 + 真正调 evaluate_js 之前各查一次闸门，再查 `frame.is_window_alive(hwnd)`，
          最后一层还捕获 ObjectDisposedException（并且只记一条日志，避免刷屏）；
        · 同时先停掉会回调前端的后台组件（首屏就绪定时器 / 全局热键 / 托盘线程）。
    ⚠️⚠️ 只守住自己代码还不够：pywebview 的 `js_bridge_call`（webview/util.py:264）在
       **js_api 回调返回之后**还要 `window.evaluate_js(...)` 把结果送还 JS。那段代码在库内部，
       我们闸不住 —— 所以退出类接口（`window.close` / `shell.quit` / `shell.restart` /
       `update.install_and_restart`）一律"**先返回、再延迟退出**"
       （`request_close_async` / `quit_app_async`），把那句回调的时间差让出来。
========== F11 / 全屏（第三条到达路径）==========
    F11 有三条可能到达后端的路径：页面 keydown、WebView2 原生 `AcceleratorKeyPressed`
    （`frame.install_webview_accelerators`，在 GUI 线程上装）、前端按钮点击。
    三条全部汇聚到本文件的 `toggle_fullscreen()`，由它统一做诊断日志 + 状态判断 +
    `push_event("window.fullscreen", {fullscreen})`，前端据此隐藏自绘标题栏。
    ⚠️ 原生那条路径会在 F11 上 `Handled=True`（页面收不到该键），避免"原生切一次 +
       前端再切一次"的双触发；原生装不上时自动退回页面 JS 那条路。
"""

import os
import sys
import threading
import time

import webview

from pymodels.constants import IS_AUTOSTART, SCRIPT_DIR, CONFIG_DIR

from .api import Api
from .native import appicon, autostart, frame, hotkey, tray, win32
from .splash import SplashController
from .webhost import create_app

# 首屏迟迟不 ready 也要把窗口放出来（否则用户以为没启动）
#⚠️ 这个值必须覆盖"冷启动 + WebView2 首次初始化 + 页面加载 + boot() 数据拉取"的完整耗时。
#    实测 WebView2 冷启动本身就要 8 秒左右（页面 loaded 事件在窗口显示之后才到），
#    原来写 6000ms 会在页面还没开始跑 boot() 时就判超时，日志表现为
#    首屏超过 6000 ms 未上报就绪紧跟着前端页面已加载——顺序颠倒。
UI_READY_TIMEOUT_MS = 20000

# ========== 窗口边框：**系统标题栏**（真正的原生 caption 按钮） ==========
# True  = 自绘无边框窗口（前端画标题栏 + 三个按钮，frame.py 打 WS_THICKFRAME 补丁）。
# False = 普通系统窗口：Windows 自己画标题栏与三个按钮（DWM 绘制，带 Win11 的悬停/按下过渡动画）。
#需求原话（最新一轮）：
#   修复窗口顶部栏的最小化/全屏/关闭按钮不是系统原生 —— 因为我 Win11 它每个按钮点击后
#     都有过渡动画反馈，所以知道你用的不是系统原生的；还有全屏点击没反应，全屏按钮图标不对。
# 自绘按钮**永远**做不出 Win11 原生 caption 按钮的那套过渡动画（那是 DWM 的特效），
#所以这里必须是 False：
#   · 三个按钮 = 系统绘制，动画/命中/最大化还原/贴边吸附全是原生行为；
#   · 系统标题栏会通过 DWMWA_USE_IMMERSIVE_DARK_MODE 刷成程序的深色（见 _apply_caption_theme），
#     观感仍然"暗色 + 左边图标标题、右边三个按钮"；
#   · 前端 index.html 里那条品牌栏保留（logo + 标题），只删掉三个自绘按钮，避免出现两套按钮；
#   · 真·全屏用 F11 / 前端全屏按钮都行：统一走 shell.toggle_fullscreen() →
#     frame.enter_fullscreen/exit_fullscreen（原生 SetWindowPos 铺满显示器 + 置顶让开任务栏，
#     退出时还原矩形/最大化状态/Z 序）。见 frame.py 里那一大段注释。
FRAMELESS_WINDOW = True

WINDOW_TITLE = "ToolsGCP"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 880
WINDOW_MIN_SIZE = (1000, 660)

# 建窗时用的"屏幕外"坐标（经典的空闲窗口位置）。
# ⚠️ 见模块 docstring：pywebview 的 hidden 实现会先 Show() 一次，把窗口放在这里，
#    那一次 Show 就在用户视野之外；ready 之后我们再移回工作区正中。
OFFSCREEN_X = -32000
OFFSCREEN_Y = -32000

# 热键表：与原版 `MainWindow.HOTKEYS` 完全一致（name, settings_key, default, label_key）
HOTKEYS = (
    ("search", "hotkey_search", "Ctrl+Q", "hotkey_search"),
    ("ai", "hotkey_ai", "Ctrl+Alt+G", "hotkey_ai"),
)


def _log(level: str, category_zh: str, category_en: str, message: str):
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)(category_zh, category_en, message)
    except Exception:
        pass


class AppShell:
    """整个桌面上壳（一个实例）"""

    def __init__(self, settings_manager, splash_enabled: bool = True,
                 splash_duration_ms: int = 2000):
        self.settings_manager = settings_manager
        # 业务管理器：与原版 MainWindow 的接线保持一致（同一份实例传给所有域）
        # ⚠️ 它们必须在**任何 API 调用之前**就绪：js_api 回调是并发的工作线程，
        #    懒建会出现"两个线程各建一份"的竞态。
        from pymodels.core.favorites_manager import FavoritesManager
        from pymodels.core.language_manager import LanguageManager
        self.favorites_manager = FavoritesManager()
        self.language_manager = LanguageManager()

        self.started_at = time.time()
        self.window = None
        self.splash = None
        self.tray = None
        self.hotkeys = None
        self.api = None

        # 隐私同意 + 公告状态：原版各有一份落盘状态文件，这里复用同一套（含哈希校验）
        # ⚠️ 隐私状态用 desktop/native/privacy_state.py 这个**纯 Python** 版本：
        #    原版 ui/privacy_consent.py 顶部就 import PyQt5 + qfluentwidgets，而主线程
        #    import 过 PyQt5 会让进程退出时 100% 崩 0xC0000005（见 splash.py 长注释）。
        #    两份写的是同一个 json、同一套哈希，所以原版里同意过这里直接认。
        #    ⚠️ 目录必须是 DATA_DIR（= <数据根>/config），和原版 resolve_data_root()/config 一致；
        #       用 CONFIG_DIR（.ToolsGCP 目录本身）会把文件放错位置、两边各写一份。
        from .native.privacy_state import PrivacyState
        from pymodels.core.announcements import AnnouncementStore
        from pymodels.constants import DATA_DIR
        self.privacy_manager = PrivacyState(DATA_DIR)
        self.announcement_store = AnnouncementStore()

        # 启动双条件（照原版 state = {"ui": ..., "splash": ...}）
        self._frontend_ready = False
        self._splash_done = not splash_enabled
        self._shown = False
        # 「启动时最小化到托盘」闸门（设置 minimize_to_tray，仅在开机自启 --autostart 时生效）：
        # ⚠️ 需求修复：这个开关以前**从来没接进启动流程** —— autostart.py 写的命令行带了
        #    `--autostart`，pymodels.constants.IS_AUTOSTART 也确实解析它，但全项目没有任何
        #    一处读这个值（grep 实证：只有定义、没有消费方），所以开关拨了也没用。
        #    现在：开机自启 + 开关开 → _try_show 不做那次"唯一的 show"，窗口留在屏幕外，
        #    托盘照常创建（图标在、双击/右键可呼出）；手动启动不受影响。
        #    注意不能走 hide_to_tray()：那会弹"已隐藏到托盘"气泡，开机静默自启不该打扰人。
        # ⚠️ 兜掉"开机自启没开但带 --autostart"的脏场景（比如用户关了自启、注册表还留着旧值）：
        #    以注册表实际值 + IS_AUTOSTART 双条件为准。
        self._startup_hidden = False
        try:
            if IS_AUTOSTART and self.settings_manager:
                minimize = bool(self.settings_manager.settings.get("minimize_to_tray", True))
                # ⚠️ 法律闸门优先于"最小化到托盘"（本轮两条需求不能打架）：
                #    没同意过协议就静默藏进托盘，用户永远看不到协议窗 → 程序等于
                #    死锁（前端也会把窗口放出来要同意）。已同意才允许隐藏启动。
                agreed = False
                try:
                    state = self.privacy_manager
                    agreed = bool(state and state.is_valid(state.load()))
                except Exception:
                    agreed = False
                if minimize and autostart.is_enabled() and not agreed:
                    _log("info", "启动", "startup",
                         "开机自启带「启动时最小化到托盘」，但本机还没有有效的法律同意记录："
                         "本次照常显示主窗口（协议必须让用户看到），同意后再按设置隐藏")
                elif minimize and autostart.is_enabled():
                    self._startup_hidden = True
                    _log("info", "启动", "startup",
                         "检测到开机自启（--autostart）且「启动时最小化到托盘」已开启："
                         "主窗口将保持隐藏，可从托盘呼出")
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "启动", "startup", f"读取启动最小化设置失败（按正常启动处理）: {exc}")
        self._show_lock = threading.RLock()
        self._closing = False
        self._quitting = False
        self._tray_hint_shown = False
        # 退出闸门：置位后**禁止**再有任何"回调前端"的动作（见模块 docstring 的"退出闸门"）
        self._teardown_started = False
        # 退出确认闸门 —— 前端已经弹过确认框并得到用户同意时置 True，
        #    后端就**不再**弹原生确认框（避免弹两次）。
        self._exit_confirmed = False
        # 给 api 层判断"要不要走原生全屏"用（frameless 模式下全屏是 frame.py 自己实现的）
        self.frameless = FRAMELESS_WINDOW
        self._window_closed = False
        # 全屏状态（F11 / 按钮 共用；非 frameless 模式下 pywebview 不回报状态，只能自己记）
        self._fullscreen_state = False
        # 前端脚本执行失败/WebView2 已释放的日志限流（退出竞态会连续失败，别刷屏）
        self._js_disposed_logged = False
        self._js_error_logged_at = 0.0
        self._stop_lock = threading.RLock()
        # 目标几何（工作区居中）；建窗时故意用的是屏幕外坐标，ready 时才搬回来
        self._final_size = (WINDOW_WIDTH, WINDOW_HEIGHT)
        self._final_pos = (None, None)

        self._splash_enabled = bool(splash_enabled)
        self._splash_duration_ms = int(splash_duration_ms or 0)
        # 启动画面真正开始播放的时刻（run() 里会再设一次；先给个值防止提前被问到）
        self._splash_started_at = self.started_at
        self._ready_watchdog = None
        self._hotkey_status = {}
        self._icon_path = os.path.join(CONFIG_DIR, "logo.png")

    # ================= 窗口句柄 =================
    def hwnd(self) -> int:
        return frame.hwnd_of_window(self.window) if self.window is not None else 0

    # ================= 系统标题栏配色（非 frameless 模式） =================
    def _apply_caption_theme(self):
        """让 Windows **自带的标题栏**跟随程序的深/浅色主题
        ⚠️ 只在 FRAMELESS_WINDOW=False（系统标题栏）时有意义：不刷的话，程序是深色、
           系统是浅色时，顶部会突然出现一条白条，很割裂。
        DWMWA_USE_IMMERSIVE_DARK_MODE 在 Win10 1809~1909 是 19，之后固定 20 —— 两个都试一遍。
        """
        try:
            import ctypes
            from .native import win32
            hwnd = self.hwnd()
            if not hwnd or not getattr(win32, "dwmapi", None):
                return
            value = ctypes.c_int(1 if self._is_dark() else 0)
            for attr in (20, 19):
                try:
                    win32.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
                except Exception:
                    pass
            # Win11：顺带把标题栏/边框颜色钉成程序底色，避免"沉浸深色"下仍偏系统灰
            if self._is_dark():
                color = ctypes.c_int(0x001C1C1C)          # 0x00BBGGRR
                try:
                    win32.dwmapi.DwmSetWindowAttribute(
                        hwnd, 34, ctypes.byref(color), ctypes.sizeof(color))   # DWMWA_BORDER_COLOR
                except Exception:
                    pass
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "启动", "startup", f"系统标题栏配色失败: {exc}")

    # ================= 系统对话框（另存为 / 选目录） =================
    # 都是 pywebview 的标准对话框（内部 Invoke 到 GUI 线程，从 js_api 工作线程调用是安全的）。
    # 原版对应 QFileDialog.getSaveFileName / getExistingDirectory，行为一致。
    @staticmethod
    def normalize_file_types(file_types) -> tuple:
        """把前端/调用方传的 file_types 规范成 pywebview 能吃的元组
        pywebview 的 `parse_file_type`（webview/util.py:155-165）是个**严格**正则：
            ^([\\w ]+)\\((\\*(?:\\.(?:\\w+|\\*))*(?:;\\*(?:\\.(?:\\w+|\\*))*)*)\\)$
        只认 `描述 (*.ext)` 一种写法，描述里只允许字母/数字/下划线/空格（中文可以，
        因为 Python 的 `\\w` 默认是 Unicode；但 `-` `/` `：` `&` 这类字符会让它抛
        ValueError）。而 `Window.create_file_dialog` 是**先校验再弹框**，所以：
            前端只要传个 `*.json` 或 `JSON 文件|*.json`，异常就会在对话框打开之前抛出来，
            被这里 except 吞掉 ⇒ 用户看到的是"点了导出什么都没发生"（像被取消）。
        这里把常见写法都吃下来（返回空元组 = 不加筛选器，用"所有文件"）：
            `*.json`                        → `JSON 文件 (*.json)`
            `JSON 文件|*.json`              → `JSON 文件 (*.json)`
            `JSON 文件 (*.json)`            → 原样（描述里的非法字符会被清掉）
            `清单 (*.json);;文本 (*.txt)`   → 两条（也接受列表）
        """
        import re
        if not file_types:
            return tuple()
        if isinstance(file_types, str):
            raw = [file_types]
        else:
            try:
                raw = [str(item) for item in file_types if item]
            except Exception:
                raw = [str(file_types)]
        entries = []
        for item in raw:
            for piece in str(item).split(";;"):
                piece = piece.strip()
                if not piece:
                    continue
                description = ""
                patterns_text = piece
                if "|" in piece:
                    description, patterns_text = piece.split("|", 1)
                elif "(" in piece and ")" in piece:
                    description = piece.split("(", 1)[0]
                    patterns_text = piece.split("(", 1)[1].rsplit(")", 1)[0]
                patterns = []
                for token in re.split(r"[;,]", patterns_text):
                    token = token.strip().lower()
                    if not token:
                        continue
                    if token == "*" or token == "*.*":
                        token = "*.*"
                    elif not token.startswith("*."):
                        if token.startswith("."):
                            token = "*" + token
                        else:
                            token = "*." + token.lstrip("*.")
                    if token == "*.*" or re.fullmatch(r"\*\.[\w.*]+", token):
                        patterns.append(token)
                if not patterns:
                    continue
                if not description:
                    exts = [p[2:].upper() for p in patterns if p.startswith("*.") and p != "*.*"]
                    description = (exts[0] + " 文件") if exts else "文件"
                # 描述里只留正则允许的字符（多语言描述尽量保留，非法字符换空格）
                description = re.sub(r"[^\w ]+", " ", str(description)).strip()
                description = re.sub(r"\s+", " ", description) or "文件"
                entries.append(f"{description} ({';'.join(patterns)})")
        return tuple(entries)

    def pick_save_path(self, default_name: str = "", file_type="", file_types=None):
        """系统另存为：返回完整路径；用户取消返回 None
        `file_type` / `file_types` 都接受字符串或列表，由 `normalize_file_types` 兜底，
        所以前端传 `*.json` 这种裸写法也不会让对话框打不开（见那里的长注释）。
        返回的路径**不保证**带扩展名（.NET 的 SaveFileDialog 会按筛选器补，但用户
        自己敲了别的后缀就照原样），补扩展名由调用方按自己的业务决定。
        """
        if self.window is None:
            return None
        types = self.normalize_file_types(file_types if file_types else file_type)
        try:
            result = self.window.create_file_dialog(
                webview.FileDialog.SAVE,
                # ⚠️ 不要传 ""：winforms 后端会退化成 os.environ['HOMEPATH']
                #    （形如 \Users\Administrator，没有盘符，跨盘时对话框会开错地方）。
                directory=os.path.expanduser("~"),
                allow_multiple=False,
                save_filename=str(default_name or ""),
                file_types=types)
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "外壳", "dialog", f"另存为对话框失败: {exc}")
            return None
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        return str(path or "") or None

    def pick_folder(self, title: str = "", initial: str = "") -> str:
        """系统选择文件夹：返回目录；取消返回空串
        ⚠️ pywebview 的 folder 对话框返回的是所选目录本身（不递归、不建子目录），
           下面再建 .ToolsGCP这件事由调用方决定（原版 cards_storage.py 也是这么做的）。
        """
        if self.window is None:
            return ""
        try:
            result = self.window.create_file_dialog(
                webview.FileDialog.FOLDER, directory=str(initial or ""))
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "外壳", "dialog", f"选择文件夹对话框失败: {exc}")
            return ""
        if not result:
            return ""
        path = result[0] if isinstance(result, (list, tuple)) else result
        return str(path or "")

    # ================= 启动 =================
    def _precheck_privacy(self):
        """第一步校验法律同意状态（需求：把协议校验提到最高优先级，先于云端资源准备）。
        ⚠️ 这是**纯本地**读取（json + 哈希），不碰网络，毫秒级完成；读到什么就记什么，
           弹窗与否由前端决定（前端的闸门同样排在所有网络加载之前）。
           它存在的意义：① 日志里第一眼就能看到"这台机器同意过没有、文件在不在"；
           ② 提前把 PrivacyState 读一遍，前端第一次调 privacy_state 时零等待。
        """
        try:
            state = self.privacy_manager
            if state is None:
                return
            path = str(getattr(state, "path", "") or "")
            exists = bool(state.exists()) if hasattr(state, "exists") else False
            data = state.load()
            agreed = bool(state.is_valid(data))
            _log("info", "启动", "startup",
                 f"法律同意状态预校验（第一步）：path={path} exists={exists} agreed={agreed}")
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "启动", "startup", f"法律同意状态预校验失败（不挡启动）: {exc}")

    def run(self) -> int:
        """主入口：建窗口 → 起启动画面 → 进入 pywebview 主循环"""
        # ⚠️ 第一件事：法律文件（用户协议/隐私政策）同意状态校验 —— 在任何网络
        #    资源准备之前（本轮需求）。失败也只记日志，绝不挡启动。
        self._precheck_privacy()
        app = create_app()
        self.api = Api(self)

        # ⚠️ 建窗时就把坐标算好（供 ready 之后搬回来用），但**传进去的是屏幕外坐标**：
        #    WinForms 的 Form.Show() 会按 StartPosition 自己摆一次，先显示再 SetWindowPos
        #    会看到"先偏一下、再跳回中间"。给 x/y 会让 pywebview 把 StartPosition 设成
        #    Manual（webview/platforms/winforms.py:214-220），于是位置完全由我们说了算。
        #    而"放在屏幕外"是为了躲开 pywebview `hidden=True` 那次真实的 Show()
        #    （见模块 docstring：它就是那个"和主窗口一样大的空窗口"的来源）。
        # ⚠️ 分辨率等比适配（需求：以"1080p 刚刚好"为基准，其它分辨率按比例放大窗口与界面）：
        #    `ui_scale_factor()` 返回 r =（当前逻辑工作区宽 ÷ 1920）。窗口逻辑宽高各乘 r，
        #    界面再用 WebView2 ZoomFactor=r 同步缩放（见 frame.apply_page_zoom 的推导注释）。
        #    1080p@100% 时 r=1 → 与现在**完全一致**（1280×880、无缩放）；
        #    2560×1440 → r≈1.33 → 窗口与卡片/文字/间距整体等比放大。
        self._ui_scale = frame.ui_scale_factor()
        win_w, win_h = frame.fit_size(round(WINDOW_WIDTH * self._ui_scale),
                                      round(WINDOW_HEIGHT * self._ui_scale))
        pos_x, pos_y = frame.centered_position(win_w, win_h)
        self._final_size = (win_w, win_h)
        self._final_pos = (pos_x, pos_y)
        if self._ui_scale != 1.0:
            _log("info", "启动", "startup",
                 f"分辨率适配：缩放比例 r={self._ui_scale:.3f}，"
                 f"窗口 {WINDOW_WIDTH}x{WINDOW_HEIGHT} → {win_w}x{win_h}（逻辑像素）")

        self.window = webview.create_window(
            WINDOW_TITLE,
            url=app,
            js_api=self.api,
            width=win_w,
            height=win_h,
            # ⚠️ 屏幕外（不是最终位置）：ready 之后由 _try_show 搬回工作区正中再显示。
            x=OFFSCREEN_X,
            y=OFFSCREEN_Y,
            min_size=(max(640, round(WINDOW_MIN_SIZE[0] * self._ui_scale)),
                      max(420, round(WINDOW_MIN_SIZE[1] * self._ui_scale))),
            frameless=FRAMELESS_WINDOW,   # False = 系统标题栏与系统三个按钮
            easy_drag=False,         # ⚠️ 必须关：否则整个窗口都是拖动区，前端按钮点不动
            shadow=True,             # 让 DWM 画投影（Win11 圆角也靠它）
            resizable=True,
            # ⚠️ 建窗时 pywebview 会把它写成 WebView2 的 DefaultBackgroundColor 和
            #    Form.BackColor —— 也就是"四角/顶边露出来的那一圈颜色"。
            #    必须和 webui/css/variables.css 的 `--page` 深色值（#1c1c1c）一致，
            #    否则浅色主题下这层深色底会从圆角/顶边透出来 = 用户说的白边黑边。
            #    真正的深浅跟随在 frame.apply_dark() → _refresh_page_background() 里刷。
            background_color="#1C1C1C",
            text_select=False,
            hidden=True,             # 双条件 ready 之后才 show
        )
        self.window.events.closing += self._on_closing
        self.window.events.closed += self._on_closed
        self.window.events.loaded += self._on_loaded
        self.window.events.shown += self._on_shown

        # 启动画面（Qt 原版逻辑，跑在自己的线程里）
        # ⚠️「启动时最小化到托盘」生效时**不播启动画面**：那是个独立的 Qt 小窗，
        #    主窗口藏了、画面却弹出来，等于开机自启还是打扰用户（自启默认值
        #    splash_screen_enabled 也是 False，这里只是给"开了动画 + 开了最小化"
        #    的组合兜底，让隐藏启动真正做到全程静默）。
        splash_enabled = self._splash_enabled and not self._startup_hidden
        if not splash_enabled and self._splash_enabled:
            _log("info", "启动", "startup", "启动画面已跳过（本次为最小化到托盘的静默启动）")
            # 双条件的另一条要**立刻置完成**，否则 _try_show 永远等不到 splash 回调
            self._splash_done = True
        self._splash_started_at = time.time()
        self.splash = SplashController(
            self._icon_path, self._splash_duration_ms,
            enabled=splash_enabled, on_finished=self._on_splash_finished)
        self.splash.start()

        # 前端首屏就绪的兜底定时器：超时即视为就绪（与原版 UI_READY_TIMEOUT_MS 语义一致）
        self._ready_watchdog = threading.Timer(
            UI_READY_TIMEOUT_MS / 1000.0, self._on_ready_timeout)
        self._ready_watchdog.daemon = True
        self._ready_watchdog.start()

        _log("info", "启动", "startup", "pywebview 主循环已启动（窗口暂不显示）")
        try:
            webview.start(self._on_gui_started, gui="edgechromium")
        finally:
            self._shutdown()
        return 0

    def _on_gui_started(self):
        """webview.start() 的回调：GUI 线程已就绪（此时可以安全操作窗口）
        ⚠️ 这个回调是 `webview.start(func=...)` 起的**另一条线程**里跑的，而且跑在
           `guilib.create_window()` **之前**（见 webview/__init__.py:300-312）——这时
           `window.native` 还不存在，直接取句柄会拿到 0。所以这里只是等一个事件，
           真正的补丁在窗口 Shown 之后打（见 _wait_for_window）。
        """
        threading.Thread(target=self._wait_for_window, name="ToolsGCP-framewait",
                         daemon=True).start()
        self._start_tray_and_hotkeys()

    def _wait_for_window(self):
        """等窗口真的创建出来，再打无边框补丁 + 设图标
        ⚠️ 这里**不居中**：居中的正确时机是 ready 之后、`show()` 之前（见 `_try_show` 的说明）。
        """
        try:
            self.window.events.shown.wait(10)
        except Exception:
            pass
        hwnd = self.hwnd()
        if not hwnd:
            _log("warn", "启动", "startup", "未取得窗口句柄，无边框补丁未应用")
            return
        if not FRAMELESS_WINDOW:
            # 系统标题栏模式：补丁会把非客户区抹掉（等于隐藏系统按钮），所以跳过。
            _log("info", "启动", "startup",
                 f"窗口外壳就绪 hwnd={hwnd}，使用系统标题栏（未打无边框补丁）")
        else:
            try:
                # ⚠️ 把 window 一起传进去：frame 层要用它把 Form.BackColor /
                #    WebView2.DefaultBackgroundColor 刷成页面底色（见
                #    frame._refresh_page_background），否则四角会露出建窗时写死的底色。
                frame.install(hwnd, dark=self._is_dark(), window=self.window)
                _log("info", "启动", "startup",
                     f"窗口外壳就绪 hwnd={hwnd}，已打无边框补丁（可拖边缩放）")
            except Exception as exc:                          # noqa: BLE001
                _log("err", "启动", "startup", f"窗口外壳初始化失败: {exc}")
        # 图标：窗口句柄一存在就设（show 之后 _on_shown 还会再设一次，见那里的说明）
        self._apply_icon()
        # 分辨率等比适配：把 WebView2 的 ZoomFactor 钉成 r（见 run() 里的推导注释）。
        # ⚠️ r=1.0（1080p@100% 基准）时**跳过**：WebView2 默认就是 1.0，不去碰它最安全。
        # ⚠️ 内部走 GUI 线程轮询等 CoreWebView2 就绪，不在这里阻塞，也不会崩。
        try:
            scale = float(getattr(self, "_ui_scale", 1.0) or 1.0)
            if abs(scale - 1.0) > 0.005:
                frame.apply_page_zoom(self.window, scale)
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "启动", "startup", f"应用界面缩放失败（窗口照常可用）: {exc}")
        # F11：原生层接管（WebView2 的浏览器加速键 + AcceleratorKeyPressed）。
        # ⚠️ 必须放在窗口建好之后、GUI 线程里（frame 内部用 on_gui_thread 编组），
        #    而且它自己会等 CoreWebView2 初始化完成，这里不会阻塞。
        try:
            installed = frame.install_webview_accelerators(
                self.window, on_f11=self._on_native_f11)
            _log("info" if installed else "warn", "启动", "startup",
                 "F11 全屏快捷键：" + ("原生层已安装处理通道" if installed
                                      else "未安装原生通道，F11 由页面脚本处理"))
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "启动", "startup", f"安装 F11 原生快捷键处理器失败（不影响启动）: {exc}")

    def _apply_icon(self):
        """把 `.ToolsGCP/logo.png` 设为窗口图标 + 任务栏图标（失败只记日志）
        ⚠️ 只设 AppUserModelID 不够：任务栏按钮图标读的是窗口的 WM_SETICON（详见
           desktop/native/appicon.py 的 docstring）。这里做两遍（建窗后 + 首次显示后），
           因为任务栏按钮是在窗口第一次真正显示时才建立的。
        """
        if self._teardown_started:
            return False
        hwnd = self.hwnd()
        if not hwnd:
            return False
        try:
            ok = appicon.apply_to_window(hwnd, self._icon_path, self.window)
            if not ok:
                _log("warn", "启动", "startup",
                     f"窗口图标设置失败（任务栏可能显示默认 Python 图标）: {self._icon_path}")
            return ok
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "启动", "startup", f"设置窗口图标异常（已跳过）: {exc}")
            return False

    # ================= 事件 =================
    def _on_loaded(self):
        """页面加载完成（DOM ready）：此时前端脚本开始跑，但还没画完"""
        _log("info", "启动", "startup", "前端页面已加载，等待首屏就绪上报")

    def _on_shown(self):
        """窗口第一次真正显示：这里做"显示之后才能做"的事"""
        if self._teardown_started:
            return
        try:
            hwnd = self.hwnd()
            if hwnd:
                # 圆角/边框色 + 逐窗口的过渡动画属性，在"真的显示出来"之后重放一次：
                # 这时 DWM 一定已经接管了这个窗口，重放必定生效（见 frame.refresh_window_attrs）
                frame.refresh_window_attrs()
                hwnd = self.hwnd()
            if hwnd:
                # 任务栏按钮是在窗口第一次显示时建立的 → 这里再设一次图标最保险
                self._apply_icon()
                frame.bring_to_front(hwnd)
        except Exception:
            pass

    def _on_closed(self):
        """窗口已销毁（pywebview 的 closed 事件）：从此禁止一切窗口/前端操作"""
        self._window_closed = True
        self._teardown_started = True
        _log("info", "窗口", "window", "主窗口已销毁，已停止向前端推送")

    def _on_splash_finished(self):
        self._splash_done = True
        self._log_startup_state()
        self._try_show()

    def splash_remaining_ms(self) -> int:
        """启动画面还剩多少毫秒（给前端做"启动动画播完再显示界面"用）
        ⚠️ 需求：把启动动画时长设成 5 就必须真的播满 5 秒。
            早期只有原生窗口受这个约束，前端自己的 loading 遮罩却在数据一回来就撤了，
            看起来就是"5 秒没到窗口就出来了"。所以这里把剩余时长也告诉前端。
        """
        if self._splash_done:
            return 0
        if not self._splash_enabled:
            return 0
        splash = self.splash
        if splash is None:
            return 0
        # 已经播过的毫秒数 = 现在 - 启动时刻（SplashController.start 的时间点）
        try:
            elapsed_ms = (time.time() - self._splash_started_at) * 1000.0
        except Exception:
            return 0
        left = int(self._splash_duration_ms - elapsed_ms)
        return max(0, left)

    def wait_splash_done(self, timeout: float = 30.0) -> bool:
        """阻塞等启动画面播完（js_api 工作线程里用；超时也放行）"""
        splash = self.splash
        if splash is None:
            return True
        try:
            return bool(splash.wait(timeout))
        except Exception:
            return True

    def _on_ready_timeout(self):
        if self._frontend_ready or self._teardown_started:
            return
        self._frontend_ready = True
        _log("warn", "启动", "startup",
             f"首屏在 {UI_READY_TIMEOUT_MS} ms 内未上报就绪，已按超时继续显示窗口")
        self._try_show()

    def mark_frontend_ready(self):
        """由 `api.app.ready()` 调用（工作线程里）"""
        if self._frontend_ready:
            return
        self._frontend_ready = True
        _log("info", "启动", "startup",
             f"首屏内容加载完成（启动后 {time.time() - self.started_at:.2f}s）")
        self._log_startup_state()
        self._try_show()

    def _log_startup_state(self):
        # 只在调试级别记录：这个方法会在"前端就绪/启动画面完成"时各调用一次，
        # INFO 级别会重复刷两条，真正重要的是后面的主窗口已显示。
        _log("dbg", "启动", "startup",
             f"启动条件状态：前端就绪={self._frontend_ready}，启动画面完成={self._splash_done}")

    # ================= 显示（双条件） =================
    def _try_show(self):
        """双条件都满足后**唯一**的一次显示动作
        顺序（每一步都有原因，别调）：
          1. 退出闸门 / 已显示过 → 直接返回；
          2. 补一次无边框补丁（句柄可能刚就绪，先显示再改样式会闪边框）；
          3. 把窗口从屏幕外搬回工作区正中（work area 居中）；
             ⚠️ pywebview 的 `resize()`/`move()` 自带 SWP_SHOWWINDOW，所以这一步实际上
             就已经把窗口"显示"出来了 —— 但此刻它还在屏幕外，用户看不到任何东西；
          4. 确认它真的回到屏幕上了（frame.is_on_screen）；没有就用原生 SetWindowPos 兜底；
          5. 最后 `show()` 收口：用户第一次看到它的那一帧已经在最终位置、最终尺寸上，
             无边框补丁/主题色/图标也都就位 —— 这就是"不闪"的原因。
        """
        with self._show_lock:
            if self._shown or self.window is None:
                return
            if self._teardown_started or self._quitting:
                return
            if not (self._frontend_ready and self._splash_done):
                return
            # 「启动时最小化到托盘」：开机自启且开关打开 → 这次"唯一显示"不执行。
            # ⚠️ 这里连"搬回工作区居中"都不能做：center/resize/move 全都带
            #    SWP_SHOWWINDOW（见模块 docstring 第③点），搬回来就等于显示。
            #    窗口安静地留在屏幕外，后续由 show_window()（托盘双击/热键/单实例激活）
            #    再走一次"居中 + show"。
            if self._startup_hidden:
                self._shown = True
                _log("info", "启动", "startup",
                     "启动时最小化到托盘已开启（开机自启）：主窗口保持隐藏，"
                     "双击托盘图标可呼出")
                return
            self._shown = True
        try:
            # ① 先补一次补丁（句柄可能刚就绪），再显示 —— 顺序反了会闪一下系统边框
            #    ⚠️ 系统标题栏模式（FRAMELESS_WINDOW=False）下不能打这个补丁，
            #       否则非客户区被清零 = 系统三个按钮消失。
            hwnd = self.hwnd()
            if hwnd and FRAMELESS_WINDOW:
                # window 一起传：显示前把 Form/WebView2 底色对齐主题，首帧就不会露色差
                frame.install(hwnd, dark=self._is_dark(), window=self.window)

            # ② 把窗口从"屏幕外"搬回目标位置（工作区居中）
            #    ⚠️ 建窗时是 OFFSCREEN_X/Y（见 run()），所以这一步是必须的：搬不回来
            #       就会出现"窗口隐藏着但永远在屏幕外"，用户以为程序没启动。
            #    ⚠️ 必须让 frame 层编组到 **GUI 线程**：跨线程的 SetWindowPos / Form.Location
            #       会被 WinForms 静默忽略（返回 1、错误码 0，窗口却不动）。
            #    ⚠️⚠️ 注意 `window.resize()/move()` **自带 SWP_SHOWWINDOW**
            #       （webview/platforms/winforms.py:617 的 flags=64、:635-643 显式写了
            #       SWP_SHOWWINDOW=0x0040）—— 也就是说调它们就等于"把窗口显示出来"。
            #       这不会闪：此刻窗口还在屏幕外，resize 那一拍用户看不到；
            #       真正露脸的是随后的 move，而它已经带着最终尺寸与居中位置
            #       （探针 first_onscreen_frame_is_final_geometry 验证了这一点）。
            if self.window is not None:
                try:
                    frame.center_on_screen(hwnd, self.window)
                except Exception:
                    pass
            # ③ 兜底 + 自检：托管属性那条路没生效时就上原生 SetWindowPos（同样编组 GUI 线程）
            if hwnd and not frame.is_on_screen(hwnd):
                try:
                    frame.force_center_on_screen(hwnd, self.window)
                except Exception:
                    pass
                _log("warn", "启动", "startup",
                     "托管居中未生效，已改用原生 SetWindowPos 将窗口移回工作区")

            # ④ 唯一一次 show()
            self.window.show()
            # ⑤ 系统标题栏配色（必须在 show 之后：DWM 在窗口真正显示时才建 caption）
            if not FRAMELESS_WINDOW:
                self._apply_caption_theme()

            # ⑤ show 之后再纠一次（对 Show() 可能做的自我摆放做最终收敛；同样编组 GUI 线程）
            if hwnd:
                frame.center_on_screen(hwnd, self.window)
                # 记一条几何日志：启动期"窗口摆在哪"这件事全靠它排查
                # （原版也有 `_geometry_text()` 这套记录，见 main_window.py:918）
                try:
                    wl, wt, wr, wb = frame.win32.rect_of(hwnd)
                    al, at, ar, ab = frame.win32.work_area(hwnd)
                    _log("info", "启动", "startup",
                         f"窗口几何: ({wl},{wt})-({wr},{wb}) "
                         f"工作区: ({al},{at})-({ar},{ab}) "
                         f"目标: {self._final_size[0]}x{self._final_size[1]}"
                         f"@{self._final_pos[0]},{self._final_pos[1]}")
                except Exception:
                    pass
            _log("info", "启动", "startup", "主窗口已显示（尺寸/位置/图标/补丁均已就位）")
        except Exception as exc:                          # noqa: BLE001
            _log("err", "启动", "startup", f"显示主窗口失败: {exc}")

    # ================= 托盘 + 热键 =================
    def _start_tray_and_hotkeys(self):
        # 已经在退出流程里就不要再建托盘/热键了（建了马上又要拆，还会多几条回调路径）
        if self._teardown_started:
            return
        labels = self._tray_labels()
        handlers = {
            "home": self.show_window,
            "search": self.on_tray_search,
            "ai": self.on_tray_ai,
            "exit": self.quit_app,
        }
        try:
            self.tray = tray.TrayIcon(icon_png_path=self._icon_path,
                                      labels=labels, on_select=handlers,
                                      tooltip=WINDOW_TITLE,
                                      # ⚠️ 主题/字体要显式传进去：托盘菜单是 Win32 自绘的，
                                      #    拿不到 QApplication 的主题和字体，只能由这边喂。
                                      settings_manager=self.settings_manager,
                                      font_family=self._tray_font_family())
            # 热键管理器复用托盘那条消息线程的窗口（WM_HOTKEY 必须投递到同一个线程队列）
            self.hotkeys = hotkey.GlobalHotkeyManager(
                hwnd_provider=(lambda: self.tray.hwnd if self.tray else 0),
                dispatcher=(lambda fn, timeout=3.0: self.tray.invoke(fn, timeout)
                            if self.tray else fn()))
            self.hotkeys.set_callbacks(on_activated=self._on_hotkey)
            # 托盘窗口收到 WM_HOTKEY 时转给我们
            self.tray.on_hotkey = lambda hotkey_id: self.hotkeys.handle_hotkey(hotkey_id)
            # ⚠️ 热键登记必须在托盘窗口创建**之后**、且**在同一条线程**上：
            #    通过 on_ready_native 在原生线程里直接注册，避免 1408（未注册）那个坑。
            self.tray.on_ready_native = lambda _tray: self.apply_hotkey_settings(notify=False)
            ok = self.tray.start()
            if ok:
                _log("info", "启动", "startup", "托盘图标已创建")
            else:
                _log("warn", "启动", "startup", "托盘图标创建失败（当前系统或会话不支持托盘）")
                self.apply_hotkey_settings(notify=False)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "启动", "startup", f"托盘初始化异常: {exc}")

        # 开机自启同步（原版 main_window.py:94-117 的"启动同步检查"）
        self._sync_autostart()

    def _tray_labels(self) -> dict:
        labels = {}
        for key, fallback in (("show_main_window", "Show Main Window"),
                              ("show_search_box", "Open Search Box"),
                              ("show_ai_search", "Open AI"),
                              ("exit", "Exit"),
                              ("hidden_to_tray", "Hidden to tray")):
            labels[key] = self._text("nav", key) or fallback
        return labels

    def _tray_font_family(self) -> str:
        """界面字体族（设置里的 ui_font_family）——原版托盘菜单就是用这个字体画的
        原版 `main_window.py:171` 调 `fonts.apply_font(settings["ui_font_family"])`
        把整个程序（含 QMenu）刷成该字体；自绘版必须拿到同一个族名才不会"菜单字体和
        界面字体不是一套"。取不到就交空串，由 traymenu 按默认候选表（微软雅黑→…）选。
        """
        try:
            if self.settings_manager:
                return str(self.settings_manager.settings.get("ui_font_family", "") or "")
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "外壳", "tray", f"读取界面字体设置失败（用默认字体）: {exc}")
        return ""

    def _text(self, module: str, key: str) -> str:
        """取一条文案（托盘菜单 / 快捷键提示用；module 与 language_manager 的模块键一致）
        ⚠️ v1.1.4 起语言文件按语言分目录（languages/zh_CN|zh_TW|en_US/<module>_language.json），
           不再是根目录下一个三语混合 json —— 不能再自己 open 旧路径，必须过 LanguageManager，
           否则读不到文件会静默返回空串（托盘菜单掉回硬编码英文、快捷键名显示成 key）。
        ⚠️ 这里保留"空串 = 没取到"的语义：调用方都用 `_text(...) or 英文兜底`，
           所以把 get_text 的兜底返回值（key 本身）也当成没取到。
        """
        try:
            manager = getattr(self, "language_manager", None)
            if manager is not None:
                text = str(manager.get_text(module, key) or "")
                return "" if text == key else text
        except Exception:
            pass
        return ""

    # ---------- 热键 ----------
    def apply_hotkey_settings(self, notify: bool = True):
        """按设置注册/注销全部全局热键（逐条注册：一个被占用不影响别的）
        返回 (是否全部成功, 第一条错误)。逻辑与原版 `MainWindow.apply_hotkey_settings` 一致：
        ⚠️ 老配置里 `Ctrl+Caps` 这种"拿 Caps Lock 做主键"的值必然注册失败（错误码 1409），
           认出来就换成默认值并落盘。
        """
        if self.hotkeys is None:
            return False, "热键管理器未就绪"
        manager = self.settings_manager
        enabled = bool(manager.settings.get("hotkey_enabled", True)) if manager else True
        if not enabled:
            self.hotkeys.unregister_all()
            _log("info", "快捷键", "hotkey", "全局快捷键已关闭")
            return True, None

        first_error = None
        status = {}
        for name, key, default, label_key in HOTKEYS:
            label = self._text("settings", label_key) or label_key
            sequence = str(manager.settings.get(key, default) or "").strip() if manager else default
            bad = hotkey.unusable_main_key(sequence)
            if bad:
                _log("err", "快捷键", "hotkey",
                     f"{label} 的快捷键 {sequence} 使用了系统保留键 {bad}"
                     f"（RegisterHotKey 会失败），已自动改为 {default}")
                sequence = default
                if manager:
                    manager.update_setting(key, default)
            if not sequence:
                self.hotkeys.unregister(name)
                status[name] = (False, self._text("settings", "hotkey_status_unset")
                                or "未设置")
                continue
            ok, err = self.hotkeys.register(name, sequence)
            if ok:
                _log("info", "快捷键", "hotkey",
                     f"{label} 已注册: {self.hotkeys.sequence(name)}")
                status[name] = (True, self.hotkeys.sequence(name))
            else:
                _log("err", "快捷键", "hotkey", f"{label} 注册失败: {err}")
                status[name] = (False, err)
                if first_error is None:
                    first_error = f"{label}：{err}"
        self._hotkey_status = status
        if first_error and notify:
            _log("warn", "快捷键", "hotkey", f"部分全局快捷键注册失败: {first_error}")
        return (first_error is None), first_error

    def hotkey_status(self) -> dict:
        """给前端/自检脚本看的热键状态（name → {ok, sequence/error}）"""
        raw = getattr(self, "_hotkey_status", {}) or {}
        return {name: {"ok": bool(ok), "text": text} for name, (ok, text) in raw.items()}

    def _on_hotkey(self, name: str):
        """热键触发（在原生消息线程里）：转给 GUI 线程执行"""

        def _run():
            try:
                if name == "search":
                    self.show_window()
                    self.push_event("hotkey", {"name": "search", "action": "focus_search"})
                elif name == "ai":
                    self.show_window()
                    self.push_event("hotkey", {"name": "ai", "action": "open_ai"})
            except Exception as exc:                      # noqa: BLE001
                _log("err", "快捷键", "hotkey", f"执行快捷键动作失败（{name}）: {exc}")

        threading.Thread(target=_run, name=f"ToolsGCP-hotkey-{name}", daemon=True).start()

    # ---------- 托盘动作 ----------
    def on_tray_search(self):
        self.show_window()
        self.push_event("tray", {"action": "focus_search"})

    def on_tray_ai(self):
        self.show_window()
        self.push_event("tray", {"action": "open_ai"})

    def show_tray_menu(self, x=None, y=None):
        """弹出**原生**托盘右键菜单（自绘圆角菜单，desktop/native/traymenu.py）
        ⚠️ 为什么菜单必须在后端画、而不是前端画一个 HTML 菜单：
           Windows 托盘菜单是系统级弹层 —— 它必须能**超出** pywebview 窗口边界，
           并且窗口失焦时也要保持最上层。HTML 做不到（webview 窗口一失焦，
           HTML 菜单就被裁掉或被别的窗口盖住）。所以只能由原生分层窗口来画。
        ⚠️⚠️ **绝对不能**在这里 `invoke(..., timeout=...)` 同步等它返回：
           `TrayMenu.popup()` 内部是**阻塞式模态消息泵**（和系统 TrackPopupMenu 一样，
           用户不选就一直在里面转消息）。早先写 `tray.invoke(_run, timeout=0.1)`，
           0.1 秒就超时返回、菜单虽然建了窗口但立刻被后续流程盖掉/清掉 ——
           表现就是"右键托盘完全没有任何 UI 出现"。
           正确做法：把弹菜单这件事排进托盘自己的原生消息线程，然后**立刻返回**。
        """
        tray = self.tray
        if tray is None or not getattr(tray, "available", False):
            _log("warn", "外壳", "tray", "托盘不可用，无法弹出菜单")
            return False
        point = None
        if x is not None and y is not None:
            try:
                point = (int(x), int(y))
            except Exception:
                point = None

        def _run():
            try:
                tray.show_menu(point)
            except Exception as exc:                      # noqa: BLE001
                _log("err", "外壳", "tray", f"弹出托盘菜单失败: {exc}")

        # 排到托盘原生线程里执行，然后马上返回（不等待模态循环结束）
        try:
            hwnd = getattr(tray, "hwnd", 0)
            if hwnd:
                with tray._jobs_lock:
                    tray._jobs.append(_run)
                win32.user32.PostMessageW(hwnd, tray._wake_msg, 0, 0)
            else:
                threading.Thread(target=_run, name="ToolsGCP-traymenu",
                                 daemon=True).start()
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "外壳", "tray", f"托盘菜单任务投递失败，已改为独立线程执行: {exc}")
            threading.Thread(target=_run, name="ToolsGCP-traymenu",
                             daemon=True).start()
        return True

    # ================= 后端 → 前端的**唯一**出口 =================
    def eval_js_safe(self, script: str) -> bool:
        """唯一允许调用 `window.evaluate_js` 的地方（所有前端推送都必须经过它）
        ========== 为什么要有这一层（WebView2 释放异常）==========
        典型的触发 traceback 是 `pywebview/platforms/edgechromium.py:152 evaluate_js` 里的
        `System.ObjectDisposedException: 无法访问已释放的对象。对象名:"WebView2"`。
        审计过整个 `desktop/` 与 `modules/`，`evaluate_js` 的调用点只有两处来源：
          ① **我们自己**的 `push_event()`（后台线程推事件）—— 由"三道闸"守住；
          ② **pywebview 自己**：`webview/util.py:264 js_bridge_call._call()` 在 js_api
             回调**返回之后**还要 `window.evaluate_js(...)` 把结果送还给 JS。
             所以在 js_api 回调里同步销毁窗口必然会踩到它（例如 `api.shell.quit()`
             → `quit_app()` → `window.destroy()`），而且这一条我们**拦不住**（不在我们代码里）。
             对策：退出类接口改成"先把返回值交回去，再异步退出"（见 `quit_app_async`）。
        闸门（任一关不过就静默丢弃，绝不抛）：
          · `_teardown_started` / `_quitting` / `_window_closed`：退出流程已开始；
          · `frame.is_window_alive(hwnd)`：原生窗口已经不在了；
          · 真调时再捕一次 ObjectDisposedException 之类的异常（最后一刻的竞态）——
            并且**只记一条**日志，避免退出瞬间刷出几十条同样的报错。
        """
        if self.window is None:
            return False
        if self._teardown_started or self._quitting or self._window_closed:
            return False
        hwnd = self.hwnd()
        if hwnd and not frame.is_window_alive(hwnd):
            return False
        try:
            self.window.evaluate_js(script)
            return True
        except Exception as exc:                          # noqa: BLE001
            self._note_js_failure(exc)
            return False

    def _note_js_failure(self, exc):
        """记录一次前端脚本执行失败（"WebView2 已释放"只记一条，避免刷屏）"""
        text = f"{type(exc).__name__}: {exc}"
        lowered = text.lower()
        disposed = ("objectdisposed" in lowered or "已释放" in text
                    or "disposed" in lowered or "webview2" in lowered)
        if disposed:
            if not self._js_disposed_logged:
                self._js_disposed_logged = True
                _log("info", "外壳", "event",
                     f"WebView2 已释放，后续前端推送已停止（{text}）")
            return
        now = time.time()
        if now - self._js_error_logged_at >= 5.0:         # 其它异常最多 5 秒一条
            self._js_error_logged_at = now
            _log("warn", "外壳", "event", f"前端脚本执行失败（本次推送已跳过）: {text}")

    def push_event(self, name: str, payload: dict):
        """后端 → 前端推送（原版 pyqtSignal 的等价物）
        ⚠️ `evaluate_js` 会阻塞等 JS 执行完；绝不能在 js_api 的工作线程里直接调它去等
           "另一个需要 js_api 的回调"（会互相等死）。所以这里只在独立线程里发，且只发
           不等待返回。
        ⚠️ 前端还没 ready（api 都还没注入）时直接丢弃：那些事件本来就是"界面联动"用的，
           早期丢几条没有副作用（比如 favorites-changed 在首屏之前没人监听）。
        ⚠️⚠️ **退出闸门**：真正的闸门现在统一在 `eval_js_safe()` 里（发起时 + 调用前
           各查一次 + 捕获 ObjectDisposedException）。这里只保留"发起时"的廉价预检，
           避免为一个注定要丢的事件起线程。
        """
        if self.window is None or self._teardown_started or self._quitting:
            return

        def _send():
            try:
                import json as _json
                script = ("window.ToolsGCP && window.ToolsGCP.emit("
                          f"{_json.dumps(name)}, {_json.dumps(payload, ensure_ascii=False)});")
            except Exception as exc:                      # noqa: BLE001
                _log("warn", "外壳", "event", f"推送事件 {name} 序列化失败: {exc}")
                return
            self.eval_js_safe(script)                     # ① 内部会再查一遍闸门

        threading.Thread(target=_send, name=f"ToolsGCP-event-{name}", daemon=True).start()

    def _push_event(self, name: str, payload: dict):
        """兼容旧名（hotkey / tray 的推送走的还是 push_event，这里只是别名）"""
        self.push_event(name, payload)

    # ================= 全屏（前端按钮 / F11 / 页面 keydown 都汇聚到这里） =================
    def toggle_fullscreen(self) -> dict:
        """切换全屏（**唯一实现**），返回诊断字典
        返回 `{"ok": bool, "fullscreen": bool, "via": str, "error": str, "state": dict}`；
        `ok=False` 表示"请求确实到了后端，但窗口没变成预期状态"（前端要据此提示，
        不能再静默无反应）。成功时同时 `push_event("window.fullscreen", {fullscreen})`，
        前端靠这个事件隐藏/恢复自己的标题栏。
        为什么在这里统一：F11 有三条到达路径 ——
          ① 前端 page keydown（Lead 那边）→ `api.window.toggle_fullscreen`；
          ② 原生 `AcceleratorKeyPressed`（frame.install_webview_accelerators）→ `_on_native_f11`；
          ③ 前端按钮点击 → `api.window.toggle_fullscreen`。
        三条最后都落到本方法，日志/事件/状态判断只写一份，不会各有各的行为。
        """
        if self.window is None or self._teardown_started or self._window_closed:
            return {"ok": False, "fullscreen": bool(getattr(self, "_fullscreen_state", False)),
                    "via": "none", "error": "窗口还没就绪或正在退出", "state": {}}
        hwnd = self.hwnd()
        if not hwnd:
            return {"ok": False, "fullscreen": bool(getattr(self, "_fullscreen_state", False)),
                    "via": "none", "error": "未取得窗口句柄", "state": {}}
        before = frame.fullscreen_diagnostics(hwnd)
        _log("info", "窗口", "fullscreen",
             f"收到全屏切换请求: 句柄={hwnd} 当前全屏={before.get('fullscreen')} "
             f"矩形={before.get('rect')} 显示器={before.get('monitor')} "
             f"最大化={before.get('maximized')} "
             f"样式=0x{int(before.get('style') or 0):08X} "
             f"无边框补丁={bool(self.frameless)}")
        via = "framepos"
        error = ""
        full = bool(getattr(self, "_fullscreen_state", False))
        try:
            if not getattr(self, "frameless", True):
                # 系统标题栏模式：交给 pywebview 原生（FormBorderStyle + WindowState），
                # frame.py 那套原生 SetWindowPos 是给"无边框补丁窗口"设计的。
                # ⚠️ pywebview 不回报状态（frame._state.fullscreen 不会变），所以这里只能
                #    按"翻转自己记的状态"来算，不能拿 frame.fullscreen_diagnostics 的结果。
                self.window.toggle_fullscreen()
                self._fullscreen_state = not bool(full)
                full = self._fullscreen_state
                via = "pywebview"
            else:
                target = not frame.is_fullscreen()
                frame.toggle_fullscreen(hwnd, self.window)
                full = bool(frame.is_fullscreen())
                self._fullscreen_state = full
                if full != target:
                    error = "全屏切换未生效（窗口几何没有变化，可能是 DPI/多屏或窗口状态异常）"
                via = ("pywebview-fallback" if frame._state.fullscreen_native
                       else "framepos")
        except Exception as exc:                          # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        state = frame.fullscreen_diagnostics(hwnd)
        ok = (not error) and (bool(full) == bool(self._fullscreen_state))
        level = "op" if ok else "err"
        _log(level, "窗口", "fullscreen",
             f"全屏切换完成: 成功={ok} 全屏={full} 路径={via} "
             f"矩形={state.get('rect')} 显示器={state.get('monitor')} "
             f"最大化={state.get('maximized')} {error}".strip())
        if ok:
            # 前端靠这个事件隐藏/恢复自绘标题栏（Lead 已监听 window.fullscreen）
            self.push_event("window.fullscreen",
                            {"fullscreen": full, "via": via})
        return {"ok": bool(ok), "fullscreen": full, "via": via,
                "error": error, "state": state}

    def _on_native_f11(self):
        """原生 F11（在 GUI 线程上触发）：切全屏 + 推事件
        ⚠️ 这里不能抛 —— 异常跨过 .NET 事件边界会直接带走进程。
        """
        try:
            self.toggle_fullscreen()
        except Exception as exc:                          # noqa: BLE001
            _log("err", "窗口", "fullscreen", f"原生 F11 处理失败: {exc}")

    def quit_app_async(self, delay: float = 0.25, force: bool = False):
        """**异步**退出：先把 js_api 的返回值交回去，再销毁窗口
        ⚠️⚠️ 这是 WebView2 释放异常的第二个根源（第一个是 push_event 竞态）：
            pywebview 的 `js_bridge_call` 在 js_api 回调返回之后，还要
            `window.evaluate_js(...)` 把结果送还给 JS（webview/util.py:264）。
            如果在回调里同步 `window.destroy()`，那一句 evaluate_js 就打在已经释放的
            WebView2 上 —— 这段代码在 pywebview 内部，我们闸不住。
            所以退出类接口一律"立即 return + 延迟一会儿再退"，把时间差留给那句回调。
        ⚠️ `force` 透传给 quit_app —— 更新包安装完的重启不该被"有下载任务"拦住。
        """
        def _run():
            try:
                time.sleep(max(0.0, float(delay)))
            except Exception:
                pass
            self.quit_app(force=force)

        threading.Thread(target=_run, name="ToolsGCP-quit", daemon=True).start()

    # ================= 窗口显示/隐藏 =================
    def show_window(self):
        """把窗口显示出来并抬到最前（托盘/热键/单实例激活都走这里）"""
        if self._teardown_started or self._window_closed:
            return
        try:
            hwnd = self.hwnd()
            # ⚠️「启动时最小化到托盘」那条路径下，窗口还停在 OFFSCREEN_X/Y（屏幕外）。
            #    直接 show() 会"在看不见的地方显示"= 用户以为双击托盘没反应。
            #    所以这里先把窗口搬回工作区正中（center_on_screen 内部的 resize/move
            #    自带 SWP_SHOWWINDOW，等于顺带显示），再 show + 置顶收口。
            if hwnd and not frame.is_on_screen(hwnd):
                try:
                    frame.center_on_screen(hwnd, self.window)
                except Exception:
                    pass
            if self.window is not None:
                self.window.show()
            hwnd = self.hwnd()
            if hwnd:
                frame.bring_to_front(hwnd)
                # 从屏幕外搬回来的那一拍再兜一次（show() 之后才保证 DWM 已接管）
                if not frame.is_on_screen(hwnd):
                    frame.force_center_on_screen(hwnd, self.window)
            # 托盘呼出时要清掉"启动隐藏"标记：之后关闭按钮等行为恢复正常
            self._startup_hidden = False
        except Exception as exc:                          # noqa: BLE001
            _log("err", "窗口", "window", f"呼出主窗口失败: {exc}")

    def hide_to_tray(self):
        # ⚠️ 这里只挡"窗口已经销毁"：close_mode=隐藏到托盘时也会走本方法，而那条路径
        #    **不**置 `_teardown_started`（见 _on_closing），否则窗口会关不掉也藏不起来。
        if self._window_closed:
            return
        try:
            if self.window is not None:
                self.window.hide()
            if self.tray is not None and not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.notify(WINDOW_TITLE,
                                 self._text("nav", "hidden_to_tray") or
                                 "程序已隐藏到托盘")
            _log("info", "窗口", "window", "关闭窗口：隐藏到托盘")
        except Exception as exc:                          # noqa: BLE001
            _log("err", "窗口", "window", f"隐藏到托盘失败: {exc}")

    # ================= 退出闸门 / 后台线程收尾 =================
    def _stop_background(self, reason: str = "", join_tray: bool = True):
        """先停掉"会回调前端 / 会碰窗口"的后台东西，再让窗口走销毁流程
        为什么必须先停（对应 bug A）：
            · `_ready_watchdog`（首屏就绪超时定时器）会调 `_try_show()`；
            · 全局热键回调和托盘回调分别在原生线程/独立线程里跑，会调 `show_window()`
              或 `push_event()`；
            · 托盘线程还会弹气泡、弹菜单。
            这些东西只要有一条在"WebView2 已释放、窗口已销毁"之后跑到，就会产生
            `evaluate_js` 那个 ObjectDisposedException，或者把窗口又 show 出来。
        幂等：重复调用安全（`_teardown_started` + 各组件自己的 stop 都是幂等的）。
        日志口径：拆成"开始（带中文原因）"+"逐项结果"两条 —— 只记一行开始
        既不能确认每一步是否真的停掉了，`shutdown` 这类内部代号也不该以英文混进中文日志；
        失败项写明异常。
        """
        reason_key = {"shutdown": "程序收尾"}.get(str(reason or ""), str(reason or ""))
        with self._stop_lock:
            first = not self._teardown_started
            self._teardown_started = True        # ⚠️ 第一个置位：之后所有前端推送都会被挡
            if first:
                _log("info", "启动", "startup",
                     f"退出流程开始（原因：{reason_key or '未说明'}）：先停止会回调前端的后台组件")
        stopped = []
        failed = []
        # ① 首屏就绪超时定时器（会调 _try_show）
        if self._ready_watchdog is not None:
            try:
                self._ready_watchdog.cancel()
                self._ready_watchdog = None
                stopped.append("首屏就绪定时器")
            except Exception as exc:                      # noqa: BLE001
                failed.append(f"首屏就绪定时器（{exc}）")
        # ② 全局热键（回调会 show_window / push_event）
        if self.hotkeys is not None:
            try:
                self.hotkeys.unregister_all()
                stopped.append("全局热键")
            except Exception as exc:                      # noqa: BLE001
                failed.append(f"全局热键（{exc}）")
        # ③ 托盘线程（回调会 show_window / push_event / 弹菜单）
        if self.tray is not None:
            try:
                self.tray.stop(timeout=2.0 if join_tray else 0.0)
                stopped.append("托盘线程")
            except Exception as exc:                      # noqa: BLE001
                failed.append(f"托盘线程（{exc}）")
        if first:
            detail = "已停止：" + "、".join(stopped) if stopped else "没有需要停止的后台组件"
            if failed:
                detail += "；失败：" + "、".join(failed)
            _log("warn" if failed else "info", "启动", "startup", "退出流程 · " + detail)

    # ================= 关闭 =================
    def _on_closing(self):
        """pywebview 的 closing 事件
        ⚠️⚠️ 返回值的语义**和直觉相反**，这是 pywebview 的一个坑：
            `Event.set()` 收集所有处理器的返回值，只要**有任意一个返回 `False`**，
            就认为"要取消"（`webview/event.py:60-63` 的 `return len(false_values) != 0`），
            而 `winforms.py:400-403` 拿到 True 就 `args.Cancel = True`。
            所以：
                · 允许关闭 → 必须返回 **True**（或任何不是 False 的值）
                · 取消关闭 → 返回 **False**
            实测教训：一开始按"返回 True = 已处理"来写，结果"彻底退出"被反着取消、
            窗口关不掉、进程也退不出去（日志停在"关闭窗口：彻底退出"就没了下文）。
        对应原版 `MainWindow.closeEvent`：
            close_mode == "隐藏到托盘中" → hide() + 气泡 + event.ignore()（= 取消关闭）
            否则 → 真退出（= 允许关闭）
        """
        if self._quitting:
            return True
        mode = "彻底退出"
        try:
            if self.settings_manager:
                mode = str(self.settings_manager.settings.get("close_mode", "彻底退出"))
        except Exception:
            pass
        if mode == "隐藏到托盘中":
            # ⚠️ hide 必须异步：在 closing 回调里直接 hide() 会和 WinForms 的关闭流程打架
            # ⚠️ 这条路径**不能**置 _teardown_started：程序只是藏起来，前端还要活着
            threading.Thread(target=self.hide_to_tray, name="ToolsGCP-hide",
                             daemon=True).start()
            return False                                   # False = 取消本次关闭
        # ⚠️ 还有下载任务在跑时，先问一句"要不要打断"（原生确认框）。
        #    位置很关键：**在"隐藏到托盘"分支之后** —— 藏到托盘不是退出，
        #    不该弹框打断用户（程序还在后台继续下载）。
        if not self._confirm_exit_with_downloads():
            _log("info", "窗口", "window", "关闭窗口：用户取消退出（有下载任务在跑）")
            return False                                   # False = 取消本次关闭
        _log("info", "窗口", "window", "关闭窗口：彻底退出")
        self._quitting = True
        self._stopping = True
        # ⚠️⚠️ 在这里就把闸门关上 + 停掉会回调前端的后台东西（不 join 托盘，避免卡住
        #     GUI 线程的关闭流程）。之后 Form 才会真的被销毁；这中间的空档里，任何
        #     已经在跑的推送线程都会在 _send() 里被拦下，不会再碰已释放的 WebView2。
        self._stop_background("窗口关闭（彻底退出）", join_tray=False)
        return True

    def request_close_async(self, delay: float = 0.35, force: bool = False):
        """**异步**请求关闭窗口（标题栏 × 走这条）
        ⚠️⚠️ 同步版 `request_close()` 只能给"非 js_api 上下文"用（托盘/热键/自检脚本）。
            js_api 里（`api.window.close()`）必须用这个：pywebview 的 `js_bridge_call`
            在回调返回后还要 `evaluate_js` 把结果送还 JS（webview/util.py:264），
            而 `WM_CLOSE` 一进去窗口就开始销毁，那句 evaluate_js 必然抛
            `System.ObjectDisposedException ... "WebView2"` —— 用户每点一次 × 都可能刷一段。
            留 0.35s 给"返回值送达 + 前端那句 toast 起个头"。
        ⚠️ `force=True` = 前端已经问过用户了 —— 先置 `_exit_confirmed`，
           别在 `_on_closing` 里又弹一次原生确认框（弹两次太烦人）。
        """
        if force:
            try:
                self.set_exit_confirmed()
            except Exception:
                pass

        def _run():
            try:
                time.sleep(max(0.0, float(delay)))
            except Exception:
                pass
            self.request_close()

        threading.Thread(target=_run, name="ToolsGCP-request-close",
                         daemon=True).start()

    def request_close(self):
        """标题栏 × ：发送原生 WM_CLOSE，走和系统关闭完全一致的路径
        ⚠️ 不要直接 `window.destroy()`：那样会绕过 pywebview 的 closing 事件，
           也会跳过 Win11 的关闭过渡动画（窗口"啪"一下消失）。
        """
        try:
            hwnd = self.hwnd()
            if hwnd and frame.close_window(hwnd):
                return
        except Exception:
            pass
        try:
            if self.window is not None:
                self.window.destroy()
        except Exception:
            self.quit_app()

    # ================= 退出闸门（有下载任务时先确认）=================
    def set_exit_confirmed(self):
        """前端已经问过用户并得到仍然退出的确认 —— 后端别再弹原生框
        ⚠️ 前端（下载页那个退出确认弹窗）问过一次之后会调这个；
           不置这个标记的话，点关闭会**弹两次**确认框（一次前端的，一次原生的）。
        """
        self._exit_confirmed = True
        return True

    def _download_active_count(self) -> int:
        """当前正在执行的下载任务数（downloading + paused）；后端不可用时返回 0
        ⚠️ 取不到就当 0（= 没有下载任务）：退出流程不能因为下载域异常而卡死。
        """
        try:
            api = self.api
            domain = getattr(api, "downloader", None)
            if domain is None:
                return 0
            result = domain.active_count()
            return int((result or {}).get("count") or 0)
        except Exception:
            return 0

    def _exit_prompt_text(self, count: int):
        """退出确认框的文案（标题, 正文）；按当前界面语言给中文或英文"""
        lang = ""
        try:
            if self.settings_manager:
                lang = str(self.settings_manager.settings.get("language", "") or "")
        except Exception:
            lang = ""
        # ⚠️ 只有明确的简体中文才用中文文案；其余（英文/繁體/跟随系统）走英文兜底，
        #    免得弹出一堆用户看不懂的繁体字。
        if "简体中文" in lang or "zh_CN" in lang:
            return ("ToolsGCP",
                    f"还有 {count} 个下载任务正在执行。\n"
                    "现在退出会中断这些下载，确定要退出吗？")
        return ("ToolsGCP",
                f"{count} download task(s) are still running.\n"
                "Quitting now will interrupt them. Quit anyway?")

    def _confirm_exit_with_downloads(self) -> bool:
        """有下载任务在跑时弹**原生**确认框；返回 True = 允许退出
        ⚠️ 为什么用原生框而不是前端的 HTML 弹窗：
            退出确认往往发生在前端正在销毁的时刻，走 WebView 弹窗容易和
            `evaluate_js` 撞上（AGENTS 第 8 条）。原生 MessageBox 不碰 WebView2。
        ⚠️ 默认焦点放在否（MB_DEFBUTTON2）：误按回车不会把下载打断。
        """
        if self._exit_confirmed:
            return True
        count = self._download_active_count()
        if count <= 0:
            return True
        title, body = self._exit_prompt_text(count)
        try:
            hwnd = self.hwnd()
            # ⚠️ 确认框是**模态**的（MessageBox 自己起消息循环），
            #    如果主窗口不在前台，框会藏在后面 —— 先把主窗口抬到前面再弹。
            if hwnd:
                try:
                    frame.bring_to_front(hwnd)
                except Exception:
                    pass
            ret = win32.message_box(hwnd, body, title,
                                    win32.MB_YESNO | win32.MB_ICONWARNING
                                    | win32.MB_DEFBUTTON2)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "启动", "startup", f"退出确认框弹出失败（按同意处理）: {exc}")
            return True
        if ret == win32.IDYES:
            self._exit_confirmed = True
            return True
        return False

    def quit_app(self, force: bool = False):
        """真正退出（托盘菜单"退出" / 前端 api.shell.quit）
        ⚠️ 顺序：**先关闸门 + 停后台线程**，再销毁窗口。反过来的话，销毁窗口的瞬间
           托盘/热键/首屏就绪定时器还能再往前端推一次（就是那个 WebView2 ObjectDisposedException）。
        ⚠️ `force=True` 表示"用户已经确认过了"（更新包安装完的重启走这条路），
           跳过下载确认框 —— 不然更新重启会被"还有下载任务在跑"拦住。
        """
        if self._quitting or self._teardown_started:
            return
        if not force and not self._confirm_exit_with_downloads():
            _log("info", "启动", "startup", "用户取消退出：有下载任务正在执行")
            return
        _log("info", "启动", "startup", "用户退出程序")
        self._quitting = True
        self._stopping = True
        # ① 关闭推送闸门 + 停止首屏就绪定时器 / 热键 / 托盘（托盘 join 等它真的退出；它是独立线程，
        #    不在 GUI 线程上，这里等 2s 不会影响窗口销毁）
        self._stop_background("用户退出", join_tray=True)
        # ② 再销毁窗口
        try:
            if self.window is not None:
                self.window.destroy()
        except Exception:
            pass

    def restart(self, open_settings: bool = False):
        """重启程序（原版 `restart_program`：起一个新进程后自己退出）
        ⚠️ 起完新进程后用 `quit_app_async` 延迟退出：本方法会被 `api.shell.restart()`
           从 js_api 工作线程调进来，同步 destroy 会让 pywebview 在回调返回时对着已释放的
           WebView2 调 evaluate_js（见 quit_app_async 的说明）。
        """
        import subprocess
        args = []
        if getattr(sys, "frozen", False):
            args.append(sys.executable)
        else:
            args = [sys.executable, os.path.abspath(sys.argv[0])]
        if open_settings:
            args.append("--open-settings")
        # ⚠️ 先问再起新进程：反过来的话（新进程已经起来了，用户才在确认框里点"否"），
        #    旧实例没退、新实例又起来了 —— 两个实例在跑，抢同一个数据目录。
        if not self._confirm_exit_with_downloads():
            _log("info", "启动", "startup", "用户取消重启：有下载任务正在执行")
            return
        _log("info", "启动", "startup", f"重启程序: {' '.join(args)}")
        subprocess.Popen(args)
        # ⚠️ force=True：新进程**已经**起来了，这时的"还有下载任务在跑"确认框要是被取消，
        #    就会留下两个实例在跑（旧的没退、新的已经起来了）。所以这里不能拦。
        self.quit_app_async(force=True)

    def _shutdown(self):
        """webview.start() 返回后的收尾（顺序：闸门/热键/托盘 → **启动画面** → 日志）
        ⚠️ 第一步就是 `_stop_background`（幂等）：到这里的路径可能是"窗口被销毁后
           webview.start() 返回"，也可能是"点托盘退出"。无论哪条，先把 `_teardown_started`
           置上、把会调 `evaluate_js` / 会 show 窗口的东西停干净。
        ⚠️⚠️ **启动画面的 stop() 必须在这里调，而且必须 join**，否则会出现：
            `QObject：killTimer: Timers cannot be stopped from another thread`
            `QObject：~QObject: Timers cannot be stopped from another thread`
            成因：用户在**启动画面还在播**的时候点托盘退出（托盘比启动画面先建好），
                  `quit_app()` 会让 `webview.start()` 立刻返回、`_shutdown()` 开始跑，
                  而此时 Qt 线程还停在 `exec_()` 里。如果这里不等它，进程会带着
                  **活着的 QApplication / QWidget** 直接走到解释器退出 ——
                  由主线程去析构它们，Qt 就在错误的线程里执行 killTimer/析构并打印警告。
                  （退出码仍然是 0，所以只看退出码排查不到这句话。）
            `stop()` 置位退出标志 → Qt 线程里那个 100ms watcher 调 `app.quit()` →
            `exec_()` 正常返回 → 清理在 **Qt 线程**上跑完 → 这里再 join 等它结束。
        """
        # ① 推送闸门 + 首屏就绪定时器 + 热键 + 托盘（全部幂等；托盘已在 quit_app 里停过）
        self._stop_background("shutdown", join_tray=True)
        # ② 启动画面（放在托盘之后：托盘退出可能触发回调；日志关闭之前：Qt 线程还会写日志）
        try:
            if self.splash is not None:
                self.splash.stop()
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "启动", "startup", f"停止启动画面失败: {exc}")
        # ③ 收尾完成标记（放在 log.close() 之前：这是正常退出的最后一条日志）
        _log("info", "启动", "startup",
             "程序收尾完成：后台组件、启动画面均已停止，进程即将退出")
        try:
            from pymodels.utils.logger import log
            log.close()
        except Exception:
            pass

    # ================= 杂项 =================
    def current_language(self) -> str:
        """当前界面语言（跟随系统时按原版规则判定）"""
        try:
            saved = str(self.settings_manager.settings.get("language", "跟随系统")) \
                if self.settings_manager else "跟随系统"
        except Exception:
            saved = "跟随系统"
        if saved != "跟随系统":
            return saved
        try:
            import locale
            name = locale.getlocale()[0]
            if name and ("Chinese (Simplified)" in name or "zh_CN" in name):
                return "简体中文"
            if name and ("Chinese (Traditional)" in name or "zh_TW" in name
                         or "zh_HK" in name):
                return "繁體中文"
            return "English"
        except Exception:
            return "简体中文"

    def _is_dark(self) -> bool:
        try:
            theme = str(self.settings_manager.settings.get("theme", "跟随系统")) \
                if self.settings_manager else "跟随系统"
            if theme == "深色主题":
                return True
            if theme == "浅色主题":
                return False
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
        except Exception:
            return True

    def _sync_autostart(self):
        """启动同步：设置里"开了自启"但注册表没生效时要补上（原版 startup 同步检查）"""
        try:
            if not self.settings_manager:
                return
            wanted = bool(self.settings_manager.settings.get("startup_with_windows", False))
            actual = autostart.is_enabled()
            _log("info", "启动", "startup",
                 f"启动同步检查: 开机自启={'开' if wanted else '关'}，注册表={'开' if actual else '关'}")
            if wanted and not actual:
                ok, err = autostart.set_enabled(True)
                _log("info" if ok else "err", "启动", "startup",
                     "开机自启同步完成" if ok else f"开机自启同步失败: {err}")
            elif wanted and actual:
                # 命令格式可能变过（python.exe → pythonw.exe），以当前配置为准重写一次
                autostart.set_enabled(True)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "系统", "system", f"自动同步开机自启动异常: {exc}")
