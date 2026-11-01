# ToolsGCP 原版 UI 规格提取（第二册）
## 提交软件 / 应用部署 / 设置补充 / 托盘菜单

> 本文件是**实现依据**，不是综述。每条结论都带 `文件:行号`，能直接照着写代码。
> 与 `docs/py-to-web-spec.md`（第一册）是**并列关系**：第一册覆盖首页/设置主体/导航，本册只覆盖
> ①提交软件 ②应用部署 ③设置里的下载限速、搜索源、下载源 ④主题效果 ⑤托盘菜单。
> 凡本册与第一册冲突，以本册为准（本册是逐行复核后的结果）；不确定的一律写「未能确认」。

---

## 0. 阅读须知

### 0.1 谁才是「原版」

原版 UI 的**唯一**事实来源是 `.ToolsGCP/modules/pymodels/`（PyQt5 + qfluentwidgets），
它现在仍以「启动画面/兼容层」的形式留在仓库里，被 webui 逐步替换。

| 角色 | 路径 | 本册是否作为依据 |
| --- | --- | --- |
| 原版页面实现 | `.ToolsGCP/modules/pymodels/interfaces/` | ✅ 唯一依据 |
| 原版常量 / 语言包 | `.ToolsGCP/modules/pymodels/constants.py`、`.ToolsGCP/modules/languages/*.json` | ✅ |
| 新外壳（pywebview 侧） | `desktop/`、`ToolsGCP.pyw` | ✅ 仅用于第 5、6 节 |
| 新前端 | `webui/` | ⚠️ 只读对照，用来写「网页端缺什么」 |
| 旧 Qt5 入口留档 | `legacy/ToolsGCP.pyw.qt5` | ❌ 与页面结构无关 |

### 0.2 本册涉及的原版文件（行数已核对）

| 文件 | 行数 | 内容 |
| --- | --- | --- |
| `.ToolsGCP/modules/pymodels/interfaces/resource_maker_interface.py` | 582 | 提交软件页外壳（页头 / 分节 / 按需构建） |
| `.ToolsGCP/modules/pymodels/interfaces/resource_maker_pages.py` | 3381 | 四个功能页（表单/浏览/批量/说明） |
| `.ToolsGCP/modules/pymodels/interfaces/resource_maker_core.py` | 528 | 制作器常量与纯函数 |
| `.ToolsGCP/modules/pymodels/interfaces/deploy_interface.py` | 1053 | 应用部署页 |
| `.ToolsGCP/modules/pymodels/interfaces/settings/cards_download.py` | 486 | 设置·下载卡片（资源来源/搜索源/下载源/更新渠道/下载限速） |
| `.ToolsGCP/modules/pymodels/ui/tray_menu.py` | 147 | 托盘右键菜单 |
| `.ToolsGCP/modules/pymodels/core/resource_schema.py` | 509 | 资源字段表 / 枚举 / normalize |
| `.ToolsGCP/modules/pymodels/interfaces/settings/theme.py` | — | 设计尺寸 `SIZES`（`:171-182`） |

### 0.3 全局设计尺寸（所有页面共用，抄这一份）

`.ToolsGCP/modules/pymodels/interfaces/settings/theme.py:171-182`

```python
SIZES = {
    "content_max_width": 880,   # 设置页用；制作器**不用**这个值（见 1.0）
    "content_margin": 30,       # 内容区左右最小留白
    "section_gap": 32,          # 板块与板块之间
    "card_gap": 16,             # 同板块内卡片之间
    "card_padding": 20,         # 卡片上下左右内边距
    "card_radius": 10,          # 卡片圆角
    "row_height": 48,           # 单行高度（带副说明 60）
    "row_height_with_desc": 60,
    "control_width": 200,       # 设置行右侧控件统一宽度
    "sidebar_width": 196,
}
```

制作器里被再次导出的常量（`resource_maker_pages.py:96-111`）：

```python
CARD_RADIUS = 10          # = SIZES["card_radius"]
CARD_PADDING = 20
CARD_GAP = 16
SECTION_GAP = 32
CONTROL_WIDTH = 200
SIDE_CARD_W = 280         # 右侧「预览 + 产出」列宽
PREVIEW_INNER_W = 240     # = 280 - 20*2
TWO_COLUMN_MIN_WIDTH = 820
HELP_TEXT_MAX_WIDTH = 900
FORM_LABEL_WIDTH = 104    # 见 resource_maker_core.py:91
```

工具栏返回的 `CardWidget` 三件套（`resource_maker_pages.py:214-249`）：

* 序号徽标：`CaptionLabel`，`setFixedSize(20, 20)`，`border-radius: 10px`，`font-weight: 600`，底色 `accent_soft`、字色 `accent`（`:214-223`）。
* 卡片标题行：徽标 + `StrongBodyLabel(title)` + `addStretch(1)`（`:236-245`）。
* 标题下一条 1px 分隔线，颜色 `theme_tokens()["card_border"]`（`:205-211`）。
* 卡片内容布局：`setContentsMargins(20, 18, 20, 18)`、`setSpacing(12)`（`:230-232`）。

---

## 1. 提交软件（资源制作器）

入口：左侧栏「更多 → 提交软件」（`nav_language.json: resource_maker = 提交软件`）。
容器类 `ResourceMakerInterface`，`objectName = "resourceMakerInterface"`（`resource_maker_interface.py:215`）。

### 1.0 页面外框（数值）

`resource_maker_interface.py:239-303`

```text
outer QVBoxLayout: margins(0,0,0,0), spacing 0
└─ root QWidget #resourceMakerRoot（AlignHCenter，宽度由 _apply_root_width 固定）
   box QVBoxLayout: margins(30, 22, 30, 16), spacing 12      # :255-257
   ├─ header HBox: spacing 10                                  # :259-260
   │  └─ title_box VBox: spacing 2, stretch=1                  # :261-262, :271
   │     ├─ SubtitleLabel(标题)
   │     └─ CaptionLabel(副标题)  ← setWordWrap(True)，用 style_hint 上色（次要色）
   ├─ divider QFrame: setFixedHeight(1)                        # :275-277
   ├─ toolbar HBox: spacing 8                                  # :279-280
   │  ├─ SegmentedWidget（四个分节）
   │  ├─ addStretch(1)
   │  ├─ library_status CaptionLabel（"资源库 N 条" / "资源库还没建"）
   │  └─ TipIcon(library_tip) 16×16                            # :294-295
   └─ stack QStackedWidget（stretch=1）
```

宽度规则（`:45-52`、`:423-432`）：

* `FORM_MAX_WIDTH = 1600`；四个分节 `SECTION_MAX_WIDTH` **全部 = 1600**（切分节时宽度不变，避免控件跳动）。
* `width = max(360, min(1600, self.width() - 30*2))`，然后 `root.setFixedWidth(width)` + `AlignHCenter`。

页头文案（`resource_maker_interface.py:548-564` 的中文兜底，语言键优先）：

| 元素 | 语言键 | 中文兜底 |
| --- | --- | --- |
| 标题 | `title` | 提交软件 |
| 副标题 | `subtitle` | 制作 / 浏览 / 合并 ToolsGCP 资源库里的条目；改动写进 .ToolsGCP/ToolsGCP-Resources.json，写盘前自动备份。 |
| 资源库提示 ⓘ | `library_tip` | 资源库固定是程序目录下的 .ToolsGCP/ToolsGCP-Resources.json，制作器不会另外生成一份；\n每次写盘前会自动备份到同级 backups/ 目录，只保留最近 20 份。 |

页头右侧状态（`:471-483`）：存在资源库 → `library_count`（"资源库 {n} 条"）；不存在 → `library_missing`（"资源库还没建"）。
`toolTip = "<完整路径>\n" + library_tooltip`。

### 1.1 分节（四个 Tab）

`resource_maker_interface.py:36-41`

```python
SECTIONS = [
    ("form",    "投稿表单", FIF.EDIT),
    ("browser", "资源浏览", FIF.LIBRARY),
    ("batch",   "批量合成", FIF.ZIP_FOLDER),
    ("help",    "使用说明", FIF.HELP),
]
```

语言键：`section_form` / `section_browser` / `section_batch` / `section_help`（`maker_language.json`，值同上表）。
控件：`SegmentedWidget`，`currentItemChanged → show_section`（`:282-286`）。

**按需构建**（`:306-420`）：四个页面**不是**一次全建（原注释：全建 0.9s，Windows 会标"未响应"）。
每页拆成 `build_steps()` 返回的 `[(步骤名, 函数)]`，由 `QTimer.singleShot(0)` 每轮事件循环做一步；
未建好时显示 `SectionPlaceholder`（居中 `IndeterminateProgressBar` 固定宽 180 + 步骤文字 `step_progress`="…（第 n/total 步）"）。
某步抛异常 → 占位页变错误页（`section_failed` = "「{title}」没能准备出来"），**不推半成品页面**。
网页端不需要复刻这套"分帧构建"，但**必须复刻「四页都读同一个资源库文件」与切换时刷新条数**的语义。

### 1.2 投稿表单 FormPage（`resource_maker_pages.py:418-1965`）

#### 1.2.1 布局骨架

```
scroll(QScrollArea, 无边框/横不滚/主题化滚动条)          :459-460
└─ content QWidget
   body QGridLayout: margins(0,10,0,18), hSpacing 24, vSpacing 16   :467-471
   ├─ (0,0) _left   QWidget  VBox spacing 16, AlignTop, columnStretch=1
   └─ (0,1) right_host QWidget VBox spacing 16, AlignTop, columnStretch=0
```

两列规则（`:998-1016`）：

* `viewport_w >= 820` → 两列（右列在 (0,1)）；否则右列挪到表单**下面** (1,0)。
* 两个守卫：`_build_done` 为假不算；`viewport_w < 280` 不下结论。
* `resizeEvent` + 建完后 `QTimer.singleShot(0)` 与 `singleShot(120)` 各算一次。

左列四张卡片、右列两张卡片，顺序即 `build_steps()`（`:493-513`）：

| 顺序 | 卡片 | 步骤名（语言键即中文） | 列 |
| --- | --- | --- | --- |
| 1 | 基本信息 | 基本信息卡片 | 左 |
| 2 | 链接 | 链接与简介卡片 | 左 |
| 3 | 多语言字段 | 多语言字段卡片 | 左 |
| 4 | 其它链接 | 补充说明卡片 | 左 |
| 5 | 实时预览 | 实时预览卡片 | 右 |
| 6 | 产出 | 产出卡片 | 右 |

> ⚠️ 第 3 张**必须紧跟第 2 张**：它是那两个字段的其它语言版本，放远会被当成新字段组（原注释 `:503-504`）。

表单网格 `FormGrid`（`:294-331`）：

* 两列：左列标签容器 `setFixedWidth(104)`，右列控件。
* `setHorizontalSpacing(10)`、`setVerticalSpacing(12)`、`setContentsMargins(0,0,0,0)`。
* 标签行：`BodyLabel`（`setWordWrap(False)`）+ 可选 `TipIcon`（16×16）+ `addStretch(1)`，单元格内 spacing 4。
* `add_gap(height)` 用来在同一张卡片里再分小段。

#### 1.2.2 卡片①「基本信息」（step=1）——逐字段

`_build_basic_card`，`resource_maker_pages.py:785-858`

| # | 标签（语言键 / 中文） | 控件 | 占位符（语言键 / 中文） | 默认值 | 必填 | 右侧追加控件 | ⓘ 提示文案 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `name_required` = **名称 \*** | `LineEdit` | `ph_name` = 例如：LocalSend | 空 | **是** | — | 软件的名字；导入图片后图片会被自动改成这个名字 |
| 2 | `id` = **标识 id \*** | `LineEdit` | `ph_id` = 英文小写，例如 localsend | 空（随名称自动生成） | **是** | — | 资源库里的唯一标识，只允许小写字母/数字/连字符 |
| 3 | `code` = 编码 | `LineEdit` **只读**，文字用 `text_disabled` 上色 | — | `next_code()` → `TG-000001` 形态 | 否 | — | `tip_code` = 系统自动分配的唯一编码（可留空），部署清单靠它指代程序 |
| 4 | `category` = 类别 | `EditableComboBox`（可输入新值） | — | `index = 0`，即 `CATEGORIES[0]` = **工具**（当前语言的译名） | 否 | — | 决定它显示在搜索页的哪个分组下，也可以直接输入新类别；\n填好后标签会自动跟着写 |
| 5 | `platforms` = 适用系统 | 一排可多选胶囊 `PillPushButton`（容器 `ChipFlow`） | — | **全部不选中** | 否 | — | 可多选；不选就是留空。\n现在只存进 JSON，主程序搜索页也能按它筛（按钮 tooltip：`tip_none_decided` = 点一下选中／取消；留空表示还没确定） |
| 6 | `arch` = CPU 架构 | 同上 | — | **全部不选中** | 否 | — | 可多选；留空表示没填。例如 Windows 版常见 x64 / x86，\n手机端常见 arm64（tooltip：`tip_none` = 点一下选中／取消；留空表示没填） |
| 7 | `icon` = 图标 | 行内：只读 `LineEdit`(stretch=1) + `PushButton("导入图片", FIF.FOLDER)` | `no_image` = 尚未选择图片 | 空 | 否 | 导入按钮 | 可选。导入的图片会自动存到 .ToolsGCP/Icon，\n并按「名称」自动改名，不用自己整理文件名。\n支持 png / jpg / gif / ico / webp / svg，建议 256x256 以上 |
| 8 | `tags` = 标签 | 行内：`LineEdit`(stretch=1) + `PushButton("跟随类别", FIF.SYNC)` | `ph_tags` = 例如：工具, 系统, 官方 | **跟随类别**：初始 = `category_combo.currentText()` | 否 | 跟随类别按钮 | 默认跟着「类别」自动填；你自己改过之后就不再自动覆盖，\n想恢复联动就点右边的「跟随类别」。写「官方」会显示成金色标签 |

胶囊行的数值（`:755-771`）：`ChipFlow(spacing=6, row_spacing=6)`；按钮 `setFixedHeight(26)`；
`setFixedWidth(fontMetrics().horizontalAdvance(label) + 26)`；`setCheckable(True)`；`toggled → refresh_preview()`。

取值集合（**闭集，顺序即界面顺序**）：

* `CATEGORIES`：`resource_maker_core.py:26-32`，31 项：
  `工具, 游戏, 平台, 编程, 游戏引擎, 视频平台, 建筑/设计, AI, 个性化, 其他, 剪辑, 音频, 图像, 设计, 办公, 学习, 网络, 系统, 安全, 驱动, 开发工具, 数据库, 聊天, 音乐, 阅读, 下载工具, 压缩解压, 远程控制, 虚拟机, 直播, 浏览器`
