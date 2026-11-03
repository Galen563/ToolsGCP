# AGENTS.md · 给后续 AI / 开发者的项目说明

> 这份文件写给「以后接手这个仓库的 AI Agent 或开发者」。
> 读完这一页，你就能知道**东西在哪、改哪个文件、别碰什么、怎么验证**，不用再满仓库 grep。

---

## 1. 这是什么项目

**ToolsGCP** —— Windows 工具箱启动器。
当前主体是 **web 版**：`pywebview`（WebView2 窗口）当壳，**Vue3（运行时 CDN 版）** 当界面，
Python 负责窗口 / 托盘 / 原生能力，业务逻辑复用旧 PyQt 版的 `pymodels.core|utils`。

> 旧 PyQt5 单机版已经整体归档，只作为参考：`py版本-已弃用仅作为参考项目，主体转为web版本/备份py版本/`
> —— **那个目录是只读存档，绝对不要修改、不要删除、不要"顺手优化"**。

---

## 2. 目录结构（唯一正确版本，改结构前先读第 6 节）

```
ToolsGCP.pyw                                   ← 唯一入口（根目录只有它一个 .py）
requirements.txt / README*.md / AGENTS.md      ← 根目录只放这些"门面文件"
.github/workflows/release.yml                  ← 打 v* 标签自动打包成 exe

.ToolsGCP/                                     ← ★ 所有程序和运行数据都在这里
├─ desktop/                                    ← Python 包 `desktop`：桌面外壳
│  ├─ shell.py                                 窗口装配 / 启动时序 / 托盘 / 热键 / 退出闸门
│  ├─ webhost.py                               本地 WSGI 服务（把 webui/ 和资源喂给 WebView2）
│  ├─ splash.py                                启动动画（**纯 Win32 分层窗口**，无 Qt）
│  ├─ api/                                     window.pywebview.api 的各域
│  │  ├─ __init__.py                           app / window / i18n / log / shell / clipboard
│  │  ├─ resources.py                          resources / favorites / settings（含存储迁移）
│  │  └─ ai.py                                 GCP-AI 会话 / 历史 / 发送
│  └─ native/                                  原生层（ctypes / pythonnet，不依赖 Qt）
│     ├─ win32.py                              基础封装 + 常量
│     ├─ frame.py                              无边框窗口补丁（自绘标题栏模式）
│     ├─ tray.py / traymenu.py                 托盘图标 + 自绘圆角右键菜单（分层窗口）
│     ├─ clipboard.py                          原生剪贴板（前端"复制"按钮走这里）
│     ├─ appicon.py / autostart.py / hotkey.py / backdrop.py / privacy_state.py
├─ webui/                                      ← 前端（无构建步骤，改完刷新即生效）
│  ├─ index.html                               单文件模板：所有页面段都在这里（v-if 切换）
│  ├─ js/app.js                                ★ 全部前端逻辑（经典脚本，不是 ES Module）
│  ├─ js/icons.js                              内联 SVG symbol 精灵（id="i-xxx"）
│  ├─ js/vendor/{vue.global.prod.js,tailwind.js}
│  └─ css/{variables,base,components,layout,animations,overlays}.css
├─ modules/                                    ← Python 包 `pymodels`（业务逻辑，被 web 版复用）
│  ├─ pymodels/core/                           资源查询 / 收藏 / 设置 / 插件 / AI / 数据根
│  ├─ pymodels/utils/                          日志 / 全局热键 / 字体 / 崩溃护栏
│  ├─ pymodels/constants.py                    ★ 路径与默认设置的唯一事实来源
│  └─ languages/{zh_CN,zh_TW,en_US}/*.json      15 个语言模块 × 3 个单语言目录（每文件只有一种语言）
├─ images/                                     图片资源
│  ├─ icon/                                    资源库图标（注意：不是 Icon，是小写 icon）
│  └─ qq/                                      反馈页二维码
├─ plugins/                                    内置插件（一个文件夹 = 一个插件；**随程序发布**）
├─ ToolsGCP-Resources.json                     资源库（52 条资源）
└─ logo.png                                    程序图标

py版本-…/备份py版本/                             旧 PyQt5 版存档（只读参考，勿动）
项目资料-文档与开发测试/                          设计文档 / 回归脚本 / 构建工具（不参与运行）
```

### 三条硬规则

1. **新代码写进 `.ToolsGCP/`**，别在根目录新建 Python 包或资源目录（根目录只留入口/文档/依赖）。
2. **`webui/js/app.js` 是唯一被加载的前端逻辑**。`webui/js/` 下不存在 `main.js`/`pages.js`/
   `components/`/`core/`（那些前端旧架构死文件已在 2026-10-31 清理中删除，git 历史可查），
   不要按"Vue 工程惯例"去找。
