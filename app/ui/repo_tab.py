import os
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QWidget, QSplitter, QListWidget, QListWidgetItem,
    QToolBar, QToolButton, QMenu, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QFileSystemWatcher
from PyQt6.QtGui import QColor, QAction

from app.i18n import t
from app.git.repo import GitRepo
from app.git.models import CommitRecord, FileStatusEntry
from app.git.runner import GitCommandError, open_terminal_in
from app.workers.git_worker import GitWorker
from app.constants import STATUS_COLORS
from PyQt6.QtCore import QThreadPool

from .commit_list_view import CommitListView
from .branch_panel import BranchPanel
from .working_copy_widget import WorkingCopyWidget
from .diff_viewer import DiffViewer
from .diff_controller import DiffController
from .large_file_banner import LargeFileBanner
from .commit_info_panel import CommitInfoPanel
from .commit_file_actions import CommitFileActions
from .dialogs.remote_dialog import RemoteDialog
from .dialogs.stash_dialog import StashDialog
from .dialogs.tag_dialog import TagDialog
from .dialogs.branch_dialog import BranchDialog
from .dialogs.lfs_dialog import LfsDialog
from .dialogs.remotes_dialog import RemotesDialog
from .dialogs.coauthor_history_dialog import CoAuthorHistoryDialog
from .ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("repo_tab.ui")

_QWIDGETSIZE_MAX = 16777215


STATUS_LABELS = {
    "M": "M", "A": "A", "D": "D", "R": "R",
    "C": "C", "?": "?", "U": "U", "T": "T",
}


class _SlotFiller:
    """Puts a code-built widget in place of a placeholder widget of a .ui form.

    The placeholder keeps the widget's position in Designer: its splitter index
    or layout item (with that item's stretch), and any explicit minimum /
    maximum width or height set on it, which are copied to the real widget.
    """

    @staticmethod
    def fill(slot: QWidget, widget: QWidget) -> QWidget:
        _SlotFiller._copy_size_limits(slot, widget)
        parent = slot.parentWidget()
        if isinstance(parent, QSplitter):
            parent.replaceWidget(parent.indexOf(slot), widget)
        else:
            parent.layout().replaceWidget(slot, widget)
        slot.setParent(None)
        slot.deleteLater()
        return widget

    @staticmethod
    def _copy_size_limits(slot: QWidget, widget: QWidget) -> None:
        if slot.minimumWidth() > 0:
            widget.setMinimumWidth(slot.minimumWidth())
        if slot.minimumHeight() > 0:
            widget.setMinimumHeight(slot.minimumHeight())
        if slot.maximumWidth() < _QWIDGETSIZE_MAX:
            widget.setMaximumWidth(slot.maximumWidth())
        if slot.maximumHeight() < _QWIDGETSIZE_MAX:
            widget.setMaximumHeight(slot.maximumHeight())


