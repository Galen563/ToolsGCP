# ToolsGCP v1.1.4 · 第二轮需求总报告

> 本轮用户明确：「我现在不打游戏你可以随意测验弹窗」→ 允许真机验证。
> 分工：Lead 做 GCP-AI 全部 + 浏览器模式 + 启动画面浅色/叠加（webui 侧）+ 设置页二轮 + 多语言；
> `autostart-r2` 做开机自启；`splash-r2` 做启动动画底板/圆角与取证。
> ⚠️ 上一轮 4 个 teammate（win-shell / win-visual / cards-fe / settings-fe）claim 任务后
> **连续 20+ 小时零产出**（工作区无任何改动），本轮重派为 `autostart-r2` / `splash-r2`，
> 并把原 task-8（设置页二轮）整块收回 Lead 自己做。

---

## 一、GCP-AI（10 项，全部完成）

### 1. 输入框重构 ✅
需求原话：「重构输入框UI：底部按钮行移入输入框内部；更改模型切换图标 要求更贴切的图标；
润色去掉文字放在发送按钮左边；且把思考开关改为对接官方API的多档位滑动强度而不是只有开和关
（类似Codex）；模型切换的对勾放在模型前面 模型前面都要留点空隙确保对勾能放下。
复述一遍整体样貌：一个大输入框默认内容可以输入2行 超过2行才会改变输入框大小高度，
输入框内部最下排左侧为模型和思考 右侧从左往右为润色和发送按钮。」

**落地结构**（`index.html` 独立页 + 抽屉两处完全一致）：
```
.ai-box                      一个框（边框/圆角/聚焦光圈都在框上）
├ .ai-box-text               富文本输入区（min-height 55px ≈ 2 行；超过才长高到 190px）
└ .ai-box-bar                框**内部**最下排
  ├ .ai-box-left            模型胶囊 + 思考滑块
  └ .ai-box-right           润色（纯图标）→ 发送
```
- **按钮行入框内**：旧 `.ai-input-col/.ai-input-foot`（工具行在框外）整段删除，
  探针 A 断言"旧结构不得残留"。
- **2 行高度**：`min-height:55px`（13px × 1.5 × 2 + 内边距），`max-height:190px`
  —— 注意是**长高**而不是封顶内部滚动（用户说的是"超过2行才会改变高度"）。
- **模型图标**：`#i-chip`（芯片，读起来像硬件）→ 新增 `#i-model`（等距立方体），
  这是各类 AI 客户端里"选模型"的通用视觉语言。
- **润色去文字**：`.ai-polish.is-mini`（带文字）→ `.ai-polish.is-icon`（纯图标 26×26），
  位置移到发送按钮左边。
- **对勾前置**：`.ai-model-item` 结构改为 `[.ai-model-mark 18px 固定占位][名称][思考徽标]`，
  **未选中时也占位** —— 否则选中/取消会让模型名左右跳（用户要的"留点空隙"）。
- **思考多档滑块**：见下条。

### 2. 思考改为官方 API 多档强度 ✅（含后端）
不是简单加几个 UI 档位，是**打通到请求体**：
- `providers.py`：新增 `THINKING_LEVELS`（off/low/medium/high）、`normalize_thinking()`
  （**兼容旧布尔配置**：`False→"off"`、`True→"medium"`）、`thinking_levels()`；`model_catalog`
  带 `thinking_levels`。
- `client.py`：`_thinking_params()` 把档位翻译成请求体 ——
  `off` → 只发 `thinking.disabled`（推理模型服务端**默认开着**，不显式关就会一直吐
  reasoning_content，这是"没开思考却有思考内容"的根因）；`low/medium/high` →
  `thinking.enabled` + **`reasoning_effort`**（Codex / OpenAI 兼容网关的事实标准字段名）。
- `ai.py`：`_thinking_state()` 返回档位串；`_thinking_open()` 统一替代散落的 `thinking is True`
  （档位变字符串后 `is True` 永远为假 → 思考开了也看不见，这是必须一起改的连带 bug）。
- **400 自动降级**：用户填的中转/自建网关很多不认这两个字段 → `send`/`send_stream`
  收到 `bad_request` 且带档位时，**去掉思考参数重试一次**，用户最差只是"这一档没生效"，
  而不是整条消息发不出去。流式重试前会先清掉已收到的半截思考，避免"档位已关却还有思考块"。
