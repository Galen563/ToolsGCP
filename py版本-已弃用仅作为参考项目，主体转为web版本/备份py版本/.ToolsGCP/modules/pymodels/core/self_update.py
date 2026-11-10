r"""自更新：用 %TEMP% 里的临时更新器把新版换上去（Windows 不允许程序替换自己）。

主程序把新版下到 %TEMP%\ToolsGCP_new.exe，带 --update --pid <自己PID> --target <原exe路径>
启动它并真正退出；更新器等旧进程退出、备份原 exe、复制自身覆盖原路径、启动新版；
新版带 --cleanup 删掉临时文件。

⚠️ 三条硬性约定：程序目录里永远只有 ToolsGCP.exe（不写 .cmd/.new/.bak）；任何一步失败都
回滚成原 exe 并把旧版重新启动起来；目标目录不可写时用 ShellExecuteW(runas) 提权重来。
"""

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes

from ..constants import APP_ASSET_NAME, SCRIPT_DIR

# ---------- 一、失败原因（机器码；文案在语言文件里，见 ui/update_dialog.py） ----------

BLOCK_SOURCE_RUN = "SOURCE_RUN"        # 源码运行且目录里没有 exe，没有东西可换
BLOCK_NO_EXE = "NO_EXE"                # 该目录里找不到可替换的 exe
BLOCK_RENAMED = "RENAMED"              # 文件名带非 ASCII（启动参数传不了）
BLOCK_NOT_WRITABLE = "NOT_WRITABLE"    # 目录不可写（现在会提权重试，保留给提示用）
BLOCK_NOT_WINDOWS = "NOT_WINDOWS"      # 非 Windows：这套方案只在 Windows 上有效
BLOCK_STAGE = "STAGE_FAILED"           # 新版复制不进程序目录（空间/权限/杀软）
BLOCK_SCRIPT = "SCRIPT_FAILED"         # 连更新器都拉不起来

# 临时文件的名字（都在 %TEMP% 里，程序目录一个都不放）
STAGING_NAME = "ToolsGCP_new.exe"       # 下载下来的新版：它自己就是"临时更新器"
BACKUP_NAME = "ToolsGCP.bak"            # 原 exe 的备份（回滚用）
LOG_NAME = "ToolsGCP_update.log"        # 更新过程日志（纯文本，出问题好查）

WAIT_TIMEOUT_MS = 60_000                # 等旧进程退出最多等这么久
COPY_RETRIES = 30                       # 覆盖原 exe 的重试次数（刚退出时文件可能还被锁着）
COPY_RETRY_WAIT = 0.2
SETTLE_MS = 120                         # 旧进程退出后的静默期
CLEANUP_RETRY_TIMEOUT_S = 60.0          # 后台删临时文件的时限（刚退出时那个文件还被更新器自己占着）

# 更新模式 / 启动后清理的参数名（主程序入口和更新器共用）
FLAG_UPDATE = "--update"
FLAG_PID = "--pid"
FLAG_TARGET = "--target"
FLAG_CLEANUP = "--cleanup"
FLAG_ELEVATED = "--elevated"


# ---------- 二、路径 ----------

def temp_dir() -> str:
    """系统临时目录（Windows 用 GetTempPathW，其它平台退回 tempfile）"""
    if sys.platform == "win32":
        try:
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


def staging_exe_path() -> str:
    """下载下来的新版放在哪：`%TEMP%\\ToolsGCP_new.exe`"""
    return os.path.join(temp_dir(), STAGING_NAME)


def backup_exe_path() -> str:
    """原 exe 的备份放在哪：`%TEMP%\\ToolsGCP.bak`（不放程序目录）"""
    return os.path.join(temp_dir(), BACKUP_NAME)


def log_path() -> str:
    return os.path.join(temp_dir(), LOG_NAME)


def log_line(message: str):
    """往 %TEMP%\\ToolsGCP_update.log 追加一行（更新阶段没有 Qt，不能用日志模块）"""
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path(), "a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


# ---------- 三、目标识别（能不能换、换哪个） ----------

def current_executable():
    """当前正在运行的可执行文件路径；源码运行（开发状态）返回 "" """
    if getattr(sys, "frozen", False):
        try:
            return os.path.abspath(sys.executable)
        except Exception:
            return ""
    return ""


