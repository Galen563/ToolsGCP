# ToolsGCP 自动更新（自更新）方案 · 计划

> 对应版本：`v1.0.0-beta.1`
> 目标仓库：`https://github.com/Galen563/ToolsGCP`
> 更新来源：`https://github.com/Galen563/ToolsGCP/releases`

---

## 实施进展（截至 v1.0.0-beta.1）

| 阶段 | 内容 | 状态 |
|---|---|---|
| **阶段 1** | 版本解析比较 + 查询 GitHub + `ToolsGCP.exe` 识别 | ✅ **已完成** |
| **阶段 2** | 下载到 **%TEMP%** + SHA-256 校验 + 进度反馈弹窗 | ✅ **已完成** |
| **阶段 3** | 自替换（**%TEMP% 临时更新器**）+ 回滚 + 提权 | ✅ **已完成**（本轮按需求重写：不再是托孤 `.cmd`，见 4.6） |
| **阶段 4** | 启动静默自动检查 | ⬜ 未做 |

已经落地的具体东西：

- `.ToolsGCP/modules/pymodels/core/updater.py` —— 版本比较 / 通道过滤 / 目标识别 / 两个工作线程
- `.ToolsGCP/modules/pymodels/core/self_update.py` —— 自更新：能不能换（原因码）+ 拉起临时更新器 + 更新器主流程（进程句柄等待 / 备份 / 覆盖 / 回滚 / 提权）+ 启动后清理
- `.ToolsGCP/modules/pymodels/ui/update_dialog.py` —— 「发现新版本」/「下载进度」/「无法自动替换（统一提示原因）」三个弹窗
- `interfaces/settings/cards_misc.py` —— 「关于」卡片改成 `程序名 / logo / 版本号` 竖排 + 真实的检查更新 + 下载完自动替换重启
- `interfaces/settings/cards_download.py` —— 下载区域新增「更新下载渠道」下拉框
- `ToolsGCP.pyw` —— 入口最前面处理 `--update` / `--cleanup`（必须在单实例检测之前）
- `set_language.json` + `texts.py` —— 59 条新文案，简中 / 繁中 / 英文三语齐全

### 4.6 的最终形态（本轮重写，需求原话）

    主程序下载新版到 %TEMP%（用 GetTempPath），校验 SHA256/签名，
    启动 %TEMP%\ToolsGCP_new.exe --update --pid <当前PID> --target <原ToolsGCP.exe完整路径>，
    主程序退出。临时更新器用进程句柄等待旧 PID 退出（带超时），备份原 exe 为 .bak，
    复制自身到原路径覆盖，启动原路径新版并设置工作目录，然后临时更新器退出。
    原路径新版启动后清理 %TEMP%\ToolsGCP_new.exe 和 .bak，失败则回滚。
    Program Files 下需管理员权限。
    最后说一点 ToolsGCP.exe 原有目录下替换时不要生成一堆文件，
    我只允许原有目录存在 ToolsGCP.exe。

落地时的两个决定（都写进了 `core/self_update.py` 的注释）：

| 决定 | 为什么 |
|---|---|
| **备份放 `%TEMP%\ToolsGCP.bak`，不放程序目录** | 需求同时要求"备份原 exe 为 .bak"和"原有目录只允许存在 ToolsGCP.exe"。放 %TEMP% 两边都满足：回滚照样好使，程序目录永远干干净净。 |
| **等待用 `OpenProcess` + `WaitForSingleObject`** | 需求点名要用进程句柄等；它比轮询 `tasklist` 精确、不占 CPU，而且"OpenProcess 失败"本身就等于"那个进程已经没了"。 |

⚠️ 旧的"托孤 `.cmd` + `ToolsGCP.exe.new`"方案**已整体删除**（它会往程序目录写 `.cmd` / `.new` / `.bak` 三样东西，正是需求里禁止的）。

⚠️ "签名校验"目前只做到 **SHA-256 + PE 魔数 + 最小体积**（Release 挂了 `SHA256SUMS.txt` 时强制校验）。
 代码签名（Authenticode）尚未接入，见 4.7 的清单。

⚠️ **下面第 2 章"现状盘点"记录的是动手之前的状态**，留着是为了说明"为什么要这么改"。
其中第 1、2、7、8、9、10 条现在已经不成立（假的检查更新按钮已经换成真的了）。

---

## 〇、一句话结论

现在设置里的「检查更新」**曾经是个假的**——点一下转 1.8 秒进度环就恢复，代码注释里写得很直白："没有真实更新源"。
（**这一条已经修好了**：现在它是真的去问 GitHub。）
要让它变成真的，不需要发明新东西：GitHub Releases 本身就提供了一套标准的"问答"接口。
真正需要动脑子的只有两件事：**怎么在一堆发布文件里认出 `ToolsGCP.exe`**，以及**怎么让一个正在运行的 exe 把自己换掉**（Windows 不允许，这一条还没做）。

---

## 一、先把"原理"讲清楚（你说不知道这是什么原理，这一章就是回答）

### 1. GitHub Releases 到底是什么

你在 GitHub 上点「Create a new release」时，实际发生了三件事：

1. **打一个 tag**（标签），比如 `v1.1.4`。tag 是 git 里的一个"书签"，指向某个提交。
2. **写一段说明**（release notes / body）。
3. **挂上若干文件**（assets，资产），比如 `ToolsGCP.exe`、`SHA256SUMS.txt`。

所以一个 Release ≈ **一个版本号 + 一段文字 + 一堆文件**。你上传的那个 `ToolsGCP.exe` 就是其中最重要的一个 asset。

### 2. 客户端怎么知道"有新版本了"

程序自己不可能"感知"网络，它必须**主动去问**。三步：

