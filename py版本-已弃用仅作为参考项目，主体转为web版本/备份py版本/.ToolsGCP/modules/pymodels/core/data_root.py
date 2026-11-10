r"""用户数据根（.ToolsGCP）的定位、自愈与迁移 —— 需求：「配置文件改存到用户目录」。
========== 这里到底管哪一批文件 ==========
只管**程序自己写出来的配置/数据**（就是 constants.DATA_DIR 那批）：
    toolsgcp_config.json / favorites.json / deploy_config.json / plugins.json /
    plugin_notes.json / announcements.json / privacy_policy.json / chats/ / plugin_data/ / logs/

**绝不搬**随程序发布的资源（它们永远留在程序目录旁的 .ToolsGCP 里）：
    ToolsGCP-Resources.json（用户明确说了不要动）、modules/（含 modules/languages）、
    images/、Icon/、logo.png、plugins/、backups/。

========== 两个文件的关系 ==========
1. `<用户主目录>\ToolsGCP.json`   —— **指针**：里面写着"真正的 .ToolsGCP 在哪"
       {"data_root": "C:\\Users\\xxx\\.ToolsGCP", "version": 1}
2. `<data_root>`                 —— **数据目录**：上面那批配置文件就放这儿

指针丢了 / 坏了 / 指向的目录没了 → 自动回落到默认位置 `<用户主目录>\.ToolsGCP`，
并把它连同指针一起重建（需求："自动创建默认位置全新的 .ToolsGCP 文件夹"）。

⚠️ 本模块**不 import PyQt**：设置页的迁移进度条要靠它，而它也要能在无 GUI 环境下测试。
⚠️ 任何函数都不向上抛异常：定位失败一律退回一个可用的路径。
"""

import json
import os
import shutil
import time

# 指针文件名（用户主目录下）
POINTER_NAME = "ToolsGCP.json"
POINTER_VERSION = 1

# 默认数据目录名（用户主目录下）
DATA_DIR_NAME = ".ToolsGCP"

# 需要搬迁/管理的"配置类"条目（相对用户数据根）。
# ⚠️ 只有这些会被搬；资源类文件一律不在表里 —— 这张表就是"只搬配置文件"的硬边界。
CONFIG_FILES = (
    "toolsgcp_config.json",
    "favorites.json",
    "deploy_config.json",
    "plugins.json",
    "plugin_notes.json",
    "announcements.json",
    "privacy_policy.json",
)
CONFIG_DIRS = (
    "chats",
    "plugin_data",
    "logs",
)

# 老位置里可能出现的散落文件名（早期版本直接放在 .ToolsGCP 根下）
_LEGACY_NAMES = CONFIG_FILES


def _log_info(message: str):
    try:
        from ..utils.logger import log
        log.info("数据目录", "data_root", message)
    except Exception:
        pass


def _log_warn(message: str):
    try:
        from ..utils.logger import log
        log.warn("数据目录", "data_root", message)
    except Exception:
        pass


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
    """默认数据根：<用户主目录>\\.ToolsGCP

    ⚠️ home 参数必须一路透传：测试会把"假主目录"传进来，绝不能悄悄回落到真实主目录
       （否则测试会往用户的真实配置目录里写垃圾）。
    """
    return os.path.join(home or home_dir(), DATA_DIR_NAME)


def pointer_file_path(home: str = None) -> str:
    """指针文件 ToolsGCP.json 的完整路径（默认在用户主目录下）"""
    return os.path.join(home or home_dir(), POINTER_NAME)


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


# ==================== 解析 / 自愈 ====================

def resolve_data_root(home: str = None) -> str:
    """算出"现在到底该用哪个数据根"（只算不建）：指针优先，坏了回默认"""
    pointer = load_pointer(home)
    if pointer:
        return pointer
    return default_data_root(home)