- `constants.py` / 前端 `DEFAULT_SETTINGS`：`ai_thinking` 默认值 `False` → `"off"`
  （旧配置由 `normalize_thinking` 兜掉，**不需要配置迁移**）。
- UI：`<input type="range" min=0 max=3 step=1>`，格数由**当前模型支持的档位表**决定
  （不支持思考的模型整块不渲染）；右侧实时显示"关/低/中/高"。

### 3. 模型与思考在设置页改了不立即变化 ✅
两条根因，都在 `app.js`：
- `watch` 只看了 `ai_provider + apiKeyConfigured`，**漏了 `model_name`** —— 而设置页那个
  「模型选择」下拉改的正是 `model_name` → 档位表一直停在旧模型。
- 跨端 `settings-changed` 事件里没重拉档位表 → 另一端改了，本端滑块不动。
→ 补齐 watch + 事件分支；探针 I 专门验这条路（改模型胶囊跟着变 / 改档位滑块跟着动 /
切不支持思考的模型撤滑块）。

### 4. 用户气泡配色 + 编辑态反馈 ✅
- 「用户的聊天气泡不要是特殊的颜色，和AI聊天气泡一致颜色就ok」→ `.bubble.is-user`
  从 `--ball-a/--ball-b` 渐变改成与 `.is-ai` 同款 `var(--card-solid)` + 描边；
  **保留右对齐 + 右下小圆角**（方向性线索不能丢，否则分不清谁说的）；
  glass/acrylic 两档也跟着 AI 气泡一起半透明（否则一个糊一个实）。
- 「编辑模式下…反馈感不强 感觉还像是在聊天气泡内输入」→ `.bubble.ai-bubble-edit`：
  强调色描边 + 3px 外发光 + 圆角 16→10 + `caret-color` 强调色 + 去掉气泡尾部圆角。
  ⚠️ 只改颜色/描边/圆角，**不写 width/height**（上一轮"尺寸保持"的硬要求不能破坏）。

### 5. 气泡右键：删全选只留复制 + 修框选不弹菜单 ✅
- 菜单项从 2 项减到 1 项（`.ai-ctx-menu`），`aiCtxSelectAll` 整个函数与模板一起删。
- **真根因**（不是"事件没绑上"）：旧代码 `String(sel.toString || '')().length`
  是**调用 `toString` 本身**（返回 undefined）→ 长度判定恒为假。
  新增 `aiHasSelection()` 正常调用 `sel.toString()`。
- 复制语义保留上一轮约定：有框选复制选中部分，没框选复制整条气泡。

### 6. 选区颜色更蓝 ✅
`::selection` 的 `color-mix(var(--accent) 46%)`（浅色主题 34%），色相仍是强调色，
只提高不透明度，保证浅色主题下文字可读。

### 7. 抽屉点菜单按钮不自动关闭 ✅
**真根因**：抽屉的"点外部自动收"是 document mousedown 委托，而菜单浮层
（`.ai-ctx-menu` / `#input-menu` / `.ai-model-pop` / `.ai-at-pop`）在 DOM 上**都不在
`.ai-drawer` 里** → 点菜单项被判成"点了外面"→ 抽屉先关，菜单的 click 也就丢了。
→ 这四类浮层一律算"抽屉内部"。

### 8. 链接改由 AI 显式决定（不再自动匹配应用名）✅
用户原话：「我选择一个模型他之中会说xxx模型 我点击之后直接跳转到了对应资源页面是不对的…
而是真正需要的时候才弹」。
- **删掉**"拿资源库所有 name 去正文里找子串"的模糊匹配（`aiNameIndex` / `aiNameBoundary` 一并删）。
- 只认**显式**写法：`@名称(编码)` / 裸编号 `TG-xxxxx` / `设置<API Key>`。
- **同时改了提示词**（`prompt.py`）：告诉 AI 这三种写法会被渲染成可点链接、
  "要不要用由你自己判断"，并明确举例"说模型名/参数名时**不要**加链接"——
  否则取消自动匹配后 AI 根本不知道该在哪写链接，功能等于没了。

