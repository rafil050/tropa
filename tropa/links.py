"""Разбор ссылок vless:// vmess:// trojan:// ss:// socks:// hysteria2:// в профили."""

from __future__ import annotations

import base64
import binascii
import json
import re
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .models import Profile


class LinkError(ValueError):
    """Ссылку не удалось разобрать или такой вариант не поддерживается."""


SCHEMES = ("vless", "vmess", "trojan", "ss", "socks", "socks5", "socks4", "hysteria2", "hy2")

SS_METHODS = {
    "aes-128-gcm", "aes-256-gcm", "chacha20-poly1305", "chacha20-ietf-poly1305",
    "xchacha20-poly1305", "xchacha20-ietf-poly1305", "2022-blake3-aes-128-gcm",
    "2022-blake3-aes-256-gcm", "2022-blake3-chacha20-poly1305", "none", "plain",
}

NETWORK_ALIASES = {
    "raw": "tcp", "tcp": "tcp", "": "tcp",
    "ws": "ws", "websocket": "ws",
    "grpc": "grpc", "gun": "grpc",
    "xhttp": "xhttp", "splithttp": "xhttp",
    "httpupgrade": "httpupgrade",
    "kcp": "kcp", "mkcp": "kcp",
}

REMOVED_NETWORKS = {
    "h2": "HTTP/2", "http": "HTTP/2", "h3": "HTTP/3", "quic": "QUIC",
}


# ---------------------------------------------------------------- base64

def b64decode_text(data: str) -> str:
    """Декодирует base64 (обычный и url-safe, с паддингом и без). Бросает ValueError."""
    cleaned = re.sub(r"\s+", "", data)
    if not cleaned:
        raise ValueError("empty")
    cleaned = cleaned.replace("-", "+").replace("_", "/")
    cleaned += "=" * (-len(cleaned) % 4)
    try:
        raw = base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    return raw.decode("utf-8")


