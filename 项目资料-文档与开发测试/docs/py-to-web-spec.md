# ToolsGCP PyQt 原版规格提取（供 webui 对齐）

> 目的：把**原 PyQt5 桌面版**的既有行为逐条固化下来，作为 `webui/`（Vue3 + 原生 JS）对齐依据。
> 所有结论都带 `文件:行号` 证据与关键代码片段。凡是**没能确认**的地方单列在 §7，不猜测。

---

## 0. 阅读须知（先看这段，能省很多返工）

### 0.1 谁才是"原版"

| 角色 | 位置 |
|---|---|
| 原版入口（Qt5） | `legacy/ToolsGCP.pyw.qt5`（223 行；`QApplication` / `AppUserModelID` / 启动画面都在这里） |
| 原版业务与界面 | `.ToolsGCP/modules/pymodels/`（约 **3.84 万行** `.py`，不含 `.pyc`） |
| 现入口（pywebview 壳） | `ToolsGCP.pyw`（263 行，只做装配，**不含业务**） |

`.pyc` 全部忽略，本文只依据 `.py` 与语言 JSON。

### 0.2 网页端真正被加载的文件（很重要）

`webui/index.html:1422-1424`：

```html
<!-- 主逻辑：经典脚本（非 ES Module），与 index.html 模板直接配合 -->
<script src="/static/js/icons.js"></script>
<script src="/static/js/app.js"></script>
```

→ **只有 `webui/js/app.js`（经典脚本）与 `webui/js/icons.js` 被加载**。
`webui/js/main.js`、`webui/App.vue`、`webui/pages.js` 都是 ES Module / 组件形态，没有被 `index.html` 引用；`UI_FIX_ROUND_12.md（已清理，见 git 历史）:247-248` 明确写了"**`pages.js` 是死文件**（没有任何地方引用它）"。当时的组件文件 `webui/js/components/{Card,Combo,Toast,Tooltip}.js` 与 `webui/js/core/*`（连同 main.js/pages.js/App.vue 一起，已在 2026-10-31 清理中删除）同样**只有 `app.js` 里的等价实现参与运行**（`app.js` 自己定义了 `t()/flattenI18n/term/bridge/...`，见 `app.js:114-158`）。

### 0.3 本文快照（webui 正在被并行修改，务必注意）

| 文件 | md5 | 行数 | 时间 |
|---|---|---|---|
| `webui/js/app.js` | `eb79670a14205696b5aff47a2f357a3a` | 3569 | 2026-10-22 23:48:56 |
| `webui/index.html` | `da3bb271a3ae756dc0101cf34f2c6934` | 1426 | 2026-10-21 23:45:58 |
| `webui/css/layout.css` | `64d35dd4043b21eea7947f144312e1d7` | 501 | 2026-10-22 23:48:37 |
| `.ToolsGCP/modules/pymodels/interfaces/home_interface.py` | `0e317f9a71f34b4881a5903633e5a742` | 716 | — |
| `.ToolsGCP/modules/pymodels/constants.py` | `25324d5edd51cd96f2916eca330804c9` | 256 | — |

⚠️ 审计过程中 `app.js` 在 23:46–23:48 之间被改过多次（行数 3539 → 3550 → 3569）。§6 的网页端行号取自上表快照，**以锚点文本（函数名 / 键名）为准**；如果对不上，`grep` 锚点。

### 0.4 原版已确认的缺陷 / 陷阱（网页端不要照抄）

1. **`SLIDE_DEFAULT_ASPECT` 未定义** → 海报目录为空时首页会抛 `NameError`。
   `home_interface.py:333`（注释）与 `home_interface.py:339`（使用）是**全代码库仅有的两处**（`grep` 全 `pymodels`）。`_discover_posters()` 返回空列表时 `_target_aspect()` 会执行到这一行。
2. **`accent_color = "blue"` 的实际色值是青色 `#009FAA`**，不是品牌蓝 `#4F7BF7`（`interfaces/settings/theme.py:13` vs `:26`）。
3. **`ui_font_desc` 文案与实现不符**：语言文件写"选「跟随系统」恢复默认"（`set_language.json` 的 `ui_font_desc`），但字体下拉框**已经删掉"跟随系统"这一项**（`cards_ui.py:76`）。
4. **多个键用了但不在 `DEFAULT_SETTINGS` 里**：`ui_font_family`（`cards_ui.py:311`、`main_window.py:173`）、`ai_reply_mode`（`cards_ai.py:124,144`，`constants.py:236` 只留了一句注释没留键）、`customize_interests` / `customize_onboarded`（`customize_interface.py:37-38`）。
5. **`settings_manager` 会写"迁移标记"键**：`_migrated_show_github_default`、`_migrated_splash_default`、`_migrated_ui_defaults`（`settings_manager.py:65-83`；只有第一个在 `DEFAULT_SETTINGS` 里）。
6. 语言切换是**重启才会生效**（见 §3.6），不是重建界面。

---

## 1. 首页海报 / 轮播尺寸逻辑

文件：`.ToolsGCP/modules/pymodels/interfaces/home_interface.py`（716 行），常量依赖 `.ToolsGCP/modules/pymodels/constants.py:72` 的 `IMAGES_DIR`。

### 1.1 常量（`home_interface.py:25-43`）

```python
# 轮播图配置
SLIDE_COUNT = 5          # 圆点分页最多 5 个
SLIDE_INTERVAL_MS = 3000  # 每 3 秒换下一张
SLIDE_MIN_HEIGHT = 200    # 轮播（图片区）的最低高度
SLIDE_MAX_HEIGHT = 460    # 上限 —— 窗口拉得很宽时（2560）别让一张海报把整页顶下去
SLIDE_PAGER_ROW_HEIGHT = 12  # 圆点分页那一行的兜底高度（PipsPager 的 sizeHint 不可信）

WHEEL_STEP = 120          # 攒够 120 单位（普通滚轮一格）才翻一张
WHEEL_DEBOUNCE_MS = 180   # 一次翻页后这段时间内不再翻页

POSTERS_DIR = os.path.join(IMAGES_DIR, "posters")            # .ToolsGCP/images/posters/
POSTER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
```

首页内容区布局（`home_interface.py:599-607`）：`contentsMargins = 30,24,30,30`、`spacing = 18`，轮播是第一个 widget。

### 1.2 海报发现：**扫目录 + 数字排序 + 自动补空**

`home_interface.py:46-78`：

```python
def _poster_sort_key(name: str) -> tuple:
    stem = os.path.splitext(name)[0]
    digits = "".join(ch for ch in stem if ch.isdigit())
    return (int(digits) if digits else 9999, stem.lower())      # 必须按数字排，否则 poster10 排到 poster2 前

def _discover_posters() -> list:
    try:
        names = os.listdir(POSTERS_DIR)
    except OSError:
        return []
    found = [name for name in names
             if not name.startswith(".") and name.lower().endswith(POSTER_EXTENSIONS)]
    found.sort(key=_poster_sort_key)
    return [os.path.join(POSTERS_DIR, name) for name in found]

SLIDES = [{"image": path, "title": "", "subtitle": ""} for path in _discover_posters()[:SLIDE_COUNT]]
SLIDES += [{"image": "", "title": "", "subtitle": ""}
           for _ in range(max(0, SLIDE_COUNT - len(SLIDES)))]     # 不足 5 张补空占位
```

要点：
- 排序是**按文件名里的数字**，不是字符串；
- 认 5 种扩展名（大写 `.PNG` 也算，走 `name.lower()`）；
- **不足 5 张会补空占位**（空块也画一块带边框的底色，见 `SlideCard.apply_theme` `:158-171`），所以轮播**永远是 5 页**；
- 标题/副标题**全部为空字符串**（`SLIDES` 里没填），因此 `SlideCard` 里两个文字标签实际 `setVisible(False)`（`:100-110`）。

当前仓库里的实际海报（读 PNG IHDR 得到，宽度×高度）：

| 文件 | 像素 | 高/宽 |
|---|---|---|
| `poster1.png` | 1916×821 | 0.4285 |
| `poster2.png` | 2172×724 | **0.3333** |
| `poster3.png` | 2172×724 | **0.3333** |
| `poster4.png` | 1974×797 | 0.4037 |
| `poster5.png` | 1974×797 | 0.4037 |

→ **目标高宽比 = min = 0.33333**（见下）。

### 1.3 高度计算（核心）

**轮播区只有一个高度，取"最扁的那张海报"的高宽比**（`home_interface.py:325-340`）：

```python
def _target_aspect(self) -> float:
    aspects = [slide.image_aspect() for slide in self._slides]
    aspects = [a for a in aspects if a > 0]
    if not aspects:
        return SLIDE_DEFAULT_ASPECT        # ⚠️ 这个常量在本代码库里没有定义（§0.4-1）
    return min(aspects)
```

理由（注释 `:326-334`）：容器取"最扁"的比 → 用 `KeepAspectRatio` 缩放时**每张海报都能完整放下**；而且固定一次，避免每 3 秒按当前页重排导致整页上下跳。

`image_aspect()` 定义（`home_interface.py:125-130`）：`pixmap.height() / pixmap.width()`，无图返回 `0.0`（图片只从磁盘读一次，`:117-123`）。

**图片区高度**（`SlideCard.preferred_height`，`:132-149`）：

```python
aspect = self.image_aspect()
if aspect <= 0: return SLIDE_MIN_HEIGHT
return max(SLIDE_MIN_HEIGHT, min(SLIDE_MAX_HEIGHT, int(width * aspect)))
```

**整块轮播高度 = 图片区高度 + 圆点行高度**（`BannerCarousel.preferred_height`，`:362-373`）：

```python
image_h = max(SLIDE_MIN_HEIGHT, min(SLIDE_MAX_HEIGHT, int(width * self._aspect)))
return image_h + self._pager_row_height()
```

**圆点行高度**（`:342-360`）：实测 `self.pager.height()`，测不到用 `SLIDE_PAGER_ROW_HEIGHT = 12`，再 **加上布局 spacing（10）** → 正常是 `12 + 10 = 22`：

```python
measured = int(self.pager.height())
if measured <= 0: measured = SLIDE_PAGER_ROW_HEIGHT
spacing = int(self.layout().spacing())     # layout.setSpacing(10)，见 :282
return measured + spacing
```

**随窗口宽高变化**：用 Qt 的 height-for-width 协议接进布局，宽度变了就重算并**固定高度**（`:151-156`、`:375-393`）：

```python
def hasHeightForWidth(self) -> bool: return True
def heightForWidth(self, width: int) -> int: return self.preferred_height(width)

def _sync_height(self):                     # resizeEvent 里调
    height = self.preferred_height()
    image_h = max(SLIDE_MIN_HEIGHT, height - self._pager_row_height())
    if self.stack.height() != image_h: self.stack.setFixedHeight(image_h)
    if height != self.height():        self.setFixedHeight(height)
```

`BannerCarousel` 的高度策略是 `QSizePolicy.Preferred × Fixed`（`:296`）。

**数值示例**（目标比 0.33333，spacing 10，pager 12）：
- 内容宽 1172px → 图片区 `min(460, floor(1172×0.33333)=390)` = **390**，整块 = **412**；
- 内容宽 700px → `floor(233)` → 233 + 22 = **255**；
- 内容宽 400px → `floor(133) < 200` → 夹到 **200** + 22 = **222**；
- 内容宽 ≥ 1380px → 夹到 **460** + 22 = **482**（上限生效）。

### 1.4 图片缩放与"留白填充"

