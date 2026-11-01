<div align="center">

# ToolsGCP

<img src=".ToolsGCP/logo.png" alt="ToolsGCP logo" width="140">

[English](README.zh-CN.md) ｜ **简体中文** ｜ [繁體中文](README.zh-TW.md)

*免费开源的 Windows 工具箱启动器 —— 每条资源都直达官网或 GitHub。*

</div>

---

## ToolsGCP 是什么

ToolsGCP 是一款免费开源的 Windows 工具箱启动器。它维护一份整理好的程序 / 网站索引，让你能快速找到、
收藏，并在换电脑后一次性把常用软件装回来，不用再去到处翻下载页。

- **纯净无捆绑** —— 每条资源都直达官网或官方 GitHub 仓库，不夹带、不劫持、不用二次打包的安装包。
- **应用部署** —— 把常用软件整理成清单，重装系统后一键还原。
- **GCP-AI** —— 内置 AI 助手。说一句"我想要个能干某事的软件"，它直接从资源库里找出来告诉你。
- **插件系统** —— 往 `.ToolsGCP/plugins/` 里放一个文件夹就是一个插件（manifest + 可选 HTML 配置页），任何人都能扩展，不用改核心代码。
- **资源制作器** —— 一个小工具，把"我想让这个软件被收录"变成一条规范的资源数据，图片导入、标签、写 JSON 全包。

## 功能一览

| 模块 | 内容 |
|---|---|
| 首页 | 顶部轮播图（5 张，每 3 秒自动翻页，圆点分页可点），下面是「推荐插件」——本机 `plugins/` 里的插件一览，点一下进插件中心 |
| 搜索 | 关键词搜索（名称 / 简介 / 标签 / 编码如 `TG-000015`）、按类别分组、A–Z 排序、收藏 |
| 筛选 | 类别、标签、来源（有官网 / 有仓库 / 可自动下载）、仅看收藏，以及**更新时间**（最新 / 10 天前 / 30 天前 / 半年前） |
| 卡片 | 自适应网格随窗口变化；**磁贴（一行 4 个大卡片）/ 网格（一行 6 个小卡片）两种视图**，工具栏最右边切换；小 / 中 / 大三种卡片尺寸；支持动态 GIF 图标；每张卡片有「@给AI」按钮。网格视图只保留收藏按钮，文字放不下会自动省略 |
| GCP-AI | 右下角液态悬浮球 → 右侧聊天抽屉；历史对话页（删除对话会二次确认）；消息可复制 / 重写 / 重新生成（带版本翻页）；未配置 API Key 时点提示直达设置；输入框最右侧有「**润色**」按钮（只改措辞、不发送、不进历史，可在设置 → GCP-AI 关闭） |
| 部署 | 从搜索结果整理部署清单，之后由 ToolsGCP 负责下载安装（**部署页只负责清单本身，不再和收藏互相关联**） |
| 资源来源 | 设置 → 下载 → 资源来源：**云端**（自动选 GitHub Releases 里最新的资源库，含 beta）或**本地文件**；云端失败保留旧缓存并继续用本地资源库，设置页会显示一行云端资源库状态 |
| 插件 | 井字 / 列表两种排版，**卡片右上角的状态徽章（已启用绿 / 已禁用红）**，左下角可写 20 字备注（点输入框外面自动取消），禁用后整卡变暗，还能搜索插件；插件配置页（iframe）会与主程序**同步深色主题 / 材质 / 强调色 / 语言** |
| 公告 | 内容来自 GitHub 上带「公告」标签、且**作者本人发的** Issue（一条 Issue = 一整条公告，标题 + 正文原样显示）。左侧栏「公告」上有像微信那样的**红色未读数**；右上角「全部已读」把未读清零；启动时若有未读，用「检查更新」那种窗口内弹窗提示。已读状态存在数据根的 `config/announcements.json` |
| 收藏 | 类似 B 站收藏夹：左侧收藏夹列表（默认夹不可删），右侧卡片网格；支持新建 / 重命名 / 删除 / 批量移动；**整页可导出 / 导入 JSON**（导入时可以放进已有收藏夹或新建一个，导入后星标与列表同步刷新） |
| GCP工坊 | 左侧栏「收藏」下面的一页（Galne563 自制）。**当前内容留空**，只放了标题与署名，等内容补充 |
| 侧边栏 AI | 设置 → GCP-AI 打开「改用侧边栏 AI 单独界面」后，左侧栏在 GCP工坊下面出现「AI」整页界面（输入框 / 发送 / 新建对话 / 历史一应俱全），同时右下角悬浮球消失。默认不开启。**两种形态共用同一段对话**：在悬浮球抽屉里聊到一半、去设置切到这个整页界面（或反过来），正在聊的那段会自动接过来 |
| 链接点击 | 详情页、搜索卡片、AI 回答、反馈页……**所有**外链：**左键**用浏览器打开并切到浏览器；**Ctrl+左键**浏览器照常打开，但当前程序**留在前台**（浏览器多是自己抢焦点，程序会把它抢回来后继续待着） |
| 界面字体 | 设置 → 外观 → 字体：从系统已安装字体里挑一个铺到整个程序，第一条（微软雅黑）就是默认字体 |
| 提交软件 | 左侧栏「更多」最下面一条，打开内置的**资源制作器页面**（投稿表单 / 资源浏览器 / 批量合成 / 使用说明）。类别是**可编辑下拉**（31 个内置类别 + 自定义输入，落盘前还原成规范名）；**三语字段**（简中 / 繁中 / 英文）；资源浏览器**双击**一行进入编辑，编辑态多出「保存到原列表」；「追加到本机资源库」和「另存为独立资源库」都会真实写盘并自动备份 |
| 设置 | 左侧板块列表 + 右侧**一整页**（点左侧滚到对应板块）；顶部可搜设置项，命中会全部列出来让你挑 |
| 窗口 | F11 进入真全屏并隐藏顶部标题栏（保留左侧导航栏），Esc 退出；无边框窗口**四边四角都能拖拽缩放，四周没有可见的白 / 黑边框** |
| 日志 | 终端与数据根的 `logs/` 双写，格式统一，历史归档最多 30 份 |

### 最近更新（R19）

