# ToolsGCP 插件开发文档

> **简体中文** ｜ [繁體中文](README.zh-TW.md) ｜ [English](README.en.md)

这个目录里放插件。**一个文件夹 = 一个插件**，ToolsGCP 启动时自动扫描。

```
plugins/
├─ README.md          ← 你正在看的这份（简体中文完整文档）
├─ README.zh-TW.md    ← 繁體中文
├─ README.en.md       ← English
├─ _template/         ← 开发者模板：多文件、多语言、分好模块（下划线开头不会被加载）
└─ plugin-showcase/   ← py 版时代的完整示例（**也不会被加载**，见下）
```

---

## ⚠️ 最重要的一件事：插件有**两个**存放位置

程序**同时扫描两个目录**，两处都能生效：

| | 位置 | 谁用 | 能不能写 |
|---|---|---|---|
| ① 内置目录 | `<程序目录>\.ToolsGCP\plugins\` | 随程序发布的官方插件 | 源码运行时可以；**exe 打包后多半只读** |
| ② 用户目录 | `<数据根>\plugins\` = 默认 `%USERPROFILE%\.ToolsGCP\plugins\` | **开发者 / 用户自己装的插件** | 永远可写（程序启动时自动创建） |

- **优先级：② > ①**。同名插件（同文件夹名）以用户目录那份为准，内置那份被"遮住"但不会被删除。
- 两处**都会加载**，不是"只认一个"。
- 插件页右上角「打开插件目录」按钮打开的是 ②（用户可写那个）。
- 插件页底部会显示 ② 的完整路径，照着复制进去即可。

> **为什么必须有 ②？** exe 打包后，① 被塞进了 exe 本体所在目录：
> 装在 `Program Files` 时不可写、程序升级会整体覆盖、用户根本"放不进去"。
> ② 在用户数据根里，跟着「设置 → 存储」的数据根迁移一起走，写进去的插件不会丢。
>
> **开发时的建议**：想改官方插件做调试，把它的文件夹**复制到 ②** 再改 ——
> ② 优先级高，你的版本会生效，删掉 ② 那份就自动回落到官方版本（内置那份受保护，删不掉）。

---

> ⚠️ **先看清你要做的是哪一版的插件 —— 这两套机制目前完全不通用。**
>
> | | Web 版（**当前发布的主体**） | py(QuQt) 版（只读存档，已弃用） |
> |---|---|---|
> | 谁在扫目录 | `desktop/api/plugins.py` | `pymodels/core/plugin_manager.py` |
> | 真正加载什么 | `manifest.json` + `config.html`（iframe） | `app.py` 的 `create_page(context) -> QWidget` |
> | 开关怎么生效 | manifest 的 `enabled_setting` 指向一个设置键 | `PluginManager.disabled` 集合 |
> | `app.py` / `ui/` / `core/` | **一行都不执行** | 全部执行 |
>
> 也就是说：**只抄 py 版那一套（本文件第五~十节讲的 `create_page`），在 Web 版里会得到
> 一个「插件列表里有、⚙ 按钮是灰的、开关拨不动（提示"这个插件没有提供开关配置"）、
> 界面一片空」的壳子。** 这不是 bug，是护栏：Web 版主线程 import PyQt5 会让 WebView2
> 初始化崩溃（见根目录 AGENTS.md 第 8 节）。
>
> - **做 Web 版插件 → 先看下面「零、Web 版插件（当前主体）」那一节**，只要三个文件。
> - 给旧 py 版写插件 → 从第五节往后看（那些 API 在 Web 版里不会被调用）。

> ⚠️ **`_template` 和 `plugin-showcase` 都不会被程序加载。**
> 它们只是**给你照着写的模板**：不出现在插件列表里、不会被启停、也不会有自己的
> 数据目录，但文件会原样留着（见 `plugin_manager.RESERVED_DIR_NAMES`）。
> 你想让某个目录不被加载，把名字改成下划线开头，或者找开发者把它加进保留名单。

- 只想跑起来看看 → 看 [零](#零web-版插件当前主体) 和 [二](#二放进程序里看效果)
- 准备写正式插件 → 从 [三](#三正式开发用-_template) 开始
- 卡住了 → [十一、常见坑与报错对照表](#十一常见坑与报错对照表)

---

## 零、Web 版插件（当前主体）

Web 版**不需要你写一行 Python**。一个插件最少只要两样东西：

```
plugins/<你的插件id>/
├─ manifest.json      ← 必须（没这个文件 = 列表里根本不出现）
└─ config.html        ← 可选：⚙ 按钮点开的那个配置页（iframe 加载）
```

`manifest.json` 里 Web 版真正读的字段只有这几个：

| 字段 | 作用 | 不写会怎样 |
|---|---|---|
| `id` | 插件唯一标识（建议与目录名一致） | 用**目录名**顶上 |
| `name` / `description` | 卡片上的名字和说明，可以是字符串，也可以是 `{"简体中文": …, "English": …}` | 名字退回 id |
| `icon` | 相对插件目录的图片路径 | 卡片没图 |
| `config_page` | **配置页 HTML** 的相对路径 | ⚙ 按钮是灰的，点不进去 |
| `enabled_setting` | 那个开关写进哪个**设置键** | 开关拨不动，提示"这个插件没有提供开关配置" |
| `default_disabled` | 没有开关键时的默认状态（配合 `enabled_setting` 用） | 默认为"已启用" |
| `builtin` | 标记为官方内置，**拒绝删除** | 用户可以在插件页里把这个插件删掉 |
| `companion` / `generated_by` | 启停连坐：启用我时顺带启用谁 / 我被关掉时连带停用谁 | 不联动 |

配置页那一侧只有三条硬规矩（照 `_template/config.html` 写就行，它已经把三条都实现好了）：

1. **自带样式、不联网、不引 webui 的 CSS/JS** —— 它是 iframe，独立可跑；
   纯浏览器打开时拿不到接口，会自动降级成"预览模式 + 只读"。
2. **读写设置只走宿主接口**：`window.pywebview.api.settings.get(key)` /
   `settings.set(key, value)`。iframe 里没有 `window.pywebview`（pywebview 只往主框架
   注入），所以要回退 `parent.pywebview.api`。返回值是 `{ok: …}` 信封；
   ⚠️ **别把 `ok` 当业务字段名**（会被信封覆盖，见 AGENTS.md 第 3 节）。
3. **主题跟宿主走**：监听宿主 postMessage 的 `{type:'toolsgcp-theme', theme, fx, accent, language}`，
   首帧先读父文档的 `data-theme` 兜底（只信自己 `matchMedia` 会白一下）。
   关闭本页用 `window.parent.postMessage({type:'toolsgcp-close-plugin', id}, '*')`。

开关的值就是一个布尔设置键，会落进 `<数据根>/config/settings.json`，
所以"关程序后开关还在"是正常行为。要存插件自己的数据，用同一个 settings 域存一个
带插件 id 前缀的键即可。

> 从 `_template` 复制着做 Web 版插件时，**必改三处**并且保持一致：
> 目录名、`manifest.id`、`manifest.enabled_setting`
> （命名约定 `plugin_<id 里的 - 换成 _>_enabled`）。
> 三个里面漏一个，就会出现"两个插件共用同一份配置/同一个开关"的怪事。

---

## 目录

0. [**Web 版插件（当前主体）**](#零web-版插件当前主体) ← 现在发布的版本看这一节就够
1. [最少的插件长什么样](#一最少的插件长什么样)
2. [放进程序里看效果](#二放进程序里看效果)
3. [正式开发用 `_template`](#三正式开发用-_template)
4. [manifest.json 字段](#四manifestjson-字段一个一个说)
5. [`create_page(context)` 的约定](#五create_pagecontext-的约定)
6. [context：插件和 ToolsGCP 之间唯一的接口](#六context插件和-toolsgcp-之间唯一的接口)
7. [资源库数据长什么样](#七资源库数据长什么样)
8. [多语言](#八多语言)
9. [存配置 / 存数据](#九存配置--存数据)
10. [图片等资源](#十图片等资源)
11. [常见坑与报错对照表](#十一常见坑与报错对照表)
12. [调试技巧](#十二调试技巧)
13. [发给别人 / 卸载](#十三发给别人--卸载)
14. [安全提醒](#十四安全提醒)

---

## 一、最少的插件长什么样

只要**两个文件**：

```
plugins/my-plugin/
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

