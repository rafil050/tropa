"""Точка входа: python main.py  (или pythonw main.py — без окна консоли)."""

import sys
import traceback


def _redirect_output() -> None:
    """В оконном режиме (pythonw, собранный exe) stdout/stderr отсутствуют — пишем их в tropa.log."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        from tropa.paths import data_dir

        log = open(data_dir() / "tropa.log", "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


def _show_crash(text: str) -> None:
    print(text, file=sys.stderr)
    if sys.platform == "win32":
        import ctypes

        message = "Tropa не смогла запуститься.\n\n" + text[-1500:]
        ctypes.windll.user32.MessageBoxW(None, message, "Tropa", 0x10)


if __name__ == "__main__":
    _redirect_output()
    try:
        from tropa.app import run

        sys.exit(run())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        _show_crash(traceback.format_exc())
        sys.exit(1)