```
第 1 步  问：GET https://api.github.com/repos/Galen563/ToolsGCP/releases
             GitHub 回一串 JSON，每个 release 里有 tag_name、assets 列表、body、prerelease…

第 2 步  比：把远端最大的 tag_name（如 "v1.1.5"）去掉 v 得 "1.1.5"，
             和程序自己写死的 APP_VERSION（如 "1.1.4"）比大小
             → 1.1.5 > 1.1.4，说明有新版本

第 3 步  下：在远端 release 的 assets 里找到名字叫 ToolsGCP.exe 的那个，
             取它的 browser_download_url，下载到本地
```

**这就是全部原理。** 没有任何"推送"、没有服务器、没有长连接——纯粹是客户端定期去 GitHub 问一句"你最新版本是几"。
这也是为什么 GitHub API 有**限流**：未登录状态每小时 60 次（按 IP 算）。所以客户端必须缓存结果，不能每次启动都问。

### 3. 难点在哪：Windows 不允许程序换掉自己

你在 Windows 上删不掉/覆盖不了**正在运行**的 exe（文件被系统锁住）。
所以"下载新版本 → 覆盖旧版本"这一步**不能在 ToolsGCP 自己内部完成**。

业界标准做法是"**托孤**"：

```
ToolsGCP 自己：下载新版到临时目录 → 校验 → 写一个 .cmd 小脚本到临时目录
             → 用"脱离父进程"的方式启动那个 .cmd → 自己退出
.cmd 小脚本：  等 ToolsGCP 进程真的消失 → 把旧 exe 改名成 .bak
             → 把新 exe 复制进来 → 启动新 exe → 删掉自己
```

那个 `.cmd` 只是一段文本文件，不是常驻程序，所以它能安全地做"程序已经死了之后才做的事"。

### 4. `SHA256SUMS.txt` 是干什么的

它是一份"指纹清单"，里面是每个文件的 SHA-256 哈希值。
下载完 exe 后，本地也算一遍哈希，**对不上就坚决不安装**。它能防住：

- 下载被截断 / 中途网络出错损坏（最常见）
- 镜像站/代理投毒（你现在 `constants.py` 里就有 4 个国内镜像：`ghfast.top` / `gh-proxy.com` / `ghproxy.net` / `gh.ddlc.top`）
- 磁盘写入错误

⚠️ 诚实地说：如果镜像站**同时**篡改 exe 和 `SHA256SUMS.txt`，这个校验挡不住（要挡住得用 GPG 签名，属于第三阶段，而且你现在 exe 也没做代码签名）。**它防的是损坏和不完整的下载，以及"改了一个没改另一个"的情况——这已经覆盖了 99% 的真实故障。**

### 5. draft / prerelease / latest 三个概念的可见性差别

| 状态 | 普通用户能看见吗 | 能否被 API 匿名查询到 | 用途 |
|---|---|---|---|
| **Draft**（草稿） | ❌ 看不见 | ❌ 查不到 | 自己先试装，确认没问题再发布 |
| **Prerelease**（预发布，勾选后） | ✅ 看得见（有 Pre-release 标签） | ✅ 能查到，但 `prerelease: true` | beta / rc 测试版 |
| **正式 Release** | ✅ | ✅ `prerelease: false` | 给所有人 |

关键点：
- `GET /releases/latest` **只会返回"最新的正式版"**，自动跳过 draft 和 prerelease。这对正式通道很方便，但**测不了 beta**。
- 所以推荐用 `GET /releases`（列表）自己过滤——这样"正式版"和"测试版"两个通道可以共用一套代码。

### 6. 你现在的发布流程（CI）

`.github/workflows/release.yml` 已经写好了自动化：**推一个 `v*` 开头的 tag → 自动打包 → 自动挂到 Release 上**。

```bash
git tag v1.1.5 && git push origin v1.1.5     # 这一行就能自动发一个版本
```

产出三个 asset：`ToolsGCP.exe`、`ToolsGCP-ResourceMaker.exe`、`SHA256SUMS.txt`。

---

## 二、现状盘点（以下全部是我从你代码里读出来的事实，附位置）

| # | 位置 | 现在是什么 | 结论 |
|---|---|---|---|
| 1 | `interfaces/settings/cards_misc.py:37` | `CHECK_UPDATE_SPIN_MS = 1800`，注释明写"**没有真实更新源**，转一会儿就把文字恢复" | 「检查更新」是纯装饰 |
| 2 | `cards_misc.py:399` `_on_check_update` | 放一个 `IndeterminateProgressRing` 到按钮里，`QTimer.singleShot(1800)` 后复原 | 动画部分**可以复用**，只要把"固定 1800ms"改成"等真实请求回来" |
| 3 | `utils/downloader.py:33` | `GITHUB_API = ".../releases/latest"`，`_pick_asset` 按后缀优先级 + 体积打分 | ⚠️ 这是一个**真的** GitHub Releases 客户端，但它服务的是"部署模式下载第三方工具"，**不是自更新** |
| 4 | `downloader.py:61-88` `_pick_asset` | 优先 `.exe`，**体积越大分越高**，只扣分不排除 | ⚠️ 如果直接拿它做自更新，它会选**体积更大的 `ToolsGCP-ResourceMaker.exe`**，或者任何一个大 exe。**不能复用** |
| 5 | `downloader.py:36` `_asset_cache` | 纯内存 dict，**没有过期时间** | 进程活着就一直用旧结果，限流上是好事，但要加 TTL 和落盘 |
| 6 | 全仓库 | `grep` 不到任何"比较两个版本号"的代码 | 版本比较必须**从零写**（这是最容易埋坑的地方，见 §4.3） |
| 7 | `pymodels/constants.py:11` | `APP_VERSION = "1.1.4"`（当时的值） | 这是**实际生效**的版本号。现已定为 `1.0.0-beta.1`（见 `VERSIONING.md`） |
| 8 | `pymodels/__init__.py:5` | `__version__ = "1.0.0"` | ❌ **陈旧且无人使用**，两个版本号并存，早晚改错文件 → ✅ 已改成从 constants 转发 |
| 9 | `ui/main_window.py:362` | `log.info("启动", "startup", f"版本: {APP_NAME} {APP_VERSION}")` | 版本号**只进了一条日志**，界面上用户永远看不到自己是什么版本 → ✅ 已显示在「关于」卡片 |
| 10 | `cards_misc.py:372` `_create_about_card` | 整个"关于"页**只有一行「检查更新」按钮** | 没有版本号、没有作者、没有链接 → ✅ 已改成 `程序名 / logo / 版本号` 竖排 + 检查更新行 |
| 11 | `constants.py` | `GITHUB_MIRRORS = ["ghfast.top", "gh-proxy.com", "ghproxy.net", "gh.ddlc.top"]` | 已有镜像基础设施，自更新应该复用 |
| 12 | `requirements.txt` 注释 | 提到运行依赖属于 `ToolsGCP.pyw` **和** `ToolsGCP-ResourceMaker.pyw` | ⚠️ 见下 |

