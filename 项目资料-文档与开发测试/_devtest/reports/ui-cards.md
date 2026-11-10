# task-3 · 卡片/收藏页/详情页 修复报告（cards-fe）

> 工作流 C · ui-cards。5 项全部修完并通过验证。
> 环境限制：这台机器的 OS 沙箱**起不了任何 Chromium**（Edge/Chrome 的 mojo 命名管道
> CreateFile 被拒 0x5，crashpad FATAL；Lead 也确认"无头浏览器在本沙箱跑不动、别再试"）。
> 因此视觉像素级截图**没有**，验证全部换成三条不弹窗的通道（见 §4）：
> `node --check` + **jsdom 运行时回归**（真 Vue + 真 app.js + 真 serve.py mock，进程内无窗口）
> + **布局矩阵**（真实列数公式 × 12 档分辨率/缩放）+ 静态契约断言。
> 真机观感请用户按 §5 清单最后过一遍。

---

## 0. 改动文件一览

| 文件 | 区域 | 内容 |
|---|---|---|
| `.ToolsGCP/webui/js/app.js` | loadResources / openDetail / detailRows / 收藏页网格区 / 虚拟列表区 / toggleFilter / onMounted | 5 项修复的 JS 侧（详见下） |
| `.ToolsGCP/webui/index.html` | 详情段(464-580)、收藏段(721-895) | 先量后渲染门控、星标恒实心、空字段不渲染、minHeight |
| `.ToolsGCP/webui/css/fav-fixes.css` | ② 卡片网格区 | `height:auto` + `scrollbar-gutter: stable` |
| `.ToolsGCP/webui/css/components.css` | `.grid-static .card` | `height:196px` → `min-height:196px`（AGENTS 第 5 条） |
| `项目资料-文档与开发测试/_devtest/` | 新增 | `test_cards_runtime.js`（40 项 jsdom 运行时）、`test_cards_layout_matrix.js`（53 项布局矩阵）、`test_cards_contracts.js`（31 项静态契约）、`_nodeprobe/`（jsdom 依赖，带 .gitignore）、`reports/cards-*.txt`（输出证据） |

未动：AI 区、设置/combo/右键菜单区、`layout.css`/`r24-fixes.css`（检查后无需改）、py 存档、用户数据。

---

## 1. 收藏页"重启后再进 UI 混乱、像匀速整理"

**根因（三条叠加，逐条排查结果）：**

1. **先渲染后测量 → 二次跳变**。`favGridWidth` 初始 0，`favLayout` 走兜底列数
   （tile=4/grid=6）先把卡片画出来；`onPageAfterEnter`/rAF 补拍才量到真实宽度 →
   列数变化 → 整屏卡片宽度和换行位置**当场重排一次**。切页过渡（out-in 230ms）
   期间量不到容器，这个跳变就落在用户眼皮底下。
2. **ResizeObserver 从来没生效过（旧错误代码）**。`onMounted` 里
   `if (favGrid.value) observe(...)` —— 启动落在搜索页，收藏页网格还没挂载，
   条件恒 false，观察器**从未建立**；切页后网格是全新元素也没人重新挂。
   重排只能靠 onPageAfterEnter 的"补一拍"，时机不可控。
3. **滚动条 ↔ 列数反馈回路**。`.page-scroll` 是 `overflow-y:auto`：内容超高出滚动条
   → clientWidth 少 8px → 恰好可能让列数 4↔3 翻转 → 行数变化又可能消掉滚动条
   → 宽度回来 → 再翻回去。每次翻转都伴随一次全网格重排 —— 这就是
   "像匀速整理/排序"的直接来源（不是排序动画：全仓库 grep 证实没有 FLIP/
   transition-group/逐项 `--i` 卡片动画残留，`cardIn` 入场动画只挂在搜索页
   `.vlist.cards-anim` 且每会话只播一次；`.card` 上没有 transition 尺寸属性）。

**修法：**

- **先量后渲染**：`ref` 从网格（`v-if="favItems.length"`，随数据卸载）改挂到**常驻**
  的 `.page-scroll`（`favScroller`），`@vue:mounted="measureFavGrid"` 在插入后、
  浏览器绘制前同步量宽（`.page` 是 `position:absolute; inset:0`，插入即有最终宽）；
  网格渲染条件加 `favMeasured` 门控 → **第一帧列数就是终值，结构上不存在二次跳变**。
  空文案从 `v-else` 改成 `v-if="!favItems.length"`，防止门控那一帧闪"收藏夹是空的"。
