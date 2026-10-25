"""Запуск приложения: одна копия, тема, главное окно."""

from __future__ import annotations

import getpass
import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import APP_ID, APP_NAME, winutil
from .paths import data_dir, resource_path
from .storage import Store
from .ui import theme
from .ui.main_window import MainWindow


def _instance_name() -> str:
    return f"{APP_NAME}-{getpass.getuser()}".replace(" ", "_")


def _notify_running_instance(command: bytes = b"show") -> bool:
    """Если Tropa уже запущена — передаём ей команду (показать окно или выйти)."""
    socket = QLocalSocket()
    socket.connectToServer(_instance_name())
    if socket.waitForConnected(300):
        socket.write(command)
        socket.flush()
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return True
    return False


def run() -> int:
    minimized = "--minimized" in sys.argv
    winutil.set_app_user_model_id(APP_ID)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(str(resource_path("icon.svg"))))

    if "--quit" in sys.argv:
        # используется установщиком: аккуратно закрыть запущенную Tropa (с выключением системного прокси)
        _notify_running_instance(b"quit")
        return 0
    if _notify_running_instance():
        return 0
    server = QLocalServer()
    QLocalServer.removeServer(_instance_name())
    server.listen(_instance_name())

    font = QFont()
    font.setFamilies(theme.FONT_FAMILIES)
    font.setPointSizeF(10)
    app.setFont(font)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet(theme.chevron_file(data_dir() / "chevron.svg")))

    store = Store()
    window = MainWindow(store)

    def on_connection():
        conn = server.nextPendingConnection()
        command = b"show"
        if conn is not None:
            if conn.waitForReadyRead(500):
                command = bytes(conn.readAll()).strip() or b"show"
            conn.disconnectFromServer()
        if command == b"quit":
            window.quit_app()
        else:
            window.show_window()

    server.newConnection.connect(on_connection)
    app.aboutToQuit.connect(lambda: window.ctrl.stop(quiet=True))

    if minimized and window.tray is not None:
        pass  # стартуем в трее
    else:
        window.show()

    shot = os.environ.get("TROPA_SCREENSHOT")
    if shot:  # диагностика: снимок окна и выход (используется при проверке сборки)
        delay = int(os.environ.get("TROPA_SCREENSHOT_DELAY", "5000"))
        QTimer.singleShot(delay, lambda: (window.grab().save(shot), window.quit_app()))

    code = app.exec()
    print("Tropa: работа завершена", file=sys.stderr, flush=True)
    return code
