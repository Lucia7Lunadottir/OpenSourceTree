from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QCheckBox,
    QDialogButtonBox, QMessageBox, QLabel
)
from PyQt6.QtCore import QThreadPool

from app.i18n import t
from app.git.repo import GitRepo
from app.workers.git_worker import GitWorker


class TagDialog(QDialog):
    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self.setWindowTitle(t("tag.title"))
        self.setMinimumWidth(360)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("v1.0.0")
        form.addRow(t("tag.name"), self._name_edit)

        self._ref_edit = QLineEdit("HEAD")
        form.addRow(t("tag.from_ref"), self._ref_edit)

        self._message_edit = QLineEdit()
        self._message_edit.setPlaceholderText(t("tag.message_placeholder"))
        form.addRow(t("tag.message"), self._message_edit)

        layout.addLayout(form)

        self._push_check = QCheckBox(t("tag.push_after"))
        self._push_check.setChecked(True)
        layout.addWidget(self._push_check)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        layout.addWidget(self._status_label)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("tag.btn"))
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _set_busy(self, text: str):
        self._status_label.setText(text)
        self._buttons.setEnabled(False)

    def _on_accept(self):
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, t("tag.title"), t("tag.error.empty_name"))
            return
        ref     = self._ref_edit.text().strip() or "HEAD"
        message = self._message_edit.text().strip()
        push    = self._push_check.isChecked()

        self._set_busy(t("tag.creating"))
        worker = GitWorker(self._repo.create_tag, name, ref, message)
        worker.signals.result.connect(lambda _: self._after_create(name, push))
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _after_create(self, name: str, push: bool):
        if push:
            self._set_busy(t("tag.pushing"))
            worker = GitWorker(self._repo.push_tag, name)
            worker.signals.result.connect(lambda _: self.accept())
            worker.signals.error.connect(self._on_push_error)
            QThreadPool.globalInstance().start(worker)
        else:
            self.accept()

    def _on_error(self, error: str):
        QMessageBox.critical(self, t("tag.error"), error)

    def _on_push_error(self, error: str):
        # Tag was created locally — warn about push failure but still close
        QMessageBox.warning(
            self, t("tag.push_error"),
            t("tag.push_error_msg", error=error)
        )
        self.accept()
