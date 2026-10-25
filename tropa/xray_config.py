"""Сборка JSON-конфига для ядра Xray из профиля и настроек."""

from __future__ import annotations

import copy
import ipaddress
import json
import re
from typing import Any

from .models import Profile, Settings


class ConfigError(ValueError):
    pass


NETWORK_NAMES = {
    "tcp": "tcp",
    "ws": "ws",
    "grpc": "grpc",
    "xhttp": "xhttp",
    "httpupgrade": "httpupgrade",
    "kcp": "kcp",
    "hysteria": "hysteria",
}

SNIFFING = {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": True}

RU_DOMAINS = ["geosite:category-ru", "domain:ru", "domain:su", "domain:xn--p1ai"]

DOMAIN_PREFIXES = ("geosite:", "domain:", "full:", "regexp:", "keyword:", "ext:")


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,\n]", value or "") if item.strip()]


# ---------------------------------------------------------------- транспорт

def _stream(p: Profile, warnings: list[str]) -> dict[str, Any]:
    network = NETWORK_NAMES.get(p.network)
    if network is None:
        raise ConfigError(f"неизвестный транспорт: {p.network}")
    stream: dict[str, Any] = {"network": network}
    path = p.path or "/"

    if network == "tcp":
        if p.header_type == "http":
            request: dict[str, Any] = {"path": [x.strip() for x in path.split(",") if x.strip()] or ["/"]}
            hosts = _split_list(p.host)
            if hosts:
                request["headers"] = {"Host": hosts}
            stream["tcpSettings"] = {"header": {"type": "http", "request": request}}
    elif network == "ws":
        ws: dict[str, Any] = {"path": path}
        if p.host:
            ws["host"] = p.host
        stream["wsSettings"] = ws
    elif network == "httpupgrade":
        hu: dict[str, Any] = {"path": path}
        if p.host:
            hu["host"] = p.host
        stream["httpupgradeSettings"] = hu
    elif network == "grpc":
        grpc: dict[str, Any] = {"serviceName": p.service_name, "multiMode": p.grpc_mode == "multi"}
        if p.authority:
            grpc["authority"] = p.authority
        stream["grpcSettings"] = grpc
    elif network == "xhttp":
        xh: dict[str, Any] = {"path": path, "mode": p.xhttp_mode or "auto"}
        if p.host:
            xh["host"] = p.host
        if p.xhttp_extra:
            try:
                extra = json.loads(p.xhttp_extra)
            except json.JSONDecodeError:
                warnings.append("параметр extra для XHTTP повреждён и пропущен")
            else:
                if isinstance(extra, dict):
                    xh["extra"] = extra
        stream["xhttpSettings"] = xh
    elif network == "kcp":
        masks = []
        if p.kcp_seed:
            masks.append({"type": "mkcp-legacy", "settings": {"value": p.kcp_seed}})
        if p.header_type:
            header = {"wechat-video": "wechat"}.get(p.header_type, p.header_type)
            masks.append({"type": "mkcp-legacy", "settings": {"header": header}})
        if not masks:
            masks.append({"type": "mkcp-legacy"})
        stream["finalmask"] = {"udp": masks}

    _security(p, stream, warnings)
    return stream


def _server_name(p: Profile) -> str:
    if p.sni:
        return p.sni
    if p.host and p.network in ("ws", "httpupgrade", "xhttp") and "," not in p.host:
        return p.host
    if p.address and not _is_ip(p.address):
        return p.address
    return ""