3. **`.ToolsGCP/config`、`.ToolsGCP/logs`、`.ToolsGCP/chats` 是用户数据**，已在 `.gitignore` 里，
   永远不要把里面的内容写进代码或提交。

---

## 3. 三层架构 & 数据流

```
┌──────────────────┐  window.pywebview.api（JS↔Python，自动展开成 api.<域>.<方法>）
│ .ToolsGCP/webui  │ ─────────────────────────────────────────────┐
│  index.html      │                                              ▼
│  js/app.js       │  fetch /static/...        ┌──────────────────────────────┐
│  css/*.css       │ ────────────────────────▶ │ desktop/webhost.py（WSGI）     │
└──────────────────┘  fetch /res/image/icon/…  │  → .ToolsGCP/webui            │
                                              │  → .ToolsGCP/images / logo.png │
                                              │  → .ToolsGCP/ToolsGCP-*.json   │
                                              └──────────────────────────────┘
                                                          ▲
                          ┌───────────────────────────────┴──────────┐
                          │ desktop/shell.py（窗口/托盘/热键/退出）      │
                          │ desktop/api/*（业务门面，JSON 化 + 兜异常）   │
                          │ pymodels/core|utils（真业务，不 import Qt 除外）│
                          └──────────────────────────────────────────┘
```

- **前端只能通过 `bridge.tryCall('域.方法', ...args)` 调后端**（`app.js` 里的 `bridge` 对象）。
  `tryCall` 在"后端没这个接口"时返回 `null`，调用方**必须显式降级**（`needApi()`），不许假装成功。
- 后端方法**返回值必须是 JSON 可序列化的 dict**，约定 `{ok: True, ...}` / `{ok: False, error: "..."}`。
  ⚠️ 千万别在返回值里再用 `ok` 当业务字段名（会覆盖信封的 `ok`）—— 用 `success`。
- 后端 → 前端推送用 `shell.push_event(name, payload)`，前端 `window.ToolsGCP.emit` 收。

---

## 4. 常见改动该动哪里（速查表）

| 需求 | 改这里 |
|---|---|
| 加/改一个页面 | `webui/index.html` 加 `<section v-if="page === 'x'">` + `app.js` 的 `navTop/navBottom` |
| 加一个设置项 | `pymodels/constants.py` 的 `DEFAULT_SETTINGS` + `app.js` 的 `sections` computed（`type:` 见现有 15 种行类型）+ 三语 `languages/{zh_CN,zh_TW,en_US}/*.json` |
| 加一个后端接口 | `desktop/api/xxx.py` 加方法 → `desktop/api/__init__.py` 的 `Api.__init__` 挂域 → 前端 `bridge.tryCall('xxx.方法')` |
| 改资源库字段 / 查询 | `pymodels/core/resource_schema.py`、`resource_query.py`（**不要在 app.js 里重写算法**） |
| 改图标 | `webui/js/icons.js` 的 `ICONS`（只放子元素，24×24 viewBox，stroke=currentColor） |
| 改配色 / 毛玻璃 / 亚克力 | `webui/css/variables.css`（`--fx-*` 三档）+ 组件自己的 `backdrop-filter` |
| 改托盘菜单 | `desktop/native/traymenu.py`（自绘分层窗口）+ `tray.py` 里的菜单项 |
| 改窗口行为 / 启动流程 | `desktop/shell.py`（文件头有一大段时序说明，**先读再改**） |
| 改资源路径（图片/图标） | `desktop/webhost.py` 的路由 + `desktop/api/resources.py` 的 `icon_url()` |

---

## 5. 踩过的坑（别再踩）

1. **`webui/js/app.js` 是经典脚本，不是模块**。里面不能用 `import`；`const { createApp } = Vue` 从全局拿。
2. **`docs/`、`_devtest/` 已归档**到 `项目资料-文档与开发测试/`，里面写的路径是**整理前**的，别照抄。
3. **`v-cloak` 必须有样式**（`base.css: [v-cloak]{display:none!important}`），否则启动瞬间会露出
   原始 `{{ t('xxx') }}` 和未挂载的弹层。
4. **下拉框是自绘的 `<combo>`**，不是原生 `<select>`；互斥靠 `app.js` 的 `comboOpenRegistry`。
5. **卡片列表是虚拟列表**（`vlist/vrow/vgroup` + 绝对定位），行高/列宽由 JS 计算，
   **不要在 CSS 里给卡片写死宽高**，否则会出现"卡片被拉伸填满空位"或"文字被裁"。
6. **图标目录是小写** `.ToolsGCP/images/icon/`；URL 规范是 `/res/image/icon/<文件名>`
   （`/res/icon/<文件名>` 是兼容别名，别新增用法）。
7. **托盘菜单是原生分层窗口**（不是 HTML）。它超出窗口边界、失焦也要置顶，HTML 做不到。
8. **退出时严禁再 `evaluate_js`**：WebView2 比主窗口先销毁，会抛
   `System.ObjectDisposedException: 无法访问已释放的对象。对象名:"WebView2"`。
   `shell.push_event` 已有三道闸门，新增后台轮询也要自己检查 `_teardown_started`。
