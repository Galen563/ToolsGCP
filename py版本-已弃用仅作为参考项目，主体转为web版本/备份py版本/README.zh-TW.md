<div align="center">

# ToolsGCP

<img src=".ToolsGCP/logo.png" alt="ToolsGCP logo" width="140">

[English](README.md) ｜ [简体中文](README.zh-CN.md) ｜ **繁體中文**

*免費開源的 Windows 工具箱啟動器 —— 每條資源都直達官網或 GitHub。*

</div>

---

## ToolsGCP 是什麼

ToolsGCP 是一款免費開源的 Windows 工具箱啟動器。它維護一份整理好的程式 / 網站索引，讓你快速找到、
收藏，並在換電腦後一次把常用軟體裝回來，不必到處找下載頁。

- **純淨無捆綁** —— 每條資源都直達官網或官方 GitHub 倉庫，不夾帶、不劫持、不用二次打包的安裝檔。
- **應用部署** —— 把常用軟體整理成清單，重裝系統後一鍵還原。
- **GCP-AI** —— 內建 AI 助手。說一句「我想要個能做某件事的軟體」，它直接從資源庫裡找出來告訴你。
- **外掛系統** —— 往 `plugins/` 放一個資料夾就是一個新頁面，任何人都能擴充，不用改核心程式。
- **資源製作器** —— 一個小工具，把「我想讓這個軟體被收錄」變成一份規範的資源資料，圖片匯入、標籤、寫 JSON 全包。

## 功能一覽

| 模組 | 內容 |
|---|---|
| 首頁 | 頂部輪播圖（5 張，每 3 秒自動翻頁，圓點分頁可點），下面是「推薦外掛」——本機 `plugins/` 裡的外掛一覽，點一下進外掛中心 |
| 搜尋 | 關鍵字搜尋（名稱 / 簡介 / 標籤 / 編碼如 `TG-000015`）、依類別分組、A–Z 排序、收藏 |
| 篩選 | 類別、標籤、來源（有官網 / 有倉庫 / 可自動下載）、僅看收藏，以及**更新時間**（最新 / 10 天前 / 30 天前 / 半年前） |
| 卡片 | 自適應網格隨視窗變化；**磁貼（一行 4 個大卡片）/ 網格（一行 6 個小卡片）兩種檢視**，工具列最右邊切換；小 / 中 / 大三種卡片尺寸；支援動態 GIF 圖示；每張卡片有「@給AI」按鈕。網格檢視只保留收藏按鈕，文字放不下會自動省略 |
| GCP-AI | 右下角液態懸浮球 → 右側聊天抽屜；歷史對話頁（刪除對話會二次確認）；訊息可複製 / 重寫 / 重新生成（帶版本翻頁）；未設定 API Key 時點提示直達設定 |
| 部署 | 從搜尋結果或收藏夾整理部署清單，之後由 ToolsGCP 負責下載安裝 |
| 外掛 | 井字 / 清單兩種排版，**卡片右上角的狀態徽章（已啟用綠 / 已停用紅）**，左下角可寫 20 字備註（點輸入框外面自動取消），停用後整張卡片變暗，還能搜尋外掛 |
| 公告 | 內容來自 GitHub 上帶「公告」標籤、且**作者本人發的** Issue（一條 Issue = 一整條公告，標題 + 正文原樣顯示）。左側欄「公告」上有像微信那樣的**紅色未讀數**；右上角「全部已讀」把未讀歸零；啟動時若有未讀，用「檢查更新」那種視窗內彈窗提示 |
| 提交軟體 | 左側欄「更多」最下面一條，打開內建的**資源製作器頁面**（投稿表單 / 資源瀏覽器 / 批次合成 / 使用說明），做的稿子直接進 `.ToolsGCP/ToolsGCP-Resources.json` |
| 設定 | 左側板塊清單 + 右側**一整頁**（點左側捲到對應板塊）；頂部可搜設定項，命中會全部列出來讓你挑 |
| 視窗 | F11 進入真全螢幕並隱藏頂部標題列（保留左側導覽列），Esc 離開 |
| 日誌 | 終端與 `.ToolsGCP/logs/` 雙寫，格式統一，歷史歸檔最多 30 份 |

