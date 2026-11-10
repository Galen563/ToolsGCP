<div align="center">

# ToolsGCP

<img src=".ToolsGCP/logo.png" alt="ToolsGCP logo" width="140">

**English** ｜ [简体中文](README.zh-CN.md) ｜ [繁體中文](README.zh-TW.md)

*A free, open-source toolbox launcher for Windows — every entry points straight to its official site or GitHub.*

</div>

---

## What is ToolsGCP

ToolsGCP is a free and open-source toolbox launcher for Windows. It keeps a curated index of useful
programs and websites so you can find them, favorite them, and reinstall them on a new machine
without hunting for download pages.

- **Clean by design** — every entry links to the official website or the official GitHub repo. No bundles, no ads, no repackaged installers.
- **App deployment** — collect the software you use into a list; after a reinstall, restore the whole list in one go.
- **GCP-AI** — a built-in assistant. Describe what you need in plain words and it finds the matching entry in the resource library for you.
- **Plugin system** — drop a folder into `plugins/` and it becomes a new page inside the app. Anyone can extend it without touching the core.
- **ResourceMaker** — a small GUI tool that turns "I want this app listed" into a valid resource entry, including image import, tagging and a JSON writer.

## Features

| Area | What you get |
|---|---|
| Search | Keyword search (name / description / tag / code like `TG-000015`), category grouping, A–Z sort, favorites |
| Filters | Category, tag, source (site / repo / auto-download), favorites only, and **updated time** (latest / 10 days / 30 days / 6 months) |
| Home | Banner carousel at the top (5 blank slides, auto-advance every 3 s, clickable pips), then "Recommended Plugins" - what is in your local plugins/ folder, one click to the plugin center |
| Cards | Responsive grid that adapts to the window; **two views — Tile (4 large cards per row) and Grid (6 small cards per row)**, switched from the right end of the toolbar; small / medium / large card sizes; optional animated GIF icons; an @-to-AI button on every card. The Grid view keeps only the favourite button and elides text that no longer fits |
| GCP-AI | Liquid floating orb in the bottom-right corner → chat drawer on the right; saved conversations (deleting one asks for confirmation first); a missing-API-Key hint that jumps straight to Settings |
| Deployment | Build a deploy list from search results or a favorites folder, then let ToolsGCP download and install later |
| Plugins | Grid or list layout, a **status badge in the top-right corner (enabled = green / disabled = red)**, a 20-character note you can edit in the bottom-left (clicking outside cancels it), disabled plugins shown dimmed, plus a search box |
| Notice | Content comes from GitHub issues labelled 公告 that were **opened by the repository owner** (one issue = one whole announcement, title + body rendered as-is). The sidebar entry carries a **WeChat-style red unread counter**; the **Mark all read** button in the top-right corner clears it; on startup, unread announcements pop up in the same in-window dialog style as "Check for updates" |
| GCP Workshop | The page right below "Favorites" in the sidebar (by Galne563). **Currently empty** — only the title and credit are there; content will be added later |
| Sidebar AI | With "Use the sidebar AI page instead" enabled in Settings → GCP-AI, an "AI" page appears in the sidebar right below GCP Workshop (input box, send, new chat, history), and the floating ball disappears. Off by default. **Both forms share one conversation**: chat halfway in the floating-ball drawer, switch this page on in Settings (or the other way round), and the conversation you were in carries over |
| Link clicks | Every external link (detail page, search cards, AI answers, feedback page …): **left click** opens the browser and switches to it; **Ctrl+left click** opens it too but keeps this app in the foreground (browsers like to grab focus themselves — the app takes it back and stays put) |
| UI font | Settings → Appearance → Font: pick any installed font for the whole app; the first entry (Microsoft YaHei) is the default |
| Submit software | The last entry under **More** in the sidebar: it opens the built-in **resource maker** page (submission form / library browser / batch merge / built-in manual). Whatever you produce goes straight into `.ToolsGCP/ToolsGCP-Resources.json` |
| Settings | A section list on the left plus **one single scrollable page** on the right (clicking a section scrolls to it); the search box on top lists every match and lets you pick |
| Window | F11 switches to a real fullscreen that hides the top title bar but keeps the navigation rail; Esc exits |
| Logging | Unified log format in the terminal and in `.ToolsGCP/logs/`, with 30 rotating history files |

