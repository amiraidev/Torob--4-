@echo off
cd /d "%~dp0"
python scripts\setup.py
if errorlevel 1 (
  echo Setup failed. Read the error above and run setup again.
  pause
  exit /b 1
)
echo Ready. Run start.bat
pause