* `SYSTEM_PLATFORMS` = `resource_schema.SYSTEMS`（`resource_schema.py:22`）：
  `全平台, Windows, macOS, Android, iOS, Linux, web, 其他`
* `ARCHITECTURES` = `resource_schema.ARCHITECTURES`（`resource_schema.py:27`）：
  `x64, x86, arm64, arm, Apple Silicon, 其他`

> 语言键 `platforms`/`arch`/`icon`/`tags` 的**译名**由 `language_manager.translate_term()` 提供；
> 落盘前必须用 `_canonical_term()` 还原成上表的规范值（`:70-93`，`build_entry` 里 `:1560-1563` 调用）。

联动规则（`:1414-1450`）：

1. `name` 改动 → `id = slugify(name)[:40]`（`slugify` 定义 `resource_maker_core.py:303-309`：小写、`[\s_]+→-`、非 `[a-z0-9-]` → `-`、合并连续 `-`、去首尾 `-`），并**防抖 800ms** 触发图标改名（`QTimer.setInterval(800)`，`:450-453`）。
2. `id` 改动 → 立刻 `flush_name_icon_rename()`（`:1425-1430`）。
3. `category` 改动 → 若 `_tags_auto` 为真，`tags = category`（`:1432-1439`）。
4. 用户在 `tags` 里**手打**（`textEdited`，程序 setText 不触发）→ `_tags_auto = False`，此后不再自动覆盖（`:1447-1450`）。
5. 「跟随类别」按钮 → `_tags_auto = True` 并立即把 tags 写成当前类别（`:860-864`）。

#### 1.2.3 卡片②「链接」（step=2）

`_build_content_card`，`:921-937`。语言键 `links_only`（旧键 `links_desc` 仍在语言文件里）。

| # | 标签 | 控件 | 占位符 | ⓘ 提示 |
| --- | --- | --- | --- | --- |
| 1 | `url` = 官网 | `LineEdit` | `ph_url` = https://example.com（没有可留空） | 可选。点卡片上的「官网」时跳转的地址；\n只写 example.com 也行，保存时会自动补上 https:// |
| 2 | `github` = 开源仓库 | 行内：平台 `ComboBox`(固定 110) + 前缀 `BodyLabel` + `LineEdit`(stretch=1) | 见下 | 选好平台后会自动补上前缀；卡片右下角会出现仓库按钮 |
| 3 | （无标签） | `repo_preview_label` `CaptionLabel`，`align=AlignLeft` | — | 显示 `"→ {完整地址}"`，空则空串（`:916-919`） |

仓库平台（`resource_maker_core.py:41-48`，顺序即下拉顺序）：

```python
REPO_PLATFORMS = [
    ("github",  "GitHub",  "https://github.com/"),
    ("gitcode", "GitCode", "https://gitcode.com/"),
    ("gitee",   "Gitee",   "https://gitee.com/"),
    ("gitlab",  "GitLab",  "https://gitlab.com/"),
    ("custom",  "自定义",  ""),
    ("none",    "不开源",  ""),
]
```

* 默认 `setCurrentIndex(0)` = **GitHub**。
* 平台切换（`:896-914`）：
  * `none` → 前缀标签隐藏、输入框只读、占位符 `已选择「不开源」`；
  * `custom` → 前缀标签隐藏、可编辑、占位符 `https://你的仓库地址`；
  * 其它 → 前缀标签显示为该平台前缀、可编辑、占位符固定 `owner/repo`。
* 地址归一 `normalize_repo_url()`（`resource_maker_core.py:133-157`）：去 `http(s)://`、去 `www.`、去该平台域名、去前导 `/`，再拼前缀；`none` 或空 → `""`；`custom` 原样。
* 反推平台 `detect_repo_platform()`（`:160-168`）：空 → `none`；命中前缀 → 该 key；否则 `custom`。

#### 1.2.4 卡片③「多语言字段」（step=3）

`_build_i18n_card`，`:547-644`。**默认开启**（`i18n_switch.setChecked(True)`，`:562`）。

结构：

```text
卡片标题：lang_fields_default_on（多语言字段（三种语言一起提交））
head HBox: spacing 6
  ├─ BodyLabel(lang_fields_hint = 按语言分别填写名称与简介)
  ├─ TipIcon(lang_fields_tip)
  ├─ addStretch(1)
  └─ SwitchButton  ← 默认开；checkedChanged → i18n_body.setVisible(checked)
i18n_body VBox: margins 0, spacing 10
  ├─ SegmentedWidget：分段按钮 i18n0/i18n1/i18n2
  │    显示文本 = t("zh_cn") / t("zh_tw") / 字面量 "English"
  └─ QStackedWidget：每语言一页，每页一个 FormGrid(标签宽 104)
```

⚠️ **两个必须照抄的细节**：

1. 语言字典的键是**固定规范名** `("简体中文", "繁體中文", "English")`（`:572`），**不是**译文。
   英文界面下 `t("zh_cn")` 会变成 "Simplified Chinese"，写进 JSON 就成了读不出来的键（原注释 `:589-590`）。
2. 多语言字段必须在 `resource_schema.normalize()` **之后**合并（`build_entry`，`:1578-1582`），
   否则 `normalize` 会把 i18n 按当前语言压成一句话。

每语言页的 4 个字段（`:624-627`）：

| 标签 | 控件 | 占位符 | 高 |
| --- | --- | --- | --- |
| `name_required` = 名称 * | `LineEdit` | `ph_name_l10n` = 留空即同上 | 默认 |
| `description` = 简介 | `LineEdit` | `ph_desc_main` = 一句话说明它是什么、能干什么（可留空） | 默认 |
| `intro` = 应用介绍 | `PlainTextEdit` | `ph_intro_main` = 详情页「应用介绍」里显示的正文（没有可留空）：… | `setFixedHeight(84)` |
| `supplement` = 补充 | `PlainTextEdit` | `ph_supplement_main` = 补充说明（没有可留空）：使用场景、注意事项、系统要求…… | `setFixedHeight(84)` |

⚠️ 多语言页里的**名称只是可选翻译**：`apply_i18n_to_entry` 对 `name` 字段 `pass`（不写），
名称一律以卡片①为准（`:711-714`）。

合并规则 `apply_i18n_to_entry`（`:707-726`）：

* 开关关 → 原样返回。
* 收集四字段三种语言里的非空文本；
* 全空 → 跳过该字段；
* **所有值完全相同（去重后只剩 1 个）→ 不写字典**（保持 `build_entry` 里已有的纯字符串）。

回填 `load_i18n_from_entry`（`:728-743`）：`any(field 是 dict)` 决定开关状态；
某语言无值且该字段是纯字符串时，把它填进**简中**那一格；回填后切回"当前界面语言"那一页。

#### 1.2.5 卡片④「其它链接」（无序号徽标）

`_build_extra_card`，`:939-951`。语言键 `other_links` = 其它链接（可留空）。

| 标签 | 控件 | 占位符 |
| --- | --- | --- |
| `author_page` = 作者主页 | `LineEdit` | `ph_author_page` = 作者主页（没有可留空） |
| `chat_url` = 聊天地址 | `LineEdit` | `ph_chat` = 聊天/交流地址（没有可留空） |

两个字段落盘都过 `auto_http_url()`（`resource_maker_core.py:335-340`：没有 scheme 就补 `https://`）。

#### 1.2.6 右列卡片⑤「实时预览」

`_build_preview_card`，`:953-962`。卡片 `setFixedWidth(280)`；标题 `preview` = 实时预览。

`PreviewCard`（`:357-414`）：

* `setFixedWidth(240)`（= 280 − 20×2），`setMinimumHeight(190)`。
* 内容 `margins(16,16,16,16)`、`spacing 8`。
* 上半 `HBox(spacing=12)`：图标 `QLabel` `setFixedSize(72,72)` + 右侧 VBox(spacing 6)：名称 `StrongBodyLabel`、简介 `CaptionLabel(setWordWrap)`。
* 一条 1px 分隔线。
* 下方标签行 `CaptionLabel(setWordWrap)`。

内容规则（`update_preview`，`:396-414`）：

| 项 | 规则 |
| --- | --- |
| 名称 | `entry["name"]`，空则显示 `preview_name` = （名称） |
| 简介 | `entry["description"]`，空则 `preview_desc` = （简介）；**超过 60 字截断并加 `...`**（`:399`） |
| 标签 | `"  ".join(f"[{t}]" for t in tags)`；无标签显示 `（无标签）`（`:402`） |
| 图标 | 有文件且**不是 .gif** → 按 `KeepAspectRatio` 缩到 72×72；否则显示 `"?"`，底色 `rgba(128,128,128,60)`、圆角 8、字色 gray（`:404-414`） |

⚠️ 预览卡**不显示** `intro` / `supplement` / `systems` / `architectures` / `url` / `github`。
卡片下方还有一行 `status_label`（`CaptionLabel(setWordWrap)`），见 1.2.8。

#### 1.2.7 右列卡片⑥「产出」——按钮、行为链、文件名规则

`_build_action_card`，`:964-995`。卡片 `setFixedWidth(280)`，标题 `output` = 产出。
卡片内从上到下（每行一个控件，无额外间距离散值，沿用卡片 `spacing 12`）：

| 顺序 | 文本（语言键 / 中文） | 类型 | 图标 | 点击行为 |
| --- | --- | --- | --- | --- |
| 0 | `then_do_one` = 填好必填项后，下面任选一项产出即可（不必全做）。 | `CaptionLabel(setWordWrap)`，次要色 | — | — |
| 1 | `load_existing` = 载入现有资源来编辑 | `PushButton` | `FIF.DOWNLOAD` | `load_existing` |
| 2 | `gen_draft` = 生成稿件（发给作者） | `PrimaryPushButton` | `FIF.SHARE` | `export_draft` |
| 3 | `append_local` = 追加到本机资源库 | `PrimaryPushButton` | `FIF.ADD` | `append_to_library(confirm=True)` |
| 4 | `save_as_new` = 另存为独立资源库 | `PushButton` | `FIF.SAVE_AS` | `save_standalone` |
| 5 | `clear_form` = 清空表单 | `PushButton` | `FIF.DELETE` | `clear_form` |
| 6 | `library_label` | `CaptionLabel(setWordWrap)` | — | 显示资源库信息；完整路径在 tooltip |

`library_label` 文案（`reload_library_info`，`:1391-1411`）：

* 存在 → `library_path_hint` = `资源库：{path}\n当前共 {n} 条`，其中 **`path` 只放文件名**（`os.path.basename`），
  完整路径挂 tooltip —— 卡片内宽只有 240px，放整条路径会折成四五行的（原注释 `:1398-1399`）。
* 不存在 → `library_not_found_hint` = `未找到本机资源库，\n「追加到本机资源库」会新建一份。`

---

##### 行为链 A：`export_draft` 生成稿件（`:1675-1746`）

1. `validate()` 有错 → InfoBar 错误，标题 `请先处理这些问题`，内容 `errors_fix_first` = `还有问题需要先修好：\n· {list}`；**中止**。
2. `flush_name_icon_rename()`：把待处理的图标改名落实，保证 JSON 里的文件名与磁盘一致。
3. 弹目录选择：`QFileDialog.getExistingDirectory`，标题 `选择稿件输出目录`，默认目录 `<项目根>/ResourceDrafts`；取消 → 中止。
4. `entry = build_entry()`。
5. `draft_dir = <选择目录>/<entry["id"]>`；图标目录 `<draft_dir>/Icon`。
6. 有图标 → `copy_icon(src, <draft_dir>/Icon, entry["name"] or entry["id"])`，把返回的文件名写回 `entry["icon"]`；无图标 → `entry.pop("icon")`。
7. 写 `resource.json`：
   ```json
   {
     "schema_version": "2.1.0",
     "metadata": {
       "name": "ToolsGCP Draft - {name}",
       "description": "单条资源稿件，可直接提交给 ToolsGCP 作者",
       "icon_dir": "Icon",
       "updated_at": "<now isoformat(seconds)>"
     },
     "resources": [ entry ]
   }
   ```
8. 写说明文件 `<draft_dir>/<localized 说明.txt>`：
   * 文件名**随语言变**：简中 `说明.txt` / 繁中 `說明.txt` / English `README.txt`（`maker_language.json`）。
   * 内容 = `draft_readme_head` + `\n\n` + `draft_readme_json` + `\n` + 图标行 + `\n` + `draft_readme_howto` + `\n`；
     图标行有图 = `draft_readme_icon_line`（`Icon/{name} —— 图片（已按名称命名）`），无图 = `draft_readme_no_icon`。
9. 打包 zip：`<选择目录>/<id>.zip`，`ZIP_DEFLATED`，arcname = 相对 `draft_dir` 的路径。
   成功 → 追加 `zip_packed` = `\n已打包：{path}`；失败 → 追加 `zip_pack_failed`。
10. InfoBar 成功：标题 `稿件已生成`，内容 `"{draft_dir}{zip_msg}"`，`duration=6000`。

##### 行为链 B：`append_to_library(confirm=True)` 追加到资源库（`:1748-1836`）

1. `_sync_editing_state()`：若名称/id 已与"载入的那条"不同 → 视为新条目（重新分配编码、忘掉上一条的图标）。
2. `validate()` 有错 → 中止（同上提示）。
3. `flush_name_icon_rename()`。
4. 读 `path = <项目根>/.ToolsGCP/ToolsGCP-Resources.json`。
5. 若图片还在原位置（`_icon_is_src`）→ 先 `store_icon()` 复制进图标目录；失败则报
   `图片没能存进图标目录，已中止写入（资源库没有被改动）` 并**中止**。
6. `build_entry()`；无 `icon` → `entry.pop("icon")`。
7. 若库里已有同 `id` 且 `confirm=True` → 确认框：
   * 标题 `覆盖已有资源`
   * 内容 `confirm_overwrite_entry` = `资源库里已经有 id 为「{id}」的条目（{name}），要用现在的表单内容覆盖它吗？\n\n资源库文件：{path}`
   * 按钮：`覆盖` / `取消`
8. 覆盖时：保留原 `listed_at`（编辑旧条目不算重新上架）；新条目 `listed_at = now_listed_at()`（`%Y-%m-%d %H:%M:%S`）。
9. 更新 `metadata.updated_at` 与 `metadata.total_count`。
10. 文件存在 → 先 `backup_library()`；**备份失败就中止**（`backup_failed_abort`）。
    * 备份位置：同目录 `backups/`，文件名 `ToolsGCP-Resources.backup-{YYYYmmdd-HHMMSS}.json`，同秒冲突加 `-2/-3`；**只保留最近 20 份**（`resource_maker_core.py:191-229`）。
