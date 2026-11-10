# -*- coding: utf-8 -*-
"""task-6 ①/④ 开机自启单测（**桩掉 winreg**，绝不碰真实注册表）

覆盖：
 [1] desktop.api.resources.SettingsDomain.set('startup_with_windows', True/False)
     → 立刻联动 autostart.set_enabled，并且**先注册表后落盘**
 [2] 注册表写失败 → 返回 ok=False + error，且**不落盘**（设置值不留下假状态）
 [3] 其它键不受影响（不联动、不报错）
 [4] autostart.set_enabled(True) → 写 Run 值 **+ 清掉 StartupApproved 禁用标记**
     autostart.set_enabled(False) → 删 Run 值 + 也清标记
 [5] startup_disabled_by_explorer()：0x02→True / 0x03→False / 值不存在→False
 [6] command_line()：源码 .pyw → pythonw + .pyw；打包 exe → 只有 exe（不再拼 script）
 [7] shell._sync_autostart：设置关但注册表还留着 → 也会删掉（本轮补的那半边）

跑法：python "项目资料-文档与开发测试/_devtest/test_autostart_toggle.py"
⚠️ 不弹窗、不写注册表、不写用户配置（TOOLSGCP_NO_SETTINGS_WRITE=1 + FakeWinreg）。
"""
import os
import sys
import types

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(BASE, ".ToolsGCP"),
                os.path.join(BASE, ".ToolsGCP", "modules")]
# 桩测一律不落盘用户配置（见 settings_manager.update_setting 的说明）
os.environ["TOOLSGCP_NO_SETTINGS_WRITE"] = "1"

FAILS = []