### 9. 「请填写<API Key>」可点蓝字 ✅（找到真根因）
用户原话：「当未填写API Key时或者填写有误会固定回复 其中包括"请填写<API Key>"
这个是下滑线字体 点击跳转页面到设置中的GCP-AI 位置（现在的那个是不可点击状态
无下划线 不是蓝色字体的普通字体是不对的 还有"<>"不是变量而是就是可点击文本的一部分）」

**真根因不在 AI 气泡，在两个地方**：
1. 语言包 `ai_no_key_reply` **三语都写着 HTML 标签**：
   `还没配置 <a href="toolsgcp://api_key">API Key</a>，填好就能聊。`
   而 toast 模板是 `{{ toast.message }}` **纯文本插值** → 用户看到的就是**字面的尖括号**，
   当然"不可点、无下划线、不是蓝字"。他说的"`<>` 不是变量"，指的正是这对被当成占位符写进文案的标签。
2. 后端固定回复写的是「打开设置里的 GCP-AI 板块填好再聊」，没有可点字面量。

**修法**：
- 语言包三语 + `en_fallback.py` 去掉 HTML，改成普通文字 + `请填写<API Key>` 字面量；
- `client.py` 的 401/403 文案（"填写有误"）也带 `请填写<API Key>`；
- 前端认三种字面量（`设置<API Key>` / `请填写<API Key>` / `填写<API Key>`）；
- toast 支持内联可点片段（`toastParts()`，**仍不用 v-html**），点击弹两项小菜单
  （去填写 API Key / 知道了）→ 跳 设置 → GCP-AI（toast 本身不接 click，必须给入口）。

### 10. 抽屉不半透明 ✅
上一轮为"材质联动"给 `.ai-drawer` 在 glass/acrylic 两档做了半透明 + 背景模糊，
用户明确不要 → 任何材质档都 `background: var(--card-solid)` + 去掉 backdrop-filter
（浅色主题 `#ffffff`）。只动 `.ai-drawer`，`.ai-history` 未提，保持原样。

### 11. 删除"未保存"确认弹窗 ✅
`goto()` 里那段三选框（放弃修改 / 留在当前界面 / 保存并继续）整块删除。
**取舍写进注释**：设置页只有 API Key 那一格是"要点保存才落盘"的
（文本行/下拉都是 `@change` 即时提交），所以这个弹窗只保护"Key 打到一半"这一种情况；
现在直接切页，回来时 `loadApiKeyForProvider()` 重新读后端，不会写出半截 Key、数据不会坏。
`apiKeyDirty()/saveApiKey()` 本身保留（保存按钮还在用）。

### 12. 版本树切换保持滚动位置 ✅
根因：翻版本走"整会话重建"，旧代码重建完直接 `nextTick(scrollAiToEnd)` —— 不管用户在
看第几条都拉到底。→ 改成**锚点法**：重建**前**记下被翻那条气泡在视口里的位置，
重建**后**把它挪回原处。用锚点而不是记 `scrollTop`，是因为新版本正文长短不同会让内容高度变，
固定 scrollTop 会跳到别的消息上。

---

## 二、浏览器模式（3 项，全部完成）

### 1. 标签页标题去掉 " · render" ✅
**真根因**：`setStep()` 会把**启动步骤名**拼进 `document.title`（排查启动卡死用的），
而 boot 最后一步正好叫 `render`（`setStep('render')`），走完之后再没人改回来 →
浏览器模式下页签**永久**显示 `ToolsGCP · render`（桌面 WebView2 没页签，所以只在浏览器模式暴露）。
→ 标题恒等于 `ToolsGCP`；启动步骤仍写进 `bootText` 和 `[boot] step=` 日志，排查能力没丢。

### 2. 真缩进托盘（任务栏不留图标）✅
你这轮把上一轮的歧义说清了：**要真 hide_to_tray，任务栏无 ToolsGCP**。
- `open_browser_mode()`：`minimize_window()` → **`hide_to_tray()`**；
- 新增 `_browser_mode_hidden` 标记 + `toggle_browser_mode()`：
  **再按一次 Ctrl+Shift+O 切回桌面**（你选的），切回时**不关 HTTP 服务**
  （浏览器页签还开着，关服务=那边整页废掉）；
