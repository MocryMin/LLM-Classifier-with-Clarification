@echo off
title Baogu Chat Playground

echo ============================================
echo   Baogu Chat Playground Launcher
echo ============================================
echo.

cd /d "%~dp0"

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.10+
    pause
    exit /b 1
)

:: Check Node.js
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found. Install Node.js 18+
    pause
    exit /b 1
)

:: Install backend deps
echo [1/4] Checking backend dependencies...
cd server
pip install -q fastapi uvicorn 2>nul
cd ..

:: Install frontend deps
echo [2/4] Checking frontend dependencies...
cd web
if not exist "node_modules" (
    echo   First run: installing frontend deps (~30s)...
    call npm install
)
cd ..

:: Start backend (cmd /k keeps window open on error)
echo [3/4] Starting backend (localhost:8000)...
start "Baogu Backend" cmd /k "cd /d "%~dp0server" && echo Starting backend... && python main.py 2>&1"
timeout /t 3 /nobreak >nul

:: Start frontend (cmd /k keeps window open on error)
echo [4/4] Starting frontend (localhost:5173)...
start "Baogu Frontend" cmd /k "cd /d "%~dp0web" && echo Starting frontend... && npm run dev"
timeout /t 4 /nobreak >nul

:: Open browser
echo.
echo ============================================
echo   Opening browser at http://localhost:5173
echo ============================================

start http://localhost:5173

echo.
pause
