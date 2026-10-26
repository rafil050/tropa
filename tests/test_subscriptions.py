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

from tropa.links import parse_link, parse_many  # noqa: E402
from tropa.models import Profile, Subscription  # noqa: E402
from tropa.storage import Store  # noqa: E402
from tropa.subscriptions import SubscriptionError, apply_result, fetch, human_bytes, update_due  # noqa: E402

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

    def test_selected_server_survives_provider_rename(self):
        """Панели вроде 3x-ui пишут в название остаток трафика и дни — после обновления подписки
        выбранный сервер должен остаться выбранным (а с ним id и задержка), а не смениться на первый."""
        import json
        import tempfile
        trojan = SAMPLES["trojan"].partition("#")[0]
        vmess = json.loads(base64.b64decode(SAMPLES["vmess_ws"][len("vmess://"):]))
        config = json.loads(JSON_SUB)
        config = config[0] if isinstance(config, list) else config

        def batch(gb: int) -> list[Profile]:
            vmess["ps"] = f"VMess {gb}GB"  # у vmess название внутри base64
            config["remarks"] = f"JSON {gb}GB"
            vm_link = "vmess://" + base64.b64encode(json.dumps(vmess).encode()).decode()
            return [parse_link(f"{trojan}#Trojan {gb}GB"), parse_link(vm_link), parse_many(json.dumps(config))[0][0]]

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            sub = Subscription(url="http://x")
            store.subscriptions.append(sub)
            store.replace_subscription_profiles(sub.id, batch(10))
            for index in range(len(store.profiles)):
                profile = store.profiles[index]  # после обновления в списке уже новые объекты
                with self.subTest(server=profile.name):
                    store.selected_id, profile.ping = profile.id, 40 + index
                    store.replace_subscription_profiles(sub.id, batch(9 - index))
                    chosen = store.selected()
                    self.assertIsNotNone(chosen)
                    self.assertEqual(store.profiles.index(chosen), index)
                    self.assertTrue(chosen.name.endswith(f"{9 - index}GB"), chosen.name)
                    self.assertEqual(chosen.ping, 40 + index)

    def test_same_server_twice_under_new_names_gets_two_ids(self):
        import tempfile
        link = SAMPLES["trojan"].partition("#")[0]
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            sub = Subscription(url="http://x")
            store.replace_subscription_profiles(sub.id, [parse_link(link + "#A")])
            old_id = store.profiles[0].id
            store.replace_subscription_profiles(sub.id, [parse_link(link + "#B"), parse_link(link + "#C")])
            ids = [p.id for p in store.profiles]
            self.assertEqual(len(set(ids)), 2)
            self.assertEqual(ids[0], old_id)

    def test_import_selects_added_not_duplicate(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            old = Profile(protocol="socks", address="1.1.1.1", port=1080, name="old")
            store.add_profiles([old])
            store.selected_id = ""
            twin = Profile(protocol="socks", address="1.1.1.1", port=1080, name="twin")
            fresh = Profile(protocol="socks", address="2.2.2.2", port=1080, name="fresh")
            self.assertEqual(store.add_profiles([twin, fresh]), 1)
            self.assertEqual(store.selected().name, "fresh")


class AutoUpdateTests(unittest.TestCase):
    HOUR = 3600

    def test_provider_interval(self):
        sub = Subscription(url="http://x", updated_at=0, update_interval_h=12)
        now = 100 * self.HOUR
        sub.updated_at = now - 11 * self.HOUR
        self.assertFalse(update_due(sub, now))
        sub.updated_at = now - 12 * self.HOUR
        self.assertTrue(update_due(sub, now))

    def test_default_once_a_day(self):
        sub = Subscription(url="http://x", update_interval_h=0)
        now = 100 * self.HOUR
        sub.updated_at = now - 23 * self.HOUR
        self.assertFalse(update_due(sub, now))
        sub.updated_at = now - 25 * self.HOUR
        self.assertTrue(update_due(sub, now))
        sub.updated_at = 0  # ещё ни разу не обновлялась
        self.assertTrue(update_due(sub, now))

    def test_upgrade_respects_updates_switched_off(self):
        """В state.json от 1.1.x нет sub_auto_update: кто выключил «Обновлять при запуске»,
        не должен после обновления программы получить обновления в фоне."""
        import json
        import tempfile
        cases = (({"sub_update_on_start": False}, False), ({"sub_update_on_start": True}, True), ({}, True),
                 ({"sub_update_on_start": False, "sub_auto_update": True}, True))
        for saved, expected in cases:
            with self.subTest(saved=saved), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "state.json"
                path.write_text(json.dumps({"version": 1, "settings": saved}), "utf-8")
                self.assertEqual(Store(path).settings.sub_auto_update, expected)

    def test_failed_attempt_retried_hourly(self):
        now = 100 * self.HOUR
        sub = Subscription(url="http://x", updated_at=now - 48 * self.HOUR)
        self.assertFalse(update_due(sub, now, last_attempt=now - 10 * 60))
        self.assertTrue(update_due(sub, now, last_attempt=now - self.HOUR))


if __name__ == "__main__":
    unittest.main()