- 托盘双击 / 托盘右键「显示主窗口」/ 热键呼出都会清掉标记。

### 3. 「桌面端又突然跳到所有窗口最顶端」✅
**真根因两条**（不是启动时序）：
- 浏览器页自身加载时会调 `window.center` / `window.show`（`goto()` 里就有），
  这两个在桌面端等于"把窗口搬出来 + 置前"。`center` 内部的 resize/move 还带
  **`SWP_SHOWWINDOW`** → 调用即显示。
- → `api.window.show` / `api.window.center` 增加 `_browser_mode_hidden` 闸门，
  浏览器模式期间前端这一路**不再掀窗口**；用户主动呼出（托盘/热键/单实例）不走这里，照常置前
  —— 这正是你在选项里选的那条「浏览器模式期间不要跳，但热键/托盘呼出时当然要跳到最前」。

**验证**：新增 `test_browser_mode_tray.py` **20 项全过**（含"失败时不碰窗口不留标记"、
"切回桌面不关服务"、两道闸门、源码层防回归）。

---

## 三、启动加载画面（浅色/叠加/居中/底板）—— 本轮最大的一次"找错对象"

### 结论：用户说的「程序窗口**中的**启动加载画面」是 webui 的 `.boot-screen`，
**不是** `desktop/splash.py` 那个 180px 原生浮窗。
上一轮改错了对象，所以"修过但没修好"。

`splash-r2` 真机取证（我独立复核过）：
```
[启动|splash] 启动画面底色: 浅色 theme='浅色主题' light=True
              DATA_DIR=C:\Users\Administrator\.ToolsGCP\config cfg_exists=True
```
DATA_DIR 是真实数据根、走到了浅色分支、预乘 BGRA 也没算错 → **原生 splash 无罪**。

### 三条真因与修复

**① 首帧主题依赖 localStorage，而它每次启动必然是空的** ✅
`index.html` 首帧脚本问 `localStorage['toolsgcp.theme']`，没有就退到
`matchMedia('(prefers-color-scheme: dark)')`。但：
- pywebview **默认 `private_mode=True`**，本项目从未传 `private_mode`/`storage_path`
  → WebView2 每次跑在**全新的临时 profile** 里（实测 `%APPDATA%\pywebview`、
  `%LOCALAPPDATA%\pywebview` 都不存在）→ 这个键**永远读不到**；
- 本机 Windows 应用模式是深色（`AppsUseLightTheme=0`）→ 退路也判深色。
⇒ 用户明明在软件里选了浅色主题，首帧仍然黑。

**修法**：`/` 是服务端路由，后端本来就知道用户存的是什么主题 →
`webhost._boot_theme()` 把真实 theme/accent 烘进 HTML（`<meta id="tg-boot-theme">`），
首帧脚本**第 0 优先**读它。桌面端与浏览器模式共用同一个 bottle app ⇒ **两端一起修好**。
（没有去动 `private_mode`：那会牵动 WebView2 profile 位置，副作用大得多。）
`_boot_theme` **复用** `splash._theme_is_light()`，不写第二份字符串判定表。

**② shell.py 建窗 `background_color` 写死 `#1C1C1C`** ✅
这是页面合成之前用户实际看到的那一层。→ 改成按 `_is_dark()` 取
`#F3F4F7` / `#1C1C1C`。
**连带修**：`_is_dark()` 原来只认死字符串 `"深色主题"/"浅色主题"`（和 splash 上一轮
**同一个 bug**），写法稍偏就掉到"读注册表"→ 判成深色。现在也复用 `_theme_is_light`。

**③ `.boot-screen` 透明 + absolute → "UI 叠加" + "不居中"** ✅
- **不居中是可算的几何**：`absolute; inset:0` 挂在 `<main class="content">` 里，
  居中于**内容盒**而不是窗口 —— `.titlebar` 高 48 + `.nav-rail` 宽 48 →
  内容盒中心 (664,464) vs 窗口中心 (640,440)，**偏右下各 24px**。
  → 改 `position: fixed; inset:0`（与视口同心，标题栏/导航多高都不影响）。
