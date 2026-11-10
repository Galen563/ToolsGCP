"""程序数据目录（用户主目录下的 .ToolsGCP/config）：程序自己产出的文件都放这，并把老用户的数据迁进来。

========== 位置变了（需求）==========
配置/对话/日志现在存在**用户主目录**下的 `.ToolsGCP/`（自适应，不是写死 C:\\Users\\Administrator），
具体路径由 core/data_root.py 解析（`<用户主目录>\\ToolsGCP.json` 指针说了算）。

启动时做两件事：
1. 保证用户数据根的 config/、chats/、plugin_data/、logs/ 存在；
2. 把**老位置**（程序目录旁的 .ToolsGCP 根下）散落的配置按"旧的还在 + 新的还没有"搬进新位置。

⚠️ 任何情况下都不要搬 ToolsGCP-Resources.json（制作器按固定路径读写，用户明确要求别动）、
   Icon/、images/、modules/（含语言文件）、logo.png、plugins/、backups/ —— 那些是
   "随程序发布"的资源，不是程序生成的配置文件。

用法（必须在创建任何 Manager 之前调用）：
    from pymodels.core.data_dir import ensure_data_dir
    ensure_data_dir()
"""

import os

from ..constants import CONFIG_DIR, DATA_DIR, CHATS_DIR, PLUGIN_DATA_DIR

# 需要从旧位置搬到 config/ 的文件（老名字 -> 新名字）
# ⚠️ privacy_policy.json（隐私政策/免责声明的同意记录）也是**程序自己写出来的配置**，
#    所以按需求一起搬进用户目录（老版本它在程序目录旁的 .ToolsGCP 根下）。
MIGRATABLE_FILES = (
    ("toolsgcp_config.json", "toolsgcp_config.json"),
    ("favorites.json", "favorites.json"),
    ("deploy_config.json", "deploy_config.json"),
    ("plugins.json", "plugins.json"),
    ("plugin_notes.json", "plugin_notes.json"),
    ("announcements.json", "announcements.json"),
    ("privacy_policy.json", "privacy_policy.json"),
)

# 需要整体搬过去的目录（插件数据目录 / 对话历史）
MIGRATABLE_DIRS = (
    ("plugin_data", "plugin_data"),
    ("chats", "chats"),
)


def ensure_data_dir(data_dir: str = None, config_dir: str = None):
    """保证 config/ 及其子目录存在，并把老位置的数据搬进来

    data_dir / config_dir 可整体重定向供测试用；返回 (新建目录数, 搬运条目数)。
    ⚠️ 会写磁盘，但永不抛异常。
    """
    target_dir = data_dir or DATA_DIR
    # 源目录 = 程序目录旁的老 .ToolsGCP（新装用户这里没有配置，函数就是空转）
    source_dir = config_dir or CONFIG_DIR
    chats_dir = os.path.join(target_dir, "chats")
    plugin_data_dir = os.path.join(target_dir, "plugin_data")

    created = 0
    moved = 0

    # 目标目录可能就在 source_dir 里面（回落路径），那样就不用"1) 建目录 2) 再搬"了：
    # 先建目录会把老数据留在旧位置（os.replace 要求目标不存在）。
    same_tree = _is_same_target(source_dir, target_dir)

    # ⚠️ 这里只建 target_dir 本身，**不要**先建 chats/plugin_data：
    #    目录迁移走的是 os.replace / 改名，目标目录一旦存在（哪怕是空的）就搬不动了
    #    —— 老用户的对话历史会整批留在旧位置（踩过：迁移后 chats 里 0 条）。
    for directory in (target_dir,):
        try:
            if not os.path.isdir(directory):
                os.makedirs(directory, exist_ok=True)
                created += 1
        except Exception as exc:
            _log_warn(f"创建目录失败 {directory}: {exc}")

    moved += _migrate_files(source_dir, target_dir)
    moved += _migrate_dirs(source_dir, target_dir)

    # 兜底：上面两步之后 chats/ plugin_data/ 还不存在就建一个空的
    for directory in (chats_dir, plugin_data_dir):
        if not os.path.isdir(directory):
            try:
                os.makedirs(directory, exist_ok=True)
                created += 1
            except Exception as exc:
                _log_warn(f"创建目录失败 {directory}: {exc}")

    if moved:
        _log_info(f"已把 {moved} 项旧数据搬进 {target_dir}")

    return created, moved


def _is_same_target(source_dir: str, target_dir: str) -> bool:
    """target 是不是就在 source 下面（同一个 .ToolsGCP 树里）"""
    try:
        src = os.path.abspath(source_dir)
        dst = os.path.abspath(target_dir)
        return dst == src or dst.startswith(src + os.sep)
    except Exception:
        return False


def _candidates(source_dir: str, name: str) -> list:
    """一个条目在"老位置"可能待的几个地方（按优先级）

    历史原因，老版本把配置文件直接放在 `.ToolsGCP/` 根下，新一点的版本放在
    `.ToolsGCP/config/` 下 —— 升级用户的这两种形态都要能找到。
    """
    return [os.path.join(source_dir, name),
            os.path.join(source_dir, "config", name)]