def replacement_target(directory=None, running_exe=None):
    """返回 (要替换的目录, 要替换的 exe 文件名, 正在运行的 exe 全路径)

    程序目录里就有 ToolsGCP.exe 就换它，否则若正跑在这个目录下打包好的 exe 上就换它自己。
    """
    directory = os.path.abspath(directory or SCRIPT_DIR)
    running = current_executable() if running_exe is None else str(running_exe or "")
    if os.path.exists(os.path.join(directory, APP_ASSET_NAME)):
        return directory, APP_ASSET_NAME, running
    if running:
        exe_dir = os.path.dirname(os.path.abspath(running))
        if os.path.normcase(exe_dir) == os.path.normcase(directory):
            return directory, os.path.basename(running), running
    return directory, APP_ASSET_NAME, running


def replacement_blockers(directory=None, running_exe=None):
    """现在能不能自动替换？返回原因码列表，空列表 = 可以

    目录不可写**不算**阻塞：那种情况更新器会提权（UAC）重来一遍，见 run_update_mode。
    """
    exe_dir, exe_name, running = replacement_target(directory, running_exe)
    target = os.path.join(exe_dir, exe_name)
    blockers = []

    if sys.platform != "win32":
        blockers.append(BLOCK_NOT_WINDOWS)

    if not os.path.exists(target):
        blockers.append(BLOCK_NO_EXE)
        if not running:
            blockers.append(BLOCK_SOURCE_RUN)
    elif not exe_name.isascii():
        # 启动参数要能原样传过去；非 ASCII 的路径在命令行里容易出岔子
        blockers.append(BLOCK_RENAMED)

    return blockers


# ---------- 四、主程序这一侧：拉起"临时更新器" ----------

def build_updater_args(staging: str, target: str, pid=None) -> list:
    """拼更新器的启动参数：

        ToolsGCP_new.exe --update --pid <PID> --target <原 exe 完整路径>
    """
    return [str(staging), FLAG_UPDATE,
            FLAG_PID, str(int(os.getpid() if pid is None else pid)),
            FLAG_TARGET, str(target)]


def launch_updater(staging: str, target: str, pid=None):
    """启动"临时更新器"（就是刚下载下来的那个新版）；返回 (ok, 说明)

    调用方拿到 ok=True 之后必须立刻真正退出（更新器在按 PID 等我们消失）。
    """
    staging = str(staging or "")
    target = str(target or "")
    if not os.path.exists(staging):
        return False, [BLOCK_STAGE]
    if not target:
        return False, [BLOCK_NO_EXE]

    args = build_updater_args(staging, target, pid)
    flags = 0
    if sys.platform == "win32":
        # DETACHED_PROCESS：父进程退出后它继续跑；CREATE_NO_WINDOW：别闪黑窗
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    try:
        subprocess.Popen(args, creationflags=flags, close_fds=True,
                         cwd=os.path.dirname(staging) or None)
    except Exception as exc:
        log_line(f"拉起更新器失败: {exc!r}")
        return False, [BLOCK_SCRIPT]
    log_line(f"已拉起更新器: {args}")
    return True, staging


# ---------- 五、更新器这一侧（由 %TEMP%\ToolsGCP_new.exe 自己执行） ----------

def is_update_mode(argv=None) -> bool:
    argv = list(sys.argv if argv is None else argv)
    return FLAG_UPDATE in argv


def parse_update_args(argv=None) -> dict:
    """从命令行里取出 --pid / --target / --cleanup 等参数"""
    argv = list(sys.argv if argv is None else argv)
    out = {"pid": 0, "target": "", "cleanup": "", "elevated": False}

    def value_of(flag):
        if flag in argv:
            index = argv.index(flag)
            if index + 1 < len(argv):
                return argv[index + 1]
        return ""

    try:
        out["pid"] = int(value_of(FLAG_PID) or 0)
    except (TypeError, ValueError):
        out["pid"] = 0
    out["target"] = value_of(FLAG_TARGET)
    out["cleanup"] = value_of(FLAG_CLEANUP)
    out["elevated"] = FLAG_ELEVATED in argv
    return out


# ---------- Win32：进程句柄 / 提权 ----------

SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
MOVEFILE_DELAY_UNTIL_REBOOT = 0x00000004
ERROR_ACCESS_DENIED = 5

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None
_shell32 = ctypes.WinDLL("shell32", use_last_error=True) if sys.platform == "win32" else None

if _kernel32 is not None:
    # ⚠️ 必须声明 argtypes/restype：默认按 32 位 int 处理，64 位下句柄会被截断
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      wintypes.DWORD]
    _kernel32.MoveFileExW.restype = wintypes.BOOL
if _shell32 is not None:
    _shell32.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR,
                                       wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       wintypes.LPCWSTR, ctypes.c_int]
    _shell32.ShellExecuteW.restype = ctypes.c_void_p


