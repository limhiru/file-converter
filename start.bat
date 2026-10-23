@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 goto :failed
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failed
.venv\Scripts\python.exe run.py
if errorlevel 1 goto :failed
exit /b 0
:failed
echo.
echo Setup failed. Install Python 3.11 or later and try again.
pause
exit /b 1
