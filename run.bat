@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment was not found.
    echo Run setup.bat first, then run this file again.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m src.main
if errorlevel 1 (
    echo.
    echo Application exited with an error. Check logs\app.log.
    pause
)
