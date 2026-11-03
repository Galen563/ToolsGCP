r"""用户数据根（.ToolsGCP）的定位、自愈与迁移 —— 语义和旧 py 版一致。
========== 这里到底管哪一批文件 ==========
只管**程序自己写出来的配置/数据**（就是 constants.DATA_DIR 那批）：
    toolsgcp_config.json / favorites.json / deploy_config.json / plugins.json /
    plugin_notes.json / announcements.json / privacy_policy.json / chats/ / plugin_data/ / logs/
**绝不搬**随程序发布的资源（它们永远留在程序目录旁的 .ToolsGCP 里）：
    ToolsGCP-Resources.json（用户明确说了不要动）、modules/（含 modules/languages）、
    images/、Icon/、logo.png、plugins/、backups/。
========== 两个东西的关系（用户需求，别搞反） ==========
1. `<用户主目录>\ToolsGCP.json`  —— **位置记录文件 / 指针**：里面写着"真正的 .ToolsGCP 在哪"
       {"data_root": "C:\\Users\\xxx\\.ToolsGCP", "version": 1}
   它**固定在用户主目录**，不随迁移改变位置。
2. `<数据根>` = 默认 `<用户主目录>\.ToolsGCP` —— **程序自动创建的数据目录**：
   上面那批配置/日志/对话就放这儿（"更改存储位置"迁的是它，不是程序目录旁的资源目录）。
⚠️ 程序目录旁的 `.ToolsGCP` 是**资源大本营**（modules/images/resources/plugins），
   永远不动、也不能被选作数据根（见 validate_target）。
指针丢了 / 坏了 / 指向的目录没了 → 自动回落到默认位置 `<用户主目录>\.ToolsGCP`，
并把它连同指针一起重建（需求："自动创建默认位置全新的 .ToolsGCP 文件夹"）。
========== 一次性反向迁移（老 web 用户，必须做，否则数据"像丢了"） ==========
此前 web 版把默认数据根错误地设成了**程序目录旁的 .ToolsGCP**，并把指针写成了它。
本版恢复 py 语义后，真实启动（home=None）时会检测：
    · 指针不存在，或指针正好指向程序目录旁的 .ToolsGCP（旧 web 版写进去的）；且
    · 程序目录 `.ToolsGCP/config` 或 `logs/` 里确实有数据；且
    · 用户主目录 `.ToolsGCP` 还没有 config/logs 数据（或只有空目录）
就把程序目录的 config/、logs/ **复制**到 `<用户主目录>\.ToolsGCP`（**不删源，留作备份**；
目标已有同名文件不覆盖），然后把指针改写为用户主目录。只复制 CONFIG_FILES / CONFIG_DIRS
白名单里的东西，资源文件一个都不碰。迁完指针指向用户主目录，下次启动不会再迁（幂等）。
⚠️ 反向迁移**不搬**两类"用户状态"文件（`_REVERSE_SKIP_FILES`）：
    · `privacy_policy.json`（隐私同意记录）——同意状态必须跟"当前数据根"同生共死，
      否则用户删掉数据根后，下次启动又会从程序目录的旧备份里把"已同意"搬回来；
    · `announcements.json`（公告已读状态）——同理，删掉数据根应让公告**全部重新未读**，
      否则旧备份里的 read_ids 会让"已读"复活（用户实测反馈的 bug）。
    这两条只影响"程序目录 → 用户主目录"的一次性反向迁移；设置页的"更改存储位置"
    和日常读写照常搬/写它们。
========== 公告已读状态（announcements.json）到底在哪（用户反复问） ==========
**只存在于当前数据根的 config/ 下**：`<数据根>/config/announcements.json`
    默认 = `<用户主目录>\.ToolsGCP\config\announcements.json`
（data_root 只负责"数据根在哪"；写文件的是 pymodels/core/announcements.py 的
  AnnouncementStore，AppShell 用 `AnnouncementStore()`，DATA_DIR = `<当前数据根>/config`。）
所以：
    · 用户删掉**设置 → 存储里显示的那个 .ToolsGCP** ⇒ announcements.json 一起没了
      ⇒ 下次启动 read_ids=[] ⇒ 所有公告重新未读、重新弹窗（这是正确行为，有测试）；
    · 程序目录旁 `.ToolsGCP` 里的旧 announcements.json 备份不会被反向迁移搬回来
      （`_REVERSE_SKIP_FILES`，另有一道"迁移后兜底删除"的防御）；
    · 只删**旧的**数据根（改过存储位置之后）不会重置已读，因为状态已经跟着新根走了。
========== 隐私同意记录（privacy_policy.json）到底在哪（用户反复问） ==========
**只存在于当前数据根的 config/ 下**：`<数据根>/config/privacy_policy.json`
    默认 = `<用户主目录>\.ToolsGCP\config\privacy_policy.json`
（data_root 只负责"数据根在哪"；写文件的是 desktop/native/privacy_state.py，
  AppShell 用 `PrivacyState(DATA_DIR)`，DATA_DIR = `<当前数据根>/config`。）
所以：
    · 用户删掉**设置 → 存储里显示的那个 .ToolsGCP** ⇒ privacy_policy.json 一起没了
      ⇒ 下次启动 `is_valid()` 必然 False ⇒ 前端重新弹隐私政策（这是正确行为，有测试）；
    · 程序目录旁 `.ToolsGCP` 是资源目录，里面就算还留着旧备份也不会被搬回来
      （`_REVERSE_SKIP_FILES`，另有一道"迁移后兜底删除"的防御）；
    · 只删**旧的**数据根（改过存储位置之后）不会重置同意，因为记录已经跟着新根走了。
========== 设置页更改存储位置= 真剪切 + 残留清理（用户需求） ==========
。所以 `migrate_data_root()` 按**剪切**语义：
    · 白名单（CONFIG_FILES / CONFIG_DIRS）里的配置、chats、plugin_data、logs 搬到新根后，
      **旧根里必须没有它们**；目标已有同名文件 → 保留目标、删掉源文件；
    · 目标已有同名目录 → 递归合并搬（绝不覆盖目标里已有的文件）；
    · `logs/system_log.log` 被 logger 长期打开（Windows 上 rename 会失败）→ 本次跳过，
      写 `<新数据根>/config/.pending_migration_cleanup.json`；下次启动
      `ensure_user_data_root()` 会把这批残留补搬完，然后清理旧根；
    · 搬完旧根若只剩空目录 → 整个删掉；旧根若**是程序资源目录**
      （modules/images/资源库/插件），只删空掉的 config/logs，**绝不删根**，资源一个都不动。
⚠️ 本模块**不 import PyQt**：设置页的迁移进度条要靠它，而它也要能在无 GUI 环境下测试。
⚠️ 任何函数都不向上抛异常：定位失败一律退回一个可用的路径。
"""

import json
import os
import shutil
import threading
import time

# 指针文件名（用户主目录下）
POINTER_NAME = "ToolsGCP.json"
POINTER_VERSION = 1

# 默认数据目录名（用户主目录下）
DATA_DIR_NAME = ".ToolsGCP"

# 隐私同意记录的文件名（相对数据根的 config/）。
# ⚠️ 它必须**只属于当前数据根**：删数据根 = 重新同意；反向迁移绝不复制它。
CONSENT_FILE = "privacy_policy.json"

# 公告已读状态的文件名（相对数据根的 config/；和 announcements.STORE_FILENAME 一致）。
# ⚠️ 同理：删数据根 = 公告全部重新未读；反向迁移绝不复制它。
#    这里写字面量而不是 import announcements：constants → data_root 已在导入链上，
#    反向 import 会成环（而且 announcements 自己就 import constants.DATA_DIR）。
ANNOUNCEMENTS_FILE = "announcements.json"

