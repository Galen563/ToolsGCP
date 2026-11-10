# -*- coding: utf-8 -*-
"""启动画面真机取证（splash-r2 · task-7 · 第 2 轮）

⚠️ 这个脚本**会真弹窗口、会截屏**（用户本轮明确允许），测完自己收干净进程。

三个取证动作（对应三条 bug）：
  A. 只起 SplashController（不碰主窗口）：
     · 截"弹之前"的基屏 + "弹之中"的屏，把 splash 矩形**四角**像素和基屏逐点比对
       → 证明"去底板后圆角外是真透明"（不是黑边/白边/脏边，而是**和桌面一模一样**）；
     · 采样 logo 中心像素 → 证明画面就是 logo 本身；
     · 每 10ms 记一次 GetWindowRect → 证明第一帧就居中、没有位置跳变；
     · 打印 splash 实际读到的 theme / DATA_DIR / dark → 证明浅色分支走没走到。
  B. 真跑整个程序（`pythonw ToolsGCP.pyw`），在启动时间轴上多次截屏 + 枚举所有
     ToolsGCP / webview 顶层窗口（类名、标题、矩形、可见性、**Z 序**、分层/置顶样式），
     回答"到底有几个窗口、各自在哪、谁压谁"（需求 ② 的"UI 叠加"）。
  C. 事后从真实日志里把 splash 的底色行、主窗口显示行抠出来，和截屏互相印证。

跑法（仓库根目录）：
    python "项目资料-文档与开发测试/_devtest/probe_splash_r2.py"          # A + C（只弹小窗）
    python "项目资料-文档与开发测试/_devtest/probe_splash_r2.py" --full   # A + B + C（真起整个程序）

产物都落在 项目资料-文档与开发测试/_tmp-ai-test/splash-r2/：
    base.png / splash.png / app_t*.png（截屏）、windows_*.txt（窗口清单）、probe.json（汇总）
⚠️ 不用系统 %TEMP% / tempfile.mkdtemp：本沙箱里新建随机目录不可写（Errno 13），一律固定名 + makedirs。
"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TMP = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", "splash-r2")
os.makedirs(TMP, exist_ok=True)

FULL = "--full" in sys.argv
ICON = os.path.join(ROOT, ".ToolsGCP", "logo.png")
REAL_CONFIG = os.path.join(os.environ.get("USERPROFILE", ""), ".ToolsGCP",
                           "config", "toolsgcp_config.json")
LOG_FILE = os.path.join(os.environ.get("USERPROFILE", ""), ".ToolsGCP",
                        "logs", "system_log.log")

REPORT = {}
FINDINGS = []


def note(msg):
    print(msg, flush=True)
    FINDINGS.append(msg)


def check(name, cond, detail=""):
    note(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"   <- {detail}" if detail else ""))
    REPORT.setdefault("checks", {})[name] = bool(cond)
    return bool(cond)


# ======================================================================
# 0) DPI：必须让本进程是 per-monitor v2 aware，否则 GetWindowRect / 截屏会被
#    系统虚拟化（150% 缩放下坐标差 1.5 倍），采样点会错位（踩过）。
# ======================================================================
def make_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return "SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)"
    except Exception:                                    # noqa: BLE001
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return "SetProcessDPIAware"
    except Exception:                                    # noqa: BLE001
        return "none"


DPI_MODE = make_dpi_aware()

U = ctypes.windll.user32
G = ctypes.windll.gdi32
K = ctypes.windll.kernel32
# ⚠️ 64 位下必须声明 argtypes/restype：HWND 超过 32 位，不声明会被截断成 int，
#    GetClassNameW 直接返回空串 → 枚举永远找不到目标窗口（上一轮踩过）。
U.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
U.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
U.IsWindowVisible.argtypes = [wintypes.HWND]
U.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
U.GetWindowLongW.restype = ctypes.c_long
U.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
U.GetWindow.restype = wintypes.HWND
U.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
U.GetWindowThreadProcessId.restype = wintypes.DWORD
U.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def window_pid(hwnd):
    pid = wintypes.DWORD(0)
    U.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value)

GW_OWNER = 4
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080


def rect_of(hwnd):
    r = wintypes.RECT()
    if U.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
        return (r.left, r.top, r.right, r.bottom)
    return None


def enum_windows(filter_prefixes=("ToolsGCP", "Chrome_WidgetWin", "Win32", "webview")):
    """枚举**顶层**窗口（EnumWindows 的回调顺序就是 Z 序，从上到下）"""
    rows = []
    cbuf = (ctypes.c_wchar * 256)()
    tbuf = (ctypes.c_wchar * 256)()

    def cb(h, _lp):
        U.GetClassNameW(h, cbuf, 256)
        cls = str(cbuf.value)
        U.GetWindowTextW(h, tbuf, 256)
        title = str(tbuf.value)
        low = cls.lower()
        hit = (cls.startswith("ToolsGCP") or "webview" in low or "chrome" in low
               or "ToolsGCP" in title)
        if not hit:
            return True
        r = rect_of(int(h))
        ex = U.GetWindowLongW(h, -20) & 0xFFFFFFFF       # GWL_EXSTYLE
        rows.append({
            "z": len(rows),
            "hwnd": int(h),
            "pid": window_pid(int(h)),
            "class": cls,
            "title": title,
            "rect": r,
            "visible": bool(U.IsWindowVisible(h)),
            "layered": bool(ex & WS_EX_LAYERED),
            "topmost": bool(ex & WS_EX_TOPMOST),
            "toolwindow": bool(ex & WS_EX_TOOLWINDOW),
            "owner": int(U.GetWindow(h, GW_OWNER) or 0),
            "size": (None if not r else (r[2] - r[0], r[3] - r[1])),
            "center": (None if not r else (round((r[0] + r[2]) / 2),
                                           round((r[1] + r[3]) / 2))),
        })
        return True

    U.EnumWindows(ENUMPROC(cb), 0)
    return rows


def dump_windows(tag, rows=None):
    rows = rows if rows is not None else enum_windows()
    path = os.path.join(TMP, f"windows_{tag}.txt")
    lines = [f"== 窗口清单 @{tag}  共 {len(rows)} 个（EnumWindows 顺序 = Z 序，从上到下）=="]
    for row in rows:
        lines.append(
            f"  [z{row['z']}] {row['class']:<28} 标题={row['title']!r:<16} "
            f"rect={row['rect']} size={row['size']} center={row['center']} "
            f"visible={row['visible']} layered={row['layered']} "
            f"topmost={row['topmost']} tool={row['toolwindow']} hwnd={row['hwnd']}")
    text = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    note(text)
    REPORT.setdefault("windows", {})[tag] = rows
    return rows


# ======================================================================
# 截屏：用 GDI BitBlt 直接抓主屏（不用 PowerShell：多一次进程、DPI 也不可控）
# ======================================================================
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def screenshot(path):
    from PIL import Image
    sw = U.GetSystemMetrics(0)          # SM_CXSCREEN（本进程已 DPI aware = 物理像素）
    sh = U.GetSystemMetrics(1)
    hdc = U.GetDC(None)
    mem = G.CreateCompatibleDC(hdc)
    bmp = G.CreateCompatibleBitmap(hdc, sw, sh)
    old = G.SelectObject(mem, bmp)
    SRCCOPY = 0x00CC0020
    CAPTUREBLT = 0x40000000             # 不然分层窗口（splash）抓不到！
    G.BitBlt(mem, 0, 0, sw, sh, hdc, 0, 0, SRCCOPY | CAPTUREBLT)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth, bmi.biHeight = sw, -sh
    bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(sw * sh * 4)
    got = G.GetDIBits(mem, bmp, 0, sh, buf, ctypes.byref(bmi), 0)
    G.SelectObject(mem, old)
    G.DeleteObject(bmp)
    G.DeleteDC(mem)
    G.DeleteDC(hdc)
    if not got:
        note(f"  !! GetDIBits 失败 err={K.GetLastError()}")
        return None
    im = Image.frombuffer("RGBA", (sw, sh), buf, "raw", "BGRA", 0, 1)
    im.convert("RGB").save(path)
    return {"path": path, "w": sw, "h": sh, "img": im}


def px(shot, x, y):
    if not shot:
        return None
    if not (0 <= x < shot["w"] and 0 <= y < shot["h"]):
        return None
    return shot["img"].getpixel((x, y))


def rects_to_points(r, inset=2):
    """一个矩形的四角（往里缩 inset 像素，避开 1px 边框）+ 中心"""
    l, t, rr, b = r
    return {
        "TL": (l + inset, t + inset), "TR": (rr - 1 - inset, t + inset),
        "BL": (l + inset, b - 1 - inset), "BR": (rr - 1 - inset, b - 1 - inset),
        "C": ((l + rr) // 2, (t + b) // 2),
        "TM": ((l + rr) // 2, t + inset),                 # 上边中点
    }


def diff_points(a, b, keys):
    out = {}
    for k in keys:
        pa, pb = a.get(k), b.get(k)
        same = (pa is not None and pa == pb)
        dist = None
        if pa and pb:
            dist = sum(abs(x - y) for x, y in zip(pa, pb))
        out[k] = {"before": pa, "during": pb, "identical": same, "l1": dist}
    return out


# ======================================================================
# A) 只起 splash：证明"没有底板 + 四角真透明 + 第一帧居中"
# ======================================================================
def part_a():
    sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                    os.path.join(ROOT, ".ToolsGCP", "modules")]
    sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
    import pymodels.constants as constants_mod            # noqa: F401
    from desktop import splash as S
    from desktop.native import win32

    note("== A) 真机单起 SplashController（用**用户真实配置**，不改 DATA_DIR）==")
    note(f"  DPI 模式: {DPI_MODE}")
    try:
        with open(REAL_CONFIG, encoding="utf-8") as fh:
            cfg = json.load(fh)
        note(f"  真实配置 theme={cfg.get('theme')!r} "
             f"splash_screen_enabled={cfg.get('splash_screen_enabled')!r} "
             f"splash_screen_duration={cfg.get('splash_screen_duration')!r}")
    except Exception as exc:                               # noqa: BLE001
        note(f"  !! 读真实配置失败: {exc}")

    diag = S._theme_diagnostics()
    note(f"  splash 现场: DATA_DIR={diag['data_dir']} cfg_exists={diag['cfg_exists']} "
         f"theme_raw={diag['theme_raw']} light={diag['light']} dark={diag['dark']} "
         f"err={diag['error']!r}")
    check("splash 读到的是**当前真实数据根**（不是 import 期的旧值）",
          diag["data_dir"] == constants_mod.DATA_DIR, f"{diag['data_dir']}")
    check("theme=浅色主题 时 resolve_splash_dark() 返回 False（走浅色分支）",
          diag["dark"] is False, str(diag))

    w, h, raw = S._prepare_bitmap(ICON, diag["dark"])
    note(f"  离屏位图 {w}x{h} 圆角半径={S._corner_radius(w, h)}")
    REPORT["bitmap"] = {"w": w, "h": h,
                        "radius": S._corner_radius(w, h),
                        "corners": [list(raw[i:i + 4]) for i in
                                    (0, (w - 1) * 4, (h - 1) * w * 4,
                                     ((h - 1) * w + w - 1) * 4)]}
    check("位图四角 alpha==0（真透明，非脏边）",
          all(raw[i + 3] == 0 for i in
              (0, (w - 1) * 4, (h - 1) * w * 4, ((h - 1) * w + w - 1) * 4)))

    base = screenshot(os.path.join(TMP, "base.png"))
    check("截屏可用", base is not None)

    ctl = S.SplashController(ICON, 4000, enabled=True)
    t0 = time.monotonic()
    frames = []
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            hwnd = ctl._hwnd
            if hwnd:
                r = rect_of(hwnd)
                if r:
                    frames.append((round(time.monotonic() - t0, 3), r,
                                   bool(U.IsWindowVisible(wintypes.HWND(hwnd)))))
            time.sleep(0.01)

    th = threading.Thread(target=watch, daemon=True)
    th.start()
    started = ctl.start()
    check("SplashController.start() 成功", bool(started))
    time.sleep(0.45)
    shots = {"splash.png": screenshot(os.path.join(TMP, "splash.png"))}
    rows = dump_windows("splash")
    splash_rows = [x for x in rows if x["class"].startswith("ToolsGCP_Splash")]
    check("屏幕上 ToolsGCP_Splash* 窗口**只有一个**", len(splash_rows) == 1,
          f"{len(splash_rows)} 个")
    stop.set()
    th.join(2)
    ctl.stop(3)
    time.sleep(0.2)
    after = enum_windows()
    left = [x for x in after if x["class"].startswith("ToolsGCP_Splash")]
    check("stop() 之后 splash 窗口已销毁（无残留）", not left, f"{left}")

    REPORT["splash_frames"] = frames
    if frames:
        note(f"  窗口矩形时间轴：共 {len(frames)} 帧，首帧={frames[0][1]} "
             f"末帧={frames[-1][1]} 不同帧数={len({f[1] for f in frames})}")
        wa = win32.work_area()
        r = frames[0][1]
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        ax, ay = (wa[0] + wa[2]) / 2, (wa[1] + wa[3]) / 2
        note(f"  work_area={wa}  splash 中心=({cx:.1f},{cy:.1f}) 工作区中心=({ax:.1f},{ay:.1f})")
        check("第一帧就居中（中心 == 工作区中心 ±2px）",
              abs(cx - ax) <= 2 and abs(cy - ay) <= 2, f"差=({cx - ax:.1f},{cy - ay:.1f})")
        check("整段播放**没有位置跳变**（所有帧矩形一致）",
              len({f[1] for f in frames}) == 1, f"{len({f[1] for f in frames})} 种矩形")

    # 真透明实测。
    # ⚠️ 为什么**不能**只比"弹之前 vs 弹之中"两张截图的同一个坐标：
    #    本机桌面是动态的（壁纸幻灯片 / 指针 / 别的窗口在动），实测 TL 两次截屏
    #    L1 差到 202，全是桌面自己变了，和 splash 无关。
    #    → 改成**同一张截图内**比"角内 1px"和"沿对角外移 8px"：桌面在这么近的距离
    #      必然连续，若 splash 角是真透明则两者接近；若预乘 alpha 算错留下黑边/白边，
    #      角内会出现接近 (0,0,0) 或 (255,255,255) 的脏点。
    if frames and shots["splash.png"] and base:
        r = frames[len(frames) // 2][1]
        pts = rects_to_points(r, inset=1)
        outer = {"TL": (r[0] - 8, r[1] - 8), "TR": (r[2] + 7, r[1] - 8),
                 "BL": (r[0] - 8, r[3] + 7), "BR": (r[2] + 7, r[3] + 7)}
        note("  同一张 splash 截图内：角内(应透出桌面) vs 角外 8px（桌面参照）")
        note("  另附基屏同坐标值（仅参考，本机桌面是动态的，不作为判据）")
        corner_rows = {}
        for k in ("TL", "TR", "BL", "BR"):
            inside = px(shots["splash.png"], *pts[k])
            outside = px(shots["splash.png"], *outer[k])
            was = px(base, *pts[k])
            l1 = sum(abs(a - b) for a, b in zip(inside, outside)) if inside and outside else None
            corner_rows[k] = {"inside": inside, "outside": outside, "l1": l1,
                              "base_before": was}
            note(f"    {k} 角内={inside} 角外={outside} L1={l1}  (基屏同点={was})")
        REPORT["splash_corner_pixels"] = corner_rows
        # 判据一（硬）：角内不是黑边/白边/纯色脏边（脏边特征 = R=G=B 且极暗或极亮）
        no_dirty = all(
            v["inside"] is not None
            and not (max(v["inside"]) <= 8 or min(v["inside"]) >= 250)
            for v in corner_rows.values())
        check("四角内像素不是黑边/白边（预乘 alpha 没错、没留脏边）", no_dirty,
              str({k: v["inside"] for k, v in corner_rows.items()}))
        # 判据二（**仅作参考**，不计入失败）：角内 vs 紧邻角外的连续性。
        # ⚠️ 本机桌面是**动态**的（实测背后是 Chrome 全屏播放视频），两张相邻坐标
        #    本来就可能差 180+，用它当硬判据会误报。真透明的**确定性**证明在
        #    下面的 `_premultiply_bgra` 断言（直接查喂给 UpdateLayeredWindow 的缓冲）。
        l1s = {k: v["l1"] for k, v in corner_rows.items()}
        note(f"  （参考）角内 vs 角外 L1（受动态桌面影响，不作判据）: {l1s}")
        # 底板真没了：窗口内**不存在**任何一块 (28,28,28)/(243,244,247) 的均匀背景带
        band = [px(shots["splash.png"], r[0] + 1, r[1] + h // 2),
                px(shots["splash.png"], r[2] - 2, r[1] + h // 2),
                px(shots["splash.png"], r[0] + w // 2, r[3] - 2)]
        check("紧贴窗口边缘的点是 logo 自己的像素（没有残留的底板色带）",
              all(b is not None and abs(b[0] - b[1]) > 12 for b in band), str(band))

        # 存一张带周围 24px 的裁剪图，便于目视复核"圆润效果 / 有没有脏边"
        try:
            crop = shots["splash.png"]["img"].crop(
                (max(0, r[0] - 24), max(0, r[1] - 24),
                 min(shots["splash.png"]["w"], r[2] + 24),
                 min(shots["splash.png"]["h"], r[3] + 24)))
            crop = crop.resize((crop.width * 2, crop.height * 2))
            crop.convert("RGB").save(os.path.join(TMP, "splash_corner_crop.png"))
            note(f"  已存放大裁剪图: {os.path.join(TMP, 'splash_corner_crop.png')}")
        except Exception as exc:                           # noqa: BLE001
            note(f"  （裁剪图保存失败：{exc}）")

        logo_pt = px(shots["splash.png"], *pts["C"])
        # 中心应当是 logo 的白心（#FFFFFF 附近）；无论去底板前(深色底 (28,28,28))
        # 还是后，中心都不是"纯灰阶的底板色"，所以用"是不是接近白"来判定。
        near_white = logo_pt is not None and min(logo_pt) >= 235
        check("中心是 logo 自己的像素（白心，不是底板灰阶）", near_white, str(logo_pt))
        REPORT["splash_rect"] = list(r)

    # 底板没了 ⇒ splash 矩形面积应当 == 位图面积
    if frames:
        r = frames[0][1]
        check("窗口尺寸 == 位图尺寸（80px 边距的底板真的没了）",
              (r[2] - r[0], r[3] - r[1]) == (w, h), f"{(r[2]-r[0], r[3]-r[1])} vs {(w, h)}")


# ======================================================================
# B) 真跑整个程序：看"叠加"到底是什么叠什么
# ======================================================================
def pid_alive(pid):
    """tasklist 判活：别把"进程已死"当成"窗口没出现"（lead 的要求）"""
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             timeout=15, shell=True).stdout.decode("gbk", "replace")
    except Exception:                                     # noqa: BLE001
        return None
    return str(pid) in out


def part_b():
    """真起整个程序，按 lead 给的时间轴（splash 0–2s、主窗口 ~3.3s）采样到 12s。

    ⚠️ 三条纪律（lead 明确要求）：
      · **不改 DATA_DIR / 不造临时数据根** —— 就用用户真实环境（theme 已经是浅色主题）；
      · 轮询到 **12 秒**、每 0.4 秒采一次，记下**第一次看到主窗口的时刻**；
      · 起进程时把 **stdout/stderr 重定向到文件**（进程早退的原因只在那里面），
        并用 tasklist 判活。
    """
    note("== B) 真起整个程序（python ToolsGCP.pyw），0.4s 一次采样到 12s ==")
    out_path = os.path.join(TMP, "app_stdout.txt")
    err_path = os.path.join(TMP, "app_stderr.txt")
    pyw = os.path.join(ROOT, "ToolsGCP.pyw")
    exe = sys.executable                       # 用 python.exe（不是 pythonw）才能拿到两路输出
    note(f"  用 {exe}（stdout/stderr → {out_path} / {err_path}）")
    t0 = time.monotonic()
    with open(out_path, "wb") as fo, open(err_path, "wb") as fe:
        # CREATE_NO_WINDOW：用 python.exe 拿得到两路输出，又不弹控制台
        #（控制台本身是个可见顶层窗口，会污染"谁盖谁"的判断）
        proc = subprocess.Popen([exe, pyw], cwd=ROOT, stdout=fo, stderr=fe,
                                stdin=subprocess.DEVNULL,
                                creationflags=0x08000000)
    note(f"  已拉起 PID={proc.poll()}→{proc.pid}")
    REPORT["app_pid"] = proc.pid
    timeline = []
    main_first = None
    overlap = []
    try:
        for i in range(30):                     # 0.4s × 30 = 12s
            target = t0 + 0.4 * (i + 1)
            wait = target - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            tag = f"t{0.4 * (i + 1):.1f}"
            alive = proc.poll() is None
            rows = enum_windows()
            vis = [x for x in rows if x["visible"] and x["rect"]
                   and x["rect"][2] - x["rect"][0] > 1]
            sp = [x for x in vis if x["class"].startswith("ToolsGCP_Splash")]
            # 主窗口：pywebview/WinForms 的顶层类名是 Chrome_WidgetWin_1，
            # 且**属于本 PID**（用 GetWindowThreadProcessId 精确归属，避免抓到别的 Chrome 窗口）
            mn = [x for x in vis if x["class"] == "Chrome_WidgetWin_1"
                  and x["pid"] == proc.pid]
            shot = screenshot(os.path.join(TMP, f"app_{tag}.png"))
            entry = {"tag": tag, "alive": alive,
                     "splash": [x["rect"] for x in sp],
                     "main": [x["rect"] for x in mn],
                     "visible_all": [(x["class"], x["title"][:24], x["rect"], x["z"])
                                     for x in vis],
                     "shot": (shot or {}).get("path")}
            if mn and main_first is None:
                main_first = tag
            if sp and mn:
                overlap.append(tag)
            timeline.append(entry)
            note(f"  @{tag} 存活={alive}  splash={len(sp)} "
                 f"{[x['rect'] for x in sp]}  本进程主窗口={len(mn)} "
                 f"{[(x['rect'], x['z']) for x in mn]}  可见顶层共 {len(vis)}")
            if shot and (sp or mn):
                for label, w in (("splash", sp), ("main", mn)):
                    for x in w[:1]:
                        pts = rects_to_points(x["rect"], inset=2)
                        samp = {k: px(shot, *v) for k, v in pts.items()}
                        note(f"       {label} 像素 " +
                             " ".join(f"{k}={v}" for k, v in samp.items()))
                        REPORT.setdefault("live_pixels", {}).setdefault(tag, {})[label] = samp
            if not alive:
                note(f"  !! 进程在 @{tag} 已退出（code={proc.returncode}）→ 停止采样")
                break
        REPORT["timeline"] = timeline
        note(f"  首次看到**本进程主窗口**的时刻: {main_first}")
        note(f"  splash 与主窗口**同时可见**的采样点: {overlap or '无'}")
        REPORT["main_first_seen"] = main_first
        REPORT["overlap_tags"] = overlap
        check("进程全程存活（没启动即退）", proc.poll() is None or main_first is not None,
              f"poll={proc.poll()}")
        check("12 秒内主窗口出现过", main_first is not None, str(main_first))
        check("splash 与主窗口没有同时可见（启动时序正常，没有叠加）", not overlap,
              str(overlap))
    finally:
        note("  收尾：关闭程序（taskkill 进程树）")
        try:
            r = subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=30, shell=True)
            note("    " + r.stdout.decode("gbk", "replace").strip()[:400])
        except Exception as exc:                           # noqa: BLE001
            note(f"    !! taskkill 异常: {exc}")
        try:
            proc.wait(timeout=20)
        except Exception:                                  # noqa: BLE001
            pass
        note(f"    进程退出码={proc.returncode}  tasklist 仍存活={pid_alive(proc.pid)}")
    for p, name in ((out_path, "app stdout"), (err_path, "app stderr")):
        try:
            txt = open(p, encoding="utf-8", errors="replace").read().strip()
            note(f"  ---- {name}（{len(txt)} 字节）----")
            for line in (txt.splitlines()[-25:] if txt else ["(空)"]):
                note("    " + line[:200])
            REPORT[name] = txt[-4000:]
        except Exception as exc:                           # noqa: BLE001
            note(f"  !! 读 {name} 失败: {exc}")
    time.sleep(1.2)
    rows = enum_windows()
    left = [x for x in rows if x["class"].startswith("ToolsGCP") or
            (x["visible"] and "ToolsGCP" in x["title"])]
    check("测完没有残留的 ToolsGCP 窗口", not left,
          str([(x["class"], x["title"], x["visible"]) for x in left]))
    return timeline


# ======================================================================
# C) 从真实日志抠证据
# ======================================================================
def part_c(since_bytes=0):
    note("== C) 真实日志里与启动画面/主窗口相关的行 ==")
    if not os.path.exists(LOG_FILE):
        note("  （没有日志文件）")
        return []
    with open(LOG_FILE, encoding="utf-8", errors="replace") as fh:
        if since_bytes:
            fh.seek(since_bytes)
        tail = fh.read()
    keys = ("启动画面", "显示自己", "底色", "splash", "首屏", "窗口", "boot")
    lines = [l.strip() for l in tail.splitlines()
             if any(k in l for k in keys)]
    for l in lines[-40:]:
        note("  " + l[:220])
    REPORT["log_lines"] = lines[-60:]
    return lines


def main():
    log_size = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0
    part_a()
    if FULL:
        part_b()
        part_c(log_size)
    else:
        part_c(0)
    fails = [k for k, v in REPORT.get("checks", {}).items() if not v]
    note("\n== 结论 ==")
    note(f"  检查项 {len(REPORT.get('checks', {}))} 条，失败 {len(fails)} 条：{fails}")
    REPORT["failed"] = fails
    with open(os.path.join(TMP, "probe.json"), "w", encoding="utf-8") as fh:
        json.dump(REPORT, fh, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(TMP, "findings.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(FINDINGS) + "\n")
    note(f"  产物目录: {TMP}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