- **部署页只管部署**：彻底移除与收藏相关的联动（原先「导入清单顺带导入收藏」整块删除）。
- **收藏页新增导出 / 导入**：导出为 JSON（`schema_version` + 全部收藏夹与条目）；导入时可选放进已有收藏夹或新建一个，导入后星标与列表同步刷新。
- **提交软件**：类别改成可编辑下拉（31 个内置类别 + 自定义，落盘前还原成规范名）；三语字段；资源浏览器双击进入编辑，「保存到原列表」写回原条目；「追加到本机资源库」「另存为独立资源库」都是真实写盘 + 自动备份；删掉「载入到制作资源」；预览与产出的滚动、阴影、间距和顶部分段留白统一。
- **无边框窗口**：四边四角可拖拽缩放，四周不再出现白 / 黑边框（不再内缩 WebView2，改为页面上 8 个透明热区调 `window.start_resize` 走系统原生缩放；DWM 描边已关闭）。
- **插件配置页深色主题**：宿主与 iframe 用 `postMessage` 同步主题 / 材质 / 强调色 / 语言，切换后立即生效，不再停在白底。
- **`/plugin` 只由「插件制作辅助」控制**：只开启 GCP-AI Agent 时输入 `/` 不会有任何提示或蓝色命令；两个开关不再互相连坐（只有一个方向：启用制作辅助时顺带启用 Agent）。
- **GCP-AI 输入框「润色」**：输入框右侧新增 AI 润色按钮，可在设置 → GCP-AI 关闭。
- **产品边界**：`.ToolsGCP/legal/` 下的《用户协议》《隐私政策及免责声明》两份 txt 在运行时注入 AI 提示词（正文**不写进代码**），改条款只改 txt。
- **云端资源来源**：自动从 GitHub Releases（含 beta）里按 semver 挑最新版本，下载其中的 `ToolsGCP-Resources.json`，校验后原子替换本地缓存；失败保留旧缓存并继续用本地资源库。
- **设置 → 资源来源**：说明改成与其它设置一致的提示（ⓘ），去掉多余分割线与「功能开发中」提示，并多一行云端资源库状态（版本 / 条数 / 更新时间，或失败原因）。
- **公告**：已读状态存在数据根的 `config/announcements.json`；删掉数据根或这个文件，所有公告会重新未读、重新推送。
- **日志**：级别统一 INFO / OP / WARN / ERROR / DBG（DBG 默认关）；启动环境、窗口几何、退出流程逐项记录。
- **宣传片 UI 素材导出工具开源**：独立单文件附属工具，**不属于程序本体**（见文末章节）。

### 最近更新（R20）

- **搜索页图标**：卡片图标改 eager 加载；加载失败自动重试 2 次（带缓存破坏参数），仍失败才显示首字母，不再"要更新状态才恢复"。
- **窗口四角**：改回**圆润角**。白 / 黑角的真正来源不是圆角的抗锯齿，而是 pywebview `shadow=True` 留下的那 1px「玻璃条」（桌面色从窗口边缘透进来）→ 把 DWM 描边色改成贴近页面底色即可消掉；最大化时 DWM 自动忽略圆角，全屏时显式改回方角。拉伸热区方案不变。
- **插件**：`gcp-ai-agent` 显示名改为 **AI Agent**；两个内置插件作者改为 **Galen563**；启用「插件制作辅助」会一并启用 AI Agent，关闭 AI Agent 会一并关闭插件制作辅助（只开 Agent 不会反向开启制作辅助）。
- **收藏页**：导出前先弹窗勾选收藏夹（默认勾选默认收藏夹）；左侧操作面板重做为紧凑分组；定制页 / 收藏页卡片恢复随窗口宽度自适应。
- **部署页**：双击清单行直接进入该资源的详情页。
- **提交软件**：多语言字段常开（删除开关与其中的「名称」输入）；删除「退出编辑」按钮；三语仍从资源库 JSON 完整加载。
- **插件配置页**：Esc 返回插件列表；进入页面 / 配置页时开关、分段、导航指示标不再重播入场动画。
- **设置**：下载区去掉多余「资源来源」首行与分割线；云端资源库状态行最右侧加**重试图标**；关闭「开启GCP-AI」时隐藏该区其余内容；关闭「启用全局快捷键」时隐藏快捷键项；「存储位置」改为「配置存储」；「侧边栏指示Q弹效果」默认关闭；启动 / 动画区的子项缩进。
- **云端启动加载**：检测到云端模式时允许等它加载（单次 60 秒，失败最多重试 3 次），失败后回退本地并提示原因。
- **GitHub Releases 下载（新）**：有 GitHub 仓库的资源卡片 / 详情多一个 Releases 入口，弹窗列出全部 Release 与附件，点文件直接下载；文件名按平台 / 架构 / 扩展名智能匹配（Windows exe/msi、macOS dmg/pkg、Linux AppImage/deb/rpm、通用 zip/tar.gz/7z）；右下角出现下载小圆，点开是独立下载页（隐藏左侧栏，左上角返回 + 下载，右侧窗口按钮不变）。
- **GCP-AI 润色按钮**：移到输入框**内部右下角**，长文本换行也不会压住按钮。
- **宣传片 UI 素材导出工具**：取消缩放倍率（固定 1x 原生无损）；开始前可选主题 / 主题效果 / 强调色；每个页面 × 每个切换分页都额外导出一张**整程序整图**；素材范围扩大、运行速度优化（详见文末章节）。

## 项目结构

```
ToolsGCP.pyw                       主程序（双击运行）—— **web 版入口**（pywebview 壳 + webui/ 前端）
requirements.txt                   依赖（pywebview / bottle / pythonnet / Pillow / PyQt5）
README.md（简体中文，默认）/ README.zh-CN.md（English）/ README.zh-TW.md（繁體中文）
.ToolsGCP/desktop/                web 版桌面外壳（Python，只做装配，不含业务）
  shell.py                         窗口装配、启动时序、托盘 / 热键 / 退出闸门
  webhost.py                       本地 WSGI 服务：把 webui/ 与 .ToolsGCP 的资源喂给 WebView2
  api/                             window.pywebview.api 的各个域（app/window/i18n/log/shell/
                                   resources/favorites/settings/ai/clipboard）
  native/                          原生层：托盘、自绘圆角菜单、图标、DPI、剪贴板、窗口边框
.ToolsGCP/webui/                   前端（Vue3 运行时 + 手写组件，**无构建步骤**，改完刷新即生效）
  index.html                       单文件模板（所有页面段都在这里）
  js/app.js                        全部前端逻辑（经典脚本）+ js/icons.js 图标精灵
  css/                             variables / base / components / layout / animations / overlays
.ToolsGCP/                         ★ 所有程序文件（**资源目录**，不要删；运行数据在数据根，见下方）
  ToolsGCP-Resources.json          资源库（制作器按这个固定路径读写）
  logo.png                         程序图标 / 窗口图标
  images/                          图片资源
    icon/                          资源库里引用的图标（**原 .ToolsGCP/Icon，web 版已改名并移到这里**）
    posters/                       首页轮播海报
    qq/                            反馈页二维码
  modules/                         业务代码与语言文件（pymodels 的 core / utils + languages）
  plugins/                         内置插件（一个文件夹 = 一个插件；Web 版只读 manifest / config.html / lang）
  legal/                           产品边界文本：用户协议 / 隐私政策（运行时注入 AI 提示词，正文不进代码）
  config/                          运行期配置（实际写在**数据根**，见下方说明；首次运行自动建）
    toolsgcp_config.json           设置（含加密后的 API Key、接口地址、模型名称）
    favorites.json                 收藏夹
    deploy_config.json             部署清单
    plugins.json                   插件启用 / 禁用状态
    plugin_notes.json              插件卡片备注
    announcements.json             公告已读状态（删掉 = 全部重新未读）
    privacy_policy.json            隐私政策同意记录
    plugin_data/<插件id>/           插件自己的数据目录
    chats/                         GCP-AI 历史对话（每次对话一个 json）
    cloud/                         云端资源库缓存（资源库 json + 元数据）
  logs/                            运行日志与历史归档
.github/workflows/release.yml      GitHub Actions：打 v* 标签自动打包成 exe 并发布（文件头有说明）
py版本-已弃用仅作为参考项目，主体转为web版本/
                                   旧 PyQt5 单机版（**只读参考**，不参与运行）
项目资料-文档与开发测试/             设计文档、回归脚本、构建工具（不参与运行）
  tools/ToolsGCP_UI_Asset_Exporter.py  宣传片 UI 素材导出工具（**附属工具，不是程序本体**，见文末）
```

