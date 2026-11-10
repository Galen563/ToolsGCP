# -*- coding: utf-8 -*-
"""启动画面（splash.py）跟随主题的回归测试 —— 需求 A。

背景：启动画面是**纯 Win32 分层窗口**，底色以前写死深色 (43,43,43,240)，
      用户设置"浅色主题"时启动画面仍是深色 → 观感割裂。
现在：贴图前读一次设置里的 `theme`，浅色用 webui 的浅色 `--page` #F3F4F7、
      深色用深色 `--page` #1C1C1C；"跟随系统"按 Windows 判定；
      **读设置失败 / 设置文件损坏 → 回退深色，绝不抛异常、绝不白屏**。

本脚本验证三件事：
    ① 三种主题（浅色 / 深色 / 跟随系统）splash 选到的底色正确，
       且深/浅两个色值就是 webui/css/variables.css 里的 `--page`（不另造一套色）；
    ② 设置缺失 / JSON 损坏 / 键缺失 / 目录不存在 → 回退深色且**不抛异常**；
       另外确认"读设置"这一步**只读不写**（绝不改用户配置）；
    ③ 真正画出来的位图底色对得上（_prepare_bitmap 的像素采样），
       且窗口尺寸/圆角规格没被这次外观改动带偏；splash.py 仍然不 import PyQt5。

⚠️⚠️ 跑法：
    python "项目资料-文档与开发测试/_devtest/test_splash_theme.py"
⚠️ 本脚本**绝不碰用户真实配置**：把 pymodels.constants.DATA_DIR 临时指向
   tempfile.mkdtemp() 里的目录，只在那里造/删配置文件；跑完恢复原值。
⚠️ 本脚本**不真的弹启动画面窗口**（那会闪一下）；只在最后一步做静态接线检查，
   确认 `_run_native` 里确实是"先 resolve_splash_dark() 再 _prepare_bitmap(..., dark)"。
"""
import json
import os
import re
import shutil
import sys
import tempfile

# ---------- 第一件事：把"入口"摆成真实入口，再 import pymodels ----------
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

import pymodels.constants as constants_mod                    # noqa: E402
from pymodels.utils.system_utils import detect_system_theme   # noqa: E402

_qt_before = "PyQt5" in sys.modules
from desktop import splash as splash_mod                      # noqa: E402

FAILS = []
SKIPS = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def hex_of(rgb):
    return "#%02x%02x%02x" % tuple(rgb[:3])


def write_cfg(tmp, data, name="toolsgcp_config.json"):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(data, str):
            fh.write(data)
        else:
            json.dump(data, fh, ensure_ascii=False)
    return path


ORIG_DATA_DIR = constants_mod.DATA_DIR

# ======================================================================
print("[1] 三种主题 → 底色选择（含与 webui --page 的色值一致性）")
# 与 webui/css/variables.css 对齐：浅色 --page #f3f4f7、深色 --page #1c1c1c
css_path = os.path.join(ROOT, ".ToolsGCP", "webui", "css", "variables.css")
with open(css_path, encoding="utf-8") as fh:
    css_pages = [v.lower() for v in re.findall(r"--page:\s*(#[0-9a-fA-F]{6})", fh.read())]
check("webui variables.css 里同时有浅色 #f3f4f7 与深色 #1c1c1c 的 --page",
      "#f3f4f7" in css_pages and "#1c1c1c" in css_pages, str(css_pages))
check("splash 浅色底就取 webui 的浅色 --page（#f3f4f7）",
      hex_of(splash_mod._SPLASH_BG_LIGHT) == "#f3f4f7", hex_of(splash_mod._SPLASH_BG_LIGHT))
check("splash 深色底就取 webui 的深色 --page（#1c1c1c）",
      hex_of(splash_mod._SPLASH_BG_DARK) == "#1c1c1c", hex_of(splash_mod._SPLASH_BG_DARK))
check("底色仍然是半透明 240（原视觉规格：分层窗口圆角半透明底）",
      splash_mod._SPLASH_BG_DARK[3] == 240 and splash_mod._SPLASH_BG_LIGHT[3] == 240)

