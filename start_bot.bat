@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "HIDDEN_MODE=0"
if /i "%~1"=="--hidden" set "HIDDEN_MODE=1"

if "%HIDDEN_MODE%"=="0" (
    title 刀劍神域 SAO 艾恩葛朗特 RPG Discord 機器人 (常駐模式)
)

if not exist "logs" mkdir "logs"

set "PYTHON_CMD="
python -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    py -3 -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    echo [錯誤] 找不到 Python 3！請至 https://www.python.org/downloads/ 安裝 Python 3.11 並勾選 Add python.exe to PATH。>> "logs\startup.log"
    if "%HIDDEN_MODE%"=="0" (
        echo [錯誤] 找不到 Python 3！
        echo 請至 https://www.python.org/downloads/ 安裝 Python 3.11，
        echo 並在安裝畫面最下方勾選 "Add python.exe to PATH" 後再重新執行。
        pause
    )
    exit /b 1
)

if not exist ".env" (
    if "%HIDDEN_MODE%"=="1" (
        echo [錯誤] 尚未建立 .env 設定檔，背景啟動已中止。請先手動執行一次 start_bot.bat 完成設定。>> "logs\startup.log"
        exit /b 3
    )
    echo [提示] 尚未建立 .env 設定檔，正在為您自動從 .env.example 建立 .env ...
    copy ".env.example" ".env" >nul
    echo [提示] 已為您打開 .env 記事本，請填入您的 DISCORD_BOT_TOKEN 後按 Ctrl+S 存檔，再重新點兩下此檔案！
    notepad ".env"
    pause
    exit /b 0
)

%PYTHON_CMD% -c "import discord, dotenv" >nul 2>&1
if errorlevel 1 (
    if "%HIDDEN_MODE%"=="0" echo [1/2] 首次啟動，正在安裝必要套件...
    %PYTHON_CMD% -m pip install -r requirements.txt --quiet >> "logs\startup.log" 2>&1
)

:loop
if exist "data\bot.stop" del /f /q "data\bot.stop" >nul 2>&1

if "%HIDDEN_MODE%"=="0" (
    echo.
    echo [啟動] 正在啟動刀劍神域 SAO 艾恩葛朗特 RPG Discord 機器人...
    echo [提示] 日誌將自動存至 logs\bot.log；按 Ctrl+C 或執行 stop_bot.bat 可安全存檔並關閉。
    %PYTHON_CMD% bot.py --log-file logs/bot.log
) else (
    %PYTHON_CMD% bot.py --log-file logs/bot.log >> "logs\startup.log" 2>&1
)

set "BOT_EXIT=%ERRORLEVEL%"

if "%BOT_EXIT%"=="0" (
    if "%HIDDEN_MODE%"=="0" echo [提示] 機器人已完成存檔並安全關閉。
    exit /b 0
)

if "%BOT_EXIT%"=="2" (
    if "%HIDDEN_MODE%"=="0" (
        echo [提示] 偵測到機器人已經在背景執行中，無需重複啟動。
        echo 若要關閉背景機器人，請雙擊 stop_bot.bat。
        pause
    )
    exit /b 2
)

if "%BOT_EXIT%"=="3" (
    if "%HIDDEN_MODE%"=="0" (
        echo [錯誤] .env 中尚未填入 DISCORD_BOT_TOKEN，請打開 .env 填入後再試。
        pause
    )
    exit /b 3
)

if exist "data\bot.stop" (
    del /f /q "data\bot.stop" >nul 2>&1
    exit /b 0
)

if "%HIDDEN_MODE%"=="0" (
    echo.
    echo [提示] 機器人已中斷連線（代碼 %BOT_EXIT%），將於 10 秒後自動重新啟動...
)
ping -n 11 127.0.0.1 >nul

if exist "data\bot.stop" (
    del /f /q "data\bot.stop" >nul 2>&1
    exit /b 0
)
goto loop