> **数据根（用户数据）和程序目录旁的 `.ToolsGCP` 是两回事。**
> 程序自己产出的配置 / 收藏 / 日志 / AI 对话 / 公告已读默认放在 `<用户主目录>\.ToolsGCP`（首次运行自动创建）；
> `<用户主目录>\ToolsGCP.json` 是**位置指针**，记录数据根在哪 —— 它固定在主目录，不随迁移移动。
> 可以在「设置 → 存储」里把数据根迁到任意位置（迁移的是数据根，不是程序目录）。
>
> 程序目录旁的 `.ToolsGCP/` 是**资源目录**：modules / images / 插件 / 资源库 / legal / logo。
> 它随程序发布、永远不搬、也不是配置目录；删掉它程序就跑不起来了（反过来说，删数据根只会重置
> 配置、收藏、日志和公告已读状态）。
>
> **图标路径变了**：`.ToolsGCP/Icon/` → `.ToolsGCP/images/icon/`；
> 规范 URL 是 `/res/image/icon/<文件名>`（`/res/icon/<文件名>` 保留为兼容别名）。
>
> 仓库里 `py版本-已弃用仅作为参考项目…/` 只留了 PyQt 的界面层（`interfaces/ ui/ widgets/`）、
> Qt 入口和历史备份；`pymodels` 的 **core / utils 仍然留在 `.ToolsGCP/modules/`**，
> 因为 web 版的业务逻辑（资源查询、收藏、设置、AI 会话、日志）全部复用它们。

## 技术点

程序本体是 **Python 桌面外壳 + 本地 HTTP 服务 + 无构建前端** 三层：Python 只负责窗口、托盘、热键和原生
能力，界面全部是 HTML / CSS / JS，业务算法复用同一套 `pymodels` 纯 Python 模块。

### 三层架构与 JS ↔ Python 桥

- **外壳**：`pywebview`（Windows 上就是 WebView2）+ 无边框自绘标题栏；托盘、全局热键、DPI、窗口边框
  补丁都在 `desktop/native/` 里直接用 Win32 API（ctypes / pythonnet）实现，不依赖 Qt。
- **本地服务**：`bottle` 写的小 WSGI 应用（`desktop/webhost.py`）把 `webui/`、`images/`、资源库和插件
  配置页喂给 WebView2；`window.pywebview.api` 的每个域（`resources` / `favorites` / `settings` / `ai` /
  `maker` / `plugins` …）就是 JS ↔ Python 的桥。
- **前端**：Vue 3 运行时（`vue.global.prod.js`，CDN 文件随仓库分发）+ 手写组件，**没有打包步骤** ——
  改完 `.ToolsGCP/webui/` 里的文件刷新窗口就生效。页面段、图标精灵、CSS 变量全部手写。
- **JSON 信封**：后端方法只返回可 JSON 序列化的 dict，约定 `{ok: true, ...}` / `{ok: false, error: "…"}`；
  前端统一走 `bridge.tryCall()`，**接口不存在时返回 `null`，调用方必须显式降级**（提示「接口未就绪」），
  绝不假装成功。业务字段叫 `success`，避免覆盖信封的 `ok`。

### 无边框窗口：能拖边缩放，但四周没有可见边框

`pywebview` 的 `frameless=True` 会把窗口变成 `WS_POPUP`：没有缩放边框、没有最大化吸附，也没有系统阴影。
`desktop/native/frame.py` 用三步把它补回来：

1. 把 `WS_THICKFRAME` 等样式加回去 → 系统重新提供四边四角的原生缩放手势；
2. 子类化窗口过程，在 `WM_NCCALCSIZE` 里返回 0 → 吃掉系统要画的边框，客户区重新铺满整个窗口；
3. 在 `WM_GETMINMAXINFO` 里把最大化尺寸钉到**当前显示器工作区** → 加了 `WS_THICKFRAME` 之后最大化不会
   再盖住任务栏；同时关掉 DWM 的窗口过渡动画与描边。

缩放热区放在**页面上**，而不是让 WebView2 内缩：`index.html` 里 8 个透明 `span`（四边 + 四角）接管
`pointerdown`，调用 `window.start_resize(direction)` → 原生 `WM_NCLBUTTONDOWN` 模态缩放，和拖动标题栏
是同一套系统循环。**为什么不内缩 WebView2**：内缩会在窗口四周留出一条父窗口底色带，而标题栏在毛玻璃 /
亚克力档下是半透明渐变，任何纯色都匹配不上 —— 用户看到的就是「白边 / 黑边 / 边框变粗」。现在 WebView2
铺满窗口，没有色带，手感仍然是原生的。

### 主题、材质与强调色

配色全部收在 `webui/css/variables.css` 的 CSS 变量里（深 / 浅两套 `--page` / `--text` / `--accent` …），
运行时只改 `<html>` 上的三个属性：

- `data-theme="dark|light"`：深 / 浅主题（「跟随系统」时由 `matchMedia` 解析后落成确定值）；
- `data-fx="mica|glass|acrylic"`：主题效果（云母 / 毛玻璃 / 亚克力），只换模糊、底噪与高光描边；
- `data-accent="blue|purple|orange"`：组件强调色。

插件配置页是 iframe：宿主在载入完成、切换主题 / 材质 / 强调色 / 语言时用 `postMessage` 把
`{type:'toolsgcp-theme', theme, fx, accent, language}` 推过去，插件页收到后立即改自己的 `<html>` 属性；
「读取父文档」只作为首帧兜底。这样深色主题下配置页不会停在白底。

### 数据与性能

- **搜索 / 筛选 / 排序 / 分组全部交给后端 `resources.query`**（算法唯一真源），前端不重写算法；卡片列表
  是自绘的**虚拟列表**，只渲染视口附近的行，窗口缩放时只重算一次行高。
- **收藏只有一个真源**（后端 `favorites.*`）：卡片星标、收藏页、详情页共用同一份状态，任何写操作后统一
  刷新；导出是带 `schema_version` 的 JSON，导入兼容「收藏夹数组 / codes 数组 / items 数组」多种写法。
