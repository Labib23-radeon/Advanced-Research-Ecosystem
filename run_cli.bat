@echo off
setlocal enabledelayedexpansion

title Advanced Research Studio - Terminal REPL
cd /d "%~dp0"

echo ======================================================================
echo            ADVANCED AI RESEARCH STUDIO - TERMINAL REPL
echo ======================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Initializing .venv...
    python -m venv .venv
    .venv\Scripts\pip.exe install -r requirements.txt
)

.venv\Scripts\python.exe main.py
pause