- **完整显示、绝不裁切**（`_scaled_for_current_size`，`:249-263`）：
  ```python
  scaled = pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
  ```
  代码注释明确否定了"填满式裁切"（`KeepAspectRatioByExpanding`），实测会切掉 17~22% 的海报文字。
- 绘制在几何中心：`x = (w - scaled.w)//2`、`y = (h - scaled.h)//2`（`:191-193`）。
- **圆角裁切**：`QPainterPath().addRoundedRect(self.rect(), radius=12)`（`:186-189`，半径来自 `apply_theme`）。
- **留白用海报自己的边缘像素拉伸铺满**（`_fill_letterbox` / `_edge_strips`，`:202-247`）：
  - 上下留白：取海报**第 0 行**与**最后一行**像素，横向 `scaled(width, y)`；
  - 左右留白：取海报**第 0 列**与**最后一列**像素，纵向 `scaled(x, height)`；
  - 结果按当前控件尺寸缓存（`:220-223`），`resizeEvent` 里作废（`:265-269`）。
- 空白占位的底色（`:158-171`）：深色 `rgba(255,255,255,0.05)` + 边框 `rgba(255,255,255,0.08)`；浅色 `rgba(0,0,0,0.035)` + `rgba(0,0,0,0.06)`；圆角 12。

### 1.5 翻页

- **自动**：`QTimer` 间隔 3000ms（`:310-312`），`next_slide()` 取模回绕（`:396-398`）。
- **只在页面可见时跑**：`showEvent → start()`、`hideEvent → stop()`（`:463-477`）。
- **圆点点击**：`_on_pager_clicked → go_to(index, restart_timer=True)`（`:423-424`），手动操作后**重置计时**（`:411-413`），否则刚点完就被自动翻走。
- **滚轮翻页**（`:427-457`）：
  - `angleDelta().y()`；为 0 时用 `pixelDelta().y() * 4` 估算（触摸板）；
  - 只有 1 张时不抢滚轮（`event.ignore()`，交回外层页面滚动）；
  - 累加 `_wheel_accum`，`abs(accum) >= WHEEL_STEP(120)` 才翻一张，然后**只扣掉一格**并把 `_wheel_accum` 清 0、进 180ms 冷却（`_wheel_cooldown`）；
  - 方向：`delta < 0`（下滚）= 下一张；
  - 事件必须 `accept()`，否则外层页面会跟着滚。
- `go_to(index)` 用 `int(index) % self._count`（`:404-409`），越界安全。

### 1.6 指示点（PipsPager）

`home_interface.py:298-308`：

```python
self.pager = PipsPager(self)
self.pager.setPageNumber(self._count)      # _count = max(1, len(SLIDES)) → 恒为 5
self.pager.setVisibleNumber(self._count)   # 显示 5 个点
self.pager.currentIndexChanged.connect(self._on_pager_clicked)
```

- 页数 = `max(1, len(SLIDES))`（`:278`），因为 `SLIDES` 补齐到 5，所以**恒为 5 个点**；
- 同步用 `blockSignals(True)` 防自触发（`:415-421`）；
- 圆点行水平居中：`addStretch(1) + pager + addStretch(1)`（`:299-308`）。

### 1.7 可直接翻译成 JS 的伪代码

```js
// ---------- 常量 ----------
const SLIDE_COUNT = 5, SLIDE_INTERVAL_MS = 3000;
const SLIDE_MIN_HEIGHT = 200, SLIDE_MAX_HEIGHT = 460, SLIDE_PAGER_ROW_HEIGHT = 12;
const WHEEL_STEP = 120, WHEEL_DEBOUNCE_MS = 180;
const EXT = ['.png', '.jpg', '.jpeg', '.webp', '.bmp'];

// ---------- 发现海报（后端给目录清单时）----------
function posterSortKey(name) {
  const stem = name.replace(/\.[^.]+$/, '');
  const digits = (stem.match(/\d/g) || []).join('');
  return [digits ? parseInt(digits, 10) : 9999, stem.toLowerCase()];
}
// slides = 排序后前 5 张；不足 5 张补 {image:''} 空占位 → 长度恒为 5

// ---------- 目标高宽比 ----------
// slideAspects[i] = naturalHeight / naturalWidth（图片 onload 后量），空占位不计
function targetAspect(aspects) {
  const valid = aspects.filter(a => a > 0);
  if (!valid.length) return null;        // ⚠️ 原版这里是未定义常量会抛异常；网页端应返回 null 并保持 MIN 高度
  return Math.min(...valid);             // 最扁的那张
}

// ---------- 高度 ----------
function pagerRowHeight(pagerElHeight, layoutSpacing) {
  return (pagerElHeight > 0 ? pagerElHeight : SLIDE_PAGER_ROW_HEIGHT) + layoutSpacing; // 12 + 10
}
function carouselHeight(containerWidth, aspect, pagerRowH) {
  if (!aspect || containerWidth <= 0) return SLIDE_MIN_HEIGHT + pagerRowH;
  const img = Math.max(SLIDE_MIN_HEIGHT, Math.min(SLIDE_MAX_HEIGHT, Math.floor(containerWidth * aspect)));
  return img + pagerRowH;
}
// resize 时：container.style.height = carouselHeight(container.clientWidth, aspect, 22) + 'px'

// ---------- 图片摆放 ----------
// 容器：overflow hidden，圆角 12，object-fit: contain（完整显示不裁切），居中
// 原版额外做"边缘像素铺满留白"：上下用第 0 行/最后一行横向拉伸，左右用第 0 列/最后一列纵向拉伸
// CSS 用 3 层背景或 canvas 都能复刻；至少不要用 cover（会裁掉 17~22%）

// ---------- 翻页 ----------
let index = 0, timer = 0, wheelAcc = 0, wheelCooldownUntil = 0;
const next = () => goTo(index + 1);
const prev = () => goTo(index - 1);
function goTo(i, restartTimer) {
  index = ((i % 5) + 5) % 5;                       // 取模，负数也安全
  render(); syncPips();
  if (restartTimer && timer) { clearInterval(timer); timer = setInterval(next, SLIDE_INTERVAL_MS); }
}
function onPipClick(i) { goTo(i, true); }
function onWheel(e) {                              // 只在轮播图上监听
  if (count <= 1) return;                          // 不抢滚轮
  const now = Date.now();
  if (now < wheelCooldownUntil) { e.preventDefault(); return; }
  const dy = e.deltaY || 0;                        // 原版 pixelDelta 会 ×4 折算
  wheelAcc += dy;
  if (Math.abs(wheelAcc) >= WHEEL_STEP) {
    if (dy > 0) next(); else prev();               // 下滚 = 下一张
    wheelAcc = 0; wheelCooldownUntil = now + WHEEL_DEBOUNCE_MS;
    goTo(index, true);
    e.preventDefault();
  }
}
function onShow() { if (count > 1 && !timer) timer = setInterval(next, SLIDE_INTERVAL_MS); }
function onHide() { clearInterval(timer); timer = 0; }   // 离开页面必须停表
```

网页端现有实现（供对照）：`webui/js/app.js:1179`（`targetAspect`）、`:1203`（`discoverPosters`）、`:1222`（`updateCarouselHeight`）、`:1240`（`carouselWheel`）、常量 `:42`；模板 `webui/index.html:165-178`；CSS `webui/css/layout.css:93-108`（`.carousel` 第 93-97 行 `min-height:200px; max-height:460px`；`.slide img` 第 104 行 `object-fit: contain`）。

---

## 2. 设置页完整结构

### 2.1 默认设置项（键 / 默认值 / 类型）

唯一真源：`.ToolsGCP/modules/pymodels/constants.py:156-256` 的 `DEFAULT_SETTINGS`。
读盘合并与类型修正：`core/settings_manager.py:20-93`；单键写入：`update_setting()` `:105-116`（每次改都落盘 + 记 OP 日志；测试可用 `TOOLSGCP_NO_SETTINGS_WRITE=1` 只改内存）。

| # | 键 | 默认值 | 类型 | 行号 | 备注 |
|---|---|---|---|---|---|
| 1 | `theme` | `"跟随系统"` | str | 157 | 取值：`跟随系统`/`浅色主题`/`深色主题` |
| 2 | `accent_color` | `"blue"` | str | 159 | 取值：`blue`/`purple`/`orange` |
| 3 | `language` | `"跟随系统"` | str | 160 | 取值：`跟随系统`/`简体中文`/`繁體中文`/`English` |
| 4 | `license_key` | `""` | str | 161 | |
| 5 | `notify_enabled` | `True` | bool | 162 | |
| 6 | `last_search` | `""` | str | 163 | 写了但**不再回填**（`search_interface.py:97,1250`） |
| 7 | `startup_with_windows` | `False` | bool | 164 | |
| 8 | `minimize_to_tray` | `True` | bool | 165 | |
| 9 | `default_page` | `"搜索"` | str | 166 | 取值同 `common.PAGE_ORDER` |
| 10 | `close_mode` | `"彻底退出"` | str | 167 | 另一取值 `"隐藏到托盘中"` |
| 11 | `open_settings_on_restart` | `False` | bool | 168 | 切换语言时被置 True |
| 12-15 | `dev_mode_enabled` / `dev_mode_admin` / `dev_mode_verify_time` / `dev_mode_key` | `False` / `""` / `""` / `""` | bool/str×3 | 169-172 | |
| 16-17 | `debug_info_enabled_Galen563` / `..._Cyric373` | `False` / `False` | bool | 173-174 | 键名带管理员名，见 `get_debug_info_key()` `:118-120` |
| 18 | `search_source` | `""` | str | 175 | 老配置的"国内源"会被迁到 `Github`（`cards_download.py:474-484`） |
| 19 | `download_source` | `""` | str | 176 | 同上 |
| 20 | `download_speed_limit_enabled` | `False` | bool | 177 | |
| 21 | `download_speed_limit` | `100` | int（夹 1..300，非法回 100） | 178 | `settings_manager.py:50-59` |
| 22 | `deploy_mode` | `False` | bool | 179 | False=导出模式 / True=部署模式 |
| 23 | `splash_screen_enabled` | `False` | bool | 180 | 默认关（迁移强制改一次，`settings_manager.py:72-75`） |
| 24 | `splash_screen_duration` | `2` | int（夹 1..5） | 181 | `settings_manager.py:34-43` |
| 25 | `theme_effect` | `"mica"` | str | 184 | 取值 `mica`/`glass`/`acrylic`；**原版 PyQt 界面没有这一行**（见 §2.5） |
| 26 | `nav_hover_expand` | `False` | bool | 186 | **原版界面无此开关** |
| 27 | `toast_position` | `"top_right"` | str | 188 | 取值 `top_right`/`bottom_right`/`top_left`/`bottom_left`/`top`；**原版界面无此项** |
| 28 | `auto_search` | `True` | bool | 189 | |
| 29 | `hotkey_enabled` | `True` | bool | 190 | |
| 30 | `hotkey_search` | `"Ctrl+Q"` | str | 191 | |
| 31 | `hotkey_ai` | `"Ctrl+Alt+G"` | str | 195 | 注释说明**不能**用 Caps Lock 做主键（VK_CAPITAL 注册必失败） |
| 32 | `search_card_size` | `"medium"` | str | 197 | 取值 `small`/`medium`/`large`；**设置页已删除该项**，但 `main_window.py:209-210` 仍读 |
| 33 | `search_view` | `"tile"` | str | 199 | `tile`（4 列大卡）/`grid`（6 列小卡） |
| 34 | `search_show_github` | `True` | bool | 201 | |
| 35 | `_migrated_show_github_default` | `True` | bool | 204 | 内部一次性迁移标记 |
| 36 | `search_show_view_switch` | `True` | bool | 206 | |
| 37 | `plugin_view` | `"grid"` | str | 208 | `grid`/`list` |
| 38 | `resource_source` | `"cloud"` | str | 210 | `cloud`/`local` |
| 39 | `local_resource_dir` | `""` | str | 212 | 留空用程序自带 `.ToolsGCP` |
| 40 | `update_channel` | `"all"` | str | 217 | `all`/`stable`/`beta` |
| 41-42 | `api_key` / `api_key_enc` | `""` / `""` | str | 218-219 | `api_key_enc` 是 DPAPI 密文；读写在 `settings_manager.py:123-143` |
| 43 | `model_name` | `""` | str | 220 | |
| 44 | `ai_provider` | `"deepseek"` | str | 224 | 只决定下拉框默认值 |
| 45 | `api_base` | `"https://api.deepseek.com/v1"` | str | 225 | |
| 46 | `ai_enabled` | `False` | bool | 226 | |
| 47 | `ai_sidebar_mode` | `False` | bool | 229 | 仅 `ai_enabled` 时露行 |
| 48-50 | `limit_token_output` / `min_token` / `max_token` | `False` / `0.5` / `4096` | bool/float/int | 230-232 | |
| 51 | `ai_context_rounds` | `0` | int | 235 | 0=整个会话；10/20/30=最近 N 轮 |
| 52 | `gcp_ai_agent_enabled` | `False` | bool | 243 | 内置插件开关 |
| 53 | `gcp_ai_agent_tools_off` | `[]` | list | 246 | 只记**被关掉**的工具 |
| 54 | `gcp_plugin_maker_enabled` | `False` | bool | 249 | |
| 55 | `gcp_plugin_maker_options` | `{}` | dict | 255 | |

