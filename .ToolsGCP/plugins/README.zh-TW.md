# ToolsGCP 插件开发文档

> [简体中文](README.md) ｜ **繁體中文** ｜ [English](README.en.md)

這個目錄放外掛。**一個資料夾 = 一個外掛**，ToolsGCP 啟動時自動掃描。

```
plugins/
├─ README.md          ← 簡體中文完整文件
├─ README.zh-TW.md    ← 你正在看的這份（繁體中文）
├─ README.en.md       ← English
├─ _template/         ← 開發者範本（底線開頭，不會被載入）
└─ plugin-showcase/   ← py 版時代的完整範例（**也不會被載入**）
```

---

## ⚠️ 最重要的一件事：外掛有**兩個**存放位置

程式**同時掃描兩個目錄**，兩邊都能生效：

| | 位置 | 給誰用 | 能不能寫 |
|---|---|---|---|
| ① 內建目錄 | `<程式目錄>\.ToolsGCP\plugins\` | 隨程式發佈的官方外掛 | 原始碼執行時可寫；**exe 打包後多半唯讀** |
| ② 使用者目錄 | `<資料根>\plugins\` = 預設 `%USERPROFILE%\.ToolsGCP\plugins\` | **開發者 / 使用者自己裝的外掛** | 永遠可寫（程式啟動時自動建立） |

- **優先順序：② > ①**。同名外掛（同資料夾名）以使用者目錄那份為準，內建那份被「遮住」但不會被刪除。
- 兩處**都會載入**，不是「只認一個」。
- 外掛頁右上角「開啟外掛目錄」按鈕開啟的是 ②（使用者可寫的那個）。
- 外掛頁底部會顯示 ② 的完整路徑，照著複製進去即可。

> **為什麼必須有 ②？** exe 打包後，① 被塞進了 exe 本體所在目錄：
> 裝在 `Program Files` 時無法寫入、程式升級會整體覆蓋、使用者根本「放不進去」。
> ② 在使用者資料根裡，跟著「設定 → 儲存」的資料根遷移一起走，寫進去的東西不會丟。
>
> **開發時的建議**：想改官方外掛做除錯，把它的資料夾**複製到 ②** 再改 ——
> ② 優先順序高，你的版本會生效，刪掉 ② 那份就自動回退到官方版本（內建那份受保護，刪不掉）。

---

> ⚠️ **先看清你要做的是哪一版的外掛 —— 這兩套機制目前完全不通用。**
>
> | | Web 版（**目前發佈的主體**） | py(QuQt) 版（唯讀存檔，已棄用） |
> |---|---|---|
> | 誰在掃目錄 | `desktop/api/plugins.py` | `pymodels/core/plugin_manager.py` |
> | 真正載入什麼 | `manifest.json` + `config.html`（iframe） | `app.py` 的 `create_page(context) -> QWidget` |
> | 開關怎麼生效 | manifest 的 `enabled_setting` 指向一個設定鍵 | `PluginManager.disabled` 集合 |
> | `app.py` / `ui/` / `core/` | **一行都不執行** | 全部執行 |
>
> 也就是说：**只抄 py 版那一套（`create_page`），在 Web 版裡會得到一個
> 「外掛列表裡有、⚙ 按鈕是灰的、開關撥不動、介面一片空」的空殼。**
> 這不是 bug，是護欄：Web 版主執行緒 import PyQt5 會讓 WebView2 初始化崩潰
> （見根目錄 AGENTS.md 第 8 節）。
>
> - **做 Web 版外掛 → 看下面「零、Web 版外掛」那一節**，只要三個檔案。
> - 給舊 py 版寫外掛 → 從第五節往後看（那些 API 在 Web 版裡不會被呼叫）。

> ⚠️ **`_template` 和 `plugin-showcase` 都不會被程式載入。**
> 它們只是**給你照著寫的範本**：不出現在外掛列表、不會被啟停、也沒有自己的資料目錄。
> 想讓某個目錄不被載入，把名字改成底線開頭。

- 只想跑起來看看 → 看 [零](#零web-版外掛目前主體) 和 [二](#二放進程式裡看效果)
- 準備寫正式外掛 → 從 [三](#三正式開發用-_template) 開始
- 卡住了 → [六、常見坑與錯誤對照表](#六常見坑與錯誤對照表)

> 📄 **關於章節完整度**：這份繁體中文版聚焦 **Web 版外掛**（目前發佈的主體）的實作與排錯。
> 簡體中文版 [`README.md`](README.md) 另有 py(QuQt) 舊版的 `create_page(context)` /
> `context` API / 資源庫資料結構等歷史章節 —— 那些**只對已棄用的 py 版有效，Web 版不會執行**。
> 要查那部分請看簡中版。

---

## 零、Web 版外掛（目前主體）

Web 版**不需要你寫一行 Python**。一個外掛最少只要兩樣東西：

```
plugins/<你的外掛id>/
├─ manifest.json      ← 必須（沒這個檔案 = 列表裡根本不出現）
└─ config.html        ← 選用：⚙ 按鈕開啟的設定頁（iframe 載入）
```

`manifest.json` 裡 Web 版真正讀的欄位只有這幾個：

| 欄位 | 作用 | 不寫會怎樣 |
|---|---|---|
| `id` | 外掛唯一標識（建議與目錄名一致） | 用**目錄名**代替 |
| `name` / `description` | 卡片上的名稱與說明，可為字串，也可為 `{"简体中文": …, "English": …}` | 名稱退回 id |
| `icon` | 相對於外掛目錄的圖片路徑 | 卡片沒圖 |
| `config_page` | **設定頁 HTML** 的相對路徑 | ⚙ 按鈕是灰的，點不進去 |
| `enabled_setting` | 那個開關寫進哪個**設定鍵** | 開關撥不動 |
| `default_disabled` | 沒有開關鍵時的預設狀態 | 預設為「已啟用」 |
| `builtin` | 標記為官方內建，**拒絕刪除** | 使用者可以把它刪掉 |
| `companion` / `generated_by` | 啟停連動 | 不連動 |

設定頁那一側只有三條硬規矩（照 `_template/config.html` 寫就行，它已經三條都實作好了）：

1. **自帶樣式、不連網、不引 webui 的 CSS/JS** —— 它是 iframe，要能獨立執行；
   純瀏覽器開啟時拿不到介面，會自動降級成「預覽模式 + 唯讀」。
2. **讀寫設定只走宿主介面**：`window.pywebview.api.settings.get(key)` /
   `settings.set(key, value)`。iframe 裡沒有 `window.pywebview`（pywebview 只往主框架
   注入），所以要回退 `parent.pywebview.api`。回傳值是 `{ok: …}` 信封；
   ⚠️ **別把 `ok` 當業務欄位名**（會被信封覆蓋）。
3. **主題跟宿主走**：監聽宿主 postMessage 的
   `{type:'toolsgcp-theme', theme, fx, accent, language}`，首幀先讀父文件的
   `data-theme` 兜底。關閉本頁用
   `window.parent.postMessage({type:'toolsgcp-close-plugin', id}, '*')`。

開關的值就是一個布林設定鍵，會落進 `<資料根>/config/settings.json`，所以
「關掉程式後開關還在」是正常行為。要存外掛自己的資料，用同一個 settings 域
存一個帶外掛 id 前綴的鍵即可。

> 從 `_template` 複製著做 Web 版外掛時，**必改三處**並且保持一致：
> 目錄名、`manifest.id`、`manifest.enabled_setting`
> （命名慣例 `plugin_<id 裡的 - 換成 _>_enabled`）。
> 三個裡漏一個，就會出現「兩個外掛共用同一份設定/同一個開關」的怪事。

---

## 一、最少的外掛長什麼樣

```
plugins/hello/
└─ manifest.json
```

```json
{
  "id": "hello",
  "name": "Hello",
  "version": "1.0.0",
  "description": "最小可用外掛",
  "config_page": "config.html",
  "enabled_setting": "plugin_hello_enabled",
  "default_disabled": true
}
```

只有 `manifest.json` 也能被掃到：列表裡會出現，但 ⚙ 是灰的（因為沒有 `config_page`）、
開關也撥不動（因為沒有 `enabled_setting`）。所以實務上**這兩個欄位一定要寫**。

---

## 二、放進程式裡看效果

1. 把外掛資料夾放進**使用者外掛目錄**：`%USERPROFILE%\.ToolsGCP\plugins\`
   （程式啟動時自動建立；也可以在**外掛頁**點「開啟外掛目錄」直接開啟它）
   - 原始碼執行時放進本目錄（`<程式目錄>\.ToolsGCP\plugins\`）同樣有效，
     但建議養成放使用者目錄的習慣 —— exe 版只有那個位置可寫
2. 開啟 ToolsGCP → 左側欄「更多」→「外掛」
3. 點「重新載入」
4. 列表裡就會出現你的外掛

改完程式碼**不用重啟程式**，再點一次「重新載入」即可。

---

## 三、正式開發用 `_template`

複製 `_template` 整個資料夾、改成你的外掛 id（英文小寫，例如 `my-tool`），然後照下面的分工寫：

```
_template/
├─ manifest.json        外掛基本資訊（改這裡填你的資訊）
├─ config.html          ★ Web 版真正載入的設定頁（iframe）—— 做 Web 版外掛改這個就夠
├─ app.py               ★ 程式基本架構（**只有 py 版會執行**）
├─ core/                ★ 邏輯層（**只有 py 版會執行**）
├─ ui/                  ★ 介面層（**只有 py 版會執行**）
├─ lang/                多語言文案（zh_CN / zh_TW / en_US）
└─ assets/              圖片等唯讀資源
```

> ⚠️ `app.py` / `core/` / `ui/` 這套 Python 分層是 **py(QuQt) 版架構，Web 版一行都不執行**
> （主執行緒 import PyQt5 會讓 WebView2 崩潰，見 AGENTS.md 第 8 節）。
> 做 **Web 版**外掛只要兩樣：`manifest.json` + `config.html`。

### `config.html` 寫法要點

- 自帶 `<!doctype html>`、`<meta charset>`、全部樣式，**不要**引用外部的 css/js。
- 版面要能塞進外掛頁裡的 iframe（寬度自適應，不要寫死 `width: 1200px`）。
- 主題色用宿主傳來的值；拿不到就用父文件的 `data-theme` 兜底，避免「白一下」。
- 所有會失敗的操作（讀設定、寫設定）都要 try/catch 並在畫面上給回饋，
  寫失敗要**回滾** UI 到操作前的狀態。

---

## 四、manifest.json 欄位（一個一個說）

| 欄位 | 必填 | 說明 |
|---|---|---|
| `id` | 建議 | 唯一標識，2~41 字元；不寫就用目錄名 |
| `name` | 建議 | 卡片名稱，字串或三語字典 |
| `version` | 建議 | 顯示在卡片上 |
| `author` | 選用 | 作者 |
| `description` | 選用 | 說明，字串或三語字典 |
| `icon` | 選用 | 相對路徑，例如 `assets/icon.png` |
| `config_page` | **強烈建議** | 設定頁 HTML 的相對路徑 |
| `enabled_setting` | **強烈建議** | 開關對應的設定鍵 |
| `default_disabled` | 選用 | `true` = 預設關閉 |
| `builtin` / `protected` | 官方外掛用 | `true` 時拒絕刪除 |
| `companion` / `generated_by` | 選用 | 啟停連動的 id |

⚠️ 多語言欄位可寫 `{"简体中文": "…", "繁體中文": "…", "English": "…"}`；
取值順序是 **目前語言 → 簡體中文 → English → 鍵名本身**。

---

## 五、`create_page(context)` 的約定（僅 py 版）

```python
def create_page(context):
    return MyPage(context)      # 必須回傳 QWidget