## 專案結構

```
ToolsGCP.pyw                   主程式（雙擊執行）
ToolsGCP-ResourceMaker.pyw     資源製作器（做 / 改資源條目）
requirements.txt               相依套件
README.md                      README（English）
README.zh-CN.md                README（简体中文）
README.zh-TW.md                README（繁體中文）
plugins/                       外掛目錄（見 plugins/README.md）
  _template/                   自己寫外掛的範本
  hello-world/                 極簡範例外掛
  plugin-showcase/             完整範例外掛：示範 context 能拿到的一切
docs/                          文件
  LOGGING.md                   日誌格式與排查方法
  SECURITY_AND_ENGINEERING.md  安全模型與工程規範
.ToolsGCP/                     程式資料（請勿刪除）
  ToolsGCP-Resources.json      資源庫（所有應用都在這裡，製作器依這個固定路徑讀寫）
  privacy_policy.json          隱私政策同意記錄
  logo.png                     程式圖示 / 視窗圖示
  Icon/                        資源庫裡引用的圖示
  modules/                     核心 Python 模組與語言檔
  backups/                     資源庫自動備份（只留最近 20 份）
  logs/                        執行日誌與歷史歸檔
  config/                      程式自己寫出來的設定（首次執行自動建立）
    toolsgcp_config.json       設定（含加密後的 API Key、介面位址、模型名稱）
    favorites.json             收藏夾
    deploy_config.json         部署清單
    plugins.json               外掛啟用 / 停用狀態
    plugin_notes.json          外掛卡片上的備註
    plugin_data/<外掛id>/       外掛自己的資料目錄
    chats/                     GCP-AI 的歷史對話（每次對話一個 json）
```

> **`.ToolsGCP/config/` 裡只放「程式自己寫出來」的檔案。**
> 資源庫、隱私政策記錄、圖示、語言檔、日誌都不屬於這裡，它們在 `.ToolsGCP/` 下原地不動 ——
> 這些檔案由製作器或安裝包管理，挪動位置會讓另一個程式找不到它們。
>
> 舊版本（設定平鋪在 `.ToolsGCP/` 根目錄）升級上來時，程式會在啟動階段把這幾個檔案
> **自動搬進 `config/`**，你的設定與收藏夾不會遺失，日誌裡會記一筆 `[資料目錄] migrate_file`。

## 執行環境

- Windows 10 / 11
- Python 3.10 以上（在 3.13 上測試）
- 只有兩個執行相依：

