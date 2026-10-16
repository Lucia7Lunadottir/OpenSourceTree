from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QMessageBox,
)
from PyQt6.QtCore import Qt

from app.i18n import t
from app.git.repo import GitRepo
from app.ui.extract_runner import ExtractRunner

_PATH_ROLE = Qt.ItemDataRole.UserRole


class CommitTreeDialog(QDialog):
    """Whole snapshot of a commit as a checkable tree; extract files or whole folders."""

    def __init__(self, repo: GitRepo, sha: str, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._sha = sha
        self._runner = ExtractRunner(repo, self)
        self._runner.finished.connect(self._on_done)
        self._runner.failed.connect(self._on_failed)
        self.setWindowTitle(t("extract.tree_title", sha=sha[:8]))
        self.resize(560, 640)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(t("extract.tree_hint")))
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        layout.addWidget(self._tree, 1)
        self._status = QLabel("")
        layout.addWidget(self._status)

        row = QHBoxLayout()
        row.addStretch(1)
        self._extract_btn = QPushButton(t("extract.btn_extract"))
        close_btn = QPushButton(t("extract.btn_close"))
        row.addWidget(self._extract_btn)
        row.addWidget(close_btn)
        layout.addLayout(row)
        self._extract_btn.clicked.connect(self._on_extract)
        close_btn.clicked.connect(self.accept)

        self._populate()

    def _populate(self):
        try:
            files = self._repo.list_commit_tree(self._sha)
        except Exception as e:
            self._status.setText(str(e))
            self._extract_btn.setEnabled(False)
            return
        dirs: dict[str, QTreeWidgetItem] = {}
        flags = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                 | Qt.ItemFlag.ItemIsAutoTristate)
        self._tree.setUpdatesEnabled(False)
        for path in files:
            parent_item = self._tree.invisibleRootItem()
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
        self._tree.setUpdatesEnabled(True)
        self._status.setText(t("extract.tree_count", n=len(files)))

    def _checked_files(self) -> list[str]:
        out: list[str] = []
        stack = [self._tree.invisibleRootItem()]
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
        self._status.setText(message)

    def _on_failed(self, error: str):
        QMessageBox.critical(self, "Git Error", error)
