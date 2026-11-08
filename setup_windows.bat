@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install -r requirements-wechat.txt
if errorlevel 1 goto failed
echo Setup complete. Double-click start_browser.bat to launch.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.11 64-bit and check network access.
pause
exit /b 1
