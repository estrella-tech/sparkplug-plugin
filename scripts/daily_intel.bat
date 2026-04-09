@echo off
REM Atomic Fungi Daily Intel — full pipeline via Windows Task Scheduler
REM Exports Sparkplug data, analyzes, sends to Google Chat + email

set VENV_PYTHON=%USERPROFILE%\.sparkplug-venv\Scripts\python.exe
set SCRIPT=%~dp0daily_intel.py
set LOG=%USERPROFILE%\sparkplug_exports\daily_intel.log

echo [%date% %time%] Starting AF Daily Intel pipeline... >> "%LOG%" 2>&1
"%VENV_PYTHON%" "%SCRIPT%" >> "%LOG%" 2>&1
echo [%date% %time%] Done. >> "%LOG%" 2>&1
