import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QListWidget, QListWidgetItem, QLabel,
    QToolBar, QToolButton, QMenu, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer, QFileSystemWatcher
from PyQt6.QtGui import QIcon, QFont, QColor, QAction

from app.i18n import t
from app.git.repo import GitRepo
from app.git.models import CommitRecord, FileStatusEntry
from app.git.runner import GitCommandError
from app.workers.git_worker import GitWorker
from app.constants import STATUS_COLORS
from PyQt6.QtCore import QThreadPool

from .commit_list_view import CommitListView
from .branch_panel import BranchPanel
from .working_copy_widget import WorkingCopyWidget
from .diff_viewer import DiffViewer
from .dialogs.remote_dialog import RemoteDialog
from .dialogs.stash_dialog import StashDialog
from .dialogs.tag_dialog import TagDialog
from .dialogs.branch_dialog import BranchDialog
from .dialogs.lfs_dialog import LfsDialog
from .dialogs.remotes_dialog import RemotesDialog


STATUS_LABELS = {
    "M": "M", "A": "A", "D": "D", "R": "R",
    "C": "C", "?": "?", "U": "U", "T": "T",
}


class RepoTab(QWidget):
    status_message = pyqtSignal(str)
    title_changed = pyqtSignal(str)

    def __init__(self, repo_path: str, parent=None):
        super().__init__(parent)
        self._repo_path = repo_path
        try:
            self._repo = GitRepo(repo_path)
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Cannot open repository:\n{e}")
            raise
        self._current_commit = None
        self._setup_ui()
        self._connect_signals()
        self._refresh_all()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        self._toolbar = self._build_toolbar()
        layout.addWidget(self._toolbar)

        # Main splitter: branch panel | content
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Branch panel
        self._branch_panel = BranchPanel(self._repo)
        self._branch_panel.setMinimumWidth(160)
        self._branch_panel.setMaximumWidth(280)
        self._main_splitter.addWidget(self._branch_panel)

        # Right side: commit list + bottom pane
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._right_splitter = QSplitter(Qt.Orientation.Vertical)

        # Commit list
        self._commit_list = CommitListView(self._repo)
        self._right_splitter.addWidget(self._commit_list)

        # Bottom pane: file list + diff viewer
        self._bottom_splitter = QSplitter(Qt.Orientation.Horizontal)

        # File list (stacked: commit files or working copy)
        self._file_stack = QTabWidget()
        self._file_stack.setTabPosition(QTabWidget.TabPosition.North)
        self._file_stack.setDocumentMode(True)

        self._commit_files_list = QListWidget()
        self._file_stack.addTab(self._commit_files_list, t("tab.files"))

        self._working_copy_widget = WorkingCopyWidget(self._repo)
        self._file_stack.addTab(self._working_copy_widget, t("tab.working_copy"))

        self._bottom_splitter.addWidget(self._file_stack)

        # Diff viewer
        self._diff_viewer = DiffViewer()
        self._bottom_splitter.addWidget(self._diff_viewer)
        self._bottom_splitter.setSizes([300, 600])

        self._right_splitter.addWidget(self._bottom_splitter)
        self._right_splitter.setSizes([400, 300])

        right_layout.addWidget(self._right_splitter)
        self._main_splitter.addWidget(right_widget)
        self._main_splitter.setSizes([200, 800])

        layout.addWidget(self._main_splitter)

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        tb.addAction(t("toolbar.fetch"), self._on_fetch)
        tb.addAction(t("toolbar.pull"), self._on_pull)
        tb.addAction(t("toolbar.push"), self._on_push)
        tb.addSeparator()

        branch_btn = QToolButton()
        branch_btn.setText(t("toolbar.branch"))
        branch_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        branch_menu = QMenu()
        branch_menu.addAction(t("toolbar.branch.create"), self._on_create_branch)
        branch_menu.addAction(t("toolbar.branch.merge"), self._on_merge)
        branch_menu.addAction(t("toolbar.branch.rebase"), self._on_rebase)
        branch_btn.setMenu(branch_menu)
        tb.addWidget(branch_btn)

        tb.addAction(t("toolbar.stash"), self._on_stash)
        tb.addAction(t("toolbar.tag"), self._on_tag)
        tb.addAction(t("toolbar.lfs"), self._on_lfs)
        tb.addAction(t("toolbar.remotes"), self._on_remotes)
        tb.addSeparator()
        tb.addAction(t("toolbar.refresh"), self._refresh_all)

        return tb

    def _connect_signals(self):
        self._commit_list.commit_selected.connect(self._on_commit_selected)
        self._commit_list.working_copy_selected.connect(self._on_working_copy_selected)
        self._commit_list.refresh_requested.connect(self._refresh_all)
        self._commit_list.status_message.connect(self.status_message)
        self._commit_files_list.currentItemChanged.connect(self._on_commit_file_selected)
        self._branch_panel.refresh_requested.connect(self._refresh_all)
        self._branch_panel.branch_checked_out.connect(self._on_branch_checked_out)
        self._branch_panel.status_message.connect(self.status_message)
        self._branch_panel.error_occurred.connect(self._on_error)
        self._working_copy_widget.committed.connect(self._refresh_all)
        self._working_copy_widget.file_selected.connect(self._on_working_file_selected)
        self._working_copy_widget.status_message.connect(self.status_message)
        self._setup_fs_watcher()

    def _setup_fs_watcher(self):
        """Watch .git/index and .git/HEAD so the UI auto-updates on external changes."""
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(400)
        self._refresh_timer.timeout.connect(self._on_fs_change)

        self._fs_watcher = QFileSystemWatcher(self)
        git_dir = os.path.join(self._repo_path, ".git")
        for name in ("index", "HEAD"):
            p = os.path.join(git_dir, name)
            if os.path.exists(p):
                self._fs_watcher.addPath(p)
        self._fs_watcher.fileChanged.connect(self._schedule_fs_refresh)

    def _schedule_fs_refresh(self, path: str):
        # Re-add path in case git replaced the file atomically
        if path not in self._fs_watcher.files():
            self._fs_watcher.addPath(path)
        self._refresh_timer.start()

    def _on_fs_change(self):
        self._working_copy_widget.refresh()
        self._branch_panel.refresh()
        self._commit_list.load_commits()

    def _refresh_all(self):
        self._commit_list.load_commits()
        self._branch_panel.refresh()
        self._working_copy_widget.refresh()
        self.title_changed.emit(self._repo.get_repo_name())
        self._fetch_tags_bg()

    def _fetch_tags_bg(self):
        """Silently fetch remote tags in background so the panel stays in sync."""
        worker = GitWorker(self._repo.fetch_tags_silent)
        worker.signals.result.connect(lambda _: self._branch_panel.refresh())
        # Errors (e.g. offline) are silently ignored
        QThreadPool.globalInstance().start(worker)

    def _on_commit_selected(self, commit: CommitRecord):
        self._current_commit = commit
        self._file_stack.setCurrentIndex(0)
        self._load_commit_files(commit)

    def _on_working_copy_selected(self):
        self._file_stack.setCurrentIndex(1)
        self._working_copy_widget.refresh()

    def _load_commit_files(self, commit: CommitRecord):
        self._commit_files_list.clear()
        self._diff_viewer.clear_diff()
        try:
            files = self._repo.get_commit_files(commit.hash)
        except Exception:
            return
        for entry in files:
            label = STATUS_LABELS.get(entry.status, entry.status)
            item = QListWidgetItem(f"{label}  {entry.path}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            color = STATUS_COLORS.get(
                next((s for s in STATUS_COLORS if s.value == entry.status), None),
                QColor("#d4d4d4")
            )
            item.setForeground(color)
            self._commit_files_list.addItem(item)

    def _on_commit_file_selected(self, current, previous):
        if current is None or self._current_commit is None:
            return
        entry = current.data(Qt.ItemDataRole.UserRole)
        if entry is None:
            return
        try:
            diff = self._repo.get_diff(self._current_commit.hash, entry.path)
            self._diff_viewer.show_diff(diff, entry.path)
        except Exception as e:
            self._diff_viewer.show_diff(str(e))

    def _on_working_file_selected(self, path: str, staged: bool):
        try:
            diff = self._repo.get_working_copy_diff(path, staged)
            self._diff_viewer.show_diff(diff, path)
        except Exception as e:
            self._diff_viewer.show_diff(str(e))

    def _on_branch_checked_out(self, name: str):
        self._refresh_all()

    # ---- Toolbar actions ----

    def _on_fetch(self):
        dlg = RemoteDialog(self._repo, mode="fetch", parent=self)
        if dlg.exec():
            self._refresh_all()
            self.status_message.emit(t("status.fetch_done"))

    def _on_pull(self):
        dlg = RemoteDialog(self._repo, mode="pull", parent=self)
        if dlg.exec():
            self._refresh_all()
            self.status_message.emit(t("status.pull_done"))

    def _on_push(self):
        dlg = RemoteDialog(self._repo, mode="push", parent=self)
        if dlg.exec():
            self._refresh_all()
            self.status_message.emit(t("status.push_done"))

    def _on_create_branch(self):
        dlg = BranchDialog(self._repo, mode="create", parent=self)
        if dlg.exec():
            self._refresh_all()

    def _on_merge(self):
        dlg = BranchDialog(self._repo, mode="merge", parent=self)
        if dlg.exec():
            self._refresh_all()

    def _on_rebase(self):
        dlg = BranchDialog(self._repo, mode="rebase", parent=self)
        if dlg.exec():
            self._refresh_all()

    def _on_stash(self):
        dlg = StashDialog(self._repo, parent=self)
        if dlg.exec():
            self._refresh_all()
            self.status_message.emit(t("status.stash_done"))

    def _on_tag(self):
        dlg = TagDialog(self._repo, parent=self)
        if dlg.exec():
            self._refresh_all()
            self.status_message.emit(t("status.tag_done"))

    def _on_lfs(self):
        if not self._repo.lfs_is_enabled():
            QMessageBox.warning(self, t("toolbar.lfs"), t("lfs.not_enabled"))
            return
        dlg = LfsDialog(self._repo, parent=self)
        dlg.exec()

    def _on_remotes(self):
        dlg = RemotesDialog(self._repo, parent=self)
        dlg.exec()

    def _on_error(self, error: str):
        lines = [l for l in error.splitlines() if l.strip()]
        msg = lines[-1] if lines else "Git error"
        self.status_message.emit(f"Error: {msg}")
        QMessageBox.critical(self, "Git Error", error)