def ensure_user_data_root(home: str = None) -> str:
    """保证数据根存在并可用；返回最终生效的路径

    - 指针有效 → 用它（目录不在就建出来）；
    - 指针缺失/损坏 → 用默认位置，建目录 + **重建指针**；
    - 目标不可写（权限/盘符没了）→ 退回默认位置再试一次。
    """
    try:
        root = load_pointer(home)
    except Exception:
        root = ""
    if root:
        try:
            os.makedirs(root, exist_ok=True)
            _ensure_subdirs(root)
            return root
        except Exception as exc:
            _log_warn(f"指针指向的数据根不可用（{root}）：{exc}，回落到默认位置")

    root = default_data_root(home)
    try:
        os.makedirs(root, exist_ok=True)
    except Exception as exc:
        _log_warn(f"创建默认数据根 {root} 失败: {exc}")
        # 用户主目录彻底不可写：退回程序目录，至少别让程序起不来
        try:
            from ..constants import SCRIPT_DIR
            root = os.path.join(SCRIPT_DIR, DATA_DIR_NAME)
            os.makedirs(root, exist_ok=True)
        except Exception:
            pass
    try:
        _ensure_subdirs(root)
        save_pointer(root, home)      # 重建/修正指针
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
    """
    for rel in (os.path.join("config", "chats"),
                os.path.join("config", "plugin_data"),
                "logs",
                os.path.join("logs", "history")):
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
    try:
        from ..constants import CONFIG_DIR
        resource_root = os.path.abspath(CONFIG_DIR)
        if os.path.abspath(target) == resource_root:
            return False, "不能使用程序自带的资源目录"
        if os.path.abspath(target).startswith(resource_root + os.sep):
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
    if os.path.abspath(target) == os.path.abspath(default_data_root(home)):
        return True, "默认位置"
    return True, "可用"


# ==================== 迁移 ====================

def _move(src: str, dst: str) -> None:
    """搬一个文件/目录（跨盘也能用）；dst 已存在时抛 FileExistsError"""
    if os.path.exists(dst):
        raise FileExistsError(dst)
    try:
        os.replace(src, dst)
    except OSError:
        # 跨盘 / 被占用：退回复制 + 删除
        if os.path.isdir(src):
            shutil.copytree(src, dst)
            shutil.rmtree(src, ignore_errors=True)
        else:
            shutil.copy2(src, dst)
            os.remove(src)


def _list_movable(root: str) -> list:
    """列出 root 下真正要搬的条目（只用 CONFIG_FILES / CONFIG_DIRS 这张白名单）

    ⚠️ 真实布局是：
        <root>/config/<各个配置文件>
        <root>/config/chats、<root>/config/plugin_data
        <root>/logs
       所以这里的条目是**相对路径**（"config/favorites.json"），不是裸文件名 ——
       老版本按裸名在 root 下找，结果一个都找不到（配置文件全在 config/ 子目录里）。
    """
    items = []
    for name in CONFIG_FILES:
        rel = os.path.join("config", name)
        if os.path.isfile(os.path.join(root, rel)):
            items.append(rel)
        elif os.path.isfile(os.path.join(root, name)):
            items.append(name)          # 兼容早期直接放在根下的写法
    for name in CONFIG_DIRS:
        if name == "logs":
            candidates = ("logs",)
        else:
            candidates = (os.path.join("config", name), name)
        for rel in candidates:
            if os.path.isdir(os.path.join(root, rel)):
                items.append(rel)
                break
    return items


def migrate_data_root(new_root: str, progress_cb=None, home: str = None) -> tuple:
    """把数据根迁到 new_root；返回 (ok, message)

    progress_cb(done, total, text)：设置页拿它驱动进度条（普通回调，可在工作线程调用）。

    ⚠️ 只搬 CONFIG_FILES / CONFIG_DIRS 白名单里的东西 —— 资源文件永远不搬。
    ⚠️ 单个条目失败不中断整场迁移，最后如实汇报失败项。
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
    if os.path.abspath(source) == target:
        report(1, 1, "已在目标位置")
        return True, "数据已经在目标位置，无需迁移"

    items = _list_movable(source)
    total = max(1, len(items))
    report(0, total, "准备迁移")

    moved, skipped, failed = 0, 0, []
    for done, name in enumerate(items, start=1):
        src = os.path.join(source, name)
        dst = os.path.join(target, name)
        report(done - 1, total, f"正在迁移：{name}")
        try:
            if not os.path.exists(src):
                skipped += 1
                continue
            if os.path.exists(dst):
                # 目标已有同名条目：绝不覆盖（用户可能已经在新位置写过东西）
                skipped += 1
                _log_info(f"目标已存在 {name}，跳过")
                continue
            # ⚠️ 条目可能带子目录前缀（config/chats），目标这边的父级要先建出来
            parent = os.path.dirname(dst)
            if parent:
                os.makedirs(parent, exist_ok=True)
            _move(src, dst)
            moved += 1
        except Exception as exc:
            failed.append(f"{name}（{exc}）")
            _log_warn(f"迁移 {name} 失败: {exc}")
        report(done, total, f"已处理：{name}")

    # 白名单里没有、但老位置可能残留的散落配置：逐个补搬
    try:
        for extra in ("plugin_notes.json", "announcements.json", "privacy_policy.json"):
            if extra in items:
                continue
            src = os.path.join(source, extra)
            dst = os.path.join(target, extra)
            if os.path.isfile(src) and not os.path.exists(dst):
                try:
                    _move(src, dst)
                    moved += 1
                except Exception as exc:
                    _log_warn(f"补搬 {extra} 失败: {exc}")
    except Exception:
        pass

    # 目录结构补齐（chats/logs/plugin_data）
    try:
        _ensure_subdirs(target)
    except Exception:
        pass

    # 指针必须最后更新：中途失败时还能指回老位置
    saved = save_pointer(target, home)
    if not saved:
        return False, "迁移完成，但写入 ToolsGCP.json 失败"

    report(total, total, "完成")
    if failed:
        return False, f"部分条目迁移失败：{'；'.join(failed)}"
    return True, f"已迁移 {moved} 项到 {target}" + (f"，跳过 {skipped} 项" if skipped else "")


def reset_to_default_root(home: str = None) -> tuple:
    """把数据根恢复到默认位置（指针丢了/坏了时的自愈入口）"""
    try:
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
