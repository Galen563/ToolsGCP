<div align="center">

# ToolsGCP

![ToolsGCP logo](.ToolsGCP/logo.png)

[English](README.en.md) ｜ [简体中文](README.md) ｜ **繁體中文**

*免費開源的 Windows 工具箱啟動器 —— 每條資源都直達官網或 GitHub。*

</div>

---

## 目录

- [ToolsGCP 是什麼](#toolsgcp-是什麼)
- [功能一覽](#功能一覽)
- [專案結構](#專案結構)
- [技術點](#技術點)
- [執行環境](#執行環境)
- [執行](#執行)
- [GCP-AI](#gcp-ai)
- [快速鍵](#快速鍵)
- [外掛](#外掛)
- [資源庫格式](#資源庫格式)
- [資源製作器](#資源製作器)
- [日誌](#日誌)

---

## ToolsGCP 是什麼

ToolsGCP 是一款免費開源的 Windows 工具箱啟動器。它維護一份整理好的程式 / 網站索引，讓你快速找到、
收藏，並在換電腦後一次把常用軟體裝回來，不必到處找下載頁。

- **純淨無捆綁** —— 每條資源都直達官網或官方 GitHub 倉庫，不夾帶、不劫持、不用二次打包的安裝檔。
- **應用部署** —— 把常用軟體整理成清單，重裝系統後一鍵還原。
- **GCP-AI** —— 內建 AI 助手。說一句「我想要個能做某件事的軟體」，它直接從資源庫裡找出來告訴你。
- **外掛系統** —— 往 `.ToolsGCP/plugins/` 放一個資料夾就是一個外掛（manifest + 可選 HTML 設定頁），任何人都能擴充，不用改核心程式。
- **資源製作器** —— 一個小工具，把「我想讓這個軟體被收錄」變成一份規範的資源資料，圖片匯入、標籤、寫 JSON 全包。

## 功能一覽

| 模組 | 內容 |
|---|---|
| 搜尋 | 關鍵字搜尋（名稱 / 簡介 / 標籤 / 編碼如 `TG-000015`）、依類別分組、A–Z 排序、收藏 |
| 篩選 | 類別、標籤、來源（有官網 / 有倉庫 / 可自動下載）、僅看收藏，以及**更新時間**（最新 / 10 天前 / 30 天前 / 半年前） |
| 卡片 | 自適應網格隨視窗變化；**磁貼（一行 4 個大卡片）/ 網格（一行 6 個小卡片）兩種檢視**，工具列最右邊切換；小 / 中 / 大三種卡片尺寸；支援動態 GIF 圖示；每張卡片有「@給AI」按鈕。網格檢視只保留收藏按鈕，文字放不下會自動省略 |
| GCP-AI | 右下角液態懸浮球 → 右側聊天抽屜；歷史對話頁（刪除對話會二次確認）；訊息可複製 / 重寫 / 重新生成（帶版本翻頁）；未設定 API Key 時點提示直達設定；輸入框最右側有「**潤色**」按鈕（只改措辭、不傳送、不進歷史，可在設定 → GCP-AI 關閉） |
| 部署 | 從搜尋結果整理部署清單，之後由 ToolsGCP 負責下載安裝（**部署頁只負責清單本身，不再和收藏互相牽連**） |
| 資源來源 | 設定 → 下載 → 資源來源：**雲端**（自動選 GitHub Releases 裡最新的資源庫，含 beta）或**本機檔案**；雲端失敗時保留舊快取並繼續用本機資源庫，設定頁會顯示一行雲端資源庫狀態 |
| 外掛 | 井字 / 清單兩種排版，**卡片右上角的狀態徽章（已啟用綠 / 已停用紅）**，左下角可寫 20 字備註（點輸入框外面自動取消），停用後整張卡片變暗，還能搜尋外掛；外掛設定頁（iframe）會與主程式**同步深色主題 / 材質 / 強調色 / 語言** |
| 公告 | 內容來自 GitHub 上帶「公告」標籤、且**作者本人發的** Issue（一條 Issue = 一整條公告，標題 + 正文原樣顯示）。左側欄「公告」上有像微信那樣的**紅色未讀數**；右上角「全部已讀」把未讀歸零；啟動時若有未讀，用「檢查更新」那種視窗內彈窗提示。已讀狀態存在資料根的 `config/announcements.json` |
| 收藏 | 類似 B 站收藏夾：左側收藏夾清單（預設夾不可刪），右側卡片網格；支援新增 / 重新命名 / 刪除 / 批次移動；**整頁可匯出 / 匯入 JSON**（匯入時可以放進既有收藏夾或新建一個，匯入後星標與清單同步刷新） |
| GCP工坊 | 左側欄「收藏」下面的一頁（Galne563 自製）。**目前內容留空**，只放了標題與署名，等內容補充 |
| 側邊欄 AI | 設定 → GCP-AI 開啟「改用側邊欄 AI 單獨介面」後，左側欄在 GCP工坊下面出現「AI」整頁介面（輸入框 / 傳送 / 新對話 / 歷史一應俱全），同時右下角懸浮球消失。預設不開啟。**兩種形態共用同一段對話**：在懸浮球抽屜裡聊到一半、去設定切到這個整頁介面（或反過來），正在聊的那段會自動接過來 |
| 連結點擊 | 詳情頁、搜尋卡片、AI 回答、回饋頁……**所有**外鏈：**左鍵**用瀏覽器開啟並切到瀏覽器；**Ctrl+左鍵**瀏覽器照常開啟，但目前程式**留在前景**（瀏覽器多會自己搶焦點，程式會把它搶回來後繼續待著） |
| 介面字型 | 設定 → 外觀 → 字型：從系統已安裝字型裡挑一個鋪到整個程式，第一條（微軟雅黑）就是預設字型 |
| 提交軟體 | 左側欄「更多」最下面一條，打開內建的**資源製作器頁面**（投稿表單 / 資源瀏覽器 / 批次合成 / 使用說明）。類別是**可編輯下拉**（31 個內建類別 + 自訂輸入，落盤前還原成規範名）；**三語欄位**（簡中 / 繁中 / 英文）；資源瀏覽器**雙擊**一列進入編輯，編輯態多出「儲存回原清單」；「追加到本機資源庫」與「另存為獨立資源庫」都會真正寫盤並自動備份 |
| 設定 | 左側板塊清單 + 右側**一整頁**（點左側捲到對應板塊）；頂部可搜設定項，命中會全部列出來讓你挑 |
| 視窗 | F11 進入真全螢幕並隱藏頂部標題列（保留左側導覽列），Esc 離開；無邊框視窗**四邊四角都能拖曳縮放，四周沒有可見的白 / 黑邊框** |
| 日誌 | 終端與資料根的 `logs/` 雙寫，格式統一，歷史歸檔按上限輪替 |

### 最近更新（R19）

- **部署頁只管部署**：徹底移除與收藏相關的牽連（原先「匯入清單順帶匯入收藏」整塊刪除）。
- **收藏頁新增匯出 / 匯入**：匯出為 JSON（`schema_version` + 全部收藏夾與條目）；匯入時可選放進既有收藏夾或新建一個，匯入後星標與清單同步刷新。
- **提交軟體**：類別改成可編輯下拉（31 個內建類別 + 自訂，落盤前還原成規範名）；三語欄位；資源瀏覽器雙擊進入編輯，「儲存回原清單」寫回原條目；「追加到本機資源庫」「另存為獨立資源庫」都是真實寫盤 + 自動備份；刪除「載入到製作資源」；預覽與產出的捲動、陰影、間距與頂部分段留白統一。
- **無邊框視窗**：四邊四角可拖曳縮放，四周不再出現白 / 黑邊框（不再內縮 WebView2，改為頁面上 8 個透明熱區呼叫 `window.start_resize` 走系統原生縮放；DWM 描邊已關閉）。
- **外掛設定頁深色主題**：宿主與 iframe 用 `postMessage` 同步主題 / 材質 / 強調色 / 語言，切換後立即生效，不再停在白底。
- **`/plugin` 只由「外掛製作輔助」控制**：只開啟 GCP-AI Agent 時輸入 `/` 不會有任何提示或藍色指令；兩個開關不再互相連坐（只剩一個方向：啟用製作輔助時順帶啟用 Agent）。
- **GCP-AI 輸入框「潤色」**：輸入框右側新增 AI 潤色按鈕，可在設定 → GCP-AI 關閉。
- **產品邊界**：`.ToolsGCP/legal/` 下的《使用者協議》《隱私政策及免責聲明》兩份 txt 於執行時注入 AI 提示詞（正文**不寫進程式碼**），改條款只改 txt。
- **雲端資源來源**：自動從 GitHub Releases（含 beta）依 semver 挑最新版本，下載其中的 `ToolsGCP-Resources.json`，校驗後原子替換本機快取；失敗保留舊快取並繼續用本機資源庫。
- **設定 → 資源來源**：說明改成與其他設定一致的提示（ⓘ），去掉多餘分隔線與「功能開發中」提示，並多一行雲端資源庫狀態（版本 / 筆數 / 更新時間，或失敗原因）。
- **公告**：已讀狀態存在資料根的 `config/announcements.json`；刪掉資料根或這個檔案，所有公告會重新未讀、重新推送。
- **日誌**：級別統一 INFO / OP / WARN / ERROR / DBG（DBG 預設關閉）；啟動環境、視窗幾何、結束流程逐項記錄。

### 最近更新（R20）

- **搜尋頁圖示**：卡片圖示改 eager 載入；失敗自動重試 2 次（帶快取破壞參數），仍失敗才顯示首字母，不再「要更新狀態才恢復」。
- **視窗四角**：改回**圓潤角**。白 / 黑角的真正來源不是圓角的抗鋸齒，而是 pywebview `shadow=True` 留下的那 1px「玻璃條」（桌面色從視窗邊緣透進來）→ 把 DWM 描邊色改成貼近頁面底色即可消掉；最大化時 DWM 自動忽略圓角，全螢幕時顯式改回方角。拉伸熱區方案不變。
- **外掛**：`gcp-ai-agent` 顯示名改為 **AI Agent**；兩個內建外掛作者改為 **Galen563**；啟用「外掛製作輔助」會一併啟用 AI Agent，關閉 AI Agent 會一併關閉外掛製作輔助（只開 Agent 不會反向開啟製作輔助）。
- **收藏頁**：匯出前先彈窗勾選收藏夾（預設勾選預設收藏夾）；左側操作面板重做為緊湊分組；定製頁 / 收藏頁卡片恢復隨視窗寬度自適應。
- **部署頁**：雙擊清單列直接進入該資源的詳情頁。
- **提交軟體**：多語言欄位常開（刪除開關與其中的「名稱」輸入）；刪除「退出編輯」按鈕；三語仍從資源庫 JSON 完整載入。
- **外掛設定頁**：Esc 返回外掛清單；進入頁面 / 設定頁時開關、分段、導覽指示標不再重播入場動畫。
- **設定**：下載區去掉多餘「資源來源」首行與分割線；雲端資源庫狀態列最右側加**重試圖示**；關閉「開啟GCP-AI」時隱藏該區其餘內容；關閉「啟用全域快速鍵」時隱藏快速鍵項；「儲存位置」改為「設定儲存」；「側邊欄指示Q彈效果」預設關閉；啟動 / 動畫區的子項縮排。
- **雲端啟動載入**：偵測到雲端模式時允許等它載入（單次 60 秒，失敗最多重試 3 次），失敗後回退本地並提示原因。
- **GitHub Releases 下載（新）**：有 GitHub 倉庫的資源卡片 / 詳情多一個 Releases 入口，彈窗列出全部 Release 與附件，點檔案直接下載；檔名按平台 / 架構 / 副檔名智慧匹配；右下角出現下載小圓，點開是獨立下載頁（隱藏左側欄，左上角返回 + 下載，右側視窗按鈕不變）。
- **GCP-AI 潤色按鈕**：移到輸入框**內部右下角**，長文字換行也不會壓住按鈕。

## 專案結構

```
ToolsGCP.pyw                       主程式（雙擊執行）—— **web 版入口**（pywebview 殼 + webui/ 前端）
requirements.txt                   相依套件（pywebview / bottle / pythonnet / Pillow / PyQt5）
README.md（简体中文，預設）/ README.zh-CN.md（English）/ README.zh-TW.md（繁體中文）
.ToolsGCP/desktop/                web 版桌面外殼（Python，只做裝配，不含業務）
  shell.py                         視窗裝配、啟動時序、托盤 / 快速鍵 / 結束閘門
  webhost.py                       本機 WSGI 服務：把 webui/ 與 .ToolsGCP 的資源餵給 WebView2
  api/                             window.pywebview.api 的各個域
  native/                          原生層：托盤、自繪圓角選單、圖示、DPI、剪貼簿、視窗邊框
.ToolsGCP/webui/                   前端（Vue3 執行時 + 手寫元件，**無建置步驟**）
  index.html                       單一檔案範本（所有頁面段都在這裡）
  js/app.js                        全部前端邏輯（傳統腳本）+ js/icons.js 圖示精靈
  css/                             variables / base / components / layout / animations / overlays
.ToolsGCP/                         ★ 所有程式檔案（**資源目錄**，請勿刪除；執行資料在資料根，見下方）
  ToolsGCP-Resources.json          資源庫（製作器依這個固定路徑讀寫）
  logo.png                         程式圖示 / 視窗圖示
  images/                          圖片資源
    icon/                          資源庫裡引用的圖示（**原 .ToolsGCP/Icon，web 版已改名並移到這裡**）
    qq/                            回饋頁 QR Code
  modules/                         業務程式碼與語言檔（pymodels 的 core / utils + languages）
  plugins/                         內建外掛（一個資料夾 = 一個外掛；Web 版只讀 manifest / config.html / lang）
  legal/                           產品邊界文字：使用者協議 / 隱私政策（執行時注入 AI 提示詞，正文不進程式碼）
  config/                          執行期設定（實際寫在**資料根**，見下方說明；首次執行自動建立）
    toolsgcp_config.json           設定（含加密後的 API Key、介面位址、模型名稱）
    favorites.json                 收藏夾
    deploy_config.json             部署清單
    plugins.json                   外掛啟用 / 停用狀態
    plugin_notes.json              外掛卡片備註
    announcements.json             公告已讀狀態（刪掉 = 全部重新未讀）
    privacy_policy.json            隱私政策同意記錄
    plugin_data/<外掛id>/           外掛自己的資料目錄
    chats/                         GCP-AI 歷史對話（每次對話一個 json）
    cloud/                         雲端資源庫快取（資源庫 json + 中介資料）
  logs/                            執行日誌與歷史歸檔
.github/workflows/release.yml      GitHub Actions：打 v* 標籤自動打包成 exe 並發佈
py版本-已弃用仅作为参考项目，主体转为web版本/
                                   舊 PyQt5 單機版（**唯讀參考**，不參與執行）
项目资料-文档与开发测试/             設計文件、回歸腳本、建置工具（不參與執行）
```

> **資料根（使用者資料）和程式目錄旁的 `.ToolsGCP` 是兩回事。**
> 程式自己產出的設定 / 收藏 / 日誌 / AI 對話 / 公告已讀預設放在 `<使用者主目錄>\.ToolsGCP`（首次執行
> 自動建立）；`<使用者主目錄>\ToolsGCP.json` 是**位置指標**，記錄資料根在哪 —— 它固定在主目錄，
> 不隨遷移移動。可以在「設定 → 儲存」把資料根遷到任意位置（遷的是資料根，不是程式目錄）。
>
> 程式目錄旁的 `.ToolsGCP/` 是**資源目錄**：modules / images / 外掛 / 資源庫 / legal / logo。
> 它隨程式發佈、永遠不搬、也不是設定目錄；刪掉它程式就跑不起來（反過來說，刪資料根只會重置
> 設定、收藏、日誌和公告已讀狀態）。
>
> **圖示路徑變了**：`.ToolsGCP/Icon/` → `.ToolsGCP/images/icon/`；
> 正式 URL 是 `/res/image/icon/<檔名>`（`/res/icon/<檔名>` 保留為相容別名）。

## 技術點

程式本體是 **Python 桌面外殼 + 本機 HTTP 服務 + 無建置前端** 三層：Python 只負責視窗、托盤、快速鍵與
原生能力，介面全部是 HTML / CSS / JS，業務演算法沿用同一套 `pymodels` 純 Python 模組。

### 三層架構與 JS ↔ Python 橋

- **外殼**：`pywebview`（Windows 上就是 WebView2）+ 無邊框自繪標題列；托盤、全域快速鍵、DPI、視窗邊框
  補丁都在 `desktop/native/` 用 Win32 API（ctypes / pythonnet）直接實作，不依賴 Qt。
- **本機服務**：`bottle` 寫的小 WSGI 應用（`desktop/webhost.py`）把 `webui/`、`images/`、資源庫與外掛
  設定頁餵給 WebView2；`window.pywebview.api` 的每個域（`resources` / `favorites` / `settings` / `ai` /
  `maker` / `plugins` …）就是 JS ↔ Python 的橋。
- **前端**：Vue 3 執行時（`vue.global.prod.js`，隨倉庫分發）+ 手寫元件，**沒有打包步驟** —— 改完
  `.ToolsGCP/webui/` 裡的檔案重新整理視窗就生效。頁面段、圖示精靈、CSS 變數全部手寫。
- **JSON 信封**：後端方法只回傳可 JSON 序列化的 dict，約定 `{ok: true, ...}` / `{ok: false, error: "…"}`；
  前端統一走 `bridge.tryCall()`，**介面不存在時回傳 `null`，呼叫方必須明確降級**（提示「介面未就緒」），
  絕不假裝成功。業務欄位叫 `success`，避免覆蓋信封的 `ok`。

### 無邊框視窗：能拖邊縮放，但四周沒有可見邊框

`pywebview` 的 `frameless=True` 會把視窗變成 `WS_POPUP`：沒有縮放邊框、沒有最大化貼齊，也沒有系統陰影。
`desktop/native/frame.py` 用三步把它補回來：

1. 把 `WS_THICKFRAME` 等樣式加回去 → 系統重新提供四邊四角的原生縮放手勢；
2. 子類化視窗程序，在 `WM_NCCALCSIZE` 回傳 0 → 吃掉系統要畫的邊框，客戶區重新鋪滿整個視窗；
3. 在 `WM_GETMINMAXINFO` 把最大化尺寸釘到**目前螢幕的工作區** → 加了 `WS_THICKFRAME` 之後最大化不會
   再蓋住工作列；同時關掉 DWM 的視窗過場動畫與描邊。

縮放熱區放在**頁面上**，而不是讓 WebView2 內縮：`index.html` 裡 8 個透明 `span`（四邊 + 四角）接管
`pointerdown`，呼叫 `window.start_resize(direction)` → 原生 `WM_NCLBUTTONDOWN` 模態縮放，和拖曳標題列
是同一套系統迴圈。**為什麼不內縮 WebView2**：內縮會在視窗四周留下一條父視窗底色帶，而標題列在毛玻璃 /
壓克力檔下是半透明漸層，任何純色都比對不上 —— 使用者看到的就是「白邊 / 黑邊 / 邊框變粗」。現在 WebView2
鋪滿視窗，沒有色帶，手感仍然是原生的。

### 主題、材質與強調色

配色全部收在 `webui/css/variables.css` 的 CSS 變數裡（深 / 淺兩套 `--page` / `--text` / `--accent` …），
執行時只改 `<html>` 上的三個屬性：

- `data-theme="dark|light"`：深 / 淺主題（「跟隨系統」時由 `matchMedia` 解析後落成確定值）；
- `data-fx="mica|glass|acrylic"`：主題效果（雲母 / 毛玻璃 / 壓克力），只換模糊、底噪與高光描邊；
- `data-accent="blue|purple|orange"`：元件強調色。

外掛設定頁是 iframe：宿主在載入完成、切換主題 / 材質 / 強調色 / 語言時用 `postMessage` 把
`{type:'toolsgcp-theme', theme, fx, accent, language}` 推過去，外掛頁收到後立即改自己的 `<html>` 屬性；
「讀取父文件」只作為首幀備援。這樣深色主題下設定頁不會停在白底。

### 資料與效能

- **搜尋 / 篩選 / 排序 / 分組全部交給後端 `resources.query`**（演算法唯一真源），前端不重寫演算法；
  卡片清單是自繪的**虛擬清單**，只渲染視口附近的行，視窗縮放時只重算一次行高。
- **收藏只有一個真源**（後端 `favorites.*`）：卡片星標、收藏頁、詳情頁共用同一份狀態，任何寫入後統一
  刷新；匯出是帶 `schema_version` 的 JSON，匯入相容「收藏夾陣列 / codes 陣列 / items 陣列」多種寫法。
- **雲端資源來源**：`resources.cloud_status()` 只讀本機快取（不連網、不卡設定頁），
  `resources.cloud_refresh(force)` 才真的去 GitHub 抓：先取 release 清單（含 beta），依 semver 選最新，
  再在附件裡找 `ToolsGCP-Resources.json`，校驗後**原子寫入**資料根的 `config/cloud/`；失敗保留舊快取並
  繼續用本機資源庫，首屏只讀快取、背景執行緒按間隔檢查。
- **公告已讀**只存在資料根的 `config/announcements.json`：刪掉資料根或這個檔案 ⇒ 全部重新未讀、下次啟動
  重新彈窗；程式目錄旁 `.ToolsGCP` 裡的舊備份不會被反向遷移搬回來。

### 製作器的寫盤與備份

所有寫入操作都走 `maker.*`：條目先過 `resource_schema.normalize()`，寫盤用「暫存檔 + `os.replace`」
原子替換；替換前把舊資源庫複製成 `ToolsGCP-Resources.backup-<時間戳>.json`，只保留最近 20 份。
「儲存回原清單」強制按載入時的 id / 編碼寫回，避免使用者改了 id 之後被當成新條目追加；
「另存為獨立資源庫」會把圖示一起複製到目標目錄並改寫 `icon`，不會寫出一個圖示懸空的 JSON。

### GCP-AI 的提示詞分層

系統提示詞分四層組裝（`modules/pymodels/core/ai/prompt.py`）：角色與內建知識 → 回覆模式（簡潔 / 標準 /
專業）→ 硬規則（不輸出程式碼、不複述問題、連結必須完整）→ 資源庫清單（依關鍵字壓縮，最多 120 / 40 筆）。
`@資源(編碼)` 會作為「就是這一筆」的強指令；`.ToolsGCP/legal/*.txt` 兩份協議正文在執行時讀盤注入
（正文**不寫進程式碼**，改條款只改 txt），讓 AI 能說明觸發了哪一條、為什麼不能做。
輸入框右側的「潤色」按鈕是**獨立的小請求**：只改措辭、不回答問題、不寫入歷史對話。

### 國際化與日誌

- 文案在 `.ToolsGCP/modules/languages/{zh_CN,zh_TW,en_US}/` 下，**15 個模組 × 3 個單語言目錄**
  （每個檔案只放一種語言）；後端依「目前語言 → 簡體中文 → 英文」回退，前端用同一份 bundle 渲染。
- 日誌格式固定：`[時間] [級別] [中文分類|英文子類] 訊息 鍵=值`；級別 INFO / OP（操作稽核）/ WARN /
  ERROR / FATAL，DBG 預設關閉（開發者模式可開）；密鑰類欄位自動打碼；啟動環境、視窗幾何、結束流程都
  逐項記錄；歷史歸檔按上限輪替。

## 執行環境

- Windows 10 / 11
- Python 3.10 以上（在 3.13 上測試）
- 執行相依（`requirements.txt` 一併裝好）：

```bash
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

## 執行

```bash
python ToolsGCP.pyw
```

也可以直接在檔案總管雙擊 `ToolsGCP.pyw`。要改資源庫就在程式裡打開「更多 → **提交軟體**」（內建
資源製作器），不需要獨立的 exe 或腳本。

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
| 設定 → API Key → **模型選擇** | 純下拉框：只列該服務商支援的模型（清單隨服務商切換）。依官方文件 V4.1-Flash 的 API 名稱是 `deepseek-flash`，程式內部自動轉換，介面顯示/選擇用 `deepseek-v4.1-flash` 即可 | `deepseek-v4.1-flash`（預設） |
| 設定 → API Key → **模型名稱** | 可自訂任意模型名稱（本機/中轉/自建閘道的模型填這裡） |
| 設定 → API Key → **介面位址** | OpenAI 相容格式的位址，通常以 `/v1` 結尾。跟著服務商自動填，也可以自己改 | `https://api.deepseek.com/v1` |
| 設定 → API Key → **API Key** | 你的金鑰。**以 Windows DPAPI 加密後存在 `config/toolsgcp_config.json` 的 `api_key_enc`**，密文換台電腦解不開 | 空 |
| 設定 → AI → **回覆模式** | 控制回答的**長度與細節**，見下表 | 標準 |
| 設定 → AI → **上下文範圍** | 每次提問帶多少歷史對話給模型：整個會話（預設，記憶最長）/ 最近 10 / 20 / 30 輪 | 整個會話 |
| 設定 → 模型呼叫 → 限制 token 輸出 | 限制單次回答的最大長度 | 關閉 |

內建服務商與常用模型（都可以自己改）：

| 服務商 | 介面位址 | 常用模型 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-v4.1-flash`（預設；內部依官方文件轉成 API 名 `deepseek-flash`）、`deepseek-v4-pro` |
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

一個外掛就是 `.ToolsGCP/plugins/` 下的一個資料夾，啟動時自動掃描 —— **一個資料夾 = 一個外掛**。

Web 版和舊 PyQt 版看外掛的方式不一樣，先講清楚：

- **只讀 `manifest.json`（+ `lang/` + 可選的 `config.html`），絕不 import 外掛的 Python**。
  `app.py` 那套 `create_page(context) → QWidget` 是 PyQt 版入口，Web 版不載入它 —— 主執行緒裡
  import PyQt5 會讓 WebView2 崩潰，所以 Web 版外掛介面用 **HTML** 寫。
- 外掛的開關、圖示、說明、設定介面都來自 manifest；開關本身寫進**主程式設定**（見 `enabled_setting`）。

```
.ToolsGCP/plugins/
├─ README.md          PyQt 版外掛的完整文件（create_page / context，存檔參考）
├─ _template/         PyQt 版開發者範本（底線開頭，**永遠不會被載入**）
├─ plugin-showcase/   範例（同樣不會被載入）
├─ gcp-ai-agent/      內建外掛：manifest + config.html + lang/
├─ gcp-plugin-maker/  內建外掛：manifest + config.html + lang/ + core/
└─ 我的外掛/          你要寫的：manifest.json 必須有，其它按需
```

> `_template` / `plugin-showcase` / `_` 或 `.` 開頭的目錄都是保留目錄
> （`plugin_manager.RESERVED_DIR_NAMES`）：不掃描、不進外掛清單、不建資料目錄，檔案原樣保留。

### 最少的外掛

一個 `manifest.json` 就能被識別：

```
.ToolsGCP/plugins/我的外掛/
├─ manifest.json     外掛基本資訊（**必須**）
├─ config.html       設定介面（可選；寫了才會出現「設定介面」按鈕）
└─ lang/             三語文案（可選）
   ├─ zh_CN.json
   ├─ zh_TW.json
   └─ en_US.json
```

```json
{
  "id": "my-plugin",
  "name": "我的外掛",
  "version": "1.0.0",
  "author": "你的名字",
  "description": "一句話說明",
  "enabled_setting": "my_plugin_enabled",
  "config_page": "config.html",
  "builtin": false
}
```

放進 `.ToolsGCP/plugins/` → 打開 ToolsGCP →「外掛」→「重新載入」就出現了。
改完 `manifest.json` / `config.html` 再點一次「重新載入」，不必重啟。

`manifest.json` 欄位（Web 版實際讀取的）：

| 欄位 | 必填 | 說明 |
|---|---|---|
| `id` | 建議填 | 外掛唯一識別，2~41 位小寫字母/數字/`-`/`_`（首字元必須是字母或數字）；留空就用資料夾名；重複時只有先掃到的生效 |
| `name` | 建議填 | 卡片上顯示的名稱；可寫字串，也可寫多語言字典 `{"简体中文": "…", "English": "…"}` |
| `version` | 否 | 顯示成 `v1.0.0`；留空不顯示 |
| `author` | 否 | 顯示在版本旁邊 |
| `description` | 否 | 卡片上的兩行說明；同樣支援多語言字典 |
| `entry` | 否 | PyQt 版入口檔名（預設 `app.py`）。**Web 版不載入它**，保留欄位是為了同一份外掛目錄還能給 PyQt 版用 |
| `icon` | 否 | 相對外掛目錄的圖片路徑，如 `assets/icon.png`（Web 版按 `/res/plugins/<id>/<icon>` 取圖；FluentIcon 名字是 PyQt 版寫法，Web 版不認） |
| `enabled_setting` | 否 | 宣告由**哪個設定鍵**控制這個外掛的開關，例如 `gcp_plugin_maker_enabled`。**沒寫這一項的外掛在外掛中心裡不能撥開關**（點了只會提示沒有開關設定） |
| `config_page` | 否 | 相對外掛目錄的 HTML（如 `config.html`）。寫了卡片上的「設定介面」按鈕才可點，介面在右側內容區用 iframe 承載 |
| `default_disabled` | 否 | 沒有 `enabled_setting` 時用來決定預設開關狀態（內建外掛預設 `true`） |
| `builtin` | 否 | 內建 / 受保護：卡片垃圾桶變灰，後端也拒絕刪除（官方外掛 id 還額外寫死在 `desktop/api/plugins.py`） |
| `companion` | 否 | 「搭子」外掛 id：**啟用我這個外掛時順帶啟用它**（反向不連坐） |
| `generated_by` | 否 | 由哪個外掛產生（目前是「外掛製作輔助」）；停用產生者時，它產生的外掛一起停用 |

檔名必須是 `manifest.json`（很舊的 `plugin.json` 也還認，但新外掛請用 `manifest.json`）。
資料夾名以 `_` 或 `.` 開頭會被跳過；**沒有 manifest.json 的資料夾在外掛中心裡看不到**
（前端全靠 manifest 渲染卡片），修好檔案再點「重新載入」即可。

### 正式開發用範本

Web 版最可靠的參考是**內建外掛自己**，直接抄它們的結構：

| 參考 | 裡面有什麼 | 適合抄什麼 |
|---|---|---|
| `gcp-ai-agent/` | `manifest.json` + `config.html` + `lang/*.json` | 一個完整的設定頁：總開關、逐項開關、統計、最近動作、主題同步 |
| `gcp-plugin-maker/` | 上面這些 + `core/`（純標準庫 Python） | 需要後端參與時的寫法：後端用 `importlib` 把 `core/` 當合成包載入（**僅內建外掛走這條通道**） |
| `_template/` | PyQt 版多檔案範本（`app.py` / `ui/` / `core/`） | 只有給 PyQt 版寫外掛時才有用；Web 版不載入它 |

> 為什麼 `_template` 和 `plugin-showcase` 不會被載入：它們在底線/保留名單裡，
> 只當「照著寫」的範本，不出現在清單、不能啟停、也沒有資料目錄。

### 設定頁能拿到什麼

Web 版**沒有** `create_page(context)` 這個入口，外掛介面就是 `config.html`（一個普通網頁）。
它和主程式同源（都由本機 WSGI 服務出頁面），所以能拿到這些：

| 能用的東西 | 說明 |
|---|---|
| 自己的檔案 | 相對路徑直接讀：`manifest.json`、`lang/zh_CN.json`、`assets/icon.png` … |
| 主程式介面 | `parent.pywebview.api.<域>.<方法>(…)`。pywebview 只往最上層框架注入 `window.pywebview`，iframe 裡必須回退到 `parent`；`settings.get/set`、`resources.*`、`ai.*` 等域和主介面用的是同一套 |
| 主程式事件 | `parent.ToolsGCP.on('settings-changed', (payload) => …)`（後端廣播時才有；沒有廣播就自己輪詢備援 —— 內建兩個外掛就是「事件 + 5 秒輪詢」） |
| 主題同步 | 宿主在 iframe 載入完成、切換主題 / 材質 / 強調色 / 語言時 `postMessage` 一條 `{type:'toolsgcp-theme', theme, fx, accent, language}`；設定頁收到後改自己的 `<html data-theme data-fx data-accent>` 即可（首幀也可以直接讀 `parent.document.documentElement` 的 `data-theme`，單獨打開時退回 `matchMedia`） |
| 視窗尺寸 | 正常 `window.innerWidth/innerHeight`，頁面在右側內容區裡自適應 |

⚠️ Web 版**沒有**給第三方外掛暴露「外掛專屬可寫目錄」（PyQt 版的 `context.data_dir` / `context.log`
在 Web 版不存在）。需要存資料時，優先使用主程式已經暴露的設定項或介面；不要往外掛目錄寫檔案
（那是唯讀資源區，升級 / 重裝會被覆蓋）。

### 多語言

文案放 `lang/zh_CN.json`、`zh_TW.json`、`en_US.json`，平鋪鍵值對：

```json
{
  "title": "我的外掛",
  "greet": "你好，{name}！"
}
```

取詞順序是 **目前語言 → 簡體中文 → 英文 → 鍵名本身**，找不到不會顯示空白。
`_template/core/i18n.py` 裡有一個現成的 `I18n` 類可以照著寫（帶 `{佔位符}` 替換）：

```python
i18n = I18n(plugin_dir, "zh_TW")
i18n.t("title")              # → 我的外掛 / 我的外掛 / My Plugin
i18n.t("greet", name="小明")  # → 你好，小明！
```

manifest 裡的 `name` / `description` 也可以直接寫成多語言字典（鍵用語言名
`简体中文` / `繁體中文` / `English`，也相容 `zh_CN` 這類 locale 名）。
主程式自己的介面文案在 `.ToolsGCP/modules/languages/{zh_CN,zh_TW,en_US}/`，
**外掛文案不要往那裡加**，放自己的 `lang/`。

### 能用什麼函式庫

- 外掛介面 = **普通 HTML / CSS / JS，沒有建置步驟**：可以手寫，也可以把任意前端函式庫
  放進外掛目錄自己引用（別引 CDN，離線會白屏）。
- **不要用 PyQt5 / qfluentwidgets**：Web 版根本不執行外掛的 Python 入口，寫了也不會跑；
  而且主執行緒 import PyQt5 會讓 WebView2 崩潰。
- 例外：內建 `gcp-plugin-maker` 的 `core/` 是純標準庫 Python，由後端按需載入
  （`importlib` + 合成包名）。第三方外掛目前**沒有**這條通道。

### 管理 / 除錯

ToolsGCP 左側欄「外掛」頁（也可以在「更多 → 外掛」打開）：

| 項目 | 作用 |
|---|---|
| **重新載入** | 重新掃描 `.ToolsGCP/plugins/`，改完 manifest / config.html 不必重啟 |
| **開啟外掛目錄** | 直接開啟 `.ToolsGCP/plugins/` |
| **我想開發** | 彈窗裡是簡版約定：manifest 欄位、三語語言包、`enabled_setting`、`config_page` |
| 搜尋框 | 依名稱、id、作者篩選外掛 |
| 排版按鈕 | 井字 / 清單之間切換 |
| 卡片開關 | 只對宣告了 `enabled_setting` 的外掛可用；寫入的就是那個設定項，設定頁 / 聯動邏輯共用同一個鍵 |
| 設定介面按鈕 | 只有宣告了 `config_page` 才可點；在右側內容區用 iframe 打開，深色主題 / 材質 / 強調色 / 語言會和主程式同步 |
| 刪除按鈕 | 內建 / 受保護外掛變灰不可點；可刪的會二次確認，且只刪 `plugins/` 第一層的真實目錄 |

幾個聯動規則（都是「依 manifest 宣告走」，不是寫死某個外掛名）：

- **開關聯動**：`enabled_setting` 那個鍵變化時，外掛卡片和設定頁讀的是同一份設定；
- **搭子**：啟用 A 時如果 A 的 `companion` 是 B，會順帶啟用 B（反過來不會）；
- **產生物**：停用「產生者」外掛時，`generated_by` 指向它的外掛一起停用；
- **`/plugin` 只由「外掛製作輔助」控制**：只有 `gcp_plugin_maker_enabled` 為開時，GCP-AI 輸入框敲 `/`
  才會出提示、`/plugin` 才會變藍並發給模型；只開 GCP-AI Agent 不算。

除錯與分發：

- 設定頁就是普通網頁，改完重新整理（再點一次「重新載入」或重新開啟設定介面）就生效；
  後端 / 主程式日誌在資料根 `logs/`（預設 `<使用者主目錄>\.ToolsGCP\logs`）。
- 外掛寫崩了不會影響主程式：manifest 解析失敗時外掛中心看不到它（修好後重新載入即可）；
  設定頁裡的 JS 錯誤只影響那個 iframe。
- **分發 / 卸載**：把外掛資料夾打包成 zip（別帶 `__pycache__`），對方解壓到 `.ToolsGCP/plugins/`；
  卸載就刪資料夾。

> **安全**：外掛設定頁就是網頁，能呼叫主程式暴露給前端的介面。只裝你自己寫的或完全信任的外掛，
> 裝之前看一下它的 `config.html`。

PyQt 版外掛（`create_page(context)`、`context` 全部成員、`on_show()` 鉤子等）的完整文件見
[`.ToolsGCP/plugins/README.md`](.ToolsGCP/plugins/README.md)；那份文件針對 PyQt 版，
Web 版請以本節為準。

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

入口只有一個：主程式左側欄「更多 → **提交軟體**」，寫完直接進資源庫（沒有獨立的 exe 了）。分四頁：

1. **製作資源** —— 表單頁。只有**名稱**和**識別 id** 必填，其它留空就不會寫進 JSON；
   簡介最多 100 字，更長的內容放進「補充」框。類別是**可編輯下拉**：31 個內建類別 + 自訂輸入
   （落盤前會還原成規範名，避免出現「工具 / 工具 」兩個類別）；名稱 / 簡介 / 補充都支援
   **三語欄位**（簡中 / 繁中 / 英文），三種語言寫在同一筆資料裡。
2. **瀏覽 / 資源庫** —— 整庫表格。**雙擊**一列進入編輯（不是就地改儲存格），編輯態多出
   「**儲存回原清單**」——依載入時的 id / 編碼寫回原條目，不會產生重複條目，也不動原上架時間；
   雙擊**圖示**那一格可以換圖片，圖片會自動存進 `.ToolsGCP/images/icon` 並改成應用名稱。
3. **批次合成** —— 把一份或多份投稿 `resource.json` 併進本機資源庫，或把多個檔案合成一份新 JSON。
4. **使用說明** —— 程式內建的手冊。

寫盤有兩個落點：**追加到本機資源庫**（寫 `.ToolsGCP/ToolsGCP-Resources.json`）與
**另存為獨立資源庫**（系統「另存為」對話框選目錄，JSON 與圖示一起複製過去）——兩者都是真正寫盤，
不是「匯出一份 JSON 讓你自己放回去」。

### 圖片（圖示）處理

- 匯入圖片會立刻複製進資源庫的圖示目錄。
- 不管原圖下載下來叫什麼，都會被改成你填的**名稱**（`LocalSend` → `LocalSend.png`）；
  之後再改名稱，檔案也會跟著改名。
- 如果這個名稱已經被**別的**資源佔用，會自動加 `-2`、`-3`，絕不覆蓋別人的圖；
  換自己的圖則直接覆蓋自己那一份。
- 每次操作都會在磁碟上核對一遍，JSON 裡寫的永遠是真實存在的檔名。

### 備份

每次寫入前，目前資源庫會複製到同目錄下的
`ToolsGCP-Resources.backup-<時間戳>.json`，只保留最近 20 份。
寫入是原子操作（先寫暫存檔再置換），中途被打斷也不會把資源庫寫壞。
資源庫永遠只有 `.ToolsGCP/ToolsGCP-Resources.json` 這一個檔案，製作器不會另外產生一份。

## 日誌

所有輸出（終端 + 檔案）格式統一（檔案在**資料根**下，預設 `<使用者主目錄>\.ToolsGCP\logs`）：

```
<資料根>/logs/system_log.log         目前執行
<資料根>/logs/history/               歷史歸檔（按上限輪替）
```

```powershell
Select-String -Path "$HOME\.ToolsGCP\logs\system_log.log" -Pattern '\[ERROR\]|\[OP   \]'
```

級別是 `INFO` / `OP`（操作稽核）/ `WARN` / `ERROR` / `FATAL`，`DBG` 預設關閉（開發者模式可開）；
密鑰類欄位自動打碼。詳細格式與排查方法見
[`项目资料-文档与开发测试/docs/LOGGING.md`](项目资料-文档与开发测试/docs/LOGGING.md)。