### ⚠️ 两个必须在开工前解决的阻断项

**阻断项 A —— `ToolsGCP-ResourceMaker.pyw` 这个文件不存在，但 CI 在引用它。**

`.github/workflows/release.yml` 里：

- 第 35 行：`python -m compileall -q ".ToolsGCP/modules" ToolsGCP.pyw ToolsGCP-ResourceMaker.pyw`
- 第 46-52 行：`pyinstaller --name ToolsGCP-ResourceMaker ... ToolsGCP-ResourceMaker.pyw`

但我在工作目录里**递归找不到任何 `*ResourceMaker*` 文件**（只有 `interfaces/resource_maker_pages.py` 和 `plugins/gcp-plugin-maker/`，都不是 `.pyw` 入口）。

**后果：`compileall` 拿到一个不存在的文件名会以非 0 退出 → 工作流在"代码自检"这一步就失败 → Release 根本发不出来。**
你说"想随便发布几个试试"——**先确认现在这条流水线是绿的**，否则你 tag 推上去，等半天发现什么都没出来。

**阻断项 B —— 只换 exe 到底能不能一起更新图标 / 语言 / 资源库？必须实测。**

这是一个真实存在的矛盾，两边不一致：

- `constants.py:21` `get_script_dir()`：`frozen` 时用 `os.path.dirname(sys.executable)` → **exe 所在目录**
- `ToolsGCP.pyw:98` `CURRENT_DIR`：`os.path.dirname(os.path.abspath(__file__))` → onefile 打包后通常指向 **`sys._MEIPASS` 临时解包目录**

而打包命令是 `--onefile --add-data ".ToolsGCP;.ToolsGCP"`，也就是 `.ToolsGCP`（含 `Icon/`、`modules/languages/`、`ToolsGCP-Resources.json`）**被打进了 exe 内部**。
全仓库**没有任何 `sys._MEIPASS` 的处理代码**。

**这意味着两种可能，必须实测才知道是哪种：**

| 可能性 | 表现 | 对更新方案的影响 |
|---|---|---|
| 甲：程序实际读 exe 旁边的 `.ToolsGCP` | 首次运行 exe 时旁边**不会**自动生成完整的 `.ToolsGCP`（用户会缺图标/语言） | 更新时必须**连 `.ToolsGCP` 一起更新**，只换 exe 没用 |
| 乙：程序实际读 `_MEIPASS` 里的 `.ToolsGCP` | 配置写在临时目录，**每次启动都丢设置** | 已发布的 exe 可能根本没人在用（太反常），需要先修这个 bug |

**实测方法（5 分钟）：** 把 `dist/ToolsGCP.exe` 复制到一个**空文件夹**里双击运行 → 观察退出后该文件夹里有没有出现 `.ToolsGCP` 目录、里面有没有 `config/`。
结果直接决定 §4.8 走哪个方案。

---

## 三、更新目标的识别契约：**`ToolsGCP.exe`**

这是你明确点名的需求："这个里面 `ToolsGCP.exe` 将成为更新目标识别"。
把它固化成一个**契约**，而不是散落在代码里的字符串判断。

### 3.1 契约表

| Asset 名 | 是否必需 | 在自更新里的角色 |
|---|---|---|
| `ToolsGCP.exe` | ✅ **必需** | **更新载荷本体**。按"名字完全相同"匹配，优先级最高 |
| `SHA256SUMS.txt` | ✅ 强烈建议 | 完整性校验用；里面必须有一行以 `ToolsGCP.exe` 结尾 |
| `ToolsGCP-ResourceMaker.exe` | 可选 | **永远不选**（它是另一个程序） |
| `ToolsGCP-<版本>.exe`（可选，带版本号的副本） | 可选 | 仅当"精确名匹配"失败时的兜底候选 |
| 其它任何文件 | 忽略 | — |

### 3.2 选择规则（按优先级，命中即停）

```
① 名字 == "ToolsGCP.exe"（忽略大小写）                → 选中
② 名字匹配 ^ToolsGCP[-_ ]?v?\d[\d.]*\.exe$             → 选中（兜底）
③ 都不匹配 → 报错「该 Release 里没有找到 ToolsGCP.exe」→ 不更新（绝不猜）
```

### 3.3 硬性拒绝规则（**先排除，再选择**）

只要文件名满足下列任意一条，**无条件排除**：