- **叠加**：上一轮按"要能看见底下界面轮廓"把它改成**完全透明**，而 `continueBoot()`
  在撤启动页**之前**就已经 `page.value='search'` → 透明的启动 UI 直接压在搜索页骨架上。
  → 铺一层**跟随主题 92%** 的页面底色 + blur：底下页面被压到几乎看不见，
  真黑屏时露出的也是跟随主题的底（不再固定 #1C1C1C）。
  ⚠️ 不用纯不透明 `var(--page)` —— 那会回到上一轮被否掉的"像弹了个窗"。

### 启动动画去底板 + logo 四角圆角（splash-r2 完成）✅
- `_prepare_bitmap()` 不再画底板，窗口尺寸 == logo 尺寸（180×180，原 260×260）；
- 圆角打在 logo **自己的 alpha 通道**上（半径 = 短边 16%，180→29px）；
- **防脏边的关键做法**：蒙版先用 2x LANCZOS 超采样拿平滑过渡，再与 1x **二值硬蒙版
  `darker()` 取 min** → 圆角外 alpha 被强制严格 0，堵掉 LANCZOS 振铃在角外留的 1~2 漏光；
  `_update_layered` 里 `a==0` 分支把 BGRA 四个字节全写 0。
- 验证：`test_splash_theme.py` 59 行 0 FAIL，含"全图所有 alpha==0 像素 BGRA 都是 0（0 个违规）"。
- ⚠️ **方法论修正**（已写进报告）：截屏**不能**用来证明"角外透明"——BitBlt 对分层窗口有
  抓取伪影，且背景本身在变（用户机器上 Chrome 正全屏放视频）。硬判据换成
  `_premultiply_bgra()` 的输出断言，截屏降级为"仅参考"。

---

## 四、设置页二轮（5 项，全部完成）

### 1. 下拉框：滚出可视区**不关闭、保留原地** ✅
用户本轮**推翻**上一轮做法：「下拉框滚动超出页面还是存在的而不是直接把下拉框给关闭了
你需要修改保留在原地即可无需超出窗口边界自动关闭。」
→ `place()` 里删掉"触发器离开可视区就关闭"和"夹到窗口底部"两条；
现在永远 `top = trigger.bottom + 4` 跟着触发器滚，触发器滚出屏幕弹层就跟着滚出去。
关闭只由用户动作决定（再点触发器 / 选中 / Esc / 点别处）。

### 2. 右键菜单点击无效果 ✅
排查结论：`_execInputMenuCommand` 的六项实现本身是对的，问题在**状态判定被误禁用**与
**文案提示缺失**。已修 + 新增专项探针 `test_input_menu_click.mjs`
**逐项点击并断言真实效果**（全选→选区、剪切→value 变化、复制→剪贴板、
粘贴→插入、撤销→明确提示而非静默）。

### 3. 快捷键文本移到右侧 + 加括号 + 菜单缩小 ✅
- HTML：`.imi-key` 从 `.imi-text` 竖排容器里**挪出来**，与 label 同级；
- CSS：`margin-left:auto` 顶到最右 + `min-width:132px`（原 172）、行高 36→24、字号 12→11.5；
- JS：括号在渲染时加 `（Ctrl+C）`（写死在 HTML 里切语言重刷会丢）。

### 4. 删除 AI 区"未保存"弹窗 ✅
见 GCP-AI 第 11 条。

### 5. 搜索「板块-设置项」里 "-" 前面用组件配色 ✅
`.hit-merged-section { color: var(--accent) }`（跟着"强调色"设置走），
"-" 与设置项名保持正文色；选中态再加粗区分。

---

## 五、多语言（3 项）

### 1. 漏翻补齐 ✅
先做**键集合审计**：三语 14 个模块 × 3 语 **0 缺口** → 说明问题不在语言包缺键，
而在**硬编码中文**。

**⚠️ 关键方法论（踩了三次才走对）**：
1. 第一版扫描探针用 `fetch('/mock/i18n')` 取语言包 —— **jsdom 不实现 window.fetch**，
   于是语言包根本没加载，页面上每个 `t()` 都退回中文兜底，扫出「282 处残留」**全是假阳性**。
   正解照搬已跑通的 settings_probe：用 jsdom 支持的 `XMLHttpRequest`；
   也不能把整包 JSON 塞进 js0（会超 http.server 请求行上限，直接 414）。