11. `write_json()`（原子写：先写 `.tmp` → `fsync` → `os.replace`，`indent=2`、`ensure_ascii=False`、末尾换行；`resource_maker_core.py:232-246`）。
12. 覆盖且旧图标文件名变了、且没被别的条目引用 → 删掉旧图标文件。
13. 表单进入"代表库里这一条"状态（`_loaded_id` / `_loaded_name` / `_is_new_entry=False` / `_listed_at`），刷新页头与浏览页。
14. InfoBar 成功：标题 `已写入资源库`，内容 `written_to_library` = `{name}（{code}）→ {n} 条`，`duration=4000`。

##### 行为链 C：`save_standalone` 另存为独立资源库（`:1838-1880`）

1. `validate()` → `flush_name_icon_rename()`。
2. `QFileDialog.getSaveFileName`，默认路径 `<项目根>/ToolsGCP-Resources.json`，过滤 `JSON 文件 (*.json)`。
3. `icon_dir = <所选文件所在目录>/Icon`；有图标则 `copy_icon()` 并把文件名写回 `entry["icon"]`。
4. 写：
   ```json
   {
     "schema_version": "2.1.0",
     "metadata": {
       "name": "ToolsGCP Resources",
       "description": "ToolsGCP 资源索引文件",
       "icon_dir": "<Icon 相对该文件的路径，用 / 分隔>",
       "updated_at": "<now>"
     },
     "resources": [ entry ]
   }
   ```
5. InfoBar 成功：标题 `已生成独立资源库`，内容 = 完整路径，`duration=5000`。

##### ⚠️ 两套图标命名规则**不一样**（极易漏）

| 流程 | 函数 | 命名规则 |
| --- | --- | --- |
| 导入进本机图标目录（卡片①/浏览页） | `copy_into_icon_dir`（`:1233-1298`） | `icon_base_from_name(名称, id) + 原扩展名`。只去掉 Windows 非法字符 `\/:*?"<>|` 与控制字符，**保留中文**；为空才退回 id。 |
| 稿件 / 独立库 | `copy_icon`（`resource_maker_core.py:364-391`） | `re.sub(r"[^A-Za-z0-9_\-]+", "", preferred_name)` → **中文会被清空**，为空退回收源文件原名（stem）；再冲突加 `-{HHMMSS}` 时间戳。 |

`copy_into_icon_dir` 的完整顺序（网页端必须照抄，否则会覆盖别人的图）：

1. 目标目录建不出来 → 报 `icon_dir_create_failed` = `图标目录建不了：{err}`，返回空。
2. `want = preferred_icon_name(src)`；`dest = <图标目录>/<want>`。
3. `src` 与 `dest` 是同一文件 → 不复制，直接返回。
4. `dest` 已存在且**内容相同**（先比大小再比字节）→ 复用，不复制。
5. `dest` 已存在且这个文件名**不是"我这条"在用** → `unique_name_in()` → `名称-2.png` / `名称-3.png`（`:354-361`）。
6. `shutil.copyfile`，**失败重试 2 次、每次间隔 0.1s**；成功后校验 `getsize(dest) == getsize(src)`。最终失败 → 报 `图片复制失败：{err}` 或 `图片没能复制进图标目录，请再试一次。`
7. 旧文件若已不被引用 → `_recycle_icon()` 删掉。

##### 图标"跟着名称改名"（`:1319-1374`）

* 触发：`name` 变化后 800ms 防抖。
* 前置条件（缺一不可）：`_ensure_new_entry_for_icon()` 为真（**已发布的条目不后台改名**）、
  `_icon_picked` 为真（这份图是用户刚为本条导入的）、文件存在、文件名没有被**别的**条目引用、
  文件所在目录 == 资源库图标目录。
* 动作：`os.replace(old, new)`，**重试 2 次**；冲突则 `unique_name_in()`；成功后回到步骤刷新状态并按需回收旧文件。
* 产出前统一调 `flush_name_icon_rename()`（停掉定时器 + 立即执行 + 刷新）。

##### 导入图片 UI 反馈（`:1477-1503`）

* 起始目录：有当前图标 → 它的目录；否则图标目录；再否则 `~`。
* 过滤串 `image_filter()`（`resource_maker_core.py:52-77`）：按语言取 `maker.image_filter`，
  兜底 `Image files (*.png *.jpg *.jpeg *.gif *.ico *.bmp *.webp *.svg);;All files (*.*)`。
* 取消 → 什么都不做；文件不存在 → 报 `这个图片文件不存在`。
* 成功 → InfoBar 成功：标题 `图片已导入`，内容 `image_saved_as` = `已存为 {name}（{path}）`
  / `Saved as {name} ({path})`，`duration=2500`。
  `{path}` 的取值：图片不在图标目录（`_icon_is_src`）时传 `原位置`，否则传图标文件所在目录。

##### `clear_form`（`:1505-1543`）

确认框：标题 `clear_form` = 清空表单，内容 `确定要清空当前填写的所有内容吗？`，按钮 `清空` / `取消`。
确认后清空：名称、id、tags（并重置 `_tags_auto=True` 且重新跟随类别）、官网、仓库（平台回 index 0）、
**三种语言的所有 desc/intro/supplement**、系统/架构胶囊、作者主页、聊天地址、
`_loaded_id`/`_loaded_name`/`_is_new_entry=True`/`_listed_at`、图标选择（`icon_source=""`、`icon_edit.clear()`）。
⚠️ **不删除磁盘上的图标文件**（可能被别的条目引用着，原注释 `:1538`）。

##### `load_existing` / `load_resource`（`:1882-1959`）

* 库为空 → 报 `本机资源库是空的，没有可载入的条目。`
* 选项文本格式：`f"{code}  {name}  ({id})"`（两个空格分隔）。
* 选择框走 `ask_choice()`（`ui/fluent_dialogs.py`）—— 原注释：不能用原生 `QInputDialog.getItem`，深色下看不见（`:1890-1892`）。
* 标题 `载入现有资源`，提示 `选择要编辑的资源：`。
* 载入后 InfoBar info：标题 `已载入`，内容 `{name}（{code}）`。
* `load_resource` 期间 `_loading=True`（不触发改名定时器）；类别列表用 `", "` 拼回输入框（往返无损）；`_tags_auto=False`。

#### 1.2.8 校验规则（逐条，含文案）

`validate()`（`:1589-1619`）——**只有两种是真错（拦截产出）**：

| # | 条件 | 文案 |
| --- | --- | --- |
| 1 | `name` 为空 | `「名称」必填` |
| 2 | `id` 为空 | `「标识 id」必填` |
| 3 | `id` 不匹配 `^[a-z0-9\-]+$` | `「标识 id」只能包含小写字母、数字和连字符` |
| 4 | `icon_source` 非空但文件不存在 | `图标文件不存在（重新导入一次图片）` |
| 5 | 库里已有同 `id` 且不是"正在编辑的那条" | `err_id_taken` = `标识 id「{id}」已被占用（{name}）` |
| 6 | 库里已有同 `code` 且不是"正在编辑的那条" | `err_code_taken` = `编码「{code}」已被占用（{name}）` |

`validate_warnings()`（`:1621-1646`）——**只提示，不拦截**：

| 条件 | 文案 |
| --- | --- |
| 没有图标 | `还没导入图片，卡片上会显示成默认图标` |
| `url` 空 | `「官网」留空了，卡片上会没有「官网」按钮` |
| `url` 非空但无 scheme | `「官网」没写 http://，已按 https:// 处理` |
| `description` 空 | `「简介」留空了，卡片上只有名称` |
| `category` 空 | `「类别」留空了，这条不会出现在类别分组里` |
| 作者主页/聊天地址无 scheme | `warn_no_http_scheme` = `「{label}」没写 http://，已按 https:// 处理` |
| 平台不是 `none/custom` 且仓库地址解析为空 | `「开源仓库」留空了，卡片上会没有仓库按钮` |

状态行 `status_label` 的三种呈现（`refresh_preview`，`:1651-1672`）：

1. 有错误 → `"· " + "\n· ".join(errors[:4])`，色 `danger`（**只显示前 4 条**）。
2. 无错误有警告 → `status_all_ok_with_warns` = `必填项都填好了，可以生成/追加。\n（另外：\n· {list}）`，色 `warning`（警告也只取前 4 条）。
3. 全干净 → `信息完整，可以生成/追加了。`，色 `success`。

#### 1.2.9 `build_entry()` 落盘字段（`:1553-1582`）

```python
entry = {
    "id": id_edit.strip(),
    "code": code_edit.strip(),
    "name": name_edit.strip(),
    "category": [_canonical_term(c) for c in split_categories(category_combo.currentText())],  # list
    "tags":     [_canonical_term(t) for t in split_tags(tags_edit.text())],                    # list
    "icon": current_icon_name(),          # 磁盘上真实存在的文件名，没有则 ""
    "url": auto_http_url(url_edit),
    "github": normalize_repo_url(平台, github_edit),
    "download_url": self._loaded_download_url,   # ⚠️ 表单已无此字段，只原样保留旧条目里的值
    "chat_url": auto_http_url(chat_edit),
    "author_url": auto_http_url(author_url_edit),
    "description": desc_edit  (换行压成空格),
    "intro": intro_edit      (换行压成空格),
    "supplement": supplement_edit (换行压成空格),
    "listed_at": now_listed_at() if is_new_entry() else self._listed_at,
    "systems": [勾选的系统],
    "architectures": [勾选的架构],
}
normalized = resource_schema.normalize(entry)     # 字段顺序/空值过滤/tags 去重
return self.apply_i18n_to_entry(normalized)       # 多语言必须最后合并
```

`resource_schema.normalize()`（`resource_schema.py:362-396`）的关键语义：

* 落盘字段顺序 = `FIELD_ORDER`（`id, code, name, category, tags, icon, url, github, download_url, chat_url, author_url, description, intro, supplement, listed_at, systems, architectures, variants, default_variant`）。
* 未知字段**原样保留**；`category` 一律 list；`tags` 去掉与 `category` 重复的值；空的可选字段不写，必填字段恒在。
* 分隔符 `CATEGORY_SPLIT_CHARS = (",", "，", "、", ";", "；")`；**不拆 `/`、不拆空格**（`resource_schema.py:18`）。

**必填字段的最终裁决权在 schema**：`REQUIRED_FIELDS = ("id", "code", "name")`（`resource_schema.py:144`）。
表单里的 `code` 只读且由 `next_code()` 自动分配（`TG-` + 6 位数字，从现有最大值 +1，`resource_maker_core.py:271-286`）。

#### 1.2.10 ⚠️ 原版**没有**的东西（不许凭空补）

* **没有「预览 JSON」文本框**。全库 grep `preview_json` / `json_preview` / `预览 JSON` 均无命中（`maker_language.json` 里也没有这两个 key）。原版的"预览"= 1.2.6 的卡片式实时预览。
* 没有 `variants` / `default_variant` 的编辑控件（这两个字段 schema 里有，但表单不提供；网页端若已有输入框，那是网页端自己加的）。
* 没有表单级"下载直链"输入框（`download_url` 只能通过载入旧条目带进来）。
* 没有"名称/简介"之外的字段做三语（`systems`/`architectures` 等仍走术语译名，不写字典）。

### 1.3 资源浏览 BrowserPage（`resource_maker_pages.py:1978-2781`）

#### 1.3.1 骨架

```
layout VBox: margins(0,10,0,18), spacing 12                 :2052-2054
├─ toolbar HBox spacing 8                                    :2058-2059
│  ├─ search_edit LineEdit  固定宽 240
│  │    占位符 search_library = 按编码 / 名称 / 标签 / id 搜索
│  ├─ category_combo ComboBox 固定宽 140
│  │    第 0 项 all_categories = 全部类别 (userData="")
│  │    之后 = CATEGORIES 的译名，userData = 规范中文
│  ├─ reload_btn PushButton("重新载入", FIF.SYNC)
│  ├─ open_btn  PushButton("打开资源库文件", FIF.FOLDER)
│  ├─ addStretch() → addSpacing(12)
│  ├─ edit_btn   PushButton(load_into_form = 载入到制作资源, FIF.EDIT)
│  └─ delete_btn PushButton(delete_selected = 删除选中条目, FIF.DELETE)
├─ table EditableTableWidget（stretch=1）
└─ footer HBox spacing 12
   ├─ hint_label CaptionLabel(setWordWrap, 次要色)  —— 长说明见下
   └─ count_label CaptionLabel（右对齐，只在筛选时才有字）
```

`hint_label` 原文（`:2126-2128`）：
`双击单元格直接修改内容，改完自动保存（写入前会自动备份到 backups/）；双击「图标」列的格子可以重新挑一张图片（自动存进图标目录并改成应用名）；\n「上架时间」是新资源入库的时间；想大改就选中一行点「载入到制作资源」。`

#### 1.3.2 表格列规格（11 列，顺序即数组）

`:1982-2035`

| 列号 | 表头兜底中文 | 字段 | 语言键 | 理想宽 | 最小宽 | 内容规则 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 图标 | `icon` | `icon` | 56 | 52 | **不显示文字**，显示 24×24 缩略图（`ICON_THUMB_SIZE = 24`）；真实文件名放 `Qt.UserRole+1` 与 tooltip（tooltip 兜底 `双击这里可以换一张图片`） |
| 1 | 编码 | `code` | `code` | 120 | 110 | 纯文本 |
| 2 | 名称 | `name` | `name` | 170 | 118 | 纯文本（宽裕时**吃掉全部剩余宽度**） |
| 3 | 类别 | `category` | `category` | 88 | 64 | list → `", ".join` |
| 4 | 标签 | `tags` | `tags` | 130 | 74 | list → `", ".join` |
| 5 | 官网 | `url` | `url` | 160 | 78 | 挂整串 tooltip |
| 6 | 开源仓库 | `github` | `github` | 170 | 78 | 挂 tooltip |
| 7 | 简介 | `description` | `description` | 200 | 88 | 挂 tooltip |
| 8 | 应用介绍 | `intro` | `intro` | 200 | 80 | 挂 tooltip |
| 9 | 补充 | `supplement` | `supplement` | 170 | 78 | 挂 tooltip |
| 10 | 上架时间 | `listed_at` | `column_listed_at` | 130 | 86 | 纯文本 |

