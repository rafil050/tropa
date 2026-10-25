@echo off
chcp 65001 >nul
cd /d "%~dp0.."
rem Полная сборка установщика: Tropa.exe (PyInstaller) + ядро Xray + Tropa-Setup.exe (NSIS).
rem Нужны Python 3.10+ и NSIS 3 (https://nsis.sourceforge.io/Download).

call "%~dp0..\scripts\setup_env.cmd"
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto :fail

".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --name Tropa ^
    --icon "tropa\assets\icon.ico" ^
    --add-data "tropa\assets;tropa\assets" ^
    --version-file "packaging\version_info.txt" ^
    --exclude-module tkinter --exclude-module unittest --exclude-module pydoc ^
    main.py
if errorlevel 1 goto :fail

".venv\Scripts\python.exe" packaging\fetch_core.py dist\Tropa\core
if errorlevel 1 goto :fail

set "MAKENSIS="
where makensis >nul 2>nul && set "MAKENSIS=makensis"
if not defined MAKENSIS if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" set MAKENSIS="%ProgramFiles(x86)%\NSIS\makensis.exe"
if not defined MAKENSIS if exist "%ProgramFiles%\NSIS\makensis.exe" set MAKENSIS="%ProgramFiles%\NSIS\makensis.exe"
if not defined MAKENSIS (
    echo.
    echo Tropa.exe собран в dist\Tropa, но NSIS не найден — установщик не создан.
    echo Установите NSIS: https://nsis.sourceforge.io/Download и запустите скрипт снова.
    goto :fail
)
for /f %%v in ('".venv\Scripts\python.exe" -c "from tropa import APP_VERSION; print(APP_VERSION)"') do set "TROPA_VERSION=%%v"
%MAKENSIS% /DAPP_VERSION=%TROPA_VERSION% packaging\installer.nsi
if errorlevel 1 goto :fail

echo.
echo Готово: dist\Tropa-Setup-%TROPA_VERSION%.exe
pause
exit /b 0

:fail
echo.
pause
exit /b 1
