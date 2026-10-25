"""Загрузка подписок: список серверов + служебные заголовки (трафик, срок, название)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

from .links import parse_many, try_b64decode
from .models import Profile, Subscription
from .netutil import http_get


class SubscriptionError(Exception):
    pass


@dataclass
class SubscriptionResult:
    profiles: list[Profile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    title: str = ""
    upload: int = 0
    download: int = 0
    total: int = 0
    expire: int = 0
    update_interval_h: int = 0
    support_url: str = ""
    announce: str = ""


def _decode_header(value: str) -> str:
    value = value.strip()
    if value.lower().startswith("base64:"):
        decoded = try_b64decode(value[7:])
        return (decoded or "").strip()
    return unquote(value)


def parse_userinfo(value: str) -> dict[str, int]:
    """'upload=1; download=2; total=3; expire=4' → словарь чисел."""
    result: dict[str, int] = {}
    for key, number in re.findall(r"(upload|download|total|expire)\s*=\s*(\d+)", value or "", re.I):
        result[key.lower()] = int(number)
    return result


def fetch(url: str, *, user_agent: str, timeout: float, proxy: str | None) -> SubscriptionResult:
    if not re.match(r"(?i)^https?://", url.strip()):
        raise SubscriptionError("ссылка подписки должна начинаться с http:// или https://")
    response = http_get(url.strip(), timeout=timeout, user_agent=user_agent, proxy=proxy)
    text = response.body.decode("utf-8", errors="replace")
    if "<html" in text[:500].lower():
        raise SubscriptionError(
            "вместо списка серверов пришла веб-страница. Попробуйте сменить User-Agent подписки в настройках"
        )

    result = SubscriptionResult()
    result.profiles, result.errors = parse_many(text)
    if not result.profiles and not result.errors:
        raise SubscriptionError("в подписке не найдено ни одного сервера")

    h = response.headers
    result.title = _decode_header(h.get("profile-title", ""))
    info = parse_userinfo(h.get("subscription-userinfo", ""))
    result.upload = info.get("upload", 0)
    result.download = info.get("download", 0)
    result.total = info.get("total", 0)
    result.expire = info.get("expire", 0)
    try:
        result.update_interval_h = int(float(h.get("profile-update-interval", "0") or 0))
    except ValueError:
        result.update_interval_h = 0
    result.support_url = h.get("support-url", "").strip()
    result.announce = _decode_header(h.get("announce", ""))
    return result


def apply_result(sub: Subscription, result: SubscriptionResult) -> None:
    """Переносит служебную информацию в подписку."""
    if result.title and not sub.name:
        sub.name = result.title
    if not sub.name:
        sub.name = urlsplit(sub.url).hostname or "Подписка"
    sub.upload, sub.download, sub.total, sub.expire = result.upload, result.download, result.total, result.expire
    sub.update_interval_h = result.update_interval_h
    sub.support_url = result.support_url
    sub.announce = result.announce
    sub.updated_at = time.time()
    sub.last_error = ""


def human_bytes(value: int) -> str:
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit in ("Б", "КБ") else f"{size:.1f} {unit}".replace(".", ",")
        size /= 1024
    return f"{value} Б"
