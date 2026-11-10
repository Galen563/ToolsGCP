"""检查更新：下载更新包 + 重启替换（`api.update.*`）
========== 一、为什么要有这个域 ==========
前端 `app.js` 的 `checkUpdate()` 拿到新版本后调的是 `bridge.tryCall('downloader.start', …)`，
但后端**从来没有 downloader 域** —— tryCall 拿到 `null` 只能降级去开浏览器。
本域把"下载 → 提示 → 重启并替换"这条链路补齐（下载到 temp\\ToolsGCP\\update，重启后替换下载好后弹窗问是否立即重启更新，可选稍后或立即重启）。
========== 二、接口契约（前端 Lead 按这个联调，名字/参数/返回值不要改）==========
`update.info()`
    → `{ok, version, frozen:bool, exe:str, temp_dir:str, platform:str,
        pid:int, downloading:bool, last:{path,filename,size}|None}`
`update.download(url, filename="ToolsGCP.exe", expected_size=0)`
    · **立即返回**（下载在后台线程里跑，绝不阻塞 js_api）：
        `{ok:true, started:true, path:"<temp>/ToolsGCP/update/ToolsGCP.exe", filename}`
        `{ok:false, error:"已有下载在进行", busy:true}`  ← 同一时间只允许一个下载
    · 后台事件（`shell.push_event`，前端用 `window.ToolsGCP.emit` 的同名监听收）：
        `update.progress` `{received, total, percent}`   percent 是 0~100 的 float（total=0 时 null）
        `update.done`     `{ok:true, path, size, filename}`
        `update.error`    `{error}`（用户取消时带 `canceled:true`）
    · `expected_size > 0` 时按它校验，不匹配算失败并删掉半成品；`=0` 时用服务器
      `Content-Length` 校验（拿不到就不校验，但空文件一律算失败）。
`update.cancel()` → `{ok, canceled:bool, running:bool}`
`update.install_and_restart()`
    · 源码运行（非 frozen）→ `{ok:false, error:"当前是源码运行，无法自动替换；请在打包版使用，或手动更新"}`
    · 成功 → `{ok:true, restarting:true, script:"…/apply_update.cmd", app:"…\\ToolsGCP.exe", update_file, size}`
      并在 0.9s 后自动退出（前端收到返回值先把 toast 弹出来，再安静退出）。
    · 失败 → `{ok:false, error:"…"}`
`update.open_folder()` → `{ok, path}`（打开 `<temp>/ToolsGCP/update`）
========== 三、替换怎么做（apply_update.cmd）==========
Windows 不允许程序替换正在运行的自己，所以写一个**纯 ASCII** 的 .cmd（关键：脚本里
一个中文都不写 —— encoding="ascii" 会直接炸，且 cmd 按系统 OEM 代码页读 .cmd，
中文在别的机器上会变乱码），路径全部通过命令行参数 `%~1/%~2/%~3` 传进去。
拉起方式：`_launch_hidden(_cmd_c_line([脚本, 当前exe, 更新包, PID]))`
（⚠️ 两步都是修 bug：① `_cmd_c_line` 用"整串外面再套一对引号"的形态绕开
   cmd 剥最外层引号导致带空格路径被截断；② **只给 CREATE_NO_WINDOW +
   STARTUPINFO(SW_HIDE)**，旧代码把它和互斥的 DETACHED_PROCESS 一起 or，
   等于未定义行为 → 黑窗口照样弹出来）。
    ① 用"对目标 exe 改名试探"等旧进程**真正松手**（改名成功=解锁；正在运行的
      exe 改名必失败）。⚠️ 不能像旧版那样拿"删得掉更新包"当判据 —— 运行中的
      程序根本没打开那个文件，第一次删就成功 → 后面覆盖必然失败。
    ② 备份原 exe 为 `<exe>.bak`，`copy /b` 覆盖 + **按字节数校验**（重试 20 次）。
    ③ 校验失败 → 用 .bak 回滚并重新启动旧版（不让用户"程序没了"）。
    ④ 成功 → 启动新 exe、删掉 .bak 与更新包、最后删掉自己。
    任何提前退出的路都先把探测改名的文件**改回原名**，再重启。
⚠️ 安全边界（用户数据一律不碰）：
    · 只在 `sys.frozen` 为真、且 `sys.executable` 存在时允许替换；
    · 更新包必须落在 `<temp>/ToolsGCP/update/` **里面**、非空
      （`_resolve_update_file` 会做规范化 + 前缀校验，防止"被指到用户数据目录"）；
    · 只动 `sys.executable` 这一个文件；`.bak` 只是它旁边的副本。
⚠️ 本模块**不 import PyQt5**、不创建窗口，所有涉及前端的推送都走 `shell.push_event`
   （那条路自带退出闸门，见 shell.eval_js_safe）。
"""

import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

from pymodels.constants import APP_NAME, APP_VERSION

from . import _fail, _log, _ok

# 下载/安装都用这个目录：<系统临时目录>/ToolsGCP/update
UPDATE_DIR_PARTS = ("ToolsGCP", "update")
DEFAULT_FILENAME = "ToolsGCP.exe"
APPLY_SCRIPT_NAME = "apply_update.cmd"