```
- ResourcesMaker / ResourceMaker / Maker       ← 另一个程序
- Setup / Installer / _installer                 ← 安装器不是绿色包
- .txt .json .sha256 .sig .asc .yml .yaml .blockmap .blockmap
- source / src / symbols / debug / test
- *.exe.sha256 这类"校验文件伪装成 exe"
```

### 3.4 为什么可以放心地把文件名"钉死"

因为**打包命令本身就保证了文件名**：CI 里是 `pyinstaller --name ToolsGCP ... ToolsGCP.pyw`，PyInstaller 必然产出 `dist/ToolsGCP.exe`。
所以"asset 叫 `ToolsGCP.exe`"不是运气，是**构建系统的结构性保证**。

好处是巨大的：**更新器永远不需要解析 tag 名就能找到该下哪个文件**——版本号只用来比大小，文件名只用来找文件，两件事彻底解耦。tag 叫 `v1.1.5` 还是 `v1.1.5-beta.2` 都不影响下载。

### 3.5 耦合提醒

这个契约有两端：**代码里的常量** 和 **Release 里实际的文件名**。
所以：常量只写一处（`APP_ASSET_NAME = "ToolsGCP.exe"`），CI 里加一句断言 `if (!(Test-Path dist/ToolsGCP.exe)) { exit 1 }`，防止哪天有人改了 `--name` 却忘了改代码。

---

## 四、方案设计

### 4.1 新增一个模块：`core/updater.py`

**不要改 `downloader.py` 来兼任自更新。** 两者的目标完全不同：

| | `downloader.py`（现有） | `core/updater.py`（新增） |
|---|---|---|
| 服务对象 | 部署模式下载**别人的**工具 | 更新 **ToolsGCP 自己** |
| 选文件的逻辑 | 后缀打分 + 体积越大越好 | **精确文件名匹配** |
| 版本概念 | 无 | 有（比大小） |
| 校验 | 无 | SHA-256 必须校验 |

复用而不是重写：`downloader.py` 里的 `_open()`（带 User-Agent 的请求封装）、`DownloadWorker`（带进度/限速/取消的下载线程，`:167-228`）都可以直接用；只需给 `DownloadWorker` 加一个可选的 `expected_sha256` 参数，下载完成后就地校验。

模块内含四块，**互相独立、可单独测试**：

```
updater.py
├── 版本解析与比较    parse_version() / compare_versions() / is_newer()
├── 远端查询          fetch_releases(channel) → 带缓存、限流、通道过滤
├── 资产识别          pick_update_asset(release) → 严格按 §3 的规则
└── 下载与校验        download_and_verify() → 落临时目录 + SHA-256
```

### 4.2 版本号"单一事实来源"

动手之前有两个版本号（`constants.py` = 1.1.4，`__init__.py` = 1.0.0），这必然出事。
**现在已经统一**：

- **唯一来源**：`pymodels/constants.py` 的 `APP_VERSION`（当前 = `1.0.0-beta.1`）
- `pymodels/__init__.py` 的 `__version__`：已改成 `from .constants import APP_VERSION as __version__`
- 已新增的常量（`constants.py`）：

```python
APP_VERSION   = "1.0.0-beta.1"    # 不带 v，纯 SemVer
APP_CHANNEL   = "beta"            # 本构建自身的通道，只影响界面标注
APP_REPO      = "Galen563/ToolsGCP"
APP_HOMEPAGE  = "https://github.com/Galen563/ToolsGCP"
APP_RELEASES_PAGE = "https://github.com/Galen563/ToolsGCP/releases"
APP_ASSET_NAME = "ToolsGCP.exe"   # ← §3 契约的唯一落点
APP_CHECKSUM_ASSET = "SHA256SUMS.txt"
UPDATE_RELEASES_API = "https://api.github.com/repos/{repo}/releases"
# 更新渠道的三个取值 + 设置默认值 "update_channel": "all"
UPDATE_CHANNEL_ALL / UPDATE_CHANNEL_STABLE / UPDATE_CHANNEL_BETA
```

还顺手加了 `constants.resource_path(*parts)`：同时查"程序目录旁的 `.ToolsGCP`"和
`sys._MEIPASS/.ToolsGCP`，解决 onefile 打包下 logo / 语言文件找不到的问题（见下面阻断项 B）。

**还差一道保险（CI 里做，尚未做）：** 构建时读环境变量 `GITHUB_REF_NAME`（也就是 tag），断言 `tag == "v" + APP_VERSION`，不一致就**让构建失败**。
这一句能永久消灭"我 tag 打了 v1.0.1 但忘了改 constants.py，结果用户永远收不到更新"这个经典事故。

### 4.3 版本比较算法（⚠️ 最容易写错的地方）

**绝对不能直接比字符串。** 字符串比较会得出 `"1.1.10" < "1.1.4"`（因为逐字符比 `'1' < '4'`），
于是第 10 个补丁版本永远更新不出去——这是自更新最经典的翻车方式。

正确做法：

```
1. 去掉前缀 v/V
2. 按 "+" 切掉 build 元数据（不参与比较）
3. 按 "-" 切成 [数字部分, 预发布标识]
4. 数字部分按 "." 拆成整数元组比较          → (1,1,10) > (1,1,4) ✅
5. 数字部分相同时按 SemVer 规则比预发布标识：
   · 没有预发布标识 > 有预发布标识           → 1.1.5 > 1.1.5-beta.1
   · 逐段比较：纯数字段按数值比，数字段 < 字母段
   · 段数少的更小：1.1.5-beta < 1.1.5-beta.1
6. 解析失败（比如 tag 叫 "1.1.4 正式版"）→ 返回"无法比较"
   → 更新器此时必须**拒绝更新**并记日志，绝不"猜一个大小"
```

必须覆盖的测试用例（写代码时直接拿来当单测）：