- **云端资源来源**：`resources.cloud_status()` 只读本地缓存（不联网、不卡设置页），
  `resources.cloud_refresh(force)` 才真的去 GitHub 拉：先取 release 列表（含 beta），按 semver 选最新，
  再在附件里找 `ToolsGCP-Resources.json`，校验后**原子写**进数据根的 `config/cloud/`；失败保留旧缓存并
  继续用本地资源库，首屏只读缓存、后台线程按间隔检查。
- **公告已读**只存在数据根的 `config/announcements.json`：删掉数据根或这个文件 ⇒ 全部重新未读、下次启动
  重新弹窗；程序目录旁 `.ToolsGCP` 里的旧备份不会被反向迁移搬回来。

### 制作器的写盘与备份

所有写操作都走 `maker.*`：条目先过 `resource_schema.normalize()`，写盘用「临时文件 + `os.replace`」
原子替换；替换前把旧资源库复制成 `ToolsGCP-Resources.backup-<时间戳>.json`，只保留最近 20 份。
「保存到原列表」强制按载入时的 id / 编码写回，避免用户改了 id 之后被当成新条目追加；
「另存为独立资源库」会把图标一起复制到目标目录并改写 `icon`，不会写出一个图标悬空的 JSON。

### GCP-AI 的提示词分层

系统提示词分四层拼装（`modules/pymodels/core/ai/prompt.py`）：角色与内置知识 → 回复模式（简洁 / 标准 /
专业）→ 硬规矩（不输出代码、不复述问题、链接必须完整）→ 资源库清单（按关键词压缩，最多 120 / 40 条）。
`@资源(编码)` 会作为「就是这一条」的强指令；`.ToolsGCP/legal/*.txt` 两份协议正文在运行时读盘注入
（正文**不写进代码**，改条款只改 txt），让 AI 能说明触发了哪一条、为什么不能做。
输入框右侧的「润色」按钮是**独立的小请求**：只改措辞、不回答问题、不写入历史对话。

### 国际化与日志

- 文案在 `.ToolsGCP/modules/languages/{zh_CN,zh_TW,en_US}/` 下，**15 个模块 × 3 个单语言目录**
  （每个文件只放一种语言）；后端按「当前语言 → 简体中文 → 英文」回退，前端用同一份 bundle 渲染。
- 日志格式固定：`[时间] [级别] [中文分类|英文子类] 消息 键=值`；级别 INFO / OP（操作审计）/ WARN /
  ERROR / FATAL，DBG 默认关闭（开发者模式可开）；密钥类字段自动打码；启动环境、窗口几何、退出流程都
  逐项记录；历史归档按上限轮转。

## 运行环境

- Windows 10 / 11
- Python 3.10 以上（在 3.13 上测试）
- 运行依赖（`requirements.txt` 里一并装好）：

```bash
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

## 运行

```bash
python ToolsGCP.pyw
```

也可以直接在资源管理器里双击 `ToolsGCP.pyw`。要改资源库就在程序里打开「更多 → **提交软件**」（内置
资源制作器），不需要单独的 exe 或脚本。

## GCP-AI

内置的 AI 助手，**默认关闭**。到「设置 → AI」打开「开启GCP-AI」，右下角会出现一颗会缓慢流动的液态悬浮球。

### 怎么用

1. 点右下角的球（或按 `Ctrl+Caps`），右侧滑出聊天抽屉；
2. 在底部输入框里说人话，例如：
   - 「我想要一个能局域网传文件的工具」
   - 「有什么好用的录屏软件？」
   - 「minecraft 启动器有哪些？」
3. 它会拿你这句话去对照 ToolsGCP 的资源库，把命中的条目的**简介、分类、标签、官网和 GitHub** 给你。

`Enter` 发送，`Shift+Enter` 换行，`Esc` 收起抽屉（在历史对话页按 `Esc` 是**先返回聊天**，
再按一次才收起）。抽屉打开时那颗球会隐藏，收起后自动回来。

顶栏三个按钮：

| 按钮 | 作用 |
|---|---|
| `＋` | 开一个新对话（也可以按 `Ctrl+J`） |
| 🕘 | 打开**历史对话**页：每条对话一张卡片，卡片里是对话内容（超长用 `…` 省略），右下角是**开始时间 → 结束时间**，越早的对话越靠下；点任意一张就把那次对话载回来 |
| `×` | 收起抽屉（`Esc` 同样） |

历史页左上角是一个**左箭头按钮**（没有文字），点它或按 `Esc` 返回聊天。

每次重新打开 ToolsGCP 都会自动开一个新对话，之前的对话都留在历史里（存在
`.ToolsGCP/config/chats/`，一次对话一个 json）。

### 配置

| 设置在 | 说明 | 默认 |
|---|---|---|
| 设置 → API Key → **服务商** | 选 DeepSeek / OpenAI / Claude / Grok / Kimi / 通义千问 / 硅基流动 / 自定义。选完下面的模型和接口地址**自动填好** | DeepSeek |
| 设置 → API Key → **模型选择** | 纯下拉框：只列该服务商支持的模型（清单随服务商切换）。V4.1-Flash 的 API 模型名官方叫 `deepseek-flash`，程序按官方文档内部自动转换，界面显示/选择用 `deepseek-v4.1-flash` 即可 | `deepseek-v4.1-flash`（默认） |
| 设置 → API Key → **模型名称** | 可自定义任意模型名（本地/中转/自建网关的模型都填这里） |
| 设置 → API Key → **接口地址** | OpenAI 兼容格式的地址，通常以 `/v1` 结尾。跟着服务商自动填，也可以自己改 | `https://api.deepseek.com/v1` |
| 设置 → API Key → **API Key** | 你的密钥。**用 Windows DPAPI 加密后存在 `config/toolsgcp_config.json` 的 `api_key_enc`**，密文换台电脑解不开 | 空 |
| 设置 → AI → **回复模式** | 控制回答的**长度和细节**，见下表 | 标准 |
| 设置 → AI → **上下文范围** | 每次提问带多少历史对话给模型：整个会话（默认，记忆最长）/ 最近 10 / 20 / 30 轮 | 整个会话 |
| 设置 → 模型调用 → 限制 token 输出 | 限制单次回答的最大长度 | 关闭 |

内置服务商与常用模型（都可以自己改）：

| 服务商 | 接口地址 | 常用模型 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-v4.1-flash`（默认；内部按官方文档转成 API 名 `deepseek-flash`）、`deepseek-v4-pro` |
| OpenAI | `https://api.openai.com/v1` | `gpt-5.1`、`gpt-5.1-mini`、`gpt-4.1` |
| Anthropic（Claude） | `https://api.anthropic.com/v1` | `claude-sonnet-4-6`、`claude-opus-4-1`、`claude-haiku-4-5` |
| xAI（Grok） | `https://api.x.ai/v1` | `grok-4`、`grok-4-fast`、`grok-3` |
| Kimi | `https://api.moonshot.cn/v1` | `kimi-k3`、`kimi-k2.7-code`、`kimi-k2.6` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3-max`、`qwen-plus`、`qwen-flash` |
| 硅基流动 | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3`、`Qwen/Qwen3-8B` 等（以控制台为准） |
| 自定义 | 自己填 | 本地 Ollama / vLLM / one-api / 中转站等，填到 `/v1` 为止 |

