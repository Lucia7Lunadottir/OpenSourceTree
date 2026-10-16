import os
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QLineEdit, QPushButton, QFileDialog, QLabel,
    QDialogButtonBox, QProgressBar, QMessageBox
)
from PyQt6.QtCore import QThreadPool

from app.i18n import t
from app.ui.ui_translator import UiTranslator
from app.workers.git_worker import GitWorker
from app.git.runner import GitRunner

_UI_FILE = Path(__file__).with_name("clone_dialog.ui")


class CloneDialog(QDialog):
    # widgets created by loadUi from clone_dialog.ui
    urlEdit: QLineEdit
    destEdit: QLineEdit
    browseButton: QPushButton
    nameEdit: QLineEdit
    progressBar: QProgressBar
    statusLabel: QLabel
    buttonBox: QDialogButtonBox

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result_path = None
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)

        self.destEdit.setPlaceholderText(os.path.expanduser("~/"))
        self.progressBar.setVisible(False)
        # a standard button's text can't be set in Designer
        self._ok_btn = self.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText(t("clone.btn"))

        self.browseButton.clicked.connect(self._browse_dest)
        self.buttonBox.accepted.connect(self._on_clone)
        self.buttonBox.rejected.connect(self.reject)
        self.urlEdit.textChanged.connect(self._on_url_changed)

    def _browse_dest(self):
        path = QFileDialog.getExistingDirectory(
            self, t("clone.select_dest"), os.path.expanduser("~")
        )
        if path:
            self.destEdit.setText(path)

    def _on_url_changed(self, url: str):
        if url:
            basename = url.rstrip("/").split("/")[-1]
            if basename.endswith(".git"):
                basename = basename[:-4]
            self.nameEdit.setPlaceholderText(basename)

    def _on_clone(self):
        url = self.urlEdit.text().strip()
        if not url:
            QMessageBox.warning(self, t("clone.title"), t("clone.error.no_url"))
            return

        if url.startswith("/") or url.startswith("./") or url.startswith("~"):
            QMessageBox.warning(
                self, t("clone.title"),
                t("clone.error.local_path_as_url")
            )
            return

        dest = self.destEdit.text().strip() or os.path.expanduser("~")
        name = self.nameEdit.text().strip() or self.nameEdit.placeholderText()
        target_path = os.path.join(dest, name)

        self._ok_btn.setEnabled(False)
        self.progressBar.setVisible(True)
        self.statusLabel.setText(t("clone.cloning"))

        _is_ssh = url.startswith("git@") or url.startswith("ssh://")

        def do_clone():
            runner = GitRunner(dest)
            if _is_ssh:
                runner.run_in_terminal(["clone", url, target_path])
                if not os.path.isdir(os.path.join(target_path, ".git")):
                    raise RuntimeError(t("clone.error.ssh_failed"))
            else:
                runner.run(["clone", url, target_path])
            return target_path

        worker = GitWorker(do_clone)
        worker.signals.result.connect(self._on_clone_done)
        worker.signals.error.connect(self._on_clone_error)
        QThreadPool.globalInstance().start(worker)

    def _on_clone_done(self, path: str):
        self._result_path = path
        self.progressBar.setVisible(False)
        self.statusLabel.setText(t("clone.done", path=path))
        self.accept()

    def _on_clone_error(self, error: str):
        self.progressBar.setVisible(False)
        self._ok_btn.setEnabled(True)
        lines = [l for l in error.splitlines() if l.strip()]
        self.statusLabel.setText(lines[-1] if lines else t("clone.error.title"))
        QMessageBox.critical(self, t("clone.error.title"), error)

    def result_path(self) -> str | None:
        return self._result_path