**运行时才写、不在 `DEFAULT_SETTINGS` 里的键**（网页端做兜底时要补上）：

| 键 | 默认（代码里的取值兜底） | 类型 | 证据 |
|---|---|---|---|
| `ui_font_family` | `""` → 用 `dark_default_family()` | str | `cards_ui.py:311`、`main_window.py:170-175`、`utils/fonts.py:14` |
| `ai_reply_mode` | `"standard"` | str | `cards_ai.py:124,144`、`ai_chat_panel.py:4604` |
| `customize_interests` | `[]` | list[str] | `customize_interface.py:37` |
| `customize_onboarded` | `False` | bool | `customize_interface.py:38` |
| `_migrated_splash_default` | — | bool | `settings_manager.py:72-75` |
| `_migrated_ui_defaults` | — | bool | `settings_manager.py:78-83` |

配置文件位置：`DATA_DIR/toolsgcp_config.json`（`settings_manager.py:12-18`；`DATA_DIR = USER_DATA_ROOT/config`，`constants.py:113`）。
`USER_DATA_ROOT` 由 `core/data_root.py` 解析（`constants.py:108-111`）：优先级 `ToolsGCP.json` 指针 → 用户主目录 `\.ToolsGCP`。

### 2.2 板块顺序（左侧列表 = 页面从上到下，逐项对应）

`interfaces/settings/interface.py:303-322`：

```python
return [
    ("appearance", "appearance", [self._create_appearance_card]),
    ("startup",    "startup",    [self._create_startup_card]),
    ("search",     "search_settings", [self._create_search_card]),
    ("hotkey",     "hotkey_section",  [self._create_hotkey_card]),
    ("download",   "download",   [self._create_download_card]),
    ("functions",  "functions",  [self._create_function_card]),
    ("storage",    "storage_section", [self._create_storage_card]),
    ("ai",         "ai_section", [self._create_ai_card,
                                  self._create_api_key_card,
                                  self._create_model_calling_card]),
    ("dev",        "developer_functions", [self._create_dev_card]),
    ("about",      "about",      [self._create_about_card]),
]
```

- 共 **10 个板块**（`ai` 板块下 **3 张卡片**，其余 1 张）；
- 老键名别名：`api_key`/`model`/`api` → `ai`（`:325-329`）；
- 左侧列表 + 右侧内容**都是同一份定义**（`:268-271` 建页面，`:363-364` 建列表项），**顺序天然一致**；
- ⚠️ 单页结构：所有板块一次性建好，点左侧列表 = **滚动到锚点**（`_select_section` `:400-422`，动画 320ms `:449-470`），不是切页；
- 滚动时左侧高亮反向同步（`_sync_section_from_scroll` `:483-506`，判定偏移 60px）；
- 内容限宽 **880px** 居中（`_apply_content_width` `:508-522`）。

### 2.3 行模型（控件类型 / 缩进 / 描述 / 提示）

两条实现路线并存 —— 网页端要按"统一行模型"还原：

**(A) `SettingRow`（规范行，只有"外观"卡片在用）** `interfaces/settings/widgets.py:81-139`

```python
SettingRow(title, control=None, desc="", hint="", tip="", control_width=CONTROL_WIDTH)
# 左：标题 + 可选 ⓘ(TipIcon, tip 文本) + 可选 desc 副说明（第二行小字）
# 右：控件，固定宽 200（CONTROL_WIDTH；传 control_width=None 则用控件原始宽度 —— 开关类就是这么用的）
# 行高：有 desc → 60，无 desc → 48
# hint → 鼠标悬浮在标题上 300ms 弹 tooltip（ToolTipFilter TOP）
```

> **"是否带描述"的准确答案**：本版本的设置页里**没有任何一行用 `desc=`**（整个 `interfaces/settings/` 目录 `grep -n "desc="` 只命中 `widgets.py:3` 的文档注释），也就是说**原版所有设置项都只有"标题 + 悬浮提示（tip/hint）"，没有第二行常驻说明文字**；唯一的"第二行说明"在「存储」板块，由另一个类 `_PathRow(title, desc, tip, ...)` 提供（`cards_storage.py:39-67`，用到它的两行在 `:114-119`）。网页端有 `row.desc` + `.has-desc` 机制（`index.html:1105,1119`），比原版多一种表现，对齐时不要凭这个反推原版有描述行。

**(B) 其它卡片（下载/快捷键/功能/开发者/关于/AI）直接手搭 `QHBoxLayout`**：`BodyLabel(get_text(key))` 靠左 + `addStretch()` + 控件靠右；提示是 `QLabel("ⓘ")` + `setToolTip()`（`_make_tip_icon()`，`cards_ai.py:98-104`）；**缩进**用 `setContentsMargins(20, 0, 0, 0)`（`cards_hotkey.py:59`、`cards_download.py:295`）。

**(C) 卡片容器**：`SettingCard`（`widgets.py:170-204`）—— 行间画 1px 分隔线（`divider=False` 不画，外观卡就是 `divider=False`，`cards_ui.py:42`）；普通卡是 `SimpleCardWidget` + `QMargins(20,20,20,20)` + `layout.setSpacing(15)`。

尺寸 token（`interfaces/settings/theme.py:171-185`）：

| token | 值 |
|---|---|
| 内容最大宽 / 左右最小留白 | 880 / 30 |
| 板块间距 / 卡片间距 | 32 / 16 |
| 卡片内边距 / 圆角 | 20 / 10 |
| 行高（无描述 / 有描述） | 48 / 60 |
| 控件统一宽（`CONTROL_WIDTH`） | 200 |
| 左侧板块列表宽 | 196 |

### 2.4 逐板块行清单

> 图例：`S`=下拉框、`SW`=开关、`CB`=复选框、`SL`=滑块、`IN`=输入框、`BTN`=按钮、`HK`=快捷键框、`PATH`=只读路径行、`TXT`=纯文本/说明、`→`=缩进从属行。

#### ① 外观 `appearance`（`cards_ui.py:37-156`，`SettingCard(divider=False)` 无行分隔线）

| 顺序 | 行标题（语言键） | 控件 | 缩进 | 描述/tip | 证据 |
|---|---|---|---|---|---|
| 1 | 主题模式 `theme_mode` | S：跟随系统 / 浅色主题 / 深色主题 | — | tip=`theme_mode_desc` | `:44-52` |
| 2 | 组件配色 `accent_color` | S：蓝色 / 紫罗兰 / Claude橙（值 blue/purple/orange） | — | tip=`accent_color_desc` | `:54-63` |
| 3 | 语言 `language` | S：跟随系统 / 简体中文 / 繁體中文 / English | — | tip=`language_desc` | `:65-73` |
| 4 | 字体 `ui_font` | S：系统已安装字体（**无"跟随系统"项**，默认取 `dark_default_family()`，最多可见 14 项） | — | tip=`ui_font_desc` | `:75-91` |
| 5 | 启动动画 `splash_screen` | SW | — | tip=`splash_screen_tip` | `:93-100` |
| 6 | 启动动画时长 `splash_screen_duration` | SL(1–5) + IN(1–5) + "秒" | — | tip=`splash_screen_duration_tip`；**开关关时整行隐藏** | `:103-151`、`:409-422` |

#### ② 启动 `startup`（`cards_ui.py:159-238`）

| 顺序 | 行 | 控件 | 可见性 | 证据 |
|---|---|---|---|---|
| 1 | 开机自启动 `startup_with_windows` | SW（写注册表，失败回滚开关并弹错误） | 常显 | `:166-179`、`:248-261` |
| 2 | 启动时最小化到托盘 `minimize_to_tray` | SW + ⓘ | **仅"开机自启动"打开时可见**（整行隐藏） | `:181-205`、`:275-291` |
| 3 | 默认启动页面 `default_page` | S（顺序固定 `PAGE_ORDER`） | 常显 | `:207-236` |

`PAGE_ORDER = ["首页", "搜索", "定制页", "收藏", "部署", "设置"]`（`common.py:24`）—— 下拉框**顺序必须与它逐项对应**，因为回填用 `PAGE_ORDER.index(saved_page)`。

#### ③ 搜索 `search_settings`（`cards_hotkey.py:262-368`）

| 顺序 | 行 | 控件 | tip | 证据 |
|---|---|---|---|---|
| 1 | 自动搜索 `auto_search` | SW | `auto_search_tip` | `:271-292` |
| 2 | 显示 GitHub 按钮 `show_github_button` | SW | `show_github_button_tip` | `:294-315` |
| 3 | 在搜索页显示视图切换按钮 `show_view_switch` | SW | `show_view_switch_tip` | `:317-340` |
| 4 | 搜索页视图 `search_view_mode` | S：磁贴 tile / 网格 grid | `search_view_mode_tip` | `:342-366` |

#### ④ 快捷键 `hotkey_section`（`cards_hotkey.py:20-112`）

| 顺序 | 行 | 控件 | 缩进 | 证据 |
|---|---|---|---|---|
| 1 | 启用全局快捷键 `hotkey_enable` | SW + ⓘ | — | `:27-47` |
| 2 | 呼出搜索框 `hotkey_search` | HK + 左置注册状态小字 + 「恢复默认」BTN | **是**（margins 20） | `:53-97` |
| 3 | 呼出 GCP-AI `hotkey_ai` | 同上 | **是** | `:53-97` |
| 4 | 操作提示 `hotkey_hint` | TXT（灰字 11px） | **是** | `:105-109` |

默认值真源 `HOTKEY_DEFAULTS = {"search": ("hotkey_search","Ctrl+Q"), "ai": ("hotkey_ai","Ctrl+Alt+G")}`（`common.py:28-29`）。
总开关关闭 → 子行整体置灰（`:114-124`）；注册失败才显示红字（`:126+`）。

