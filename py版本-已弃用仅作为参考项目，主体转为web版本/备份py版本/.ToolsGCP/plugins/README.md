# ToolsGCP 插件开发文档

这个目录里放插件。**一个文件夹 = 一个插件**，ToolsGCP 启动时自动扫描。

```
plugins/
├─ README.md          ← 你正在看的这份（完整开发文档）
├─ _template/         ← 开发者模板：多文件、多语言、分好模块（下划线开头不会被加载）
├─ hello-world/       ← 极简示例：只有两个文件也能跑
└─ plugin-showcase/   ← 完整示例：一个真实插件长什么样（**也不会被加载**，见下）
```

> ⚠️ **`_template` 和 `plugin-showcase` 都不会被程序加载。**
> 它们只是**给你照着写的模板**：不出现在插件列表里、不会被启停、也不会有自己的
> 数据目录，但文件会原样留着（见 `plugin_manager.RESERVED_DIR_NAMES`）。
> 你想让某个目录不被加载，把名字改成下划线开头，或者找开发者把它加进保留名单。

- 只想跑起来看看 → 看 [一](#一最少的插件长什么样) 和 [二](#二放进程序里看效果)
- 准备写正式插件 → 从 [三](#三正式开发用-_template) 开始
- 卡住了 → [十一、常见坑与报错对照表](#十一常见坑与报错对照表)

---

## 目录

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

1. 把上面的文件夹放进 `plugins/`
2. 打开 ToolsGCP → 左侧栏底部「插件」
3. 点「重新加载」
4. 列表里就会出现你的插件，左下角开关是打开状态（绿色）

改完代码**不用重启程序**，再点一次「重新加载」即可。

---

## 三、正式开发用 `_template`

复制 `_template` 整个文件夹、改成你的插件 id（英文小写，例如 `my-tool`），然后照下面的分工写：

```
_template/
├─ manifest.json        插件基本信息（改这里填你的信息）
├─ app.py               ★ 程序基本架构：装配各模块，产出页面
├─ core/                ★ 逻辑层（不碰界面）
│  ├─ config.py           读写插件自己的配置
│  ├─ i18n.py             多语言
│  └─ logic.py            功能与逻辑算法 ← 业务代码写这里
├─ ui/                  ★ 界面层（不写业务逻辑）
│  ├─ sidebar.py          左侧栏模块
│  └─ page.py             专属界面模块
├─ lang/                多语言文案
│  ├─ zh_CN.json
│  ├─ zh_TW.json
│  └─ en_US.json
└─ assets/              图片等只读资源（放了个示例图标）
```

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

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 建议填 | 插件唯一标识，2~40 位小写字母/数字/连字符/下划线。**留空就用文件夹名** |
| `name` | 建议填 | 卡片上显示的名字；留空则显示 `id` |
| `version` | 否 | 显示成 `v1.0.0`；留空则不显示版本 |
| `author` | 否 | 显示在卡片副标题上（`v1.0.0 · 作者`） |
| `description` | 否 | 卡片上的两行说明；留空显示"（没有填写说明）" |
| `entry` | 否 | 入口文件名，默认 `app.py`。**必须和实际文件名一致** |
| `icon` | 否 | 图标：可以写插件目录里的图片相对路径（如 `assets/icon.png`），也可以写 FluentIcon 的名字（如 `HOME`、`TOOLS`）。都没有就用默认图标 |

几个容易忽略的点：

- **文件名必须是 `manifest.json`**。旧插件如果叫 `plugin.json` 也还能识别，但新插件请用 `manifest.json`。
- **文件夹名以下划线开头会被跳过**（`_template` 就是这样躲开加载的），点号开头同理。
- `id` 重复的两个插件只会加载先扫到的那个。
- 状态保存在 `.ToolsGCP/plugins.json`（内容形如 `{"disabled": ["某个插件id"]}`），
  是"禁用清单"，不是"启用清单"。

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

```python
def create_page(context):
    context.log(f"插件启动，语言 {context.locale}")
    resources = context.get_resources()          # list[dict]
    settings = context.settings_manager.settings  # dict，只读着用
    return QWidget()
```

`context.log()` 的输出进 `.ToolsGCP/logs/system_log.log`，同时在终端打印。

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
- **看日志**：`context.log("消息")` 同时写文件和终端，只看插件的日志用：

```powershell
Select-String -Path .ToolsGCP\logs\system_log.log -Pattern '\[插件\|'
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
