# 独立复核：tiez 条目性质（在线工具站 vs 桌面/移动客户端）

- 任务：task-5（owner: verifier-tiez）
- 复核对象：`tiez` / TG-000022 / name=Tiez / url=<https://tiez.name666.top/>
- 复核时间：本次会话
- 结论一句话：**tiez 不是在线工具站，判定为桌面 + 移动端剪贴板管理工具，`systems` 不应写 `["web"]`。**

## 0. 环境与取证方式说明（先声明方法学限制）

- `browser_open` 等浏览器工具在本会话**不可用**（provider electron 报 “no spawnable Electron binary”），因此本次全部取证走 `web_fetch`（HTTP 抓取）。
- 抓取到的内容**不是空壳**：`https://tiez.name666.top/` 返回 HTTP 200，且标题、导航、下载区文案均为**静态可读正文**，不存在“前端渲染抓不到正文”的情况。以下所有摘录均为真实抓取原文。
- 本机 hosts 文件把 `github.com` / `api.github.com` / `raw.githubusercontent.com` / `objects.githubusercontent.com` 等**全部指向 127.0.0.1**，第三方镜像（jsdelivr、ghfast、gitclone 等）也不通。因此**我无法直接打开任何 GitHub 页面**，这一点在下文“不确定的地方”中逐条标注。

## 1. 页面现状（标题 + 原文摘录）

### 1.1 英文首页 <https://tiez.name666.top/>（HTTP 200）

`<title>` 原文：

> TieZ Clipboard Manager for Windows and macOS | Clipboard History, Rich Text, WebDAV Sync

页面导航（原文）：

> Home / About / Thanks / Changelog / FAQ / Contact / 中文

首屏标语与平台行（原文）：

> Minimal, but never simplistic. Capture every spark and empower every paste.
> **Windows 10/11 macOS Android** Installer and Portable

### 1.2 中文首页 <https://tiez.name666.top/zh/>（HTTP 200）

`<title>` 原文：

> TieZ剪贴板管理工具 | Windows 与 macOS 剪贴板历史、富文本、WebDAV 同步

导航（原文）：

> 首页 / 关于 / 致谢 / 更新日志 / FAQ / 联系我 / English

首屏（原文）：

> 当然你也可以叫我贴之、贴汁
> 极简而不简单。捕捉每一份灵感，赋能每一次粘贴。
> **Windows 10/11 macOS Android** 安装版与便携版

### 1.3 下载区原文摘录（中英一致，逐字）

「选择下载版本」区块共 3 个卡片：

| 卡片 | 原文平台/架构行 | 原文产物与链接 |
| --- | --- | --- |
| Windows v0.3.3 推荐 · 安装版 | `Windows 10/11 · x64 · 约 4MB` | 直接下载 → `https://github.com/jimuzhe/tiez-clipboard/releases/download/v0.3.3/TieZ_0.3.3_x64-setup.exe` |
| Windows v0.3.3 免安装 · 便携版 | `Windows 10/11 · Portable · 约 5MB` | 直接下载 → `https://github.com/jimuzhe/tiez-clipboard/releases/download/v0.3.3/TieZ_0.3.3-portable.zip` |
| macOS v0.1.3 正式版 | `macOS · Apple Silicon / Intel · 约 6MB` | 原文：「支持 Apple Silicon (M1/M2/M3) 与 Intel 芯片。点击下载即可选择对应您的架构版本。」**直接下载/网盘下载链接均为 `javascript:void(0)` 占位符** |

移动端原文（正文段落，非下载卡片）：

