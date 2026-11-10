"""日志模块 - 统一日志与终端输出

**所有**输出都走这里：既写进日志文件，也打到终端。不要再直接用 print()。

格式（固定，方便 grep）：[本地时间到毫秒] [级别左对齐补 5 位] [中文分类|英文子类] 消息
结构化信息写成 键=值（值里有空格加英文双引号）；多行消息后续行按前缀宽度缩进对齐。

用法：
    log.info("搜索", "search", "用户输入关键词: ToolsGCP")
    log.op("设置", "update", key="theme", value="深色主题")
"""

import ctypes
import os
import shutil
import sys
import threading
import zipfile
from datetime import datetime

from ..constants import (
    LOGS_DIR,
    LOG_HISTORY_DIR,
    LOG_CURRENT_FILE,
    LOG_FILE_PREFIX,
    LOG_MAX_HISTORY,
)


# 级别

# 级别名 → 数值
LEVEL_VALUES = {
    "DEBUG": 10,
    "INFO": 20,
    "OP": 25,
    "WARN": 30,
    "ERROR": 40,
    "FATAL": 50,
}

# 兼容老写法的级别名
LEVEL_ALIASES = {
    "DBG": "DEBUG",
    "ERR": "ERROR",
    "OP": "OP",
    "INFO": "INFO",
    "WARN": "WARN",
    "FATAL": "FATAL",
}

# 默认记录的级别（DEBUG 默认关，开发者模式可以打开）
DEFAULT_ENABLED_LEVELS = {"INFO", "OP", "WARN", "ERROR", "FATAL"}

# 这些键的值不写进日志（避免密钥泄漏）
REDACT_KEYS = {"api_key", "api_key_enc", "license_key", "dev_mode_key", "password", "token"}
REDACTED = "***"


def _fmt_value(value, max_len: int = 200) -> str:
    """把值格式化成日志里好读的形式：有空格/特殊字符就加引号"""
    text = str(value)
    if len(text) > max_len:
        text = text[:max_len] + f"...(共 {len(text)} 字)"
    if text == "":
        return '""'
    if any(ch in text for ch in ' \t"=,'):
        text = text.replace('"', "'")
        return f'"{text}"'
    return text


def _format_fields(fields: dict) -> str:
    """把 键=值 拼成一段（键排序，输出稳定，敏感值自动打码）"""
    fields = dict(fields or {})

    # 敏感值打码：字段名本身叫 api_key / password 这类，
    # 或形如 key=api_key new=xxx —— 改的是敏感项，值也一起打码
    subject = str(fields.get("key") or fields.get("setting") or "")
    subject_is_secret = subject in REDACT_KEYS
    for name in ("new", "old", "value", "v"):
        if name in fields and (name.lower() in REDACT_KEYS or subject_is_secret):
            fields[name] = REDACTED
    for name in list(fields.keys()):
        if name in REDACT_KEYS and fields[name] not in ("", None):
            fields[name] = REDACTED

    parts = []
    for key in sorted(fields.keys()):
        value = fields[key]
        if value is None:
            continue
        parts.append(f"{key}={_fmt_value(value)}")
    return " ".join(parts)


