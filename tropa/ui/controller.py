"""Управление подключением: запуск/остановка xray, системный прокси, логи."""

from __future__ import annotations

import json
import time
from collections import deque

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .. import winutil
from ..core import find_binary
from ..models import Profile, Settings
from ..netutil import port_is_free
from ..paths import data_dir
from ..xray_config import ConfigError, build_config


class ConnectionController(QObject):
    stateChanged = Signal(str)  # off / connecting / on
    logLine = Signal(str)
    failed = Signal(str)

    START_TIMEOUT_MS = 10000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "off"
        self.profile: Profile | None = None
        self.settings: Settings | None = None
        self.connected_at = 0.0
        self._proc: QProcess | None = None
        self._stopping = False
        self._proxy_enabled = False
        self._tail: deque[str] = deque(maxlen=40)
        self._poll = QTimer(self, interval=150)
        self._poll.timeout.connect(self._check_started)
        self._started_at = 0.0
        self._buffer = ""

    # ------------------------------------------------------------ публичное

    def is_running(self) -> bool:
        return self.state in ("connecting", "on")

    def start(self, profile: Profile, settings: Settings) -> None:
        self.stop(quiet=True)
        self.profile, self.settings = profile, settings
        binary = find_binary()
        if binary is None:
            self.failed.emit("Ядро Xray не установлено. Скачайте его в настройках.")
            return
        try:
            config, warnings = build_config(profile, settings)
        except (ConfigError, ValueError) as exc:
            self.failed.emit(f"Не удалось подготовить подключение: {exc}")
            return
        for warning in warnings:
            self._log(f"⚠ {warning}")

        host = "0.0.0.0" if settings.allow_lan else "127.0.0.1"
        for port in (settings.socks_port, settings.http_port):
            if not port_is_free(port, host):
                self.failed.emit(f"Порт {port} уже занят другой программой. Поменяйте порты в настройках.")
                return

        path = data_dir() / "config.json"
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), "utf-8")

        proc = QProcess(self)
        proc.setProgram(str(binary))
        proc.setArguments(["run", "-c", str(path)])
        proc.setWorkingDirectory(str(binary.parent))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("XRAY_LOCATION_ASSET", str(binary.parent))
        proc.setProcessEnvironment(env)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._read_output)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc = proc
        self._stopping = False
        self._tail.clear()
        self._buffer = ""
        self._set_state("connecting")
        self._log(f"Подключение к «{profile.title()}» ({profile.protocol_title()}, {profile.summary()})")
        proc.start()
        if proc.waitForStarted(3000):
            winutil.bind_child_to_app(int(proc.processId()))
            self._started_at = time.monotonic()
            self._poll.start()

    def stop(self, quiet: bool = False) -> None:
        self._poll.stop()
        self._disable_proxy()
        proc, self._proc = self._proc, None
        if proc is not None:
            self._stopping = True
            try:
                proc.finished.disconnect(self._on_finished)
                proc.errorOccurred.disconnect(self._on_error)
            except (RuntimeError, TypeError):
                pass
            if proc.state() != QProcess.NotRunning:
                proc.kill()
                proc.waitForFinished(3000)
            self._read_from(proc)
            proc.deleteLater()
            if not quiet:
                self._log("Отключено")
        self.connected_at = 0.0
        if self.state != "off":
            self._set_state("off")

    def apply_system_proxy(self, enabled: bool) -> None:
        """Включить/выключить системный прокси без переподключения."""
        if self.state != "on" or self.settings is None:
            return
        if enabled:
            self._enable_proxy()
        else:
            self._disable_proxy()

    def tail(self) -> str:
        return "\n".join(self._tail)

    # ------------------------------------------------------------ внутреннее

    def _set_state(self, state: str) -> None:
        self.state = state
        self.stateChanged.emit(state)

    def _log(self, text: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {text}"
        self.logLine.emit(line)

    def _read_output(self) -> None:
        if self._proc is not None:
            self._read_from(self._proc)

    def _read_from(self, proc: QProcess) -> None:
        data = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not data:
            return
        self._buffer += data
        *lines, self._buffer = self._buffer.split("\n")
        for raw in lines:
            line = raw.rstrip("\r")
            if line.strip():
                self._tail.append(line)
                self.logLine.emit(line)

    def _check_started(self) -> None:
        if self._proc is None or self.settings is None:
            self._poll.stop()
            return
        from ..netutil import wait_port

        if wait_port(self.settings.http_port, timeout=0.05):
            self._poll.stop()
            self.connected_at = time.time()
            if self.settings.system_proxy:
                self._enable_proxy()
            self._set_state("on")
            self._log("Подключено")
            return
        if (time.monotonic() - self._started_at) * 1000 > self.START_TIMEOUT_MS:
            self._poll.stop()
            reason = self._last_error() or "ядро не ответило вовремя"
            self.stop(quiet=True)
            self.failed.emit(f"Не удалось подключиться: {reason}")

    def _on_finished(self, code: int, _status) -> None:
        if self._stopping:
            return
        proc = self._proc
        if proc is not None:
            self._read_from(proc)
        was = self.state
        self._poll.stop()
        self._disable_proxy()
        self._proc = None
        if proc is not None:
            proc.deleteLater()
        self.connected_at = 0.0
        self._set_state("off")
        reason = self._last_error() or f"ядро завершилось с кодом {code}"
        if was == "connecting":
            self.failed.emit(f"Не удалось подключиться: {reason}")
        else:
            self.failed.emit(f"Соединение прервано: {reason}")

    def _on_error(self, error) -> None:
        if error == QProcess.FailedToStart:
            self._poll.stop()
            self._proc = None
            self._set_state("off")
            self.failed.emit("Не удалось запустить ядро Xray. Проверьте, не блокирует ли его антивирус.")

    def _last_error(self) -> str:
        for line in reversed(self._tail):
            low = line.lower()
            if "failed" in low or "error" in low or "panic" in low:
                text = line.split("> ")[-1] if "> " in line else line
                return text.strip()[-220:]
        return ""

    def _enable_proxy(self) -> None:
        if self.settings is None:
            return
        try:
            winutil.enable_system_proxy(self.settings.http_port)
            self._proxy_enabled = True
        except OSError as exc:
            self._log(f"Не удалось включить системный прокси: {exc}")

    def _disable_proxy(self) -> None:
        if not self._proxy_enabled:
            return
        try:
            winutil.disable_system_proxy(self.settings.http_port if self.settings else None)
        except OSError as exc:
            self._log(f"Не удалось выключить системный прокси: {exc}")
        self._proxy_enabled = False
