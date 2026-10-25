@echo off
chcp 65001 >nul
rem Готовит окружение .venv с зависимостями. errorlevel 0 — всё готово.
rem Папку не меняем и выходим из подпрограмм через goto :eof — так скрипт одинаково работает везде.
set "TROPA_ROOT=%~dp0.."
set "VENV_PY=%TROPA_ROOT%\.venv\Scripts\python.exe"

if exist "%VENV_PY%" "%VENV_PY%" -c "import PySide6" >nul 2>nul
if exist "%VENV_PY%" if not errorlevel 1 exit /b 0

call :findpy
if not defined PY call :installpy
if not defined PY exit /b 1

echo.
echo Создаю окружение Python и ставлю зависимости. Это 1-2 минуты, нужен интернет...
if exist "%TROPA_ROOT%\.venv" rmdir /s /q "%TROPA_ROOT%\.venv"
%PY% -m venv "%TROPA_ROOT%\.venv"
if errorlevel 1 goto :venv_failed
"%VENV_PY%" -m pip install --upgrade pip >nul 2>nul
"%VENV_PY%" -m pip install -r "%TROPA_ROOT%\requirements.txt"
if errorlevel 1 goto :pip_failed
exit /b 0

:venv_failed
echo Не удалось создать окружение Python.
exit /b 1

:pip_failed
echo.
echo Не удалось установить зависимости. Проверьте интернет и запустите ещё раз.
exit /b 1


rem ---------------------------------------------------------------- поиск Python 3.10-3.13
rem PySide6 6.9 поддерживает Python 3.10-3.13. Сначала обычные папки установки, потом py и python из PATH.
:findpy
set "PY="
for %%V in (312 313 311 310) do if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
for %%V in (3.12 3.13 3.11 3.10) do if not defined PY if exist "%LOCALAPPDATA%\Python\pythoncore-%%V-64\python.exe" set PY="%LOCALAPPDATA%\Python\pythoncore-%%V-64\python.exe"
if defined PY goto :eof
for %%V in (3.12 3.13 3.11 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>nul
        if not errorlevel 1 set "PY=py -%%V"
    )
)
if defined PY goto :eof
python -c "import sys; raise SystemExit(not ((3, 10) <= sys.version_info[:2] < (3, 14)))" >nul 2>nul
if not errorlevel 1 set "PY=python"
goto :eof


rem ---------------------------------------------------------------- установка Python
:installpy
echo.
echo На этом компьютере не найден подходящий Python (3.10-3.13) — он нужен, чтобы запустить Tropa.
where winget >nul 2>nul
if errorlevel 1 goto :manual
echo.
echo   1 - установить Python 3.12 автоматически (через winget, права администратора не нужны)
echo   2 - отмена, установлю сам
choice /C 12 /N /M "Ваш выбор (1 или 2): "
if errorlevel 2 goto :manual
echo.
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
set "WINGET_RESULT=%errorlevel%"
call :findpy
if defined PY goto :installed
if not "%WINGET_RESULT%"=="0" (
    echo.
    echo Автоматическая установка не удалась.
    goto :manual
)
echo.
echo Python установлен, но это окно его пока не видит.
echo Закройте окно и запустите run.bat ещё раз.
goto :eof

:installed
echo.
echo Python установлен.
goto :eof

:manual
echo.
echo Установите Python 3.12 или 3.13 вручную: https://www.python.org/downloads/
echo При установке обязательно отметьте галочку "Add python.exe to PATH",
echo затем снова запустите run.bat.
goto :eof
