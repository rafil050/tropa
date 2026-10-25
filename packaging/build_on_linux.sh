#!/usr/bin/env bash
# Сборка Windows-установщика на Linux через Wine — так собран выложенный Tropa-Setup.exe.
# Нужны: wine64, makensis (пакет nsis), Windows-сборка CPython 3.12 (python-build-standalone,
# распакованная в $WINPY) и колёса для win_amd64 в $WHEELS
# (PySide6-Essentials==6.9.3, shiboken6==6.9.3, pyinstaller и его зависимости, включая pefile и pywin32-ctypes).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${WINPY:?укажите WINPY — папку с python.exe для Windows}"
: "${WHEELS:?укажите WHEELS — папку с колёсами win_amd64}"
export WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
VERSION="$(python3 -c "import re;print(re.search(r'APP_VERSION = \"(.+?)\"', open('$ROOT/tropa/__init__.py').read()).group(1))")"
BUILD="$(mktemp -d)"
cp -r "$ROOT/main.py" "$ROOT/tropa" "$ROOT/packaging" "$BUILD/"
find "$BUILD" -name __pycache__ -prune -exec rm -rf {} +

wine "$WINPY/python.exe" -m pip install --no-index --find-links "$WHEELS" \
    "PySide6-Essentials==6.9.3" "shiboken6==6.9.3" pyinstaller < /dev/null 2>&1 | cat
cd "$BUILD"
wine "$WINPY/python.exe" -m PyInstaller --noconfirm --clean --windowed --name Tropa \
    --icon 'tropa\assets\icon.ico' --add-data 'tropa\assets;tropa\assets' \
    --version-file 'packaging\version_info.txt' \
    --exclude-module tkinter --exclude-module unittest --exclude-module pydoc \
    main.py < /dev/null 2>&1 | cat
python3 "$ROOT/packaging/fetch_core.py" "$BUILD/dist/Tropa/core" "${XRAY_VERSION:-}"
mkdir -p "$ROOT/dist"
makensis -V2 -DAPP_VERSION="$VERSION" -DSRC_DIR="$BUILD/dist/Tropa" -DOUT_FILE="$ROOT/dist/Tropa-Setup-$VERSION.exe" "$ROOT/packaging/installer.nsi"
echo "Готово: $ROOT/dist/Tropa-Setup-$VERSION.exe"
