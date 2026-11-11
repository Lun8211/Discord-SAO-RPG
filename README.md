# 🛒 val-dc — 特戰英豪 (VALORANT) 多人每日商店 Discord 機器人

自動擷取您與朋友們的多個 **VALORANT（特戰英豪）** 帳號每日商店刷新的 **4 個武器造型**，並透過您的 **Discord 機器人** 在指定聊天頻道內，依序為每個人的帳號發送 **4 張精美 Embed 圖卡**（包含自訂暱稱、自動 `@標註` 對應朋友、造型名稱、高清圖片、VP 價格、稀有度顏色與等級圖示、特效預覽影片連結，以及特務幣/輻能點數餘額）。

支援透過 **GitHub Actions 免費每日自動排程執行**（不需開著電腦或租用伺服器），也支援本地執行或常駐 `/shop` 指令模式。

---

## ✨ 功能特色

- **👥 支援多人帳號推送**：可綁定無限多個特戰英豪帳號，每天依序推送每個人的每日商店，並支援設定「玩家暱稱」、「自動 `@Tag` 對應的 Discord 成員」或「個別指定發送頻道」。
- **🛡️ 帳號獨立容錯與過期提醒**：若其中一位朋友的 `ssid` Cookie 過期，其他人的商店依然會正常推送，且機器人會針對過期的帳號發送提醒並 `@標註` 該名成員更新 Cookie。
- **🃏 4 張獨立 Discord Embed 圖卡**：每個帳號發送一則包含 4 張 Embed 的訊息，完整呈現每日刷新的 4 把槍枝造型高清圖片、VP 售價、稀有度分級與對應色條。
- **🎬 支援特效影片預覽**：若造型具備升級特效影片，點擊標題或欄位連結即可直接預覽。
- **⏰ GitHub Actions 全自動排程**：預設於每日 **台灣時間早上 08:05（UTC 00:05）**（即特戰英豪每日 08:00 商店刷新後 5 分鐘）自動發送至您的 Discord 頻道。

---

## 🚀 快速設定教學（GitHub Actions 免伺服器每日自動發送）

### 第一步：準備 Discord 機器人與頻道 ID