def _migrate_files(source_dir: str, target_dir: str) -> int:
    """逐文件搬迁；返回成功搬动的个数"""
    moved = 0
    for old_name, new_name in MIGRATABLE_FILES:
        new_path = os.path.join(target_dir, new_name)
        for old_path in _candidates(source_dir, old_name):
            # ⚠️ 两个判断缺一不可：old 不存在就没得搬；new 已存在时必须保留新的，不能反向覆盖。
            if not os.path.isfile(old_path) or os.path.exists(new_path):
                continue
            if os.path.abspath(old_path) == os.path.abspath(new_path):
                continue
            try:
                _move_path(old_path, new_path)
                moved += 1
                _log_op("migrate_file", name=old_name, to=new_path)
                break
            except Exception as exc:
                # 常见原因：文件被另一个实例占用（程序开了两份）、权限不足、跨盘失败
                _log_warn(f"迁移 {old_name} 失败（新位置会重新生成）: {exc}")
    return moved


def _migrate_dirs(source_dir: str, target_dir: str) -> int:
    """逐目录搬迁；返回成功搬动的个数

    os.replace 要求目标不存在且同卷；目标已存在时只有它是空目录才删掉再搬。
    ⚠️ 搬不动时一个字节都不删，宁可插件数据留在老位置。
    """
    moved = 0
    for old_name, new_name in MIGRATABLE_DIRS:
        new_path = os.path.join(target_dir, new_name)
        old_path = next((p for p in _candidates(source_dir, old_name)
                         if os.path.isdir(p)), "")
        if not old_path:
            continue
        if os.path.abspath(old_path) == os.path.abspath(new_path):
            continue
        # 目标已经有东西了就绝不动它（可能用户/插件已经在新位置写数据了）
        if os.path.isdir(new_path) and not _is_empty_dir(new_path):
            # ⚠️ 但**不能整批跳过**：目标目录可能只是被上次启动提前建成了空的子目录
            #    （plugin_data/、chats/ 里已经有新文件），老数据还留在源目录里等着搬。
            #    这里改成"逐条目补搬"：只补目标里还没有的，绝不覆盖。
            moved += _merge_dir(old_path, new_path)
            continue

        if os.path.isdir(new_path):
            try:
                os.rmdir(new_path)          # 只会成功删掉空目录，非空会抛异常
            except Exception as exc:
                _log_warn(f"目标目录 {new_name} 非空，跳过搬迁: {exc}")
                continue

        try:
            _move_path(old_path, new_path)
            moved += 1
            _log_op("migrate_dir", name=old_name, to=new_path)
        except Exception as exc:
            _log_warn(f"迁移目录 {old_name} 失败（继续使用旧位置）: {exc}")
    return moved


def _move_path(src: str, dst: str):
    """搬一个文件/目录：优先 os.replace；跨盘 / 被占用时退回复制 + 删除"""
    try:
        os.replace(src, dst)
        return
    except OSError:
        pass
    if os.path.isdir(src):
        import shutil
        shutil.copytree(src, dst)
        shutil.rmtree(src, ignore_errors=True)
    else:
        import shutil
        shutil.copy2(src, dst)
        os.remove(src)


def _merge_dir(old_path: str, new_path: str) -> int:
    """目标目录已存在时：把源目录里**目标还没有**的条目逐个补搬过去（绝不覆盖）

    返回补搬成功、且已从源位置删除的条目数。
    """
    moved = 0
    try:
        names = os.listdir(old_path)
    except Exception as exc:
        _log_warn(f"读取目录 {old_path} 失败: {exc}")
        return 0
    for name in names:
        src = os.path.join(old_path, name)
        dst = os.path.join(new_path, name)
        try:
            if os.path.exists(dst):
                # 同名条目目标已经有了：留着目标那份
                continue
            _move_path(src, dst)
            moved += 1
        except Exception as exc:
            _log_warn(f"补搬 {name} 失败: {exc}")
    # 源目录这时应该空了；空了就删掉（留着也不影响，但干净些）
    try:
        if not os.listdir(old_path):
            os.rmdir(old_path)
    except Exception:
        pass
    return moved


def _is_empty_dir(path: str) -> bool:
    """是不是一个（存在且）空目录"""
    try:
        return os.path.isdir(path) and not os.listdir(path)
    except Exception:
        return False


# ---------- 日志（延迟导入，避免与 logger 成环） ----------

def _logger():
    try:
        from ..utils.logger import log
        return log
    except Exception:
        return None


def _log_info(message: str):
    logger = _logger()
    if logger is not None:
        try:
            logger.info("数据目录", "data_dir", message)
        except Exception:
            pass


def _log_warn(message: str):
    logger = _logger()
    if logger is not None:
        try:
            logger.warn("数据目录", "data_dir", message)
        except Exception:
            pass


def _log_op(action: str, **fields):
    logger = _logger()
    if logger is not None:
        try:
            logger.op("数据目录", action, **fields)
        except Exception:
            pass
