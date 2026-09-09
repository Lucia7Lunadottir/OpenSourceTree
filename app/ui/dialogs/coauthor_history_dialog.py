from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QDialogButtonBox, QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QColor

from app.i18n import t
from app.git.repo import GitRepo
from app.workers.git_worker import GitWorker


class CoAuthorHistoryDialog(QDialog):
    """Find Co-authored-by trailers across the current branch's history and
    strip selected ones via a scripted interactive rebase (GitRepo.reword_
    strip_co_authors). Read-only until "Remove selected" is pressed and
    confirmed -- opening this dialog never touches the repo."""

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._found: list[tuple[str, str, list[tuple[str, str]]]] = []
        self.setWindowTitle(t("coauthor_history.title"))
        self.setMinimumSize(600, 420)
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self._info_label = QLabel(t("coauthor_history.loading"))
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self._list)

        select_row = QHBoxLayout()
        self._select_all_btn = QPushButton(t("coauthor_history.select_all"))
        self._select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self._select_none_btn = QPushButton(t("coauthor_history.select_none"))
        self._select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        select_row.addWidget(self._select_all_btn)
        select_row.addWidget(self._select_none_btn)
        select_row.addStretch()
        layout.addLayout(select_row)

        self._warning_label = QLabel("")
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet("color: rgb(230, 170, 90);")
        layout.addWidget(self._warning_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        self._remove_btn = QPushButton(t("coauthor_history.remove_selected"))
        self._remove_btn.setObjectName("primaryButton")
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self._on_remove_selected)
        buttons.addButton(self._remove_btn, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ Load

    def _load(self):
        worker = GitWorker(self._repo.find_commits_with_co_authors)
        worker.signals.result.connect(self._on_loaded)
        worker.signals.error.connect(self._on_load_error)
        QThreadPool.globalInstance().start(worker)

    def _on_load_error(self, error: str):
        self._info_label.setText(t("coauthor_history.load_error", error=error))

    def _on_loaded(self, found: list[tuple[str, str, list[tuple[str, str]]]]):
        self._found = found
        if not found:
            self._info_label.setText(t("coauthor_history.none_found"))
            return
        self._info_label.setText(t("coauthor_history.found_count", n=len(found)))

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

            self._list.addItem(item)

        self._remove_btn.setEnabled(True)
        if pushed_count:
            self._warning_label.setText(t("coauthor_history.push_warning", n=pushed_count))

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(state)

    # ---------------------------------------------------------------- Rewrite

    def _on_remove_selected(self):
        selected_shas = [
            self._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.CheckState.Checked
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

        self._remove_btn.setEnabled(False)
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
        self._remove_btn.setEnabled(True)
        QMessageBox.critical(self, t("coauthor_history.title"), error)