* 理想宽度合计 **1594px**，最小宽度合计 **906px**（原注释要求 min 之和 < 常规窗口视口，否则会横向滚动）。
* 对齐：原版**没有任何 `setTextAlignment` 调用**（全文件 grep 只命中徽标与图标标签），
  即沿用 `QTableWidgetItem` 默认（Windows 风格下**左对齐 + 垂直居中**）；网页端照此实现即可。
* 表格设置：`Interactive` 列宽、`setStretchLastSection(False)`、`SelectRows`、`NoEditTriggers`、
  `setWordWrap(False)`、`verticalHeader().setDefaultSectionSize(34)`、`setIconSize(24×24)`、
  `header().setMinimumSectionSize(48)`。
* 「图标」列双击才进编辑（`EditableTableWidget.edit`，`:1969-1975`）。

#### 1.3.3 列宽自适应算法（`_fit_columns`，`:2189-2222`）

```text
available = table.viewport().width()
total_ideal = 1594, total_min = 906
if available >= total_ideal:   widths = ideal;  widths[2] += available - total_ideal
elif available <= total_min:   widths = min              # 此时才允许横向滚动
else:                          # 中间态：按"每列可压缩量"等比缩
    slack = total_ideal - available; room = total_ideal - total_min
    widths = [w - round((w-m) * slack / room) for w, m in zip(ideal, min)]
    widths[2] += available - sum(widths)                 # 抹平四舍五入误差
每列 max(40, int(width))
```

* 用户手动拖过列宽 → `_user_resized_columns = True`，**之后不再自动改**（`:2149-2153`）。
* 初始化列宽必须包在 `_applying_widths` 里，否则一开始就被判成"用户拖过"（原注释 `:2111-2112`）。

#### 1.3.4 筛选与填表

* 筛选（`apply_filter`，`:2274-2289`）：
  * 类别：`category in resource_schema.categories_of(r)`（多类别任一命中即算）。
  * 关键词：`code` / `name` / `id` 的不区分大小写子串，**或** 命中 `keywords_of(r)`（= 类别 ∪ 标签）。
* 分帧填表：`FILL_CHUNK = 120` 行一批（约 4ms），中间回事件循环；`_fill_token` 作废旧批次。
* 脚注 `count_label` 文案：
  * 只在**筛选时**显示 `browser_shown` = `筛选中 · 显示 {n} / 共 {total} 条`（不筛选时不显示，页头已有"资源库 N 条"）。
  * 填表中显示 `browser_busy_filling` = `{count}，正在填表 {n}/{total}…`。

#### 1.3.5 就地编辑（双击单元格）

* 双击「图标」列 → 弹选图框（标题 `pick_icon_dialog_title` = `给「{name}」挑一张图片`），选完自动复制进图标目录并改名为应用名，写盘成功后 InfoBar 成功
  `图片已换好` / `icon_replaced_backup` = `{name} → {file}（已自动备份资源库）`。
* 双击其它列 → 原地变输入框；`itemChanged` 落盘。
* 名称列不允许清空 → `_revert_cell` + InfoBar warning 标题 `这一格没有改`，内容 `「名称」不能留空`。
* 单元格清空 = 从 JSON 里删掉这个字段（`_write_field`，`:2490-2492`）。
* 改 `category` / `tags` 后**必须重新保证 tags 不含 category**（`:2496-2502`）。
* 多语言字段只覆盖"表格里显示的那一种语言"对应的键（`_merge_i18n_cell`，`:2459-2467`；
  挑选顺序 `简体中文 → 繁體中文 → English`，都没有就写简中）。
* 写盘成功 InfoBar 成功：标题 `已修改`，内容 `cell_changed_backup` = `{column}：{value}（已自动备份资源库）`，value 超 20 字截断加 `…`。
* 备份失败 / 写盘失败：标题 `备份失败，已中止写入` / `写入失败`。

#### 1.3.6 右键菜单（`:2678-2691`）

先 `selectRow(item.row())`，然后 `RoundMenu` 两项，顺序固定：

1. `load_into_form` = 载入到制作资源
2. `换一张图片（改图标）`

#### 1.3.7 其它

* 「载入到制作资源」未选中 → InfoBar warning 标题 `没有选中任何条目`，内容 `先在表格里点一行，再点「载入到制作资源」`；成功后 `load_resource()` + **切到投稿表单分节**（`switch_to_page`）。
* 「删除选中条目」未选中 → 正文改为 `先在表格里选一行`；确认框标题 `删除条目`，内容 `confirm_delete_entries` = `确定要从资源库删除这些条目吗？\n{names}`，按钮 `删除` / `取消`；成功后顺带删除不再被引用的图标文件，InfoBar 成功 `已删除` / `entries_backed_up` = `{n} 条（已自动备份资源库）`。
* 「打开资源库文件」= `os.startfile(所在目录)`；失败 InfoBar 错误标题 `打不开`。

### 1.4 批量合成 BatchPage（`:2788-3272`）

两个模式常量（`:2791-2792`）：`MODE_APPEND = "append"`（默认）、`MODE_MERGE = "merge"`。

四张卡片，顺序即 `build_steps()`（`:2818-2829`）：

| # | 标题（语言键 = 中文） | 说明 | 内容 |
| --- | --- | --- | --- |
| ① | `① 选择合成模式` | `追加模式：把投稿的条目合进本机资源库，已经有的编码会自动跳过。\n新建模式：把多个投稿文件合并成一个新的 JSON，原来的文件不动。` | 两行设置（见下） |
| ② | `② 选择要合成的 JSON 文件` | `batch_files_hint` = 可以一次选多个；文件里是列表或 {"resources": [...]} 都能识别。 | 按钮行 + 列表 |
| ③ | `③ 输出位置` | — | 追加模式行 / 新建模式行 + 模式提示 |
| ④ | `④ 检查并执行` | — | 预览文字 + 两个按钮 |

设置行数值：左标题（+ 可选 TipIcon），`addStretch(1)`，右侧控件 `setFixedWidth(200)`，行内 spacing 12（`:2850-2864`）。

①的两行：

| 标签 | 控件 | 选项（显示文本 → userData） | tip |
| --- | --- | --- | --- |
| `合成模式` | `ComboBox`，最小宽 = 最宽项像素宽 + 76（兜底 240） | `追加到本机资源库（默认）` → `append`；`多个 JSON 合并成新文件` → `merge` | — |
| `重复条目` | `ComboBox` | `跳过重复（推荐）` → `skip`；`重复的覆盖旧条目` → `overwrite`；`全部保留（重新分配编码）` → `keep` | 判断重复的依据：编码相同，或者标识 id 相同 |

②的按钮行（spacing 8）：`添加文件`(FIF.ADD)、`移除选中`(FIF.DELETE)、`清空列表`(FIF.CANCEL)、`addStretch()`、右侧 `files_count`
（`files_selected` = `已选 {n} 个文件`）；下面是 `ListWidget`，`setMinimumHeight(150)`，`ExtendedSelection`。

③的两行（按模式互斥显示）：

* 追加：左 `目标资源库` + `addStretch()` + 右侧 `library_label`（路径，`elide_path(limit=72)` 中间省略，tooltip 放完整路径）。
* 新建：左 `保存到` + `LineEdit`(stretch=1，占位符 `选择新 JSON 的保存位置`) + `PushButton("选择…", FIF.SAVE_AS)`。
  `choose_output` 默认文件名 **`ToolsGCP-Resources-merged.json`**，对话框标题 `保存合并结果`，过滤 `JSON 文件 (*.json)`，没写后缀自动补 `.json`。
* 模式提示 `mode_tip`（`:3032-3035`）：
  * append → `会把合进来的条目直接写进本机资源库，写入前会自动备份一份。`
  * merge → `只生成一个新文件，本机资源库不受影响，之后可以再导进来。`

④：`preview_label`（默认 `点「预览结果」看看会合并进来多少条。`）+ 行内 `预览结果`(FIF.VIEW，左) + `addStretch()` + `开始合成`(PrimaryPushButton, FIF.ACCEPT，右)。

读取源文件 `read_sources`（`:3071-3093`）：`utf-8-sig` 打开；dict 取 `resources` 或 `items`，list 直接用；只保留 dict 项；返回 `(全部条目, [(文件, 条数)], [(文件, 错误)])`。

重复判定 `entry_key = (code, id, name)`，但 `merge_entries` 里**逐条按 编码→id→名称 三级匹配**（`:3111-3122`）：

* `skip`：跳过（`skipped`）。
* `overwrite`：替换原位置（`overwritten`）。
* `keep`：两条都留，重复那条重新分配 `code` 与 `id`（`id-2`、`id-3`…），计 `recoded`。
* 无重复且没有 code → 分配 `next_code()`。

预览文本（`preview`，`:3159-3188`）逐行：

```text
merge_src_summary  源文件 {files} 个，共 {n} 条：
merge_src_item         {name} — {n} 条            （最多显示 8 个文件）
merge_more_files       …还有 {n} 个文件            （超过 8 个才有）
merge_result       结果：新增 {added} 条，跳过重复 {skipped} 条，覆盖 {overwritten} 条，重新编号 {recoded} 条
merge_count_change 资源库将从 {before} 条变成 {after} 条
⚠️ 读不了的文件：a.json, b.json                     （有失败文件才有）
```

执行 `run`（`:3190-3261`）：

* 追加模式：确认框标题 `确认合成`，内容 `confirm_merge_write` = `将把 {n} 条新条目写入本机资源库：\n{path}\n\n（写入前会自动备份一份）`，按钮 `开始合成` / `取消`；
  写盘前对每条跑 `resource_schema.normalize()`，补 `updated_at`、`total_count`、缺 `listed_at` 的补 `now_listed_at()`；
  备份失败中止；成功 InfoBar `完成` / `merged_ok` = `已合并 {n} 条到资源库（已自动备份到 backups/）`。
* 新建模式：没填输出路径 → InfoBar 错误标题 `出错了`，内容 `先选一个保存位置`；
  写出 `{schema_version(取原库,默认"2.0.0"), metadata:{icon_dir, updated_at, total_count}, resources}`；
  成功 InfoBar `完成` / `generated_ok` = `已生成 {path}（{n} 条）`。
* 未选文件 → InfoBar warning 标题 `还没选文件`，内容 `先添加要合成的 JSON`。

### 1.5 使用说明 HelpPage（`:3276-3373`）

* 正文 = 语言键 `help_text`（中文长文兜底见 `:120-176`），按 `【小节】` 或 `[小节]` 切块（`split_help_blocks`，`:3276-3309`）。
* 丢掉开头那段"整篇文档标题"（无标题且正文只有一行）；每块一张卡片，正文 `BodyLabel(setWordWrap)`，`setMaximumWidth(900)`，文字可选中。
* 底部 `addStretch(1)`；卡片间距 16。

### 1.6 本页涉及的语言 key 全清单

来源：`.ToolsGCP/modules/languages/maker_language.json`（256 条），段名 **`maker`**
（`get_text` 里同时尝试 `maker` 与 `resource_maker`，见 `resource_maker_interface.py:541`）。

按功能分组（值为简中原文）：

* **页头 / 分节**：`title`、`subtitle`、`library_tip`、`section_form`、`section_browser`、`section_batch`、`section_help`、`library_count`、`library_missing`、`library_tooltip`。
* **构建态**：`section_preparing`、`section_failed`、`step_progress`、`step_title_wrap`、`build_step_failed`、`build_failed`、`finish_failed`、`init_failed`；步骤名本身也是 key（`基本信息卡片`、`链接与简介卡片`、`多语言字段卡片`、`补充说明卡片`、`实时预览卡片`、`产出卡片`、`合成模式卡片`、`选择文件卡片`、`输出位置卡片`、`执行卡片`、`读取资源库并填表`）。
* **提示条标题**：`tip_success`=成功、`tip_error`=错误、`tip_warning`=提示、`tip_info`=信息；错误专用标题 `请先处理这些问题`。
* **表单字段/占位符**：`name_required`、`id`、`code`、`category`、`platforms`、`arch`、`icon`、`tags`、`url`、`github`、`author_page`、`chat_url`、`description`、`intro`、`supplement`、`ph_name`、`ph_id`、`ph_url`、`ph_github`、`ph_tags`、`ph_author_page`、`ph_chat`、`ph_name_l10n`、`ph_desc_main`、`ph_intro_main`、`ph_supplement_main`、`no_image`、`import_image`、`follow_category`、`basic_info`、`links_only`、`other_links`。
* **提示 / tip**：`tip_code`、`tip_import`、`tip_follow_category`、`tip_none`、`tip_none_decided`。
* **多语言**：`lang_fields`、`lang_fields_default_on`、`lang_fields_hint`、`lang_fields_tip`、`zh_cn`、`zh_tw`。
* **产出**：`output`、`then_do_one`、`load_existing`、`gen_draft`、`append_local`、`save_as_new`、`clear_form`、`library_path_hint`、`library_not_found_hint`、`覆盖`、`覆盖已有资源`、`取消`、`清空`、`确定要清空当前填写的所有内容吗？`、`载入现有资源`、`选择要编辑的资源：`、`已载入`、`已写入资源库`、`written_to_library`、`稿件已生成`、`已生成独立资源库`、`无编码`、`说明.txt`、`单条资源稿件，可直接提交给 ToolsGCP 作者`、`ToolsGCP 资源索引文件`、`JSON 文件 (*.json)`、`选择稿件输出目录`、`draft_readme_head`、`draft_readme_json`、`draft_readme_icon_line`、`draft_readme_no_icon`、`draft_readme_howto`、`zip_packed`、`zip_pack_failed`、`errors_fix_first`、`confirm_overwrite_entry`、`backup_failed_abort`、`write_failed`、`图片已导入`、`图标目录`、`原位置`、`image_saved_as`。
* **校验**：`「名称」必填`、`「标识 id」必填`、`「标识 id」只能包含小写字母、数字和连字符`、`图标文件不存在（重新导入一次图片）`、`err_id_taken`、`err_code_taken`、`还没导入图片，卡片上会显示成默认图标`、`「官网」留空了，卡片上会没有「官网」按钮`、`「官网」没写 http://，已按 https:// 处理`、`「简介」留空了，卡片上只有名称`、`「类别」留空了，这条不会出现在类别分组里`、`「开源仓库」留空了，卡片上会没有仓库按钮`、`warn_no_http_scheme`、`status_all_ok_with_warns`、`信息完整，可以生成/追加了。`。
* **图标错误**：`icon_dir_create_failed`、`icon_copy_failed`、`图片没能复制进图标目录，请再试一次。`、`图片没能存进图标目录，已中止写入（资源库没有被改动）`、`图片没能跟着改名`、`这个图片文件不存在`、`这个文件不存在`、`pick_icon_dialog_title`。
* **浏览页**：`search_library`、`all_categories`、`reload`、`open_library`、`load_into_form`、`delete_selected`、`column_listed_at`、`browser_total`、`browser_filtered`、`browser_shown`、`browser_busy_filling`、`「名称」不能留空`、`这一格没有改`、`已修改`、`cell_changed_backup`、`图标文件不存在…`、`图片已换好`、`icon_replaced_backup`、`双击这里可以换一张图片`、`换一张图片（改图标）`、`没有选中任何条目`、`先在表格里点一行，再点「载入到制作资源」`、`先在表格里选一行`、`删除条目`、`confirm_delete_entries`、`删除`、`已删除`、`entries_backed_up`、`找不到这条资源`、`备份失败，已中止写入`、`写入失败`、`备份失败，已中止删除`、`打不开`、`资源库没有被改动`、`（无标签）`、`preview`、`preview_name`、`preview_desc`。
* **批量页**：`① 选择合成模式`、`② 选择要合成的 JSON 文件`、`③ 输出位置`、`④ 检查并执行`、`合成模式`、`追加到本机资源库（默认）`、`多个 JSON 合并成新文件`、`重复条目`、`跳过重复（推荐）`、`重复的覆盖旧条目`、`全部保留（重新分配编码）`、`判断重复的依据：编码相同，或者标识 id 相同`、`batch_files_hint`、`添加文件`、`移除选中`、`清空列表`、`files_selected`、`目标资源库`、`保存到`、`选择新 JSON 的保存位置`、`选择…`、`保存合并结果`、`选择要合成的 JSON`、`点「预览结果」看看会合并进来多少条。`、`预览结果`、`开始合成`、`还没选文件`、`先添加要合成的 JSON`、`确认合成`、`confirm_merge_write`、`先选一个保存位置`、`merge_src_summary`、`merge_src_item`、`merge_more_files`、`merge_result`、`merge_count_change`、`⚠️ 读不了的文件：`、`merged_ok`、`generated_ok`、`完成`、`出错了`。
* **使用说明**：`help_text`、`help_first_block_title`。

