import os
import fnmatch as _fnmatch
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QWidget, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
    QListWidget, QListWidgetItem,
    QStackedWidget,
    QLabel, QTextEdit, QPushButton, QCheckBox,
    QMenu, QMessageBox, QAbstractItemView,
    QProgressBar, QFrame, QLineEdit, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QThreadPool
from PyQt6.QtGui import QColor, QMouseEvent

from app.i18n import t
from app.git.repo import GitRepo
from app.git.models import FileStatusEntry
from app.git.trailers import add_co_author, remove_co_author
from app.constants import STATUS_COLORS
from app.workers.git_worker import GitWorker
from app.ui.co_authors_bar import CoAuthorsBar
from app.ui.dialogs.add_coauthor_dialog import AddCoAuthorDialog
from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("working_copy_widget.ui")

LFS_ICON = "⬡"

STATUS_LABELS = {
    "M": "M", "A": "A", "D": "D", "R": "R",
    "C": "C", "?": "?", "U": "U", "T": "T",
}


_DEFAULT_COLOR = QColor("#d4d4d4")
_COLOR_BY_CHAR = {s.value: c for s, c in STATUS_COLORS.items()}


def release_freed_memory():
    """Give memory freed by a rebuilt file list back to the OS.

    Rebuilding lists of 100k+ items leaves the glibc heap fragmented, so RSS
    looked like a leak after every Stage/Unstage/Commit even though the
    objects were gone. malloc_trim returns the free pages.
    """
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass  # not glibc / not Linux - harmless


def _is_lfs(path: str, patterns: list[str]) -> bool:
    name = os.path.basename(path)
    for pat in patterns:
        if _fnmatch.fnmatch(name, pat):
            return True
        if _fnmatch.fnmatch(path, pat.replace("**", "*")):
            return True
    return False


# ── Flat list view ────────────────────────────────────────────────────────────

class FileListWidget(QListWidget):
    file_selected = pyqtSignal(str, bool)

    def __init__(self, staged: bool, parent=None):
        super().__init__(parent)
        self._staged = staged
        self._pending_files: tuple | None = None
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setUniformItemSizes(True)
        self.currentItemChanged.connect(self._on_item_changed)

    def set_files(self, entries: list[FileStatusEntry], lfs_patterns: list[str] = ()):
        # Save current selection so it can be restored after rebuild
        cur = self.currentItem()
        cur_entry = cur.data(Qt.ItemDataRole.UserRole) if cur else None
        cur_path = cur_entry.path if cur_entry else None
        sel_paths = {
            item.data(Qt.ItemDataRole.UserRole).path
            for item in self.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        }

        self._pending_files = None
        self.setUpdatesEnabled(False)
        self.blockSignals(True)
        self.clear()
        for entry in entries:
            sc = entry.status
            badge = STATUS_LABELS.get(sc, sc)
            lfs_mark = f" {LFS_ICON}" if lfs_patterns and _is_lfs(entry.path, lfs_patterns) else ""
            conflict = " ⚠" if sc == "U" else ""
            item = QListWidgetItem(f"{badge}  {entry.path}{lfs_mark}{conflict}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            color = _COLOR_BY_CHAR.get(sc, _DEFAULT_COLOR)
            item.setForeground(color)
            if sc == "U":
                item.setToolTip("⚠ Merge conflict — right-click to resolve")
            elif lfs_mark:
                item.setToolTip(f"Git LFS: {entry.path}")
            self.addItem(item)
        self.blockSignals(False)

        # Restore multi-selection without firing signals, then set current once
        new_current = None
        for i in range(self.count()):
            item = self.item(i)
            entry = item.data(Qt.ItemDataRole.UserRole)
            if entry:
                if entry.path in sel_paths:
                    item.setSelected(True)
                if entry.path == cur_path:
                    new_current = item
        if new_current:
            self.setCurrentItem(new_current)  # fires signal once → reloads diff
        self.setUpdatesEnabled(True)

    def apply_filter(self, text: str):
        text = text.strip().lower()
        for i in range(self.count()):
            item = self.item(i)
            entry = item.data(Qt.ItemDataRole.UserRole)
            if entry:
                item.setHidden(bool(text) and text not in entry.path.lower())

    def selected_entries(self) -> list[FileStatusEntry]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        ]

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            item = self.itemAt(event.pos())
            if item and item.isSelected():
                # Don't clear multi-selection when right-clicking an already-selected item
                return
        super().mousePressEvent(event)

    def _on_item_changed(self, current, _prev):
        if current:
            entry = current.data(Qt.ItemDataRole.UserRole)
            if entry:
                self.file_selected.emit(entry.path, self._staged)


