# ui-settings · task-4 完成报告（settings-fe）

> 范围：设置页左栏选中稳定 / 设置搜索栏优化 / 自绘下拉框（Combo）滚动 / 全局输入框右键菜单。
> 改动文件：`.ToolsGCP/webui/js/app.js`（settings 区、Combo 区、新增全局右键菜单模块级代码、mount 后一行）、
> `.ToolsGCP/webui/index.html`（设置段 + 新增 `#input-menu` 模板）、`.ToolsGCP/webui/js/icons.js`（新增 4 个 symbol）、
> `.ToolsGCP/webui/css/settings-fixes.css`、`.ToolsGCP/webui/css/overlays.css`。
> 全部为小范围精确 edit，无整文件重写、无格式化。

---

## 1) 左栏点击「GCP-AI / 开发者功能」自己跳到「关于」

**根因（两层叠加）**
1. `syncSectionFromScroll` 里"触底就选最后一个板块"的分支：GCP-AI/开发者功能本来就靠底，
   平滑滚动到位≈触底 → spy 立刻把选中改成「关于」。
2. 旧修复 `scrollLockUntil = Date.now() + 700` 是**延时假装正常**：长距离平滑滚动（如从「外观」点「关于」）
   或性能抖动时 700ms 不够，锁一过期 spy 照样乱改；反过来 700ms 内用户真滚了页面，spy 又被误锁。

**修复（真状态机，删掉时间戳）**
- `scrollSection()`：置 `spyMode='locked'`、`userScrollIntent=false`，然后发起 `scrollTo`。
- 新增用户滚动意图检测（document 捕获阶段，四个入口）：
  - `wheel` / `touchstart`：事件目标必须在 `.settings-main` 内；
  - `keydown`：只认翻页类键（↑↓/PgUp/PgDn/Home/End/空格），且焦点不在输入控件（输入框里方向键=移光标）；
  - `mousedown`：落在容器自身且横坐标进入滚动条区域（拖动滚动条）。
- `syncSectionFromScroll()`：locked 期间**什么都不做**（程序滚动途中和稳定后选中都钉在点击项）；
  只有带着 `userScrollIntent` 的 scroll 才把状态交还 `free` —— 意图驱动，不由时间驱动。
- rAF 回调里二次检查 `spyMode==='locked'`（排队期间用户点了左栏 → 该帧作废，防竞态）。
- 触底分支改为选**视口里顶边真正露出的最后一节**（`offsetTop < 视口底-8`），不再无脑 `nodes[last]`。
  用户自己滚到底时选中=关于（正确），但点「开发者功能」到位后即使≈触底也不会跳。
- `watch(page)`：离开设置页解除 locked，回来时 spy 按恢复的滚动位置正常工作。

## 2) 设置搜索栏

**② 首字符变灰/变小**：全仓库 grep 无 `::first-letter`/`text-indent` 规则（探针也遍历 styleSheets 断言了）。
最可疑的既有隐患是 `.search-box input` 为搜索页设计的 `padding: 0 62px 0 36px`（右缘给"搜索按钮+清除按钮"两个坑位）
被设置搜索复用后右缘留白 62px 但只有一个清除按钮，placeholder 灰字与正文视觉错位被读成"第一个字不对"；
另一候选是 Chromium/WebView2 的 autofill 会给输入框首字符刷特殊底色/字色（语言包 hint 文案排查过无异常）。
修复：`settings-fixes.css` 给 `.settings-search input` 显式钉死 `font-size / color / -webkit-text-fill-color /
font-family / padding 32px/30px / text-indent:0 / letter-spacing:normal`，placeholder 只作用于 `::placeholder`，
所有字符同字号同颜色（探针断言输入前后 computed style 一致；`-webkit-text-fill-color` 同时压掉 autofill 首字符染色）。

**③ 结果格式「板块-设置项」**：模板两个 `<span class="hit-section/hit-row">` 合并成
`<span class="hit-merged">{{ hit.section }}-{{ hit.label }}</span>`；CSS 加 `.search-hit-merged`
（单行、省略号）。三语正确性天然成立：section/label 都来自 `t()` 当前语言文案（探针英文态断言
`Hotkeys-Open in Browser` 通过）。注意：语言包现势文案是「在浏览器中打开」，所以搜"浏"显示
「快捷键-在浏览器中打开」（格式=用户要的 板块-设置项）。

