@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "AUTO_MODE=0"
if /i "%~1"=="--auto" set "AUTO_MODE=1"

title 刀劍神域 SAO 艾恩葛朗特 RPG Discord 機器人 — 一鍵更新工具

set "REPO_URL=https://github.com/Lun8211/RPG"
set "REPO_BRANCH=main"
set "REPO_ZIP_URL=https://github.com/Lun8211/RPG/archive/refs/heads/main.zip"
set "RPG_DIR=%~dp0"

if not exist "logs" mkdir "logs"

echo ============================================================
echo   刀劍神域 SAO 艾恩葛朗特 RPG Discord 機器人 — 一鍵更新工具
echo ============================================================
echo.

REM ------------------------------------------------------------
REM [1/5] 檢查機器人是否正在執行，若有則先安全存檔停止
REM ------------------------------------------------------------
set "WAS_RUNNING=0"
set "BOT_PID="
if exist "data\bot.pid" (
    set /p BOT_PID=<"data\bot.pid"
)
if defined BOT_PID (
    tasklist /FI "PID eq %BOT_PID%" /NH 2>nul | findstr /C:"%BOT_PID%" >nul
    if not errorlevel 1 set "WAS_RUNNING=1"
)

if "%WAS_RUNNING%"=="1" (
    echo [1/5] 偵測到機器人正在執行 (PID: %BOT_PID%)，先進行安全存檔與停止...
    call "%~dp0stop_bot.bat" --no-pause
) else (
    echo [1/5] 機器人目前未執行，直接進入更新流程。
)

REM ------------------------------------------------------------
REM [2/5] 更新前自動備份本地存檔 data\rpg.db（保障資料零遺失）
REM ------------------------------------------------------------
if exist "data\rpg.db" (
    echo [2/5] 正在備份現有玩家存檔 data\rpg.db ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$dir = $env:RPG_DIR.TrimEnd('\'); $src = Join-Path $dir 'data\rpg.db'; $bakDir = Join-Path $dir 'data\backups'; New-Item -ItemType Directory -Force -Path $bakDir | Out-Null; $ts = Get-Date -Format 'yyyyMMdd_HHmmss'; Copy-Item -Path $src -Destination (Join-Path $bakDir ('pre_update_' + $ts + '.db')) -Force"
    if errorlevel 1 (
        echo [警告] 自動備份存檔時發生異常，但仍保留原始 data\rpg.db。
    ) else (
        echo       已安全備份至 data\backups\ 資料夾。
    )
) else (
    echo [2/5] 尚未建立本地存檔 data\rpg.db，略過存檔備份。
)

REM ------------------------------------------------------------
REM [3/5] 自動偵測更新模式（Git 拉取 / GitHub ZIP 下載覆蓋）
REM ------------------------------------------------------------
set "UPDATE_OK=0"
set "USE_GIT=0"
if exist ".git" (
    git --version >nul 2>&1
    if not errorlevel 1 set "USE_GIT=1"
)

if "%USE_GIT%"=="1" goto update_via_git
goto update_via_zip

:update_via_git
echo [3/5] 偵測到 Git 儲存庫，正在從 GitHub 同步最新版本 (%REPO_BRANCH%)...
git diff --quiet >nul 2>&1
set "DIRTY_WT=%ERRORLEVEL%"
git diff --cached --quiet >nul 2>&1
set "DIRTY_IDX=%ERRORLEVEL%"
if not "%DIRTY_WT%"=="0" (
    echo       偵測到本地有修改過追蹤檔案，先自動暫存 (git stash)...
    git stash push -m "pre-update-auto-backup" >> "logs\update.log" 2>&1
) else if not "%DIRTY_IDX%"=="0" (
    echo       偵測到本地有暫存區修改，先自動暫存 (git stash)...
    git stash push -m "pre-update-auto-backup" >> "logs\update.log" 2>&1
)

git fetch origin %REPO_BRANCH% >> "logs\update.log" 2>&1
if errorlevel 1 (
    echo [警告] git fetch 失敗，將自動改用 GitHub ZIP 下載模式重試...
    goto update_via_zip
)

git pull --ff-only origin %REPO_BRANCH% >> "logs\update.log" 2>&1
if errorlevel 1 (
    echo [警告] 無法直接 fast-forward 合併，將改用一般 git pull 嘗試同步...
    git pull origin %REPO_BRANCH% >> "logs\update.log" 2>&1
    if errorlevel 1 (
        echo [錯誤] Git 更新失敗！詳細原因請查看 logs\update.log。
        goto fail_exit
    )
)
set "UPDATE_OK=1"
echo       Git 同步完成！目前版本：
git log -n 1 --oneline
goto post_update

:update_via_zip
echo [3/5] 正在從 GitHub 下載最新 ZIP 並更新檔案（自動保留 .env 與 data 存檔）...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop';" ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
    "$dest = $env:RPG_DIR.TrimEnd('\');" ^
    "$tmp = Join-Path $env:TEMP ('sao_rpg_update_' + [Guid]::NewGuid().ToString('N').Substring(0,8));" ^
    "$zip = Join-Path $tmp 'repo.zip';" ^
    "$ext = Join-Path $tmp 'extracted';" ^
    "New-Item -ItemType Directory -Force -Path $ext | Out-Null;" ^
    "try {" ^
    "  Invoke-WebRequest -Uri $env:REPO_ZIP_URL -OutFile $zip -UseBasicParsing;" ^
    "  Expand-Archive -Path $zip -DestinationPath $ext -Force;" ^
    "  $root = Get-ChildItem -Path $ext -Directory | Select-Object -First 1;" ^
    "  if (-not $root) { throw 'ZIP 壓縮檔內容為空'; }" ^
    "  $skipTop = @('.env', '.env.local', '.env.production', 'data', 'logs', '.venv', '.git', '.agents');" ^
    "  Get-ChildItem -Path $root.FullName -Force | ForEach-Object {" ^
    "    if ($skipTop -contains $_.Name) { return }" ^
    "    $target = Join-Path $dest $_.Name;" ^
    "    if ($_.Name -ieq 'update_bot.bat') {" ^
    "      Copy-Item -Path $_.FullName -Destination (Join-Path $dest 'update_bot.bat.new') -Force;" ^
    "      return" ^
    "    }" ^
    "    if ($_.PSIsContainer) {" ^
    "      Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force;" ^
    "    } else {" ^
    "      Copy-Item -Path $_.FullName -Destination $target -Force;" ^
    "    }" ^
    "  }" ^
    "} finally {" ^
    "  if (Test-Path $tmp) { Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue }" ^
    "}" >> "logs\update.log" 2>&1
if errorlevel 1 (
    echo [錯誤] 從 GitHub 下載或解壓更新失敗！請檢查網路連線或查看 logs\update.log。
    goto fail_exit
)
set "UPDATE_OK=1"
echo       ZIP 下載與檔案覆蓋完成（已完整保留 .env 與 data 存檔）！
goto post_update

REM ------------------------------------------------------------
REM [4/5] 同步 Python 套件依賴並驗證 SAO JSON 內容
REM ------------------------------------------------------------
:post_update
echo [4/5] 正在檢查 Python 環境、更新套件並驗證 SAO 100 層資料檔...
set "PYTHON_EXE="
set "PYTHON_ARG="
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=.venv\Scripts\python.exe"
)
if not defined PYTHON_EXE (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    py -3 -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARG=-3"
    )
)