---

## 2. 应用部署页（`deploy_interface.py`）

容器类 `DeployInterface`，`objectName = "deployInterface"`，表格 `objectName = "deployTable"`（`:240`、`:333`）。

### 2.1 骨架与尺寸

`setup_ui`，`:258-364`

```text
layout VBox: margins(36, 28, 36, 28), spacing 16          :260-261
├─ mode_widget HBox: margins 0, spacing 10                 :264-267
│  ├─ SwitchButton（OnText/OffText 都设为空串）             :269-274
│  ├─ mode_label BodyLabel，字体 = ui_font(12)（12pt）      :276-277
│  ├─ addSpacing(16)
│  ├─ mode_hint CaptionLabel（次要色，未上色）
│  └─ addStretch()
├─ toolbar HBox: spacing 8                                 :287-288
├─ table TableWidget（stretch=1）
└─ bottom HBox: spacing 12
   ├─ progress QProgressBar（stretch=1，高 6，无文字，默认 hide）
   └─ progress_label CaptionLabel
```

### 2.2 模式开关与两种模式差异矩阵

模式持久化键：设置项 **`deploy_mode`**（`False`=导出模式，`True`=部署模式；`:246-247`、`:1028-1032`）。
切换时：写设置 → `update_mode_ui()` → 记日志 → InfoBar info（标题 `模式切换`，内容 `当前模式: {模式名}`，`duration=1500`）。

`update_mode_ui`（`:485-512`）一次性决定：

| 元素 | 导出模式（is_deploy_mode=False） | 部署模式（True） |
| --- | --- | --- |
| `mode_label` | `export_mode` = 导出模式 | `deploy_mode` = 部署模式 |
| `mode_hint` | `export_hint` = 把本机常用软件整理成清单，导出后拷到新电脑 | `deploy_hint` = 导入清单后一键自动下载 / 打开官网，快速还原环境 |
| 第 6 列表头 | `install_path` = 安装路径 | `download_source` = 下载来源 |
| `deploy_btn`（一键部署，Primary, FIF.PLAY） | 隐藏 | 显示 |
| `import_btn`（导入清单, FIF.DOWNLOAD） | 隐藏 | 显示 |
| `export_btn`（导出清单, FIF.SAVE_AS） | 显示 | 隐藏 |
| `add_btn`（从资源库添加, FIF.ADD） | 显示 | 隐藏 |
| `pick_btn`（从搜索页选择, FIF.SEARCH） | 显示 | 隐藏 |
| `fav_import_switch` + `fav_import_label`（从收藏夹导入） | 显示 | 隐藏 |
| `clear_btn`（清空列表, FIF.DELETE） | **始终显示** | **始终显示** |

工具栏顺序（`:290-324`，全部左对齐，末尾 `addStretch()`，**没有右侧计数文字**）：

```text
[从资源库添加] [从搜索页选择] · addSpacing(6) · [从收藏夹导入 开关+文字] [导入清单/导出清单] [一键部署] [清空列表] ——stretch——
```

「从收藏夹导入」开关：`SwitchButton`，**默认关闭**（`setChecked(False)`），
tooltip `import_favorites_tip` = `打开后，从搜索页选择时可以整夹导入收藏夹里的程序`。

### 2.3 表格 8 列规格

常量（`:214-234`）与渲染（`:514-543`）：

| 列号 | 常量 | 表头（导出模式 / 部署模式） | 初始宽 | 对齐 | 内容规则 |
| --- | --- | --- | --- | --- | --- |
| 0 | `COL_ICON` | 空字符串 | 52 | 默认 | 资源库那条资源的图标（`resource_icon()`，24×24）；取不到 → `FIF.APPLICATION.icon()`；**tooltip = 软件名称** |
| 1 | `COL_INDEX` | `sequence` = 序数 | 52 | 默认 | `str(i + 1)`，从 1 开始 |
| 2 | `COL_CODE` | `code` = 编码 | 112 | 默认 | `software["code"]`；**为空显示 `—`**（全角破折号） |
| 3 | `COL_NAME` | `software_name` = 软件名称 | 200（实际 = `QHeaderView.Stretch`，吃掉剩余宽度） | 默认 | `software["name"]` |
| 4 | `COL_VERSION` | `version` = 版本 | 96 | 默认 | `software["version"]`（导出模式基本是空串） |
| 5 | `COL_SOURCE` | `install_path` / `download_source` | 150 | 默认 | 导出模式 = `software["path"]`；部署模式 = `software["source"]`，为空则 `_source_text()`（见下） |
| 6 | `COL_STATUS` | `status` = 状态 | 110 | 默认 | **纯文本**，`status_text(存盘值)`（见 2.5）。⚠️ 原版**没有胶囊、没有颜色** |
| 7 | `COL_OPS` | `operation` = 操作 | 110 | — | `setCellWidget(i, COL_OPS, self._make_ops(i))`，一个 `QWidget`（内容 `margins(4,2,4,2)`、spacing 4、末尾 `addStretch()`） |

`COLUMN_COUNT = 8`；表头 `Interactive` + `setStretchLastSection(False)`；`SelectRows`；`NoEditTriggers`；
`setIconSize(24×24)`；`verticalHeader().setDefaultSectionSize(36)`。
⚠️ 编码列 96px 会把 `TG-000001` 截成 `TG-00…`，必须 ≥112（原注释 `:227`）。

`_source_text()`（`:545-553`）——只在部署模式下兜底：

| 条件 | 显示 |
| --- | --- |
| 资源库找不到该编码 | `unknown_code` = 资源库里没有这个编码 |
| 资源有 `download_url` | `source_direct` = 直链 |
| 资源有 `github` | 字面量 `GitHub Release`（**不是语言键**） |
| 其它 | `source_page` = 官网 |

### 2.4 行内操作按钮（`_make_ops`，`:555-606`）

所有按钮都是 `ToolButton`（无文字），`ToolTip` 即文案。

**部署模式**（3 个）：

| 顺序 | 图标 | tooltip | 行为 | 出现条件 |
| --- | --- | --- | --- | --- |
| 1 | `FIF.DOWNLOAD` | `download` = 下载 | `deploy_single(i)` | `_preview_kind` ∈ {direct, github} |
| 1' | `FIF.LINK` | `open_page` + `\n` + `ctrl_open_tip` | `open_page_single(i)` | 其它情况（page / unknown） |
| 2 | `FIF.GLOBE` | `open_page` + `\n` + `ctrl_open_tip` | `open_page_single(i)` | **始终有** |
| 3 | `FIF.CANCEL` | `skip` = 跳过 | `set_status(i, ST_SKIPPED)` | **始终有** |

`ctrl_open_tip` = `Ctrl+左键：静默打开，不切走`。
⚠️ 顺序是「下载/链接 → 地球 → 跳过」，**地球和第一个常常功能重复**（这是原版行为，不是笔误）。

`_preview_kind`（`:608-619`）：无 code → `None`；库中找不到 → `None`；有 `download_url` → `direct`；有 `github` → `github`；否则 `page`。

**导出模式**（2 个）：

| 顺序 | 图标 | tooltip | 行为 |
| --- | --- | --- | --- |
| 1 | `FIF.EDIT` | `edit` = 编辑 | `edit_software(i)` |
| 2 | `FIF.DELETE` | `delete` = 删除 | `delete_software(i)`（**无二次确认**，直接 pop + 存盘 + 刷新） |

### 2.5 状态胶囊的取值与显示文案

⚠️ 原版**没有胶囊控件**，是表格里的纯文本单元格。存盘值（稳定值，写进 `deploy_config.json`
且被 `startswith(ST_FAILED)` 之类判断依赖，**不随语言变**，`:43-51`）：

| 存盘常量 | 值 | 显示用语言键 | 简中显示 |
| --- | --- | --- | --- |
| `ST_PENDING` | `待部署` | `pending` | 待部署 |
| `ST_DOWNLOADING` | `下载中` | `st_downloading` | 下载中 |
| `ST_DONE` | `已下载` | `st_done` | 已下载 |
| `ST_OPENED` | `已打开官网` | `st_opened` | 已打开官网 |
| `ST_SKIPPED` | `已跳过` | `st_skipped` | 已跳过 |
| `ST_FAILED` | `失败` | 无（走前缀分支） | `失败: {原因}` |

`status_text()`（`:414-421`）：

```python
if status.startswith("失败: "):
    return f"{get_text('st_failed')}: {status[len('失败')+2:]}"   # 前缀翻译，原因原样保留
return get_text(STATUS_KEYS.get(status, status))                  # 认不出来就原样回显存盘值
```

`STATUS_KEYS = {ST_PENDING:"pending", ST_DOWNLOADING:"st_downloading", ST_DONE:"st_done", ST_OPENED:"st_opened", ST_SKIPPED:"st_skipped"}`（`:54-60`，**没有 ST_FAILED**）。
载入旧数据时缺 `status` → 一律 `ST_PENDING`（`:467`）。

### 2.6 进度条行为

`self.progress` = `QProgressBar`，`setFixedHeight(6)`、`setTextVisible(False)`、**默认 hide**（`:353-357`）；`progress_label` 是右侧 `CaptionLabel`。

生命周期（`:901-951`、`:1010-1025`）：

| 时刻 | progress | progress_label |
| --- | --- | --- |
| 空闲 | 隐藏 | 空串 |
| 开始单条下载 | `setRange(0, 0)`（**不确定态/滚动条**） | `正在处理: {name}` |
| 收到进度且 `total > 0` | `setRange(0, 100)`，`setValue(int(received*100/total))` | `正在处理: {name}  {received/1048576:.1f} / {total/1048576:.1f} MB` |
| 收到进度但 `total == 0` | 保持不确定态 | `正在处理: {name}  {received/1048576:.1f} MB` |
| 成功 / 失败 / 批处理结束 | 隐藏 | 清空 |

单条下载会**串行**：`_batch_running` 为真时，成功或失败后 `QTimer.singleShot(200, _next_in_batch)`。
下载目录 `_ensure_download_dir()`（`:889-899`）：默认 `~/Downloads/ToolsGCP-Deploy`（自动创建），
弹目录选择框（标题 `download_dir` = 选择下载目录）；取消 → 整批中止。同一批只问一次（`_download_dir` 缓存）。
限速值来自设置：`is_download_speed_limited()` → `download_speed_limit`（MB/s），传给 `DownloadWorker`（`:906-910`）。
文件名：`safe_filename(target["filename"] or f"{name}.bin")`（去 `\/:*?"<>|`）。

### 2.7 空状态

⚠️ **原版没有空状态占位控件**。列表为空时表格就是 0 行，什么都不显示。
`no_software`（= 暂无软件）这个语言键**在原版代码里没有任何调用点**（`deploy_interface.py` 只在默认表里有它，见 `:375`；全库 grep 仅此一处）。

`empty_tip` = `列表为空，先「从资源库添加」几条吧` 只在两个动作里以 **InfoBar warning** 出现：

* 「导出清单」且列表为空（`:797-800`）；
* 「一键部署」且列表为空（`:958-960`）。

网页端若要加真正的空状态占位，属于**新增**，不是还原。

### 2.8 导入 / 导出清单

落盘位置：**`%DATA_DIR%/deploy_config.json`**（绝对路径，`DEPLOY_FILE`，`:40`），格式：

```json
{ "schema_version": "1.0.0", "updated_at": "<isoformat(seconds)>", "items": [ ... ] }
```

`DEPLOY_FILE_SCHEMA = "1.0.0"`。每条 item 固定 6 键（`_normalize_loaded`，`:450-470`）：
`code, name, version, path, status, source`（都 `str()`，缺失给 `""`；`status` 缺失给 `ST_PENDING`）。
兼容旧格式：顶层可直接是 list，或 `{"software": [...]}`。

**导出清单**（`:797-824`）：

1. 空列表 → warning `empty_tip`，中止。
2. `QFileDialog.getSaveFileName`，标题 `export_list` = 导出清单，
   默认路径 `<程序目录>/ToolsGCP-Deploy-{YYYYMMDD}.json`，过滤 `json_file_filter` = `JSON 文件 (*.json)`。
3. 写出：
   ```json
   { "schema_version": "1.0.0", "generator": "ToolsGCP",
     "exported_at": "<isoformat(seconds)>", "count": n, "items": [ ... ] }
   ```
   `ensure_ascii=False, indent=2`，末尾补 `\n`，`newline="\n"`。
4. 成功 → `清单已导出: <完整路径>`；失败 → `export_failed` = `{title}失败：{err}`（title 用名词短语 `导出清单`，避免拼成"清单已导出 失败"）。

**导入清单**（`:826-850`）：

