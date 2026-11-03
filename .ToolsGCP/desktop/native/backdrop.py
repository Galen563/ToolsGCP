"""DWM 系统背景材质（Windows 11 的 Mica / Acrylic）—— 主题效果的**桌面端那一半**。
对应设置项 `theme_effect`（mica 云母 / glass 毛玻璃 / acrylic 亚克力）。
另外一半在 `webui/css/variables.css`：`#app：before` 背景层 + 面板 `backdrop-filter`。
两条路线的关系（务必分清主次）：
    · 桌面端这条 = 让 **DWM** 在窗口背后画系统材质（真的能透出并模糊桌面壁纸）；
    · 网页端那条 = 让 **页内**面板背后有东西可糊（不依赖任何系统能力，永远可用）；
    · 桌面端单独用 ⇒ 材质真，但页面只要有整块不透明底色，效果等于没有；
    · 两条一起用 ⇒ 才是云母 / 亚克力该有的观感。
⚠️ 本模块**只做尽力而为**：所有原生调用都包在 try/except 里，失败只记日志，
   绝不抛异常、绝不改变调用方语义（和 desktop/native/win32.py 的 `safe()` 同款约定）。
================ 前置条件（缺任何一条都"看不到变化"，这不是本模块的 bug）================
1. **Windows 11 22H2（build 22621）及以上**。`DWMWA_SYSTEMBACKDROP_TYPE`(38) 在 Win10
   与 Win11 21H2(22000) 上返回 `E_INVALIDARG`；Win10 全系没有系统材质可用。
2. **窗口必须透明**。pywebview 6.2.1 只在 `transparent=True` 时才把 WebView2 的
   `DefaultBackgroundColor` 设成透明（`webview/platforms/winforms.py:286-292`）。
   当前 `desktop/shell.py` 传的是不透明的 `background_color="#16181D"` ⇒ 必须先改成
   `transparent=True`（并接受随之而来的副作用：窗口阴影/圆角要自己补）。
3. **客户区必须延展进非客户区**：`DwmExtendFrameIntoClientArea(hwnd, MARGINS(-1,-1,-1,-1))`
   （本模块的 `extend_frame()`；`apply()` 会自动先做这一步）。
   ⚠️ pywebview 在 `shadow=True and not transparent` 时会自己做一次同类调用并设
   `DWMWA_NCRENDERING_POLICY=DISABLED`；一旦改成 `transparent=True`，它就**不再做**，
   所以这两步必须由我们自己补。
4. 窗口**不能**是 `WS_EX_LAYERED`（分层窗口不参与 DWM 材质合成）。
5. WebView2 自己不能铺不透明底色 —— 第 2 条满足时它才是透明的。
================ 三档映射（`glass` 没有直接对应档）================
| theme_effect | 属性 38 的值 | 说明 |
| `mica`       | 2 = DWMSBT_MAINWINDOW      | 云母（主窗口材质），与网页端"淡背景 + 实色面板"同向 |
| `acrylic`    | 3 = DWMSBT_TRANSIENTWINDOW | 亚克力（瞬态窗口材质），与"中模糊 + 亮高光边 + 底噪"同向 |
| `glass`      | 3 = DWMSBT_TRANSIENTWINDOW | **DWM 没有"毛玻璃"这一档**：`DWMSBT_*` 只有 AUTO / NONE /
|              |                            | MAINWINDOW / TRANSIENTWINDOW / TABBEDWINDOW 五个值。
|              |                            | 这里取"最接近的底层材质"= 亚克力，磨砂质感由网页端负责 |
| 其它/未知     | 0 = DWMSBT_AUTO            | 交回系统默认，不主动破坏 |
| `none`/`off` | 1 = DWMSBT_NONE            | 显式关掉系统材质 |
================ 失败时的表现 ================
任何一步失败 ⇒ 只是"**没有系统材质**"，窗口照常显示、功能照常可用；
网页端 `#app：before` + `backdrop-filter` 那一套不受影响（那才是保底路线）。
`apply()` 返回每个属性各自的 HRESULT，**不假报成功**：
    `S_OK(0)` = 成功；`E_INVALIDARG(0x80070057)` = 系统不支持该属性（多半是 Win10/21H2）。
================ 接进 desktop/shell.py（由 shell.py 的所有者贴，本文件不动 shell.py）================
位置：`AppShell._try_show()` 里，**第 ④ 步 `self.window.show()` 之后**（show 之前 HWND 还没有
DWM 材质合成，属性会被丢掉），和现有的 ⑤show 之后再纠一次居中同一段落；另外在
`apply_settings` 之类"主题效果被改"的入口再调一次。
    # 文件顶部：from .native import appicon, autostart, backdrop, frame, hotkey, tray, win32
    # ↓ 贴在 _try_show() 的 self.window.show() 之后
    try:
        backdrop.apply(hwnd, self.settings_manager.get("theme_effect", "mica"),
                       dark=bool(self.settings_manager.get("theme", "dark") != "浅色主题"))
    except Exception:
        pass
（`dark` 那半句按 shell 里现成的主题判断写即可；本模块自己也会兜底。）
"""