#### ⑤ 下载 `download`（`cards_download.py:161-334`，一张卡里两块，中间画 1px 分割线）

**资源来源块**（`:47-113`）：`SubtitleLabel("资源来源")` + 说明整段（`resource_source_tip`）→ 行「资源来源 `resource_source_mode`」S：云端 cloud / 本地 local → 行「资源目录 `local_dir`」IN + 「选择文件夹」BTN（**仅本地时可显**）→ 当前索引文件状态行 → **橙色临时提示** `local_dir_temp_notice` → 1px 分割线。

**下载块**：

| 顺序 | 行 | 控件 | tip | 证据 |
|---|---|---|---|---|
| 1 | 搜索源 `search_source` | S：`Github` + 4 个镜像站 | `github_mirror_hint` | `:171-195`、`constants.py:149-150` |
| 2 | 下载源 `download_source` | 同上下拉 | `github_mirror_hint` | `:197-220` |
| 3 | 更新下载渠道 `update_channel` | S：all/stable/beta | `update_channel_tip` | `:222-252` |
| 4 | 下载限速 `download_speed_limit` | CB + 右侧状态字（`100 MB/s` / `无限制`） | — | `:254-290`、`:337-342` |
| 5 | 限速 `limit_speed` | SL(1–300) + IN + "MB/s"，**缩进 20** | — | `:292-330` |

`SOURCE_OPTIONS = ["Github", "ghfast.top", "gh-proxy.com", "ghproxy.net", "gh.ddlc.top"]`（`constants.py:149-150`）。
限速未勾选 → **整行隐藏**（`:345-361`）；滑块/数字框接管滚轮"一格 ±1"（`:328-330`、`:384-396`）。

#### ⑥ 功能 `functions`（`cards_misc.py:55-143`）

| 顺序 | 行 | 控件 | 说明 | 证据 |
|---|---|---|---|---|
| 1 | GCP License Key `gcp_license_key` | IN + 「验证」BTN（PrimaryPushButton，宽 80） | 关键：`key == "Galen563-ToolsGCP"` → 弹可用密钥窗口；`key in VALID_GCP_KEYS` → 成功提示；否则无效 | `:62-95`、`:146-160` |
| 2 | 启用通知 `enable_notification` | SW | | `:97-109` |
| 3 | 关闭模式 `close_mode` | S：彻底退出 / 隐藏到托盘中 | tip=`close_mode_tip` | `:111-141` |

⚠️ 原版"功能"板块**没有**「侧栏鼠标靠近自动展开」「提示框位置」两行（`grep` 全 `pymodels`：`nav_hover_expand`/`toast_position` 只出现在 `constants.py:186,188` 与 `settings_manager.py:80-81`）。
`VALID_GCP_KEYS` / `DEV_KEYS` / `SPECIAL_KEYS` 定义在 `constants.py:128-142`。

#### ⑦ 存储 `storage_section`（`cards_storage.py:93-343`）

| 顺序 | 行 | 控件 | 证据 |
|---|---|---|---|
| 1 | 存储位置 `storage_location`（desc=`storage_location_desc`，tip=`storage_location_tip`） | 只读 PATH 框（吃掉剩余宽度，最小 280）+ 「更改」BTN | `:114-119` |
| 2 | 位置记录文件 `storage_pointer_file` | 只读 PATH 框 + 「恢复默认」BTN | 同卡 |
| — | 迁移进度条 + 进度提示（更改时弹确认框，迁移中显示 `ProgressBar`） | | `:94-98`、`cards_storage.py:1-13` 需求说明 |

#### ⑧ GCP-AI `ai_section`（3 张卡片）

**卡 1 `_create_ai_card`**（`cards_ai.py:51-96`）：

| 顺序 | 行 | 控件 | 可见性 | 证据 |
|---|---|---|---|---|
| 1 | 开启GCP-AI `ai_enable` | SW | 常显 | `:58-71` |
| 2 | 改用侧边栏 AI 单独界面 `ai_sidebar_mode` | SW + ⓘ | **仅 ai_enabled 时可见** | `:73-90` |
| 3 | 上下文范围 `ai_context_window` | S：整个会话(0) / 10 / 20 / 30 轮 | 常显 | `:147-173` |
| 4 | 回复模式 `ai_reply_mode` | S：标准 standard / 简洁 concise / 专业 professional | 常显（存的键不在默认表里） | `:106-129` |

**卡 2 `_create_api_key_card`**（`cards_ai.py:228-...`）：

| 顺序 | 行 | 控件 | 证据 |
|---|---|---|---|
| 1 | 服务商 `ai_provider` | S（可编辑性：清单 8 家，见 `core/ai/providers.py:23-111`；选中后自动填 base/model） | `:252-280` |
| 2 | 模型名称 `model_name` | EditableComboBox（可自己敲） | `:282-300` |
| 3 | 接口地址 `ai_api_base` | IN（占位 `https://api.deepseek.com/v1`） | `:302-318` |
| 4 | API Key `api_key_section` | IN（密码态）+ 「显示/隐藏」「清空」「保存」BTN | `:320-360` |

8 家服务商 id：`deepseek` / `openai` / `claude` / `grok` / `kimi` / `qwen` / `siliconflow` / `custom`（`providers.py:23-111`）。

**卡 3 `_create_model_calling_card`**（`cards_ai.py:522-...`）：

| 顺序 | 行 | 控件 | 可见性 | 证据 |
|---|---|---|---|---|
| 1 | 限制token输出 `limit_token_output` | SW | 常显 | `:534-...` |
| 2 | 最小token量 `min_token_placeholder`+":" | IN + 单位 `token_unit` | **仅限流开启时** | `:551-570` |
| 3 | 最大token量 `max_token_placeholder`+":" | IN + 单位 | 同上 | `:573-590` |

离开设置页时若 API Key/模型/地址有未保存改动 → 三选一弹窗（保存并继续 / 放弃修改 / 留在当前界面），见 `interface.py:694-757` 与 `widgets.py:302-344`。

#### ⑨ 开发者功能 `developer_functions`（`cards_misc.py:168-209`、`:212-290`）

- 未验证：行「开发者身份令牌 `developer_identity_token`」 + IN（占位 `input_dev_key`）+ 「验证」BTN；
- 已验证：状态行「`{管理员}` + `admin_verified`」 + 「退出」BTN + 灰字验证时间 + 行「调试信息 `debug_info`」 SW + ⓘ（开关写 `debug_info_enabled_<admin>`）；
- 密钥规则：`key in SPECIAL_KEYS` → 弹可用开发者密钥窗口；`key in DEV_KEYS` → 记录管理员名 + 时间戳（格式 `%Y年%m月%d日 %H时%M分%S秒`）并置 `dev_mode_*` 四个键（`:300-324`）。

#### ⑩ 关于 `about`（`cards_misc.py:379-457`）

竖排居中：`ToolsGCP` 标题 → logo（高 72，`ABOUT_LOGO_SIZE`）→ 版本号（自动补 `v`，Beta 通道且版本号无 `-` 时补 " Beta"）→ **左右各内缩 12px 的分割线** → 行「检查更新 `check_update`」 + BTN（宽 120）→ 完整更新流程（可用版弹窗 → 下载（带 sha256 校验）→ 自动替换 → 失败原因弹窗）。

### 2.5 【重点】主题模式 / 主题效果 / 组件配色 / 语言 的确切顺序与取值

**原版 PyQt 界面的真实顺序**（`cards_ui.py:44-91` 顺序即界面顺序）：

```
1. 主题模式 theme_mode        → 跟随系统 / 浅色主题 / 深色主题        （值就是这三个中文字符串）
2. 组件配色 accent_color      → 蓝色 blue / 紫罗兰 purple / Claude橙 orange
3. 语言 language              → 跟随系统 / 简体中文 / 繁體中文 / English
4. 字体 ui_font               → 系统字体列表（无"跟随系统"项）
5. 启动动画 splash_screen_enabled
6. 启动动画时长 splash_screen_duration
```

**"主题效果"在原版 PyQt 界面里不存在**：
- `theme_effect` 只有三处：`constants.py:184`（默认 `"mica"`）、`settings_manager.py:79`（迁移写默认）、语言文件 `set_language.json` 的 `theme_effect`/`theme_effect_tip`/`fx_mica`/`fx_glass`/`fx_acrylic`（词条已备好）；
- 全 `pymodels` 里**没有任何界面代码读它**（`grep theme_effect` 结果只有上面两处 `.py`）。
- 需求指定位置见 `UI_FIX_ROUND_12.md（已清理，见 git 历史）:226-227`：**「设置 → 外观 →『主题模式』与『组件配色』之间」**，三档含义与参数见该文档 `:230-234`（云母=模糊 0/不透明 100%/有底噪；毛玻璃=26px/62%/无底噪/弱高光；亚克力=16px/80%/无底噪/亮高光）。

**网页端现状（快照 `app.js` md5 `eb79670a...`）**：顺序是

```
主题模式(app.js:2202) → 组件配色(2206) → 主题效果(2212) → 语言(2217) → 字体(2221) → 启动动画(2225) → 启动动画时长(2227)
```

即 **主题效果被放在"组件配色"与"语言"之间**，与 `UI_FIX_ROUND_12.md` 要求的"主题模式与组件配色之间"**不一致**；且该文件正在被并行修改，写文档时仍在变动。网页端主题效果选项值：`mica`/`glass`/`acrylic`，标签 `fx_mica`/`fx_glass`/`fx_acrylic`（`app.js:2212-2216`），通过 `document.documentElement[data-fx]` 生效（`app.js:386`）。

**accent 的取值与色值（原版，`interfaces/settings/theme.py:19-31`）**：

```python
ACCENT_PRESETS = {
    "blue":   {"color": "#009FAA"},   # ⚠️ 名字叫 blue，实际是青色
    "purple": {"color": "#8B6CF6"},
    "orange": {"color": "#D97757"},
}
DEFAULT_ACCENT_KEY = "blue"
```

- 显示名来自语言键 `accent_blue`="蓝色" / `accent_purple`="紫罗兰" / `accent_orange`="Claude橙"；
- 另有两个**不受 accent 影响**的常量：`ACCENT = "#4F7BF7"`、`ACCENT_DARK = "#6E93FF"`（`:13-15`，`tokens()` 里会被 preset 覆盖，见 `:220-230`）；
- AI 悬浮球渐变**恒定**不跟 accent 变：`BALL_GRADIENT = ("#5B8DEF", "#8A6BEF")`（`:33-40`、`:96-107`）。
- 主题模式取值就是三个中文字符串 `跟随系统` / `浅色主题` / `深色主题`，索引映射 `{0:跟随系统, 1:浅色主题, 2:深色主题}`（`interface.py:856`、`cards_ui.py:47`）。
- 语言取值 4 个，索引映射 `{"跟随系统":0, "简体中文":1, "繁體中文":2, "English":3}`（`cards_ui.py:68`）。
- 网页端 accent 选项标签：蓝色/紫罗兰/Claude橙，值 blue/purple/orange（`app.js:2206-2211`），注入 `data-accent`（`app.js:384`）。

### 2.6 主题与配色的实现要点（对齐时需要）

