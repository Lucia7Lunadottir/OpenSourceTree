import posixpath

from PyQt6.QtCore import QObject, QPoint, pyqtSignal
from PyQt6.QtWidgets import QListWidget, QMenu, QMessageBox, QWidget

from app.i18n import t
from app.git.repo import GitRepo
from app.git.models import FileStatusEntry
from app.ui.extract_runner import ExtractRunner


class CommitFileActions(QObject):
    """Right-click menu of the changed-files list of a commit:
    extract files and whole folders."""
    status_message = pyqtSignal(str)

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

    def _show_error(self, error: str):
        self.status_message.emit("Error: " + (error.strip().splitlines() or [""])[-1])
        QMessageBox.critical(self._parent, "Git Error", error)
