r"""清理系统 %temp% 里 ToolsGCP 的残留（更新替换流程留下的临时文件）
========== 这个模块解决什么 ==========
用户的原话是「更新下载到系统 %temp%，程序有没有替换完删 temp 里 ToolsGCP 相关的东西？
没有就做成"替换完毕重启时直接删除"」。
现状是：更新包下到 `<temp>\ToolsGCP\update\`、替换脚本 `apply_update.cmd` 也写在
那里，但**没人负责收尾** —— 替换完之后 `<temp>\ToolsGCP\` 整个目录、
`<temp>\ToolsGCP_new.exe`、`<temp>\ToolsGCP.bak`、`<temp>\ToolsGCP_update.log`
全都留在系统临时目录里（用户能在"设置 → 存储"里看到它们，也占着磁盘）。

========== 两条安全红线（本模块最容易做错的地方）==========
① **普通启动绝不能删掉 `<temp>\ToolsGCP\` 整个目录**：
   那个目录里可能躺着**还没应用的更新包**（用户点过"稍后提醒"，下次启动还想用）。
   所以只有两个语义不同的入口：
     · `cleanup_temp_residues()` —— 只清"替换完之后的残留"
       （.bak / 日志 / 散落脚本 / 中间文件），**保留**仍然有效的更新包目录内容；
     · `cleanup_after_replace()` —— **替换已经走过**之后，才允许连根拔掉
       `<temp>\ToolsGCP\`。
② **绝不能碰 temp 根以外的任何东西，也绝不能碰名字不是 ToolsGCP 的文件**：
   每个要删的路径都要过一遍 `is_whitelisted()` 名字白名单校验，
   白名单只有：`ToolsGCP`（目录本身）、`ToolsGCP_new.exe`、`ToolsGCP.bak`、
   `ToolsGCP_update.log`、`apply_update.cmd`。

========== "替换是否已完成"怎么判断 ==========
新版进程启动时**无法知道**上一次替换到底成功没有（成功的话旧进程已经没了）。
所以做法是：`update.install_and_restart()` 在拉起 `apply_update.cmd` **之前**
先写一个标记文件 `<temp>\ToolsGCP\.replace-pending`（纯 ASCII，内容含目标 exe
与时间戳）。新版进程启动早期读到标记 = "上一次替换流程已经走过（无论成功失败）"，
此时更新包已经没有用处了 → 才允许连根删 `<temp>\ToolsGCP\`；标记读掉即删，
否则每次启动都当成"替换过"。
没有标记 = 从没触发过更新 → 只清残留，**不删更新包目录**。

========== 删不掉怎么办 ==========
文件被占用（替换脚本正在自删、句柄还没释放）时：先重试几轮，每轮之间短暂 sleep；
仍失败就用 Win32 `MoveFileExW(path, None, MOVEFILE_DELAY_UNTIL_REBOOT)`
（常量 0x00000004）登记"重启后删除" —— 与
`pymodels.core.self_update._delete_on_reboot` 同一个思路（见 self_update.py:351）。

========== 其它约定 ==========
· 只在 Windows 上干活，其它平台直接返回（不抛）。
· 整个函数体包 try/except：**清理失败绝不能打断启动**，只记日志。
· 不引入新依赖，不 import PyQt5。
"""

import base64
import os
import shutil
import stat
import sys
import threading
import time

# ----------------------------------------------------------------------
# 白名单（名字级）：只有精确属于 ToolsGCP 的东西才允许被删
# ----------------------------------------------------------------------
APP_TEMP_DIR_NAME = "ToolsGCP"          # <temp>\ToolsGCP\ 整个目录（更新包/脚本都在里面）
RESIDUE_FILE_NAMES = (                   # <temp> 根下的散落残留（精确文件名匹配）
    "ToolsGCP_new.exe",                  # 旧自更新器下载的新版 exe
    "ToolsGCP.bak",                      # 旧自更新器的 exe 备份
    "ToolsGCP_update.log",               # 旧自更新器的过程日志
    "apply_update.cmd",                  # 散落在 temp 根的替换脚本
)
REPLACE_MARKER_NAME = ".replace-pending"  # <temp>\ToolsGCP\ 下的"替换进行中"标记
UPDATE_SUBDIR_NAME = "update"              # <temp>\ToolsGCP\update\ —— 更新包目录
APPLY_SCRIPT_NAME = "apply_update.cmd"     # 替换脚本名（update\ 里的那份也会被重新生成）