| 左 | 右 | 期望 |
|---|---|---|
| `1.1.4` | `1.1.10` | 右更大 |
| `1.1.4` | `v1.1.4` | 相等 |
| `1.1.5-beta.1` | `1.1.5` | 右更大 |
| `1.2.0-beta.2` | `1.2.0-beta.10` | 右更大 |
| `1.2.0-rc.1` | `1.2.0` | 右更大 |
| `1.2.0-alpha` | `1.2.0-beta` | 右更大 |
| `1.1.4+build.12` | `1.1.4` | **相等**（build 元数据不参与比较！） |
| `1.1.4 正式版` | `1.1.5` | 解析失败 → 拒绝更新 |

### 4.4 查询策略：用列表，不用 `/latest`

```
GET /repos/Galen563/ToolsGCP/releases?per_page=30

stable 通道：过滤 draft==false && prerelease==false → 取 tag 最大的
beta   通道：过滤 draft==false                     → 取 tag 最大的
```

**为什么不用 `/releases/latest`：**
1. 它无法服务 beta 通道；
2. 如果哪天你只发了 prerelease，stable 用户拿到 404，客户端会误报"检查失败"；
3. 列表能顺便实现"正式版已是最新，但有个更新的 beta"这种提示。

**必须处理的异常：**

| 情况 | 处理 |
|---|---|
| 403 / 429 | 触发限流 → 提示"今日检查次数已用完，请稍后再试"，并延长缓存 |
| 404 | 仓库不存在或没有 Release → "作者还没有发布任何版本" |
| 超时 / DNS 失败 | "网络不可用"，**不得阻塞启动流程** |
| JSON 结构异常 | 记日志 + 友好报错，绝不能抛到 UI 线程 |

**缓存：** 结果落盘到 `.ToolsGCP/config/update_cache.json`，含 `checked_at` + `latest_tag`。
规则：手工点按钮 = 强制查（但 60 秒内重复点击走缓存）；启动自动查 = 24 小时内查过就不查。

**镜像：** 复用 `constants.GITHUB_MIRRORS`。
注意分工——**查询走 `api.github.com`**（镜像站一般只代理下载），**下载走镜像前缀**：
`https://ghfast.top/https://github.com/Galen563/ToolsGCP/releases/download/v1.1.5/ToolsGCP.exe`。
每个镜像的 URL 拼接形式不同，要逐个验证；且镜像不可信 → 这就是 §1.4 里 SHA-256 校验的用武之地。

### 4.5 界面流程（**进度环保留，只是不再空转**）—— ✅ 已实现

你之前明确要求过"按钮里的文字换成不确定进度环、不要顶部 InfoBar"——**这个设计保留了**，
只把 `QTimer.singleShot(1800)` 换成真实请求的信号回调。实际做出来的流程：

```
点击「检查更新」
  → 按钮文字清空 + 进度环开始转 + 禁用（原代码保留）
  → UpdateCheckWorker(QThread) 发请求（UI 线程绝不碰网络）
  → 信号回来，无论成功失败都收掉进度环、恢复文字
  → 分支：
      · 无更新   → InfoBar「当前已是最新版本（v1.0.0-beta.1）」
      · 有更新   → 弹「发现新版本」窗：logo / 版本号 / Beta 标识
                   + 当前版本 / 最新版本 / 更新文件 / 文件大小 / 发布日期
                   + 版本信息（release body，可滚动）
                   [ 稍后 ]  [ 打开发布页 ]  [ 立即下载 ]
      · 出错     → InfoBar 显示具体原因（错误码 → 三语文案）
  → 20 秒兜底超时（UPDATE_CHECK_TIMEOUT_MS），进度环绝不会无限转
```

点「立即下载」之后是第二个弹窗（**当前阶段下到 %TEMP%，下完自动替换重启**）：

```
「正在下载更新」窗
  · 文件名 + 总大小
  · 进度条（真实百分比）
  · 17.45 MB / 45.00 MB  ·  2.30 MB/s      ← 已下载 / 总量 / 实时速度
  · [ 取消 ]                                ← 点它或直接关窗都会掐掉下载线程
下载完成 → 同一个窗切成完成态：
  · 标题变「更新包下载完成」，进度条 100%
  · 显示保存的完整路径
  · [ 打开文件夹 ]  [ 关闭 ]
  · 关掉后再补一条成功 InfoBar
```

**「关于」卡片（`_create_about_card`）实际做出来的样子：**

```
        ToolsGCP            ← APP_NAME
        [ logo ]            ← .ToolsGCP/logo.png，72×72 等比
     v1.0.0-beta.1          ← 版本号，界面首次可见
检查更新        [ 检查更新 ]
```

⚠️ 和原计划的差别：**「更新通道」下拉框没有放在这里**，而是按你的要求放到了
「设置 → 下载」区域（见 `cards_download.py` 的「更新下载渠道」）。

### 4.6 下载 → 校验 → 自替换（最难的一步）

```
第一步 前置检查（在下载 100MB 之前就要做）
  · 程序所在目录可写吗？（装在 Program Files / 只读盘 / 网络盘 → 直接放弃自替换）
  · 磁盘剩余空间够吗？（新版体积 × 2）
  · 失败时 → 不下载，改为"打开发布页让你手动下载"+ 提示"下载到桌面"

第二步 下载到临时目录（绝不下载到程序目录！）
  %TEMP%\ToolsGCP_update\ToolsGCP-1.1.5.exe
  理由：下到一半断网/断电，程序目录里就是一个残缺的 exe，比不更新危险得多
```

> ℹ️ 这一节的"下到程序目录"是阶段 2 的形态；阶段 3 落地后下载目标已经改成
> `%TEMP%\ToolsGCP_new.exe`（见 4.6），程序目录里不再留任何下载产物。

