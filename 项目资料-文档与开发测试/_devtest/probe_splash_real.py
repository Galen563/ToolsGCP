# -*- coding: utf-8 -*-
"""启动画面真机取证脚本（win-visual · task-7 · 第 32 轮需求改版后重写）

用法（在仓库根目录执行）：
    python "项目资料-文档与开发测试/_devtest/probe_splash_real.py"            # 默认：只跑离屏，**不碰屏幕**
    python "项目资料-文档与开发测试/_devtest/probe_splash_real.py" --show     # 才真弹 + 截全屏

⚠️ 第 31 轮起：**默认不弹任何窗、不截任何屏**（用户要边用电脑边跑测试）。
真机取证必须显式加 --show，那时才会真弹一个小窗 + 截全屏到 _tmp-ai-test。

⚠️⚠️ 第 32 轮需求又变了，本脚本跟着改写（先读这段再看断言）：
    用户原话「浅色主题的悬浮启动动画底板要和深色一致。不是单纯改个颜色，而是把之前
    判断主题的那套逻辑删掉——底板固定一种颜色，不需要专门一套检测逻辑服务它」。
    ⇒ 上一版这里第①件事是"让 splash 走真实读取路径读到 theme=浅色主题，验证底板变浅"，
      并调用 resolve_splash_dark() 与 _prepare_bitmap(ICON, dark=False)。
      这些符号已经**整体删除**（_read_theme_setting / resolve_splash_dark /
      _theme_diagnostics / _SPLASH_BG_LIGHT），_prepare_bitmap 的签名现在是
      (icon_path, scale=1.0) —— 显示路径对配置文件**零读取**。
    ⇒ 本脚本第①件事改成："把真实配置复制进临时数据根（含它的 theme）→ 证明
      不论 theme 是什么，出图字节与截图像素都是同一块固定深色底板"，
      而不是"证明浅色主题下底板变浅"。第②③件事（居中/跳变、窗口清单）不变。
    ⇒ 另外本轮 splash 的等待循环已换成**真消息泵**（PeekMessageW + DispatchMessageW +
      MsgWaitForMultipleObjects），所以"鼠标一碰就未响应、再点直接被关掉"应当消失；
      本脚本 --show 段顺带取证"窗口能建起来、且 stop() 能让窗口线程正常收尾"。
    ⇒ _theme_is_light 仍然存在（shell 的主窗口配色要用），它的兼容表在
      test_splash_theme.py 里逐条测，本脚本不重复。

⚠️ 绝不改用户真实 %USERPROFILE% 下的 .ToolsGCP：本脚本把 USERPROFILE 换成临时目录再 import。
"""
import json
import os
import shutil
import subprocess
import sys
# ⚠️ Windows 控制台默认是 GBK 代码页：本文件的断言名里有 ⇒ 这类非 GBK 字符，
#    直接 print 会抛 UnicodeEncodeError，把取证脚本**从中间打断**
#    （实测 probe_splash_live.py 因此崩在半路、退出码 1，看起来像断言失败）。
#    这里只把编不出来的字符替换掉，**不改编码**：中文仍按控制台原编码输出，
#    不会变乱码；换到 UTF-8 终端（Windows Terminal / PYTHONIOENCODING=utf-8）同样正常。
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:                            # noqa: BLE001
    pass

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
#     本轮起 splash 不读配置，这一步的意义变成**反向证明**：真实 theme（大概率是
#     "浅色主题"）摆在那里，画面也仍是那块固定深色底板。
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
    print("!! 读取真实配置失败（继续；本轮画面与配置无关）:", exc)

os.environ["USERPROFILE"] = HOME
os.environ["HOMEDRIVE"], os.environ["HOMEPATH"] = os.path.splitdrive(HOME)

sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

import pymodels.constants as constants_mod                  # noqa: E402
from desktop import splash as S                             # noqa: E402
from desktop.native import win32                            # noqa: E402

ICON = os.path.join(ROOT, ".ToolsGCP", "logo.png")
SHOT = os.path.join(TMP_ROOT, "splash_shot.png")

