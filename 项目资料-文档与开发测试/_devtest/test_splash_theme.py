# -*- coding: utf-8 -*-
"""启动画面（splash.py）**底板固定深色**的回归测试 —— 第 32 轮需求改版后的重写。

⚠️⚠️ 本脚本验证什么（本轮需求变了，先读这段再往下看）
    用户原话：「浅色主题的悬浮启动动画底板要和深色一致。不是单纯改个颜色，而是把
    之前判断主题的那套逻辑删掉——底板固定一种颜色，不需要专门一套检测逻辑服务它。」
    ⇒ 上一版这个脚本验的是"底板跟随主题"（浅色 #F3F4F7 / 深色 #1C1C1C 二选一 +
      读设置失败回退深色）。**那一整套主题分支断言已经整段作废**，被本文件替换成
      "底板固定深色 + 浅色主题下也仍然是这块深色底板 + 显示路径根本不读配置"。

现在 splash.py 的事实（断言就围绕这几条）：
  · 底板**固定** _SPLASH_BG_DARK = (28, 28, 28, 240)，与 webui 深色 --page #1c1c1c 对齐；
  · 已删除的符号：_read_theme_setting / resolve_splash_dark / _theme_diagnostics /
    _SPLASH_BG_LIGHT；_prepare_bitmap 签名从 (icon_path, dark, scale) 变成
    (icon_path, scale=1.0) —— 显示路径对配置文件**零读取**（连 json 都不 import）；
  · _theme_is_light **仍然保留**：desktop/shell.py 的主窗口 / boot-screen 配色还在
    import 它（那是"窗口**里面**的启动动画"另一条链路，与本浮窗无关），所以它的
    浅/深/跟随系统兼容表本脚本继续测，别跟着删。

四段验证：
    ① 符号面：四个符号确实没了、新签名里没有 dark 参数、固定底色 == webui 深色
       --page（不另造一套色）、_theme_is_light 兼容表没退化、shell 还在用它；
    ② 显示路径零配置读取：把 DATA_DIR 指向"浅色主题 / 坏 JSON / 目录不存在"三种配置，
       _prepare_bitmap 出来的**字节完全一致**（浅色主题下仍是这块深色底板），
       且配置文件内容 / mtime 一字未动、不会顺手创建文件；
    ③ 真正画出来的位图：底板像素 = 固定深色、圆角外 alpha 严格 0（无黑边/白边/脏边）、
       logo 居中、图片缺失/损坏走同构兜底块且不崩、DPI 放大后尺寸与底色都对；
       splash 仍然不把 PyQt5 拉进 sys.modules（主线程禁 Qt）；
    ④ 喂给 UpdateLayeredWindow 的**预乘 BGRA 缓冲**（真透明的确定性证明，
       截屏会被动态桌面干扰，实测同坐标能差 L1=202，所以拿字节当判据）。

⚠️⚠️ 跑法：
    python "项目资料-文档与开发测试/_devtest/test_splash_theme.py"
⚠️ 本脚本**绝不碰用户真实配置**：把 pymodels.constants.DATA_DIR 临时指向工作区
   _tmp-ai-test/splash-theme（沙箱里 tempfile.mkdtemp 新建的随机目录不可写，
   Errno 13，所以用固定名目录），跑完删除并恢复原值。
⚠️ 本脚本**不真的弹启动画面窗口**（那会闪一下）；真机取证见 probe_splash_*.py。
"""
import ast
import inspect
import json
import os
import re
import shutil
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


# ---------- 第一件事：把"入口"摆成真实入口，再 import pymodels ----------
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

import pymodels.constants as constants_mod                    # noqa: E402
from desktop import splash as splash_mod                      # noqa: E402

_qt_before = "PyQt5" in sys.modules

FAILS = []
SKIPS = []

# 本轮被删掉的符号：脚本本身、以及 splash 源码里，都不该再出现它们
DEAD_SYMBOLS = ("_read_theme_setting", "resolve_splash_dark",
                "_theme_diagnostics", "_SPLASH_BG_LIGHT")


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def hex_of(rgb):
    return "#%02x%02x%02x" % tuple(rgb[:3])


