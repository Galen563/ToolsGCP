<div align="center">

# ToolsGCP

<img src=".ToolsGCP/logo.png" alt="ToolsGCP logo" width="140">

[English](README.md) ｜ **简体中文** ｜ [繁體中文](README.zh-TW.md)

*免费开源的 Windows 工具箱启动器 —— 每条资源都直达官网或 GitHub。*

</div>

---

## ToolsGCP 是什么

ToolsGCP 是一款免费开源的 Windows 工具箱启动器。它维护一份整理好的程序 / 网站索引，让你能快速找到、
收藏，并在换电脑后一次性把常用软件装回来，不用再去到处翻下载页。

- **纯净无捆绑** —— 每条资源都直达官网或官方 GitHub 仓库，不夹带、不劫持、不用二次打包的安装包。
- **应用部署** —— 把常用软件整理成清单，重装系统后一键还原。
- **GCP-AI** —— 内置 AI 助手。说一句"我想要个能干某事的软件"，它直接从资源库里找出来告诉你。
- **插件系统** —— 往 `plugins/` 里放一个文件夹就是一个新页面，任何人都能扩展，不用改核心代码。
- **资源制作器** —— 一个小工具，把"我想让这个软件被收录"变成一条规范的资源数据，图片导入、标签、写 JSON 全包。

## 功能一览

| 模块 | 内容 |
|---|---|
| 首页 | 顶部轮播图（5 张，每 3 秒自动翻页，圆点分页可点），下面是「推荐插件」——本机 `plugins/` 里的插件一览，点一下进插件中心 |
| 搜索 | 关键词搜索（名称 / 简介 / 标签 / 编码如 `TG-000015`）、按类别分组、A–Z 排序、收藏 |
| 筛选 | 类别、标签、来源（有官网 / 有仓库 / 可自动下载）、仅看收藏，以及**更新时间**（最新 / 10 天前 / 30 天前 / 半年前） |
| 卡片 | 自适应网格随窗口变化；**磁贴（一行 4 个大卡片）/ 网格（一行 6 个小卡片）两种视图**，工具栏最右边切换；小 / 中 / 大三种卡片尺寸；支持动态 GIF 图标；每张卡片有「@给AI」按钮。网格视图只保留收藏按钮，文字放不下会自动省略 |
| GCP-AI | 右下角液态悬浮球 → 右侧聊天抽屉；历史对话页（删除对话会二次确认）；消息可复制 / 重写 / 重新生成（带版本翻页）；未配置 API Key 时点提示直达设置 |
| 部署 | 从搜索结果或收藏夹整理部署清单，之后由 ToolsGCP 负责下载安装 |
| 插件 | 井字 / 列表两种排版，**卡片右上角的状态徽章（已启用绿 / 已禁用红）**，左下角可写 20 字备注（点输入框外面自动取消），禁用后整卡变暗，还能搜索插件 |
| 公告 | 内容来自 GitHub 上带「公告」标签、且**作者本人发的** Issue（一条 Issue = 一整条公告，标题 + 正文原样显示）。左侧栏「公告」上有像微信那样的**红色未读数**；右上角「全部已读」把未读清零；启动时若有未读，用「检查更新」那种窗口内弹窗提示 |
| 收藏 | 类似 B 站收藏夹：左侧收藏夹列表（默认夹不可删），右侧卡片网格；支持新建 / 重命名 / 删除 / 批量移动 |
| GCP工坊 | 左侧栏「收藏」下面的一页（Galne563 自制）。**当前内容留空**，只放了标题与署名，等内容补充 |
| 侧边栏 AI | 设置 → GCP-AI 打开「改用侧边栏 AI 单独界面」后，左侧栏在 GCP工坊下面出现「AI」整页界面（输入框 / 发送 / 新建对话 / 历史一应俱全），同时右下角悬浮球消失。默认不开启。**两种形态共用同一段对话**：在悬浮球抽屉里聊到一半、去设置切到这个整页界面（或反过来），正在聊的那段会自动接过来 |
| 链接点击 | 详情页、搜索卡片、AI 回答、反馈页……**所有**外链：**左键**用浏览器打开并切到浏览器；**Ctrl+左键**浏览器照常打开，但当前程序**留在前台**（浏览器多是自己抢焦点，程序会把它抢回来后继续待着） |
| 界面字体 | 设置 → 外观 → 字体：从系统已安装字体里挑一个铺到整个程序，第一条（微软雅黑）就是默认字体 |
| 提交软件 | 左侧栏「更多」最下面一条，打开内置的**资源制作器页面**（投稿表单 / 资源浏览器 / 批量合成 / 使用说明），做的稿子直接进 `.ToolsGCP/ToolsGCP-Resources.json` |
| 设置 | 左侧板块列表 + 右侧**一整页**（点左侧滚到对应板块）；顶部可搜设置项，命中会全部列出来让你挑 |
| 窗口 | F11 进入真全屏并隐藏顶部标题栏（保留左侧导航栏），Esc 退出 |
| 日志 | 终端与 `.ToolsGCP/logs/` 双写，格式统一，历史归档最多 30 份 |

