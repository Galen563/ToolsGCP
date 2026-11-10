"""Caps Lock 组合键的全局监听（低级键盘钩子 WH_KEYBOARD_LL）—— 浏览器模式快捷键专用。

========== 为什么不能用现成的 GlobalHotkeyManager ==========
⚠️ 现在的默认值已经是 **Ctrl+Shift+O**（不含 Caps，走 RegisterHotKey）；
   本模块负责的是"**值里含 Caps Lock**"的那一类组合 —— 上一版默认值 Ctrl+Caps+O
   就是这种，用户自己也可能在设置里录成这类值。Windows 的 `RegisterHotKey`
在这条组合上**从两头都堵死**：
① Caps Lock（VK_CAPITAL=0x14）**不能做主键** —— 注册必失败，错误码 1409
   （见 `pymodels.utils.global_hotkey.unusable_main_key`，老默认值 Ctrl+Caps 就是这么坏的）；
② Caps Lock **也不能做修饰键** —— MOD_* 只有 ALT(0x1)/CONTROL(0x2)/SHIFT(0x4)/WIN(0x8)，
   根本没有"Caps"这一位，系统自己占着；
③ 本项目的解析器把 `Ctrl+Caps+O` 判成"两个主键"直接报错（实测）。
→ 想支持用户明确要的组合，只能自己装 **WH_KEYBOARD_LL** 键盘钩子，手动判
  "Ctrl 按下 + Caps 物理按下 + O 键落下"。

========== 与 RegisterHotKey 路径的分工（重要） ==========
`desktop/native/hotkey.py`（RegisterHotKey）继续管 **不含 Caps** 的快捷键
（呼出搜索框 / 呼出 AI）—— 那条路更省资源、系统级、和别的程序互斥可见。
本模块**只**管含 Caps 的组合。两条路都只有一份"触发后做什么"的实现
（shell 里的 `_on_hotkey` / `_on_caps_hotkey`），行为对齐。

========== 钩子的三个硬约束（踩过的坑都在这） ==========
1. **钩子必须和消息循环在同一线程**：`SetWindowsHookEx` 传 `dwThreadId=GetCurrentThreadId()`，
   然后本线程必须一直跑 `GetMessage/DispatchMessage`，否则钩子回调永远不来。
2. **回调里绝不能做耗时的事**：低级钩子在**输入线程**上同步执行，回调卡住 =
   全系统键盘卡住（用户会觉得"电脑死了"）。所以回调只做"判断 + 投递到别的线程"，
   真正的动作（起服务、开浏览器、最小化）在别的线程跑。
3. **必须卸载**：进程退出时 `UnhookWindowsHookEx` + `PostQuitMessage`，
   否则钩子线程和它的 Python 回调会拖住解释器退出（表现为"关掉程序后进程还在"）。
   ⚠️ 回调是 ctypes CFUNCTYPE，卸载前必须**保住它的引用**：被 GC 掉之后
      系统再回调进来就是悬空指针 → 直接崩（access violation），不是抛异常。
"""

import ctypes
import ctypes.wintypes as wintypes
import threading
import time as _time

from . import win32

WH_KEYBOARD_LL = 13
WM_APP_QUIT = 0x8000                 # WM_APP 区间：给钩子线程自己用的"退出"消息
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
VK_CONTROL = 0x11
VK_CAPITAL = 0x14
LLKHF_UP = 0x0080
LLKHF_ALTDOWN = 0x0020
GK_TOGGLE = 0x0001                 # GetKeyState 的"已切换"位（Caps Lock 灯亮）
HTDATASELECT = 1                   # GetKeyState 返回值：按下为负

# 钩子回调的函数签名：LRESULT CALLBACK (int nCode, WPARAM wParam, KBDLLHOOKSTRUCT*)
_LOW_LEVEL_PROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int,
                                     ctypes.c_size_t, ctypes.c_void_p)