- 切换主题（`interface.py:855-904`）：写 `theme` → `setTheme(Theme.LIGHT/DARK, lazy=True)` → `apply_app_palette()` → `apply_accent_color()` → InfoBar → 交给 `MainWindow.refresh_all_pages_theme()`（只刷当前可见页，其余标脏）。
- 切换配色（`cards_ui.py:335-398`）：写 `accent_color` → `set_accent_key()` → `apply_accent_color(dark, lazy=True)`（灌 `qfluentwidgets` 的 `setThemeColor`）→ 推送到聊天抽屉 / 搜索页 / 插件页 / 首页 / 收藏页。
- 设置页配色 token：浅色 `page #F3F4F7` / `card #FFFFFF` / `card_border #E6E9F0` / `text #1F2329`；深色 `page #1C1C1C` / `card #272727` / `card_border #343434` / `text #E8E8E8`（`theme.py:132-168`）。
- 设置页搜索：左侧列表与"搜索结果列表"二选一，命中项显示 `板块 · 行标题`（`interface.py:596-625`）；回车跳第一条（`:627-630`）；跳转后该行**闪烁高亮**（`_flash_row`，`:646-653`）。

---

## 3. 语言切换逻辑

### 3.1 目录与命名

- 目录：`.ToolsGCP/modules/languages/`（`constants.py:71` `LANGUAGES_DIR = CONFIG_DIR/modules/languages`）。
- 命名：`<模块>_language.json`，全小写下划线；实际文件：

```
ToolsGCPcenter_language.json   common_language.json        customize_language.json
deploy_language.json           feedback_language.json      github_language.json
home_language.json             log_language.json           maker_language.json
nav_language.json              notice_language.json        plugin_language.json
privacy_language.json          search_language.json        set_language.json
```

### 3.2 加载：模块名 → 文件名是**硬编码映射表**

`core/language_manager.py:105-140`：

```python
language_files = {
    "search": "search_language.json", "home": "home_language.json",
    "notice": "notice_language.json", "tools_gcp": "ToolsGCPcenter_language.json",
    "deploy": "deploy_language.json", "github": "github_language.json",
    "settings": "set_language.json", "log": "log_language.json",
    "feedback": "feedback_language.json", "nav": "nav_language.json",
    "privacy": "privacy_language.json", "plugin": "plugin_language.json",
    "maker": "maker_language.json", "customize": "customize_language.json",
    "common": "common_language.json",
}
```

- **共 15 个模块**；新增模块必须登记在这张表里，否则 `get_text` 只能退到代码兜底文案（`:119-120` 注释）。
- 文件缺失/解析失败 → 该模块记为 `{}` 并写 warn/err 日志（`:133-140`）。
- **语言文件全部在内存里**，`LanguageManager` 每 `new` 一次就重读全部 JSON，全程序**只应有一个实例**（`:88-93`）。

### 3.3 key 的组织方式：**文件即模块，key 本身没有模块前缀；模块内部扁平**

`home_language.json` 实样：

```json
{
  "home_title": { "简体中文": "首页", "繁體中文": "首頁", "English": "Home" },
  "recommend_plugins": { "简体中文": "推荐插件", "繁體中文": "推薦外掛", "English": "Recommended Plugins" }
}
```

- 结构：`{ "<key>": { "简体中文": str, "繁體中文": str, "English": str } }` —— **两层，扁平 key，无前缀**；
- 语言名作为内层键，**固定三种**：`简体中文` / `繁體中文` / `English`；
- 取词必须带模块名：`get_text(module, key)`；`terms_*` 类词放在 `common` 模块（如 `term_AI`、`term_GitHub`）；
- ⚠️ 判定"有没有这条 key"要**看键在不在**，不能比较"取出来是否等于 key" —— `maker_language.json` 里有上百条 key 本身就是中文原文（`language_manager.py:146-148` 注释）。

### 3.4 回退链（**准确版**）

`LanguageManager.get_text`（`language_manager.py:142-162`）：

```python
entry = None
if module in self.translations:
    entry = self.translations[module].get(key)
if isinstance(entry, dict):
    text = entry.get(language) or entry.get("简体中文")     # ① 当前语言 → ② 简体中文
    if text:
        return text
# ③ 内嵌英文兜底表（按模块分层）→ ④ key 本身
return EN_FALLBACK.get(module, {}).get(key, key)
```

完整链：**当前语言 → 简体中文 → 模块内嵌英文兜底 `EN_FALLBACK[module][key]` → 返回 key 本身**。

- `EN_FALLBACK` 是自动生成的英文表，来源就是各 JSON 的 `English` 值（`core/en_fallback.py:1-24`；生成脚本 `.ToolsGCP/tools/build_en_fallback.py`）。
- 表**必须按模块分层**：不同模块同名 key 的占位符不同（例：`tools_gcp."count" = "共 {n} 项"`，`plugin."count" = "共 {total} 个，已启用 {enabled} 个"`）—— 拍平会 `KeyError`（`en_fallback.py:14-18`）。
- 注意：**没有"当前语言缺失时先退到繁體中文"这一步**；`繁體中文` 只在"三语对象取值"（`pickI18n`，网页端 `app.js:146-152`）里出现。
- 术语译名走 `common.term_<原值>`（`translate_term`，`:65-85`）；InfoBar 标题走 `common.tip_success/tip_error/tip_warning/tip_info`（`:30-62`）。

### 3.5 语言名 ↔ 设置值映射

| 界面显示（语言键） | 设置里的值 `language` | 备注 |
|---|---|---|
| `follow_system` = 跟随系统 / 跟隨系統 / Follow System | `"跟随系统"` | 默认值 |
| 简体中文 | `"简体中文"` | 语言文件内层键 |
| 繁體中文 | `"繁體中文"` | 语言文件内层键 |
| English | `"English"` | 语言文件内层键 |

- 下拉框选项顺序由 `get_language_options()` 决定：`[跟随系统, 简体中文, 繁體中文, English]`（`interface.py:156-159`），**第一项是"跟随系统"的当前语言译文**；
- 写入时反查映射表 `lang_display_map`（`interface.py:910-916`）：把"跟随系统的当前译文"还原成字面量 `"跟随系统"`；
- **跟随系统**的判定在启动时做一次（`main_window.py:119-131`）：`locale.getlocale()[0]` 含 `Chinese (Simplified)`/`zh_CN` → `简体中文`；含 `Chinese (Traditional)`/`zh_TW`/`zh_HK` → `繁體中文`；否则 `English`；异常兜底 `简体中文`。
  - 另有一份等价实现 `utils/system_utils.detect_system_language()`（`:49-60`），用于设置页弹窗里显示"实际生效语言"。
- 语言管理器内部默认值 `current_language = "简体中文"`（`language_manager.py:100`）。

### 3.6 切换语言**实际做了什么**（关键结论：重启，不重建界面）

`interface.py:907-934`：

```python
def change_language(self, index):
    language_name = self.get_language_options()[index]
    lang_display_map = {self.get_text("follow_system"): "跟随系统", "简体中文": "简体中文",
                        "繁體中文": "繁體中文", "English": "English"}
    actual_lang = lang_display_map.get(language_name, "跟随系统")
    display_lang = detect_system_language() if actual_lang == "跟随系统" else actual_lang
    self.settings_manager.update_setting("language", actual_lang)          # ① 落盘
    self.settings_manager.update_setting("open_settings_on_restart", True) # ② 要重开设置页
    box = MessageBox(self.get_text("restart_required"), "...程序将自动重启以应用更改...")
    box.yesButton.setText(self.get_text("restart_now"))       # 立即重启
    box.cancelButton.setText(self.get_text("restart_later"))  # 稍后手动重启
    if box.exec():
        restart_program(open_settings=True)
```

要点：
1. **只写配置 + 提示重启**：没有调用任何"重建界面/重读语言"的逻辑；
2. `LanguageManager.set_language()` 只赋值 `self.current_language`（`language_manager.py:172-174`），`reload()`（`:176-177`）只是重读 JSON —— **原版切语言路径上并不调用它们**；
3. 重启时会带 `--open-settings`（`restart_program(open_settings=True)`，`utils/system_utils.py:15-31`；`constants.py:55` `OPEN_SETTINGS = "--open-settings" in sys.argv`），启动后自动跳回设置页（`main_window.py:930-932` 处理 `open_settings_on_restart`）；
4. 重启实现：打包态 `[sys.executable, "--open-settings"]`，源码态 `[sys.executable, script, "--open-settings"]`，然后 `QApplication.quit()`；
5. 设置页的文案在**切换当下不会变**（因为 `self.lang.current_language` 未变），重启后整体换语言。

网页端现状（供对照）：`app.js:2515 changeLanguage()` = 存 `language` → 存 `open_settings_on_restart=true` → 弹"需要重启" → 选"立即重启"则 `shell.restart`，选"稍后"则**把 language 回滚成旧值**（`app.js:2535-2538`）。注意这个"回滚"与原版不同（原版选"稍后"也会保留新语言，下次启动生效）。

---

## 4. 左侧栏导航项与图标

文件：`.ToolsGCP/modules/pymodels/ui/main_window.py`，`init_navigation()` 在 `:376-475`。

### 4.1 结构（顺序即界面顺序）

| 位置 | 顺序 | 文本（nav 语言键 / 三语） | qfluentwidgets 图标 | 页面 | 证据 |
|---|---|---|---|---|---|
| TOP | 1 | `home` 首页 / 首頁 / Home | **`FIF.HOME`** | `homeInterface` | `:380-382` |
| TOP | 2 | `search` 搜索 / 搜尋 / Search | **`FIF.SEARCH`** | `searchInterface` | `:384-386` |
| TOP | 3 | `customize` 定制页 / 定制頁 / Customize | **`FIF.PALETTE`** | `customizeInterface` | `:389-391` |
| TOP | 4 | `tools_gcp` 收藏 / 收藏 / Favorites | **`FIF.TAG`** | `toolsGCPInterface` | `:393-394` |
| TOP | 5 | `gcp_workshop` GCP工坊 / GCP工坊 / GCP Workshop | **`FIF.DEVELOPER_TOOLS`**（注释：本版本没有 `FIF.TOOLS`） | `workshopInterface` | `:396-399` |
| TOP | 6（条件） | `ai_page` AI | **`FIF.ROBOT`** | `aiSidebarPage` | `:1369-1375`、`:1421-1427` |
| — | — | 分隔线 | | | `:408` |
| BOTTOM | 1 | `notice` 公告 / 公告 / Notice | **`FIF.MEGAPHONE`** | `noticeInterface`（挂未读红点） | `:411-415` |
| BOTTOM | 2 | `github` Github / Github / Github | **`FIF.GITHUB`** | `githubInterface` | `:417-419` |
| BOTTOM | 3 | `more` 更多 / 更多 / More | **`FIF.MORE`** | 不切页，弹菜单 | `:423-430` |
| BOTTOM | 4 | `settings` 设置 / 設定 / Settings | **`FIF.SETTING`** | `settingsInterface` | `:432-434` |

其它导航参数：展开宽 `setExpandWidth(240)`、`setMinimumExpandWidth(1500)`（强制 flyout，`:466-468`）。
「更多」条目 `selectable=True` + tooltip=`nav.more_tip`（`:421-430`）。

### 4.2 「更多」菜单条目（顺序 = 菜单从上到下）

`more_menu_pages()`（`main_window.py:1473-1484`）+ `more_menu_entries()`（`:1486-1494`）：

| 顺序 | 文本（nav 键 / 三语） | 图标 | 页面/动作 | 证据 |
|---|---|---|---|---|
| 1 | `feedback` 反馈 / 反饋 / Feedback | **`FIF.FEEDBACK`** | `feedbackInterface` | `:1480` |
| 2 | `log` 查看日志 / 查看日誌 / View Logs | **`FIF.DOCUMENT`** | `logInterface` | `:1481` |
| 3 | `deploy` 应用部署 / 應用部署 / App Deploy | **`FIF.LIBRARY`** | `deployInterface`（**已不在左侧栏**） | `:1482` |
| 4 | `plugins` 插件 / 外掛 / Plugins | **`FIF.APPLICATION`** | `pluginInterface` | `:1483` |
| 5 | `submit_software` 提交软件 / 提交軟體 / Submit software | **`FIF.UP`** | 懒建 `resourceMakerInterface` | `:1490-1493` |

