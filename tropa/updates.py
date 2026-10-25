"""Проверка новых версий Tropa и ссылки для обратной связи на GitHub."""

from __future__ import annotations

import platform
import re
import ssl
import urllib.request
from urllib.parse import urlencode

from . import APP_VERSION, REPO_URL


def parse_version(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in match.groups()) if match else (0, 0, 0)


def is_newer(candidate: str, current: str = APP_VERSION) -> bool:
    return parse_version(candidate) > parse_version(current)


def latest_release(proxy: str | None = None, timeout: float = 15) -> str | None:
    """Номер последнего релиза на GitHub или None, если релизов ещё нет.
    Без API: смотрим, куда GitHub перенаправляет /releases/latest — так нет лимита запросов."""
    proxies = {"http": proxy, "https": proxy} if proxy else {}
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(proxies),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    request = urllib.request.Request(f"{REPO_URL}/releases/latest", headers={"User-Agent": "Tropa"}, method="HEAD")
    with opener.open(request, timeout=timeout) as response:
        final = response.geturl()
    match = re.search(r"/releases/tag/v?(\d+\.\d+\.\d+)", final)
    return match.group(1) if match else None


def release_page(version: str | None = None) -> str:
    return f"{REPO_URL}/releases/tag/v{version}" if version else f"{REPO_URL}/releases/latest"


def _system() -> str:
    if platform.system() == "Windows":
        release, build = platform.release(), platform.version()
        return f"Windows {release} ({build})"
    return f"{platform.system()} {platform.release()}"


def idea_url() -> str:
    """Форма «Предложить улучшение» с уже подставленной версией."""
    return f"{REPO_URL}/issues/new?" + urlencode({"template": "idea.yml", "version": APP_VERSION})


def bug_url(core_version: str | None = None) -> str:
    """Форма «Сообщить об ошибке» с версией программы, ядра и Windows (без личных данных)."""
    fields = {"template": "bug.yml", "version": APP_VERSION, "os": _system()}
    if core_version:
        fields["core"] = core_version
    return f"{REPO_URL}/issues/new?" + urlencode(fields)
