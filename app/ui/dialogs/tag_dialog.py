from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import QThreadPool

from app.git.repo import GitRepo
from app.workers.git_worker import GitWorker


class TagDialog(QDialog):
    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self.setWindowTitle("Create Tag")
        self.setMinimumWidth(360)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("v1.0.0")
        form.addRow("Tag Name:", self._name_edit)

        self._ref_edit = QLineEdit("HEAD")
        form.addRow("From Ref:", self._ref_edit)

        self._message_edit = QLineEdit()
        self._message_edit.setPlaceholderText("(leave empty for lightweight tag)")
        form.addRow("Message:", self._message_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create Tag")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Tag name cannot be empty.")
            return
        ref = self._ref_edit.text().strip() or "HEAD"
        message = self._message_edit.text().strip()
        worker = GitWorker(self._repo.create_tag, name, ref, message)
        worker.signals.result.connect(lambda _: self.accept())
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_error(self, error: str):
        QMessageBox.critical(self, "Tag Error", error)