if not defined PYTHON_EXE (
    echo [錯誤] 找不到 Python 3！請安裝 Python 3.11+ 並勾選 Add python.exe to PATH。
    goto fail_exit
)

"%PYTHON_EXE%" %PYTHON_ARG% -m pip install -r requirements.txt --quiet >> "logs\update.log" 2>&1
if errorlevel 1 (
    echo [警告] pip 安裝套件回傳非零狀態，嘗試繼續驗證現有環境...
)

"%PYTHON_EXE%" %PYTHON_ARG% -c "from src.rpg.content.loader import load_and_validate_all; load_and_validate_all(); print('      SAO 100 層內容與頭目資料驗證通過！')"
if errorlevel 1 (
    echo [錯誤] SAO 遊戲資料驗證失敗！請查看 logs\update.log 或重新執行更新。
    goto fail_exit
)

REM ------------------------------------------------------------
REM [5/5] 完成更新並選擇啟動方式
REM ------------------------------------------------------------
echo.
echo ============================================================
echo   [5/5] 更新完成！你的 .env 與玩家存檔皆已完整保留。
echo   提示：若 Discord 尚未顯示最新斜線指令，按 Ctrl+R 重新整理即可。
echo ============================================================
echo.

if "%AUTO_MODE%"=="1" (
    if "%WAS_RUNNING%"=="1" (
        echo [自動模式] 正在背景重新啟動機器人...
        start "" wscript.exe "%~dp0start_bot_hidden.vbs"
    )
    goto finish_self_update
)

echo 請選擇接下來要執行的動作：
echo   [1] 立即在背景啟動機器人（無黑窗，推薦）
echo   [2] 開啟終端機視窗啟動機器人（可即時看上線日誌）
echo   [3] 暫不啟動，直接離開
echo.
set "CHOICE=1"
set /p "CHOICE=請輸入選項 (1-3，直接按 Enter 預設 1): "

if "%CHOICE%"=="1" (
    echo [啟動] 正在背景啟動刀劍神域 SAO 機器人...
    start "" wscript.exe "%~dp0start_bot_hidden.vbs"
    goto finish_self_update
)
if "%CHOICE%"=="2" (
    echo [啟動] 正在開啟終端機視窗啟動刀劍神域 SAO 機器人...
    start "" "%~dp0start_bot.bat"
    goto finish_self_update
)
echo [提示] 已更新完成，隨時可雙擊 start_bot.bat 啟動機器人！
goto finish_self_update

:finish_self_update
if exist "update_bot.bat.new" (
    start "" /b cmd /c "ping -n 2 127.0.0.1 >nul & move /y update_bot.bat.new update_bot.bat >nul"
)
if "%AUTO_MODE%"=="0" pause
exit /b 0

:fail_exit
echo.
echo [失敗] 更新未完成；你的 .env 與 data\rpg.db 皆未受影響。
if "%WAS_RUNNING%"=="1" (
    echo [提示] 若需要可雙擊 start_bot.bat 重新啟動原本的機器人。
)
if "%AUTO_MODE%"=="0" pause
exit /b 1
