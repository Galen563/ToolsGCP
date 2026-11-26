"""启动画面：**纯 Win32 实现，不再依赖 PyQt5**
========== 为什么换掉 Qt 版 ==========
旧版把原版 PyQt5 的 `SplashScreen` 放到 worker 线程里跑。它能用，但代价很实在：
  · **打包体积**：PyQt5 + PyQt-Fluent-Widgets 一起进 exe 就是几十 MB —— 而整个 Web 版
    的界面根本不用 Qt 画，只为了这一块启动画面拖着整套 Qt 进去（用户明确要求砍掉）；
  · **必须装在 worker 线程**：Qt 的 QApplication 有线程亲和性，主线程一旦 import 过
    PyQt5，进程退出就 100% 崩 0xC0000005（见旧版长注释，实测 8/8）；顺带还逼出了
    "退出时必须在创建线程里销毁、还要轮询 stop 请求"那一整套绕法。
现在改成 Win32 分层窗口（`UpdateLayeredWindow` 画**圆角半透明底板 + 居中 logo**）：
  · 零第三方依赖：只用 ctypes + 本仓库已有的 `desktop/native/win32.py`；
  · 在**自己的线程**里建窗口，和 `traymenu.py`（自绘托盘菜单）是同一个成熟路子；
  · logo 解码用 `Pillow`（requirements.txt 里本来就有，`native/appicon.py` 在用）。
========= 与旧版保持完全一致的对外契约 =========
`SplashController(icon_path, duration_ms, enabled, on_finished)`：
    `.start() -> bool`   真正起来了吗（False = 关闭/降级，此时已经 _finish 过）
    `.finished`          bool，播放结束了吗
    `.wait(timeout)`     等到结束
    `.stop(timeout)`     退出流程用：让窗口线程收尾并 join
shell.py 只依赖这几个方法，所以换实现不动外壳逻辑（双条件 ready 照旧）。
⚠️⚠️ 本轮需求变更：**显示多久不再由 duration 决定**（用户原话：「设置中的启动动画时长
删除，这个从此就不要了……显示时长相关代码改为程序什么时候出现这个悬浮启动画面就什么
时候消失；启动完成后再让悬浮启动动画消失」）。于是：
  · 窗口一直显示，**直到主流程叫它消失**（shell 在主窗口显示之后 stop()）；
  · 形参 `duration_ms` 只为兼容既有调用点/取证脚本而保留，**不再参与任何计时**；
  · `SPLASH_HARD_TIMEOUT_MS` 退化成的安全网含义也变了：从"最多播这么久"变成
    "万一主流程永远没叫我关（异常/死锁），最多赖屏这么久也必须自毁"，所以调大了。

⚠️⚠️ 本轮需求变更 2：**等待循环必须是真消息泵**（用户报"鼠标一碰启动画面就显示未
响应，再点一下直接被关闭"）。旧写法只有 `time.sleep(0.03)` 轮询，这条窗口线程
从不取消息；分层窗口被鼠标碰到时系统要跨线程调用本窗口的 WndProc，没人泵消息
调用方就阻塞 → 窗口被标记未响应 → 用户下一次点击被引导走到关闭路径。现在
_run_native 的等待段用 PeekMessageW/TranslateMessage/DispatchMessageW +
MsgWaitForMultipleObjects(30ms, QS_ALLINPUT)：消息被正常派发（不忙等、不重建位图），
三条退出条件（stop_requested / 窗口已销毁 / 硬超时安全网）保持不变。
WM_CLOSE 仍然只置标志，销毁只发生在建窗这条线程上（老规矩）。

============ 位置/尺寸：DPI 那一段是本轮修的 bug ============
⚠️⚠️ 用户反馈"启动画面先出现在屏幕正中央，然后突然跳到非中央的位置"（只有网友报，
   开发者本机不复现）。真因**不是居中算错**，而是**进程 DPI awareness 在启动画面
   显示期间被翻转**：pywebview 直到 webview.start() 里才 SetProcessDPIAware，
   而我们在那之前就用裸 Win32 建好了窗 —— 建窗时坐标被系统按" unaware + 缩放比"
   虚拟化，翻转之后同一组坐标按物理像素解释，窗口就"跳"了；100% 缩放的机器上
   这个翻转是恒等操作，所以只有 125%/150% 缩放的用户看得见。
   修法与完整推导写在 native/win32.py 的 `ensure_dpi_awareness()` 里，改之前先读它。
   另外整条链路只允许**一次定位**：建窗即按最终坐标建、UpdateLayeredWindow 用同一个
   (x,y)、ShowWindow 之后只做"校验"（偏了才纠正并记日志），绝不主动再搬第二次。
========= 视觉规格（底板 + 居中 logo；只学老版本的规格，不复制它的实现） =========
参考目录 `老版本临时参考文件/v1.0.0-beta.2/.ToolsGCP/desktop/splash.py`（**只读参考，
一个字节都不许改**）的视觉规格是：logo 最长边夹到 300px、窗口比 logo 每边多一圈边距、
画一块**圆角半透明底**，再把 logo **居中**贴上去。本轮用户要求"学习老版本的 UI 和动画
和大小，包括窗口动画的主体背景"，所以**底板加回来** —— 但实现全部自己写
（老版那份有不少已知 bug。老版底色同样写死深色，本轮需求也固定深色，但取值
   与 webui 的深色 --page 对齐，且实现全部自己写）。
现在的规格：
  · logo 最长边仍然夹到 300px（`_SPLASH_LOGO_MAX`，LANCZOS 平滑缩放）；
  · **窗口尺寸 = logo 尺寸 + 2 × 边距**，边距 `_SPLASH_MARGIN = 32`（每边 32px），
    底板圆角半径 `_SPLASH_RADIUS = 20`；
    ⚠️ 老版自己写的是"总共 +80"（`setFixedSize(w + 80, h + 80)`，即每边 40）；
       本项目一开始按用户口径"边距 80"取成**每边 80**，实测底板太空、logo 像浮在
       一张大纸上，用户明确要求"把底层边距距离 logo 缩短" ⇒ 现取**每边 32**
       （比老版每边 40 还紧一点，窗口 244×244，比老版 260×260 更小一圈）；
  · 边距 / 圆角半径 / logo 上限 / 兜底块尺寸**全部随 DPI 缩放比放大**
    （分层窗口的尺寸单位是物理像素，不放大在 150%/200% 屏上会缩水一半）；
  · **底板**：圆角矩形 + **固定深色**底（`_SPLASH_BG_DARK` = (28,28,28,240)，alpha 240）；
    ⚠️⚠️ 本轮需求变更（用户原话）：「浅色主题的悬浮启动动画底板要和深色一致。不是
       单纯改个颜色，而是把之前判断主题的那套逻辑删掉——底板固定一种颜色，不需要
       专门一套检测逻辑服务它」。原"读配置文件里的 theme → 判深浅 → 二选一底色"那一
       整套函数与常量（含取证日志）已**整体删除**，`_prepare_bitmap` 不再有 `dark`
       参数，显示路径对配置**零读取**。
       （历史备注：上一轮"底色必须跟随主题"是为了修"浅色主题下启动画面是一块黑"；
        本轮需求相反 —— 两种主题共用同一块深色底板，跟随逻辑整体作废，别加回来。）
       `_theme_is_light` 仍留在文件里：`desktop/shell.py` 的主窗口/boot-screen 配色
       还在 import 它 —— 那是"窗口内启动动画"的另一条链路，与本浮窗无关。
    底板圆角沿用 `_rounded_mask`（2x 超采样 + 1x 硬边取 min）⇒ **圆角外 alpha 严格为 0**，
    不会留下 LANCZOS 振铃造成的黑边/白边（脏边）；
  · logo **居中**贴在底板上（`alpha_composite` 到 (win_w-w)//2, (win_h-h)//2）；
  · logo **自身**的四角圆润处理**保留**（`_apply_corner_radius`，比例制半径）——
    它只乘在 logo 位图自己的 alpha 通道上，不影响底板；
  · 兜底路径（图片缺失/损坏）：与主路径**同构**——同样是一块圆角底板
    （中心是固定深色底、角外 alpha==0），绝不白屏/崩溃；
  · 无边框 + 置顶 + 不抢焦点（WS_POPUP + WS_EX_TOOLWINDOW|TOPMOST|LAYERED，
    ShowWindow(SW_SHOWNOACTIVATE)）。
本项目 logo 是 180×180 → 窗口 244×244（180 + 2×32；上一版每边 80 是 340×340，
去底板那版是 180×180，老版是 260×260）。
⚠️ 它**永远是独立小窗口**，绝不许拿主窗口冒充（那是"启动时闪一个等大空窗"的来源）。
"""

