from typing import Callable
from PyQt6.QtCore import QRunnable
from app.workers.base_worker import WorkerSignals


class StreamingWorker(QRunnable):
    """Call fn(*args) which must return Iterator[str]; emit each line as progress_text."""

    def __init__(self, fn: Callable, *args):
        super().__init__()
        self.fn = fn
        self.args = args
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            for line in self.fn(*self.args):
                self.signals.progress_text.emit(line.rstrip("\n"))
            self.signals.result.emit(None)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()
