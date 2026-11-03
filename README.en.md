<div align="center">

# ToolsGCP

![ToolsGCP logo](.ToolsGCP/logo.png)

[English](README.en.md) ｜ [简体中文](README.md) ｜ [繁體中文](README.zh-TW.md)

*A free, open-source toolbox launcher for Windows — every entry points straight to its official site or GitHub.*

</div>

---

## 目录

- [What is ToolsGCP](#what-is-toolsgcp)
- [Features](#features)
- [Project structure](#project-structure)
- [Technical notes](#technical-notes)
- [Requirements](#requirements)
- [Running](#running)
- [GCP-AI](#gcp-ai)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Plugins](#plugins)
- [Resource library format](#resource-library-format)
- [ResourceMaker](#resourcemaker)
- [Logs](#logs)

---

## What is ToolsGCP

ToolsGCP is a free and open-source toolbox launcher for Windows. It keeps a curated index of useful
programs and websites so you can find them, favorite them, and reinstall them on a new machine
without hunting for download pages.

- **Clean by design** — every entry links to the official website or the official GitHub repo. No bundles, no ads, no repackaged installers.
- **App deployment** — collect the software you use into a list; after a reinstall, restore the whole list in one go.
- **GCP-AI** — a built-in assistant. Describe what you need in plain words and it finds the matching entry in the resource library for you.
- **Plugin system** — one folder under `.ToolsGCP/plugins/` is one plugin (a manifest plus an optional HTML config page). Anyone can extend the app without touching the core.
- **ResourceMaker** — a small GUI tool that turns "I want this app listed" into a valid resource entry, including image import, tagging and a JSON writer.

## Features

| Area | What you get |
|---|---|
| Search | Keyword search (name / description / tag / code like `TG-000015`), category grouping, A–Z sort, favorites |
| Filters | Category, tag, source (site / repo / auto-download), favorites only, and **updated time** (latest / 10 days / 30 days / 6 months) |
| Cards | Responsive grid that adapts to the window; **two views — Tile (4 large cards per row) and Grid (6 small cards per row)**, switched from the right end of the toolbar; small / medium / large card sizes; optional animated GIF icons; an @-to-AI button on every card. The Grid view keeps only the favourite button and elides text that no longer fits |
| GCP-AI | Liquid floating orb in the bottom-right corner → chat drawer on the right; saved conversations (deleting one asks for confirmation first); a missing-API-Key hint that jumps straight to Settings; a **Polish** button at the right end of the input box (rewrites wording only, never sends, never enters history; can be turned off in Settings → GCP-AI) |
| Deployment | Build a deploy list from search results, then let ToolsGCP download and install later (**the deploy page now owns its list only and no longer interacts with favorites**) |
| Resource source | Settings → Downloads → Resource source: **cloud** (the newest library from GitHub Releases, betas included) or **local file**; when the cloud fetch fails the old cache and the local library stay in use, and a one-line cloud status is shown in Settings |
| Plugins | Grid or list layout, a **status badge in the top-right corner (enabled = green / disabled = red)**, a 20-character note you can edit in the bottom-left (clicking outside cancels it), disabled plugins shown dimmed, plus a search box; a plugin's config iframe **follows the host's dark theme / material / accent / language** |
| Notice | Content comes from GitHub issues labelled 公告 that were **opened by the repository owner** (one issue = one whole announcement, title + body rendered as-is). The sidebar entry carries a **WeChat-style red unread counter**; the **Mark all read** button in the top-right corner clears it; on startup, unread announcements pop up in the same in-window dialog style as "Check for updates". Read state lives in the data root's `config/announcements.json` |
| Favorites | Bilibili-style folders: a folder list on the left (the default folder cannot be deleted), a card grid on the right; create / rename / delete / batch-move. The whole page can be **exported to / imported from JSON** (import into an existing folder or create one; stars and lists refresh afterwards) |
| GCP Workshop | The page right below "Favorites" in the sidebar (by Galne563). **Currently empty** — only the title and credit are there; content will be added later |
| Sidebar AI | With "Use the sidebar AI page instead" enabled in Settings → GCP-AI, an "AI" page appears in the sidebar right below GCP Workshop (input box, send, new chat, history), and the floating ball disappears. Off by default. **Both forms share one conversation**: chat halfway in the floating-ball drawer, switch this page on in Settings (or the other way round), and the conversation you were in carries over |
| Link clicks | Every external link (detail page, search cards, AI answers, feedback page …): **left click** opens the browser and switches to it; **Ctrl+left click** opens it too but keeps this app in the foreground (browsers like to grab focus themselves — the app takes it back and stays put) |
| UI font | Settings → Appearance → Font: pick any installed font for the whole app; the first entry (Microsoft YaHei) is the default |
| Submit software | The last entry under **More** in the sidebar: it opens the built-in **resource maker** page (submission form / library browser / batch merge / built-in manual). The category is an **editable dropdown** (31 built-in categories + your own text, normalised before saving); **three-language fields** (Simplified / Traditional Chinese / English); **double-click** a row in the browser to edit it, and edit mode adds **Save back to original entry**; **Append to local library** and **Save as standalone library** both really write to disk and back up first |
| Settings | A section list on the left plus **one single scrollable page** on the right (clicking a section scrolls to it); the search box on top lists every match and lets you pick |
| Window | F11 switches to a real fullscreen that hides the top title bar but keeps the navigation rail; Esc exits; the borderless window **resizes from all four edges and corners and has no visible white / black border** |
| Logging | Unified log format in the terminal and in the data root's `logs/`, with rotating history files |

### Recent changes (R19)

- **Deployment page is deployment-only**: all favorites coupling was removed (the old "import favorites while importing a deploy list" block is gone).
- **Favorites: export / import**: export the whole library as JSON (`schema_version` + every folder and entry); importing can target an existing folder or a new one, then stars and lists refresh.
- **Submit software**: category is now an editable dropdown (31 built-ins + custom, normalised before saving); three-language fields; double-click a row in the browser to edit, with **Save back to original entry**; **Append to local library** / **Save as standalone library** are real writes with automatic backups; the old "load into the maker" flow is gone; preview/output scrolling, shadows, spacing and top-segment padding were unified.
- **Borderless window**: resize from all four edges and corners with no visible white / black border (the WebView2 is no longer inset; 8 transparent hotspots in the page call `window.start_resize` and the native resize loop takes over; DWM borders are disabled).
- **Plugin config page dark theme**: host and iframe sync theme / material / accent / language over `postMessage`, so switching takes effect immediately instead of leaving a white page.
- **`/plugin` is controlled by the Plugin Maker Helper only**: with only GCP-AI Agent enabled, typing `/` produces no hints and no blue command token; the two switches no longer link (the only remaining link is "enabling the helper also enables the Agent").
- **GCP-AI input "Polish"**: a new AI polish button on the right of the input box; can be turned off in Settings → GCP-AI.
- **Product boundaries**: the two txt files under `.ToolsGCP/legal/` (User Agreement, Privacy Policy & Disclaimer) are injected into the AI prompt at runtime — the text is **not** baked into the code, so changing terms means editing the txt only.
- **Cloud resource source**: picks the newest GitHub Release (betas included) by semver, downloads its `ToolsGCP-Resources.json`, validates it and atomically replaces the local cache; on failure the old cache and local library stay in use.
- **Settings → Resource source**: the long note became an inline tip (ⓘ) like other rows, the extra divider and the "feature under development" notice were removed, and a one-line cloud library status (version / count / updated time, or the failure reason) was added.
- **Announcements**: read state lives in the data root's `config/announcements.json`; delete the data root or that file and every announcement becomes unread and is pushed again.
- **Logging**: levels are INFO / OP / WARN / ERROR / DBG (DBG off by default); startup environment, window geometry and the exit sequence are logged item by item.

### Recent changes (R20)

- **Search icons**: card icons load eagerly now; a failed load retries twice with a cache-busting query before falling back to the initial letter — no more "only fixed after refreshing the state".
- **Window corners**: switched back to **rounded corners**. The tiny white/black corners were not caused by corner anti-aliasing but by the 1px "glass strip" left behind by pywebview's `shadow=True` (the desktop colour bled through the window edge) — setting the DWM border colour close to the page background removes it; DWM ignores corners automatically when maximized, and fullscreen explicitly uses square corners. The resize hot-zone approach is unchanged.
- **Plugins**: `gcp-ai-agent` is now displayed as **AI Agent**; both built-in plugins list **Galen563** as author; enabling Plugin Maker Helper also enables AI Agent, and disabling AI Agent also disables Plugin Maker Helper (enabling Agent alone does not enable the maker).
- **Favorites**: exporting now opens a folder picker first (default folder checked by default); the left action panel was redesigned into compact groups; favorites/customize cards are responsive to window width again.
- **Deploy page**: double-click a row to open that resource's detail page.
- **Submit Software**: localized fields are always on (the switch and the per-language "name" input were removed); the "exit editing" button was removed; all three languages still load from the resource JSON.
- **Plugin config page**: Esc returns to the plugin list; entering a page/config page no longer replays switch, segmented or nav indicator entrance animations.
- **Settings**: removed the redundant "resource source" heading and divider in Download; added a retry icon at the end of the cloud status row; hiding the rest of the GCP-AI section while "Enable GCP-AI" is off; hiding hotkey rows while global hotkeys are off; "Storage location" renamed to "Config storage"; "sidebar indicator bounce" now defaults to off; dependent rows in Startup/Animation are indented.
- **Cloud startup loading**: in cloud mode the app may wait for it (60s per attempt, up to 3 attempts) and then fall back to local with a reason.
- **GitHub Releases download (new)**: resources with a GitHub repo get a Releases entry that lists every release and asset; clicking an asset downloads it directly; filenames are matched by platform/arch/extension; a small download dot appears at the bottom-right and opens a standalone download page (left sidebar hidden, back + "Download" at the top-left, window buttons unchanged).
- **GCP-AI polish button**: moved **inside** the input box, bottom-right, so wrapped multi-line text never covers it.

## Project structure

```
ToolsGCP.pyw                       Entry point (double-click to run) — the **web build**
requirements.txt                   Dependencies (pywebview / bottle / pythonnet / Pillow / PyQt5)
README.md (Simplified Chinese, default) / README.zh-CN.md (English) / README.zh-TW.md (Traditional Chinese)
.ToolsGCP/desktop/                Desktop shell for the web build (assembly only, no business logic)
  shell.py                         Window assembly, startup sequence, tray / hotkeys / shutdown gate
  webhost.py                       Local WSGI server feeding webui/ and .ToolsGCP to WebView2
  api/                             The window.pywebview.api domains (app/window/i18n/log/shell/
                                   resources/favorites/settings/ai/clipboard)
  native/                          Native layer: tray, owner-drawn rounded menu, icons, DPI, clipboard, frame
.ToolsGCP/webui/                   Frontend (Vue3 runtime + hand-written components, **no build step**)
  index.html                       Single-file template (every page section lives here)
  js/app.js                        All frontend logic (classic script) + js/icons.js icon sprite
  css/                             variables / base / components / layout / animations / overlays
.ToolsGCP/                         All program files (**resource directory**; do not delete — runtime data lives in the data root, see below)
  ToolsGCP-Resources.json          The resource library (ResourceMaker reads/writes this exact path)
  logo.png                         Program / window icon
  images/                          Image assets
    icon/                          Icons referenced by the resource library (was .ToolsGCP/Icon)
    qq/                            Feedback page QR codes
  modules/                         Business code and language files (pymodels core / utils + languages)
  plugins/                         Built-in plugins (one folder = one plugin; the web build only reads manifest / config.html / lang)
  legal/                           Product boundaries: User Agreement / Privacy Policy (injected into the AI prompt at runtime; text is not in code)
  config/                          Runtime configuration (actually stored in the **data root**, see below; created on first run)
    toolsgcp_config.json           Settings (encrypted API key, base URL, model name)
    favorites.json                 Favorites
    deploy_config.json             Deploy list
    plugins.json                   Plugin enabled / disabled state
    plugin_notes.json              Per-plugin notes
    announcements.json             Announcement read state (delete it = everything unread again)
    privacy_policy.json            Privacy-policy consent record
    plugin_data/<plugin-id>/       Per-plugin writable data folder
    chats/                         GCP-AI conversation history (one JSON per conversation)
    cloud/                         Cloud library cache (library JSON + metadata)
  logs/                            Runtime logs and history
.github/workflows/release.yml      GitHub Actions: pushing a v* tag builds the exe and publishes it
py版本-已弃用仅作为参考项目，主体转为web版本/
                                   The old PyQt5 desktop build (**reference only**, not executed)
项目资料-文档与开发测试/             Design docs, regression scripts, build tools (not executed)
```

> **The data root (user data) and the `.ToolsGCP` next to the program are two different things.**
> Configuration, favorites, logs, AI chats and announcement read state live in `<home>\.ToolsGCP` by
> default (created automatically on first run). `<home>\ToolsGCP.json` is the **location pointer**
> that records where the data root is — it stays in the home folder and never moves.
> You can relocate the data root in Settings → Storage (that migrates the data root, not the program
> directory).
>
> The `.ToolsGCP/` next to the program is the **resource directory**: modules / images / plugins /
> resource library / legal / logo. It ships with the program, is never moved, and is not a config
> directory; deleting it breaks the program (deleting the data root only resets settings, favorites,
> logs and announcement read state).
>
> **Icon path changed**: `.ToolsGCP/Icon/` -> `.ToolsGCP/images/icon/`; the canonical URL is
> `/res/image/icon/<file>` (`/res/icon/<file>` is kept as a compatibility alias).
>
> Only the PyQt UI layer (`interfaces/ ui/ widgets/`), the Qt entry point and old backups were moved into
> the reference folder. `pymodels/core` and `pymodels/utils` **stay** under `.ToolsGCP/modules/` because the
> web build reuses them for all business logic (resource queries, favorites, settings, AI sessions, logging).

## Technical notes

The program is **a Python desktop shell + a local HTTP server + a build-free frontend**, in three layers:
Python handles windows, the tray, hotkeys and native abilities; the UI is plain HTML / CSS / JS; business
logic reuses the same `pymodels` pure-Python modules.

### Three layers and the JS ↔ Python bridge

- **Shell**: `pywebview` (WebView2 on Windows) with a borderless, custom-drawn title bar. Tray, global
  hotkeys, DPI and the window-frame patch are implemented directly on Win32 APIs (ctypes / pythonnet) in
  `desktop/native/` — no Qt involved.
- **Local server**: a small `bottle` WSGI app (`desktop/webhost.py`) serves `webui/`, `images/`, the resource
  library and plugin config pages to WebView2. Each domain of `window.pywebview.api` (`resources` /
  `favorites` / `settings` / `ai` / `maker` / `plugins` …) is the JS ↔ Python bridge.
- **Frontend**: Vue 3 runtime (`vue.global.prod.js`, shipped with the repo) plus hand-written components,
  **no build step** — edit a file under `.ToolsGCP/webui/` and refresh the window. Page sections, the icon
  sprite and CSS variables are all hand-written.
- **JSON envelope**: backend methods only return JSON-serialisable dicts, `{ok: true, ...}` /
  `{ok: false, error: "…"}`. The frontend goes through `bridge.tryCall()`; **a missing method returns
  `null` and the caller must degrade explicitly** ("interface not ready") instead of pretending success.
  Business fields are named `success` so they never shadow the envelope's `ok`.

### Borderless window: resizable, with no visible border

`pywebview`'s `frameless=True` turns the window into `WS_POPUP`: no resize border, no snap-to-maximize and no
system shadow. `desktop/native/frame.py` restores it in three steps:

1. add `WS_THICKFRAME` (and friends) back → the system provides native resize gestures on all edges/corners;
2. subclass the window procedure and return 0 from `WM_NCCALCSIZE` → the system-painted border is swallowed
   and the client area covers the whole window;
3. pin the maximized size to the **current monitor's work area** in `WM_GETMINMAXINFO` → after adding
   `WS_THICKFRAME` the window no longer covers the taskbar; DWM transition animations and borders are off.

Resize hotspots live **in the page**, not as an inset WebView2: 8 transparent `span`s in `index.html`
(4 edges + 4 corners) take `pointerdown` and call `window.start_resize(direction)` → native
`WM_NCLBUTTONDOWN` modal resize, the same system loop as dragging the title bar. **Why not inset the
WebView2**: an inset leaves a strip of the parent window's background around the window, and the title bar is
a translucent gradient under the Glass/Acrylic materials — no solid colour matches, which is exactly what
users saw as "white / black edges / a thicker border". Now WebView2 fills the window, there is no coloured
strip, and resizing still feels native.

### Theme, material and accent colour

All colours live as CSS variables in `webui/css/variables.css` (a dark and a light set of `--page` / `--text` /
`--accent` …). At runtime only three attributes on `<html>` change:

- `data-theme="dark|light"`: dark / light theme ("follow system" is resolved through `matchMedia` into a
  concrete value);
- `data-fx="mica|glass|acrylic"`: theme effect (Mica / Glass / Acrylic) — only blur, grain and highlight
  edges change;
- `data-accent="blue|purple|orange"`: component accent colour.

A plugin config page is an iframe: on load and whenever theme / material / accent / language change, the host
`postMessage`s `{type:'toolsgcp-theme', theme, fx, accent, language}` to it and the page immediately updates its
own `<html>`; reading the parent document stays as a first-frame fallback only. That is why the config page no
longer stays white in dark mode.

### Data and performance

- **Search / filter / sort / group are delegated to the backend's `resources.query`** (the single source of
  truth), and the frontend never re-implements the algorithm. The card list is a **virtual list** that only
  renders rows near the viewport and recomputes row heights only on resize.
- **Favorites have one source of truth** (`favorites.*`): card stars, the favorites page and the detail page
  share the same state, and every write refreshes all of them. Export is JSON with `schema_version`; import
  accepts folder arrays, code arrays and item arrays.
- **Cloud resource source**: `resources.cloud_status()` only reads the local cache (no network, never blocks
  Settings); `resources.cloud_refresh(force)` does the real GitHub fetch — list releases (betas included),
  pick the newest by semver, find `ToolsGCP-Resources.json` among the assets, validate it and **atomically
  write** it into the data root's `config/cloud/`. On failure the old cache and the local library stay in use;
  the first screen only reads the cache and a background thread checks on an interval.
- **Announcement read state** exists only in the data root's `config/announcements.json`: delete the data root
  or that file and everything becomes unread and is pushed again; the old backup next to the program is never
  reverse-migrated back.

### How ResourceMaker writes and backs up

Every write goes through `maker.*`: the entry is first run through `resource_schema.normalize()`, then
written with an atomic temporary-file + `os.replace` swap; before the swap the old library is copied to
`ToolsGCP-Resources.backup-<timestamp>.json` and only the newest 20 are kept. **Save back to original entry**
writes using the id / code it loaded, so changing the id in the form cannot append a duplicate.
**Save as standalone library** also copies the icon into the target folder and rewrites `icon`, so it never
writes a JSON whose icon points at nothing.

### GCP-AI prompt layering

The system prompt is assembled from four layers (`modules/pymodels/core/ai/prompt.py`): role and built-in
knowledge → reply mode (Concise / Standard / Professional) → hard rules (no code, no restating the question,
links must be complete) → resource catalogue (compressed by keyword, at most 120 / 40 entries). An
`@resource(code)` mention acts as a strong "this exact entry" instruction. The two agreement texts under
`.ToolsGCP/legal/*.txt` are read from disk and injected at runtime (**the text is not in code**, so editing
terms only means editing the txt), letting the AI explain which boundary was crossed and why. The **Polish**
button next to the input box is a separate small request: it only rewrites wording, never answers and never
enters the chat history.

### Localization and logging

- Text lives under `.ToolsGCP/modules/languages/{zh_CN,zh_TW,en_US}/` — **15 modules × 3 single-language
  directories** (each file holds one language only). The backend falls back "current language → Simplified
  Chinese → English", and the frontend renders from the same bundle.
- Log format is fixed: `[time] [level] [zh category|en subcategory] message key=value`; levels are INFO / OP
  (operation audit) / WARN / ERROR / FATAL, DBG is off by default (developer mode can enable it); secret
  fields are redacted; startup environment, window geometry and the exit sequence are logged item by item;
  history archives rotate with a cap.

## Requirements

- Windows 10 / 11
- Python 3.10 or newer (tested on 3.13)
- Runtime dependencies (installed from `requirements.txt`):

```bash
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

## Running

```bash
python ToolsGCP.pyw
```

Or double-click `ToolsGCP.pyw` in Explorer. To edit the resource library, open **More → Submit software**
inside the app (the built-in resource maker); there is no separate exe or script any more.

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
| Settings → API Key → **Model select** | Dropdown only: lists the models this provider supports (follows the provider). Per official docs V4.1-Flash's API name is `deepseek-flash`; the app converts it internally, so the UI shows/picks `deepseek-v4.1-flash` | `deepseek-v4.1-flash` (default) |
| Settings → API Key → **Model Name** | Type any custom model id (local / relay / gateway models go here) |
| Settings → API Key → **API Base URL** | OpenAI-compatible base URL, usually ending in `/v1`. Filled from the provider, editable | `https://api.deepseek.com/v1` |
| Settings → API Key → **API Key** | Your key. **Encrypted with Windows DPAPI and stored as `api_key_enc` in `config/toolsgcp_config.json`** — the ciphertext cannot be decrypted on another machine | empty |
| Settings → AI → **Reply Mode** | Controls answer **length and detail** — see the table below | Standard |
| Settings → AI → **Context Window** | How much history is sent with each question: the whole session (default, longest memory) / last 10 / 20 / 30 rounds | whole session |
| Settings → Model Calling → Limit token output | Cap the length of a single answer | off |

Built-in providers and their common models (all editable):

| Provider | Base URL | Common models |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-v4.1-flash` (default; sent as the official API name `deepseek-flash`), `deepseek-v4-pro` |
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

A plugin is a folder under `.ToolsGCP/plugins/`. ToolsGCP scans it at startup — **one folder = one plugin**.

The web build treats plugins differently from the old PyQt build, so read this first:

- **It only reads `manifest.json` (plus `lang/` and an optional `config.html`) and never imports the plugin's
  Python.** `app.py` with `create_page(context) → QWidget` is the PyQt entry point; the web build does not load
  it — importing PyQt5 on the main thread crashes WebView2 — so a web plugin's UI is written in **HTML**.
- A plugin's switch, icon, description and config screen all come from the manifest; the switch value itself
  is stored in the **app settings** (see `enabled_setting`).

```
.ToolsGCP/plugins/
├─ README.md         full guide for the *PyQt* plugin API (create_page / context, reference only)
├─ _template/        PyQt-era starter template (leading "_", **never loaded**)
├─ plugin-showcase/  showcase (also never loaded)
├─ gcp-ai-agent/     built-in: manifest + config.html + lang/
├─ gcp-plugin-maker/ built-in: manifest + config.html + lang/ + core/
└─ my-plugin/        yours: manifest.json is required, everything else is optional
```

> `_template` / `plugin-showcase` / anything starting with `_` or `.` are reserved
> (`plugin_manager.RESERVED_DIR_NAMES`): not scanned, not listed, no data folder — the files stay as they are.

### The smallest plugin

A single `manifest.json` is enough to be recognised:

```
.ToolsGCP/plugins/my-plugin/
├─ manifest.json    plugin metadata (**required**)
├─ config.html      config screen (optional; without it the "Config" button does not appear)
└─ lang/            three languages (optional)
   ├─ zh_CN.json
   ├─ zh_TW.json
   └─ en_US.json
```

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "author": "Your name",
  "description": "One line about what it does",
  "enabled_setting": "my_plugin_enabled",
  "config_page": "config.html",
  "builtin": false
}
```

Drop the folder into `.ToolsGCP/plugins/` → open ToolsGCP → **Plugins** → **Reload** and it appears.
After editing `manifest.json` / `config.html`, press Reload again — no restart.

`manifest.json` fields (what the web build actually reads):

| Field | Required | Meaning |
|---|---|---|
| `id` | recommended | Unique id, 2–41 chars of lowercase letters / digits / `-` / `_` (must start with a letter or digit). Falls back to the folder name; if duplicated, the first one scanned wins |
| `name` | recommended | Display name. Either a plain string or an i18n dict `{"简体中文": "…", "English": "…"}` |
| `version` | no | Shown as `v1.0.0`; omitted when empty |
| `author` | no | Shown next to the version |
| `description` | no | Two lines of text on the card; also supports the i18n dict form |
| `entry` | no | PyQt entry file name (default `app.py`). **The web build does not load it**; kept so one folder can still be used by the PyQt build |
| `icon` | no | Image path relative to the plugin folder, e.g. `assets/icon.png` (served as `/res/plugins/<id>/<icon>`; FluentIcon names are a PyQt-only thing and are not resolved by the web build) |
| `enabled_setting` | no | Declares **which settings key** owns this plugin's on/off switch, e.g. `gcp_plugin_maker_enabled`. **Without it the card switch cannot be toggled** (it only reports that no switch is configured) |
| `config_page` | no | HTML path relative to the plugin folder (e.g. `config.html`). Only then is the card's **Config** button enabled; the page opens in an iframe inside the content area |
| `default_disabled` | no | Used when there is no `enabled_setting` to decide the initial switch state (built-in plugins default to `true`) |
| `builtin` | no | Built-in / protected: the trash button is greyed out and the backend refuses to delete it (official ids are also hard-coded in `desktop/api/plugins.py`) |
| `companion` | no | Another plugin id: **enabling this plugin also enables it** (not the other way round) |
| `generated_by` | no | Which plugin generated this one (currently the Plugin Maker Helper); disabling the generator disables its generated plugins too |

The file must be named `manifest.json` (`plugin.json` is still accepted for very old plugins, but new plugins
should use `manifest.json`). Folders starting with `_` or `.` are skipped; **a folder without `manifest.json`
is invisible in the plugin center** (the frontend renders every card from the manifest) — fix the file and
press Reload.

### Full template

For the web build the best reference is the **built-in plugins themselves**:

| Reference | What it contains | What to copy |
|---|---|---|
| `gcp-ai-agent/` | `manifest.json` + `config.html` + `lang/*.json` | A complete config screen: master switch, per-item switches, stats, recent actions, theme sync |
| `gcp-plugin-maker/` | the same plus `core/` (standard-library Python) | How to involve the backend: it loads `core/` through `importlib` as a synthetic package (**built-in plugins only**) |
| `_template/` | the PyQt multi-file template (`app.py` / `ui/` / `core/`) | Only useful when writing for the PyQt build; the web build does not load it |

> Why `_template` and `plugin-showcase` are never loaded: they are in the reserved list — templates only,
> never listed, never toggled, and they get no data folder.

### What a config page can use

The web build has **no** `create_page(context)` entry point: the plugin UI is just `config.html`, an ordinary
web page. It is same-origin with the app (both served by the local WSGI server), so it can use:

| Available | Notes |
|---|---|
| Its own files | relative paths just work: `manifest.json`, `lang/zh_CN.json`, `assets/icon.png` … |
| Host APIs | `parent.pywebview.api.<domain>.<method>(…)`. pywebview only injects `window.pywebview` into the top frame, so an iframe must go through `parent`; `settings.get/set`, `resources.*`, `ai.*` … are the same domains the main UI uses |
| Host events | `parent.ToolsGCP.on('settings-changed', (payload) => …)` when the backend broadcasts; otherwise poll as a fallback (both built-in plugins use "event + 5 s polling") |
| Theme sync | the host `postMessage`s `{type:'toolsgcp-theme', theme, fx, accent, language}` when the iframe finishes loading and whenever theme / material / accent / language change; the page then updates its own `<html data-theme data-fx data-accent>` (for the first frame it may also read `parent.document.documentElement`'s `data-theme`, falling back to `matchMedia` when opened standalone) |
| Window size | plain `window.innerWidth/innerHeight`; the page adapts inside the content area |

⚠️ The web build exposes **no** "plugin-owned writable folder" to third-party plugins (`context.data_dir` /
`context.log` from the PyQt build do not exist here). Persist data through settings or APIs the host already
exposes; never write into the plugin folder (it is a read-only resource area and updates/repairs would
overwrite it).

### Localization

Put strings in `lang/zh_CN.json`, `lang/zh_TW.json`, `lang/en_US.json` as a flat key/value map:

```json
{
  "title": "My Plugin",
  "greet": "Hello, {name}!"
}
```

Lookup order is **current language → Simplified Chinese → English → the key itself**, so a missing string is
never blank. `_template/core/i18n.py` has a ready-made `I18n` class you can copy (with `{placeholder}`
substitution):

```python
i18n = I18n(plugin_dir, "zh_TW")
i18n.t("title")              # → 我的外掛 / 我的插件 / My Plugin
i18n.t("greet", name="小明")  # → 你好，小明！
```

`name` / `description` in the manifest may also be i18n dicts (keys are language names
`简体中文` / `繁體中文` / `English`; `zh_CN`-style locale keys are accepted too).
The app's own UI strings live under `.ToolsGCP/modules/languages/{zh_CN,zh_TW,en_US}/` —
**do not add plugin strings there**; keep them in your plugin's `lang/`.

### Available libraries

- A plugin UI is **plain HTML / CSS / JS with no build step**: hand-write it, or drop any frontend library
  into the plugin folder and reference it locally (do not use a CDN — offline it would stay blank).
- **Do not use PyQt5 / qfluentwidgets**: the web build never executes a plugin's Python entry, and importing
  PyQt5 on the main thread crashes WebView2.
- Exception: the built-in `gcp-plugin-maker` has a standard-library-only `core/` that the backend loads on
  demand (`importlib` + a synthetic package name). Third-party plugins currently have **no** such channel.

### Managing and debugging

Inside ToolsGCP → **Plugins** (also under **More → Plugins**):

| Item | What it does |
|---|---|
| **Reload** | rescan `.ToolsGCP/plugins/` — pick up manifest / config.html changes without restarting |
| **Open plugin folder** | opens `.ToolsGCP/plugins/` |
| **Dev guide** | a short version of the conventions: manifest fields, three-language packs, `enabled_setting`, `config_page` |
| Search box | filter plugins by name, id or author |
| Layout button | switch between grid and list |
| Card switch | only usable when the plugin declares `enabled_setting`; it writes that settings key, shared with Settings and the linkage rules |
| Config button | only enabled when the plugin declares `config_page`; opens in an iframe inside the content area, following the host's dark theme / material / accent / language |
| Delete button | greyed out for built-in / protected plugins; otherwise asks for confirmation and only removes a real first-level folder under `plugins/` |

Linkage rules (all driven by manifest declarations, no plugin names hard-coded):

- **Switch**: the `enabled_setting` key is shared between the plugin card and Settings;
- **Companion**: enabling A also enables B when A declares `companion: B` (never the reverse);
- **Generated plugins**: disabling the generator also disables plugins whose `generated_by` points at it;
- **`/plugin` is controlled by the Plugin Maker Helper only**: only when `gcp_plugin_maker_enabled` is on does
  typing `/` in a GCP-AI input box show hints, turn `/plugin` blue and send it to the model. Enabling GCP-AI
  Agent alone does not count.

Debugging and sharing:

- The config page is an ordinary web page: reload it (press Reload again or reopen the config screen). Backend /
  app logs live in the data root's `logs/` (default `<home>\.ToolsGCP\logs`).
- A broken plugin cannot take down the app: if the manifest fails to parse, the plugin center simply does not
  show it (fix and reload); JS errors inside a config page only affect that iframe.
- **Sharing / uninstalling**: zip the plugin folder (skip `__pycache__`) and let others unzip it into
  `.ToolsGCP/plugins/`; to uninstall, delete the folder.

> **Security**: a plugin config page is a web page that can call every API the frontend exposes. Only install
> plugins you wrote or fully trust, and read its `config.html` before installing.

The complete **PyQt-build** plugin guide — `create_page(context)`, the full `context` reference, `on_show()`
hooks and a troubleshooting table — is in [`.ToolsGCP/plugins/README.md`](.ToolsGCP/plugins/README.md); for the
web build this chapter is authoritative.

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

There is a single entry point: **More → Submit software** in the sidebar, which writes straight into the
library (there is no standalone exe any more). Four pages:

1. **Create** — the form. Only **name** and **id** are required; every other field can be left empty and
   will simply be omitted from the JSON. The description counter allows up to 100 characters, and there is
   an extra "supplement" box for anything longer. The category is an **editable dropdown**: 31 built-in
   categories plus free text, normalised before saving (so "工具" and "工具 " never become two categories).
   Name / description / supplement all support **three-language fields** (Simplified Chinese, Traditional
   Chinese, English) stored in one entry.
2. **Browse / Library** — a table of the whole library. **Double-click** a row to edit it (no in-place cell
   editing); edit mode adds **Save back to original entry**, which writes to the entry you loaded (same
   id / code, original `listed_at` preserved) instead of appending a duplicate. Double-click the **icon**
   cell to pick a new image; the file is copied into `.ToolsGCP/images/icon` and renamed to the app name.
3. **Batch** — merge one or many `resource.json` submissions into the local library, or merge several files
   into a new JSON.
4. **Help** — the in-app manual.

There are two write targets: **Append to local library** (writes `.ToolsGCP/ToolsGCP-Resources.json`) and
**Save as standalone library** (a system "Save as" dialog; the JSON and its icons are copied to the chosen
folder). Both really write to disk — neither is a "here is a JSON, put it back yourself" export.

### Icons

- Importing an image copies it into the resource library's icon folder immediately.
- Whatever the downloaded file was called, it is renamed to the **name** you typed
  (`LocalSend` → `LocalSend.png`). Changing the name later renames the file as well.
- If the target name is already used by **another** entry, ResourceMaker appends `-2`, `-3`… and
  never overwrites someone else's image. Replacing your own icon simply overwrites your own file.
- Every write is verified on disk, and the JSON always stores the file name that actually exists.

### Backups

Before each write, the current library is copied to
`ToolsGCP-Resources.backup-<timestamp>.json` next to it, and only the newest 20 files are
kept. Writes are atomic (a temporary file is written and then renamed), so an interrupted write
cannot corrupt the library. The library itself is always the single file
`.ToolsGCP/ToolsGCP-Resources.json` — ResourceMaker never creates a second library file.

## Logs

All output goes to the terminal and to a file in the same format (files live in the **data root**,
default `<home>\.ToolsGCP\logs`):

```
<data root>/logs/system_log.log       current session
<data root>/logs/history/             archived sessions (rotated with a cap)
```

Search for errors and operations:

```powershell
Select-String -Path "$HOME\.ToolsGCP\logs\system_log.log" -Pattern '\[ERROR\]|\[OP   \]'
```

Levels are `INFO` / `OP` (operation audit) / `WARN` / `ERROR` / `FATAL`, `DBG` is off by default (developer
mode can enable it), and secret fields are redacted. See
[`项目资料-文档与开发测试/docs/LOGGING.md`](项目资料-文档与开发测试/docs/LOGGING.md) for the full format and
troubleshooting guide.