# ⚠️ 不用系统 %TEMP%，也**不用 mkdtemp**：本沙箱里 mkdtemp 新建的随机目录写文件会
#    PermissionDenied（Errno 13），但固定名字的 os.makedirs 目录可写。
#    和 test_ai_versions.py 同一套约定：写进工作区 _tmp-ai-test/<固定名>（.gitignore 覆盖）。
tmpdir = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", "splash-theme")
shutil.rmtree(tmpdir, ignore_errors=True)
os.makedirs(tmpdir, exist_ok=True)
try:
    constants_mod.DATA_DIR = tmpdir

    write_cfg(tmpdir, {"theme": "浅色主题"})
    check("theme=浅色主题 → 浅色（resolve 返回 False）",
          splash_mod.resolve_splash_dark() is False)
    light_pick = splash_mod.resolve_splash_dark()
    check("浅色时实际用的底色 = _SPLASH_BG_LIGHT",
          splash_mod._SPLASH_BG_LIGHT if not light_pick else None
          == splash_mod._SPLASH_BG_LIGHT)

    write_cfg(tmpdir, {"theme": "深色主题"})
    check("theme=深色主题 → 深色（resolve 返回 True）",
          splash_mod.resolve_splash_dark() is True)

    write_cfg(tmpdir, {"theme": "跟随系统"})
    expected_follow = detect_system_theme() == "深色主题"
    check(f"theme=跟随系统 → 按 Windows 判定（复用 detect_system_theme()={expected_follow}）",
          splash_mod.resolve_splash_dark() is expected_follow)
    probe = detect_system_theme()
    check("跟随系统走的是**项目里现成**的 system_utils.detect_system_theme（不是新写的注册表读取）",
          probe in ("浅色主题", "深色主题"), probe)

    # 显式传参优先于读文件（给测试/其它调用方留的口子）
    write_cfg(tmpdir, {"theme": "深色主题"})
    check("显式传 theme 时以传参为准（不被配置文件覆盖）",
          splash_mod.resolve_splash_dark("浅色主题") is False
          and splash_mod.resolve_splash_dark("深色主题") is True)

    # ---------- ② 回退：缺失 / 损坏 / 认不出来 ----------
    print("\n[2] 读设置失败 / 设置损坏 → 一律回退深色，且绝不抛异常")
    cfg_path = os.path.join(tmpdir, "toolsgcp_config.json")
    os.remove(cfg_path)
    check("设置文件不存在 → 回退深色", splash_mod.resolve_splash_dark() is True)

    write_cfg(tmpdir, "{ this is not json ")
    check("设置文件是坏 JSON → 回退深色", splash_mod.resolve_splash_dark() is True)

    write_cfg(tmpdir, [1, 2, 3])
    check("设置文件不是对象（是数组）→ 回退深色",
          splash_mod.resolve_splash_dark() is True)

    write_cfg(tmpdir, {"theme": ""})
    check("theme 是空串 → 回退深色", splash_mod.resolve_splash_dark() is True)
    write_cfg(tmpdir, {"theme": None})
    check("theme 是 null → 回退深色", splash_mod.resolve_splash_dark() is True)
    write_cfg(tmpdir, {"theme": "Dark"})
    check("theme 是认不出来的值 → 回退深色", splash_mod.resolve_splash_dark() is True)
    write_cfg(tmpdir, {"other_key": 1})
    check("设置里没有 theme 键 → 回退深色", splash_mod.resolve_splash_dark() is True)

    os.remove(cfg_path)
    os.makedirs(cfg_path)                       # 配置"文件"竟然是个目录 → open 必然抛
    check("读取时抛异常（配置路径是目录）→ 回退深色、不抛",
          splash_mod.resolve_splash_dark() is True)
    os.rmdir(cfg_path)

    # "_read_theme_setting 自己炸了"也要兜住
    real_reader = splash_mod._read_theme_setting
    splash_mod._read_theme_setting = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        check("_read_theme_setting 抛异常 → resolve 仍返回深色、不抛",
              splash_mod.resolve_splash_dark() is True)
    finally:
        splash_mod._read_theme_setting = real_reader

    # DATA_DIR 整个不存在
    constants_mod.DATA_DIR = os.path.join(tmpdir, "does-not-exist")
    check("数据根目录不存在 → 回退深色、不创建目录、不抛",
          splash_mod.resolve_splash_dark() is True
          and not os.path.exists(constants_mod.DATA_DIR))
    constants_mod.DATA_DIR = tmpdir

    # ---------- 只读不写 ----------
    write_cfg(tmpdir, {"theme": "浅色主题", "hotkey_browser": "Ctrl+Shift+O"})
    before = open(cfg_path, "rb").read()
    stat_before = os.stat(cfg_path)
    splash_mod.resolve_splash_dark()
    splash_mod.resolve_splash_dark()
    after = open(cfg_path, "rb").read()
    check("读主题**只读不写**：配置文件内容/大小/mtime 都没变",
          before == after and os.stat(cfg_path).st_size == stat_before.st_size
          and os.stat(cfg_path).st_mtime == stat_before.st_mtime)
    check("读主题不会顺手创建别的文件（目录里仍然只有这一个配置）",
          sorted(os.listdir(tmpdir)) == ["toolsgcp_config.json"], str(os.listdir(tmpdir)))
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)
    constants_mod.DATA_DIR = ORIG_DATA_DIR

