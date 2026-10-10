@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo 未找到 Python。请安装 Python 3.12 或 3.13，并勾选 Add Python to PATH。
    pause
    exit /b 1
  )
  python -m venv .venv
) else (
  py -3 -m venv .venv
)
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo 安装完成。现在可以双击「启动程序.bat」。
pause
exit /b 0
:failed
echo 安装失败，请检查 Python 版本和网络连接。建议使用 Python 3.12。
pause
exit /b 1