2. 修好后加了**自证**（`bundle 直调 modules=14` + `t('search')="Search"` 才继续扫），
   才拿到真数据：**只剩 5 类残留**，且都是真 bug。
3. 简繁差异字表也别拍脑袋：`於`（屬於/過於）、`查`（檢查）在繁体里**本来就是正确写法**，
   把它们当简体字会误报 3 条。

**扫出并修掉的真漏翻（三类）**：

| 位置 | 现象 | 修法 |
|---|---|---|
| `index.html` 标题栏三个按钮 | `aria-label="最小化"` 等**硬编码**，最大化/还原连 t() 都没走 | 全部改 `t()`；新增 `title_maximize` / `title_restore` 三语键 |
| `app.js:1563` 资源库错误兜底 | `'资源库读取失败'` 硬编码 → 英文界面出现「Could not load the cloud resource library: {err}**资源库读取失败**」中英混排 | 新增 `resource_load_failed_plain` / `resource_api_not_ready`，走 t() |
| **后端固定回复 + 错误文案** | 见下条（前端 grep 永远查不出来） | `_text()` + `_localized_error()` |

另外（不靠扫描、直接读代码发现的）：
- `aiProviderLabel()`：模型弹层的服务商分组名来自 `providers.py`（Python 侧简体中文），
  前端原来直接渲染 → 英文界面露中文。语言包**早就有** `ai_provider_<id>` 三语，按 id 取。
- 保存失败 / 启动异常 / 请求失败 → 走 `t()`。
- `introLines`（介绍 5 条）、`qqGroups`（QQ 群名）从**普通数组**改 `computed + t()`
  （普通数组在 setup 时就把中文固化了，切语言不生效）。
- `REPO_PLATFORMS` 的"自定义/不开源"→ `computed + t()`（GitHub 等专名不翻）。

**★ 后端那一类是本轮最大的发现**：用户说「包括各种地方」，但前端 grep 只能查前端。
"没配 Key 的固定回复"和"401/429/404… 错误气泡"都是**后端生成、直接落盘进气泡**的文本，
前端只负责显示、翻不了 → 英文界面下整条提示是中文。
- `desktop/api/ai.py` 新增 `_text(key, fallback, module, **fmt)`：按 `_locale()`
  （它会优先问 `shell.current_language()`；"跟随系统"时 `_language()` 只会硬退回简体中文）
  取当前语言文案；绝不抛异常，取不到退回中文 fallback。
- 新增 `_localized_error(kind, message, status)`：按 `client` 的 **kind** 查表重写
  （12 个 kind 全覆盖），**保留 client 拼的「（服务端说明：…）」尾巴** ——
  那是排查 401 最有用的原始信息，本地化不能把它吞掉；认不出 kind 或语言包缺键
  → 原样返回，绝不因为翻译失败丢报错。
- 三条固定回复（chat / polish / test）也接进语言包。
- ⚠️ **可点击 token 的字面量按语言各写一份**（中文 `请填写<API Key>`、英文
  `fill in <API Key>`）：如果英文界面里还写中文 token，就又变成用户报的"露简体中文"。
  前端 `AI_SETTINGS_TOKENS` 全部认，并且**必须按长度降序排**（否则
  `请填写<API Key>` 会被裸 `<API Key>` 先匹配掉，链接文字少一截）。
- ⚠️ 我自己在这过程中埋过一个 bug 并被测试抓到：`ai_err_server/unknown` 的模板带
  `{status}`，第一版没填 → 会把字面量 `{status}` 显示给用户。现在填不上就整条退回原文。

**新增键**（全部三语、JSON 校验通过）：`intro_line_1~5`、`repo_platform_custom/none`、
`boot_error_prefix`、`boot_watchdog_fail`、`toast_link_go_settings/dismiss`、
`ai_think_level_off/low/medium/high`、`ai_think_level_toast`、`ai_think_slider_tip`、
`title_maximize`、`title_restore`、`resource_load_failed_plain`、`resource_api_not_ready`、
`ai_err_*`（12 个 kind + failed + current_config）、`ai_no_key_chat/polish/test`。