# 需要搬迁/管理的"配置类"条目（相对用户数据根）。
# ⚠️ 只有这些会被搬；资源类文件一律不在表里 —— 这张表就是"只搬配置文件"的硬边界。
CONFIG_FILES = (
    "toolsgcp_config.json",
    "favorites.json",
    "deploy_config.json",
    "plugins.json",
    "plugin_notes.json",
    ANNOUNCEMENTS_FILE,
    CONSENT_FILE,
)
CONFIG_DIRS = (
    "chats",
    "plugin_data",
    "logs",
    # ⚠️ 用户自己装的插件：`<数据根>\plugins`（顶层目录，和 logs/ 一样不放在 config/ 下）
    #    它跟 config/ 里那些"程序自动产出的配置"不同 —— 里面是**用户/开发者放进去的
    #    插件代码**，属于用户资产，所以数据根迁移时必须跟着走，不能丢。
    #    ⚠️ 反向迁移（程序目录 → 用户主目录）时**必须跳过**它（见 _REVERSE_SKIP_DIRS）：
    #       程序目录旁的 plugins/ 是随包发布的官方插件，复制进用户根会让官方插件
    #       被"用户版本"遮住，以后升级程序时新版本插件反而加载不到。
    "plugins",
)

# 老位置里可能出现的散落文件名（早期版本直接放在 .ToolsGCP 根下）
_LEGACY_NAMES = CONFIG_FILES

# 上次迁移没搬完的"待清理清单"文件名（放在数据根的 config/ 下）
PENDING_CLEANUP_NAME = ".pending_migration_cleanup.json"
PENDING_CLEANUP_VERSION = 2

# 反向迁移（旧 web 数据：程序目录 → 用户主目录）**不搬**的条目：
# 这些是"用户的当前状态"，必须跟当前数据根同生共死 —— 否则删掉数据根后，
# 下次启动又会从程序目录的旧备份把它们搬回来，用户会看到
# "隐私已经同意过 / 公告已经全读过"（两个都踩过）。
_REVERSE_SKIP_FILES = (CONSENT_FILE, ANNOUNCEMENTS_FILE)
# 反向迁移同样**不搬**的目录：程序目录旁的 plugins/ 是随包发布的**官方插件**，
# 复制进用户根会让它们变成"用户版本"而遮住以后的官方更新（plugins_dirs() 里
# 用户根优先级更高），属于典型的"越迁越坏"。用户插件只存在于数据根，不需要搬。
_REVERSE_SKIP_DIRS = ("plugins",)


def consent_file_path(root: str) -> str:
    """某个数据根下的隐私同意记录路径：`<root>/config/privacy_policy.json`
    只是路径计算（不建目录、不写文件）；真正的读写由 desktop/native/privacy_state.py 负责。
    """
    return os.path.join(str(root or ""), "config", CONSENT_FILE)


def announcements_file_path(root: str) -> str:
    """某个数据根下的公告已读状态路径：`<root>/config/announcements.json`
    只是路径计算（不建目录、不写文件）；真正的读写由 pymodels/core/announcements.py 负责。
    """
    return os.path.join(str(root or ""), "config", ANNOUNCEMENTS_FILE)


def _log_info(message: str):
    _emit_log("info", message)


def _log_warn(message: str):
    _emit_log("warn", message)


# ⚠️ 为什么日志要"排队补写"：
#    真实启动时的定位发生在 constants.py 的导入中途（它 import 本模块后就立刻调
#    ensure_user_data_root()），而 pymodels.utils.logger 自己又 `from ..constants import LOGS_DIR`
#    —— 这时候 constants 还没执行到 LOGS_DIR，logger import 必然失败。直接 pass 会让
#    "旧数据已迁移"这条**一次性**记录永远丢失（下次启动不会再迁移，也就不会再记）。
#    所以这里把写不进去的日志先攒着，起一个守护线程等 logger 真正可用后补写。
_PENDING_LOGS = []
_PENDING_LOCK = threading.Lock()
_FLUSH_THREAD_STARTED = [False]


def _logger_module():
    """拿 logger 模块；constants 导入中途拿不到时返回 None（原因见上面注释）"""
    try:
        from ..utils import logger as logger_module
        return logger_module
    except Exception:
        return None


def _emit_log(level: str, message: str):
    _flush_pending_logs()
    module = _logger_module()
    if module is not None:
        try:
            getattr(module.log, level)("数据目录", "data_root", message)
            return
        except Exception:
            pass
    with _PENDING_LOCK:
        _PENDING_LOGS.append((level, message))
    _start_flush_thread()


def _flush_pending_logs() -> bool:
    """把积压的日志写进 logger；返回 True = 队列已清空（或本来就没东西）"""
    with _PENDING_LOCK:
        if not _PENDING_LOGS:
            return True
        module = _logger_module()
        if module is None:
            return False
        pending, _PENDING_LOGS[:] = list(_PENDING_LOGS), []
    for level, message in pending:
        try:
            getattr(module.log, level)("数据目录", "data_root", message)
        except Exception:
            pass
    return True


def _start_flush_thread():
    """起一次性守护线程，等 logger 可用后补写启动期积压的日志（最多等 30 秒）"""
    with _PENDING_LOCK:
        if _FLUSH_THREAD_STARTED[0]:
            return
        _FLUSH_THREAD_STARTED[0] = True

    def _worker():
        deadline = time.time() + 30.0
        while time.time() < deadline:
            if _flush_pending_logs():
                return
            time.sleep(0.1)

    try:
        threading.Thread(target=_worker, name="ToolsGCP-data-root-log",
                         daemon=True).start()
    except Exception:
        pass


# ==================== 迁移期间"关掉日志又打开" ====================
# ⚠️ 为什么需要（我希望最后原版的 .ToolsGCP 配置文件被删除而新位置还照常包含所有内容）：
#    `logs/system_log.log` 被 logger **长期打开**（append 模式）。Windows 上一个被打开的
#    文件既不能改名也不能删除 → 迁移时它必然搬不动 → 旧根删不掉 →
#    程序输出本次有 1 项被占用（logs/system_log.log），下次启动会自动完成剩余迁移。
#    而"下次启动"也搬不动：constants 导入期会先建 logger（打开日志文件），
#    再调 ensure_user_data_root() 补搬 —— 顺序正好反了，文件又被占住了。
#   根治办法：**搬 logs 之前把日志文件句柄关掉，搬完再打开**。
#    关掉句柄期间日志会"写不进去"（logger 的 log() 对写失败是静默吞掉的，
#    不会抛也不会刷屏）—— 这段时间本来就在搬数据，日志丢几条无所谓。
_LOG_RELEASE_LOCK = threading.RLock()


def _release_log_file():
    """把日志文件句柄关掉（让 Windows 允许搬走/删除它）；返回 True = 之前是开着的
    ⚠️ 关掉之后 logger 还活着，只是 `log._file` 变成 None → 写日志会静默失败。
       搬完必须调 `_reopen_log_file()` 把它重新打开（见下面）。
    """
    try:
        module = _logger_module()
        if module is None:
            return False
        handle = getattr(module.log, "_file", None)
        if handle is None:
            return False
        module.log.close()
        return True
    except Exception:
        return False


