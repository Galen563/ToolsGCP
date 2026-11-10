"""全局热键（Win32 RegisterHotKey）—— 去掉 PyQt5 的等价实现。
========== 与 `pymodels/utils/global_hotkey.py` 的关系 ==========
原版的**解析/回显/校验**逻辑（解析 Caps Lock 不能做主键、OEM 标点键原样回显、0xBD 十六进制
幂等、不许裸字母数字）是踩了很多坑的成果，**一行都不能改**。所以这里不重写解析，
而是直接从原模块借：
    from pymodels.utils.global_hotkey import parse_sequence, format_sequence, unusable_main_key
⚠️ 原模块顶层 `from PyQt5.QtCore import ...`，在无 Qt 环境下会 ImportError。所以这里做一个
   **按需加载**：只有真的要用热键时才 import；import 失败就退回本文件的纯 ctypes 解析
   （逻辑逐行照抄原版，保证结果一致）。这样"没有 PyQt5 也能跑 Web 版"。
========== 线程模型 ==========
原版靠 `QAbstractNativeEventFilter` 在 Qt 事件循环里收 WM_HOTKEY。pywebview 没有 Qt
事件循环，所以这里把热键挂到托盘那条**自建消息线程**的窗口上（见 tray.py）：WM_HOTKEY 由
`DispatchMessage` 送到该窗口的过程函数，再由它回调到本管理器。实测可收到（PostMessage 合成
的 WM_HOTKEY 能命中）。
"""

import ctypes
import threading

from . import win32
from .win32 import (ERROR_HOTKEY_ALREADY_REGISTERED, MOD_ALT, MOD_CONTROL, MOD_NOREPEAT,
                    MOD_SHIFT, MOD_WIN)

HOTKEY_ID_BASE = 0xA001
MAX_HOTKEYS = 16

# ---------- 解析逻辑的兜底实现（必须与 pymodels/utils/global_hotkey.py 逐行等价）----------
_ERROR_FALLBACK = {
    "hotkey_err_unsupported": "Global hotkeys are not supported on this system",
    "hotkey_err_too_many": "Too many hotkeys are registered",
    "hotkey_err_empty": "The hotkey is empty",
    "hotkey_err_one_main_key": ("Only one main key is allowed — got both "
                                "{first} and {second}"),
    "hotkey_err_no_main_key": "Missing the main key (for example Q or F9)",
    "hotkey_err_unsupported_key": "Unsupported key: {key}",
    "hotkey_err_need_modifier": ("A hotkey needs at least one modifier "
                                 "(Ctrl / Alt / Shift / Win) or an F1–F24 key"),
    "hotkey_err_occupied": ("The shortcut {sequence} is already taken by "
                            "another program — please pick another one"),
    "hotkey_err_register_failed": ("Could not register the shortcut {sequence} "
                                   "(error code {code})"),
    "hotkey_err_system_key": ("{key} cannot be the main key of a shortcut "
                              "(the system reserves it) — please pick another "
                              "combination"),
}

UNUSABLE_MAIN_KEYS = {0x14: "Caps Lock", 0x90: "Num Lock", 0x91: "Scroll Lock"}

_MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT,
              "shift": MOD_SHIFT, "win": MOD_WIN, "super": MOD_WIN, "meta": MOD_WIN}

_VK_CODES = {}
for _c in range(ord("A"), ord("Z") + 1):
    _VK_CODES[chr(_c)] = _c
for _d in range(ord("0"), ord("9") + 1):
    _VK_CODES[chr(_d)] = _d
for _i in range(1, 25):
    _VK_CODES[f"F{_i}"] = 0x6F + _i
_VK_CODES.update({
    "SPACE": 0x20, "TAB": 0x09, "ENTER": 0x0D, "RETURN": 0x0D,
    "ESC": 0x1B, "ESCAPE": 0x1B, "BACKSPACE": 0x08, "DELETE": 0x2E,
    "INSERT": 0x2D, "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "CAPS": 0x14, "CAPSLOCK": 0x14,
    "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC,
    ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF, "`": 0xC0,
})

_VK_NAMES = {
    0x14: "Caps", 0x20: "Space", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
    0x08: "Backspace", 0x2E: "Delete", 0x2D: "Insert", 0x24: "Home", 0x23: "End",
    0x21: "PageUp", 0x22: "PageDown",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
}
_VK_OEM_NAMES = {
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
    0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}
