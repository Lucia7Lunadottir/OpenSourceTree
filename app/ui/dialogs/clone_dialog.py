import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QFileDialog, QLabel,
    QDialogButtonBox, QProgressBar, QMessageBox
)
from PyQt6.QtCore import QThreadPool

from app.i18n import t
from app.workers.git_worker import GitWorker
from app.git.runner import GitRunner


class CloneDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("clone.title"))
        self.setMinimumWidth(480)
        self._result_path = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://github.com/user/repo.git")
        form.addRow(t("clone.url"), self._url_edit)

        dest_row = QHBoxLayout()
        self._dest_edit = QLineEdit()
        self._dest_edit.setPlaceholderText(os.path.expanduser("~/"))
        browse_btn = QPushButton(t("clone.browse"))
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_dest)
        dest_row.addWidget(self._dest_edit)
        dest_row.addWidget(browse_btn)
        form.addRow(t("clone.dest"), dest_row)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(t("clone.name_placeholder"))
        form.addRow(t("clone.name"), self._name_edit)

        layout.addLayout(form)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: rgb(140,120,180);")
        layout.addWidget(self._status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText(t("clone.btn"))
        buttons.accepted.connect(self._on_clone)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._url_edit.textChanged.connect(self._on_url_changed)

    def _browse_dest(self):
        path = QFileDialog.getExistingDirectory(
            self, t("clone.select_dest"), os.path.expanduser("~")
        )
        if path:
            self._dest_edit.setText(path)

    def _on_url_changed(self, url: str):
        if url:
            basename = url.rstrip("/").split("/")[-1]
            if basename.endswith(".git"):
                basename = basename[:-4]
            self._name_edit.setPlaceholderText(basename)

    def _on_clone(self):
        url = self._url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, t("clone.title"), t("clone.error.no_url"))
            return

        dest = self._dest_edit.text().strip() or os.path.expanduser("~")
        name = self._name_edit.text().strip() or self._name_edit.placeholderText()
        target_path = os.path.join(dest, name)

        self._ok_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._status_label.setText(t("clone.cloning"))

        def do_clone():
            runner = GitRunner(dest)
            runner.run(["clone", url, target_path], timeout=300)
            return target_path

        worker = GitWorker(do_clone)
        worker.signals.result.connect(self._on_clone_done)
        worker.signals.error.connect(self._on_clone_error)
        QThreadPool.globalInstance().start(worker)

    def _on_clone_done(self, path: str):
        self._result_path = path
        self._progress.setVisible(False)
        self._status_label.setText(t("clone.done", path=path))
        self.accept()

    def _on_clone_error(self, error: str):
        self._progress.setVisible(False)
        self._ok_btn.setEnabled(True)
        lines = [l for l in error.splitlines() if l.strip()]
        self._status_label.setText(lines[-1] if lines else t("clone.error.title"))
        QMessageBox.critical(self, t("clone.error.title"), error)

    def result_path(self) -> str | None:
        return self._result_path
