"""Где приложение хранит свои данные и ядро."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME

IS_WINDOWS = sys.platform == "win32"


def app_dir() -> Path:
    """Папка, где лежит само приложение (exe или исходники)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Путь к файлам из tropa/assets — работает и из исходников, и из сборки PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath("tropa", "assets", *parts)


def data_dir() -> Path:
    """Папка с настройками, серверами и логами пользователя."""
    override = os.environ.get("TROPA_DATA")
    if override:
        path = Path(override)
    elif IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        path = Path(base) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def core_dir() -> Path:
    path = data_dir() / "core"
    path.mkdir(parents=True, exist_ok=True)
    return path


def xray_name() -> str:
    return "xray.exe" if IS_WINDOWS else "xray"
