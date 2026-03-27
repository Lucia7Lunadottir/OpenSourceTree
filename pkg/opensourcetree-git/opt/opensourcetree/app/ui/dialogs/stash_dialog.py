from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QCheckBox, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import QThreadPool

from app.i18n import t
from app.git.repo import GitRepo
from app.workers.git_worker import GitWorker


class StashDialog(QDialog):
    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self.setWindowTitle(t("stash.title"))
        self.setMinimumWidth(360)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._message_edit = QLineEdit()
        self._message_edit.setPlaceholderText(t("stash.message_placeholder"))
        form.addRow(t("stash.message"), self._message_edit)
        layout.addLayout(form)

        self._untracked_check = QCheckBox(t("stash.include_untracked"))
        self._untracked_check.setChecked(True)
        layout.addWidget(self._untracked_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("stash.btn"))
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        message = self._message_edit.text().strip()
        include_untracked = self._untracked_check.isChecked()
        worker = GitWorker(self._repo.stash_save, message, include_untracked)
        worker.signals.result.connect(lambda _: self.accept())
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_error(self, error: str):
        QMessageBox.critical(self, t("stash.error"), error)
