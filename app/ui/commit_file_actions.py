import posixpath

from PyQt6.QtCore import QObject, QPoint, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import QListWidget, QMenu, QMessageBox, QWidget

from app.i18n import t
from app.git.repo import GitRepo
from app.git.models import FileStatusEntry
from app.workers.git_worker import GitWorker
from app.ui.extract_runner import ExtractRunner


class CommitFileActions(QObject):
    """Right-click menu of the changed-files list of a commit:
    extract files, extract whole folders, drop files from the commit."""
    status_message = pyqtSignal(str)
    history_rewritten = pyqtSignal()

    def __init__(self, repo: GitRepo, files_list: QListWidget, parent: QWidget):
        super().__init__(parent)
        self._repo = repo
        self._list = files_list
        self._parent = parent
        self._sha = ""
        self._runner = ExtractRunner(repo, parent)
        self._runner.finished.connect(self.status_message)
        self._runner.failed.connect(self._show_error)

    def set_commit(self, sha: str):
        self._sha = sha

    def show_menu(self, pos: QPoint):
        if not self._sha:
            return
        entries: list[FileStatusEntry] = [
            i.data(0x0100) for i in self._list.selectedItems() if i.data(0x0100)]
        if not entries:
            return
        present = [e for e in entries if e.status != "D"]   # deleted files aren't in the snapshot
        folders = sorted({posixpath.dirname(e.path) for e in present if posixpath.dirname(e.path)})

        menu = QMenu(self._list)
        extract_act = menu.addAction(t("extract.menu_files", n=len(present)))
        extract_act.setEnabled(bool(present))
        folder_acts = {}
        if folders:
            sub = menu.addMenu(t("extract.menu_folder"))
            for folder in folders:
                folder_acts[sub.addAction(folder)] = folder
        browse_act = menu.addAction(t("extract.menu_browse"))
        menu.addSeparator()
        discard_act = menu.addAction(t("discard_commit.menu", n=len(entries)))

        action = menu.exec(self._list.viewport().mapToGlobal(pos))
        if action is None:
            return
        if action == extract_act:
            self._runner.extract(self._sha, [e.path for e in present])
        elif action in folder_acts:
            self._runner.extract(self._sha, [folder_acts[action]])
        elif action == browse_act:
            from app.ui.dialogs.commit_tree_dialog import CommitTreeDialog
            CommitTreeDialog(self._repo, self._sha, parent=self._parent).exec()
        elif action == discard_act:
            self._discard(entries)

    def _discard(self, entries: list[FileStatusEntry]):
        paths: list[str] = []
        for e in entries:
            paths.append(e.path)
            if e.old_path:           # a rename touches both names
                paths.append(e.old_path)
        try:
            pushed = self._repo.is_commit_pushed(self._sha)
        except Exception:
            pushed = False
        names = "\n".join(f"  • {p}" for p in paths[:10])
        if len(paths) > 10:
            names += f"\n  … (+{len(paths) - 10})"
        text = t("discard_commit.confirm", sha=self._sha[:8], names=names)
        if pushed:
            text += "\n\n" + t("discard_commit.pushed_warning")
        ret = QMessageBox.warning(
            self._parent, t("discard_commit.title"), text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if ret != QMessageBox.StandardButton.Yes:
            return
        worker = GitWorker(self._repo.discard_files_from_commit, self._sha, paths)
        worker.signals.result.connect(self._on_discarded)
        worker.signals.error.connect(self._show_error)
        QThreadPool.globalInstance().start(worker)

    def _on_discarded(self, outcome: str):
        key = "discard_commit.done_dropped" if outcome == "dropped" else "discard_commit.done"
        self.status_message.emit(t(key))
        self.history_rewritten.emit()

    def _show_error(self, error: str):
        self.status_message.emit("Error: " + (error.strip().splitlines() or [""])[-1])
        QMessageBox.critical(self._parent, "Git Error", error)
        self.history_rewritten.emit()
