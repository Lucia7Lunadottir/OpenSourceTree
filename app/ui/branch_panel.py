from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QMenu, QMessageBox, QInputDialog,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialogButtonBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QColor

from app.i18n import t
from app.git.repo import GitRepo
from app.git.models import BranchInfo, TagInfo, StashInfo
from app.constants import BranchType
from app.workers.git_worker import GitWorker
from PyQt6.QtCore import QThreadPool


class BranchPanel(QTreeWidget):
    branch_checked_out = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    status_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.itemDoubleClicked.connect(self._on_double_click)
        self.setIndentation(12)

    def refresh(self):
        # Save selected item identity so we can restore it after rebuild
        selected = self.currentItem()
        saved_key = None
        if selected:
            d = selected.data(0, Qt.ItemDataRole.UserRole)
            if d:
                kind, obj = d
                saved_key = (kind, obj.name)

        self.clear()
        try:
            branches = self._repo.get_branches()
            tags = self._repo.get_tags()
            stashes = self._repo.get_stashes()
        except Exception as e:
            self.error_occurred.emit(str(e))
            return

        # LOCAL BRANCHES
        local_root = self._make_section(t("branch_panel.local"))
        for b in branches:
            if not b.is_remote:
                item = QTreeWidgetItem([b.name])
                item.setData(0, Qt.ItemDataRole.UserRole, ("branch", b))
                if b.is_current:
                    font = item.font(0)
                    font.setBold(True)
                    item.setFont(0, font)
                    item.setForeground(0, QColor("#4ec9b0"))
                local_root.addChild(item)

        # REMOTE BRANCHES
        remote_root = self._make_section(t("branch_panel.remote"))
        for b in branches:
            if b.is_remote:
                item = QTreeWidgetItem([b.name])
                item.setData(0, Qt.ItemDataRole.UserRole, ("branch", b))
                item.setForeground(0, QColor("#9cdcfe"))
                remote_root.addChild(item)

        # TAGS
        tags_root = self._make_section(t("branch_panel.tags"))
        for tag in tags:
            item = QTreeWidgetItem([tag.name])
            item.setData(0, Qt.ItemDataRole.UserRole, ("tag", tag))
            item.setForeground(0, QColor("#dcdcaa"))
            tags_root.addChild(item)

        # STASHES
        stash_root = self._make_section(t("branch_panel.stashes"))
        for s in stashes:
            label = f"{s.name}: {s.message}" if s.message else s.name
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.ItemDataRole.UserRole, ("stash", s))
            item.setForeground(0, QColor("#ce9178"))
            stash_root.addChild(item)

        self.expandAll()

        # Restore previously selected item
        if saved_key:
            it = QTreeWidgetItemIterator(self)
            while it.value():
                item = it.value()
                d = item.data(0, Qt.ItemDataRole.UserRole)
                if d:
                    kind, obj = d
                    if (kind, obj.name) == saved_key:
                        self.setCurrentItem(item)
                        break
                it += 1

    def _make_section(self, title: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self, [title])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setForeground(0, QColor("#888888"))
        return item

    def _on_double_click(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None:
            return
        kind, obj = data
        if kind == "branch" and not obj.is_remote:
            self._checkout(obj.name)

    def _context_menu(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None:
            return
        kind, obj = data
        menu = QMenu(self)

        if kind == "branch":
            if not obj.is_remote:
                menu.addAction(t("branch.checkout"), lambda: self._checkout(obj.name))
                menu.addAction(t("branch.merge_into"), lambda: self._merge(obj.name))
                menu.addAction(t("branch.rebase_onto"), lambda: self._rebase(obj.name))
                menu.addSeparator()
                menu.addAction(t("branch.rename"), lambda: self._rename_branch(obj.name))
                menu.addAction(t("branch.delete"), lambda: self._delete_branch(obj.name, force=False))
                menu.addAction(t("branch.force_delete"), lambda: self._delete_branch(obj.name, force=True))
                if obj.tracking:
                    menu.addSeparator()
                    menu.addAction(t("branch.push"), lambda: self._push_branch(obj.name))
                    menu.addAction(t("branch.pull"), lambda: self._pull_branch(obj.name))
            else:
                menu.addAction(t("branch.checkout_local"), lambda: self._checkout_remote(obj.name))

        elif kind == "tag":
            menu.addAction(t("branch.push_tag"), lambda: self._push_tag(obj.name))
            menu.addSeparator()
            menu.addAction(t("branch.delete_tag"), lambda: self._delete_tag(obj.name))

        elif kind == "stash":
            menu.addAction(t("branch.stash_apply"), lambda: self._stash_apply(obj.index))
            menu.addAction(t("branch.stash_pop"), lambda: self._stash_pop(obj.index))
            menu.addAction(t("branch.stash_drop"), lambda: self._stash_drop(obj.index))

        menu.exec(self.mapToGlobal(pos))

    def _run(self, fn, *args, success_msg="Done", refresh=True):
        worker = GitWorker(fn, *args)
        def on_result(_):
            self.status_message.emit(success_msg)
            if refresh:
                self.refresh_requested.emit()
        def on_error(e):
            self.error_occurred.emit(e)
            if refresh:
                self.refresh_requested.emit()  # refresh even on error — conflicts must be shown
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        QThreadPool.globalInstance().start(worker)

    def _checkout(self, name: str):
        self._run(self._repo.checkout, name, success_msg=f"Checked out {name}")
        self.branch_checked_out.emit(name)

    def _checkout_remote(self, name: str):
        # e.g. origin/main -> create local main tracking it
        local_name = name.split("/", 1)[-1] if "/" in name else name
        self._run(
            self._repo.runner.run,
            ["checkout", "-b", local_name, "--track", name],
            success_msg=f"Checked out {local_name}",
        )
        self.branch_checked_out.emit(local_name)

    def _merge(self, name: str):
        self._run(self._repo.merge, name, success_msg=f"Merged {name}")

    def _rebase(self, name: str):
        self._run(self._repo.rebase, name, success_msg=f"Rebased onto {name}")

    def _rename_branch(self, old_name: str):
        new_name, ok = QInputDialog.getText(
            self, "Rename Branch", f"New name for '{old_name}':", text=old_name
        )
        if ok and new_name and new_name != old_name:
            self._run(self._repo.rename_branch, old_name, new_name, success_msg=f"Renamed to {new_name}")

    def _delete_branch(self, name: str, force: bool):
        ret = QMessageBox.question(
            self,
            "Delete Branch",
            f"Delete branch '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self._run(self._repo.delete_branch, name, force, success_msg=f"Deleted {name}")

    def _push_tag(self, name: str):
        self._run(self._repo.push_tag, name, success_msg=t("status.tag_pushed", name=name))

    def _delete_tag(self, name: str):
        dlg = QDialog(self)
        dlg.setWindowTitle(t("branch_dialog.title.delete"))
        dlg.setMinimumWidth(430)

        vbox = QVBoxLayout(dlg)
        vbox.setSpacing(10)

        lbl_title = QLabel(t("tag.delete.text", name=name))
        lbl_title.setStyleSheet("font-weight: bold;")
        vbox.addWidget(lbl_title)

        lbl_info = QLabel(t("tag.delete.info"))
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet("color: #aaa; font-size: 11px;")
        vbox.addWidget(lbl_info)

        vbox.addSpacing(4)

        hbox = QHBoxLayout()
        cancel_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        cancel_box.rejected.connect(dlg.reject)
        local_btn  = QPushButton(t("tag.delete.local_only"))
        remote_btn = QPushButton(t("tag.delete.local_and_remote"))
        remote_btn.setStyleSheet("color: #f44747;")
        hbox.addWidget(cancel_box)
        hbox.addStretch()
        hbox.addWidget(local_btn)
        hbox.addWidget(remote_btn)
        vbox.addLayout(hbox)

        _result = [None]
        local_btn.clicked.connect(lambda: (_result.__setitem__(0, "local"),  dlg.accept()))
        remote_btn.clicked.connect(lambda: (_result.__setitem__(0, "remote"), dlg.accept()))

        dlg.exec()

        if _result[0] == "local":
            # Do NOT emit refresh_requested — that triggers fetch_tags_bg which
            # re-downloads the tag from remote, making it instantly reappear.
            worker = GitWorker(self._repo.delete_tag, name)
            worker.signals.result.connect(lambda _: (
                self.status_message.emit(t("tag.delete.success_local", name=name)),
                self.refresh(),
            ))
            worker.signals.error.connect(lambda e: self.error_occurred.emit(e))
            QThreadPool.globalInstance().start(worker)
        elif _result[0] == "remote":
            self._run_delete_tag_remote(name)

    def _run_delete_tag_remote(self, name: str):
        """Delete tag locally first, then from the remote."""
        local_worker = GitWorker(self._repo.delete_tag, name)

        def _after_local(_):
            remote_worker = GitWorker(self._repo.delete_remote_tag, name)
            remote_worker.signals.result.connect(
                lambda _: (
                    self.status_message.emit(t("tag.delete.success_remote", name=name)),
                    self.refresh(),
                    self.refresh_requested.emit(),
                )
            )
            remote_worker.signals.error.connect(self._on_remote_tag_delete_error)
            QThreadPool.globalInstance().start(remote_worker)

        local_worker.signals.result.connect(_after_local)
        local_worker.signals.error.connect(lambda e: self.error_occurred.emit(e))
        QThreadPool.globalInstance().start(local_worker)

    def _on_remote_tag_delete_error(self, error: str):
        self.refresh()
        self.refresh_requested.emit()
        QMessageBox.warning(
            self,
            t("tag.delete.remote_error_title"),
            t("tag.delete.remote_error_text", error=error),
        )

    def _push_branch(self, name: str):
        self._run(self._repo.push, "", name, success_msg=f"Pushed {name}")

    def _pull_branch(self, name: str):
        self._run(self._repo.pull, "", name, success_msg=f"Pulled {name}")

    def _stash_apply(self, index: int):
        self._run(self._repo.stash_apply, index, success_msg=t("stash_pop.success"))

    def _stash_pop(self, index: int):
        ret = QMessageBox.question(
            self, t("stash_pop.dialog_title"),
            t("stash_pop.dialog_text"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self._run(self._repo.stash_pop, index, success_msg=t("stash_pop.success"))

    def _stash_drop(self, index: int):
        ret = QMessageBox.warning(
            self, t("stash_drop.dialog_title"),
            t("stash_drop.dialog_text"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self._run(self._repo.stash_drop, index, success_msg=t("stash_drop.success"))
