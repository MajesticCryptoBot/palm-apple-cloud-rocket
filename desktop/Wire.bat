@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0wire_bridge.py" --desktop %*
) else (
  python "%~dp0wire_bridge.py" --desktop %*
)