class RepoTab(QWidget):
    status_message = pyqtSignal(str)
    title_changed = pyqtSignal(str)

    # widgets / actions created by loadUi from repo_tab.ui
    toolBar: QToolBar
    mainSplitter: QSplitter
    centerWidget: QWidget
    rightSplitter: QSplitter
    bottomSplitter: QSplitter
    infoSplitter: QSplitter
    commitFilesList: QListWidget
    diffPane: QWidget
    # placeholders, replaced in _create_panels() by widgets built in code
    branchPanelSlot: QWidget
    commitListSlot: QWidget
    commitInfoSlot: QWidget
    largeFileBannerSlot: QWidget
    diffViewerSlot: QWidget
    workingCopySlot: QWidget
    actionFetch: QAction
    actionPull: QAction
    actionPush: QAction
    actionBranch: QAction           # its menu is built in _setup_branch_menu()
    actionCreateBranch: QAction
    actionMerge: QAction
    actionRebase: QAction
    actionCoauthorHistory: QAction
    actionStash: QAction
    actionTag: QAction
    actionLfs: QAction
    actionRemotes: QAction
    actionRefresh: QAction
    actionTerminal: QAction
    actionFix: QAction

    def __init__(self, repo_path: str, parent=None):
        super().__init__(parent)
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
        # Static layout (toolbar actions, splitter skeleton, commit-files list)
        # lives in repo_tab.ui and is editable in Qt Designer.
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)
        self._setup_branch_menu()
        self._create_panels()

        # Splitter sizes are not stored by Designer
        self.infoSplitter.setSizes([180, 120])
        self.bottomSplitter.setSizes([360, 600])
        self.rightSplitter.setSizes([400, 300])
        self.mainSplitter.setSizes([200, 680, 360])

    def _setup_branch_menu(self):
        # Designer can't attach a QMenu to a toolbar action of a plain QWidget
        # form; the menu's actions themselves are in the .ui.
        branch_menu = QMenu(self)
        branch_menu.addAction(self.actionCreateBranch)
        branch_menu.addAction(self.actionMerge)
        branch_menu.addAction(self.actionRebase)
        branch_menu.addSeparator()
        branch_menu.addAction(self.actionCoauthorHistory)
        self.actionBranch.setMenu(branch_menu)
        branch_button = self.toolBar.widgetForAction(self.actionBranch)
        branch_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # The toolbar makes its buttons NoFocus; the Branch menu button stays
        # reachable with Tab, as it was when it was a separate QToolButton.
        branch_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def _create_panels(self):
        # These widgets need the repository (or other arguments) in their
        # constructors, which promoted widgets can't pass; they are built here
        # and put in place of the placeholder widgets of the .ui.
        self._branch_panel = _SlotFiller.fill(
            self.branchPanelSlot, BranchPanel(self._repo))
        self._commit_list = _SlotFiller.fill(
            self.commitListSlot, CommitListView(self._repo))

        # Left column of the bottom pane: full commit information above the
        # changed-files list (commitFilesList comes from the .ui)
        self._commit_info_panel = _SlotFiller.fill(
            self.commitInfoSlot, CommitInfoPanel())
        self._commit_files_list = self.commitFilesList
        self._commit_file_actions = CommitFileActions(
            self._repo, self._commit_files_list, self)

        self._large_file_banner = _SlotFiller.fill(
            self.largeFileBannerSlot, LargeFileBanner())
        self._diff_viewer = _SlotFiller.fill(self.diffViewerSlot, DiffViewer())
        self._diff_controller = DiffController(
            self._repo, self._diff_viewer, self._large_file_banner, self)

        # Right panel: working copy (stage / unstage / commit)
        self._working_copy_widget = _SlotFiller.fill(
            self.workingCopySlot, WorkingCopyWidget(self._repo))
        self._restore_tab_order()

    def _restore_tab_order(self):
        # Widgets inserted after loadUi land at the end of the focus chain;
        # put them back into visual order (toolbar, branches, commits, info,
        # files, diff, working copy).
        chain = [self.toolBar.widgetForAction(self.actionBranch), self._branch_panel, self._commit_list, self._commit_info_panel,
                 self._commit_files_list, self._large_file_banner,
                 self._diff_viewer, self._working_copy_widget]
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

    def _connect_toolbar(self):
        triggers = {
            self.actionFetch: self._on_fetch,
            self.actionPull: self._on_pull,
            self.actionPush: self._on_push,
            self.actionCreateBranch: self._on_create_branch,
            self.actionMerge: self._on_merge,
            self.actionRebase: self._on_rebase,
            self.actionCoauthorHistory: self._on_coauthor_history,
            self.actionStash: self._on_stash,
            self.actionTag: self._on_tag,
            self.actionLfs: self._on_lfs,
            self.actionRemotes: self._on_remotes,
            self.actionRefresh: self._refresh_all,
            self.actionTerminal: self._on_open_terminal,
            self.actionFix: self._on_fix,
        }
        for action, slot in triggers.items():
            action.triggered.connect(slot)

    def _connect_signals(self):
        self._connect_toolbar()
        self._commit_list.commit_selected.connect(self._on_commit_selected)
        self._commit_list.working_copy_selected.connect(self._on_working_copy_selected)
        self._commit_list.refresh_requested.connect(self._refresh_all)
        self._commit_list.status_message.connect(self.status_message)
        self._commit_files_list.currentItemChanged.connect(self._on_commit_file_selected)
        self._commit_files_list.customContextMenuRequested.connect(
            self._commit_file_actions.show_menu)
        self._commit_file_actions.status_message.connect(self.status_message)
        self._commit_file_actions.history_rewritten.connect(self._on_history_rewritten)
        self._commit_info_panel.parent_clicked.connect(self._commit_list.select_commit)
        self._branch_panel.refresh_requested.connect(self._refresh_all)
        self._branch_panel.branch_checked_out.connect(self._on_branch_checked_out)
        self._branch_panel.status_message.connect(self.status_message)
        self._branch_panel.error_occurred.connect(self._on_error)
        self._working_copy_widget.committed.connect(self._refresh_all)
        self._working_copy_widget.file_selected.connect(self._on_working_file_selected)
        self._working_copy_widget.status_message.connect(self.status_message)
        self._setup_fs_watcher()

    def _setup_fs_watcher(self):
        """Watch .git state files/dirs so the UI auto-updates on external changes."""
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(400)
        self._refresh_timer.timeout.connect(self._on_fs_change)

        self._fs_watcher = QFileSystemWatcher(self)
        git_dir = self._repo.get_git_dir()

        # Files that change on every write operation or state change
        for name in ("HEAD", "MERGE_HEAD", "MERGE_MSG", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
            p = os.path.join(git_dir, name)
            if os.path.exists(p):
                self._fs_watcher.addPath(p)

        # Directories that appear/disappear during rebase
        for name in ("rebase-merge", "rebase-apply"):
            p = os.path.join(git_dir, name)
            if os.path.isdir(p):
                self._fs_watcher.addPath(p)

        # Watch the .git dir itself so we notice when MERGE_HEAD / CHERRY_PICK_HEAD
        # are created or deleted (files that don't exist yet can't be watched directly)
        self._fs_watcher.addPath(git_dir)

        self._fs_watcher.fileChanged.connect(self._schedule_fs_refresh)
        self._fs_watcher.directoryChanged.connect(self._on_git_dir_changed)

    def _on_git_dir_changed(self, path: str):
        """Re-register any newly appeared state files and schedule a refresh."""
        git_dir = self._repo.get_git_dir()
        for name in ("index", "HEAD", "MERGE_HEAD", "MERGE_MSG", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
            p = os.path.join(git_dir, name)
            if os.path.exists(p) and p not in self._fs_watcher.files():
                self._fs_watcher.addPath(p)
        self._refresh_timer.start()

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
        self._commit_file_actions.set_commit(commit.hash if commit else "")
        if commit is None:
            self._commit_info_panel.clear_info()
            return
        self._load_commit_info(commit)
        self._load_commit_files(commit)

    def _load_commit_info(self, commit: CommitRecord):
        worker = GitWorker(self._repo.get_commit_info, commit.hash)
        worker.signals.result.connect(
            lambda info, h=commit.hash: self._on_commit_info_ready(h, info))
        worker.signals.error.connect(
            lambda err, h=commit.hash: self._on_commit_info_failed(h, err))
        QThreadPool.globalInstance().start(worker)

    def _on_commit_info_ready(self, hash: str, info):
        # Ignore a slow answer for a commit that is no longer selected
        if self._current_commit and self._current_commit.hash == hash:
            self._commit_info_panel.show_info(info)

    def _on_commit_info_failed(self, hash: str, error: str):
        if self._current_commit and self._current_commit.hash == hash:
            lines = [l for l in error.splitlines() if l.strip()]
            self._commit_info_panel.show_error(lines[-1] if lines else "Git error")

    def _on_history_rewritten(self):
        # Hashes changed: the selected commit no longer exists under its old id
        self._current_commit = None
        self._commit_file_actions.set_commit("")
        self._commit_files_list.clear()
        self._commit_info_panel.clear_info()
        self._diff_controller.clear()
        self._refresh_all()

    def _on_working_copy_selected(self):
        self._working_copy_widget.refresh()

    def _load_commit_files(self, commit: CommitRecord):
        # Save current selection so it can be restored after reload
        cur = self._commit_files_list.currentItem()
        saved_path = None
        if cur:
            e = cur.data(Qt.ItemDataRole.UserRole)
            if e:
                saved_path = e.path

        self._commit_files_list.blockSignals(True)
        self._commit_files_list.clear()
        try:
            files = self._repo.get_commit_files(commit.hash)
        except Exception:
            self._commit_files_list.blockSignals(False)
            self._diff_controller.clear()
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
        self._commit_files_list.blockSignals(False)

        # Restore previously selected file, or clear diff if none
        restored = False
        if saved_path:
            for i in range(self._commit_files_list.count()):
                item = self._commit_files_list.item(i)
                e = item.data(Qt.ItemDataRole.UserRole)
                if e and e.path == saved_path:
                    self._commit_files_list.setCurrentItem(item)  # fires signal → reloads diff
                    restored = True
                    break
        if not restored:
            self._diff_controller.clear()

    def _on_commit_file_selected(self, current, previous):
        if current is None or self._current_commit is None:
            return
        entry = current.data(Qt.ItemDataRole.UserRole)
        if entry is None:
            return
        self._diff_controller.show_commit_file(self._current_commit.hash, entry.path)

    def _on_working_file_selected(self, path: str, staged: bool):
        self._diff_controller.show_working_file(path, staged)

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
        accepted = dlg.exec()
        self._refresh_all()  # always refresh — pull may have left conflicts on disk
        if accepted:
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
        dlg.exec()
        # Always refresh: a merge with conflicts writes state to disk even on failure
        self._refresh_all()

    def _on_rebase(self):
        dlg = BranchDialog(self._repo, mode="rebase", parent=self)
        dlg.exec()
        # Always refresh: rebase pauses on conflicts leaving state that must be shown
        self._refresh_all()

    def _on_coauthor_history(self):
        dlg = CoAuthorHistoryDialog(self._repo, parent=self)
        dlg.exec()
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

    def _on_open_terminal(self):
        try:
            open_terminal_in(self._repo.path)
        except Exception as e:
            self.status_message.emit(f"Error: {e}")

    def _on_fix(self):
        ret = QMessageBox.question(
            self, t("cleanup.title"), t("cleanup.confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        result = self._repo.cleanup_repo()
        locks  = result["locks_removed"]
        pids   = result["pids_killed"]
        errors = result["errors"]

        if not locks and not pids and not errors:
            QMessageBox.information(self, t("cleanup.title"), t("cleanup.nothing"))
            return

        locks_str = ", ".join(locks) if locks else "0"
        pids_str  = ", ".join(str(p) for p in pids) if pids else "0"

        if errors:
            msg = t("cleanup.done_with_errors",
                    locks=locks_str, pids=pids_str,
                    errors="\n".join(errors))
        else:
            msg = t("cleanup.done", locks=locks_str, pids=pids_str)

        QMessageBox.information(self, t("cleanup.title"), msg)
        self._refresh_all()

    def _on_error(self, error: str):
        lines = [l for l in error.splitlines() if l.strip()]
        msg = lines[-1] if lines else "Git error"
        self.status_message.emit(f"Error: {msg}")
        QMessageBox.critical(self, "Git Error", error)
