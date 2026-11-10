# win-splash-r2 · 启动动画第 2 轮取证与修复报告

- 任务：task-7（浅色背景仍深色 / 居中+UI 叠加 / 去底板 + logo 四角圆润）
- 执行人：splash-r2
- 时间：2026-11-07 16:27 → 17:30（Asia/Shanghai）
- 写作用域：`.ToolsGCP/desktop/splash.py`、`项目资料-文档与开发测试/_devtest/`（**未动 win32.py**，本轮不需要）
- 本轮用户明确允许真机弹窗 + 截屏，已按许可真机取证；测完窗口与进程已收干净（见 §4 收尾证据）。

产物目录：`项目资料-文档与开发测试/_tmp-ai-test/splash-r2/`
（`probe.json` 汇总、`findings.txt` 全量输出、`base.png` / `splash.png` /
`splash_corner_crop.png` 截屏、`windows_*.txt` 窗口清单、`app_*.png` 时间轴截屏）

取证脚本：
- `项目资料-文档与开发测试/_devtest/probe_splash_r2.py`（真机：单起 splash + 截屏采样 + 枚举窗口矩形/Z 序/样式；`--full` 真跑整个程序到 12s）
- `项目资料-文档与开发测试/_devtest/probe_capture_artifact.py`（对照实验：证明"截屏里角外是黑的"是抓取伪影，不是渲染 bug）
- `项目资料-文档与开发测试/_devtest/test_splash_theme.py`（回归，已按新规格改写 + 新增第 [4] 段预乘缓冲断言）

---

## 0. 一句话结论

| 项 | 结论 |
|---|---|
| ③ 去底板 + 四角圆润 | **已修复**（改 splash.py），离屏 + 真机双重验证 |
| ① 浅色仍深色 | **原生 splash 不是元凶**（真机日志证明它走的就是浅色分支）。用户说的"程序窗口**中的**启动加载画面"是 **webui 的 `.boot-screen` 启动遮罩**，它变黑的根因有两条，都在我的写作用域之外（`webui/index.html` 首帧脚本 + `shell.py` 的 `background_color`）→ 已带证据 send_message 给 lead |
| ② 没在中央 + UI 叠加 | 同样**不在 shell.py 的启动时序**（splash 与主窗口实测从不重叠）。"叠加"和"不居中"都发生在**主窗口内部**：`.boot-screen` 是透明层，盖在"已经切好的真实页面 + 资源加载遮罩"之上，且它居中于 `.content` 而不是窗口 → 水平/垂直各偏 24px |

> 补充：③ 顺带**消掉了原生 splash 的全部主题相关像素**（去底板后深/浅两次出图 raw 字节完全相同），
> 所以"如果用户指的是那个浮窗"，深色背景这个观感问题已经随 ③ 一并消失；
> 剩下真正需要 lead 协调的是 **webui `.boot-screen` 那一层**（§2、§3.3）。

---

## 1. ③ 去掉底板 + logo 四角圆润（已完成）

### 1.1 改了什么（只改 `desktop/splash.py`）

| 位置 | 改动 |
|---|---|
| `_prepare_bitmap()` | **删掉整块底板绘制**（不再有 `canvas` + `bg` 矩形 + `paste(bg, mask)`）。返回值 `w,h` 现在**就是 logo 尺寸**，窗口尺寸 = 位图尺寸 |
| `_SPLASH_MARGIN` | 80 → **0**（去底板 = 不再有边距；保留常量名只为兼容旧测试引用） |
| 新增 `_corner_radius(w,h)` | 半径按图片短边**比例**算（`_SPLASH_CORNER_RATIO = 0.16`），180px → **29px**；上限 `_SPLASH_CORNER_MAX = 48`，并夹到短边一半（防止大图标圆成圆形贴纸） |
| 新增 `_rounded_mask(w,h,r)` | 圆角蒙版：2x LANCZOS 超采样拿平滑过渡，**再与 1x 二值硬蒙版 `ImageChops.darker()` 取逐像素 min** |
| 新增 `_apply_corner_radius(img,r)` | 把圆角**乘到 logo 自己的 alpha 通道**上（`ImageChops.multiply(A, mask)`），不动 RGB、不新建背景层 |
| 新增 `_premultiply_bgra()` | 把原来内联在 `_update_layered` 里的那段通道/预乘循环**抽成纯函数**（逻辑不变），目的是**可测** —— 见 §1.3 |
| 兜底路径 | 图片缺失/损坏 → 仍然出一个 **220×220 的带圆角纯色块**（深浅跟随主题、alpha 240），不抛异常 |
| `_SPLASH_BG_*` | 保留，但**只剩兜底块一个用途**（注释已写明：正常路径不再有任何背景像素，所以"浅色看到深色"不可能再由这两个常量造成） |

