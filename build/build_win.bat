@echo off
REM 在 Windows 上打包 QuickTranslate 单文件 EXE
REM 前置：已安装 Python + PyInstaller（py -m pip install pyinstaller）
cd /d "%~dp0\.."
py -m PyInstaller QuickTranslate.spec --noconfirm --clean
echo.
echo 打包完成，产物位于 dist\QuickTranslate.exe
pause
