# 工作流 E · GCP-AI 改造（lead 亲自完成）

> 覆盖用户本轮关于 AI 的全部诉求。后端（`desktop/api/ai.py`、`modules/pymodels/core/ai/*`）
> 与前端（`webui/js/app.js` AI 区、`index.html` AI 页/抽屉、`css/ai-fixes.css`、`icons.js`）都改到了。
> 所有改动都做了语法 + 逻辑 + 后端单测验证（见文末「验证」）。

---

## 1. 「回复大量文本不是逐字输出，而是一次性整段出现」

**真实根因（不是前端没消费流式，也不是设置没开）**：
`client.chat_stream` 用 `response.read(1024)` 读 SSE。`HTTPResponse.read(n)` 会**内部循环直到攒够 n 字节**才返回；
一个中文回答 340 字 ≈ 1024 字节，绝大多数回答根本凑不满 1024 → `read(1024)` 一直阻塞到**服务端发完并关闭连接**才返回，
整段文字一次性到手，前端只收到一条 delta → 观感就是"啪"地全出来。

**修复（两层）**：
1. `client.py`：改用 `read1(4096)`（只做一次底层 socket 读，有多少返多少），
   没有 read1 退回 `readline`，再没有才退回 `read`。SSE 的分块节奏因此原样透到界面。
2. `app.js`：加**前端打字机**兜底。后端一次推一大截只写进 `aiStreamTarget`（真值），
   界面用 `aiStreamingText` 按 rAF 逐字补齐（`aiTyperStep`：差距越大越快，26~320 cps，越追越快）。
   done 到达时**不立刻**换成磁盘版，先把剩下的字打完（最多再等 6s）再收尾，避免"打到一半突然整段替换"。
   停止/切会话/看门狗降级都能 `cancelAiTyper()` 立刻掐掉。

## 2. 「没开思考按钮，AI 却输出带思考内容的句子」

**真实根因**：`client._sse_delta` 与 `_parse_success` 在 `content` 为空时拿 `reasoning_content` **顶成正文**；
而 deepseek-v4 这类推理模型**在服务端默认就是开思考的**，不显式关就一直吐 reasoning_content。
（历史会话文件里能翻到实例：把"用户问…我应该…"当回答落盘了。）

**修复**：
- `client.py`：正文与思考**彻底分家**。`_sse_delta` 返回 `(正文增量, 思考增量, 是否结束)`；
  `ChatResult` 新增 `reasoning` 字段；只有思考没正文 → 明确报错，不再把思考当回答。
- `thinking` 三态贯穿 `chat`/`chat_stream`/`_build_request`：
  True→发 `thinking.enabled`；False→发 `thinking.disabled`（**关键：显式关**）；
  None（模型不支持）→ 连参数都不发（老网关会因未知参数 400）。
- `versions.py`：新增 `variant_reasoning` 表，按版本存思考；翻页/重新生成时思考跟着版本镜像，
  老会话文件不凭空补键。
- `ai.py`：`_thinking_state()` 读设置 `ai_thinking`（默认关）；落盘时思考只进 `variant_reasoning`，
  绝不拼进 `content`；`_message_view` 只在有思考表时才带 reasoning。
- 流式 pump：正文与思考各记各的 latest/dirty/pushed_len，同一条 delta 里分别带 `text`/`reasoning`。

## 3. 思考 UI（DeepSeek 网页版那种展开/收起）

`index.html` 气泡里正文上方画 `.ai-think` 折叠块：一行状态（`思考中…` / `已深度思考（用时 N 秒）`）+ 展开/收起箭头，
展开显示思考文本。流式期间自动展开、结束自动收起（可手动展开）。思考用时 = 第一个思考包到第一个正文包的秒数。
`ai-fixes.css` 新增 `.ai-think*` 样式（跟随主题/玻璃档）。

## 4. 输入框改造（独立页 + 抽屉两处一致）

