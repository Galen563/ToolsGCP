# ToolsGCP 安全模型与工程规范化

> 本文档对应 `v1.1.4`。带 ✅ 的是本轮已经落地的改动，带 ⏳ 的是建议后续处理的事项。

---

## 一、安全模型

### 1. 先把威胁模型说清楚

一个"本地工具聚合器"真正需要防的不是黑客攻击，而是下面这几类：

| 编号 | 威胁 | 现实后果 | 现状 |
|---|---|---|---|
| T1 | 配置文件里的第三方密钥被读取 | API Key 被盗刷 | ✅ 已加密 |
| T2 | 把"密钥"当权限边界 | 反编译即绕过，形成虚假安全感 | ⏳ 需重新定位 |
| T3 | 下载的文件被替换 / 下到错误路径 | 用户装到恶意程序 | ⚠️ 部分处理 |
| T4 | 资源索引 JSON 被投毒 | 卡片显示钓鱼链接 | ⏳ 需校验 |
| T5 | 全局热键独占 | 抢掉其它软件的快捷键 | ✅ 可关闭 / 可改键 |
| T6 | 单实例互斥体被抢占 | 程序打不开 | ⚠️ 可接受 |

---

### 2. T1：密钥存储 —— ✅ 本轮修复

**原来的问题**

`toolsgcp_config.json` 里 `"api_key": "sk-xxxx"` 是明文的。任何能读到这个文件的东西（同步盘、备份、误传的截图、别人借用电脑、被顺手打包进 issue 的日志）都能直接拿到。

**现在的做法**：`pymodels/utils/secret_store.py`

- Windows 上用 **DPAPI**（`CryptProtectData` / `CryptUnprotectData`）加密；
- 密文只能用**同一台电脑 + 同一个 Windows 用户**解开，拷到别的机器上是废数据；
- 程序本身**不保存主密钥**——这是关键。很多程序"加密"密钥的做法是把主密钥也写在同一份代码里，那叫混淆，不叫加密；
- 加了程序自带的一段 entropy，换个程序也解不开；
- 配置里新增 `api_key_enc`，同时**清空** `api_key`，避免"加密了但明文还躺着"；
- 兼容旧配置：读到旧明文会自动上迁移，用户无感。

```jsonc
// 迁移前
{ "api_key": "sk-xxxxxxxx" }
// 迁移后
{ "api_key": "", "api_key_enc": "dpapi:AQAAANCMnd8BFdERjHoAwE/Cl+sBAAAA..." }
```

非 Windows 平台自动降级为 `plain:` 前缀的 base64，并**明确标记**——不假装安全，代码里一眼能看出这是弱保护。

**⏳ 还可以做的**

- 「清空 API Key」时提供"安全擦除"提示；
- 如果以后要存更多凭据，统一走 `secret_store`，不要再往 JSON 里塞明文；
- 日志里绝对不能打印 `get_api_key()` 的返回值（现在没有打印，但要在 review 时守住这条）。

---

### 3. T2：把密钥当权限 —— ⏳ 必须重新定位

`pymodels/constants.py` 里：

```python
VALID_GCP_KEYS = ["GCP-74G2-N052-8X42", ...]     # 4 个"许可证"
DEV_KEYS = {"GCP-G756-23L4-N375": "Galen563", ...}  # 开发者密钥
```

**事实是**：Python 打成 exe 之后，这些字符串用 `strings` 或者随便一个反编译器就能捞出来；就算用 Cython/Nuitka 也只是抬高门槛，不是安全边界。

**所以现在的定位是对的**——它们只是"解锁隐藏 UI"的彩蛋，不涉及付费、不涉及数据权限。**请务必守住这条线**：

- ❌ 不要用它做付费校验（用户白嫖零成本，且你无法吊销）；
- ❌ 不要用它做"只有开发者能执行危险操作"的权限（一样能绕过）；
- ✅ 可以继续用它做"给赞助者的彩蛋 / 调试面板开关"。

**如果将来真要做授权**，唯一可用的方向是**服务端校验**：

1. 客户端把密钥 + 机器指纹发给你的服务器；
2. 服务器签发一个**短期**（比如 7 天）的签名 token（Ed25519）；
3. 客户端内置**公钥**，只验签，不存私钥；
4. 到期自动续签，吊销在服务端做。

公钥放客户端是安全的，私钥永远不出服务器——这是唯一能真正防绕过的结构。

---

### 4. T3：下载安全 —— ⚠️ 部分处理

`pymodels/utils/downloader.py` 是新增的"一键部署"下载器，几点说明：

