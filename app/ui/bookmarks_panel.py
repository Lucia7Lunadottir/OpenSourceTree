import os
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QWidget, QListWidget, QListWidgetItem, QPushButton, QFileDialog, QMenu,
    QLabel, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from app import config
from app.i18n import t
from app.git.repo import GitRepo
from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("bookmarks_panel.ui")


class BookmarksPanel(QWidget):
    repo_selected = pyqtSignal(str)   # emits repo path

    # widgets created by loadUi from bookmarks_panel.ui
    # (panelHeader / iconBtn objectNames are styled in style.qss)
    panelHeader: QWidget
    titleLabel: QLabel
    iconBtn: QPushButton
    bookmarkList: QListWidget

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._load_bookmarks()

    def _setup_ui(self):
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)
        self.bookmarkList.customContextMenuRequested.connect(self._context_menu)
        self.bookmarkList.itemDoubleClicked.connect(self._on_item_activated)
        self.bookmarkList.itemClicked.connect(self._on_item_activated)
        self.iconBtn.clicked.connect(self._on_add)

    def _load_bookmarks(self):
        self.bookmarkList.clear()
        bookmarks = config.load_bookmarks()
        for path in bookmarks:
            self._add_item(path)

    def _add_item(self, path: str):
        name = os.path.basename(path)
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        item.setForeground(QColor("#d4d4d4"))
        self.bookmarkList.addItem(item)

    def _on_add(self):
        path = QFileDialog.getExistingDirectory(
            self,
            t("bookmarks.select_dir"),
            os.path.expanduser("~"),
        )
        if path:
            self.add_repo(path)

    def add_repo(self, path: str):
        # Resolve to the actual working-tree top-level rather than trusting
        # `path` verbatim — a bookmark saved from a subdirectory of a repo
        # (which passes `is_git_repo`-style checks fine, since git searches
        # upward) breaks stage/unstage/stash pathspecs later, since those
        # are always relative to the true top-level. GitRepo already does
        # this resolution on construction, so reuse it here as validation.
        try:
            resolved_path = GitRepo(path).path
        except Exception:
            QMessageBox.warning(
                self,
                t("bookmarks.not_git.title"),
                t("bookmarks.not_git.text", path=path),
            )
            return
        config.add_bookmark(resolved_path)
        self._load_bookmarks()
        # Select the newly added item
        for i in range(self.bookmarkList.count()):
            item = self.bookmarkList.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == resolved_path:
                self.bookmarkList.setCurrentItem(item)
                self.repo_selected.emit(resolved_path)
                break

    def _on_item_activated(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.repo_selected.emit(path)

    def _context_menu(self, pos):
        item = self.bookmarkList.itemAt(pos)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        open_action = menu.addAction(t("bookmarks.open"))
        remove_action = menu.addAction(t("bookmarks.remove"))
        action = menu.exec(self.bookmarkList.mapToGlobal(pos))
        if action == open_action:
            self.repo_selected.emit(path)
        elif action == remove_action:
            config.remove_bookmark(path)
            self._load_bookmarks()
