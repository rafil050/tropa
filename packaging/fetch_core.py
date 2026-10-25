"""Скачивает ядро Xray для Windows в папку сборки и проверяет SHA-256.

    python packaging/fetch_core.py dist/Tropa/core [версия]

Без версии берётся последний релиз. Кладёт xray.exe, geoip.dat, geosite.dat и LICENSE-Xray.txt.
"""

from __future__ import annotations

import hashlib
import io
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "XTLS/Xray-core"
ASSET = "Xray-windows-64.zip"


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Tropa-build"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def main() -> int:
    # консоль Windows в CI работает в cp1252 — без этого русский текст в выводе роняет скрипт
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/Tropa/core")
    version = sys.argv[2] if len(sys.argv) > 2 else ""
    base = (f"https://github.com/{REPO}/releases/download/v{version.lstrip('v')}/" if version
            else f"https://github.com/{REPO}/releases/latest/download/")
    print(f"Скачиваю {base}{ASSET}")
    digest = get(base + ASSET + ".dgst").decode("utf-8", "replace")
    expected = re.search(r"SHA2-256=\s*([0-9a-fA-F]{64})", digest)
    if not expected:
        print("В файле контрольных сумм нет SHA-256")
        return 1
    archive = get(base + ASSET)
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected.group(1).lower():
        print("Контрольная сумма не совпала — архив повреждён или подменён")
        return 1
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        names = {Path(n).name: n for n in zf.namelist()}
        for src, dst in (("xray.exe", "xray.exe"), ("geoip.dat", "geoip.dat"),
                         ("geosite.dat", "geosite.dat"), ("LICENSE", "LICENSE-Xray.txt")):
            (target / dst).write_bytes(zf.read(names[src]))
    print(f"Ядро Xray сохранено в {target} (SHA-256 проверен)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
