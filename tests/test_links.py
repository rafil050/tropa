"""Проверка разбора ссылок и сборки конфигов.

Запуск:  python -m unittest discover -s tests
Если задана переменная XRAY_BIN (путь к xray), конфиги дополнительно проверяются
настоящим ядром командой `xray run -test`.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samples import BAD, JSON_SUB, PBK, PLAINTEXT, SAMPLES, SS22_KEY, UUID  # noqa: E402

from tropa.core import _accepted, real_delays  # noqa: E402
from tropa.links import LinkError, parse_link, parse_many, share_link, share_links  # noqa: E402
from tropa.models import PING_FAILED, Profile  # noqa: E402
from tropa.models import Settings  # noqa: E402
from tropa.xray_config import ConfigError, build_config, build_test_config, parse_rule_list  # noqa: E402

XRAY = os.environ.get("XRAY_BIN")


def xray_test(config: dict) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(config, fh)
        path = fh.name
    try:
        env = dict(os.environ, XRAY_LOCATION_ASSET=str(Path(XRAY).parent))
        proc = subprocess.run([XRAY, "run", "-test", "-c", path], capture_output=True, text=True, timeout=30, env=env)
        return proc.returncode == 0, proc.stdout + proc.stderr
    finally:
        os.unlink(path)


class ParseTests(unittest.TestCase):
    def test_vless_reality(self):
        p = parse_link(SAMPLES["vless_reality"])
        self.assertEqual(p.protocol, "vless")
        self.assertEqual(p.address, "nl.example.com")
        self.assertEqual(p.port, 443)
        self.assertEqual(p.uuid, UUID)
        self.assertEqual(p.flow, "xtls-rprx-vision")
        self.assertEqual(p.security, "reality")
        self.assertEqual(p.public_key, PBK)
        self.assertEqual(p.short_id, "6ba85179e30d4fc2")
        self.assertEqual(p.name, "🇳🇱 Нидерланды")

    def test_ws_tls(self):
        p = parse_link(SAMPLES["vless_ws_tls"])
        self.assertEqual((p.network, p.security, p.host, p.path), ("ws", "tls", "cdn.example.com", "/ws?ed=2048"))
        self.assertTrue(p.insecure)

    def test_vmess(self):
        p = parse_link(SAMPLES["vmess_ws"])
        self.assertEqual((p.protocol, p.network, p.security, p.path, p.fingerprint), ("vmess", "ws", "tls", "/vmws", "firefox"))
        self.assertEqual(p.name, "VMess WS")
        p = parse_link(SAMPLES["vmess_tcp_http"])
        self.assertEqual((p.network, p.header_type, p.port), ("tcp", "http", 8080))

    def test_shadowsocks_variants(self):
        p = parse_link(SAMPLES["ss_sip002"])
        self.assertEqual((p.method, p.password, p.address, p.port), ("aes-256-gcm", "pass", "5.6.7.8", 8388))
        p = parse_link(SAMPLES["ss_2022"])
        self.assertEqual(p.method, "2022-blake3-aes-128-gcm")
        self.assertEqual(p.password, "WJpaXfQnjpu7OjqjHzrKJA==")
        p = parse_link(SAMPLES["ss_legacy"])
        self.assertEqual((p.method, p.password, p.address), ("chacha20-ietf-poly1305", "pw", "9.9.9.9"))

    def test_socks(self):
        p = parse_link(SAMPLES["socks"])
        self.assertEqual((p.username, p.password), ("user", "pass"))
        p = parse_link(SAMPLES["socks5_plain"])
        self.assertEqual((p.address, p.username, p.password), ("::1", "bob", "secret"))

    def test_trojan(self):
        p = parse_link(SAMPLES["trojan"])
        self.assertEqual((p.password, p.security), ("p@ss", "tls"))

    def test_hysteria2(self):
        p = parse_link(SAMPLES["hy2"])
        self.assertEqual((p.protocol, p.password, p.obfs, p.obfs_password), ("hysteria2", "myauth", "salamander", "obfspw"))
        p = parse_link(SAMPLES["hy2_hop"])
        self.assertEqual((p.port, p.hop_ports, p.password), (443, "443,20000-30000", "user:pass"))

    def test_kcp_ipv6(self):
        p = parse_link(SAMPLES["vless_kcp"])
        self.assertEqual((p.address, p.network, p.kcp_seed), ("fd00::1", "kcp", "s33d"))

    def test_short_salamander_password_rejected(self):
        p = parse_link("hysteria2://auth@hy.example.com:443?sni=hy.example.com&obfs=salamander&obfs-password=ab#t")
        with self.assertRaises(ConfigError):
            build_config(p, Settings())

    def test_plaintext_rejected_with_clear_error(self):
        for name, link in PLAINTEXT.items():
            with self.subTest(name=name):
                with self.assertRaises(ConfigError):
                    build_config(parse_link(link), Settings())
        items = [(parse_link(link), 31000 + i) for i, link in enumerate(PLAINTEXT.values())]
        _, failed = build_test_config(items)
        self.assertEqual(len(failed), 2)

    def test_ss2022_keys(self):
        def password(method: str, key: str) -> str:
            p = Profile(protocol="shadowsocks", address="ss.example.com", port=443, method=method, password=key)
            return build_config(p, Settings())[0]["outbounds"][0]["settings"]["servers"][0]["password"]

        method = "2022-blake3-aes-128-gcm"
        self.assertEqual(password(method, SS22_KEY), SS22_KEY)
        # без «=» и в url-safe виде ядро ключ не принимает — приводим к стандартному base64
        self.assertEqual(password(method, SS22_KEY.rstrip("=")), SS22_KEY)
        self.assertEqual(password(method, f"{SS22_KEY.rstrip('=')}:{SS22_KEY}"), f"{SS22_KEY}:{SS22_KEY}")
        self.assertEqual(password("aes-256-gcm", "просто пароль"), "просто пароль")
        for bad_method, bad_key in ((method, "hunter2"), ("2022-blake3-aes-256-gcm", SS22_KEY),
                                    (method, SS22_KEY + ":abc")):
            with self.subTest(key=bad_key):
                with self.assertRaisesRegex(ConfigError, "Shadowsocks 2022"):
                    password(bad_method, bad_key)

    def test_json_server_copied_as_config(self):
        profile = parse_many(JSON_SUB)[0][0]
        again, _ = parse_many(share_link(profile))
        self.assertEqual(again[0].key(), profile.key())
        second = parse_many(JSON_SUB)[0][0]
        both, _ = parse_many(share_links([profile, second]))
        self.assertEqual(len(both), 2)
        plain = [parse_link(link) for link in list(SAMPLES.values())[:2]]
        self.assertEqual(share_links(plain), "\n".join(p.raw_link for p in plain))

    def test_rejected_server_search(self):
        """Сломанный сервер в пачке не должен помечать нерабочими остальные (логика без ядра)."""
        items = [(Profile(protocol="socks", name=n), 40000 + i) for i, n in enumerate("abcdefgh")]
        broken_tagged, broken_silent = {"c"}, {"f", "h"}

        def check(subset):
            names = [p.name for p, _ in subset]
            for index, name in enumerate(names):
                if name in broken_tagged:
                    return False, f"failed to build outbound config with tag p{index} > invalid"
            if broken_silent & set(names):
                return False, "main: failed to create server > bad key"
            return True, "Configuration OK."

        results = {}
        accepted = _accepted(items, check, lambda pid, ms, err: results.__setitem__(pid, (ms, err)), None)
        names = {p.id: p.name for p, _ in items}
        self.assertEqual([p.name for p, _ in accepted], ["a", "b", "d", "e", "g"])
        self.assertEqual(sorted(names[pid] for pid in results), ["c", "f", "h"])
        self.assertTrue(all(ms == PING_FAILED for ms, _ in results.values()))
        self.assertIn("bad key", results[items[5][0].id][1])

    def test_bad_links(self):
        for name, link in BAD.items():
            with self.subTest(name=name):
                with self.assertRaises(LinkError):
                    parse_link(link)

    def test_parse_many_base64_and_errors(self):
        import base64
        blob = "\n".join(list(SAMPLES.values()) + [BAD["h2"]])
        profiles, errors = parse_many(base64.b64encode(blob.encode()).decode())
        self.assertEqual(len(profiles), len(SAMPLES))
        self.assertEqual(len(errors), 1)

    def test_parse_many_json(self):
        profiles, errors = parse_many(JSON_SUB)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0].protocol, "json")
        self.assertEqual(profiles[0].address, "de.example.com")

    def test_rule_list(self):
        domains, ips = parse_rule_list("youtube.com\n*.example.org\nhttps://site.ru/page\ngeosite:Google\n10.0.0.0/8\ngeoip:ru\n# comment")
        self.assertEqual(domains, ["domain:youtube.com", "domain:example.org", "domain:site.ru", "geosite:google"])
        self.assertEqual(ips, ["10.0.0.0/8", "geoip:ru"])


@unittest.skipUnless(XRAY, "XRAY_BIN не задан — проверка ядром пропущена")
class XrayValidationTests(unittest.TestCase):
    def test_all_samples_valid(self):
        for mode in ("global", "bypass_ru", "whitelist"):
            settings = Settings(routing_mode=mode, block_ads=True, direct_list="vk.com\n192.168.0.0/16")
            for name, link in SAMPLES.items():
                with self.subTest(name=name, mode=mode):
                    config, _ = build_config(parse_link(link), settings)
                    ok, out = xray_test(config)
                    self.assertTrue(ok, out)

    def test_json_profile_valid(self):
        profile = parse_many(JSON_SUB)[0][0]
        config, _ = build_config(profile, Settings())
        tags = [ob["tag"] for ob in config["outbounds"]]
        self.assertEqual(tags[0], "proxy")
        self.assertIn("sub-aux1", tags)
        self.assertEqual(config["outbounds"][0]["streamSettings"]["sockopt"]["dialerProxy"], "sub-aux1")
        ok, out = xray_test(config)
        self.assertTrue(ok, out)

    def test_real_delay_marks_only_broken_servers(self):
        """Сервер, который Tropa не может собрать, и сервер, который отклоняет ядро, —
        в одной пачке с рабочими: «нерабочими» должны стать только они двое."""
        good = [parse_link(SAMPLES["vless_reality"]), parse_link(SAMPLES["trojan"])]
        unbuildable = parse_link(list(PLAINTEXT.values())[0])
        rejected = parse_link(f"vless://{UUID}@x.example.com:443?security=reality&pbk=abc&sni=x.com#bad-pbk")
        profiles = [unbuildable, good[0], rejected, good[1]]
        results = {}
        real_delays(profiles, "http://127.0.0.1:9/", lambda pid, ms, err: results.__setitem__(pid, (ms, err)),
                    binary=Path(XRAY))
        self.assertIn("VLESS", results[unbuildable.id][1])
        self.assertIn("abc", results[rejected.id][1])
        for p in good:  # до них дошла очередь: просто не ответил несуществующий адрес
            self.assertEqual(results[p.id], (PING_FAILED, "нет ответа"))

    def test_batch_test_config_valid(self):
        items = [(parse_link(link), 30000 + i) for i, link in enumerate(SAMPLES.values())]
        items.append((parse_many(JSON_SUB)[0][0], 30100))
        config, failed = build_test_config(items)
        self.assertEqual(failed, {})
        ok, out = xray_test(config)
        self.assertTrue(ok, out)


if __name__ == "__main__":
    unittest.main()
