; Установщик Tropa (NSIS 3).
; Собирается командой:  makensis packaging\installer.nsi
; Ожидает готовую сборку PyInstaller в dist\Tropa (Tropa.exe, _internal, core).
; Ставит в профиль пользователя — права администратора не нужны.

Unicode true
Target amd64-unicode  ; программа 64-битная, установщик тоже
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!define APP_NAME     "Tropa"
!ifndef APP_VERSION
  !define APP_VERSION "1.1.0"  ; передаётся скриптами сборки из tropa/__init__.py
!endif
!define APP_EXE      "Tropa.exe"
!define APP_URL      "https://github.com/rafil050/tropa"
!define APP_ID       "Tropa.ProxyClient"
!define UNINST_KEY   "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
!define INET_KEY     "Software\Microsoft\Windows\CurrentVersion\Internet Settings"

!ifndef SRC_DIR
  !define SRC_DIR "..\dist\Tropa"
!endif
!ifndef OUT_FILE
  !define OUT_FILE "..\dist\Tropa-Setup-${APP_VERSION}.exe"
!endif

Name "${APP_NAME}"
OutFile "${OUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "${APP_NAME} ${APP_VERSION}"
ShowInstDetails nevershow
ShowUninstDetails nevershow

VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=1049 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=1049 "FileDescription" "Установка ${APP_NAME}"
VIAddVersionKey /LANG=1049 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1049 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1049 "CompanyName" "${APP_NAME}"
VIAddVersionKey /LANG=1049 "LegalCopyright" "${APP_NAME}"

!define MUI_ICON   "..\tropa\assets\icon.ico"
!define MUI_UNICON "..\tropa\assets\icon.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Установка ${APP_NAME} ${APP_VERSION}"
!define MUI_WELCOMEPAGE_TEXT "${APP_NAME} — клиент для ваших прокси-серверов (VLESS, VMess, Trojan, Shadowsocks, Hysteria2) на открытом ядре Xray.$\r$\n$\r$\nПрограмма ставится только для текущего пользователя, права администратора не нужны.$\r$\n$\r$\nНажмите «Далее», чтобы продолжить."
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Запустить ${APP_NAME}"
!define MUI_COMPONENTSPAGE_NODESC

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Russian"


; Проверка «файл занят»: запущенный exe нельзя открыть на запись. Путь в $R7, результат в $R9 (1 — занят).
!macro IS_LOCKED UN
Function ${UN}IsLocked
  StrCpy $R9 0
  IfFileExists "$R7" 0 free
  ClearErrors
  FileOpen $R8 "$R7" a
  IfErrors locked
  FileClose $R8
  Goto free
  locked:
    StrCpy $R9 1
  free:
FunctionEnd
!macroend
!insertmacro IS_LOCKED ""
!insertmacro IS_LOCKED "un."

; Аккуратно закрывает запущенную Tropa: сначала просим её выйти самой (она выключит
; системный прокси и остановит ядро), если не вышла — завершаем принудительно.
; Пока программа работает, файлы не трогаем: иначе установка получится наполовину старой.
!macro CLOSE_RUNNING UN
Function ${UN}CloseRunning
  start:
  StrCpy $R7 "$INSTDIR\${APP_EXE}"
  Call ${UN}IsLocked
  StrCmp $R9 1 0 core_check
  DetailPrint "Закрываю запущенную ${APP_NAME}..."
  ExecWait '"$INSTDIR\${APP_EXE}" --quit'
  StrCpy $1 0
  wait:
    Sleep 500
    Call ${UN}IsLocked
    StrCmp $R9 1 0 core_check
    IntOp $1 $1 + 1
    IntCmp $1 16 0 wait 0
  nsExec::Exec 'taskkill /F /IM ${APP_EXE}'
  Pop $0
  Sleep 1000
  ; принудительно закрытая программа не успела вернуть системный прокси — вернём сами
  ReadRegStr $2 HKCU "${INET_KEY}" "ProxyServer"
  StrCmp $2 "127.0.0.1:10809" 0 proxy_ok
    WriteRegDWORD HKCU "${INET_KEY}" "ProxyEnable" 0
    System::Call 'wininet::InternetSetOptionW(p 0, i 39, p 0, i 0)'
    System::Call 'wininet::InternetSetOptionW(p 0, i 37, p 0, i 0)'
  proxy_ok:
  Call ${UN}IsLocked
  StrCmp $R9 1 0 core_check
  MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Не удаётся закрыть ${APP_NAME}.$\r$\nЗакройте её вручную (значок в трее → «Выход») и нажмите «Повтор»." /SD IDCANCEL IDRETRY start
  Abort

  core_check:
  ; ядро завершается вместе с программой — дадим ему пару секунд
  StrCpy $R7 "$INSTDIR\core\xray.exe"
  StrCpy $1 0
  core_wait:
    Call ${UN}IsLocked
    StrCmp $R9 1 0 done
    Sleep 500
    IntOp $1 $1 + 1
    IntCmp $1 10 0 core_wait 0
  MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Файл ядра xray.exe занят другой программой.$\r$\nЗакройте её и нажмите «Повтор»." /SD IDCANCEL IDRETRY start
  Abort
  done:
FunctionEnd
!macroend
!insertmacro CLOSE_RUNNING ""
!insertmacro CLOSE_RUNNING "un."


Section "${APP_NAME}" SecMain
  SectionIn RO
  Call CloseRunning
  SetOutPath "$INSTDIR"
  ; при обновлении убираем старые файлы программы (настройки лежат отдельно и не трогаются)
  RMDir /r "$INSTDIR\_internal"
  File "${SRC_DIR}\${APP_EXE}"
  File /r "${SRC_DIR}\_internal"
  SetOutPath "$INSTDIR\core"
  File "${SRC_DIR}\core\xray.exe"
  File "${SRC_DIR}\core\geoip.dat"
  File "${SRC_DIR}\core\geosite.dat"
  File "${SRC_DIR}\core\LICENSE-Xray.txt"
  SetOutPath "$INSTDIR"
  File "..\THIRD_PARTY_NOTICES.md"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateShortCut "$SMPROGRAMS\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0

  WriteRegStr HKCU "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "URLInfoAbout" "${APP_URL}"
  WriteRegStr HKCU "${UNINST_KEY}" "HelpLink" "${APP_URL}/issues"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Section "Ярлык на рабочем столе" SecDesktop
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
SectionEnd


Section "Uninstall"
  Call un.CloseRunning
  Delete "$SMPROGRAMS\${APP_NAME}.lnk"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${APP_NAME}"

  ; удаляем только свои файлы и папки — никаких рекурсивных удалений папки установки
  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\core\xray.exe"
  Delete "$INSTDIR\core\geoip.dat"
  Delete "$INSTDIR\core\geosite.dat"
  Delete "$INSTDIR\core\LICENSE-Xray.txt"
  RMDir "$INSTDIR\core"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"

  MessageBox MB_YESNO|MB_ICONQUESTION "Удалить также настройки, список серверов и скачанное ядро?$\r$\n(папка $LOCALAPPDATA\${APP_NAME})" /SD IDNO IDNO keep_data
    RMDir /r "$LOCALAPPDATA\${APP_NAME}"
  keep_data:

  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\${APP_NAME}"
SectionEnd
