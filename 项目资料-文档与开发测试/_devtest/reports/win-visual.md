# 工作流 B · win-visual（启动画面 + 托盘菜单）—— Lead 接手完成

> 原派给 win-visual 的 teammate 因 2-child 并发上限中断、未落盘任何改动，由 Lead 接手。
> 全程**不弹窗**（用户在打游戏）；splash 真机探针只在早期跑过一次拿证据，之后已改成默认离屏。

## 1. 浅色主题下启动画面仍是深色
- splash.py 的 `resolve_splash_dark()` 底色逻辑本身是对的（浅 #F3F4F7 / 深 #1C1C1C，alpha 240），
  位图像素采样也证明浅色底确实是 #F3F4F7（见下"证据"）。
- **真实根因 = theme 值写法不统一**：旧 `resolve_splash_dark` 只认死字符串
  `== "浅色主题"`，而配置里的 theme 远不止这一种写法：
  · 设置页下拉框存规范简体（浅色主题/深色主题/跟随系统）—— 这一种以前能认；
  · **GCP-AI 的 set_theme 工具**（core/ai/agent_tools.py）以前写的是**短形式** "浅色"/"深色"；
  · 繁体界面存 "淺色主題"、英文界面存 "Light Theme"、老配置可能存 "light"。
  上面这些以前全部落到"认不出来 → 回退深色"，于是**用户明明选了浅色，启动画面还是黑的**。
- 修法（两处，双保险）：
  ① `splash.py` 新增 `_theme_is_light()`：兼容短形式/繁体/英文/大小写/全半角，
     认得出浅/深就直接用，认不出才回退深色；"跟随系统"走 detect_system_theme()。
  ② `agent_tools.tool_set_theme`：改成写**规范全名**（浅色主题/深色主题/跟随系统），
     与设置页 optionsFor、前端 isDark、splash 同一套字符串（以前写短形式，
     前端 isDark 也只认全名 → "AI 说切浅色"其实界面根本没变浅）。
- 证据：
  · `test_splash_theme.py`（既有）全过 —— 三种主题底色、色值与 webui --page 一致、
    读设置失败一律回退深色不抛、位图像素/尺寸/圆角规格、不 import PyQt5。
  · `probe_splash_live.py`（改成默认离屏）：`_prepare_bitmap(dark=False)` 背景像素 = (243,244,247,240)
    = #F3F4F7；早期一次 --show 真机截屏采样窗口背景 = #EEECEC（浅色 OK）。
  · `resolve_splash_dark('浅色主题'/'浅色'/'淺色主題'/'Light Theme'/'light')` 全部 → 浅色。

## 2. 启动画面"先居中后跑偏"的位置跳变
- 代码审查：`_run_native` 里居中坐标 (x,y) 在建窗前按主屏 work_area 算好，
  并且**同时**传给 CreateWindowExW 和 `_update_layered(..., x, y)`（UpdateLayeredWindow 的 pptDst）。
  注释里记录的"第一版把 src_pt 当 pptDst 传 → 窗口被挪到 (0,0)"这个坑**已经修掉了**，
  当前代码没有第二个 SetWindowPos/MoveWindow 会二次改位置。
- 真机证据（早期一次 --show，260x260 小窗，用 EnumWindows 按类名 ToolsGCP_Splash* 精确抓）：
  实测矩形**只有 1 个** = (830,386,1090,646)，正好等于 work_area(0,0,1920,1032) 的理论中心
  (830,386)，尺寸 260x260 —— 第一帧就居中、全程无跳变。
- 结论：这条在当前代码里**已不复现**（应是之前某轮已修，用户看到的是旧包）。
  已把 `probe_splash_live.py` 固化成默认离屏 + `--show` 才真弹的取证脚本，
  并加了"只统计有尺寸的矩形、按类名精确匹配"的防误抓逻辑（之前 FindWindow 抓到托盘窗口是假阳性）。
- ⚠️ 多显示器/不同 DPI 缩放的居中仍需真机复核（本机只有一个 1920x1032 工作区）。

## 3. 托盘右键菜单 hover 移出后残留
- 根因：`traymenu.py` 的窗口过程只处理 `WM_MOUSEMOVE`，**没有 `WM_MOUSELEAVE`**。
  WM_MOUSEMOVE 只在光标在窗口**内**移动时来；光标一旦移出菜单窗口，再也收不到 mousemove，
  `_hover` 停在最后一次命中的那一项 → 高亮框永远留着（用户报的现象）。
- 修法：
  ① 新增 `_TRACKMOUSEEVENT` 结构 + `_track_mouse_leave()`（TrackMouseEvent TME_LEAVE）；
  ② `_on_mouse_move` 里首次进入时申请一次 leave（TrackMouseEvent 是一次性的，用
     `_tracking_leave` 标志防重复申请）；
  ③ 窗口过程加 `WM_MOUSELEAVE` 分支 → `_on_mouse_leave()`：清 `_hover=-1`、重绘、
     重置 `_tracking_leave`（下次回来能重新申请）。
- 证据：`test_traymenu_hover.py`（桩掉 _draw/_hit_test/TrackMouseEvent，纯状态机）全过：
  窗口内移动 hover 跟手、第一次 mousemove 申请 leave、leave 后 hover 清零并重绘、
  回来能重新申请、再移出再清零、窗口过程确有 WM_MOUSELEAVE 分支。

## 验证汇总（全程不弹窗）
- `python -m compileall -q .ToolsGCP/desktop .ToolsGCP/modules ToolsGCP.pyw` → OK
- `test_splash_theme.py` / `test_traymenu_hover.py` / `probe_splash_live.py`（离屏）→ 全 PASS

## 需真机确认
- 浅色主题启动画面：开发机 Windows 应用模式当前是"深色"，"跟随系统"分支无法在本机复现浅色；
  显式"浅色主题"分支已用像素采样证明正确。请在真机设成浅色主题（或系统浅色 + 跟随系统）复核一眼。
- 多显示器 / 非 100% 缩放下的 splash 居中。
- 托盘菜单 hover：状态机与消息接线已测；实际"移出鼠标高亮即消失"的手感需真机右键托盘看一眼。