def _security(p: Profile, stream: dict[str, Any], warnings: list[str]) -> None:
    if p.security == "tls":
        tls: dict[str, Any] = {}
        name = _server_name(p)
        if name:
            tls["serverName"] = name
        tls["fingerprint"] = p.fingerprint or "chrome"
        alpn = _split_list(p.alpn)
        if alpn:
            tls["alpn"] = alpn
        if p.pinned_sha256:
            tls["pinnedPeerCertSha256"] = p.pinned_sha256
        if p.verify_names:
            tls["verifyPeerCertByName"] = p.verify_names
        if p.ech_config:
            tls["echConfigList"] = p.ech_config
        if p.insecure and not p.pinned_sha256 and not p.verify_names:
            warnings.append(
                "в ссылке разрешён «небезопасный» TLS (allowInsecure), но ядро Xray это больше не поддерживает. "
                "Если у сервера самоподписанный сертификат, попросите у провайдера ссылку с параметром pcs."
            )
        stream["security"] = "tls"
        stream["tlsSettings"] = tls
    elif p.security == "reality":
        if not p.public_key:
            raise ConfigError("для REALITY нужен публичный ключ (pbk)")
        reality: dict[str, Any] = {
            "fingerprint": p.fingerprint or "chrome",
            "password": p.public_key,
        }
        name = p.sni or ("" if _is_ip(p.address) else p.address)
        if name:
            reality["serverName"] = name
        if p.short_id:
            reality["shortId"] = p.short_id
        if p.spider_x:
            reality["spiderX"] = p.spider_x if p.spider_x.startswith("/") else "/" + p.spider_x
        if p.mldsa65_verify:
            reality["mldsa65Verify"] = p.mldsa65_verify
        stream["security"] = "reality"
        stream["realitySettings"] = reality
    else:
        stream["security"] = "none"


# ---------------------------------------------------------------- исходящие

def _is_private_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        host = address.lower().rstrip(".")
        return host == "localhost" or "." not in host or host.endswith((".local", ".lan", ".internal", ".home.arpa"))
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _check_plaintext(p: Profile) -> None:
    """Ядро Xray само запрещает VLESS/Trojan без шифрования к публичным адресам — скажем об этом понятно."""
    if p.security != "none" or _is_private_address(p.address):
        return
    if p.protocol == "vless" and p.encryption in ("", "none"):
        raise ConfigError("ядро Xray не разрешает VLESS без TLS/REALITY к публичному серверу — это небезопасно")
    if p.protocol == "trojan":
        raise ConfigError("ядро Xray не разрешает Trojan без TLS к публичному серверу")


def build_outbound(p: Profile, tag: str = "proxy", warnings: list[str] | None = None) -> dict[str, Any]:
    """Исходящее соединение Xray для одного обычного профиля (не JSON)."""
    if warnings is None:
        warnings = []
    if not p.address or not p.port:
        raise ConfigError("не указан адрес или порт сервера")
    _check_plaintext(p)

    if p.protocol == "vless":
        user: dict[str, Any] = {"id": p.uuid, "encryption": p.encryption or "none"}
        if p.flow:
            user["flow"] = p.flow
        outbound = {
            "protocol": "vless",
            "settings": {"vnext": [{"address": p.address, "port": p.port, "users": [user]}]},
        }
        outbound["streamSettings"] = _stream(p, warnings)
    elif p.protocol == "vmess":
        outbound = {
            "protocol": "vmess",
            "settings": {"vnext": [{
                "address": p.address, "port": p.port,
                "users": [{"id": p.uuid, "security": p.cipher or "auto"}],
            }]},
        }
        outbound["streamSettings"] = _stream(p, warnings)
    elif p.protocol == "trojan":
        outbound = {
            "protocol": "trojan",
            "settings": {"servers": [{"address": p.address, "port": p.port, "password": p.password}]},
        }
        outbound["streamSettings"] = _stream(p, warnings)
    elif p.protocol == "shadowsocks":
        outbound = {
            "protocol": "shadowsocks",
            "settings": {"servers": [{
                "address": p.address, "port": p.port, "method": p.method, "password": p.password,
            }]},
        }
    elif p.protocol == "socks":
        server: dict[str, Any] = {"address": p.address, "port": p.port}
        if p.username:
            server["users"] = [{"user": p.username, "pass": p.password}]
        outbound = {"protocol": "socks", "settings": {"servers": [server]}}
    elif p.protocol == "hysteria2":
        stream: dict[str, Any] = {
            "network": "hysteria",
            "hysteriaSettings": {"version": 2, "auth": p.password},
        }
        _security(p, stream, warnings)
        udp_masks = []
        if p.obfs == "salamander":
            udp_masks.append({"type": "salamander", "settings": {"password": p.obfs_password}})
        if p.hop_ports:
            udp_masks.append({
                "type": "udphop",
                "settings": {"mode": "intervalLocal,intervalRemote", "remotePorts": p.hop_ports},
            })
        if udp_masks:
            stream["finalmask"] = {"udp": udp_masks}
        outbound = {
            "protocol": "hysteria",
            "settings": {"version": 2, "address": p.address, "port": p.port},
            "streamSettings": stream,
        }
    else:
        raise ConfigError(f"протокол {p.protocol} не поддерживается")

    outbound["tag"] = tag
    return outbound