> 模型名变化比软件发版快，所以两个框都是**可编辑**的：清单里没有的直接敲进去。
> OpenAI / Claude / Grok 的官方接口在国内多数网络下需要自备网络环境，
> 连不上时会给出明确的错误提示（认证失败 / 频率限制 / 超时 / 连不上分别提示）。

### 每条消息可以做些什么

每条气泡下面都有一条小按钮栏，用户消息靠右、AI 消息靠左：

| 按钮 | 在哪 | 作用 |
|---|---|---|
| ✎ | 用户消息（左） | **重写**：把这条消息放回输入框，改完重发；旧回答会被丢掉，旧版本仍可翻回查看 |
| ⧉ | 两边都有 | **复制**这条消息的纯文本 |
| ⟳ | AI 消息（右） | **重新生成**：用同一个问题再问一次；点下去按钮会变成转圈的进度环 |
| ‹ 2/3 › | 中间 | 同一个位置有**两个以上版本**时出现（重写过 / 重新生成过）。左右箭头翻版本，到头部/尾部时对应箭头变灰；载入历史对话时默认翻到最新那一版 |

> 版本信息**只存在内存里**，`config/chats/*.json` 里永远只保存当前选中的那一版，
> 老文件的格式没有任何变化。

### @ 提到某条资源

搜索页和收藏页的**每张资源卡片右下角多了一个 @ 按钮**（气泡图标）：

- 点它 → 自动打开 AI 抽屉，并在输入框**末尾**追加 `@名称(资源编码)`，例如 `@LocalSend(TG-000001)`；
- 输入框里已有内容时是**追加**在末尾，不会覆盖你已经打的字；
- 接着补一句话发出去，AI 就知道你说的是库里那一条，回答会围绕它展开（不是另找别的资源）；
- 也可以自己手打 `@OBS` 这种形式。

### 回复模式

| 模式 | 回答长什么样 |
|---|---|
| **简洁** | 最多 4 行，只给结论：哪个 + 干什么 + 一个链接。不要分类、优缺点、对比 |
| **标准** | 6 行以内：推荐（名称 + 一句话）+ 官网链接 + 一个备选 |
| **专业** | 10 行左右：先结论，再关键差异（适用场景、是否开源、有无中文界面…），最后 1~2 个备选 |

三种模式共同遵守的硬规矩：**绝不输出代码**（代码块、命令、脚本、配置片段一律不给）、
不用表格和标题、不复述你的问题、不写客套话，链接必须是完整 `http(s)` 地址。

**没配 API Key 会怎样**：可以直接发消息，但它不会去调模型，而是在气泡里给一句短提示
「还没配置 API Key，填好就能聊。」，其中蓝字下划线的 `API Key` 可以点 —— 点了会跳到设置页，
并把那张卡片闪两下指给你看。配好保存后回来就能正常聊。

**API Key 走哪条路**：程序直接用你的密钥请求你填的那个接口地址，中间不经过任何第三方服务器；
ToolsGCP 只把**资源库清单和你的对话**放进上下文，不会上传你的本地文件。

## 快捷键

| 按键 | 作用 |
|---|---|
| `Ctrl+Q` | 在任何程序里呼出搜索框（可在设置里改） |
| `Ctrl+Caps` | 在任何程序里呼出 GCP-AI，直接把光标放进输入框（可在设置里改） |
| `Ctrl+J` | 开一个新的 AI 对话（只在 ToolsGCP 窗口里生效） |
| `Enter` / `Shift+Enter` | AI 输入框：发送 / 换行 |
| `Ctrl + 左键` | 点 AI 回答里的链接才跳转（在浏览器里打开）；不按 Ctrl 单击不会误触 |
| `F11` | 进入 / 退出全屏（会隐藏顶部标题栏） |
| `Esc` | 退出全屏；AI 抽屉打开时先收起抽屉（历史对话页则是先返回聊天） |

## 插件

一个插件就是 `.ToolsGCP/plugins/` 下的一个文件夹，启动时自动扫描 —— **一个文件夹 = 一个插件**。

Web 版和旧 PyQt 版看插件的方式不一样，这一点先说清楚：

- **只读 `manifest.json`（+ `lang/` + 可选的 `config.html`），绝不 import 插件的 Python**。
  `app.py` 那套 `create_page(context) → QWidget` 是 PyQt 版入口，Web 版不加载它 ——
  主线程里 import PyQt5 会让 WebView2 崩溃，所以 Web 版的插件界面用 **HTML** 写。
- 插件的开关、图标、描述、配置界面都来自 manifest；开关本身写进**主程序设置**（见 `enabled_setting`）。

```
.ToolsGCP/plugins/
├─ README.md          py 版插件的完整文档（create_page / context，存档参考）
├─ _template/         py 版开发者模板（下划线开头，**永远不会被加载**）
├─ plugin-showcase/   示例（同样不会被加载）
├─ gcp-ai-agent/      内置插件：manifest + config.html + lang/
├─ gcp-plugin-maker/  内置插件：manifest + config.html + lang/ + core/
└─ 我的插件/          你要写的：manifest.json 必须有，其它按需
```

> `_template` / `plugin-showcase` / `_` 或 `.` 开头的目录都是保留目录
> （`plugin_manager.RESERVED_DIR_NAMES`）：不扫描、不进插件列表、不建数据目录，文件原样保留。

### 最少的插件

一个 `manifest.json` 就能被识别：

```
.ToolsGCP/plugins/我的插件/
├─ manifest.json     插件基本信息（**必须**）
├─ config.html       配置界面（可选；写了才会出现「配置界面」按钮）
└─ lang/             三语文案（可选）
   ├─ zh_CN.json
   ├─ zh_TW.json
   └─ en_US.json
```

```json
{
  "id": "my-plugin",
  "name": "我的插件",
  "version": "1.0.0",
  "author": "你的名字",
  "description": "一句话说明",
  "enabled_setting": "my_plugin_enabled",
  "config_page": "config.html",
  "builtin": false
}
```

放进 `.ToolsGCP/plugins/` → 打开 ToolsGCP →「插件」→「重新加载」就出现了。
改完 `manifest.json` / `config.html` 再点一次「重新加载」，不用重启。