## Project structure

```
ToolsGCP.pyw                   Main program (double-click to run)
ToolsGCP-ResourceMaker.pyw     ResourceMaker tool (create / edit resource entries)
requirements.txt               Dependencies
README.md                      README (English)
README.zh-CN.md                README (Simplified Chinese)
README.zh-TW.md                README (Traditional Chinese)
plugins/                       Plugin folder (see plugins/README.md)
  _template/                   Starter template for your own plugin
  hello-world/                 Minimal example plugin
  plugin-showcase/             Full example plugin showing everything context exposes
docs/                          Documentation
  LOGGING.md                   Log format and troubleshooting
  SECURITY_AND_ENGINEERING.md  Security model and engineering rules
.ToolsGCP/                     Program data (do not delete)
  ToolsGCP-Resources.json      The resource library (all apps; ResourceMaker reads/writes this exact path)
  privacy_policy.json          Privacy-policy consent record
  logo.png                     Program logo / window icon
  Icon/                        App icons referenced by the resource library
  modules/                     Core Python modules and language files
  backups/                     Automatic backups of the resource library (latest 20)
  logs/                        Runtime logs and history
  config/                      Settings written by the program itself (created on first run)
    toolsgcp_config.json       Settings (encrypted API key, base URL, model name)
    favorites.json             Favorites
    deploy_config.json         Deploy list
    plugins.json               Plugin enabled / disabled state
    plugin_notes.json          Your per-plugin notes from the cards
    plugin_data/<plugin-id>/   Per-plugin writable data folder
    chats/                     GCP-AI conversation history (one JSON per conversation)
```

> **`.ToolsGCP/config/` holds only files the program writes itself.**
> The resource library, the privacy record, icons, language files and logs stay where they are under
> `.ToolsGCP/` — they belong to ResourceMaker or to the installer, and moving them would break the
> other program that looks for them.
>
> When upgrading from an older version (settings sitting flat in `.ToolsGCP/`), the program
> **moves those files into `config/` automatically** at startup. Your settings and favorites are kept,
> and the log records a `[数据目录] migrate_file` line for each move.

## Requirements

- Windows 10 / 11
- Python 3.10 or newer (tested on 3.13)
- Two runtime dependencies only:

```bash
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

## Running

```bash
python ToolsGCP.pyw
```

Or double-click `ToolsGCP.pyw` in Explorer. To edit the resource library:

```bash
python ToolsGCP-ResourceMaker.pyw
```

## GCP-AI

A built-in assistant, **off by default**. Turn on "Enable GCP-AI" in Settings → AI and a slowly
flowing liquid orb appears in the bottom-right corner.

### How to use it

1. Click the orb (or press `Ctrl+Caps`) — the chat drawer slides in from the right;
2. Type what you need in the box at the bottom, for example:
   - "I want a tool to transfer files over my LAN"
   - "any good screen recorder?"
   - "what Minecraft launchers are there?"
3. It matches your words against the ToolsGCP resource library and answers with the matching
   entries' **description, category, tags, official site and GitHub**.

`Enter` sends, `Shift+Enter` inserts a newline, `Esc` collapses the drawer (on the history page
`Esc` goes **back to the chat** first, and a second `Esc` collapses). While the drawer is open the
orb hides; it comes back as soon as you collapse the drawer.

The three header buttons:

| Button | What it does |
|---|---|
| `＋` | Start a new conversation (or press `Ctrl+J`) |
| 🕘 | Open the **history** page: one card per conversation showing the conversation *content* (truncated with `…`), with the **start → end time** at the bottom right and older conversations further down. Click a card to load that conversation |
| `×` | Collapse the drawer (`Esc` works too) |

The history page has a **left-arrow button** (no text) in the top-left corner; click it or press
`Esc` to go back to the chat.

Every time you reopen ToolsGCP a fresh conversation starts; earlier ones stay in the history under
`.ToolsGCP/config/chats/` (one JSON per conversation).

### Configuration

| Where | What it does | Default |
|---|---|---|
| Settings → API Key → **Provider** | Pick DeepSeek / OpenAI / Claude / Grok / Kimi / Qwen / SiliconFlow / Custom. The model and base URL below are **filled in automatically** | DeepSeek |
| Settings → API Key → **Model Name** | Editable dropdown: lists the provider's common models, and you can type any model id | `deepseek-v4.1-flash` (V4.1-Flash) |
| Settings → API Key → **API Base URL** | OpenAI-compatible base URL, usually ending in `/v1`. Filled from the provider, editable | `https://api.deepseek.com/v1` |
| Settings → API Key → **API Key** | Your key. **Encrypted with Windows DPAPI and stored as `api_key_enc` in `config/toolsgcp_config.json`** — the ciphertext cannot be decrypted on another machine | empty |
| Settings → AI → **Reply Mode** | Controls answer **length and detail** — see the table below | Standard |
| Settings → AI → **Context Window** | How much history is sent with each question: the whole session (default, longest memory) / last 10 / 20 / 30 rounds | whole session |
| Settings → Model Calling → Limit token output | Cap the length of a single answer | off |

