from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget,
    QWidget, QLineEdit, QComboBox, QCheckBox, QPushButton,
    QDialogButtonBox, QMessageBox, QLabel
)
from PyQt6.QtCore import Qt, QThreadPool

from app.git.repo import GitRepo
from app.workers.git_worker import GitWorker


class BranchDialog(QDialog):
    def __init__(self, repo: GitRepo, mode: str = "create", branch_name: str = "", parent=None):
        super().__init__(parent)
        self._repo = repo
        self._mode = mode
        self._branch_name = branch_name
        titles = {
            "create": "Create Branch",
            "rename": "Rename Branch",
            "delete": "Delete Branch",
            "merge": "Merge Branch",
            "rebase": "Rebase",
        }
        self.setWindowTitle(titles.get(mode, "Branch"))
        self.setMinimumWidth(360)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        if self._mode == "create":
            self._name_edit = QLineEdit()
            form.addRow("Branch Name:", self._name_edit)
            self._from_edit = QLineEdit("HEAD")
            form.addRow("From:", self._from_edit)
            self._checkout_check = QCheckBox("Checkout after create")
            self._checkout_check.setChecked(True)
            layout.addLayout(form)
            layout.addWidget(self._checkout_check)

        elif self._mode == "rename":
            self._old_label = QLabel(f"Rename: {self._branch_name}")
            layout.addWidget(self._old_label)
            self._name_edit = QLineEdit(self._branch_name)
            form.addRow("New Name:", self._name_edit)
            layout.addLayout(form)

        elif self._mode == "delete":
            label = QLabel(f"Delete branch '{self._branch_name}'?")
            layout.addWidget(label)
            self._force_check = QCheckBox("Force delete (even if not merged)")
            layout.addWidget(self._force_check)

        elif self._mode in ("merge", "rebase"):
            branches = self._get_branch_names()
            self._branch_combo = QComboBox()
            self._branch_combo.addItems(branches)
            form.addRow("Branch:", self._branch_combo)
            layout.addLayout(form)
            if self._mode == "merge":
                self._no_ff_check = QCheckBox("No fast-forward (--no-ff)")
                self._squash_check = QCheckBox("Squash commits")
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
            branches = self._repo.get_branches()
            return [b.name for b in branches]
        except Exception:
            return []

    def _on_accept(self):
        worker = None
        if self._mode == "create":
            name = self._name_edit.text().strip()
            if not name:
                QMessageBox.warning(self, "Error", "Branch name cannot be empty.")
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
                QMessageBox.warning(self, "Error", "Branch name cannot be empty.")
                return
            worker = GitWorker(self._repo.rename_branch, self._branch_name, new_name)

        elif self._mode == "delete":
            force = self._force_check.isChecked()
            worker = GitWorker(self._repo.delete_branch, self._branch_name, force)

        elif self._mode == "merge":
            branch = self._branch_combo.currentText()
            no_ff = self._no_ff_check.isChecked()
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
        QMessageBox.critical(self, "Git Error", error)