```bash
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

## 執行

```bash
python ToolsGCP.pyw
```

也可以直接在檔案總管雙擊 `ToolsGCP.pyw`。要改資源庫就執行：

```bash
python ToolsGCP-ResourceMaker.pyw
```

## GCP-AI

內建的 AI 助手，**預設關閉**。到「設定 → AI」打開「開啟GCP-AI」，右下角會出現一顆緩慢流動的液態懸浮球。

### 怎麼用

1. 點右下角的球（或按 `Ctrl+Caps`），右側滑出聊天抽屜；
2. 在底部輸入框裡說人話，例如：
   - 「我想要一個能區域網路傳檔的工具」
   - 「有什麼好用的螢幕錄影軟體？」
   - 「minecraft 啟動器有哪些？」
3. 它會拿你這句話去對照 ToolsGCP 的資源庫，把命中的條目的**簡介、分類、標籤、官網與 GitHub** 給你。

`Enter` 傳送，`Shift+Enter` 換行，`Esc` 收起抽屜（在歷史對話頁按 `Esc` 是**先返回聊天**，
再按一次才收起）。抽屜開啟時那顆球會隱藏，收起後自動回來。

頂欄三個按鈕：

| 按鈕 | 作用 |
|---|---|
| `＋` | 開一個新對話（也可以按 `Ctrl+J`） |
| 🕘 | 打開**歷史對話**頁：每則對話一張卡片，卡片裡是對話內容（過長用 `…` 省略），右下角是**開始時間 → 結束時間**，越早的對話越靠下；點任一張就把那次對話載回來 |
| `×` | 收起抽屜（`Esc` 相同） |

歷史頁左上角是一個**左箭頭按鈕**（沒有文字），點它或按 `Esc` 返回聊天。

每次重新打開 ToolsGCP 都會自動開一個新對話，先前的對話都留在歷史裡（存在
`.ToolsGCP/config/chats/`，一次對話一個 json）。

### 設定

| 設定在 | 說明 | 預設 |
|---|---|---|
| 設定 → API Key → **服務商** | 選 DeepSeek / OpenAI / Claude / Grok / Kimi / 通義千問 / 矽基流動 / 自訂。選完下面的模型與介面位址**自動填好** | DeepSeek |
| 設定 → API Key → **模型名稱** | 可編輯下拉框：列出該服務商常用模型，也可以自己敲任意模型名稱 | `deepseek-v4.1-flash`（V4.1-Flash） |
| 設定 → API Key → **介面位址** | OpenAI 相容格式的位址，通常以 `/v1` 結尾。跟著服務商自動填，也可以自己改 | `https://api.deepseek.com/v1` |
| 設定 → API Key → **API Key** | 你的金鑰。**以 Windows DPAPI 加密後存在 `config/toolsgcp_config.json` 的 `api_key_enc`**，密文換台電腦解不開 | 空 |
| 設定 → AI → **回覆模式** | 控制回答的**長度與細節**，見下表 | 標準 |
| 設定 → AI → **上下文範圍** | 每次提問帶多少歷史對話給模型：整個會話（預設，記憶最長）/ 最近 10 / 20 / 30 輪 | 整個會話 |
| 設定 → 模型呼叫 → 限制 token 輸出 | 限制單次回答的最大長度 | 關閉 |

內建服務商與常用模型（都可以自己改）：

| 服務商 | 介面位址 | 常用模型 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-v4.1-flash`（V4.1-Flash，預設）、`deepseek-v4-pro`、`deepseek-v4-flash` |
| OpenAI | `https://api.openai.com/v1` | `gpt-5.1`、`gpt-5.1-mini`、`gpt-4.1` |
| Anthropic（Claude） | `https://api.anthropic.com/v1` | `claude-sonnet-4-6`、`claude-opus-4-1`、`claude-haiku-4-5` |
| xAI（Grok） | `https://api.x.ai/v1` | `grok-4`、`grok-4-fast`、`grok-3` |
| Kimi | `https://api.moonshot.cn/v1` | `kimi-k3`、`kimi-k2.7-code`、`kimi-k2.6` |
| 通義千問 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3-max`、`qwen-plus`、`qwen-flash` |
| 矽基流動 | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3`、`Qwen/Qwen3-8B` 等（以主控台為準） |
| 自訂 | 自己填 | 本機 Ollama / vLLM / one-api / 中轉站等，填到 `/v1` 為止 |

> 模型名稱變化比軟體發版快，所以兩個框都是**可編輯**的：清單裡沒有的直接敲進去。
> OpenAI / Claude / Grok 的官方介面在國內多數網路下需要自備網路環境，
> 連不上時會給出明確的錯誤提示（認證失敗 / 頻率限制 / 逾時 / 連不上分別提示）。

### 每則訊息可以做什麼

每條氣泡下面都有一條小按鈕列，使用者訊息靠右、AI 訊息靠左：

| 按鈕 | 在哪 | 作用 |
|---|---|---|
| ✎ | 使用者訊息（左） | **重寫**：把這則訊息放回輸入框，改完重送；舊回答會被丟掉，舊版本仍可翻回查看 |
| ⧉ | 兩邊都有 | **複製**這則訊息的純文字 |
| ⟳ | AI 訊息（右） | **重新生成**：用同一個問題再問一次；按下去按鈕會變成轉圈的進度環 |
| ‹ 2/3 › | 中間 | 同一個位置有**兩個以上版本**時出現（重寫過 / 重新生成過）。左右箭頭翻版本，到頭/到尾時對應箭頭變灰；載入歷史對話時預設翻到最新那一版 |