def try_b64decode(data: str) -> str | None:
    try:
        return b64decode_text(data)
    except (ValueError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------- helpers

def _first(params: dict[str, list[str]], *names: str, default: str = "") -> str:
    for name in names:
        values = params.get(name)
        if values and values[0] != "":
            return values[0]
    return default


def _flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _port(value: str | int | None) -> int:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        raise LinkError(f"неверный порт: {value!r}") from None
    if not 0 < port < 65536:
        raise LinkError(f"неверный порт: {port}")
    return port


def _split_host_port(hostport: str) -> tuple[str, str]:
    """'host:port', '[::1]:443', 'host:443,2000-3000' → (host, port-строка)."""
    hostport = hostport.strip().rstrip("/")
    if hostport.startswith("["):
        end = hostport.find("]")
        if end < 0:
            raise LinkError("неверный IPv6-адрес")
        host = hostport[1:end]
        rest = hostport[end + 1:]
        if not rest.startswith(":"):
            raise LinkError("не указан порт")
        return host, rest[1:]
    if hostport.count(":") != 1:
        raise LinkError("не указан порт")
    host, port = hostport.split(":", 1)
    return host, port


def _apply_stream_params(p: Profile, params: dict[str, list[str]], default_security: str = "none") -> None:
    """Общие параметры транспорта и шифрования из query-строки (формат Xray/v2rayN)."""
    raw_network = _first(params, "type", "network", default="tcp").lower()
    if raw_network in REMOVED_NETWORKS:
        raise LinkError(
            f"транспорт {REMOVED_NETWORKS[raw_network]} убран из ядра Xray — попросите у провайдера ссылку с XHTTP"
        )
    network = NETWORK_ALIASES.get(raw_network)
    if network is None:
        raise LinkError(f"неизвестный транспорт: {raw_network}")
    p.network = network

    p.header_type = _first(params, "headerType").lower()
    if p.header_type == "none":
        p.header_type = ""
    p.host = _first(params, "host")
    p.path = _first(params, "path")
    p.service_name = _first(params, "serviceName", "servicename")
    if network == "grpc" and not p.service_name:
        p.service_name = p.path
    mode = _first(params, "mode")
    if network == "grpc":
        p.grpc_mode = mode
    elif network == "xhttp":
        p.xhttp_mode = mode
    p.authority = _first(params, "authority")
    p.xhttp_extra = _first(params, "extra")
    p.kcp_seed = _first(params, "seed")
    if network == "kcp" and not p.kcp_seed and p.path:
        p.kcp_seed = p.path

    p.security = _first(params, "security", default=default_security).lower()
    if p.security in ("", "0", "false"):
        p.security = "none"
    if p.security not in ("none", "tls", "reality"):
        raise LinkError(f"неизвестный режим защиты: {p.security}")
    p.sni = _first(params, "sni", "serverName", "peer")
    p.fingerprint = _first(params, "fp", "fingerprint").lower()
    p.alpn = _first(params, "alpn")
    p.public_key = _first(params, "pbk", "publicKey", "password")
    p.short_id = _first(params, "sid", "shortId")
    p.spider_x = _first(params, "spx", "spiderX")
    p.mldsa65_verify = _first(params, "pqv")
    p.pinned_sha256 = _first(params, "pcs", "pinSHA256", "pinnedPeerCertSha256")
    p.verify_names = _first(params, "vcn", "verifyPeerCertByName")
    p.ech_config = _first(params, "ech", "echConfigList")
    p.insecure = _flag(_first(params, "allowInsecure", "insecure", "allow_insecure", default="0"))
    if p.security == "reality" and not p.public_key:
        raise LinkError("в ссылке REALITY нет публичного ключа (pbk)")


def _split_url(link: str):
    try:
        parts = urlsplit(link)
    except ValueError as exc:
        raise LinkError(f"не удалось разобрать ссылку: {exc}") from None
    params = parse_qs(parts.query, keep_blank_values=True)
    name = unquote(parts.fragment).strip()
    return parts, params, name


def _host_port_from_parts(parts) -> tuple[str, int]:
    netloc = parts.netloc.rsplit("@", 1)[-1]
    host, port = _split_host_port(netloc)
    if not host:
        raise LinkError("не указан адрес сервера")
    return host, _port(port)


# ---------------------------------------------------------------- протоколы

def parse_vless(link: str) -> Profile:
    parts, params, name = _split_url(link)
    host, port = _host_port_from_parts(parts)
    user = unquote(parts.netloc.rsplit("@", 1)[0]) if "@" in parts.netloc else ""
    if not user:
        raise LinkError("в ссылке нет UUID")
    p = Profile(protocol="vless", address=host, port=port, name=name, uuid=user, raw_link=link)
    p.encryption = _first(params, "encryption", default="none")
    p.flow = _first(params, "flow")
    _apply_stream_params(p, params)
    return p


def parse_trojan(link: str) -> Profile:
    parts, params, name = _split_url(link)
    host, port = _host_port_from_parts(parts)
    password = unquote(parts.netloc.rsplit("@", 1)[0]) if "@" in parts.netloc else ""
    if not password:
        raise LinkError("в ссылке нет пароля")
    p = Profile(protocol="trojan", address=host, port=port, name=name, password=password, raw_link=link)
    p.flow = _first(params, "flow")
    _apply_stream_params(p, params, default_security="tls")
    return p


def parse_vmess(link: str) -> Profile:
    body = link[len("vmess://"):]
    payload, _, frag = body.partition("#")
    decoded = try_b64decode(payload)
    if decoded is None:
        # формат вида vmess://uuid@host:port?...
        parts, params, name = _split_url(link)
        host, port = _host_port_from_parts(parts)
        user = unquote(parts.netloc.rsplit("@", 1)[0]) if "@" in parts.netloc else ""
        if not user:
            raise LinkError("в ссылке нет UUID")
        p = Profile(protocol="vmess", address=host, port=port, name=name, uuid=user, raw_link=link)
        p.cipher = _first(params, "encryption", "scy", default="auto")
        _apply_stream_params(p, params)
        return p

    try:
        data = json.loads(decoded)
    except json.JSONDecodeError:
        raise LinkError("ссылка vmess повреждена") from None
    if not isinstance(data, dict):
        raise LinkError("ссылка vmess повреждена")

    def g(key: str, default: str = "") -> str:
        value = data.get(key, default)
        return "" if value is None else str(value).strip()

    address = g("add")
    if not address:
        raise LinkError("не указан адрес сервера")
    if not g("id"):
        raise LinkError("в ссылке нет UUID")
    p = Profile(
        protocol="vmess",
        address=address,
        port=_port(g("port")),
        name=g("ps") or unquote(frag),
        uuid=g("id"),
        raw_link=link,
    )
    try:
        p.alter_id = int(g("aid", "0") or 0)
    except ValueError:
        p.alter_id = 0
    p.cipher = g("scy") or "auto"

    params = {
        "type": [g("net") or "tcp"],
        "host": [g("host")],
        "path": [g("path")],
        "security": [g("tls") or "none"],
        "sni": [g("sni")],
        "alpn": [g("alpn")],
        "fp": [g("fp")],
        "pbk": [g("pbk")],
        "sid": [g("sid")],
        "spx": [g("spx")],
        "allowInsecure": [g("allowInsecure") or g("insecure")],
    }
    net = (g("net") or "tcp").lower()
    header = g("type").lower()
    if net in ("tcp", "raw", "kcp", "mkcp"):
        params["headerType"] = [header]
    elif net == "grpc":
        params["mode"] = [header if header in ("gun", "multi") else ""]
        params["serviceName"] = [g("path")]
    elif net in ("xhttp", "splithttp"):
        params["mode"] = [header if header in ("auto", "packet-up", "stream-up", "stream-one") else ""]
    _apply_stream_params(p, params)
    return p


def parse_shadowsocks(link: str) -> Profile:
    rest = link[len("ss://"):]
    body, _, frag = rest.partition("#")
    name = unquote(frag).strip()
    query = ""
    if "?" in body:
        body, _, query = body.partition("?")
    body = body.rstrip("/")

    if "@" in body:
        userinfo, hostport = body.rsplit("@", 1)
        decoded = try_b64decode(unquote(userinfo))
        if decoded is not None and ":" in decoded:
            userinfo = decoded
        else:
            userinfo = unquote(userinfo)
    else:
        decoded = try_b64decode(body)
        if decoded is None or "@" not in decoded:
            raise LinkError("ссылка ss повреждена")
        userinfo, hostport = decoded.rsplit("@", 1)

    if ":" not in userinfo:
        raise LinkError("в ссылке ss нет метода шифрования или пароля")
    method, password = userinfo.split(":", 1)
    method = method.strip().lower()
    if method not in SS_METHODS:
        raise LinkError(f"шифр {method} не поддерживается ядром Xray")
    host, port = _split_host_port(hostport)

    params = parse_qs(query, keep_blank_values=True)
    plugin = _first(params, "plugin")
    if plugin:
        raise LinkError("плагины Shadowsocks (obfs, v2ray-plugin) ядро Xray не поддерживает")

    return Profile(
        protocol="shadowsocks", address=host, port=_port(port), name=name,
        method=method, password=password, raw_link=link,
    )


def parse_socks(link: str) -> Profile:
    parts, params, name = _split_url(link)
    host, port = _host_port_from_parts(parts)
    username = password = ""
    if "@" in parts.netloc:
        userinfo = unquote(parts.netloc.rsplit("@", 1)[0])
        decoded = try_b64decode(userinfo)
        if decoded is not None and ":" in decoded:
            userinfo = decoded
        if ":" in userinfo:
            username, password = userinfo.split(":", 1)
        else:
            username = userinfo
    return Profile(
        protocol="socks", address=host, port=port, name=name,
        username=username, password=password, raw_link=link,
    )


def parse_hysteria2(link: str) -> Profile:
    scheme, _, rest = link.partition("://")
    body, _, frag = rest.partition("#")
    name = unquote(frag).strip()
    query = ""
    if "?" in body:
        body, _, query = body.partition("?")
    auth = ""
    if "@" in body:
        auth, body = body.rsplit("@", 1)
        auth = unquote(auth)
    body = body.split("/", 1)[0]
    host, port_spec = _split_host_port(body)
    params = parse_qs(query, keep_blank_values=True)

    first_port = re.split(r"[,\-]", port_spec, maxsplit=1)[0]
    p = Profile(
        protocol="hysteria2", address=host, port=_port(first_port), name=name,
        password=auth or _first(params, "auth"), raw_link=link, network="hysteria",
    )
    if port_spec != first_port:
        p.hop_ports = port_spec
    p.hop_ports = _first(params, "mport", default=p.hop_ports)
    p.security = "tls"
    p.sni = _first(params, "sni", "peer")
    p.alpn = _first(params, "alpn")
    p.fingerprint = _first(params, "fp").lower()
    p.pinned_sha256 = _first(params, "pinSHA256", "pcs")
    p.verify_names = _first(params, "vcn")
    p.ech_config = _first(params, "ech")
    p.insecure = _flag(_first(params, "insecure", "allowInsecure", default="0"))
    p.obfs = _first(params, "obfs").lower()
    if p.obfs and p.obfs != "salamander":
        raise LinkError(f"обфускация {p.obfs} не поддерживается")
    p.obfs_password = _first(params, "obfs-password", "obfsPassword", "obfs_password")
    return p


PARSERS = {
    "vless": parse_vless,
    "vmess": parse_vmess,
    "trojan": parse_trojan,
    "ss": parse_shadowsocks,
    "socks": parse_socks,
    "socks5": parse_socks,
    "socks4": parse_socks,
    "hysteria2": parse_hysteria2,
    "hy2": parse_hysteria2,
}


def parse_link(link: str) -> Profile:
    link = link.strip()
    scheme = link.split("://", 1)[0].lower() if "://" in link else ""
    parser = PARSERS.get(scheme)
    if parser is None:
        raise LinkError(f"неизвестный тип ссылки: {scheme or link[:20]}")
    profile = parser(link)
    if not profile.name:
        profile.name = f"{profile.address}:{profile.port}"
    return profile


# ---------------------------------------------------------------- JSON-конфиги

def profiles_from_json(text: str) -> list[Profile]:
    """Подписки, которые отдают полный конфиг Xray (один объект или массив)."""
    data = json.loads(text)
    items = data if isinstance(data, list) else [data]
    result: list[Profile] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict) or not isinstance(item.get("outbounds"), list):
            continue
        main = _main_outbound(item["outbounds"])
        if main is None:
            continue
        address, port = _outbound_endpoint(main)
        name = str(item.get("remarks") or item.get("name") or f"Сервер {index}")
        raw = json.dumps(item, ensure_ascii=False, sort_keys=True)
        protocol_name = str(main.get("protocol", ""))
        p = Profile(protocol="json", address=address, port=port, name=name, raw_config=raw)
        stream = main.get("streamSettings") or {}
        p.security = str(stream.get("security") or "none")
        p.network = str(stream.get("network") or protocol_name)
        result.append(p)
    return result