**明确未做**：`makerPlatforms`（适用系统）、`CATEGORY_ORDER`、`DEPLOY_STATES` 等是
**数据结构取值**（存进 JSON、后端按它匹配），不是显示文案，翻译它们会破坏 schema。
要走"显示层翻译"需单独设计值→显示映射表，本轮不做。
`en_US` 包内还有 4 条 maker 长说明文本里带中文（其中一条键名本身就是中文），属既有低优先项。

### 2. 英文模式按钮尺寸 ✅
用户举例收藏页「导入/导出」：
- 语言包 `en_US` 的 `fav_export/fav_import` 从 `"Export favorites"/"Import favorites"`
  缩成 `"Export"/"Import"`；
- CSS 给 `.fav-ops-row .btn-half` 加 `min-width:0` + `overflow:hidden`（允许 flex 收缩）
  —— **不写死宽度**（AGENTS 第 5 条禁止）。

### 3. 本轮新增的验证工具（可长期复用）
- `test_i18n_english_leak.mjs`：切英文逐页扫**可见文本 + placeholder/title/aria-label**，
  排除资源库数据值；开头自证语言包已加载，没加载就 abort 并声明"本轮结果作废"
  （就是这条自证救了这次排查）。
- `test_ai_error_i18n.py`：后端错误/固定回复三语断言（含"英文包不许有简体字"、
  "token 表按长度优先"、"占位符必须填掉"、"缺键退回原文"）。
- `test_r2_visual_css.mjs`：**用 jsdom 真实 CSS 解析 + 文档顺序求级联生效值**，
  不再手写正则解析 CSS（前几版反复假 FAIL：注释里提到选择器名、逗号分组选择器、
  @media 嵌套、以及把 `:root[data-fx="glass"] .ai-drawer` 当成 @media 条件去找）。
- `test_unsaved_dialog_removed.mjs`：真跑交互验"未保存弹窗已删"（9 项全过）。

## 六、开机自启（autostart-r2，4 项）

### ① 开关不好使 ✅
**两条根因**：
1. `SettingsDomain.set` 对 `startup_with_windows` **完全没联动**（只有启动时同步一次）；
2. ★真机取证发现更硬的一条：`HKCU\...\Explorer\StartupApproved\Run` 里
   **`[ToolsGCP] = 02 00 00 00...`（被标记"已禁用"）** —— Run 值在、设置说"开"，
   但 Explorer 开机根本不拉起，任务管理器"启动应用"显示**已禁用**。这才是"不好使"的主因。
→ `set_enabled(True)` = 写 Run + **清 StartupApproved 禁用标记**；`set_enabled(False)` = 删 Run + 同样清标记；
开关失败时返回 `{ok:False}` 且**不落盘**（不留"显示开了实际没开"的假状态）。
证据：`test_autostart_toggle.py` 27 项全过（桩 winreg，不碰真实注册表）。

### ②③ 静默启动真隐藏任务栏 + 托盘呼出 ✅
`frame.set_taskbar_hidden()`：`hidden=True` 清 `WS_EX_APPWINDOW` + 置 `WS_EX_TOOLWINDOW`
（+ 可见性），`hidden=False` 反向恢复；`shell._apply_taskbar_hidden()` 保证**成对**，
呼出主窗口时自动恢复（否则"从托盘呼出后任务栏没按钮/Alt+Tab 缺失"）。
证据日志记录切换前后的 exstyle 与 IsWindowVisible 原值。

### ④ 注册表取证 ✅（见 ① 的 StartupApproved 发现）

---

## 七、验证汇总（最终全量 sweep，21 项全绿）

`bash 项目资料-文档与开发测试/_devtest/run_final_sweep.sh` →
`reports/final_sweep.txt`

**语法 / 导入 / 数据**
- `python -m compileall`（desktop + modules + ToolsGCP.pyw）✅
- `import desktop.shell` ✅（无 Qt 主链路）
- `node --check` app.js / icons.js / rich-input.js ✅
- 三语 42 个 JSON 全部可 `json.load` ✅；键集合对比 0 缺口 ✅

**Python 套件（14 个，全 PASS）**
test_ai_thinking_stream / test_ai_versions / test_ai_regen_behavior /
test_ai_assistant_branch_tree / **test_ai_error_i18n**（新，含真实 LanguageManager 端到端）/
**test_boot_screen_theme**（新，首帧主题烘进 HTML + background_color 跟随）/
**test_browser_mode_tray**（新，20 项，取代上轮 minimize 契约）/
test_browser_tab_icon / test_settings_sync / test_op_log_path /
test_splash_theme（含去底板+四角真透明的预乘 BGRA 断言）/
test_traymenu_hover / test_restart_relay /
**test_autostart_toggle**（新，27 项，桩 winreg）

