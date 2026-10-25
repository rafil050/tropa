"""Сквозная проверка: поднимаем локальные серверы Xray разных протоколов, подключаемся
к ним конфигом, который собирает Tropa из ссылки, и качаем страницу через прокси.

Запуск:  XRAY_BIN=/путь/к/xray python -m unittest tests.test_e2e
"""

import hashlib
import http.server
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tropa.core import real_delays  # noqa: E402
from tropa.links import parse_link  # noqa: E402
from tropa.models import Settings  # noqa: E402
from tropa.netutil import http_get, port_is_free, wait_port  # noqa: E402
from tropa.xray_config import build_config  # noqa: E402

XRAY = os.environ.get("XRAY_BIN")
UUID = "a6dbbbcc-dcd6-4341-98bd-2ee419f4bf5d"
BODY = b"hello-from-target"


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args):
        pass


def _start_target() -> int:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


def _start_tls_dummy(cert: Path, key: Path) -> int:
    """Простой TLS 1.3 сервер — «маскировочный» сайт для REALITY."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)

    def serve():
        while True:
            conn, _ = sock.accept()

            def handle(c):
                try:
                    with ctx.wrap_socket(c, server_side=True) as s:
                        s.recv(1024)
                        s.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
                except (OSError, ssl.SSLError):
                    pass
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    return sock.getsockname()[1]


@unittest.skipUnless(XRAY, "XRAY_BIN не задан")
class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tropa-e2e-"))
        cls.env = dict(os.environ, XRAY_LOCATION_ASSET=str(Path(XRAY).parent))
        cls.target_port = _start_target()
        cert_json = json.loads(subprocess.check_output([XRAY, "tls", "cert", "-domain=tropa.test", "-json"]))
        cls.cert_lines, cls.key_lines = cert_json["certificate"], cert_json["key"]
        cls.cert = cls.tmp / "cert.pem"
        cls.key = cls.tmp / "key.pem"
        cls.cert.write_text("\n".join(cls.cert_lines) + "\n")
        # xray подписывает PKCS#8-ключ как «RSA PRIVATE KEY» — для Python поправим заголовок
        cls.key.write_text("\n".join(cls.key_lines).replace("RSA PRIVATE KEY", "PRIVATE KEY") + "\n")
        der = ssl.PEM_cert_to_DER_cert(cls.cert.read_text())
        cls.pcs = hashlib.sha256(der).hexdigest()
        keys = subprocess.check_output([XRAY, "x25519"], text=True)
        cls.reality_private = keys.split("PrivateKey:")[1].split()[0]
        cls.reality_public = keys.split("Password (PublicKey):")[1].split()[0]
        cls.dummy_tls_port = _start_tls_dummy(cls.cert, cls.key)
        cls.procs = []
        cls.logs = []
        cls.cases = cls._make_cases()

    @classmethod
    def tearDownClass(cls):
        for proc in cls.procs:
            proc.kill()
            proc.wait()
        for log in cls.logs:
            log.close()

    @classmethod
    def _run(cls, config: dict, name: str) -> subprocess.Popen:
        path = cls.tmp / f"{name}.json"
        path.write_text(json.dumps(config))
        log = open(cls.tmp / f"{name}.log", "w")
        cls.logs.append(log)
        proc = subprocess.Popen([XRAY, "run", "-c", str(path)], stdout=log, stderr=subprocess.STDOUT, env=cls.env)
        cls.procs.append(proc)
        return proc

    @classmethod
    def _tls(cls) -> dict:
        return {"certificates": [{"certificate": cls.cert_lines, "key": cls.key_lines}]}

    @classmethod
    def _make_cases(cls):
        """(имя, inbound сервера без порта, функция порт → ссылка)."""
        pcs = cls.pcs
        tls = cls._tls()
        # REALITY маскируется под настоящий сайт. В CI есть интернет — там берём реальный сайт
        # (TROPA_REALITY_TARGET=www.microsoft.com:443), иначе локальный TLS-сервер на Python.
        reality_target = os.environ.get("TROPA_REALITY_TARGET") or f"127.0.0.1:{cls.dummy_tls_port}"
        reality_sni = reality_target.rsplit(":", 1)[0] if os.environ.get("TROPA_REALITY_TARGET") else "tropa.test"
        return [
            ("vless_tcp", {"protocol": "vless", "settings": {"clients": [{"id": UUID}], "decryption": "none"}},
             lambda p: f"vless://{UUID}@127.0.0.1:{p}?type=tcp&security=none#t"),
            ("vless_ws_tls", {"protocol": "vless", "settings": {"clients": [{"id": UUID}], "decryption": "none"},
                              "streamSettings": {"network": "ws", "wsSettings": {"path": "/ws"}, "security": "tls", "tlsSettings": tls}},
             lambda p: f"vless://{UUID}@127.0.0.1:{p}?type=ws&path=%2Fws&security=tls&sni=tropa.test&pcs={pcs}#t"),
            ("vless_grpc_tls", {"protocol": "vless", "settings": {"clients": [{"id": UUID}], "decryption": "none"},
                                "streamSettings": {"network": "grpc", "grpcSettings": {"serviceName": "svc"}, "security": "tls", "tlsSettings": tls}},
             lambda p: f"vless://{UUID}@127.0.0.1:{p}?type=grpc&serviceName=svc&security=tls&sni=tropa.test&pcs={pcs}#t"),
            ("vless_xhttp_tls", {"protocol": "vless", "settings": {"clients": [{"id": UUID}], "decryption": "none"},
                                 "streamSettings": {"network": "xhttp", "xhttpSettings": {"path": "/xh"}, "security": "tls", "tlsSettings": tls}},
             lambda p: f"vless://{UUID}@127.0.0.1:{p}?type=xhttp&path=%2Fxh&mode=auto&security=tls&sni=tropa.test&alpn=h2&pcs={pcs}#t"),
            ("vless_reality_vision", {"protocol": "vless", "settings": {"clients": [{"id": UUID, "flow": "xtls-rprx-vision"}], "decryption": "none"},
                                      "streamSettings": {"network": "tcp", "security": "reality", "realitySettings": {
                                          "target": reality_target, "serverNames": [reality_sni],
                                          "privateKey": cls.reality_private, "shortIds": ["ab12"]}}},
             lambda p: f"vless://{UUID}@127.0.0.1:{p}?type=tcp&security=reality&flow=xtls-rprx-vision&sni={reality_sni}"
                       f"&pbk={cls.reality_public}&sid=ab12&fp=chrome#t"),
            ("vmess_tcp", {"protocol": "vmess", "settings": {"clients": [{"id": UUID}]}},
             lambda p: f"vmess://{UUID}@127.0.0.1:{p}?type=tcp&encryption=auto#t"),
            ("trojan_tls", {"protocol": "trojan", "settings": {"clients": [{"password": "secret"}]},
                            "streamSettings": {"network": "tcp", "security": "tls", "tlsSettings": tls}},
             lambda p: f"trojan://secret@127.0.0.1:{p}?sni=tropa.test&pcs={pcs}#t"),
            ("ss_2022", {"protocol": "shadowsocks", "settings": {"method": "2022-blake3-aes-128-gcm",
                                                                  "password": "WJpaXfQnjpu7OjqjHzrKJA==", "network": "tcp,udp"}},
             lambda p: f"ss://2022-blake3-aes-128-gcm:{quote('WJpaXfQnjpu7OjqjHzrKJA==', safe='')}@127.0.0.1:{p}#t"),
            ("ss_aes", {"protocol": "shadowsocks", "settings": {"method": "aes-256-gcm", "password": "pw", "network": "tcp,udp"}},
             lambda p: "ss://YWVzLTI1Ni1nY206cHc@127.0.0.1:%d#t" % p),
            ("socks_auth", {"protocol": "socks", "settings": {"auth": "password", "accounts": [{"user": "u", "pass": "p"}]}},
             lambda p: f"socks5://u:p@127.0.0.1:{p}#t"),
            ("hysteria2", {"protocol": "hysteria", "settings": {"version": 2, "clients": [{"auth": "hyauth"}]},
                           "streamSettings": {"network": "hysteria", "hysteriaSettings": {"version": 2},
                                              "security": "tls", "tlsSettings": {**tls, "alpn": ["h3"]},
                                              "finalmask": {"udp": [{"type": "salamander", "settings": {"password": "obfspass"}}]}}},
             lambda p: f"hysteria2://hyauth@127.0.0.1:{p}?sni=tropa.test&alpn=h3&pcs={pcs}&obfs=salamander&obfs-password=obfspass#t"),
        ]

    _next = 43000
    _taken: set = set()

    @classmethod
    def _port(cls) -> int:
        """Порты выдаём по порядку: серверы стартуют асинхронно, и случайный выбор мог дать
        двум процессам один порт ещё до того, как первый успел его занять."""
        while True:
            cls._next += 1
            if cls._next not in cls._taken and port_is_free(cls._next):
                cls._taken.add(cls._next)
                return cls._next

    def _server(self, name: str, inbound: dict) -> int:
        port = self._port()
        config = {"log": {"loglevel": "info"}, "inbounds": [{"port": port, "listen": "127.0.0.1", **inbound}],
                  # Xray по умолчанию запрещает серверам VLESS/VMess/Trojan/SS/Hysteria ходить на локальные
                  # адреса (защита от доступа к внутренней сети). Тестовая «цель» живёт на 127.0.0.1 — разрешаем.
                  "outbounds": [{"protocol": "freedom",
                                 "settings": {"finalRules": [{"action": "allow", "ip": ["127.0.0.0/8"]}]}}]}
        self._run(config, f"server-{name}")
        if inbound["protocol"] != "hysteria":
            self.assertTrue(wait_port(port, 8), f"сервер {name} не запустился")
        else:
            time.sleep(1.0)
        return port

    @classmethod
    def _log_tail(cls, name: str, limit: int = 6) -> str:
        """Строки логов Xray, похожие на причину сбоя, — чтобы она была видна прямо в отчёте."""
        try:
            lines = (cls.tmp / f"{name}.log").read_text(errors="replace").splitlines()
        except OSError:
            return "(лога нет)"
        keys = ("fail", "error", "reject", "reality", "hysteria", "quic", "tls", "invalid", "timeout")
        picked = [line[-220:] for line in lines if any(k in line.lower() for k in keys)]
        return "\n".join((picked or lines)[-limit:]) or "(лог пуст)"

    def test_connect_every_protocol(self):
        for name, inbound, link_for in self.cases:
            with self.subTest(protocol=name):
                server_port = self._server(name, inbound)
                profile = parse_link(link_for(server_port))
                socks_port, http_port = self._port(), self._port()
                settings = Settings(socks_port=socks_port, http_port=http_port, routing_mode="global", dns="",
                                    log_level="info")
                config, warnings = build_config(profile, settings, bypass_private=False)
                self.assertEqual(warnings, [])
                self._run(config, f"client-{name}")
                self.assertTrue(wait_port(http_port, 8), f"клиент {name} не запустился")
                # до трёх попыток: на Windows в CI локальные соединения изредка обрываются на закрытии
                problem = ""
                for _attempt in range(3):
                    try:
                        response = http_get(f"http://127.0.0.1:{self.target_port}/", timeout=15,
                                            proxy=f"http://127.0.0.1:{http_port}")
                    except Exception as exc:  # noqa: BLE001
                        problem = str(exc)
                    else:
                        if response.body == BODY:
                            problem = ""
                            break
                        problem = f"неожиданный ответ: {response.body[:60]!r}"
                    time.sleep(1)
                if problem:
                    self.fail(f"{problem}\n--- сервер:\n{self._log_tail('server-' + name)}"
                              f"\n--- клиент:\n{self._log_tail('client-' + name)}")

    def test_real_delay_batch(self):
        profiles = []
        names = {}
        for name, inbound, link_for in self.cases:
            server_port = self._server(name + "-rd", inbound)
            profile = parse_link(link_for(server_port))
            names[profile.id] = name
            profiles.append(profile)
        results = {}
        real_delays(profiles, f"http://127.0.0.1:{self.target_port}/",
                    lambda pid, ms, err: results.__setitem__(pid, (ms, err)), binary=Path(XRAY))
        for profile in profiles:
            with self.subTest(protocol=names[profile.id]):
                ms, err = results[profile.id]
                self.assertGreater(ms, 0, err)


if __name__ == "__main__":
    unittest.main()