import ctypes
import sys
from ctypes import wintypes

from . import win32

# dwmapi.h 常量（Win11 SDK）
DWMWA_USE_IMMERSIVE_DARK_MODE = 20        # 深色标题栏/边框（Win10 1809+ 是属性 19）
DWMWA_WINDOW_CORNER_PREFERENCE = 33       # 圆角偏好
DWMWA_SYSTEMBACKDROP_TYPE = 38            # ⚠️ 本模块的主角：系统背景材质
DWMWA_MICA_EFFECT = 1029                  # 未公开的旧写法（Win11 21H2 只有它）
DWMWA_NCRENDERING_POLICY = 2

DWMSBT_AUTO = 0
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2          # Mica（云母）
DWMSBT_TRANSIENTWINDOW = 3     # Acrylic（亚克力）
DWMSBT_TABBEDWINDOW = 4        # Mica Alt

DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3

DWMNCRP_USEWINDOWSTYLE = 0

# 设置项取值 → 属性 38 的值
BACKDROP_FOR_MODE = {
    "mica": DWMSBT_MAINWINDOW,
    "glass": DWMSBT_TRANSIENTWINDOW,     # DWM 无"毛玻璃"档，取最接近的亚克力
    "acrylic": DWMSBT_TRANSIENTWINDOW,
    "auto": DWMSBT_AUTO,
    "none": DWMSBT_NONE,
    "off": DWMSBT_NONE,
}

S_OK = 0
# 常见失败码（只用于日志可读性，不做逻辑分支）
_HR_TEXT = {
    0: "S_OK",
    0x80070057: "E_INVALIDARG（多半是系统不支持该属性：Win10 / Win11 21H2）",
    0x80070005: "E_ACCESSDENIED",
    0x80070006: "E_HANDLE（窗口句柄无效或已销毁）",
    0x80004005: "E_FAIL",
}

_MIN_BUILD_FOR_BACKDROP = 22621   # Windows 11 22H2


class MARGINS(ctypes.Structure):
    """DwmExtendFrameIntoClientArea 的参数；全 -1 = 整个客户区都参与合成。"""
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]


def _log(level, message):
    """记日志；日志模块不可用时安静地放弃（绝不因为记日志把功能带崩）。"""
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)("主题效果", "theme-effect", message)
    except Exception:
        pass


def _hr_text(hr):
    try:
        return _HR_TEXT.get(int(hr) & 0xFFFFFFFF, "0x%08X" % (int(hr) & 0xFFFFFFFF))
    except Exception:
        return str(hr)