# 白名单的小写副本：Windows 文件系统本身**大小写不敏感**，"ToolsGCP.bak" 和
# "toolsgcp.bak" 指的是同一个文件，所以判定要按小写比 —— 但仍然是**整名精确命中**，
# "ToolsGCP-notes.txt" 这种只沾前缀的依旧不在白名单里。
_WHITELIST_NAMES_LOWER = frozenset(
    [APP_TEMP_DIR_NAME.lower()] + [n.lower() for n in RESIDUE_FILE_NAMES])
MARKER_HEADER = "ToolsGCP replace-pending v1"

# ----------------------------------------------------------------------
# 删除行为参数
# ----------------------------------------------------------------------
MOVEFILE_DELAY_UNTIL_REBOOT = 0x00000004   # MoveFileExW 的"重启后删除"标志
DELETE_RETRY_ROUNDS = 3                     # 删不掉时重试几轮（占用是瞬时的，等一下就好）
DELETE_RETRY_WAIT_S = 0.4                   # 每轮之间的等待（秒）

# 默认延迟：替换脚本 apply_update.cmd 可能正在自删、文件句柄还没释放，
# 立刻删会失败（表现是"temp 里东西还在"）。等几秒成功率最高。
DEFAULT_CLEANUP_DELAY_S = 8.0

# 普通启动（residue 模式）要不要保留"断点续传凭据"（.part / .part.meta.json）。
# ⚠️ 默认保留：那两个文件是 update.py 的续传依据（_resume_offset），
#    删掉等于把用户已经下好的一大截进度扔了 —— 那是实打实的功能回退，
#    比 temp 里多留两个文件亏得多。真要清干净只有一种场合：
#    替换已经走过（full 模式，整棵树连根删）。
RESIDUE_KEEP_RESUMABLE = True

# 续传凭据（.part / .part.meta.json）最多保留多久。
# ⚠️ 为什么不"每次启动都删"：那两个文件是 update.py 的 _resume_offset 依据，
#    删掉等于把用户已经下好的一大截进度扔了（几百 MB 重下）——那是实打实的
#    功能回退，比 temp 里多留两个文件亏得多。
# ⚠️ 为什么又设个上限：失败的半成品（换了版本、换了镜像）对谁都没用了，
#    一直堆着只会白占磁盘。所以"最近还可能用"的留着，明显废弃的清掉。
RESIDUE_RESUMABLE_MAX_AGE_S = 7 * 24 * 3600

# "正在下载"的判定窗口：update\ 里若有最近修改过的 .part，说明**别的实例**
# 可能正在下载更新包 —— 这时候**绝不能**连根删 <temp>\ToolsGCP\。
ACTIVE_DOWNLOAD_WINDOW_S = 180

# update\ 里那份 apply_update.cmd 至少"静置"这么久才允许删。
# ⚠️ 为什么：cmd.exe 执行 .cmd 时**可能还会回头读脚本文件**，删掉正在跑的脚本
#    会让替换流程半路断掉（表现是"更新卡住、版本没换"）。而这份脚本每次安装前
#    都会由 update.py 重新生成，删掉完全没有副作用 —— 只是要避开"正在执行中"。
REPLACE_SCRIPT_MIN_AGE_S = 60


# ----------------------------------------------------------------------
# 日志（与 desktop/api/__init__.py 的 _log 同款封装风格，只是这层在 desktop 层，
# 自己 import pymodels.utils.logger；日志失败也绝不能抛）
# ----------------------------------------------------------------------
def _log(level: str, category_zh: str, category_en: str, message: str):
    """写日志；**绝不抛**（日志系统本身出问题时也不能连带影响启动）"""
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)(category_zh, category_en, message)
    except Exception:
        pass


# ----------------------------------------------------------------------
# 路径
# ----------------------------------------------------------------------
def _resolve_temp_root(temp_root: str = None) -> str:
    """系统临时目录（Windows 用 GetTempPathW，其它平台退回 tempfile）
    ⚠️ 允许外部传 `temp_root`：测试要在**工作区内**造假 temp 根，
       沙箱里的 %TEMP% 不可写，而且测试绝不能碰用户的真实临时目录。
    """
    if temp_root:
        try:
            return os.path.abspath(str(temp_root))
        except Exception:
            pass
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
        import tempfile
        return tempfile.gettempdir()
    except Exception:
        return os.environ.get("TEMP") or os.environ.get("TMP") or "."