| 风险 | 处理 |
|---|---|
| 路径穿越（文件名里带 `../`） | ✅ `safe_filename()` 过滤 `\/:*?"<>|` |
| 半截文件被当成完整安装包 | ✅ 先写 `.part`，成功后才 `rename` |
| 断网 / 404 静默失败 | ✅ 异常统一走 `failed` 信号，UI 标红并记录日志 |
| 下载来源不可信 | ⚠️ 只从「资源里显式写的 `download_url`」或「该资源 GitHub 仓库的 Releases API」取地址，不接受资源 JSON 里的任意跳转 |
| **完整性校验** | ⏳ **没做**。建议：Release 资产如果有 `.sha256` 附件，下载后自动比对；资源 schema 里增加 `download_sha256` 字段 |
| **HTTPS 证书** | ✅ 用的 `urllib` 默认校验（没有关过验证） |
| 限速逻辑被用来绕过 | 无所谓，限速只是本地体验 |

**⏳ 建议补上**：

1. 资源 schema 增加 `"download_sha256": "..."`，下载完成后比对，不一致就删文件并报错；
2. 下载目录里附一个 `来源.txt`，写清每个文件是从哪个 URL 来的——出事时能追溯；
3. 一键部署前，把"将要从哪些域名下载"列出来给用户确认一次。

---

### 5. T4：资源索引投毒 —— ⏳ 需要校验

`ToolsGCP-Resources.json` 以后是要从 GitHub 拉取的（支持社区 PR），那它就是一坨**外部输入**。原则：

- **永远不要**对 JSON 里的字符串做 `eval` / `exec` / `os.system`（现在没有，要保持）；
- `icon` 字段只允许是文件名，`ResourceLoader._normalize` 会拼到 `metadata.icon_dir` 下；⏳ 还应该**再挡一层**：解析后校验最终路径必须落在 `.ToolsGCP/Icon/` 之内，防止 `"icon": "../../../../Windows/System32/xxx"`；
- `url` / `github` / `chat_url` / `author_url` 只允许 `http(s)://`，打开前再校验一次协议（防止 `file://` 或 `javascript:`）；
- ⏳ 发布前对 JSON 做一次 schema 校验（可以参考新加的 `ToolsGCP-ResourceMaker.pyw` 的 `validate()`，它就是按这个思路写的）。

---

### 6. T5：全局热键 —— ✅ 已做，但要提醒用户

`RegisterHotKey` 是**独占**的：注册成功之后，其它程序（包括浏览器）再也收不到这个组合键。

- 默认给了 `Ctrl+Q`。这个键在浏览器（退出）、很多编辑器里都有用途，**属于比较激进的默认值**；
- 设置页新增「快捷键」区域，可以随时关掉或改键；
- 注册失败（被别的程序占了）会弹提示并**自动回滚开关**，不会出现"显示开着但实际没生效"；
- 想更保守的话，建议默认改成 `Ctrl+Alt+Q` 之类——改一个常量即可（`pymodels/constants.py` 的 `hotkey_search`）。

---

### 7. T6：单实例与其它

- 互斥体名 `ToolsGCP_SingleInstance_Mutex_v1.0` 写死了版本号，**别的进程可以用同名互斥体把你挡在门外**（低危，但改版本号会顺带解决）。⏳ 建议改成基于安装路径的 GUID。
- 程序**没有任何联网行为**（除了资源更新和下载），这是卖点，别破坏它。⏳ 如果在 README 里承诺"无遥测"，就要在代码 review 时守住。

---

## 二、工程规范化

### 1. ✅ 版本号单一来源

以前 `APP_VERSION` 在两个文件里各写一份，还都是 `1.0.0`（而目录叫 v1.1.4）。现在：

- 唯一来源：`pymodels/constants.py` 的 `APP_VERSION = "1.1.4"`；
- `pymodels/core/constants.py` 改成**转发模块**（`from ..constants import *`），保留兼容但不再有第二份真实数据 —— 这种"改错文件"的坑就是这么埋下的。

⏳ 进一步：让 `APP_VERSION` 从 `version.txt` 或 git tag 读取，CI 里自动注入。

### 2. ✅ 依赖声明

`requirements.txt` 以前写的是两行 `pip install ...`（不是合法的 requirements 文件，`pip install -r` 会直接报错）。现在改成标准格式并带上版本范围：

```
PyQt5>=5.15.9,<5.16
PyQt-Fluent-Widgets>=1.11,<2
```

带**上界**很重要：qfluentwidgets 的次版本升级经常改 API（这轮开发里就踩到 `ComboBox.setEditable` 不存在、`FluentLabelBase` 改写样式表等），不锁上界会让"用户装完打不开"。

### 3. ✅ .gitignore

新增，重点是把**运行期用户数据**挡在版本库外：

```
.ToolsGCP/config/                   # 程序自己写出来的配置全在这里（含加密密钥）
.ToolsGCP/privacy_policy.json       # 每个用户的同意记录
.ToolsGCP/logs/                     # 日志里可能有本机路径
__pycache__/  build/  dist/  *.spec
```

> 说明：`toolsgcp_config.json`（可能含加密密钥）、`favorites.json`、`deploy_config.json`、
> `plugins.json`、`plugin_data/`、`chats/`（AI 历史对话）现在统一在 `.ToolsGCP/config/` 下，
> 所以一条 `.ToolsGCP/config/` 就够了；老版本的平铺路径写在 README 的迁移说明里。