菜单实现：`RoundMenu` + `QAction(icon.icon(), text)`，从「更多」按钮**右侧**弹出（`:1496-1525`）；点菜单里的页会把左侧高亮**钉在「更多」**上（`_sync_more_indicator`，`:1537-1548`）。

### 4.3 AI 条目（条件显示）

- 默认**不显示**，只有设置里打开「改用侧边栏 AI 单独界面」（`ai_sidebar_mode`）才出现；
- 位置固定在 **GCP工坊下面**（`_move_ai_item_below_workshop()` `:1399-1430`，用 `insertItem` 按工坊下标 +1 插入；拿不到下标就放顶部区末尾）；
- 图标 `FIF.ROBOT`，文本 `nav.ai_page`；
- 打开时**悬浮球消失**、抽屉收起（`:1381-1395`）。

### 4.4 nav 三语文案（`nav_language.json` 实值，供网页端核对）

| key | 简体中文 | 繁體中文 | English |
|---|---|---|---|
| home | 首页 | 首頁 | Home |
| search | 搜索 | 搜尋 | Search |
| customize | 定制页 | 定制頁 | Customize |
| tools_gcp | 收藏 | 收藏 | Favorites |
| gcp_workshop | GCP工坊 | GCP工坊 | GCP Workshop |
| ai_page | AI | AI | AI |
| notice | 公告 | 公告 | Notice |
| github | Github | Github | Github |
| more | 更多 | 更多 | More |
| settings | 设置 | 設定 | Settings |
| deploy | 应用部署 | 應用部署 | App Deploy |
| plugins | 插件 | 外掛 | Plugins |
| log | 查看日志 | 查看日誌 | View Logs |
| feedback | 反馈 | 反饋 | Feedback |
| submit_software | 提交软件 | 提交軟體 | Submit software |
| more_tip | 更多（反馈 / 查看日志 / 插件 / 提交软件） | 更多（意見 / 檢視日誌 / 外掛 / 提交軟體） | More (Feedback / Logs / Plugins / Submit software) |
| show_main_window | 呼出主窗口 | 呼出主視窗 | Show Main Window |
| show_search_box | 呼出搜索框 | 呼出搜尋框 | Open Search Box |
| show_ai_search | 呼出AI | 呼出AI | Open AI |
| exit | 退出 | 退出 | Exit |

网页端对应定义：`webui/js/app.js:413`（`navTop`）、`:426`（`navBottom`）、`:432`（`moreItems`）；`webui/index.html:124-154`（渲染）。图标由 `webui/js/icons.js` 的 `#i-<name>` sprite 提供，名称映射：home/search/palette/star/developer/robot/megaphone/github/more/setting；更多菜单为 feedback/document/library/puzzle/up（**注意 `plugins` 图标网页端用 `puzzle`，原版是 `FIF.APPLICATION`**）。

---

## 5. 窗口 / 任务栏图标

结论：**原版完全没有 `.ico` 资源，也没有给 exe 打图标；窗口/任务栏图标一律运行时加载 `.ToolsGCP/logo.png`，再配 AppUserModelID 把任务栏归组到应用名下。**

### 5.1 应用级（原版入口 `legacy/ToolsGCP.pyw.qt5`）

```python
# :160-161
app.setApplicationName("ToolsGCP")
app.setApplicationDisplayName("ToolsGCP")

# :163-170  ⚠️ 必须在创建任何窗口之前
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(u"Galen563.ToolsGCP.v1")
    except Exception as _e:
        print(f"[警告] 设置 AppUserModelID 失败（任务栏图标可能显示为 Python 图标）: {_e}")

# :172-175
_APP_ICON_PATH = os.path.join(CURRENT_DIR, ".ToolsGCP", "logo.png")
if os.path.exists(_APP_ICON_PATH):
    from PyQt5.QtGui import QIcon
    app.setWindowIcon(QIcon(_APP_ICON_PATH))
```

- AppUserModelID 固定字符串：**`Galen563.ToolsGCP.v1`**；
- 启动画面用同一个 png：`:183-184` `icon_path = .../logo.png; splash = show_splash_screen(icon_path, splash_duration_ms)`（内部 `QIcon` 见 `.ToolsGCP/modules/pymodels/splash_screen.py`）。

### 5.2 窗口级（`ui/main_window.py:200-204`）

```python
icon_path = os.path.join(SCRIPT_DIR, ".ToolsGCP", "logo.png")
if os.path.exists(icon_path):
    self.setWindowIcon(QIcon(icon_path))
else:
    self.setWindowIcon(FIF.APPLICATION.icon())     # 兜底：库内置图标
```

### 5.3 托盘图标（`ui/main_window.py:952-970`）

注释明确要求"图标必须是**和任务栏同一个 QIcon**（`self.windowIcon()`），否则没设 AppUserModelID 时 Windows 会把窗口归到 python.exe 名下"：

```python
self.tray_icon = QSystemTrayIcon(self)
icon = self.windowIcon()
if icon is None or icon.isNull():                  # 兜底：直接从 logo.png 再取一次
    fallback = os.path.join(str(SCRIPT_DIR), ".ToolsGCP", "logo.png")
    if os.path.exists(fallback): icon = QIcon(fallback)
self.tray_icon.setIcon(icon)
self.tray_icon.setToolTip("ToolsGCP")
```

托盘菜单项顺序（`ui/tray_menu.py`，由 `main_window.py:974-981` 组装）：呼出主窗口 / 呼出搜索框 / 呼出AI / 分隔线 / 退出。

### 5.4 没有 .ico / 没有 --icon

- 全仓库 `glob **/*.ico` → **0 个文件**；
- 打包工作流 `.github/workflows/release.yml` 的 PyInstaller 命令只有 `--name ToolsGCP`（`:41`）与 `--name ToolsGCP-ResourceMaker`（`:52`），**没有 `--icon`**；
- 图标文件本体：`.ToolsGCP/logo.png`（38,095 字节，176×? PNG，运行时资源，非 exe 资源）。

### 5.5 网页端现状（供对齐）

- 前端所有 logo 引用都是 HTTP 资源 `/res/logo.png`：`webui/index.html:61`（preload）、`:70`（启动画面）、`:83`（标题栏图标）、`:1199`（关于卡片）；
- 资源映射：`desktop/webhost.py:16`（`/res/<name>` → `.ToolsGCP/<name>`）；
- AppUserModelID 由新壳设置：`desktop/native/win32.py:331-332` 声明 `SetCurrentProcessExplicitAppUserModelID`；入口 `ToolsGCP.pyw:180-186` 在**建窗之前**调用（字符串 `"Galen563.ToolsGCP.v1"`，与原版一致）；
- 启动画面图标：`desktop/splash.py:108` `app.setWindowIcon(QIcon(self.icon_path))`，`icon_path` = `desktop/shell.py:114` `os.path.join(CONFIG_DIR, "logo.png")`。
- ⚠️ **审计期间新增（未提交，`git status` 显示 `?? desktop/native/appicon.py`）**：`desktop/native/appicon.py`（254 行）专门解决"任务栏显示默认 Python 图标"：pywebview 自己的 `webview.start(icon=...)` 走 .NET `System.Drawing.Icon`，**只认 `.ico`，喂 PNG 会被吞掉并退回 exe 图标**（该文件 `:13-16`）；所以它在窗口创建后用 `WM_SETICON(ICON_BIG/ICON_SMALL)` + `SetClassLongPtrW(GCLP_HICON)` 兜底，PNG→HICON 有"裸 PNG / Pillow 转 ICO / .NET `Bitmap.GetHicon()`"三条路径（`:20-23`、`:104`、`:120`），ICO 只在内存里生成、不落盘。
- ⚠️ 因此"网页端没有 `.ico`"仍是事实（`glob **/*.ico` = 0），但**图标注入方式**正在从"只靠 AppUserModelID + QIcon"改成"AppUserModelID + WM_SETICON HICON"。这是审计期间进行中的改动，落地状态需以当时工作区为准。

---

## 6. 功能对齐清单（原版 vs `webui/js/app.js` + `webui/index.html`）

### 6.1 口径与快照

- "原版"= §0.1 的 PyQt5 代码；
- "网页端"= `webui/index.html`（md5 `da3bb271…`，1426 行）+ `webui/js/app.js`（md5 `eb79670a…`，3569 行，**持续被并行修改**）+ `webui/css/layout.css`（md5 `64d35dd4…`，501 行）；
- 标注：**一致** / **部分**（有实现但行为/字段不一致或有缺项）/ **缺失**（原版有、网页端完全没有）；
- ⚠️ 设置页那些行级行号漂移最快（同一 key 在不同时刻可能差十几行）。**定位时以 `key: '<键名>'` 或 `t('<语言键>'` 为准**，行号仅作参考。

### 6.2 清单

#### A. 首页

| # | 功能点 | 原版 | 网页端 | 标注 |
|---|---|---|---|---|
| A1 | 海报自动发现 | 扫 `posters/` 目录，认 png/jpg/jpeg/webp/bmp，按文件名数字排序，截前 5（`home_interface.py:46-70`） | 逐个探测 `/res/image/posters/poster1..8.png`，**只认 .png**，凑满 5 停（`app.js:1203-1219`） | **部分** |
| A2 | 不足 5 张补空占位、圆点恒 5 个 | `SLIDES` 补齐 5；`PipsPager.setPageNumber(max(1,len(SLIDES)))`（`:73-78`、`:298-308`） | 无占位；圆点 `posters.slice(0,5)` 只有实际张数（`index.html:175-178`） | **部分** |
| A3 | 高度 = clamp(宽×最扁比, 200, 460) + 圆点行 | `:325-373` | 同公式，`layout.css:93-108` + `app.js:1222-1231` | **一致**（数值口径相同） |
| A4 | 图片完整显示不裁切 | `KeepAspectRatio`（`:249-263`） | `object-fit: contain`（`layout.css:104`） | **一致** |
| A5 | 留白用海报边缘像素铺满 | `_fill_letterbox`/`_edge_strips`（`:202-247`） | 无（注释 `app.js:1172` 明确"暂时透明背景"） | **缺失** |
| A6 | 圆角裁切 12px | `:186-189` | `border-radius: 12px`（`layout.css:94`） | **一致** |
| A7 | 3s 自动翻页 + 手动后重置计时 | `:310-312`、`:411-413` | `startSlide/goSlide`（`app.js:1231-1238`） | **一致** |
| A8 | 滚轮攒 120 单位 + 180ms 冷却 +（触摸板 pixelDelta×4） | `:427-457` | 累 `deltaY` ≥120 + 180ms 锁；**无触控板折算**（`app.js:1240-1249`） | **部分** |
| A9 | 离开页面停止翻页 | `showEvent/hideEvent`（`:470-477`） | 只有组件卸载时才 `stopSlide()`（`app.js:3233`）；**切页不停表**（`startSlide` 只在发现海报/点击圆点/滚轮时调用：`:1213,1238,1247`） | **部分** |
| A10 | 推荐插件 + 隐藏名单 + 数量 | `HOME_HIDDEN_PLUGIN_IDS`（`plugin_manager.py:30`）；过滤 3 种状态（`home_interface.py:641-675`） | 过滤 `gcp-ai-agent`/`gcp-plugin-maker`（`app.js:1254`） | **一致** |
| A11 | 空态两种文案 | 有插件但全被滤 vs 一个都没有（`home_interface.py:663-668`） | 单一文案（`index.html:202`） | **部分** |