> 版本資訊**只存在記憶體裡**，`config/chats/*.json` 裡永遠只保存目前選中的那一版，
> 舊檔案格式完全沒變。

### @ 提到某條資源

搜尋頁與收藏頁的**每張資源卡片右下角多了一個 @ 按鈕**（氣泡圖示）：

- 點它 → 自動開啟 AI 抽屜，並在輸入框**末尾**追加 `@名稱(資源編碼)`，例如 `@LocalSend(TG-000001)`；
- 輸入框已有內容時是**追加**在末尾，不會覆蓋你已經打的字；
- 接著補一句話送出，AI 就知道你說的是庫裡那一條，回答會圍繞它展開；
- 也可以自己手打 `@OBS` 這種形式。

### 回覆模式

| 模式 | 回答長什麼樣 |
|---|---|
| **簡潔** | 最多 4 行，只給結論：哪個 + 做什麼 + 一個連結。不要分類、優缺點、對比 |
| **標準** | 6 行以內：推薦（名稱 + 一句話）+ 官網連結 + 一個備選 |
| **專業** | 10 行左右：先結論，再關鍵差異（適用場景、是否開源、有無中文介面…），最後 1~2 個備選 |

三種模式共同遵守的硬規矩：**絕不輸出程式碼**（程式碼區塊、命令、腳本、設定片段一律不給）、
不用表格與標題、不複述你的問題、不寫客套話，連結必須是完整 `http(s)` 位址。

**沒設定 API Key 會怎樣**：可以直接傳訊息，但它不會去呼叫模型，而是在氣泡裡給一句短提示
「還沒設定 API Key，填好就能聊。」，其中藍字底線的 `API Key` 可以點 —— 點了會跳到設定頁，
並把那張卡片閃兩下指給你看。設定好儲存後回來就能正常聊。

**API Key 走哪條路**：程式直接用你的金鑰請求你填的那個介面位址，中間不經過任何第三方伺服器；
ToolsGCP 只把**資源庫清單和你的對話**放進上下文，不會上傳你的本機檔案。

## 快速鍵

| 按鍵 | 作用 |
|---|---|
| `Ctrl+Q` | 在任何程式裡呼出搜尋框（可在設定裡改） |
| `Ctrl+Caps` | 在任何程式裡呼出 GCP-AI，直接把游標放進輸入框（可在設定裡改） |
| `Ctrl+J` | 開一個新的 AI 對話（只在 ToolsGCP 視窗內生效） |
| `Enter` / `Shift+Enter` | AI 輸入框：傳送 / 換行 |
| `Ctrl + 左鍵` | 外鏈（AI 回答、詳情頁、搜尋卡片…）：瀏覽器照常開啟，但 ToolsGCP 留在前景；單擊左鍵則是開啟並切到瀏覽器 |
| `F11` | 進入 / 離開全螢幕（會隱藏頂部標題列） |
| `Esc` | 離開全螢幕；AI 抽屜開啟時先收起抽屜（歷史對話頁則是先返回聊天） |

## 外掛

一個外掛就是 `plugins/` 下的一個資料夾，ToolsGCP 啟動時自動掃描 —— **一個資料夾 = 一個外掛**。

```
plugins/
├─ README.md          外掛開發完整文件
├─ _template/         開發者範本（多檔案、多語言）；底線開頭不會被載入
└─ hello-world/       極簡範例：兩個檔案就能跑
```

### 最少的外掛

兩個檔案：

```
plugins/我的外掛/
├─ manifest.json     外掛基本資訊
└─ app.py            入口檔案
```

`manifest.json`：

```json
{
  "id": "my-plugin",
  "name": "我的外掛",
  "version": "1.0.0",
  "author": "你的名字",
  "description": "一句話說明",
  "entry": "app.py"
}
```

`app.py`：

```python
from PyQt5.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import SubtitleLabel


def create_page(context):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addWidget(SubtitleLabel("你好，ToolsGCP"))
    return page
```

