# ⚔️ 星界紀元 RPG — Discord 持久化長線冒險機器人

一套專為 Discord 打造的**完整長線養成 RPG 機器人**，整合全按鈕互動選單、**免費開源奇幻圖庫與裝備展示圖卡**，以及 **SQLite WAL 即時自動存檔＋選填雲端快照備份**——無論在自己的電腦、VPS，還是透過 **GitHub Actions** 隨選啟動，每次機器人重啟都能完整記憶所有玩家的資料、裝備、進度與全服世界王狀態！

---

## ✨ 核心玩法特色

- **🎨 免費開源奇幻圖庫 × 視覺化圖卡**：整合經典開源奇幻戰棋專案 [The Battle for Wesnoth](https://github.com/wesnoth/wesnoth)（GPL-2.0，零 API Key、完全免費），所有裝備（`T1~T6` × 6 大部位）、副本與世界王首領立繪、1轉~3轉進階職業立繪、礦區／鐵匠鋪／遠征場景橫幅，以及戰鬥掉落、開箱、鍛造、強化結果皆以精美 Embed 圖卡呈現。
- **🧙 四大職業與三段覺醒轉職**：劍士、法師、遊俠、聖騎士，各有專屬主動技能與終極奧義；達 `Lv.30` 可二轉、`Lv.70` 可三轉覺醒（立繪同步進化），亦可透過轉職徽章自由切換職業並保留階級。
- **⛏️ 階梯挖礦、礦鎬鍛造與奇遇**：6 大階梯礦區（翠綠淺礦坑 ➔ 星界原初脈）、`T1~T8` 礦鎬鍛造升級、採礦連擊熱度倍率與隨機礦脈奇遇（富礦脈、星晶簇、遠古寶箱、哥布林偷襲）。
- **🛡️ 深度裝備、套裝、強化與圖鑑展示**：
  - 6 大部位（武器、頭盔、護甲、手套、戰靴、飾品）、6 階稀有度（普通 ~ 神話）、隨機詞條與 5 大套裝（2 件／4 件套效果）。
  - 鐵匠鋪支援指定部位鍛造與 **`+1 ~ +15` 強化（絕不碎裝，失敗累積保底祝福值，達 100% 必成，並支援保護卷軸防止高階掉階）**。
  - 支援 `/inspect` 指令與背包下拉選單，隨時檢視與公開展示裝備圖片卡片。
- **🏰 副本、無盡深淵與全服世界王**：
  - **8 大階梯副本 × 普通／困難／地獄 3 種難度**：支援首領立繪即時預覽、回合制互動戰鬥（首領蓄力預警 + 防禦反擊）、自動戰鬥、勝利掉落裝備展示卡，通關後解鎖快速掃蕩。
  - **🗼 無盡深淵**：無限爬塔挑戰，每 5 層守門王豐厚大獎，長線戰力試金石。
  - **🐉 全伺服器共鬥世界王**：全服共享血條與即時傷害貢獻榜，擊殺後自動發放獎勵給所有參與玩家，並刷新更高階世界王。
- **🛒 多元商店與抽箱保底**：常駐物資店、每 6 小時全服同步刷新的限時折扣神秘商店、星界秘寶抽箱（10 抽傳說保底／30 抽神話保底）與多餘礦石出售／低階裝備一鍵分解。
- **📅 每日簽到、任務、離線派遣、成就與轉生飛升**：7 日循環簽到、每日／每週任務、**離線與重啟皆持續計時的冒險派遣**、17 項永久屬性加成成就與稱號，以及 **`Lv.100` 星界轉生飛升**（保留裝備、礦鎬與資源，永久疊加全屬性與收益倍率）。
- **🏆 6 大伺服器排行榜**：戰力榜、等級轉生榜、無盡深淵榜、財富榜、礦神榜、世界王貢獻榜。
- **🎭 `/p` 二次元梗圖／表情包隨機抽選**：免費串接多個 GitHub 開源中文二次元梗圖與表情包資料庫（零 API Key、3,000+ 張以上圖庫），支援一鍵 `/p` 平衡隨機抽圖、分類篩選（二次元綜合／經典動漫／藍色大肥魚 DeepSeek娘／動態 GIF）、繁簡中文關鍵字搜尋，以及「換一張／再來一張／原圖」互動按鈕。

---

## 📜 斜線指令一覽（直接輸入 `/` 即可使用）

| 指令 | 說明 |
| :--- | :--- |
| `/start` | 建立冒險者檔案、選擇初始職業並領取新手裝備包 |
| `/profile` | 查看自己或隊友的角色面板、職業立繪、戰力、裝備與主城快捷按鈕 |
| `/mine` | 進入 6 大階梯礦區挖礦（附礦區橫幅、連挖與快速喝體力劑按鈕） |
| `/dungeon` | 開啟副本征討大廳（首領立繪預覽）或直接進入指定副本與難度開戰／掃蕩 |
| `/abyss` | 挑戰無限層數「無盡深淵」爬塔 |
| `/boss` | 查看並共同討伐全伺服器共享血條的「世界王」 |
| `/shop` | 開啟冒險商店（常駐物資、6 小時神秘商店、保底抽箱、礦石回收） |
| `/bag` | 管理裝備與材料背包、鎖定裝備、檢視裝備圖卡、一鍵穿戴最佳裝備 |
| `/equip` | 穿戴指定裝備（支援自動補全），留空則一鍵自動穿戴各部位最強裝備 |
| `/inspect` | 公開展示指定或最強裝備的精美圖片卡片、屬性、詞條與套裝加成 |
| `/forge` | 進入鐵匠鋪（指定部位鍛造套裝、升級礦鎬、強化裝備 `+1~+15`、一鍵分解） |
| `/daily` | 每日連續簽到與一鍵領取每日／每週任務獎勵 |
| `/expedition` | 派遣離線冒險探索（離線或重啟皆持續計時領取戰利品） |
| `/class` | 職業殿堂（`Lv.30` 二轉、`Lv.70` 三轉覺醒，或消耗轉職徽章自由切換職業） |
| `/rebirth` | 滿級 `Lv.100` 星界轉生飛升（保留裝備與進度，永久獲得全屬性倍率加成） |
| `/achievements` | 查看 17 項永久屬性加成成就並切換配戴顯示稱號 |
| `/leaderboard` | 查看 6 大伺服器排行榜（支援下拉選單即時切換） |
| `/p` | 隨機產生一張二次元梗圖／表情包（支援分類篩選、繁簡關鍵字搜尋與互動換圖按鈕） |
| `/help` | 查看完整新手指南與指令說明 |

---

## 🚀 快速開始與啟動教學

### 第一步：建立並邀請 Discord 機器人

1. 前往 [Discord Developer Portal](https://discord.com/developers/applications) 建立或選擇您的 Application。
2. 點選左側 **Bot** 頁面 ➔ 點擊 **Reset Token** 複製您的機器人 Token（即 `DISCORD_BOT_TOKEN`）。
3. 點選左側 **OAuth2 -> URL Generator**：
   - **Scopes** 勾選 `bot` 與 **`applications.commands`**（使用斜線指令必勾）。
   - **Bot Permissions** 勾選 `View Channels`、`Send Messages`、`Embed Links`、`Attach Files`、`Read Message History`（後兩項為選填私有備份頻道自動存檔所需）。
   - 複製下方生成的網址並將機器人邀請進您的 Discord 伺服器。

---

### 第二步：選擇啟動方式

#### 方式一：透過 GitHub Actions 免伺服器啟動（推薦先體驗）

1. 打開您的 GitHub 專案，點選上方 **Settings** ➔ **Secrets and variables** ➔ **Actions** ➔ **New repository secret**，設定以下 Secrets：

| Secret 名稱 | 必填 | 說明 |
| :--- | :---: | :--- |
| `DISCORD_BOT_TOKEN` | ✅ 必填 | 您的 Discord 機器人 Token |
| `RPG_BACKUP_CHANNEL_ID` | ⭐ 強烈建議 | 在 Discord 建立一個**僅管理員與機器人可見的私有文字頻道**，貼上頻道 ID；每次 Actions 重啟都會自動還原與備份所有玩家進度，永不掉檔！ |
| `TIMEZONE_OFFSET_HOURS` | 選填 | 每日簽到與任務重置時區（預設 `8`，即台灣時間 UTC+8） |
| `RPG_BACKUP_INTERVAL_MINUTES` | 選填 | 自動備份間隔分鐘數（預設 `15`） |

2. 點選專案上方的 **Actions** 分頁 ➔ 左側點選 **啟動星界紀元 RPG Discord 機器人 (Interactive RPG Bot)**。
3. 點擊右側 **Run workflow**，輸入要維持上線的分鐘數（最長 `350` 分鐘，到期前會自動完成存檔並安全下線）即可開玩！

#### 方式二：在自己的電腦或 VPS 上 24 小時常駐執行

- **Windows 使用者（支援完全無黑窗開機自動啟動）**：
  1. 下載整個專案並解壓縮到固定資料夾（例如 `C:\RPG-Bot`）。
  2. 先手動點兩下 [`start_bot.bat`](start_bot.bat)：首次會自動建立 `.env` 並打開記事本，填入 `DISCORD_BOT_TOKEN` 存檔後再點兩下確認機器人正常上線。
  3. 測試沒問題後關掉黑窗，點兩下 [`setup_autostart.bat`](setup_autostart.bat) ➔ 輸入 **`1`**，即可一鍵安裝**「開機自動無黑窗背景啟動」**並立刻在背景上線！
  4. 平常想確認執行紀錄可開 [`setup_autostart.bat`](setup_autostart.bat) 選 `[5]`（或直接看 `logs\bot.log`）；想安全存檔並關閉背景機器人只要點兩下 [`stop_bot.bat`](stop_bot.bat)。
- **macOS / Linux / VPS 使用者**：

```bash
# 安裝依賴套件
pip install -r requirements.txt

# 複製環境變數範本並填入 DISCORD_BOT_TOKEN
cp .env.example .env

# 啟動常駐型 RPG 機器人
python bot.py
```

---

## 💾 重啟永久存檔機制（本地 & 雲端皆支援）

1. **本地常駐（`start_bot.bat` / 本機 / VPS）**：
   - 所有遊玩進度即時以 **SQLite WAL 交易模式**寫入 `data/rpg.db`（可透過 `RPG_DB_PATH` 自訂），並於定時與安全關機前自動執行 WAL checkpoint 與輪替備份至 `data/backups/`。
   - **免任何額外設定**，每次重新啟動機器人皆會完整記憶所有人的角色、裝備、背包、副本通關、深淵紀錄、離線派遣與世界王血量！
2. **GitHub Actions / 無本地硬碟雲端環境**：
   - 只要在 Secrets 設定 **`RPG_BACKUP_CHANNEL_ID`**（指向僅管理員與機器人可見的私有文字頻道），機器人開機時會自動從該頻道還原最新壓縮快照（附版本序號防回滾保護），執行期間定時上傳並於關機前自動備份，**永不掉檔且絕不公開任何玩家資料**。

---

## 🧪 執行單元測試

```bash
pytest -v
```

測試涵蓋：全流程重啟持久化、Gzip 快照還原與防回滾保護、Discord 備份頻道同步、挖礦／鍛造／強化保底與保護卷軸、副本／掃蕩／無盡深淵、全服世界王共鬥、商店抽箱保底、轉職轉生、全套 120+ 張免費圖庫資源格式驗證、本機單實例防重複鎖定與輪替日誌，以及所有 Embed 圖卡與 Discord UI View 版面檢查。

---

## 🎨 免費開源美術素材與梗圖資料庫授權致謝

- **RPG 奇幻圖庫**：本專案 RPG 系統之裝備圖示、職業與首領立繪及場景橫幅皆取自免費開源專案 **[The Battle for Wesnoth](https://github.com/wesnoth/wesnoth)**（GPL-2.0 授權），透過 GitHub 固定 Commit CDN 靜態載入，完全免費且無需任何 API Key。
- **`/p` 二次元梗圖免費開源資料庫**：動態串接以下免費公開 GitHub 社群開源二次元表情包與梗圖倉庫（零 API Key、無需額外設定，原圖版權歸各原作者與社群貢獻者所有，僅供非商業交流使用）：
  - [DDZS987/astrbot-meme-pack-semantic-01](https://github.com/DDZS987/astrbot-meme-pack-semantic-01)（二次元綜合梗圖庫）
  - [DumKing/ChineseBQB-AstrBot](https://github.com/DumKing/ChineseBQB-AstrBot)（精選整理自 [zhaoolee/ChineseBQB](https://github.com/zhaoolee/ChineseBQB) 的純動漫分類：原神、芙莉蓮、北方栖姬、阿庫婭、JOJO、輝夜大小姐、間諜過家家、鬼滅之刃、進擊的巨人、美少女戰士、電鋸人等）
  - [EDMOK/blue-fish-archive](https://github.com/EDMOK/blue-fish-archive)、[anka-afk/deepseek-fanart-meme-pack](https://github.com/anka-afk/deepseek-fanart-meme-pack)、[anka-afk/blue-fat-fish-meme-pack](https://github.com/anka-afk/blue-fat-fish-meme-pack)、[yyh-001/dsh-meme-packs](https://github.com/yyh-001/dsh-meme-packs)（藍色大肥魚／DeepSeek娘與 AI 娘化動靜態梗圖）
  - [NooAcc/astrbot-meme-IzumiHiyori](https://github.com/NooAcc/astrbot-meme-IzumiHiyori)、[anka-afk/juxueli-meme-pack](https://github.com/anka-afk/juxueli-meme-pack)、[anka-afk/congyu-meme-pack](https://github.com/anka-afk/congyu-meme-pack)、[anka-afk/clover-days-meme-pack](https://github.com/anka-afk/clover-days-meme-pack)（和泉妃愛、橘雪莉、叢雨、鷹倉杏鈴等萌系動漫表情包）

---

## 📁 專案結構

- [`bot.py`](bot.py)：Discord 機器人入口（註冊 19 個頂層斜線指令含 RPG 與 `/p` 梗圖、防重複啟動鎖定、UTF-8 輪替日誌、定時與關機前 SQLite／雲端備份還原、支援 `--run-minutes` 定時安全下線與本機安全停止訊號）。
- [`src/config.py`](src/config.py)：環境變數與 RPG 存檔／備份頻道設定解析器。
- [`src/memes/`](src/memes/)：`/p` 隨機二次元梗圖模組：
  - [`catalog.py`](src/memes/catalog.py)：免費開源線上二次元梗圖多來源索引抓取器、記憶體快取（TTL 6 小時＋背景刷新）、SFW 過濾、繁簡關鍵字搜尋、防連抽重複與離線備援圖庫。
  - [`commands.py`](src/memes/commands.py)：`/p` 斜線指令、Embed 卡片建構器與「換一張／再來一張／原圖」互動按鈕。
- [`src/rpg/`](src/rpg/)：完整持久化長線 RPG 核心模組：
  - [`database.py`](src/rpg/database.py)：SQLite WAL 持久化、自動輪替備份與 Discord 私有頻道 Gzip 快照還原／上傳。
  - [`data.py`](src/rpg/data.py)：職業、礦區、礦鎬、裝備、詞條、套裝、副本、世界王、商店、任務、成就與派遣數值設定。
  - [`models.py`](src/rpg/models.py)：玩家、裝備、戰鬥狀態、遠征與世界王資料模型。
  - [`engine.py`](src/rpg/engine.py)：核心遊戲邏輯引擎（戰力計算、挖礦、鍛造強化、回合制戰鬥、深淵、世界王、商店抽箱、轉職轉生）。
  - [`assets.py`](src/rpg/assets.py)：免費開源奇幻圖庫 URL 註冊表（裝備、首領、職業立繪、礦區與場景橫幅）。
  - [`embeds.py`](src/rpg/embeds.py)：Discord Embed 介面與裝備展示圖卡建構器。
  - [`views.py`](src/rpg/views.py)：互動式按鈕與下拉選單 UI 元件。
  - [`commands.py`](src/rpg/commands.py)：頂層斜線指令與自動補全實作。
- [`tests/test_rpg.py`](tests/test_rpg.py)：RPG 核心玩法、持久化、圖庫與 UI 完整單元測試。
- [`tests/test_memes.py`](tests/test_memes.py)：`/p` 二次元梗圖指令、線上多來源資料庫解析、SFW 過濾、繁簡搜尋與互動元件單元測試。
- [`start_bot.bat`](start_bot.bat)：Windows 一鍵常駐啟動腳本（含自動建立 `.env`、防重複啟動、UTF-8 日誌與斷線重連）。
- [`start_bot_hidden.vbs`](start_bot_hidden.vbs)：Windows 無黑窗靜默背景啟動器。
- [`setup_autostart.bat`](setup_autostart.bat)：Windows 一鍵安裝／移除開機自動無黑窗啟動與狀態／紀錄查看工具。
- [`stop_bot.bat`](stop_bot.bat)：Windows 一鍵安全存檔並停止背景機器人。
- [`.github/workflows/discord_bot.yml`](.github/workflows/discord_bot.yml)：GitHub Actions 隨選啟動 Discord RPG 機器人工作流程。
