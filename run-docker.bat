@echo off
cd /d "%~dp0"
docker compose up --build -d
if errorlevel 1 (
  echo Docker failed. Start Docker Desktop and check the error above.
  pause
  exit /b 1
)
echo Ready after the container health check: http://localhost:8000
echo Logs: docker compose logs -f web
pause