def wait_for_process_exit(pid: int, timeout_ms: int = WAIT_TIMEOUT_MS) -> bool:
    """用进程句柄等 pid 退出；返回 True = 已退出（或本来就不存在）

    OpenProcess 拿不到句柄说明进程已经没了（或没权限），也算退出。
    """
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError):
        pid = 0
    if sys.platform != "win32" or pid <= 0:
        time.sleep(max(0.0, min(2.0, timeout_ms / 1000.0)))
        return True

    handle = _kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return True
    try:
        deadline = time.monotonic() + max(0.0, timeout_ms / 1000.0)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            slice_ms = max(1, int(min(remaining, 0.25) * 1000))
            result = _kernel32.WaitForSingleObject(handle, slice_ms)
            if result == WAIT_OBJECT_0:
                return True
            if result != WAIT_TIMEOUT:
                return False
    finally:
        try:
            _kernel32.CloseHandle(handle)
        except Exception:
            pass


def relaunch_elevated(argv=None) -> bool:
    """用 UAC 提权把自己重新拉起来（Program Files 下必须有管理员）"""
    if sys.platform != "win32":
        return False
    argv = list(sys.argv if argv is None else argv)
    if FLAG_ELEVATED in argv:
        return False                # 已经提过一次：不能再弹 UAC（会死循环）
    argv = argv + [FLAG_ELEVATED]
    try:
        exe = os.path.abspath(argv[0])
        params = subprocess.list2cmdline(argv[1:])
        result = _shell32.ShellExecuteW(None, "runas", str(exe), params,
                                        os.path.dirname(str(exe)) or None, 1)
        # 返回值 > 32 表示成功（<= 32 是错误码）
        return int(result or 0) > 32
    except Exception as exc:
        log_line(f"提权失败: {exc!r}")
        return False


# ---------- 文件操作 ----------

def _sha256(path: str) -> str:
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_copy(src: str, dst: str) -> bool:
    """复制完再对一遍体积 + SHA-256，防止"复制到一半"被当成成功"""
    try:
        if os.path.getsize(src) != os.path.getsize(dst):
            return False
        return _sha256(src) == _sha256(dst)
    except Exception:
        return False


def _copy_with_retry(src: str, dst: str, retries: int = COPY_RETRIES) -> bool:
    """把 src 复制到 dst（覆盖），失败重试；成功返回 True

    旧进程刚退出时 exe 可能还被系统锁着一瞬间，所以要重试；但"拒绝访问"（WinError 5）
    是权限问题，重试没用，早点交给提权那条路。
    """
    last_error = None
    for attempt in range(max(1, int(retries))):
        try:
            shutil.copy2(src, dst)
            return True
        except Exception as exc:
            last_error = exc
            if getattr(exc, "winerror", None) == ERROR_ACCESS_DENIED and attempt >= 1:
                break
            time.sleep(COPY_RETRY_WAIT)
    log_line(f"复制失败 {src} → {dst}: {last_error!r}")
    return False


