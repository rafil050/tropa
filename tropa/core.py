"""Ядро Xray: поиск, скачивание с проверкой SHA-256, версия, массовая проверка задержки."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from .models import PING_FAILED, Profile
from .netutil import free_ports, url_delay, wait_port
from .paths import IS_WINDOWS, app_dir, core_dir, xray_name
from .winutil import popen_hidden, run_hidden
from .xray_config import build_test_config

REPO = "XTLS/Xray-core"
CORE_FILES = (xray_name(), "geoip.dat", "geosite.dat")


class CoreError(Exception):
    pass


def asset_name() -> str:
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if IS_WINDOWS:
        if arm:
            return "Xray-windows-arm64-v8a.zip"
        return "Xray-windows-64.zip" if sys.maxsize > 2**32 or machine in ("amd64", "x86_64") else "Xray-windows-32.zip"
    if sys.platform == "darwin":
        return "Xray-macos-arm64-v8a.zip" if arm else "Xray-macos-64.zip"
    return "Xray-linux-arm64-v8a.zip" if arm else "Xray-linux-64.zip"


def find_binary() -> Path | None:
    """Сначала ядро, скачанное или обновлённое пользователем, потом то, что пришло с установщиком."""
    for folder in (core_dir(), app_dir() / "core"):
        candidate = folder / xray_name()
        if candidate.is_file():
            return candidate
    return None


def core_version(binary: Path | None = None) -> str | None:
    binary = binary or find_binary()
    if binary is None:
        return None
    try:
        proc = run_hidden([str(binary), "version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"Xray\s+(\d+\.\d+\.\d+)", proc.stdout)
    return match.group(1) if match else None


def _opener(proxy: str | None):
    proxies = {"http": proxy, "https": proxy} if proxy else {}
    return urllib.request.build_opener(
        urllib.request.ProxyHandler(proxies),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )


def latest_version(proxy: str | None = None, timeout: float = 15) -> str:
    """Номер последней версии на GitHub (без запросов к API — по адресу редиректа)."""
    request = urllib.request.Request(
        f"https://github.com/{REPO}/releases/latest", headers={"User-Agent": "Tropa"}, method="HEAD"
    )
    with _opener(proxy).open(request, timeout=timeout) as response:
        final = response.geturl()
    match = re.search(r"/tag/v?(\d+\.\d+\.\d+)", final)
    if not match:
        raise CoreError("не удалось узнать последнюю версию Xray")
    return match.group(1)


def _download(url: str, target: Path, proxy: str | None, progress: Callable[[int, int], None] | None,
              cancel: threading.Event | None, timeout: float = 30) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Tropa"})
    with _opener(proxy).open(request, timeout=timeout) as response, open(target, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancel is not None and cancel.is_set():
                raise CoreError("загрузка отменена")
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)


def _expected_sha256(dgst_text: str) -> str:
    match = re.search(r"SHA2-256=\s*([0-9a-fA-F]{64})", dgst_text)
    if not match:
        raise CoreError("в файле контрольных сумм нет SHA-256")
    return match.group(1).lower()


def download_core(proxy: str | None = None, progress: Callable[[int, int], None] | None = None,
                  cancel: threading.Event | None = None, target_dir: Path | None = None) -> str:
    """Скачивает последнюю версию Xray с GitHub, проверяет SHA-256 и распаковывает.
    Возвращает установленную версию."""
    target_dir = target_dir or core_dir()
    name = asset_name()
    base = f"https://github.com/{REPO}/releases/latest/download/{name}"
    with tempfile.TemporaryDirectory(prefix="tropa-core-") as tmp:
        tmp_dir = Path(tmp)
        archive = tmp_dir / name
        digest = tmp_dir / (name + ".dgst")
        _download(base + ".dgst", digest, proxy, None, cancel)
        _download(base, archive, proxy, progress, cancel)

        expected = _expected_sha256(digest.read_text("utf-8", errors="replace"))
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != expected:
            raise CoreError("контрольная сумма архива не совпала — файл повреждён или подменён")

        extract_dir = tmp_dir / "x"
        extract_dir.mkdir()
        with zipfile.ZipFile(archive) as zf:
            members = {Path(m).name: m for m in zf.namelist()}
            for wanted in CORE_FILES:
                if wanted not in members:
                    raise CoreError(f"в архиве нет файла {wanted}")
                with zf.open(members[wanted]) as src, open(extract_dir / wanted, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        binary = extract_dir / xray_name()
        if not IS_WINDOWS:
            binary.chmod(0o755)
        version = core_version(binary)
        if not version:
            raise CoreError("скачанное ядро не запускается")

        target_dir.mkdir(parents=True, exist_ok=True)
        for wanted in CORE_FILES:
            destination = target_dir / wanted
            try:
                os.replace(extract_dir / wanted, destination)
            except OSError:
                shutil.copy2(extract_dir / wanted, destination)
        return version


# ------------------------------------------------------------------ проверка многих серверов

BATCH_SIZE = 80


def _failed_index(output: str) -> int | None:
    match = re.search(r"outbound config with tag p(\d+)", output)
    return int(match.group(1)) if match else None


def _core_reason(output: str) -> str:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    return lines[-1].strip()[-200:] if lines else "ядро отклонило конфиг"


def _accepted(items: list[tuple[Profile, int]], check: Callable[[list[tuple[Profile, int]]], tuple[bool, str]],
              on_result: Callable[[str, int, str], None], cancel: threading.Event | None) -> list[tuple[Profile, int]]:
    """Оставляет серверы, которые ядро принимает, остальным сообщает ошибку.
    Виновника сначала ищем по тегу из ошибки ядра. Если ядро его не называет (например, неверный ключ
    Shadowsocks 2022 — «failed to create server»), делим пачку пополам, чтобы один сломанный сервер
    не помечал нерабочими все остальные."""
    while items:
        if cancel is not None and cancel.is_set():
            return []
        ok, output = check(items)
        if ok:
            return items
        if len(items) == 1:
            on_result(items[0][0].id, PING_FAILED, _core_reason(output))
            return []
        index = _failed_index(output)
        if index is not None and index < len(items):
            bad = items[index]
            on_result(bad[0].id, PING_FAILED, _core_reason(output))
            items = items[:index] + items[index + 1:]
            continue
        middle = len(items) // 2
        return (_accepted(items[:middle], check, on_result, cancel)
                + _accepted(items[middle:], check, on_result, cancel))
    return []


def real_delays(profiles: list[Profile], test_url: str, on_result: Callable[[str, int, str], None],
                cancel: threading.Event | None = None, binary: Path | None = None) -> None:
    """Реальная задержка через само ядро: поднимаем один xray с отдельным HTTP-портом
    на каждый сервер и делаем запрос к test_url через каждый порт.
    on_result(id профиля, мс или -1, текст ошибки)."""
    binary = binary or find_binary()
    if binary is None:
        raise CoreError("ядро Xray не установлено")
    env = dict(os.environ, XRAY_LOCATION_ASSET=str(binary.parent))

    for start in range(0, len(profiles), BATCH_SIZE):
        if cancel is not None and cancel.is_set():
            return
        batch = profiles[start:start + BATCH_SIZE]
        items = list(zip(batch, free_ports(len(batch))))

        with tempfile.TemporaryDirectory(prefix="tropa-test-") as tmp:
            config_path = Path(tmp) / "test.json"
            # профили, для которых Tropa сама не может собрать конфиг (понятная причина уже есть)
            _config, failed = build_test_config(items)
            for profile_id, error in failed.items():
                on_result(profile_id, PING_FAILED, error)
            items = [(p, port) for p, port in items if p.id not in failed]

            def check(subset: list[tuple[Profile, int]]) -> tuple[bool, str]:
                # конфиг собирается заново из subset — тег pN всегда указывает на subset[N]
                config_path.write_text(json.dumps(build_test_config(subset)[0]), "utf-8")
                proc = run_hidden([str(binary), "run", "-test", "-c", str(config_path)],
                                  capture_output=True, text=True, timeout=60, env=env)
                return proc.returncode == 0, proc.stdout + proc.stderr

            items = _accepted(items, check, on_result, cancel)
            if not items:
                continue

            config_path.write_text(json.dumps(build_test_config(items)[0]), "utf-8")
            proc = popen_hidden([str(binary), "run", "-c", str(config_path)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            try:
                if not wait_port(items[0][1], timeout=8):
                    for p, _ in items:
                        on_result(p.id, PING_FAILED, "ядро не запустилось")
                    continue

                def check_one(item: tuple[Profile, int]) -> None:
                    if cancel is not None and cancel.is_set():
                        return
                    profile, port = item
                    delay = url_delay(port, test_url)
                    on_result(profile.id, delay, "" if delay > 0 else "нет ответа")

                with ThreadPoolExecutor(max_workers=16) as pool:
                    list(pool.map(check_one, items))
            finally:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