# ========== Win32 绑定（一次性把签名声明清楚） ==========
# ⚠️ use_last_error=True：钩子装不上时 126/1429/0 是完全不同的原因
#    （沙箱拦 vs 参数写错），拿不到错误码就只能靠猜。
# ⚠️ 显式 argtypes/restype：不声明时 ctypes 默认按 32 位 int 处理句柄，
#    64 位下 HHOOK 会被截断（同一个坑见 self_update.py 的 OpenProcess）。
_user32 = ctypes.WinDLL("user32", use_last_error=True) if win32.IS_WINDOWS else None
if _user32 is not None:
    _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _LOW_LEVEL_PROC,
                                          ctypes.c_void_p, ctypes.c_uint]
    _user32.SetWindowsHookExW.restype = ctypes.c_void_p
    _user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    _user32.UnhookWindowsHookEx.restype = ctypes.c_bool
    _user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                       ctypes.c_size_t, ctypes.c_void_p]
    _user32.CallNextHookEx.restype = ctypes.c_long
    _user32.GetMessageW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_uint, ctypes.c_uint]
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.TranslateMessage.argtypes = [ctypes.c_void_p]
    _user32.TranslateMessage.restype = ctypes.c_bool
    _user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
    _user32.DispatchMessageW.restype = ctypes.c_long
    _user32.PostThreadMessageW.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                           ctypes.c_size_t, ctypes.c_ssize_t]
    _user32.PostThreadMessageW.restype = ctypes.c_bool
    _user32.PostQuitMessage.argtypes = [ctypes.c_int]
    _user32.PostQuitMessage.restype = None
    _user32.GetKeyState.restype = ctypes.c_short


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", ctypes.c_uint),
                ("scanCode", ctypes.c_uint),
                ("flags", ctypes.c_uint),
                ("time", ctypes.c_uint),
                ("dwExtraInfo", ctypes.c_void_p)]


def _down(state) -> bool:
    """GetKeyState 返回值里"此刻按着没" = 最高位 0x8000
    ⚠️ GetKeyState 返回 **SHORT**（16 位带符号）。不声明 restype 时 ctypes 默认按
       c_int 读，负数会符号扩展成 0xFFFFFFFF……，`& 0x8000` 碰巧还能中，但
       `state < 0` 这类写法两种情况下结果不同 —— 统一只看 0x8000 这一位最稳。
    """
    try:
        return bool(int(state) & 0x8000)
    except Exception:                                # noqa: BLE001
        return False


def _resolve_main_key(text: str):
    """从 `Ctrl+Caps+O` 这种序列里取出【主键 VK】和【要求哪些真修饰键】
    返回 (main_vk, need_ctrl, need_alt, need_shift, need_win, error_key)
    · Caps 出现在这里被当成"额外修饰键"（不是主键），这正是 RegisterHotKey 做不到、
      必须由本模块接手的原因；
    · 主键只允许一个（多个直接判错，和原解析器同一口径）；
    · 没有任何修饰键也没有 F 键 → 报错（和原解析器一致：不许裸字母）。
    ⚠️ 返回的 5 个位是【真修饰键】要求，**不含 Caps**：Caps 由本模块单独用
       自己的按下/抬起跟踪来判断（`_caps_down`），所以这里遇到 Caps 只是"跳过"，
       不能把它算进任何 MOD 位，也不能当成主键。
    """
    from pymodels.utils import global_hotkey as gh        # 只借它的键码表，不改它逻辑
    parts = [p for p in str(text or "").replace("++", "+").split("+") if p.strip()]
    if not parts:
        return 0, False, False, False, False, "hotkey_err_empty"
    need_ctrl = need_alt = need_shift = need_win = False
    has_caps = False
    mains = []
    for raw in parts:
        name = str(raw).strip()
        low = name.lower()
        if low == "caps" or low.startswith("capslock") or low in ("capslk", "capital"):
            has_caps = True
            continue
        if low in ("ctrl", "control"):
            need_ctrl = True
            continue
        if low == "alt":
            need_alt = True
            continue
        if low == "shift":
            need_shift = True
            continue
        if low in ("win", "super", "meta"):
            need_win = True
            continue
        mains.append(name)
    if len(mains) != 1:
        return 0, False, False, False, False, "hotkey_err_one_main_key"
    vk = gh._VK_CODES.get(mains[0].upper()) or gh._VK_CODES.get(mains[0])
    if not vk:
        return 0, False, False, False, False, "hotkey_err_unsupported_key"
    # 原解析器要求"至少一个修饰键或 F 键"；Caps 也算修饰（Ctrl+Caps+O 有 Ctrl，
    # 而 Caps+O 这种也成立 —— 因为 Caps 就是我们这条路的"修饰"）。
    if not has_caps and not (need_ctrl or need_alt or need_shift or need_win) \
            and not (0x70 <= vk <= 0x87):
        return 0, False, False, False, False, "hotkey_err_need_modifier"
    return vk, need_ctrl, need_alt, need_shift, need_win, ""