import ctypes
import os
import sys
import threading
import time
import traceback
from ctypes import wintypes

# 启动画面的**赖屏上限**（毫秒）：本轮起它不再是"播放时长"，而只是安全网 ——
# 正常路径是"主流程完成后由 shell 调 stop() 关掉"，这一条只防"主流程出了意外、
# 永远没人叫它关"（异常、死锁、显示逻辑被跳过），那种情况下也绝不能让一块
# 置顶的透明窗永远压在用户桌面上。
# ⚠️ 为什么从 12 秒调到 90 秒：慢机器/杀软首启、云端资源库第一次拉取时，
#    "主界面就绪"本身就可能要十几二十秒；安全网必须**明显大于**真实启动耗时，
#    否则又变回用户报的另一个问题"启动动画一瞬间就消失了"。
SPLASH_HARD_TIMEOUT_MS = 90000

# ---- 视觉常量（见模块 docstring 的"视觉规格"） ----
# 底板底色**固定深色**，本轮起不再跟随用户主题（需求与推导见 docstring：用户要求
# 把整套主题判定逻辑删掉，而不是只换个颜色）。取值仍与 webui/css/variables.css 的
# 深色 --page 对齐（#1C1C1C），alpha 240 沿用原视觉规格。
# ⚠️ 浅色底板色值常量已随之删除；谁再"跟随主题"就是把本轮需求改回去。
_SPLASH_BG_DARK = (28, 28, 28, 240)      # #1C1C1C = webui 深色 --page（唯一底板色）
_SPLASH_LOGO_MAX = 300                  # 原版 max_size = 300（logo 最长边上限）
# 底板圆角半径（老版 drawRoundedRect(..., 20, 20) 的规格）
_SPLASH_RADIUS = 20.0
# 底板边距：窗口 = logo + 2 × 边距（老版 setFixedSize(w+80, h+80) 是"总共 80"，
# 即每边 40；本项目先按"每边 80"做了一版，底板太空、logo 像浮在大纸上，
# 用户要求"把底层边距距离 logo 缩短" ⇒ 每边收到 32，窗口 244×244，比老版还小一圈）
_SPLASH_MARGIN = 32
# logo **自身**的四角半径：按图片短边的比例算，而不是写死像素（图片被缩放后圆润程度
# 保持一致）。0.16 → 180px 的 logo ≈ 29px 半径；只乘在 logo 位图自己的 alpha 上，
# 不影响底板的圆角。
_SPLASH_CORNER_RATIO = 0.16
_SPLASH_CORNER_MAX = 48                 # 半径上限：大图标别圆成圆形贴纸
# 图片缺失/损坏时的兜底方块尺寸（沿用旧版数字，改小会显得"启动画面消失了"）
_SPLASH_FALLBACK_SIZE = 220

# ---- Win32 常量（本地定义，避免动 win32.py 的公开面） ----
_WS_POPUP = 0x80000000
_WS_EX_LAYERED = 0x00080000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_TOPMOST = 0x00000008
_SW_SHOWNOACTIVATE = 0x0004
_ULW_ALPHA = 0x00000002
_AC_SRC_OVER = 0x00
_AC_SRC_ALPHA = 0x01
_WM_QUIT = 0x0012
_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_ERASEBKGND = 0x0014
# 消息泵（等待循环）用：PeekMessageW 的"取出即移除"模式，以及
# MsgWaitForMultipleObjects 的"任何输入消息都醒"过滤位（数值同 winuser.h）
_PM_REMOVE = 0x0001
_QS_ALLINPUT = 0x04FF
_WAIT_TIMEOUT = 258             # MsgWaitForMultipleObjects 返回值：正常超时
_WAIT_FAILED = 0xFFFFFFFF       # 同上：调用失败（ctypes 按有符号读回 -1）
_PUMP_WAIT_MS = 30              # 空闲等待粒度：stop() 标志最迟 30ms 被看到