def _declare_extra():
    """补声明本模块要用的、win32.py 里没有的函数原型。
    ⚠️ 只做**追加**，不改 win32.py 已有的声明；重复声明同一份原型是幂等的。
    """
    if not win32.IS_WINDOWS:
        return
    try:
        d = win32.dwmapi
        d.DwmIsCompositionEnabled.restype = ctypes.c_long          # HRESULT
        d.DwmIsCompositionEnabled.argtypes = [ctypes.POINTER(wintypes.BOOL)]
    except Exception:
        pass


_declare_extra()


# 状态 / 能力探测
def windows_build():
    """当前 Windows 内部版本号（拿不到返回 0）"""
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def is_composition_enabled():
    """DWM 合成是否开启（关掉时任何材质都不会显示）"""
    if not win32.IS_WINDOWS:
        return False
    try:
        enabled = wintypes.BOOL(0)
        hr = win32.dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled))
        return int(hr) == S_OK and bool(enabled.value)
    except Exception:
        return False


def is_supported():
    """(是否支持系统材质, 原因)。只用于日志/自检，不用于阻止调用。"""
    if not win32.IS_WINDOWS:
        return False, "非 Windows 平台"
    build = windows_build()
    if build and build < _MIN_BUILD_FOR_BACKDROP:
        return False, ("Windows build %d < %d：没有 DWMWA_SYSTEMBACKDROP_TYPE，"
                       "只能靠网页端那半" % (build, _MIN_BUILD_FOR_BACKDROP))
    if not is_composition_enabled():
        return False, "DWM 合成未开启（远程桌面/虚拟机/经典主题下可能如此）"
    return True, "Windows build %d，支持属性 38" % build


def is_layered(hwnd):
    """窗口是否是 WS_EX_LAYERED（分层窗口不参与 DWM 材质合成）"""
    if not win32.IS_WINDOWS or not hwnd:
        return False
    try:
        ex = win32.user32.GetWindowLongPtrW(wintypes.HWND(hwnd), win32.GWL_EXSTYLE)
        return bool((int(ex or 0)) & win32.WS_EX_LAYERED)
    except Exception:
        return False


# 原子操作
def _set_attr(hwnd, attr, value):
    """设一个 DWORD 型 DWM 窗口属性，返回 HRESULT（int）。永不抛。"""
    try:
        buf = ctypes.c_int(int(value))
        hr = win32.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), ctypes.c_uint(attr),
            ctypes.byref(buf), ctypes.sizeof(buf))
        return int(hr)
    except Exception as exc:
        _log("warn", "设置窗口材质属性失败（attr=%s，value=%s）：%r" % (attr, value, exc))
        return -1


def extend_frame(hwnd):
    """客户区延展进非客户区（材质要能在客户区后面合成，必须做这一步）。
    返回 (是否调用成功, HRESULT)。全 -1 的 MARGINS = 四周各延展整块窗口。
    """
    if not win32.IS_WINDOWS:
        return False, None
    try:
        margins = MARGINS(-1, -1, -1, -1)
        hr = win32.dwmapi.DwmExtendFrameIntoClientArea(
            wintypes.HWND(hwnd), ctypes.byref(margins))
        return int(hr) == S_OK, int(hr)
    except Exception as exc:
        _log("warn", "扩展窗口边框到客户区失败：%r" % (exc,))
        return False, None


def set_backdrop_type(hwnd, value):
    """只设属性 38（材质本身）。返回 HRESULT。"""
    return _set_attr(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, value)


def set_dark_mode(hwnd, dark=True):
    """属性 20：深色标题栏/边框。返回 HRESULT。"""
    return _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)


def set_round_corners(hwnd, prefer=DWMWCP_ROUND):
    """属性 33：圆角偏好（透明窗口失去 shadow=True 那条路径后靠它补圆角）。"""
    return _set_attr(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, prefer)