def sequence_has_caps(sequence: str) -> bool:
    """这条序列里是不是带 Caps Lock？带就只能走本模块（RegisterHotKey 不支持）"""
    text = str(sequence or "").lower()
    return ("caps" in text)


class CapsComboHook:
    """监听一条「Ctrl/Alt/Shift/Win + Caps Lock + 主键」的全局组合键
    用法：
        hook = CapsComboHook()
        hook.set_callback(on_fire)          # on_fire(name) 在**别的线程**里被调
        hook.watch("browser", "Ctrl+Caps+O")
        hook.start()                        # 起钩子线程
        ...
        hook.stop()                         # 退出时务必调
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._rules = {}                   # name -> dict(main_vk, ctrl, alt, shift, win, sequence)
        self._callback = None
        self._thread = None
        self._stop = threading.Event()
        self._running = False
        self._caps_down = False            # Caps 物理按下状态（我们自己跟，不用 GetKeyState 的切换位）
        self._proc = None                  # ⚠️ 必须长期持有引用（见模块 docstring 第 3 条）
        self._hook = 0
        self._last_fire = 0.0
        self._error = ""
        # ⚠️ `start()` 只是"线程起来了"，SetWindowsHookEx 是在**那条线程里**跑的：
        #    它失败（沙箱拦、参数错、桌面会话受限）时 start() 照样返回 True，
        #    调用方（shell._apply_caps_rules）却以为装好了 → 日志说"快捷键已注册"、
        #    用户按下去完全没反应。所以用一个事件把**真实装载结果**交回调用方。
        self._settled = threading.Event()  # 钩子装好或明确失败后置位
        self._installed = False

    # ---------- 配置 ----------
    def set_callback(self, callback):
        with self._lock:
            self._callback = callback if callable(callback) else None

    def watch(self, name: str, sequence: str):
        """登记一条组合键；返回 (ok, error)。sequence 不含 Caps 也允许（一样能判）
        ⚠️ `need_caps` 必须**逐条规则**带着：判据若不区分，用户把快捷键改成
           不含 Caps 的 `Ctrl+Shift+B` 时仍要求"Caps 按着" → 那条键永远按不出来
           （回归测试 test_caps_hotkey.py 的第 7 项抓到过）。
        """
        main_vk, ctrl, alt, shift, win, err = _resolve_main_key(sequence)
        if err:
            with self._lock:
                self._rules.pop(name, None)
            return False, err
        with self._lock:
            self._rules[name] = {"main_vk": main_vk, "ctrl": ctrl, "alt": alt,
                                 "shift": shift, "win": win,
                                 "caps": sequence_has_caps(sequence),
                                 "sequence": str(sequence or "").strip()}
        return True, ""

    def unwatch(self, name: str):
        with self._lock:
            self._rules.pop(name, None)

    def clear(self):
        with self._lock:
            self._rules.clear()

    def watched(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._rules.items()}

    @property
    def running(self) -> bool:
        return self._running

    @property
    def installed(self) -> bool:
        """钩子是否**真的**装上了（SetWindowsHookEx 返回了有效句柄）"""
        return self._installed

    @property
    def error(self) -> str:
        return self._error

    def wait_installed(self, timeout: float = 2.0) -> bool:
        """等钩子装载结果落定（成功或失败），返回是否成功
        ⚠️ 为什么要等：见 __init__ 里 `_settled` 的注释 —— `start()` 返回 True 只代表
           "线程起起来了"，不代表钩子装上了。调用方（shell._apply_caps_rules）要的是
           后者的确定答案，才能把"这条快捷键到底能不能用"如实写进日志/状态。
        ⚠️ 不会永久阻塞：线程万一在 SetWindowsHookEx 之前就被非 Win32 异常打断，
           finally 里也会把 `_settled` 置位；真的等不到就是超时（返回 False）。
        """
        self._settled.wait(max(0.0, float(timeout)))
        return self._installed

    # ---------- 生命周期 ----------
    def start(self) -> bool:
        """起钩子线程（已起就幂等返回 True）
        ⚠️ 返回值只表示"线程起来了"，**不表示钩子装上了**；要确认请调
           `wait_installed()`（或轮询 `installed` / `error`）。
        """
        with self._lock:
            if self._running:
                return True
            if not win32.IS_WINDOWS:
                self._error = "not_windows"
                self._installed = False
                self._settled.set()
                return False
            self._stop.clear()
            self._settled.clear()
            self._installed = False
            self._error = ""
            self._thread = threading.Thread(target=self._thread_main,
                                            name="ToolsGCP-caps-hotkey", daemon=True)
            self._running = True
            self._thread.start()
        return True

    def stop(self, timeout: float = 2.0):
        """卸载钩子 + 结束线程（幂等；退出流程必调）
        ⚠️ 只 set 事件是不够的：那条线程正阻塞在 `GetMessageW` 里，不看事件。
           必须给它投递一条 WM_APP_QUIT —— 它的消息循环拿到这条消息后调
           `PostQuitMessage`，`GetMessageW` 才会返回 0 并退出，钩子才会在
           finally 里被摘掉。**直接 join 等待**是等不回来的。
        """
        with self._lock:
            thread = self._thread
            self._thread = None
        self._stop.set()
        try:
            if thread is not None and thread.is_alive() and thread.ident:
                ok = _user32.PostThreadMessageW(thread.ident, WM_APP_QUIT, 0, 0)
                if not ok:
                    # 投不进去（线程已退出消息循环等）→ 至少自己把状态清干净
                    self._running = False
        except Exception:                             # noqa: BLE001
            pass
        try:
            if thread is not None:
                thread.join(max(0.1, float(timeout)))
        except Exception:                             # noqa: BLE001
            pass
        with self._lock:
            self._running = False

    # ---------- 线程主体 ----------
    def _thread_main(self):
        try:
            self._proc = _LOW_LEVEL_PROC(self._on_key)   # 保住引用（见模块 docstring）
            # ⚠️⚠️ WH_KEYBOARD_LL 的正确参数是 **hMod=NULL、dwThreadId=0**（全局钩子）。
            #    实测本机：
            #      hMod=GetModuleHandleW(None), tid=0 → 失败 err=126 ERROR_MOD_NOT_FOUND
            #      hMod=NULL,                         tid=0 → 成功
            #    低级钩子的回调在**安装它的线程**上、由该线程的消息队列派发，
            #    所以"传 0（全局）"和"本线程必须有消息循环"两件事不矛盾 ——
            #    别被"dwThreadId 要传自己线程 id"的直觉带跑（那是 CBT 之类的线程钩子）。
            hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
            err = ctypes.get_last_error()
            self._hook = int(hook or 0)
            if not self._hook:
                # ⚠️ 错误码要写全：126=ERROR_MOD_NOT_FOUND（参数写法错了）、
                #    1429=ERROR_HOOK_NEEDS_HMOD、0=成功返回 NULL（极少见，多半是
                #    回调对象已经被 GC）。沙箱/受限会话里也常见装不上。
                #    以前只有这一行日志、调用方看不见 → 排查全靠猜。
                self._error = f"SetWindowsHookEx 失败（错误码 {err}）"
                self._running = False
                self._installed = False
                self._settled.set()
                return
            self._installed = True
            self._error = ""
            self._settled.set()                         # 把"装上了"交回 wait_installed()
            msg = wintypes.MSG()
            # GetMessageW 返回 0 = WM_QUIT，-1 = 出错；两者都退出循环
            while not self._stop.is_set():
                got = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if got <= 0:
                    break
                if int(msg.message) == WM_APP_QUIT:
                    _user32.PostQuitMessage(0)
                    continue
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:                          # noqa: BLE001
            self._error = f"caps hook thread crashed: {exc}"
        finally:
            # ⚠️ 顺序很重要：先摘钩子（顺序反了会出现"钩子还在、回调对象已释放"的悬空指针）
            try:
                if self._hook:
                    _user32.UnhookWindowsHookEx(self._hook)
            except Exception:                             # noqa: BLE001
                pass
            self._hook = 0
            self._proc = None
            self._running = False
            self._installed = False
            self._settled.set()                           # 兜底：装载阶段之前就抛异常也要给个答复

    # ---------- 回调 ----------
    def _on_key(self, n_code, w_param, l_param):
        """钩子回调：只做判断和投递，**绝不做耗时操作**（见模块 docstring 第 2 条）"""
        next_result = 0
        try:
            if n_code >= 0:
                info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk = int(info.vkCode)
                flags = int(info.flags)
                # 判定逻辑全在 handle_key_event()：钩子这里只负责拆装结构体 + 决定返回值。
                # ⚠️ 抽出来的原因是那段"该不该吞这次按键"的判断直接决定用户会不会
                #    被误切大写锁定，必须能被单测覆盖（真钩子没法在测试里喂按键）。
                if self.handle_key_event(vk, bool(flags & LLKHF_UP)):
                    return 1                              # 已吞：不再传给任何程序
        except Exception:
            # 回调里抛异常绝不能外泄给系统（会崩在输入线程上）；吞掉并放行下一个钩子
            pass
        try:
            next_result = _user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
        except Exception:
            next_result = 0
        return int(next_result) & 0xFFFFFFFF

    def handle_key_event(self, vk: int, is_up: bool) -> bool:
        """处理一次按键，返回 True = 这条按键要**吞掉**（回调 return 1，不再往下传）
        ⚠️ Caps Lock 的坑（用户实测会撞上）：按住 Ctrl 时按下 Caps，系统照样在
           keydown 那一刻**切换**大写锁定 → 按完 Ctrl+Caps+O 松手，灯还亮着、
           之后打字全是大写。组合键不该有这种副作用。
           → Ctrl 按着时把 Caps 的按下/抬起**吞掉**（return True）：系统看不到这次
             Caps 按下，就不会切换；**单独**按 Caps（Ctrl 没按）完全不受影响。
        ⚠️⚠️ 但**状态一定要先更新再吞**：`_caps_down` 是这条组合键的判据，
           如果"吞掉"时顺手跳过了更新，Ctrl+Caps 永远不被记录 → 按 O 时
           `caps_down` 恒为 False → **组合键彻底失效**（这个 bug 是单测抓出来的，
           见 _devtest/test_caps_hotkey.py 的"Ctrl 按着时 Caps 落下后按主键要命中"）。
        ⚠️ 不能用 GetKeyState(VK_CAPITAL) 的"切换位"判断有没有按住 Caps ——
           那是**灯**的状态（按一次开、再按一次关），和"此刻按住"是两回事，
           所以自己跟 `_caps_down`。
        """
        if vk == VK_CAPITAL:
            self._caps_down = not is_up          # 先记账
            if _down(_user32.GetKeyState(VK_CONTROL)):
                return True                      # 再吞掉，避免误切大写锁定
            return False
        if is_up:
            return False
        return self._match(vk)

    def _match(self, vk: int) -> bool:
        """主键落下时匹配组合键；命中就起一条线程回调。返回是否命中"""
        now = _time.monotonic()
        if now - self._last_fire < 0.35:                  # 按住不放会连发：加节流
            return False
        with self._lock:
            rules = dict(self._rules)
            callback = self._callback
        if not rules or callback is None:
            return False
        # 真修饰键用 GetKeyState 读实时物理状态（钩子里读是安全的，纯查询）
        # ⚠️ 高位（0x8000）= 按下。GetKeyState 返回 SHORT，restype 已在模块里声明。
        ctrl = _down(_user32.GetKeyState(VK_CONTROL))
        alt = _down(_user32.GetKeyState(0x12))
        shift = _down(_user32.GetKeyState(0x10))
        win = _down(_user32.GetKeyState(0x5B)) or _down(_user32.GetKeyState(0x5C))
        caps = self._caps_down
        for name, rule in rules.items():
            if rule["main_vk"] != vk:
                continue
            # 逐条判断要不要 Caps（`Ctrl+Shift+B` 这种就不要求）
            if rule.get("caps", True) and not caps:
                continue
            if bool(rule["ctrl"]) != ctrl or bool(rule["alt"]) != alt \
                    or bool(rule["shift"]) != shift or bool(rule["win"]) != win:
                continue
            self._last_fire = now
            # 投递到别的线程：回调里做"起服务 + 开浏览器"会卡住系统输入
            threading.Thread(target=self._fire, args=(callback, name),
                             name=f"ToolsGCP-caps-fire-{name}", daemon=True).start()
            return True
        return False

    @staticmethod
    def _fire(callback, name):
        try:
            callback(name)
        except Exception:
            pass


# ---------- 模块级单例（shell 用；和 hotkey.GlobalHotkeyManager 一样只装一条钩子） ----------
_shared = None
_shared_lock = threading.RLock()


def shared_hook() -> CapsComboHook:
    global _shared
    if _shared is not None:
        return _shared
    with _shared_lock:
        if _shared is None:
            _shared = CapsComboHook()
        return _shared


__all__ = ["CapsComboHook", "shared_hook", "sequence_has_caps", "_resolve_main_key"]