**Node 探针（7 个，全 PASS）**
- test_ai_pure_logic（链接契约已改"应用名不再自动成链"）
- test_cards_contracts / test_cards_layout_matrix（51 项）
- **test_r2_visual_css**（新）：用 **jsdom 真实 CSSOM + index.html 实际加载顺序**求级联生效值，
  覆盖气泡同色/编辑态反馈/抽屉不透明/选区更蓝/boot-screen fixed + [7] 裸中文兜底守卫
- settings_probe_jsdom（下拉框契约已按本轮反转为"跟随不关闭"）
- **test_input_menu_click**（新）：右键菜单**逐项真点**，断言全选/剪切/复制/粘贴都产生可观察效果
- **test_unsaved_dialog_removed**（新）：改脏 API Key → 切页 → 断言不弹确认框、也没"顺手保存"
- test_ai_jsdom（**11 用例** A–K，本轮新增 H 滑块 / I 即时同步 / J toast 链接 / K 菜单细节）
- **test_ai_version_scroll**（新）：自带假布局，两个场景验"翻版本保持位置"
  （变长→精确保持；变短→允许被上限夹住但气泡必须仍在视野内）
- **test_i18n_english_leak**（新）：English 逐页扫可见文本 + placeholder/title/aria-label，
  13 页**全部 0 处中文残留**

**过程中的自我纠错（都写进了代码注释/报告，避免复发）**
1. 泄漏探针第一版用 `fetch` → jsdom 不支持 → 语言包没加载 → 误报"282 处残留"（全是假阳性）。
   加"自证 + 轮询等待"后才拿到真数据。
2. 后端 `_text` 模块名写成 `set`（正确是 `settings`）→ **静默永远查不到、退回中文**，
   桩版测试全测不出来；只有走真实 `LanguageManager` 的端到端断言抓到。
3. `get_text` 找不到键会**返回键名本身**，我把它当有效文案用了 → 界面会显示 `ai_no_key_chat`。
4. 视觉测试前几版手写正则解析 CSS，反复假 FAIL（注释里提到选择器名 / 逗号分组 /
   把 `:root[data-fx=…]` 当 @media）→ 改用 jsdom CSSOM 后一次通过。
5. 版本树锚点 `restoreAiAnchor` 原来查 `.bubble[data-i]`（取到**第一个**气泡而非锚定那条）
   → 自查时发现并修（顺带把"box 已脱离文档"也兜住）。
6. `boot-theme` 一度用错路径常量 `CONFIG_DIR`（那是随程序发布的资源目录，不是用户配置）
   → 改用 `DATA_DIR`，与 splash/SettingsManager 同一份文件。
7. 多次"锚点凭记忆写"导致 edit 落空（AssertionError 退出、后续语句没执行）——
   一律改成先读实际内容再定位。

## 八、需要你在真机复核的（沙箱测不了）

1. **像素级观感**：`splash-r2` 与我都受沙箱限制（pythonnet 初始化被拒 → 整个程序起不来），
   webui 侧结论是"源码+库源码+注册表+目录实测"推出的，证据链闭合但**没有那张截图**。
   请真机跑一次确认：浅色主题下启动加载画面是浅色、居中、没有两层字叠在一起。
2. **开机自启**：真机拨一次开关，看任务管理器"启动应用"里 ToolsGCP 是否从"已禁用"变"已启用"。
3. **浏览器模式**：按 Ctrl+Shift+O → 任务栏应无图标、窗口不抢前台；再按一次应切回桌面。

## 九、仍未处理（需要你拍板）

1. **`makerPlatforms` 等数据结构值的中文化**：翻译会破坏 schema，要做需单独设计"值→显示"映射表。
2. 上一轮遗留的「浏览器模式任务栏保留图标」实现已被本轮推翻并纠正，旧测试
   `test_browser_mode_minimize.py` 保留作历史证据（契约已由 `test_browser_mode_tray.py` 取代）。
