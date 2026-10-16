from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QWidget, QLabel, QAbstractButton, QTreeWidget, QTreeWidgetItem,
    QPushButton, QMessageBox,
)
from PyQt6.QtCore import Qt

from app.i18n import t
from app.git.repo import GitRepo
from app.ui.extract_runner import ExtractRunner
from app.ui.ui_translator import UiTranslator

_PATH_ROLE = Qt.ItemDataRole.UserRole
_UI_FILE = Path(__file__).with_name("commit_tree_dialog.ui")


class CommitTreeDialog(QDialog):
    """Whole snapshot of a commit as a checkable tree; extract files or whole folders."""

    # widgets created by loadUi from commit_tree_dialog.ui
    tree: QTreeWidget
    statusLabel: QLabel
    extractButton: QPushButton
    closeButton: QPushButton

    def __init__(self, repo: GitRepo, sha: str, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._sha = sha
        uic.loadUi(_UI_FILE, self)
        UiTranslator({self.objectName(): {"sha": sha[:8]}}).apply(self)

        self._runner = ExtractRunner(repo, self)
        self._runner.finished.connect(self._on_done)
        self._runner.failed.connect(self._on_failed)
        self.extractButton.clicked.connect(self._on_extract)
        self.closeButton.clicked.connect(self.accept)

        self._populate()

    def _populate(self):
        try:
            files = self._repo.list_commit_tree(self._sha)
        except Exception as e:
            self.statusLabel.setText(str(e))
            self.extractButton.setEnabled(False)
            return
        dirs: dict[str, QTreeWidgetItem] = {}
        flags = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                 | Qt.ItemFlag.ItemIsAutoTristate)
        self.tree.setUpdatesEnabled(False)
        for path in files:
            parent_item = self.tree.invisibleRootItem()
            built = ""
            *folders, name = path.split("/")
            for folder in folders:
                built = f"{built}/{folder}" if built else folder
                node = dirs.get(built)
                if node is None:
                    node = QTreeWidgetItem(parent_item, [folder])
                    node.setFlags(flags)
                    node.setCheckState(0, Qt.CheckState.Unchecked)
                    dirs[built] = node
                parent_item = node
            leaf = QTreeWidgetItem(parent_item, [name])
            leaf.setFlags(flags & ~Qt.ItemFlag.ItemIsAutoTristate)
            leaf.setCheckState(0, Qt.CheckState.Unchecked)
            leaf.setData(0, _PATH_ROLE, path)
        self.tree.setUpdatesEnabled(True)
        self.statusLabel.setText(t("extract.tree_count", n=len(files)))

    def _checked_files(self) -> list[str]:
        out: list[str] = []
        stack = [self.tree.invisibleRootItem()]
        while stack:
            item = stack.pop()
            for i in range(item.childCount()):
                child = item.child(i)
                path = child.data(0, _PATH_ROLE)
                if path is not None:
                    if child.checkState(0) == Qt.CheckState.Checked:
                        out.append(path)
                else:
                    stack.append(child)
        return out

    def _on_extract(self):
        paths = self._checked_files()
        if not paths:
            QMessageBox.information(self, self.windowTitle(), t("extract.nothing_selected"))
            return
        self._runner.extract(self._sha, paths)

    def _on_done(self, message: str):
        self.statusLabel.setText(message)

    def _on_failed(self, error: str):
        QMessageBox.critical(self, "Git Error", error)