### 1.2 为什么圆角外一定"真透明"（这是本轮最容易出错的地方）

分层窗口 `UpdateLayeredWindow` 吃的是 **premultiplied BGRA**，脏边有两个来源，我分别堵掉了：

1. **LANCZOS 振铃/漏光**：超采样蒙版缩回 1x 时，"本该是 0"的角外像素会变成 1~2 之类的非零值 → 一圈洗不掉的淡边。
   → 对策：`_rounded_mask()` 用 1x 的**二值硬蒙版**与 2x 平滑蒙版取 `darker()`（逐像素 min）。圆角外 alpha **严格 0**，内侧仍保留平滑过渡。
2. **"alpha=0 但 RGB 留着原图颜色"**：原图角上是深紫 (95,83,242)，如果只清 alpha 不清 RGB，预乘缓冲里就是 `(242,84,95,0)` —— 某些合成路径会显出边。
   → 对策：`_premultiply_bgra()` 的 `a == 0` 分支把 **B/G/R/A 四个字节全部写 0**。

实测证据（`test_splash_theme.py` 第 [4] 段，**全图扫描**而非只查 4 个点）：

```
OK  圆角外 4 个像素 BGRA 全 0                     {'TL': (0,0,0,0), 'TR': (0,0,0,0), 'BL': (0,0,0,0), 'BR': (0,0,0,0)}
OK  全图所有 alpha==0 的像素 BGRA 都是 (0,0,0,0)   0 个违规
OK  中心 = logo 白心 (255,255,255,255)
OK  非灰像素 R/B 没有被装反    src RGBA=(95,84,242,255) → packed BGRA=(242,84,95,255)
OK  兜底块 alpha=240 预乘 = 通道×240/255          got=(232,229,228,240) want=(232,229,228,240)
```

离屏位图规格（第 [3] 段）：

```
OK  窗口尺寸 == logo 尺寸（底板和 80px 边距已去掉）      180x180 vs logo (180,180)
OK  圆角半径按图片比例算且不为 0（180px → 29px 量级）    29
OK  四个角 alpha == 0                                   [(95,83,242,0),(83,109,254,0),(106,61,232,0),(94,87,243,0)]
OK  角外沿邻近像素也全为 alpha==0（振铃没有漏光）        前 6 个 alpha 全 0
OK  中心仍是 logo 自己的像素（没被底色覆盖）             splash=(255,255,255,255) logo=(255,255,255,255)
OK  四边中点仍是 logo 像素、alpha=255（只裁角、没裁边）  [(103,67,235,255),(86,102,251,255)]
OK  透明像素只出现在圆角处且边缘有平滑过渡              alpha0=756  alpha中间值=244  总像素=32400
OK  深浅两次出图 raw 字节完全相同                        180x180 vs 180x180
OK  图片缺失 → 220x220 圆角纯色块，角 alpha=0、中心 (243,244,247,240)
OK  图片损坏 → 同上（不抛异常）
OK  兜底块在深色主题下用 (28,28,28,240)
```

真机侧（`probe_splash_r2.py`，用户真实配置、不改 DATA_DIR）：