CHUNK_SIZE = 256 * 1024          # 分块下载：256 KB（进度事件也就按这个粒度走）
DOWNLOAD_TIMEOUT_S = 30.0        # 单次网络操作超时
PROGRESS_INTERVAL_S = 0.2        # 进度推送节流（push_event 每次起一条线程，别太密）
QUIT_DELAY_S = 0.9               # install_and_restart 返回后多久才真正退出（≥600ms 让 toast 出来）
# 更新包下载的默认重试次数：和下载主通道同一口径（设置项 `download_retry_count`）
DEFAULT_UPDATE_RETRY = 5

# apply_update.cmd 的正文
# ⚠️⚠️ **必须纯 ASCII**：_write_apply_script 用 encoding="ascii" 写盘，
#    混进中文会直接 UnicodeEncodeError（连更新器都起不来）；而且 cmd 是按
#    系统 OEM 代码页读 .cmd 的，中文注释在别的机器上会变成乱码甚至改坏命令行。
#    → 解释全部写在下面的 Python 注释里，脚本内只留英文 rem。
#
# ========== 这套脚本要绕开的四个真实的坑（都是踩出来的） ==========
# ① 【怎么知道旧进程已经松手】
#    原来用 `tasklist` 查 PID：onefile/子进程场景下"锁着 exe 的进程"未必等于
#    传进来的 APPPID；而且退出确认框、托盘线程 join 会让进程晚于窗口消失。
#    → 改成对**目标 exe 做改名试探**：正在运行的 exe 被系统锁定、改名必然失败，
#      改名成功就是真解锁了 —— 这才是唯一可靠的判据。
#    ⚠️ 改名成功后文件已经不是原名了，**必须用 `%TDIR%%PROBE%` 改回 `%TNAME%`** ——
#      拿 `%TARGET%` 去改回等于改一个不存在的路径，会把用户的 exe 留在
#      tg_updater_probe.tmp 这个名字上（程序直接"消失"）。这是最容易写错的地方。
# ② 【为什么不能用"删得掉更新包"当判据】
#    更新包在 %TEMP%\ToolsGCP\update 里，正在运行的程序根本没打开它 →
#    第一次 del 就成功 → 脚本以为进程退了继续往下走 → 覆盖目标必然失败。
#    这正是"下载好了但没替换成功"的直接原因。
# ③ 【覆盖后要校验大小】
#    内置 copy 覆盖"自己正在运行的文件"在个别系统上会静默留下旧文件。
#    → 先 robocopy（自带重试与校验），再退回 copy，最后**比对字节数**：
#      目标大小 == 更新包大小才算成功，否则回滚成旧版并重启旧版。
# ④ 【启动新版的引号语义】
#    `start` 会把**第一个带引号的参数当成窗口标题** → 那个 `""` 是故意的占位。
#    再补一条 `explorer <exe>`（走 ShellExecute）兜底，两条路都没起来才算失败。
APPLY_SCRIPT_LINES = (
    "@echo off",
    "setlocal",
    'set "TARGET=%~1"',
    'set "SOURCE=%~2"',
    'set "APPPID=%~3"',
    'set "TDIR=%~dp1"',
    'set "TNAME=%~nx1"',
    "set PROBE=tg_updater_probe.tmp",
    'if "%TARGET%"=="" goto giveup',
    'if not exist "%TARGET%" goto giveup',
    'if not exist "%SOURCE%" goto giveup',
    "rem ---- 1) wait until the old process releases the target exe ----",
    "set COUNT=0",
    ":probe",
    'ren "%TARGET%" "%PROBE%" >nul 2>&1',
    "rem decide by file existence, not ERRORLEVEL: a failed `ren` inside cmd does",
    "rem not reliably set ERRORLEVEL, but the probe file only appears on success.",
    'if exist "%TDIR%%PROBE%" goto got_lock',
    "set /a COUNT=%COUNT%+1",
    "if %COUNT% GEQ 300 goto giveup",
    "ping -n 2 127.0.0.1 >nul",
    "goto probe",
    ":got_lock",
    'ren "%TDIR%%PROBE%" "%TNAME%" >nul 2>&1',
    'if not exist "%TARGET%" move /y "%TDIR%%PROBE%" "%TARGET%" >nul 2>&1',
    "goto replace",
    "rem ---- 2) backup + overwrite ----",
    ":replace",
    'if exist "%TARGET%.bak" del /f /q "%TARGET%.bak" >nul 2>&1',
    'copy /b /y "%TARGET%" "%TARGET%.bak" >nul 2>&1',
    "set TRY=0",
    ":copy",
    'copy /b /y "%SOURCE%" "%TARGET%" >nul 2>&1',
    "goto verify",
    ":verify",
    "set SSIZE=0",
    "set TSIZE=0",
    'for %%F in ("%SOURCE%") do set SSIZE=%%~zF',
    'for %%F in ("%TARGET%") do set TSIZE=%%~zF',
    "if %SSIZE%==%TSIZE% goto copied",
    "set /a TRY=%TRY%+1",
    "if %TRY% GEQ 20 goto rollback",
    "ping -n 2 127.0.0.1 >nul",
    "goto copy",
    "rem ---- 3) ok: drop intermediates, relaunch the new exe ----",
    ":copied",
    'del /f /q "%TARGET%.bak" >nul 2>&1',
    'del /f /q "%SOURCE%" >nul 2>&1',
    "rem start only - no explorer fallback (see Python comment above)",
    'start "" "%TARGET%"',
    "goto done",
    "rem ---- 4) failed: roll back and relaunch the OLD exe ----",
    ":rollback",
    'if exist "%TARGET%.bak" copy /b /y "%TARGET%.bak" "%TARGET%" >nul 2>&1',
    'if exist "%TARGET%.bak" del /f /q "%TARGET%.bak" >nul 2>&1',
    ":giveup",
    "rem undo the probe rename on every early-exit path",
    'if exist "%TDIR%%PROBE%" ren "%TDIR%%PROBE%" "%TNAME%" >nul 2>&1',
    'if exist "%TARGET%" start "" "%TARGET%"',
    ":done",
    '(goto) 2>nul & del /f /q "%~f0"',
)