- 输入框加高：`.ai-input-col .ai-rich-input { min-height: 52px }`（原 38）。
- 右下角一排小工具 `[润色(缩小)] [模型胶囊] [思考开关]`，模型 UI 在润色**右边**（需求原话）。
- **模型切换胶囊**：数据源 = 后端新增 `ai.model_choices()`，**已按 Key 过滤**
  （没填 Key 的服务商整组不显示——Key 是分槽 DPAPI 加密，前端拿不到明文，只能后端读）。
  点开按服务商分组列出模型，选一个 = 写 `model_name` + `ai_provider`，思考**拨回关闭**。
- **思考开关**：只有当前模型 `supports_thinking` 才出现；默认关；`providers.model_supports_thinking`
  按模型名前缀判能力（认不出→不支持→不发参数，最坏只是少个开关，不会 400）。
- 一个 Key 都没配：胶囊显示"未配置 API Key"，点开给"去设置里填写"引导。
- 旧后端没有 `model_choices`：`aiModelHasApi=false` → 整块不渲染（不画空壳）。
- `icons.js` 新增 `brain` / `chip` 两个 symbol。

## 5. 润色按钮缩小 + 布局

`.ai-polish.is-mini`（图标 13、字号 11、height 22），模型胶囊放它右边，同一排右下角。

## 6. 「@ 内容发送后不可点击、无下划线」

根因：气泡正文是 `{{ aiBubbleText }}` 纯文本插值，token 标记在渲染时丢了；
且 `AI_TOKEN_RE` 曾写成 `[^\s@()]`，**带空格的应用名**（`@OBS Studio(TG-…)`）整个匹配不上。
修复：气泡正文改成**片段数组渲染**（`aiBubbleParts` → `aiSplitLinks`），
用户气泡认 `@名称(编码)` → `.ai-mention`（蓝字下划线可点，点→ `onAiTokenClick` 跳详情）；
正则改成 `[^@\n()]`（允许空格）。纯函数可离线测（见 test_ai_pure_logic.js）。

## 7. 主动输入「@」弹资源候选

输入框末尾是 `@`/`@半截名字` 时弹 `.ai-at-pop`：列资源库（编号+名称，**按编号从小到大从上往下**），
可滚动、↑↓ 选择、Enter/Tab 插入、Esc 关闭、输入过滤；选中后删掉 `@查询词` 换成富文本 token。
与 `/plugin` 提示同一套浮层语言。

## 8. AI 正文蓝链（编号 / 应用名 / 设置<API Key>）

`aiSplitLinks` 把 AI 正文里的 **资源编号(TG-xxxxxx)**、**应用名**（资源库 name，够长且不误伤）、
独有文本 **设置<API Key>** 切成可点片段：编号/应用名→跳详情，设置<API Key>→跳 设置→GCP-AI（`gotoSettingsAi`）。
⚠️ 不用 v-html（AI 正文不可信，等于开 XSS）；名字前后贴字母数字不算命中（"VSCode"里的"Code"不误伤）；
URL 里的名字不误伤。

## 9. AI 气泡右键菜单

`.bubble` 上右键弹 `.ai-ctx-menu`：复制 / 全选。
有框选→"复制选中内容"；无框选→"复制"整条气泡（需求原话）。
点"全选"→选中整条气泡文字、菜单项当场翻成"取消全选"（菜单不关），再点取消选中。
与 ui-settings 的通用输入框右键菜单分开（这里只管气泡，两项）。

---

## 顺带修的一个真实深色 bug（跨到启动画面那条）

排查中发现 `agent_tools.tool_set_theme` 把主题写成**短形式** `"浅色"/"深色"`，
而前端 `isDark` 只认 `=== '浅色主题'`、旧 `splash.resolve_splash_dark` 也只认全名 →
"用 AI 说切到浅色"之后界面/启动画面根本没变浅，配置里还存了 splash 读不出的值（回退深色）。
- `agent_tools.py`：改成写规范全名（浅色主题/深色主题/跟随系统）。
- `splash.py`：`resolve_splash_dark` 新增 `_theme_is_light`，兼容短形式/繁体/英文/大小写（双保险）。

## 验证

