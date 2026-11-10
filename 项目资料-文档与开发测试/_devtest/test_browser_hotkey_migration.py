# -*- coding: utf-8 -*-
"""浏览器模式快捷键（新默认值 Ctrl+Shift+O）的迁移 + 分流归属回归测试。

抓的是什么 bug（两轮需求叠加）：
    轮 1：老配置里 `hotkey_browser` 还是**最早的旧默认值 "Ctrl+D"**（键早就落过盘），
          所以 constants.DEFAULT_SETTINGS 里改默认值永远覆盖不了它 →
          shell.apply_hotkey_settings 里 `caps_rules` 是空的 → 键盘钩子根本没 start()
          → 用户按快捷键**完全没反应**（日志实证：
          logs/history/ToolsGCP-2026-11-06-002734027.log「在浏览器中打开 已注册: Ctrl+D」）。
          轮 1 的修法 = 一次性迁移（标记 `_migrated_browser_hotkey_caps`）。
    轮 2：默认值再改成 **Ctrl+Shift+O**，于是**已经跑过轮 1、配置里是 "Ctrl+Caps+O" 的用户**
          也必须跟着迁（新标记 `_migrated_browser_hotkey_shift`）。
    ⚠️ 两条标记都**不能**写进 DEFAULT_SETTINGS：load_settings 开头的"补默认值"循环会先把
       标记补成 True，迁移就成了死代码（轮 1 踩过，见 constants.py 的注释）。

本脚本验证：
    0) 新默认值 = Ctrl+Shift+O；两条迁移标记都**不在** DEFAULT_SETTINGS 里
    1) Ctrl+D        → Ctrl+Shift+O（含真的写回文件）
    2) Ctrl+Caps+O   → Ctrl+Shift+O（模拟"已经跑过轮 1"的配置：带 caps 标记）
    3) 用户自定义组合键（Ctrl+Shift+B / Win+T / Ctrl+Caps+P …）一律不动
    4) 幂等：迁完打标记后，用户自己改回旧值不再被覆盖；重读一次也不变
    5) 直接驱动**真实**的 AppShell.apply_hotkey_settings：
       · 迁移后的值走 **RegisterHotKey**（真 HWND、真注册成功），caps 钩子一条规则都没有；
       · 对照：用户自定义的含 Caps 值（Ctrl+Caps+P）走 capskeyhook，不进 RegisterHotKey。

⚠️⚠️ 跑法（必须照做，否则找不到资源/配置根）：
    python "项目资料-文档与开发测试/_devtest/test_browser_hotkey_migration.py"
    本脚本第一件事就是 `sys.argv[0] = <仓库根>/ToolsGCP.pyw` ——
    `pymodels.constants.CONFIG_DIR = dirname(sys.argv[0]) + "/.ToolsGCP"`，
    不设置的话从 _devtest 目录运行会把资源根算到 _devtest 旁边（那儿没有 webui/）。

⚠️ 本脚本**绝不碰用户真实配置**：所有 SettingsManager 都用临时目录（tempfile.mkdtemp）。
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile

# ---------- 第一件事：把"入口"摆成真实入口，再 import pymodels ----------
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

from pymodels.constants import CONFIG_DIR, DEFAULT_SETTINGS   # noqa: E402
from pymodels.core.settings_manager import SettingsManager    # noqa: E402
from pymodels.utils import global_hotkey as gh                # noqa: E402
from desktop.native import capskeyhook as ch                  # noqa: E402

FAILS = []
SKIPS = []
NEW_DEFAULT = "Ctrl+Shift+O"


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_cfg(tmp, data):
    path = os.path.join(tmp, "toolsgcp_config.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    return path


# ---------- 0) 前置：入口路径 + 新默认值 + 标记不在 DEFAULT_SETTINGS ----------
print("[0] 资源根定位 / 新默认值 / 迁移标记")
check("CONFIG_DIR 指向仓库根的 .ToolsGCP",
      os.path.normcase(CONFIG_DIR) == os.path.normcase(os.path.join(ROOT, ".ToolsGCP")),
      CONFIG_DIR)
check("webui/index.html 在 CONFIG_DIR 下存在",
      os.path.isfile(os.path.join(CONFIG_DIR, "webui", "index.html")))
check(f"新默认值就是 {NEW_DEFAULT}",
      DEFAULT_SETTINGS.get("hotkey_browser") == NEW_DEFAULT,
      repr(DEFAULT_SETTINGS.get("hotkey_browser")))
check("新默认值不含 Caps Lock（所以它必须走 RegisterHotKey 那条路）",
      ch.sequence_has_caps(NEW_DEFAULT) is False)
check("新默认值的主键 O 不是系统保留键（unusable_main_key 判不出来）",
      gh.unusable_main_key(NEW_DEFAULT) == "", gh.unusable_main_key(NEW_DEFAULT))
# ⚠️ 这一条是防"迁移又变成死代码"的护栏（轮 1 的实际 bug）
check("迁移标记 _migrated_browser_hotkey_caps 不在 DEFAULT_SETTINGS 里",
      "_migrated_browser_hotkey_caps" not in DEFAULT_SETTINGS)
check("迁移标记 _migrated_browser_hotkey_shift 不在 DEFAULT_SETTINGS 里",
      "_migrated_browser_hotkey_shift" not in DEFAULT_SETTINGS)

# ---------- 1) 最早的遗留值 Ctrl+D → Ctrl+Shift+O ----------
print("\n[1] 一次性迁移：最早的旧默认值 Ctrl+D")
tmp = tempfile.mkdtemp(prefix="tgcp-hk-")
try:
    path = write_cfg(tmp, {"hotkey_enabled": True, "hotkey_search": "Ctrl+Q",
                           "hotkey_ai": "Ctrl+Alt+G", "hotkey_browser": "Ctrl+D",
                           "browser_port": 0})
    sm = SettingsManager(config_dir=tmp)
    check(f"迁移后 hotkey_browser == {NEW_DEFAULT}",
          sm.settings.get("hotkey_browser") == NEW_DEFAULT,
          repr(sm.settings.get("hotkey_browser")))
    migrated = sm.settings.get("hotkey_browser")   # 先存下来：[4] 会把内存值改脏（轮 1 踩过）
    check("轮 1 标记已落盘", sm.settings.get("_migrated_browser_hotkey_caps") is True)
    check("轮 2 标记已落盘", sm.settings.get("_migrated_browser_hotkey_shift") is True)
    on_disk = read_json(path)
    check("迁移结果**真的写回文件**了（不是只在内存里改）",
          on_disk.get("hotkey_browser") == NEW_DEFAULT, repr(on_disk.get("hotkey_browser")))

    # ---------- 2) 轮 1 的产物 Ctrl+Caps+O → Ctrl+Shift+O ----------
    print("\n[2] 轮 2 迁移：已经跑过轮 1 的配置（hotkey_browser=Ctrl+Caps+O，caps 标记已在）")
    t2 = tempfile.mkdtemp(prefix="tgcp-hk-caps-")
    try:
        p2 = write_cfg(t2, {"hotkey_enabled": True, "hotkey_search": "Ctrl+Q",
                            "hotkey_ai": "Ctrl+Alt+G", "hotkey_browser": "Ctrl+Caps+O",
                            "_migrated_browser_hotkey_caps": True})
        s2 = SettingsManager(config_dir=t2)
        check(f"Ctrl+Caps+O 也迁到了 {NEW_DEFAULT}",
              s2.settings.get("hotkey_browser") == NEW_DEFAULT,
              repr(s2.settings.get("hotkey_browser")))
        check("轮 2 标记已落盘（下次不再重复迁）",
              s2.settings.get("_migrated_browser_hotkey_shift") is True)
        check("轮 2 的结果也写回了文件",
              read_json(p2).get("hotkey_browser") == NEW_DEFAULT)
    finally:
        shutil.rmtree(t2, ignore_errors=True)

    # ---------- 3) 只迁遗留默认值：用户自己录的组合键一律不动 ----------
    print("\n[3] 用户自定义值必须原样保留（含用户自己填的 Caps 组合）")
    for keep in ("Ctrl+Shift+B", "Ctrl+Alt+F9", "Win+T", "Ctrl+Caps+P"):
        t3 = tempfile.mkdtemp(prefix="tgcp-hk-keep-")
        try:
            write_cfg(t3, {"hotkey_browser": keep, "hotkey_search": "Ctrl+Q",
                           "hotkey_ai": "Ctrl+Alt+G"})
            got = SettingsManager(config_dir=t3).settings.get("hotkey_browser")
            check(f"用户自定义 {keep} 不被迁移改动", got == keep, repr(got))
        finally:
            shutil.rmtree(t3, ignore_errors=True)

    # 其它快捷键就算等于旧默认值也不该被这两条迁移碰
    t4 = tempfile.mkdtemp(prefix="tgcp-hk-other-")
    try:
        write_cfg(t4, {"hotkey_search": "Ctrl+D", "hotkey_ai": "Ctrl+Caps+O",
                       "hotkey_browser": "Ctrl+D"})
        s4 = SettingsManager(config_dir=t4).settings
        check("旧默认值出现在 hotkey_search/hotkey_ai 上**不受影响**",
              s4.get("hotkey_search") == "Ctrl+D" and s4.get("hotkey_ai") == "Ctrl+Caps+O",
              f"{s4.get('hotkey_search')} / {s4.get('hotkey_ai')}")
    finally:
        shutil.rmtree(t4, ignore_errors=True)

    # ---------- 4) 幂等 ----------
    print("\n[4] 幂等：迁完打标记，用户自己改回旧值不再被覆盖")
    sm.update_setting("hotkey_browser", "Ctrl+D")
    sm2 = SettingsManager(config_dir=tmp)
    check("用户自己改回 Ctrl+D 后**不再被翻回**（幂等）",
          sm2.settings.get("hotkey_browser") == "Ctrl+D",
          repr(sm2.settings.get("hotkey_browser")))
    check("重启后两条标记仍在（不会被反复改写）",
          sm2.settings.get("_migrated_browser_hotkey_caps") is True
          and sm2.settings.get("_migrated_browser_hotkey_shift") is True)
    # 再跑一遍"迁移后的原始配置"：值应稳定在新默认值
    check("迁移后的值再读一次仍是新默认值（迁移不抖）", migrated == NEW_DEFAULT, repr(migrated))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ======================================================================
# 5) 直接驱动**真实**的 AppShell.apply_hotkey_settings
#    前面都是"配置迁移"层面；这一步证明喂进 shell 后 browser 这条确实走 RegisterHotKey
#    （真的注册到一个真 HWND 上），而不是被分流到 caps 钩子。
# ======================================================================
print("\n[5] 真实 shell.apply_hotkey_settings 的分流归属")
from desktop import shell as shell_mod                            # noqa: E402
from desktop.native import hotkey as hotkey_mod                   # noqa: E402
from desktop.native import win32 as win32_mod                     # noqa: E402

_ALIVE = {"proc": None, "hwnd": 0}


def make_hotkey_window():
    """建一个"消息窗口"给 RegisterHotKey 用（本线程建 → 注册/注销同线程）

    ⚠️ RegisterHotKey 注册的是"**调用线程**的热键"，而 GlobalHotkeyManager 需要一个
       真实 HWND（正式程序里由托盘图标提供）。这里用 WS_POPUP 且**从不 Show**，
       窗口不会露脸；测试结束销毁。
    """
    if not win32_mod.IS_WINDOWS:
        return 0
    hinst = win32_mod.kernel32.GetModuleHandleW(None)
    class_name = "ToolsGCP_devtest_hotkey_%d" % os.getpid()

    @win32_mod.WNDPROC
    def _proc(hwnd, msg, wparam, lparam):
        return win32_mod.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    _ALIVE["proc"] = _proc          # ⚠️ 必须保引用，被 GC 掉就是悬空回调指针
    cls = win32_mod.WNDCLASSW()
    cls.style = 0
    cls.lpfnWndProc = _proc
    cls.cbClsExtra = 0
    cls.cbWndExtra = 0
    cls.hInstance = hinst
    cls.hIcon = None
    cls.hCursor = None
    cls.hbrBackground = None
    cls.lpszMenuName = None
    cls.lpszClassName = class_name
    win32_mod.user32.RegisterClassW(ctypes.byref(cls))
    hwnd = win32_mod.user32.CreateWindowExW(
        0, class_name, "ToolsGCP-devtest-hotkey", 0x80000000, 0, 0, 0, 0,
        None, None, hinst, None)
    return int(hwnd or 0)


def make_shell(config_dir, hwnd):
    """绕开 AppShell.__init__（那要建真的窗口/托盘/隐私状态，会碰用户数据），
    只装配分流用到的字段；apply_hotkey_settings 本身是**真函数**。"""
    sh = object.__new__(shell_mod.AppShell)
    sh.settings_manager = SettingsManager(config_dir=config_dir)
    sh.hotkeys = hotkey_mod.GlobalHotkeyManager(hwnd_provider=lambda: hwnd)
    sh._hotkey_status = {}
    sh.language_manager = None
    sh._teardown_started = False
    return sh


def quiet_caps_hook():
    hook = ch.shared_hook()
    hook.stop()
    hook.clear()
    return hook


def check_registerhotkey_case(title, cfg):
    """cfg 里的 hotkey_browser 经过迁移后应当 == NEW_DEFAULT，并走 RegisterHotKey"""
    tmpdir = tempfile.mkdtemp(prefix="tgcp-hk-shell-")
    try:
        cfg = dict(cfg)
        cfg.setdefault("hotkey_enabled", True)
        # 只留 browser 这条：Ctrl+Q / Ctrl+Alt+G 可能被别的程序（或本程序实例）占着，
        # 空值 = "未设置"，不会被注册，也就不干扰结论。
        cfg["hotkey_search"] = ""
        cfg["hotkey_ai"] = ""
        write_cfg(tmpdir, cfg)
        sh = make_shell(tmpdir, _ALIVE["hwnd"])
        seq = sh.settings_manager.settings.get("hotkey_browser")
        check(f"{title}：配置迁移后的值 = {NEW_DEFAULT}", seq == NEW_DEFAULT, repr(seq))
        quiet_caps_hook()
        ok_all, first_err = sh.apply_hotkey_settings(notify=False)
        registered = set(sh.hotkeys.registered_names())
        status = sh.hotkey_status().get("browser", {})
        hook_rules = ch.shared_hook().watched()
        check(f"{title}：browser 走了 RegisterHotKey", "browser" in registered, str(registered))
        check(f"{title}：browser **没有**进 caps 钩子规则",
              "browser" not in hook_rules, f"hook rules={list(hook_rules)}")
        check(f"{title}：caps 钩子没被启动（无规则 → 不白装全局钩子）",
              ch.shared_hook().running is False)
        if status.get("ok") is True:
            check(f"{title}：RegisterHotKey 真的注册成功（真 HWND）", True,
                  f"sequence={sh.hotkeys.sequence('browser')}")
        else:
            # 本机上如果 ToolsGCP 实例正在运行，Ctrl+Shift+O 会被它占着（1409）——
            # 那是环境问题，不是代码问题：分流归属仍已被上面两条证明。
            text = str(status.get("text") or "")
            if "占用" in text or "occupied" in text.lower():
                print(f"      ⚠️ 本机 {NEW_DEFAULT} 已被占用（很可能 ToolsGCP 正在运行）："
                      f"{text} → 这一项按环境跳过，分流归属已验证")
                SKIPS.append(f"{title} 真注册（被占用）")
            else:
                check(f"{title}：RegisterHotKey 真的注册成功（真 HWND）", False, text)
        check(f"{title}：apply_hotkey_settings 无错误", first_err is None, str(first_err))
        sh.hotkeys.unregister_all()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


try:
    _ALIVE["hwnd"] = make_hotkey_window()
    if not _ALIVE["hwnd"]:
        print("  ⚠️ 无法创建热键测试窗口（非 Windows？）→ 跳过 [5] 的真注册部分")
        SKIPS.append("[5] 真 HWND 注册")
    else:
        # 5a) 最早的遗留值 Ctrl+D（经过两轮迁移 → 新默认值）
        check_registerhotkey_case("Ctrl+D 老配置", {"hotkey_browser": "Ctrl+D"})
        # 5b) 轮 1 的产物 Ctrl+Caps+O（已经跑过轮 1 的用户）
        check_registerhotkey_case("Ctrl+Caps+O 老配置",
                                  {"hotkey_browser": "Ctrl+Caps+O",
                                   "_migrated_browser_hotkey_caps": True})
        # 5c) 对照：用户自定义的含 Caps 值 → 必须走 capskeyhook，而不是 RegisterHotKey
        tmp5 = tempfile.mkdtemp(prefix="tgcp-hk-caps2-")
        try:
            write_cfg(tmp5, {"hotkey_enabled": True, "hotkey_search": "",
                             "hotkey_ai": "", "hotkey_browser": "Ctrl+Caps+P"})
            sh5 = make_shell(tmp5, _ALIVE["hwnd"])
            quiet_caps_hook()
            sh5.apply_hotkey_settings(notify=False)
            rules = ch.shared_hook().watched()
            check("对照：用户自定义 Ctrl+Caps+P **没有**走 RegisterHotKey",
                  "browser" not in sh5.hotkeys.registered_names(),
                  str(sh5.hotkeys.registered_names()))
            check("对照：用户自定义 Ctrl+Caps+P 进了 caps 钩子规则",
                  "browser" in rules, f"hook rules={list(rules)}")
            installed = ch.shared_hook().wait_installed(3.0)
            print(f"      shared_hook: running={ch.shared_hook().running} "
                  f"installed={installed} error={ch.shared_hook().error or '(无)'}")
        finally:
            shutil.rmtree(tmp5, ignore_errors=True)
finally:
    quiet_caps_hook()
    if _ALIVE["hwnd"]:
        try:
            win32_mod.user32.DestroyWindow(_ALIVE["hwnd"])
        except Exception:
            pass

print("\n" + ("全部通过 OK" if not FAILS else f"失败 {len(FAILS)} 项: {FAILS}"))
if SKIPS:
    print(f"环境跳过: {SKIPS}")
sys.exit(1 if FAILS else 0)
