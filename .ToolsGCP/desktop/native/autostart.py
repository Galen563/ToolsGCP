r"""开机自启（注册表 Run 项）—— 去掉 PyQt5 的等价实现。
原版在 `pymodels/utils/system_utils.py`，但那个模块顶层 `from PyQt5.QtWidgets import
QApplication`，无 Qt 环境下 import 就炸。这里按**同样的路径与同样的值**重写一份：
    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
    值名 "ToolsGCP"
    .pyw 源码运行时 → "<pythonw.exe>" "<script.pyw>" --autostart
    打包 exe 时     → "<ToolsGCP.exe>" --autostart（exe 自己就是程序，不再拼 script）
⚠️ 值名与命令格式必须和原版一字不差（.pyw 那条）：老用户机器上已经有这条注册表项，
   格式不一致会导致"开过一次自启之后被新版本写坏"或"关闭自启时删不掉"。
   exe 那条是本轮修正：旧格式 `"exe" "exe" --autostart` 把 exe 当脚本传了两遍，
   任务管理器"启动项"里显示成"ToolsGCP.exe 的 ToolsGCP.exe"，且多余参数可能拖慢
   启动期的参数解析（--update/--restart 那套对 argv 位置敏感）。

⚠️⚠️ 本轮新增：写 Run 项时**同步清掉 Explorer 的"禁用"标记**。
   Windows 的开机启动流程除了读 `...\CurrentVersion\Run`，还会看
   `...\Explorer\StartupApproved\Run` 里的同名值：
       首字节 0x03 = 启用（后面 8 字节是最后一次"启用时刻"的 FILETIME）
       首字节 0x02 = **已禁用**（用户在任务管理器"启动应用"里点过"禁用"）
   被标记 0x02 后，Explorer **开机不再拉起**这一项 —— 但我们的设置里
   `startup_with_windows` 还是 True、Run 值也还在 → 用户看到的就是
   "开关明明开着，程序却不自启"（= 用户原话"开关操控不好使"的真实根因之一，
   本机实测取证：ToolsGCP 的 StartupApproved 标记就是 02）。
   所以：**打开开关 = 写 Run + 删标记**（删掉 = 恢复默认启用，最干净；
   不删的话任务管理器还会显示"已禁用"）。
"""

import os
import sys

from . import win32

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# 任务管理器「启动应用」的启用/禁用标记（首字节 0x03=启用 / 0x02=已禁用）
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
APP_NAME = "ToolsGCP"
# StartupApproved 里"已禁用"标记的首字节
_MARK_DISABLED = 0x02
_MARK_ENABLED = 0x03


def _log(level: str, message: str):
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)("系统", "autostart", message)
    except Exception:
        pass


def is_packaged_exe() -> bool:
    """是否运行在打包 exe 里（PyInstaller：sys.executable 就是 ToolsGCP.exe 本身）"""
    return bool(getattr(sys, "frozen", False))


def command_line() -> str:
    """开机自启要写的命令行

    · 源码运行：`"<pythonw.exe>" "<ToolsGCP.pyw>" --autostart`
      —— 和原版 `set_windows_autostart` 一字不差（老用户机器上的既有值就是它，
         格式变了会导致"关自启时删不掉 / 开一次就被写坏"）。
      ⚠️ 用 pythonw.exe 而不是 python.exe：python.exe 会闪一个控制台黑窗。
      ⚠️ `python_dir` 取 `sys.executable` 同目录（当前解释器旁边一定有个
         pythonw.exe；找不到才退回 sys.executable 本身）。

    · 打包 exe（本轮修正）：`"<ToolsGCP.exe>" --autostart`
      旧写法走的是下面那条 `f'"{sys.executable}" "{script_path}"'`，
      而 exe 里 `sys.argv[0] == sys.executable` → 拼出来是
      `"ToolsGCP.exe" "ToolsGCP.exe" --autostart`：exe 被当脚本传了两遍。
      后果不只是难看 —— 任务管理器「启动应用」里命令行显示重复、
      入口对 argv 位置敏感（`--update --pid --target` / `--restart <pid>`），
      多一个参数就多一分解析歧义。exe 自己就是程序，不需要"解释器 + 脚本"两段。
    """
    if is_packaged_exe():
        return f'"{os.path.abspath(sys.executable)}" --autostart'
    script_path = os.path.abspath(sys.argv[0])
    if script_path.lower().endswith(".pyw"):
        python_dir = os.path.dirname(sys.executable)
        pythonw_path = os.path.join(python_dir, "pythonw.exe")
        if not os.path.exists(pythonw_path):
            pythonw_path = sys.executable
        return f'"{pythonw_path}" "{script_path}" --autostart'
    return f'"{sys.executable}" "{script_path}" --autostart'