# 主入口
def apply(hwnd, mode, dark=None):
    """按设置档位给窗口套上 DWM 系统材质。
    参数
        hwnd : 顶层窗口句柄（int / HWND / pywebview 的 window.native 取到的句柄）
        mode : "mica" | "glass" | "acrylic"（也接受 "none"/"off"/"auto"，未知值按 auto）
        dark : 是否深色主题；None = 不改（保留调用方已经设好的值）
    返回（可直接写日志 / 断言，绝不假报成功）
        {"mode", "hwnd", "supported", "reason", "backdrop": <38 的值>,
         "hr_backdrop", "hr_dark", "hr_corner", "hr_extend", "ok", "layered"}
        `hr_*` 为 None 表示"这一步没执行"（例如 dark=None 时不动属性 20）。
    """
    key = str(mode or "mica").strip().lower()
    if key not in BACKDROP_FOR_MODE:
        key = "auto"
    backdrop = BACKDROP_FOR_MODE[key]

    out = {"mode": key, "hwnd": None, "supported": False, "reason": "",
           "backdrop": backdrop, "hr_backdrop": None, "hr_dark": None,
           "hr_corner": None, "hr_extend": None, "ok": False, "layered": False}

    if not win32.IS_WINDOWS:
        out["reason"] = "非 Windows 平台，跳过"
        return out
    try:
        hwnd_val = int(hwnd or 0)
    except Exception:
        hwnd_val = 0
    out["hwnd"] = hwnd_val
    if not hwnd_val:
        out["reason"] = "窗口句柄为空（窗口还没创建/已销毁）"
        _log("warn", "主题效果：%s（mode=%s）" % (out["reason"], key))
        return out

    supported, reason = is_supported()
    out["supported"] = supported
    out["reason"] = reason
    out["layered"] = is_layered(hwnd_val)
    if out["layered"]:
        out["reason"] = reason + "；⚠️ 窗口是 WS_EX_LAYERED，材质不会显示"

    # ① 客户区延展（必须在前：材质被不透明客户区挡住就等于没设）
    ok_extend, hr_extend = extend_frame(hwnd_val)
    out["hr_extend"] = hr_extend

    # ② 材质本体
    out["hr_backdrop"] = set_backdrop_type(hwnd_val, backdrop)

    # ③ 深色模式（可选）
    if dark is not None:
        out["hr_dark"] = set_dark_mode(hwnd_val, bool(dark))

    # ④ 圆角（透明窗口下 shadow=True 那条 DWM 路径没了，靠这个补）
    out["hr_corner"] = set_round_corners(hwnd_val, DWMWCP_ROUND)

    out["ok"] = (out["hr_backdrop"] == S_OK)
    detail = ("主题效果 → 系统材质：mode=%s backdrop=%d extend=%s(%s) dark=%s backdrop_hr=%s "
              "corner_hr=%s%s" % (key, backdrop, ok_extend, _hr_text(hr_extend) if hr_extend is not None else "-",
                                  out["hr_dark"] if out["hr_dark"] is None else _hr_text(out["hr_dark"]),
                                  _hr_text(out["hr_backdrop"]),
                                  "None" if out["hr_corner"] is None else _hr_text(out["hr_corner"]),
                                  "" if supported else "；⚠️ " + reason))
    _log("info" if out["ok"] else "warn", detail)
    return out


def clear(hwnd):
    """关掉系统材质（回到"没有材质"）。"""
    return apply(hwnd, "none")


def diagnose(hwnd):
    """自检：把"为什么看不到材质"需要的全部事实一次读出来（返回值可直接打日志）。"""
    supported, reason = is_supported()
    info = {"build": windows_build(), "windows": win32.IS_WINDOWS,
            "composition": is_composition_enabled(), "supported": supported, "reason": reason,
            "hwnd": None, "layered": None, "hr_20": None, "hr_33": None, "hr_38": None,
            "hr_mica_effect_1029": None}
    try:
        hwnd_val = int(hwnd or 0)
    except Exception:
        hwnd_val = 0
    info["hwnd"] = hwnd_val
    if not hwnd_val:
        return info
    info["layered"] = is_layered(hwnd_val)
    info["hr_20"] = set_dark_mode(hwnd_val, True)
    info["hr_33"] = set_round_corners(hwnd_val, DWMWCP_ROUND)
    info["hr_38"] = set_backdrop_type(hwnd_val, DWMSBT_MAINWINDOW)
    info["hr_mica_effect_1029"] = _set_attr(hwnd_val, DWMWA_MICA_EFFECT, 1)
    return info


