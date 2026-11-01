# ToolsGCP 日志系统

这份文档讲清楚三件事：**日志长什么样**、**都记了什么**、**出问题时怎么用它排查**。

---

## 一、日志在哪

```
.ToolsGCP/logs/
├── system_log.log                          当前这次运行的日志（实时写）
└── history/
    ├── ToolsGCP-2026-09-19-221843285.log   历史日志（每次启动自动归档，最多留 30 份）
    └── ...
```

程序每次启动都会把上一次的 `system_log.log` 归档到 `history/`，然后新建一个空的继续写。
所以**不要担心日志被覆盖**，往上一次翻就行。

**「清理历史日志」按钮只删 `history/` 里的归档，当前 `system_log.log` 的内容一个字都不动。**

这一条是刻意的：正在写的这份日志记的就是"刚刚发生了什么"，点一下清理就把它清空，
等于把排查现场一起删掉。想彻底重来一次，**重启程序**就行 —— 启动时会把当前日志
归档进 `history/`（照样翻得到），再开一份新的。

日志同时会**打到终端**：

- 用 `python ToolsGCP.pyw` 启动 → 直接在同一条命令行里看到
- 双击 `.pyw` 启动 → 程序会尝试附着到调用它的终端；完全没有终端时只写文件

---

## 二、日志格式（固定，可以放心写脚本解析）

```
[2026-09-19 22:15:22.064] [INFO ] [启动|startup] 主窗口 启动成功
[2026-09-19 22:15:23.001] [OP   ] [设置|操作] update key=theme new=深色主题 old=跟随系统
[2026-09-19 22:15:24.112] [WARN ] [部署|download] 跳过 code=TG-999999 reason=资源库里没有这个编码
[2026-09-19 22:15:25.220] [ERROR] [插件|hello-world] 加载失败: ModuleNotFoundError: ...
```

拆开看是四段：

| # | 字段 | 格式 | 说明 |
|---|---|---|---|
| ① | 时间 | `YYYY-MM-DD HH:MM:SS.mmm` | 本地时间，精确到毫秒 |
| ② | 级别 | 固定 5 字符宽 | `DEBUG` `INFO ` `OP   ` `WARN ` `ERROR` `FATAL` |
| ③ | 分类 | `中文分类\|英文子类` | 例如 `启动\|startup`、`设置\|操作` |
| ④ | 消息 | 自由文本 | 结构化信息写成 `键=值` |

**几条约定，方便你 grep：**

- 级别**左对齐补空格到 5 位**，所以 `[INFO ]`、`[OP   ]` 这类列是对齐的，可以用 `sed` 按列切
- 值里**有空格或特殊字符会自动加英文双引号**：`reason="资源库里没有这个编码"`
- 多行消息（异常堆栈）：第一行带完整前缀，后续行**按前缀宽度缩进对齐**，视觉上是一整块
- 敏感值（API Key、License Key 等）**自动打码成 `***`**，日志里不会有密钥

### 级别含义

| 级别 | 什么时候出现 |
|---|---|
| `DEBUG` | 调试细节，默认**不记录**（开发者模式可打开） |
| `INFO ` | 正常流程节点：启动、加载完成、下载完成…… |
| `OP   ` | **用户操作**：切页面、改设置、点卡片、收藏、搜索、点按钮…… |
| `WARN ` | 可以继续但需要注意：编码查不到、资源没找到、功能被跳过 |
| `ERROR` | 出错：下载失败、插件加载失败、写文件失败…… |
| `FATAL` | 致命错误 |

---

## 三、都记了些什么（操作日志覆盖范围）

`OP` 级别专门用来记录**用户操作**，目前覆盖：

