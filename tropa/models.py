"""Данные приложения: серверы, подписки, настройки."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import Any

PROTOCOL_TITLES = {
    "vless": "VLESS",
    "vmess": "VMess",
    "trojan": "Trojan",
    "shadowsocks": "Shadowsocks",
    "socks": "SOCKS",
    "hysteria2": "Hysteria2",
    "json": "JSON",
}

# Пинг: None — ещё не проверяли, -1 — тайм-аут/ошибка
PING_FAILED = -1


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _from_dict(cls, data: dict[str, Any]):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class Profile:
    """Один сервер (одна ссылка)."""

    protocol: str
    address: str = ""
    port: int = 0
    name: str = ""
    id: str = field(default_factory=new_id)
    sub_id: str = ""  # пустая строка — добавлен вручную

    # учётные данные
    uuid: str = ""  # vless / vmess
    password: str = ""  # trojan / shadowsocks / socks / hysteria2
    username: str = ""  # socks
    method: str = ""  # shadowsocks
    flow: str = ""  # vless
    encryption: str = "none"  # vless
    alter_id: int = 0  # vmess
    cipher: str = "auto"  # vmess

    # транспорт
    network: str = "tcp"  # tcp, ws, grpc, xhttp, httpupgrade, kcp, hysteria
    header_type: str = ""  # tcp http / kcp header
    host: str = ""
    path: str = ""
    service_name: str = ""  # grpc
    grpc_mode: str = ""  # gun / multi
    authority: str = ""  # grpc
    xhttp_mode: str = ""
    xhttp_extra: str = ""  # JSON-строка
    kcp_seed: str = ""

    # безопасность
    security: str = "none"  # none, tls, reality
    sni: str = ""
    fingerprint: str = ""
    alpn: str = ""  # через запятую
    public_key: str = ""  # reality pbk
    short_id: str = ""
    spider_x: str = ""
    mldsa65_verify: str = ""
    pinned_sha256: str = ""  # pcs
    verify_names: str = ""  # vcn
    ech_config: str = ""
    insecure: bool = False  # в ссылке был allowInsecure — Xray его больше не поддерживает

    # hysteria2
    obfs: str = ""
    obfs_password: str = ""
    hop_ports: str = ""

    # полный JSON-конфиг (подписки в формате Xray JSON)
    raw_config: str = ""

    raw_link: str = ""
    ping: int | None = None

    def title(self) -> str:
        return self.name or f"{self.address}:{self.port}"

    def protocol_title(self) -> str:
        return PROTOCOL_TITLES.get(self.protocol, self.protocol.upper())

    def summary(self) -> str:
        """Короткое описание для списка: «Reality · tcp · host:port»."""
        parts: list[str] = []
        if self.protocol == "json":
            parts.append("Xray JSON")
        else:
            if self.security == "reality":
                parts.append("Reality")
            elif self.security == "tls":
                parts.append("TLS")
            if self.protocol != "hysteria2":
                parts.append(self.network)
            elif self.obfs:
                parts.append(self.obfs)
        if self.address:
            host = f"[{self.address}]" if ":" in self.address else self.address
            parts.append(f"{host}:{self.port}")
        return " · ".join(parts)

    def key(self) -> str:
        """Чем профиль отличается от других — чтобы не плодить дубли при обновлении подписки."""
        return self.raw_link or self.raw_config or f"{self.protocol}|{self.address}|{self.port}|{self.uuid}{self.password}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        return _from_dict(cls, data)


@dataclass
class Subscription:
    url: str
    name: str = ""
    id: str = field(default_factory=new_id)
    updated_at: float = 0.0
    upload: int = 0
    download: int = 0
    total: int = 0
    expire: int = 0  # unix-время окончания, 0 — бессрочно
    update_interval_h: int = 0
    support_url: str = ""
    announce: str = ""
    last_error: str = ""

    def title(self) -> str:
        return self.name or self.url

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Subscription":
        return _from_dict(cls, data)


ROUTING_MODES = {
    "global": "Всё через прокси",
    "bypass_ru": "Кроме российских сайтов",
    "whitelist": "Только мой список",
}


@dataclass
class Settings:
    socks_port: int = 10808
    http_port: int = 10809
    allow_lan: bool = False
    system_proxy: bool = True
    routing_mode: str = "bypass_ru"
    block_ads: bool = False
    direct_list: str = ""
    proxy_list: str = "geosite:youtube\ngeosite:instagram\ngeosite:facebook\ngeosite:twitter\ngeosite:discord\ngeosite:openai"
    dns: str = "localhost"
    sub_update_on_start: bool = True
    sub_user_agent: str = "Tropa/1.0"
    sub_timeout: int = 15
    sub_via_proxy: bool = False
    tray_on_close: bool = True
    connect_on_start: bool = False
    autostart: bool = False
    log_level: str = "warning"
    test_url: str = "https://www.gstatic.com/generate_204"
    tray_hint_shown: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        return _from_dict(cls, data)


def now() -> float:
    return time.time()