放進 `plugins/` → 打開 ToolsGCP →「外掛」→「重新載入」就出現了。改完程式只要再點一次「重新載入」，不必重啟。

> **唯一的約定**：入口檔案裡必須有 `create_page(context)`，而且它要回傳一個 `QWidget`。

`manifest.json` 欄位：

| 欄位 | 必填 | 說明 |
|---|---|---|
| `id` | 建議填 | 外掛唯一識別，2~40 位小寫字母/數字/`-`/`_`；留空就用資料夾名 |
| `name` | 建議填 | 卡片上顯示的名稱；留空則顯示 `id` |
| `version` | 否 | 顯示成 `v1.0.0` |
| `author` | 否 | 顯示在版本旁邊 |
| `description` | 否 | 卡片上的兩行說明 |
| `entry` | 否 | 入口檔名，預設 `app.py` |
| `icon` | 否 | 外掛目錄裡的圖片路徑，或 FluentIcon 的名字（如 `TOOLS`） |

檔名必須是 `manifest.json`（很舊的 `plugin.json` 也還認）。資料夾名以 `_` 或 `.` 開頭會被跳過。

### 正式開發用範本

複製 `_template/` 改個名就是你的外掛，它把程式分成三層：

| 層 | 檔案 | 該放什麼 | 不該放什麼 |
|---|---|---|---|
| 架構 | `app.py` | 組裝模組、組織頁面結構、頁面切換 | 演算法、大段控件程式 |
| 介面 | `ui/*.py` | 控件、佈局、顯示資料、收集輸入 | 複雜計算、直接讀寫檔案 |
| 邏輯 | `core/*.py` | 演算法、資料處理、設定讀寫、翻譯 | 任何 Qt 控件 |

介面要算東西就呼叫 `self.logic.xxx()`，以後介面重寫邏輯不用動。

### context 能拿到什麼

`context` 是外掛和 ToolsGCP 之間唯一的介面：

| 成員 | 說明 |
|---|---|
| `context.id` / `name` / `version` / `author` / `description` | 外掛資訊 |
| `context.plugin_dir` | 外掛目錄（**唯讀**，放資源） |
| `context.data_dir` | **可寫**目錄，已自動建好，設定與快取寫這裡 |
| `context.app_dir` | ToolsGCP 程式目錄 |
| `context.language` | 目前介面語言，如 `简体中文` |
| `context.locale` | 目前語言對應的檔名：`zh_CN` / `zh_TW` / `en_US` |
| `context.settings_manager` | ToolsGCP 設定（`.settings` 是字典） |
| `context.favorites_manager` | 收藏夾管理器 |
| `context.language_manager` | 語言管理器（一般用不到） |
| `context.get_resources()` | 整個資源庫，`list[dict]` |
| `context.log("訊息")` | 寫日誌（**檔案 + 終端都輸出**），也可 `context.log(msg, level="err")` |

**絕對不要往外掛目錄裡寫東西** —— 那是唯讀的，而且更新外掛會把你的資料覆蓋掉。
要寫就寫 `context.data_dir`：`.ToolsGCP/config/plugin_data/<外掛id>/`。

### 多語言

範本內建了，**不用自己判斷語言**。文案放 `lang/zh_CN.json`、`zh_TW.json`、`en_US.json`：

```json
{
  "title": "我的外掛",
  "greet": "你好，{name}！"
}
```

```python
i18n = I18n(context.plugin_dir, context.locale)
i18n.t("title")                # → 我的外掛 / 我的外掛 / My Plugin
i18n.t("greet", name="小明")    # → 你好，小明！
```

找不到的句子會依序回退 `zh_CN` → `en_US` → 鍵名本身，不會顯示成空白。

### 能用什麼函式庫

ToolsGCP 內建 **PyQt5** 和 **qfluentwidgets**，外掛裡直接用，不必另外安裝。
建議用 qfluentwidgets 的控件，看起來才和主程式是一體的。

### 管理 / 除錯

ToolsGCP 左側欄「外掛」頁：

