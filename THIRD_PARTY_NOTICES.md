# Сторонние компоненты

## Xray-core

- Проект: https://github.com/XTLS/Xray-core
- Лицензия: Mozilla Public License 2.0 (https://www.mozilla.org/MPL/2.0/)
- Как используется: Tropa не содержит код Xray. Готовый исполняемый файл `xray.exe` и базы
  `geoip.dat` / `geosite.dat` скачиваются с официальной страницы релизов проекта и запускаются
  как отдельная программа. Исходный код Xray доступен по ссылке выше.
- Если вы распространяете Tropa вместе с `xray.exe` (папка `core`), приложите текст лицензии MPL-2.0
  и ссылку на исходный код Xray-core — файл `LICENSE` есть в архиве релиза Xray.

## Базы geoip / geosite

- Проект: https://github.com/XTLS/Xray-rules-dat (данные v2fly/domain-list-community и IPinfo Lite)
- Поставляются вместе с архивом Xray-core.

## Qt for Python (PySide6)

- Проект: https://www.qt.io/qt-for-python
- Лицензия: GNU LGPL v3 (https://www.gnu.org/licenses/lgpl-3.0.html)
- Сборка через `build.bat` создаёт папку с отдельными библиотеками Qt (режим PyInstaller onedir),
  поэтому пользователь может заменить их — это соответствует требованиям LGPL.

## Python и его библиотеки (входят в Tropa.exe)

- CPython 3.12 — Python Software Foundation License (https://docs.python.org/3/license.html).
  Сборка Python для Windows — python-build-standalone (https://github.com/astral-sh/python-build-standalone).
- OpenSSL (libssl, libcrypto) — Apache License 2.0; libffi — MIT; среда выполнения Microsoft Visual C++ —
  распространяется по условиям Microsoft для redistributable-библиотек.
- PyInstaller (загрузчик Tropa.exe) — GPL 2.0 с исключением, разрешающим распространение собранных программ.