def _reopen_log_file():
    """日志句柄被关掉后重新打开（指向**当前**数据根的 logs/system_log.log）
    ⚠️ 必须在数据根已经切换之后调用：常量 LOGS_DIR 是导入期算好的，
       迁移改了指针 → constants.LOGS_DIR 还是**旧**根的路径。
       所以这里优先用当前生效的数据根重算 logs 目录，
       只有拿不到时才退回 constants.LOGS_DIR。
    """
    try:
        module = _logger_module()
        if module is None:
            return False
        handle = getattr(module.log, "_file", None)
        if handle is not None:
            return True                      # 还开着（没关过）
        target = ""
        try:
            target = os.path.join(resolve_data_root(), "logs")
        except Exception:
            target = ""
        if not target:
            try:
                from ..constants import LOGS_DIR
                target = LOGS_DIR
            except Exception:
                return False
        try:
            os.makedirs(target, exist_ok=True)
            os.makedirs(os.path.join(target, "history"), exist_ok=True)
        except Exception:
            pass
        # ⚠️ current_path 要一起改：logger 用它算归档/历史目录，
        #    不改的话新日志会继续写回**旧**根的日志文件（那就白搬了）。
        module.log.current_path = os.path.join(target, "system_log.log")
        # ⚠️ 归档/清理历史日志用的常量也一起指到新根 ——
        #    它们是导入期从 constants 取的，还指着旧根（迁移后旧根会被删掉）。
        try:
            module.LOGS_DIR = target
            module.LOG_HISTORY_DIR = os.path.join(target, "history")
        except Exception:
            pass
        module.log._open_current()
        return True
    except Exception:
        return False


class _LogFileReleased:
    """上下文管理器：进入时关掉日志句柄，退出时**一定**重新打开
    ⚠️ 用 try/finally 的上下文管理器而不是裸的 try/finally ——
       搬日志的代码路径有好几处（正常迁移 / 补搬残留），
       每处都手写 try/finally 容易漏掉其中一条 → 日志就此不再写盘。
    """

    def __init__(self, enabled: bool = True):
        self.enabled = bool(enabled)
        self.released = False

    def __enter__(self):
        if not self.enabled:
            return self
        with _LOG_RELEASE_LOCK:
            self.released = _release_log_file()
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self.enabled or not self.released:
            return False
        with _LOG_RELEASE_LOCK:
            _reopen_log_file()
        return False


# ==================== 主目录 ====================

def home_dir() -> str:
    """当前用户的**主目录**（自适应，绝不写死 C:\\Users\\Administrator）
    顺序：USERPROFILE → HOMEDRIVE+HOMEPATH → os.path.expanduser("~") → 当前盘根。
    """
    for getter in (
        lambda: os.environ.get("USERPROFILE"),
        lambda: ((os.environ.get("HOMEDRIVE") or "") + (os.environ.get("HOMEPATH") or "")),
    ):
        try:
            value = getter()
            if value and os.path.isdir(value):
                return os.path.abspath(value)
        except Exception:
            continue
    try:
        expanded = os.path.expanduser("~")
        if expanded and expanded != "~" and os.path.isdir(expanded):
            return os.path.abspath(expanded)
    except Exception:
        pass
    # 最后的兜底：老行为（程序目录），至少保证程序能启动
    try:
        from ..constants import SCRIPT_DIR
        return SCRIPT_DIR
    except Exception:
        return os.getcwd()


def default_data_root(home: str = None) -> str:
    r"""默认数据根：`<home or 用户主目录>\.ToolsGCP`（和 py 版完全一致）
    ⚠️ 这里**不许**再看程序目录、不许再"程序目录优先"：程序目录旁的 .ToolsGCP 是资源大本营
       （modules/images/resources/plugins），用户数据必须落在用户主目录，见模块开头说明。
    ⚠️ home 参数必须一路透传：测试会把"假主目录"传进来，绝不能悄悄回落到真实主目录
       （否则测试会往用户的真实配置目录里写垃圾）。
    """
    return os.path.join(home or home_dir(), DATA_DIR_NAME)


def program_data_root() -> str:
    """程序目录旁的 .ToolsGCP —— **资源大本营**（modules/images/resources/plugins）
    ⚠️ 它**不是**用户数据根。只允许两种用法：
       ① 一次性反向迁移时的**源**（旧 web 版误把它当数据根）；
       ② validate_target() 里"禁止把数据根设成资源目录"的校验。
       其它地方一律不要拿它当数据根。
    """
    try:
        from ..constants import SCRIPT_DIR
        return os.path.join(SCRIPT_DIR, DATA_DIR_NAME)
    except Exception:
        return ""


def pointer_file_path(home: str = None) -> str:
    """指针文件 ToolsGCP.json 的完整路径（**固定在用户主目录**，不随迁移改变）"""
    return os.path.join(home or home_dir(), POINTER_NAME)


# ==================== 小工具 ====================

def _same_path(left: str, right: str) -> bool:
    """两个路径是不是同一个（忽略大小写 / 相对路径差异）"""
    if not left or not right:
        return False
    try:
        return (os.path.normcase(os.path.abspath(left))
                == os.path.normcase(os.path.abspath(right)))
    except Exception:
        return False


def _dir_has_content(path: str) -> bool:
    """目录存在且里面有东西（空目录不算）"""
    try:
        return os.path.isdir(path) and bool(os.listdir(path))
    except Exception:
        return False


def _has_user_data(root: str) -> bool:
    """root 下 config/ 或 logs/ 里有没有真正的用户数据（空目录不算）"""
    if not root:
        return False
    return (_dir_has_content(os.path.join(root, "config"))
            or _dir_has_content(os.path.join(root, "logs")))


def _is_within(child: str, parent: str) -> bool:
    """child 是否等于 parent 或位于 parent 里面（不区分大小写）
    用途：拦住"把新数据根选在当前数据根里面"这种自我嵌套（搬完再删旧根会把新数据一起删掉）。
    """
    if not child or not parent:
        return False
    try:
        child_abs = os.path.normcase(os.path.abspath(child))
        parent_abs = os.path.normcase(os.path.abspath(parent))
        return (child_abs == parent_abs
                or child_abs.startswith(parent_abs + os.sep))
    except Exception:
        return False


def _tree_has_files(root: str) -> bool:
    """目录树里还有没有文件（只看文件，空目录不算）"""
    try:
        for _base, _dirs, files in os.walk(root):
            if files:
                return True
    except Exception:
        pass
    return False


def _count_files(root: str) -> int:
    """目录树里一共有多少个文件（用来在报告里说"还剩几个残留"）"""
    count = 0
    try:
        for _base, _dirs, files in os.walk(root):
            count += len(files)
    except Exception:
        pass
    return count


def _remove_path(path: str):
    """删文件/删目录（失败只记日志，不抛）"""
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    except Exception as exc:
        _log_warn(f"删除 {path} 失败: {exc}")


def _remove_empty_dir(path: str):
    """只删空目录（非空会抛异常，这里吞掉）"""
    try:
        os.rmdir(path)
    except Exception:
        pass


def _rename_path(src: str, dst: str) -> bool:
    """用改名方式搬（同卷最快、不复制数据）；能改成功返回 True
    ⚠️ 目标必须不存在（调用方保证）：os.replace 在 Windows 上会覆盖同名文件，绝不能误覆盖。
    """
    try:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        os.replace(src, dst)
        return True
    except OSError:
        return False


def _move_file(src: str, dst: str) -> None:
    """搬一个文件：os.replace 优先；跨盘 / 被占用退回复制+删除（删不掉会抛异常）
    ⚠️ 被 logger 打开的 `logs/system_log.log` 在 Windows 上 rename/remove 都会失败，
       异常交给调用方记进"待下次启动清理"清单。
    """
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    try:
        os.replace(src, dst)
        return
    except OSError:
        pass
    shutil.copy2(src, dst)
    os.remove(src)


# ==================== 指针读写 ====================