def app_temp_dir(temp_root: str = None) -> str:
    r"""`<temp>\ToolsGCP\`（更新包目录 `update\` 就在它下面）"""
    return os.path.join(_resolve_temp_root(temp_root), APP_TEMP_DIR_NAME)


def marker_path(temp_root: str = None) -> str:
    r"""替换标记文件路径：`<temp>\ToolsGCP\.replace-pending`"""
    return os.path.join(app_temp_dir(temp_root), REPLACE_MARKER_NAME)


# ----------------------------------------------------------------------
# 白名单校验（**所有删除动作的前置关卡**）
# ----------------------------------------------------------------------
def _normalize(path: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(str(path)))
    except Exception:
        return ""


def is_whitelisted(path: str, temp_root: str = None) -> bool:
    """这个路径允许删吗？（名字白名单 + 位置白名单，双重校验）
    ⚠️ 必须是**精确匹配**：temp 根下任何叫 `ToolsGCP` 前缀但不完全一致的东西
       （比如用户的 `ToolsGCP-notes.txt`）都不许碰。
    ⚠️⚠️ 踩过的坑：**不能用** `_normalize()` 的结果去做"文件名相等"判断 ——
       Windows 上 `os.path.normcase` 会把整条路径**转成小写**，
       于是 `ToolsGCP.bak` 变成 `toolsgcp.bak`，和白名单里的原样字符串
       永远不相等 → 白名单形同虚设（表现为"该删的没删，还报'不在白名单内'"）。
       所以：**路径比较**用 normcase（大小写不敏感，符合 Windows 语义），
       **文件名比较**用原始大小写 + 小写白名单副本（仍然要求整名精确命中）。
    """
    try:
        root_raw = os.path.abspath(str(_resolve_temp_root(temp_root)))
        target_raw = os.path.abspath(str(path))
        if not root_raw or not target_raw:
            return False
        # 位置校验：必须**直接**躺在 temp 根下（normcase 只用于路径比较）
        if os.path.normcase(os.path.dirname(target_raw)) != os.path.normcase(root_raw):
            return False                       # 只允许 temp 根的**直接子项**
        base = os.path.basename(target_raw)
        return base.lower() in _WHITELIST_NAMES_LOWER
    except Exception:
        return False


def is_whitelisted_tree_member(path: str, temp_root: str = None) -> bool:
    r"""这个路径属于白名单里的 `<temp>\ToolsGCP\` **整棵目录树**吗？
    ⚠️ 白名单的第一条就是"`<temp>\ToolsGCP\` 整个目录（含 update\\ 子目录、
       更新包、apply_update.cmd、.part/.meta 中间文件）"——所以这棵树里的东西
       整体是被授权清理的；但**树外**的一切仍然一律不许碰。
    """
    try:
        root = _resolve_temp_root(temp_root)
        app_dir = os.path.join(root, APP_TEMP_DIR_NAME)
        return _is_inside(path, app_dir)
    except Exception:
        return False


def _age_s(path: str) -> float:
    """文件"多久没动了"（秒）；取不到就当成 0（= 刚动过 → 保守起见当作还要留）"""
    try:
        return max(0.0, time.time() - os.path.getmtime(path))
    except Exception:
        return 0.0


def _is_inside(path: str, base_dir: str) -> bool:
    """`path` 是否位于 `base_dir` 之内（防止有人把路径拼错后删到别处）"""
    try:
        target = _normalize(path)
        base = _normalize(base_dir)
        if not target or not base:
            return False
        return target == base or target.startswith(base + os.sep)
    except Exception:
        return False


# ----------------------------------------------------------------------
# 底层删除（重试 → 登记重启后删除）
# ----------------------------------------------------------------------
def _remove_tree(path: str):
    """递归删目录；只读文件先解除只读再删（否则永远删不掉）"""
    def _on_error(func, target, exc_info):
        try:
            os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
            func(target)
        except Exception:
            raise exc_info[1]

    if sys.version_info >= (3, 12):
        # 3.12 起 onerror 被 onexc 取代（onerror 仍能用但会告警）
        def _on_exc(func, target, exc):
            try:
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
                func(target)
            except Exception:
                raise exc
        shutil.rmtree(path, onexc=_on_exc)
    else:
        shutil.rmtree(path, onerror=_on_error)


