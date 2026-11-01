# 资源库 schema（ToolsGCP-Resources.json）

> 唯一事实来源：`.ToolsGCP/modules/pymodels/core/resource_schema.py`
> 版本：`schema_version = 2.1.0`（2.0.0 → 2.1.0：`category` 变数组、`tags` 不再重复类别）

这份文档存在的理由：以前 `category` 是逗号拼接的字符串、`tags` 里又抄一份类别、
`description` / `intro` / `supplement` 三个文本字段的差别只写在代码注释里 ——
结果就是文件越写越乱、每个消费方各自解释一遍。现在字段含义、类型、枚举都在
`resource_schema.FIELDS` 里（代码和本文档同一份来源），加字段请先改那里。

---

## 顶层结构

```json
{
  "schema_version": "2.1.0",
  "metadata": {
    "name": "ToolsGCP Resources",
    "description": "ToolsGCP 资源索引文件",
    "icon_dir": ".ToolsGCP/Icon",
    "updated_at": "2026-10-05T18:11:18+08:00",
    "total_count": 53
  },
  "resources": [ { ... } ]
}
```

- `icon_dir`：图标目录，条目的 `icon` 只写文件名，加载时由 `ResourceLoader` 补成 `目录/文件名`。
- `total_count` / `updated_at`：由写入方（制作器、迁移脚本）维护，**不要手改**。

---

## 字段一览

| 字段 | 类型 | 必填 | 用途（一句话） |
|---|---|---|---|
| `id` | str | ✅ | 英文 slug 主键（`localsend`）：详情页、图标名、条目身份 |
| `code` | str | ✅ | 系统编码 `TG-000001`：收藏夹、部署清单、AI 工具拿它当主键 |
| `name` | str / i18n | ✅ | 名称：卡片标题、详情页标题 |
| `category` | **list[str]** | | 类别：搜索页分组与类别筛选、定制页喜好来源 |
| `tags` | list[str] | | 补充标签（**不含** `category` 里已有的值）：详情页胶囊、标签筛选、AI 检索词 |
| `description` | str / i18n | | **简介**：卡片上那一行、详情页标题下的小字，≤100 字 |
| `intro` | str / i18n | | **应用介绍**：详情页「应用介绍」正文，可写几段；留空时退回 `description` |
| `supplement` | str / i18n | | **补充说明**：接在应用介绍后面的一段（注意事项、平台差异） |
| `icon` | str | | 图标文件名，如 `localsend.png`（目录见 `metadata.icon_dir`） |
| `url` | str | | 官网 / 官方下载页 |
| `github` | str | | 开源仓库完整地址（GitHub / GitCode / Gitee / GitLab 都写这里） |
| `download_url` | str | | 直接下载地址；留空时部署页退回用 `github` |
| `author_url` | str | | 作者主页 |
| `chat_url` | str | | 交流群 / 社区 |
| `listed_at` | str | | 上架时间 `YYYY-MM-DD HH:MM:SS`；搜索页「更新时间」按它筛 |
| `systems` | list[enum] | | 适用系统，多选，见下 |
| `architectures` | list[enum] | | CPU 架构，多选，见下 |
| `variants` | list[obj] | | 多版本 `[{key,label,url}]`（如 Trae 的国内版/国际版） |
| `default_variant` | str | | 默认版本 `key`；加载时把它的链接提升到顶层 |

**三个文本字段怎么分工**（这是以前最容易搞混的地方）：

```
description  一句话简介 —— 卡片上显示的那一行（≤100 字）
intro        应用介绍 —— 详情页正文，可以写几段；留空时详情页退回显示简介
supplement   补充说明 —— 接在应用介绍后面的一段（注意事项、平台差异等）
```

### 枚举

```python
SYSTEMS       = ("全平台", "Windows", "macOS", "Android", "iOS", "Linux", "web", "其他")
ARCHITECTURES = ("x64", "x86", "arm64", "arm", "Apple Silicon", "其他")
```

- 顺序就是界面上的顺序（制作器的胶囊、搜索页的筛选项）。
- `全平台` 是**元值**：表示覆盖全部平台，不表示"同时是 Windows 和 macOS"。
- `Apple Silicon` 与 `arm64` 语义重叠，但**故意不合并**：库里两者各有一批条目，
  合并等于替用户改数据，还会改掉搜索页「CPU 架构」的筛选项。读入时只统一大小写。
- 读入时按别名表归一大小写（`windows→Windows`、`aarch64→arm64`、`osx→macOS`…）；
  **认不出来的值原样保留**，由 `validate()` 报出来，绝不悄悄吞掉。
- `category` **不是**闭集：可以直接在制作器里输入新类别（`CATEGORIES` 只是候选列表）。

### 多语言（现在**库里每条都是三语言**）

`name` / `description` / `intro` / `supplement` 四个字段在库里的实际形态是：

```json
"name":        { "简体中文": "本地发送", "繁體中文": "本機傳送", "English": "LocalSend" },
"description": { "简体中文": "…",       "繁體中文": "…",       "English": "…" }
```

- 读取时 `ResourceLoader` 会按**当前界面语言**把它压成一句话再进内存
  （`resource_schema.first_text`，回退顺序：当前语言 → 简中 → 繁中 → 英文 → 第一个非空值），
  所以消费方拿到的永远是字符串，不需要自己判断类型。
- **写入**（制作器）走的是 `build_entry()`：先 `normalize()` 再合并多语言字典 ——
  顺序反了会被 `normalize()` 按当前语言压扁成一种语言。
