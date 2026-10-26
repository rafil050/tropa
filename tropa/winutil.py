"""Всё, что специфично для Windows: системный прокси, автозапуск, привязка дочерних процессов.
На других системах функции ничего не делают — так приложение можно запускать и тестировать где угодно."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .paths import IS_WINDOWS, data_dir

if IS_WINDOWS:
    import ctypes
    import winreg
    from ctypes import wintypes

INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PROXY_BYPASS = "localhost;127.*;10.*;172.16.*;172.17.*;172.18.*;172.19.*;172.20.*;172.21.*;172.22.*;172.23.*;" \
               "172.24.*;172.25.*;172.26.*;172.27.*;172.28.*;172.29.*;172.30.*;172.31.*;192.168.*;<local>"

NO_WINDOW = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW


def _backup_path() -> Path:
    return data_dir() / "proxy_backup.json"


# ------------------------------------------------------------------ системный прокси

def _read_proxy() -> dict:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS, 0, winreg.KEY_READ) as key:
        def get(name, default):
            try:
                return winreg.QueryValueEx(key, name)[0]
            except FileNotFoundError:
                return default
        return {
            "ProxyEnable": int(get("ProxyEnable", 0)),
            "ProxyServer": str(get("ProxyServer", "")),
            "ProxyOverride": str(get("ProxyOverride", "")),
        }


def _write_proxy(enable: int, server: str, override: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, enable)
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server)
        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, override)
    _notify_proxy_changed()


def _notify_proxy_changed() -> None:
    internet_set_option = ctypes.windll.wininet.InternetSetOptionW
    internet_set_option(None, 39, None, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
    internet_set_option(None, 37, None, 0)  # INTERNET_OPTION_REFRESH


def enable_system_proxy(http_port: int) -> None:
    if not IS_WINDOWS:
        return
    server = f"127.0.0.1:{http_port}"
    current = _read_proxy()
    # запоминаем прежние настройки, если это не наши
    if current["ProxyServer"] != server:
        _backup_path().write_text(json.dumps(current), "utf-8")
    _write_proxy(1, server, PROXY_BYPASS)


def disable_system_proxy(http_port: int | None = None) -> None:
    """Возвращает прокси Windows как было до нас."""
    if not IS_WINDOWS:
        return
    backup = _backup_path()
    previous = None
    if backup.exists():
        try:
            previous = json.loads(backup.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
    current = _read_proxy()
    ours = current["ProxyServer"].startswith("127.0.0.1:") and (
        http_port is None or current["ProxyServer"] == f"127.0.0.1:{http_port}"
    )
    if ours:
        if previous and not str(previous.get("ProxyServer", "")).startswith("127.0.0.1:"):
            _write_proxy(int(previous.get("ProxyEnable", 0)), str(previous.get("ProxyServer", "")),
                         str(previous.get("ProxyOverride", "")))
        else:
            _write_proxy(0, current["ProxyServer"], current["ProxyOverride"])
    try:
        backup.unlink()
    except OSError:
        pass


def system_proxy_points_to(http_port: int) -> bool:
    if not IS_WINDOWS:
        return False
    current = _read_proxy()
    return bool(current["ProxyEnable"]) and current["ProxyServer"] == f"127.0.0.1:{http_port}"


# ------------------------------------------------------------------ автозапуск

def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    main = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{exe}" "{main}" --minimized'


def set_autostart(enabled: bool, name: str = "Tropa") -> None:
    if not IS_WINDOWS:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


# ------------------------------------------------------------------ одна копия программы

class InstanceLock:
    """Именованный мьютекс Windows: «я — первая копия Tropa».

    Проверка через QLocalServer сама по себе не атомарна: пока первая копия грузится
    (несколько секунд), вторая не находит её сервер и тоже открывает окно и значок в трее.
    Мьютекс создаётся ядром Windows атомарно, поэтому двух владельцев быть не может.
    На других системах замок всегда «свободен» — там работает только проверка через сокет."""

    _WAIT_OBJECT_0 = 0x00000000
    _WAIT_ABANDONED = 0x00000080
    _ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str):
        self.handle = None
        self.owned = not IS_WINDOWS
        if not IS_WINDOWS:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self._kernel32 = kernel32
        handle = kernel32.CreateMutexW(None, True, f"Local\\{name}")
        error = ctypes.get_last_error()
        if not handle:  # мьютекс создать не удалось — не мешаем запуску, остаётся проверка через сокет
            self.owned = True
            return
        self.handle = handle  # держим до конца работы: Windows освободит мьютекс при выходе процесса
        self.owned = error != self._ERROR_ALREADY_EXISTS

    def wait(self, timeout_ms: int) -> bool:
        """Ждём, не освободит ли мьютекс закрывающаяся копия. True — теперь он наш."""
        if self.owned or self.handle is None:
            return True
        result = self._kernel32.WaitForSingleObject(self.handle, timeout_ms)
        self.owned = result in (self._WAIT_OBJECT_0, self._WAIT_ABANDONED)
        return self.owned


# ------------------------------------------------------------------ дочерние процессы

class _KillOnCloseJob:
    """Job Object Windows: дочерние процессы завершаются вместе с приложением,
    даже если оно упало. Иначе xray.exe мог бы остаться висеть и держать порты."""

    def __init__(self):
        self.handle = None
        if not IS_WINDOWS:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32 = kernel32

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.OpenProcess.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)  # JobObjectExtendedLimitInformation
        )
        if ok:
            self.handle = job

    def attach(self, pid: int) -> None:
        if not self.handle or not pid:
            return
        k = self._kernel32
        process = k.OpenProcess(0x0001 | 0x0100, False, pid)  # PROCESS_TERMINATE | PROCESS_SET_QUOTA
        if process:
            k.AssignProcessToJobObject(wintypes.HANDLE(self.handle), wintypes.HANDLE(process))
            k.CloseHandle(wintypes.HANDLE(process))


_job: _KillOnCloseJob | None = None


def bind_child_to_app(pid: int) -> None:
    global _job
    if not IS_WINDOWS:
        return
    if _job is None:
        _job = _KillOnCloseJob()
    _job.attach(pid)


def popen_hidden(args: list[str], **kwargs) -> subprocess.Popen:
    """Запуск консольной программы без мигающего окна."""
    if IS_WINDOWS:
        kwargs.setdefault("creationflags", NO_WINDOW)
    proc = subprocess.Popen(args, **kwargs)
    bind_child_to_app(proc.pid)
    return proc


def run_hidden(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    if IS_WINDOWS:
        kwargs.setdefault("creationflags", NO_WINDOW)
    return subprocess.run(args, **kwargs)


def dark_title_bar(hwnd: int) -> None:
    """Тёмный заголовок окна в Windows 10/11 — под тёмную тему приложения."""
    if not IS_WINDOWS:
        return
    try:
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (новые и старые сборки)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd), attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except (AttributeError, OSError):
        pass


def set_app_user_model_id(app_id: str) -> None:
    """Чтобы Windows показывала нашу иконку на панели задач, а не иконку Python."""
    if IS_WINDOWS:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except (AttributeError, OSError):
            pass