```
第三步 校验（✅ 已实现，见 core/updater.UpdateDownloadWorker）
  · SHA-256 对上 SHA256SUMS.txt（大小写不敏感）；Release 没挂清单就跳过这一步
  · 没有 PE 魔数（"MZ"）/ 体积过小 → 只警告不拦
  · 哈希对不上 → 删掉 .part + 报错，绝不转正
  · 下载先写成 <目标>.part，校验通过才改名转正

第四步 临时更新器（✅ 已实现，见 core/self_update.run_update_mode）
  · 等待旧进程退出：OpenProcess + WaitForSingleObject（带超时，60 秒）
  · 旧 exe → %TEMP%\ToolsGCP.bak（放 %TEMP%，程序目录不留 .bak）
  · 复制"自己"（%TEMP%\ToolsGCP_new.exe）覆盖原路径，再核对体积 + SHA-256
  · 启动原路径新版（工作目录 = 程序目录），让它带 --cleanup 清理临时文件
  · 覆盖失败且不是管理员 → ShellExecuteW(runas) 提权重来；否则回滚并启动旧版
  · 更新器自己退出（`sys.exit(0)`）
  用 subprocess.Popen(..., creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW) 启动
  （CREATE_NO_WINDOW 防止黑色命令行窗口闪一下）

  ⚠️ 为什么不再用 .cmd 托孤脚本：它会往程序目录写 .cmd / .exe.new / .bak 三样东西，
     而需求要求"原有目录只允许存在 ToolsGCP.exe"。临时更新器把中间产物全放 %TEMP%。
```

第五步 自己退出 —— ⚠️ 注意托盘（✅ 已实现）
  你的设置里有 minimize_to_tray / close_mode，窗口关闭可能只是**藏进托盘**。
  更新时触发退出必须走**真正的退出流程**（先摘托盘图标，再 app.quit()），
  否则"程序还活着"→ 更新器一直等 → 用户以为卡死。
  这也是为什么更新器要**等 PID**而不是"等 3 秒"。
  （实现：cards_misc._quit_for_update() 调主窗口的 quit_app()。）

第六步 换不了就说清楚是哪几种原因（✅ 已实现）
  `replacement_blockers()` 只返回"机器码"，界面弹一个**统一提示**：
    · 本次检测到的（红点 + 加粗）：源码运行且目录里没有 exe / 找不到可替换的 exe /
      exe 文件名带非 ASCII 字符 / 目录不可写 / 新 exe 复制不进去 /
      新 exe 复制不进去 / 更新器拉不起来 / 不是 Windows
    · 其它同样会导致失败、但程序没法自动判断的，一并列在下面（灰色）
  这样用户不会只看到一句"更新失败"，而是知道**到底是哪几种原因**。
