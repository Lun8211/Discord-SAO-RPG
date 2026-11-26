@echo off
chcp 65001 >nul
title 停止刀劍神域 SAO 艾恩葛朗特 RPG Discord 機器人
cd /d "%~dp0"

if not exist "data\bot.pid" (
    if exist "data\bot.stop" del /f /q "data\bot.stop" >nul 2>&1
    echo [提示] 目前沒有偵測到正在執行中的機器人。
    if /i not "%~1"=="--no-pause" pause
    exit /b 0
)

set "BOT_PID="
set /p BOT_PID=<"data\bot.pid"

if not defined BOT_PID (
    del /f /q "data\bot.pid" >nul 2>&1
    echo [提示] 目前沒有偵測到正在執行中的機器人。
    if /i not "%~1"=="--no-pause" pause
    exit /b 0
)

tasklist /FI "PID eq %BOT_PID%" /NH 2>nul | findstr /C:"%BOT_PID%" >nul
if errorlevel 1 (
    del /f /q "data\bot.pid" >nul 2>&1
    if exist "data\bot.stop" del /f /q "data\bot.stop" >nul 2>&1
    echo [提示] 機器人目前已停止（已自動清理舊狀態檔）。
    if /i not "%~1"=="--no-pause" pause
    exit /b 0
)

echo [1/2] 已發送安全停止訊號給機器人 (PID: %BOT_PID%)，正在等待存檔與雲端備份完成...
echo stop>"data\bot.stop"

set /a WAIT_SEC=0
:wait_loop
ping -n 2 127.0.0.1 >nul
tasklist /FI "PID eq %BOT_PID%" /NH 2>nul | findstr /C:"%BOT_PID%" >nul
if errorlevel 1 goto stopped

set /a WAIT_SEC+=1
if %WAIT_SEC% LSS 15 goto wait_loop

echo [警告] 等待逾時，正在強制結束機器人程序 (PID: %BOT_PID%)...
taskkill /PID %BOT_PID% /T /F >nul 2>&1
del /f /q "data\bot.pid" >nul 2>&1
if exist "data\bot.stop" del /f /q "data\bot.stop" >nul 2>&1

:stopped
echo [2/2] 機器人已完成存檔並安全停止！
if /i not "%~1"=="--no-pause" pause
exit /b 0