> **唯一的约定**：入口文件里必须有一个 `create_page(context)`，而且它要返回一个 `QWidget`。
> 其余的（拆几个文件、用什么控件、要不要左侧栏）完全随你。

## 二、放进程序里看效果

1. 把插件文件夹放进**用户插件目录**：`%USERPROFILE%\.ToolsGCP\plugins\`
   （程序启动时会自动创建；也可以在插件页点「打开插件目录」直接打开它）
   - 源码运行时放进本目录（`<程序目录>\.ToolsGCP\plugins\`）同样有效，但建议养成放用户目录的习惯 —— exe 版只有那个位置可写
2. 打开 ToolsGCP → 左侧栏「更多」→「插件」
3. 点「重新加载」
4. 列表里就会出现你的插件，左下角开关是打开状态（绿色）

改完代码**不用重启程序**，再点一次「重新加载」即可。

> ⚠️ 插件页底部会显示当前用户插件目录的**完整路径**，直接照着复制进去最稳妥。
> 两个目录同时生效；同名时用户目录那份优先（见上一节）。

---

## 三、正式开发用 `_template`

复制 `_template` 整个文件夹、改成你的插件 id（英文小写，例如 `my-tool`），然后照下面的分工写：

```
_template/
├─ manifest.json        插件基本信息（改这里填你的信息）
├─ config.html          ★ Web 版真正加载的配置页（iframe）—— 做 Web 版插件改这个就够
├─ app.py               ★ 程序基本架构：装配各模块，产出页面（**只有 py 版会执行**）
├─ core/                ★ 逻辑层（不碰界面）（**只有 py 版会执行**）
│  ├─ config.py           读写插件自己的配置
│  ├─ i18n.py             多语言
│  └─ logic.py            功能与逻辑算法 ← 业务代码写这里
├─ ui/                  ★ 界面层（不写业务逻辑）（**只有 py 版会执行**）
│  ├─ sidebar.py          左侧栏模块
│  └─ page.py             专属界面模块
├─ lang/                多语言文案
│  ├─ zh_CN.json
│  ├─ zh_TW.json
│  └─ en_US.json
└─ assets/              图片等只读资源（放了个示例图标）
```

> ⚠️ **上面这套 Python 分层是 py(QuQt) 版的架构，Web 版一行都不会执行**
> （主线程 import PyQt5 会让 WebView2 崩溃，见 AGENTS.md 第 8 节）。
> 做 **Web 版**插件只要两样：`manifest.json`（填 `config_page` / `enabled_setting`）
> + `config.html`（业务界面直接写 HTML/JS，设置走 `parent.pywebview.api.settings`）。
> 详见 [零、Web 版插件（当前主体）](#零web-版插件当前主体)。
> 下面这段三层分工，是给要同时兼容 py 版、或者在改旧插件的人看的。

### 三层分工（照着做就不会乱）

| 层 | 文件 | 该放什么 | 不该放什么 |
|---|---|---|---|
| 架构 | `app.py` | 装配模块、组织页面结构、页面切换 | 具体算法、大量控件代码 |
| 界面 | `ui/*.py` | 控件、布局、显示数据、收集用户输入 | 复杂计算、直接读写文件 |
| 逻辑 | `core/*.py` | 算法、数据处理、配置读写、翻译 | 任何 Qt 控件 |

界面要算东西时，就去调 `self.logic.xxx()`。这样以后界面重写，逻辑一行都不用动。

### 模板里现成的东西

| 文件 | 里面已经写好的 |
|---|---|
| `config.html` | **Web 版**配置页：首帧主题兜底 + 宿主 `toolsgcp-theme` 联动、开关读写 `settings.get/set`、布尔归一化、写失败回滚、预览模式降级、返回插件列表 —— 直接照着加你自己的行 |
| `app.py` | `create_page()` 入口 + `PluginRoot`（左侧栏 + `QStackedWidget` 多页切换） |
| `ui/sidebar.py` | 竖向导航条 `Sidebar`，`currentChanged(key)` 信号；不想用可以不建这个文件，换成标签页也行 |
| `ui/page.py` | `BasePage`（带 `on_show()` 钩子）+ 首页 + 统计页两个示例 |
| `core/logic.py` | 拿资源库、按类别/标签统计、关键词搜索 —— 换成你自己的业务即可 |
| `core/config.py` | 极简 JSON 配置，`get` / `set` / `bump` |
| `core/i18n.py` | 多语言翻译器，带语言回退 |
| `lang/*.json` | 三种语言的示例文案 |

**`on_show()` 钩子是干什么的**：页面被切过去时调用一次，用刷新数据。模板里 `PluginRoot.switch_to()`
每次切页都会调 `page.on_show()`，所以统计数字永远是新的。

---

## 四、manifest.json 字段（一个一个说）

> ⚠️ 下面这张表是 **py 版 `PluginManager` 读的字段**。Web 版另外还要 `config_page` /
> `enabled_setting` / `default_disabled` / `builtin` / `companion` / `generated_by` ——
> 那几个才是"插件在 Web 版里到底能不能点开、能不能开关"的关键，见
> [零、Web 版插件（当前主体）](#零web-版插件当前主体)。

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 建议填 | 插件唯一标识，2~41 位小写字母/数字/连字符/下划线（首字符必须是字母或数字）。**留空就用文件夹名** |
| `name` | 建议填 | 卡片上显示的名字；留空则显示 `id` |
| `version` | 否 | 显示成 `v1.0.0`；留空则不显示版本 |
| `author` | 否 | 显示在卡片副标题上（`v1.0.0 · 作者`） |
| `description` | 否 | 卡片上的两行说明；留空显示"（没有填写说明）" |
| `entry` | 否 | 入口文件名，默认 `app.py`。**必须和实际文件名一致**（Web 版不加载它，py 版才用） |
| `icon` | 否 | 图标：可以写插件目录里的图片相对路径（如 `assets/icon.png`），也可以写 FluentIcon 的名字（如 `HOME`、`TOOLS`）。都没有就用默认图标 |

几个容易忽略的点：

- **文件名必须是 `manifest.json`**。旧插件如果叫 `plugin.json` 也还能识别，但新插件请用 `manifest.json`。
- **文件夹名以下划线开头会被跳过**（`_template` 就是这样躲开加载的），点号开头同理。
- `id` 重复的两个插件只会加载先扫到的那个。
- ⚠️ **`id` 必须和目录名一致**。宿主把 `id` 当作插件的**数据目录名**，
  两个不同目录却写着同一个 `id` 的插件会**共用同一份配置数据**、互相踩。
  （`_template/manifest.json` 里那个 `REPLACE-WITH-YOUR-PLUGIN-ID` 占位串是故意的：
  复制完忘了改就一定会报错，不会静默地撞车。）
- 启用/禁用状态保存在 **`<数据根>/config/plugins.json`**（内容形如 `{"disabled": ["某个插件id"]}`），
  是"禁用清单"，不是"启用清单"。
  ⚠️ 默认数据根是 `<用户主目录>\.ToolsGCP`，**不是程序目录旁的那个 `.ToolsGCP`**
  （那是随程序发布的资源目录）；在「设置 → 存储」里迁移过数据根的话，这个文件跟着搬。
  见根目录 AGENTS.md 第 5 节第 9 条。

---

## 五、`create_page(context)` 的约定

```python
def create_page(context):
    """返回一个 QWidget，ToolsGCP 会把它当成插件页面显示"""
    return 你的页面控件
```

- 可以写在 `app.py` 里，也可以在一个包里：`entry` 写 `"main.py"` 之类都行。
- **插件自己的模块请用相对导入**（`from .core.logic import Logic`）。
  插件是当独立包加载的，这样两个插件里都叫 `core/`、`ui/` 也不会互相覆盖。
- 返回值必须是 `QWidget` 的子类实例，忘了写 `return` 会被判为"没有返回 QWidget"。
- 这个函数**允许抛异常**：出错只影响这个插件，卡片上会显示错误原因，ToolsGCP 主程序不受影响。

---

## 六、context：插件和 ToolsGCP 之间唯一的接口

`create_page(context)` 里的 `context` 就是你能用到的全部外部能力：

| 成员 | 类型 | 说明 |
|---|---|---|
| `context.id` | str | 插件 id |
| `context.name` | str | 插件名 |
| `context.version` | str | 版本 |
| `context.author` | str | 作者 |
| `context.description` | str | 说明 |
| `context.plugin_dir` | str | 插件自己的目录（**只读**，放资源） |
| `context.data_dir` | str | **可写**目录，ToolsGCP 已自动创建，存你的配置/缓存 |
| `context.app_dir` | str | ToolsGCP 程序目录 |
| `context.language` | str | 当前界面语言：`简体中文` / `繁體中文` / `English` |
| `context.locale` | str | 当前语言对应的文件名：`zh_CN` / `zh_TW` / `en_US` |
| `context.settings_manager` | 对象 | ToolsGCP 设置；`context.settings_manager.settings` 是字典 |
| `context.favorites_manager` | 对象 | 收藏夹管理器 |
| `context.language_manager` | 对象 | 语言管理器（一般用不到，`locale` 已经够） |
| `context.get_resources()` | list[dict] | 整个资源库（字段见下一节） |
| `context.log("消息")` | — | 写日志：日志文件 + 终端都会输出，也可 `context.log(消息, level="err")` |
| `context.ai_agent` | 对象 / None | GCP-AI Agent 运行时（**属性**不是方法；主窗口没建好时是 None，必须判空） |
| `context.register_ai_tool(name, desc, handler, parameters="", danger=False)` | bool | 给 AI 加一只"手"（本插件专属，停用时一起卸掉） |
| `context.register_chat_hint(hint_id, label, insert, prompt, priority)` | bool | 在聊天输入框上方登记一条悬浮提示 / 斜杠命令 |
| `context.unregister_chat_hint(hint_id)` | bool | 卸掉一条提示（停用时调） |
| `context.style_scroll_area(area)` | bool | 把滚动区域刷成主程序同款滚动条 + 平滑滚动（插件拿不到 pymodels.ui，由 context 代劳） |
| `context.plugins_dir` | str | `plugins/` 目录的绝对路径（"插件制作辅助"用它落新插件） |
| `context.reload_plugins()` | int | 让宿主重新扫描插件目录，返回加载数 |
| `context.open_plugin_config(plugin_id)` | bool | 打开另一个插件的配置页（跨插件跳转用） |

```python
def create_page(context):
    context.log(f"插件启动，语言 {context.locale}")
    resources = context.get_resources()          # list[dict]
    settings = context.settings_manager.settings  # dict，只读着用
    return QWidget()
```

`context.log()` 的输出进 **`<数据根>\logs\system_log.log`**（默认
`<用户主目录>\.ToolsGCP\logs\system_log.log`），同时在终端打印。
⚠️ 是**数据根**下面，不是程序目录旁那个 `.ToolsGCP`（那是资源目录）；
在「设置 → 存储」迁移过数据根的用户，日志在新数据根下面。

---

## 七、资源库数据长什么样

`context.get_resources()` 返回的就是 `.ToolsGCP/ToolsGCP-Resources.json` 里的 `resources` 数组：

```python
{
  "id": "localsend",              # 唯一标识
  "code": "TG-000001",            # 编码，部署清单靠它指代程序
  "name": "LocalSend",
  "category": "工具",
  "tags": ["工具", "传输"],
  "icon": ".ToolsGCP/Icon/localsend.png",   # 已经补成可用的相对路径
  "url": "https://localsend.org/",
  "github": "https://github.com/localsend/localsend",
  "description": "跨平台局域网文件传输工具……",
  "listed_at": "2026-09-21 00:40:14",       # 上架时间
  "systems": [],                            # 适用系统（制作器里填，可空）
  "architectures": [],                      # CPU 架构（制作器里填，可空）
}
```

不是每条都有全部字段：`url` / `github` / `description` 等都可能不存在，取值时请用 `item.get("x")`。

---

## 八、多语言

模板已经内置，**不用自己判断语言**。

1. 文案写在 `lang/zh_CN.json`、`zh_TW.json`、`en_US.json` 里（平铺键值对）：

```json
{
  "title": "我的插件",
  "greet": "你好，{name}！"
}
```

2. 代码里这样用：

```python
i18n = I18n(context.plugin_dir, context.locale)   # context.locale 已经是当前语言
i18n.t("title")                  # → 我的插件 / 我的外掛 / My Plugin
i18n.t("greet", name="小明")      # → 你好，小明！
i18n.available_locales()         # → ['en_US', 'zh_CN', 'zh_TW']
i18n.all()                       # 当前语言的完整文案表（合并了回退结果）
```

**语言对应关系**

| ToolsGCP 界面语言 | 插件语言文件 |
|---|---|
| 简体中文 | `zh_CN.json` |
| 繁體中文 | `zh_TW.json` |
| English | `en_US.json` |

某句没翻译也不怕：找不到会依次回退到 `zh_CN` → `en_US` → 键名本身，不会显示成空白。
语言文件用 `utf-8-sig` 读取，记事本另存出来的带 BOM 的 JSON 也能用。

---

## 九、存配置 / 存数据

**要写东西一律写 `context.data_dir`，绝对不要写插件目录。**

- 插件目录是只读的：写进去（尤其是打包发布后）会失败，用户更新插件时数据也会被覆盖。
- 每个插件有独立的可写目录：`.ToolsGCP/config/plugin_data/<插件id>/`，ToolsGCP 已经建好。

模板里的 `Config` 就是最小可用的 JSON 配置：

```python
config = Config(context.data_dir)      # 默认文件 config.json
config.get("times", 0)
config.set("times", 5)
config.bump("open_times")              # 计数 +1，返回新值
config.save()
```

想存别的文件就 `Config(context.data_dir, "cache.json")`；路径自己拼也可以，只要是 `data_dir` 下面。

---

## 十、图片等资源

- 只读资源（图标、示例图、模板文件）放 `assets/`，用
  `os.path.join(context.plugin_dir, "assets", "icon.png")` 取。
- 用 `QIcon` / `QPixmap` 加载；`ui/page.py` 里有一个完整的显示图片示例。
- 需要缓存的图片请放 `context.data_dir`，不要往 `assets/` 写。
- 卡片图标可以用图片，也可以直接用 FluentIcon 的名字（`"icon": "TOOLS"`）。

---

## 十一、常见坑与报错对照表

| 现象 / 报错 | 原因与解决 |
|---|---|
| 插件根本不出现在列表里 | 文件夹名以下划线或点开头会被跳过；或者缺 `manifest.json` |
| 「缺少 manifest.json」 | 文件名必须是 `manifest.json`（`plugin.json` 是旧写法，仍兼容） |
| 「入口文件不存在」 | `manifest.json` 里的 `entry` 和实际文件名对不上（大小写也要对） |
| 「没有 create_page」 | 入口文件里必须定义 `create_page(context)` 函数 |
| 「必须返回一个 QWidget」 | 函数返回了别的类型，或者忘了写 `return` |
| 「manifest.json 解析失败」 | JSON 语法错（多余逗号、引号不配对）；文件带 BOM 也没关系 |
| 界面上是空白一片 | 页面建好了但没往 layout 里加控件，或者控件没设 parent |
| 存的数据下次打开就没了 | 写到了 `plugin_dir`（只读），应该写 `context.data_dir` |
| 两个插件互相干扰 | 插件自己的模块用了绝对导入；请改成相对导入（`from .core...`） |
| 改完代码没变化 | 没点「重新加载」；重启程序也可以 |
| 开关是灰的、点不动 | 插件加载失败（状态不是"已启用/已禁用"），鼠标悬停卡片看完整报错 |
| 导入第三方库报 `ModuleNotFoundError` | 插件只能用 ToolsGCP 自带的库（见下），或把纯 Python 依赖一起放进插件目录 |

**能用什么库**：ToolsGCP 自带 **PyQt5** 和 **qfluentwidgets**，插件里直接用，不用另外安装。

```python
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton
from qfluentwidgets import SubtitleLabel, BodyLabel, PrimaryPushButton, FluentIcon
```

界面建议用 qfluentwidgets 的控件，看起来才和主程序是一体的。

---

## 十二、调试技巧

- **加载失败**：卡片上会直接显示错误原因，鼠标悬停看完整堆栈；日志里也有。
- **插件写崩了不会连带主程序**：异常被捕获，只会让这个插件标记成"加载失败"。
- **看日志**：`context.log("消息")` 同时写文件和终端，只看插件的日志用
  （路径里的 `.ToolsGCP` 是**数据根**，默认在用户主目录下，不是程序目录旁那个）：

```powershell
Select-String -Path "$env:USERPROFILE\.ToolsGCP\logs\system_log.log" -Pattern '\[插件\|'
```

- **临时禁用**：卡片左下角开关一关，插件就不加载了，文件夹还在（改动可以随时恢复）。
- **改完直接生效**：点「重新加载」，不用重启 ToolsGCP。

---

## 十三、发给别人 / 卸载

- **分发**：把插件文件夹打包成 zip 发出去，对方解压到 `plugins/` 下即可。
  建议只包含 `manifest.json`、代码、`lang/`、`assets/`，别把 `__pycache__` 和本地数据打进去。
- **卸载**：删掉插件文件夹。插件的数据在 `.ToolsGCP/config/plugin_data/<插件id>/`，想彻底清干净就一起删。

---

## 十四、安全提醒

**插件就是一段普通的 Python 代码，拥有和 ToolsGCP 完全相同的权限。**

- 只安装你自己写的、或者你完全信任的来源的插件
- 装之前建议先打开 `app.py` 看一眼
- 插件能读写文件、发网络请求、启动进程 —— 这些权限主程序都有，插件一样有
