@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "FormatConverter\FormatConverter.exe" (
  start "" "FormatConverter\FormatConverter.exe"
  exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "main.py"
  exit /b
)
echo 请先运行「安装依赖.bat」，或解压便携版后启动程序。
pause