#### B. 搜索

| # | 功能点 | 原版 | 网页端 | 标注 |
|---|---|---|---|---|
| B1 | 排序 4 项（全部/类别/A-Z/Z-A），默认"类别" | `search_interface.py:331-343` | `app.js:670-674` | **一致** |
| B2 | 筛选 7 组（类别/标签/来源/收藏/更新时间/系统/架构） | `search_interface.py:375-418` | `app.js:679-713` | **一致** |
| B3 | 视图 tile/grid + 工具栏开关 | `:351-368`、`cards_hotkey.py:317-340` | `index.html:237-246`、`app.js:2218-2223` | **一致** |
| B4 | 虚拟列表 + 分组 + 图标懒加载 | `widgets/apps_index_framework.py`（1363 行） | 自实现 `vlist/vRows`（`index.html:277-343`） | **部分**（实现不同，行为大致等价） |
| B5 | 搜索框内 `@` 提及（原子片段、光标吸附、框选整体扩展） | `search_interface.py:290-306`、`:498-507`（`MENTION_STOP_CHARS`） | 仅卡片**右键** @给AI（`app.js:1019-1026`、`index.html:286`）；搜索框是普通 input | **部分** |
| B6 | 自动搜索防抖 300ms，关闭后需 Enter/按钮 | `search_interface.py:481-496` | `autoSearch` 开关（`index.html:220-222`） | **一致** |
| B7 | `last_search` 只写不回填 | `search_interface.py:97,1250` | 不写不回填（`DEFAULT_SETTINGS` 有键） | **一致** |
| B8 | 卡片大小 small/medium/large（设置行已删，键仍生效） | `cards_ui.py:153-154`、`main_window.py:209-210`、`app_card.py:254-303` | `CARD_PRESETS` 读 `search_card_size`（`app.js:34,661-668`） | **一致** |
| B9 | 勾选 → 加到部署清单 / 从收藏夹导入 | `search_interface.py:424-429`；`main_window.py:300-302` | `index.html:263-275`、`app.js:1576` | **一致** |
| B10 | Ctrl+左键"后台打开"不抢焦点 | `utils/url_open.py`（247 行）、`search_interface` `LinkButton`（`resource_detail_interface.py:186-220`） | `openLink` 不处理修饰键（`app.js:1012-1017`） | **部分**（详情页同） |

#### C. 资源详情

| # | 功能点 | 原版 | 网页端 | 标注 |
|---|---|---|---|---|
| C1 | 头部（大图标/名称/编码/描述/标签） | `resource_detail_interface.py:400-520` | `index.html:365-389` | **一致** |
| C2 | 版本（variants）切换 | `resource_detail_interface.py` 头部版本区 | `index.html:391-397`、`app.js:1072`（`chooseVariant`） | **一致** |
| C3 | 应用介绍（多段 + 补充说明） | `:399-406` | `index.html:399-406` | **一致** |
| C4 | 详细信息字段顺序 systems/architectures/category/listed_at + 链接行 url/github | `DETAIL_ROW_DEFS :69-80` | `detailRows`（`index.html:411-424`） | **一致** |
| C5 | 链接行复制按钮（✓ 2 秒） | `CopyLinkButton :138-179` | `index.html:417-421` | **一致** |
| C6 | 空字段不渲染占位噪音 | `:5` 硬约定 | 显示 `—`（`index.html:414`） | **部分** |

#### D. 定制页 / 收藏页

| # | 功能点 | 原版 | 网页端 | 标注 |
|---|---|---|---|---|
| D1 | 喜好引导（类别+标签，取覆盖 ≥2 条的、前 20） | `customize_interface.py:4-8` 硬约定 | `interestCatalog`（`app.js:1261`）、`index.html:434-465` | **部分**（"前 20 / ≥2 条"口径需核对，见 §7） |
| D2 | 推荐网格 + 分数 + 已收藏排除 | `customize_interface.py`（1508 行） | `index.html:466-515`、`app.js:1315`（`recommendations`） | **一致** |
| D3 | 「恢复默认」清 `customize_interests` + 复位 `customize_onboarded` | `customize_interface.py:37-38,893` | `resetInterests`（`index.html:454-456`） | **一致** |
| D4 | 收藏夹 CRUD / 重命名 / 删除 / 批量移动 | `core/favorites_manager.py`、`tools_gcp_interface.py`（466 行） | `index.html:520-599` | **一致** |

#### E. 工坊 / 公告 / Github / 反馈

| # | 功能点 | 原版 | 网页端 | 标注 |
|---|---|---|---|---|
| E1 | GCP工坊页面内容 | `gcp_workshop_interface.py:43-73`：**只有滚动容器 + 居中限宽，没有任何卡片**（页面内容待补充） | `index.html:602-604` `workshop-blank` 空页 | **一致**（都是空页） |
| E2 | 公告：未读红点（数字，>99 显示 99+）、全部已读、在 GitHub 查看、刷新 | `main_window.py:481-500,526-548`；`notice_interface.py`（423 行） | `index.html:142,613-645`、`app.js:1367-1462` | **一致** |
| E3 | 启动拉到未读公告 → 弹「新公告」窗 | `main_window.py:568-655`（`AnnouncementDialog`，延迟 1200ms 拉、700ms 弹） | `noticePopped` 弹窗（`app.js:1437-1462`） | **一致** |
| E4 | 公告已读持久化 | `core/announcements.py`（487 行）→ `announcements.json` | `announcements.list/mark_read/mark_all_read` + localStorage 兜底（`app.js:1367-1433`） | **一致** |
| E5 | Github 页（开发者信息/赞助码/介绍/图片放大） | `github_interface.py`（563 行） | `index.html:651-699` | **一致** |
| E6 | 反馈页（去 GitHub/QQ 群/图片放大） | `feedback_interface.py`（640 行） | `index.html:702-736` | **一致** |

#### F. 日志

| # | 功能点 | 原版 | 网页端 | 标注 |
|---|---|---|---|---|
| F1 | 导出日志 / 导出全部 / 打开目录 / 清理历史 | `log_interface.py`（873 行） | `index.html:739-773`、`app.js:1475-1502` | **一致** |
| F2 | 双击日志 → **独立窗口内查看**（Qt `LogViewerWindow`） | `ui/log_viewer_window.py`（367 行）、`log_interface.py` 双击绑定 | 双击 → `openPath` 用系统默认程序打开（`index.html:760`、`app.js:1504`） | **部分** |
| F3 | 日志预览 + 当前日志标记 | `log_interface.py` | `logPreview`、`（当前）`（`index.html:763-769`） | **一致** |

#### G. 应用部署

| # | 功能点 | 原版 | 网页端 | 标注 |
|---|---|---|---|---|
| G1 | 导出/部署双模式 + 提示文案 | `deploy_interface.py:276,486-489` | `index.html:779-786` | **一致** |
| G2 | 状态机 6 态（待部署/下载中/已下载/已打开官网/已跳过/失败） | `deploy_interface.py:43-60` | `DEPLOY_STATES`（`app.js:43-44`）、`index.html:824` | **一致** |
| G3 | 从资源库添加（多选、搜索、双击） | `deploy_interface.py:110-131` | `index.html:1388-1412`、`app.js:1554-1575`（`openPicker`/`applyPicker`） | **一致** |
| G4 | 从搜索页选择 / 从收藏夹导入 | `:294-305` | `startDeploySelection`（`app.js:1576`）；**收藏夹导入开关无**（仅在搜索页勾选导入） | **部分** |
| G5 | 导出/导入清单（JSON） | `:799-850`（`export_list`/`import_list`） | `exportManifest`/`importManifest`（`app.js:1598,1607`） | **一致** |
| G6 | 手动添加一行 | `manual_add_title`（`:749-756`） | 无 | **缺失** |
| G7 | 下载目录可选 | `download_dir`（`:895`） | 无（`downloader.start` 不带目录） | **缺失** |
| G8 | 一键部署（下载→校验→打开官网）+ 进度条 | `:956-1023` | `confirmDeploy`/`deployOne` + 进度条（`index.html:852-855`、`app.js:1639,1649`） | **一致** |

#### H. 插件

| # | 功能点 | 原版 | 网页端 | 标注 |
|---|---|---|---|---|
| H1 | 卡片/列表两种排版 | `cards_misc`/`plugin_interface.py`（1715 行） | `plugin_view`（`index.html:887-892`、`app.js:1809`） | **一致** |
| H2 | 启停 / 删除 / 内置不可删 | `plugin_interface.py:288,1491` | `index.html:905-942` | **一致** |
| H3 | 备注（最多 20 字，Enter 保存/Esc 取消，点外面关闭） | `PluginNoteEdit :485-620` | `index.html:912-916`、`app.js startNote/saveNote` | **一致** |
| H4 | 插件配置界面（iframe 承载插件页） | `open_config :1086-1102` | `index.html:1362-1373` | **一致** |
| H5 | 「重新加载」/「打开插件目录」 | `plugin_interface.py:1659-1672` | `app.js:1803`、`index.html:880-883` | **一致** |
| H6 | 「开发文档」按钮 | 打开**本地** `plugins/README.md`（`plugin_interface.py:959-961,1668-1671`） | 打开 GitHub 仓库页（`index.html:884-885`） | **部分** |
| H7 | 我想开发（内置开发指南 + 打开目录） | `plugin_interface.py:1260-1280`、`DEV_GUIDE` | `index.html:1375-1386`、`app.js:98-111` | **一致** |

#### I. 提交软件（资源制作器）—— **差距最大**

| # | 功能点 | 原版 | 网页端 | 标注 |
|---|---|---|---|---|
| I1 | 四个分节：投稿表单 / 资源浏览 / 批量合成 / 使用说明 | `resource_maker_interface.py:36-41` | 只有一个简化表单页（`index.html:953-1014`） | **部分** |
| I2 | 投稿表单完整字段（基础/分类/链接/三语文案…）+ 校验 | `resource_maker_pages.py:418-1968`（FormPage，含 `build_steps`、`_build_i18n_card` 等） | 简化字段（`index.html:966-1010`） | **部分** |
| I3 | 资源浏览（在页内浏览/编辑资源库） | `BrowserPage :1978-2787` | 无 | **缺失** |
| I4 | 批量合成（多种模式 + 输出配置） | `BatchPage :2788-3311`（`_build_mode_card`/`_build_files_card`/`_build_output_card`/`_build_run_card`） | 无 | **缺失** |
| I5 | 使用说明页 | `HelpPage :3312+` | 无（只有那句 `workshop_submit_desc`） | **缺失** |
| I6 | 生成/合并进资源库 | `appendToLibrary`/`saveStandalone`/`clearForm` 等（`app.js:2088-2126`） | 只"生成并下载 JSON"（`index.html:961-962`） | **部分** |

#### J. GCP-AI

