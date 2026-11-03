# ToolsGCP Plugin Developer Guide

> [简体中文](README.md) ｜ [繁體中文](README.zh-TW.md) ｜ **English**

This folder holds plugins. **One folder = one plugin**, scanned automatically at startup.

```
plugins/
├─ README.md          ← Simplified Chinese (complete)
├─ README.zh-TW.md    ← Traditional Chinese
├─ README.en.md       ← the file you are reading (English)
├─ _template/         ← developer skeleton (underscore prefix = never loaded)
└─ plugin-showcase/   ← legacy example from the py(QuQt) era (**also never loaded**)
```

---

## ⚠️ The single most important thing: plugins live in **two** locations

The app scans **both** directories, and both work:

| | Location | Who uses it | Writable? |
|---|---|---|---|
| ① built-in | `<program dir>\.ToolsGCP\plugins\` | official plugins shipped with the app | writable when running from source; **usually read-only in a packaged exe** |
| ② user | `<data root>\plugins\` = by default `%USERPROFILE%\.ToolsGCP\plugins\` | **plugins installed by developers / users** | always writable (auto-created at startup) |

- **Precedence: ② beats ①.** If two plugins share a folder name, the user copy wins and the
  built-in one is *shadowed* (not deleted).
- **Both are loaded** — it is not "pick one".
- The **Open plugins folder** button on the Plugins page opens ② (the writable one).
- The Plugins page shows the full path of ② at the bottom; copy your folder there.

> **Why is ② required?** In a packaged exe, ① ends up inside the exe's own directory:
> it is not writable when installed under `Program Files`, it gets overwritten by upgrades,
> and users simply *cannot put anything there*. ② lives in the user data root, follows the
> data-root migration in **Settings → Storage**, and never loses what you put in it.
>
> **Tip for development:** to debug an official plugin, copy its folder into ② and edit it
> there. ② has higher precedence, so your version is used; delete the ② copy and the official
> version comes back (the built-in one is protected and cannot be deleted).

---

> ⚠️ **Know which plugin system you are targeting — they are completely separate.**
>
> | | Web edition (**what ships today**) | py(QuQt) edition (read-only archive, deprecated) |
> |---|---|---|
> | Who scans the folder | `desktop/api/plugins.py` | `pymodels/core/plugin_manager.py` |
> | What is actually loaded | `manifest.json` + `config.html` (iframe) | `create_page(context) -> QWidget` in `app.py` |
> | How the toggle works | manifest `enabled_setting` points at a settings key | `PluginManager.disabled` set |
> | `app.py` / `ui/` / `core/` | **never executed** | all executed |
>
> In other words: **copying the py-edition style (`create_page`) gives you an empty shell in the
> Web edition** — it shows up in the list, but the ⚙ button is greyed out, the toggle does nothing,
> and the panel is blank. That is not a bug, it is a guard rail: importing PyQt5 on the main thread
> crashes WebView2 initialisation (see AGENTS.md §8).
>
> - **Web-edition plugin → read section 0 below**, you only need three files.
> - Legacy py edition → the `create_page` sections (only relevant to the archive).

> ⚠️ **`_template` and `plugin-showcase` are never loaded.** They are skeletons to copy from:
> they do not appear in the list, cannot be toggled, and get no data folder of their own.
> To exclude any folder from loading, prefix its name with an underscore.

- Just want to see something work → sections [0](#0-web-edition-plugins-current-main) and [2](#2-installing-it-and-seeing-it-work)
- Writing a real plugin → start at [3](#3-use-_template-for-real-development)
- Stuck → [6](#6-common-problems-and-fixes)

> 📄 **About completeness**: this English edition focuses on **Web-edition plugins** (what ships
> today) — implementation and troubleshooting. The Simplified Chinese [`README.md`](README.md)
> additionally documents the legacy py(QuQt) `create_page(context)` / `context` API / resource
> database schema. Those chapters **only apply to the deprecated py edition and are never executed
> by the Web edition**; consult the Chinese version for that material.

---

## 0. Web-edition plugins (current main)

The Web edition **does not require a single line of Python**. A plugin needs two things:

```
plugins/<your-plugin-id>/
├─ manifest.json      ← required (without it the plugin never shows up)
└─ config.html        ← optional: the settings page opened by the ⚙ button (loaded in an iframe)
```

These are the only `manifest.json` fields the Web edition actually reads:

| Field | Purpose | If omitted |
|---|---|---|
| `id` | unique identifier (keep it equal to the folder name) | the **folder name** is used |
| `name` / `description` | card title/description, string or `{"简体中文": …, "English": …}` | falls back to the id |
| `icon` | image path relative to the plugin folder | no card icon |
| `config_page` | relative path of the **settings page HTML** | ⚙ button is greyed out |
| `enabled_setting` | which **settings key** the toggle writes to | the toggle does nothing |
| `default_disabled` | default state when no settings key exists | defaults to "enabled" |
| `builtin` | marks an official plugin, **deletion refused** | users can delete it |
| `companion` / `generated_by` | cascade enable/disable | no cascade |

There are only three hard rules for the settings page (`_template/config.html` already
implements all three — copy it):

1. **Self-contained styles, no network, do not reference webui CSS/JS** — it is an iframe and
   must run standalone; opened directly in a browser it degrades to "preview mode + read-only".
2. **Read/write settings only through the host API**:
   `window.pywebview.api.settings.get(key)` / `settings.set(key, value)`.
   An iframe has no `window.pywebview` (pywebview only injects into the main frame), so fall
   back to `parent.pywebview.api`. Returns are `{ok: …}` envelopes —
   ⚠️ **never use `ok` as a business field name** (it would be overwritten).
3. **Follow the host theme**: listen for the host's
   `{type:'toolsgcp-theme', theme, fx, accent, language}` postMessage, and on the first frame
   read the parent document's `data-theme` as a fallback. Close the page with
   `window.parent.postMessage({type:'toolsgcp-close-plugin', id}, '*')`.

The toggle value is a boolean settings key stored in `<data root>/config/settings.json`, so
"the switch is still there after a restart" is expected behaviour. To store plugin-specific
data, use the same settings domain with a key prefixed by your plugin id.

> When copying `_template` for a Web-edition plugin, you **must change three things** and keep
> them consistent: the folder name, `manifest.id`, and `manifest.enabled_setting`
> (convention: `plugin_<id with - replaced by _>_enabled`).
> Missing one of them causes "two plugins sharing the same config/toggle".

---

## 1. The smallest possible plugin

```
plugins/hello/
└─ manifest.json
```

```json
{
  "id": "hello",
  "name": "Hello",
  "version": "1.0.0",
  "description": "Minimal working plugin",
  "config_page": "config.html",
  "enabled_setting": "plugin_hello_enabled",
  "default_disabled": true
}
```

A plugin with only `manifest.json` is still discovered: it appears in the list, but the ⚙
button is greyed out (no `config_page`) and the toggle does nothing (no `enabled_setting`).
In practice you should always provide those two fields.

---

## 2. Installing it and seeing it work

1. Put the plugin folder into the **user plugin directory**: `%USERPROFILE%\.ToolsGCP\plugins\`
   (created automatically at startup; you can also open it with **Open plugins folder** on the
   Plugins page).
   - Putting it in this repo's `.ToolsGCP\plugins\` also works when running from source,
     but prefer the user directory — it is the only writable place in a packaged exe.
2. Open ToolsGCP → sidebar **More** → **Plugins**
3. Click **Reload**
4. Your plugin appears in the list.

No restart needed after code changes — just click **Reload** again.

---

## 3. Use `_template` for real development

Copy the whole `_template` folder, rename it to your plugin id (lowercase ASCII, e.g.
`my-tool`), then follow the layout:

```
_template/
├─ manifest.json        plugin metadata (edit this)
├─ config.html          ★ the settings page the Web edition actually loads (iframe)
├─ app.py               ★ py edition only — never executed by the Web edition
├─ core/                ★ py edition only
├─ ui/                  ★ py edition only
├─ lang/                translations (zh_CN / zh_TW / en_US)
└─ assets/              read-only resources such as images
```

> ⚠️ The `app.py` / `core/` / `ui/` Python layering is **py(QuQt)-edition architecture and is
> never executed by the Web edition** (importing PyQt5 on the main thread crashes WebView2,
> see AGENTS.md §8). A **Web-edition** plugin only needs `manifest.json` + `config.html`.

### Notes for writing `config.html`

- Include `<!doctype html>`, `<meta charset>` and all styles inline — do **not** reference
  external css/js.
- The layout must fit inside the iframe on the Plugins page (responsive width; never hard-code
  `width: 1200px`).
- Use the theme values sent by the host; fall back to the parent document's `data-theme` to
  avoid a flash of the wrong colour.
- Wrap every fallible operation (reading/writing settings) in try/catch and give visible
  feedback; **roll the UI back** if a write fails.

---

## 4. `manifest.json` fields

| Field | Required | Notes |
|---|---|---|
| `id` | recommended | unique id, 2–41 chars; defaults to the folder name |
| `name` | recommended | card title, string or a 3-language dict |
| `version` | recommended | shown on the card |
| `author` | optional | author |
| `description` | optional | description, string or 3-language dict |
| `icon` | optional | relative path, e.g. `assets/icon.png` |
| `config_page` | **strongly recommended** | relative path of the settings page HTML |
| `enabled_setting` | **strongly recommended** | settings key backing the toggle |
| `default_disabled` | optional | `true` = disabled by default |
| `builtin` / `protected` | for official plugins | `true` refuses deletion |
| `companion` / `generated_by` | optional | cascade enable/disable ids |

⚠️ Localised fields may be written as
`{"简体中文": "…", "繁體中文": "…", "English": "…"}`; lookup order is
**current language → Simplified Chinese → English → the key itself**.

---

## 5. The `create_page(context)` contract (py edition only)

```python
def create_page(context):
    return MyPage(context)      # must return a QWidget
