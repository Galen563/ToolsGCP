# 工作流 A · win-shell（Python 外壳）—— Lead 接手完成

> 原派给 win-shell 的 teammate 因 2-child 并发上限两次中断、未落盘任何改动，
> 由 Lead 直接接手完成。全程**不弹窗**（用户在打游戏），验证一律用离线/进程内方式。

## 1. 浏览器模式页签：程序图标 + 名称 ToolsGCP
- 现象：Ctrl+Shift+O 打开浏览器后，页签只有默认地球图标。
- 根因：`index.html` 的 `<head>` 没有 `<link rel="icon">`，浏览器只会去要 `/favicon.ico`，
  本地 WSGI（webhost）没有这个文件 → 图标缺失。`<title>` 本来就是 ToolsGCP（没问题）。
- 修法：在 `index.html` head 加 `<link rel="icon" type="image/png" href="/res/logo.png">`
  （复用既有 `/res/<name>` 路由 = `.ToolsGCP/logo.png`，不新增文件/路由）。
- 证据：`test_browser_tab_icon.py`（直接喂 WSGI environ，不开浏览器）15 项全过：
  favicon link 存在、`/res/logo.png` 返回 200 + image/png + 真 PNG 签名、
  桌面 webhost 与浏览器 bridge_app 对 `/`、`/res/logo.png` **逐字节一致**（两端页签同源）。

## 2. 浏览器模式：窗口收起方式（重要 · 需求歧义，需用户确认）
- 用户原话：「打开浏览器模式没缩到托盘 bug（任务栏的 ToolsGCP 彻底消失**而不是还保留在任务栏中显示**）」。
- 断句结论：括号里前半是**现象**（彻底消失 = 错），后半是**期望**（任务栏仍保留图标）。
  → 期望 = **最小化**（保留任务栏按钮），**不是** hide 进托盘。
- 现状：上一轮把 `open_browser_mode` 从 `minimize_window()` 误改成了 `hide_to_tray()`
  （`minimize_window` 自己的注释就写着"隐藏后任务栏没图标，用户会以为程序没了"）。
- 修法：改回 `minimize_window()`；事件字段从 `hidden_to_tray` 改回 `minimized`；日志同步。
- 证据：`test_browser_mode_minimize.py` 11 项全过（桩对象跑真实 open_browser_mode，
  断言调 minimize 不调 hide、失败时不碰窗口、事件带 minimized、源码里不再出现 hide_to_tray）。
- ⚠️ 这条存在真实歧义（"缩到托盘"字面又像要 hide）。已按"保留任务栏图标"实现，
  **请用户在真机确认**：如果其实想要"任务栏不留图标"，把这一处改回 hide_to_tray 即可（一行）。

## 3. 桌面端 ↔ 浏览器端「配置类改动」双向同步
- 根因（关键）：`settings.set` 只在 `notify=True` 才广播 `settings-changed`，
  而**前端所有 saveSetting 都传 notify=false** → 这条事件实际上从没为用户改动发过，
  另一端自然收不到 = 用户说的"一端改了另一端还是老样子"。
- 修法（后端单点）：`SettingsDomain.set` 改成**值真的变了就广播**（notify 参数保留兼容）。
  push_event 会同时投给桌面 WebView2 与浏览器长轮询队列（shell.push_event 一份逻辑两端等价）。
  收藏 favorites.* 本来就广播（回归验证未改坏）。
- 回声安全：发起端自己也会收到，但前端 listener 只做 `settings[key]=new`（幂等），
  不会再调 settings.set → 无死循环/重复落盘（静态断言验证）。
- 敏感项：api_key*/license_key/dev_mode_key **一律不广播**（明文 Key 不能经 HTTP 桥投给另一端；
  也不"广播但抹空值"，否则另一端会把空串写回正在填的框）。
- 证据：`test_settings_sync.py` 全过（值变广播/值不变不广播/notify 兼容/敏感项不广播但照常落盘/
  收藏广播回归/前端 listener 幂等/日志打码/快照分槽 Key 清空）。

## 4. 迁移后点「立即重启」没重启
- 根因：`shell.restart()` 是 `Popen(新进程)` 在前、旧进程 0.25s 后才 `quit_app_async`，
  而单实例互斥锁要到 `main()` 的 finally 才 release。新进程跑得更快，在旧进程还攥着
  `ToolsGCP_SingleInstance_Mutex` 时 check() → ERROR_ALREADY_EXISTS → 判定"已有实例"、
  激活旧窗后**自己退出** → 用户看到"点了重启但没重启"。
  （和文件头 `--update --pid` 那条是同一个坑，重启路径此前没处理。）
- 修法：
  ① `shell.restart()` 拉起新进程时带 `--restart <旧PID>`；
  ② `ToolsGCP.pyw` 单实例检测**之前**加 `_wait_for_restart_parent()`：
     看到 `--restart` 就 OpenProcess+WaitForSingleObject 等旧 PID 退出（上限 10s，异常/超时放行）。
- 证据：`test_restart_relay.py` 全过（无 --restart 秒回/死 PID 不傻等/活 PID 真等够/
  非法 PID 不抛/源码接线带 --restart+getpid）。全程用控制台子进程当"旧 PID"，不开窗。

## 5. 日志补全 —— 发现并修复一个**系统性**根因
- 用户反馈"日志部分操作不记录"。审计发现真根因不是漏加，而是**加了也没用**：
  `Logger.op(self, cat_zh, action, **fields)` 只吃 2 个位置参数，
  而 api 层 40 处 `_log("op", 分类, 动作, 文本)` 传第 3 个位置参数 →
  `TypeError` 被 `_log` 的 `except: pass` 静默吞掉 → **这 40 处 op 日志一条都没落盘**
  （AI 流式、收藏、下载、迁移、重启、公告……全空白）。
- 修法：`Logger.op` 增加可选第 3 位置参数 `message`（默认空串），既修好全部 api 层调用，
  又完全兼容所有既有 2 位置参数调用方（favorites/settings/announcements 的直接 log.op）。
- 顺带修一个**明文泄漏**（实测复现）：logger 的 REDACT_KEYS 是精确匹配，
  按服务商分槽的 `api_key_enc_deepseek` 会把**明文 Key 写进 system_log.log**。
  新增 `is_secret_key()`（精确名 + 前缀族），logger 打码、settings 快照、广播三处统一走它。
- 补记 set_api_key（以前一行日志都不写，注释还谎称"走了 notify"）与公告 mark_read 的 op 日志
  （只记服务商+长度+状态，绝不记 Key 本体）。
- 证据：`test_op_log_path.py` 全过（op 3 位置参数不再抛 TypeError、文本保留、
  其它级别不受影响、明文 Key 不进日志）。

## 验证汇总（全程不弹窗）
- `python -m compileall -q .ToolsGCP/desktop .ToolsGCP/modules ToolsGCP.pyw` → OK
- `import desktop.shell/api/browsermode/splash` → OK；noqt_check → 主链路无 Qt
- 新增离线单测：test_browser_tab_icon / test_browser_mode_minimize / test_settings_sync /
  test_restart_relay / test_op_log_path → 全 PASS
- 回归：test_splash_theme / test_ai_* / test_traymenu_hover → 全 PASS

## 需真机确认
- 第 2 项（浏览器模式收起方式）的需求歧义，见上 ⚠️。
- 第 3 项跨端实时刷新、第 4 项真重启，逻辑与单测都过了，端到端需两台客户端同开一次实跑。