`manifest.json` 字段（Web 版实际读取的）：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 建议填 | 插件唯一标识，2~40 位小写字母/数字/`-`/`_`；留空就用文件夹名；重复时只有先扫到的生效 |
| `name` | 建议填 | 卡片上显示的名字；可以写字符串，也可以写多语言字典 `{"简体中文": "…", "English": "…"}` |
| `version` | 否 | 显示成 `v1.0.0`；留空不显示 |
| `author` | 否 | 显示在版本旁边 |
| `description` | 否 | 卡片上的两行说明；同样支持多语言字典 |
| `entry` | 否 | py 版入口文件名（默认 `app.py`）。**Web 版不加载它**，保留字段是为了同一份插件目录还能给 py 版用 |
| `icon` | 否 | 相对插件目录的图片路径，如 `assets/icon.png`（Web 版按 `/res/plugins/<id>/<icon>` 取图；FluentIcon 名字是 py 版写法，Web 版不认） |
| `enabled_setting` | 否 | 声明由**哪个设置键**控制这个插件的开关，例如 `gcp_plugin_maker_enabled`。**没写这一项的插件在插件中心里不能拨开关**（点了只会提示没有开关配置） |
| `config_page` | 否 | 相对插件目录的 HTML（如 `config.html`）。写了插件卡片上的「配置界面」按钮才可点，界面在右侧内容区用 iframe 承载 |
| `default_disabled` | 否 | 没有 `enabled_setting` 时用来决定默认开关状态（内置插件默认 `true`） |
| `builtin` | 否 | 内置 / 受保护：卡片垃圾桶置灰，后端也拒绝删除（官方插件的 id 还额外写死在 `desktop/api/plugins.py`） |
| `companion` | 否 | 「搭子」插件 id：**启用我这个插件时顺带启用它**（反向不连坐） |
| `generated_by` | 否 | 由哪个插件生成（目前是「插件制作辅助」）；停用生成者时，它生成的插件一起停用 |

文件名必须是 `manifest.json`（很旧的 `plugin.json` 也还认，但新插件请用 `manifest.json`）。
文件夹名以 `_` 或 `.` 开头会被跳过；**没有 manifest.json 的文件夹在插件中心里看不到**
（前端全靠 manifest 渲染卡片），修好文件再点「重新加载」即可。

### 正式开发用模板

Web 版最靠谱的参考是**内置插件自己**，直接抄它们的结构：

| 参考 | 里面有什么 | 适合抄什么 |
|---|---|---|
| `gcp-ai-agent/` | `manifest.json` + `config.html` + `lang/*.json` | 一个完整的配置页：总开关、逐项开关、统计、最近动作、主题同步 |
| `gcp-plugin-maker/` | 上面这些 + `core/`（纯标准库 Python） | 需要后端参与时的写法：后端用 `importlib` 把 `core/` 当合成包加载（**仅内置插件走这条通道**） |
| `_template/` | py 版多文件模板（`app.py` / `ui/` / `core/`） | 只有给 PyQt 版写插件时才有用；Web 版不加载它 |

> 为什么 `_template` 和 `plugin-showcase` 不会被加载：它们在下划线/保留名单里，
> 只当"照着写"的模板，不出现在列表、不能启停、也没有数据目录。

### 配置页能拿到什么

Web 版**没有** `create_page(context)` 这个入口，插件界面就是 `config.html`（一个普通网页）。
它和主程序同源（都由本地 WSGI 服务出页面），所以能拿到这些：

| 能用的东西 | 说明 |
|---|---|
| 自己的文件 | 相对路径直接读：`manifest.json`、`lang/zh_CN.json`、`assets/icon.png` … |
| 主程序接口 | `parent.pywebview.api.<域>.<方法>(…)`。pywebview 只往顶层框架注入 `window.pywebview`，iframe 里必须回退到 `parent`；`settings.get/set`、`resources.*`、`ai.*` 等域和主界面用的是同一套 |
| 主程序事件 | `parent.ToolsGCP.on('settings-changed', (payload) => …)`（后端广播时才有；没有广播就自己轮询兜底 —— 内置两个插件就是"事件 + 5 秒轮询"） |
| 主题同步 | 宿主在 iframe 载入完成、切换主题 / 材料 / 强调色 / 语言时 `postMessage` 一条 `{type:'toolsgcp-theme', theme, fx, accent, language}`；配置页收到后改自己的 `<html data-theme data-fx data-accent>` 即可（首帧也可以直接读 `parent.document.documentElement` 的 `data-theme`，单独打开时退回 `matchMedia`） |
| 窗口尺寸 | 正常 `window.innerWidth/innerHeight`，页面在右侧内容区里自适应 |

⚠️ Web 版**没有**给第三方插件暴露"插件专属可写目录"（py 版的 `context.data_dir` / `context.log`
在 Web 版不存在）。需要存数据时，优先用主程序已经暴露的设置项或接口；不要往插件目录里写文件
（那是只读资源区，升级 / 重装会被覆盖）。

### 多语言

文案放 `lang/zh_CN.json`、`zh_TW.json`、`en_US.json`，平铺键值对：

```json
{
  "title": "我的插件",
  "greet": "你好，{name}！"
}
```

取词顺序是 **当前语言 → 简体中文 → 英文 → 键名本身**，找不到不会显示空白。
`_template/core/i18n.py` 里有一个现成的 `I18n` 类可以照着写（带 `{占位符}` 替换）：

```python
i18n = I18n(plugin_dir, "zh_TW")
i18n.t("title")              # → 我的外掛 / 我的插件 / My Plugin
i18n.t("greet", name="小明")  # → 你好，小明！
```

manifest 里的 `name` / `description` 也可以直接写成多语言字典（键用语言名
`简体中文` / `繁體中文` / `English`，也兼容 `zh_CN` 这类 locale 名）。
主程序自己的界面文案在 `.ToolsGCP/modules/languages/{zh_CN,zh_TW,en_US}/`，
**插件文案不要往那里加**，放自己的 `lang/`。

### 能用什么库

- 插件界面 = **普通 HTML / CSS / JS，没有构建步骤**：可以手写，也可以把任意前端库
  放进插件目录自己引用（别引 CDN，离线会白屏）。
- **不要用 PyQt5 / qfluentwidgets**：Web 版根本不执行插件的 Python 入口，写了也不会跑；
  而且主线程 import PyQt5 会让 WebView2 崩溃。
- 例外：内置 `gcp-plugin-maker` 的 `core/` 是纯标准库 Python，由后端按需加载
  （`importlib` + 合成包名）。第三方插件目前**没有**这条通道。

### 管理 / 调试

ToolsGCP 左侧栏「插件」页（也可以在「更多 → 插件」打开）：