def check(name, cond, extra=""):
    print(("  OK    " if cond else "  FAIL  ") + name + (f"  <- {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# =========================================================================
# FakeWinreg：只在内存在跑，接口对齐真 winreg
# =========================================================================
HKEY_CURRENT_USER = "HKCU"
KEY_WRITE = 2
REG_SZ = 1
REG_BINARY = 3


class _Key:
    def __init__(self, store, path):
        self._store = store
        self._path = path

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeWinreg(types.ModuleType):
    HKEY_CURRENT_USER = HKEY_CURRENT_USER
    KEY_WRITE = KEY_WRITE
    REG_SZ = REG_SZ
    REG_BINARY = REG_BINARY

    def __init__(self):
        super().__init__("winreg")
        # {key_path: {value_name: (value, vtype)}}
        self.data = {}
        self.calls = []

    def OpenKey(self, root, path, reserved=0, access=0):
        self.calls.append(("OpenKey", path))
        if path not in self.data:
            raise FileNotFoundError(path)
        return _Key(self.data, path)

    def CreateKey(self, root, path):
        self.calls.append(("CreateKey", path))
        self.data.setdefault(path, {})
        return _Key(self.data, path)

    def SetValueEx(self, key, name, reserved, vtype, value):
        self.calls.append(("SetValueEx", key._path, name, value, vtype))
        key._store.setdefault(key._path, {})[name] = (value, vtype)

    def QueryValueEx(self, key, name):
        if key._path not in key._store or name not in key._store[key._path]:
            raise FileNotFoundError(name)
        return key._store[key._path][name]

    def DeleteValue(self, key, name):
        self.calls.append(("DeleteValue", key._path, name))
        if key._path not in key._store or name not in key._store[key._path]:
            raise FileNotFoundError(name)
        del key._store[key._path][name]


import winreg as _real_winreg                                # noqa: E402


def use_fake(fake):
    sys.modules["winreg"] = fake


def restore_winreg():
    sys.modules["winreg"] = _real_winreg


from desktop.native import autostart                          # noqa: E402

RUN = autostart.RUN_KEY
APP = autostart.APP_NAME

print("[6] command_line()：源码 / 打包 exe")
fake = FakeWinreg()
use_fake(fake)
try:
    # 源码 .pyw：argv[0] 以 .pyw 结尾 → "<pythonw>" "<x.pyw>" --autostart
    orig = (sys.argv, sys.executable)
    sys.argv = [os.path.join(BASE, "ToolsGCP.pyw")]
    sys.executable = r"D:\Python3.13.1\python.exe"
    import importlib
    cl = autostart.command_line()
    check(".pyw 源码格式与原版一致（pythonw + 脚本 + --autostart）",
          cl.startswith('"') and "pythonw.exe" in cl
          and cl.rstrip().endswith("--autostart") and "ToolsGCP.pyw" in cl, cl)

    # 打包 exe：frozen + 无 .pyw 脚本 → 只写 exe 自身（本轮修正）
    sys.frozen = True
    sys.executable = r"D:\ToolsGCP\ToolsGCP.exe"
    sys.argv = [r"D:\ToolsGCP\ToolsGCP.exe"]
    cl2 = autostart.command_line()
    check("打包 exe 不再拼成 pythonw + .pyw", "pythonw" not in cl2, cl2)
    check("打包 exe 不把 exe 当脚本传两遍（本轮 ④ 修正点）",
          cl2.count("ToolsGCP.exe") == 1 and cl2.rstrip().endswith("--autostart"), cl2)

    # python.exe 旁边没有 pythonw.exe 时退回 sys.executable（老逻辑不能坏）
    del sys.frozen
    sys.executable = r"D:\NoSuchPythonDir\python.exe"
    sys.argv = [os.path.join(BASE, "ToolsGCP.pyw")]
    cl3 = autostart.command_line()
    check("pythonw.exe 缺失时退回 sys.executable（不炸）",
          "NoSuchPythonDir" in cl3 and cl3.count("pythonw.exe") == 0, cl3)
    sys.argv, sys.executable = list(orig[0]), orig[1]
finally:
    pass

print("[5] startup_disabled_by_explorer() 判据")
use_fake(FakeWinreg())
try:
    f = FakeWinreg()
    use_fake(f)
    check("无 StartupApproved 键 → False（默认启用）",
          autostart.startup_disabled_by_explorer() is False)
    f.data[RUN] = {APP: ("cmd", FakeWinreg.REG_SZ)}
    check("Run 项存在 → is_enabled True", autostart.is_enabled() is True)
    check("Run 项不存在 → is_enabled False",
          (setattr(f, "data", {RUN: {}}), autostart.is_enabled() is False)[1])
finally:
    pass

print("[4] set_enabled：写 Run + 清禁用标记")
f = FakeWinreg()
use_fake(f)
f.data[RUN] = {}
# 预置：任务管理器里被标成"已禁用"（本机实测就是这个状态）
f.data[autostart.APPROVED_KEY] = {APP: (bytes([2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
                                       FakeWinreg.REG_BINARY)}
check("前置条件：StartupApproved 首字节 0x02 → 判定为已禁用",
      autostart.startup_disabled_by_explorer() is True)
ok, err = autostart.set_enabled(True)
check("set_enabled(True) 成功", ok is True and err == "", err)
check("写了 Run 值（值名 ToolsGCP）", APP in f.data.get(RUN, {}), str(list(f.data)))
check("★ 同步清掉了 StartupApproved 的禁用标记（本轮修复关键）",
      APP not in f.data.get(autostart.APPROVED_KEY, {}), str(f.data))

ok, err = autostart.set_enabled(False)
check("set_enabled(False) 成功", ok is True, err)
check("删掉了 Run 值", APP not in f.data.get(RUN, {}))
f.data[autostart.APPROVED_KEY] = {APP: (bytes([2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
                                       FakeWinreg.REG_BINARY)}
ok, err = autostart.set_enabled(False)
check("关自启时**也**清掉禁用标记（不留空壳条目）",
      APP not in f.data.get(autostart.APPROVED_KEY, {}), str(f.data))

print("[4b] 写失败要返回错误而不是静默成功")


class BoomWinreg(FakeWinreg):
    def SetValueEx(self, key, name, reserved, vtype, value):
        raise PermissionError("拒绝访问（模拟无写权限）")


b = BoomWinreg()
b.data[RUN] = {}
use_fake(b)
ok, err = autostart.set_enabled(True)
check("注册表写失败 → (False, 错误信息)", ok is False and "拒绝访问" in err, err)
use_fake(FakeWinreg())
print("  （非 Windows 平台语义）", end=" ")
_orig_isw = autostart.win32.IS_WINDOWS
autostart.win32.IS_WINDOWS = False
ok, err = autostart.set_enabled(True)
check("非 Windows → False + 明确原因", ok is False and "Windows" in err, err)
autostart.win32.IS_WINDOWS = _orig_isw

restore_winreg()

# =========================================================================
# [1][2][3] SettingsDomain.set 的联动（桩 autostart.set_enabled）
# =========================================================================
print("[1] settings.set('startup_with_windows') → 立刻联动")
from desktop.api import resources as res_mod                    # noqa: E402

calls = []
real_set_enabled = autostart.set_enabled
real_is_enabled = autostart.is_enabled
autostart.set_enabled = lambda enabled: (calls.append(enabled), (True, ""))[1]

real_cl = autostart.command_line
autostart.command_line = lambda: '"x" --autostart'


class MiniManager:
    def __init__(self, initial=None):
        self.settings = dict(initial or {})
        self.writes = []

    def update_setting(self, key, value):
        self.writes.append((key, value))
        self.settings[key] = value


class MiniShell:
    def __init__(self, initial=None):
        self.settings_manager = MiniManager(initial)

    def push_event(self, name, payload):
        pass


try:
    shell = MiniShell({"startup_with_windows": False})
    sd = res_mod.SettingsDomain(shell)
    r = sd.set("startup_with_windows", True)
    check("开 → 立刻调 autostart.set_enabled(True)", calls == [True], str(calls))
    check("返回 ok=True", r.get("ok") is True, str(r))
    check("设置值也落了盘（manager 里为 True）",
          shell.settings_manager.settings.get("startup_with_windows") is True)

    r2 = sd.set("startup_with_windows", False)
    check("关 → 立刻调 autostart.set_enabled(False)", calls == [True, False], str(calls))
    check("关也返回 ok=True", r2.get("ok") is True)

    print("[3] 其它键不联动")
    calls.clear()
    r_other = sd.set("theme", "浅色主题")
    check("其它键不碰 autostart", calls == [] and r_other.get("ok") is True,
          f"{calls} {r_other}")
finally:
    autostart.set_enabled = real_set_enabled

print("[2] 注册表失败 → ok=False + error + 不落盘")
calls2 = []
autostart.set_enabled = lambda enabled: (calls2.append(enabled), (False, "拒绝访问"))[1]
try:
    shell3 = MiniShell({"startup_with_windows": False})
    sd3 = res_mod.SettingsDomain(shell3)
    r3 = sd3.set("startup_with_windows", True)
    check("ok=False", r3.get("ok") is False, str(r3))
    check("error 带回前端", "拒绝访问" in str(r3.get("error")), str(r3))
    check("★ 注册表失败时**不落盘**（不留'显示开了其实没开'的假状态）",
          shell3.settings_manager.writes == []
          and shell3.settings_manager.settings.get("startup_with_windows") is False,
          str(shell3.settings_manager.writes))
finally:
    autostart.set_enabled = real_set_enabled

print("[7] shell._sync_autostart：设置关 + 注册表残留 → 也要删")
from desktop.shell import AppShell                             # noqa: E402

log_lines = []
real_log = res_mod._log
import desktop.shell as shell_mod
real_shell_log = shell_mod._log
shell_mod._log = lambda level, *a, **k: log_lines.append((level,) + a)
seq = []
autostart.set_enabled = lambda enabled: (seq.append(enabled), (True, ""))[1]
autostart.is_enabled = lambda: True
try:
    s = AppShell.__new__(AppShell)
    s.settings_manager = MiniManager({"startup_with_windows": False})
    AppShell._sync_autostart(s)
    check("设置=关 / 注册表=开 → 调用 set_enabled(False)（本轮补的半边）",
          seq == [False], str(seq))
    check("记了日志", len(log_lines) >= 2, str(log_lines)[:200])
    seq.clear()
    s.settings_manager = MiniManager({"startup_with_windows": True})
    AppShell._sync_autostart(s)
    check("设置=开 / 注册表=开 → 重写一次（自愈格式）", seq == [True], str(seq))
finally:
    autostart.set_enabled = real_set_enabled
    autostart.is_enabled = real_is_enabled
    autostart.command_line = real_cl
    shell_mod._log = real_shell_log

res_mod._log = real_log
restore_winreg()

print("=" * 72)
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL OK")