_VK_ALIASES = {
    "PGUP": "PAGEUP", "PGDN": "PAGEDOWN", "DEL": "DELETE",
    "INS": "INSERT", "SPACEBAR": "SPACE", "UPARROW": "UP",
    "DOWNARROW": "DOWN", "LEFTARROW": "LEFT", "RIGHTARROW": "RIGHT",
    "CAPSLK": "CAPS", "CAPITAL": "CAPS",
}

import re as _re


def _err(err_key: str, **kwargs) -> str:
    """报错文案按当前界面语言来（原版同名函数；第一个参数必须叫 err_key，理由见原版注释）"""
    template = _ERROR_FALLBACK.get(err_key, err_key)
    try:
        from pymodels.core.language_manager import get_current_manager
        manager = get_current_manager()
        if manager is not None:
            text = manager.get_text("settings", err_key)
            if text and text != err_key:
                template = str(text)
    except Exception:
        pass
    try:
        return template.format(**kwargs) if kwargs else template
    except Exception:
        return template


def _parse_sequence_local(text: str):
    if not text or not str(text).strip():
        return 0, 0, _err("hotkey_err_empty")
    parts = [p.strip() for p in str(text).replace(" ", "").split("+") if p.strip()]
    if not parts:
        return 0, 0, _err("hotkey_err_empty")
    mods = 0
    key = None
    for part in parts:
        low = part.lower()
        if low in _MODIFIERS:
            mods |= _MODIFIERS[low]
            continue
        if key is not None:
            return 0, 0, _err("hotkey_err_one_main_key", first=key, second=part)
        key = part
    if key is None:
        return 0, 0, _err("hotkey_err_no_main_key")
    name = _VK_ALIASES.get(key.upper(), key.upper())
    vk = _VK_CODES.get(name)
    if vk is None and len(name) == 1:
        vk = ord(name)
    if vk is None and _re.fullmatch(r"0X[0-9A-F]{1,3}", name):
        vk = int(name[2:], 16)
    if vk is None:
        return 0, 0, _err("hotkey_err_unsupported_key", key=key)
    if not mods and not (0x70 <= vk <= 0x87):
        return 0, 0, _err("hotkey_err_need_modifier")
    return mods, vk, None


def _format_sequence_local(mods: int, vk: int) -> str:
    parts = []
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    if mods & MOD_WIN:
        parts.append("Win")
    if vk in _VK_NAMES:
        parts.append(_VK_NAMES[vk])
    elif vk in _VK_OEM_NAMES:
        parts.append(_VK_OEM_NAMES[vk])
    elif 0x70 <= vk <= 0x87:
        parts.append(f"F{vk - 0x6F}")
    elif 32 < vk < 127:
        parts.append(chr(vk).upper())
    else:
        parts.append(f"0x{vk:02X}")
    return "+".join(parts)


def _unusable_local(sequence: str) -> str:
    _mods, vk, err = _parse_sequence_local(sequence)
    if err:
        return ""
    return UNUSABLE_MAIN_KEYS.get(vk, "")


_shared = None
_shared_lock = threading.Lock()


def _core():
    """优先用原版解析函数（单一事实来源）；拿不到就用本文件的等价实现"""
    global _shared
    if _shared is not None:
        return _shared
    with _shared_lock:
        if _shared is not None:
            return _shared
        try:
            from pymodels.utils import global_hotkey as original
            _shared = (original.parse_sequence, original.format_sequence,
                       original.unusable_main_key)
        except Exception:
            _shared = (_parse_sequence_local, _format_sequence_local, _unusable_local)
        return _shared


def parse_sequence(text):
    return _core()[0](text)


def format_sequence(mods, vk):
    return _core()[1](mods, vk)


def unusable_main_key(sequence: str) -> str:
    return _core()[2](sequence)


def normalize_sequence(text: str) -> str:
    mods, vk, err = parse_sequence(text)
    if err:
        return ""
    return format_sequence(mods, vk)


