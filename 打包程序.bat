@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先运行「安装依赖.bat」。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name FormatConverter --collect-all imageio_ffmpeg --collect-all pillow_heif --collect-all pdf2docx --collect-all pymupdf --collect-all pikepdf --hidden-import win32com.client --hidden-import pythoncom --hidden-import pywintypes main.py
if errorlevel 1 goto failed
echo 已生成 dist\FormatConverter。分发时必须复制整个文件夹。
pause
exit /b 0
:failed
echo 打包失败，请查看上面的错误信息。
pause
exit /b 1