```
离屏位图 180x180 圆角半径=29
窗口矩形时间轴：共 388 帧，首帧=(870,426,1050,606) 末帧=(870,426,1050,606) 不同帧数=1
OK  窗口尺寸 == 位图尺寸（80px 边距的底板真的没了）   (180,180) vs (180,180)
OK  中心是 logo 自己的像素（白心）                    (255,255,255,255)
OK  上边中点是 logo 蓝紫像素（不是底板灰阶）          (87,101,250,255)
OK  紧贴窗口边缘的点是 logo 自己的像素（没有残留底板色带） [(103,68,235),(86,102,251),(102,69,235)]
OK  四角内像素不是黑边/白边                            {'TL':(4,4,4),'TR':(78,63,54),'BL':(118,77,50),'BR':(168,142,122)}
```

目视复核图：`_tmp-ai-test/splash-r2/splash_corner_crop.png`（放大 2x 的 splash 裁剪）——
蓝紫 logo 四角圆润、边缘平滑、无可见边界线。

### 1.3 为什么不能只靠截屏证明"透明"（踩过的坑，已写进脚本注释）

第一次真机跑，splash 四角截屏**全是纯黑 (0,0,0)**，看着像"脏边"。做对照实验
（`probe_capture_artifact.py`，同一坐标连抓 5 张：splash 前 / 中(带 CAPTUREBLT) / 中(不带) / 后 / 后再一张）后确认：

- **是抓取伪影 + 背景在变**，不是渲染 bug：splash 销毁后同一坐标变成 (230,242,233)；
- 本机背景**是动态的**（实测用户 Chrome 正在全屏放 bilibili 视频，`Chrome_WidgetWin_1 rect=(-8,-8,1928,1040)`），
  所以"弹前 vs 弹中"比同一坐标 L1 能差到 202，用它当判据必然误报。

→ 所以脚本里把硬判据换成 **`_premultiply_bgra()` 的输出断言**（那才是真正交给分层窗口的字节，
确定性、可重复），截屏的"角内 vs 角外 L1"降级为**仅供参考、不计入失败**。
`_update_layered` 也因此改成调用抽出来的函数 —— 避免"内联循环"和"被测函数"两处不一致。

---

## 2. ① 浅色主题下"启动加载画面背景仍是深色"

### 2.1 先排除原生 splash（真机日志是决定性证据）

我在 `_run_native()` 里加了现场取证日志（新增 `_theme_diagnostics()`，只读、绝不抛），
真机跑出来的原文：

```
[启动|splash] 启动画面底色: 浅色（跟随设置里的 theme） theme='浅色主题' light=True
              DATA_DIR=C:\Users\Administrator\.ToolsGCP\config cfg_exists=True 圆角半径=29
```

用户上一次**真实启动**（14:24 那次，`%USERPROFILE%\.ToolsGCP\logs\system_log.log`）：

```
14:24:24.058 [启动|splash] 启动画面底色: 浅色（跟随设置里的 theme）
14:24:24.104 [启动|splash] 启动画面窗口尺寸: 260x260（独立 splash 窗口，主窗口 1280x880 不参与）
14:24:26.116 [启动|splash] 启动画面结束：播放完成
```

逐项核对 lead 列的排查方向：

| 排查方向 | 实测结论 |
|---|---|
| splash 线程读到的 DATA_DIR 是不是当前真实数据根 | **是**。`DATA_DIR=C:\Users\Administrator\.ToolsGCP\config`，与 `constants.DATA_DIR` 同一值；指针文件 `%USERPROFILE%\ToolsGCP.json` 的 `data_root` 也指向这里；`cfg_exists=True`。没有"import 期旧值/迁移时机"问题 |
| 是不是根本没走到浅色分支 | **走到了**。`theme_raw='浅色主题'` → `_theme_is_light=True` → `dark=False` |
| `_prepare_bitmap(dark=False)` 算错 | 没算错（上一轮已证 (243,244,247,240)）；**本轮去底板后，深浅两次出图 raw 字节完全相同**，正常路径根本不再产生背景像素 |
| `_update_layered` 的 premultiplied BGRA 在浅色底上算错 | 没算错。§1.2 的全图断言 + 通道装反断言 + 预乘值断言全过 |
| alpha=240 透出底下的深色主窗口/壁纸 | **这条成立，但方向反了**：splash 是 TOPMOST 分层窗、在**最上层**（实测 z0，主窗口还没出现）。透出的是桌面，不是"深色主窗口" |

