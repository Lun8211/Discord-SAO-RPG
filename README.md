# 🛒 val-dc — 特戰英豪 (VALORANT) 多人每日商店 Discord 機器人

自動擷取您與朋友們的多個 **VALORANT（特戰英豪）** 帳號每日商店刷新的 **4 個武器造型**，並透過您的 **Discord 機器人** 在指定聊天頻道內，依序為每個人的帳號發送 **4 張精美 Embed 圖卡**（包含自訂暱稱、自動 `@標註` 對應朋友、造型名稱、高清圖片、VP 價格、稀有度顏色與等級圖示、特效預覽影片連結，以及特務幣/輻能點數餘額）。

支援透過 **GitHub Actions 免費每日自動排程執行**（不需開著電腦或租用伺服器），也支援本地常駐或在 Discord 內使用 **`/shop`** 指令手動即時查詢！

---

## ✨ 功能特色

- **👥 支援多人帳號推送**：可綁定多個特戰英豪帳號，每天依序推送每個人的每日商店，並支援「玩家暱稱」、「自動 `@Tag` 對應的 Discord 成員」或「個別指定發送頻道」。
- **🛡️ 帳號獨立容錯與過期提醒**：若其中一位朋友的 Cookie 過期，其他人的商店依然會正常推送，且機器人會針對過期的帳號單獨發送提醒並 `@標註` 該名成員更新 Cookie。
- **🃏 4 張獨立 Discord Embed 圖卡**：每個帳號發送一則包含 4 張 Embed 的訊息，完整呈現每日刷新的 4 把槍枝造型高清圖片、VP 售價、稀有度分級與對應色條。
- **🎬 支援特效影片預覽**：若造型具備升級特效影片，點擊標題或欄位連結即可直接預覽。
- **⏰ GitHub Actions 全自動排程**：預設於每日 **台灣時間早上 08:17（UTC 00:17）**（特戰英豪每日 08:00 商店刷新後，完美避開整點尖峰塞車）自動發送至您的 Discord 頻道。
- **⚡ 互動式 `/shop` 斜線指令**：支援在 Discord 隨時輸入 `/shop` 即時手動查詢，可選擇「查詢所有人」、「只查我自己」或「指定隊友」。

---

## 🚀 快速設定教學（GitHub Actions 免伺服器每日自動發送）

### 第一步：準備 Discord 機器人與頻道 ID

