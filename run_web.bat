@echo off
setlocal enabledelayedexpansion

title Advanced Research Studio - Web Workstation
cd /d "%~dp0"

echo ======================================================================
echo            ADVANCED AI RESEARCH STUDIO - QUICK LAUNCHER
echo ======================================================================
echo.

:: 1. Setup Virtual Environment automatically if missing
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] First-time setup: creating Python virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Python 3.10+ not found in PATH. Please install Python first.
        pause
        exit /b 1
    )
    echo [INFO] Installing dependencies from requirements.txt...
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\pip.exe install -r requirements.txt
)

:: 2. Start Server and wait until ready before auto-opening browser cleanly
echo [INFO] Booting server and opening browser once ready...
echo [INFO] Press Ctrl+C anytime to stop the studio.
echo ======================================================================
echo.
.venv\Scripts\python.exe main.py --ui --open --port 8080

pause