# ── Tree view ─────────────────────────────────────────────────────────────────

_DIR_KEY_ROLE = Qt.ItemDataRole.UserRole + 1

# Indexes of the view toggle buttons and of the stack pages they show.
_LIST_MODE = 0
_TREE_MODE = 1


class FileTreeWidget(QTreeWidget):
    file_selected = pyqtSignal(str, bool)

    def __init__(self, staged: bool, parent=None):
        super().__init__(parent)
        self._staged = staged
        self._entries: list[FileStatusEntry] = []
        self._lfs_patterns: list[str] = []
        self._pending_files: tuple | None = None
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setIndentation(16)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.currentItemChanged.connect(self._on_item_changed)

    def set_files(self, entries: list[FileStatusEntry], lfs_patterns: list[str] = ()):
        self._entries = list(entries)
        self._lfs_patterns = list(lfs_patterns)
        self._rebuild()

    def apply_filter(self, text: str):
        self._filter_tree(text.strip().lower())

    def get_entries_under(self, item: QTreeWidgetItem) -> list[FileStatusEntry]:
        """Recursively collect file entries under a directory node.

        Files hidden by the filter are skipped: acting on a folder must only
        touch what the user can see in it.
        """
        result = []
        for i in range(item.childCount()):
            child = item.child(i)
            if child.isHidden():
                continue
            entry = child.data(0, Qt.ItemDataRole.UserRole)
            if entry is not None:
                result.append(entry)
            else:
                result.extend(self.get_entries_under(child))
        return result

    def selected_entries(self) -> list[FileStatusEntry]:
        """Selected files plus every visible file under each selected folder (no duplicates)."""
        result: list[FileStatusEntry] = []
        seen: set[str] = set()
        for item in self.selectedItems():
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            found = [entry] if entry is not None else self.get_entries_under(item)
            for e in found:
                if e.path not in seen:
                    seen.add(e.path)
                    result.append(e)
        return result

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            item = self.itemAt(event.pos())
            if item and item.isSelected():
                return
        super().mousePressEvent(event)

    def _rebuild(self):
        # Save current selection path
        cur = self.currentItem()
        cur_entry = cur.data(0, Qt.ItemDataRole.UserRole) if cur else None
        cur_path = cur_entry.path if cur_entry else None

        # Remember which folders the user has open/closed so a refresh doesn't reset them
        expanded_state: dict[str, bool] = {}
        stack = [self.invisibleRootItem()]
        while stack:
            node = stack.pop()
            for i in range(node.childCount()):
                child = node.child(i)
                key = child.data(0, _DIR_KEY_ROLE)
                if key is not None:
                    expanded_state[key] = child.isExpanded()
                    stack.append(child)

        self.setUpdatesEnabled(False)
        self.blockSignals(True)
        self.clear()
        dir_items: dict[str, QTreeWidgetItem] = {}

        for entry in self._entries:
            parts = entry.path.replace("\\", "/").split("/")
            filename = parts[-1]

            parent = self.invisibleRootItem()
            dir_key = ""
            for d in parts[:-1]:
                dir_key = f"{dir_key}/{d}" if dir_key else d
                if dir_key not in dir_items:
                    node = QTreeWidgetItem(parent)
                    node.setText(0, f"📁  {d}")
                    node.setForeground(0, QColor("#7a6e9e"))
                    node.setData(0, Qt.ItemDataRole.UserRole, None)
                    node.setData(0, _DIR_KEY_ROLE, dir_key)
                    node.setExpanded(expanded_state.get(dir_key, True))
                    dir_items[dir_key] = node
                parent = dir_items[dir_key]

            sc = entry.status
            badge = STATUS_LABELS.get(sc, sc)
            lfs_mark = f" {LFS_ICON}" if self._lfs_patterns and _is_lfs(entry.path, self._lfs_patterns) else ""
            conflict = " ⚠" if sc == "U" else ""

            item = QTreeWidgetItem(parent)
            item.setText(0, f"{badge}  {filename}{lfs_mark}{conflict}")
            item.setData(0, Qt.ItemDataRole.UserRole, entry)
            color = _COLOR_BY_CHAR.get(sc, _DEFAULT_COLOR)
            item.setForeground(0, color)
            if sc == "U":
                item.setToolTip(0, "⚠ Merge conflict — right-click to resolve")
            elif lfs_mark:
                item.setToolTip(0, f"Git LFS: {entry.path}")
        self.blockSignals(False)

        # Restore previously selected file
        if cur_path:
            it = QTreeWidgetItemIterator(self)
            while it.value():
                node = it.value()
                entry = node.data(0, Qt.ItemDataRole.UserRole)
                if entry and entry.path == cur_path:
                    self.setCurrentItem(node)  # fires signal once → reloads diff
                    break
                it += 1
        self.setUpdatesEnabled(True)

    def _filter_tree(self, text: str):
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            self._filter_item(root.child(i), text)

    def _filter_item(self, item: QTreeWidgetItem, text: str) -> bool:
        entry = item.data(0, Qt.ItemDataRole.UserRole)
        if entry is not None:
            visible = not text or text in entry.path.lower()
            item.setHidden(not visible)
            return visible
        any_vis = False
        for i in range(item.childCount()):
            if self._filter_item(item.child(i), text):
                any_vis = True
        item.setHidden(not any_vis)
        if any_vis and text:   # only an active search opens folders; an empty filter must keep the user's state
            item.setExpanded(True)
        return any_vis

    def _on_item_changed(self, current, _prev):
        if current:
            entry = current.data(0, Qt.ItemDataRole.UserRole)
            if entry:
                self.file_selected.emit(entry.path, self._staged)


