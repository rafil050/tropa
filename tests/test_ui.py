"""Главное окно без экрана (Qt offscreen): фоновые дела не должны мешать пользователю.

Запуск:  python -m unittest tests.test_ui
"""

import base64
import http.server
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TROPA_DATA", tempfile.mkdtemp(prefix="tropa-ui-test-"))

from samples import SAMPLES  # noqa: E402

try:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication, QDialog, QMenu
except ImportError:  # интерфейс не установлен — проверяем только логику
    QApplication = None

BODY = base64.b64encode("\n".join(list(SAMPLES.values())[:2]).encode())


class _Subscription(http.server.BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self):  # noqa: N802
        type(self).hits += 1
        self.send_response(200)
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args):
        pass


@unittest.skipIf(QApplication is None, "PySide6 не установлен")
class BackgroundUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Subscription)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        from tropa.models import Subscription
        from tropa.storage import Store
        from tropa.ui.main_window import MainWindow

        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "state.json")
        s = self.store.settings
        s.sub_update_on_start = s.check_updates = s.system_proxy = False
        url = f"http://127.0.0.1:{self.server.server_address[1]}/sub"
        self.store.subscriptions.append(Subscription(url=url, name="Тест"))  # ни разу не обновлялась
        _Subscription.hits = 0
        self.window = MainWindow(self.store)
        self.pump(0.2)

    def tearDown(self):
        self.window.housekeeping_timer.stop()
        self.window.save_timer.stop()
        self.window.deleteLater()
        self.pump(0.1)
        self.tmp.cleanup()

    def pump(self, seconds: float, until=None) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if until is not None and until():
                return
            time.sleep(0.02)

    def tick_and_wait(self, seconds: float = 3) -> None:
        self.window._housekeeping()
        self.pump(seconds, until=lambda: bool(self.store.profiles))

    def tick_expecting_nothing(self) -> None:
        self.tick_and_wait(1)  # локальный сервер отвечает за миллисекунды — секунды хватает с запасом
        self.assertEqual(_Subscription.hits, 0)

    def test_idle_window_updates_subscription(self):
        self.tick_and_wait()
        self.assertEqual(_Subscription.hits, 1)
        self.assertEqual(len(self.store.profiles), 2)

    def test_postponed_while_latency_check_runs(self):
        # обновление посреди проверки подменило бы серверы, и итог «Отвечают X из N» был бы неверным
        self.window.ping_cancel = threading.Event()
        self.tick_expecting_nothing()
        self.window.ping_cancel = None
        self.tick_and_wait()
        self.assertEqual(_Subscription.hits, 1)

    def test_postponed_while_menu_is_open(self):
        # меню сервера держит строку списка: после обновления «Подключиться» попало бы в другой сервер
        menu = QMenu(self.window)
        menu.addAction("Подключиться")
        menu.popup(QPoint(10, 10))
        self.pump(0.2, until=lambda: QApplication.activePopupWidget() is menu)
        self.assertIs(QApplication.activePopupWidget(), menu)
        self.tick_expecting_nothing()
        menu.close()
        self.pump(0.1)
        self.tick_and_wait()
        self.assertEqual(_Subscription.hits, 1)

    def test_postponed_while_dialog_is_open(self):
        dialog = QDialog(self.window)
        dialog.setModal(True)
        dialog.show()
        self.pump(0.2, until=lambda: QApplication.activeModalWidget() is dialog)
        self.assertIs(QApplication.activeModalWidget(), dialog)
        self.tick_expecting_nothing()
        dialog.close()
        self.pump(0.1)
        self.tick_and_wait()
        self.assertEqual(_Subscription.hits, 1)


if __name__ == "__main__":
    unittest.main()