class GlobalHotkeyManager:
    """全局热键管理器（挂在一个原生消息窗口上）
    ⚠️ 必须由 `TrayIcon` 提供消息线程的 hwnd：WM_HOTKEY 投递到登记它的线程队列，
       而 pywebview 的主线程是 WinForms 的 GUI 线程，我们插不进自己的窗口过程。
    """

    def __init__(self, hwnd_provider=None, dispatcher=None):
        self._hwnd_provider = hwnd_provider
        # dispatcher(func, timeout) → 把 func 编组到原生消息线程执行（见 tray.TrayIcon.invoke）
        self._dispatcher = dispatcher
        self._registered = {}          # name -> (id, sequence)
        self._next_id = HOTKEY_ID_BASE
        self._supported = win32.IS_WINDOWS
        self._lock = threading.RLock()
        self._on_activated = None
        self._on_error = None

    # ---------- 编组 ----------
    def _on_native(self, func, timeout: float = 3.0):
        """在原生消息线程上执行（能编组就编组，否则原地执行）
        ⚠️ RegisterHotKey 注册的是"**调用线程**的热键"：从主线程注册、让托盘线程收消息
           会得到 1408（ERROR_HOTKEY_NOT_REGISTERED）。所以必须走编组。
        """
        if callable(self._dispatcher):
            return self._dispatcher(func, timeout)
        return func()

    # ---------- 回调 ----------
    def set_callbacks(self, on_activated=None, on_error=None):
        self._on_activated = on_activated
        self._on_error = on_error

    def handle_hotkey(self, hotkey_id: int):
        """由托盘消息线程的窗口过程调用（WM_HOTKEY 的 wParam 是热键 id）"""
        with self._lock:
            for name, (hid, _seq) in self._registered.items():
                if hid == hotkey_id:
                    break
            else:
                return
        if callable(self._on_activated):
            try:
                self._on_activated(name)
            except Exception:
                pass

    # ---------- 状态 ----------
    @property
    def supported(self) -> bool:
        return self._supported

    def is_registered(self, name: str) -> bool:
        return name in self._registered

    def sequence(self, name: str) -> str:
        entry = self._registered.get(name)
        return entry[1] if entry else ""

    def registered_names(self) -> list:
        return list(self._registered.keys())

    def _hwnd(self) -> int:
        if callable(self._hwnd_provider):
            try:
                return int(self._hwnd_provider() or 0)
            except Exception:
                return 0
        return 0

    # ---------- 注册 / 注销 ----------
    def register(self, name: str, sequence: str):
        """注册一个具名热键，返回 (是否成功, 错误信息)"""
        if not self._supported:
            return False, _err("hotkey_err_unsupported")
        mods, vk, err = parse_sequence(sequence)
        if err:
            return False, err
        hwnd = self._hwnd()
        if not hwnd:
            return False, _err("hotkey_err_register_failed", sequence=sequence, code=0)

        self.unregister(name)
        with self._lock:
            if len(self._registered) >= MAX_HOTKEYS:
                return False, _err("hotkey_err_too_many")
            hotkey_id = self._next_id
            self._next_id += 1

        def _do_register():
            return bool(win32.user32.RegisterHotKey(
                hwnd, hotkey_id, mods | MOD_NOREPEAT, vk))

        # ⚠️ 先清 last_error：否则注册成功时读到的仍可能是上一次的陈旧错误码
        try:
            ctypes.set_last_error(0)
        except Exception:
            pass
        ok = self._on_native(_do_register, timeout=3.0)
        if not ok:
            code = win32.last_error()
            if code == ERROR_HOTKEY_ALREADY_REGISTERED:
                return False, _err("hotkey_err_occupied", sequence=sequence)
            return False, _err("hotkey_err_register_failed", sequence=sequence, code=code)

        with self._lock:
            self._registered[name] = (hotkey_id, format_sequence(mods, vk))
        return True, None

    def unregister(self, name: str = None):
        hwnd = self._hwnd()
        with self._lock:
            names = [name] if name else list(self._registered.keys())
            entries = [(key, self._registered.pop(key, None)) for key in names]
        if not (self._supported and hwnd):
            return
        for _key, entry in entries:
            if not entry:
                continue
            hotkey_id = entry[0]
            self._on_native(
                lambda hid=hotkey_id: win32.user32.UnregisterHotKey(hwnd, hid),
                timeout=2.0)

    def unregister_all(self):
        self.unregister(None)