def _json_outbounds(p: Profile, tag: str, prefix: str = "") -> list[dict[str, Any]]:
    """Достаёт исходящие из полного JSON-конфига: главный получает тег `tag`,
    вспомогательные (цепочки через dialerProxy) — префикс, чтобы не пересекаться с нашими."""
    from .links import _main_outbound  # локально, чтобы не было циклического импорта

    try:
        config = json.loads(p.raw_config)
    except json.JSONDecodeError:
        raise ConfigError("JSON-конфиг сервера повреждён") from None
    outbounds = [ob for ob in config.get("outbounds", []) if isinstance(ob, dict)]
    main = _main_outbound(outbounds)
    if main is None:
        raise ConfigError("в JSON-конфиге нет прокси-сервера")

    def references(obj: Any, found: set[str]) -> set[str]:
        """Теги, на которые ссылаются через dialerProxy или proxySettings."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "dialerProxy" and isinstance(value, str):
                    found.add(value)
                elif key == "proxySettings" and isinstance(value, dict) and isinstance(value.get("tag"), str):
                    found.add(value["tag"])
                else:
                    references(value, found)
        elif isinstance(obj, list):
            for item in obj:
                references(item, found)
        return found

    used = references(outbounds, set())
    renames: dict[str, str] = {}
    main_out: dict[str, Any] = {}
    aux: list[dict[str, Any]] = []
    for index, ob in enumerate(outbounds):
        ob = copy.deepcopy(ob)
        old = ob.get("tag", "")
        if outbounds[index] is main:
            new = tag
            main_out = ob
        elif ob.get("protocol") in ("freedom", "blackhole", "dns", "loopback") and old not in used:
            continue  # свои direct/block добавим сами
        else:
            new = f"{prefix}aux{index}"
            aux.append(ob)
        if old:
            renames[old] = new
        ob["tag"] = new

    def fix(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "dialerProxy" and isinstance(value, str):
                    obj[key] = renames.get(value, value)
                elif key == "proxySettings" and isinstance(value, dict) and isinstance(value.get("tag"), str):
                    value["tag"] = renames.get(value["tag"], value["tag"])
                else:
                    fix(value)
        elif isinstance(obj, list):
            for item in obj:
                fix(item)

    result = [main_out] + aux
    fix(result)
    return result


def outbounds_for(p: Profile, tag: str = "proxy", warnings: list[str] | None = None, prefix: str = "") -> list[dict[str, Any]]:
    if p.protocol == "json":
        return _json_outbounds(p, tag, prefix)
    return [build_outbound(p, tag, warnings)]


# ---------------------------------------------------------------- маршрутизация

def parse_rule_list(text: str) -> tuple[list[str], list[str]]:
    """Список из настроек → (домены для Xray, IP/подсети для Xray)."""
    domains: list[str] = []
    ips: list[str] = []
    for raw in re.split(r"[\n,]", text or ""):
        item = raw.split("#", 1)[0].strip()
        if not item:
            continue
        lower = item.lower()
        if lower.startswith("geoip:"):
            ips.append(lower)
            continue
        try:
            ipaddress.ip_network(item, strict=False)
            ips.append(item)
            continue
        except ValueError:
            pass
        if lower.startswith(DOMAIN_PREFIXES):
            domains.append(item if not lower.startswith("geosite:") else lower)
            continue
        host = re.sub(r"^[a-z]+://", "", lower).split("/", 1)[0]
        host = host.lstrip("*.").strip(".")
        if host:
            domains.append(f"domain:{host}")
    return domains, ips


def _rules_for(domains: list[str], ips: list[str], outbound: str) -> list[dict[str, Any]]:
    rules = []
    if domains:
        rules.append({"type": "field", "domain": domains, "outboundTag": outbound})
    if ips:
        rules.append({"type": "field", "ip": ips, "outboundTag": outbound})
    return rules


def build_routing(settings: Settings, bypass_private: bool = True) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    if bypass_private:
        rules.append({"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"})
    if settings.block_ads:
        rules.append({"type": "field", "domain": ["geosite:category-ads-all"], "outboundTag": "block"})

    proxy_domains, proxy_ips = parse_rule_list(settings.proxy_list)
    direct_domains, direct_ips = parse_rule_list(settings.direct_list)
    rules += _rules_for(proxy_domains, proxy_ips, "proxy")
    if settings.routing_mode != "whitelist":
        rules += _rules_for(direct_domains, direct_ips, "direct")

    if settings.routing_mode == "bypass_ru":
        rules.append({"type": "field", "domain": list(RU_DOMAINS), "outboundTag": "direct"})
        rules.append({"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"})
    elif settings.routing_mode == "whitelist":
        rules.append({"type": "field", "network": "tcp,udp", "outboundTag": "direct"})

    strategy = "AsIs" if settings.routing_mode == "global" else "IPIfNonMatch"
    return {"domainStrategy": strategy, "rules": rules}


# ---------------------------------------------------------------- полный конфиг

def build_config(profile: Profile, settings: Settings, *, bypass_private: bool = True) -> tuple[dict[str, Any], list[str]]:
    """Конфиг для обычного подключения. Возвращает (конфиг, предупреждения)."""
    warnings: list[str] = []
    listen = "0.0.0.0" if settings.allow_lan else "127.0.0.1"
    if settings.socks_port == settings.http_port:
        raise ConfigError("порты SOCKS и HTTP должны различаться")

    outbounds = outbounds_for(profile, "proxy", warnings, prefix="sub-")
    outbounds.append({"tag": "direct", "protocol": "freedom"})
    outbounds.append({"tag": "block", "protocol": "blackhole"})

    level = settings.log_level if settings.log_level in ("debug", "info", "warning", "error", "none") else "warning"
    config: dict[str, Any] = {
        "log": {"loglevel": level, "access": "" if level in ("debug", "info") else "none"},
        "inbounds": [
            {
                "tag": "socks-in", "listen": listen, "port": settings.socks_port, "protocol": "socks",
                "settings": {"udp": True, "auth": "noauth"}, "sniffing": dict(SNIFFING),
            },
            {
                "tag": "http-in", "listen": listen, "port": settings.http_port, "protocol": "http",
                "settings": {}, "sniffing": dict(SNIFFING),
            },
        ],
        "outbounds": outbounds,
        "routing": build_routing(settings, bypass_private),
    }
    dns_servers = _split_list(settings.dns)
    if dns_servers:
        config["dns"] = {"servers": dns_servers}
    return config, warnings


def build_test_config(items: list[tuple[Profile, int]]) -> tuple[dict[str, Any], dict[str, str]]:
    """Конфиг для одновременной проверки многих серверов: у каждого свой HTTP-порт.
    Возвращает (конфиг, {id профиля: ошибка}) — сломанные профили в конфиг не попадают."""
    inbounds: list[dict[str, Any]] = []
    outbounds: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    failed: dict[str, str] = {}
    for index, (profile, port) in enumerate(items):
        try:
            obs = outbounds_for(profile, f"p{index}", prefix=f"p{index}-")
        except (ConfigError, ValueError) as exc:
            failed[profile.id] = str(exc)
            continue
        inbounds.append({"tag": f"t{index}", "listen": "127.0.0.1", "port": port, "protocol": "http", "settings": {}})
        outbounds.extend(obs)
        rules.append({"type": "field", "inboundTag": [f"t{index}"], "outboundTag": f"p{index}"})
    outbounds.append({"tag": "direct", "protocol": "freedom"})
    config = {
        "log": {"loglevel": "none", "access": "none"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"domainStrategy": "AsIs", "rules": rules},
    }
    return config, failed