def load_pointer(home: str = None) -> str:
    """读指针，返回它记录的数据根（读不到 / 坏了 / 指向的目录不存在 → 返回空串）
    ⚠️ 只负责"读"，不在里面建目录 —— 建目录由 ensure_user_data_root() 做。
    """
    path = pointer_file_path(home)
    try:
        if not os.path.isfile(path):
            return ""
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            value = str(data.get("data_root") or "").strip()
        elif isinstance(data, str):
            value = data.strip()
        else:
            value = ""
        if not value:
            return ""
        value = os.path.abspath(os.path.expandvars(os.path.expanduser(value)))
        return value if os.path.isdir(value) else ""
    except Exception:
        return ""


def save_pointer(data_root: str, home: str = None) -> bool:
    """写指针（原子写：临时文件 + os.replace）；失败返回 False，不抛异常"""
    path = pointer_file_path(home)
    payload = {
        "data_root": os.path.abspath(str(data_root or "")),
        "version": POINTER_VERSION,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as exc:
        _log_warn(f"写指针 {path} 失败: {exc}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


# ==================== 一次性反向迁移（旧 web 版 → 用户主目录） ====================

def _copy_tree_without_overwrite(src: str, dst: str) -> int:
    """递归复制目录：**目标已有的同名文件一律跳过**；返回复制了几个文件
    为什么不直接 copytree(dirs_exist_ok=True)：那会覆盖目标里已有的文件，
    而迁移目标（用户主目录）可能有用户后来写的新数据。宁可少搬，不许覆盖。
    """
    copied = 0
    try:
        for base, _dirs, files in os.walk(src):
            rel = os.path.relpath(base, src)
            target_dir = dst if rel in (".", "") else os.path.join(dst, rel)
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception as exc:
                _log_warn(f"创建目录 {target_dir} 失败: {exc}")
                continue
            for name in files:
                source_file = os.path.join(base, name)
                target_file = os.path.join(target_dir, name)
                if os.path.exists(target_file):
                    continue
                try:
                    shutil.copy2(source_file, target_file)
                    copied += 1
                except Exception as exc:
                    _log_warn(f"复制 {source_file} → {target_file} 失败: {exc}")
    except Exception as exc:
        _log_warn(f"遍历 {src} 失败: {exc}")
    return copied


def _copy_whitelisted(src_root: str, dst_root: str, skip_files=(), skip_dirs=()) -> int:
    """只把 CONFIG_FILES / CONFIG_DIRS 白名单里的条目从 src_root 复制到 dst_root
    skip_files：再次排除的文件名（反向迁移时用来跳过隐私同意记录，见模块开头）。
    skip_dirs：再次排除的目录名（反向迁移时跳过"用户插件目录"，见 _REVERSE_SKIP_DIRS）。
    ⚠️ 这是"绝不搬资源"的执行点：函数里没有任何兜底的"整个目录复制"分支。
    """
    copied = 0
    config_dst = os.path.join(dst_root, "config")
    for name in CONFIG_FILES:
        if name in skip_files:
            continue
        source_file = ""
        for rel in (os.path.join("config", name), name):   # 兼容早期直接放根下
            candidate = os.path.join(src_root, rel)
            if os.path.isfile(candidate):
                source_file = candidate
                break
        if not source_file:
            continue
        target_file = os.path.join(config_dst, name)
        if os.path.exists(target_file):
            continue
        try:
            os.makedirs(config_dst, exist_ok=True)
            shutil.copy2(source_file, target_file)
            copied += 1
        except Exception as exc:
            _log_warn(f"复制 {source_file} → {target_file} 失败: {exc}")
    for name in CONFIG_DIRS:
        if name == "logs":
            source_dir = os.path.join(src_root, "logs")
            target_dir = os.path.join(dst_root, "logs")
        elif name == "plugins":
            # ⚠️ 用户插件是**顶层目录**（`<数据根>\plugins`），不是 config/plugins。
            #    并且它**永远不参与反向迁移**（源是程序目录 = 随包发布的官方插件，
            #    复制过去反而会遮住官方版本），所以在 _migrate_program_data_to_home_once
            #    里通过 skip_dirs 传进来跳过；这里只负责"正向迁移（用户换数据根）"时搬走。
            if name in skip_dirs:
                continue
            source_dir = os.path.join(src_root, "plugins")
            target_dir = os.path.join(dst_root, "plugins")
        else:
            source_dir = os.path.join(src_root, "config", name)
            if not os.path.isdir(source_dir):
                source_dir = os.path.join(src_root, name)
            target_dir = os.path.join(config_dst, name)
        if os.path.isdir(source_dir):
            copied += _copy_tree_without_overwrite(source_dir, target_dir)
    return copied


def _migrate_program_data_to_home_once() -> bool:
    r"""一次性反向迁移：程序目录旁 .ToolsGCP 里的用户数据 → `<用户主目录>\.ToolsGCP`
    为什么需要它：此前 web 版把默认数据根错误地设成了程序目录旁的 .ToolsGCP，还把指针
    写成了它；本版恢复 py 语义后，如果直接按指针/默认走，老用户的配置与历史对话会"凭空消失"。
    什么时候迁（四个条件同时满足）：
        ① 指针不存在，或指针正好指向程序目录旁的 .ToolsGCP（旧 web 版写进去的）；
        ② 程序目录 `.ToolsGCP/config` 或 `logs/` 里确实有数据；
        ③ 用户主目录 `.ToolsGCP` 还没有 config/logs 数据（空目录不算）；
        ④ 用户主目录可写。
    迁什么：只复制 config/ 与 logs/ 里的白名单条目（CONFIG_FILES / CONFIG_DIRS），
            **不删源**（那是备份），**不覆盖**目标已有文件，资源文件一个不搬。
            ⚠️ 两类"用户当前状态"**例外**：不搬（见 `_REVERSE_SKIP_FILES`）——
               `privacy_policy.json`（隐私同意记录）与 `announcements.json`（公告已读状态）。
               否则"用户删了数据根 → 重新同意 / 公告重新未读"会被程序目录里的旧备份破坏。
    结果：指针改写为用户主目录 —— 下次启动指针已是用户主目录，条件①不成立，天然幂等。
    返回 True 表示这次真的迁移了（写了指针）。
    """
    try:
        program = program_data_root()
        if not program or not os.path.isdir(program):
            return False
        home_root = default_data_root()          # home=None → 真实用户主目录
        if _same_path(program, home_root):
            return False                         # 程序目录 == 主目录（罕见），没什么可迁
        pointer = load_pointer()
        pointer_on_program = bool(pointer) and _same_path(pointer, program)
        if pointer and not pointer_on_program:
            # 指针指着用户自己选的位置：那是用户意图，不许动、不许往主目录塞数据
            return False
        if not _has_user_data(program):
            return False                         # 程序目录里只有资源，没有可迁的用户数据
        if _has_user_data(home_root):
            # 用户主目录里已经有数据（可能是 py 版留下的）：不复制，避免两套数据打架。
            # 指针仍指着程序目录时，也保持原样 —— 换成主目录反而会让当前数据"消失"。
            _log_info(f"用户主目录已有数据（{home_root}），跳过一次性反向迁移")
            return False
        try:
            os.makedirs(home_root, exist_ok=True)
        except Exception as exc:
            _log_warn(f"无法创建用户数据根 {home_root}（{exc}），跳过一次性反向迁移")
            return False
        _ensure_subdirs(home_root)
        # 防御：反向迁移**永远不恢复"用户当前状态"文件**（隐私同意记录 / 公告已读状态）——
        # 删了数据根就必须重新同意、公告重新未读。
        # 正常路径靠 `_REVERSE_SKIP_FILES` 跳过；万一以后有人改了白名单/复制逻辑，
        # 这里在复制完再兜一道（只有"复制前不存在、复制后冒出来"才删）。
        protected = {name: os.path.isfile(os.path.join(home_root, "config", name))
                     for name in _REVERSE_SKIP_FILES}
        copied = _copy_whitelisted(program, home_root, skip_files=_REVERSE_SKIP_FILES,
                                   skip_dirs=_REVERSE_SKIP_DIRS)
        for name, existed_before in protected.items():
            restored_path = os.path.join(home_root, "config", name)
            if existed_before or not os.path.isfile(restored_path):
                continue
            try:
                os.remove(restored_path)
                _log_warn(f"反向迁移意外带回了 {name}，已删除"
                          f"（删除数据根后隐私/公告状态必须重新开始）")
            except Exception as exc:
                _log_warn(f"删除迁移带回来的 {name} 失败（请手动删除 {restored_path}）：{exc}")
        if not save_pointer(home_root):
            _log_warn(f"旧数据已复制到 {home_root}，但写入 ToolsGCP.json 失败（下次启动会重试）")
            return False
        _log_info(f"旧数据已从程序目录迁移到用户目录：{program} → {home_root}"
                  f"（复制 {copied} 个文件，源目录保留作备份，资源文件未动；"
                  f"隐私同意记录 / 公告已读状态不搬，需在新数据根重新开始）")
        return True
    except Exception as exc:
        _log_warn(f"一次性反向迁移失败（继续按指针/默认位置走）：{exc}")
        return False


# ==================== 解析 / 自愈 ====================

def resolve_data_root(home: str = None) -> str:
    """算出"现在到底该用哪个数据根"（只算不建）：指针优先，坏了/丢了回默认
    ⚠️ 和 `ensure_user_data_root` 用同一套判断（否则设置页显示的路径会和实际用的不一致）。
       不看程序目录：程序目录旁 .ToolsGCP 是资源，不是数据根。
    """
    pointer = load_pointer(home)
    if pointer:
        return pointer
    return default_data_root(home)


def ensure_user_data_root(home: str = None) -> str:
    r"""保证数据根存在并可用；返回最终生效的路径
    - 指针有效 → 用它（目录不在就建出来）；
    - 指针缺失/损坏 → 用默认位置 `<用户主目录>\.ToolsGCP`，建目录 + **重建指针**；
    - 目标不可写（权限/盘符没了）→ 退回程序目录再试一次（最后的兜底，别让程序起不来）。
    - **真实启动（home=None）先做一次**"旧 web 数据（程序目录）→ 用户主目录"的反向迁移，
      见 `_migrate_program_data_to_home_once`。
    - 每次启动都会补完**上次迁移被占用**的残留（待清理清单，多为 logs/system_log.log），
      补完顺手删掉旧数据目录；见 `_complete_pending_cleanup`。
    """
    if home is None:
        _migrate_program_data_to_home_once()
    try:
        root = load_pointer(home)
    except Exception:
        root = ""
    if root:
        try:
            os.makedirs(root, exist_ok=True)
            _ensure_subdirs(root)
            _safe_complete_pending_cleanup(root)  # 上次迁移的残留（被占用的日志），这次补完
            return root
        except Exception as exc:
            _log_warn(f"指针指向的数据根不可用（{root}）：{exc}，回落到默认位置")

    root = default_data_root(home)
    try:
        os.makedirs(root, exist_ok=True)
    except Exception as exc:
        _log_warn(f"创建默认数据根 {root} 失败: {exc}")
        # 用户主目录彻底不可写：退回程序目录，至少别让程序起不来
        fallback = program_data_root()
        if fallback:
            try:
                os.makedirs(fallback, exist_ok=True)
                root = fallback
            except Exception:
                pass
    try:
        _ensure_subdirs(root)
        save_pointer(root, home)      # 重建/修正指针
        _safe_complete_pending_cleanup(root)
    except Exception:
        pass
    return root


def _ensure_subdirs(root: str):
    """把数据根下的目录建好（失败不抛）
    真实布局（和 constants 保持一致）：
        <root>/config/            ← 所有配置文件
        <root>/config/chats/      ← 对话历史
        <root>/config/plugin_data/
        <root>/logs/
        <root>/plugins/           ← 用户/开发者自己装的插件（默认为空，见 plugins_dirs()）
    ⚠️ plugins/ 必须**自动建出来**：exe 打包后程序目录旁的 .ToolsGCP/plugins 在 exe 本体里
       摸不到，开发者/用户唯一能放插件的地方就是这个目录 —— 目录不存在的话
       "把插件拷进去"这一步就无从下手（用户得自己猜路径、自己新建）。
    """
    for rel in (os.path.join("config", "chats"),
                os.path.join("config", "plugin_data"),
                "logs",
                os.path.join("logs", "history"),
                "plugins"):
        try:
            os.makedirs(os.path.join(root, rel), exist_ok=True)
        except Exception:
            continue


# ==================== 校验 ====================

def validate_target(path: str, home: str = None) -> tuple:
    """校验"用户想把数据搬到这里"是否可行；返回 (ok, reason)"""
    text = str(path or "").strip()
    if not text:
        return False, "路径为空"
    target = os.path.abspath(os.path.expandvars(os.path.expanduser(text)))
    if os.path.exists(target) and not os.path.isdir(target):
        return False, "目标已存在且不是文件夹"
    # 不能指向程序自带资源目录（那是随程序发布的东西，不是用户数据）
    resource_root = program_data_root()
    if resource_root and _same_path(target, resource_root):
        return False, "不能使用程序自带的资源目录"
    if resource_root:
        try:
            abspath_target = os.path.abspath(target)
            abspath_resource = os.path.abspath(resource_root)
            if abspath_target.startswith(abspath_resource + os.sep):
                return False, "不能使用程序自带的资源目录"
        except Exception:
            pass
    # 父目录存在且可写（目标本身可能还不存在）
    parent = os.path.dirname(target) or "."
    probe = target
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        probe = parent
    if not os.path.isdir(parent):
        return False, "上级目录不存在"
    if not os.access(parent, os.W_OK):
        return False, "没有写入权限"
    try:
        os.makedirs(target, exist_ok=True)
    except Exception as exc:
        return False, f"无法创建目录：{exc}"
    probe_file = os.path.join(target, ".write_test")
    try:
        with open(probe_file, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe_file)
    except Exception:
        return False, "没有写入权限"
    if _same_path(target, default_data_root(home)):
        return True, "默认位置"
    return True, "可用"


# ==================== 真剪切（merge move） ====================

def _merge_move(src: str, dst: str, from_rel: str, to_rel: str,
                pending: list, stats: dict = None) -> bool:
    """把 src **真剪切**到 dst（目标已存在同名目录时递归合并）；返回 True = src 已不存在
    剪切语义（用户需求："应该是剪切而不是复制"）：
        · 文件 → 目标没有就搬走；**目标已有同名文件时保留目标、删掉源文件**（旧目录不留数据）；
        · 目录 → 目标没有就整目录改名搬（快）；目标已有就逐条目递归搬（绝不覆盖目标文件）；
        · 搬不动的（Windows 上被 logger 打开的 logs/system_log.log）→ 记进 pending，
          由下次启动的 `_complete_pending_cleanup()` 补搬。
    stats：只用于统计（conflicts / moved_files），可以传 None。
    """
    stats = stats if stats is not None else {}
    if not src or not os.path.exists(src) or _same_path(src, dst):
        return True

    # ---------- 目录 ----------
    if os.path.isdir(src) and not os.path.islink(src):
        if os.path.isdir(dst):
            try:
                names = os.listdir(src)
            except Exception as exc:
                _log_warn(f"读取目录 {src} 失败: {exc}")
                _append_pending(pending, from_rel, to_rel)
                return False
            for name in names:
                _merge_move(os.path.join(src, name), os.path.join(dst, name),
                            os.path.join(from_rel, name), os.path.join(to_rel, name),
                            pending, stats)
        elif os.path.exists(dst):
            # 目标是同名文件：保留目标那份，删掉源目录（冲突策略）
            _remove_path(src)
            stats["conflicts"] = stats.get("conflicts", 0) + 1
            _log_info(f"目标已有同名文件 {to_rel}，按剪切语义删除源目录 {from_rel}")
            return not os.path.exists(src)
        elif not _rename_path(src, dst):
            # 跨盘 / 目录里有被占用的文件：逐条目搬
            try:
                os.makedirs(dst, exist_ok=True)
            except Exception as exc:
                _log_warn(f"创建目录 {dst} 失败: {exc}")
                _append_pending(pending, from_rel, to_rel)
                return False
            try:
                names = os.listdir(src)
            except Exception:
                names = []
            for name in names:
                _merge_move(os.path.join(src, name), os.path.join(dst, name),
                            os.path.join(from_rel, name), os.path.join(to_rel, name),
                            pending, stats)
        # 源目录这时应该空了；空目录删掉（非空说明有子项被占用，子项已记 pending）
        _remove_empty_dir(src)
        if os.path.isdir(src):
            if not any(str(entry.get("from", "")).startswith(from_rel + os.sep)
                       for entry in pending):
                _append_pending(pending, from_rel, to_rel)
            return False
        return True

    # ---------- 文件 ----------
    if os.path.isdir(dst):
        _remove_path(src)                 # 目标是同名目录：保留目标，删源文件
        stats["conflicts"] = stats.get("conflicts", 0) + 1
        return not os.path.exists(src)
    if os.path.exists(dst):
        _remove_path(src)                 # 目标已有同名文件：保留目标，删源文件
        stats["conflicts"] = stats.get("conflicts", 0) + 1
        _log_info(f"目标已有 {to_rel}，按剪切语义删除源文件 {from_rel}")
        return not os.path.exists(src)
    try:
        _move_file(src, dst)
        stats["moved_files"] = stats.get("moved_files", 0) + 1
        return not os.path.exists(src)
    except Exception as exc:
        _log_warn(f"移动 {from_rel} 失败（被占用？已安排下次启动重试）: {exc}")
        _append_pending(pending, from_rel, to_rel)
        return False


def _append_pending(pending: list, from_rel: str, to_rel: str):
    """往"待下次启动清理"清单里加一条（路径都相对数据根）"""
    if not from_rel:
        return
    pending.append({"from": from_rel, "to": to_rel or from_rel})


# ==================== 旧根清理 ====================

def _cleanup_old_root(old_root: str, target_root: str = "") -> dict:
    r"""迁移完清掉旧根；返回 {root_removed, program_root, files_left}
    ⚠️⚠️ 规则改了：
       旧根是**用户数据根**（默认 `<用户主目录>\.ToolsGCP`）→ **整个目录删掉**，
       哪怕里面还剩着"不认识的"文件也不留（旧根留着只会让用户以为迁移没成功）。
       ⚠️ 删之前先把**白名单之外**的文件也搬到新根（免得丢数据）：
          这些文件本来就不在搬移白名单里（不是配置、不是 chats/logs），
          但删掉整个旧根就等于删了它们 → 所以先补搬，再删。
       ⚠️ 唯一不能删的是**程序资源目录**（modules/images/资源库/插件）——
          那是随程序发布的资源，不是用户数据。
    """
    result = {"root_removed": False, "program_root": False, "files_left": 0}
    if not old_root or not os.path.isdir(old_root):
        result["root_removed"] = True
        return result
    if target_root and _same_path(old_root, target_root):
        result["files_left"] = _count_files(old_root)
        return result
    if _same_path(old_root, program_data_root()):
        # 程序资源目录：绝不删根，只把空掉的 config/、logs/ 删掉，资源一个都不动。
        result["program_root"] = True
        for sub in ("config", "logs"):
            path = os.path.join(old_root, sub)
            if os.path.isdir(path) and not _tree_has_files(path):
                shutil.rmtree(path, ignore_errors=True)
        _log_info(f"旧位置是程序资源目录，只清理了其中的 config/logs：{old_root}")
        return result

    # ---- 把白名单之外的文件也补搬到新根，然后整个删掉旧根 ----
    if target_root:
        _move_extra_files(old_root, target_root)

    result["files_left"] = _count_files(old_root)
    shutil.rmtree(old_root, ignore_errors=True)
    result["root_removed"] = not os.path.exists(old_root)
    if result["root_removed"]:
        _log_info(f"旧数据目录已清理（整个删除）：{old_root}")
    else:
        _log_warn(f"旧数据目录 {old_root} 删除失败（可能有文件被占用），"
                  f"还剩 {result['files_left']} 个文件")
    return result


def _move_extra_files(old_root: str, target_root: str) -> int:
    """把旧根里**白名单之外**的文件也搬到新根（否则整个删旧根会丢数据）
    ⚠️ 白名单（CONFIG_FILES / CONFIG_DIRS）里的东西在迁移主流程里已经搬过了，
       这里只处理"剩下的"（不在白名单里的文件），搬进新根的对应位置。
    ⚠️ 搬不动的（被占用）就留在原地 —— `_cleanup_old_root` 之后的删除会失败，
       那时报告里会写明"还剩几个文件"。
    返回搬成功的文件数。
    """
    moved = 0
    try:
        whitelist = set(CONFIG_FILES) | set(CONFIG_DIRS) | set(_LEGACY_NAMES)
        for base, dirs, files in os.walk(old_root):
            rel_base = os.path.relpath(base, old_root)
            rel_base = '' if rel_base == '.' else rel_base.replace('/', os.sep)
            # 顶层就是白名单条目的，跳过（主流程搬过了）
            top = rel_base.split(os.sep)[0] if rel_base else ''
            if top in whitelist:
                dirs[:] = []
                continue
            for name in files:
                src = os.path.join(base, name)
                dst_dir = os.path.join(target_root, rel_base) if rel_base else target_root
                dst = os.path.join(dst_dir, name)
                try:
                    os.makedirs(dst_dir, exist_ok=True)
                    if os.path.exists(dst):
                        os.remove(src)          # 目标已有同名 → 以目标为准，删源
                    else:
                        shutil.copy2(src, dst)
                        os.remove(src)
                    moved += 1
                except Exception:
                    continue             # 搬不动就留在原地（后面会报告）
    except Exception as exc:
        _log_warn(f"补搬旧目录里的额外文件失败（忽略）: {exc}")
    return moved


# ==================== 待清理清单（被占用的日志文件） ====================

def pending_cleanup_path(root: str) -> str:
    """上次迁移没搬完的"待清理清单"：`<数据根>/config/.pending_migration_cleanup.json`"""
    return os.path.join(root, "config", PENDING_CLEANUP_NAME)


def _normalize_pending_items(raw) -> list:
    """把清单条目统一成 [{"from": "...", "to": "..."}]
    兼容两种写法：新格式 dict、旧格式裸字符串（历史遗留）。
    """
    items = []
    if not isinstance(raw, list):
        return items
    for entry in raw:
        if isinstance(entry, dict):
            from_rel = str(entry.get("from") or entry.get("src") or "").strip()
            to_rel = str(entry.get("to") or entry.get("dst") or from_rel).strip()
        else:
            from_rel = str(entry or "").strip()
            to_rel = from_rel
        if not from_rel:
            continue
        items.append({"from": from_rel, "to": to_rel or from_rel})
    return _dedupe_pending(items)


def _dedupe_pending(items: list) -> list:
    """按 (from, to) 去重，保持顺序"""
    seen = set()
    result = []
    for item in items or []:
        try:
            key = (os.path.normcase(item["from"]), os.path.normcase(item["to"]))
        except Exception:
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _merge_pending_groups(groups: list) -> list:
    """把同一个 source 的多组清单合并成一组（多次迁移叠加时用）"""
    merged = {}
    order = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        source = str(group.get("source") or "").strip()
        items = _normalize_pending_items(group.get("items"))
        if not source or not items:
            continue
        try:
            key = os.path.normcase(os.path.abspath(source))
        except Exception:
            continue
        if key not in merged:
            merged[key] = {"source": source, "items": []}
            order.append(key)
        merged[key]["items"].extend(items)
    result = []
    for key in order:
        group = merged[key]
        group["items"] = _dedupe_pending(group["items"])
        result.append(group)
    return result


def _load_pending_groups(root: str) -> list:
    """读待清理清单；读不到 / 坏了 / 空清单都返回 []（永不影响启动）"""
    try:
        with open(pending_cleanup_path(root), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    groups = []
    raw_groups = data.get("groups")
    if isinstance(raw_groups, list):
        for group in raw_groups:
            if not isinstance(group, dict):
                continue
            source = str(group.get("source") or "").strip()
            items = _normalize_pending_items(group.get("items"))
            if source and items:
                groups.append({"source": source, "items": items})
    else:
        # 旧版格式：{"source": "...", "items": ["logs/system_log.log"]}
        source = str(data.get("source") or "").strip()
        items = _normalize_pending_items(data.get("items"))
        if source and items:
            groups.append({"source": source, "items": items})
    return _merge_pending_groups(groups)


def _save_pending_groups(root: str, groups: list) -> bool:
    """写待清理清单（原子写）；失败返回 False，不抛"""
    groups = _merge_pending_groups(groups)
    if not groups:
        _clear_pending_groups(root)
        return True
    path = pending_cleanup_path(root)
    payload = {
        "version": PENDING_CLEANUP_VERSION,
        "groups": groups,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": ("上次迁移时有文件被占用（通常是 logs/system_log.log 被日志模块打开），"
                 "下次启动会自动完成剩余迁移并清理旧目录。"),
    }
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as exc:
        _log_warn(f"写待清理清单 {path} 失败: {exc}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def _clear_pending_groups(root: str):
    """清单处理完就删掉（没有清单时什么也不做）"""
    try:
        path = pending_cleanup_path(root)
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def pending_cleanup_info(root: str = None) -> dict:
    """给设置页/排查看的"待下次启动完成的迁移"摘要；没有就返回 {}"""
    try:
        root = root or resolve_data_root()
    except Exception:
        return {}
    groups = _load_pending_groups(root)
    if not groups:
        return {}
    return {
        "groups": [{"source": group["source"],
                    "items": [item["from"] for item in group["items"]]}
                   for group in groups],
        "count": sum(len(group["items"]) for group in groups),
    }


def _complete_pending_cleanup(root: str) -> bool:
    """启动时把上次被占用没搬完的条目补搬，并清理旧根；返回 True = 处理过清单
    ⚠️ 必须在 logger 打开日志文件**之前**跑（本函数由 constants 导入期调用），
       否则 logs/system_log.log 还是搬不动。
    """
    groups = _load_pending_groups(root)
    if not groups:
        return False
    remaining_groups = []
    # ⚠️ 补搬残留时也要把日志句柄关掉。
    #    这个函数由 constants 导入期调用（**在 logger 建好之后**），
    #    所以旧根里的 logs/system_log.log 很可能正被打开 → 搬不动 → 旧根永远删不掉。
    #    关掉句柄再搬 → 这一次就能把旧根彻底清掉（用户要的"原版 .ToolsGCP 被删除"）。
    with _LogFileReleased():
        for group in groups:
            source = group["source"]
            items = group["items"]
            if not os.path.isdir(source) or _same_path(source, root):
                _log_info(f"上次迁移的旧目录已不存在，丢弃待清理清单：{source}")
                continue
            pending = []
            for item in items:
                src = os.path.join(source, item["from"])
                dst = os.path.join(root, item["to"])
                if not os.path.exists(src):
                    continue
                _merge_move(src, dst, item["from"], item["to"], pending)
                if os.path.exists(src) and not any(
                        str(entry.get("from", "")).startswith(item["from"] + os.sep)
                        for entry in pending):
                    _append_pending(pending, item["from"], item["to"])
            # 迁移完成到下次启动之间，运行中的程序可能又往旧目录写了东西（旧根的 config/logs
            # 还在被当前进程使用）。这里把旧根里剩下的白名单条目也按剪切语义处理掉 ——
            # 冲突以新根为准、多余的（比如迁移后新产生的对话）搬进新根，旧根才能真正删掉。
            for from_rel, to_rel in _movable_pairs(source):
                _merge_move(os.path.join(source, from_rel), os.path.join(root, to_rel),
                            from_rel, to_rel, pending)
            pending = _dedupe_pending(pending)
            if pending:
                remaining_groups.append({"source": source, "items": pending})
                _log_warn(f"仍有 {len(pending)} 项旧数据被占用（{source}），下次启动继续补搬")
                continue
            cleanup = _cleanup_old_root(source, root)
            _log_info(f"上次迁移遗留的数据已补搬完成：{source} → {root}"
                      + ("（旧目录已清理）" if cleanup.get("root_removed") else ""))
    # ⚠️ 上下文管理器退出 → 日志句柄重新打开（指向当前数据根的 logs/system_log.log）
    if remaining_groups:
        _save_pending_groups(root, remaining_groups)
    else:
        _clear_pending_groups(root)
    return True


def _safe_complete_pending_cleanup(root: str):
    """`_complete_pending_cleanup` 的防呆包装：它绝不能把启动流程带崩/带偏"""
    try:
        _complete_pending_cleanup(root)
    except Exception as exc:
        _log_warn(f"补搬上次迁移残留失败（忽略，继续启动）：{exc}")


# ==================== 迁移 ====================

def _movable_pairs(root: str) -> list:
    """列出 root 下要搬的条目：[(源相对路径, 目标相对路径)]
    只用 CONFIG_FILES / CONFIG_DIRS 这张白名单；老版本把配置直接放在 .ToolsGCP 根下的，
    这里统一映射到新布局 `<root>/config/<名字>`（搬完旧根才干净）。
    ⚠️ 真实布局是：
        <root>/config/<各个配置文件>
        <root>/config/chats、<root>/config/plugin_data
        <root>/logs
    """
    pairs = []
    for name in CONFIG_FILES:
        for rel_src in (os.path.join("config", name), name):
            if os.path.isfile(os.path.join(root, rel_src)):
                pairs.append((rel_src, os.path.join("config", name)))
                break
    for name in CONFIG_DIRS:
        if name == "logs":
            candidates = (("logs", "logs"),)
        else:
            target_rel = os.path.join("config", name)
            candidates = ((os.path.join("config", name), target_rel),
                          (name, target_rel))
        for rel_src, rel_dst in candidates:
            if os.path.isdir(os.path.join(root, rel_src)):
                pairs.append((rel_src, rel_dst))
                break
    return pairs


def _list_movable(root: str) -> list:
    """兼容旧调用：只返回白名单条目的源相对路径（新代码请用 `_movable_pairs`）"""
    return [from_rel for from_rel, _to_rel in _movable_pairs(root)]


def is_inside_data_root(path: str, home: str = None) -> bool:
    """path 是不是当前数据根本身或它里面的路径（设置页选新位置时要拦掉）"""
    try:
        return _is_within(path, resolve_data_root(home))
    except Exception:
        return False


def migrate_data_root(new_root: str, progress_cb=None, home: str = None) -> tuple:
    r"""把数据根**剪切**到 new_root；返回 (ok, message)
    progress_cb(done, total, text)：设置页拿它驱动进度条（普通回调，可在工作线程调用）。
    源永远是 `ensure_user_data_root(home)`（当前生效的数据根），目标由调用方给定
    （前端 pick_data_root 负责"在选中目录下建 .ToolsGCP"的规则）。
    真剪切规则（应该是剪切而不是复制）：
        · CONFIG_FILES / CONFIG_DIRS 白名单里的配置、logs、chats、plugin_data 搬到新根后，
          旧根里**必须没有它们**（不是复制）；
        · 目标已有同名目录 → 递归合并搬（绝不覆盖目标已有文件）；
        · 目标已有同名文件 → 保留目标、删掉源文件（旧目录不留旧数据）；
        · `logs/system_log.log` 被 logger 长期占用（Windows 移不动）→ 本次跳过，
          写 `<new_root>/config/.pending_migration_cleanup.json`，下次启动
          `ensure_user_data_root()` 自动补搬并清理旧根；
        · 搬完旧根若只剩空目录 → 整个删掉；旧根是**程序资源目录**时只删空掉的
          config/logs，绝不删根（modules/images/resources/plugins 是随程序发布的资源）；
        · 资源文件永远不搬、不删。
    ⚠️ 单条目失败不中断整场迁移；message 区分完全剪切成功 / 部分待下次启动完成。
    """
    def report(done, total, text):
        if progress_cb is None:
            return
        try:
            progress_cb(int(done), int(total), str(text))
        except Exception:
            pass

    ok, reason = validate_target(new_root, home)
    if not ok:
        report(0, 1, reason)
        return False, reason

    target = os.path.abspath(os.path.expandvars(os.path.expanduser(str(new_root).strip())))
    source = ensure_user_data_root(home)
    if _same_path(source, target):
        report(1, 1, "已在目标位置")
        return True, "数据已经在目标位置，无需迁移"
    if _is_within(target, source):
        message = "新位置不能放在当前数据目录里面（否则会把数据搬进自己的子目录）"
        report(0, 1, message)
        return False, message

    pairs = _movable_pairs(source)
    total = max(1, len(pairs))
    report(0, total, "准备迁移")

    stats = {"conflicts": 0, "moved_files": 0}
    pending = []
    moved = 0
    # ⚠️ 搬之前先把日志句柄关掉。
    #    `logs/system_log.log` 被 logger 长期打开（append），Windows 上被打开的文件
    #    既不能改名也不能删除 → 它必然搬不动 → 旧根永远删不掉
    #    （用户看到的本次有 1 项被占用（logs/system_log.log），下次启动会…）。
    #    关掉句柄 → 日志文件当场就能搬走/删掉 → **旧根这次就被彻底清掉**。
    #    搬完由上下文管理器保证重新打开日志（指向新根）。
    with _LogFileReleased():
        for index, (from_rel, to_rel) in enumerate(pairs, start=1):
            report(index - 1, total, f"正在迁移：{from_rel}")
            src = os.path.join(source, from_rel)
            dst = os.path.join(target, to_rel)
            _merge_move(src, dst, from_rel, to_rel, pending, stats)
            if not os.path.exists(src):
                moved += 1
            report(index, total, f"已处理：{from_rel}")
        pending = _dedupe_pending(pending)

        # 目录结构补齐（chats/logs/plugin_data）
        try:
            _ensure_subdirs(target)
        except Exception:
            pass

        # 指针必须最后更新：中途失败时还能指回老位置
        if not save_pointer(target, home):
            return False, ("数据已搬到新位置，但写入 ToolsGCP.json 失败："
                           "重启后会继续指向旧位置，请检查用户主目录写权限")

        # 上次迁移遗留的清单要保留/合并（可能还欠着更早一次迁移的日志）
        groups = _load_pending_groups(target)
        if pending:
            groups.append({"source": source, "items": pending})
            groups = _merge_pending_groups(groups)
            if not _save_pending_groups(target, groups):
                return False, (f"数据已剪切到 {target}，但待清理清单写入失败，"
                               f"旧目录暂时保留：{source}")
            _log_warn(f"迁移 .ToolsGCP 时有 {len(pending)} 项被占用，"
                      f"已写待清理清单，下次启动补搬并清理旧目录 {source}")
        else:
            _save_pending_groups(target, groups)      # 空清单会顺手删掉旧文件

        # ⚠️ 清旧根要**在日志句柄关着的时候**做 ——
        #    否则 logs/system_log.log 还被占着，旧根删不掉（用户的老问题）。
        cleanup = _cleanup_old_root(source, target)
    # ⚠️ 上下文管理器退出 → 日志句柄已重新打开（指向新根的 logs/system_log.log）
    report(total, total, "完成")

    conflict_note = ""
    if stats.get("conflicts"):
        conflict_note = f"，{stats['conflicts']} 项同名冲突以目标为准"

    # ---- message 区分完全剪切 / 部分待下次启动 ----
    if pending:
        names = "、".join(sorted({str(item.get("from", "")) for item in pending})[:5])
        program_note = "（程序资源目录保留，只清空了其中的 config/logs）" \
            if cleanup.get("program_root") else ""
        return True, (f"已剪切 {moved} 项到 {target}{conflict_note}；"
                      f"本次有 {len(pending)} 项被占用（{names}），"
                      f"下次启动会自动完成剩余迁移并清理旧目录 {source}{program_note}")
    if cleanup.get("program_root"):
        return True, (f"已剪切 {moved} 项到 {target}{conflict_note}；"
                      f"旧位置是程序资源目录，只清空了其中的 config/logs，资源文件未动")
    if cleanup.get("files_left"):
        # 旧目录**已经尝试整个删除**，但有文件被占用删不掉 —— 如实报告还剩几个。
        return True, (f"已剪切 {moved} 项到 {target}{conflict_note}；"
                      f"旧目录 {source} 删除失败（{cleanup['files_left']} 个文件被占用），"
                      f"可手动删除")
    if not cleanup.get("root_removed"):
        return True, (f"已剪切 {moved} 项到 {target}{conflict_note}；"
                      f"旧目录 {source} 已清空但目录本身删除失败（可能被占用），可手动删除")
    return True, (f"已剪切 {moved} 项到 {target}{conflict_note}；"
                  f"旧目录 {source} 已删除")


def reset_to_default_root(home: str = None) -> tuple:
    r"""把数据根恢复到默认位置 `<用户主目录>\.ToolsGCP`（指针丢了/坏了时的自愈入口）
    ⚠️ 只改指针，**不搬数据**（和原版一致）；切换前顺手把当前数据根上"待下次启动"的
       清单补搬掉，免得旧根里的残留日志永远没人管。
    """
    try:
        try:
            current = resolve_data_root(home)
            if current:
                _safe_complete_pending_cleanup(current)
        except Exception:
            pass
        root = default_data_root(home)
        ok, reason = validate_target(root, home)
        if not ok:
            return False, reason
        _ensure_subdirs(root)
        if not save_pointer(root, home):
            return False, "无法写入 ToolsGCP.json"
        return True, root
    except Exception as exc:
        return False, str(exc)