1. `QFileDialog.getOpenFileName`，标题 `import_list` = 导入清单，起始目录 `<程序目录>`，过滤同上。
2. 解析 + `_normalize_loaded`；异常 → `导入失败: {err}`；结果为空 → `导入失败`。
3. **所有条目 status 强制改写为 `ST_PENDING`**（`:842-843`）。
4. `software_list = items`（**整体替换**，不是合并）→ 存盘 → 刷新表格。
5. 成功 → `imported_count` = `清单已导入：{n} 项`。

**清空列表**（`:783-794`）：确认框标题 `clear_list` = 清空列表，内容
`confirm_clear_list` = `确定要清空当前清单吗？（本机保存的清单也会一起清空）`，按钮 `confirm_clear` = 清空 / `cancel` = 取消。

### 2.9 两条添加链路

#### 链路 1：从资源库添加（`add_from_library`，`:629-666`）

1. 资源库空 → InfoBar 错误，内容 `unknown_code`。
2. 弹 `ResourcePickerDialog(resources, self, selected_codes=已在清单里的编码)`。
3. 对话框规格（`:97-208`）：
   * 继承 `MessageBoxBase`；标题 `add_from_library` = 从资源库添加（`SubtitleLabel`）。
   * `SearchLineEdit`，占位符 `search_placeholder` = `按编码或名称搜索，例如 TG-000001 / Steam`。
   * `ListWidget`，`setMinimumHeight(340)`，`ExtendedSelection`（Ctrl / Shift 多选），图标 24×24，
     **双击 = 直接确认**；每项文本 = `"{code}   {name}"`（三个空格），`Qt.UserRole` 存整条资源 dict。
   * 过滤：关键词命中 `code` / `name` / `id`（不区分大小写）。
   * 提示行 `CaptionLabel`：`picker_multi_hint` = `可以多选（Ctrl / 点选多条，Shift 连选），双击也会直接添加`。
   * 按钮：`add` = 添加 / `cancel` = 取消；`widget.setMinimumWidth(460)`。
   * ⚠️ `selected_codes` 参数在构造函数里被赋值但**没有实际用于预选中**（原版代码里 `self._selected_codes` 建完就再没被读）——这是原版的一个"说了没做"。
4. 确认后逐条去重（同 `code` 已存在则跳过），新条目固定：
   `{code, name: 资源名, version: "", path: "", status: ST_PENDING, source: ""}`。
5. 存盘 + 刷新；`added > 0` → InfoBar 成功 `added_n_from_library` = `已从资源库添加 {n} 条`；
   否则 InfoBar info `all_selected_in_list` = `选中的应用都已在清单里`。

#### 链路 2：从搜索页选择（`open_picker`，`:668-681` → `add_codes`，`:683-714`）

1. 点「从搜索页选择」：取主窗口的 `searchInterface`；拿不到 → InfoBar 错误 `search_page_missing` = 找不到搜索页。
2. `search.begin_selection("deploy", allow_favorites=fav_import_switch.isChecked())`
   （`search_interface.py:706-732`）：
   * 搜索页进入勾选模式；显示 `SelectionBar`；确认按钮文字改成 `add_to_deploy` = **添加到部署清单**；
   * `allow_favorites=True` 时额外显示「从收藏夹导入」下拉（第 0 项占位 `choose_folder` = 选择收藏夹…，
     之后每个收藏夹一项 `"{显示名} ({条数})"`），选中某夹 → 该夹全部程序被勾上，弹提示 `从收藏夹导入: {name} → {n}`；
   * `SelectionBar`（`widgets/selection_bar.py:16-69`）结构：`CheckBox(select_all)` + `BodyLabel("selected / total")` +
     `addStretch()` + 右侧「取消」+「添加到部署清单」。勾选数 0 或部分时全选框为未选中（`CheckBox` 没有三态）。
   * 确认时无勾选 → InfoBar warning `nothing_selected` = 还没有勾选任何应用。
3. 切换主窗口到搜索页并同步左侧导航选中项。
4. 搜索页确认后 `apps_selected` 信号 → `add_codes(codes)`（`:683-714`）：
   逐条去重（`s.get("code") == code` 则跳过），新条目 `{code, name: 资源名或 code, version:"", path:"", status:ST_PENDING, source:""}`；
   存盘 + 刷新 + 提示；**加完自动切回应用部署页**（`go_to_self_page()`，`:716-727`；原注释：不切回去用户不知道清单变了）。

### 2.10 单条部署 / 一键部署

下载目标解析 `utils/downloader.resolve_target(resource)`（`downloader.py:118-143`）：

| 优先级 | kind | 条件 |
| --- | --- | --- |
| 1 | `direct` | `download_url` 以 `http://`/`https://` 开头；文件名 = URL 路径的 basename，空则 `{id}.bin` |
| 2 | `github` | 有 `github` → 查 `https://api.github.com/repos/{owner}/{repo}/releases/latest`，按打分挑安装包 |
| 3（退路） | `page` | GitHub 查询失败 → 打开 `url`，没有 `url` 就打开 `github` |
| 3' | `page` | 没有 `download_url` 也没有 `github`，但有 `url` |
| 4 | `unknown` | 都没有 → `error = "该资源没有可用地址"` |

GitHub 资产打分（`downloader.py:53-80`）：后缀优先级 `PREFERRED_EXTS = (.exe, .msi, .zip, .7z, .rar, .dmg, .pkg, .apk, .deb, .appimage)`，
第 i 个给 `100 - i*5` 分；命中 `SKIP_HINTS = ("source","src","debug","symbols","linux","macos","darwin","android","ios")` 扣 60；
含 `mono/console/headless` 扣 15；有 size 加 1；跳过 `.sig/.sha256/.txt/.json/.yml/.yaml/.asc`。
结果按 repo 缓存（`_asset_cache`）。`USER_AGENT = "ToolsGCP-Deploy/1.0"`，超时 20s（API 15s）。

**一键部署**（`deploy_all`，`:954-1008`）：

1. 正在批处理 → InfoBar info `batch_running` = 正在处理，直接返回。
2. 空列表 → warning `empty_tip`。
3. 确认框：标题 `confirm_deploy` = 开始部署，内容 `confirm_deploy_body` =
   `将处理清单里的 {n} 个程序：\n· 能从 GitHub / 直链拿到安装包的会自动下载\n· 只能拿到官网的会帮你打开下载页面\n（开始前会让你选一个下载目录）`，按钮 `start` = 开始 / `cancel` = 取消。
4. 选下载目录（取消 → 中止）；`deploy_btn.setEnabled(False)`，`_batch_index=0`。
5. 逐条：`direct/github` → 下载（走 2.6）；`page` → `open_url()` 后 `set_status(ST_OPENED)`，**停 1200ms** 再下一条（避免一次开几十个标签页）；`unknown` → `set_status("失败: {err}")`，停 120ms。
6. 收尾 `_finish_batch`（`:1010-1025`）：恢复按钮、隐藏进度、
   InfoBar 成功：标题 `deploy_done` = 部署完成，内容 `batch_done_summary` = `自动下载完成 {done} 个，已打开官网 {opened} 个，失败 {failed} 个`，`duration=6000`。
   统计口径：`done = status == ST_DONE`；`opened = status == ST_OPENED`；`failed = status.startswith(ST_FAILED)`。

**单条部署**：`deploy_single`（`:877-887`）kind 不是 direct/github 时**退化成打开官网**。

Ctrl+左键：`open_page_single` 通过 `watch_ctrl(widget)` 观察 Ctrl 状态（状态存在**页面**上 `self._open_page_ctrl`，因为 clicked 回调拿不到按钮对象，`utils/url_open.py` 的 `open_url()` 自己读）。

### 2.11 语言 key 清单（`deploy_language.json`，73 条，段名 `deploy`）

`sequence, software_name, version, install_path, status, operation, edit, delete, deploy, no_software, export_mode,
deploy_mode, mode_switched, current_mode, code, download_source, add_from_library, added_n_from_library, add_manual,
pick_from_search, import_favorites, import_favorites_tip, import_list, export_list, deploy_all, clear_list,
export_hint, deploy_hint, download, open_page, ctrl_open_tip, skip, empty_tip, exported, imported, import_failed,
unknown_code, deploy_done, download_dir, confirm_deploy, batch_running, manual_add_title, pending, search_placeholder,
add, cancel, code_placeholder, software_name_placeholder, confirm_clear, start, picker_double_click_hint,
picker_multi_hint, already_in_list, search_page_missing, all_selected_in_list, confirm_clear_list, export_failed,
imported_count, confirm_deploy_body, name_label, json_file_filter, source_direct, source_page, st_downloading,
st_done, st_opened, st_skipped, st_failed, batch_done_summary, tip_success, tip_error, tip_warning, tip_info`

搜索页侧还要用到（`search_language.json`）：`select_all`、`from_folder`、`choose_folder`、`add_to_deploy`、`nothing_selected`、`cancel`。

### 2.12 ⚠️ 原版这里的问题（网页端不要照抄）

1. **`add_manual` 是死代码**：`:729-743` 定义了「手动添加」，但工具栏里**没有任何按钮连它**（全库 grep 只有定义处）。
   `manual_add_title` / `code_placeholder` / `software_name_placeholder` / `name_label` 这几个 key 只被它和被「编辑」共用的 `_ask_two_lines` 使用。
2. **「编辑」弹的是两行裸输入框**（`_ask_two_lines`，`:745-762`）：用原生 `QDialog + QFormLayout + QDialogButtonBox`，
   **不是** qfluentwidgets 的 `MessageBox`，所以深色主题下按钮是 Qt 默认英文 `OK` / `Cancel`，与整页风格不一致。
   编辑逻辑：`item["code"] = 输入 or 原值`、`item["name"] = 输入 or 原值`（**清空 = 不改**，`version/path` 根本改不了）。
3. **删除无确认**；「清空列表」有确认。
4. `_source_text` 里的 `"GitHub Release"` 是硬编码英文（未走语言键）。
5. 下载按钮的 tooltip 提示 Ctrl+左键，但 `deploy_single` → `_start_download` **不经过** `open_url`，所以 Ctrl 对「下载」按钮其实没有静默打开语义（只有 `open_page_single` 有）。

### 2.13 网页端现状对照（`webui/index.html:827-910`，只读核对，供对齐参考）

| 项 | 原版 | 网页端现状 | 结论 |
| --- | --- | --- | --- |
| 工具栏（导出模式） | 从资源库添加 / 从搜索页选择 / **从收藏夹导入开关** / 导出清单 / 清空列表 | 少了「从收藏夹导入」开关 | 缺 |
| 工具栏（部署模式） | 导入清单 / 一键部署 / 清空列表 | 一致 | ✅ |
| 工具栏右端 | 无计数 | 多了「清单里 {n} 项」 | 新增，非还原 |
| 编码列空值 | `—` | 原样输出 | 缺 |
| 第 6 列（来源） | 部署模式三态兜底文案 / 导出模式只看 `path` | `row.path \|\| row.source \|\| row.url \|\| row.github \|\| '—'` | 规则不同 |
| 状态列 | **纯文本** | `.status-pill` 胶囊 | 新增，非还原 |
| 空状态 | **没有**（0 行） | 有一行居中提示 | 新增，非还原 |
| 行内操作 | 部署 3 个（下载/链接、地球、跳过）；导出 2 个（编辑、删除） | 一致 | ✅ |
| 进度条 | 高 6 的 QProgressBar，未知总量时不确定态 | `.mini-progress` 百分比 | 需按 2.6 改 |
| 模式提示文字 | `export_hint` / `deploy_hint` | 用了 `export_mode_tip` / `deploy_mode_tip`（自造 key） | key 名不同 |

---

## 3. 设置 · 下载限速

### 3.1 原版这一行的完整构成

全部在 `_create_download_card` 里，**同一个卡片内部**，顺序：
资源来源块（`:47-113`）→ 搜索源（`:171-195`）→ 下载源（`:197-220`）→ 更新下载渠道（`:222-252`）→ **下载限速**（`:254-332`）。

卡片本身：`SimpleCardWidget`，`layout.setContentsMargins(20,20,20,20)`、`setSpacing(15)`（`:163-166`）。

**第 1 行（开关行）** `:255-290`

```text
HBox margins(0,0,0,0)，无 spacing 设置（默认）
├─ BodyLabel(download_speed_limit = 下载限速)，objectName "whiteInDarkLabel"
├─ addStretch()
└─ checkbox_container QWidget  setFixedWidth(180)   ← 与上面的 ComboBox 对齐
   HBox margins(0,0,0,0), spacing 6, AlignRight|AlignVCenter
   ├─ speed_limit_status_label QLabel(动态文案)，objectName "whiteInDarkLabel"，字体 ui_font(9)（9pt ≈ 12px）
   └─ speed_limit_checkbox CheckBox()  ← Fluent 风格，没有任何 setStyleSheet
```

* 初始化：`enabled = settings["download_speed_limit_enabled"]`（默认 `False`），`value = settings["download_speed_limit"]`（默认 `100`）。
* 状态文字（`update_speed_limit_status_text`，`:337-342`）：开 → `"{value} MB/s"`；关 → `unlimited` = **无限制**。
* ⚠️ 这一行的标题**没有 ⓘ tooltip**。语言文件里虽然有 `download_speed_limit_tip`
  （= 限制下载速度，避免占满带宽），但 `cards_download.py` 从未使用它（全库 grep 只命中语言文件与 en_fallback）。

**第 2 行（滑块行，缩进）** `:292-330`

```text
HBox: setContentsMargins(20, 0, 0, 0)     ← 左侧缩进 20px（表示是上面那个开关的分支）
      spacing 8
├─ speed_limit_label BodyLabel(limit_speed = 限速)，objectName "whiteInDarkLabel"
├─ addStretch()
├─ speed_limit_slider Slider(Qt.Horizontal)  setRange(1, 300)  setFixedWidth(250)
├─ speed_limit_input  LineEdit  setFixedWidth(50)  setAlignment(AlignCenter)
│                     setValidator(QIntValidator(1, 300))
└─ speed_limit_unit_label QLabel("MB/s")   ← 硬编码，非语言键
```

| 属性 | 值 |
| --- | --- |
| 范围 | **1 ~ 300**（闭区间） |
| 步长 | 拖动为 1（Qt Slider 默认 `singleStep = 1`）；**滚轮一格 = ±1**（原版自己接管） |
| 单位 | `MB/s`（大写 MB） |
| 默认值 | `100` |
| 滑块宽 / 数字框宽 | **250px** / **50px**（数字框文字居中） |
| 越界处理 | **钳制**：`< 1` → 写回 `"1"`；`> 300` → 写回 `"300"`（`:398-408`） |
| 非法输入 | `ValueError` → 静默忽略（不报错、不落盘） |