# 离屏探针：不显示任何窗口，只验证 API 通路与 HRESULT
#   python -m desktop.native.backdrop            # 自建隐藏窗口（WS_POPUP + STATIC，从不 Show）
#   python -m desktop.native.backdrop --hwnd 123 # 直接探某个真实窗口句柄
def _probe_hidden_window():
    """建一个**从不 Show**的隐藏 WS_POPUP 窗口当探针对象。
    用系统预定义类 "STATIC"，不需要 RegisterClass，也不会出现在屏幕上/任务栏里。
    """
    if not win32.IS_WINDOWS:
        return None
    try:
        hinst = win32.kernel32.GetModuleHandleW(None)
        hwnd = win32.user32.CreateWindowExW(
            0, "STATIC", "ToolsGCP-backdrop-probe", win32.WS_POPUP,
            0, 0, 32, 32, None, None, hinst, None)
        return int(hwnd) if hwnd else None
    except Exception as exc:
        print("  建探针窗口失败：%r" % (exc,))
        return None


def _destroy(hwnd):
    try:
        win32.user32.DestroyWindow(wintypes.HWND(hwnd))
    except Exception:
        pass


def _main(argv):
    print("== ToolsGCP 主题效果 · DWM 材质通路自检 ==")
    supported, reason = is_supported()
    print("  平台        : %s (build %s)" % ("Windows" if win32.IS_WINDOWS else "非 Windows", windows_build()))
    print("  支持材质    : %s — %s" % (supported, reason))
    print("  DWM 合成    : %s" % is_composition_enabled())

    hwnd = None
    if "--hwnd" in argv:
        try:
            hwnd = int(argv[argv.index("--hwnd") + 1])
            print("  探针对象    : 外部句柄 %d" % hwnd)
        except Exception:
            hwnd = None
    owned = False
    if not hwnd:
        hwnd = _probe_hidden_window()
        owned = bool(hwnd)
        print("  探针对象    : 隐藏探针窗口 %s（从未 ShowWindow，不会出现在屏幕上）" % hwnd)
    if not hwnd:
        print("  没有可用句柄，无法继续。")
        return 1

    print("  分层窗口    : %s" % is_layered(hwnd))
    print("\n  -- 逐档调用 apply() --")
    for mode in ("mica", "glass", "acrylic", "none"):
        r = apply(hwnd, mode)
        print("  [%-7s] 属性38=%-2d hr_backdrop=%-12s hr_extend=%-12s hrcorner=%-12s ok=%s"
              % (mode, r["backdrop"], _hr_text(r["hr_backdrop"]),
                 _hr_text(r["hr_extend"]) if r["hr_extend"] is not None else "-",
                 _hr_text(r["hr_corner"]) if r["hr_corner"] is not None else "-", r["ok"]))
    print("\n  -- diagnose() --")
    for k, v in diagnose(hwnd).items():
        print("    %-22s %s" % (k, _hr_text(v) if k.startswith("hr_") and v is not None else v))
    if owned:
        _destroy(hwnd)
        print("\n  探针窗口已销毁。")
    print("\n  说明：HRESULT=0（S_OK）只代表「系统接受了这个属性」；"
          "能不能**看见**材质还取决于窗口是否透明 + 客户区是否延展 + WebView2 是否透明。")
    return 0


if __name__ == "__main__":                       # pragma: no cover - 手动自检用
    raise SystemExit(_main(sys.argv[1:]))
