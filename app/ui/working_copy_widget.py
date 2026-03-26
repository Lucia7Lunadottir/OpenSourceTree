import os
import fnmatch as _fnmatch

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QLabel, QTextEdit,
    QPushButton, QCheckBox, QMenu, QMessageBox, QAbstractItemView,
    QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QThreadPool
from PyQt6.QtGui import QColor, QFont

from app.i18n import t
from app.git.repo import GitRepo
from app.git.models import FileStatusEntry
from app.constants import STATUS_COLORS
from app.workers.git_worker import GitWorker
from app.workers.batch_worker import BatchWorker

LFS_ICON = "⬡"


def _is_lfs(path: str, patterns: list[str]) -> bool:
    name = os.path.basename(path)
    for pat in patterns:
        if _fnmatch.fnmatch(name, pat):
            return True
        if _fnmatch.fnmatch(path, pat.replace("**", "*")):
            return True
    return False


STATUS_LABELS = {
    "M": "M",
    "A": "A",
    "D": "D",
    "R": "R",
    "C": "C",
    "?": "?",
    "U": "U",
    "T": "T",
}


class FileListWidget(QListWidget):
    file_selected = pyqtSignal(str, bool)  # path, staged

    def __init__(self, staged: bool, parent=None):
        super().__init__(parent)
        self._staged = staged
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(False)
        self.currentItemChanged.connect(self._on_item_changed)

    def set_files(self, entries: list[FileStatusEntry], lfs_patterns: list[str] = ()):
        self.clear()
        for entry in entries:
            status_char = entry.status
            label = STATUS_LABELS.get(status_char, status_char)
            lfs_mark = f" {LFS_ICON}" if lfs_patterns and _is_lfs(entry.path, lfs_patterns) else ""
            item = QListWidgetItem(f"{label}  {entry.path}{lfs_mark}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            color = STATUS_COLORS.get(
                next((s for s in STATUS_COLORS if s.value == status_char), None),
                QColor("#d4d4d4")
            )
            item.setForeground(color)
            if lfs_mark:
                item.setToolTip(f"Git LFS tracked: {entry.path}")
            self.addItem(item)

    def selected_entries(self) -> list[FileStatusEntry]:
        result = []
        for item in self.selectedItems():
            entry = item.data(Qt.ItemDataRole.UserRole)
            if entry:
                result.append(entry)
        return result

    def _on_item_changed(self, current, previous):
        if current:
            entry = current.data(Qt.ItemDataRole.UserRole)
            if entry:
                self.file_selected.emit(entry.path, self._staged)