9. **数据根**：程序自动产出的配置/日志在 `<用户主目录>\.ToolsGCP`（默认，自动创建）；`%USERPROFILE%\ToolsGCP.json` 是**位置指针**（用户可以在设置 → 存储里迁移 `.ToolsGCP`，指针文件本身固定在主目录）。程序目录旁的 `.ToolsGCP` 是**资源目录**（modules/images/资源库/插件），永远不搬、也不是配置目录。
   `constants.CONFIG_DIR`（随程序发布的资源）和 `constants.USER_DATA_ROOT`（用户数据）**都由 data_root.py 算**，
   不要在别处硬编码路径。
10. **中文路径**：仓库路径里有中文和空格，命令行一律加引号；Python 里用 `os.path.join`，别手拼 `/`。
11. **插件有两个根目录，两处都要加载**（`desktop/api/plugins.py` 的 `plugins_dirs()`）：
    ① `<程序目录>\.ToolsGCP\plugins\`（内置，随程序发布，exe 里多半只读）；
    ② `<数据根>\plugins\`（用户可写，默认 `%USERPROFILE%\.ToolsGCP\plugins\`，启动时自动创建）。
    **优先级 ② > ①**（同名插件用户那份生效、内置那份被遮住但受保护不可删）。
    ⚠️ 任何"找插件目录/读插件文件"的新代码**一律走 `plugins_dirs()` / `find_plugin_dir(id)`**，
    不要再写死 `CONFIG_DIR/plugins`（webhost 的 `/res/plugins/<path>` 路由也已按同样顺序解析）。
    ⚠️ 数据根迁移时 `plugins/` 跟着搬；但**反向迁移（程序目录→用户主目录）必须跳过它**
    （否则官方插件会被复制成"用户版本"、以后升级反而不生效，见 `_REVERSE_SKIP_DIRS`）。

---

## 6. 怎么验证做完的改动

```bash
# 1) Python 语法（必须有输出 OK 才算过）
python -m compileall -q ".ToolsGCP/desktop" ".ToolsGCP/modules" ToolsGCP.pyw
python -c "import sys,os; sys.path[:0]=['.ToolsGCP','.ToolsGCP/modules']; import desktop.shell; print('IMPORT OK')"

# 2) 前端语法（Node 18+）
node --check .ToolsGCP/webui/js/app.js
node --check .ToolsGCP/webui/js/icons.js

# 3) HTML 标签配平（可选，用项目里现成的小脚本思路）
#    或者直接起本地预览：
python 项目资料-文档与开发测试/_devtest/serve.py 8791
#    然后浏览器打开 http://127.0.0.1:8791/ （带 mock pywebview.api，能看 UI 但不能测原生功能）

# 4) 真正跑一次
python ToolsGCP.pyw
```

回归脚本在 `项目资料-文档与开发测试/_devtest/regression.py`（无头 Edge 逐页审计），
但它**需要一台没有被沙箱限制的 Windows**（Chromium 多进程要开命名管道）。

---

## 7. 编码规范（跟着现有代码走）

- 注释与文档用**中文**，讲**为什么**而不是"这行在干嘛"；踩过的坑写在代码旁边。
- 不引入新依赖（当前依赖见 `requirements.txt`，每行都有注释说明用途）。
- 前端不要引入构建链（没有 webpack/vite），改完保存刷新即可。
- 后端不 import PyQt5（**本项目已不再依赖 PyQt5**：`requirements.txt` 里已移除，
  `desktop/splash.py` 换成纯 Win32 分层窗口，主链路自检要求"屏蔽 PyQt5 后仍能完整 import"）。
  剩下几个 `pymodels/utils|core` 里的旧模块仍写着 Qt import，但**都只在旧 py 版/惰性路径里用**，
  Web 版主链路不碰；新增代码不要往主链路引入任何 Qt。
- 破坏性操作（删除 / 迁移 / 覆盖用户数据）必须有二次确认 + 明确日志。

---

## 8. 绝对不要做的事

| ❌ | 原因 |
|---|---|
| 修改 `py版本-…/备份py版本/` | 那是用户的只读存档 |
| 在根目录新建 `webui/`、`desktop/`、`assets/` | 所有程序文件归 `.ToolsGCP/` |
| 把 `.ToolsGCP/config|logs` 提交到 git | 里面可能有加密后的 API Key |
| 在主线程 `import PyQt5` | WebView2 初始化会崩（见 `desktop/splash.py` 的注释） |
| 用 `--onefile` 打包 | `webhost.py` 按 exe 目录找静态资源，onefile 会全 404（用 `--onedir`） |
| 给卡片/列表写死宽高 | 布局由 JS 按虚拟列表算法计算，会打架 |
