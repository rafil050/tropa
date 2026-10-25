"""Сетевые мелочи: HTTP-запросы напрямую или через прокси, пинг, свободные порты."""

from __future__ import annotations

import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def http_get(url: str, *, timeout: float = 15, user_agent: str = "Tropa/1.0",
             proxy: str | None = None, max_bytes: int = 32 * 1024 * 1024) -> HttpResponse:
    """GET-запрос. proxy=None — строго напрямую (системный прокси Windows игнорируется),
    иначе адрес вида http://127.0.0.1:10809."""
    proxies = {"http": proxy, "https": proxy} if proxy else {}
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(proxies),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    with opener.open(request, timeout=timeout) as response:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError("ответ сервера слишком большой")
        headers = {k.lower(): v for k, v in response.headers.items()}
        return HttpResponse(response.status, headers, body)


def describe_error(exc: BaseException) -> str:
    """Понятное описание сетевой ошибки."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"сервер ответил ошибкой {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, socket.timeout) or "timed out" in str(reason):
            return "истекло время ожидания"
        if isinstance(reason, ssl.SSLError):
            return f"ошибка TLS: {reason}"
        if isinstance(reason, socket.gaierror):
            return "не удалось найти адрес сервера"
        if isinstance(reason, ConnectionRefusedError):
            return "соединение отклонено"
        return str(reason)
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "истекло время ожидания"
    return str(exc) or exc.__class__.__name__


def tcp_ping(host: str, port: int, timeout: float = 3.0) -> int:
    """Время TCP-подключения в мс или -1."""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return -1
    return max(1, round((time.perf_counter() - start) * 1000))


def url_delay(proxy_port: int, url: str, timeout: float = 8.0) -> int:
    """Реальная задержка: сколько мс занимает запрос к url через локальный HTTP-прокси, или -1."""
    start = time.perf_counter()
    try:
        response = http_get(url, timeout=timeout, proxy=f"http://127.0.0.1:{proxy_port}", max_bytes=1024 * 1024)
    except Exception:  # noqa: BLE001 — любая ошибка значит «не работает»
        return -1
    if response.status >= 500:
        return -1
    return max(1, round((time.perf_counter() - start) * 1000))


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def wait_port(port: int, timeout: float = 5.0, host: str = "127.0.0.1") -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def free_ports(count: int, start: int = 41000) -> list[int]:
    ports: list[int] = []
    port = start
    while len(ports) < count and port < 65000:
        if port_is_free(port):
            ports.append(port)
        port += 1
    if len(ports) < count:
        raise OSError("не хватает свободных портов")
    return ports