## 项目结构

```
ToolsGCP.pyw                   主程序（双击运行）
ToolsGCP-ResourceMaker.pyw     资源制作器（做 / 改资源条目；主程序里也有同一套界面）
requirements.txt               依赖
README.md                      README（English）
README.zh-CN.md                README（简体中文）
README.zh-TW.md                README（繁體中文）
README设置UI优化.md             设置界面/配色/导航的改造方案与落地记录
plugins/                       插件目录（见 plugins/README.md）
  _template/                   自己写插件的模板（不会被当成插件加载）
  hello-world/                 极简示例插件（一个文件就能跑）
  plugin-showcase/             完整示例插件：演示 context 能拿到的一切
                               （同上，只是模板，程序不加载、也不删）
docs/                          文档
  LOGGING.md                   日志格式与排查方法
  SECURITY_AND_ENGINEERING.md  安全模型与工程规范
.ToolsGCP/                     程序数据（不要删）
  ToolsGCP-Resources.json      资源库（所有应用都在这里，制作器按这个固定路径读写）
  privacy_policy.json          隐私政策同意记录
  logo.png                     程序图标 / 窗口图标
  Icon/                        资源库里引用的图标
  modules/                     核心 Python 模块与语言文件
    pymodels/interfaces/       每个页面一个模块（搜索 / 插件 / 设置 / 提交软件 …）
      resource_maker_*.py      资源制作器页面（从 ToolsGCP-ResourceMaker.pyw 移植）
  backups/                     资源库自动备份（只留最近 20 份）
  logs/                        运行日志与历史归档
  config/                      程序自己写出来的配置（首次运行自动建）
    toolsgcp_config.json       设置（含加密后的 API Key、接口地址、模型名称）
    favorites.json             收藏夹
    deploy_config.json         部署清单
    plugins.json               插件启用 / 禁用状态
    plugin_notes.json          插件卡片上的备注（你自己写的 20 字）
    plugin_data/<插件id>/       插件自己的数据目录
    chats/                     GCP-AI 的历史对话（每次对话一个 json）
```

> **`.ToolsGCP/config/` 里只放"程序自己写出来"的文件。**
> 资源库、隐私政策记录、图标、语言文件、日志都不属于这里，它们在 `.ToolsGCP/` 下原地不动 ——
> 这些文件由制作器或安装包管理，挪动位置会让另一个程序找不到它们。
>
> 老版本（配置平铺在 `.ToolsGCP/` 根下）升级上来时，程序在启动阶段会把这几个文件
> **自动搬进 `config/`**，你的设置和收藏夹不会丢，日志里会记一条 `[数据目录] migrate_file`。

## 运行环境

- Windows 10 / 11
- Python 3.10 以上（在 3.13 上测试）
- 只有两个运行依赖：

```bash
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

## 运行

```bash
python ToolsGCP.pyw
```

也可以直接在资源管理器里双击 `ToolsGCP.pyw`。要改资源库就跑：

```bash
python ToolsGCP-ResourceMaker.pyw
```

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
| 设置 → API Key → **模型名称** | 可编辑下拉框：列出该服务商常用模型，也可以自己敲任意模型名 | `deepseek-v4.1-flash`（V4.1-Flash） |
| 设置 → API Key → **接口地址** | OpenAI 兼容格式的地址，通常以 `/v1` 结尾。跟着服务商自动填，也可以自己改 | `https://api.deepseek.com/v1` |
| 设置 → API Key → **API Key** | 你的密钥。**用 Windows DPAPI 加密后存在 `config/toolsgcp_config.json` 的 `api_key_enc`**，密文换台电脑解不开 | 空 |
| 设置 → AI → **回复模式** | 控制回答的**长度和细节**，见下表 | 标准 |
| 设置 → AI → **上下文范围** | 每次提问带多少历史对话给模型：整个会话（默认，记忆最长）/ 最近 10 / 20 / 30 轮 | 整个会话 |
| 设置 → 模型调用 → 限制 token 输出 | 限制单次回答的最大长度 | 关闭 |

内置服务商与常用模型（都可以自己改）：

