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
一个中文都不写，路径全部通过命令行参数 `%~1/%~2/%~3` 传进去 —— 这样文件的编码
（cmd 按系统 OEM 代码页读 .cmd）永远不会把中文路径读坏），然后
`cmd /c apply_update.cmd <当前exe> <更新包> <当前PID>`（CREATE_NO_WINDOW | DETACHED_PROCESS）：
    ① 轮询 tasklist 等当前进程退出（最多 ~2 分钟）；
    ② 备份原 exe 为 `<exe>.bak`，`copy /b` 覆盖（重试 20 次，刚退出时文件可能还被锁着）；
    ③ 覆盖失败 → 用 .bak 回滚并重新启动旧版（不让用户"程序没了"）；
    ④ 成功 → 启动新 exe、删掉 .bak 与下载下来的更新包、最后删掉自己。
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

# apply_update.cmd 的正文（**必须是纯 ASCII**，见模块 docstring 第三节）
APPLY_SCRIPT_LINES = (
    "@echo off",
    "setlocal",
    'set "TARGET=%~1"',
    'set "SOURCE=%~2"',
    'set "APPPID=%~3"',
    'if "%TARGET%"=="" goto giveup',
    'if not exist "%TARGET%" goto giveup',
    'if not exist "%SOURCE%" goto giveup',
    "rem ---- wait for the running app to exit (max ~120s) ----",
    "set COUNT=0",
    ":wait",
    'tasklist /FI "PID eq %APPPID%" /NH 2>nul | findstr /C:"%APPPID%" >nul',
    "if errorlevel 1 goto settle",
    "set /a COUNT=%COUNT%+1",
    "if %COUNT% GEQ 120 goto settle",
    "ping -n 2 127.0.0.1 >nul",
    "goto wait",
    ":settle",
    "ping -n 1 -w 300 127.0.0.1 >nul",
    'if exist "%TARGET%.bak" del /f /q "%TARGET%.bak" >nul 2>&1',
    'copy /b /y "%TARGET%" "%TARGET%.bak" >nul 2>&1',
    "set TRY=0",
    ":copy",
    'copy /b /y "%SOURCE%" "%TARGET%" >nul 2>&1',
    "if not errorlevel 1 goto copied",
    "set /a TRY=%TRY%+1",
    "if %TRY% GEQ 20 goto rollback",
    "ping -n 2 127.0.0.1 >nul",
    "goto copy",
    ":rollback",
    'if exist "%TARGET%.bak" copy /b /y "%TARGET%.bak" "%TARGET%" >nul 2>&1',
    "goto giveup",
    ":copied",
    'del /f /q "%TARGET%.bak" >nul 2>&1',
    'del /f /q "%SOURCE%" >nul 2>&1',
    'start "" "%TARGET%"',
    "goto remove_self",
    ":giveup",
    'if exist "%TARGET%" start "" "%TARGET%"',
    ":remove_self",
    '(goto) 2>nul & del /f /q "%~f0"',
)


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
        """真正的下载线程（urllib，256KB 分块，写 .part 再原子改名）"""
        part = target + ".part"
        received = 0
        total = expected
        header_total = 0
        last_emit = 0.0
        last_percent = None
        try:
            request = urllib.request.Request(
                url, headers={
                    "User-Agent": f"{APP_NAME}/{APP_VERSION}",
                    "Accept": "*/*",
                })
            with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
                length = response.headers.get("Content-Length")
                if length and str(length).strip().isdigit():
                    header_total = int(str(length).strip())
                    if not total:
                        total = header_total
                with open(part, "wb") as handle:
                    while True:
                        if cancel.is_set():
                            raise _Canceled()
                        chunk = response.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        handle.write(chunk)
                        received += len(chunk)
                        now = time.time()
                        if now - last_emit >= PROGRESS_INTERVAL_S:
                            last_emit = now
                            percent = (round(received * 100.0 / total, 1)
                                       if total > 0 else None)
                            if percent != last_percent:      # 同一百分比不重复推
                                last_percent = percent
                                self._push("update.progress", {
                                    "received": received,
                                    "total": total,
                                    "percent": percent,
                                })
            # ---------- 校验 ----------
            if received <= 0:
                raise ValueError("下载到的文件是空的")
            if expected > 0 and received != expected:
                raise ValueError(f"下载大小与预期不符（预期 {expected} 字节，"
                                 f"实际 {received} 字节）")
            if expected == 0 and header_total > 0 and received != header_total:
                raise ValueError(f"下载不完整（服务器声明 {header_total} 字节，"
                                 f"实际 {received} 字节）")
            # ---------- 收尾：.part → 正式文件（同一分区，原子改名） ----------
            if os.path.exists(target):
                try:
                    os.remove(target)
                except OSError:
                    pass
            os.replace(part, target)
            self._last_size = received
            _log("op", "更新", "update",
                 f"更新包下载完成: {target}（{received} 字节）")
            self._push("update.done", {
                "ok": True,
                "path": target,
                "size": received,
                "filename": os.path.basename(target),
            })
        except _Canceled:
            self._remove_quietly(part)
            self._last_size = 0
            _log("info", "更新", "update", "更新包下载已取消")
            self._push("update.error", {"error": "下载已取消", "canceled": True})
        except Exception as exc:                          # noqa: BLE001
            self._remove_quietly(part)
            self._last_size = 0
            reason = _friendly_error(exc)
            _log("err", "更新", "update", f"更新包下载失败: {reason}")
            self._push("update.error", {"error": reason})
        finally:
            with self._lock:
                self._thread = None
                self._cancel = None

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
            flags = 0
            for name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS",
                         "CREATE_NEW_PROCESS_GROUP"):
                try:
                    flags |= int(getattr(subprocess, name, 0) or 0)
                except Exception:
                    pass
            subprocess.Popen(
                ["cmd", "/c", script, exe, source, str(os.getpid())],
                cwd=directory, creationflags=flags, close_fds=True)
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
        """把 apply_update.cmd 写到更新目录（纯 ASCII + CRLF，见模块 docstring）"""
        script = os.path.join(directory, APPLY_SCRIPT_NAME)
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
