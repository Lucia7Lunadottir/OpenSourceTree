from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QCheckBox,
    QDialogButtonBox, QMessageBox, QLabel
)
from PyQt6.QtCore import QThreadPool

from app.i18n import t
from app.git.repo import GitRepo
from app.workers.git_worker import GitWorker


class BranchDialog(QDialog):
    def __init__(self, repo: GitRepo, mode: str = "create", branch_name: str = "", parent=None):
        super().__init__(parent)
        self._repo = repo
        self._mode = mode
        self._branch_name = branch_name

        title_keys = {
            "create": "branch_dialog.title.create",
            "rename": "branch_dialog.title.rename",
            "delete": "branch_dialog.title.delete",
            "merge":  "branch_dialog.title.merge",
            "rebase": "branch_dialog.title.rebase",
        }
        self.setWindowTitle(t(title_keys.get(mode, "branch_dialog.title.create")))
        self.setMinimumWidth(380)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        if self._mode == "create":
            self._name_edit = QLineEdit()
            form.addRow(t("branch_dialog.name"), self._name_edit)
            self._from_edit = QLineEdit("HEAD")
            form.addRow(t("branch_dialog.from"), self._from_edit)
            self._checkout_check = QCheckBox(t("branch_dialog.checkout_after"))
            self._checkout_check.setChecked(True)
            layout.addLayout(form)
            layout.addWidget(self._checkout_check)

        elif self._mode == "rename":
            label = QLabel(t("branch_dialog.rename_label", name=self._branch_name))
            layout.addWidget(label)
            self._name_edit = QLineEdit(self._branch_name)
            form.addRow(t("branch_dialog.new_name"), self._name_edit)
            layout.addLayout(form)

        elif self._mode == "delete":
            label = QLabel(t("branch_dialog.delete_label", name=self._branch_name))
            layout.addWidget(label)
            self._force_check = QCheckBox(t("branch_dialog.force_delete"))
            layout.addWidget(self._force_check)

        elif self._mode in ("merge", "rebase"):
            branches = self._get_branch_names()
            self._branch_combo = QComboBox()
            self._branch_combo.addItems(branches)
            form.addRow(t("branch_dialog.branch"), self._branch_combo)
            layout.addLayout(form)
            if self._mode == "merge":
                self._no_ff_check = QCheckBox(t("branch_dialog.no_ff"))
                self._squash_check = QCheckBox(t("branch_dialog.squash"))
                layout.addWidget(self._no_ff_check)
                layout.addWidget(self._squash_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _get_branch_names(self) -> list[str]:
        try:
            return [b.name for b in self._repo.get_branches()]
        except Exception:
            return []

    def _on_accept(self):
        worker = None
        if self._mode == "create":
            name = self._name_edit.text().strip()
            if not name:
                QMessageBox.warning(self, t("branch_dialog.title.create"),
                                    t("branch_dialog.error.empty_name"))
                return
            from_ref = self._from_edit.text().strip() or "HEAD"
            checkout = self._checkout_check.isChecked()

            def do_create():
                if checkout:
                    self._repo.create_branch(name, from_ref)
                else:
                    self._repo.runner.run(["branch", name, from_ref])

            worker = GitWorker(do_create)

        elif self._mode == "rename":
            new_name = self._name_edit.text().strip()
            if not new_name:
                QMessageBox.warning(self, t("branch_dialog.title.rename"),
                                    t("branch_dialog.error.empty_name"))
                return
            worker = GitWorker(self._repo.rename_branch, self._branch_name, new_name)

        elif self._mode == "delete":
            force = self._force_check.isChecked()
            worker = GitWorker(self._repo.delete_branch, self._branch_name, force)

        elif self._mode == "merge":
            branch = self._branch_combo.currentText()
            no_ff  = self._no_ff_check.isChecked()
            squash = self._squash_check.isChecked()
            worker = GitWorker(self._repo.merge, branch, no_ff, squash)

        elif self._mode == "rebase":
            branch = self._branch_combo.currentText()
            worker = GitWorker(self._repo.rebase, branch)

        if worker:
            worker.signals.result.connect(lambda _: self.accept())
            worker.signals.error.connect(self._on_error)
            QThreadPool.globalInstance().start(worker)

    def _on_error(self, error: str):
        QMessageBox.critical(self, t("branch_dialog.error.git"), error)