- **极端兜底**：窗口隐藏等量到 0 时 rAF 重试一次，再不行放行渲染（用兜底列数）——
  宁可退化成旧行为也不留空白页；后续 ResizeObserver 拿到真实尺寸自动纠正。
- **ResizeObserver 随页重挂**：`watch(favScroller)` 挂载即观察/卸载即断开，
  侧栏展开收起、窗口缩放都走这一条（唯一允许重排的路径）。
- **断开反馈回路**：`.fav-main .page-scroll { scrollbar-gutter: stable }`
  滚动条槽常驻预留，clientWidth 与内容高度无关。
- **尊重 `ui_animation`**：没有全局关动画；`data-motion=off/reduced` 的既有分级不变。
  旧的两处"补一拍"（onPageAfterEnter / doGoto 里 measureFavGrid + rAF）保留为幂等兜底
  （measureFavGrid 幂等，量到同值不触发重渲染）。

## 2. 收藏页星标显示成"未收藏（空心）"

**根因**：`mapItem` 把每个新对象初始化为 `_fav:false`。`loadResources()` 重建
`items.value`（启动、云端后台刷新 `cloud.refresh.done`、切资源源、语言切换等多条路）
之后**没有任何人重算 `_fav`** —— 唯一真源 `folders.value`（favorites.list）此时早已在
内存里，但只有 `loadFavorites()` 会调 `syncFavoriteState()`。`favItems` 是从 `items`
筛出来的 → 星星空心；点一下反而走"取消收藏"。重启后必现（boot 里 loadResources 与
loadFavorites 之间隔着网络等待）。`openDetail` 也抄了传入卡片的旧 `_fav` 副本，同样会串。

**修法（三层保险）：**

1. `loadResources()` 重建 items 后立即 `syncFavoriteState()`（兑现该文件 1509 行注释
   里"任何收藏变化后都必须调用"的承诺，补上资源库重建这条漏掉的路）。
2. `openDetail` 的 `merged._fav = favoriteCodeSet().has(merged.code)` —— 以收藏夹为
   真源，不抄副本。
3. 收藏页模板星标**恒实心**（`class="card-btn is-fav"` + 固定 `#i-star_solid`）：
   收藏页的卡片必然已收藏，这是页面级不变量，不再依赖任何同步时序。
   点击行为不变（仍是取消收藏，取消后卡片即从网格消失）。
   搜索页/详情页/定制页保持 `it._fav` 三元（它们确实存在未收藏态），由 1+2 保证正确。

## 3. 多分辨率/缩放下卡片大小不对、简介被遮挡

**根因**：AGENTS.md 第 5 条点名的"CSS 写死卡片宽高"仍在两处生效：
`.grid-static .card { height: 196px }`（components.css，收藏页/定制页共用）和
收藏页模板内联 `height: cardPx.height`。卡片内容高度**不恒定**：
① 带 `download_page_url` 的卡片卡脚多一行按钮（+32px）；② 不同机型/系统**最小字号**
设置、字体度量（雅黑缺失回退到别的字体）、DPI 缩放都会把标题/简介/标签行顶高。
固定高 + `.card{overflow:hidden}` → 简介下沿/卡脚被裁 —— 只在部分机器复现，正是用户描述。
搜索页虚拟列表同理：行高是固定 `cardPx.height`，带下载行按钮的卡片会被裁。

**修法（全部自适应，不写死）：**

- 收藏页：模板内联 `height` → **`minHeight`**；fav-fixes.css 卡片 `height:auto`。
  高度交还给内容，grid 行 auto 取整行最高卡（同行仍等高）；列宽仍 1fr 等分。
- 定制页：`.grid-static .card` `height:196px` → `min-height:196px`
  （flex-wrap 行默认 stretch，同行等高不变；宽度 272 固定是"等宽不拉伸"需求，保留）。
- 搜索页：`rowModel` 行高按行内容计算 —— 行内有带下载页按钮的卡片时整行 +32
  （`FOOT_LINKS_H`），虚拟列表的确定行高与卡片实际高度一致。
