from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QWidget

from app.i18n import t
from app.git.repo import GitRepo
from app.git.remote_attach import EmptyRepoAdvisor, EmptyRepoState, RemoteHistoryAttacher
from app.workers.git_worker import GitWorker
from .empty_repo_banner import EmptyRepoBanner
from .dialogs.remote_dialog import RemoteDialog
from .dialogs.remotes_dialog import RemotesDialog


class EmptyRepoController(QObject):
    """Keeps EmptyRepoBanner in step with the repository and runs its action:
    connect a remote, fetch it, or attach the first branch to its history."""
    changed = pyqtSignal()          # repository state changed: the tab should refresh
    status_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, repo: GitRepo, banner: EmptyRepoBanner, dialog_parent: QWidget):
        super().__init__(dialog_parent)
        self._repo = repo
        self._banner = banner
        self._dialog_parent = dialog_parent
        self._advisor = EmptyRepoAdvisor(repo)
        self._fetched = False
        self._state: EmptyRepoState | None = None
        self._actions = {
            EmptyRepoState.NO_REMOTE: self._connect_remote,
            EmptyRepoState.NEEDS_FETCH: self._fetch,
            EmptyRepoState.REMOTE_HAS_HISTORY: self._attach,
        }
        banner.action_requested.connect(self._on_action)

    def refresh(self):
        self._state = self._advisor.state(self._fetched)
        if self._state is None:
            self._banner.hide_banner()
            return
        self._banner.show_state(self._state, self._advisor.remote_name(),
                                self._advisor.remote_branch())

    def _on_action(self):
        action = self._actions.get(self._state)
        if action:
            action()

    def _connect_remote(self):
        RemotesDialog(self._repo, parent=self._dialog_parent).exec()
        self.refresh()

    def _fetch(self):
        if RemoteDialog(self._repo, mode="fetch", parent=self._dialog_parent).exec():
            self._fetched = True
            self.status_message.emit(t("status.fetch_done"))
            self.changed.emit()

    def _attach(self):
        ref = self._advisor.remote_branch()
        branch = ref.split("/", 1)[1]
        ret = QMessageBox.question(
            self._dialog_parent, t("empty_repo.attach.title"),
            t("empty_repo.attach.confirm", branch=branch, ref=ref),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        worker = GitWorker(RemoteHistoryAttacher(self._repo).attach, ref)
        worker.signals.result.connect(lambda _: self._on_attached(ref))
        worker.signals.error.connect(self.error_occurred)
        QThreadPool.globalInstance().start(worker)

    def _on_attached(self, ref: str):
        self.status_message.emit(t("empty_repo.attach.done", ref=ref))
        self.changed.emit()