def pixel(raw, w, x, y):
    i = (y * w + x) * 4
    return tuple(raw[i:i + 4])


def write_cfg(tmp, data, name="toolsgcp_config.json"):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(data, str):
            fh.write(data)
        else:
            json.dump(data, fh, ensure_ascii=False)
    return path


ORIG_DATA_DIR = constants_mod.DATA_DIR
logo = os.path.join(ROOT, ".ToolsGCP", "logo.png")

# ======================================================================
print("[1] 符号面：主题检测逻辑已整体删除，底板只剩一块固定深色")
# —— ① 被删的四个符号：模块属性面 + 源码文本面，两处都不能有残留
for name in DEAD_SYMBOLS:
    check(f"splash 模块里已删除 {name}", not hasattr(splash_mod, name))
with open(os.path.join(ROOT, ".ToolsGCP", "desktop", "splash.py"), encoding="utf-8") as fh:
    src = fh.read()
# 源码里允许在"历史备注/需求变更"注释中提到旧名字，但必须是**否定式**表述；
# 真正判据是模块属性面没有这些函数 + 显示路径不引用它们（下面几条逐一验）。
for name in DEAD_SYMBOLS:
    call_sites = [m.start() for m in re.finditer(re.escape(name) + r"\s*\(", src)]
    check(f"splash.py 源码里没有 {name}(...) 的调用点", not call_sites,
          f"{len(call_sites)} 处")
check("_prepare_bitmap 的新签名是 (icon_path, scale=1.0)，没有 dark 参数",
      list(inspect.signature(splash_mod._prepare_bitmap).parameters) == ["icon_path", "scale"],
      str(inspect.signature(splash_mod._prepare_bitmap)))
# ⚠️ 这里必须用 AST 取**函数体**（去掉 docstring）再找 dark：
#    _prepare_bitmap 的 docstring 里写的是"本轮已删掉原来的第二个位置参数 dark"，
#    那是**历史备注**、不是分支。整段源码字符串匹配会把它误判成"还有 dark 分支"。
_fn = ast.parse(inspect.getsource(splash_mod._prepare_bitmap))
_body = _fn.body[0].body
if isinstance(_body[0], ast.Expr) and isinstance(_body[0].value, ast.Constant) \
        and isinstance(_body[0].value.value, str):
    _body = _body[1:]                              # 丢掉 docstring
_fn_code = "\n".join(ast.unparse(n) for n in _body)
check("_prepare_bitmap 函数体（去 docstring）里没有 dark 分支，底色直接取固定深色",
      "dark" not in _fn_code and "bg_color = _SPLASH_BG_DARK" in _fn_code,
      "dark" in _fn_code and "函数体仍出现 dark" or "OK")

# —— ② 固定底色与 webui 深色 --page 对齐（"不另造一套色"这条老规矩继续有效）
css_path = os.path.join(ROOT, ".ToolsGCP", "webui", "css", "variables.css")
with open(css_path, encoding="utf-8") as fh:
    css_pages = [v.lower() for v in re.findall(r"--page:\s*(#[0-9a-fA-F]{6})", fh.read())]
check("splash 固定底板 = webui 深色 --page（#1c1c1c），不另造一套色",
      hex_of(splash_mod._SPLASH_BG_DARK) == "#1c1c1c" and "#1c1c1c" in css_pages,
      f"{hex_of(splash_mod._SPLASH_BG_DARK)} / css={css_pages}")
check("底板 alpha 仍是 240（分层窗口圆角半透明的原视觉规格）",
      splash_mod._SPLASH_BG_DARK[3] == 240, str(splash_mod._SPLASH_BG_DARK))
check("浅色底板色值常量已随之删除（谁再'跟随主题'就是把本轮需求改回去）",
      not hasattr(splash_mod, "_SPLASH_BG_LIGHT"))
