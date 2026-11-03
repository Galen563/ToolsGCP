"""全局快捷键（Windows）
用 Win32 RegisterHotKey 注册系统级热键：热键被本程序独占，无论焦点在哪都会把 WM_HOTKEY
投递到本进程，由 QAbstractNativeEventFilter 在 Qt 事件循环里接收。
用法：manager = GlobalHotkeyManager(app)；manager.register("search", "Ctrl+Q")
"""

import ctypes
import re
import sys

from PyQt5.QtCore import QAbstractNativeEventFilter, QObject, pyqtSignal

# Win32 常量
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# 语言文件缺失时的英文兜底（和 set_language.json 的 English 一列一致）
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


def _err(err_key: str, **kwargs) -> str:
    """报错文案按当前界面语言来（这些错误是要弹给用户看的）
    ⚠️⚠️ 第一个参数必须叫 `err_key`，**不能**叫 `key`：调用点有
       `_err("hotkey_err_unsupported_key", key=key)` 这种写法，参数名撞上就会抛
       TypeError: _err() got multiple values for argument 'key' —— 于是"录到一个不认识的
       键"不是给提示，而是直接抛异常（被崩溃护栏吞掉，表现成"按了没反应"）。
    """
    template = _ERROR_FALLBACK.get(err_key, err_key)
    try:
        from ..core.language_manager import get_current_manager
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

# "系统自己占着"的主键：拿它们做主键注册必然失败（见 unusable_main_key）
UNUSABLE_MAIN_KEYS = {
    0x14: "Caps Lock",
    0x90: "Num Lock",
    0x91: "Scroll Lock",
}


def unusable_main_key(sequence: str) -> str:
    """这个快捷键是不是用了"系统占着"的主键？是就返回键名，否则返回空串
    ⚠️ Caps Lock / Num Lock / Scroll Lock **根本不能做全局热键的主键**：RegisterHotKey 会
       失败并返回 ERROR_HOTKEY_ALREADY_REGISTERED(1409)，提示"已被其它程序占用"。
    """
    _mods, vk, err = parse_sequence(sequence)
    if err:
        return ""
    return UNUSABLE_MAIN_KEYS.get(vk, "")

# 修饰键名称 → 掩码
_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "meta": MOD_WIN,
}

# 键名 → 虚拟键码
_VK_CODES = {}
for _c in range(ord("A"), ord("Z") + 1):
    _VK_CODES[chr(_c)] = _c
for _d in range(ord("0"), ord("9") + 1):
    _VK_CODES[chr(_d)] = _d
for _i in range(1, 25):
    _VK_CODES[f"F{_i}"] = 0x6F + _i  # VK_F1 = 0x70
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

# 虚拟键码 → 显示名（用于把快捷键回显给用户）
_VK_NAMES = {
    0x14: "Caps", 0x20: "Space", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
    0x08: "Backspace", 0x2E: "Delete", 0x2D: "Insert", 0x24: "Home", 0x23: "End",
    0x21: "PageUp", 0x22: "PageDown",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
}

# ⚠️ OEM 标点键（VK 0xBA~0xC0 那一批）必须能**原样回显**：
#    回显给字符、解析时也认十六进制，否则 "Ctrl+-" 会存成并显示成 "Ctrl+0xBD"，
#    再解析时归一成空串、键就失效了（见 parse_sequence）。
_VK_OEM_NAMES = {
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
    0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}

# 单字符别名归一
_VK_ALIASES = {
    "PGUP": "PAGEUP", "PGDN": "PAGEDOWN", "DEL": "DELETE",
    "INS": "INSERT", "SPACEBAR": "SPACE", "UPARROW": "UP",
    "DOWNARROW": "DOWN", "LEFTARROW": "LEFT", "RIGHTARROW": "RIGHT",
    "CAPSLK": "CAPS", "CAPITAL": "CAPS",
}


def normalize_sequence(text: str) -> str:
    """把用户输入归一成 "Ctrl+Alt+Q" 这种形式（无效返回空串）"""
    mods, vk, err = parse_sequence(text)
    if err:
        return ""
    return format_sequence(mods, vk)


