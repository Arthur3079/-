from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import QObject, pyqtSignal


class OperationWorker(QObject):
    progress = pyqtSignal(int)
    current_path = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, task: Callable[..., object], *args, **kwargs) -> None:
        super().__init__()
        self._task = task
        self._args = args
        self._kwargs = kwargs
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def is_cancelled(self) -> bool:
        return self._cancel_requested

    def run(self) -> None:
        try:
            result = self._task(
                *self._args,
                **self._kwargs,
                cancel_check=self.is_cancelled,
                progress_cb=self.progress.emit,
                current_path_cb=self.current_path.emit,
            )
            if self._cancel_requested:
                self.cancelled.emit()
                return
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
