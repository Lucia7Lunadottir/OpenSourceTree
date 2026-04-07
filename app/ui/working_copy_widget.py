import os
import fnmatch as _fnmatch

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem,
    QListWidget, QListWidgetItem,
    QStackedWidget,
    QLabel, QTextEdit, QPushButton, QCheckBox,
    QMenu, QMessageBox, QAbstractItemView,
    QProgressBar, QFrame, QLineEdit, QButtonGroup, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QThreadPool
from PyQt6.QtGui import QColor, QFont, QMouseEvent

from app.i18n import t
from app.git.repo import GitRepo
from app.git.models import FileStatusEntry
from app.constants import STATUS_COLORS
from app.workers.git_worker import GitWorker
from app.workers.batch_worker import BatchWorker

LFS_ICON = "⬡"

STATUS_LABELS = {
    "M": "M", "A": "A", "D": "D", "R": "R",
    "C": "C", "?": "?", "U": "U", "T": "T",
}


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
        self._pending_files = None
        self.setUpdatesEnabled(False)
        self.clear()
        for entry in entries:
            sc = entry.status
            badge = STATUS_LABELS.get(sc, sc)
            lfs_mark = f" {LFS_ICON}" if lfs_patterns and _is_lfs(entry.path, lfs_patterns) else ""
            conflict = " ⚠" if sc == "U" else ""
            item = QListWidgetItem(f"{badge}  {entry.path}{lfs_mark}{conflict}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            color = STATUS_COLORS.get(
                next((s for s in STATUS_COLORS if s.value == sc), None),
                QColor("#d4d4d4"),
            )
            item.setForeground(color)
            if sc == "U":
                item.setToolTip("⚠ Merge conflict — right-click to resolve")
            elif lfs_mark:
                item.setToolTip(f"Git LFS: {entry.path}")
            self.addItem(item)
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
        """Recursively collect all file entries under a directory node."""
        result = []
        for i in range(item.childCount()):
            child = item.child(i)
            entry = child.data(0, Qt.ItemDataRole.UserRole)
            if entry is not None:
                result.append(entry)
            else:
                result.extend(self.get_entries_under(child))
        return result

    def selected_entries(self) -> list[FileStatusEntry]:
        return [
            item.data(0, Qt.ItemDataRole.UserRole)
            for item in self.selectedItems()
            if item.data(0, Qt.ItemDataRole.UserRole) is not None
        ]

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            item = self.itemAt(event.pos())
            if item and item.isSelected():
                return
        super().mousePressEvent(event)

    def _rebuild(self):
        self.setUpdatesEnabled(False)
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
                    node.setExpanded(True)
                    # Dir nodes not selectable as files, but still receive right-click
                    node.setFlags(
                        (node.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                        | Qt.ItemFlag.ItemIsEnabled
                    )
                    dir_items[dir_key] = node
                parent = dir_items[dir_key]

            sc = entry.status
            badge = STATUS_LABELS.get(sc, sc)
            lfs_mark = f" {LFS_ICON}" if self._lfs_patterns and _is_lfs(entry.path, self._lfs_patterns) else ""
            conflict = " ⚠" if sc == "U" else ""

            item = QTreeWidgetItem(parent)
            item.setText(0, f"{badge}  {filename}{lfs_mark}{conflict}")
            item.setData(0, Qt.ItemDataRole.UserRole, entry)
            color = STATUS_COLORS.get(
                next((s for s in STATUS_COLORS if s.value == sc), None),
                QColor("#d4d4d4"),
            )
            item.setForeground(0, color)
            if sc == "U":
                item.setToolTip(0, "⚠ Merge conflict — right-click to resolve")
            elif lfs_mark:
                item.setToolTip(0, f"Git LFS: {entry.path}")
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
        if any_vis:
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

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._abort_fn = None
        self._pre_amend_text = ""
        self._setup_ui()
        self._connect_signals()
        self.refresh()

    # Active-view helpers
    @property
    def _staged_list(self) -> FileListWidget | FileTreeWidget:
        return self._staged_stack.currentWidget()

    @property
    def _unstaged_list(self) -> FileListWidget | FileTreeWidget:
        return self._unstaged_stack.currentWidget()

    # ------------------------------------------------------------------ UI

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Conflict banner ───────────────────────────────────────────
        self._conflict_banner = QFrame()
        self._conflict_banner.setObjectName("conflictBanner")
        banner_row = QHBoxLayout(self._conflict_banner)
        banner_row.setContentsMargins(8, 5, 8, 5)
        self._conflict_label = QLabel("")
        self._abort_btn = QPushButton("")
        self._abort_btn.setFixedHeight(22)
        self._abort_btn.clicked.connect(self._on_abort)
        self._banner_icon = QLabel("⚠")
        banner_row.addWidget(self._banner_icon)
        banner_row.addWidget(self._conflict_label, 1)
        banner_row.addWidget(self._abort_btn)
        self._conflict_banner.setVisible(False)
        layout.addWidget(self._conflict_banner)

        # ── View toggle ───────────────────────────────────────────────
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(4, 2, 4, 2)
        self._list_btn = QPushButton("☰  " + t("working_copy.view_list"))
        self._tree_btn = QPushButton("🌲  " + t("working_copy.view_tree"))
        for btn in (self._list_btn, self._tree_btn):
            btn.setCheckable(True)
            btn.setFixedHeight(20)
            btn.setObjectName("smallBtn")
        self._list_btn.setChecked(True)
        self._view_group = QButtonGroup(self)
        self._view_group.addButton(self._list_btn, 0)
        self._view_group.addButton(self._tree_btn, 1)
        self._view_group.setExclusive(True)
        self._view_group.idClicked.connect(self._set_tree_mode)
        toggle_row.addStretch()
        toggle_row.addWidget(self._list_btn)
        toggle_row.addWidget(self._tree_btn)
        layout.addLayout(toggle_row)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Staged section ────────────────────────────────────────────
        staged_widget = QWidget()
        sl = QVBoxLayout(staged_widget)
        sl.setContentsMargins(4, 4, 4, 0)
        sl.setSpacing(2)

        staged_header = QHBoxLayout()
        staged_lbl = QLabel(t("working_copy.staged"))
        staged_lbl.setStyleSheet("color: #4ec9b0; font-weight: bold;")
        self._unstage_all_btn = QPushButton(t("working_copy.unstage_all"))
        self._unstage_all_btn.setFixedHeight(22)
        staged_header.addWidget(staged_lbl)
        staged_header.addStretch()
        staged_header.addWidget(self._unstage_all_btn)
        sl.addLayout(staged_header)

        self._staged_filter = QLineEdit()
        self._staged_filter.setPlaceholderText(t("working_copy.filter_placeholder"))
        self._staged_filter.setClearButtonEnabled(True)
        self._staged_filter.setFixedHeight(24)
        sl.addWidget(self._staged_filter)

        self._staged_stack = QStackedWidget()
        self._staged_flat = FileListWidget(staged=True)
        self._staged_tree = FileTreeWidget(staged=True)
        self._staged_stack.addWidget(self._staged_flat)   # index 0
        self._staged_stack.addWidget(self._staged_tree)   # index 1
        sl.addWidget(self._staged_stack)

        # ── Unstaged section ──────────────────────────────────────────
        unstaged_widget = QWidget()
        ul = QVBoxLayout(unstaged_widget)
        ul.setContentsMargins(4, 4, 4, 0)
        ul.setSpacing(2)

        unstaged_header = QHBoxLayout()
        unstaged_lbl = QLabel(t("working_copy.unstaged"))
        unstaged_lbl.setStyleSheet("color: #dcdcaa; font-weight: bold;")
        self._stage_all_btn = QPushButton(t("working_copy.stage_all"))
        self._stage_all_btn.setFixedHeight(22)
        unstaged_header.addWidget(unstaged_lbl)
        unstaged_header.addStretch()
        unstaged_header.addWidget(self._stage_all_btn)
        ul.addLayout(unstaged_header)

        self._unstaged_filter = QLineEdit()
        self._unstaged_filter.setPlaceholderText(t("working_copy.filter_placeholder"))
        self._unstaged_filter.setClearButtonEnabled(True)
        self._unstaged_filter.setFixedHeight(24)
        ul.addWidget(self._unstaged_filter)

        self._unstaged_stack = QStackedWidget()
        self._unstaged_flat = FileListWidget(staged=False)
        self._unstaged_tree = FileTreeWidget(staged=False)
        self._unstaged_stack.addWidget(self._unstaged_flat)
        self._unstaged_stack.addWidget(self._unstaged_tree)
        ul.addWidget(self._unstaged_stack)

        splitter.addWidget(staged_widget)
        splitter.addWidget(unstaged_widget)
        splitter.setSizes([200, 200])
        layout.addWidget(splitter, 1)

        # ── Progress bar ──────────────────────────────────────────────
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

        # ── Commit area ───────────────────────────────────────────────
        commit_area = QWidget()
        commit_area.setObjectName("commitArea")
        commit_layout = QVBoxLayout(commit_area)
        commit_layout.setContentsMargins(4, 4, 4, 4)
        commit_layout.setSpacing(4)

        self._commit_edit = QTextEdit()
        self._commit_edit.setPlaceholderText(t("working_copy.commit_placeholder"))
        self._commit_edit.setFixedHeight(80)
        self._commit_edit.setFont(QFont("Monospace", 11))
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
        commit_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(commit_area)

    def _connect_signals(self):
        for view in (self._staged_flat, self._staged_tree):
            view.file_selected.connect(self.file_selected)
            view.customContextMenuRequested.connect(self._staged_context_menu)
        for view in (self._unstaged_flat, self._unstaged_tree):
            view.file_selected.connect(self.file_selected)
            view.customContextMenuRequested.connect(self._unstaged_context_menu)

        # Filter applies to the currently active view (evaluated at call time)
        self._staged_filter.textChanged.connect(
            lambda text: self._staged_list.apply_filter(text)
        )
        self._unstaged_filter.textChanged.connect(
            lambda text: self._unstaged_list.apply_filter(text)
        )

        self._stage_all_btn.clicked.connect(self._on_stage_all)
        self._unstage_all_btn.clicked.connect(self._on_unstage_all)
        self._commit_btn.clicked.connect(self._on_commit)
        self._amend_check.toggled.connect(self._on_amend_toggled)

    # ------------------------------------------------------------------ Slots

    def _set_tree_mode(self, mode_id: int):
        """0 = flat list, 1 = tree."""
        self._staged_stack.setCurrentIndex(mode_id)
        self._unstaged_stack.setCurrentIndex(mode_id)
        # Flush pending data into the newly visible views
        for view in (self._staged_list, self._unstaged_list):
            if view._pending_files is not None:
                view.set_files(*view._pending_files)
                # _pending_files cleared inside set_files
        self._staged_list.apply_filter(self._staged_filter.text())
        self._unstaged_list.apply_filter(self._unstaged_filter.text())

    def _on_amend_toggled(self, checked: bool):
        if checked:
            self._pre_amend_text = self._commit_edit.toPlainText()
            try:
                msg = self._repo.get_last_commit_message()
            except Exception:
                msg = ""
            self._commit_edit.setPlainText(msg)
            cursor = self._commit_edit.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._commit_edit.setTextCursor(cursor)
        else:
            self._commit_edit.setPlainText(self._pre_amend_text)

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

            active_staged.apply_filter(self._staged_filter.text())
            active_unstaged.apply_filter(self._unstaged_filter.text())
            self._update_conflict_banner(staged, unstaged)
        except Exception as e:
            self.status_message.emit(f"Error refreshing status: {e}")

    def _update_conflict_banner(self, staged, unstaged):
        conflicted = {e.path for e in staged + unstaged if e.status == "U"}
        if not conflicted:
            if self._repo.is_merging():
                # All conflicts resolved but merge not yet committed
                self._banner_icon.setText("✓")
                self._banner_icon.setStyleSheet("color: #4ec9b0; font-size: 14px;")
                self._conflict_banner.setStyleSheet(
                    "background: rgba(78,201,176,20); border-bottom: 1px solid rgba(78,201,176,60);"
                )
                self._conflict_label.setText(t("conflict.merge_ready"))
                self._abort_btn.setText(t("conflict.merge_ready_abort"))
                self._abort_fn = self._repo.abort_merge
                self._conflict_banner.setVisible(True)
                self._maybe_fill_merge_msg()
            else:
                self._conflict_banner.setVisible(False)
                self._abort_fn = None
            return
        # Reset banner style to warning style
        self._banner_icon.setText("⚠")
        self._banner_icon.setStyleSheet("")
        self._conflict_banner.setStyleSheet("")
        if self._repo.is_merging():
            op, fn = t("conflict.abort_merge"), self._repo.abort_merge
        elif self._repo.is_rebasing():
            op, fn = t("conflict.abort_rebase"), self._repo.abort_rebase
        elif self._repo.is_cherry_picking():
            op, fn = t("conflict.abort_cherry_pick"), self._repo.abort_cherry_pick
        else:
            op, fn = t("conflict.abort_merge"), self._repo.abort_merge
        self._abort_fn = fn
        self._conflict_label.setText(t("conflict.banner", n=len(conflicted)))
        self._abort_btn.setText(op)
        self._conflict_banner.setVisible(True)

    def _maybe_fill_merge_msg(self):
        if not self._commit_edit.toPlainText().strip():
            try:
                msg = self._repo.get_merge_msg()
                if msg:
                    self._commit_edit.setPlainText(msg)
            except Exception:
                pass

    # ------------------------------------------------------------------ Context menus

    def _staged_context_menu(self, pos: QPoint):
        sender_view = self.sender()

        # Directory node in tree mode → offer to unstage the whole folder
        if isinstance(sender_view, FileTreeWidget):
            item = sender_view.itemAt(pos)
            if item and item.data(0, Qt.ItemDataRole.UserRole) is None:
                entries = sender_view.get_entries_under(item)
                if not entries:
                    return
                menu = QMenu(self)
                act = menu.addAction(t("working_copy.unstage_folder", n=len(entries)))
                if menu.exec(sender_view.mapToGlobal(pos)) == act:
                    self._run_batch(self._repo.unstage_file,
                                    [e.path for e in entries], "unstaging")
                return

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
            for entry in entries:
                self._run_op(self._repo.unstage_file, entry.path)

    def _unstaged_context_menu(self, pos: QPoint):
        sender_view = self.sender()

        # Directory node in tree mode → offer to stage the whole folder
        if isinstance(sender_view, FileTreeWidget):
            item = sender_view.itemAt(pos)
            if item and item.data(0, Qt.ItemDataRole.UserRole) is None:
                entries = sender_view.get_entries_under(item)
                if not entries:
                    return
                menu = QMenu(self)
                act = menu.addAction(t("working_copy.stage_folder", n=len(entries)))
                if menu.exec(sender_view.mapToGlobal(pos)) == act:
                    self._run_batch(self._repo.stage_file,
                                    [e.path for e in entries], "staging")
                return

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
            for entry in entries:
                self._run_op(self._repo.stage_file, entry.path)
        elif action == discard_action:
            if len(entries) == 1:
                msg = f"Discard changes to {entries[0].path}?"
            else:
                names = "\n".join(f"  • {e.path}" for e in entries)
                msg = f"Discard changes to {len(entries)} files?\n\n{names}"
            ret = QMessageBox.question(
                self, "Discard Changes", msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret == QMessageBox.StandardButton.Yes:
                def do_discard(ents=entries):
                    for e in ents:
                        try:
                            if e.status == "?":
                                self._repo.runner.run(["clean", "-f", "-q", "--", e.path])
                            else:
                                self._repo.runner.run(["checkout", "--", e.path])
                        except Exception:
                            pass
                self._run_op(do_discard)

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
            except Exception as e:
                self.status_message.emit(str(e))

    def _on_stage_all(self):
        try:
            _, unstaged = self._repo.get_working_copy_status()
        except Exception as e:
            self.status_message.emit(str(e))
            return
        if unstaged:
            self._run_batch(self._repo.stage_file, [e.path for e in unstaged], "staging")

    def _on_unstage_all(self):
        try:
            staged, _ = self._repo.get_working_copy_status()
        except Exception as e:
            self.status_message.emit(str(e))
            return
        if staged:
            self._run_batch(self._repo.unstage_file, [e.path for e in staged], "unstaging")

    def _on_commit(self):
        message = self._commit_edit.toPlainText().strip()
        if not message and not self._amend_check.isChecked():
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

        worker = GitWorker(self._repo.commit, message, self._amend_check.isChecked())
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
        key = "progress.staging" if op == "staging" else "progress.unstaging"
        self._progress_bar.setMaximum(len(paths))
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._progress_label.setVisible(True)
        self._progress_label.setText(t(key, current=0, total=len(paths)))
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
