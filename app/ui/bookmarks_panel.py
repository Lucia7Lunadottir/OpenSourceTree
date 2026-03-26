import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QFileDialog, QMenu, QLabel, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from app import config
from app.i18n import t
from app.git.repo import GitRepo


class BookmarksPanel(QWidget):
    repo_selected = pyqtSignal(str)   # emits repo path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._load_bookmarks()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setObjectName("panelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 4, 6)
        label = QLabel(t("bookmarks.title"))
        label.setStyleSheet("font-weight: bold; color: #d4d4d4;")
        self._add_btn = QPushButton("+")
        self._add_btn.setObjectName("iconBtn")
        self._add_btn.setFixedSize(22, 22)
        self._add_btn.setToolTip(t("bookmarks.add_tooltip"))
        header_layout.addWidget(label)
        header_layout.addStretch()
        header_layout.addWidget(self._add_btn)
        layout.addWidget(header)

        # List
        self._list = QListWidget()
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        self._list.itemDoubleClicked.connect(self._on_item_activated)
        self._list.itemClicked.connect(self._on_item_activated)
        layout.addWidget(self._list)

        self._add_btn.clicked.connect(self._on_add)

    def _load_bookmarks(self):
        self._list.clear()
        bookmarks = config.load_bookmarks()
        for path in bookmarks:
            self._add_item(path)

    def _add_item(self, path: str):
        name = os.path.basename(path)
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        item.setForeground(QColor("#d4d4d4"))
        self._list.addItem(item)

    def _on_add(self):
        path = QFileDialog.getExistingDirectory(
            self,
            t("bookmarks.select_dir"),
            os.path.expanduser("~"),
        )
        if path:
            self.add_repo(path)

    def add_repo(self, path: str):
        if not GitRepo.is_git_repo(path):
            QMessageBox.warning(
                self,
                t("bookmarks.not_git.title"),
                t("bookmarks.not_git.text", path=path),
            )
            return
        config.add_bookmark(path)
        self._load_bookmarks()
        # Select the newly added item
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                self._list.setCurrentItem(item)
                self.repo_selected.emit(path)
                break

    def _on_item_activated(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.repo_selected.emit(path)

    def _context_menu(self, pos):
        item = self._list.itemAt(pos)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        open_action = menu.addAction(t("bookmarks.open"))
        remove_action = menu.addAction(t("bookmarks.remove"))
        action = menu.exec(self._list.mapToGlobal(pos))
        if action == open_action:
            self.repo_selected.emit(path)
        elif action == remove_action:
            config.remove_bookmark(path)
            self._load_bookmarks()