# ======================================================================
# 隐藏更新器控制台窗口（"关掉程序后弹出一个黑色 cmd 窗口"的根治）
# ======================================================================
def _hidden_console_flags() -> int:
    """拉起 cmd.exe 时用的创建标志：**只用 CREATE_NO_WINDOW**
    ⚠️⚠️ 旧代码把 `DETACHED_PROCESS(0x8) | CREATE_NO_WINDOW(0x08000000) |
       CREATE_NEW_PROCESS_GROUP` 三个一起 or 传进去 —— 前两个在 MSDN 里是
       **互斥**的（一个说"给我一个新的隐藏控制台"，一个说"我根本不attach控制台"），
       同时给 = 未定义行为，Windows 常常把 CREATE_NO_WINDOW 忽略掉 →
       子进程自己分配一个**可见**控制台 → 用户看到的"更新时弹出 cmd 黑窗口"。
       另外 cmd.exe 是**控制台子系统**程序，从一个 --windowed 的 GUI 进程里拉它，
       系统本来就会给它新建一个控制台窗口，所以必须显式压掉。
    """
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) or 0)
    if not flags:
        # 极老的 Python 没有这个常量 → 退回"新控制台 + STARTUPINFO 里 SW_HIDE"
        flags = int(getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10) or 0)
    return flags


def _hidden_startup_info():
    """STARTUPINFO：WANTS_GETTIME 之外只多一件事 —— **别显示窗口**
    ⚠️ 与 CREATE_NO_WINDOW 是"双保险"：不同 Windows 版本对其中一个标志的
       处理略有差异，两个都给最稳；STARTF_USESHOWWINDOW 本身不带其它副作用。
    """
    if sys.platform != "win32":
        return None
    try:
        info = subprocess.STARTUPINFO()
        info.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x1)
        info.wShowWindow = 0                # SW_HIDE
        return info
    except Exception:                       # noqa: BLE001 - 拿不到就算了
        return None


def _cmd_c_line(argv: list) -> str:
    """拼一条 **cmd /c 能正确解析** 的命令行（整串再套一层引号）

    ⚠️⚠️ 这就是"下载好了但没替换、也没重启、还弹出一个 cmd 窗口"的真根因：
       旧代码用列表形式 `Popen(["cmd","/c",脚本,目标,更新包,PID])`，
       subprocess 会把它拼成 `cmd /c "…apply_update.cmd" "…ToolsGCP.exe" …` ——
       而 cmd 对 `/c` 后面**以引号开头**的参数有条老规则：**剥掉最外面一对引号**，
       于是脚本路径上的引号没了 → 路径里的空格（`v1.1.4 - 12`、`Program Files`…）
       把命令截断 → cmd 直接报
           'C:\\…\\v1.1.4' is not recognized as an internal or external command
       → **更新脚本根本没跑**（没替换、没重启），而那句报错打在控制台上
         就是用户看到的"cmd 窗口弹出来"。
       实测（_tmp_cmdq2 那组对照）：
           list 形式      rc=1  ← 生产环境就是这个
           双层引号形式   rc=0  ← 参数解析正确
       官方写法就是"整串外面再套一对引号"，而且**脚本路径自己不要再包引号** ——
    实测可用形态：`cmd /c ""<脚本路径>" "<参数1>" "<参数2>"`
    （开头那对空引号吃掉 cmd "剥最外层引号" 的规则，脚本路径靠它继续带空格）。
    ⚠️ 也试过"脚本路径再额外带一层引号"的写法 → rc=1、完全没输出：
      那种三引号连写会让 cmd 把命令名解析成空串。所以照抄上面这个已验证的形态。
    """
    parts = [str(a) for a in (argv or [])]
    if not parts:
        return ""
    line = 'cmd /c ""' + parts[0]
    for one in parts[1:]:
        line += '" "' + one
    return line + '"'