- `scrollbar-gutter: stable` 同时消掉"窄一档就少 8px"造成的列数抖动。

**验证（本机无 Chromium，用真实公式跑矩阵）**：`test_cards_layout_matrix.js` 把
1280×720 / 1440×900 / 1920×1080 / 2560×1440 × dsf 1/1.25/1.5（CSS 像素=物理/dsf，
外壳 342px+滚动槽 8px 按 CSS 实测常量扣）逐档喂给**真实 app.js 的 favLayout**，断言：
行宽自洽、渲染卡宽∈[minW,maxCardW]、无 0 宽面条、列数与搜索页公式一致、
1 列超宽由 CSS max-width 封顶；另加极窄 300px / 极宽 2100px 两档。51 项全过，
明细见 `reports/cards-layout-matrix.txt`（例：1280@1.5 → 1 列 400 封顶；
2560@1.0 → 6 列 356）。

## 4. 详情页空字段显示"—"

**根因**：`detailRows` 的过滤是 `index < 4 || row.value` —— 前四行（适用系统/CPU 架构/
类别/上架时间）**无条件保留**，空值靠模板 `row.value || '—'` 画占位；且"全空→整块不显示"
只是注释意图，从未实现。

**修法**：

- `detailRows` 统一 `rows.filter((row) => String(row.value || '').trim())` ——
  空值整行（label+value）不进 rows，`detail-grid` 是 2 列 CSS Grid，行少了**自动收缩**，
  不留空位。链接行（官网/GitHub/下载地址）本来就有 `isHttp` 把关。
- 模板删掉 `|| '—'`；`<div v-if="detailRows.length" class="detail-block">` 全空整块隐藏。
- 推广到同类空值项：详情头部的**标签行**（`v-if="detailTags.length"`）和
  **作者/聊天按钮行**（`v-if="isHttp(author)||isHttp(chat)"`）空时整行不渲染
  （空 div 在 flex column gap 里仍占一格）；变体行已有 `variants.length > 1` 把关。
  应用介绍为空有既有"还没有填写应用介绍"文案，不动。
- 部署表 `col-code` 的 `|| '—'`、maker 标题的 `|| '—'` 不在本任务范围（非卡片/详情段），未动。

## 5. 更多筛选展开时顶部卡片提前消失

**根因**：虚拟列表行坐标（`rowModel.top`）是相对 `.vlist` 的，而 `.vlist` 在滚动容器
内容里还有 `vlistTop` 的起始偏移（搜索框行+工具栏+**展开的筛选面板 ~400px**+选择条）。
旧 `vRows` 直接把 `scrollTop` 当行坐标 → 窗口上边界比真实可视区**高出 vlistTop 像素**；
筛选一展开偏移暴涨，顶部 2~3 行卡片明明还在屏幕上就被裁出 DOM —— 与用户描述完全一致。
（定制页是静态 flex 网格、无虚拟化，代码里不存在任何滚动驱动的移除路径；
它若出现同样现象，根因即 §3 的固定高度裁切/或搜索页视觉混淆，已一并覆盖。）

**修法**：

- 新增 `vlistTop` + `measureVlistTop()`：`rect(.vlist) − rect(.page-scroll) + scrollTop
  − clientTop` 换算内容坐标（offsetParent 链走不到未定位的滚动容器，rect 法才正确）。
- `vRows` 窗口上界改为 `Math.max(0, scrollTop − vlistTop)` —— 卡片只在**真正**滚出
  可视区（含 OVERSCAN=3 行余量）后才移除。
- 重测时机三处：`measureViewport()` 内（进页/切视图/返回详情）、`onScrollArea` 每帧
  （覆盖筛选 180ms max-height 过渡的中间态）、`toggleFilter` 的 nextTick + 220ms
  过渡结束各一次。`vlistTop`/`measureViewport` 已加入 setup return（测试接缝）。

---

## 6. 验证证据（全部不弹窗）

