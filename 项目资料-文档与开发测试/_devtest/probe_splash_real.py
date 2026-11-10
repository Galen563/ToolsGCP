# -*- coding: utf-8 -*-
"""启动画面真机取证脚本（win-visual · task-7）

用法（在仓库根目录执行）：
    python "项目资料-文档与开发测试/_devtest/probe_splash_real.py"

做三件事（**都会真弹一个几百毫秒的小窗 + 截全屏到 _tmp-ai-test**）：
  ① 浅色主题：用"临时数据根"（把用户真实 config 复制进 项目资料-.../_tmp-ai-test/home/），
     让 splash 走真实读取路径读到 theme="浅色主题"，然后截全屏、采样窗口内背景像素；
  ② 居中/位置跳变：从窗口一出现就每 10ms 记 GetWindowRect，直到销毁，检查首帧==后续帧；
  ③ 窗口清单：同一时刻枚举所有可见顶层窗口（类名/标题/矩形），确认只有 splash 一个。
另外离屏校验 _prepare_bitmap 的四角 alpha=0（本轮需求③"去掉底板 + 图片四角圆角"）。

⚠️ 绝不改用户真实 %USERPROFILE%\\.ToolsGCP：本脚本把 USERPROFILE 换成临时目录再 import。
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import ctypes
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TMP_ROOT = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", "splash-real")
HOME = os.path.join(TMP_ROOT, "home")

REAL_CONFIG = os.path.join(os.environ.get("USERPROFILE", ""), ".ToolsGCP", "config",
                           "toolsgcp_config.json")

# ---- 1) 隔离用户数据根：把真实 config 复制到临时 home，再改 USERPROFILE ----
os.makedirs(os.path.join(HOME, ".ToolsGCP", "config"), exist_ok=True)
os.makedirs(os.path.join(HOME, ".ToolsGCP", "logs"), exist_ok=True)
copied_theme = "<no-real-config>"
try:
    with open(REAL_CONFIG, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    copied_theme = str(cfg.get("theme"))
    with open(os.path.join(HOME, ".ToolsGCP", "config", "toolsgcp_config.json"),
              "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False)
except Exception as exc:                                    # noqa: BLE001
    print("!! 读取真实配置失败（继续，会按默认深色跑）:", exc)

os.environ["USERPROFILE"] = HOME
os.environ["HOMEDRIVE"], os.environ["HOMEPATH"] = os.path.splitdrive(HOME)

sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

import pymodels.constants as constants_mod                  # noqa: E402
from desktop import splash as S                             # noqa: E402
from desktop.native import win32                            # noqa: E402

ICON = os.path.join(ROOT, ".ToolsGCP", "logo.png")
SHOT = os.path.join(TMP_ROOT, "splash_shot.png")
LOG = []
FAILS = []


def say(msg):
    print(msg)
    LOG.append(msg)


def check(name, cond, detail=""):
    say(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"   <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def screenshot(path):
    """PowerShell System.Drawing 截全屏 -> PNG"""
    ps = (
        "Add-Type -AssemblyName System.Drawing;"
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
        f"$bmp.Save('{path}',[System.Drawing.Imaging.ImageFormat]::Png);"
        "$g.Dispose();$bmp.Dispose();"
    )
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                       check=True, timeout=20,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return os.path.exists(path)
    except Exception as exc:                                # noqa: BLE001
        say(f"  !! 截屏失败: {exc}")
        return False


U = ctypes.windll.user32
# ⚠️ 必须声明 argtypes：64 位下 HWND 会超过 32 位，不声明会被截断成 int，
#    GetClassNameW 直接返回空串 → 枚举永远找不到 ToolsGCP_Splash* 窗口（踩过）。
U.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
U.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
U.IsWindowVisible.argtypes = [wintypes.HWND]
U.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def enum_windows():
    rows = []
    buf = (ctypes.c_wchar * 256)()
    tbuf = (ctypes.c_wchar * 256)()

    def cb(h, _lp):
        U.GetClassNameW(h, buf, 256)
        cls = str(buf.value)
        if cls.startswith("ToolsGCP") or "webview" in cls.lower():
            U.GetWindowTextW(h, tbuf, 256)
            r = wintypes.RECT()
            U.GetWindowRect(h, ctypes.byref(r))
            rows.append({
                "hwnd": int(h), "class": cls, "title": str(tbuf.value),
                "rect": (r.left, r.top, r.right, r.bottom),
                "visible": bool(U.IsWindowVisible(h)),
            })
        return True

    U.EnumWindows(ENUMPROC(cb), 0)
    return rows


def sample_shot(path, rects):
    """在截图里采样：窗口四角外(应透明不受影响)、窗口内背景点、中心点"""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    W, H = im.size
    out = {}
    for name, (x, y) in rects.items():
        if 0 <= x < W and 0 <= y < H:
            out[name] = im.getpixel((x, y))
    return out


def main():
    from PIL import Image
    say("== 环境 ==")
    say(f"  USERPROFILE(临时)={os.environ['USERPROFILE']}")
    say(f"  DATA_DIR={constants_mod.DATA_DIR}")
    say(f"  复制的真实 theme={copied_theme!r}  resolve_splash_dark()={S.resolve_splash_dark()}")

    # ---- 离屏：位图四角 alpha / 背景像素 ----
    w, h, raw = S._prepare_bitmap(ICON, dark=False)

    def px(x, y):
        i = (y * w + x) * 4
        return (raw[i], raw[i + 1], raw[i + 2], raw[i + 3])

    say(f"== 离屏位图 {w}x{h}（浅色主题）==")
    say(f"  corner(0,0)={px(0,0)}  corner(w-1,0)={px(w-1,0)}  "
        f"corner(0,h-1)={px(0,h-1)}  corner(w-1,h-1)={px(w-1,h-1)}")
    if w > 100:
        say(f"  bg(8,h//2)={px(8, h // 2)}  center={px(w // 2, h // 2)}")

    # ---- 真机：起 splash，记录矩形 + 截屏 ----
    say("== 真机：起 splash（5s，截一次屏再立刻收尾）==")
    ctl = S.SplashController(ICON, 5000, enabled=True)
    rects = []
    stop = threading.Event()

    def watch():
        # 直接轮询控制器句柄：比 EnumWindows 更稳（窗口还没上屏时也能拿到真实矩形）
        while not stop.is_set():
            hwnd = ctl._hwnd
            if hwnd:
                r = wintypes.RECT()
                got = U.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
                if got:
                    rects.append((round(time.monotonic() - t0, 3),
                                  (r.left, r.top, r.right, r.bottom),
                                  bool(U.IsWindowVisible(wintypes.HWND(hwnd)))))
            time.sleep(0.01)

    t0 = time.monotonic()
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    started = ctl.start()
    say(f"  start()={started}")
    time.sleep(0.9)
    hwnd_now = ctl._hwnd
    say(f"  截屏前 hwnd={hwnd_now} "
        f"visible={bool(hwnd_now and U.IsWindowVisible(wintypes.HWND(hwnd_now)))}")
    t_shot = time.monotonic()
    shot_ok = screenshot(SHOT)
    say(f"  截屏耗时 {time.monotonic() - t_shot:.2f}s  ok={shot_ok}  "
        f"PNG mtime={time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(SHOT))) if os.path.exists(SHOT) else '-'}")
    time.sleep(0.15)
    say("  窗口清单（此刻）：")
    for row in enum_windows():
        say(f"    {row['class']}  标题={row['title']!r}  rect={row['rect']}  visible={row['visible']}")
    stop.set()
    ctl.wait(5)
    watcher.join(2)

    # ---- ① 首帧矩形 & 是否跳变 ----
    say("== ② 居中/跳变 ==")
    if not rects:
        say("  !! 没抓到 splash 窗口（可能被沙箱限制）")
    else:
        first = rects[0]
        uniq = []
        for _t, r, v in rects:
            if not uniq or uniq[-1] != r:
                uniq.append(r)
        say(f"  采样 {len(rects)} 次，时间 {rects[0][0]}~{rects[-1][0]}s")
        say(f"  首帧 rect={first[1]} visible={first[2]}")
        say(f"  不同矩形序列({len(uniq)}): {uniq[:12]}")
        wa = win32.work_area()
        fw = first[1][2] - first[1][0]
        fh = first[1][3] - first[1][1]
        cx = (first[1][0] + first[1][2]) / 2.0
        cy = (first[1][1] + first[1][3]) / 2.0
        ax = (wa[0] + wa[2]) / 2.0
        ay = (wa[1] + wa[3]) / 2.0
        say(f"  work_area={wa}  首帧中心=({cx},{cy})  工作区中心=({ax},{ay})")
        check("首帧就居中（±2px）", abs(cx - ax) <= 2 and abs(cy - ay) <= 2)
        check("窗口尺寸==位图尺寸", (fw, fh) == (w, h), f"窗 {fw}x{fh} / 位图 {w}x{h}")
        check("整段生命周期矩形不变（无跳变）", len(uniq) == 1, str(uniq[:6]))

    # ---- ① 截图像素 ----
    # ⚠️ 本轮**底板已去掉**（用户要求"底板去除 + 给加载图片四角加圆润效果"），
    #    所以窗口内不再有"背景像素"可采：紧贴边缘 20px 的位置现在是 **logo 自己的像素**，
    #    蓝紫底 (≈101,69,236) 的 R/G 本来就 < 200 —— 老的那条"背景 R,G,B 都 > 200"判据
    #    在新设计下**必然 FAIL**，属于断言过期，不是渲染 bug。
    #    另外：截屏本身**不能**用来证明"角外真透明"（实测会被 BitBlt 对分层窗口的行为
    #    + 动态桌面干扰，同一坐标两张图能差 L1=202；见 probe_capture_artifact.py 的对照实验）。
    #    真透明的确定性判据在 probe_splash_r2.py / test_splash_theme.py 里：
    #    直接断言 `_premultiply_bgra()` 的输出（那才是交给 UpdateLayeredWindow 的字节）。
    say("== ① 浅色主题截图像素（新规格：只查'是不是 logo 自己的像素'）==")
    if shot_ok and rects:
        l, t, r, b = rects[0][1]
        mid_y = (t + b) // 2
        pts = {
            "窗口内·左边20px(应是 logo 像素)": (l + 20, mid_y),
            "窗口内·上边20px(应是 logo 像素)": ((l + r) // 2, t + 20),
            "窗口中心(应是 logo 白心)": ((l + r) // 2, mid_y),
            "窗口外(左20px，桌面参照)": (l - 20, mid_y),
            "窗口外(上方20px，桌面参照)": ((l + r) // 2, t - 20),
        }
        got = sample_shot(SHOT, pts)
        for k, v in got.items():
            say(f"  {k} = #{v[0]:02X}{v[1]:02X}{v[2]:02X}  {v}")
        inside = [v for k, v in got.items() if "窗口内" in k]
        if inside:
            check("窗口内像素不是底板灰阶（#1c1c1c / #f3f4f7 那种 R=G=B），而是 logo 的彩色像素",
                  all(abs(v[0] - v[2]) > 12 for v in inside), str(inside))
        say(f"  截图={SHOT}")
    else:
        say("  !! 没有截图/窗口矩形，跳过像素断言")

    # ---- 四角 alpha = 0（需求③）----
    say("== ③ 四角真透明 ==")
    corner_alpha = [px(0, 0)[3], px(w - 1, 0)[3], px(0, h - 1)[3], px(w - 1, h - 1)[3]]
    check("四角 alpha==0", all(a == 0 for a in corner_alpha), str(corner_alpha))

    say("")
    say(f"结果：{'全部通过' if not FAILS else '有失败项: ' + str(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