def _launch_hidden(command, cwd: str = "") -> bool:
    """以"绝对不弹窗口"的方式拉起进程；`command` 可以是字符串或参数列表
    ⚠️ 传字符串时**必须**是 `_cmd_c_quoted`/`_cmd_c_line` 生成的那种（带外层引号），
       否则会踩上面那个 cmd 解析坑。
    """
    try:
        argv = command if isinstance(command, str) else list(command)
        subprocess.Popen(argv, cwd=cwd or None,
                         creationflags=_hidden_console_flags(),
                         startupinfo=_hidden_startup_info(),
                         close_fds=True)
        return True
    except Exception as exc:                # noqa: BLE001
        _log("err", "更新", "update", f"启动更新脚本失败: {exc}")
        return False


# ======================================================================
# 路径与小工具
# ======================================================================
def _temp_dir() -> str:
    """系统临时目录（Windows 优先 GetTempPathW，其它平台退回 tempfile）
    ⚠️ 没有直接复用 `pymodels.core.self_update.temp_dir`：那是旧 PyQt 版自更新器的
       命名规则（`%TEMP%\\ToolsGCP_new.exe` + `--update --pid/--target` 参数重启自己），
       和本版"temp\\ToolsGCP\\update\\ + apply_update.cmd"是两套机制。混用会在用户机器上
       留下两套临时文件，也会让"到底哪个在替换我"变得不可查。
    """
    if sys.platform == "win32":
        try:
            import ctypes
            size = 32768
            buffer = ctypes.create_unicode_buffer(size)
            length = ctypes.windll.kernel32.GetTempPathW(size, buffer)
            path = buffer.value if length else ""
            if path and os.path.isdir(path):
                return path
        except Exception:
            pass
    try:
        return tempfile.gettempdir()
    except Exception:
        return os.environ.get("TEMP") or os.environ.get("TMP") or "."


def update_dir() -> str:
    """更新包目录：`<临时目录>/ToolsGCP/update`（不存在不创建）"""
    return os.path.join(_temp_dir(), *UPDATE_DIR_PARTS)


def safe_filename(name: str) -> str:
    """把前端给的下载文件名清成安全的**单层文件名**（不允许路径穿越/非法字符）
    ⚠️ 前端可能从 GitHub Release 的 asset.name 直接传过来，理论上可信，但这里必须当成
       不可信输入：只保留 basename、去掉 `\\/:*?"<>|` 与控制字符，防止
       `../../config/settings.json` 这类名字把文件写到更新目录之外。
    """
    raw = str(name or "").strip().replace("\\", "/")
    raw = os.path.basename(raw)
    raw = re.sub(r'[<>:"|?*\x00-\x1f]', "_", raw)
    raw = raw.strip(" .")
    if not raw:
        raw = DEFAULT_FILENAME
    if len(raw) > 120:
        root, ext = os.path.splitext(raw)
        raw = root[:120 - len(ext)] + ext
    return raw


def _file_size(path: str) -> int:
    """文件字节数（不存在/被占用时返回 0，不抛）"""
    try:
        return int(os.path.getsize(path)) if os.path.isfile(path) else 0
    except OSError:
        return 0


class DownloadErrorLite(Exception):
    """内部用：源"提前结束/短读"，属于可换源继续的软失败"""


