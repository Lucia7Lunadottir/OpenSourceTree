from typing import Callable, Optional

from PyQt6.QtCore import QObject, QThreadPool
from PyQt6.QtWidgets import QMessageBox, QWidget

from app.i18n import t
from app.constants import LARGE_DIFF_BYTES, HUGE_DIFF_BYTES
from app.git.repo import GitRepo
from app.workers.git_worker import GitWorker
from .diff_viewer import DiffViewer
from .large_file_banner import LargeFileBanner, format_size


class _Request:
    """What to show: how to measure it, how to fetch it, and its name."""

    def __init__(self, path: str, size_fn: Callable[[], int], diff_fn: Callable[[], str]):
        self.path = path
        self.size_fn = size_fn
        self.diff_fn = diff_fn


class DiffController(QObject):
    """Loads diffs off the UI thread and guards against gigantic files.

    A diff is only fetched/rendered automatically when the file is below
    LARGE_DIFF_BYTES; otherwise the viewer shows a notice and the banner offers
    "Open fully". Answers for a file that is no longer selected are dropped.
    """

    def __init__(self, repo: GitRepo, viewer: DiffViewer, banner: LargeFileBanner,
                 dialog_parent: Optional[QWidget] = None):
        super().__init__(viewer)
        self._repo = repo
        self._viewer = viewer
        self._banner = banner
        self._dialog_parent = dialog_parent
        self._token = 0
        self._current: Optional[_Request] = None
        self._current_size = 0
        banner.open_requested.connect(self._on_open_requested)

    # -- public API ---------------------------------------------------------

    def show_commit_file(self, commit_hash: str, path: str):
        self._start(_Request(
            path,
            lambda: self._repo.get_commit_diff_size(commit_hash, path),
            lambda: self._repo.get_diff(commit_hash, path),
        ))

    def show_working_file(self, path: str, staged: bool):
        self._start(_Request(
            path,
            lambda: self._repo.get_working_copy_diff_size(path, staged),
            lambda: self._repo.get_working_copy_diff(path, staged),
        ))

    def clear(self):
        self._token += 1
        self._current = None
        self._banner.hide_banner()
        self._viewer.clear_diff()

    # -- internals ----------------------------------------------------------

    def _start(self, request: _Request, force: bool = False):
        self._token += 1
        token = self._token
        self._current = request
        if not force:
            self._banner.hide_banner()
        self._viewer.show_message(t("diff.loading"))

        def fetch():
            size = 0 if force else request.size_fn()
            if size >= LARGE_DIFF_BYTES:
                return size, None
            return size, request.diff_fn()

        worker = GitWorker(fetch)
        worker.signals.result.connect(lambda res, tok=token, r=request: self._on_ready(tok, r, res))
        worker.signals.error.connect(lambda err, tok=token: self._on_failed(tok, err))
        QThreadPool.globalInstance().start(worker)

    def _on_ready(self, token: int, request: _Request, result):
        if token != self._token:
            return
        size, diff = result
        if diff is None:
            self._current_size = size
            self._viewer.show_message(t("diff.large.not_loaded", path=request.path, size=format_size(size)))
            self._banner.show_for(size)
            return
        self._banner.hide_banner()
        self._viewer.show_diff(diff, request.path)

    def _on_failed(self, token: int, error: str):
        if token != self._token:
            return
        self._banner.hide_banner()
        lines = [l for l in error.splitlines() if l.strip()]
        self._viewer.show_diff(lines[-1] if lines else "Git error")

    def _on_open_requested(self):
        if self._current is None:
            return
        if self._current_size >= HUGE_DIFF_BYTES:
            ret = QMessageBox.warning(
                self._dialog_parent, t("diff.huge.title"),
                t("diff.huge.confirm", size=format_size(self._current_size)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
        self._banner.set_loading()
        self._start(self._current, force=True)
