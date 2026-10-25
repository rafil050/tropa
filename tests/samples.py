"""Тестовые ссылки (все ключи и адреса выдуманные)."""

import base64
import json
from urllib.parse import quote

UUID = "a6dbbbcc-dcd6-4341-98bd-2ee419f4bf5d"
PBK = "U9_qeJ3EzZdI12W4kytXU3vMdGoKMNCxf9FmLv_KrBg"
SS22_KEY = "WJpaXfQnjpu7OjqjHzrKJA=="

VMESS_WS = "vmess://" + base64.b64encode(json.dumps({
    "v": "2", "ps": "VMess WS", "add": "vm.example.com", "port": "443", "id": UUID, "aid": "0",
    "scy": "auto", "net": "ws", "type": "none", "host": "vm.example.com", "path": "/vmws",
    "tls": "tls", "sni": "vm.example.com", "alpn": "h2,http/1.1", "fp": "firefox",
}).encode()).decode()

VMESS_TCP_HTTP = "vmess://" + base64.urlsafe_b64encode(json.dumps({
    "v": "2", "ps": "VMess HTTP header", "add": "1.2.3.4", "port": 8080, "id": UUID, "aid": 0,
    "net": "tcp", "type": "http", "host": "speedtest.net", "path": "/", "tls": "",
}).encode()).decode().rstrip("=")

SAMPLES = {
    "vless_reality": (
        f"vless://{UUID}@nl.example.com:443?encryption=none&flow=xtls-rprx-vision&security=reality"
        f"&sni=www.microsoft.com&fp=chrome&pbk={PBK}&sid=6ba85179e30d4fc2&spx=%2F&type=tcp&headerType=none"
        "#%F0%9F%87%B3%F0%9F%87%B1%20Нидерланды"
    ),
    "vless_ws_tls": (
        f"vless://{UUID}@1.2.3.4:443?encryption=none&security=tls&sni=cdn.example.com&type=ws"
        "&host=cdn.example.com&path=%2Fws%3Fed%3D2048&allowInsecure=1#WS%20TLS"
    ),
    "vless_grpc": (
        f"vless://{UUID}@grpc.example.com:443?security=tls&type=grpc&serviceName=gun&mode=multi"
        "&alpn=h2&fp=safari#gRPC"
    ),
    "vless_xhttp_reality": (
        f"vless://{UUID}@xh.example.com:443?encryption=none&security=reality&sni=yahoo.com&pbk={PBK}"
        "&sid=ab&type=xhttp&path=%2Fxh&mode=packet-up"
        "&extra=" + quote(json.dumps({"xPaddingBytes": "100-1000", "noGRPCHeader": True})) + "#XHTTP"
    ),
    "vless_httpupgrade": (
        f"vless://{UUID}@hu.example.com:443?type=httpupgrade&security=tls&host=hu.example.com&path=%2Fup#HTTPUpgrade"
    ),
    "vless_kcp": f"vless://{UUID}@[fd00::1]:4000?type=kcp&headerType=wechat-video&seed=s33d#KCP",
    "vless_lan_plain": f"vless://{UUID}@192.168.1.10:8080?type=tcp#LAN",
    "vmess_ws": VMESS_WS,
    "vmess_tcp_http": VMESS_TCP_HTTP,
    "trojan": "trojan://p%40ss@tr.example.com:443?sni=tr.example.com&type=tcp#Trojan",
    "trojan_ws": "trojan://secret@tr.example.com:8443?security=tls&type=ws&path=%2Ftr&host=tr.example.com#Trojan%20WS",
    "ss_sip002": "ss://" + base64.urlsafe_b64encode(b"aes-256-gcm:pass").decode().rstrip("=") + "@5.6.7.8:8388#SS",
    "ss_2022": f"ss://2022-blake3-aes-128-gcm:{quote(SS22_KEY, safe='')}@ss.example.com:443#SS2022",
    "ss_legacy": "ss://" + base64.b64encode(b"chacha20-ietf-poly1305:pw@9.9.9.9:443").decode() + "#Legacy",
    "socks": "socks://" + base64.b64encode(b"user:pass").decode() + "@1.2.3.4:1080#Socks",
    "socks5_plain": "socks5://bob:secret@[::1]:1080",
    "hy2": "hysteria2://myauth@hy.example.com:443?sni=hy.example.com&obfs=salamander&obfs-password=obfspw#HY2",
    "hy2_hop": "hy2://user%3Apass@hy.example.com:443,20000-30000/?sni=hy.example.com&insecure=1#Hop",
}

# Разбираются, но ядро Xray их не примет (VLESS/Trojan без шифрования к публичному адресу)
PLAINTEXT = {
    "vless_plain_public": f"vless://{UUID}@hu.example.com:80?type=httpupgrade&host=hu.example.com&path=%2Fup#Plain",
    "trojan_plain_public": "trojan://pw@8.8.4.4:80?security=none#PlainTrojan",
}

BAD = {
    "h2": f"vless://{UUID}@x.com:443?type=h2&security=tls#old",
    "plugin": "ss://" + base64.urlsafe_b64encode(b"aes-256-gcm:pass").decode() + "@1.1.1.1:8388/?plugin=obfs-local%3Bobfs%3Dhttp#P",
    "no_port": f"vless://{UUID}@x.com?security=none",
    "unknown": "wireguard://abc@1.1.1.1:51820",
    "reality_no_key": f"vless://{UUID}@x.com:443?security=reality&sni=a.com",
}

JSON_SUB = json.dumps([
    {
        "remarks": "🇩🇪 Germany JSON",
        "outbounds": [
            {
                "tag": "proxy", "protocol": "vless",
                "settings": {"vnext": [{"address": "de.example.com", "port": 443,
                                        "users": [{"id": UUID, "encryption": "none", "flow": "xtls-rprx-vision"}]}]},
                "streamSettings": {"network": "tcp", "security": "reality",
                                   "realitySettings": {"serverName": "www.google.com", "password": PBK,
                                                       "fingerprint": "chrome", "shortId": "abcd"},
                                   "sockopt": {"dialerProxy": "fragment"}},
            },
            {"tag": "fragment", "protocol": "freedom",
             "settings": {"fragment": {"packets": "tlshello", "length": "100-200", "interval": "10-20"}}},
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {"rules": []},
    }
])
