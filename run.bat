@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Запуск Tropa из исходников. При первом запуске ставится Python-окружение с PySide6.
call "%~dp0scripts\setup_env.cmd"
if errorlevel 1 goto :fail
start "" ".venv\Scripts\pythonw.exe" main.py
exit /b 0

:fail
echo.
pause
exit /b 1