**③ 清除按钮 + Esc**：搜索框加与搜索页同款 `.search-clear`（`v-show="settingQuery"`，i-close 图标，
`right:6px` 贴框内右缘；`.is-empty` 类同步搜索页行为）。点击/Esc 都走 `clearSettingQuery($event)`：
清空 `settingQuery` → `v-if` 自动恢复板块列表；Esc 时 `stopPropagation` 防止误触发全局 Esc 链
（关弹窗/退详情），**空框按 Esc 不拦截**，全局链照常。

## 3) Combo 弹层滚动 bug

**根因**
- `place()` 末尾 `this.top = Math.min(this.top, Math.max(8, innerHeight - maxHeight - 8))`：
  触发器上移（下方空间 < 96+8）时把弹层**拽到窗口底部** → "抵到触发器原位置中间"遮挡；
  触发器滚出视口后弹层仍按旧 x 重定位 → "一直留在屏幕底部之前 x 轴位置"。
- 只有 scroll/resize 触发重定位，布局位移（上方行隐藏、图片撑高）不响应。

**修复**
- `place()`：触发器**部分/完全**离开可视区（上、下、左、右任一）→ `this.open=false` 直接关闭；
  未离开 → `top = r.bottom + 4` 永远贴合，**删除夹取**（下方放不下就让列表自然截断，绝不翻上去压触发器）。
- 打开期间 `watch: open` 启停 rAF 逐帧跟踪（`_startTrack/_stopTrack`）：滚动（含内部容器）、
  resize、布局位移统一覆盖；rect 没变时不写响应式字段，稳定后近零成本；`beforeUnmount` 停帧，切页不残留弹层
  （teleport 随组件卸载消失 + registry 互斥照旧）。
- `_onScroll` 跳过"滚动弹层自己"（`e.target ∈ pop`），保留"31 项类别列表可内部滚动"的既有修复。
- 触发器仍在视口但下方空间不足时：`maxHeight` 保底 96 允许伸出窗口底（与旧版一致，不遮挡触发器优先）。

## 4) 全局输入框右键菜单

**实现**：`index.html` 在 `#app` 外新增常驻 `#input-menu`（复用 `.card-menu/.card-menu-item` 外壳 →
主题/毛玻璃/圆角/阴影与现有卡片右键菜单完全一致），app.js 末尾新增模块级驱动（与 tip-bubble 同套路，
不占 Vue 状态，切页/卸载天然不残留）：
- 接管对象：`input(text/search/url/tel/password/email/number，含 readonly) / textarea / contenteditable`，
  document 捕获阶段委托 `contextmenu`；**排除** `.ai-input/.ai-rich-input/.bubble*`（AI 队友已有
  `openAiCtx` 专属菜单 + `@contextmenu.prevent.stop`，stopPropagation 与我的排除双保险，互不冲突）。
  checkbox/range/color 不接管。
- 六项：复制/粘贴/剪切/全选/撤销/重做（"左撤回/右撤回"= Undo/Redo），每项前置图标 +
  文字下方灰色小字快捷键 `Ctrl+C/V/X/A/Z/Y`。
- 图标：icons.js 复用现有 `i-copy`/`i-undo`，新增 `i-redo`（undo 水平镜像）/`i-cut`/`i-paste`/`i-select_all`
  （24 网格、stroke=currentColor、线宽 1.7，注释按该文件既有格式）。
- 禁用态（置灰 + `pointer-events:none`）：无选区→复制/剪切禁；readonly→剪切/粘贴/撤销/重做禁；
  无内容→全选禁；剪贴板确认空→粘贴禁（先 `clipboard.read` 后端、再 `navigator.clipboard.readText`，
  **都拿不到时保守视为可用**）；撤销/重做对文本框无法程序触发（Chromium 不暴露 input 撤销栈），
  点击时把焦点交回并提示 Ctrl+Z/Ctrl+Y，contenteditable 走 `execCommand('undo'/'redo')`。
- 关闭：点外部（document mousedown 捕获）/ Esc（捕获阶段先关菜单并 stopPropagation，菜单没开时不影响
  全局 Esc 链）/ 滚动 / resize / 窗口失焦。
- 定位：跟随鼠标，双帧量尺寸后夹进窗口（`left/top ≥8`、不超右下缘）。
- 兼容性：只 `preventDefault` contextmenu 本身，不拦任何 keydown/beforeinput → 快捷键与中文输入法
  composition 不受影响；执行命令时**不无脑 focus**（快捷键框 @focus 会进录制态，copy 不需要焦点）。
- 文案三语：`copy/paste/cut/undo/redo` 键不在语言包（语言包目录不归本任务改），
  `_inputMenuLabel` 按 `I18N.language` 给中/英双兜底（`select_all` 用现有键）；繁体的精确词形是已知小缺口。

