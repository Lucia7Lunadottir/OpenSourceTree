import os
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QLineEdit, QPushButton, QFileDialog, QDialogButtonBox, QMessageBox
)

from app.i18n import t
from app.git.repo import GitRepo
from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("init_dialog.ui")


class InitDialog(QDialog):
    """Turns a folder into a git repository: first branch name and, optionally,
    the remote it will be pushed to (added as `origin`, nothing is downloaded)."""

    # widgets created by loadUi from init_dialog.ui
    folderEdit: QLineEdit
    browseButton: QPushButton
    branchEdit: QLineEdit
    remoteEdit: QLineEdit
    buttonBox: QDialogButtonBox

    def __init__(self, folder: str = "", parent=None):
        super().__init__(parent)
        self._result_path = None
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)
        self.folderEdit.setText(folder)
        # a standard button's text can't be set in Designer
        self.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setText(t("init.btn"))
        self.browseButton.clicked.connect(self._browse)
        self.buttonBox.accepted.connect(self._on_init)
        self.buttonBox.rejected.connect(self.reject)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(
            self, t("init.select_folder"), self.folderEdit.text() or os.path.expanduser("~"))
        if path:
            self.folderEdit.setText(path)

    def _on_init(self):
        folder = self.folderEdit.text().strip()
        branch = self.branchEdit.text().strip() or "main"
        url = self.remoteEdit.text().strip()
        if not os.path.isdir(folder):
            QMessageBox.warning(self, t("init.title"), t("init.error.no_folder"))
            return
        try:
            repo = GitRepo.init(folder, branch)
            if url:
                repo.add_remote("origin", url)
        except Exception as e:
            QMessageBox.critical(self, t("init.title"), str(e))
            return
        self._result_path = repo.path
        self.accept()

    def result_path(self) -> str | None:
        return self._result_path
