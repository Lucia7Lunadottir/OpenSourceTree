from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QWidget

from app.i18n import t
from app.git.repo import GitRepo
from app.workers.git_worker import GitWorker


class ExtractRunner(QObject):
    """Asks for a destination folder and extracts paths of a commit in the background."""
    finished = pyqtSignal(str)   # human-readable result
    failed = pyqtSignal(str)

    def __init__(self, repo: GitRepo, parent: QWidget):
        super().__init__(parent)
        self._repo = repo
        self._parent = parent

    def extract(self, sha: str, paths: list[str]) -> bool:
        """Returns False if the user cancelled the folder choice."""
        dest = QFileDialog.getExistingDirectory(self._parent, t("extract.choose_dest"))
        if not dest:
            return False
        worker = GitWorker(self._repo.extract_paths, sha, paths, dest)
        worker.signals.result.connect(lambda n: self.finished.emit(
            t("extract.done", n=n, dest=dest)))
        worker.signals.error.connect(self.failed.emit)
        QThreadPool.globalInstance().start(worker)
        return True