class Logger:
    """日志记录器（单例）"""

    def __init__(self):
        self._lock = threading.Lock()
        self.current_path = os.path.join(LOGS_DIR, LOG_CURRENT_FILE)
        self._enabled_levels = set(DEFAULT_ENABLED_LEVELS)
        self._language = "简体中文"
        self._terminal = False
        self._file = None

        self._ensure_dirs()
        self._ensure_console()
        self._archive_previous()
        self._open_current()
        # 新会话开个头：否则空的 system_log.log 看起来像"日志被清空了"
        self.info("启动", "startup", "日志会话开始")

    # ---------- 初始化 ----------

    def _ensure_dirs(self):
        os.makedirs(LOGS_DIR, exist_ok=True)
        os.makedirs(LOG_HISTORY_DIR, exist_ok=True)

    def _ensure_console(self):
        """保证能把日志打到终端

        ⚠️ .pyw / pythonw 启动时没有控制台，sys.stdout 是 None：尝试附着到父进程的控制台，
           失败就只写文件（不报错）。
        """
        try:
            if sys.stdout is not None and sys.stdout.fileno() >= 0:
                self._terminal = True
                return
        except Exception:
            pass

        if sys.platform != "win32":
            self._terminal = False
            return
        try:
            ATTACH_PARENT_PROCESS = -1
            if not ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
                self._terminal = False
                return
            sys.stdout = open("CONOUT$", "w", encoding="utf-8",
                              buffering=1, errors="replace")
            sys.stderr = open("CONOUT$", "w", encoding="utf-8",
                              buffering=1, errors="replace")
            self._terminal = True
        except Exception:
            self._terminal = False

    def _archive_previous(self):
        """把上次的 system_log.log 归档到 history/（失败也不影响启动）"""
        # 兼容更早版本的 current.log
        legacy = os.path.join(LOGS_DIR, "current.log")
        if os.path.exists(legacy) and legacy != self.current_path:
            self._move_to_history(legacy)

        if not os.path.exists(self.current_path):
            return
        try:
            if os.path.getsize(self.current_path) == 0:
                os.remove(self.current_path)
                return
        except Exception:
            return
        self._move_to_history(self.current_path)
        self._prune_history()

    def _move_to_history(self, path: str):
        try:
            stamp = datetime.fromtimestamp(
                os.path.getmtime(path)).strftime("%Y-%m-%d-%H%M%S%f")[:-3]
            archive_path = os.path.join(LOG_HISTORY_DIR, f"{LOG_FILE_PREFIX}-{stamp}.log")
            if os.path.exists(archive_path):
                archive_path = os.path.join(
                    LOG_HISTORY_DIR,
                    f"{LOG_FILE_PREFIX}-{stamp}-{int(datetime.now().timestamp())}.log")
            shutil.move(path, archive_path)
        except Exception:
            # 归档失败（比如文件被另一个实例占用）不影响启动
            pass

    def _open_current(self):
        try:
            self._file = open(self.current_path, "a", encoding="utf-8", buffering=1)
        except Exception:
            self._file = None

    # ---------- 级别控制 ----------

    def set_enabled_levels(self, levels):
        self._enabled_levels = {LEVEL_ALIASES.get(str(x).upper(), str(x).upper())
                                for x in levels}

    def enable_debug(self, enabled=True):
        if enabled:
            self._enabled_levels.add("DEBUG")
        else:
            self._enabled_levels.discard("DEBUG")

    def is_level_enabled(self, level):
        level = LEVEL_ALIASES.get(str(level).upper(), str(level).upper())
        return level in self._enabled_levels

    @property
    def terminal_available(self) -> bool:
        """当前是否有终端可输出"""
        return self._terminal

    # ---------- 写入主入口 ----------

    def log(self, level, cat_zh, cat_en, message, thread=None):
        """写一条日志（文件 + 终端）

        :param level:  DEBUG / INFO / OP / WARN / ERROR / FATAL（兼容 DBG / ERR）
        :param cat_zh: 中文分类，例如 "设置"
        :param cat_en: 英文子类，例如 "update"
        :param message: 消息内容（可含 \\n）
        """
        level = LEVEL_ALIASES.get(str(level).upper(), str(level).upper())
        if level not in self._enabled_levels:
            return

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        category = f"{cat_zh}|{cat_en}" if cat_en else str(cat_zh)
        header = f"[{ts}] [{level:<5}] [{category}] "

        lines = str(message).split("\n")
        formatted = header + lines[0]
        for extra in lines[1:]:
            formatted += "\n" + (" " * len(header)) + extra
        line = formatted + "\n"

        with self._lock:
            if self._file:
                try:
                    self._file.write(line)
                except Exception:
                    pass
            if self._terminal:
                try:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                except Exception:
                    pass

    # ---------- 快捷方法 ----------
    # 全部支持 **fields：按 键=值 追加到消息后面，方便结构化排查

    def _with_fields(self, msg, fields):
        detail = _format_fields(fields or {})
        return f"{msg} {detail}".strip() if detail else str(msg)

    def dbg(self, cat_zh, cat_en, msg, thread=None, **fields):
        self.log("DEBUG", cat_zh, cat_en, self._with_fields(msg, fields), thread)

    def info(self, cat_zh, cat_en, msg, thread=None, **fields):
        self.log("INFO", cat_zh, cat_en, self._with_fields(msg, fields), thread)

    def warn(self, cat_zh, cat_en, msg, thread=None, **fields):
        self.log("WARN", cat_zh, cat_en, self._with_fields(msg, fields), thread)

    def err(self, cat_zh, cat_en, msg, thread=None, **fields):
        self.log("ERROR", cat_zh, cat_en, self._with_fields(msg, fields), thread)

    def fatal(self, cat_zh, cat_en, msg, thread=None, **fields):
        self.log("FATAL", cat_zh, cat_en, self._with_fields(msg, fields), thread)

    def op(self, cat_zh, action, **fields):
        """记录一次用户操作，例：log.op("设置", "update", key="theme", value="深色主题")"""
        detail = _format_fields(fields)
        message = f"{action} {detail}".strip()
        self.log("OP", cat_zh, "操作", message)

    # ---------- 列表 / 清理 / 导出（供日志页调用） ----------

    def list_logs(self):
        """返回日志列表（当前日志固定置顶）"""
        items = []
        current_suffix = self._current_suffix_text()
        if os.path.exists(self.current_path):
            st = os.stat(self.current_path)
            items.append({
                "name": self._format_display_time(st.st_mtime) + f" {current_suffix}",
                "path": self.current_path,
                "is_current": True,
                "mtime": st.st_mtime,
            })
        if os.path.isdir(LOG_HISTORY_DIR):
            for fn in os.listdir(LOG_HISTORY_DIR):
                fp = os.path.join(LOG_HISTORY_DIR, fn)
                if not os.path.isfile(fp) or not fn.lower().endswith(".log"):
                    continue
                st = os.stat(fp)
                items.append({
                    "name": self._format_display_time(st.st_mtime),
                    "path": fp,
                    "is_current": False,
                    "mtime": st.st_mtime,
                })
        items[1:] = sorted(items[1:], key=lambda x: x["mtime"], reverse=True)
        return items

    def set_language(self, language):
        self._language = language or "简体中文"

    def _current_suffix_text(self):
        return "(Current)" if getattr(self, "_language", "") == "English" else "(当前)"

    def _format_display_time(self, ts):
        dt = datetime.fromtimestamp(ts)
        if getattr(self, "_language", "") == "English":
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return f"{dt.year} 年 {dt.month} 月 {dt.day} 日 {dt.strftime('%H:%M:%S')}"

    def clear_history(self):
        """只删除 history/ 下的**历史归档**日志，返回删除数量

        ⚠️ **当前日志（system_log.log）一个字都不动**：它是本次运行正在写的排查现场。
           想彻底重来就重启程序（当前日志会先归档）。
        """
        count = 0
        if os.path.isdir(LOG_HISTORY_DIR):
            for fn in os.listdir(LOG_HISTORY_DIR):
                fp = os.path.join(LOG_HISTORY_DIR, fn)
                # 只删 .log（和 list_logs / _prune_history 一个口径）
                if not os.path.isfile(fp) or not fn.lower().endswith(".log"):
                    continue
                try:
                    os.remove(fp)
                    count += 1
                except Exception as e:
                    self.err("日志", "log", f"删除历史日志失败: {fn} - {e}")

        # ⚠️ 这里**不**调 _open_current()：当前日志的写句柄从头到尾没关过，
        #    再 open 一次会把老句柄丢掉（句柄泄漏）
        return count

    def _prune_history(self):
        """只保留最近 LOG_MAX_HISTORY 个历史日志"""
        if not os.path.isdir(LOG_HISTORY_DIR):
            return
        files = []
        for fn in os.listdir(LOG_HISTORY_DIR):
            fp = os.path.join(LOG_HISTORY_DIR, fn)
            if os.path.isfile(fp) and fn.lower().endswith(".log"):
                files.append((os.path.getmtime(fp), fp))
        files.sort(reverse=True)
        for _, fp in files[LOG_MAX_HISTORY:]:
            try:
                os.remove(fp)
            except Exception:
                pass

    def export_zip(self, zip_path, file_paths):
        """把指定日志文件打包成 zip"""
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in file_paths:
                if not os.path.isfile(fp):
                    continue
                zf.write(fp, os.path.join("logs", os.path.basename(fp)))
        return zip_path

    def close(self):
        with self._lock:
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None


# 全局单例
log = Logger()