# 第 31 轮：默认**不弹窗、不截全屏**（用户要一边用电脑一边跑测试）。
# 真机取证必须显式加 --show。
SHOW = "--show" in sys.argv
LOG = []
FAILS = []
SKIPS = []


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
        "$bmp.Save('" + path + "',[System.Drawing.Imaging.ImageFormat]::Png);"
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
U.GetWindowThreadProcessId.restype = wintypes.DWORD
U.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def enum_windows():
    rows = []
    buf = (ctypes.c_wchar * 256)()
    tbuf = (ctypes.c_wchar * 256)()

    def cb(h, _lp):
        U.GetClassNameW(h, buf, 256)
        cls = str(buf.value)
        if cls.startswith("ToolsGCP") or "webview" in cls.lower():
            # 历史坑（第 31 轮及以前）：GetWindowTextW 会给目标窗口线程发 WM_GETTEXT，
            # 而当时 splash 窗口线程**只 sleep 轮询、从不泵消息**，同进程调用会永久阻塞
            # （实测 probe 卡死在这一行，退出码 124）。
            # 第 32 轮起 _run_native 的等待循环已换成真消息泵，那个阻塞条件消失了；
            # 但这里仍保留"自己进程的窗口不取标题"：类名足够定位、不依赖对方线程状态，
            # 取证脚本不该把自己要验的东西当依赖（万一消息泵又有问题，probe 得能跑完）。
            title = ""
            pid = wintypes.DWORD(0)
            U.GetWindowThreadProcessId(wintypes.HWND(h), ctypes.byref(pid))
            if int(pid.value) != os.getpid():
                U.GetWindowTextW(h, tbuf, 256)
                title = str(tbuf.value)
            r = wintypes.RECT()
            U.GetWindowRect(h, ctypes.byref(r))
            rows.append({
                "hwnd": int(h), "class": cls, "title": title,
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
    say("== 环境 ==")
    say(f"  USERPROFILE(临时)={os.environ['USERPROFILE']}")
    say(f"  DATA_DIR={constants_mod.DATA_DIR}")
    say(f"  复制的真实 theme={copied_theme!r}")
    # ⚠️ 本轮起**没有** resolve_splash_dark 这个函数可调：主题判定整套已随需求删除，
    #    底板固定 _SPLASH_BG_DARK。这里把"配置里写的是什么"和"画面是什么"解耦取证。
    check("splash 模块里已无 resolve_splash_dark / _SPLASH_BG_LIGHT（主题逻辑删干净了）",
          not hasattr(S, "resolve_splash_dark") and not hasattr(S, "_SPLASH_BG_LIGHT"))
    check("固定底板色 = _SPLASH_BG_DARK (28,28,28,240)",
          tuple(S._SPLASH_BG_DARK) == (28, 28, 28, 240), str(S._SPLASH_BG_DARK))

    # ---- 离屏：位图四角 alpha / 底板像素（新契约：**固定深色**，与 theme 无关）----
    w, h, raw = S._prepare_bitmap(ICON)

    def px(x, y):
        i = (y * w + x) * 4
        return (raw[i], raw[i + 1], raw[i + 2], raw[i + 3])

    say(f"== 离屏位图 {w}x{h}（底板固定深色；真实配置 theme={copied_theme!r} 不参与）==")
    say(f"  corner(0,0)={px(0,0)}  corner(w-1,0)={px(w-1,0)}  "
        f"corner(0,h-1)={px(0,h-1)}  corner(w-1,h-1)={px(w-1,h-1)}")
    board_px = px(S._SPLASH_MARGIN // 2, h // 2)
    say(f"  底板(margin/2,h//2)={board_px}  center={px(w // 2, h // 2)}")
    check("左边距那一圈 = 固定深色 (28,28,28,240)（浅色主题摆在那儿也一样）",
          board_px == (28, 28, 28, 240), str(board_px))

    # 反向证明：把临时数据根里的 theme 逐种写法改一遍，出图**字节**必须一模一样。
    # （上一版这里是"读配置 → 判深浅 → 二选一底色"，现在配置对显示路径压根不存在。）
    cfg_in_home = os.path.join(HOME, ".ToolsGCP", "config", "toolsgcp_config.json")
    orig_data_dir = constants_mod.DATA_DIR
    orig_bytes = raw
    try:
        constants_mod.DATA_DIR = os.path.join(HOME, ".ToolsGCP")
        for theme in ("浅色主题", "深色主题", "跟随系统", "Light Theme"):
            with open(cfg_in_home, "w", encoding="utf-8") as fh:
                fh.write('{"theme": "%s"}' % theme)
            _, _, t_raw = S._prepare_bitmap(ICON)
            check(f"配置 theme={theme!r} → 出图字节与基线完全一致（底板不受主题影响）",
                  t_raw == orig_bytes)
    finally:
        constants_mod.DATA_DIR = orig_data_dir
        # 把临时 home 里的配置恢复成"用户真实那一份"，别留遍历用的假 theme
        try:
            with open(REAL_CONFIG, encoding="utf-8") as fh:
                real = json.load(fh)
            with open(cfg_in_home, "w", encoding="utf-8") as fh:
                json.dump(real, fh, ensure_ascii=False)
        except Exception:                                    # noqa: BLE001
            pass

    # ---- 真机：起 splash，记录矩形 + 截屏 ----
    # 第 31 轮：默认**不弹窗、不截全屏**；真机动作必须显式 --show。
    rects = []
    shot_ok = False
    if not SHOW:
        say("== 真机段已跳过（未加 --show：默认不弹启动画面、不截全屏）==")
        say("   需要真机取证：加 --show（会占用屏幕约 1 秒）")
        SKIPS.append("真机段（未加 --show）")
    else:
        say("== 真机：起 splash（截一次屏后立刻 stop 收尾）==")
        # ⚠️ 第 32 轮起显示时长**不再由 duration 形参决定**（形参只为兼容旧调用点留着），
        #    画面一直挂到主流程调 stop()。老写法"wait(5) 就结束"会让置顶窗赖屏到硬超时，
        #    所以这里必须显式 stop()。
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
        check("SplashController.start() 成功（本机可建分层窗口）", bool(started), str(started))
        if not started:
            # 平台/沙箱限制导致起不来：如实跳过，不把"没跑成"算成 splash 的失败
            SKIPS.append("真机段（start() 返回 False：平台/沙箱限制）")
            stop.set()
            watcher.join(2)
        else:
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
            ok_stop = ctl.stop(3)
            check("stop() 后窗口线程收尾完成（消息泵能正常退出，不赖屏）", ok_stop,
                  f"stop()->{ok_stop}")
            watcher.join(2)

    # ---- ② 首帧矩形 & 是否跳变 ----
    say("== ② 居中/跳变 ==")
    if not rects:
        if SHOW:
            say("  !! 没抓到 splash 窗口（可能被沙箱限制）")
            SKIPS.append("② 居中/跳变（没抓到窗口）")
        else:
            say("  （真机段已跳过：未做居中/跳变取证；加 --show 可跑）")
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
    # 第 32 轮：底板**固定深色**（不再是"跟随主题的两种底色"）：
    #    窗口边缘那一圈是深色底板（R≈G≈B≈28，alpha 240 叠桌面后仍远小于 128），
    #    中心是 logo 白心。浅色主题配置摆在那里，这里采到的也必须是深色。
    #    另外：截屏本身**不能**用来证明"角外真透明"（实测会被 BitBlt 对分层窗口的行为
    #    + 动态桌面干扰，同一坐标两张图能差 L1=202；见 probe_capture_artifact.py 的对照实验）。
    #    真透明的确定性判据在 probe_splash_r2.py / test_splash_theme.py 里：
    #    直接断言 _premultiply_bgra() 的输出（那才是交给 UpdateLayeredWindow 的字节）。
    say("== ① 截图像素（新契约：边缘=固定深色底板、中心=logo 白心）==")
    if shot_ok and rects:
        l, t, r, b = rects[0][1]
        mid_y = (t + b) // 2
        pts = {
            "窗口内·左边20px(应是深色底板)": (l + 20, mid_y),
            "窗口内·上边20px(应是深色底板)": ((l + r) // 2, t + 20),
            "窗口中心(应是 logo 白心)": ((l + r) // 2, mid_y),
            "窗口外(左20px，桌面参照)": (l - 20, mid_y),
            "窗口外(上方20px，桌面参照)": ((l + r) // 2, t - 20),
        }
        got = sample_shot(SHOT, pts)
        for k, v in got.items():
            say(f"  {k} = #{v[0]:02X}{v[1]:02X}{v[2]:02X}  {v}")
        edge = [v for k, v in got.items() if "窗口内·" in k]
        if edge:
            check("窗口边缘一圈是灰阶（底板中性色；本轮起只有深色这一种）",
                  all(abs(v[0] - v[1]) <= 12 and abs(v[1] - v[2]) <= 12 for v in edge),
                  str(edge))
            # 本轮新增的硬判据：那圈灰阶必须**偏暗**，不能是浅色的 #f3f4f7。
            # 深色底板 (28,28,28) alpha=240 叠任何桌面后通道值仍远小于中灰 128。
            check("窗口边缘是**深色**底板（通道值 <128，浅色主题下也没变浅）",
                  all(max(v) < 128 for v in edge), str(edge))
        center_v = got.get("窗口中心(应是 logo 白心)")
        if center_v:
            check("窗口中心是 logo 白心（近白、不是灰阶底板）",
                  min(center_v) >= 235, str(center_v))
        say(f"  截图={SHOT}")
    elif SHOW:
        say("  !! 没有截图/窗口矩形，跳过像素断言")
        SKIPS.append("① 截图像素（无截图/矩形）")
    else:
        say("  （未加 --show：无截图可采，跳过截图像素断言，不算失败也不算通过）")

    # ---- ③ 四角 alpha = 0（离屏确定性判据，与主题无关，本轮继续有效）----
    say("== ③ 四角真透明 ==")
    corner_alpha = [px(0, 0)[3], px(w - 1, 0)[3], px(0, h - 1)[3], px(w - 1, h - 1)[3]]
    check("四角 alpha==0", all(a == 0 for a in corner_alpha), str(corner_alpha))
    packed = S._premultiply_bgra(raw, w, h)
    bad = [(i, tuple(packed[i:i + 4])) for i in range(0, len(packed), 4)
           if packed[i + 3] == 0 and any(packed[i:i + 4])]
    check("预乘缓冲里所有 alpha==0 的像素 BGRA 全 0（截屏不可靠，字节才是确定性判据）",
          not bad, f"{len(bad)} 个违规")

    say("")
    if SKIPS:
        say(f"环境跳过: {SKIPS}")
    say(f"结果：{'全部通过' if not FAILS else '有失败项: ' + str(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
