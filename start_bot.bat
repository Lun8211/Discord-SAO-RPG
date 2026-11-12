@echo off
chcp 65001 >nul
title VALORANT 每日商店 Discord 機器人 (常駐模式)
cd /d "%~dp0"

if not exist ".env" (
    echo [提示] 尚未建立 .env 設定檔，正在為您自動從 .env.example 建立 .env ...
    copy ".env.example" ".env" >nul
    echo [提示] 已為您打開 .env 記事本，請填入您的 DISCORD_BOT_TOKEN 與 RIOT_SSID_1~5 後按 Ctrl+S 存檔，再重新點兩下此檔案！
    notepad ".env"
    pause
    exit /b
)

echo [1/2] 正在檢查並安裝必要套件...
python -m pip install -r requirements.txt --quiet

:loop
echo.
echo [2/2] 正在啟動 VALORANT Discord 機器人 (按 Ctrl+C 可關閉)...
python bot.py
echo.
echo [提示] 機器人已中斷連線，將於 10 秒後自動重新啟動...
timeout /t 10
goto loop
