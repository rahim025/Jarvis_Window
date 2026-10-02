@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0src"
if exist "..\venv\Scripts\python.exe" (
    "..\venv\Scripts\python.exe" main2.py
) else (
    python main2.py
)
pause
