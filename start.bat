@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

title 智能管家 V3 启动器

echo.
echo ================================================================
echo   智能管家 V3 — Chat Playground 启动器
echo ================================================================
echo.

:: ─── Locate project root (handle双击启动) ─────────────────
cd /d "%~dp0"
if errorlevel 1 (
    echo [FAIL] 无法切换到项目目录: %~dp0
    pause
    exit /b 1
)
echo [OK] 项目目录: %cd%
echo.

:: ─── Required dirs check ────────────────────────────────
if not exist "server" (
    echo [FAIL] 找不到 server/ 目录, 请确认在项目根目录运行此脚本
    pause
    exit /b 1
)
if not exist "web" (
    echo [FAIL] 找不到 web/ 目录, 请确认在项目根目录运行此脚本
    pause
    exit /b 1
)
if not exist "v3" (
    echo [FAIL] 找不到 v3/ 目录, V3 运行时缺失
    pause
    exit /b 1
)

:: ─── 1/6 Python ──────────────────────────────────────────
echo [1/6] 检查 Python ...
where python >nul 2>&1
if errorlevel 1 (
    echo [FAIL] 未找到 Python
    echo.
    echo   请先安装 Python 3.10+:
    echo     https://www.python.org/downloads/
    echo   安装时勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo        %%i

:: Python version >= 3.10 (rough check by parsing major.minor)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do (
    for /f "tokens=1,2 delims=." %%a in ("%%v") do (
        set PY_MAJOR=%%a
        set PY_MINOR=%%b
    )
)
if !PY_MAJOR! LSS 3 (
    echo [WARN] Python 版本过低 ^(!PY_MAJOR!.!PY_MINOR!^), 建议 3.10+
)
if !PY_MAJOR! EQU 3 if !PY_MINOR! LSS 10 (
    echo [WARN] Python 版本 3.!PY_MINOR! 可能过旧, 建议 3.10+
)

:: ─── 2/6 Node.js ──────────────────────────────────────────
echo [2/6] 检查 Node.js ...
where npm >nul 2>&1
if errorlevel 1 (
    echo [FAIL] 未找到 Node.js / npm
    echo.
    echo   请先安装 Node.js 18+:
    echo     https://nodejs.org/
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('node --version 2^>^&1') do echo        Node %%i

:: ─── 3/6 Backend deps ──────────────────────────────────
echo [3/6] 检查后端依赖 ...
cd /d "%~dp0server"

:: 检查 requirements.txt 是否存在
if not exist "requirements.txt" (
    echo [FAIL] server/requirements.txt 不存在
    pause
    exit /b 1
)

:: 用 pip show 探测关键包是否已安装
python -c "import fastapi, uvicorn" 2>nul
if errorlevel 1 (
    echo        首次运行, 安装依赖 ^(可能需要 30 秒^)...
    python -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo [WARN] pip install 出错, 尝试国内镜像 ...
        python -m pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        if errorlevel 1 (
            echo [FAIL] 后端依赖安装失败
            pause
            exit /b 1
        )
    )
    echo        [OK] 依赖已安装
) else (
    echo        [OK] 依赖已就绪
)
cd /d "%~dp0"

:: ─── 4/6 Frontend deps ─────────────────────────────────
echo [4/6] 检查前端依赖 ...
cd /d "%~dp0web"
if not exist "package.json" (
    echo [FAIL] web/package.json 不存在
    pause
    exit /b 1
)

if not exist "node_modules" (
    echo        首次运行, 安装依赖 ^(可能需要 1-2 分钟^)...
    call npm install --no-audit --no-fund
    if errorlevel 1 (
        echo [WARN] npm install 出错, 尝试淘宝镜像 ...
        call npm install --no-audit --no-fund --registry=https://registry.npmmirror.com
        if errorlevel 1 (
            echo [FAIL] 前端依赖安装失败
            pause
            exit /b 1
        )
    )
    echo        [OK] 依赖已安装
) else (
    echo        [OK] 依赖已就绪
)
cd /d "%~dp0"

:: ─── 5/6 Port check ────────────────────────────────────
echo [5/6] 检查端口占用 ...
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [WARN] 端口 8000 已被占用, 后端可能无法启动
    echo        请关闭占用程序后重试, 或在另一终端 netstat -ano 查看
    pause
)
netstat -ano | findstr ":5173" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [WARN] 端口 5173 已被占用, 前端可能无法启动
    pause
)
echo        [OK] 端口可用

:: ─── 6/6 Start servers ─────────────────────────────────
echo [6/6] 启动服务 ...
echo.
echo        启动后端 ^(端口 8000^) ...
start "Baogu-V3-Backend" cmd /k "chcp 65001 >nul && cd /d "%~dp0server" && echo. && echo === Backend === && python main.py && pause"

timeout /t 3 /nobreak >nul

echo        启动前端 ^(端口 5173^) ...
start "Baogu-V3-Frontend" cmd /k "chcp 65001 >nul && cd /d "%~dp0web" && echo. && echo === Frontend === && npm run dev && pause"

timeout /t 5 /nobreak >nul

echo        打开浏览器 ...
start http://localhost:5173

echo.
echo ================================================================
echo   启动完成!
echo.
echo   后端: http://localhost:8000  (健康检查: /api/health)
echo   前端: http://localhost:5173
echo.
echo   关闭服务: 关闭对应的 Backend / Frontend 终端窗口
echo ================================================================
echo.
echo 本窗口可以关闭, 服务继续运行.
pause