# ======================================================================
print("\n[3] 真正画出来的位图：去底板后的规格 / 兜底 / 不 import PyQt5")
# ⚠️ 同样不用系统 %TEMP%（沙箱里新建随机目录不可写，Errno 13），用固定名目录。
tmpdir2 = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", "splash-theme2")
logo = os.path.join(ROOT, ".ToolsGCP", "logo.png")
if not os.path.isfile(logo):
    print(f"  ⚠️ 找不到 {logo} → 跳过位图采样")
    SKIPS.append("位图采样（缺 logo.png）")
else:
    from PIL import Image
    win_d, h_d, raw_dark = splash_mod._prepare_bitmap(logo, True)
    win_l, h_l, raw_light = splash_mod._prepare_bitmap(logo, False)

    def pixel(raw, w, x, y):
        i = (y * w + x) * 4
        return tuple(raw[i:i + 4])

    # —— 本轮需求 ③：底板去除后，位图**就是 logo 本身**，不再有背景矩形 ——
    im = Image.open(logo)
    lw, lh = im.size
    if max(lw, lh) > splash_mod._SPLASH_LOGO_MAX:
        ratio = min(splash_mod._SPLASH_LOGO_MAX / lw, splash_mod._SPLASH_LOGO_MAX / lh)
        lw, lh = int(lw * ratio), int(lh * ratio)
    check("窗口尺寸 == logo 尺寸（底板和 80px 边距已去掉）",
          (win_d, h_d) == (lw, lh), f"{win_d}x{h_d} vs logo {im.size}")
    check("_SPLASH_MARGIN 已废弃为 0（代码里不再参与绘制）",
          splash_mod._SPLASH_MARGIN == 0, str(splash_mod._SPLASH_MARGIN))
    check("圆角半径按图片比例算且不为 0（180px → 29px 量级）",
          0 < splash_mod._corner_radius(lw, lh) <= min(lw, lh) // 2,
          str(splash_mod._corner_radius(lw, lh)))

    corners = [(0, 0), (win_l - 1, 0), (0, h_l - 1), (win_l - 1, h_l - 1)]
    cpx = [pixel(raw_light, win_l, x, y) for (x, y) in corners]
    check("四个角 alpha == 0（真透明，不留黑边/白边/脏边）",
          all(p[3] == 0 for p in cpx), str(cpx))
    # 圆角外沿一圈也必须是 0（LANCZOS 振铃最容易在这里留 1~2 的漏光）
    ring = [pixel(raw_light, win_l, x, y)
            for x in range(0, min(20, win_l)) for y in (0,)
            ] + [pixel(raw_light, win_l, x, 1) for x in range(0, 6)]
    check("角外沿邻近像素也全为 alpha==0（超采样振铃没有漏光）",
          all(p[3] == 0 for p in ring), str(ring[:6]))
    center = pixel(raw_light, win_l, win_l // 2, h_l // 2)
    src_center = im.convert("RGBA").getpixel((im.size[0] // 2, im.size[1] // 2))
    check("中心仍是 logo 自己的像素（没被底色覆盖）",
          center[:3] == src_center[:3] and center[3] == 255,
          f"splash={center} logo={src_center}")
    check("四边中点仍是 logo 像素、alpha=255（只有角被裁，边上没被裁）",
          pixel(raw_light, win_l, 0, h_l // 2)[3] == 255
          and pixel(raw_light, win_l, win_l - 1, h_l // 2)[3] == 255,
          str([pixel(raw_light, win_l, 0, h_l // 2),
               pixel(raw_light, win_l, win_l - 1, h_l // 2)]))
    n_zero = sum(1 for i in range(3, len(raw_light), 4) if raw_light[i] == 0)
    n_part = sum(1 for i in range(3, len(raw_light), 4) if 0 < raw_light[i] < 255)
    check("透明像素只出现在圆角处（数量合理）且边缘有平滑过渡",
          200 < n_zero < win_l * h_l * 0.1 and n_part > 0,
          f"alpha0={n_zero} alpha中间值={n_part} 总像素={win_l * h_l}")
    check("深浅两次出图**几何完全一致**（底板没了之后深/浅只差在兜底色，不动几何）",
          (win_d, h_d) == (win_l, h_l) and raw_dark == raw_light,
          f"{win_d}x{h_d} vs {win_l}x{h_l}")

    # —— 兜底：图片缺失/损坏 → 圆角纯色块，仍然不崩 ——
    tmp_bad = os.path.join(tmpdir2, "bad.png")
    os.makedirs(tmpdir2, exist_ok=True)
    with open(tmp_bad, "wb") as fh:
        fh.write(b"not a png at all")
    for name, path in (("缺失", os.path.join(ROOT, "no-such-logo.png")),
                       ("损坏", tmp_bad)):
        bw, bh, braw = splash_mod._prepare_bitmap(path, False)
        bcorner = pixel(braw, bw, 0, 0)
        bcenter = pixel(braw, bw, bw // 2, bh // 2)
        check(f"图片{name} → 兜底仍是带圆角的纯色块（角 alpha=0、中心 = 浅色底 240）",
              bw == splash_mod._SPLASH_FALLBACK_SIZE and bcorner[3] == 0
              and bcenter == (243, 244, 247, 240), f"{bw}x{bh} 角={bcorner} 中={bcenter}")
    # 深色兜底用深色块（主题仍然跟随）
    dw, dh, draw_ = splash_mod._prepare_bitmap(tmp_bad, True)
    check("兜底块在深色主题下用深色 #1c1c1c/240",
          pixel(draw_, dw, dw // 2, dh // 2) == (28, 28, 28, 240),
          str(pixel(draw_, dw, dw // 2, dh // 2)))
    shutil.rmtree(tmpdir2, ignore_errors=True)

check("import desktop.splash 前后都没有把 PyQt5 拉进 sys.modules（主线程禁 Qt）",
      ("PyQt5" in sys.modules) == _qt_before)

# 接线检查：_run_native 真的是"先 resolve 再贴图"
with open(os.path.join(ROOT, ".ToolsGCP", "desktop", "splash.py"), encoding="utf-8") as fh:
    src = fh.read()
check("_run_native 里调用了 resolve_splash_dark() 并把结果传给 _prepare_bitmap",
      "resolve_splash_dark()" in src and "_prepare_bitmap(self.icon_path, dark)" in src)
check("底图按 dark 二选一（没有残留写死的 _SPLASH_BG）",
      "_SPLASH_BG_DARK if dark else _SPLASH_BG_LIGHT" in src and "_SPLASH_BG " not in src)
check("已经**不再画底板**（_prepare_bitmap 里没有 canvas 背景矩形 / 不再用 _SPLASH_MARGIN 算窗口）",
      "win_w, win_h = w + _SPLASH_MARGIN" not in src
      and "canvas.paste(bg, (0, 0), mask)" not in src)
check("浅色分支带现场取证日志（theme 原值 + DATA_DIR 会进日志）",
      "_theme_diagnostics()" in src and "theme={diag['theme_raw']}" in src)

# ======================================================================
print("\n[4] 喂给 UpdateLayeredWindow 的**预乘 BGRA 缓冲**（真透明的确定性证明）")
# ⚠️ 为什么单独立一段：截屏采样会被"动态桌面/背后在放视频"干扰（实测同一坐标两张
#    截图能差 L1=202），拿它证明"角外透明"并不可靠。这里直接断言 `_premultiply_bgra`
#    的输出 —— 那才是真正交给分层窗口的字节。
if os.path.isfile(logo):
    from PIL import Image as _Img
    _src_im = _Img.open(logo)
    bw, bh, braw = splash_mod._prepare_bitmap(logo, False)
    packed = splash_mod._premultiply_bgra(braw, bw, bh)

    def pk(x, y):
        i = (y * bw + x) * 4
        return tuple(packed[i:i + 4])          # B,G,R,A

    corners = {"TL": (0, 0), "TR": (bw - 1, 0), "BL": (0, bh - 1),
               "BR": (bw - 1, bh - 1)}
    cp = {k: pk(*v) for k, v in corners.items()}
    note = list(cp.values())
    check("圆角外 4 个像素 BGRA **全 0**（alpha=0 且 RGB 也清零 = 真透明、不可能有脏边）",
          all(p == (0, 0, 0, 0) for p in note), str(cp))
    # 整圈外沿（不止 4 个点）：凡 alpha==0 的位置，BGRA 必须四个字节都是 0
    bad = [(i, tuple(packed[i:i + 4])) for i in range(0, len(packed), 4)
           if packed[i + 3] == 0 and any(packed[i:i + 4])]
    check("全图所有 alpha==0 的像素 BGRA 都是 (0,0,0,0)（没有'透明但留着颜色'的漏光）",
          not bad, f"{len(bad)} 个违规，前几个={bad[:3]}")
    center = pk(bw // 2, bh // 2)
    check("中心 = logo 白心且通道顺序已换成 BGRA（白仍是白，没被装反成别的色）",
          center == (255, 255, 255, 255), str(center))
    # 通道装反检查：取 logo 内一个**偏蓝紫**的非灰像素（R≈95、B≈242），
    # 装反的话 packed 的 B 会变成 95 —— 一眼就能看出来。
    inner = (12, 12)
    src_rgba = _src_im.convert("RGBA").getpixel(inner)
    got = pk(*inner)
    check("非灰像素的 R/B **没有**被装反（预乘后仍保持 B>G…R 的相对关系）",
          got[0] == src_rgba[2] and got[1] == src_rgba[1] and got[2] == src_rgba[0],
          f"src RGBA={src_rgba} → packed BGRA={got}")
    # 半透明（兜底块 alpha=240）预乘算得对
    fw, fh, fraw = splash_mod._prepare_bitmap(os.path.join(ROOT, "no-such.png"), False)
    fp = splash_mod._premultiply_bgra(fraw, fw, fh)
    i = ((fh // 2) * fw + fw // 2) * 4
    want = ((247 * 240) // 255, (244 * 240) // 255, (243 * 240) // 255, 240)
    check("兜底块 alpha=240 的预乘值 = 各通道 ×240/255（分层窗口要求预乘，浅色底也算对）",
          tuple(fp[i:i + 4]) == want, f"got={tuple(fp[i:i + 4])} want={want}")
    check("_update_layered 已改为调用 _premultiply_bgra（不再是内联循环，避免两处不一致）",
          "_premultiply_bgra(raw_argb, width, height)" in src)

print("\n" + ("全部通过 OK" if not FAILS else f"失败 {len(FAILS)} 项: {FAILS}"))
if SKIPS:
    print(f"环境跳过: {SKIPS}")
sys.exit(1 if FAILS else 0)