# ======================================================================
# 日志（失败一律吞掉：启动画面绝不能因为它自己把程序卡死）
# ======================================================================
def _log(level: str, message: str):
    try:
        from pymodels.utils.logger import log
        getattr(log, level)("启动", "splash", message)
    except Exception:
        pass


def _log_info(message: str):
    _log("info", message)


def _log_warn(message: str):
    _log("warn", message)


def _log_err(message: str):
    _log("err", message)


# ======================================================================
# 主题字符串判定表：**只服务 shell 的主窗口 / boot-screen 配色**
# ======================================================================
# ⚠️ 本文件自己的浮窗底板已改成**固定深色**（见模块 docstring 的需求变更说明）：
#    显示路径不再读配置、也不再调用下面这个函数。它留在这里的唯一原因是
#    `desktop/shell.py` 还写着 `from .splash import _theme_is_light` —— 那条链路
#    判断的是"窗口**里面**的启动动画"该用哪套配色，与本浮窗无关，不属于本轮改动。
#    删掉它 = 把主窗口配色弄崩。
def _theme_is_light(text: str):
    """把一个 theme 配置值判成 浅色(True) / 深色(False) / 认不出来(None)

    历史：旧代码只认死字符串 `== "浅色主题"`，可配置里的 theme 值远不止这一种写法：
      · 设置页下拉框存的是规范简体（浅色主题 / 深色主题 / 跟随系统）—— 这一种以前能认；
      · GCP-AI 的 set_theme 工具（core/ai/agent_tools.py）写的是**短形式** "浅色"/"深色"；
      · 老版本 / 繁体 / 英文界面下用户存过 "浅色主題" / "Light Theme" / "dark" 等；
    上面这些以前全部走到"认不出来 → 回退深色"，于是**用户明明选了浅色，界面还是黑的**
    （当年 splash 底板跟随主题时踩的是同一个坑）。这里把能认出的浅/深写法都收进来
    （大小写、全半角、繁简、中英文、短形式），认不出来才返回 None（交给调用方按
    "跟随系统 / 兜底深色"处理）。
    """
    t = str(text or "").strip().lower()
    if not t:
        return None
    # 浅色族
    if ("浅色" in t or "淺色" in t or "light" in t or t in ("亮色", "明亮", "白色")):
        return True
    # 深色族
    if ("深色" in t or "暗色" in t or "黑色" in t or "dark" in t
            or "night" in t or t in ("夜间", "夜間")):
        return False
    # 跟随系统族（返回 None 表示"要按系统判定"，不是"认不出来"）
    if ("跟随" in t or "跟隨" in t or "follow" in t or "system" in t or "auto" in t):
        return None
    return None


# ======================================================================
# 位图准备（Pillow）
# ======================================================================
def _scaled(value: float, scale: float = 1.0) -> int:
    """把"视觉尺寸"按 DPI 缩放比换算成**物理像素**（缩放比非法时按 1.0 兜底）

    ⚠️ 分层窗口（UpdateLayeredWindow）用的是物理像素，而边距/圆角/logo 上限这些数字
       是在 100% 缩放下定的"视觉尺寸"；进程一旦是 DPI-aware（见
       native/win32.py::ensure_dpi_awareness），高 DPI 屏上就必须乘上缩放比，
       否则整个启动画面会缩水一半。
    """
    try:
        ratio = float(scale or 1.0)
    except Exception:                                   # noqa: BLE001
        ratio = 1.0
    if ratio <= 0:
        ratio = 1.0
    return max(0, int(round(float(value) * ratio)))


