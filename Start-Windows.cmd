@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo 请安装 Python 3.11 或更新版本，并将其加入 PATH。https://www.python.org/downloads/
  echo 按任意键关闭窗口。
  pause >nul
  exit /b 1
)
python launch.py
if errorlevel 1 (
  echo 按任意键关闭窗口。
  pause >nul
)