```

**第 4.6 节的修订（本轮修的"他不替换"）**

用户反馈："更新逻辑替换当前文件夹原有 ToolsGCP.exe，现在这个逻辑有问题他不替换。"
读代码找到了**三个各自独立、都会导致"点了也不换"**的原因，已经全部修掉：

| # | 根因 | 修法 |
|---|---|---|
| 1 | **判定时机错了**。「程序目录里有没有 ToolsGCP.exe」在"刚开始下载"和"下载完"是两个答案 —— 第一次装的时候那个 exe 就是刚下载下来的这一个。界面在**下载前**算一次就把结果钉死成「查看原因」，按钮永远亮不出来。 | 下载前不再下结论（`allow_replace=None`）；下载成功的那一刻重新算一次，见 `cards_misc._on_download_succeeded` + `UpdateProgressDialog.set_replace_blockers`。 |
| 2 | **认文件名而不是认进程**。以前只要"正在跑的文件不叫 ToolsGCP.exe"就判 `RENAMED` 直接放弃；判断目标时又永远去换 `程序目录/ToolsGCP.exe`。用户把 exe 改个名（或换个目录）跑，就永远更新不了。 | `replacement_target()`：优先拿程序目录里的 `ToolsGCP.exe`，没有就换**正在运行的那个进程自己**（`sys.executable`）。只有文件名带**非 ASCII** 时才是真拦（命令行传不过去）。 |
| 3 | **源码运行一律不能换**。只要不是打包运行就报 `SOURCE_RUN`，哪怕程序目录里就摆着一个没人占用的 `ToolsGCP.exe`。 | 源码运行时改为"退回到程序目录里的 `ToolsGCP.exe`"：它没在运行、不会被系统锁住，照样能换（用户明确要求的那一条）。只有"连那个文件都找不到"才拦。 |

⚠️ 顺带说明：源码运行时点「立即重启并更新」，更新器会真的把新版复制成程序目录里的
`ToolsGCP.exe` 并启动它 —— 开发目录里因此会多出一个 `ToolsGCP.exe`，
这是符合"替换当前文件夹原有 ToolsGCP.exe"这个要求的预期行为。

**回滚设计：**
已经落地的是"替换过程中失败就立刻回滚"（备份在 `%TEMP%\ToolsGCP.bak`，回滚后启动旧版）。
⬜ 还没做的是"下次启动时体检"：如果当前 exe 明显是坏的，用 `.bak` 拉回来并提示用户。

### 4.7 安全清单（✅ = 已经落地）

- ✅ **强制 SHA-256 校验**（Release 挂了 `SHA256SUMS.txt` 时），不匹配就删掉、绝不转正
- ✅ PE 魔数（`MZ`）+ 最小体积（1MB）检查 —— 挡住"下回来的其实是个网页"
- ✅ 文件名经 `safe_filename()` 清洗；更新包固定落在 `%TEMP%\ToolsGCP_new.exe`（会覆盖上一次的残留）
- ✅ 下载地址套镜像前先校验镜像在白名单里（`apply_mirror` 只认 `constants.GITHUB_MIRRORS`）
- ✅ 网络请求全部在 QThread 里，UI 线程不碰网络；另有 20 秒兜底超时
- ✅ **不做静默自动安装**，必须用户点「立即下载」
- ✅ 版本号解析失败 → **拒绝更新**，绝不"猜一个大小"
- ✅ 下载与替换产物只在 `%TEMP%`，程序目录里始终只有 `ToolsGCP.exe`
- ⬜ 只允许 HTTPS + 下载域名白名单（部分做到：URL 只可能来自 GitHub API 或白名单镜像的拼接结果）
- ⚠️ 当前 exe **没有代码签名**，Windows SmartScreen 可能拦截。建议中期接入（成本较高）
- ⚠️ 绝不在客户端内置 GitHub Token（反编译即泄露）→ 承受 60 次/小时的匿名限流
- ⚠️ **诚实说明**：如果镜像站**同时**篡改 exe 和 `SHA256SUMS.txt`，这个校验挡不住。
  它防的是下载损坏 / 截断 / 以及"改了一个没改另一个"。要真正抗住得用 GPG 签名（阶段 3 之后）。

### 4.8 `.ToolsGCP` 资源目录要不要一起更新？（取决于阻断项 B 的实测结果）

`.ToolsGCP` 里混着两类东西，**更新时必须区别对待**：

| 类别 | 内容 | 更新时 |
|---|---|---|
| **随程序发布** | `Icon/`、`modules/languages/*.json`、`images/`、`ToolsGCP-Resources.json`、`modules/pymodels/**` | ✅ 可以覆盖 |
| **用户数据** | `config/`（设置、API Key、收藏夹、插件状态、AI 对话）、`logs/`、`backups/` | 🚫 **绝对不能碰** |

两种方案：

**方案甲（推荐先做）：只更新 exe。**
若实测是"程序读 exe 旁边的 `.ToolsGCP`"，则图标/语言/资源库的改动**不会**随 exe 更新——但那没关系，因为你可以在需要时把资源改动和新版 exe 一起发，让"资源库更新"也通过发版本来实现（见 `VERSIONING.md` §6）。

**方案乙（第二阶段）：加一个可选资产 `ToolsGCP-assets.zip`。**
更新器只覆盖上表第一类，永不触碰 `config/`。风险更高（多一个失败点），收益是可以"只更新资源库不发新版"。建议等甲跑稳了再说。

---

## 五、改动文件清单

| 文件 | 动作 | 状态 | 说明 |
|---|---|---|---|
| `.ToolsGCP/modules/pymodels/core/updater.py` | 🆕 新增 | ✅ 已完成 | 版本比较 / 通道过滤 / 资产识别 / 查询线程 / 下载线程 |
| `.ToolsGCP/modules/pymodels/ui/update_dialog.py` | 🆕 新增 | ✅ 已完成 | 「发现新版本」+「下载进度」两个弹窗 |
| `.ToolsGCP/modules/pymodels/constants.py` | ✏️ 改 | ✅ 已完成 | 版本号、更新相关常量、`resource_path()`、`update_channel` 默认值 |
| `.ToolsGCP/modules/pymodels/__init__.py` | ✏️ 改 | ✅ 已完成 | 干掉陈旧的 `__version__ = "1.0.0"`，改为从 constants 转发 |
| `interfaces/settings/cards_misc.py` | ✏️ 改 | ✅ 已完成 | 关于卡片改成 程序名/logo/版本 竖排；`_on_check_update` 接真实请求 |
| `interfaces/settings/cards_download.py` | ✏️ 改 | ✅ 已完成 | 下载区域新增「更新下载渠道」下拉框 |
| `interfaces/settings/texts.py` | ✏️ 改 | ✅ 已完成 | 43 条新文案的**中文兜底** |
| `.ToolsGCP/modules/languages/set_language.json` | ✏️ 改 | ✅ 已完成 | 同样 43 条，简中 / 繁中 / 英文三语齐全 |
| `.ToolsGCP/modules/pymodels/utils/downloader.py` | ✏️ 小改 | ⬜ 没动 | 原计划给它加 `expected_sha256`；实际改成在 `updater.py` 里独立实现，**没碰下载器** |
| `.github/workflows/release.yml` | ✏️ 改 | ⬜ 待办 | 修 `ResourceMaker` 缺失；加 tag↔APP_VERSION 断言；显式设 `prerelease` |
| `docs/VERSIONING.md` | 🆕 新增 | ✅ 已完成 | 版本命名规则 |
| `README*.md` | ✏️ 改 | ⬜ 待办 | 补一段"自动更新"说明，指向这两份文档 |

**刻意没动的**：`ToolsGCP.pyw`、`utils/downloader.py`（第三方资源解析逻辑工作正常，就是别拿来干自更新）。

---

## 六、分阶段落地 + 验收标准

| 阶段 | 内容 | 验收标准 | 状态 |
|---|---|---|---|
| **阶段 0**<br>拆雷 | 修 `release.yml` 的 `ResourceMaker` 引用；确认 tag 推上去能出 Release | 推一个 tag，Release 里真的出现 `ToolsGCP.exe` | ✅ 已完成（ResourceMaker 步骤改成"文件存在才打"） |
| **阶段 1**<br>会看 | 版本比较 + 远端查询 + 资产识别；「检查更新」只报告 | 能准确说出"已是最新" / "发现 vX.Y.Z"，且**永不**误选 ResourceMaker | ✅ 已完成 |
| **阶段 2**<br>能下 | 下载到 %TEMP% + SHA-256 校验 + 弹窗反馈 | 改一个字节 → 校验失败被拦下；正常下载 → 弹窗显示进度和结果 | ✅ 已完成 |
| **阶段 3**<br>会换 | `%TEMP%` 临时更新器自替换 + 托盘正确退出 + 失败回滚 | 点"立即重启更新"后，程序自己变成新版本并正常启动，程序目录里只有 `ToolsGCP.exe` | ✅ 已完成 |
| **阶段 4**<br>好用 | 启动静默自动检查（可关）+ 镜像加速 | 开着自动检查时启动不卡 | ⬜ 待办 |

**已经可以满足"随便发布几个试试"的验证需求了**（阶段 1 + 2 + 3 都做完了）。

---

## 七、怎么安全地"随便发几个试试"（⚠️ 这一章很重要）

### 7.1 先说一个真实风险

如果你的测试版客户端**打开了自动更新**，而你为了测试发了一个高于线上版本的正式 Release
（比如线上是 `v1.0.0-beta.1`，你发了个带真 exe 的 `v1.0.0` 想试试）——
**所有用户都会被真的更新到那个包上。** 删掉 Release 也救不回来，因为更新已经装到人家机器里了。

（⚠️ 阶段 3 的**自替换已经上线**：更新会真的把用户机器上的 `ToolsGCP.exe` 换掉，
所以下面第 7.2 节的测试纪律现在是**硬要求**。）

### 7.2 正确姿势：**把本地版本调低，而不是把远端版本调高**

这是最优雅的测试方法，**零污染**：

```
把测试用的 constants.py 改成  APP_VERSION = "0.0.0"
→ 真实的 v1.0.0-beta.1 Release 立刻就"看起来像新版本"
→ 完整跑通"发现更新 → 弹窗 → 下载 → 校验"全链路
→ 而且下载结果是落在一个真实合法的包上
→ 一个假 Release 都不用发
```

⚠️ 注意：当前本地版本是 `1.0.0-beta.1`，**没有比它更低的正式版可用**，
所以要测"有更新"这一条，必须调到 `0.0.0`（或 `0.0.1`）。

只有在你需要验证"**我发的东西能不能被正确识别**"时，才需要真发 Release，且**一律发 prerelease**。

### 7.3 测试矩阵

| # | 想验证什么 | 怎么做 | 期望结果 |
|---|---|---|---|
| 1 | 无更新 | 保持 `APP_VERSION = 1.0.0-beta.1`，对现有 Release | 「当前已是最新版本」 |
| 2 | 有更新 | 本地改成 `APP_VERSION = "0.0.0"`，对现有 `v1.0.0-beta.1` | 弹窗显示发现 v1.0.0-beta.1 |
| 3 | **目标识别** | 发 prerelease `v9.9.9-test`，asset 同时放 `ToolsGCP.exe` + `ToolsGCP-ResourceMaker.exe` + `SHA256SUMS.txt`，用「仅下载Beta版」查 | **只挑 `ToolsGCP.exe`** |
| 4 | 缺资产 | 发一个 `v9.9.8-test`，只放说明不放 exe | 友好报错"这个版本里没有找到 ToolsGCP.exe"，不崩 |
| 5 | 校验失败 | 下载后手动改一个字节再走校验 | 拒绝安装 + 明确提示 |
| 6 | beta 不影响正式用户 | 发 `v9.9.7-test`（**勾选 Pre-release**），正式通道客户端查 | 仍显示"已是最新" |
| 7 | 非法版本号 | 发 tag `v9.9.6 正式版`（含空格/中文） | 解析失败 → 拒绝更新 + 日志，不猜 |
| 8 | 限流 | 连点 10 次「检查更新」 | 命中缓存，不触发 403 |
| 9 | 自替换 | 点"立即重启更新" | 程序退出→替换→自动重启为新版 |
| 10 | 托盘退出 | 程序最小化到托盘时点更新 | 能真退出（不是藏起来），更新器不卡死 |

**测完立刻清理**：GitHub → Releases → 删除 test Release **和对应 tag**。
注意：删 tag 后如果客户端已经缓存了那个版本号，可能出现"提示更新→又消失"。测试客户端无所谓，正式版本号**永远不要删**（见 `VERSIONING.md` §9）。

---

## 八、需要你拍板的问题（★ = 已经按某个方案做掉了）

| # | 问题 | 结论 / 建议 |
|---|---|---|
| 1 | `ToolsGCP-ResourceMaker.pyw` 到底还要不要？CI 在引用它但文件不存在 | ★ 已按"并进主程序"处理：`release.yml` 里的自检和打包步骤不再依赖它（打包改成"文件存在才打"），这样 tag 才真的能出 Release。要重新单独发布的话，把那个 `.pyw` 放回根目录即可 |
| 2 | 更新要不要也刷新 `.ToolsGCP`（图标/语言/资源库） | ★ 当前只换 exe，暂不涉及 |
| 3 | 允不允许静默自动更新（不点确认就装） | ★ 不允许，必须用户点「立即下载」 |
| 4 | 要不要 beta 通道 | ★ 要。已做成「更新下载渠道」三选一，**默认"下载正式版和Beta版"** |
| 5 | 启动时自动检查更新吗 | ⬜ 阶段 4 再说（延迟 5 秒 + 24 小时缓存 + 设置里可关） |
| 6 | 更新失败要不要自动回滚 | ★ 替换过程失败会立刻回滚；⬜ "下次启动体检"还没做 |
| 7 | 要不要上代码签名 | ⬜ 中期再说；短期接受 SmartScreen 提示 |

---

## 九、相关文档

- **`docs/VERSIONING.md`** —— 版本命名规则（`vX.Y.Z`、beta 怎么用、tag 怎么打）
- `docs/SECURITY_AND_ENGINEERING.md` —— 整体安全模型
- `docs/LOGGING.md` —— 更新过程的日志应写进 `system_log.log`，排查时用得上
