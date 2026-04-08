from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QCheckBox,
    QDialogButtonBox, QMessageBox, QLabel, QProgressBar, QFrame
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
        self.setMinimumWidth(420)
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
            # Info frame: current branch + hint about what will happen
            try:
                current = self._repo.get_head()
            except Exception:
                current = "HEAD"

            info_frame = QFrame()
            info_frame.setStyleSheet(
                "background: rgba(100,100,180,20); border: 1px solid rgba(100,100,180,60);"
                "border-radius: 4px; padding: 4px;"
            )
            info_layout = QVBoxLayout(info_frame)
            info_layout.setContentsMargins(8, 6, 8, 6)
            info_layout.setSpacing(2)
            info_layout.addWidget(QLabel(t("branch_dialog.current_branch", name=current)))

            hint_key = "branch_dialog.merge_hint" if self._mode == "merge" else "branch_dialog.rebase_hint"
            hint = QLabel(t(hint_key))
            hint.setStyleSheet("color: #9cdcfe; font-size: 11px;")
            hint.setWordWrap(True)
            info_layout.addWidget(hint)
            layout.addWidget(info_frame)

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

        # Progress bar (hidden until operation starts)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate
        self._progress.setFixedHeight(14)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # Status label
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #9cdcfe; font-size: 11px;")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _get_branch_names(self) -> list[str]:
        try:
            return [b.name for b in self._repo.get_branches()]
        except Exception:
            return []

    def _set_running(self, running: bool, msg: str = ""):
        self._ok_btn.setEnabled(not running)
        self._progress.setVisible(running)
        if msg:
            self._status_label.setText(msg)
            self._status_label.setVisible(True)
        else:
            self._status_label.setVisible(False)

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
            self._set_running(True, t("branch_dialog.creating", name=name))

        elif self._mode == "rename":
            new_name = self._name_edit.text().strip()
            if not new_name:
                QMessageBox.warning(self, t("branch_dialog.title.rename"),
                                    t("branch_dialog.error.empty_name"))
                return
            worker = GitWorker(self._repo.rename_branch, self._branch_name, new_name)
            self._set_running(True, t("branch_dialog.renaming",
                                      old=self._branch_name, new=new_name))

        elif self._mode == "delete":
            force = self._force_check.isChecked()
            worker = GitWorker(self._repo.delete_branch, self._branch_name, force)
            self._set_running(True, t("branch_dialog.deleting", name=self._branch_name))

        elif self._mode == "merge":
            branch = self._branch_combo.currentText()
            no_ff  = self._no_ff_check.isChecked()
            squash = self._squash_check.isChecked()
            worker = GitWorker(self._repo.merge, branch, no_ff, squash)
            self._set_running(True, t("branch_dialog.merging", branch=branch))

        elif self._mode == "rebase":
            branch = self._branch_combo.currentText()
            worker = GitWorker(self._repo.rebase, branch)
            self._set_running(True, t("branch_dialog.rebasing", branch=branch))

        if worker:
            worker.signals.result.connect(lambda _: self.accept())
            worker.signals.error.connect(self._on_error)
            QThreadPool.globalInstance().start(worker)

    def _on_error(self, error: str):
        self._set_running(False)

        err_lower = error.lower()
        is_conflict = "conflict" in err_lower or "conflicts" in err_lower

        if is_conflict and self._mode == "merge":
            QMessageBox.warning(
                self,
                t("branch_dialog.conflict.merge_title"),
                t("branch_dialog.conflict.merge_text"),
            )
        elif is_conflict and self._mode == "rebase":
            QMessageBox.warning(
                self,
                t("branch_dialog.conflict.rebase_title"),
                t("branch_dialog.conflict.rebase_text"),
            )
        else:
            QMessageBox.critical(self, t("branch_dialog.error.git"), error)

        # Close the dialog so repo_tab refreshes and shows the current conflict state
        self.reject()
