import traceback
from typing import Callable, Any
from .base_worker import BaseWorker


class GitWorker(BaseWorker):
    """Generic async git operation worker."""

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.signals.result.emit(result)
        except Exception as e:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()