| 服务商 | 接口地址 | 常用模型 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-v4.1-flash`（V4.1-Flash，默认）、`deepseek-v4-pro`、`deepseek-v4-flash` |
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

一个插件就是 `plugins/` 下的一个文件夹，ToolsGCP 启动时自动扫描 —— **一个文件夹 = 一个插件**。

```
plugins/
├─ README.md          插件开发完整文档
├─ _template/         开发者模板（多文件、多语言）；下划线开头不会被加载
└─ hello-world/       极简示例：两个文件就能跑
```

### 最少的插件

两个文件：

```
plugins/我的插件/
├─ manifest.json     插件基本信息
└─ app.py            入口文件
```

`manifest.json`：

```json
{
  "id": "my-plugin",
  "name": "我的插件",
  "version": "1.0.0",
  "author": "你的名字",
  "description": "一句话说明",
  "entry": "app.py"
}
```

`app.py`：

```python
from PyQt5.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import SubtitleLabel


def create_page(context):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addWidget(SubtitleLabel("你好，ToolsGCP"))
    return page
```

放进 `plugins/` → 打开 ToolsGCP →「插件」→「重新加载」就出现了。改完代码只要再点一次「重新加载」，不用重启。

> **唯一的约定**：入口文件里必须有 `create_page(context)`，而且它要返回一个 `QWidget`。

`manifest.json` 字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 建议填 | 插件唯一标识，2~40 位小写字母/数字/`-`/`_`；留空就用文件夹名 |
| `name` | 建议填 | 卡片上显示的名字；留空则显示 `id` |
| `version` | 否 | 显示成 `v1.0.0` |
| `author` | 否 | 显示在版本旁边 |
| `description` | 否 | 卡片上的两行说明 |
| `entry` | 否 | 入口文件名，默认 `app.py` |
| `icon` | 否 | 插件目录里的图片路径，或 FluentIcon 的名字（如 `TOOLS`） |

文件名必须是 `manifest.json`（很旧的 `plugin.json` 也还认）。文件夹名以 `_` 或 `.` 开头会被跳过。

### 正式开发用模板

复制 `_template/` 改个名就是你的插件，它把代码分三层：

| 层 | 文件 | 该放什么 | 不该放什么 |
|---|---|---|---|
| 架构 | `app.py` | 装配模块、组织页面结构、页面切换 | 算法、大段控件代码 |
| 界面 | `ui/*.py` | 控件、布局、显示数据、收集输入 | 复杂计算、直接读写文件 |
| 逻辑 | `core/*.py` | 算法、数据处理、配置读写、翻译 | 任何 Qt 控件 |

界面要算东西就调 `self.logic.xxx()`，以后界面重写逻辑不用动。

### context 能拿到什么

`context` 是插件和 ToolsGCP 之间唯一的接口：

| 成员 | 说明 |
|---|---|
| `context.id` / `name` / `version` / `author` / `description` | 插件信息 |
| `context.plugin_dir` | 插件目录（**只读**，放资源） |
| `context.data_dir` | **可写**目录，已自动建好，配置和缓存写这里 |
| `context.app_dir` | ToolsGCP 程序目录 |
| `context.language` | 当前界面语言，如 `简体中文` |
| `context.locale` | 当前语言对应的文件名：`zh_CN` / `zh_TW` / `en_US` |
| `context.settings_manager` | ToolsGCP 设置（`.settings` 是字典） |
| `context.favorites_manager` | 收藏夹管理器 |
| `context.language_manager` | 语言管理器（一般用不到） |
| `context.get_resources()` | 整个资源库，`list[dict]` |
| `context.log("消息")` | 写日志（**文件 + 终端都输出**），也可 `context.log(msg, level="err")` |

**绝对不要往插件目录里写东西** —— 那是只读的，而且更新插件会把你的数据覆盖掉。
要写就写 `context.data_dir`：`.ToolsGCP/config/plugin_data/<插件id>/`。

### 多语言

模板内置了，**不用自己判断语言**。文案放 `lang/zh_CN.json`、`zh_TW.json`、`en_US.json`：

```json
{
  "title": "我的插件",
  "greet": "你好，{name}！"
}
```

```python
i18n = I18n(context.plugin_dir, context.locale)
i18n.t("title")                # → 我的插件 / 我的外掛 / My Plugin
i18n.t("greet", name="小明")    # → 你好，小明！
```

找不到的句子会依次回退 `zh_CN` → `en_US` → 键名本身，不会显示成空白。

### 能用什么库

ToolsGCP 自带 **PyQt5** 和 **qfluentwidgets**，插件里直接用，不用另外安装。
建议用 qfluentwidgets 的控件，看起来才和主程序是一体的。

### 管理 / 调试

ToolsGCP 左侧栏「插件」页：

| 项目 | 作用 |
|---|---|
| **重新加载** | 重新扫描 `plugins/`，改完代码不用重启 |
| **打开插件目录** | 直接打开 `plugins/` |
| **我想开发** | 弹窗里有插件说明的精简版 |
| 搜索框 | 按名称、id、作者筛插件 |
| 排版按钮 | 井字 / 列表之间切换 |
| 卡片左下角开关 | 启用 / 禁用，禁用后整卡变暗，文件夹还在 |
| 删除按钮 | 删除插件（连文件夹一起删） |

- 插件写崩了**不会**影响 ToolsGCP：报错会被捕获并显示在那张卡片上（鼠标悬停看完整堆栈）。
- `context.log()` 的输出在 `.ToolsGCP/logs/system_log.log`，只看插件日志用
  `Select-String -Path .ToolsGCP\logs\system_log.log -Pattern '\[插件\|'`。

**分发 / 卸载**：把插件文件夹打包成 zip（别带 `__pycache__` 和本地数据），对方解压到 `plugins/` 即可；
卸载就删文件夹，插件数据在 `.ToolsGCP/config/plugin_data/<插件id>/`。

> **安全**：插件就是普通 Python 代码，权限和 ToolsGCP 完全一样。只装你自己写的或完全信任的插件，装之前看一眼 `app.py`。

完整文档（每个字段、`context` 全部成员、`on_show()` 钩子、配置助手、资源处理、报错对照表）见
[`plugins/README.md`](plugins/README.md)。

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

制作器现在有**两个入口**，都是同一套界面和同一份逻辑：

- 主程序里：左侧栏「更多 → **提交软件**」（推荐，写完直接进资源库）；
- 独立运行：`ToolsGCP-ResourceMaker.pyw`（发布包里的那个 exe，功能完全一样）。

分四页：

1. **制作资源** —— 表单页。只有**名称**和**标识 id** 必填，其它留空就不会写进 JSON；
   简介最多 100 字，更长的内容放进「补充」框。
2. **浏览 / 删除** —— 整库表格。双击任意单元格就地修改；双击**图标**那一格可以换图片，
   图片会自动存进 `.ToolsGCP/Icon` 并改成应用名。
3. **批量合成** —— 把一份或多份投稿 `resource.json` 合进本地资源库，或者把多个文件合成一份新 JSON。
4. **使用说明** —— 程序内置的手册。

### 图片（图标）处理

- 导入图片会立刻复制进资源库的图标目录。
- 不管原图下载下来叫什么，都会被改成你填的**名称**（`LocalSend` → `LocalSend.png`）；
  之后再改名称，文件也会跟着改名。
- 如果这个名字已经被**别的**资源占用，会自动加 `-2`、`-3`，绝不覆盖别人的图；
  换自己的图则直接覆盖自己那一份。
- 每次操作都会在磁盘上核对一遍，JSON 里写的永远是真实存在的那个文件名。

### 备份

每次写盘前，当前资源库会复制到
`.ToolsGCP/backups/ToolsGCP-Resources.backup-<时间戳>.json`，只保留最近 20 份。
写盘是原子操作（先写临时文件再替换），中途被打断也不会把资源库写坏。
资源库永远只有 `.ToolsGCP/ToolsGCP-Resources.json` 这一个文件，制作器不会另外生成一份。

## 日志

所有输出（终端 + 文件）格式统一：

```
.ToolsGCP/logs/system_log.log        当前运行
.ToolsGCP/logs/history/              历史归档（最多 30 份）
```

```powershell
Select-String -Path .ToolsGCP\logs\system_log.log -Pattern '\[ERROR\]|\[OP   \]'
```

详细格式与排查方法见 [`docs/LOGGING.md`](docs/LOGGING.md)。

## 文档

| 文档 | 内容 |
|---|---|
| [`plugins/README.md`](plugins/README.md) | 怎么写一个插件（三步、很简单） |
| [`docs/LOGGING.md`](docs/LOGGING.md) | 日志格式规范与排查方法 |
| [`docs/SECURITY_AND_ENGINEERING.md`](docs/SECURITY_AND_ENGINEERING.md) | 安全模型与工程规范化 |

## 参与贡献

1. Fork 仓库并开一个分支。
2. 保持现有代码风格（中文注释、安静的小函数、不引入新依赖）。
3. 提交前用 `python ToolsGCP.pyw` 和 `python ToolsGCP-ResourceMaker.pyw` 各跑一遍。
4. 想投稿新资源，附一个 `resource.json` 和对应图标即可。

## 许可

以免费开源软件形式发布，具体许可条款见仓库。

<div align="center">

[English](README.md) ｜ **简体中文** ｜ [繁體中文](README.zh-TW.md)

</div>