# 显示路径对配置零读取：模块连 json / 配置读取都不需要
check("splash 模块不再 import json（显示路径不碰配置文件）",
      "json" not in dir(splash_mod))
# ⚠️ 取**函数体文本**来断言，别用 src.split(常量名)[i] 这种"猜区间"的写法：
#    _SPLASH_CORNER_MAX 在源码里出现两次（常量定义 + _corner_radius 里用一次），
#    split 出来的 [1] 只是这两处之间的一小段，压根不含 _run_native，断言等于空转。
_run_body_src = src.split("def _run_native", 1)[1].split("def _close_window", 1)[0]
check("贴图前只做 DPI + 位图，没有'读主题/取证'那一段",
      "_prepare_bitmap(self.icon_path, scale)" in _run_body_src
      and "theme_raw" not in _run_body_src
      and "_read_theme_setting" not in _run_body_src
      and "toolsgcp_config" not in _run_body_src)
check("_run_native 里也没有任何对系统主题/注册表的读取（跟随系统那套已作废）",
      "detect_system_theme" not in _run_body_src)

# —— ③ _theme_is_light 保留：shell 的主窗口配色还要它（不属于本轮改动）
check("_theme_is_light 仍在（desktop/shell.py 的主窗口配色还在 import 它）",
      hasattr(splash_mod, "_theme_is_light"))
with open(os.path.join(ROOT, ".ToolsGCP", "desktop", "shell.py"), encoding="utf-8") as fh:
    shell_src = fh.read()
check("shell.py 里确实还写着 from .splash import _theme_is_light（别把它删了）",
      "_theme_is_light" in shell_src)
_light_cases = ["浅色主题", "浅色", "淺色主題", "Light Theme", "light", "亮色", "明亮", "白色"]
_dark_cases = ["深色主题", "深色", "暗色", "黑色", "Dark Theme", "dark", "night", "夜间"]
_none_cases = ["跟随系统", "跟隨系統", "follow system", "auto", "", "乱写的值"]
check("_theme_is_light 浅色族全部判 True（shell 那条链路不能退化）",
      all(splash_mod._theme_is_light(v) is True for v in _light_cases),
      str({v: splash_mod._theme_is_light(v) for v in _light_cases
           if splash_mod._theme_is_light(v) is not True}))
check("_theme_is_light 深色族全部判 False",
      all(splash_mod._theme_is_light(v) is False for v in _dark_cases),
      str({v: splash_mod._theme_is_light(v) for v in _dark_cases
           if splash_mod._theme_is_light(v) is not False}))
check("_theme_is_light 跟随系统族/空值/认不出来 → None（交给调用方兜深色）",
      all(splash_mod._theme_is_light(v) is None for v in _none_cases),
      str({v: splash_mod._theme_is_light(v) for v in _none_cases
           if splash_mod._theme_is_light(v) is not None}))