def format_sequence(mods: int, vk: int) -> str:
    """掩码 + 虚拟键码 → 可读文本"""
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
        # OEM 标点键显示成它本来的字符
        parts.append(_VK_OEM_NAMES[vk])
    elif 0x70 <= vk <= 0x87:
        parts.append(f"F{vk - 0x6F}")
    elif 32 < vk < 127:
        parts.append(chr(vk).upper())
    else:
        parts.append(f"0x{vk:02X}")
    return "+".join(parts)


def parse_sequence(text: str):
    """解析快捷键文本 → (修饰键掩码, 虚拟键码, 错误信息)；错误信息 None 表示成功"""
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

    name = key.upper()
    name = _VK_ALIASES.get(name, name)
    vk = _VK_CODES.get(name)
    if vk is None and len(name) == 1:
        vk = ord(name)
    if vk is None and re.fullmatch(r"0X[0-9A-F]{1,3}", name):
        # ⚠️ 兜底认 "0xBD" 这种十六进制写法（老数据 / format_sequence 的产物），
        #    才能保证"回显 → 再解析"是幂等的，不会因为显示格式把用户的键弄丢。
        vk = int(name[2:], 16)
    if vk is None:
        return 0, 0, _err("hotkey_err_unsupported_key", key=key)

    if not mods and not (0x70 <= vk <= 0x87):
        # 不允许注册裸字母数字键（会抢掉全系统的打字）
        return 0, 0, _err("hotkey_err_need_modifier")

    return mods, vk, None


class _MSG(ctypes.Structure):
    """Win32 MSG 结构体（注意 64 位下的对齐，不能按连续 uint 读）"""
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


class GlobalHotkeyManager(QObject):
    """全局热键管理器（可同时注册多个热键；仅 Windows 生效，其它平台静默降级）
    用法：manager.register("search", "Ctrl+Q")；activated 信号带注册时给的名字。
    """
    activated = pyqtSignal(str)      # 参数：热键名字
    error = pyqtSignal(str)

    HOTKEY_ID_BASE = 0xA001
    MAX_HOTKEYS = 16

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._registered = {}        # name -> (id, sequence)
        self._next_id = self.HOTKEY_ID_BASE
        self._thread_id = None

        self._supported = sys.platform == "win32"
        self._filter = None
        if self._supported:
            self._user32 = ctypes.windll.user32
            self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            self._filter = _HotkeyEventFilter(self)
            app.installNativeEventFilter(self._filter)

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

    # ---------- 注册 / 注销 ----------
    def register(self, name: str, sequence: str):
        """注册一个具名热键，返回 (是否成功, 错误信息)"""
        if not self._supported:
            return False, _err("hotkey_err_unsupported")

        mods, vk, err = parse_sequence(sequence)
        if err:
            return False, err

        self.unregister(name)
        if len(self._registered) >= self.MAX_HOTKEYS:
            return False, _err("hotkey_err_too_many")

        hotkey_id = self._next_id
        self._next_id += 1

        if not self._user32.RegisterHotKey(None, hotkey_id, mods | MOD_NOREPEAT, vk):
            code = ctypes.windll.kernel32.GetLastError()
            if code == ERROR_HOTKEY_ALREADY_REGISTERED:
                return False, _err("hotkey_err_occupied", sequence=sequence)
            return False, _err("hotkey_err_register_failed",
                               sequence=sequence, code=code)

        self._registered[name] = (hotkey_id, format_sequence(mods, vk))
        return True, None

    def unregister(self, name: str = None):
        """注销指定热键；name 为空时注销全部"""
        names = [name] if name else list(self._registered.keys())
        for key in names:
            entry = self._registered.pop(key, None)
            if entry and self._supported:
                self._user32.UnregisterHotKey(None, entry[0])

    def unregister_all(self):
        self.unregister(None)

    # ---------- 事件 ----------
    def _on_hotkey(self, hotkey_id: int):
        for name, (hid, _seq) in self._registered.items():
            if hid == hotkey_id:
                self.activated.emit(name)
                return


class _HotkeyEventFilter(QAbstractNativeEventFilter):
    """把 WM_HOTKEY 转发给管理器"""

    def __init__(self, manager: GlobalHotkeyManager):
        super().__init__()
        self._manager = manager

    def nativeEventFilter(self, event_type, message):
        try:
            if event_type == b"windows_generic_MSG" and message is not None:
                msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
                if msg.message == WM_HOTKEY:
                    self._manager._on_hotkey(int(msg.wParam))
        except Exception:
            pass
        return False, 0
