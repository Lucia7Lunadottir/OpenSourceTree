from typing import Callable
from PyQt6.QtCore import QRunnable
from app.workers.base_worker import WorkerSignals


class BatchWorker(QRunnable):
    """Run fn(item) for each item in items; emit progress(current, total) after each."""

    def __init__(self, fn: Callable, items: list, *extra_args):
        super().__init__()
        self.fn = fn
        self.items = items
        self.extra_args = extra_args
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        total = len(self.items)
        for i, item in enumerate(self.items, 1):
            try:
                self.fn(item, *self.extra_args)
            except Exception as e:
                self.signals.error.emit(str(e))
                return
            self.signals.progress.emit(i, total)
        self.signals.result.emit(None)
        self.signals.finished.emit()