def _remove_once(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return True
    except Exception:
        return False


def _remove_with_retry(path: str, retries: int = 10) -> bool:
    for _ in range(max(1, int(retries))):
        if _remove_once(path):
            return True
        time.sleep(COPY_RETRY_WAIT)
    return not os.path.exists(path)


def _delete_on_reboot(path: str):
    """最后手段：登记成"重启时删除"（非管理员会失败，失败就算了）"""
    try:
        _kernel32.MoveFileExW(str(path), None, MOVEFILE_DELAY_UNTIL_REBOOT)
    except Exception:
        pass


def rollback(target: str, backup: str) -> bool:
    """回滚：把备份复制回原路径"""
    if not backup or not os.path.exists(backup):
        return False
    log_line(f"回滚：{backup} → {target}")
    return _copy_with_retry(backup, target)


def _restore_after_failure(target: str, backup: str, had_original: bool) -> bool:
    """替换失败后的收尾；返回"现在这个 target 能不能安全启动"

    ⚠️ `shutil.copy2` 是**先清空再写**的：复制到一半失败会留下一个被截断的 exe。
       所以回滚没成功时不能盲目启动 target —— 只有确认它和备份一模一样才敢启动，
       否则宁可只写一行日志（备份还在 %TEMP%，用户能手工救回来）。
    """
    if not had_original:
        _remove_with_retry(target, retries=3)      # 本来就没有：别留半个文件
        return False
    if not os.path.exists(backup):
        return os.path.exists(target)              # 没有备份可回滚，只能赌它还在
    if rollback(target, backup):
        return True
    return _verify_copy(backup, target)


def launch_target(target: str, cleanup: str = "") -> bool:
    """启动原路径的新版（工作目录 = 程序目录），并让它启动后清理临时文件"""
    directory = os.path.dirname(os.path.abspath(target)) or None
    args = [str(target)]
    if cleanup:
        args += [FLAG_CLEANUP, str(cleanup)]
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    for attempt in range(3):
        try:
            subprocess.Popen(args, cwd=directory, close_fds=True,
                             creationflags=flags)
            log_line(f"已启动新版: {args} (cwd={directory})")
            return True
        except Exception as exc:
            log_line(f"启动新版失败({attempt + 1}/3): {exc!r}")
            time.sleep(COPY_RETRY_WAIT)
    return False


def run_update_mode(argv=None) -> int:
    """临时更新器的全部逻辑；返回进程退出码（0 = 成功）

    顺序：等旧 PID 退出 → 备份原 exe → 复制自身覆盖 → 启动原路径新版 → 退出；失败则回滚。
    """
    args = parse_update_args(argv)
    target = os.path.abspath(args["target"]) if args["target"] else ""
    # "自己"是哪个文件以 argv[0] 为准（调用方传进来的就是 %TEMP%\ToolsGCP_new.exe），
    # 比 sys.executable 可靠 —— 自检脚本也用 argv[0] 在沙箱里干跑。
    argv_list = list(sys.argv if argv is None else argv)
    staging = os.path.abspath(argv_list[0]) if argv_list else ""
    if not staging or not os.path.exists(staging):
        staging = os.path.abspath(sys.executable)
    backup = backup_exe_path()

    log_line("=" * 60)
    log_line(f"更新器启动 pid={args['pid']} target={target} "
             f"staging={staging} elevated={args['elevated']}")

    if not target:
        log_line("没有 --target，退出")
        return 2

    # ---- ① 等旧进程退出（进程句柄 + 超时）----
    if args["pid"] and not wait_for_process_exit(args["pid"], WAIT_TIMEOUT_MS):
        log_line("等待旧进程超时，放弃替换（原程序未受影响）")
        return 3
    time.sleep(SETTLE_MS / 1000.0)

    # ---- ② 备份原 exe（备份放 %TEMP%，程序目录不留文件）----
    had_original = os.path.exists(target)
    if had_original:
        try:
            shutil.copy2(target, backup)
        except Exception as exc:
            log_line(f"备份失败（继续尝试替换）: {exc!r}")
    else:
        log_line("原 exe 不存在：直接放置新版")

    # ---- ③ 复制自身到原路径覆盖，并校验复制结果 ----
    copied = _copy_with_retry(staging, target)
    if not copied or not _verify_copy(staging, target):
        # 只有"复制本身失败"才值得提权重来（校验不过说明文件有问题，提权没用）
        if not copied and not args["elevated"] and relaunch_elevated(argv):
            log_line("权限不足，已请求管理员权限重新执行更新")
            return 0
        log_line("覆盖失败，回滚")
        if _restore_after_failure(target, backup, had_original):
            launch_target(target)
        return 4

    # ---- ④ 启动原路径新版（并让它清理临时文件）----
    if not launch_target(target, cleanup=staging):
        log_line("新版启动失败，回滚")
        if _restore_after_failure(target, backup, had_original):
            launch_target(target)
        return 5

    log_line("更新完成，更新器退出")
    return 0


def cleanup_after_update(argv=None):
    """新版启动后清理临时文件（由主程序入口在 --cleanup 时调用）

    要删的那个 _new.exe 就是刚退出的更新器自己的文件，可能还没完全释放 → 先同步试几次，
    还删不掉就丢到后台线程重试，别拖慢程序启动。
    """
    args = parse_update_args(argv)
    if not args["cleanup"]:
        # 没带 --cleanup 就不是"更新之后的第一次启动"，别去动备份（那是回滚点）
        return
    pending = []
    for path in (args["cleanup"], backup_exe_path()):
        if path and not _remove_with_retry(path, retries=4):
            pending.append(path)
    log_line(f"清理临时文件: {args['cleanup']} {backup_exe_path()} 待重试={pending}")
    if pending:
        _schedule_cleanup(pending)


def _schedule_cleanup(paths):
    """后台把还没删掉的临时文件删干净（更新器进程退出后就能删了）"""
    def worker():
        deadline = time.monotonic() + CLEANUP_RETRY_TIMEOUT_S
        remaining = list(paths)
        while remaining and time.monotonic() < deadline:
            time.sleep(0.5)
            remaining = [path for path in remaining if not _remove_once(path)]
        for path in remaining:
            log_line(f"临时文件删不掉，登记为重启时删除: {path}")
            _delete_on_reboot(path)

    try:
        threading.Thread(target=worker, name="ToolsGCP-update-cleanup",
                         daemon=True).start()
    except Exception:
        pass