def _schedule_delete_on_reboot(path: str) -> bool:
    """登记"重启后删除"（MoveFileExW + MOVEFILE_DELAY_UNTIL_REBOOT）
    ⚠️ 与 `pymodels.core.self_update._delete_on_reboot` 同一个思路；
       非管理员通常会失败（PendingFileRenameOperations 在 HKLM 下），失败就当没登记。
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                          wintypes.DWORD]
        kernel32.MoveFileExW.restype = wintypes.BOOL
        return bool(kernel32.MoveFileExW(str(path), None,
                                          MOVEFILE_DELAY_UNTIL_REBOOT))
    except Exception:
        return False


def _schedule_tree_on_reboot(path: str, is_dir: bool) -> bool:
    """给一棵目录树登记"重启后删除"（**自底向上**：先文件、后空目录）"""
    if not is_dir:
        return _schedule_delete_on_reboot(path)
    ok = True
    try:
        for base, dirs, files in os.walk(path, topdown=False):
            for name in files:
                if not _schedule_delete_on_reboot(os.path.join(base, name)):
                    ok = False
            for name in dirs:
                if not _schedule_delete_on_reboot(os.path.join(base, name)):
                    ok = False
    except Exception:
        ok = False
    if not _schedule_delete_on_reboot(path):
        ok = False
    return ok


def _delete_path(path: str, is_dir: bool):
    """删一个路径；返回 ('removed' | 'scheduled' | 'failed', 错误说明)"""
    last_error = ""
    for _ in range(max(1, DELETE_RETRY_ROUNDS)):
        try:
            if is_dir:
                _remove_tree(path)
            else:
                os.remove(path)
            return "removed", ""
        except FileNotFoundError:
            return "removed", ""
        except Exception as exc:                # noqa: BLE001
            last_error = repr(exc)
            # 占用是瞬时的（替换脚本正在自删）→ 等一下再试
            try:
                time.sleep(DELETE_RETRY_WAIT_S)
            except Exception:
                pass
    # 还是删不掉 → 登记重启后删除
    if _schedule_tree_on_reboot(path, is_dir):
        return "scheduled", last_error
    return "failed", last_error


# ----------------------------------------------------------------------
# 主体：按模式清一遍
# ----------------------------------------------------------------------
def _active_download(app_dir: str) -> bool:
    r"""`update\` 里有没有"刚刚还在动"的半成品？→ 说明**别的进程可能正在下载**
    ⚠️ 为什么要这道闸：多开一个 ToolsGCP 时，第二个进程启动早期也会跑清理。
       如果第一个实例此刻正在下载更新包（.part 一直在被写），第二个实例把
       `<temp>\ToolsGCP\` 连根删掉 = **把别人正在下的更新包抽走**，
       下载直接失败。判据用"最近修改时间"，比进程名可靠（下载线程在同一个进程里）。
    """
    try:
        update_dir = os.path.join(app_dir, UPDATE_SUBDIR_NAME)
        if not os.path.isdir(update_dir):
            return False
        for name in os.listdir(update_dir):
            if not name.lower().endswith(".part"):
                continue
            path = os.path.join(update_dir, name)
            if _age_s(path) < ACTIVE_DOWNLOAD_WINDOW_S:
                return True
    except Exception:
        return False
    return False


def _newest_update_mtime(app_dir: str) -> float:
    r"""`update\` 目录里最新的那个文件是什么时候写的（epoch 秒；没有就 0）
    ⚠️ 用途：判断"这个更新包是不是**替换标记之后**才下载的"。
       场景：上次替换失败了 → 标记还在 → 用户又下了一个新包 → 这时启动
       如果无脑连根删，新包也被误删（用户刚下几百 MB 就没了）。
       所以拿"包里最新文件的修改时间"和"标记里的时间戳"比：
       包比标记新 = 那是一次**全新的**更新流程 → 只能清残留、不能连根删。
    """
    newest = 0.0
    try:
        update_dir = os.path.join(app_dir, UPDATE_SUBDIR_NAME)
        if not os.path.isdir(update_dir):
            return 0.0
        for name in os.listdir(update_dir):
            path = os.path.join(update_dir, name)
            try:
                newest = max(newest, os.path.getmtime(path))
            except OSError:
                continue
    except Exception:
        return 0.0
    return newest


def _run_cleanup(root: str, mode: str) -> dict:
    r"""真正干活的清理函数
    mode = "residue"：只清残留，**保留** `<temp>\ToolsGCP\update\` 里仍然有效的更新包
    mode = "full"   ：替换已经走过 → 允许把 `<temp>\ToolsGCP\` 连根拔掉
    """
    result = {
        "ok": True,
        "mode": mode,
        "temp_root": root,
        "removed": [],
        "scheduled": [],
        "failed": [],
    }
    removed, scheduled, failed = result["removed"], result["scheduled"], result["failed"]

    def _handle(path: str, is_dir: bool):
        status, error = _delete_path(path, is_dir)
        if status == "removed":
            removed.append(path)
        elif status == "scheduled":
            scheduled.append(path)
        else:
            failed.append({"path": path, "error": error})

    # ---- ① temp 根下的散落残留（白名单精确匹配） ----
    for name in RESIDUE_FILE_NAMES:
        path = os.path.join(root, name)
        if not os.path.exists(path):
            continue
        if not is_whitelisted(path, root):
            failed.append({"path": path, "error": "不在白名单内，拒绝删除"})
            continue
        _handle(path, os.path.isdir(path))

    # ---- ② <temp>\ToolsGCP\ 目录 ----
    app_dir = os.path.join(root, APP_TEMP_DIR_NAME)
    if os.path.isdir(app_dir) and is_whitelisted(app_dir, root):
        if mode == "full":
            # ⚠️ 连根删之前先确认"没有别的进程正在下载"：
            #    多开场景下，第二个实例的清理不能把第一个实例正在下的更新包抽走。
            if _active_download(app_dir):
                result["skipped_active_download"] = True
                _log("info", "清理", "cleanup",
                     "检测到更新包正在下载（别的实例），本次不删 %TEMP%\\ToolsGCP 目录")
            else:
                _handle(app_dir, True)
        else:
            # residue 模式：**保留** update\（还没应用的更新包）与替换标记
            try:
                entries = list(os.listdir(app_dir))
            except OSError:
                entries = []
            for name in entries:
                if name == "update" or name == REPLACE_MARKER_NAME:
                    continue
                path = os.path.join(app_dir, name)
                # ⚠️ 每个要删的路径都必须过白名单校验（不能只靠"它在目录里"这一条）：
                #    先确认它确实落在 temp 根下 ToolsGCP 这棵白名单树里。
                if not is_whitelisted_tree_member(path, root):
                    continue
                _handle(path, os.path.isdir(path))
            # ---- ②-b update\ 目录里的**中间文件**（.part / .meta）----
            # ⚠️ 这里清的是"下载过程的半成品"，**不动真正的更新包**
            #    （那个 .exe 用户还没点安装，得留着）。
            update_dir = os.path.join(app_dir, UPDATE_SUBDIR_NAME)
            if os.path.isdir(update_dir) and _is_inside(update_dir, app_dir):
                try:
                    inner = list(os.listdir(update_dir))
                except OSError:
                    inner = []
                for name in inner:
                    low = name.lower()
                    path = os.path.join(update_dir, name)
                    if not is_whitelisted_tree_member(path, root):
                        continue
                    if name == APPLY_SCRIPT_NAME:
                        # 替换脚本：每次安装前都会重新生成，删掉没副作用，
                        # 但要避开"正在执行中"的那一份（见 REPLACE_SCRIPT_MIN_AGE_S）
                        if _age_s(path) >= REPLACE_SCRIPT_MIN_AGE_S:
                            _handle(path, os.path.isdir(path))
                        continue
                    if not (low.endswith(".part") or low.endswith(".meta")):
                        continue
                    if RESIDUE_KEEP_RESUMABLE and _age_s(path) < RESIDUE_RESUMABLE_MAX_AGE_S:
                        # ⚠️⚠️ 这里**故意不删**还"新鲜"的 .part / .part.meta.json：
                        #    这两个文件是"断点续传"的凭据（update.py 的 _resume_offset
                        #    靠它判断能不能接着下），网络失败后保留半成品是**有意为之**，
                        #    用户重开程序再点更新就能续传，不必从头下几百 MB。
                        #    普通启动把续传凭据删掉 = 白白丢掉已下载的进度，
                        #    比 temp 里多留两个文件亏得多。
                        #    真要删只有两种场合：① 替换已经走过（full 模式，整棵树都删）；
                        #    ② 这份半成品已经废弃到没人会续传（超过上面的保留上限）。
                        continue
                    _handle(path, os.path.isdir(path))
    return result


# ----------------------------------------------------------------------
# 替换标记
# ----------------------------------------------------------------------
def mark_replace_pending(target_exe: str = "", temp_root: str = None,
                         pid: int = None) -> str:
    r"""写"替换进行中"标记（**纯 ASCII**，路径用 base64 存，避免中文路径破坏 ASCII 约束）
    ⚠️ 必须在**拉起替换脚本之前**写：新版进程启动时读到这个标记，
       才知道"上一次替换流程已经走过"，才可以连根删 `<temp>\ToolsGCP\`。
    """
    root = _resolve_temp_root(temp_root)
    path = marker_path(root)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass
    try:
        encoded = base64.b64encode(
            str(target_exe or "").encode("utf-8")).decode("ascii")
    except Exception:
        encoded = ""
    try:
        current_pid = int(pid) if pid is not None else int(os.getpid())
    except Exception:
        current_pid = 0
    content = "\n".join([
        MARKER_HEADER,
        # ⚠️ 时间戳要带**小数**：用 int(time.time()) 会把秒截断，
        #    同一秒内写的更新包（mtime 带小数）看起来就比标记"更新"，
        #    会被误判成"用户重新下载过" → 白白不敢删那个目录。
        f"time={time.time():.3f}",
        f"pid={current_pid}",
        f"target_b64={encoded}",
    ]) + "\n"
    try:
        with open(path, "w", encoding="ascii", newline="\n") as handle:
            handle.write(content)
    except Exception as exc:                    # noqa: BLE001
        _log("warn", "更新", "update", f"写替换标记失败: {exc}")
        return ""
    return path


def has_replace_marker(temp_root: str = None) -> bool:
    """有没有"上次替换流程已经走过"的标记"""
    try:
        return os.path.isfile(marker_path(temp_root))
    except Exception:
        return False


def read_replace_marker(temp_root: str = None) -> dict:
    """**只读**标记（不删）：解析出时间戳/目标 exe/pid
    ⚠️ 为什么要"只读"这一档：标记的消费必须和"真的把目录删掉"**绑定** ——
       万一因为"包里还有新下载的更新包"而决定不删目录，这时标记**不能**被消费掉，
       否则下次启动就看不到标记，那个判断永远做不了第二次了。
    """
    path = marker_path(temp_root)
    info = {"path": path, "read": False, "target": "", "time": "", "pid": 0,
            "timestamp": 0.0}
    try:
        if not os.path.isfile(path):
            return info
        with open(path, "r", encoding="ascii", errors="replace") as handle:
            raw = handle.read()
        info["read"] = True
        for line in raw.splitlines():
            if line.startswith("time="):
                info["time"] = line[5:].strip()
                try:
                    info["timestamp"] = float(info["time"])
                except Exception:
                    info["timestamp"] = 0.0
            elif line.startswith("pid="):
                try:
                    info["pid"] = int(line[4:].strip())
                except Exception:
                    info["pid"] = 0
            elif line.startswith("target_b64="):
                try:
                    info["target"] = base64.b64decode(
                        line[11:].strip().encode("ascii")).decode("utf-8", "replace")
                except Exception:
                    info["target"] = ""
    except Exception as exc:                    # noqa: BLE001
        _log("warn", "更新", "update", f"读替换标记失败: {exc}")
    return info


def consume_replace_marker(temp_root: str = None) -> dict:
    """读掉并删除标记（**必须删**，否则每次启动都当成"替换过"）
    返回标记内容解析出来的信息（读不出来就给空 dict，不抛）。
    """
    info = read_replace_marker(temp_root)
    path = info["path"]
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except Exception as exc:                    # noqa: BLE001
        _log("warn", "更新", "update", f"删替换标记失败: {exc}")
    return info


# ----------------------------------------------------------------------
# 对外入口
# ----------------------------------------------------------------------
def cleanup_temp_residues(reason: str = "startup", delay_s: float = 0.0,
                          temp_root: str = None) -> dict:
    r"""清理"替换完之后的残留"（**保留**仍然有效的更新包目录内容）
    ⚠️ 语义与 `cleanup_after_replace()` 完全不同：普通启动只能调这个，
       它**不会**删掉 `<temp>\ToolsGCP\` 整个目录（那里可能有还没应用的更新包）。
    """
    try:
        if sys.platform != "win32":
            return {"ok": True, "skipped": True, "reason": "not-windows",
                    "mode": "residue", "removed": [], "scheduled": [], "failed": []}
        root = _resolve_temp_root(temp_root)
        delay = max(0.0, float(delay_s or 0.0))

        def _work():
            result = _run_cleanup(root, "residue")
            _log("info", "清理", "cleanup",
                 f"临时目录残留清理完成（{reason}）：删除 {len(result['removed'])} 项，"
                 f"重启后删除 {len(result['scheduled'])} 项，失败 {len(result['failed'])} 项")
            return result

        if delay > 0:
            # 延迟执行：替换脚本可能正在自删、句柄还没释放
            def _delayed():
                try:
                    time.sleep(delay)
                except Exception:
                    pass
                try:
                    _work()
                except Exception:
                    pass

            threading.Thread(target=_delayed, name="ToolsGCP-temp-clean",
                             daemon=True).start()
            return {"ok": True, "deferred": True, "delay_s": delay,
                    "mode": "residue", "removed": [], "scheduled": [], "failed": []}
        return _work()
    except Exception as exc:                    # noqa: BLE001 - 清理失败绝不影响启动
        _log("warn", "清理", "cleanup", f"清理临时目录残留失败（不影响启动）: {exc}")
        return {"ok": False, "error": str(exc), "mode": "residue",
                "removed": [], "scheduled": [], "failed": []}


def cleanup_after_replace(reason: str = "replace", delay_s: float = 0.0,
                          temp_root: str = None,
                          consume_marker: bool = True) -> dict:
    r"""**替换已经走过**之后的收尾：允许把 `<temp>\ToolsGCP\` 连根拔掉
    ⚠️ 只有在确认"替换流程已经触发过"（有 `.replace-pending` 标记）时才允许调这个，
       否则会误删用户还没应用的更新包。
    ⚠️ `consume_marker=False`：调用方**已经**消费过标记时用（标记在启动那一刻
       就该被读掉，不能等到延迟线程里才读）。
    """
    try:
        if sys.platform != "win32":
            return {"ok": True, "skipped": True, "reason": "not-windows",
                    "mode": "full", "removed": [], "scheduled": [], "failed": []}
        root = _resolve_temp_root(temp_root)
        delay = max(0.0, float(delay_s or 0.0))

        def _work():
            # ⚠️ 顺序：**先消费标记再删目录** —— 标记被读掉并删除后，
            #    就算后面的目录删除失败（文件被占用），也不会让"下次启动又当替换过"。
            marker_info = consume_replace_marker(root) if consume_marker else {
                "path": marker_path(root), "read": False, "target": "",
                "time": "", "pid": 0}
            result = _run_cleanup(root, "full")
            result["marker"] = marker_info
            _log("info", "清理", "cleanup",
                 f"替换后清理完成（{reason}）：删除 {len(result['removed'])} 项，"
                 f"重启后删除 {len(result['scheduled'])} 项，失败 {len(result['failed'])} 项")
            return result

        if delay > 0:
            def _delayed():
                try:
                    time.sleep(delay)
                except Exception:
                    pass
                try:
                    _work()
                except Exception:
                    pass

            threading.Thread(target=_delayed, name="ToolsGCP-temp-clean-full",
                             daemon=True).start()
            return {"ok": True, "deferred": True, "delay_s": delay,
                    "mode": "full", "removed": [], "scheduled": [], "failed": []}
        return _work()
    except Exception as exc:                    # noqa: BLE001
        _log("warn", "清理", "cleanup", f"替换后清理失败（不影响启动）: {exc}")
        return {"ok": False, "error": str(exc), "mode": "full",
                "removed": [], "scheduled": [], "failed": []}


def cleanup_on_startup(reason: str = "startup", delay_s: float = 0.0,
                        temp_root: str = None, allow_full: bool = True) -> dict:
    """启动早期的统一入口：按"有没有替换标记"决定清残留还是连根清
    ⚠️ `allow_full=False` 时**只清残留、不消费标记**：用于"检测到已有实例、
       马上要退出"的场合 —— 那个正在跑的实例可能正在下载更新包，
       连根删会误伤它。
    ⚠️⚠️ 判据（读标记 + 消费标记）**放在 worker 线程里做**，不是在本函数里：
       本函数是启动早期调用的，那时还不知道"会不会因为已有实例而立刻退出"。
       如果在本函数里就消费标记，而这个进程随后因为单实例检测退出了 →
       标记已经没了、目录却没被清 → 下次真正启动时看不到标记，
       那个陈旧的更新目录就永远留在 temp 里（正好是用户要消灭的东西）。
       放进 worker 线程后：进程提前退出 → 线程还没跑 → 标记原样保留，
       下次启动照样能识别出"替换过"并清掉。
    """
    try:
        if sys.platform != "win32":
            return {"ok": True, "skipped": True, "reason": "not-windows",
                    "mode": "startup", "removed": [], "scheduled": [], "failed": []}
        root = _resolve_temp_root(temp_root)
        delay = max(0.0, float(delay_s or 0.0))

        def _work():
            app_dir = os.path.join(root, APP_TEMP_DIR_NAME)
            marker_info = read_replace_marker(root)
            found = bool(marker_info.get("read"))
            # ⚠️⚠️ 判据一：标记里记的时间 vs update\ 里最新那个文件的时间。
            #    如果更新包比标记**还新** → 那是一次**全新的**下载（用户在上次替换
            #    失败之后又点了一次更新）→ 这时候连根删就是"把用户刚下好的几百 MB
            #    删了"，必须只清残留。反过来（包比标记旧）→ 包就是那次替换的
            #    原料，替换已经走过 → 可以连根拔掉。
            package_newer = False
            if found:
                stamp = float(marker_info.get("timestamp") or 0.0)
                newest = _newest_update_mtime(app_dir)
                # ⚠️ 留 2 秒容差：文件系统的时间戳精度不一定到毫秒，
                #    差几十毫秒就判"更新"会误伤（宁可多留一会儿目录）。
                package_newer = bool(stamp > 0 and newest > stamp + 2.0)
            if found and allow_full and not package_newer:
                # 先消费标记再删目录：标记被读掉并删除后，就算目录删除失败
                # （文件被占用），也不会让"下次启动又当替换过"。
                marker_info = consume_replace_marker(root)
                result = _run_cleanup(root, "full")
                result["marker"] = marker_info
                result["marker_found"] = True
                result["marker_consumed"] = True
            else:
                if found and package_newer:
                    # ⚠️ 标记**保留**（不消费）：这次的判断（"包是新的"）到下次启动
                    #    还得再做一次，所以标记不能被消费掉。
                    _log("info", "清理", "cleanup",
                         "更新包比替换标记还新（用户重新下载过），本次只清残留，"
                         "保留更新包目录")
                result = _run_cleanup(root, "residue")
                result["marker"] = marker_info
                result["marker_found"] = found
                result["marker_consumed"] = False
                result["package_newer"] = package_newer
            # 标记必须说三态：已消费 / 还在但这次不能连根删 / 压根没有。
            # 原来只按 marker_consumed 二值输出，于是「更新包比标记新、标记被特意留着」
            # 这种情形会报成「替换标记=无」—— 排查时会误判成「这台机器从没做过替换」，
            # 把最该看得见的一条线索说反了。
            if result.get("marker_consumed"):
                marker_note = "有(已消费)"
            elif result.get("marker_found"):
                marker_note = "有(本次保留，未消费)"
            else:
                marker_note = "无"
            _log("info", "清理", "cleanup",
                 f"启动清理完成（{reason}）：删除 {len(result['removed'])} 项，"
                 f"重启后删除 {len(result['scheduled'])} 项，"
                 f"失败 {len(result['failed'])} 项，"
                 f"替换标记={marker_note}")
            return result

        if delay > 0:
            def _delayed():
                try:
                    time.sleep(delay)
                except Exception:
                    pass
                try:
                    _work()
                except Exception:
                    pass

            threading.Thread(target=_delayed, name="ToolsGCP-temp-clean-startup",
                             daemon=True).start()
            return {"ok": True, "deferred": True, "delay_s": delay,
                    "mode": "startup", "removed": [], "scheduled": [], "failed": []}
        return _work()
    except Exception as exc:                    # noqa: BLE001
        _log("warn", "清理", "cleanup", f"启动清理失败（不影响启动）: {exc}")
        return {"ok": False, "error": str(exc)}
