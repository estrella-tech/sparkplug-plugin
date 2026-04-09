@echo off
REM Sparkplug Daily Export — runs via Windows Task Scheduler
REM Exports fresh Sparkplug data and pushes to GitHub

set VENV_PYTHON=%USERPROFILE%\.sparkplug-venv\Scripts\python.exe
set SCRIPT=%~dp0export_data.py

echo [%date% %time%] Starting Sparkplug data export...
"%VENV_PYTHON%" "%SCRIPT%" --push
echo [%date% %time%] Done.
