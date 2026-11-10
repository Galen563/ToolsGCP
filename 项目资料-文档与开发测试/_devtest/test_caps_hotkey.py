# -*- coding: utf-8 -*-
"""CapsComboHook 的回归测试（浏览器模式快捷键 Ctrl+Caps+O 的核心）

为什么值得单独立一个测试文件：这条快捷键走的是**低级键盘钩子**，不是 RegisterHotKey，
出问题时表现是"按了完全没反应"或"按完大写锁定被误开"，都很难在真机上定位。
本测试不装真钩子（真钩子在沙箱里可能被拒），只测**判定逻辑** handle_key_event()：
把 GetKeyState 换成可控的假实现，喂按键序列看结果。

跑法：
    python "项目资料-文档与开发测试/_devtest/test_caps_hotkey.py"
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

from desktop.native import capskeyhook as ch           # noqa: E402


class FakeKeyState:
    """可控的 GetKeyState：只有列在 held 里的键算"按下"（返回带 0x8000 的 SHORT）"""

    def __init__(self, held=()):
        self.held = set(held)

    def __call__(self, vk):
        return -32768 if int(vk) in self.held else 0


def make_hook(sequence="Ctrl+Caps+O"):
    hook = ch.CapsComboHook()
    fired = []
    hook.set_callback(lambda name: fired.append(name))
    ok, err = hook.watch("browser", sequence)
    assert ok, f"watch 失败: {err}"
    return hook, fired


def press(hook, held, vk, is_up=False):
    """喂一次按键：先把修饰键状态设成 held，再调 handle_key_event"""
    real = ch._user32.GetKeyState
    ch._user32.GetKeyState = FakeKeyState(held)
    try:
        return hook.handle_key_event(vk, is_up)
    finally:
        ch._user32.GetKeyState = real


def case_parse():
    vk, ctrl, alt, shift, win, err = ch._resolve_main_key("Ctrl+Caps+O")
    assert err == "", f"Ctrl+Caps+O 解析失败: {err}"
    assert vk == ord("O") and ctrl and not alt and not shift and not win
    assert ch.sequence_has_caps("Ctrl+Caps+O") is True
    assert ch.sequence_has_caps("Ctrl+Q") is False
    assert ch.sequence_has_caps("Ctrl+Alt+G") is False
    # 非法输入：与原解析器同一口径（裸主键 / 空 / 多个真主键）
    assert ch._resolve_main_key("O")[5] == "hotkey_err_need_modifier"
    assert ch._resolve_main_key("")[5] == "hotkey_err_empty"
    assert ch._resolve_main_key("Ctrl+Shift+A")[5] == ""     # 合法组合
    print("  1) 序列解析 ......................... OK")


def case_full_combo():
    """完整按法：Ctrl 按下 → Caps 按下 → O 按下 → 全部抬起 ⇒ 触发一次"""
    hook, fired = make_hook()
    press(hook, {ch.VK_CONTROL}, 0x11)                       # Ctrl 本身不参与匹配
    swallowed = press(hook, {ch.VK_CONTROL}, ch.VK_CAPITAL)  # Caps 落下：要吞掉
    assert swallowed is True, "Ctrl 按着时 Caps 没被吞 → 用户会被误切大写锁定"
    assert hook._caps_down is True, "吞掉的同时必须**记下** Caps 已按下（否则组合键失效）"
    hook._last_fire = 0.0
    press(hook, {ch.VK_CONTROL, ch.VK_CAPITAL}, ord("O"))
    time.sleep(0.25)
    assert fired == ["browser"], f"Ctrl+Caps+O 没触发: {fired}"
    print("  2) Ctrl+Caps+O 命中 ................. OK")


def case_caps_not_swallowed_when_alone():
    """单独按 Caps（没按 Ctrl）绝不能被吞：那是用户在大写锁定"""
    hook, fired = make_hook()
    swallowed = press(hook, set(), ch.VK_CAPITAL)
    assert swallowed is False, "单独按 Caps 被吞了 → 大写锁定按不了"
    swallowed = press(hook, set(), ch.VK_CAPITAL, is_up=True)
    assert swallowed is False
    print("  3) 单独按 Caps 不受影响 ............. OK")


def case_requires_all_mods():
    """少按任何一个修饰键都不该触发（尤其不能把 Caps 当成可有可无）"""
    for name, held in (("没按 Ctrl", set()),
                       ("按了 Ctrl 但 Caps 没按", {ch.VK_CONTROL})):
        hook, fired = make_hook()
        if ch.VK_CAPITAL in held:
            hook._caps_down = True
        hook._last_fire = 0.0
        press(hook, held, ord("O"))
        time.sleep(0.15)
        assert fired == [], f"{name} 也触发了: {fired}"
    print("  4) 修饰键不齐不触发 ................. OK")


def case_wrong_main_key():
    hook, fired = make_hook()
    press(hook, {ch.VK_CONTROL}, ch.VK_CAPITAL)
    hook._last_fire = 0.0
    press(hook, {ch.VK_CONTROL}, ord("Q"))                   # 主键不对
    time.sleep(0.15)
    assert fired == [], f"按 Q 也触发了: {fired}"
    print("  5) 主键不对不触发 ................... OK")


def case_throttle():
    """按住 O 不放会连发（auto-repeat）：必须节流，不能刷出一排浏览器窗口"""
    hook, fired = make_hook()
    press(hook, {ch.VK_CONTROL}, ch.VK_CAPITAL)
    hook._last_fire = 0.0
    press(hook, {ch.VK_CONTROL}, ord("O"))
    press(hook, {ch.VK_CONTROL}, ord("O"))                   # 立刻再来一次
    press(hook, {ch.VK_CONTROL}, ord("O"))
    time.sleep(0.5)
    assert len(fired) == 1, f"节流失效，触发了 {len(fired)} 次"
    print("  6) auto-repeat 节流 ................. OK")


def case_other_sequences():
    """钩子也能管不含 Caps 的组合（万一用户把浏览器快捷键改成 Ctrl+Shift+B）"""
    hook, fired = make_hook("Ctrl+Shift+B")
    hook._caps_down = False                                  # 不该要求 Caps
    hook._last_fire = 0.0
    press(hook, {ch.VK_CONTROL, 0x10}, ord("B"))
    time.sleep(0.2)
    assert fired == ["browser"], f"Ctrl+Shift+B 没触发: {fired}"
    print("  7) 非 Caps 组合同样可用 ............. OK")


def case_lifecycle():
    """start/stop 必须干净：线程不残留、钩子被摘（残留会让进程退不掉）"""
    hook = ch.CapsComboHook()
    hook.watch("browser", "Ctrl+Caps+O")
    hook.start()
    time.sleep(0.8)
    installed = hook.running and not hook.error
    print(f"  （真 SetWindowsHookEx: {'装上' if installed else '未装上: ' + hook.error}）")
    hook.stop()
    time.sleep(0.4)
    assert not hook.running, "stop 之后 running 还是 True"
    assert hook._hook == 0, "钩子句柄没清零"
    if hook._thread is not None:
        assert not hook._thread.is_alive(), "钩子线程还活着（会拖住进程退出）"
    # 幂等：重复 stop / 重复 start 不该炸
    hook.stop()
    hook.start()
    time.sleep(0.3)
    hook.stop()
    print("  8) 起停生命周期 ..................... OK")


if __name__ == "__main__":
    # 控制台可能是 GBK（中文 Windows 默认），打勾符号会 UnicodeEncodeError
    # → 直接强制 stdout 用 UTF-8，忽略编码错误（测试本身不该因为打印而失败）
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("CapsComboHook 回归测试")
    case_parse()
    case_full_combo()
    case_caps_not_swallowed_when_alone()
    case_requires_all_mods()
    case_wrong_main_key()
    case_throttle()
    case_other_sequences()
    case_lifecycle()
    print("\n全部通过 OK")
