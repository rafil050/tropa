"""Фоновые задачи: сеть и ядро не должны подвешивать интерфейс."""

from __future__ import annotations

import inspect
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)
    finished = Signal()


class Task(QRunnable):
    """Запускает функцию в пуле потоков. Если у функции есть параметр `progress`,
    ей передаётся колбэк, который безопасно шлёт данные в главный поток."""

    def __init__(self, fn: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()
        try:
            if "progress" in inspect.signature(fn).parameters:
                self.kwargs["progress"] = self.signals.progress.emit
        except (TypeError, ValueError):
            pass

    def run(self) -> None:
        try:
            try:
                result = self.fn(*self.args, **self.kwargs)
            except Exception as exc:  # noqa: BLE001
                message = str(exc) or exc.__class__.__name__
                traceback.print_exc()
                self.signals.failed.emit(message)
            else:
                self.signals.done.emit(result)
            finally:
                self.signals.finished.emit()
        except RuntimeError:
            pass  # окно уже закрыто, а задача досчиталась — результат никому не нужен


class TaskRunner(QObject):
    """Держит ссылки на задачи, пока они не завершатся (иначе сигналы могут потеряться)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(max(8, self.pool.maxThreadCount()))
        self._alive: set[Task] = set()

    def run(self, fn: Callable[..., Any], *args, on_done=None, on_error=None, on_progress=None,
            on_finished=None, **kwargs) -> Task:
        task = Task(fn, *args, **kwargs)
        if on_done:
            task.signals.done.connect(on_done)
        if on_error:
            task.signals.failed.connect(on_error)
        if on_progress:
            task.signals.progress.connect(on_progress)
        if on_finished:
            task.signals.finished.connect(on_finished)
        task.signals.finished.connect(lambda: self._alive.discard(task))
        task.setAutoDelete(False)
        self._alive.add(task)
        self.pool.start(task)
        return task