| 通道 | 结果 | 证据 |
|---|---|---|
| `node --check app.js / icons.js` | 通过 | — |
| jsdom 运行时（真 Vue+真 app.js+serve.py mock） | **36/36** | `reports/cards-runtime.txt` |
| 布局矩阵（12 档分辨率×缩放+极端档） | **51/51** | `reports/cards-layout-matrix.txt` |
| 静态契约（行为钉死） | **26/26** | `reports/cards-contracts.txt` |
| 既有回归 `test_frontend_features.js` | **57/57** 无回归 | `reports/cards-frontend-features.txt` |

合计 170 条断言全过（跑法见各文件头注释；契约/矩阵纯离线，runtime 需先起 serve.py）。

jsdom 运行时覆盖：收藏页门控/列数自洽/幂等无二次跳变/RO 变宽变窄重排、
资源库重建后 `_fav` 不丢、取消再收藏、星标 DOM 恒实心、详情空字段整行消失
（数据层+DOM 层双查、无"—"）、筛选展开滚 300px 顶行仍在 DOM/真滚出才回收/
收起后偏移复位，全程无 JS 错误。
（jsdom 无排版引擎：几何用注入的模型值喂**真实测量函数**，验的是"量到之后做的事"；
像素级排版由矩阵 + 用户真机清单兜底。）

## 7. 真机复核清单（留给能跑 Chromium 的机器/用户）

```bash
# 起预览
python 项目资料-文档与开发测试/_devtest/serve.py 8811
# 截图矩阵示例（Edge；--force-device-scale-factor 需配合 --window-size 的 CSS 像素）
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new --disable-gpu ^
  --window-size=1280,720 --screenshot=fav_1280.png "http://127.0.0.1:8811/?page=favorites"
```
人眼清单：① 有收藏 → 重启 → 直接进收藏页：第一帧即终布局，无整理感；反复进出/
切收藏夹稳定。② 收藏页星星全实心；取消→消失，去搜索页再收藏→回来仍实心。
③ 1280×720 与 150% 缩放下简介完整可见、卡脚不被裁。④ 打开 CPU 架构为空的资源
（如 TG-000005）：无"CPU 架构"行、无"—"、网格无空位。⑤ 搜索页展开更多筛选 →
下滚：顶部卡片滚出屏幕才消失；开/关筛选后重滚一致。

## 8. 风险与未解决点

1. **像素级验证缺位**（沙箱禁 Chromium）：字体/DPI 真实渲染下的高度只能靠
   min-height + height:auto 的机制性兜底 + 矩阵数学，最终观感需用户真机确认。
2. `components.css` 的 `min-height` 改动**同时影响定制页**（同一规则）——与 task-2/4
   的写域有重叠，改动是单行、带注释；若 ui-settings 也在动 components.css，
   合并时以"min-height:196px"为准。
3. 搜索页 tile 视图行高仍是 JS 确定值（虚拟列表必须如此）：若某机型字体把内容顶到
   超过 preset 高，tile 卡内部仍会裁简介尾行 —— 机制上比原来好（下载行不再必裁），
   彻底解法需要动态行高测量，改动面大，留待真机反馈后再评估。
4. `favMeasured` 门控让"收藏数据回来"与"容器挂载"两事件解耦：极端时序（容器先挂载、
   数据 0 条）下网格不渲染、显示空文案 —— 与原行为一致，无回归。
5. 定制页"卡片凭空消失"未找到第二条代码路径（静态网格无虚拟化）；若用户真机仍能复现，
   需要具体机型/复现步骤再查。
6. "先量后渲染"的门控对**首次进入**（用户报的场景：重启后进收藏页）是结构性的零跳变；
   **再次进入且窗口尺寸变过**时，旧列数可能保留一个微任务（@vue:mounted 量到新宽后
   立即纠正，通常仍在同一帧绘制前）；宽度本身由 1fr 等分**从不跳**，只有换行位置
   可能微调一次。彻底消除需要把测量提到切页前，收益低风险高，未做。
7. 重跑本套测试：契约/矩阵纯离线直接跑；runtime 需要 serve.py 在跑
   （脚本会先探测、没有就自己 spawn；本沙箱 Node 不能 spawn，需手动先起）。
6. 并发编辑：app.js/index.html 被 ai/settings-fe 高频改动，本次所有 edit 均为小范围
   精确替换，FS_STALE 时重读重试；最终 diff 建议 Lead 统一跑一遍 §6 全套再合。
