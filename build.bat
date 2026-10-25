@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Сборка Tropa.exe (папка dist\Tropa), которая потом работает без Python.
call "%~dp0scripts\setup_env.cmd"
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

echo.
echo Готово: dist\Tropa\Tropa.exe
echo Ядро Xray приложение скачает само при первом подключении.
echo Чтобы собрать версию без интернета, положите xray.exe, geoip.dat и geosite.dat в dist\Tropa\core
pause
exit /b 0

:fail
echo.
echo Сборка не удалась — смотрите сообщения выше.
pause
exit /b 1