> **同步增强**：移动端 App 现已发布！支持手机快速获取电脑剪贴板、手机复制自动同步至 PC，以及体验更好的文件传输。[立即了解 →](https://github.com/jimuzhe/tiez-mobile)

弹层原文（macOS 架构选择弹层）：

> 请根据您的电脑芯片类型选择下载版本：… 选择 Mac 芯片架构

### 1.4 关键否定证据：站内**不存在**“在线工具集合”任何痕迹

我逐页抓取了该站可访问的主要页面，**没有任何**“在线工具”“实用工具集合”“网页工具”栏目或文案：

| 页面 | 抓取结果 |
| --- | --- |
| `/` `/zh/` | 标题即 “Clipboard Manager / 剪贴板管理工具”；正文全部为剪贴板功能（历史记录、搜索标签、顺序粘贴、WebDAV 同步、局域网传输、AI 动作等） |
| `/zh/about.html` | 标题「关于 TieZ - 设计哲学与故事」；原文：「我们相信工具应该是隐形的。TieZ 建立在这样一个原则之上：您的剪贴板管理器应该在您需要时出现…」 |
| `/zh/qa.html` | 标题「常见问题」；全部为客户端安装/权限问答，如「Windows 说明：应用运行后会静默存放在系统托盘中」「下载 DMG 安装包后双击打开，将 **TieZ.app** 图标拖入右侧的 **Applications** 文件夹中」「未通过 Apple 开发者公证，初次安装需要手动授予权限」 |
| `/zh/changelog.html` | 标题「更新日志 - TieZ」；分「Windows 分支 / macOS 分支」，从 v0.1.1 迭代到 Windows v0.3.3（2026-04-05）与 macOS v0.1.3；macOS 条目原文含「同时发布 Apple Silicon 与 Intel 独立架构版本」「基于 Tauri 2.0 构建」 |
| `/zh/contact.html` | 标题「联系开发者 - TieZ」；邮箱 `tiez@name666.top`，含 B 站/QQ 群/抖音 |
| `/zh/clipboard-history.html` | 标题「剪贴板历史记录管理」；原文：「由于它是本地优先的剪贴板管理工具…」 |

**因此“实用工具集合网站，提供多种便捷在线工具”这句现有描述，与站点实际内容完全不符**——它不是“过时描述”，而是从未对应过的错误描述。

## 2. 官方发布渠道核对（含失败标注）

### 2.1 站点自述的官方渠道

- 首页导航含 `GitHub`，指向 **<https://github.com/jimuzhe/tiez-clipboard>**（原文链接）
- Windows 安装版/便携版**直接下载**指向该仓库 release 资产：
  - `releases/download/v0.3.3/TieZ_0.3.3_x64-setup.exe`
  - `releases/download/v0.3.3/TieZ_0.3.3-portable.zip`
- 移动端指向 **<https://github.com/jimuzhe/tiez-mobile>**
- 网盘镜像走夸克：<https://pan.quark.cn/s/784854c899d3>（安装版）、<https://pan.quark.cn/s/796f8663ba29>（便携版）；更新日志中 macOS 分支另给 Apple Silicon / Intel 各自的夸克链接（v0.1.3：`5f12cc3fcec9` / `5e7d844c5303`）

### 2.2 我实际做到的核对

| 核对项 | 做法 | 结果 |
| --- | --- | --- |
| 仓库是否存在 | hosts 屏蔽，`Invoke-WebRequest` 到 github.com 与全部镜像 | ❌ 全部失败（“基础连接已经关闭”“无法连接到远程服务器”）。**未能自行打开仓库** |
| 仓库是否真实存在（间接） | 搜索引擎索引 | ✅ 搜索结果中出现 `jimuzhe/tiez-clipboard`，标题摘录为「TieZ 是一款基于 Tauri 的跨平台剪贴板管理器 / A cross-platform clipboard manager with history, tags, sync, privacy protection, and fast daily workflows.」——与官网自述一致。另有 `kukemc/`、`SinclairLin/` 两个同名 fork，说明主仓库确实存在且被 fork |
| Gitee 是否有官方镜像 | `https://gitee.com/jimuzhe/tiez-clipboard` | ❌ 404「你所访问的页面不存在」，**Gitee 无该官方仓库** |
| CNB 是否有官方仓库 | 未检索到 tiez 相关 CNB 地址 | ⚠️ 未发现 |
| 发行产物名 → 平台/架构 | 站点链接的文件名 | `TieZ_0.3.3_x64-setup.exe` → Windows **x64** 安装版；`TieZ_0.3.3-portable.zip` → Windows **便携版（未标架构）**。与官网标注 `Windows 10/11 · x64` 自洽 |
| 发行产物**实际可下载性** | `HEAD` 请求两个 release 资产 URL | ❌ 因 github.com 被 hosts 屏蔽而失败。**未能验证资产真实存在**（仅能证实官网这样链接） |

### 2.3 关于第二个说法中「引用的下载页是否真实存在」

第二个说法（researcher-b）称官方下载提供 Windows 10/11 x64、macOS（Apple Silicon / Intel）、Android。逐条裁决：

| researcher-b 的说法 | 我的独立复核 | 判定 |
| --- | --- | --- |
| Windows 10/11 x64 | 官网中英文下载区均明写 `Windows 10/11 · x64`，附安装版与便携版直链 | ✅ **成立** |
| macOS（Apple Silicon / Intel） | 官网明写 `macOS · Apple Silicon / Intel`，原文「支持 Apple Silicon (M1/M2/M3) 与 Intel 芯片」；更新日志 macOS 分支 v0.1.0-beta 起「同时发布 Apple Silicon 与 Intel 独立架构版本」 | ✅ **成立**（但见下方⚠️：macOS 下载按钮是 `javascript:void(0)` 占位符） |
| Android | 官网首屏平台行**确实列出 Android**，并有「移动端 App 现已发布」段落 + `jimuzhe/tiez-mobile` 仓库链接；更新日志 Windows 分支含「手机快捷同步：支持 Android 下拉中心磁贴与图标长按菜单」 | ⚠️ **部分成立**：站方自称移动端已发布且点名 Android，但**下载区没有 Android 卡片、没有 APK/应用商店直链**，唯一落地页是被屏蔽的 GitHub 仓库 |
| 「不存在在线工具集合」 | 逐页抓取 7 个页面，无任何在线工具栏目/文案 | ✅ **成立** |

## 3. 裁决

### 3.1 tiez 的 `systems`

**裁决：不应写 `["web"]`，应写实际平台列表。** 现有描述「实用工具集合网站，提供多种便捷在线工具」应废弃。

建议取值（与 group-b 一致，我独立复核后认同）：

```json
"systems": ["Windows", "macOS", "Android"],
"architectures": ["x64", "Apple Silicon", "Intel"]
```

- `systems` 依据：官网首屏平台行 `Windows 10/11 macOS Android` + 下载区 3 卡片（Windows 安装/便携、macOS）+ 移动端段落。
- `architectures` 依据：
  - `x64` —— 官网标注 `Windows 10/11 · x64`，产物名 `TieZ_0.3.3_x64-setup.exe`。
  - `Apple Silicon` / `Intel` —— 官网标注 `macOS · Apple Silicon / Intel`；更新日志明写两套独立架构版本。注意 group-b 只写了 `Apple Silicon`，**漏了 Intel**，而官网明确同时支持 Intel，应予补上（Intel Mac 对应惯例写作 `x86_64`/`Intel`，本库其他条目用 `Intel`，故建议 `Intel`）。
  - **不写 `arm64`**：官网未提到 Windows on ARM / Android ABI，不要外推。
  - **不写 `x86`**：官网 Windows 端只给 x64，无 32 位。
- Android 的 CPU 架构：官网未标注 → **按规则留空，不要猜**。

### 3.2 建议的 40~100 字中文 `supplement`

推荐文案（**86 字**，含标点与拉丁串字符，已核对落在 40~100 区间）：

> 官网现为 TieZ 剪贴板管理工具，提供 Windows 10/11 x64 安装版与便携版、macOS（Apple 芯片与 Intel 双架构）以及 Android 手机端 App，支持历史记录、搜索标签、局域网传输与 WebDAV 云同步，不再是网页版在线工具集合。

备选（更短，**54 字**）：

> 这是一款剪贴板管理工具而非在线工具站：提供 Windows 10/11、macOS 与 Android 客户端，支持剪贴板历史、搜索标签与跨设备同步。

若需同时修正条目名称，建议 `name` 由 `Tiez` 调整为 `TieZ`（站点官方写法为 TieZ），但这属于 lead 的口径决定，我仅提示。

### 3.3 memreduct 官方来源

**结论（a）：`memreduct.org` 自述确实不是官网，而是粉丝站。** 原文两处：

- 首页 <https://memreduct.org/>：「Welcome to our **fan website** dedicated to the Mem Reduct utility – a real-time memory management tool…」
- 关于页 <https://memreduct.org/about-us/>：「This **fansite** is dedicated to the Mem Reduct utility!」

该站运营主体是 **UpdateStar GmbH**（Kreuzbergstr. 28, 10965 Berlin, Germany；Managing Directors: Frank Alperstaedt / Michael Ganss / Olaf Kehrer；HRB 83422），与作者 Henry++ 无关。所以 researcher-b「memreduct.org 自述是粉丝站，不算官方」这条**批评成立**。

**结论（b）：Mem Reduct 应引用的官方来源 URL。**

- 官方源码与发布渠道（**首选**）：<https://github.com/henrypp/memreduct> ／ Releases：<https://github.com/henrypp/memreduct/releases>
- 旁证（连粉丝站自己也这么指）：`memreduct.org/more-online-resources/` 原文把该仓库标为官方：「GitHub – henrypp/memreduct: **The official GitHub page** for Mem Reduct, offering the latest releases, source code…」
- ⚠️ **注意**：`memreduct.dev` **也不能当官方依据**。它页脚自述「Independent community resource; **not operated by the Mem Reduct author**」，尽管页头又写「Official resource at memreduct.dev」——**自相矛盾**。本报告不以它为依据（仅在下方作为“存在矛盾的二手说法”提示）。

## 4. 证据 URL 列表

**tiez（一手）**

1. <https://tiez.name666.top/> — 英文首页，HTTP 200，标题含 “TieZ Clipboard Manager for Windows and macOS”
2. <https://tiez.name666.top/zh/> — 中文首页，HTTP 200，标题「TieZ剪贴板管理工具」
3. <https://tiez.name666.top/zh/about.html> — 关于/设计哲学
4. <https://tiez.name666.top/zh/qa.html> — FAQ（托盘、DMG 拖入 Applications、辅助功能权限）
5. <https://tiez.name666.top/zh/changelog.html> — 更新日志（Windows 分支 / macOS 分支、Tauri 2.0、双架构）
6. <https://tiez.name666.top/zh/contact.html> — 联系开发者
7. <https://tiez.name666.top/zh/clipboard-history.html> — 功能页（“本地优先的剪贴板管理工具”）
8. <https://github.com/jimuzhe/tiez-clipboard> — 站点自述官方仓库（**本机无法访问**，仅站点链接 + 搜索索引证实）
9. <https://github.com/jimuzhe/tiez-mobile> — 站点自述移动端仓库（**本机无法访问**）
10. <https://pan.quark.cn/s/784854c899d3>、<https://pan.quark.cn/s/796f8663ba29> — 站点标注的网盘镜像（安装版/便携版）
11. <https://gitee.com/jimuzhe/tiez-clipboard> — 实测 404，无官方 Gitee 镜像

**memreduct（一手）**

12. <https://memreduct.org/> — 自述 “fan website”
13. <https://memreduct.org/about-us/> — 自述 “fansite”，运营方 UpdateStar GmbH
14. <https://memreduct.org/more-online-resources/> — 自述 GitHub `henrypp/memreduct` 为 “The official GitHub page”
15. <https://memreduct.org/mem-reduct-download/> — 粉丝站自托管安装包链接 `memreduct.org/files/memreduct-3.5.2-setup.exe`（非官方分发，建议勿引用）
16. <https://github.com/henrypp/memreduct> ／ <https://github.com/henrypp/memreduct/releases> — 建议引用的官方来源
17. <https://memreduct.dev/> ／ <https://memreduct.dev/download.html> — 独立第三方站，自述 “not operated by the Mem Reduct author”，**不作为官方依据**

## 5. 不确定的地方（如实标注，勿当成已证实）

1. **GitHub 全程未能访问。** 本机 hosts 将 `github.com`、`api.github.com`、`raw.githubusercontent.com`、`objects.githubusercontent.com` 等全部指向 `127.0.0.1`，第三方镜像亦不通。因此：
   - 我**没有**亲眼看到 `jimuzhe/tiez-clipboard` 与 `jimuzhe/tiez-mobile` 的仓库正文；
   - 我**没有**看到任何 release 资产列表，**无法确认** `TieZ_0.3.3_x64-setup.exe` / `TieZ_0.3.3-portable.zip` 实际存在（仅确认官网这样链接）。
   - 该仓库存在性由「官网链接 + 搜索引擎索引到该仓库及其两个 fork」间接支持，属**较强但非一手**的证据。
2. **macOS 下载链接是占位符。** 官网中英文的 macOS「直接下载」「网盘下载」均为 `javascript:void(0)`，真实下载需靠弹层 JS 或走更新日志里的夸克链接。因此“macOS 有官方分发的二进制”在站方文字上成立，但**我没能取到任何一个有效的 macOS 直链**。
3. **Android 只有文字，没有下载入口。** 官网首屏列 Android、正文称移动端已发布并链到 `tiez-mobile`，但**下载区没有 Android 卡片、没有 APK / Google Play / 应用商店链接**。所以 `systems` 收 `Android` 依赖站方自述 + 该仓库，我无法独立验证 APK 的实际分发；如 lead 口径只认“官网可下载的产物”，Android 可能需降级处理。iOS 官网完全未列出，**不应写入**。
4. **`name` 大小写**：条目现为 `Tiez`，站点官方写法为 `TieZ`。是否改属 lead 口径。
5. **memory/内存清理类功能的站点描述存在夸大风险**：macOS 版 `/zh/qa.html` 明确「未通过 Apple 开发者公证」，且站点自述杀软误报原因含“全局键鼠钩子与输入模拟”。这与条目质量无关，仅提示 supplement 不要替它背书“安全”。
6. **关于 researcher-b 的 memreduct 架构结论，我发现一处无法裁定的矛盾**（供 lead 注意，不影响本任务两条结论）：
   - researcher-b 的 note 依据 `henrypp/memreduct` README 写「Windows 7, 8, 8.1, 10, 11 (64-bit/ARM64)」，并称**不支持 32 位**；
   - 但我抓到的 `memreduct.org` 与 `memreduct.dev` 都写支持 **Windows XP SP3 及更早起的 32 位与 64 位**（`memreduct.dev` 的 Download 页表格：「Platform: Windows XP SP3 and newer (32-bit and 64-bit)」，同时又写「Win 7-11」，**自身也不一致**）。
   - 由于 GitHub README 我打不开、而这两个站点都**不是官方来源**，我**无法裁决 64-bit/ARM64、是否含 32 位**这一点。若该结论要进入资源库，建议先由能访问 GitHub 的人核对 README 的 System requirements 原文。
7. 抓取时站点版权年为 2026、更新日志最新为 Windows v0.3.3（2026-04-05），说明站点**活跃维护中**；本次结论对“当时快照”有效，日后站点若改版需重核。

## 6. 给 lead 的一句话摘要

- **tiez**：官网现为「TieZ 剪贴板管理工具」官网（标题即 Clipboard Manager），下载区明确给 Windows 10/11 x64、macOS（Apple Silicon/Intel），移动端自称 Android；**站内不存在任何在线工具集合**——现有描述错误，`systems` 应写 `["Windows","macOS","Android"]` 而非 `["web"]`。
- **memreduct**：`memreduct.org` 首页与关于页均自述 “fan website / fansite”（运营方 UpdateStar GmbH），**确认非官方**；官方来源应引用 <https://github.com/henrypp/memreduct>（其 releases 页取版本与产物），`memreduct.dev` 亦自述非作者运营，同样不能当官方。
- **拿不准的**：GitHub 在本机被 hosts 屏蔽，我全程没能打开仓库 → 无法一手核对 tiez release 资产与 `tiez-mobile` 的 Android 交付物，也无法裁决 memreduct 的 32 位/ARM64 架构口径。