→ **原生 splash 不是 ① 的元凶。** 用户原话说的是"程序窗口**中的**启动加载画面" —— 那是 webui 里的 `.boot-screen` 启动遮罩（`index.html:291`，logo + "ToolsGCP" + 进度条 + `bootText`），不是那个 180px 的小浮窗。

### 2.2 `.boot-screen` 为什么是深色（两条独立成因，都在我的写作用域外）

`.boot-screen` 自己是 `background: transparent`（`overlays.css:122`），所以用户看到的"背景"= 它背后那层页面的底色。有两条路把它变成深色：

**成因 A（主因）：首帧主题判定用的是 localStorage + 系统主题，而 localStorage 每次启动必然是空的。**

`index.html:18-31` 的首帧脚本：

```js
var saved = localStorage.getItem('toolsgcp.theme');
dark = saved ? saved === 'dark'
  : (!window.matchMedia || window.matchMedia('(prefers-color-scheme: dark)').matches);
root.setAttribute('data-theme', dark ? 'dark' : 'light');
root.style.background = dark ? '#1C1C1C' : '#F3F4F7';
```

- `localStorage['toolsgcp.theme']` 是 `applyAppearance()`（`app.js:864-865`）写的，**但它在 boot 里要到 `loadSettings()`（`app.js:1517`）之后才跑**，首帧拿不到；
- 更要命的是 pywebview **默认 `private_mode=True`**（`webview/__init__.py:177`），本项目 `shell.py` / `ToolsGCP.pyw` **从未传过 `private_mode` 或 `storage_path`**（grep 全仓库无命中）。于是：
  - `winforms.py:757` → `cache_dir = tempfile.TemporaryDirectory().name`（每次都是**全新临时目录**）
  - `edgechromium.py:81` → `props.set_IsInPrivateModeEnabled(True)`
  - → **localStorage 永远不落地**，每次启动首帧都走 `matchMedia` 那条 fallback；
- 本机 Windows 应用主题：`HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\AppsUseLightTheme = 0`（实测读取），项目自己的 `detect_system_theme()` 也返回 **`深色主题`**。Chromium 的 `prefers-color-scheme` 在 Windows 上正是跟随这个值。

→ **结论：只要用户把 Windows 应用模式设为深色（本机就是），而软件内主题选"浅色主题"，每次启动的首帧就必然是 `data-theme="dark"` + `background:#1C1C1C`，而这段时间盖在上面的正是 `.boot-screen`。** 这与"上一轮把算色改对了、用户却仍然看到深色"完全吻合 —— 因为改的是 splash.py 的算色，而用户看的是 webui 首帧。

真正的浅色要等 `boot()` → `loadSettings()` → `applyAppearance()`（`app.js` 的 `boot()` 里 `setStep('settings')` 紧接 `await loadSettings()`；`loadSettings()` 末尾调 `applyAppearance()`）才切过来，日志实测在 **t≈3.2s**（`[boot] step=settings`），而窗口 show 在 **t≈3.3s**（`显示自检: 可见=True`）—— 两者只差 ~70ms，**WebView2 的合成表面在这一刻未必已经刷成浅色**，用户第一眼看到的就是那层深色。

**成因 B（叠加因素）：主窗口自己的底色写死深色。**