**可见性条件** `:324-332`、`:345-360`

* 需求原文（注释里）："设置中的下载限速未选中则关联的限速那行不显示，如果勾选了则显示。"
* `update_speed_limit_state(enabled)`：
  * `speed_limit_row.setVisible(enabled)` —— **整行 show/hide**（不是变灰）；
  * 同时 `slider.setEnabled(enabled)`、`input.setEnabled(enabled)`（防"藏起来还能让快捷键改到"）；
  * `set_label_disabled(speed_limit_label / unit_label, not enabled)` —— 标签在禁用时变灰；
  * 最后用**滑块当前值**刷新状态文字。
* 开关切换时（`:363-372`）：
  * 开 → InfoBar 成功：`下载限速: 已开启`
  * 关 → InfoBar info：`下载限速: 已关闭 (无限制)`

**联动规则** `:375-415`

```text
滑块 valueChanged(v):
    input.setText(str(v))
    _saver.set("download_speed_limit", v)      # debounce，拖动中不落盘
    若开关是开的 → 状态文字 = "{v} MB/s"

输入框 textChanged(t):
    能转成 int 才处理；<1 写回 "1"、>300 写回 "300"
    slider.setValue(value)                     # ← 唯一真源是滑块
    _saver.set(...)
    若开关是开的 → 状态文字 = "{value} MB/s"

滚轮（滑块 或 输入框上，install_wheel_step）:
    delta = +1 / -1；target = clamp(current + delta, 1, 300)
    只改滑块；输入框同步与落盘交给上面的滑块回调
```

⚠️ 原注释（`:328-330`）：**Qt 默认滚一格跳 3，数字框完全不响应滚轮**，所以原版把两边都接管掉
（`install_wheel_step` 实现见 `settings/widgets.py:44-52`）。

### 3.2 网页端当前有什么 / 缺什么

网页端位置：`webui/js/app.js` 的 `sections` → `download` 板块，两行相邻（`app.js:2312-2315`）；
渲染模板 `webui/index.html:1165-1178`；样式 `webui/css/components.css:191-199`、`webui/css/layout.css:460`。

| # | 项 | 原版 | 网页端 | 结论 |
| --- | --- | --- | --- | --- |
| 1 | 开关 = `checkbox` 类型，右侧 `statusText` | ✅ CheckBox + 右侧状态文字 | ✅ `type:'checkbox'` + `statusText`（`app.js:2313`） | 有 |
| 2 | 状态文字格式 | 开 = `{v} MB/s`，关 = `unlimited` | 同（`app.js:2313`） | 有 |
| 3 | 状态文字字号 | `ui_font(9)`（9pt ≈ **12px**） | `.switch-status { font-size: 11.5px }`（`components.css:132`） | 差 0.5px，可忽略 |
| 4 | 开关容器宽 180 与上方 ComboBox 对齐 | ✅ | `.setting-control { width: var(--control-width) }` = 200 | 差 20px（**不是**对齐 180） |
| 5 | 滑块范围 / 步长 / 单位 | 1~300 / 1 / `MB/s` | `min:1, max:300, step:1, unit:'MB/s'`（`app.js:2314-2315`） | ✅ 有 |
| 6 | 滑块**可见性** | 未勾选 → **整行 hide** | `visible: speedOn`（`app.js:2315`） | ✅ 有（需确认 CSS 是 `display:none` 而非 `opacity`） |
| 7 | 第二行缩进 | **20px** | `.setting-row.is-indent { padding-left: 20px }` | ✅ 有 |
| 8 | 滑块宽度 | **250px** | `.range { flex:1 1 auto; max-width: 150px }`（`components.css:192`） | ❌ **缺 100px** |
| 9 | 数字框宽度 / 居中 | **50px** / 居中 | `.num-input { width: 46px; text-align:center }`（`components.css:196-198`） | 差 4px |
| 10 | 数字框输入校验 | `QIntValidator(1,300)` + 越界钳制写回 | 只有 `@change` 时 `clamp(1,300)`（`app.js:2517-2518`），输入过程中不限制，非数字落 `100` | ⚠️ 弱一档（原版非数字是**忽略**，网页端会**改成 100**） |
| 11 | 拖动中不落盘 | ✅ debounce | ✅ `debouncedCommit(..., 400)`（`app.js:2476`） | ✅ |
| 12 | **滚轮一格 ±1** | ✅ 滑块 + 数字框都接管 | ❌ **完全没有**（全文件 grep `wheel` 只命中首页轮播 `app.js:1355-1363`、`index.html:36,221`） | ❌ **缺** |
| 13 | 滑块 ←→ 数字框双向联动 | ✅（滑块为唯一真源） | ✅（同一个 `draft[row.key]`，`index.html:1173-1177`） | ✅ |
| 14 | 标题 ⓘ tooltip | **原版没有** | 无 | ✅ 一致（不要加） |

**网页端要补的最小集合**：`(a)` 滚轮 ±1（对滑块与数字框各挂一个 `wheel` 监听，`preventDefault` + `clamp(1,300)`）；
`(b)` 滑块可视宽 250px（把 `.range` 的 `max-width` 提到 250，或给限速行单独一个 class）；
`(c)` 开关行容器宽按上方的 ComboBox 宽度对齐（原版是 180，网页端 ComboBox 用 `row.width` = 180 或 200，取值要统一）；
`(d)` 数字框 `input` 事件里实时钳制（照原版语义：非数字忽略、越界写回边界值）。

---

## 4. 设置 · 搜索源 / 下载源

### 4.1 可选值列表（唯一事实来源）

`constants.py:144-150`

```python
GITHUB_MIRRORS = ["ghfast.top", "gh-proxy.com", "ghproxy.net", "gh.ddlc.top"]
SOURCE_OPTIONS = ["Github"] + GITHUB_MIRRORS
# 实际顺序：["Github", "ghfast.top", "gh-proxy.com", "ghproxy.net", "gh.ddlc.top"]
```

* 原版 `_fill_source_combo`（`cards_download.py:451-461`）：第 1 项 `"Github"` **显示成语言键 `github_source`**（值就是 `Github`），
  userData = `"Github"`；其余镜像站**直接显示域名**，userData = 域名字符串。
* ⚠️ 「国内源」已按需求删除（`constants.py:145-148` 原注释）。它现在只是"可选项"，**真正走镜像下载的功能还没做**。

### 4.2 原版默认值与空值行为（关键）

设置项默认值（`constants.py:175-176`）：

```python
"search_source": "",
"download_source": "",
```

**存的是空串**。但界面**不会**显示空，因为选中逻辑是（`cards_download.py:463-472`）：

```python
def _select_source(self, combo, setting_key):
    self._migrate_source_setting(setting_key)          # 非空且不在 SOURCE_OPTIONS → 迁移成 "Github"
    value = str(settings.get(setting_key, "") or "")
    index = 0                                          # ← 找不到就落 index 0
    for i in range(combo.count()):
        if combo.itemData(i) == value:
            index = i
            break
    combo.setCurrentIndex(index)
```

⇒ `value == ""` 时循环一次都不命中，**`index` 保持 0 = `Github`**。
所以原版的实际表现是：**存盘为空串，界面显示并选中「Github」**。
用户一旦手动选一次，才写入真实值（`change_search_source` / `change_download_source`，`:418-427`，
写入 `combo.itemData(index)`，拿不到则 `or "Github"`）。

旧值迁移 `_migrate_source_setting`（`:474-484`）：值非空且不在 `SOURCE_OPTIONS` 里 → 写入 `"Github"`
（不迁移的话界面会显示一个空下拉框，且配置里存着不存在的值 —— 原注释 `:475-477`）。
`SettingsManager.get_default_source_by_language()` 现在**无条件返回 `"Github"`**（`settings_manager.py:155-161`）。

两个下拉框的其它数值：宽度 `setFixedWidth(180)`（`:192`、`:217`）；标题各自带一个 `QLabel("ⓘ")`
（`objectName = "whiteInDarkIcon"`）+ `ToolTipFilter(300ms, ToolTipPosition.TOP)`，
tooltip 内容 = `github_mirror_hint`：
`下面的镜像站会把上面的链接原样转发一份，国内下载通常快很多。这条不通就换一条，或者直接用上面的「下载」走 GitHub 官方。`
（搜索源与下载源用的是**同一段**提示文案，`:183` 与 `:208`。）
切换成功提示：InfoBar 成功，内容 `"搜索源: {当前项文字}"` / `"下载源: {当前项文字}"`（`:421`、`:427`）。

### 4.3 网页端为什么「默认选中为空」

网页端链路（四步全部核对过）：

1. 默认值同样是空串：`webui/js/app.js:53` → `search_source: '', download_source: '',`
   （`webui/js/constants.js:86` 一带是同一份默认表；这是照抄 `constants.py:175-176` 的结果）。
2. 选项列表同样**没有空值项**：`app.js:2301-2306`
   ```js
   options: SOURCE_OPTIONS.map((v) => ({ value: v, label: v }))
   // SOURCE_OPTIONS = ['Github','ghfast.top','gh-proxy.com','ghproxy.net','gh.ddlc.top']（webui/js/constants.js）
   ```
3. 模板**没有传 placeholder**：`webui/index.html:1160-1163`
   ```html
   <combo v-else-if="row.type === 'select'" :model-value="draft[row.key]"
          :options="row.options" :width="row.width || 200"
          :disabled="!!row.disabled" @change="onRowChange(row, $event)"></combo>
   ```
4. `Combo.current` 对不上就返回空串：`app.js:3370-3373`（组件版）/ `webui/js/components/Combo.js:30-33`
   ```js
   current() {
     const hit = this.options.find((o) => String(o.value) === String(this.modelValue));
     return hit ? hit.label : (this.placeholder || '');   // 没 placeholder → ''
   }
   ```

⇒ `modelValue = ''` 在 options 里找不到 → `current = ''` → 触发器渲染成**空白**。

**与原版的差异正是第 4.2 节那 12 行代码**：原版「找不到就落 index 0」；网页端「找不到就显示空」。
另外 `Combo.toggle()`（`app.js:3420-3421`）也是 `idx >= 0 ? idx : 0`，即**打开下拉时高亮第 0 项**，
只有触发器上的文字是空的 —— 所以这个 bug 表现为"看起来没选中，但点开下拉是 GitHub"。

**两种修法（都等价于还原原版，选一个）**：

* **A（推荐，最小改动）**：把 `Combo.current` 改成与原版同语义 —— 找不到匹配项时返回 `options[0].label`（并在 `mounted` 里若 `modelValue` 不在 options 中则 `emit('change', options[0].value)`，顺手把配置写成 `"Github"`）。
* **B（数据层）**：把 `DEFAULT_SETTINGS` 的 `search_source` / `download_source` 从 `''` 改成 `'Github'`，
  并在后端 `SettingsManager.load_settings()` 里加一条一次性迁移（把空串写成 `"Github"`），与 `constants.py` 的语义对齐。
  ⚠️ 只改 `DEFAULT_SETTINGS` 没用：键在用户首次启动时就已落盘为空串，"键存在"所以默认值合并不碰它 ——
  这正是 `settings_manager.py:61-83` 那三段 `_migrated_*` 标记存在的原因。

---

## 5. 主题效果（mica / glass / acrylic）

### 5.1 复核结论：**原版无实现**（已全局 grep，不是照抄第一册）

复核范围与结果（`--include=*.py --include=*.js --include=*.json --include=*.vue --include=*.html --include=*.css`，排除 `__pycache__`）：

| 位置 | 命中 | 性质 |
| --- | --- | --- |
| `.ToolsGCP/modules/pymodels/constants.py:182-184` | `"theme_effect": "mica"` + 注释「mica=云母 / glass=毛玻璃 / acrylic=亚克力」 | **只是一个设置键** |
| `.ToolsGCP/modules/pymodels/core/settings_manager.py:77-83` | `settings["theme_effect"] = "mica"`（`_migrated_ui_defaults` 一次性迁移） | 只写默认值 |
| `.ToolsGCP/modules/pymodels/interfaces/settings/cards_ui.py` | **零命中**（该文件只有 `theme_mode` 与 `accent_color` 两行，`:51-63`） | ⇒ 原版设置页**没有「主题效果」这一行**，用户根本改不到 |
| `.ToolsGCP/modules/pymodels/ui/`、`widgets/`、`interfaces/` 其它文件 | `mica` 仅在注释里出现一次（`main_window.py:1120` 提到"亚克力模糊"是解释 `WA_OpaquePaintEvent`） | 没有任何绘制层读取 |
| `.ToolsGCP/modules/languages/set_language.json:1882-1891` | `theme_effect` = 主题效果、`theme_effect_tip` = 云母：… | 只有文案，没有代码用它 |
| `desktop/native/frame.py`、`desktop/native/win32.py` | 有 `DWMWA_USE_IMMERSIVE_DARK_MODE=20`、`DWMWA_WINDOW_CORNER_PREFERENCE=33`、`DWMWA_BORDER_COLOR=34`、`DWMWA_TRANSITIONS_FORCEDISABLED=3`；**没有** `DWMWA_SYSTEMBACKDROP_TYPE`、**没有** `DWMWA_MICA_EFFECT`、**没有** `SetWindowCompositionAttribute` | ⇒ 新外壳也**没有**做系统背景材质 |

**结论：原版（PyQt5）侧 `theme_effect` 是一条"只有默认值、没有 UI、没有消费者"的僵尸设置键。网页端要真正生效必须自研。**

⚠️ 补充：**新前端 `webui/` 已经有一版自研实现**，但它是纯 CSS 的：
`webui/js/app.js:386`（与 `webui/js/core/state.js:74`）`root.setAttribute('data-fx', settings.theme_effect || 'mica')`，
`webui/css/style.css:136-146` 定义 `[data-fx="glass"] {--fx-blur:26px; --fx-sat:165%; --fx-opacity:.62}`、
`[data-fx="acrylic"] {--fx-blur:16px; --fx-sat:150%; --fx-opacity:.80; --fx-extra: inset 0 1px 0 rgba(255,255,255,.16)}`，
`webui/css/variables.css:22-28` 给 mica 档 `--fx-blur:0px; --fx-opacity:1` + SVG 底噪（`--fx` 默认值 `"mica"` 在 `:23`）。
**它只影响页内层的模糊感，不会糊到桌面** —— 因为窗口本身不透明（见 5.3 限制）。

### 5.2 路径 A：Win32 DWM 系统背景材质（真正可用）

**原理**：让 DWM 在窗口客户区背后画系统材质（Mica / Acrylic），页面背景保持半透明，桌面就真的被"糊"出来。

