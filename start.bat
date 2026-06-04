@echo off
chcp 65001 >nul
title 智能管家 · Chat Playground

echo.
echo ╔══════════════════════════════════════════════╗
echo ║     智能管家 · 对话测试工作台                   ║
echo ║     Chat Playground Launcher                 ║
echo ╚══════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: ─── 检查 Python ──────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: ─── 检查 Node.js ──────────────────────────────────
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Node.js，请先安装 Node.js 18+
    pause
    exit /b 1
)

:: ─── 安装后端依赖 ──────────────────────────────────
echo [1/4] 检查后端依赖...
cd server
pip install -q fastapi uvicorn 2>&1 >nul
cd ..

:: ─── 安装前端依赖 ──────────────────────────────────
echo [2/4] 检查前端依赖...
cd web
if not exist "node_modules" (
    echo   首次运行，正在安装前端依赖 (约 30 秒)...
    call npm install --silent 2>&1 >nul
)
cd ..

:: ─── 启动后端 (新窗口) ─────────────────────────────
echo [3/4] 启动后端服务 (localhost:8000)...
start "智能管家 · 后端" cmd /c "cd /d "%~dp0server" && python main.py"

:: 等后端启动
echo   等待后端启动...
timeout /t 3 /nobreak >nul

:: ─── 启动前端 (新窗口) ─────────────────────────────
echo [4/4] 启动前端界面 (localhost:5173)...
start "智能管家 · 前端" cmd /c "cd /d "%~dp0web" && npm run dev"

:: 等前端启动
echo   等待前端启动...
timeout /t 4 /nobreak >nul

:: ─── 打开浏览器 ────────────────────────────────────
echo.
echo ╔══════════════════════════════════════════════╗
echo ║  启动完成！浏览器即将打开...                    ║
echo ║                                              ║
echo ║  后端:  http://localhost:8000                 ║
echo ║  前端:  http://localhost:5173                 ║
echo ║                                              ║
echo ║  关闭此窗口不会停止服务                          ║
echo ║  请分别关闭"后端"和"前端"两个窗口来停止            ║
echo ╚══════════════════════════════════════════════╝

start http://localhost:5173

echo.
echo 按任意键退出此窗口 (不会停止服务)...
pause >nul
