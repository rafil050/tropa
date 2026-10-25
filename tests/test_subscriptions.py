"""Загрузка подписки с локального HTTP-сервера: base64-список, заголовки трафика и названия."""

import base64
import http.server
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samples import JSON_SUB, SAMPLES  # noqa: E402

from tropa.models import Profile, Subscription  # noqa: E402
from tropa.storage import Store  # noqa: E402
from tropa.subscriptions import SubscriptionError, apply_result, fetch, human_bytes  # noqa: E402

PAYLOADS = {
    "/b64": base64.b64encode("\n".join(SAMPLES.values()).encode()).decode(),
    "/json": JSON_SUB,
    "/html": "<!DOCTYPE html><html><body>Подписка</body></html>",
}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = PAYLOADS.get(self.path, "").encode()
        self.send_response(200 if body else 404)
        self.send_header("profile-title", "base64:" + base64.b64encode("Мой VPN".encode()).decode())
        self.send_header("subscription-userinfo", "upload=1073741824; download=2147483648; total=107374182400; expire=1798675200")
        self.send_header("profile-update-interval", "12")
        self.send_header("x-ua", self.headers.get("User-Agent", ""))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class SubscriptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{server.server_address[1]}"

    def test_base64_subscription_with_headers(self):
        result = fetch(self.base + "/b64", user_agent="Tropa/1.0", timeout=5, proxy=None)
        self.assertEqual(len(result.profiles), len(SAMPLES))
        self.assertEqual(result.title, "Мой VPN")
        self.assertEqual(result.total, 107374182400)
        self.assertEqual(result.update_interval_h, 12)
        sub = Subscription(url=self.base + "/b64")
        apply_result(sub, result)
        self.assertEqual(sub.name, "Мой VPN")
        self.assertEqual(human_bytes(sub.upload + sub.download), "3,0 ГБ")

    def test_json_subscription(self):
        result = fetch(self.base + "/json", user_agent="Tropa/1.0", timeout=5, proxy=None)
        self.assertEqual([p.protocol for p in result.profiles], ["json"])

    def test_html_page_is_explained(self):
        with self.assertRaises(SubscriptionError):
            fetch(self.base + "/html", user_agent="Mozilla/5.0", timeout=5, proxy=None)

    def test_store_keeps_ids_on_update(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            sub = Subscription(url="http://x")
            store.subscriptions.append(sub)
            first = fetch(self.base + "/b64", user_agent="t", timeout=5, proxy=None).profiles
            store.replace_subscription_profiles(sub.id, first)
            store.selected_id = store.profiles[3].id
            store.add_profiles([Profile(protocol="socks", address="1.1.1.1", port=1080, name="manual")])
            second = fetch(self.base + "/b64", user_agent="t", timeout=5, proxy=None).profiles
            store.replace_subscription_profiles(sub.id, second[:5])
            self.assertEqual(len(store.profiles), 6)
            self.assertIsNotNone(store.selected())
            store.save()
            again = Store(Path(tmp) / "state.json")
            self.assertEqual(len(again.profiles), 6)
            self.assertEqual(again.selected_id, store.selected_id)
            again.remove_subscription(sub.id)
            self.assertEqual([p.name for p in again.profiles], ["manual"])


if __name__ == "__main__":
    unittest.main()