Built-in providers and their common models (all editable):

| Provider | Base URL | Common models |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-v4.1-flash` (V4.1-Flash, default), `deepseek-v4-pro`, `deepseek-v4-flash` |
| OpenAI | `https://api.openai.com/v1` | `gpt-5.1`, `gpt-5.1-mini`, `gpt-4.1` |
| Anthropic (Claude) | `https://api.anthropic.com/v1` | `claude-sonnet-4-6`, `claude-opus-4-1`, `claude-haiku-4-5` |
| xAI (Grok) | `https://api.x.ai/v1` | `grok-4`, `grok-4-fast`, `grok-3` |
| Kimi | `https://api.moonshot.cn/v1` | `kimi-k3`, `kimi-k2.7-code`, `kimi-k2.6` |
| Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3-max`, `qwen-plus`, `qwen-flash` |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3`, `Qwen/Qwen3-8B`, … (check the console) |
| Custom | your own | local Ollama / vLLM / one-api / a relay, up to `/v1` |

> Model ids change faster than software releases, so both boxes are **editable** — just type an id
> that isn't in the list. The official OpenAI / Claude / Grok endpoints need network access from
> your region; when they're unreachable you get a specific error (auth / rate limit / timeout / no
> route) instead of a silent failure.

### What you can do with a message

Every bubble has a small button row under it — user messages on the right, AI messages on the left:

| Button | Where | What it does |
|---|---|---|
| ✎ | user message (left) | **Rewrite**: puts that message back into the input box; the old answer is dropped, and the previous version is still reachable via the pager |
| ⧉ | both | **Copy** the message as plain text |
| ⟳ | AI message (right) | **Regenerate**: asks the same question again; the button turns into a spinning progress ring while it works |
| ‹ 2/3 › | middle | Appears when a position has **two or more versions** (rewritten / regenerated). Arrows switch versions and grey out at the ends; loading a saved conversation starts at the newest version |

> Versions live **in memory only** — `config/chats/*.json` always stores just the currently
> selected version, so the file format is unchanged.

### @-mentioning a resource

Every resource card in Search and Favorites now has an **@ button** (chat icon) in its bottom row:

- Click it → the AI drawer opens and `@Name(RESOURCE-CODE)` is appended to the **end** of the input
  box, e.g. `@LocalSend(TG-000001)`;
- If you already typed something, it's **appended**, never overwritten;
- Add a sentence and send: the AI knows you mean that exact library entry and answers around it;
- You can also type `@OBS` yourself.

### Reply modes

| Mode | What an answer looks like |
|---|---|
| **Concise** | Max 4 lines, conclusion only: which one + what it does + one link. No categories, pros/cons or comparisons |
| **Standard** | Within 6 lines: a pick (name + one line) + the official link + one alternative |
| **Professional** | About 10 lines: conclusion first, then the key differences that matter (use case, open source, Chinese UI…), then 1–2 alternatives |