PROXY_PROTOCOLS = {"vless", "vmess", "trojan", "shadowsocks", "socks", "http", "hysteria", "wireguard"}


def _main_outbound(outbounds: list) -> dict | None:
    for ob in outbounds:
        if isinstance(ob, dict) and ob.get("tag") == "proxy":
            return ob
    for ob in outbounds:
        if isinstance(ob, dict) and ob.get("protocol") in PROXY_PROTOCOLS:
            return ob
    return None


def _outbound_endpoint(ob: dict) -> tuple[str, int]:
    settings = ob.get("settings") or {}
    candidates = []
    if "address" in settings:
        candidates.append(settings)
    for key in ("vnext", "servers", "peers"):
        value = settings.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            candidates.append(value[0])
    for c in candidates:
        address = str(c.get("address") or c.get("endpoint") or "")
        try:
            port = int(c.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        if address:
            if not port and ":" in address and address.count(":") == 1:
                address, _, p = address.partition(":")
                port = int(p) if p.isdigit() else 0
            return address, port
    return "", 0


# ---------------------------------------------------------------- массовый импорт

def extract_links(text: str) -> list[str]:
    """Выбирает ссылки из произвольного текста (по одной на строку или вперемешку)."""
    found: list[str] = []
    pattern = re.compile(r"(?i)\b(?:%s)://[^\s<>\"']+" % "|".join(SCHEMES))
    for match in pattern.finditer(text):
        found.append(match.group(0).rstrip(",;"))
    return found


def parse_many(text: str) -> tuple[list[Profile], list[str]]:
    """Разбирает пачку ссылок (в том числе в base64 или в виде JSON). Возвращает профили и ошибки."""
    text = text.strip().lstrip("﻿")
    if not text:
        return [], []

    if text[:1] in "[{":
        try:
            profiles = profiles_from_json(text)
            if profiles:
                return profiles, []
        except json.JSONDecodeError:
            pass

    links = extract_links(text)
    if not links:
        decoded = try_b64decode(text)
        if decoded:
            if decoded.strip()[:1] in "[{":
                try:
                    profiles = profiles_from_json(decoded)
                    if profiles:
                        return profiles, []
                except json.JSONDecodeError:
                    pass
            links = extract_links(decoded)

    profiles: list[Profile] = []
    errors: list[str] = []
    for link in links:
        try:
            profiles.append(parse_link(link))
        except LinkError as exc:
            label = unquote(link.partition("#")[2]) or link[:40] + "…"
            errors.append(f"{label}: {exc}")
    return profiles, errors


def looks_like_subscription(text: str) -> bool:
    text = text.strip()
    return bool(re.fullmatch(r"https?://\S+", text))


def share_link(profile: Profile) -> str:
    """Ссылка для копирования. Для импортированных профилей — исходная."""
    if profile.raw_link:
        return profile.raw_link
    return f"{profile.protocol}://{quote(profile.address)}:{profile.port}#{quote(profile.title())}"