# ======================================================================
print("\n[2] 显示路径零配置读取：浅色主题下也仍然是这块深色底板")
# ⚠️ 不用系统 %TEMP%，也不用 mkdtemp：本沙箱里 mkdtemp 新建的随机目录写文件会
#    PermissionDenied（Errno 13），固定名字的 os.makedirs 目录才可写。
tmpdir = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", "splash-theme")
shutil.rmtree(tmpdir, ignore_errors=True)
os.makedirs(tmpdir, exist_ok=True)
cfg_path = os.path.join(tmpdir, "toolsgcp_config.json")
try:
    # 基线：DATA_DIR 整个不存在（连配置文件都没有）时画出来的字节
    constants_mod.DATA_DIR = os.path.join(tmpdir, "does-not-exist")
    _, _, base_raw = splash_mod._prepare_bitmap(logo)
    check("数据根目录不存在时能正常出图（不抛、不创建目录）",
          len(base_raw) > 0 and not os.path.exists(constants_mod.DATA_DIR))

    constants_mod.DATA_DIR = tmpdir
    scenarios = [
        ("theme=浅色主题", {"theme": "浅色主题"}),
        ("theme=浅色（短形式，GCP-AI set_theme 写的就是这种）", {"theme": "浅色"}),
        ("theme=跟随系统", {"theme": "跟随系统"}),
        ("theme 是空串", {"theme": ""}),
        ("theme 是 null", {"theme": None}),
        ("没有 theme 键", {"other_key": 1}),
        ("坏 JSON", "{ this is not json "),
        ("顶层是数组不是对象", [1, 2, 3]),
    ]
    for label, data in scenarios:
        write_cfg(tmpdir, data)
        w2, h2, raw2 = splash_mod._prepare_bitmap(logo)
        # 这就是本轮需求的核心断言：**浅色主题下也仍是这块深色底板**，
        # 而不是"以前那样判成浅色再画"。配置文件对显示路径是彻底不存在的。
        check(f"{label} → 出图字节与'无配置'基线完全一致（底板固定深色）",
              raw2 == base_raw, f"{w2}x{h2}")

    # 配置文件"路径是个目录"这种会把 open() 炸掉的情况：显示路径压根不开它，
    # 所以不可能受影响（老脚本在这里验的是"读取抛异常 → 回退深色"，现在验的是"压根不读"）
    os.remove(cfg_path)
    os.makedirs(cfg_path)
    _, _, raw3 = splash_mod._prepare_bitmap(logo)
    check("配置路径是个目录（open 必抛）→ 出图不变（显示路径根本不打开它）",
          raw3 == base_raw)
    os.rmdir(cfg_path)

    # 只读不写 → 本轮更强：**连读都没有**
    write_cfg(tmpdir, {"theme": "浅色主题", "hotkey_browser": "Ctrl+Shift+O"})
    before = open(cfg_path, "rb").read()
    st_before = os.stat(cfg_path)
    splash_mod._prepare_bitmap(logo)
    splash_mod._prepare_bitmap(logo, 1.5)
    after = open(cfg_path, "rb").read()
    check("出图两次后配置文件内容/大小/mtime 一字未动",
          before == after and os.stat(cfg_path).st_size == st_before.st_size
          and os.stat(cfg_path).st_mtime == st_before.st_mtime)
    check("读主题不会顺手创建别的文件（目录里仍然只有这一个配置）",
          sorted(os.listdir(tmpdir)) == ["toolsgcp_config.json"], str(os.listdir(tmpdir)))
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)
    constants_mod.DATA_DIR = ORIG_DATA_DIR

# ======================================================================
print("\n[3] 真正画出来的位图：固定深色圆角底板 + 居中 logo 的规格 / 兜底 / DPI")
if not os.path.isfile(logo):
    print(f"  ⚠️ 找不到 {logo} → 跳过位图采样")
    SKIPS.append("位图采样（缺 logo.png）")