Rules every mode obeys: **never output code** (no code blocks, commands, scripts or config
snippets), no tables or headings, don't restate your question, no filler, and always give full
`http(s)` links.

**Without an API key**: you can still send messages, but it won't call any model. Instead the bubble
gives a short hint that no API key is configured, with `API Key` in blue and underlined — clicking it
jumps to Settings and makes that card flash twice so you can see where to type. Save it and come back
to chat normally.

**Where your key goes**: the program calls the base URL you configured directly with your key. No
third-party server sits in between. ToolsGCP only puts the **resource library list and your
conversation** into the context; it never uploads your local files.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Ctrl+Q` | Open the search box from any program (configurable in Settings) |
| `Ctrl+Caps` | Open GCP-AI from any program, with the cursor already in the input box (configurable in Settings) |
| `Ctrl+J` | Start a new AI conversation (inside the ToolsGCP window only) |
| `Enter` / `Shift+Enter` | In the AI input box: send / newline |
| `Ctrl + Click` | Follow a link inside an AI answer (opens in the browser). A plain click does nothing, so selecting text never accidentally launches a browser |
| `F11` | Enter / leave fullscreen (hides the top title bar) |
| `Esc` | Leave fullscreen; when the AI drawer is open it collapses the drawer (on the history page it goes back to the chat first) |

## Plugins

A plugin is a folder under `plugins/`. ToolsGCP scans that folder at startup — **one folder = one plugin**.

```
plugins/
├─ README.md          Full plugin development guide
├─ _template/         Starter template (multi-file, multi-language); names starting with "_" are skipped
└─ hello-world/       Minimal example: two files are enough
```

### The smallest plugin

Two files:

```
plugins/my-plugin/
├─ manifest.json     plugin metadata
└─ app.py            entry file
```

`manifest.json`:

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

`app.py`:

```python
from PyQt5.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import SubtitleLabel


def create_page(context):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addWidget(SubtitleLabel("你好，ToolsGCP"))
    return page