| # | 功能点 | 原版 | 网页端 | 标注 |
|---|---|---|---|---|
| J1 | 悬浮球 + 右侧抽屉 + 侧边栏整页三种入口 | `ui/ai_floating_button.py`（643 行）、`ai_chat_panel.py:2580+`、`main_window.py:328-345` | `index.html:1222-1282`、`:1017-1070` | **一致** |
| J2 | 消息变体（重新生成/上一条下一条分页） | `ai_chat_panel.py:_variants_of/_switch_variant :4007-4177` | 无 | **缺失** |
| J3 | 气泡行内编辑（inline edit） | `:1395-1538`、`:4229-4320` | 无 | **缺失** |
| J4 | 历史对话（磁盘 `chats/*.json`、多会话、删除） | `core/ai/chat_store.py`、`AIHistoryDrawer :2143-2579` | `aiHistoryList` 只读 **localStorage 里的当前消息**，无多会话/无删除单条（`app.js:2868-2871`） | **部分** |
| J5 | 请求走 `QThread` worker + 可中断 | `core/ai/worker.py`、`_start_request/_stop_current :4897-4959` | 前端 `fetch` + `AbortController` 直连 API（`app.js:2880+`） | **部分**（架构不同） |
| J6 | 上下文范围 / 回复模式 / token 限制真正参与请求 | `_build_request_messages :4577-4628`、`ai_prompt` | 上下文轮数生效（`app.js:2906-2909`）；回复模式**没有**参与前端请求拼装 | **部分** |
| J7 | Agent 工具（操作 ToolsGCP 的手） | `core/ai/agent_runtime.py`、`agent_tools.py`、`_agent* :4669-4787` | 无 | **缺失** |
| J8 | `/` 命令提示与补全弹窗、聊天提示条 | `_command_* :2868-3358`、`core/ai/chat_hints.py` | 无 | **缺失** |
| J9 | `@资源` 提及（右键卡片带入） | `main_window.py:299-304`、`_mention_to_html :3627` | 有（`app.js:1019-1026`） | **一致** |
| J10 | API Key 未配置引导 / 未保存拦截 | `ai_chat_panel.py:_api_configured :4568`、`interface.py:694-740` | 有（`app.js:2884-2897`、`:464-473`） | **一致** |

#### K. 设置

| # | 功能点 | 原版 | 网页端 | 标注 |
|---|---|---|---|---|
| K1 | 10 板块顺序 | `interface.py:303-322` | `sections`（`app.js:2187+`）：appearance/startup/search/hotkey/download/functions/storage/ai/dev/about | **一致** |
| K2 | 外观行顺序 | 主题模式→组件配色→语言→字体→启动动画→时长（`cards_ui.py:44-141`） | 主题模式→组件配色→**主题效果**→语言→字体→启动动画→时长（`app.js:2202-2229`） | **部分**（主题效果为网页端新增，位置与 `UI_FIX_ROUND_12.md:226` 要求不同，且原版无此行） |
| K3 | 侧栏悬停展开 / 提示框位置 | **原版界面无**（只有默认键 `constants.py:186,188`） | 有（`app.js:2300-2307`，功能板块） | **网页端多出** |
| K4 | 「资源来源（云端/本地）+ 本地目录」 | `cards_download.py:47-158` | `app.js:2273-2281` | **一致** |
| K5 | 搜索源/下载源 = Github + 4 镜像 | `constants.py:149-150`、`cards_download.py:171-220` | `app.js:74`、`:2283-2288` | **一致** |
| K6 | 更新渠道 3 档 | `:222-252` | `app.js:2289-2293` | **一致** |
| K7 | 下载限速（复选框 + 缩进滑块 1–300） | `:254-332` | `app.js:2294-2298` | **一致** |
| K8 | GCP License Key 校验规则 | `key == "Galen563-ToolsGCP"` → 密钥窗；**`GCP License Key` 不算**（`cards_misc.py:150-158`） | 用整个 `SPECIAL_KEYS`（含 `"GCP License Key"`）（`app.js:76,2670-2676`） | **部分**（行为差异） |
| K9 | 开发者令牌（含管理员名/时间戳/退出/调试开关） | `cards_misc.py:168-341` | `app.js:2372-2384`、`:2677-2700` | **一致** |
| K10 | 存储位置 + 更改 + 恢复默认 + **迁移进度条/确认框** | `cards_storage.py:93-343` | 有路径行与两个 action（`app.js:2319-2329`、`:2695-2712`），**无内嵌进度条** | **部分** |
| K11 | 关于卡片：logo + 版本号(+Beta) + 分隔线 + 检查更新 | `cards_misc.py:379-457` | `index.html:1197-1209` | **一致** |
| K12 | 检查更新：渠道过滤 + sha256 校验 + 镜像兜底 + **自动替换并重启** + 失败原因弹窗 | `cards_misc.py:461-765`、`core/updater.py`、`core/self_update.py` | 前端直接 `fetch` GitHub Releases，`downloader.start` 下载，**无校验/无自动替换**（`app.js:2730-2786`） | **部分** |
| K13 | 设置搜索（行级 + 回车跳第一条 + 命中行闪烁） | `interface.py:544-656`；命中项**全列** | `settingHits`（`app.js:2391-2406`，命中**截断 40 条** `:2405`） | **部分** |
| K14 | API Key 未保存拦截（离开设置页时三选一） | `interface.py:694-757`、`widgets.py:302-344` | `app.js:464-473` | **一致** |
| K15 | 语言切换需重启 | `interface.py:907-934` | `app.js:2515-2529`；但"稍后重启"会**回滚语言**（原版不回滚） | **部分** |
| K16 | 主题即时生效 + 配色即时生效 | `interface.py:855-904`、`cards_ui.py:335-398` | `applyAppearance`（`app.js:380-402`） | **一致** |

#### L. 系统级

| # | 功能点 | 原版 | 网页端 | 标注 |
|---|---|---|---|---|
| L1 | 单实例（Windows Mutex `ToolsGCP_SingleInstance_Mutex_v1.0`）+ 激活已有窗口 | `legacy/ToolsGCP.pyw.qt5:58-126` | `ToolsGCP.pyw:77-156`（同实现） | **一致** |
| L2 | AppUserModelID `Galen563.ToolsGCP.v1` | `legacy:163-170` | `ToolsGCP.pyw:179-186`、`desktop/native/win32.py:331-332` | **一致** |
| L3 | 窗口/任务栏图标 = logo.png | `legacy:172-175`、`main_window.py:200-204` | `/res/logo.png`（`index.html:61,83`）、`desktop/shell.py:114` | **一致** |
| L4 | 托盘图标 + 自定义圆角菜单（4 项 + 分隔线） | `main_window.py:952-1029`、`ui/tray_menu.py` | `desktop/native/traymenu.py`（见 `UI_FIX_ROUND_12.md（已清理，见 git 历史）:200-217`）；前端 `app.js:2934-2966` | **一致** |
| L5 | 全局快捷键 Ctrl+Q / Ctrl+Alt+G + 默认键迁移 + 注册失败提示 | `utils/global_hotkey.py`（334 行）、`main_window.py:347-357` | `hotkey.apply_settings`（`app.js:2584`）、前端录制 + 非法键校验（`app.js:2530-2539`） | **一致** |
| L6 | 启动画面（时长 1–5s，默认关） | `splash_screen.py`（156 行）、`legacy:177-184` | `index.html:67-75` + `app.splash_remaining/app.splash_wait`（`app.js:3078`） | **一致** |
| L7 | 隐私同意（版本号、用户协议、隐私政策） | `ui/privacy_consent.py`（594 行） | `index.html:1299-1317`、`app.js app.privacy_state/accept_privacy` | **一致** |
| L8 | 崩溃护栏 | `utils/crash_guard.py` | `ToolsGCP.pyw:169-170` | **一致** |

### 6.3 建议补齐优先级（按"用户可见 + 成本低"排序）

1. **A1/A2**：改成"后端返回海报清单"而不是前端硬探 `poster1..8.png`（否则加 `poster6`、放 `.jpg`、或不足 5 张都不对）。
2. **K2**：把「主题效果」移到"主题模式"与"组件配色"之间（`UI_FIX_ROUND_12.md（已清理，见 git 历史）:226-227` 是明确需求），或与需求方确认改口径。
3. **A9**：切换离开首页时停掉轮播定时器（现在是后台常跑）。
4. **F2**：日志双击改成应用内查看（对齐 `LogViewerWindow`）。
5. **K8**：License Key 校验规则对齐原版（`GCP License Key` 不算有效）。
6. **J4/J6**：AI 历史改成后端会话（`chats/*.json` + session id），回复模式接入请求拼装。
7. **I1–I6**：资源制作器的"资源浏览 / 批量合成 / 使用说明"三节缺失。

---

## 7. 未能确认 / 存疑（不要当结论用）

1. **`webui/js/app.js` 的最终行号**：审计期间该文件被并行修改 3 次（3539→3550→3569 行）。§6 的网页端行号对应 md5 `eb79670a…`；关键字锚点可靠，行号可能漂移。
2. **`accent_color = "blue"` 是青色 `#009FAA` 是否有意**：`theme.py:26` 与同文件 `:13 ACCENT = "#4F7BF7"` 并存且不等，注释没有说明原因。**未能确认**是设计如此还是历史遗留。
3. **原版"主题效果"是否曾存在于某个更早/更晚的 PyQt 版本**：本次只审 `v1.1.4 - 12` 工作区；文档（`UI_FIX_ROUND_12.md（已清理，见 git 历史）`）把它描述为"本轮新增"，只在 web 端落地，`pymodels` 侧只有默认键。**未能在 PyQt 代码中找到任何 UI 实现**。
4. **定制页喜好清单"只留覆盖 ≥2 条资源的、取前 20"**：该口径来自 `customize_interface.py:4-8` 的模块级注释；本次**没有逐行核对该过滤逻辑的代码**（文件 1508 行，未全读）。网页端 `interestCatalog`（`app.js:1261`）是否等价**未能确认**。
5. **部署页"从收藏夹导入"开关**：原版有 `fav_import_switch`（`deploy_interface.py:303-305`），网页端只在搜索页提供"从收藏夹导入"选择器；两者是否等价**未能确认**（未逐行读 deploy 的收藏导入分支）。
6. **`ui/ai_chat_panel.py`（5598 行）的完整功能面**：§6-J 的判定基于函数名与关键调用点（`grep` 全表），未逐段阅读；可能存在遗漏或过度归纳的子功能。
7. **`webui/js/core/*`、`webui/js/components/*` 是否真的全是死代码**：已确认 `index.html` 不引用它们、`app.js` 自带同名实现；但**后端（`desktop/`）是否通过其它方式加载**未核实（`desktop/webhost.py` 只做静态映射）。
8. **`resource_maker_pages.py`（3381 行）各分节的字段级清单**：只确认了四个分节与若干 `_build_*` 函数名；表单具体字段集**未逐项核对**，§6-I 的"部分"判定基于页面结构而非字段级 diff。
9. **`settings.reveal_api_key` / `downloader.start` 等新壳接口的具体行为**：属 `desktop/api`（本次未展开），因此 K12/J5 的"网页端"表述只覆盖前端调用方式。
10. **原版 `log_interface.py` 是否还有"日志等级筛选/关键字搜索"**：`grep` 未见明显标记，但**未通读 873 行**，不能断言没有。
11. **审计期间正在施工的文件**（`git status`，非本人改动）：`webui/js/app.js`、`webui/css/layout.css`、`webui/js/icons.js`、`desktop/shell.py`、`desktop/native/{frame,win32}.py`、新增 `desktop/native/appicon.py`。§5.5 的"图标注入方式"与 §6 的网页端行为可能在这之后已变，**以最终工作区为准**。
12. **`desktop/native/appicon.py` 是否已被 `desktop/shell.py` 调用、调用时机是否早于首帧**：本次只读了该模块自身，**未能确认**接线情况（`grep` 未在本文展开 `desktop/shell.py`）。