class WorkingCopyWidget(QWidget):
    committed = pyqtSignal()
    file_selected = pyqtSignal(str, bool)  # path, staged
    status_message = pyqtSignal(str)

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._setup_ui()
        self._connect_signals()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Staged files
        staged_widget = QWidget()
        staged_layout = QVBoxLayout(staged_widget)
        staged_layout.setContentsMargins(4, 4, 4, 0)
        staged_layout.setSpacing(2)

        staged_header = QHBoxLayout()
        staged_label = QLabel(t("working_copy.staged"))
        staged_label.setStyleSheet("color: #4ec9b0; font-weight: bold;")
        self._unstage_all_btn = QPushButton(t("working_copy.unstage_all"))
        self._unstage_all_btn.setFixedHeight(22)
        staged_header.addWidget(staged_label)
        staged_header.addStretch()
        staged_header.addWidget(self._unstage_all_btn)
        staged_layout.addLayout(staged_header)

        self._staged_list = FileListWidget(staged=True)
        self._staged_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        staged_layout.addWidget(self._staged_list)

        # Unstaged files
        unstaged_widget = QWidget()
        unstaged_layout = QVBoxLayout(unstaged_widget)
        unstaged_layout.setContentsMargins(4, 4, 4, 0)
        unstaged_layout.setSpacing(2)

        unstaged_header = QHBoxLayout()
        unstaged_label = QLabel(t("working_copy.unstaged"))
        unstaged_label.setStyleSheet("color: #dcdcaa; font-weight: bold;")
        self._stage_all_btn = QPushButton(t("working_copy.stage_all"))
        self._stage_all_btn.setFixedHeight(22)
        unstaged_header.addWidget(unstaged_label)
        unstaged_header.addStretch()
        unstaged_header.addWidget(self._stage_all_btn)
        unstaged_layout.addLayout(unstaged_header)

        self._unstaged_list = FileListWidget(staged=False)
        self._unstaged_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        unstaged_layout.addWidget(self._unstaged_list)

        splitter.addWidget(staged_widget)
        splitter.addWidget(unstaged_widget)
        splitter.setSizes([200, 200])
        layout.addWidget(splitter)

        # Progress bar (shown during batch stage/unstage)
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(4, 2, 4, 0)
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(14)
        self._progress_bar.setTextVisible(False)
        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color: #9cdcfe; font-size: 11px;")
        progress_row.addWidget(self._progress_bar)
        progress_row.addWidget(self._progress_label)
        self._progress_bar.setVisible(False)
        self._progress_label.setVisible(False)
        layout.addLayout(progress_row)

        # Commit area
        commit_area = QWidget()
        commit_area.setObjectName("commitArea")
        commit_layout = QVBoxLayout(commit_area)
        commit_layout.setContentsMargins(4, 4, 4, 4)
        commit_layout.setSpacing(4)

        self._commit_edit = QTextEdit()
        self._commit_edit.setPlaceholderText(t("working_copy.commit_placeholder"))
        self._commit_edit.setFixedHeight(80)
        font = QFont("Monospace", 11)
        self._commit_edit.setFont(font)
        commit_layout.addWidget(self._commit_edit)

        btn_row = QHBoxLayout()
        self._amend_check = QCheckBox(t("working_copy.amend"))
        self._commit_btn = QPushButton(t("working_copy.commit_btn"))
        self._commit_btn.setObjectName("primaryButton")
        self._commit_btn.setFixedHeight(28)
        btn_row.addWidget(self._amend_check)
        btn_row.addStretch()
        btn_row.addWidget(self._commit_btn)
        commit_layout.addLayout(btn_row)

        layout.addWidget(commit_area)

    def _connect_signals(self):
        self._staged_list.file_selected.connect(self.file_selected)
        self._unstaged_list.file_selected.connect(self.file_selected)
        self._staged_list.customContextMenuRequested.connect(self._staged_context_menu)
        self._unstaged_list.customContextMenuRequested.connect(self._unstaged_context_menu)
        self._stage_all_btn.clicked.connect(self._on_stage_all)
        self._unstage_all_btn.clicked.connect(self._on_unstage_all)
        self._commit_btn.clicked.connect(self._on_commit)
        self._amend_check.toggled.connect(self._on_amend_toggled)

    def _on_amend_toggled(self, checked: bool):
        if checked:
            self._pre_amend_text = self._commit_edit.toPlainText()
            try:
                msg = self._repo.get_last_commit_message()
            except Exception:
                msg = ""
            self._commit_edit.setPlainText(msg)
            # Move cursor to end
            cursor = self._commit_edit.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._commit_edit.setTextCursor(cursor)
        else:
            self._commit_edit.setPlainText(
                getattr(self, "_pre_amend_text", "")
            )

    def refresh(self):
        try:
            staged, unstaged = self._repo.get_working_copy_status()
            lfs_patterns = self._repo.lfs_tracked_patterns()
            self._staged_list.set_files(staged, lfs_patterns)
            self._unstaged_list.set_files(unstaged, lfs_patterns)
        except Exception as e:
            self.status_message.emit(f"Error refreshing status: {e}")

    def _staged_context_menu(self, pos: QPoint):
        entries = self._staged_list.selected_entries()
        if not entries:
            return
        menu = QMenu(self)
        unstage_action = menu.addAction(t("working_copy.unstage"))
        action = menu.exec(self._staged_list.mapToGlobal(pos))
        if action == unstage_action:
            for entry in entries:
                self._run_op(self._repo.unstage_file, entry.path)

    def _unstaged_context_menu(self, pos: QPoint):
        entries = self._unstaged_list.selected_entries()
        if not entries:
            return
        menu = QMenu(self)
        stage_action = menu.addAction(t("working_copy.stage"))
        discard_action = menu.addAction(t("working_copy.discard"))
        action = menu.exec(self._unstaged_list.mapToGlobal(pos))
        if action == stage_action:
            for entry in entries:
                self._run_op(self._repo.stage_file, entry.path)
        elif action == discard_action:
            ret = QMessageBox.question(
                self,
                "Discard Changes",
                f"Discard changes to {entries[0].path}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret == QMessageBox.StandardButton.Yes:
                for entry in entries:
                    self._run_op(
                        lambda p: self._repo.runner.run(["checkout", "--", p]),
                        entry.path,
                    )

    def _on_stage_all(self):
        try:
            _, unstaged = self._repo.get_working_copy_status()
        except Exception as e:
            self.status_message.emit(str(e))
            return
        if not unstaged:
            return
        paths = [e.path for e in unstaged]
        self._run_batch(self._repo.stage_file, paths, "staging")

    def _on_unstage_all(self):
        try:
            staged, _ = self._repo.get_working_copy_status()
        except Exception as e:
            self.status_message.emit(str(e))
            return
        if not staged:
            return
        paths = [e.path for e in staged]
        self._run_batch(self._repo.unstage_file, paths, "unstaging")

    def _on_commit(self):
        message = self._commit_edit.toPlainText().strip()
        if not message and not self._amend_check.isChecked():
            QMessageBox.warning(self, t("working_copy.commit_btn"), t("error.no_commit_message"))
            return
        amend = self._amend_check.isChecked()
        worker = GitWorker(self._repo.commit, message, amend)
        worker.signals.result.connect(lambda _: self._on_committed())
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_committed(self):
        self._commit_edit.clear()
        self._amend_check.setChecked(False)
        self.refresh()
        self.committed.emit()
        self.status_message.emit(t("status.committed"))

    def _run_op(self, fn, *args):
        worker = GitWorker(fn, *args)
        worker.signals.result.connect(lambda _: self.refresh())
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _run_batch(self, fn, paths: list[str], op: str):
        total = len(paths)
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._progress_label.setVisible(True)
        key = "progress.staging" if op == "staging" else "progress.unstaging"
        self._progress_label.setText(t(key, current=0, total=total))

        worker = BatchWorker(fn, paths)
        worker.signals.progress.connect(
            lambda cur, tot: self._on_batch_progress(cur, tot, key)
        )
        worker.signals.result.connect(lambda _: self._on_batch_done())
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_batch_progress(self, current: int, total: int, key: str):
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        self._progress_label.setText(t(key, current=current, total=total))

    def _on_batch_done(self):
        self._progress_bar.setVisible(False)
        self._progress_label.setVisible(False)
        self.refresh()

    def _on_error(self, error_msg: str):
        self._progress_bar.setVisible(False)
        self._progress_label.setVisible(False)
        lines = [l for l in error_msg.splitlines() if l.strip()]
        self.status_message.emit(lines[-1] if lines else "Git error occurred")
        self.refresh()