1. 前往 [Discord Developer Portal](https://discord.com/developers/applications) 建立或選擇您的 Application。
2. 點選左側 **Bot** 頁面：
   - 點擊 **Reset Token** 複製您的機器人 Token（即 `DISCORD_BOT_TOKEN`）。
3. 點選左側 **OAuth2 -> URL Generator**：
   - **Scopes** 勾選 `bot`（若想使用 `/shop` 指令可一併勾選 `applications.commands`）。
   - **Bot Permissions** 勾選 `Send Messages`、`Embed Links`、`View Channels`。
   - 複製下方產生的網址並邀請機器人進入您的 Discord 伺服器。
4. 在 Discord 中開啟「使用者設定 -> 進階 -> **開發者模式**」，對著您想顯示每日商店的文字頻道按右鍵 -> **複製頻道 ID**（即 `DISCORD_CHANNEL_ID`）。

---

### 第二步：取得每位玩家的 Riot `ssid` Cookie

每位想顯示每日商店的玩家，請各自執行以下步驟取得自己的 `ssid`：

1. 使用電腦瀏覽器（建議開無痕視窗）前往 Riot 登入網址：
   👉 [https://auth.riotgames.com/authorize?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in&client_id=play-valorant-web-prod&response_type=token%20id_token&nonce=1&scope=account%20openid](https://auth.riotgames.com/authorize?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in&client_id=play-valorant-web-prod&response_type=token%20id_token&nonce=1&scope=account%20openid)
2. 登入特戰英豪 Riot 帳號（登入時請務必勾選 **保持登入 / Stay signed in**，可延長 Cookie 效期）。
3. 登入後按下鍵盤 **`F12`** 開啟開發者工具：
   - 前往 **Application（應用程式）** 分頁 -> 左側展開 **Cookies**。
   - 若網址已跳轉至 `playvalorant.com`，請在網址列重新輸入 `https://auth.riotgames.com`，並在左側 Cookies 點選 `https://auth.riotgames.com`。
   - 找到名稱為 **`ssid`** 的項目，複製它的 **Value（值）**（以 `eyJ...` 開頭的一長串字串）。

---

### 第三步：在 GitHub 專案設定多人帳號 Secrets

1. 打開您 GitHub 上的這個專案（`Lun8211/val-dc`）。
2. 點選上方選單 **Settings** -> 左側 **Secrets and variables** -> **Actions** -> **New repository secret**。
3. 首先新增 **Discord 基本設定**：

| Secret 名稱 | 必填 | 說明 |
| :--- | :---: | :--- |
| `DISCORD_BOT_TOKEN` | ✅ 必填 | 您的 Discord 機器人 Token |
| `DISCORD_CHANNEL_ID` | ✅ 必填 | 預設要顯示每日商店的 Discord 頻道 ID |

4. 接著設定 **多人特戰英豪帳號**（提供以下 **2 種方式**，任選一種最方便的即可）：

#### 💡 方法 A（最推薦）：只新增一個 `RIOT_ACCOUNTS` Secret，一次貼上所有人的帳號
新增一個名為 **`RIOT_ACCOUNTS`** 的 Secret，內容**每行代表一個人**，格式如下：

```text
小明|eyJhbGciOiJSUzI1NiIs...|123456789012345678
阿華|eyJhbGciOiJSUzI1NiIs...|987654321098765432
小美|eyJhbGciOiJSUzI1NiIs...
```
> **格式說明**（以 `|` 分隔）：
> - `暱稱|ssid`：顯示 `🛒 【暱稱】RiotID#TAG 的 VALORANT 每日商店已刷新！`
> - `暱稱|ssid|Discord用戶ID`：除了顯示暱稱外，還會自動 `<@Discord用戶ID>` 標註提醒對方！
> - `暱稱|ssid|Discord用戶ID|指定頻道ID`：若想把某個人的商店發到獨立頻道，可加在第 4 欄。
> - 也可以直接每行只貼純 `ssid`，程式會自動抓遊戲內的 `RiotID#TAG` 名稱！

---

#### 💡 方法 B：使用編號 Secrets 分別設定（`RIOT_SSID_1`, `RIOT_SSID_2` ...）
若喜歡把每個人的 Secret 分開管理，可以直接建立編號 `_1` ~ `_10` 的 Secrets：

| Secret 名稱 | 必填 | 說明 |
| :--- | :---: | :--- |
| `RIOT_SSID_1` | ✅ 帳號1必填 | 第 1 位玩家的 `ssid` Cookie |
| `ACCOUNT_NAME_1` | 選填 | 第 1 位玩家的自訂暱稱（例如：`小明`） |
| `DISCORD_USER_ID_1` | 選填 | 第 1 位玩家的 Discord User ID（發送時自動 `@標註`） |
| `RIOT_SSID_2` | ✅ 帳號2必填 | 第 2 位玩家的 `ssid` Cookie |
| `ACCOUNT_NAME_2` | 選填 | 第 2 位玩家的自訂暱稱（例如：`阿華`） |
| `DISCORD_USER_ID_2` | 選填 | 第 2 位玩家的 Discord User ID |
| `RIOT_SSID_3` ~ `RIOT_SSID_10` | 選填 | 以此類推，最高支援至 `_10`（本地 `.env` 支援至 `_20`） |

*(註：單一帳號原本的 `RIOT_SSID` 依然完全相容！)*

---

### 第四步：立即測試發送！

1. 點選 GitHub 專案上方的 **Actions** 分頁。
2. 左側點選 **VALORANT 每日商店推送 (Daily Store Notifier)**。
3. 點擊右側的 **Run workflow** 按鈕：
   - 若想先測試多人 Discord 發送排版效果，可勾選 `使用範例造型測試 Discord 機器人發送` 後執行。
   - 直接點擊綠色的 **Run workflow** 即可立即讀取所有已設定帳號的真實每日商店並發送到 Discord 頻道！

---

## 💻 本地執行與常駐機器人模式（選用）

```bash
# 1. 安裝依賴套件
pip install -r requirements.txt

# 2. 複製環境變數範本並填入您的 Token 與多人帳號設定
cp .env.example .env

# 3. 單次執行（依序查詢所有帳號並發送至 Discord 頻道）
python main.py

# 4. 使用範例資料測試多人商店發送
python main.py --mock

# 5. (選用) 啟動常駐型 Discord Bot（支援每日定時推送 + /shop [account] 指定或全部帳號查詢）
python bot.py
```

---

## 📁 專案結構

- [`main.py`](main.py)：多人單次執行入口（供 GitHub Actions 每日排程或本地命令列呼叫，共用一次造型目錄快取並具備單帳號獨立容錯）。
- [`bot.py`](bot.py)：常駐型 Discord 機器人入口（支援 `/shop` 斜線指令篩選特定帳號或顯示全部帳號，以及每日定時任務）。
- [`src/valorant_client.py`](src/valorant_client.py)：Riot Cookie 驗證、Storefront v3 API 與 `valorant-api.com` 繁體中文造型資料整合。
- [`src/discord_notifier.py`](src/discord_notifier.py)：建構 4 張 Discord Embed 圖卡並支援顯示自訂暱稱、`@標註` 成員與分頻道發送。
- [`src/config.py`](src/config.py)：支援多行 `RIOT_ACCOUNTS`、JSON 陣列與編號 `RIOT_SSID_1..20` 的多帳號設定解析器。
- [`.github/workflows/daily_store.yml`](.github/workflows/daily_store.yml)：GitHub Actions 每日定時排程設定。