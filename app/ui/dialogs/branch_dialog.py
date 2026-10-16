from dataclasses import dataclass
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QLineEdit, QComboBox, QCheckBox,
    QDialogButtonBox, QMessageBox, QLabel, QProgressBar, QFrame, QFormLayout
)
from PyQt6.QtCore import QThreadPool

from app.i18n import t
from app.git.repo import GitRepo
from app.ui.ui_translator import UiTranslator
from app.workers.git_worker import GitWorker

_UI_FILE = Path(__file__).with_name("branch_dialog.ui")


@dataclass(frozen=True)
class _ModeView:
    """What part of branch_dialog.ui a mode shows.

    rows    -- field objectNames of the form rows to show (the rest are hidden)
    widgets -- objectNames of the other widgets to show
    name_label_key -- i18n key for the label of the nameEdit row
    """
    title_key: str
    rows: tuple[str, ...] = ()
    widgets: tuple[str, ...] = ()
    name_label_key: str = "branch_dialog.name"

    @property
    def shows_current_branch(self) -> bool:
        return "infoFrame" in self.widgets


_MODES: dict[str, _ModeView] = {
    "create": _ModeView("branch_dialog.title.create",
                        rows=("nameEdit", "fromEdit"), widgets=("checkoutCheck",)),
    "rename": _ModeView("branch_dialog.title.rename",
                        rows=("nameEdit",), widgets=("renameLabel",),
                        name_label_key="branch_dialog.new_name"),
    "delete": _ModeView("branch_dialog.title.delete",
                        widgets=("deleteLabel", "forceCheck")),
    "merge":  _ModeView("branch_dialog.title.merge", rows=("branchCombo",),
                        widgets=("infoFrame", "mergeHintLabel", "noFfCheck", "squashCheck")),
    "rebase": _ModeView("branch_dialog.title.rebase", rows=("branchCombo",),
                        widgets=("infoFrame", "rebaseHintLabel")),
}
# an unknown mode keeps the old behaviour: "create" title, no mode widgets
_UNKNOWN_MODE = _ModeView("branch_dialog.title.create")

# every widget / form row that depends on the mode
_MODE_ROWS = ("nameEdit", "fromEdit", "branchCombo")
_MODE_WIDGETS = ("renameLabel", "deleteLabel", "infoFrame", "mergeHintLabel",
                 "rebaseHintLabel", "checkoutCheck", "forceCheck", "noFfCheck", "squashCheck")


class BranchDialog(QDialog):
    # widgets created by loadUi from branch_dialog.ui
    renameLabel: QLabel
    deleteLabel: QLabel
    infoFrame: QFrame
    currentBranchLabel: QLabel
    formLayout: QFormLayout
    nameLabel: QLabel
    nameEdit: QLineEdit
    fromEdit: QLineEdit
    branchCombo: QComboBox
    checkoutCheck: QCheckBox
    forceCheck: QCheckBox
    noFfCheck: QCheckBox
    squashCheck: QCheckBox
    progressBar: QProgressBar
    statusLabel: QLabel
    buttonBox: QDialogButtonBox

    def __init__(self, repo: GitRepo, mode: str = "create", branch_name: str = "", parent=None):
        super().__init__(parent)
        self._repo = repo
        self._mode = mode
        self._branch_name = branch_name
        view = _MODES.get(mode, _UNKNOWN_MODE)

        uic.loadUi(_UI_FILE, self)
        current = self._current_branch() if view.shows_current_branch else ""
        UiTranslator({
            "renameLabel": {"name": branch_name},
            "deleteLabel": {"name": branch_name},
            "currentBranchLabel": {"name": current},
        }).apply(self)

        self._apply_mode(view)
        self.progressBar.setVisible(False)
        self.statusLabel.setVisible(False)

        self._ok_btn = self.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        self.buttonBox.accepted.connect(self._on_accept)
        self.buttonBox.rejected.connect(self.reject)

    def _apply_mode(self, view: _ModeView):
        self.setWindowTitle(t(view.title_key))
        self.nameLabel.setText(t(view.name_label_key))
        for name in _MODE_ROWS:
            self.formLayout.setRowVisible(getattr(self, name), name in view.rows)
        for name in _MODE_WIDGETS:
            getattr(self, name).setVisible(name in view.widgets)

        if self._mode == "rename":
            self.nameEdit.setText(self._branch_name)
        if "branchCombo" in view.rows:
            self.branchCombo.addItems(self._get_branch_names())

    def _current_branch(self) -> str:
        try:
            return self._repo.get_head()
        except Exception:
            return "HEAD"

    def _get_branch_names(self) -> list[str]:
        try:
            return [b.name for b in self._repo.get_branches()]
        except Exception:
            return []

    def _set_running(self, running: bool, msg: str = ""):
        self._ok_btn.setEnabled(not running)
        self.progressBar.setVisible(running)
        if msg:
            self.statusLabel.setText(msg)
            self.statusLabel.setVisible(True)
        else:
            self.statusLabel.setVisible(False)

    def _on_accept(self):
        worker = None
        if self._mode == "create":
            name = self.nameEdit.text().strip()
            if not name:
                QMessageBox.warning(self, t("branch_dialog.title.create"),
                                    t("branch_dialog.error.empty_name"))
                return
            from_ref = self.fromEdit.text().strip() or "HEAD"
            checkout = self.checkoutCheck.isChecked()

            def do_create():
                if checkout:
                    self._repo.create_branch(name, from_ref)
                else:
                    self._repo.runner.run(["branch", name, from_ref])

            worker = GitWorker(do_create)
            self._set_running(True, t("branch_dialog.creating", name=name))

        elif self._mode == "rename":
            new_name = self.nameEdit.text().strip()
            if not new_name:
                QMessageBox.warning(self, t("branch_dialog.title.rename"),
                                    t("branch_dialog.error.empty_name"))
                return
            worker = GitWorker(self._repo.rename_branch, self._branch_name, new_name)
            self._set_running(True, t("branch_dialog.renaming",
                                      old=self._branch_name, new=new_name))

        elif self._mode == "delete":
            force = self.forceCheck.isChecked()
            worker = GitWorker(self._repo.delete_branch, self._branch_name, force)
            self._set_running(True, t("branch_dialog.deleting", name=self._branch_name))

        elif self._mode == "merge":
            branch = self.branchCombo.currentText()
            no_ff  = self.noFfCheck.isChecked()
            squash = self.squashCheck.isChecked()
            worker = GitWorker(self._repo.merge, branch, no_ff, squash)
            self._set_running(True, t("branch_dialog.merging", branch=branch))

        elif self._mode == "rebase":
            branch = self.branchCombo.currentText()
            worker = GitWorker(self._repo.rebase, branch)
            self._set_running(True, t("branch_dialog.rebasing", branch=branch))

        if worker:
            worker.signals.result.connect(lambda _: self.accept())
            worker.signals.error.connect(self._on_error)
            QThreadPool.globalInstance().start(worker)

    def _on_error(self, error: str):
        self._set_running(False)

        err_lower = error.lower()
        is_conflict = any(kw in err_lower for kw in ("conflict", "conflicts", "конфликт"))

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