1. 前往 [Discord Developer Portal](https://discord.com/developers/applications) 建立或選擇您的 Application。
2. 點選左側 **Bot** 頁面：
   - 點擊 **Reset Token** 複製您的機器人 Token（即 `DISCORD_BOT_TOKEN`）。
3. 點選左側 **OAuth2 -> URL Generator**：
   - **Scopes** 勾選 `bot` 與 **`applications.commands`**（使用 `/shop` 指令必勾）。
   - **Bot Permissions** 勾選 `Send Messages`、`Embed Links`、`View Channels`。
   - 複製下方產生的網址並邀請機器人進入您的 Discord 伺服器。
4. 在 Discord 中開啟「使用者設定 -> 進階 -> **開發者模式**」：
   - 對著您想顯示每日商店的文字頻道按右鍵 ➔ **複製頻道 ID**（即 `DISCORD_CHANNEL_ID`）。
   - 對著您或朋友的使用者頭像按右鍵 ➔ **複製使用者 ID**（即 `Discord 用戶 ID`，供 `@標註` 使用）。

---

### 第二步：取得每位玩家的 Riot Cookie（重要操作步驟）

> [!IMPORTANT]
> **🚨 必看防坑守則（千萬不要點網頁上的「登出」）**
> - 在同一台電腦抓取多個帳號時，登出帳號會通知 Riot 伺服器**立即註銷先前的 Cookie**！
> - 請務必使用 **無痕視窗** 操作，抓完後**直接點視窗右上角 `❌` 關閉無痕視窗**，**絕對不要**在 Riot 網頁上按「登出 (Sign Out)」！

每位玩家請各自依序執行以下步驟：

1. 按下快捷鍵 **`Ctrl + Shift + N`**（Mac 為 `Cmd + Shift + N`）開啟一個**全新的無痕視窗**。
2. 在無痕視窗中打開 Riot 登入連結：
   👉 [https://auth.riotgames.com/authorize?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in&client_id=play-valorant-web-prod&response_type=token%20id_token&nonce=1&scope=account%20openid](https://auth.riotgames.com/authorize?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in&client_id=play-valorant-web-prod&response_type=token%20id_token&nonce=1&scope=account%20openid)
3. 登入特戰英豪帳號（⚠️ **務必勾選「保持登入 / Stay signed in」**，Cookie 才能維持數天至數週）。
4. 登入完成（網址跳轉）後，在**同一個分頁網址列**輸入並前往：
   👉 [https://auth.riotgames.com/.well-known/openid-configuration](https://auth.riotgames.com/.well-known/openid-configuration)
5. 按下鍵盤 **`F12`** 打開開發者工具：
   - 切換至 **`Network`（網路）** 分頁。
   - 按鍵盤 **`F5`** 重新整理網頁。
   - 在左側清單中點擊第 1 個項目 **`openid-configuration`**。
   - 在右側 **`Headers`** 面板往下捲動找到 **`Request Headers`** 區塊。
   - 找到 **`Cookie:`**，複製冒號後面的**整串完整內容**（包含 `ssid=...; csid=...; tdid=...` 等）。
   *(備註：也可以到 `Application` -> `Cookies` -> `https://auth.riotgames.com` 複製單獨的 `ssid` 欄位值)*。
6. ⚠️ **最關鍵的一步**：複製好後，**直接按視窗右上角的 `❌` 關閉整個無痕視窗**！（不要點網頁登出）。
7. **抓第 2 個人或下一個帳號時**：重新開啟一個新的無痕視窗，重複上述步驟 1~6 即可。

---

### 第三步：在 GitHub 專案設定 Secrets

1. 打開您 GitHub 上的這個專案（`Lun8211/val-dc`）。
2. 點選上方選單 **Settings** ➔ 左側 **Secrets and variables** ➔ **Actions** ➔ **New repository secret**。
3. 首先新增 **Discord 基本設定**：

| Secret 名稱 | 必填 | 說明 |
| :--- | :---: | :--- |
| `DISCORD_BOT_TOKEN` | ✅ 必填 | 您的 Discord 機器人 Token |
| `DISCORD_CHANNEL_ID` | ✅ 必填 | 預設要顯示每日商店的 Discord 頻道 ID |

4. 接著設定每位玩家的帳號資訊（提供 **2 種方式**，任選一種即可）：

#### 💡 方式 A（最直覺推薦）：使用編號 Secrets（支援管道分隔符號 `|`）
直接建立 `RIOT_SSID_1`、`RIOT_SSID_2`... 一個 Secret 搞定一個人的全部設定：

| Secret 名稱 | 內容填寫格式 | 範例 |
| :--- | :--- | :--- |
| **`RIOT_SSID_1`** | `暱稱\|Cookie內容\|Discord用戶ID` | `aaa\|ssid=eyJ...; csid=...\|123456789012345678` |
| **`RIOT_SSID_2`** | `暱稱\|Cookie內容\|Discord用戶ID` | `bbb\|ssid=eyJ...; csid=...\|234567890123456789` |
| **`RIOT_SSID_3`** | `暱稱\|Cookie內容\|Discord用戶ID` | `ccc\|ssid=eyJ...; csid=...\|345678901234567890` |
| **`RIOT_SSID_4`** | `暱稱\|Cookie內容\|Discord用戶ID` | `ddd\|ssid=eyJ...; csid=...\|456789012345678901` |
| **`RIOT_SSID_5`** | `暱稱\|Cookie內容\|Discord用戶ID` | `eee\|ssid=eyJ...; csid=...\|567890123456789012` |

> 📌 **欄位格式說明**：`暱稱|Cookie|Discord用戶ID|指定發送頻道ID(選填)`
> - 如果不需要 `@標註` 該成員，第 3 欄可留空，例如：`小明|貼上整串Cookie`。
> - 如果不需要暱稱，直接貼 Cookie 亦可，程式會自動抓取遊戲內真實的 `RiotID#TAG`。
> - 也支援把暱稱與 ID 分開寫成獨立 Secret：`ACCOUNT_NAME_1`、`DISCORD_USER_ID_1`。

#### 💡 方式 B：使用單一 `RIOT_ACCOUNTS` Secret（一行一個人）
建立一個名為 **`RIOT_ACCOUNTS`** 的 Secret，每一行代表一位玩家：
```text
Lun|貼上整串Cookie|123456789012345678
Mahiru|貼上整串Cookie|234567890123456789
Bliz|貼上整串Cookie|345678901234567890
```

---

### 第四步：立即手動測試發送！

1. 點選 GitHub 專案上方的 **Actions** 分頁。
2. 左側點選 **VALORANT 每日商店推送 (Daily Store Notifier)**。
3. 點擊右側的 **Run workflow** 按鈕 ➔ 點擊綠色的 **Run workflow**。
4. 等待約 20~30 秒，Discord 頻道就會依序跳出每位玩家的 4 張每日商店圖卡！

---

## ⚡ 在 Discord 使用 `/shop` 斜線指令即時查詢

除了每天早上 08:17 的自動推送外，如果你想隨時在 Discord 手動執行一次：

### 方式一：透過 GitHub Actions 臨時啟動機器人（不需開電腦）
1. 點選專案上方的 **Actions** 分頁。
2. 左側點選 **啟動 Discord /shop 指令機器人 (Interactive Slash Command Bot)**。
3. 點擊右側 **Run workflow**（可填寫要維持在線的分鐘數，例如 `30`）並送出。
4. 機器人上線後，任何伺服器成員即可在 Discord 輸入 **`/shop`**：
   - `/shop`：直接送出，依序查詢並推送所有人今天的商店。
   - `/shop account:🙋 我自己`：只顯示打指令者自己的商店（依 Discord ID 自動對應）。
   - `/shop account:[1] Lun`：點選自動完成選單，單獨查詢指定隊友的商店。

### 方式二：在自己的電腦或 VPS 上常駐執行
只要在電腦終端機啟動：
```bash
# 安裝依賴套件
pip install -r requirements.txt

# 複製環境變數範本並填入 DISCORD_BOT_TOKEN 等
cp .env.example .env

# 啟動常駐型機器人（支援 24 小時隨時回應 /shop 指令 + 每日定時推送）
python bot.py
```

---

## 💻 本地單次執行與測試指令

```bash
# 單次執行（立即查詢所有帳號並發送至 Discord 頻道）
python main.py

# 使用範例模擬資料測試 Discord 機器人發送效果（不需 Riot Cookie）
python main.py --mock

# 僅在終端機輸出生成的 JSON，不發送至 Discord
python main.py --dry-run
```

---

## 📁 專案結構

- [`main.py`](main.py)：多人單次執行入口（供 GitHub Actions 每日排程或本地命令列呼叫，具備單帳號獨立容錯）。
- [`bot.py`](bot.py)：Discord 機器人入口（支援即時伺服器同步、`/shop` 選單自動補全與可自訂下線時間）。
- [`src/valorant_client.py`](src/valorant_client.py)：Riot Cookie Reauth 換證邏輯、Storefront v3 API 與 `valorant-api.com` 繁體中文造型資料整合。
- [`src/discord_notifier.py`](src/discord_notifier.py)：建構 4 張 Discord Embed 圖卡並支援自訂暱稱、`@標註` 成員與錯誤提醒。
- [`src/config.py`](src/config.py)：支援多行 `RIOT_ACCOUNTS`、JSON 陣列與編號 `RIOT_SSID_1..20` 的多帳號設定解析器。
- [`.github/workflows/daily_store.yml`](.github/workflows/daily_store.yml)：GitHub Actions 每日定時排程（08:17）。
- [`.github/workflows/discord_bot.yml`](.github/workflows/discord_bot.yml)：GitHub Actions 隨選啟動 `/shop` 機器人工作流程。