| 项目 | 作用 |
|---|---|
| **重新加载** | 重新扫描 `.ToolsGCP/plugins/`，改完 manifest / config.html 不用重启 |
| **打开插件目录** | 直接打开 `.ToolsGCP/plugins/` |
| **我想开发** | 弹窗里是简版约定：manifest 字段、三语语言包、`enabled_setting`、`config_page` |
| 搜索框 | 按名称、id、作者筛插件 |
| 排版按钮 | 井字 / 列表之间切换 |
| 卡片开关 | 只对声明了 `enabled_setting` 的插件可用；写入的就是那个设置项，设置页 / 联动逻辑共用同一个键 |
| 配置界面按钮 | 只有声明了 `config_page` 才可点；在右侧内容区用 iframe 打开，深色主题 / 材质 / 强调色 / 语言会和主程序同步 |
| 删除按钮 | 内置 / 受保护插件置灰不可点；可删的会二次确认，且只删 `plugins/` 第一层的真实目录 |

几个联动规则（都是"按 manifest 声明走"，不是写死某个插件名）：

- **开关联动**：`enabled_setting` 那个键变化时，插件卡片和设置页读的是同一份设置；
- **搭子**：启用 A 时如果 A 的 `companion` 是 B，会顺带启用 B（反过来不会）；
- **生成物**：停用"生成者"插件时，`generated_by` 指向它的插件一起停用；
- **`/plugin` 只由「插件制作辅助」控制**：只有 `gcp_plugin_maker_enabled` 为开时，GCP-AI 输入框敲 `/`
  才会出提示、`/plugin` 才会变蓝并发给模型；只开 GCP-AI Agent 不算。

调试与分发：

- 配置页就是普通网页，改完刷新（重新点「重新加载」或重新打开配置界面）就生效；
  后端 / 主程序日志在数据根 `logs/`（默认 `<用户主目录>\.ToolsGCP\logs`）。
- 插件写崩了不会影响主程序：manifest 解析失败时插件中心看不到它（修好后重新加载即可）；
  配置页里的 JS 报错只影响那个 iframe。
- **分发 / 卸载**：把插件文件夹打包成 zip（别带 `__pycache__`），对方解压到 `.ToolsGCP/plugins/`；
  卸载就删文件夹。

> **安全**：插件配置页就是网页，能调用主程序暴露给前端的接口。只装你自己写的或完全信任的插件，
> 装之前看一眼它的 `config.html`。

py 版插件（`create_page(context)`、`context` 全部成员、`on_show()` 钩子等）的完整文档见
[`.ToolsGCP/plugins/README.md`](.ToolsGCP/plugins/README.md)；那份文档针对 PyQt 版，
Web 版请以本节为准。

## 资源库格式

`.ToolsGCP/ToolsGCP-Resources.json` 存放所有资源条目：

```json
{
  "schema_version": "2.0.0",
  "metadata": {
    "name": "ToolsGCP Resources",
    "description": "ToolsGCP 资源索引文件",
    "icon_dir": ".ToolsGCP/Icon",
    "updated_at": "2026-09-21T00:40:14+08:00"
  },
  "resources": [
    {
      "id": "localsend",
      "code": "TG-000001",
      "name": "LocalSend",
      "category": "工具",
      "tags": ["工具", "传输"],
      "icon": "localsend.png",
      "url": "https://localsend.org/",
      "github": "https://github.com/localsend/localsend",
      "description": "跨平台局域网文件传输工具……",
      "listed_at": "2026-09-21 00:40:14"
    }
  ]
}
```

字段说明：

| 字段 | 必填 | 含义 |
|---|---|---|
| `id` | 是 | 唯一标识，只能用小写字母 / 数字 / 连字符 |
| `name` | 是 | 显示名称 |
| `code` | 否 | 自动分配的唯一编码（`TG-000001`）；部署清单靠它指代程序 |
| `category` / `tags` | 否 | 搜索页的分组与筛选标签 |
| `icon` | 否 | 图标文件名，位于 `metadata.icon_dir` 目录下 |
| `url` / `github` / `download_url` / `author_url` / `chat_url` | 否 | 卡片上对应按钮的跳转地址 |
| `description` | 否 | 一句话简介：卡片上显示它，详情页头部那一行小字也用它 |
| `intro` | 否 | 应用介绍：详情页「应用介绍」区块的正文，比 `description` 详细；卡片和列表都不显示。留空时详情页退回显示 `description` |
| `supplement` | 否 | 补充说明：卡片不显示，详情页「应用介绍」里接在正文后面另起一段 |
| `systems` | 否 | 适用系统，多选：`全平台` / `Windows` / `macOS` / `Android` / `iOS` / `Linux` / `web` / `其他`；搜索页「适用系统」筛选用它，详情页「详细信息」按它出一行 |
| `architectures` | 否 | CPU 架构，多选：`x64` / `x86` / `arm64` / `arm` / `Apple Silicon` / `其他`；同上 |
| `listed_at` | 否 | 上架时间（`年-月-日 时:分:秒`），「更新时间」筛选按它判断；详情页「详细信息」显示到分钟 |

除 `id` 和 `name` 外全部可以省略。主程序不会因为多出来的字段报错，制作器也不会把
它不认识的字段删掉，所以可以放心加自己的键。

### 资源详情页怎么用这些字段

点搜索页的卡片进入详情页，版面从上到下是：

| 区块 | 数据来源 |
|---|---|
| 工具栏 | 返回 / 收藏（不变） |
| 头部（原样保留） | `icon`、`name`、`code`、`description`、官网 / GitHub / 作者 / 聊天 按钮；本次新增一行 `tags` 标签 |
| **应用介绍**（新增） | `intro` 作为正文（没有 `intro` 的老条目退回用 `description`）；`supplement` 有内容就接在下面另起一段 |
| **详细信息**（新增） | 键值表，依次是 `systems` → `architectures` → `category` → `listed_at` → `url` → `github` |

两条约定：

1. **有值才渲染**：某个字段不存在或为空，对应那一行**整行不出现**，不会显示「未知 / --」。
   所以 `systems: []` 的条目，详情页自然就比别的条目短一截，这是预期行为。
2. **只加不改**：头部那套（图标、名称、编码、简介、四个链接按钮）保持原样，
   两个新区块是接在它下面的；头部那四个按钮的文案也没有改动。

`software version` / `file size` 目前**不做**：资源库里没有这两项的事实数据，硬加只会得到
一排「未知」。以后要加，在 `resource_detail_interface.py` 的 `DETAIL_ROW_DEFS` 里插一行即可。

## 资源制作器

入口只有一个：主程序里左侧栏「更多 → **提交软件**」，写完直接进资源库（没有单独的 exe 了）。

分四页：

1. **制作资源** —— 表单页。只有**名称**和**标识 id** 必填，其它留空就不会写进 JSON；
   简介最多 100 字，更长的内容放进「补充」框。类别是**可编辑下拉**：31 个内置类别 +
   自定义输入（落盘前会还原成规范名，避免出现「工具 / 工具 」两个类别）；名称 / 简介 / 补充
   都支持**三语字段**（简中 / 繁中 / 英文），三种语言写在同一份数据里。
2. **浏览 / 资源库** —— 整库表格。**双击**一行进入编辑（不是就地改单元格），编辑态下多出
   「**保存到原列表**」——按载入时的 id / 编码写回原条目，不会产生重复条目，也不动原上架时间；
   双击**图标**那一格可以换图片，图片会自动存进 `.ToolsGCP/images/icon` 并改成应用名。
