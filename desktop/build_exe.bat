@echo off
cd /d "%~dp0"
py -3 -m pip install pyinstaller
py -3 -m PyInstaller --noconfirm --onefile --name Wire --add-data "desk.html;." wire_bridge.py
echo.
echo Built dist\Wire.exe
echo Start the bot with: dist\Wire.exe --run C:\path\to\ABinanceTradingBot.py
