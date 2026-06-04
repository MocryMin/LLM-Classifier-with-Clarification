@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo.
echo Baogu Chat Playground Launcher
echo ================================
echo.

cd /d "%~dp0"
if %errorlevel% neq 0 (
    echo [FAIL] Cannot cd to project dir: %~dp0
    pause
    exit /b 1
)
echo [OK] Project dir: %cd%
echo.

:: Check Python
echo [1/5] Checking Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] Python not found
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo   %%i

:: Check Node
echo [2/5] Checking Node.js...
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] Node.js not found
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('node --version 2^>^&1') do echo   Node %%i

:: Backend deps
echo [3/5] Installing backend deps...
cd /d "%~dp0server"
pip install -q fastapi uvicorn python-multipart 2>&1
if %errorlevel% neq 0 (
    echo [WARN] pip install may have failed, trying to continue...
)
cd /d "%~dp0"

:: Frontend deps
echo [4/5] Installing frontend deps...
cd /d "%~dp0web"
if not exist "node_modules" (
    echo   First run - this may take 30 seconds...
    call npm install
    if %errorlevel% neq 0 (
        echo [FAIL] npm install failed
        pause
        exit /b 1
    )
) else (
    echo   node_modules already exists, skipping
)
cd /d "%~dp0"

:: Start backend
echo [5/5] Starting servers...
echo.
echo   Backend window opening on port 8000...
start "Baogu-Backend" cmd /k "cd /d "%~dp0server" && echo Backend starting... && python main.py && pause"

:: Wait and start frontend
timeout /t 3 /nobreak >nul
echo   Frontend window opening on port 5173...
start "Baogu-Frontend" cmd /k "cd /d "%~dp0web" && echo Frontend starting... && npm run dev && pause"

:: Open browser after a delay
timeout /t 4 /nobreak >nul
echo   Opening browser...
start http://localhost:5173

echo.
echo ================================
echo   Done.
echo.
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo ================================
echo.
pause
