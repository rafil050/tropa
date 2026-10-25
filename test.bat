@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Тесты. Если ядро уже скачано, конфиги проверяются и настоящим Xray.
call "%~dp0scripts\setup_env.cmd"
if errorlevel 1 goto :end
if "%XRAY_BIN%"=="" if exist "%LOCALAPPDATA%\Tropa\core\xray.exe" set "XRAY_BIN=%LOCALAPPDATA%\Tropa\core\xray.exe"
".venv\Scripts\python.exe" -m unittest discover -s tests -v
:end
pause