| 項目 | 作用 |
|---|---|
| **重新載入** | 重新掃描 `plugins/`，改完程式不必重啟 |
| **開啟外掛目錄** | 直接開啟 `plugins/` |
| **我想開發** | 彈窗裡有外掛說明的精簡版 |
| 搜尋框 | 依名稱、id、作者篩選外掛 |
| 排版按鈕 | 井字 / 清單之間切換 |
| 卡片左下角開關 | 啟用 / 停用，停用後整張卡片變暗，資料夾還在 |
| 刪除按鈕 | 刪除外掛（連資料夾一起刪） |

- 外掛寫崩了**不會**影響 ToolsGCP：錯誤會被攔下來並顯示在那張卡片上（滑鼠移上去看完整堆疊）。
- `context.log()` 的輸出在 `.ToolsGCP/logs/system_log.log`，只看外掛日誌用
  `Select-String -Path .ToolsGCP\logs\system_log.log -Pattern '\[插件\|'`。

**分發 / 卸載**：把外掛資料夾打包成 zip（別帶 `__pycache__` 和本機資料），對方解壓到 `plugins/` 即可；
卸載就刪資料夾，外掛資料在 `.ToolsGCP/config/plugin_data/<外掛id>/`。

> **安全**：外掛就是普通 Python 程式，權限和 ToolsGCP 完全一樣。只裝你自己寫的或完全信任的外掛，裝之前看一下 `app.py`。

完整文件（每個欄位、`context` 全部成員、`on_show()` 鉤子、設定助手、資源處理、錯誤對照表）見
[`plugins/README.md`](plugins/README.md)。

## 資源庫格式

`.ToolsGCP/ToolsGCP-Resources.json` 存放所有資源條目：

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

欄位說明：

| 欄位 | 必填 | 含義 |
|---|---|---|
| `id` | 是 | 唯一識別，只能用小寫字母 / 數字 / 連字號 |
| `name` | 是 | 顯示名稱 |
| `code` | 否 | 自動分配的唯一編碼（`TG-000001`）；部署清單靠它指代程式 |
| `category` / `tags` | 否 | 搜尋頁的分組與篩選標籤 |
| `icon` | 否 | 圖示檔名，位於 `metadata.icon_dir` 目錄下 |
| `url` / `github` / `download_url` / `author_url` / `chat_url` | 否 | 卡片上對應按鈕的跳轉網址 |
| `description` | 否 | 一句話簡介：卡片上顯示它，詳情頁頂部那一行小字也用它 |
| `intro` | 否 | 應用介紹：詳情頁「應用介紹」區塊的正文，比 `description` 詳細；卡片和列表都不顯示。留空時詳情頁退回顯示 `description` |
| `supplement` | 否 | 補充說明：卡片不顯示，詳情頁「應用介紹」裡接在正文後面另起一段 |
| `systems` | 否 | 適用系統，多選：`全平台` / `Windows` / `macOS` / `Android` / `iOS` / `Linux` / `web` / `其他`；搜尋頁「適用系統」篩選與詳情頁「詳細資訊」都用它 |
| `architectures` | 否 | CPU 架構，多選：`x64` / `x86` / `arm64` / `arm` / `Apple Silicon` / `其他`；同上 |
| `listed_at` | 否 | 上架時間（`年-月-日 時:分:秒`），「更新時間」篩選依它判斷；詳情頁「詳細資訊」顯示到分鐘 |

除 `id` 與 `name` 外全部可以省略。主程式不會因為多出來的欄位報錯，製作器也不會把
它不認識的欄位刪掉，所以可以放心加自己的鍵。

### 資源詳情頁怎麼用這些欄位

點搜尋頁的卡片進入詳情頁，版面由上而下是：

| 區塊 | 資料來源 |
|---|---|
| 工具列 | 返回 / 收藏（不變） |
| 頂部（原樣保留） | `icon`、`name`、`code`、`description`、官網 / GitHub / 作者 / 聊天 按鈕；本次新增一行 `tags` 標籤 |
| **應用介紹**（新增） | `intro` 作為正文（沒有 `intro` 的舊條目退回用 `description`）；`supplement` 有內容就接在下面另起一段 |
| **詳細資訊**（新增） | 鍵值表，依序是 `systems` → `architectures` → `category` → `listed_at` → `url` → `github` |