- `category` / `tags` / `systems` / `architectures` **仍然是规范值**（中文 / 固定枚举），
  **不写成多语言字典**：搜索页的类别分组、筛选、定制页喜好、AI 检索词、
  部署清单全都按这些规范值匹配。它们的**显示译名**单独放在
  `.ToolsGCP/modules/languages/common_language.json` 里（key = `term_<规范值>`），
  由 `core/language_manager.translate_term()` 查表 —— 查不到就原样显示（用户自建的新类别）。
- 新增 / 修改资源后想补翻译，用这个脚本：
  ```bash
  python 项目资料-文档与开发测试/tools/add_i18n_keys.py   # 批量补语言键
  ```
  （当年的分片翻译工具链 i18n_split_parts / i18n_merge_parts / check_resources_i18n
   是一次性脚本，使命已完成，2026-10-31 清理中移除，git 历史可查。）

---

## 兼容与规范化（`normalize()`）

`ResourceLoader` 是唯一的读数入口：磁盘上每一条都先过 `resource_schema.normalize()`
再进内存，所以**所有消费方拿到的永远是规范形态**，它们不需要知道磁盘上以前长什么样。

`normalize()` 能吃下的历史形态：

```jsonc
"category": "工具"                                   // -> ["工具"]
"category": "工具,游戏" / "工具，游戏" / "工具、游戏"   // -> ["工具", "游戏"]
"category": ["工具", "游戏"]                          // 原样
"category": {"简体中文": "工具", "English": "Tools"}  // -> ["工具"]
"tags": ["工具", {"简体中文": "官方"}]                 // -> ["官方"]（工具与类别重复，去掉）
"systems": "Windows"                                 // -> ["Windows"]
```

⚠️ **不拆 `/`**：`建筑/设计` 是一个正经类别，按斜杠拆会把一个类别拆成两个。
分隔符固定为 `, ， 、 ; ；`（`CATEGORY_SPLIT_CHARS`）。

规范化只改三件事，「轻量」指的是**概念少**、不是字段名短：

1. `category` 一律是 `list[str]`；
2. `tags` 去掉所有与 `category` 重复的值（本次迁移删掉了 51 个）；
3. 多语言字典按当前语言解析成字符串，枚举统一大小写，字段按固定顺序落盘。

字段名一个都不改（`category` / `description` / `url` / `icon` …）—— 改名要动上百处
调用点，换不来任何用户可见的好处。不认识的字段（`version`、将来新加的）**原样保留**。

## 校验（`validate()`）

对原始形态和规范形态都能用，**永不抛异常**，返回人类可读的问题列表：

- 缺必填字段（`id` / `code` / `name`）；
- `id` 与 `code` 相同（两种标识分不开）；
- `systems` / `architectures` 里出现不在枚举里的值；
- `tags` 里重复了 `category` 的值；
- 链接字段不是完整的 `http(s)://` 地址。

## 访问器（别再自己拆 / 自己 `or`）

```python
rs.code_of(item)          # 主键：code 优先，退回 id
rs.id_of(item)
rs.name_of(item, lang)
rs.categories_of(item)    # 类别列表（规范/历史形态都能读）
rs.tags_of(item)          # 标签列表
rs.keywords_of(item)      # 检索词 = 类别 ∪ 标签  ← 搜索/筛选/AI 都用它
rs.summary_of(item, lang) # 一句话简介：description，空了退回 intro 首句
rs.links_of(item)         # [{field, url}]，含变体里的链接
rs.systems_of(item) / rs.architectures_of(item)
rs.normalize(item, lang) / rs.validate(item)
```

**为什么筛选一律用 `keywords_of`**：以前类别是抄一份进 `tags` 的，所以"只看 tags"
恰好等于"类别 + 标签"；`tags` 去重之后只看 tags 会凭空少掉「工具 / 游戏 / AI」这些
最常见的筛选项。取并集后，搜索页标签筛选的选项集合（36 个）与重构前完全一致。

---

## 迁移与自检（历史）

> 资源库已完成 schema 迁移（当前 `.ToolsGCP/ToolsGCP-Resources.json` 就是新格式），
> 迁移脚本 migrate_resources_schema.py 与自检脚本 check_resources_schema.py 是一次性工具，
> 使命完成后于 2026-10-31 清理中移除；需要回看实现细节走 git 历史。

迁移脚本的硬约定：先备份再写、幂等（内容没变就一个字节都不动）、写盘前逐条核对
"原来非空的字段还在不在"（少一个就中止，宁可不迁也不丢数据）。

### 2.0.0 → 2.1.0 实际迁移结果

| 项目 | 数值 |
|---|---|
| 条目数 | 53（不变） |
| 类别拆多值 | 1 条（`"工具,游戏"` → `["工具", "游戏"]`） |
| 删除重复标签 | 51 个（标签里与类别重名的值） |
| 标签总数 | 107 → 56 |
| 向后兼容 | 53/53 条旧格式规范化后与迁移结果逐字段一致 |
| 搜索页筛选项 | 类别 9 个、标签 36 个 —— 不变 |
| 定制页喜好清单 | 工具25 游戏13 官方12 AI9 聊天9 MC启动器6 启动器3 编程3 游戏引擎2 视频平台2 —— 不变 |

迁移后**没有丢任何命中**；有两处"多出命中"，是被修好的老问题：

- 标签 `工具` 多出 OBS / Human Benchmark，`编程` 多出 Python：这几条的类别以前
  没有抄进自己的 `tags`，用标签筛选根本搜不到它们；
- 类别 `工具` / `游戏` 多出 GSManager：它原来的 `category` 是 `"工具,游戏"`
  一整串，任何类别筛选都匹配不上。