```

⚠️ **The Web edition never calls this function.** It only applies to the legacy py(QuQt)
edition; it is documented so plugins that target both remain possible.

---

## 6. Common problems and fixes

| Symptom | Cause | Fix |
|---|---|---|
| Plugin missing from the list | wrong folder / name starts with `_` / no `manifest.json` | put it in the user plugin dir; make sure `manifest.json` exists |
| Listed but ⚙ is greyed out | no `config_page`, or the file does not exist | add `config_page` and check the filename |
| Toggle does nothing | no `enabled_setting` | add it; make sure the key is unique |
| ⚙ opens a blank page | `config.html` throws / references external assets | open that file directly in a browser and read the console |
| Two plugins share one toggle | duplicate `enabled_setting` | use `plugin_<id>_enabled` per plugin |
| Code changes have no effect | forgot **Reload** / browser cache | click **Reload** (caching is disabled in the Web edition) |
| Cannot install into the exe version | you used ① (read-only) | use ②, the user plugin directory |

---

## 7. Sharing / uninstalling

- **Sharing**: zip your plugin folder (`manifest.json` at minimum; include `config.html` and
  `assets/`). Others unzip it into `%USERPROFILE%\.ToolsGCP\plugins\`.
- **Uninstalling**: use the delete button on the Plugins page (only the user copy is removed),
  or delete `%USERPROFILE%\.ToolsGCP\plugins\<id>\`.
- **Built-in official plugins cannot be deleted** (protected). Disable them instead, or place a
  same-named folder in ② to override.

---

## 8. Security note

A plugin's `config.html` runs inside your app. Although it is sandboxed in an iframe, it can
still call the host API. **Only install plugins from sources you trust.**
Official plugins ship with `builtin: true`; verify the origin of anything third-party.
