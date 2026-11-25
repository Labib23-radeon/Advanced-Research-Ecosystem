@echo off
setlocal enabledelayedexpansion

title Advanced Research Studio - Wi-Fi LAN Mode (Phones, Tablets, PCs)
cd /d "%~dp0"

echo ======================================================================
echo       ADVANCED RESEARCH STUDIO - NETWORK / MULTI-DEVICE MODE
echo ======================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating virtual environment and installing dependencies...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\pip.exe install -r requirements.txt
)

echo [INFO] Binding to all network interfaces (0.0.0.0)...
echo [INFO] Open the Network URL printed below on your phone or laptop!
echo ======================================================================
echo.
.venv\Scripts\python.exe main.py --ui --lan --open --port 8080

pause