`shell.py:459`：`background_color="#1C1C1C"`。pywebview 把它同时写成 WinForms 的 `Form.BackColor` 和 WebView2 的 `DefaultBackgroundColor`（那行注释自己就写明了）。页面内容合成出来之前/之下露出的就是这层 **#1C1C1C**。浅色主题下它就是"窗口里那块深色背景"。

**修法建议（不在我的作用域，已发 lead）**：
1. 首帧脚本改成"先问后端要主题"不现实（bridge 还没 ready），可行的是 **`.boot-screen` 自己带一层不透明/半透明底色**，并在 `applyAppearance()` 之前用 `matchMedia` 之外的信号兜底；更彻底的做法是让 `index.html` 的首帧脚本读一个**由后端注入的模板变量**（webhost 是 Flask，`/` 路由完全可以把 `settings.theme` 直接渲染进 HTML，绕开 localStorage）；
2. 或者：`webview.start(..., private_mode=False)` / `storage_path=<数据根>/webview_profile`，让 localStorage 真正持久化（顺带还能修好其它依赖 localStorage 的首帧状态）；
3. `background_color` 按主题取 `#F3F4F7` / `#1C1C1C`（和 `frame.apply_dark()` 已有的"窗口底色刷新"统一）。

---

## 3. ② "并未在中央 + UI 叠加"

### 3.1 splash 本身：单独一个、第一帧就居中、没有第二个 splash

真机实测（`probe_splash_r2.py`，用户真实配置）：

```
== 窗口清单 @splash（EnumWindows 顺序 = Z 序）==
  [z0] ToolsGCP_Splash_774175  标题='ToolsGCP'  rect=(870,426,1050,606) size=(180,180)
       center=(960,516) visible=True layered=True topmost=True tool=True
OK  屏幕上 ToolsGCP_Splash* 窗口只有一个
OK  stop() 之后 splash 窗口已销毁（无残留）
OK  第一帧就居中（中心 == 工作区中心 ±2px）   差=(0.0,0.0)
OK  整段播放没有位置跳变（388 帧矩形全部一致） 1 种矩形
    work_area=(0,0,1920,1032) → 工作区中心 (960,516)；splash 中心 (960,516) —— 分毫不差
```

（去底板前是 260×260，中心同样是 (960,516)；上一轮 win-visual 记的 (830,386,1090,646) 也是同一中心，只是尺寸不同。）

### 3.2 "叠加"不是 splash × 主窗口，主窗口时序也没问题

按 lead 给的日志时间轴 + 我这轮的实测：

```
t=0     splash 线程起            （splash_screen_duration=2）
t≈0.8   splash 可见、居中         实测 t0.8 / t1.2 两次采样：splash=1 个，本进程主窗口=0 个
t=2.0   splash 自己结束           日志：14:24:26.116 启动画面结束：播放完成
t≈3.28  mark_frontend_ready → _try_show → 显示自检 可见=True   日志：14:24:27.248
```

- 采样点里 **splash 与主窗口从未同时可见**（`overlap_tags = []`）；
- 主窗口几何日志：`窗口矩形=(320,76)-(1600,956)`，1280×880，中心 (960,516) = 工作区中心 → **主窗口也是正居中**。

→ **② 的根因不在 `shell.py` 的启动时序，我没有需要 lead 协调的 shell.py 改动**（我也确实一行没动它）。

### 3.3 真正的"叠加 + 不居中"在主窗口内部（webui 布局）

用户看到的"UI 叠在一起、并不在中央"，是**同一个窗口里的两层 UI 同时可见**：

1. `.boot-screen`（`index.html:291`，logo + 标题 + 进度条 + `bootText`）—— `background: transparent`、`pointer-events: none`，**它是透明的**，所以底下的东西全部透出来；
2. 它下面**已经是真实页面**了 —— `continueBoot()` 在撤启动页**之前**就执行了 `page.value = 'search'`（`app.js` 里那段"起始页/启动页已挪到资源库加载之前"），搜索页的骨架/空白列表就长在 `.content` 里。

