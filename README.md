# 🛒 val-dc — 特戰英豪 (VALORANT) 每日商店 Discord 機器人

自動擷取您的 **VALORANT（特戰英豪）** 帳號每日商店刷新的 **4 個武器造型**，並透過您的 **Discord 機器人** 在指定聊天頻道內以 **4 張精美 Embed 圖卡** 每日定時顯示（包含造型名稱、高清圖片、VP 價格、稀有度顏色與等級圖示、特效預覽影片連結，以及特務幣/輻能點數餘額）。

支援透過 **GitHub Actions 免費每日自動排程執行**（不需自己開著電腦或租用伺服器），也支援本地執行或常駐指令模式。

---

## ✨ 功能特色

- **4 張獨立 Discord Embed 圖卡**：一次發送包含 4 張 Embed 的訊息，完整呈現每日刷新的 4 把槍枝造型高清圖片、VP 售價、稀有度分級與對應色條。
- **支援特效影片預覽**：若造型具備升級特效影片，點擊標題或欄位連結即可直接預覽。
- **顯示錢包餘額與刷新倒數**：自動顯示帳號目前的 **VP（特務幣）**、**輻能點數（RP）** 與 **王國幣（KC）**，以及 Discord 動態倒數計時。
- **GitHub Actions 全自動排程**：預設於每日 **台灣時間早上 08:05（UTC 00:05）**（即特戰英豪每日 08:00 商店刷新後 5 分鐘）自動發送至您的 Discord 頻道。
- **Cookie 過期提醒**：當 Riot `ssid` Cookie 過期時，機器人會自動在頻道發送提醒通知。

---

## 🚀 快速設定教學（GitHub Actions 免伺服器每日自動發送）

只需要設定 **GitHub Secrets**，GitHub 就會每天早上自動幫您把商店發到 Discord 頻道！

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

### 第二步：取得 Riot 帳號的 `RIOT_SSID` Cookie

為了避開 Riot 登入驗證碼 (Captcha) 並保護您的密碼安全，本專案採用 Riot 官方認證 Cookie (`ssid`) 進行自動換發 Token：

1. 使用電腦瀏覽器（建議開無痕視窗）前往 Riot 登入網址：
   👉 [https://auth.riotgames.com/authorize?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in&client_id=play-valorant-web-prod&response_type=token%20id_token&nonce=1&scope=account%20openid](https://auth.riotgames.com/authorize?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in&client_id=play-valorant-web-prod&response_type=token%20id_token&nonce=1&scope=account%20openid)
2. 登入您的特戰英豪 Riot 帳號（登入時請勾選 **保持登入 / Stay signed in**，可延長 Cookie 效期）。
3. 登入後畫面會跳轉（或停留在 `playvalorant.com`），此時按下鍵盤 **`F12`** 開啟開發者工具：
   - 前往 **Application（應用程式）** 分頁 -> 左側展開 **Cookies**。
   - 若網址已跳轉，請在網址列重新開啟 `https://auth.riotgames.com`，並在左側 Cookies 點選 `https://auth.riotgames.com`。
   - 找到名稱為 **`ssid`** 的項目，複製它的 **Value（值）**（以 `eyJ...` 開頭的一長串字串）。

---

### 第三步：在 GitHub 專案設定 Secrets

1. 打開您 GitHub 上的這個專案（`Lun8211/val-dc`）。
2. 點選上方選單 **Settings** -> 左側 **Secrets and variables** -> **Actions**。
3. 點擊 **New repository secret**，依序新增以下 Secrets：

| Secret 名稱 | 必填 | 說明 |
| :--- | :---: | :--- |
| `DISCORD_BOT_TOKEN` | ✅ 必填 | 您的 Discord 機器人 Token |
| `DISCORD_CHANNEL_ID` | ✅ 必填 | 要顯示每日商店的 Discord 頻道 ID |
| `RIOT_SSID` | ✅ 必填 | 剛剛從 `auth.riotgames.com` 複製的 `ssid` Cookie 值 |
| `RIOT_REGION` | 選填 | 預設為 `ap`（台灣/亞太服）。美服填 `na`、歐服填 `eu`、韓服填 `kr` |
| `VALORANT_LANG` | 選填 | 預設為 `zh-TW`（繁體中文） |

---

### 第四步：立即測試發送！

1. 點選 GitHub 專案上方的 **Actions** 分頁。
2. 左側點選 **VALORANT 每日商店推送 (Daily Store Notifier)**。
3. 點擊右側的 **Run workflow** 按鈕：
   - 若想先測試 Discord 機器人發送效果，可勾選 `使用範例造型測試 Discord 機器人發送` 後執行。
   - 直接點擊綠色的 **Run workflow** 即可立即讀取您的真實每日商店並發送到 Discord 頻道！

---

## 💻 本地執行與常駐機器人模式（選用）

若您想在自己的電腦或 VPS 上執行：

```bash
# 1. 安裝依賴套件
pip install -r requirements.txt

# 2. 複製環境變數範本並填入您的 Token 與 Cookie
cp .env.example .env

# 3. 單次執行（立即查詢並發送至 Discord 頻道）
python main.py

# 4. 使用範例資料測試 Discord 發送
python main.py --mock

# 5. (選用) 啟動常駐型 Discord Bot（支援每日定時推送 + Discord 內輸入 /shop 指令隨時查詢）
python bot.py
```

---

## 📁 專案結構

- [`main.py`](main.py)：單次執行入口（供 GitHub Actions 每日排程或本地命令列呼叫）。
- [`bot.py`](bot.py)：常駐型 Discord 機器人入口（支援 `/shop` 斜線指令與每日定時任務）。
- [`src/valorant_client.py`](src/valorant_client.py)：Riot Cookie 驗證、Storefront v3 API 與 `valorant-api.com` 繁體中文造型資料整合。
- [`src/discord_notifier.py`](src/discord_notifier.py)：建構 4 張 Discord Embed 圖卡並透過 Bot Token / Webhook 發送。
- [`src/config.py`](src/config.py)：環境變數管理與驗證。
- [`.github/workflows/daily_store.yml`](.github/workflows/daily_store.yml)：GitHub Actions 每日定時排程設定。