else:
    from PIL import Image
    im = Image.open(logo)
    lw0, lh0 = im.size
    w, h, raw = splash_mod._prepare_bitmap(logo)

    # —— 窗口尺寸 = logo + 2×边距（底板仍在，本轮只改了颜色来源，没动几何） ——
    logo_w, logo_h = lw0, lh0
    if max(lw0, lh0) > splash_mod._SPLASH_LOGO_MAX:
        ratio = min(splash_mod._SPLASH_LOGO_MAX / lw0, splash_mod._SPLASH_LOGO_MAX / lh0)
        logo_w, logo_h = int(lw0 * ratio), int(lh0 * ratio)
    margin = splash_mod._SPLASH_MARGIN
    check("窗口尺寸 == logo 尺寸 + 2×边距（底板几何未被本轮改动带偏）",
          (w, h) == (logo_w + 2 * margin, logo_h + 2 * margin),
          f"{w}x{h} vs 期望 {logo_w + 2 * margin}x{logo_h + 2 * margin}")
    check("_SPLASH_MARGIN 仍是 32（用户要求缩短底板边距）且 > 0",
          margin == 32 and margin > 0, str(margin))
    check("logo 自身圆角半径按图片比例算且不为 0（180px → 29px 量级）",
          0 < splash_mod._corner_radius(logo_w, logo_h) <= min(logo_w, logo_h) // 2,
          str(splash_mod._corner_radius(logo_w, logo_h)))

    # —— 底板：取**没有 logo 覆盖**的那一圈（左边距中央）—— 固定深色，唯一色 ——
    board = pixel(raw, w, margin // 2, h // 2)
    check("底板像素 = 固定深色 (28,28,28,240)（浅色主题下也算出来是这一块）",
          board == (28, 28, 28, 240), str(board))
    check("整张图**没有任何** (243,244,247,240) 的浅色底板像素（浅色分支真的没了）",
          not any(tuple(raw[i:i + 4]) == (243, 244, 247, 240)
                  for i in range(0, len(raw), 4)))

    # —— 圆角外必须**严格透明**（这条与主题无关，继续有效） ——
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    cpx = [pixel(raw, w, x, y) for (x, y) in corners]
    check("四个角 alpha == 0（真透明，不留黑边/白边/脏边）",
          all(p[3] == 0 for p in cpx), str(cpx))
    corner_block = [pixel(raw, w, x, y) for x in range(0, 5) for y in range(0, 5)]
    check("四角 5×5 小方块全是 alpha==0（没有任何残影/暗角）",
          all(p[3] == 0 for p in corner_block), str(corner_block[:4]))
    # 抗锯齿过渡带只能是"贴着边界的细带"，不能是散落的脏点
    band_ok, band_detail = True, ""
    for y in range(0, h):
        row = [pixel(raw, w, x, y)[3] for x in range(0, w)]
        trans = [x for x, a in enumerate(row) if 0 < a < 240]
        if len(trans) > 12:
            band_ok, band_detail = False, f"第 {y} 行有 {len(trans)} 个过渡像素（远超圆角所需）"
            break
        for x in trans:
            near = [row[i] for i in range(max(0, x - 3), min(w, x + 4)) if i != x]
            if not any(v == 0 or v == 240 for v in near):
                band_ok, band_detail = False, f"第 {y} 行 x={x} 的过渡像素远离边界（振铃脏边）"
                break
        if not band_ok:
            break
    check("抗锯齿过渡带只贴着边界（每行 ≤12 个过渡像素，且每个都紧邻 0 或 240）",
          band_ok, band_detail)
    rad = splash_mod._scaled(splash_mod._SPLASH_RADIUS, 1.0)
    edge = pixel(raw, w, rad + 2, 0)
    check("圆角半径之外紧邻处已经是底板（圆角形状正确，不是整块抠掉）",
          edge[3] == 240, str(edge))

    center = pixel(raw, w, w // 2, h // 2)
    src_center = im.convert("RGBA").getpixel((lw0 // 2, lh0 // 2))
    check("窗口中心仍是 logo 自己的像素（logo 居中贴上，没被底色覆盖）",
          center[:3] == src_center[:3] and center[3] == 255,
          f"splash={center} logo={src_center}")
    logo_edge = pixel(raw, w, margin, margin + logo_h // 2)
    check("logo 左边缘（边距处）就是 logo 像素（说明是居中贴图，不是铺满底板）",
          logo_edge[3] == 255, str(logo_edge))

    n_zero = sum(1 for i in range(3, len(raw), 4) if raw[i] == 0)
    n_part = sum(1 for i in range(3, len(raw), 4) if 0 < raw[i] < 255)
    check("透明像素只出现在四个圆角处（数量合理）且边缘有平滑过渡",
          0 < n_zero < 4000 and n_part > 0,
          f"alpha0={n_zero} alpha中间值={n_part} 总像素={w * h}")

    # —— 兜底：图片缺失/损坏 → **同构**圆角底板（中心就是固定深色），仍然不崩 ——
    # ⚠️ 同样不用系统 %TEMP%（沙箱里新建随机目录不可写，Errno 13），用固定名目录。
    tmpdir2 = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", "splash-theme2")
    os.makedirs(tmpdir2, exist_ok=True)
    tmp_bad = os.path.join(tmpdir2, "bad.png")
    with open(tmp_bad, "wb") as fh:
        fh.write(b"not a png at all")
    for label, path in (("缺失", os.path.join(ROOT, "no-such-logo.png")),
                        ("损坏", tmp_bad)):
        bw, bh, braw = splash_mod._prepare_bitmap(path)
        bcorner = pixel(braw, bw, 0, 0)
        bcenter = pixel(braw, bw, bw // 2, bh // 2)
        exp_fb = splash_mod._SPLASH_FALLBACK_SIZE + 2 * splash_mod._SPLASH_MARGIN
        check(f"图片{label} → 兜底是**同构**的圆角底板（{exp_fb}×{exp_fb}、角 alpha=0、"
              f"中心 = 固定深色 (28,28,28,240)）",
              (bw, bh) == (exp_fb, exp_fb) and bcorner[3] == 0
              and bcenter == (28, 28, 28, 240),
              f"{bw}x{bh} 角={bcorner} 中={bcenter}")
    shutil.rmtree(tmpdir2, ignore_errors=True)

    # —— DPI 缩放：尺寸随缩放比放大，底色**永远是同一块深色** ——
    for sc in (1.0, 1.25, 1.5, 2.0):
        sw, sh, sraw = splash_mod._prepare_bitmap(logo, sc)
        exp_logo = min(splash_mod._scaled(splash_mod._SPLASH_LOGO_MAX, sc),
                       splash_mod._scaled(max(lw0, lh0), sc))
        exp_w = exp_logo + 2 * splash_mod._scaled(splash_mod._SPLASH_MARGIN, sc)
        check(f"scale={sc} → 窗口 {exp_w}x{exp_w}（边距/圆角/logo 上限全部按 DPI 放大）",
              (sw, sh) == (exp_w, exp_w), f"{sw}x{sh}")
        sbar = pixel(sraw, sw, splash_mod._scaled(splash_mod._SPLASH_MARGIN, sc) // 2,
                     sh // 2)
        check(f"scale={sc} → 底板仍是固定深色 (28,28,28,240)",
              sbar == (28, 28, 28, 240), str(sbar))
    # 非法 scale 必须按 1.0 兜底（分层窗口的尺寸单位是物理像素，不能崩成 0×0）
    for bad in (0, -1, "x", None):
        bw2, bh2, _ = splash_mod._prepare_bitmap(logo, bad)
        check(f"非法 scale={bad!r} → 退回 1.0 的 {w}x{h}，不抛异常",
              (bw2, bh2) == (w, h), f"{bw2}x{bh2}")

check("import desktop.splash 前后都没有把 PyQt5 拉进 sys.modules（主线程禁 Qt）",
      ("PyQt5" in sys.modules) == _qt_before)

# 接线检查：_run_native 真的是"定 DPI → 直接按 scale 贴图"，中间没有任何主题环节
check("_run_native 里 _prepare_bitmap 只传 (icon_path, scale)（不再有 dark）",
      "_prepare_bitmap(self.icon_path, scale)" in src)
check("底板画回来了（窗口 = logo + 2×边距；圆角蒙版贴色；logo 居中合成）",
      "win_w, win_h = w + 2 * margin" in src
      and "canvas.paste(board, (0, 0), mask)" in src
      and "canvas.alpha_composite(logo," in src)
check("等待循环是真消息泵（PeekMessageW + DispatchMessageW），不是 sleep 轮询",
      "PeekMessageW" in src and "DispatchMessageW" in src
      and "MsgWaitForMultipleObjects" in src)

# ======================================================================
print("\n[4] 喂给 UpdateLayeredWindow 的**预乘 BGRA 缓冲**（真透明的确定性证明）")
# ⚠️ 为什么单独立一段：截屏采样会被"动态桌面/背后在放视频"干扰（实测同一坐标两张
#    截图能差 L1=202），拿它证明"角外透明"并不可靠。这里直接断言 _premultiply_bgra
#    的输出 —— 那才是真正交给分层窗口的字节。
if os.path.isfile(logo):
    from PIL import Image as _Img
    _src_im = _Img.open(logo)
    bw, bh, braw = splash_mod._prepare_bitmap(logo)
    packed = splash_mod._premultiply_bgra(braw, bw, bh)

    def pk(x, y):
        i = (y * bw + x) * 4
        return tuple(packed[i:i + 4])          # B,G,R,A

    corners = {"TL": (0, 0), "TR": (bw - 1, 0), "BL": (0, bh - 1), "BR": (bw - 1, bh - 1)}
    cp = {k: pk(*v) for k, v in corners.items()}
    check("圆角外 4 个像素 BGRA **全 0**（alpha=0 且 RGB 也清零 = 真透明、不可能有脏边）",
          all(p == (0, 0, 0, 0) for p in cp.values()), str(cp))
    bad = [(i, tuple(packed[i:i + 4])) for i in range(0, len(packed), 4)
           if packed[i + 3] == 0 and any(packed[i:i + 4])]
    check("全图所有 alpha==0 的像素 BGRA 都是 (0,0,0,0)（没有'透明但留着颜色'的漏光）",
          not bad, f"{len(bad)} 个违规，前几个={bad[:3]}")
    center = pk(bw // 2, bh // 2)
    check("中心 = logo 白心且通道顺序已换成 BGRA（白仍是白，没被装反成别的色）",
          center == (255, 255, 255, 255), str(center))
    # 通道装反检查：取 logo 内一个**偏蓝紫**的非灰像素（R≈95、B≈242），
    # 装反的话 packed 的 B 会变成 95 —— 一眼就能看出来。
    # ⚠️ 两边必须**同一坐标系的同一处**：src 取 logo 局部坐标，packed 取窗口坐标。
    #    logo 是**居中贴**在底板上的，窗口坐标 = 局部坐标 + 偏移量。
    _lw = _src_im.size[0]
    if max(_src_im.size) > splash_mod._SPLASH_LOGO_MAX:
        _lw = int(_src_im.size[0] * min(splash_mod._SPLASH_LOGO_MAX / _src_im.size[0],
                                        splash_mod._SPLASH_LOGO_MAX / _src_im.size[1]))
    _off = (bw - _lw) // 2
    _local = (12, 12)                                   # logo 局部坐标
    src_rgba = _src_im.convert("RGBA").getpixel(_local)
    got = pk(_off + _local[0], _off + _local[1])
    check("非灰像素的 R/B **没有**被装反（预乘后仍保持 B=src.B / R=src.R 的对应关系）",
          got[0] == src_rgba[2] and got[1] == src_rgba[1] and got[2] == src_rgba[0],
          f"src RGBA={src_rgba} → packed BGRA={got}")
    # 半透明（固定深色底板 alpha=240）预乘算得对
    fw, fh, fraw = splash_mod._prepare_bitmap(os.path.join(ROOT, "no-such.png"))
    fp = splash_mod._premultiply_bgra(fraw, fw, fh)
    i = ((fh // 2) * fw + fw // 2) * 4
    want = ((28 * 240) // 255, (28 * 240) // 255, (28 * 240) // 255, 240)
    check("兜底块 alpha=240 的预乘值 = 固定深色各通道 ×240/255（分层窗口要求预乘）",
          tuple(fp[i:i + 4]) == want, f"got={tuple(fp[i:i + 4])} want={want}")
    check("_update_layered 已改为调用 _premultiply_bgra（不再是内联循环，避免两处不一致）",
          "_premultiply_bgra(raw_argb, width, height)" in src)

print("\n" + ("全部通过 OK" if not FAILS else f"失败 {len(FAILS)} 项: {FAILS}"))
if SKIPS:
    print(f"环境跳过: {SKIPS}")
sys.exit(1 if FAILS else 0)