顺序上（`app.js:8972-8973`）是 `setStep('render'); booting.value = false;` **先**撤启动页，
**然后**才 `resourceLoading.value = true` 亮"正在加载资源库…"那块页面内遮罩 —— 这两块**不严格重叠**，
但窗口显示（t≈3.3s）到 `booting=false` 之间那段时间，用户看到的就是
**透明的启动 UI 直接压在已经切好的搜索页骨架上**（启动 UI 没有自己的底，页面元素从它缝隙里透出来）
= 用户说的"ui叠加在一起"。

（对照：`overlays.css:120-122` 的注释写明这是**上一轮按需求故意改成透明**的 ——
"背景透明：用户要能看见底下的界面轮廓，不能像'弹了个窗'"。
也就是说"透明 + 底下有页面"正是那条需求的直接副作用；而它同时让 §2 成因 A 的那层深色底**露了出来**。）

而"并未在中央"是**几何**问题，可算出来：`.boot-screen` 是 `position:absolute; inset:0`，挂在 `<main class="content">` 里（`base.css:131`），所以它居中于**内容盒**而不是窗口：

```
窗口 1280×880（逻辑）
.titlebar  height: var(--tb-height)  = 48px        (variables.css:92)
.nav-rail  flex: 0 0 var(--nav-collapsed) = 48px    (variables.css:97 / base.css:130)
→ .content 左边界 x=48、上边界 y=48
→ 内容盒中心 = (48 + (1280-48)/2, 48 + (880-48)/2) = (664, 464)
→ 窗口中心   = (640, 440)
→ 启动 UI 比窗口中心 **偏右 24px、偏下 24px**
（导航展开时 `.nav` 是 absolute，不额外挤压布局，所以偏移量不变；
  全屏/最大化下 `.content` 上边界归 0，偏移会变成只剩 +24px 水平 —— 更"歪"）
```

那 24px 在 1280 宽的窗口里不算大，但因为 `.boot-screen` 是**透明**的、底下同时有页面 + 加载遮罩在动，
视觉参照一多，"没在正中"就被放大成明显的观感问题。

**修法建议（`webui/*` 不在我的作用域）**：
- 要么让 `.boot-screen` 覆盖**整窗**（`position: fixed; inset: 0`）而不是只覆盖 `.content`，几何上就与窗口同心；
- 要么在 boot 期间**不要同时**渲染真实页面与 `resourceLoading`（撤遮罩的时机与 `page.value` 的切换二选一），消除"三层同显"；
- 要么给 `.boot-screen` 一层与主题一致的半透明底（顺带解决 §2 成因 A 的观感）。

---

## 4. 验证与收尾

```bash
python -m compileall -q ".ToolsGCP/desktop"                      # OK
python "项目资料-文档与开发测试/_devtest/test_splash_theme.py"     # 全部通过 OK（exit 0，59 行 0 FAIL）
python "项目资料-文档与开发测试/_devtest/probe_splash_r2.py"       # 真机 A+C 段（15 项检查全过）
python "项目资料-文档与开发测试/_devtest/probe_splash_live.py"     # 离屏（ALL OK）
python "项目资料-文档与开发测试/_devtest/probe_splash_real.py"     # 真机（结果：全部通过）
python "项目资料-文档与开发测试/_devtest/probe_capture_artifact.py" # 截屏伪影对照
```

### 4.0 顺手修了两个"断言过期"的旧脚本（都在我的写作用域 `_devtest/` 内）

上一轮 win-visual 留下的两个脚本断言的是**底板规格**，去底板后必然误报，已按新规格更新：

| 脚本 | 原来的断言（现在必然 FAIL） | 改成 |
|---|---|---|
| `probe_splash_live.py` | "浅色位图背景像素 = #F3F4F7""alpha 仍是 240""目标尺寸 260x260" | 窗口尺寸 == logo 尺寸(180×180)、四角 alpha 全 0、中心 = logo 原像素、**深浅两次出图字节完全相同**、兜底块仍跟随主题(243,244,247,240) 且角 alpha=0；居中计算改用真实位图尺寸 |
| `probe_splash_real.py` | "窗口内·背景(左内20px) R,G,B 都 > 200 才算浅色" | 该点在**logo 自己的像素**上（蓝紫底 R/G 本来就 < 200），判据改为"不是底板灰阶 R=G=B，而是 logo 的彩色像素"；并写明"截屏不能用来证明角外透明"，把确定性判据指向 `_premultiply_bgra()` |

