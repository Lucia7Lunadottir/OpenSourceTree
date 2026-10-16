from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QLineEdit, QCheckBox, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import QThreadPool

from app.i18n import t
from app.git.repo import GitRepo
from app.ui.ui_translator import UiTranslator
from app.workers.git_worker import GitWorker

_UI_FILE = Path(__file__).with_name("stash_dialog.ui")


class StashDialog(QDialog):
    # widgets created by loadUi from stash_dialog.ui
    messageEdit: QLineEdit
    untrackedCheck: QCheckBox
    buttonBox: QDialogButtonBox

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)

        # a standard button's text can't be set in Designer
        self.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setText(t("stash.btn"))
        self.buttonBox.accepted.connect(self._on_accept)
        self.buttonBox.rejected.connect(self.reject)

    def _on_accept(self):
        message = self.messageEdit.text().strip()
        include_untracked = self.untrackedCheck.isChecked()
        worker = GitWorker(self._repo.stash_save, message, include_untracked)
        worker.signals.result.connect(lambda _: self.accept())
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_error(self, error: str):
        QMessageBox.critical(self, t("stash.error"), error)