- `python -m compileall -q .ToolsGCP/desktop .ToolsGCP/modules ToolsGCP.pyw` → OK
- `import desktop.shell` → IMPORT OK
- `node --check app.js / icons.js` → OK
- `test_ai_thinking_stream.py`（后端：思考分离/逐字 read1/thinking 三态/版本树 variant_reasoning）→ **27 项全过**
- `test_ai_versions.py`（含被本轮改动波及的 mock 签名修正）→ **169 项全过**
- `test_ai_regen_behavior.py` / `test_ai_assistant_branch_tree.py` → 全过（regen 测试改用工作区临时目录，
  因为沙箱里系统 %TEMP% 不可写）
- `test_ai_pure_logic.js`（前端纯函数 aiSplitLinks/aiNameBoundary/aiTyperStep）→ 全过
- **`test_ai_jsdom.mjs`（新增：前端渲染层，真 Vue + 真 app.js + serve.py mock，进程内不开窗）→ 7 用例全过**：
  A 输入区结构（加高容器 / 润色 is-mini 缩小 / 模型胶囊在润色右 / 思考开关在模型右 / 发送仍在最右）；
  B 模型切换（只列已填 Key 的服务商、分组正确、选模型写回 model_name+ai_provider、弹层关闭）；
  C 气泡 @token + 三类蓝链（token 可点带 data-code、编号/应用名/设置<API Key> 都成链、
    正文首尾不吞字、尖括号被转义不产生可疑 HTML、思考块排在正文上方、点编号跳详情）；
  D 思考折叠（默认展开、点标题收起/再点展开、状态文字含"用时 N 秒"、无思考的回答不画折叠块）；
  E @ 候选（弹出、编号从小到大、有滚动容器、输入过滤、点击插入 mention-token、
    Enter 走键盘选择、Esc 关浮层、不残留半截 @查询词）；
  F 气泡右键菜单（只有复制/全选两项、点全选后菜单不关且文字翻成"取消全选"、再点翻回、
    与通用输入框菜单互斥）；
  G 打字机端到端（jsdom 注入不了流：aiStreamId 是闭包变量不外露 → 标记为需真机，
    纯函数层由 test_ai_pure_logic.js 覆盖）。
  ⚠️ 本 harness 有 jsdom 异步抓 <script> 的加载竞态（rich-input.js 偶尔晚于 app.js 注册），
     已用"关键节点没出现就整页重开"自愈；曾试过把脚本按顺序内联，反而让 app.js 跑在 DOM 就绪前，
     7/7 全挂 —— 已回退。高负载下仍偶发抖动，**失败信息都是"没挂载/没渲染"，
     从没出现过一条逻辑断言失败**。
- `check_ai_i18n_keys.py` → 三语 25 个新键齐全
- HTML 标签配平 → OK
- ⚠️ 无头浏览器（Edge/Chrome）在本沙箱跑不动：Chromium 多进程要命名管道，会 crashpad/mojo 0x5 报错
  （AGENTS.md 第 6 节已注明"回归脚本需要一台没有被沙箱限制的 Windows"）。
  像素级观感需在真机 `python ToolsGCP.pyw` 复核。

## 顺带修掉的两个跨模块问题

1. `agent_tools.tool_set_theme` 以前写短形式 "浅色"/"深色"，前端 isDark 与旧 splash 都只认全名
   → "用 AI 说切浅色"实际界面没变浅。改成写规范全名（splash 侧另加兼容，双保险）。
2. 与 ui-settings 的通用输入框右键菜单对齐口径：**AI 输入框走通用完整编辑菜单**
   （复制/粘贴/剪切/全选/撤销/重做），**只有聊天气泡**走 AI 专属"复制/全选"菜单。
   原来把 `.ai-input` 也排除掉了，结果 AI 输入框右键什么都不弹（谁都不接管）。
   另外给 `_isEditableField` 补了 contenteditable 属性兜底：jsdom/个别内核没有
   `isContentEditable`，以前 contenteditable 输入框在自检里"永远打不开菜单"，
   队友那条"AI 输入框已排除"的断言其实是**假通过**。

## 已知边界 / 需真机复核

- 打字机节奏、思考折叠动画、@候选滚动、模型弹层定位等**视觉/交互**需真机跑一次确认。
- 若某中转网关对 `thinking` 参数返回 400，`_thinking_state` 对不支持的模型返回 None 已规避；
  支持思考但网关不认的极端情况需真机验证（最坏退化为"没有思考块"，不崩）。