```

Drop the folder into `plugins/`, open ToolsGCP → **Plugins** → **Reload**, and it appears.
After editing code you only need to press Reload again — no restart.

> **The one and only contract**: the entry file must define `create_page(context)` and it must return a `QWidget`.

`manifest.json` fields:

| Field | Required | Meaning |
|---|---|---|
| `id` | recommended | Unique id, 2–40 chars of lowercase letters / digits / `-` / `_`. Falls back to the folder name |
| `name` | recommended | Display name; falls back to `id` |
| `version` | no | Shown as `v1.0.0` |
| `author` | no | Shown next to the version |
| `description` | no | Two lines of text on the card |
| `entry` | no | Entry file name, default `app.py` |
| `icon` | no | Image path inside the plugin folder, or a FluentIcon name such as `TOOLS` |

The file name must be `manifest.json` (`plugin.json` is still recognised for very old plugins).
Folders whose name starts with `_` or `.` are skipped.

### Full template

Copy `_template/` and rename it to your plugin id. It splits the code into three layers:

| Layer | Files | Put here | Do not put here |
|---|---|---|---|
| Architecture | `app.py` | wiring modules, page structure, page switching | algorithms, large chunks of widget code |
| UI | `ui/*.py` | widgets, layout, showing data, collecting input | heavy computation, direct file access |
| Logic | `core/*.py` | algorithms, data processing, config, translation | any Qt widget |

When the UI needs a result it calls `self.logic.xxx()`, so the UI can be rewritten without touching logic.

### What `context` gives you

`context` is the only bridge between your plugin and ToolsGCP:

| Member | Meaning |
|---|---|
| `context.id` / `name` / `version` / `author` / `description` | plugin metadata |
| `context.plugin_dir` | the plugin folder (**read-only**, for assets) |
| `context.data_dir` | **writable** folder, already created for you — keep your config/cache here |
| `context.app_dir` | ToolsGCP program folder |
| `context.language` | current UI language, e.g. `简体中文` |
| `context.locale` | current language as a file name: `zh_CN` / `zh_TW` / `en_US` |
| `context.settings_manager` | ToolsGCP settings (`....settings` is a dict) |
| `context.favorites_manager` | favorites manager |
| `context.language_manager` | language manager (usually not needed) |
| `context.get_resources()` | the whole resource library as `list[dict]` |
| `context.log("message")` | write to the log (file **and** terminal); also `context.log(msg, level="err")` |

**Never write into the plugin folder** — it is read-only, and a plugin update would overwrite your data.
Write to `context.data_dir` instead: `.ToolsGCP/config/plugin_data/<plugin-id>/`.

### Localization

The template has it built in; you never test the language yourself. Put strings in
`lang/zh_CN.json`, `lang/zh_TW.json`, `lang/en_US.json`:

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

Missing keys fall back to `zh_CN` → `en_US` → the key name itself, so a missing translation never shows as blank.

### Available libraries

ToolsGCP ships **PyQt5** and **qfluentwidgets**; use them directly, nothing to install.
Prefer qfluentwidgets widgets so your page looks like part of the app.

### Managing and debugging

Inside ToolsGCP → **Plugins**:

| Item | What it does |
|---|---|
| **Reload** | rescan `plugins/` — pick up code changes without restarting |
| **Open plugin folder** | opens `plugins/` |
| **Dev guide** | shows a short version of the plugin manual |
| Search box | filter plugins by name, id or author |
| Layout button | switch between grid and list |
| Card toggle switch | enable / disable a plugin (a disabled plugin is dimmed; the folder stays on disk) |
| Delete button | delete a plugin (removes the whole folder) |

- A broken plugin **cannot** take down ToolsGCP: the error is caught and shown on that card (hover for the full traceback).
- `context.log()` output goes to `.ToolsGCP/logs/system_log.log`; filter plugin lines with
  `Select-String -Path .ToolsGCP\logs\system_log.log -Pattern '\[插件\|'`.

**Sharing / uninstalling**: zip the plugin folder (skip `__pycache__` and local data) and let others unzip it
into `plugins/`. To uninstall, delete the folder; plugin data lives in `.ToolsGCP/config/plugin_data/<plugin-id>/`.

> **Security**: a plugin is ordinary Python code with exactly the same permissions as ToolsGCP itself.
> Only install plugins you wrote or fully trust, and read `app.py` before installing.

The complete guide — every manifest field, the full `context` reference, `on_show()` hooks, the
config helper, asset handling and a full error-message troubleshooting table — is in
[`plugins/README.md`](plugins/README.md).

## Resource library format

`.ToolsGCP/ToolsGCP-Resources.json` holds every app entry:

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

Field notes:

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique, lowercase letters / digits / hyphens |
| `name` | yes | Display name |
| `code` | no | Auto-assigned unique code (`TG-000001`); the deploy list refers to apps by code |
| `category` / `tags` | no | Search page grouping and filter chips |
| `icon` | no | File name inside `metadata.icon_dir` |
| `url` / `github` / `download_url` / `author_url` / `chat_url` | no | Links shown as buttons on the card |
| `description` | no | One-line summary: shown on the card and as the small line in the detail page header |
| `intro` | no | "About" text: the body of the detail page's About block, longer than `description`; never shown on cards. Falls back to `description` when empty |
| `supplement` | no | Extra notes: never shown on cards, rendered as a second paragraph under the About text |
| `systems` | no | Supported platforms (multi): `全平台` / `Windows` / `macOS` / `Android` / `iOS` / `Linux` / `web` / `其他`; drives the search-page platform filter and a "Details" row |
| `architectures` | no | CPU architectures (multi): `x64` / `x86` / `arm64` / `arm` / `Apple Silicon` / `其他`; same usage |
| `listed_at` | no | When the entry was added (`YYYY-MM-DD HH:MM:SS`); the "updated time" filter uses it, and the detail page shows it down to the minute |

Everything except `id` and `name` may be omitted. ResourceMaker never deletes fields it does not
know about, so you can add your own keys safely.

### How the resource detail page uses these fields

Clicking a card on the search page opens the detail page, laid out top to bottom as:

| Block | Data source |
|---|---|
| Toolbar | Back / Favorite (unchanged) |
| Header (kept as-is) | `icon`, `name`, `code`, `description`, and the website / GitHub / author / chat buttons; a `tags` row was added here |
| **About** (new) | `intro` as the body (older entries without `intro` fall back to `description`); `supplement` is appended as a second paragraph when present |
| **Details** (new) | Key/value table: `systems` → `architectures` → `category` → `listed_at` → `url` → `github` |

Two rules:

1. **Render only what exists**: a missing or empty field means the whole row is absent — no
   "unknown / --" placeholders. An entry with `systems: []` is simply shorter, which is expected.
2. **Additive only**: the header (icon, name, code, description, the four link buttons) is
   untouched; the two new blocks sit below it.

`software version` and `file size` are intentionally **not** rendered: the library holds no factual
data for them and inventing rows would only produce a column of "unknown". To add them later,
insert one line into `DETAIL_ROW_DEFS` in `resource_detail_interface.py`.

## ResourceMaker

`ToolsGCP-ResourceMaker.pyw` is a standalone GUI (PyQt5 + PyQt-Fluent-Widgets, same as the main
app) with four pages. Its interface is in Simplified Chinese:

1. **制作资源 (Create)** — the form. Only **name** and **id** are required; every other field can
   be left empty and will simply be omitted from the JSON. The description counter allows up to
   100 characters, and there is an extra "补充" (supplement) box for anything longer.
2. **浏览 / 删除 (Browse / Delete)** — a table of the whole library. Double-click any cell to edit
   it in place; double-click the **icon** cell to pick a new image; the icon file is copied into
   `.ToolsGCP/Icon` and renamed to the app name automatically.
3. **批量合成 (Batch)** — merge one or many `resource.json` submissions into the local library, or
   merge several files into a new JSON.
4. **使用说明 (Help)** — the in-app manual.

### Icons

- Importing an image copies it into the resource library's icon folder immediately.
- Whatever the downloaded file was called, it is renamed to the **name** you typed
  (`LocalSend` → `LocalSend.png`). Changing the name later renames the file as well.
- If the target name is already used by **another** entry, ResourceMaker appends `-2`, `-3`… and
  never overwrites someone else's image. Replacing your own icon simply overwrites your own file.
- Every write is verified on disk, and the JSON always stores the file name that actually exists.

### Backups

Before each write, the current library is copied to
`.ToolsGCP/backups/ToolsGCP-Resources.backup-<timestamp>.json` and only the newest 20 files are
kept. Writes are atomic (a temporary file is written and then renamed), so an interrupted write
cannot corrupt the library. The library itself is always the single file
`.ToolsGCP/ToolsGCP-Resources.json` — ResourceMaker never creates a second library file.

## Logs

All output goes to the terminal and to a file in the same format:

```
.ToolsGCP/logs/system_log.log        current session
.ToolsGCP/logs/history/              archived sessions (max 30)
```

Search for errors and operations:

```powershell
Select-String -Path .ToolsGCP\logs\system_log.log -Pattern '\[ERROR\]|\[OP   \]'
```

See [`docs/LOGGING.md`](docs/LOGGING.md) for details.

## Documentation

| Document | Content |
|---|---|
| [`plugins/README.md`](plugins/README.md) | How to write a plugin (three steps) |
| [`docs/LOGGING.md`](docs/LOGGING.md) | Log format and troubleshooting |
| [`docs/SECURITY_AND_ENGINEERING.md`](docs/SECURITY_AND_ENGINEERING.md) | Security model, secrets, engineering rules |

## Contributing

1. Fork the repository and create a branch.
2. Keep the existing code style (Chinese comments, quiet helper functions, no new dependencies).
3. Test with `python ToolsGCP.pyw` and `python ToolsGCP-ResourceMaker.pyw` before opening a PR.
4. New resource entries are welcome as a `resource.json` file plus its icon.

## License

Released as free and open-source software. See the repository for the license text.

<div align="center">

**English** ｜ [简体中文](README.zh-CN.md) ｜ [繁體中文](README.zh-TW.md)

</div>