# ── Working copy widget ───────────────────────────────────────────────────────

class WorkingCopyWidget(QWidget):
    committed      = pyqtSignal()
    file_selected  = pyqtSignal(str, bool)
    status_message = pyqtSignal(str)

    # widgets created by loadUi from working_copy_widget.ui
    conflictBanner: QFrame          # objectName is a style.qss selector
    bannerIconLabel: QLabel
    conflictLabel: QLabel
    continueButton: QPushButton
    abortButton: QPushButton
    listViewButton: QPushButton     # objectName becomes "smallBtn" in _setup_ui
    treeViewButton: QPushButton     # objectName becomes "smallBtn" in _setup_ui
    sectionsSplitter: QSplitter
    unstageAllButton: QPushButton
    stagedFilterEdit: QLineEdit
    stagedStack: QStackedWidget     # pages: stagedListPage / stagedTreePage
    stagedListPage: QWidget
    stagedTreePage: QWidget
    stageAllButton: QPushButton
    unstagedFilterEdit: QLineEdit
    unstagedStack: QStackedWidget   # pages: unstagedListPage / unstagedTreePage
    unstagedListPage: QWidget
    unstagedTreePage: QWidget
    progressBar: QProgressBar
    progressLabel: QLabel
    commitArea: QWidget             # objectName is a style.qss selector
    commitEdit: QTextEdit
    coAuthorsBar: CoAuthorsBar
    amendCheck: QCheckBox
    primaryButton: QPushButton      # "Commit"; objectName is a style.qss selector

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._abort_fn = None
        self._continue_fn = None
        self._pre_amend_text = ""
        self._setup_ui()
        self._connect_signals()
        self.refresh()

    # Active-view helpers
    # The stacks hold container pages, so the active view is picked by index.
    @property
    def _staged_list(self) -> FileListWidget | FileTreeWidget:
        return (self._staged_flat, self._staged_tree)[self.stagedStack.currentIndex()]

    @property
    def _unstaged_list(self) -> FileListWidget | FileTreeWidget:
        return (self._unstaged_flat, self._unstaged_tree)[self.unstagedStack.currentIndex()]

    # ------------------------------------------------------------------ UI

    def _setup_ui(self):
        # Static layout (banner, view toggle, staged/unstaged sections, progress
        # row, commit area) lives in working_copy_widget.ui and is editable in
        # Qt Designer. File views take a constructor argument, so they are built
        # here and put into the empty stack pages of the form.
        uic.loadUi(_UI_FILE, self)

        # Both toggle buttons share the style.qss selector #smallBtn; a form
        # can't hold two widgets with one objectName, so it is assigned here
        # (and the style re-applied, since it is matched by objectName).
        for btn in (self.listViewButton, self.treeViewButton):
            btn.setObjectName("smallBtn")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        UiTranslator().apply(self)

        self._view_group = QButtonGroup(self)
        self._view_group.addButton(self.listViewButton, _LIST_MODE)
        self._view_group.addButton(self.treeViewButton, _TREE_MODE)
        self._view_group.setExclusive(True)

        self._staged_flat = FileListWidget(staged=True)
        self._staged_tree = FileTreeWidget(staged=True)
        self._unstaged_flat = FileListWidget(staged=False)
        self._unstaged_tree = FileTreeWidget(staged=False)
        self.stagedListPage.layout().addWidget(self._staged_flat)
        self.stagedTreePage.layout().addWidget(self._staged_tree)
        self.unstagedListPage.layout().addWidget(self._unstaged_flat)
        self.unstagedTreePage.layout().addWidget(self._unstaged_tree)
        self.stagedStack.setCurrentIndex(_LIST_MODE)
        self.unstagedStack.setCurrentIndex(_LIST_MODE)

        # Each file view sits right after its section's filter in the tab chain.
        QWidget.setTabOrder(self.stagedFilterEdit, self._staged_flat)
        QWidget.setTabOrder(self._staged_flat, self._staged_tree)
        QWidget.setTabOrder(self._staged_tree, self.stageAllButton)
        QWidget.setTabOrder(self.unstagedFilterEdit, self._unstaged_flat)
        QWidget.setTabOrder(self._unstaged_flat, self._unstaged_tree)
        QWidget.setTabOrder(self._unstaged_tree, self.commitEdit)
        # The co-author bar's "+" button comes between the message and "Amend".
        QWidget.setTabOrder(self.commitEdit, self.coAuthorsBar.smallBtn)
        QWidget.setTabOrder(self.coAuthorsBar.smallBtn, self.amendCheck)

        # Splitter sizes and initial visibility aren't stored in the form.
        self.sectionsSplitter.setSizes([200, 200])
        self.conflictBanner.setVisible(False)
        self.continueButton.setVisible(False)
        self.progressBar.setVisible(False)
        self.progressLabel.setVisible(False)

    def _connect_signals(self):
        self.continueButton.clicked.connect(self._on_continue)
        self.abortButton.clicked.connect(self._on_abort)
        self._view_group.idClicked.connect(self._set_tree_mode)

        for view in (self._staged_flat, self._staged_tree):
            view.file_selected.connect(self.file_selected)
            view.customContextMenuRequested.connect(self._staged_context_menu)
        for view in (self._unstaged_flat, self._unstaged_tree):
            view.file_selected.connect(self.file_selected)
            view.customContextMenuRequested.connect(self._unstaged_context_menu)

        # Filter applies to the currently active view (evaluated at call time)
        self.stagedFilterEdit.textChanged.connect(
            lambda text: self._staged_list.apply_filter(text)
        )
        self.unstagedFilterEdit.textChanged.connect(
            lambda text: self._unstaged_list.apply_filter(text)
        )

        self.stageAllButton.clicked.connect(self._on_stage_all)
        self.unstageAllButton.clicked.connect(self._on_unstage_all)
        self.primaryButton.clicked.connect(self._on_commit)
        self.amendCheck.toggled.connect(self._on_amend_toggled)
        self.commitEdit.textChanged.connect(self._on_commit_text_changed)
        self.coAuthorsBar.add_requested.connect(self._on_add_co_author)
        self.coAuthorsBar.remove_requested.connect(self._on_remove_co_author)

    # ------------------------------------------------------------------ Slots

    def _set_tree_mode(self, mode_id: int):
        """0 = flat list, 1 = tree."""
        self.stagedStack.setCurrentIndex(mode_id)
        self.unstagedStack.setCurrentIndex(mode_id)
        # Flush pending data into the newly visible views
        for view in (self._staged_list, self._unstaged_list):
            if view._pending_files is not None:
                view.set_files(*view._pending_files)
                # _pending_files cleared inside set_files
        self._staged_list.apply_filter(self.stagedFilterEdit.text())
        self._unstaged_list.apply_filter(self.unstagedFilterEdit.text())

    def _on_amend_toggled(self, checked: bool):
        if checked:
            self._pre_amend_text = self.commitEdit.toPlainText()
            try:
                msg = self._repo.get_last_commit_message()
            except Exception:
                msg = ""
            self._replace_commit_text_keep_cursor_at_end(msg)
        else:
            self.commitEdit.setPlainText(self._pre_amend_text)

    def _on_commit_text_changed(self):
        self.coAuthorsBar.sync(self.commitEdit.toPlainText())

    def _on_add_co_author(self):
        dlg = AddCoAuthorDialog(self)
        if dlg.exec():
            new_text = add_co_author(self.commitEdit.toPlainText(), dlg.name, dlg.email)
            self._replace_commit_text_keep_cursor_at_end(new_text)

    def _on_remove_co_author(self, email: str):
        new_text = remove_co_author(self.commitEdit.toPlainText(), email)
        self._replace_commit_text_keep_cursor_at_end(new_text)

    def _replace_commit_text_keep_cursor_at_end(self, text: str):
        self.commitEdit.setPlainText(text)
        cursor = self.commitEdit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.commitEdit.setTextCursor(cursor)

    def refresh(self):
        try:
            staged, unstaged = self._repo.get_working_copy_status()
            lfs_patterns = self._repo.lfs_tracked_patterns()

            active_staged   = self._staged_list
            active_unstaged = self._unstaged_list

            # Rebuild only the currently visible views
            active_staged.set_files(staged, lfs_patterns)
            active_unstaged.set_files(unstaged, lfs_patterns)

            # Mark hidden views dirty — they will rebuild when shown
            for view in (self._staged_flat, self._staged_tree):
                if view is not active_staged:
                    view._pending_files = (staged, lfs_patterns)
            for view in (self._unstaged_flat, self._unstaged_tree):
                if view is not active_unstaged:
                    view._pending_files = (unstaged, lfs_patterns)

            active_staged.apply_filter(self.stagedFilterEdit.text())
            active_unstaged.apply_filter(self.unstagedFilterEdit.text())
            self._update_conflict_banner(staged, unstaged)
        except Exception as e:
            self.status_message.emit(f"Error refreshing status: {e}")
        else:
            del staged, unstaged
            release_freed_memory()

    def _update_conflict_banner(self, staged, unstaged):
        conflicted = {e.path for e in staged + unstaged if e.status == "U"}
        self._continue_fn = None

        if not conflicted:
            if self._repo.is_merging():
                # All conflicts resolved — waiting for merge commit
                self.bannerIconLabel.setText("✓")
                self.bannerIconLabel.setStyleSheet("color: #4ec9b0; font-size: 14px;")
                self.conflictBanner.setStyleSheet(
                    "background: rgba(78,201,176,20); border-bottom: 1px solid rgba(78,201,176,60);"
                )
                self.conflictLabel.setText(t("conflict.merge_ready"))
                self.abortButton.setText(t("conflict.merge_ready_abort"))
                self._abort_fn = self._repo.abort_merge
                self.continueButton.setVisible(False)
                self.conflictBanner.setVisible(True)
                self._maybe_fill_merge_msg()
            elif self._repo.is_rebasing():
                # All conflicts resolved — user must run rebase --continue
                self.bannerIconLabel.setText("✓")
                self.bannerIconLabel.setStyleSheet("color: #4ec9b0; font-size: 14px;")
                self.conflictBanner.setStyleSheet(
                    "background: rgba(78,201,176,20); border-bottom: 1px solid rgba(78,201,176,60);"
                )
                self.conflictLabel.setText(t("conflict.rebase_ready"))
                self.abortButton.setText(t("conflict.abort_rebase"))
                self._abort_fn = self._repo.abort_rebase
                self.continueButton.setText(t("conflict.continue_rebase"))
                self.continueButton.setVisible(True)
                self._continue_fn = self._repo.rebase_continue
                self.conflictBanner.setVisible(True)
            elif self._repo.is_cherry_picking():
                # All conflicts resolved — user must run cherry-pick --continue
                self.bannerIconLabel.setText("✓")
                self.bannerIconLabel.setStyleSheet("color: #4ec9b0; font-size: 14px;")
                self.conflictBanner.setStyleSheet(
                    "background: rgba(78,201,176,20); border-bottom: 1px solid rgba(78,201,176,60);"
                )
                self.conflictLabel.setText(t("conflict.cherry_pick_ready"))
                self.abortButton.setText(t("conflict.abort_cherry_pick"))
                self._abort_fn = self._repo.abort_cherry_pick
                self.continueButton.setText(t("conflict.continue_cherry_pick"))
                self.continueButton.setVisible(True)
                self._continue_fn = self._repo.cherry_pick_continue
                self.conflictBanner.setVisible(True)
            elif self._repo.is_reverting():
                self.bannerIconLabel.setText("✓")
                self.bannerIconLabel.setStyleSheet("color: #4ec9b0; font-size: 14px;")
                self.conflictBanner.setStyleSheet(
                    "background: rgba(78,201,176,20); border-bottom: 1px solid rgba(78,201,176,60);"
                )
                self.conflictLabel.setText(t("conflict.revert_ready"))
                self.abortButton.setText(t("conflict.abort_revert"))
                self._abort_fn = self._repo.abort_revert
                self.continueButton.setText(t("conflict.continue_revert"))
                self.continueButton.setVisible(True)
                self._continue_fn = self._repo.revert_continue
                self.conflictBanner.setVisible(True)
            else:
                self.conflictBanner.setVisible(False)
                self._abort_fn = None
                self.continueButton.setVisible(False)
            return

        # Reset banner style to conflict/warning style
        self.bannerIconLabel.setText("⚠")
        self.bannerIconLabel.setStyleSheet("")
        self.conflictBanner.setStyleSheet("")
        self.continueButton.setVisible(False)
        if self._repo.is_merging():
            op, fn = t("conflict.abort_merge"), self._repo.abort_merge
        elif self._repo.is_rebasing():
            op, fn = t("conflict.abort_rebase"), self._repo.abort_rebase
        elif self._repo.is_cherry_picking():
            op, fn = t("conflict.abort_cherry_pick"), self._repo.abort_cherry_pick
        elif self._repo.is_reverting():
            op, fn = t("conflict.abort_revert"), self._repo.abort_revert
        else:
            op, fn = t("conflict.abort_merge"), self._repo.abort_merge
        self._abort_fn = fn
        self.conflictLabel.setText(t("conflict.banner", n=len(conflicted)))
        self.abortButton.setText(op)
        self.conflictBanner.setVisible(True)

    def _maybe_fill_merge_msg(self):
        if not self.commitEdit.toPlainText().strip():
            try:
                msg = self._repo.get_merge_msg()
                if msg:
                    self.commitEdit.setPlainText(msg)
            except Exception:
                pass

    # ------------------------------------------------------------------ Context menus

    def _staged_context_menu(self, pos: QPoint):
        sender_view = self.sender()

        entries = sender_view.selected_entries()
        if not entries:
            return
        menu = QMenu(self)
        is_conflict = any(e.status == "U" for e in entries)
        resolve_action = menu.addAction(t("conflict.context_menu")) if is_conflict else None
        if resolve_action:
            menu.addSeparator()
        unstage_action = menu.addAction(t("working_copy.unstage"))
        action = menu.exec(sender_view.mapToGlobal(pos))
        if action is None:                          # menu dismissed
            return
        if resolve_action and action == resolve_action:
            self._open_conflict_dialog(entries[0].path)
        elif action == unstage_action:
            self._run_batch(self._repo.unstage_file, [e.path for e in entries], "unstaging")

    def _unstaged_context_menu(self, pos: QPoint):
        sender_view = self.sender()

        entries = sender_view.selected_entries()
        if not entries:
            return
        menu = QMenu(self)
        is_conflict = any(e.status == "U" for e in entries)
        if is_conflict:
            resolve_action = menu.addAction(t("conflict.context_menu"))
            menu.addSeparator()
        else:
            resolve_action = None
        stage_action   = menu.addAction(t("working_copy.stage"))
        discard_action = menu.addAction(t("working_copy.discard"))
        action = menu.exec(sender_view.mapToGlobal(pos))
        if action is None:                          # menu dismissed
            return
        if resolve_action and action == resolve_action:
            self._open_conflict_dialog(entries[0].path)
        elif action == stage_action:
            self._run_batch(self._repo.stage_file, [e.path for e in entries], "staging")
        elif action == discard_action:
            self._safe_discard(entries)

    def _open_conflict_dialog(self, path: str):
        from app.ui.dialogs.conflict_dialog import ConflictDialog
        dlg = ConflictDialog(self._repo, path, parent=self)
        if dlg.exec():
            self.refresh()

    def _on_abort(self):
        if not self._abort_fn:
            return
        ret = QMessageBox.question(
            self, t("conflict.abort_title"), t("conflict.abort_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            try:
                self._abort_fn()
                self.refresh()
                self.committed.emit()   # ask repo_tab to refresh commit list too
            except Exception as e:
                self.status_message.emit(str(e))

    def _on_continue(self):
        if not self._continue_fn:
            return
        try:
            self._continue_fn()
            self.refresh()
            self.committed.emit()   # ask repo_tab to refresh commit list too
        except Exception as e:
            # A conflict during --continue means more conflicts remain
            self.refresh()
            self.status_message.emit(str(e))

    def _safe_discard(self, entries: list):
        """Discard changes but save them to a named stash first (recoverable)."""
        if not entries:
            return

        if len(entries) == 1:
            msg = t("discard.dialog_text_one", path=entries[0].path)
        else:
            names = "\n".join(f"  \u2022 {e.path}" for e in entries)
            msg = t("discard.dialog_text_many", n=len(entries), names=names)

        ret = QMessageBox.question(
            self, t("discard.dialog_title"), msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        paths = [e.path for e in entries]
        worker = GitWorker(self._repo.safe_discard_files, paths)
        worker.signals.result.connect(self._on_discard_done)
        worker.signals.error.connect(self._on_discard_error)
        QThreadPool.globalInstance().start(worker)

    def _on_discard_done(self, stash_label: str):
        self.status_message.emit(t("discard.success", label=stash_label))
        self.refresh()

    def _on_discard_error(self, error_msg: str):
        # safe_discard_files failed — working tree is untouched, user's work is safe
        QMessageBox.warning(
            self, t("discard.error_title"),
            t("discard.error_text", error=error_msg),
        )
        self.refresh()

    def _on_stage_all(self):
        # `git add -A` stages literally everything in one process, however many
        # files there are; it must not depend on the (possibly huge or stale)
        # list of paths the UI is currently showing.
        self._run_op(self._repo.stage_all)

    def _on_unstage_all(self):
        self._run_op(self._repo.unstage_all)

    def _on_commit(self):
        message = self.commitEdit.toPlainText().strip()
        if not message and not self.amendCheck.isChecked():
            QMessageBox.warning(self, t("working_copy.commit_btn"),
                                t("error.no_commit_message"))
            return

        try:
            staged_sizes = self._repo.get_staged_file_sizes()
        except Exception:
            staged_sizes = []

        if staged_sizes:
            GITHUB_FILE_MAX = 100 * 1024 * 1024
            GITHUB_PUSH_MAX = 1024 * 1024 * 1024
            large_files = [(p, s) for p, s in staged_sizes if s > GITHUB_FILE_MAX]
            total = sum(s for _, s in staged_sizes)

            if large_files:
                names = "\n".join(f"  {p}  ({s / 1024**2:.0f} MB)" for p, s in large_files)
                ret = QMessageBox.warning(
                    self, t("commit.warn_large.title"),
                    t("commit.warn_large.file_text", files=names),
                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                )
                if ret == QMessageBox.StandardButton.Cancel:
                    return
            elif total > GITHUB_PUSH_MAX:
                ret = QMessageBox.warning(
                    self, t("commit.warn_large.title"),
                    t("commit.warn_large.total_text", size=f"{total / 1024**2:.0f} MB"),
                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                )
                if ret == QMessageBox.StandardButton.Cancel:
                    return

        worker = GitWorker(self._repo.commit, message, self.amendCheck.isChecked())
        worker.signals.result.connect(lambda _: self._on_committed())
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_committed(self):
        self.commitEdit.clear()
        self.amendCheck.setChecked(False)
        self.refresh()
        self.committed.emit()
        self.status_message.emit(t("status.committed"))

    def _run_op(self, fn, *args):
        worker = GitWorker(fn, *args)
        worker.signals.result.connect(lambda _: self.refresh())
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _run_batch(self, fn, paths: list[str], op: str):
        # Use a single atomic git add/restore call instead of one process per file.
        # This prevents partial staging on crash and avoids index.lock contention.
        if op == "staging":
            atomic_fn = self._repo.stage_files
        else:
            atomic_fn = self._repo.unstage_files
        worker = GitWorker(atomic_fn, paths)
        worker.signals.result.connect(lambda _: self._on_batch_done())
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_batch_done(self):
        self.progressBar.setVisible(False)
        self.progressLabel.setVisible(False)
        self.refresh()

    def _on_error(self, error_msg: str):
        self.progressBar.setVisible(False)
        self.progressLabel.setVisible(False)
        lines = [l for l in error_msg.splitlines() if l.strip()]
        self.status_message.emit(lines[-1] if lines else "Git error occurred")
        self.refresh()
