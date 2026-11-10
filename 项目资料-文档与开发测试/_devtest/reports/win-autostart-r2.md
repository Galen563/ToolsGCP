# 开机自启（task-6）· 第二轮

用户原话：「修复开机自启开关操控不好使还有开机自启bug和启动时最小化到托盘还是在任务栏bug，
和只有开机自启时怎么点击任务栏这个都不弹出窗口bug必须要右键托盘选择显示主窗口才恢复正常弹出。
（开机自启确保在任务管理器中的启动应用可以看到）」

实现：`autostart-r2`；报告与证据复核：`lead`（autostart-r2 未落报告文件，lead 亲自复验后补写）。

---

## ① 开关"操控不好使" —— 两条根因（都已实证）

### 根因 A：设置里拨开关**完全不联动注册表**
`startup_with_windows` 以前只有启动时 `_sync_autostart()` 同步一次；
用户在设置页拨开关 → 只改了 `toolsgcp_config.json`，注册表纹丝不动。

**修法**（`desktop/api/resources.py` `SettingsDomain.set`）：
```python
if key == "startup_with_windows":
    wanted = _as_bool(value)
    ok, err = autostart.set_enabled(wanted)
    if not ok:
        return _fail(f"写入系统启动项失败：{err}", key=key, autostart=False)
```
- ⚠️ **顺序必须是"先注册表、后落盘"**：注册表写失败就不落盘，
  否则留下"设置显示开了、实际没开"的假状态（比原来的 bug 更难排查）。
- 失败带回 `ok=False + error`，不静默成功；前端 `saveSetting` 已有
  `if (!result.ok) { 回滚 + toast(result.error) }`，错误信封直接可用，前端无需配合。
- 成功记 op 日志。
- 同时补了 `_sync_autostart()` 的**反向**分支（设置=关但注册表还留着 → 删掉；
  以前只补"开"不补"关"）。

### 根因 B（★真机取证发现，更硬）：Explorer 把启动项标记为"已禁用"
`HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run`
里 `ToolsGCP` 的 REG_BINARY **首字节 = 0x02**。

Run 项在、设置说"开"，但 Explorer 开机根本不拉起，任务管理器「启动应用」显示**已禁用**
—— 这才是用户感知"不好使"的主要现象（光修 A 不够）。

**lead 亲自复验（本机当前真实状态）**：
```
Run\ToolsGCP = "D:\Python3.13.1\pythonw.exe" "...\ToolsGCP.pyw" --autostart
StartupApproved 首字节 = 0x02 类型=3 -> 已禁用
is_enabled() = True            ← 设置说"开了"
startup_disabled_by_explorer() = True   ← 但 Windows 不会拉起
```

**修法**（`desktop/native/autostart.py`）：新增
`startup_disabled_by_explorer()` / `clear_disabled_mark()`；
`set_enabled(True)` = 写 Run **+ 清禁用标记**；`set_enabled(False)` = 删 Run + 同样清标记。
- ⚠️ **为什么删值而不是写 0x03+FILETIME**：微软没公开这个结构的写法，
  长度写错（必须 12 字节）任务管理器可能仍显示"已禁用"；
  而"值不存在"正是 Windows 自己的默认状态（新建 Run 项就没有这条），删掉最可靠。
- ⚠️ 只动 HKCU、只动我们自己的值名；失败不抛异常（不打断自启主流程）。

**证据**：`_devtest/test_autostart_toggle.py` **27 项全过**（桩 winreg，不污染真实注册表）。

---

## ② 任务管理器「启动应用」可见性 + exe 打包态命令行

`command_line()` 的 exe 分支修好了（旧写法在 exe 下 `sys.argv[0] == sys.executable`，
会拼成 `"ToolsGCP.exe" "ToolsGCP.exe" --autostart` —— exe 被当脚本传两遍）。

**lead 受控复验**（桩 `sys.argv`/`sys.executable`/`is_packaged_exe`）：
```
源码态 : "D:\Python3.13.1\pythonw.exe" "C:\proj\ToolsGCP.pyw" --autostart
exe 态 : "C:\ToolsGCP\ToolsGCP.exe" --autostart
exe 态无重复参数 : True      exe 态带 --autostart : True
源码态用 pythonw（不闪黑窗）: True      源码态脚本参数只有一个 : True
```
- 值名仍是 `ToolsGCP`、源码态格式与原版 `set_windows_autostart` **一字不差**
  （老用户机器上已有这条项，格式变了会导致"关自启时删不掉/开一次就被写坏"）。