兩條約定：

1. **有值才渲染**：欄位不存在或為空，那一行**整行不出現**，不會顯示「未知 / --」。
   所以 `systems: []` 的條目，詳情頁自然比別的條目短一截，這是預期行為。
2. **只加不改**：頂部那套（圖示、名稱、編碼、簡介、四個連結按鈕）保持原樣，
   兩個新區塊接在它下面。

`software version` / `file size` 目前**不做**：資源庫沒有這兩項的事實資料。

## 資源製作器

`ToolsGCP-ResourceMaker.pyw` 是獨立的小工具（和主程式一樣用 PyQt5 + PyQt-Fluent-Widgets），
分四頁：

1. **製作資源** —— 表單頁。只有**名稱**和**識別 id** 必填，其它留空就不會寫進 JSON；
   簡介最多 100 字，更長的內容放進「補充」框。
2. **瀏覽 / 刪除** —— 整庫表格。雙擊任一儲存格就地修改；雙擊**圖示**那一格可以換圖片，
   圖片會自動存進 `.ToolsGCP/Icon` 並改成應用名稱。
3. **批次合成** —— 把一份或多份投稿 `resource.json` 併進本機資源庫，或把多個檔案合成一份新 JSON。
4. **使用說明** —— 程式內建的手冊。

### 圖片（圖示）處理

- 匯入圖片會立刻複製進資源庫的圖示目錄。
- 不管原圖下載下來叫什麼，都會被改成你填的**名稱**（`LocalSend` → `LocalSend.png`）；
  之後再改名稱，檔案也會跟著改名。
- 如果這個名稱已經被**別的**資源佔用，會自動加 `-2`、`-3`，絕不覆蓋別人的圖；
  換自己的圖則直接覆蓋自己那一份。
- 每次操作都會在磁碟上核對一遍，JSON 裡寫的永遠是真實存在的檔名。

### 備份

每次寫入前，目前資源庫會複製到
`.ToolsGCP/backups/ToolsGCP-Resources.backup-<時間戳>.json`，只保留最近 20 份。
寫入是原子操作（先寫暫存檔再置換），中途被打斷也不會把資源庫寫壞。
資源庫永遠只有 `.ToolsGCP/ToolsGCP-Resources.json` 這一個檔案，製作器不會另外產生一份。

## 日誌

所有輸出（終端 + 檔案）格式統一：

```
.ToolsGCP/logs/system_log.log        目前執行
.ToolsGCP/logs/history/              歷史歸檔（最多 30 份）
```

```powershell
Select-String -Path .ToolsGCP\logs\system_log.log -Pattern '\[ERROR\]|\[OP   \]'
```

詳細格式與排查方法見 [`docs/LOGGING.md`](docs/LOGGING.md)。

## 文件

| 文件 | 內容 |
|---|---|
| [`plugins/README.md`](plugins/README.md) | 怎麼寫一個外掛（三步、很簡單） |
| [`docs/LOGGING.md`](docs/LOGGING.md) | 日誌格式規範與排查方法 |
| [`docs/SECURITY_AND_ENGINEERING.md`](docs/SECURITY_AND_ENGINEERING.md) | 安全模型與工程規範 |

## 參與貢獻

1. Fork 倉庫並開一個分支。
2. 保持現有程式風格（中文註解、安靜的小函式、不引入新相依）。
3. 提交前用 `python ToolsGCP.pyw` 和 `python ToolsGCP-ResourceMaker.pyw` 各跑一遍。
4. 想投稿新資源，附一個 `resource.json` 和對應圖示即可。

## 授權

以免費開源軟體形式發布，具體授權條款見倉庫。

<div align="center">

[English](README.md) ｜ [简体中文](README.zh-CN.md) ｜ **繁體中文**

</div>
