from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QListWidget, QListWidgetItem, QLabel, QPushButton,
    QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QColor

from app.i18n import t
from app.git.repo import GitRepo
from app.ui.ui_translator import UiTranslator
from app.workers.git_worker import GitWorker

_UI_FILE = Path(__file__).with_name("coauthor_history_dialog.ui")


class CoAuthorHistoryDialog(QDialog):
    """Find Co-authored-by trailers across the current branch's history and
    strip selected ones via a scripted interactive rebase (GitRepo.reword_
    strip_co_authors). Read-only until "Remove selected" is pressed and
    confirmed -- opening this dialog never touches the repo."""

    # widgets created by loadUi from coauthor_history_dialog.ui
    infoLabel: QLabel
    commitList: QListWidget
    selectAllButton: QPushButton
    selectNoneButton: QPushButton
    warningLabel: QLabel
    primaryButton: QPushButton   # "Remove selected"; objectName is a style.qss selector
    buttonBox: QDialogButtonBox

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._found: list[tuple[str, str, list[tuple[str, str]]]] = []
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)
        # Designer can't put a custom button inside a QDialogButtonBox:
        # the .ui lays it out next to the box, here it moves into it.
        self.buttonBox.addButton(self.primaryButton, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttonBox.rejected.connect(self.reject)
        self.primaryButton.clicked.connect(self._on_remove_selected)
        self.selectAllButton.clicked.connect(lambda: self._set_all_checked(True))
        self.selectNoneButton.clicked.connect(lambda: self._set_all_checked(False))
        self._load()

    # ------------------------------------------------------------------ Load

    def _load(self):
        worker = GitWorker(self._repo.find_commits_with_co_authors)
        worker.signals.result.connect(self._on_loaded)
        worker.signals.error.connect(self._on_load_error)
        QThreadPool.globalInstance().start(worker)

    def _on_load_error(self, error: str):
        self.infoLabel.setText(t("coauthor_history.load_error", error=error))

    def _on_loaded(self, found: list[tuple[str, str, list[tuple[str, str]]]]):
        self._found = found
        if not found:
            self.infoLabel.setText(t("coauthor_history.none_found"))
            return
        self.infoLabel.setText(t("coauthor_history.found_count", n=len(found)))

        pushed_count = 0
        for sha, subject, co_authors in found:
            names = ", ".join(f"{n} <{e}>" for n, e in co_authors)
            item = QListWidgetItem(f"{sha[:8]}  {subject}\n    {names}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, sha)

            try:
                remotes = self._repo.remote_branches_containing(sha)
            except Exception:
                remotes = []
            if remotes:
                pushed_count += 1
                item.setForeground(QColor(230, 170, 90))
                item.setToolTip(t("coauthor_history.already_pushed", remotes=", ".join(remotes)))

            self.commitList.addItem(item)

        self.primaryButton.setEnabled(True)
        if pushed_count:
            self.warningLabel.setText(t("coauthor_history.push_warning", n=pushed_count))

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.commitList.count()):
            self.commitList.item(i).setCheckState(state)

    # ---------------------------------------------------------------- Rewrite

    def _on_remove_selected(self):
        selected_shas = [
            self.commitList.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.commitList.count())
            if self.commitList.item(i).checkState() == Qt.CheckState.Checked
        ]
        if not selected_shas:
            return

        ret = QMessageBox.question(
            self, t("coauthor_history.title"),
            t("coauthor_history.confirm_text", n=len(selected_shas)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        self.primaryButton.setEnabled(False)
        worker = GitWorker(self._repo.reword_strip_co_authors, selected_shas)
        worker.signals.result.connect(self._on_rewrite_done)
        worker.signals.error.connect(self._on_rewrite_error)
        QThreadPool.globalInstance().start(worker)

    def _on_rewrite_done(self, backup_ref: str):
        QMessageBox.information(
            self, t("coauthor_history.title"),
            t("coauthor_history.done", backup=backup_ref),
        )
        self.accept()

    def _on_rewrite_error(self, error: str):
        self.primaryButton.setEnabled(True)
        QMessageBox.critical(self, t("coauthor_history.title"), error)