def _friendly_error(exc) -> str:
    """把下载异常翻译成用户能看懂的一句话（前后端日志都用它）"""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}：{exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"网络错误：{getattr(exc, 'reason', exc)}"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "下载超时（网络太慢或连接被中断）"
    return f"{type(exc).__name__}: {exc}"


class _Canceled(Exception):
    """用户主动取消（内部用，转成 update.error 事件）"""


# ======================================================================
# 域
# ======================================================================
class UpdateDomain:
    """`api.update.*`：下载更新包 / 重启替换 / 打开下载目录"""

    def __init__(self, shell):
        self._shell = shell
        self._lock = threading.RLock()
        self._thread = None            # 当前下载线程
        self._cancel = None            # threading.Event
        self._last_path = ""           # 上次下载到的完整路径（install 优先用它）
        self._last_size = 0
        self._last_filename = ""

    # ---------- 路径 ----------
    def update_dir(self) -> str:
        return update_dir()

    def _ensure_dir(self) -> str:
        """确保更新目录存在并返回它（失败抛异常，由调用方 _fail）"""
        directory = self.update_dir()
        os.makedirs(directory, exist_ok=True)
        return directory

    def _downloading(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    # ---------- info ----------
    def info(self):
        """更新相关的环境信息（前端据此判断"能不能自动更新"）"""
        try:
            frozen = bool(getattr(sys, "frozen", False))
            self._ensure_dir()
            last = None
            if self._last_path:
                last = {"path": self._last_path,
                        "filename": self._last_filename or os.path.basename(self._last_path),
                        "size": int(self._last_size or 0)}
            return _ok(version=APP_VERSION,
                       frozen=frozen,
                       exe=str(sys.executable or ""),
                       temp_dir=self.update_dir(),
                       platform=sys.platform,
                       pid=os.getpid(),
                       downloading=self._downloading(),
                       last=last)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    # ---------- download ----------
    def download(self, url: str = "", filename: str = DEFAULT_FILENAME,
                 expected_size: int = 0):
        """后台下载更新包（**立即返回**；进度/完成/失败都通过事件推送）
        ⚠️ 必须是"立即返回 + 事件推送"：js_api 的回调跑在工作线程里，`evaluate_js` 又
           会阻塞等 JS 执行完；在这里同步下载几十 MB 会把整个 bridge 卡死（界面像假死）。
        """
        try:
            target_url = str(url or "").strip()
            if not target_url.lower().startswith(("http://", "https://")):
                return _fail("只支持 http/https 下载地址: " + (target_url or "(空)"))
            with self._lock:
                if self._downloading():
                    _log("info", "更新", "update", "已有下载在进行，忽略这次请求")
                    return _fail("已有下载在进行", busy=True)
                directory = self._ensure_dir()
                name = safe_filename(filename)
                target = os.path.join(directory, name)
                expected = max(0, int(expected_size or 0))
                cancel = threading.Event()
                thread = threading.Thread(
                    target=self._run_download,
                    args=(target_url, target, expected, cancel),
                    name="ToolsGCP-update-download", daemon=True)
                self._cancel = cancel
                self._thread = thread
                self._last_path = target
                self._last_filename = name
                self._last_size = 0
                thread.start()
            _log("op", "更新", "update",
                 f"开始下载更新包: {target_url} → {target}"
                 + (f"（预期 {expected} 字节）" if expected else ""))
            return _ok(started=True, path=target, filename=name)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def _run_download(self, url: str, target: str, expected: int, cancel):
        """下载线程**入口**：只负责"取消/失败 → 推事件 + 收尾状态位"
        ⚠️ 为什么要拆成"入口 + _download_update"：
           下载主体要能单独测（不掺事件推送），而线程里**任何异常都不能把线程炸掉**
           —— 前端正在等 `update.done` / `update.error`，一个没推出去的异常会让
           进度条永远停在 87%（表现就是"下载卡住不动"）。
        ⚠️ 半成品（.part）的取舍：
           · **网络失败** → 保留 .part 与 .part.meta.json → 用户再点一次更新能**续传**；
           · **用户主动取消** → 删掉 .part：取消是明确"我不要这个包了"，
             留着只会白占临时目录（且下次下载的来源可能已经变了）。
        """
        part = target + ".part"
        meta = part + ".meta.json"
        try:
            self._download_update(url, target, expected, cancel)
        except _Canceled:
            self._remove_quietly(part)
            self._remove_quietly(meta)
            self._last_size = 0
            _log("info", "更新", "update", "更新包下载已取消")
            self._push("update.error", {"error": "下载已取消", "canceled": True})
        except Exception as exc:                          # noqa: BLE001
            self._last_size = 0
            reason = _friendly_error(exc)
            _log("err", "更新", "update", f"更新包下载失败: {reason}")
            self._push("update.error", {"error": reason})
        finally:
            with self._lock:
                self._thread = None
                self._cancel = None

    def _download_update(self, url: str, target: str, expected: int, cancel):
        """真正的下载线程：**镜像回退 + 断点续传 + 按设置重试**
        ⚠️⚠️ 为什么大改（用户明确要求"下载功能要稳定"）：
           旧版这里是**一次性裸 urllib**：单地址、不重试、不换镜像、中断就从 0 开始。
           而下载主通道（desktop/api/downloader.py）早就有镜像回退 + Range 续传 +
           重试配额——**更新包偏偏走的是那条脆弱的路**，测试者机器（慢网 + 镜像才有速度）
           上表现为"下载失败 / 下一半重来 / 反复失败"。
           现在把两条路并成一套：镜像列表、候选地址、读超时、重试次数**全部复用
           downloader 的实现**（唯一事实来源，见 AGENTS 第 7 条），不在这儿另写一份。
        稳定性策略（和 downloader 同口径）：
          ① 候选地址 = 官方直连 → 各 GitHub 镜像（用户设置的 download_source 优先）；
          ② 每个地址**都支持断点续传**：`.part` 已有多少字节就 `Range: bytes=N-` 接着下，
             进度**单调不回退**（旧版中断 = 前功尽弃，这是"不稳定"最大的观感来源）；
          ③ 单次读超时压到 1s（`_set_read_timeout`）→ 点"取消"能立刻生效，
             不用等 20 秒；卡住不代表失败，换下一个镜像继续续传；
          ④ 全部地址都失败 → 按设置 `download_retry_count`（默认 5）重试，
             间隔 `RETRY_INTERVAL_S`（30s）用 `cancel.wait()` 等（可被取消打断）；
          ⑤ **一旦某个地址连上并收到过数据，重试配额重置回上限**
             —— 长下载中途网络抖动不该把配额耗光；
          ⑥ 收尾必须**校验字节数**（expected_size 或 Content-Length），
             短读/空文件一律算失败并删掉半成品。
        ⚠️ 续传的"归属校验"：`.part` 旁边放一个 `.part.meta.json` 记下 url 和总大小。
           换版本 / 换文件名时旧半成品**不能**拿来续传（否则会把两个不同版本的文件
           拼成一个"大小恰好又对得上"的坏包）。对不上就删掉重下。
        """
        part = target + ".part"
        meta = part + ".meta.json"
        total = int(expected or 0)
        received = 0
        header_total = 0

        # ---- 续传起点：先看 .part 与 .part.meta.json 对不对得上 ----
        resume_from = self._resume_offset(part, meta, url)

        max_retries = self._retry_count()
        retries_left = max_retries
        interval = self._retry_interval()
        attempt_error = None

        while True:
            urls = self._candidate_urls(url)
            connected_any = False
            for candidate in urls:
                if cancel.is_set():
                    raise _Canceled()
                try:
                    got, header_total = self._download_once(
                        candidate, part, resume_from, total, cancel)
                    received = got
                    connected_any = True
                    if got > resume_from:
                        # 这一段有进展：续传点前移，下次（若有）从这里接着下
                        resume_from = got
                    self._write_meta(meta, url, resume_from, header_total or total)
                    if total and received < total:
                        # 短读：不算成功 → 换下一个地址继续续传
                        raise DownloadErrorLite(
                            f"响应提前结束：收到 {received}，应为 {total}")
                    break
                except _Canceled:
                    raise
                except Exception as exc:                    # noqa: BLE001
                    attempt_error = exc
                    # 换源前**重读一次真实落盘大小**：崩溃/断电/半途失败时内存里的
                    # 计数可能比文件长（写了没 flush），拿真实长度续传才不会写出洞。
                    resume_from = _file_size(part)
                    received = resume_from
                    _log("warn", "更新", "download",
                         f"更新包从 {candidate} 下载中断，换下一个源继续（已下 "
                         f"{resume_from} 字节）: {_friendly_error(exc)}")
                    # 进度照实推（**不回 0**：这就是"不稳定"最扎眼的表现）
                    self._push_progress(resume_from, total, force=True)
            else:
                # 所有候选地址这一轮都失败 → 看还剩几次重试
                if retries_left <= 0:
                    raise attempt_error or RuntimeError("更新包下载失败")
                retries_left -= 1
                _log("warn", "更新", "retry",
                     f"更新包下载失败，{interval:.0f}s 后重试（还剩 "
                     f"{retries_left}/{max_retries} 次）：{_friendly_error(attempt_error)}")
                if cancel.wait(interval):
                    raise _Canceled()
                continue

            if connected_any:
                retries_left = max_retries      # ⑤ 连上并收过数据 → 配额回满
            break

        # ---------- 校验 ----------
        received = _file_size(part)
        if received <= 0:
            raise ValueError("下载到的文件是空的")
        if expected > 0 and received != expected:
            raise ValueError(f"下载大小与预期不符（预期 {expected} 字节，实际 {received} 字节）")
        if expected == 0 and header_total > 0 and received != header_total:
            raise ValueError(f"下载不完整（服务器声明 {header_total} 字节，实际 {received} 字节）")
        # ---------- 收尾：.part → 正式文件（同一分区，原子改名） ----------
        if os.path.exists(target):
            try:
                os.remove(target)
            except OSError:
                pass
        os.replace(part, target)
        self._remove_quietly(meta)
        self._last_size = received
        _log("op", "更新", "update", f"更新包下载完成: {target}（{received} 字节）")
        self._push("update.done", {
            "ok": True,
            "path": target,
            "size": received,
            "filename": os.path.basename(target),
        })

    # ---------- 下载的分件（拆出来只为可测；语义与上面的策略一一对应） ----------
    def _candidate_urls(self, url: str) -> list:
        """官方直连 → 各镜像（复用 downloader 的镜像口径，不另抄一份域名列表）"""
        try:
            from .downloader import build_candidate_urls
            manager = self._shell.settings_manager if self._shell else None
            try:
                from .downloader import _mirror_order
                mirrors = _mirror_order(manager)
            except Exception:                             # noqa: BLE001
                mirrors = None
            urls = build_candidate_urls(url, mirrors)
            return urls or [url]
        except Exception as exc:                          # noqa: BLE001
            # downloader 域不可用（打包裁剪/循环导入）也不能让更新彻底下不动
            _log("warn", "更新", "download", f"取镜像列表失败，只用直连: {exc}")
            return [url]

    def _retry_count(self) -> int:
        """重试次数：跟着用户设置 `download_retry_count`（默认 5）
        ⚠️ 不 import DownloadDomain 复用：那是"下载管理器"的实例方法，依赖它自己那套
           settings_manager 注入；这里只需要同一个配置项的值，直接读更清楚也不会绕圈。
        """
        try:
            manager = self._shell.settings_manager if self._shell else None
            if manager is None:
                return DEFAULT_UPDATE_RETRY
            value = int((getattr(manager, "settings", {}) or {}).get(
                "download_retry_count", DEFAULT_UPDATE_RETRY))
            return max(0, min(50, value))
        except Exception:                                 # noqa: BLE001
            return DEFAULT_UPDATE_RETRY

    def _retry_interval(self) -> float:
        try:
            from .downloader import RETRY_INTERVAL_S
            return float(RETRY_INTERVAL_S)
        except Exception:                                 # noqa: BLE001
            return 30.0

    def _resume_offset(self, part: str, meta: str, url: str) -> int:
        """能不能续传：`.part` 存在 + meta 里记的是**同一个 url** → 返回已有字节数"""
        size = _file_size(part)
        if size <= 0:
            return 0
        try:
            import json
            with open(meta, "r", encoding="utf-8") as stream:
                saved = json.load(stream)
            if str(saved.get("url") or "") != str(url):
                _log("info", "更新", "download", "更新包来源变了，丢弃旧半成品重新下载")
                self._remove_quietly(part)
                self._remove_quietly(meta)
                return 0
        except FileNotFoundError:
            # 没有 meta = 不知道这半截文件是谁 → 保守起见重下（宁可慢，不要坏包）
            _log("info", "更新", "download", "更新包缺少续传记录，重新下载")
            self._remove_quietly(part)
            return 0
        except Exception:                                 # noqa: BLE001
            self._remove_quietly(part)
            self._remove_quietly(meta)
            return 0
        if size:
            _log("info", "更新", "download", f"从 {size} 字节处继续下载更新包")
        return size

    def _write_meta(self, meta: str, url: str, received: int, total: int):
        try:
            import json
            with open(meta, "w", encoding="utf-8") as stream:
                json.dump({"url": str(url), "received": int(received),
                           "total": int(total or 0)}, stream, ensure_ascii=False)
        except Exception:                                 # noqa: BLE001
            pass

    def _download_once(self, url: str, part: str, resume_from: int,
                       total: int, cancel):
        """单次下载：带 Range 续传；返回 (落盘总字节数, 服务器声明的总大小)
        ⚠️ 提前断流**必须抛错**（不能静默 return 短读）：静默返回会让上层以为
           "这个源成功了"，最后在大小校验处炸成失败 —— 就是用户看到的"下载失败"。
        """
        headers = {
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
            "Accept": "*/*",
        }
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"
        request = urllib.request.Request(url, headers=headers)
        written = resume_from
        header_total = 0
        response = urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S)
        try:
            status = getattr(response, "status", None) or response.getcode()
            length = response.headers.get("Content-Length")
            body = int(str(length).strip()) if (length and str(length).strip().isdigit()) else 0
            if status == 206:
                # 续传成功：总量 = 已下 + 剩余
                range_total = response.headers.get("Content-Range") or ""
                match = re.search(r"/(\d+)\s*$", str(range_total))
                header_total = int(match.group(1)) if match else (resume_from + body)
            elif status == 200:
                if resume_from > 0:
                    # ⚠️ 服务器**无视 Range** 给了整个文件 → 只能从 0 重下，
                    #    直接在半成品后面追加会把文件写坏（大小对不上还是最好的情况）。
                    _log("info", "更新", "download", f"源不支持续传，从头下载: {url}")
                    resume_from = 0
                    written = 0
                header_total = body
            else:
                header_total = resume_from + body
            if total <= 0 and header_total > 0:
                total = header_total

            mode = "r+b" if (resume_from > 0 and os.path.exists(part)) else "wb"
            with open(part, mode) as handle:
                if resume_from > 0:
                    handle.seek(resume_from)
                try:
                    from .downloader import _set_read_timeout
                    _set_read_timeout(response, 1.0)      # 取消能立刻生效
                except Exception:                         # noqa: BLE001
                    pass
                last_emit = 0.0
                while True:
                    if cancel.is_set():
                        raise _Canceled()
                    try:
                        chunk = response.read(CHUNK_SIZE)
                    except (socket.timeout, TimeoutError):
                        # 读超时不是失败：回头看取消标记，没取消就接着读
                        if cancel.is_set():
                            raise _Canceled()
                        continue
                    if not chunk:
                        break
                    handle.write(chunk)
                    written += len(chunk)
                    now = time.time()
                    if now - last_emit >= PROGRESS_INTERVAL_S:
                        last_emit = now
                        self._push_progress(written, total)
                # ⚠️ flush 必须在 `with open(...)` **里面**：挪到外面时文件已关闭，
                #   会抛 `ValueError: flush of closed file` —— 每一段都被当成失败，
                #   下载永远完不成（实测踩过）。
                handle.flush()
            return written, header_total
        finally:
            try:
                response.close()
            except Exception:                             # noqa: BLE001
                pass

    def _push_progress(self, received: int, total: int, force: bool = False):
        """推 update.progress（同一百分比不重复推；force 用于换源时纠偏）"""
        percent = (round(received * 100.0 / total, 1) if total > 0 else None)
        if not force and percent == getattr(self, "_last_percent", None):
            return
        self._last_percent = percent
        self._push("update.progress", {"received": int(received),
                                       "total": int(total or 0),
                                       "percent": percent})

    @staticmethod
    def _remove_quietly(path: str):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def _push(self, name: str, payload: dict):
        """推送事件（**绝不抛**；退出流程里 push_event 自己会静默丢弃）"""
        try:
            self._shell.push_event(name, payload)
        except Exception:                                 # noqa: BLE001
            pass

    # ---------- cancel ----------
    def cancel(self):
        """取消正在进行的下载（没有下载时返回 running=false，不报错）"""
        try:
            with self._lock:
                cancel = self._cancel
                running = self._downloading()
            if not running or cancel is None:
                return _ok(canceled=False, running=False)
            cancel.set()
            _log("info", "更新", "update", "用户请求取消下载更新包")
            return _ok(canceled=True, running=True)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    # ---------- install_and_restart ----------
    def install_and_restart(self):
        """写 apply_update.cmd → 拉起它 → 返回 → 延迟 0.9s 退出
        ⚠️ 顺序是硬要求：**先返回**（前端拿到 `{ok, restarting}` 才能弹"正在重启"的提示），
           再延迟退出。同步退出会让 pywebview 的 js_bridge_call 在送回结果时打到已释放的
           WebView2（见 shell.quit_app_async 的说明）。
        """
        try:
            if not getattr(sys, "frozen", False):
                _log("warn", "更新", "update", "非打包版，拒绝自动替换（源码运行）")
                return _fail("当前是源码运行，无法自动替换；请在打包版使用，或手动更新")
            exe = os.path.abspath(str(sys.executable or ""))
            if not exe or not os.path.isfile(exe):
                return _fail(f"找不到当前程序文件，无法替换: {exe or '(空)'}")
            directory = self._ensure_dir()
            source = self._resolve_update_file(directory)
            if not source:
                return _fail(f"没有找到已下载的更新包，请先下载到 {directory}")
            size = os.path.getsize(source)
            if size <= 0:
                return _fail("更新包是空文件，请重新下载")
            script = self._write_apply_script(directory)
            # ⚠️ 必须走 _cmd_c_line 的"外层再套一对引号"形态：
            #    列表形式会被 cmd 剥掉最外层引号 → 带空格的安装目录把命令行截断 →
            #    更新脚本根本没跑（= 没替换、没重启、还弹一个带报错的 cmd 窗口）。
            command = _cmd_c_line([script, exe, source, str(os.getpid())])
            if not _launch_hidden(command, cwd=directory):
                return _fail("更新脚本启动失败（cmd.exe 无法拉起）")
            _log("op", "更新", "update",
                 f"已启动更新脚本: {script} 目标={exe} 更新包={source}"
                 f"（{size} 字节）当前PID={os.getpid()}，{QUIT_DELAY_S}s 后退出")
            threading.Thread(target=self._quit_later, name="ToolsGCP-update-quit",
                             daemon=True).start()
            return _ok(restarting=True, script=script, app=exe,
                       update_file=source, size=int(size))
        except Exception as exc:                          # noqa: BLE001
            _log("err", "更新", "update", f"启动更新替换失败: {exc}")
            return _fail(exc)

    def _resolve_update_file(self, directory: str) -> str:
        """找要安装的更新包：优先上次下载的，其次目录里最新的 .exe
        ⚠️ 安全边界：只接受**落在更新目录里**的路径。绝不因为某个变量被污染就去
           覆盖 `sys.executable`（那是"把用户程序换成别的东西"级别的破坏）。
        """
        root = os.path.abspath(directory)
        candidates = []
        last = str(self._last_path or "")
        if last and os.path.isfile(last):
            candidates.append(last)
        try:
            for name in sorted(os.listdir(root)):
                if not name.lower().endswith((".exe", ".bin", ".zip", ".msi")):
                    continue
                candidates.append(os.path.join(root, name))
        except OSError:
            pass
        for path in candidates:
            try:
                full = os.path.abspath(path)
                if os.path.dirname(full) != root:         # 必须在更新目录第一层
                    continue
                if os.path.getsize(full) > 0:
                    return full
            except OSError:
                continue
        return ""

    def _write_apply_script(self, directory: str) -> str:
        """把 apply_update.cmd 写到更新目录（纯 ASCII + CRLF，见模块 docstring）
        ⚠️ 写盘**之前**自己先校验一遍 ASCII：以前只靠 encoding="ascii" 抛
           UnicodeEncodeError，那个异常发生在 install_and_restart 的中途 ——
           用户看到的就是"点了更新没反应"，而且日志里只有一句编码错误。
           这里提前抛带行号的清晰错误，并且**不写坏已有脚本**。
        """
        script = os.path.join(directory, APPLY_SCRIPT_NAME)
        for index, line in enumerate(APPLY_SCRIPT_LINES):
            try:
                line.encode("ascii")
            except UnicodeEncodeError:
                raise ValueError(
                    f"apply_update.cmd 第 {index + 1} 行含非 ASCII 字符（脚本必须纯 ASCII，"
                    f"cmd 按 OEM 代码页读 .cmd）: {line!r}")
        content = "\r\n".join(APPLY_SCRIPT_LINES) + "\r\n"
        with open(script, "w", encoding="ascii", newline="") as handle:
            handle.write(content)
        return script

    def _quit_later(self, delay: float = QUIT_DELAY_S):
        """延迟退出（把时间留给"前端收到返回值 → 弹提示 → 界面收起"）"""
        try:
            time.sleep(max(0.0, float(delay)))
        except Exception:
            pass
        try:
            # ⚠️ force=True：更新包已经装好了，这时候弹"还有下载任务在跑"的确认框
            #    会把更新重启卡住 —— 用户已经在更新流程里确认过了。
            self._shell.quit_app(force=True)
        except Exception:                                 # noqa: BLE001
            pass

    # ---------- open_folder ----------
    def open_folder(self):
        """打开更新下载目录（系统资源管理器）"""
        try:
            directory = self._ensure_dir()
            os.startfile(directory)                       # noqa: S606 - Windows 专用
            _log("info", "更新", "update", f"打开更新下载目录: {directory}")
            return _ok(path=directory)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)