## 验证（不弹窗，遵守用户约束）

本沙箱 Chromium 多进程被禁（实测 crashpad/mojo `拒绝访问 0x5`，Edge/Chrome 均无法起无头实例），
按 lead 指示改用 **jsdom 内存探针**（纯 Node，不开窗口）：

- `node --check` app.js / icons.js ✅
- `项目资料-文档与开发测试/_devtest/settings_probe_jsdom.mjs`（serve.py mock + jsdom + 虚拟布局打桩），
  证据：`reports/settings_probe_jsdom.txt`，连跑 3 轮全绿：
  - A 左栏状态机：按序点 外观→快捷键→存储→GCP-AI→开发者功能→关于→外观→GCP-AI，
    每个"滚动途中/到位后/稳定 1s"三拍断言选中=点击项；用户 wheel 后 spy 恢复且准确；触底不乱跳 ✅
  - B 搜索：搜「浏」→「快捷键-在浏览器中打开」合并行、旧双 span 结构清零、无 ::first-letter/text-indent
    污染规则、清除按钮存在且在框内右缘、点清除/Esc 都恢复板块列表、输入前后 computed 一致 ✅
  - C Combo：弹层 gap=4px 不遮触发器；容器滚动 80px 重定位保持 4px；触发器滚出上缘/下缘 → 弹层关闭；
    贴底场景不再出现"top < trigger.bottom"的夹取遮挡 ✅
  - D 右键菜单：6 项齐全、图标/快捷键小字/文案、空框 copy/cut/select-all 禁用、有选区解禁、
    右下角打开不超窗、点外部/Esc 关闭、AI 抽屉里 .ai-input 不被接管、readonly 快捷键框接管且
    cut/paste/undo/redo 禁用、原生菜单被 preventDefault ✅
  - E 英文态：`Hotkeys-Open in Browser` 格式正确、菜单文案 Copy/Paste/Cut/Select all/Undo/Redo ✅
- HTML 标签配平（全局栈检查）✅；CSS 括号配平 ✅；Combo 组件选项无重复键 ✅；新增函数名与
  队友代码无撞名（grep 全文件唯一）✅
- 回归对照：regression.py 的 int_combo case（open→pick→popClosed）在新逻辑下路径不变
  （点击项在视口内、弹层不关）；int_settings case 只量布局不涉 spy。regression.py 本身需无沙箱机器，
  留待 Lead 真机跑。
- `settings_probe.py`（Edge 无头版）保留在 _devtest 作为**真机脚本**，本沙箱不可执行。

## 风险与未解决点

0. **_devtest 新增测试依赖**：`settings_probe_jsdom.mjs` 依赖 `npm install jsdom`（已装在
   `_devtest/node_modules/`，`package.json`/`package-lock.json` 同目录；untracked，不影响产品代码，
   也不引入任何前端构建链——产品 webui 依旧零依赖）。Edge 无头版 `settings_probe.py` 保留但本机不可执行。

1. **视觉效果未经真实浏览器验证**：jsdom 无布局引擎，贴合/夹取/禁用置灰是逻辑级断言；
   像素级（毛玻璃菜单质感、4px 间距观感、行高）需用户真机刷新确认。
2. **Combo 保底 96px**：触发器贴窗口底缘时弹层仍会伸出窗口外（旧版同样如此，是"不遮挡触发器"的
   代价）；若用户要"贴底自动翻上"，与"永远在下方"的旧需求冲突，需产品拍板。
3. **撤销/重做对 `<input>`/`<textarea>` 无法程序触发**（浏览器不暴露 per-field undo 栈）：
   菜单项按"可编辑=启用"置灰逻辑显示，点击行为是把焦点交回 + 提示 Ctrl+Z/Y；contenteditable 正常。
   若要真正的菜单级撤销，需要自实现编辑历史（改动面大，建议另立需求）。
4. **剪贴板探测**：pywebview 桌面端走 `clipboard.read`（后端已有）；浏览器模式 `readText` 需权限，
   拒绝时保守视为可用（点了失败会 toast）。
5. **繁体词形**：菜单兜底文案繁中沿用简体词（复制/粘贴/剪切/全选/撤销/重做），
   正式译名建议后续补进三语语言包 `common` 模块（语言包目录不归本任务）。
6. **并发协作**：`#input-menu` 排除选择器已含 `.ai-no-input-menu` 预留钩子；若 AI 队友后续把专属菜单
   扩展到输入框（而非气泡），他的容器只要带 `.ai-input/.bubble` 系类即自动让路。