def _corner_radius(w: int, h: int) -> int:
    """按图片尺寸算圆角半径（比例制，别写死像素）；夹到短边一半，防止圆成圆形贴纸"""
    try:
        r = int(round(min(w, h) * _SPLASH_CORNER_RATIO))
    except Exception:                                   # noqa: BLE001
        return 0
    return max(0, min(r, _SPLASH_CORNER_MAX, min(w, h) // 2))


def _rounded_mask(w: int, h: int, radius: int):
    """生成 0~255 的圆角蒙版（L 通道）。返回 None = 不要圆角。

    ⚠️ 为什么要"2x 超采样 + 再夹一层 1x 硬边"这两步，改之前先看明白：
      ① Pillow 的 rounded_rectangle 在 1x 下圆角是**锯齿**的，而启动画面是"窗口第一眼"，
         所以先在 2x 画、再缩放回 1x 拿到平滑的 0~255 过渡；
      ② 但**缩放（LANCZOS/BILINEAR）会在完全透明的圆角外沿产生振铃/漏光**，
         让"本该是 0"的角上像素变成 1~2 之类的非零值 —— 分层窗口下就是一圈洗不掉的脏边。
         所以再用 1x 的**二值硬蒙版取 min**：凡是在圆角矩形之外的像素，alpha 一律严格 0。
         内侧仍保留 ①的平滑过渡，视觉无损，边界却是真透明。
    """
    if radius <= 0 or w <= 0 or h <= 0:
        return None
    from PIL import Image, ImageChops, ImageDraw

    def _draw(scale, filt):
        mask = Image.new("L", (w * scale, h * scale), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, w * scale - 1, h * scale - 1], radius=radius * scale, fill=255)
        return mask if scale == 1 else mask.resize((w, h), filt)

    try:
        smooth = _draw(2, Image.LANCZOS)
        hard = _draw(1, None)
        return ImageChops.darker(smooth, hard)          # 逐像素取 min：外面强制 0
    except Exception as exc:                            # noqa: BLE001
        _log_warn(f"启动画面圆角蒙版生成失败（按直角显示）: {exc}")
        return None


def _apply_corner_radius(img, radius: int):
    """把圆角**乘到图片自己的 alpha 通道**上（不新建底板、不改 RGB）

    ⚠️ 只动 alpha：圆角外的像素会被 `_premultiply_bgra()` 的 `a == 0 → BGRA 全 0` 分支
       清成完全透明，所以不会留下"原图角上的深紫像素发黑边"。
       过渡像素（0 < a < 255）走预乘分支，RGB 来自原图，也不会脏。
    """
    mask = _rounded_mask(img.width, img.height, radius)
    if mask is None:
        return img
    from PIL import ImageChops
    try:
        # multiply = a*b/255：蒙版为 0 的角外像素必然得到 0（真透明）
        img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    except Exception as exc:                            # noqa: BLE001
        _log_warn(f"启动画面圆角应用失败（按直角显示）: {exc}")
    return img


def _prepare_bitmap(icon_path: str, scale: float = 1.0):
    """把 logo 画成"**圆角半透明底板 + 居中 logo**"的 ARGB 像素，返回 (w, h, bytes)

    返回 (w, h, bytes)，且 **w/h 就是窗口尺寸**（= logo 尺寸 + 2 × 边距）。
    · 最长边超过 300 → LANCZOS 平滑缩到 300（原规格，随 DPI 放大）；
    · 底板 = 圆角矩形（`_rounded_mask`：2x 超采样 + 1x 硬边取 min ⇒ 圆角外 alpha 严格 0），
      底色**固定深色** `_SPLASH_BG_DARK`（alpha 240；本轮需求：不再跟随主题）；
    · logo **居中**贴在底板上；logo 自身四角另做圆润处理（`_apply_corner_radius`）；
    · 图片缺失/损坏 → 退回**同构**的圆角底板（中心是固定深色底、角外 alpha==0），
      保证启动画面永远有东西显示、且这条路径不抛异常；
    · `scale` = 目标显示器的 DPI 缩放比（1.0/1.25/1.5/2.0）。分层窗口的尺寸单位是
      **物理像素**，而 `_SPLASH_LOGO_MAX`/边距/圆角/兜底块这些数字是当年在 100%
      缩放下定的**视觉**尺寸；进程一旦是 DPI-aware（见 win32.ensure_dpi_awareness），
      150% 屏上就得把它们乘上缩放比，否则 180px 的 logo 在 2K/4K 屏上会小得像一颗图钉。
      默认 1.0 保持"不传参数 = 100% 缩放"的历史行为。
      ⚠️ 本轮已删掉原来的第二个位置参数 `dark`：按旧签名传参的老取证脚本
      （_devtest/ 下那几个）会失效，属预期（不在本任务写作用域，交 lead 处理）。
    """
    from PIL import Image

    try:
        ratio_in = float(scale or 1.0)
    except Exception:                                   # noqa: BLE001
        ratio_in = 1.0
    if ratio_in <= 0:
        ratio_in = 1.0
    logo_max = max(1, int(round(_SPLASH_LOGO_MAX * ratio_in)))
    margin = _scaled(_SPLASH_MARGIN, ratio_in)           # 每边的边距（物理像素）
    board_radius = _scaled(_SPLASH_RADIUS, ratio_in)     # 底板圆角半径（物理像素）
    bg_color = _SPLASH_BG_DARK           # 固定深色底板（本轮需求，见模块 docstring）

    logo = None
    if icon_path and os.path.exists(icon_path):
        try:
            logo = Image.open(icon_path).convert("RGBA")
        except Exception as exc:                        # noqa: BLE001
            _log_warn(f"启动画面图片加载异常: {exc}")
            logo = None
    else:
        _log_warn(f"启动画面图片不存在: {icon_path}")

    if logo is not None:
        w, h = logo.size
        if w > logo_max or h > logo_max:
            ratio = min(logo_max / float(w), logo_max / float(h))
            w, h = max(1, int(w * ratio)), max(1, int(h * ratio))
            logo = logo.resize((w, h), Image.LANCZOS)
        elif ratio_in > 1.0:
            # 原图比"缩放后的上限"还小（本项目 logo 就是 180×180）：高 DPI 屏上
            # 放大到它该有的物理尺寸，否则窗口只有逻辑尺寸的一半、看着像缩水了。
            target = min(logo_max, int(round(max(w, h) * ratio_in)))
            if target > max(w, h):
                grow = target / float(max(w, h))
                w, h = max(1, int(w * grow)), max(1, int(h * grow))
                logo = logo.resize((w, h), Image.LANCZOS)
    else:
        # 兜底：没有图片也照样出一块**圆角底板**（尺寸沿用旧版 220，按 DPI 放大）。
        # 中间不画 logo ⇒ 中心就是固定深色底板，结构与主路径同构（都是"底板 + 圆角"）。
        w = h = max(1, int(round(_SPLASH_FALLBACK_SIZE * ratio_in)))

    win_w, win_h = w + 2 * margin, h + 2 * margin

    # ---- 底板：圆角矩形 + 主题底色 ----
    # ⚠️ 圆角外的 alpha 必须**严格为 0**，否则分层窗口会留一圈黑边/白边（脏边）——
    #    `_rounded_mask` 的"2x 超采样 + 1x 硬边取 min"就是干这个的，别简化成直接画圆角。
    canvas = Image.new("RGBA", (win_w, win_h), (0, 0, 0, 0))
    board = Image.new("RGBA", (win_w, win_h), bg_color)
    mask = _rounded_mask(win_w, win_h, board_radius)
    if mask is None:
        canvas.paste(board, (0, 0))
    else:
        canvas.paste(board, (0, 0), mask)

    # ---- logo 居中贴上去（logo 自己的四角另做圆润处理） ----
    if logo is not None:
        logo = _apply_corner_radius(logo, _corner_radius(w, h))
        canvas.alpha_composite(logo, ((win_w - w) // 2, (win_h - h) // 2))
    return win_w, win_h, canvas.tobytes()


# ======================================================================
# 分层窗口绘制
# ======================================================================
class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


def _premultiply_bgra(raw_argb: bytes, width: int, height: int) -> bytes:
    """把 Pillow 的 RGBA 像素转成 DIB 需要的**预乘 alpha 的 BGRA**（返回新 bytes）

    ⚠️️ 三个坑，改这里之前务必看明白（都是实测踩出来的）：
      ① Pillow 的 `RGBA.tobytes()` 是 **R,G,B,A** 顺序；
      ② 而 BI_RGB 的 32bpp DIB 在内存里是 **B,G,R,A**（小端）。
         按"src[i] 当 B 用"直接拷会把红蓝通道装反（灰色看不出来、彩色 logo 会变色）。
         所以取色时 src[i+2]→B、src[i+1]→G、src[i]→R。
      ③ 分层窗口要求 **预乘 alpha**：RGB 先乘 A/255 再填，否则半透明区域会糊。
    ⚠️ `a == 0` 必须把 **B/G/R 也强制清零**：这就是"圆角外不留脏边"的关键 ——
       预乘缓冲里 alpha=0 却留着非零 RGB，某些合成路径下会显出一圈边（而且截图看不出来）。
    单独抽成函数是为了**可测**：回归脚本直接断言这段的输出，不必依赖截屏
    （截屏会被桌面动态壁纸 / 上层窗口 / BitBlt 对分层窗口的行为干扰，实测不可靠）。
    """
    n = width * height * 4
    src = raw_argb
    if len(src) < n:
        src = src + bytes(n - len(src))
    dst = bytearray(n)
    dview = memoryview(dst)
    for i in range(0, n, 4):
        a = src[i + 3]
        if a == 0:
            dview[i] = 0
            dview[i + 1] = 0
            dview[i + 2] = 0
            dview[i + 3] = 0
        elif a == 255:
            dview[i], dview[i + 1], dview[i + 2] = src[i + 2], src[i + 1], src[i]
            dview[i + 3] = 255
        else:
            dview[i] = (src[i + 2] * a) // 255            # B
            dview[i + 1] = (src[i + 1] * a) // 255        # G
            dview[i + 2] = (src[i] * a) // 255            # R
            dview[i + 3] = a
    return bytes(dst)


def _update_layered(hwnd: int, width: int, height: int, raw_argb: bytes,
                    x: int = 0, y: int = 0) -> bool:
    """把 ARGB 像素贴到分层窗口：UpdateLayeredWindow + 32bpp premultiplied DIB

    ⚠️ `x, y` 是**窗口的屏幕坐标**（UpdateLayeredWindow 的 pptDst），必须传建窗时
       算好的居中位置；不传就会被强行拉到 (0,0)（第一版就这么错，窗口跑到左上角）。
    ⚠️ 分层窗口的 32bpp 位图要求**预乘 alpha**，且通道顺序是 B,G,R,A（见
       `_premultiply_bgra` 的注释）。
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    bmi = _BITMAPINFO()
    hdr = bmi.bmiHeader
    hdr.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    hdr.biWidth = width
    hdr.biHeight = -height          # 负高度 = 自顶向下，和 Pillow 的行序一致
    hdr.biPlanes = 1
    hdr.biBitCount = 32
    hdr.biCompression = 0           # BI_RGB

    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbitmap = 0
    try:
        bits = ctypes.c_void_p()
        hbitmap = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0,
                                         ctypes.byref(bits), None, 0)
        if not hbitmap or not bits:
            return False
        gdi32.SelectObject(hdc_mem, hbitmap)

        packed = _premultiply_bgra(raw_argb, width, height)
        ctypes.memmove(bits, packed, len(packed))

        # ⚠️️ `UpdateLayeredWindow` 的 **pptDst 是"窗口新的屏幕坐标"**，不是源图偏移！
        #    第一版把 `src_pt`(0,0) 传给它 → 窗口被强行挪到屏幕左上角，
        #    建窗时算好的居中坐标被覆盖（实测 GetWindowRect 返回 (0,0)-(260,260)）。
        #    这里显式传建窗时算出的 (left, top)。
        dst_pt = _POINT(int(x), int(y))
        src_pt = _POINT(0, 0)
        size = _SIZE(width, height)
        blend = _BLENDFUNCTION(_AC_SRC_OVER, 0, 255, _AC_SRC_ALPHA)
        ok = user32.UpdateLayeredWindow(
            wintypes.HWND(hwnd), hdc_screen, ctypes.byref(dst_pt),
            ctypes.byref(size), hdc_mem, ctypes.byref(src_pt), 0,
            ctypes.byref(blend), _ULW_ALPHA)
        return bool(ok)
    finally:
        try:
            if hbitmap:
                gdi32.DeleteObject(hbitmap)
        except Exception:
            pass
        try:
            gdi32.DeleteDC(hdc_mem)
        except Exception:
            pass
        try:
            user32.ReleaseDC(None, hdc_screen)
        except Exception:
            pass


# ======================================================================
# 居中：只在"主屏工作区"里算一次，整个生命周期都用同一组物理坐标
# ======================================================================
def _splash_target_xy(win32, width: int, height: int, hwnd=None):
    """返回 ((x, y), (left, top, right, bottom))：窗口该摆的物理像素左上角 + 所用工作区。

    ⚠️ 为什么坚持用"窗口所在显示器"的工作区（hwnd 一传就用 MonitorFromWindow +
       GetMonitorInfoW），而不是老写法那句 SPI_GETWORKAREA：
         · SPI_GETWORKAREA 只给**主屏**，多屏（尤其副屏在左边、坐标是负数）时
           算出来的"中央"根本不在用户看的那块屏上；
         · GetMonitorInfoW 给的是该显示器真实的 rcWork（已扣掉任务栏），
           而且和 CreateWindowExW / UpdateLayeredWindow 用的是**同一个物理像素空间**
           （前提：调用前已经 ensure_dpi_awareness，见 _run_native 开头）。
       hwnd 还没建出来时（第一次算）退回 SPI_GETWORKAREA，也是主屏物理坐标，一致。
    ⚠️ 任何一步失败都退回 (0, 0, 宽, 高) 的"至少能看见"策略，绝不抛异常 ——
       启动画面不能因为它自己把程序卡住。
    """
    try:
        left, top, right, bottom = win32.work_area(hwnd) if hwnd else win32.work_area()
        if right <= left or bottom <= top:
            raise ValueError("work_area 返回了空矩形")
        x = int(left + ((right - left) - width) / 2)
        y = int(top + ((bottom - top) - height) / 2)
        # 窗口比工作区还大（极小屏 + 高缩放）时按左上贴住，别让居中算出负偏移
        return (max(int(left), x), max(int(top), y)), (int(left), int(top),
                                                       int(right), int(bottom))
    except Exception as exc:                            # noqa: BLE001
        _log_warn(f"启动画面居中计算失败（退回 0,0）: {exc}")
        return (0, 0), (0, 0, 0, 0)


# ======================================================================
# 控制器（对外契约与 PyQt5 版一致）
# ======================================================================
class SplashController:
    """启动画面控制器（内部 Win32 分层窗口；对外接口与旧 Qt 版逐字相同）"""

    def __init__(self, icon_path: str, duration_ms: int = 0, enabled: bool = True,
                 on_finished=None):
        self.icon_path = icon_path
        # ⚠️ `duration_ms` 本轮起**不再参与任何计时**（需求：显示时长改由主流程决定）。
        #    留着这个位置参数只是为了不改坏既有调用点与 _devtest 下的取证脚本
        #    （它们都按 `SplashController(icon, 1200, enabled=True)` 位置传参）。
        #    看到有人想把它接回 deadline 请先读模块 docstring 那段需求变更说明。
        self.duration_ms = max(0, int(duration_ms or 0))
        self.enabled = bool(enabled)
        self._on_finished = on_finished
        self._finished = threading.Event()
        self._stop_requested = threading.Event()
        self._thread = None
        self._lock = threading.RLock()
        self._fallback = False
        self._hwnd = 0
        self._class_registered = False
        # 真正 start() 的时刻（外壳只拿它写"画面顶了多久"的日志，不参与任何判定）
        self.started_at = 0.0

    # ---------- 回调挂载（本轮为"入口提前启动"新增） ----------
    def attach_finished(self, on_finished):
        """把"画面结束"回调补挂上（控制器可能在入口就 start() 了，那时还没有外壳）。

        ⚠️ 必须处理"已经结束了才来挂"的情况：启动画面被关掉/降级/秒失败时
           `_finish()` 在 `start()` 里就地跑完了，回调若只是覆盖字段就永远不会触发，
           外壳那边等着它做的事情（例如解除显示闸门）就会挂死。
           所以这里判定已结束时**立刻补发一次**（同样另起线程，和 _finish 的规矩一致）。
        """
        with self._lock:
            self._on_finished = on_finished
            already = self._finished.is_set()
        if already and callable(on_finished):
            def _call():
                try:
                    on_finished()
                except Exception as exc:                # noqa: BLE001
                    _log_warn(f"启动画面结束回调异常: {exc}")
            threading.Thread(target=_call, name="ToolsGCP-splash-done",
                             daemon=True).start()

    # ---------- 状态 ----------
    @property
    def finished(self) -> bool:
        if not self.enabled:
            return True
        return self._finished.is_set()

    def wait(self, timeout: float = None) -> bool:
        if not self.enabled:
            return True
        return self._finished.wait(timeout)

    def stop(self, timeout: float = 3.0) -> bool:
        """请求停掉启动画面并等线程收尾（退出流程必须调它）

        ⚠️ 这里**只置位标志**，不跨线程 DestroyWindow：窗口只能在创建它的线程里销毁
           （旧 Qt 版踩的正是这个坑，只是换了个实现，规则没变）。
           窗口线程在等待循环的消息泵里检查该标志（MsgWaitForMultipleObjects 粒度
           _PUMP_WAIT_MS = 30ms），最迟 30ms 后自行收尾。用户用鼠标点这块分层窗口
           产生的消息现在能被正常派发（以前不泵消息，一点就被系统判"未响应"）。
        """
        self._stop_requested.set()
        thread = self._thread
        if thread is None or not thread.is_alive():
            return True
        thread.join(timeout)
        return not thread.is_alive()

    # ---------- 启动 ----------
    def start(self) -> bool:
        """启动启动画面；返回是否真的起来了（False = 关闭/不可用，已 _finish）"""
        if not self.enabled:
            self._finish("关闭（设置里 splash_screen_enabled=False）")
            return False
        if sys.platform != "win32":
            self._fallback = True
            _log_warn("启动画面不可用（非 Windows 平台），已降级为无启动画面")
            self._finish("降级")
            return False
        try:
            import PIL  # noqa: F401  探针：缺 Pillow 就没法解码 logo
        except Exception:
            self._fallback = True
            _log_warn("启动画面不可用（缺少 Pillow），已降级为无启动画面")
            self._finish("降级")
            return False

        self._thread = threading.Thread(target=self._run, name="ToolsGCP-splash",
                                        daemon=True)
        self.started_at = time.time()
        self._thread.start()
        return True

    def _run(self):
        try:
            self._run_native()
        except Exception as exc:                        # noqa: BLE001
            _log_err(f"启动画面异常，已跳过: {exc}\n{traceback.format_exc()}")
            self._finish("异常")

    # ---------- 真正的实现 ----------
    def _run_native(self):
        """在工作线程里：定 DPI → 建分层窗口 → 贴图 → 等主流程叫停 → 本线程销毁"""
        from .native import win32

        # ⚠️⚠️ 第一件事必须是"把进程 DPI awareness 定下来"，而且必须**早于任何建窗**：
        #    pywebview 要等到 webview.start() 才 SetProcessDPIAware，而这条线程在那之前
        #    就要建窗 —— 中间那次翻转就是"画面先在中央、随后跳走"的真因
        #    （完整推导见 native/win32.py::ensure_dpi_awareness）。
        #    它和 pywebview 用的是同一个 API，所以进程的**最终状态**和以前完全一致，
        #    只是把"定下来的时刻"提前了，主窗口那套 _ui_scale / ZoomFactor 逻辑不受影响。
        dpi_note = win32.ensure_dpi_awareness()
        scale = win32.system_dpi_scale()

        # 底板固定深色（本轮需求）：贴图前**不再读用户主题、不再取证**，
        # 显示路径对配置文件零 I/O。（历史：这里曾是"读 theme → 判深浅 → 记现场日志"
        # 一整段，服务于已作废的"底板跟随主题"需求，用户要求整套删掉。）
        width, height, raw = _prepare_bitmap(self.icon_path, scale)

        # 每次用唯一类名，避免和上一次残留的注册冲突（启动画面可能开多次）
        class_name = "ToolsGCP_Splash_%d" % (int(time.time() * 1000) % 1000000)

        # 居中：**只在这里算一次**，之后建窗、贴图、显示全都复用这同一组坐标。
        # ⚠️ 绝不允许出现"已经显示了之后再搬一次"——那正是用户看到的"跳"。
        #    （唯一例外是下面显示后的**校验**：只有坐标真的不对了才纠正，且会记日志。）
        (x, y), area = _splash_target_xy(win32, width, height)
        _log_info(
            f"启动画面定位: DPI={scale:.2f}（{dpi_note}）"
            f" 主屏工作区={area} 窗口={width}x{height} → 左上=({x}, {y})")

        hinst = win32.kernel32.GetModuleHandleW(None)

        # ---- 注册窗口类（幂等；类名唯一所以每次都是新的） ----
        result = {"hwnd": 0}

        def _wndproc(hwnd, msg, wparam, lparam):
            # ⚠️ 窗口过程异常绝不能逃出去（会直接 terminate 进程），统一用守卫包
            return _wndproc_guard(_wndproc_body)(hwnd, msg, wparam, lparam)

        def _wndproc_body(hwnd, msg, wparam, lparam):
            # 分层窗口是"画上去的"，必须吃掉擦背景，否则会闪一下白底
            if msg == _WM_ERASEBKGND:
                return 1
            # 关闭请求（外部 stop 也能走这里）→ 交给等待循环处理
            if msg == _WM_CLOSE:
                self._stop_requested.set()
                return 0
            if msg == _WM_DESTROY:
                result["hwnd"] = 0
                return 0
            return win32.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        try:
            cls = win32.WNDCLASSW()
            cls.style = 0
            cls.lpfnWndProc = win32.WNDPROC(_wndproc)
            cls.cbClsExtra = 0
            cls.cbWndExtra = 0
            cls.hInstance = hinst
            cls.hIcon = None
            cls.hCursor = win32.user32.LoadCursorW(None, 32512)   # IDC_ARROW
            cls.hbrBackground = None
            cls.lpszMenuName = None
            cls.lpszClassName = class_name
            atom = win32.user32.RegisterClassW(ctypes.byref(cls))
            if not atom and win32.kernel32.GetLastError() != 1410:   # 1410 = 已存在
                _log_warn("启动画面窗口类注册失败，降级")
                self._finish("降级")
                return
            self._class_registered = True
        except Exception as exc:                        # noqa: BLE001
            _log_warn(f"启动画面窗口类注册异常 {exc}，降级")
            self._finish("降级")
            return

        # ---- 建窗（无边框 + 置顶 + 分层 + 工具栏窗） ----
        ex = _WS_EX_LAYERED | _WS_EX_TOOLWINDOW | _WS_EX_TOPMOST
        try:
            hwnd = win32.user32.CreateWindowExW(
                ex, class_name, "ToolsGCP", _WS_POPUP, x, y, width, height,
                None, None, hinst, None)
        except Exception as exc:                        # noqa: BLE001
            _log_err(f"启动画面建窗异常: {exc}")
            self._finish("异常")
            return
        if not hwnd:
            _log_warn(f"启动画面建窗失败（error={win32.kernel32.GetLastError()}），降级")
            self._finish("降级")
            return
        self._hwnd = hwnd
        result["hwnd"] = hwnd

        # ---- 贴图（失败就降级，绝不留一个空白透明窗） ----
        # ⚠️ 必须把居中坐标 (x, y) 一起传进去：UpdateLayeredWindow 会用它设置窗口位置
        if not _update_layered(hwnd, width, height, raw, x, y):
            _log_warn("启动画面贴图失败，降级")
            self._close_window(win32, hwnd)
            self._finish("降级")
            return

        # ---- 显示**之前**做一次坐标自校验（这一步是"看得见就不跳"的关键） ----
        # ⚠️ 顺序很重要：建窗(不可见) → UpdateLayeredWindow 定位并贴图(仍不可见)
        #    → 这里读实际矩形对一遍 → 有偏差就 SetWindowPos 纠正 → **最后**才 ShowWindow。
        #    这样即使某个环境（奇怪的显卡驱动/RDP 会话/多屏混合缩放）把坐标改了含义，
        #    纠正也发生在窗口对用户可见之前，用户永远看不到"先中间再跳走"。
        #    反过来如果放在 ShowWindow 之后再纠，那就等于亲手制造用户报的那个跳变。
        try:
            got = win32.rect_of(hwnd)
            gx, gy, gr, gb = got
            gw, gh = gr - gx, gb - gy
            # 容差 2px：DWM 在个别缩放档上会有 1px 的取整，不值得为它搬一次窗
            if abs(gx - x) > 2 or abs(gy - y) > 2 or abs(gw - width) > 2 or abs(gh - height) > 2:
                _log_warn(
                    f"启动画面坐标被系统改过（期望 左上=({x}, {y}) 尺寸={width}x{height}，"
                    f"实测={got}）→ 显示前纠正回目标位置")
                # SWP_NOZORDER|SWP_NOACTIVATE：保持置顶与不抢焦点，不动其它属性
                win32.user32.SetWindowPos(wintypes.HWND(hwnd), 0, int(x), int(y),
                                          int(width), int(height), 0x0040 | 0x0010)
                _log_info(f"启动画面纠正后实际矩形: {win32.rect_of(hwnd)}")
        except Exception as exc:                          # noqa: BLE001
            # 校验失败绝不能挡住显示：顶多少一层保险，主流程照常
            _log_warn(f"启动画面坐标校验跳过（不影响显示）: {exc}")

        try:
            # SW_SHOWNOACTIVATE：启动画面不抢焦点（原版 Qt.Tool 的语义）
            win32.user32.ShowWindow(wintypes.HWND(hwnd), _SW_SHOWNOACTIVATE)
            win32.user32.UpdateWindow(wintypes.HWND(hwnd))
        except Exception:
            pass
        _log_info(f"启动画面窗口尺寸: {width}x{height}"
                  f"（独立 splash 窗口，主窗口 1280x880 不参与）"
                  f" 显示后矩形={win32.rect_of(hwnd) if hasattr(win32, 'rect_of') else 'n/a'}")

        # ---- 等"主流程叫我关"或"赖屏上限到"：**消息泵**，不是 sleep 轮询 ----
        # ⚠️⚠️ 本轮需求核心：显示时长**不再由 duration 决定**，而是"程序什么时候
        #    把我显示出来，就一直显示到主流程启动完成叫我消失"。所以这里只等三件事：
        #      ① stop_requested 置位（shell 在主窗口显示之后调 stop()，或 WM_CLOSE
        #         到达窗口过程）→ 正常收尾；
        #      ② result["hwnd"] 归零（窗口已被销毁）→ 收尾；
        #      ③ 安全网超时 SPLASH_HARD_TIMEOUT_MS（主流程出了意外没人叫我关）→
        #         自毁，绝不死赖在桌面上。三条退出条件与旧写法一一对应、语义不变。
        # ⚠️⚠️ 为什么必须是消息泵（修"鼠标一碰就未响应、再点直接关闭"）：
        #    旧写法整段只有 time.sleep(0.03) 轮询，这条线程从不取消息。分层窗口被
        #    鼠标碰到 / 按下时，系统要**跨线程调用本窗口的 WndProc**（SendMessage
        #    语义）；本线程不泵消息，调用方就一直阻塞 → 窗口被系统标记"未响应"，
        #    用户再点一下就被引导走到关闭/销毁路径 —— 这正是用户报的现象。
        #    PeekMessageW + TranslateMessage + DispatchMessageW 才是 WndProc 被
        #    正常执行的唯一前提；空闲时用 MsgWaitForMultipleObjects(0, None, FALSE,
        #    30, QS_ALLINPUT) 等"下一条消息或 30ms"，既不忙等、也不吃 CPU
        #    （写法与 native/traymenu.py 的托盘菜单泵一致，是仓库内成熟路子）。
        deadline = time.monotonic() + SPLASH_HARD_TIMEOUT_MS / 1000.0
        msg = wintypes.MSG()
        pump_errors = 0
        while time.monotonic() < deadline:
            if self._stop_requested.is_set() or not result["hwnd"]:
                break
            try:
                # 把队列里已有的消息全部消化干净（含跨线程发来的鼠标/窗口消息）
                while win32.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0,
                                                _PM_REMOVE):
                    if msg.message == _WM_QUIT:
                        # 队列里出现退出消息：按"窗口即将消失"处理，走统一收尾
                        result["hwnd"] = 0
                        break
                    win32.user32.TranslateMessage(ctypes.byref(msg))
                    win32.user32.DispatchMessageW(ctypes.byref(msg))
                if self._stop_requested.is_set() or not result["hwnd"]:
                    break
                # 空闲：最多睡 _PUMP_WAIT_MS，期间**任何**消息立即唤醒（不忙等）。
                # 0 个句柄 → 正常只会返回 WAIT_TIMEOUT(258) 或 WAIT_OBJECT_0(0，
                # 表示已有消息)；WAIT_FAILED(-1) 时退回短睡，防止调用失败变空转。
                r = win32.user32.MsgWaitForMultipleObjects(
                    0, None, False, _PUMP_WAIT_MS, _QS_ALLINPUT)
                if r is None or int(r) in (-1, _WAIT_FAILED):
                    time.sleep(_PUMP_WAIT_MS / 1000.0)
            except Exception as exc:                    # noqa: BLE001
                # 泵本身出异常不能带走线程：短睡继续，但连续失败到一定次数就记一条
                # warn（说明这条线程的消息循环已经废了，窗口会再次变得"无响应"，
                # 让日志里能看到，而不是永远静默）。
                pump_errors += 1
                if pump_errors == 1 or pump_errors % 100 == 0:
                    _log_warn(f"启动画面消息泵异常（第 {pump_errors} 次，降级短睡）: {exc}")
                time.sleep(_PUMP_WAIT_MS / 1000.0)

        if self._stop_requested.is_set():
            reason = "被要求退出（主流程启动完成）"
        elif not result["hwnd"]:
            reason = "窗口已被销毁"
        else:
            reason = f"赖屏上限 {SPLASH_HARD_TIMEOUT_MS}ms 到（主流程没叫我关，安全兜底）"
            _log_warn(f"启动画面未被主流程关闭，按上限自毁：{reason}")
        self._finish(reason)

        # ⚠️ 销毁必须在**建窗这条线程**上（跨线程 DestroyWindow 是未定义行为）
        self._close_window(win32, hwnd)

    def _close_window(self, win32, hwnd):
        try:
            win32.user32.DestroyWindow(wintypes.HWND(hwnd))
        except Exception as exc:                        # noqa: BLE001
            _log_warn(f"启动画面窗口销毁异常: {exc}")
        finally:
            self._hwnd = 0

    def _finish(self, reason: str):
        """标记结束 + 回调（**回调必须离开窗口线程**再执行）

        ⚠️⚠️ 回调会去 show()/install() 主窗口（WinForms 对象）；从窗口线程直接驱动它们
           会在退出时留下跨线程 GUI 状态残留（旧 Qt 版实测 6/6 崩 0xC0000005）。
           所以统一另起一条普通线程去调 —— 这条规则换实现后依然适用，别改回去。
        """
        with self._lock:
            if self._finished.is_set():
                return
            self._finished.set()
        _log_info(f"启动画面结束：{reason}")
        callback = self._on_finished
        if not callable(callback):
            return

        def _call():
            try:
                callback()
            except Exception as exc:                    # noqa: BLE001
                _log_warn(f"启动画面结束回调异常: {exc}")

        threading.Thread(target=_call, name="ToolsGCP-splash-done", daemon=True).start()


def _wndproc_guard(func):
    """窗口过程守卫：异常绝不能逃出 WndProc（逃出去会直接 terminate 整个进程）

    直接复用 `desktop/native/win32.py` 里那套（它已经处理好日志），
    这里只是把 import 挪到函数内，避免模块加载期就依赖 win32。
    """
    from .native.win32 import wndproc_guard as _guard
    return _guard(func)
