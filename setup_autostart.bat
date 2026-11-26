@echo off
chcp 65001 >nul
title 刀劍神域 SAO 艾恩葛朗特 RPG 機器人 — Windows 開機無黑窗自啟動管理工具
cd /d "%~dp0"

set "STARTUP_LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\RPG_Discord_Bot.lnk"

:menu
cls
echo ============================================================
echo   刀劍神域 SAO 艾恩葛朗特 RPG Discord 機器人 — 開機無黑窗自啟動管理工具
echo ============================================================
echo.

if exist "%STARTUP_LNK%" (
    echo   開機自動啟動：[已啟用]
) else (
    echo   開機自動啟動：[未啟用]
)

set "BOT_RUNNING=0"
set "BOT_PID="
if exist "data\bot.pid" (
    set /p BOT_PID=<"data\bot.pid"
)
if defined BOT_PID (
    tasklist /FI "PID eq %BOT_PID%" /NH 2>nul | findstr /C:"%BOT_PID%" >nul
    if not errorlevel 1 set "BOT_RUNNING=1"
)
if "%BOT_RUNNING%"=="1" (
    echo   機器人狀態  ：[執行中] (PID: %BOT_PID%)
) else (
    echo   機器人狀態  ：[未執行]
)

if exist ".env" (
    echo   .env 設定檔 ：[已建立]
) else (
    echo   .env 設定檔 ：[尚未建立 — 請先執行一次 start_bot.bat]
)

echo.
echo ------------------------------------------------------------
echo   [1] 安裝「開機自動無黑窗啟動」＋ 立即在背景啟動機器人
echo   [2] 僅安裝「開機自動無黑窗啟動」（下次開機生效）
echo   [3] 移除「開機自動啟動」
echo   [4] 安全停止目前背景執行中的機器人
echo   [5] 查看最新 25 行執行紀錄 (logs\bot.log)
echo   [0] 離開
echo ------------------------------------------------------------
echo.

set "SEL="
set /p "SEL=請輸入選項編號 (0-5): "

if "%SEL%"=="1" goto install_and_start
if "%SEL%"=="2" goto install_only
if "%SEL%"=="3" goto uninstall
if "%SEL%"=="4" goto stop_now
if "%SEL%"=="5" goto view_logs
if "%SEL%"=="0" exit /b 0
goto menu

:create_shortcut
set "RPG_LNK_PATH=%STARTUP_LNK%"
set "RPG_VBS_PATH=%~dp0start_bot_hidden.vbs"
set "RPG_WORK_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$q = [char]34; $ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut($env:RPG_LNK_PATH); $s.TargetPath = 'wscript.exe'; $s.Arguments = $q + $env:RPG_VBS_PATH + $q; $s.WorkingDirectory = $env:RPG_WORK_DIR.TrimEnd('\'); $s.Description = 'Astral Era RPG Discord Bot Auto-Start'; $s.Save()"
exit /b %ERRORLEVEL%

:install_and_start
echo.
if not exist ".env" (
    echo [提醒] 尚未建立 .env 設定檔！
    echo 請先關閉此視窗，雙擊 start_bot.bat 填入 DISCORD_BOT_TOKEN 並測試上線後，再回來執行 [1]。
    echo.
    pause
    goto menu
)
call :create_shortcut
if errorlevel 1 (
    echo [錯誤] 建立開機啟動捷徑失敗，請確認 PowerShell 可正常執行。
    pause
    goto menu
)
echo [完成] 已安裝開機自動無黑窗啟動！
echo [啟動] 正在於背景靜默啟動機器人（無黑窗）...
start "" wscript.exe "%~dp0start_bot_hidden.vbs"
ping -n 4 127.0.0.1 >nul
echo [完成] 機器人已於背景啟動！可按 [5] 查看上線紀錄，或直接到 Discord 測試指令。
echo.
pause
goto menu

:install_only
echo.
call :create_shortcut
if errorlevel 1 (
    echo [錯誤] 建立開機啟動捷徑失敗。
) else (
    echo [完成] 已安裝開機自動無黑窗啟動！下次 Windows 開機登入時將自動於背景啟動機器人。
    if not exist ".env" echo [提醒] 別忘了先雙擊 start_bot.bat 填入 DISCORD_BOT_TOKEN！
)
echo.
pause
goto menu

:uninstall
echo.
if exist "%STARTUP_LNK%" (
    del /f /q "%STARTUP_LNK%" >nul 2>&1
    echo [完成] 已移除 Windows 開機自動啟動捷徑。
) else (
    echo [提示] 目前本來就沒有安裝開機自動啟動。
)
echo.
pause
goto menu

:stop_now
echo.
call "%~dp0stop_bot.bat" --no-pause
echo.
pause
goto menu

:view_logs
echo.
if exist "logs\bot.log" (
    echo --- logs\bot.log 最新 25 行 ---
    powershell -NoProfile -Command "Get-Content -Path 'logs\bot.log' -Encoding UTF8 -Tail 25"
) else (
    echo [提示] 目前尚未產生 logs\bot.log（請先啟動一次機器人）。
)
echo.
pause
goto menu