需要的 API（与 `desktop/native/frame.py` 现有的 ctypes 写法一致，`win32.py:364-368` 已声明 `DwmSetWindowAttribute` / `DwmExtendFrameIntoClientArea`）：

```python
# dwmapi.h（Win11 SDK）
DWMWA_USE_IMMERSIVE_DARK_MODE = 20      # 已有，desktop/native/frame.py:319
DWMWA_SYSTEMBACKDROP_TYPE     = 38      # ⚠️ 本轮新增
DWMSBT_AUTO            = 0
DWMSBT_NONE            = 1
DWMSBT_MAINWINDOW      = 2   # Mica
DWMSBT_TRANSIENTWINDOW = 3   # Acrylic
DWMSBT_TABBEDWINDOW    = 4   # Mica Alt（带标签页感的深色变体）

# 1) 让客户区参与合成（必须，否则材质被不透明客户区挡住）
MARGINS(-1, -1, -1, -1)  →  DwmExtendFrameIntoClientArea(hwnd, byref(margins))
# 2) 深色标题栏（浅色主题下要设 0）
DwmSetWindowAttribute(hwnd, 20, byref(c_int(1)), 4)
# 3) 选材质
DwmSetWindowAttribute(hwnd, 38, byref(c_int(DWMSBT_MAINWINDOW)), 4)
```

三档映射建议：

| `theme_effect` | `DWMWA_SYSTEMBACKDROP_TYPE` | 说明 |
| --- | --- | --- |
| `mica` | 2（MAINWINDOW） | 几乎不糊、带壁纸底噪 —— 与原版注释"云母"语义最贴 |
| `acrylic` | 3（TRANSIENTWINDOW） | 中模糊 + 高光 —— 对应"亚克力" |
| `glass` | 3（TRANSIENTWINDOW）或 `SetWindowCompositionAttribute(ACCENT_ENABLE_BLURBEHIND)` | DWM **没有**"毛玻璃"这一档；要么复用 Acrylic，要么走未公开的 `user32!SetWindowCompositionAttribute`（见 5.4） |

**必须同时满足的前置条件（缺一条就看不到效果）**：

1. **Windows 11 22621（22H2）及以上**。属性号 38 在 Win10 与 Win11 21H2（22000）上会返回
   `E_INVALIDARG`，只能用未公开的 `DWMWA_MICA_EFFECT = 1029`（仅 Mica，且**必须先** `DwmExtendFrameIntoClientArea(-1)`）。
   Win10 全系**没有任何**系统材质可用。
2. **WebView2 的默认背景必须透明**。pywebview 6.2.1 只在 `transparent=True` 时这么做：
   `Lib/site-packages/webview/platforms/winforms.py:286-292`
   ```python
   if window.transparent and self.browser:      # 仅在 EdgeChromium 下支持
       self.SetStyle(ControlStyles.SupportsTransparentBackColor, True)
       self.browser.DefaultBackgroundColor = Color.Transparent
   else:
       self.BackColor = ColorTranslator.FromHtml(window.background_color)
   ```
   （对应 `webview/platforms/edgechromium.py:113-114` 的 `DefaultBackgroundColor = Color.Transparent`。）
3. **当前外壳传的是 `transparent` 默认值 False + `background_color="#16181D"`**
   （`desktop/shell.py:181-198`，只有 `frameless=True, shadow=True`）⇒ 窗口完全不透明，
   DWM 材质会被 WinForms 的不透明 `BackColor` 盖住。
4. **pywebview 会在 `transparent=True` 时跳过它自己那两行非客户区处理**：
   `winforms.py:264-267`
   ```python
   if window.shadow and not window.transparent:
       ExtendFrameIntoClientArea(hwnd)
       DwmSetWindowAttribute(hwnd, 2, 2, 4)      # DWMWA_NCRENDERING_POLICY = DISABLED
   ```
   所以 `ExtendFrameIntoClientArea` + 属性 38 必须**由我们自己**在窗口 `shown` 之后补
   —— 好消息：`desktop/native/frame.py` 已经有一整套"拿到 HWND 后再补 DWM 属性"的基础设施
   （`_wait_for_window` / `install()` / `apply_dark_titlebar()`，`desktop/shell.py:224-234`），加这一个属性成本很低。
5. ⚠️ `transparent=True` 与当前的 `hidden=True` 会走 pywebview 的另一条分支
   （`winforms.py:777-787`：`hidden` 优先，`transparent` 的 Show/Hide hack 不生效），
   **这一组合必须实机验证**，不要仅凭源码下结论。

**代价与限制**

| 项 | 说明 |
| --- | --- |
| 兼容性 | Win11 22H2 起；Win10 用户只能"无材质"，需要降级到路径 B 或直接隐藏该设置行 |
| 改动面 | 要动 `desktop/shell.py`（`transparent=True`）+ `desktop/native/frame.py`（新增属性 38）+ `webui` 的半透明底（正文区仍要不透明，否则整页发糊） |
| 副作用 | 透明窗口会失去 `shadow=True` 带来的 DWM 投影/圆角路径（属性 2 不再设置），需自己用 `DWMWA_WINDOW_CORNER_PREFERENCE`(33) 补圆角；另外透明窗口在部分远程桌面/虚拟机下会变黑 |
| 性能 | DWM 自己合成，GPU 开销可忽略；但正文区每帧要透出壁纸，滚动时采样面积大 |
| 调试 | `DwmSetWindowAttribute` 返回 `S_OK(0)` 才算成功；务必像 `frame.py:250-257` 那样**读 HRESULT 并记日志**，不要假报成功 |

### 5.3 路径 B：纯前端 CSS（模糊 / 半透明）

**现状**：网页端已实现（见 5.1 末尾），但**只能糊页内层**。
`backdrop-filter` 在 Chromium 里模糊的是**合成器里它背后的那些层**；一个不透明窗口的"背后"没有桌面，
所以 CSS 永远糊不到壁纸 —— 现在的效果实际上是"半透明玻璃卡片叠在页面底色上"。

要做到"看得见桌面"，仍需路径 A 的第 2 步（`transparent=True`）。而**即使窗口透明了，CSS 依然糊不到桌面**：
WebView2 的透明区域由宿主（WinForms）透出，桌面不在 WebView2 的合成树里。
所以：

* 路径 B 单独用 ⇒ **半透明真、模糊假**（能透出桌面但不糊）。
* 路径 A + 路径 B ⇒ **半透明真 + 桌面模糊真**（唯一能达到"云母/亚克力"观感的组合）。
* 路径 A 单独用 ⇒ 材质真，但页面若有不透明底色，效果等于没有。

**代价与限制**

| 项 | 说明 |
| --- | --- |
| 依赖 | 零 OS 依赖，Win10/Win11 一致，WebView2 支持 `backdrop-filter`（Chromium 内核） |
| 现有参数 | glass：`blur 26px / saturate 165% / opacity .62`；acrylic：`blur 16px / saturate 150% / opacity .80` + `inset 0 1px 0 rgba(255,255,255,.16)`；mica：`blur 0 / opacity 1` + SVG `feTurbulence` 底噪（`webui/css/variables.css:23-28`） |
| 性能 | `backdrop-filter` 会强制提升为独立合成层；大面积的 26px 模糊在滚动时明显掉帧（尤其集显 + 高分屏） |
| 坑 | `.fx-noise::before` 用了 `opacity: 0` 再由 JS 点亮（`style.css:158-164`），如果 JS 没跑到，云母底噪会缺失；三档之间只改 4 个 CSS 变量，容易在别处漏用 `--fx-blur` |

### 5.4 不建议的第三条路（记录用）

`user32!SetWindowCompositionAttribute` + `ACCENT_ENABLE_BLURBEHIND`（Win7+ 半公开）/ `ACCENT_ENABLE_ACRYLICBLURBEHIND`（Win10 1803+）。
优点：Win10 也能有模糊。缺点（已知问题，不是猜测）：`ACCENT_ENABLE_ACRYLICBLURBEHIND` 在拖动窗口时有强烈的每帧重绘延迟
（微软自己的反馈中心长期挂着这个 bug），`ACCENT_ENABLE_BLURBEHIND` 则只是简单高斯且不支持色调。
网页端若追求"全平台一致 + 好维护"，**优先路径 A（Win11）→ 回退路径 B**，把这条留作最次选。

---

## 6. 托盘右键菜单

### 6.1 原版（`.ToolsGCP/modules/pymodels/ui/tray_menu.py`）

顺序（上→下，`make_tray_menu`，`:123-147`）：

| # | 图标枚举 | 语言段/键 | 简中 | 繁中 | English | 回调 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `FIF.HOME` | `nav.show_main_window` | 呼出主窗口 | 呼出主視窗 | Show Main Window | `handlers["home"]` → `main_window.show_main_window` |
| 2 | `FIF.SEARCH` | `nav.show_search_box` | 呼出搜索框 | 呼出搜尋框 | Open Search Box | `handlers["search"]` → `show_search_box` |
| 3 | `FIF.ROBOT` | `nav.show_ai_search` | 呼出AI | 呼出AI | Open AI | `handlers["ai"]` → `show_ai` |
| 4 | — | — | **分隔线**（`addSeparator()`） | | | — |
| 5 | `FIF.EMBED` | `nav.exit` | 退出 | 退出 | Exit | `handlers["exit"]` → `quit_app` |

* 文案段名是 **`nav`**（`language_manager.get_text("nav", key)`，`:131`）。
* 图标尺寸 `ICON_SIZE = 14`；图标必须走 `themed_icon(icon, 14)`，**不能**用 `FIF.XXX.icon()`
  （后者在建菜单那一刻把颜色定死，切主题后看不见，`:5`、`:116-120`）。
* 视觉常量（`:16-27`，desktop 侧要对齐这组数）：
  `MENU_RADIUS = 12`、`MENU_PADDING = 6`、`ITEM_HEIGHT = 30`、`ICON_SIZE = 14`、
  `ICON_LEFT = 10`、`TEXT_LEFT = 30`、`ITEM_RIGHT_PADDING = 10`、`ITEM_MIN_WIDTH = 92`。
* 两条"必须"：
  1. 圆角三件套 = `FramelessWindowHint` + `WA_TranslucentBackground` + 样式表 `border-radius`，少一条退化成直角（`:3-4`）。
  2. **不要**调 `setContextMenu()`，改用 `activated(Context)` 自己弹 —— Windows 会把 `QMenu` 转成原生 HMENU，
     圆角和悬停底色全失效（`ui/main_window.py:982-984`）。
* 弹出位置（`main_window.py:995-1019`）：拿 `tray_icon.geometry()`，菜单水平居中于图标；
  图标在屏幕下半边 → 菜单往上弹（`y = geometry.top() - size.height() - 6`），否则往下。
  弹之前先 `menu.refresh_theme()`。
* 双击托盘图标 = `show_main_window()`（`main_window.py:988-993`）。

### 6.2 新版外壳现状（`desktop/native/tray.py` + `traymenu.py`）—— 供 desktop 侧核对

* 结构与顺序**已与原版一致**（`tray.py:338-367`）：`home / search / ai / ──── / exit`，
  文案键同为 `show_main_window / show_search_box / show_ai_search / exit`（`:351-366`）。
* 用的是**自绘圆角菜单**（`traymenu.py`，`_CLASS_NAME = "ToolsGCP_TrayMenu"`），
  常量按原版复刻：圆角 12 / 行高 30 / 图标 14 / 悬停圆角 8（`tray.py:341-344`、`traymenu.py:32` 区）。
* 图标不用 PNG 文件，用 GDI+ 现画 14×14 线稿：`MENU_ICON_KEYS = ("home", "search", "ai", "exit")`
  （`tray.py:379-383`），注释明确写"按原版 `FIF.HOME / SEARCH / ROBOT / EMBED` 各画一个"。
* 兜底：自绘菜单抛异常 → 回退系统 `TrackPopupMenu`（`tray.py:369-377`），
  菜单 ID `MENU_ID_HOME = 1001`、`MENU_ID_SEARCH = 1002`（`tray.py:29-30`）。
* **核对要点（两条容易走偏的）**：
  1. 第 3 项原版图标是 `FIF.ROBOT`（机器人），不是 `FIF.SEARCH` 或 `FIF.CHAT`；
     第 5 项是 `FIF.EMBED`（箭头出框），不是 `FIF.CLOSE`/`FIF.POWER`。
  2. 原版 `ITEM_MIN_WIDTH = 92` 是**最小宽**，实际宽度跟最长文案走；三语文案长度不同，菜单宽度会随语言变。

---

## 7. 未能确认 / 存疑（不要当结论用）

1. **`transparent=True` + `hidden=True` 在 pywebview 6.2.1 上的真实行为**：源码上 `hidden` 分支先命中
   （`winforms.py:777-787`），透明所需的 Show/Hide hack 不会执行，`DefaultBackgroundColor` 是否仍生效
   **未实测**。要落地第 5 节的路径 A，必须先在真机验证这一步。
2. **`DWMWA_SYSTEMBACKDROP_TYPE = 38` 在 Win11 21H2 上的表现**：文档说 22H2 起支持，21H2 只能退回
   1029；本机 Windows 版本未核对，未实测。
3. **`edgechromium.py:106-114` 的 `DefaultBackgroundColor`**：只确认了"传透明色"这一句，
   没有跟踪它在透明模式下再被谁覆盖；网页端若发现桌面透不出来，先查这里。
4. **网页端 `.range` 的 `max-width: 150px` 是否有其它行共用**：`components.css:191-199` 的 `.range-wrap/.range/.num-input/.unit`
   是**通用**类，`app.js` 里至少有 2 个 slider 行（下载限速、启动动画时长）在用。
   改宽要按行区分，不能直接改全局 —— 具体还有哪些行在用，**未逐条核对**。
5. **`webui/js/app.js` 的 `sections` 里 `download` 板块的 `speedOn` 变量**：
   只确认了它来自 `draft.download_speed_limit_enabled`（`app.js:2207`），
   有没有别的行复用它、以及 `visible` 是 `v-if` 还是 `v-show`（涉及"隐藏 vs 卸载"语义），**未逐行核对**。
6. **原版 `settings/interface.py` 的设置搜索索引**是否收录了「搜索源/下载源/下载限速」这几行：
   只确认了它会把 ComboBox 的选项文字也收进去（`interface.py:60-87` 的注释），
   具体每行的收录结果**未展开核对**。
7. 本册**没有**核对原版 `deploy_interface.py` 的 `Ctrl+左键` 在 Windows 上的实际静默打开效果
   （`utils/url_open.py` 未读），只按代码调用链描述。