```

⚠️ **Web 版永遠不會呼叫這個函式。** 這段只對舊 py(QuQt) 版有效，
放在這裡是為了讓「同時相容兩版」的外掛有依據。

---

## 六、常見坑與錯誤對照表

| 現象 | 原因 | 怎麼修 |
|---|---|---|
| 外掛列表裡沒有我的外掛 | 資料夾沒放對位置 / 名字以 `_` 開頭 / 沒有 `manifest.json` | 放進使用者外掛目錄；確認有 `manifest.json` |
| 列表有，但 ⚙ 是灰的 | manifest 沒有 `config_page`，或檔案不存在 | 補上 `config_page` 並確認那個檔名對 |
| 開關撥不動 | manifest 沒有 `enabled_setting` | 補上，並確認值是唯一的 |
| 點 ⚙ 一片空白 | `config.html` 報錯 / 引用了外部資源 | 用瀏覽器直接開那個檔案看 console |
| 兩個外掛共用一個開關 | `enabled_setting` 撞了 | 每個外掛用 `plugin_<id>_enabled` |
| 改了程式碼沒生效 | 沒點「重新載入」/ 瀏覽器快取 | 點「重新載入」（Web 版已停用快取） |
| exe 版放不進去 | 放到了 ① 內建目錄（唯讀） | 改放 ② 使用者外掛目錄 |

---

## 七、發給別人 / 卸載

- **發佈**：把你外掛的資料夾整個打包（至少要 `manifest.json`，
  建議連 `config.html` 和 `assets/` 一起），別人解壓到
  `%USERPROFILE%\.ToolsGCP\plugins\` 即可。
- **卸載**：在外掛頁點刪除按鈕（只會刪使用者目錄那份）；
  或直接刪掉 `%USERPROFILE%\.ToolsGCP\plugins\<id>\` 資料夾。
- **官方內建外掛刪不掉**（受保護）。想讓它失效就把它關掉，或在 ② 放一個同名資料夾覆蓋。

---

## 八、安全提醒

外掛的 `config.html` 是在**你的程式裡**執行的頁面，雖然有 iframe 隔離，
但它仍然能呼叫宿主介面。**只裝你信任的來源的外掛。**
官方外掛（`builtin: true`）隨程式發佈；第三方外掛請自己確認來源。