| 分类 | 子类 | 例子 |
|---|---|---|
| `页面` | `switch` | `[OP] [页面\|操作] switch page=设置` |
| `设置` | `update` | `[OP] [设置\|操作] update key=auto_search new=True old=False` |
| `搜索` | `keyword` | `[OP] [搜索\|操作] keyword 关键词=steam 命中=1 总数=40` |
| `搜索` | `open_card` | `[OP] [搜索\|操作] open_card code=TG-000003 name=Steam` |
| `排序` | `change` | `[OP] [排序\|操作] change 方式=类别 key=category` |
| `收藏` | `toggle` / `add` / `remove` | `[OP] [收藏\|操作] toggle code=TG-000001 state=已收藏` |
| `收藏` | `create_folder` / `rename_folder` / `delete_folder` | `[OP] [收藏\|操作] create_folder name=开发工具` |
| `卡片` | `open_link` | `[OP] [卡片\|操作] open_link 类型=打开官网 code=TG-000001 url=...` |
| `快捷键` | `hotkey` | `[INFO] [快捷键\|hotkey] 呼出搜索框 已注册: Ctrl+Q` |
| `插件` | 插件名 | `[INFO] [插件\|Hello World] 插件加载成功` |
| `部署` | `deploy` | `[INFO] [部署\|deploy] 开始一键部署，共 12 项` |
| `启动` | `startup` | `[INFO] [启动\|startup] 首屏内容加载完成` |

**所有输出都走同一个通道**（`utils/logger.py` 的 `log`），代码里已经不允许再出现裸 `print()`——
这样终端和日志文件的内容**永远一致**，不会出现"终端有日志没有"或反过来的情况。

---

## 四、出问题时怎么用

### 1. 先看这次运行的日志

打开 `.ToolsGCP/logs/system_log.log`，直接从**最后往前翻**，找第一条 `[ERROR]`：

```powershell
Select-String -Path .ToolsGCP\logs\system_log.log -Pattern '\[ERROR\]|\[WARN \]'
```

### 2. 用分类快速定位

```powershell
# 只看用户操作（复现步骤）
Select-String -Path .ToolsGCP\logs\system_log.log -Pattern '\[OP   \]'

# 只看插件相关
Select-String -Path .ToolsGCP\logs\system_log.log -Pattern '\[插件\|'

# 只看失败
Select-String -Path .ToolsGCP\logs\system_log.log -Pattern '\[ERROR\]|\[FATAL\]'
```

### 3. 拿到"复现路径"

因为**每个操作都有 OP 记录**，你可以让用户按一遍问题步骤，然后从 OP 行就能还原他到底点了什么：

```
[OP] [页面|操作] switch page=设置
[OP] [设置|操作] update key=splash_screen_enabled new=False old=True
[OP] [页面|操作] switch page=搜索
[ERROR] [下载|download] ...
```

### 4. 导出给我

程序里「查看日志」页面可以选中日志文件导出成 zip。
**注意**：导出前请自己扫一眼有没有不想外发的路径信息（日志里会记录本机路径，但不会记录密钥）。

---

## 五、代码里怎么加日志

```python
from ..utils.logger import log

# 普通节点
log.info("启动", "startup", "主窗口 启动成功")

# 用户操作（推荐用这个，会自动带 键=值）
log.op("设置", "update", key="theme", old="跟随系统", new="深色主题")

# 警告 / 错误（msg 后面可以继续跟 键=值）
log.warn("部署", "download", "跳过", code="TG-999999", reason="资源库里没有这个编码")
log.err("下载", "download", f"下载失败: {e}", url=url)

# 调试（默认不输出）
log.dbg("调试", "debug", "中间变量", value=x)
```

**规则：**

1. **不要用 `print()`** —— 一律走 `log`，否则终端和日志会对不上
2. 分类用「中文分类 + 英文子类」，中文给人看、英文给脚本筛
3. 结构化信息一律写成 `键=值`，不要拼成一句话
4. 可能含密钥的字段名请加进 `utils/logger.py` 的 `REDACT_KEYS`
5. 插件里用 `context.log("消息")`，会自动带上插件名

---

## 六、日志格式版本

| 版本 | 变化 |
|---|---|
| v1.1.4 | 统一格式；新增 `OP` 操作级别；时间加日期；级别对齐；终端与文件同源；敏感值打码 |
| 旧版 | `[HH:mm:ss.fff] [LEVEL] [MAIN] [中文\|english] 消息`（没有日期，级别不对齐，部分输出走 print） |
