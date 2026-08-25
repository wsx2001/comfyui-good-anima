@echo off
rem ============================================================
rem  comfyui-good-anima Chat 一键启动 / 停止脚本
rem
rem  用法：
rem    start.bat          启动（后端 8787 + 前端 5173）
rem    start.bat stop     停止（按端口杀掉两个服务）
rem    start.bat status   查看运行状态
rem ============================================================
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "BACKEND_PORT=8787"
set "FRONTEND_PORT=5173"

if "%~1"=="stop"   goto :stop
if "%~1"=="status" goto :status
goto :start

:start
echo [Good Anima Chat] Starting...

rem ---- check python deps ----
python -c "import fastapi, uvicorn, sqlmodel" >nul 2>&1
if errorlevel 1 (
    echo [deps] installing backend requirements...
    pushd "%ROOT%chat"
    python -m pip install -r requirements.txt || (popd & echo [error] pip install failed & pause & exit /b 1)
    popd
)

rem ---- check node_modules ----
if not exist "%ROOT%chat\frontend\node_modules" (
    echo [deps] installing frontend packages...
    pushd "%ROOT%chat\frontend"
    call npm install || (popd & echo [error] npm install failed & pause & exit /b 1)
    popd
)

rem ---- avoid double-start ----
call :port_pid %BACKEND_PORT%
if not "!PID!"=="" (
    echo [skip] backend already running ^(port %BACKEND_PORT%, PID !PID!^)
) else (
    echo [start] FastAPI backend  -^> http://127.0.0.1:%BACKEND_PORT%/
    start "good-anima-backend" cmd /k "cd /d %ROOT%chat && python -m backend"
)

call :port_pid %FRONTEND_PORT%
if not "!PID!"=="" (
    echo [skip] frontend already running ^(port %FRONTEND_PORT%, PID !PID!^)
) else (
    echo [start] Vue frontend     -^> http://127.0.0.1:%FRONTEND_PORT%/
    start "good-anima-frontend" cmd /k "cd /d %ROOT%chat\frontend && npm run dev"
)

timeout /t 3 /nobreak >nul
echo.
echo [done] open http://127.0.0.1:%FRONTEND_PORT%/ in browser. To stop: start.bat stop
exit /b 0

:stop
echo [Good Anima Chat] Stopping...
set FOUND=0
for %%p in (%BACKEND_PORT% %FRONTEND_PORT%) do (
    call :port_pid %%p
    if not "!PID!"=="" (
        echo [stop] port %%p -^> PID !PID!
        taskkill /F /T /PID !PID! >nul 2>&1
        set FOUND=1
    )
)
if "!FOUND!"=="0" echo [info] nothing is running.
exit /b 0

:status
call :port_pid %BACKEND_PORT%
if "!PID!"=="" (echo [status] backend %BACKEND_PORT% : DOWN) else (echo [status] backend %BACKEND_PORT% : UP ^(PID !PID!^))
call :port_pid %FRONTEND_PORT%
if "!PID!"=="" (echo [status] frontend %FRONTEND_PORT% : DOWN) else (echo [status] frontend %FRONTEND_PORT% : UP ^(PID !PID!^))
exit /b 0

 rem ---- helper: find PID listening on a port ----
:port_pid
set "PID="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":%~1 "') do set "PID=%%a"
exit /b 0