更新后两个脚本都跑通（`ALL OK` / `结果：全部通过`），实测值：
```
窗口内·左边20px = #6547EC (101,71,236)   ← logo 蓝紫底
窗口内·上边20px = #5861F8 (88,97,248)    ← logo 蓝紫底
窗口中心        = #FFFFFF (255,255,255)  ← logo 白心
四角 alpha==0   [0,0,0,0]
首帧 rect=(870,426,1050,606) 481 次采样只有 1 种矩形（无跳变）
窗口尺寸==位图尺寸 180x180
```
（注意 `窗口外(左20px) = #000000` —— 这就是 §1.3 说的 BitBlt 抓分层窗口的伪影，
`probe_capture_artifact.py` 的对照实验已证明它不代表渲染有问题。）

- `test_splash_theme.py` 第 [1][2] 段（主题选择 + 回退不抛 + 只读不写）**未回归**，全部照旧通过；
  第 [3] 段已按"去底板"的新规格重写（原来断言"窗口 = logo+80 边距""顶部正中像素=底色"在新设计下已不成立），
  并新增第 [4] 段预乘缓冲断言。
- 窗口/进程收尾：`OK 测完没有残留的 ToolsGCP 窗口`；`stop()` 后 splash 窗口已销毁；
  `tasklist` 判活确认子进程已退出。

### 4.1 本轮的环境限制（如实说明，避免结论被过度解读）

`probe_splash_r2.py --full`（真跑整个 `ToolsGCP.pyw`）**在我这个沙箱里跑不完**：
子进程继承沙箱限制，`pythonnet` 初始化时被拒，pywebview 直接起不来 ——

```
File "D:\Python3.13.1\Lib\site-packages\webview\platforms\winforms.py", line 17, in <module>
    import clr
RuntimeError: Failed to initialize Python.Runtime.dll
内部：System.ComponentModel.Win32Exception: 拒绝访问
      at Python.Runtime.Platform.WindowsLoader.GetAllModules()
```

（lead 观察到"16:5x 那几次跑一条日志都没落盘"就是这个：进程在 `webview.start()` 处抛异常早退，
t=1.6s 退出码 0xE0434352，根本没走到 boot。**不是产品 bug，是我这边的沙箱**。我没有再尝试绕开沙箱。）

因此：
- **§1（③）与 §3.1（splash 居中/单窗/无跳变）**：由我自己真机跑 `SplashController` 取证，**实测数据**；
- **§3.2 的主窗口时间轴**：来自 lead 提供的真实日志 + 我脚本采到的 splash 侧数据（两者一致）；
  主窗口内部的像素我**没能**真机抓到；
- **§2 / §3.3 的 webui 侧根因**：由 `index.html` / `app.js` / `overlays.css` / `base.css` 源码 +
  pywebview 库源码（`private_mode` 默认值、`init_storage()`、`IsInPrivateModeEnabled`）+
  本机注册表 `AppsUseLightTheme=0` + `detect_system_theme()='深色主题'` +
  `%APPDATA%\pywebview` 与 `%LOCALAPPDATA%\pywebview` **均不存在**（实测）推出，
  证据链闭合，但"用户眼睛看到的深色"这一步我**没有截图**（沙箱起不了 WebView2）。
  → 需要一张真机截图定性的话，请 lead 或用户在**非沙箱**环境跑一次
  `python "项目资料-文档与开发测试/_devtest/probe_splash_r2.py" --full`，
  产物在 `_tmp-ai-test/splash-r2/app_t*.png`。