顺便说一句：仓库里现在的 `__pycache__/*.pyc` 应该清掉并忽略——它们会让 diff 变得没法看。

### 4. ✅ CI / 自动发布

新增 `.github/workflows/release.yml`：打 `v*` 标签就自动

1. `compileall` 语法检查；
2. 校验所有 JSON 合法性；
3. PyInstaller 打出 `ToolsGCP.exe` 与 `ToolsGCP-ResourceMaker.exe`；
4. 生成 `SHA256SUMS.txt`（用户校验用，也是"没被杀软掉包"的凭证）；
5. 自动建 Release 并挂上文件。

> ⚠️ 这个 workflow 我**没有本地跑过**（GitHub Actions 只能在 GitHub 上跑）。第一次跑可能会需要微调 PyInstaller 的参数（尤其是 `.ToolsGCP` 资源目录的 `--add-data` 路径分隔符）。

**⏳ 发布闭环还差**：

- **代码签名**：没有签名的 exe 会被 SmartScreen 拦、被国产杀软误报。个人开发者可以先用免费的 **SignPath.io** 开源项目签名，或者退一步——在 Release 说明里贴 VirusTotal 链接 + SHA256，并明确告诉用户"如果杀软报毒，这是 Python 打包的误报，可自行上传 VirusTotal 复核"；
- **更新检查**：设置页的「检查更新」现在是占位符。接 GitHub Releases API 就能实现；
- **可复现构建**：固定依赖版本 + 记录构建环境的 Python 版本。

### 5. 代码结构

现在的分层是清楚的：`core`（无 UI 的纯逻辑）/ `interfaces`（页面）/ `widgets`（可复用组件）/ `ui`（窗口级）/ `utils`（工具）。本轮新增也都放在这个框架里。几点建议：

- **`utils` 里的东西要"无 UI 依赖"**。`downloader.py` 引入了 Qt 信号（`QThread`），严格说是"带 UI 框架的工控层"。可以接受，但要知道这个边界；
- **页面不要直接读配置字典**，走 `SettingsManager` 的方法（本轮 `get_api_key/set_api_key` 就是按这个原则加的）；
- **文案全部走语言文件**，不要在代码里硬编码中文再"顺便"塞进 `get_text` 的兜底字典里。现在的兜底字典已经有两百多个键，是历史包袱。

### 6. 数据文件规范

`ToolsGCP-Resources.json` 现在有明确的 schema 约定（写进了 `ResourceLoader` 的 docstring）：

- `metadata.icon_dir` 给出图标目录，条目里 `icon` **只写文件名**；
- 每条必须有 `id`（唯一）和 `code`（唯一，`TG-0001` 形式，部署清单靠它指代程序）；
- 空字段直接省略，不写 `""` / `[]` / `{}`；
- 当前 **40 KB / 41 条**（优化前 123 KB）。

⏳ 建议再加一个 `schema_version` 迁移函数：读到旧版本时自动升级，而不是靠"字段缺失就跳过"。

### 7. 日志规范

`logger.py` 已经是"按启动归档 + 只留最近 30 份"的结构，够用。建议：

- **日志里不要出现密钥、完整路径之外的隐私信息**；
- 给用户一个"导出诊断日志"按钮（打包 zip 时**自动脱敏**用户名和路径）——这是让用户愿意反馈问题的关键；
- ⏳ `system_log.log` 现在每次启动都会覆盖，用户遇到崩溃时日志可能已经被下一次启动冲掉。建议崩溃时单独落一份 `crash_<时间>.log`。

---

## 三、本轮已落地的清单

| 项目 | 文件 |
|---|---|
| API Key DPAPI 加密 + 旧数据自动迁移 | `utils/secret_store.py`、`core/settings_manager.py` |
| 下载器安全（路径过滤 / `.part` 原子落盘 / 异常上报 / 限速） | `utils/downloader.py` |
| 全局热键可关闭 / 可改键 / 失败回滚 | `utils/global_hotkey.py`、设置页「快捷键」 |
| 版本号单一来源 | `constants.py`、`core/constants.py`（转发） |
| 依赖声明规范化（含版本上界） | `requirements.txt` |
| 忽略运行期用户数据 | `.gitignore` |
| 自动构建 + Release + SHA256 | `.github/workflows/release.yml` |
| 资源索引瘦身 67% + 惰性索引 | `ToolsGCP-Resources.json`、`core/resource_loader.py` |

## 四、建议的处理顺序

1. **代码签名 / VirusTotal + SHA256**（直接影响下载转化率，安全收益也最大）
2. **资源 JSON 的下载 sha256 与路径校验**（一键部署一旦放量，这是唯一会伤到用户的点）
3. **更新检查**（有 Release 之后就能接，顺便建立"用户知道有新版本"的通道）
4. **GCP 密钥重新定位**（只要不越界成付费/权限，就不是紧急问题）
5. 崩溃日志 + 诊断导出