def is_enabled() -> bool:
    if not win32.IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(str(value or "").strip())
    except FileNotFoundError:
        return False
    except Exception:
        return False


def startup_disabled_by_explorer() -> bool:
    """任务管理器/Explorer 有没有把我们的启动项**标记为禁用**
    ⚠️ 判据：`StartupApproved\\Run` 下值名 "ToolsGCP" 的二进制首字节 == 0x02。
       键/值不存在 = 从未被禁用（Windows 的默认状态是"启用"）。
    """
    if not win32.IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as key:
            value, vtype = winreg.QueryValueEx(key, APP_NAME)
        if vtype != winreg.REG_BINARY or not value:
            return False
        return int(value[0]) == _MARK_DISABLED
    except FileNotFoundError:
        return False
    except Exception:
        return False


def clear_disabled_mark() -> str:
    """清掉 Explorer 的"禁用"标记（= 恢复默认启用），返回说明文本
    ⚠️ 为什么**删值**而不是写成 0x03 + 当前 FILETIME：
       微软没有公开这个结构的写法，写错长度（必须是 12 字节）任务管理器可能仍显示
       "已禁用"；而"值不存在"是 Windows 自己的默认状态（新装的 Run 项就没有这条），
       删掉它最可靠 —— 实测本机 ToolsGCP 就是 02 开头，删掉后 Explorer 重新按
       "启用"处理，任务管理器里也不再显示"已禁用"。
    ⚠️ 只动 HKCU、只动我们自己的值名；失败不抛异常（不让自启主流程被打断）。
    """
    if not win32.IS_WINDOWS:
        return "非 Windows"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0,
                            winreg.KEY_WRITE) as key:
            winreg.DeleteValue(key, APP_NAME)
        return "已清除 StartupApproved 禁用标记"
    except FileNotFoundError:
        return "无禁用标记（本来就是启用）"
    except Exception as exc:                               # noqa: BLE001
        _log("warn", f"清除 StartupApproved 标记失败（不影响 Run 项本身）: {exc}")
        return f"清除标记失败: {exc}"


def set_enabled(enabled: bool):
    """开/关开机自启，返回 (是否成功, 错误信息)
    ⚠️ 本轮联动（用户报"开关操控不好使"）：
       · 开 → 写 Run 项 **+ 清掉 Explorer 的禁用标记**（否则开机不拉起，
         且任务管理器"启动应用"显示"已禁用"）；
       · 关 → 删 Run 项，**顺带把禁用标记也删掉**（值都没了，标记留着是垃圾，
         还会让任务管理器里出现一条"ToolsGCP 已禁用"的空壳条目）。
    """
    if not win32.IS_WINDOWS:
        return False, "仅支持Windows系统"
    try:
        import winreg
        if enabled:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                     winreg.KEY_WRITE)
            except FileNotFoundError:
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY)
            with key:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command_line())
            note = clear_disabled_mark()
            _log("info", f"已添加开机自启动: {command_line()}（{note}）")
            return True, ""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_WRITE) as key:
                winreg.DeleteValue(key, APP_NAME)
            _log("info", "已移除开机自启动")
        except FileNotFoundError:
            # Run 值本来就不存在（用户从没开过，或已被别的路径删掉）——
            # ⚠️ 但**禁用标记仍可能残留**（它是另一条独立的键）。
            #    单测实证过：先删 Run 再标禁用，关自启时标记就漏清了，
            #    任务管理器里留一条"ToolsGCP 已禁用"的空壳条目。
            pass
        # ⚠️ 无论 Run 值删没删成，标记都要清（本轮 ① 的完整语义）
        note = clear_disabled_mark()
        _log("info", f"关闭开机自启收尾：{note}")
        return True, ""
    except Exception as exc:                               # noqa: BLE001
        _log("err", f"开机自启动设置失败: {exc}")
        return False, str(exc)