- 用 `pythonw.exe` 而非 `python.exe`：后者会闪一个控制台黑窗。
- ⚠️ 诊断时若用 `python - <<EOF` 跑，`sys.argv[0] == '-'`，`command_line()` 会输出
  `"python.exe" "-" --autostart` 这种怪值 —— **那是诊断方式的产物，不是产品 bug**，
  复验必须像上面那样受控桩参数。

---

## ③ 静默启动仍占任务栏 —— 真隐藏 + 成对恢复

旧实现只是把窗口留在屏幕外 `OFFSCREEN(-32000,-32000)` + 不 show，
窗口仍是 `WS_EX_APPWINDOW` → **任务栏照样有按钮**（看不见但占位）。

**修法**：
- `desktop/native/frame.py` 新增 `set_taskbar_hidden(hwnd, hidden, window)`：
  - `hidden=True` → 清 `WS_EX_APPWINDOW` + 置 `WS_EX_TOOLWINDOW`（任务栏不建按钮）；
  - `hidden=False` → 反向恢复 + `SWP_FRAMECHANGED` 让系统重算；
  - ⚠️ 光有 TOOLWINDOW 还不够：窗口若有**可见父窗口**，任务栏按钮规则由父窗口决定，
    所以还要处理 owner。
- 新增 `is_taskbar_hidden(hwnd)` 读实测样式（`toolwindow` / `appwindow` / `visible`）。
- `desktop/shell.py` 新增 `_apply_taskbar_hidden(hidden, where)`，
  并把切换前后的 exstyle 与 `IsWindowVisible` **原值记进日志**（远程排查全靠它）。
- **成对**：`_on_shown` 里静默启动时 `_apply_taskbar_hidden(True)`；
  `show_window()` 里按 `is_taskbar_hidden(hwnd)["toolwindow"]` 实测结果
  `_apply_taskbar_hidden(False, where="呼出主窗口")` —— 只在**我们自己置过**时才翻转。

## ④ 点任务栏不弹窗 / 必须右键托盘才恢复

根因就是 ③：窗口在屏幕外 + 样式不对，点任务栏按钮走的是系统 restore，
进不到我们的 `show_window()`（"搬回工作区正中 + 焦点给回 WebView2"都在那里）。
③ 修完后任务栏不再有按钮，这条自然消失。

顺带补了托盘左键：`desktop/native/tray.py` 里
- `NIN_SELECT`（WM_USER+0，**Win10/11 左键单击实际发的是这个**，不是老式的 `WM_LBUTTONUP`）
  与 `WM_LBUTTONUP`（老协议兜底）→ 单击呼出；
- `WM_LBUTTONDBLCLK` → 双击呼出，并压掉紧随其后的重复单击回调。
旧代码只接了 `WM_LBUTTONDBLCLK`，所以左键**单击**没反应。

---

## 未能在本机完成的一项（如实记录）

**真机跑一次静默启动**（`python ToolsGCP.pyw --autostart` 后量任务栏按钮）
在本沙箱做不到：lead 亲自跑了 canary 复现 ——
```
step=import_webview
step=import_winforms_dependents
CLR_FAIL RuntimeError Failed to initialize Python.Runtime.dll   （退出码 0xE0434352）
```
子进程继承沙箱导致 pythonnet 初始化被拒，pywebview/WinForms 根本起不来
（同机上无头 Edge 也起不动：Chromium 多进程要命名管道，crashpad 0x5）。
**这不是产品 bug，也没有尝试绕沙箱。**

→ 请在非沙箱机器上验证这一项：
1. 保持当前配置（`startup_with_windows=True`、`minimize_to_tray=True`），
   先拨一次开关（触发 `set_enabled` → 应清掉 StartupApproved 的 0x02）；
2. 任务管理器 → 启动应用：ToolsGCP 应显示**已启用**；
3. `python ToolsGCP.pyw --autostart`：任务栏**不应**有 ToolsGCP 按钮、屏幕上无窗口；
4. 托盘图标**左键单击**、**双击**都应呼出主窗口，且呼出后任务栏按钮恢复、窗口在工作区正中并置前；
5. 日志里应有 `任务栏按钮收起（静默启动）: ok=True exstyle 0x…→0x… visible=False`
   与 `任务栏按钮恢复（呼出主窗口）: ok=True …` 两条成对记录。