3. **批量合成** —— 把一份或多份投稿 `resource.json` 合进本地资源库，或者把多个文件合成一份新 JSON。
4. **使用说明** —— 程序内置的手册。

写盘有两个落点：**追加到本机资源库**（写 `.ToolsGCP/ToolsGCP-Resources.json`）和
**另存为独立资源库**（系统「另存为」对话框选目录，JSON 与图标一起复制过去）——两者都是真实写盘，
不是「导出一份 JSON 让你自己放回去」。

### 图片（图标）处理

- 导入图片会立刻复制进资源库的图标目录。
- 不管原图下载下来叫什么，都会被改成你填的**名称**（`LocalSend` → `LocalSend.png`）；
  之后再改名称，文件也会跟着改名。
- 如果这个名字已经被**别的**资源占用，会自动加 `-2`、`-3`，绝不覆盖别人的图；
  换自己的图则直接覆盖自己那一份。
- 每次操作都会在磁盘上核对一遍，JSON 里写的永远是真实存在的那个文件名。

### 备份

每次写盘前，当前资源库会复制到同目录下的
`ToolsGCP-Resources.backup-<时间戳>.json`，只保留最近 20 份。
写盘是原子操作（先写临时文件再替换），中途被打断也不会把资源库写坏。
资源库永远只有 `.ToolsGCP/ToolsGCP-Resources.json` 这一个文件，制作器不会另外生成一份。

## 日志

所有输出（终端 + 文件）格式统一（文件在**数据根**下，默认 `<用户主目录>\.ToolsGCP\logs`）：

```
<数据根>/logs/system_log.log         当前运行
<数据根>/logs/history/               历史归档（按上限轮转）
```

```powershell
Select-String -Path "$HOME\.ToolsGCP\logs\system_log.log" -Pattern '\[ERROR\]|\[OP   \]'
```

级别是 `INFO` / `OP`（操作审计）/ `WARN` / `ERROR` / `FATAL`，`DBG` 默认关闭（开发者模式可开）；
密钥类字段自动打码。详细格式与排查方法见
[`项目资料-文档与开发测试/docs/LOGGING.md`](项目资料-文档与开发测试/docs/LOGGING.md)。

## 宣传片 UI 素材导出工具（附属工具，不是程序本体）

> **边界先讲清楚**：这是仓库里的一个**独立附属工具**，**不属于 ToolsGCP 程序本体**，也不参与程序
> 运行。它不修改原程序、不读写用户数据，**删掉它对程序没有任何影响**。开源它是因为做宣传片 /
> 演示时需要一套干净的 UI 素材，手抠图成本太高。

- **位置**：单文件 [`项目资料-文档与开发测试/tools/ToolsGCP_UI_Asset_Exporter.py`](项目资料-文档与开发测试/tools/ToolsGCP_UI_Asset_Exporter.py)。
- **原理**：工具自带一个**只读**静态服务器（读 `.ToolsGCP/webui` 与资源库，并在内存里注入 mock
  的 `window.pywebview.api`），再用无头 Edge + CDP（DevTools 协议，纯标准库 WebSocket）逐页导航、
  给目标组件打标记、滚动到可见、量 `rect` / 阴影 / 祖先裁切，最后 `Page.captureScreenshot(clip)`
  精确截取**单个组件**；再用"黑底 / 白底各截一张 + 页面内 canvas 反预乘"得到**真透明 PNG**。
  圆角、文字、图标、边框、阴影、抗锯齿都是 Chromium 真实渲染结果，不是手工抠图。
- **依赖**：Windows + Microsoft Edge（系统自带）+ **Python 3.8+**；**只用标准库**。
- **用法**：

  ```bash
  python ToolsGCP_UI_Asset_Exporter.py                      # 交互式：问输出目录 / 主题 / 主题效果 / 强调色 / 页面
  python ToolsGCP_UI_Asset_Exporter.py --yes                # 全部默认（输出到 ./ToolsGCP-UI-Assets）
  python ToolsGCP_UI_Asset_Exporter.py --yes --themes both --out "D:/素材"
  python ToolsGCP_UI_Asset_Exporter.py --list               # 只列出会导出的页面/组件，不启动浏览器
  python ToolsGCP_UI_Asset_Exporter.py --yes --pages search,maker-form
  ```

  常用参数：`--themes dark|light|both`、`--fx mica|glass|acrylic|all`、`--accent blue|purple|orange|all`、
  `--pages`、`--viewport 1440x900`、`--no-auto`、`--max-per-page`、`--settle`、`--project` / `--edge`。
  **没有缩放倍率**（`--scale` 仅为兼容旧命令保留，会被忽略）：输出固定 1x 原生像素，无损。
  `--fx all` / `--accent all` 会为每个取值各导一套；此时输出多一层组合目录，
  如 `mica-blue/dark/<页面>/`、`screens/mica-blue/dark/<页面>/`。
- **输出结构**：

  ```
  <输出目录>/
  ├─ manifest.json                全局清单（组件 + 整图；名称 / 页面 / 尺寸 / 原始坐标 / 主题 / 文件）
  ├─ assets.csv                   同一份清单的表格版（Excel / 剪映对照用）
  ├─ README-使用说明.md            工具自动生成的说明（含剪映摆放方式与已知限制）
  ├─ <theme>/<page>/<组件>__<w>x<h>.png   单个组件（透明；backdrop-filter 组件另有 __opaque 版）
  ├─ <theme>/<page>/page.json             该页组件清单
  └─ screens/<theme>/<page>/<state>__full.png   **整程序整图**：每个页面 × 每个切换分页一张
  ```
- **样例素材**：仓库里带一份实际导出的样例子集（`项目资料-文档与开发测试/tools/exported-ui-sample/`：
  40 张组件透明 PNG + 12 张整程序整图 + 清单），先看样例就知道导出来长什么样。

- **覆盖范围**：24 个页面 / 状态（首页、搜索、筛选、详情、定制、收藏、公告、Github、反馈、日志、
  部署-导出模式、部署-部署模式、插件、提交软件四个分页、设置 12 个板块、AI 整页、AI 抽屉、
  标题栏 / 侧栏 / 更多菜单 / 下拉弹层 / 右键菜单 / 弹窗）。整图与组件都会按主题分别输出。
- **局限（工具会如实写进 manifest 的 `skipped` / `note`，不伪造）**：整页背景不是组件；
  `backdrop-filter`（云母 / 玻璃 / 亚克力）组件单独抠图会丢材质，所以同时给 `__opaque`（含页面背景）
  并在清单里标 `transparent: false`；远程图片 / 视频 / 轮播过渡帧、iframe 插件页、系统原生窗口边框与
  托盘菜单、原生右键菜单都不是 DOM，导不出来；动画中间态不导出（需要中间帧请录屏）。
