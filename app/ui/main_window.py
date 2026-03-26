import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter,
    QTabWidget, QStatusBar, QToolBar,
    QApplication, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QKeySequence, QAction

from app.i18n import t

from .bookmarks_panel import BookmarksPanel
from .repo_tab import RepoTab
from .dialogs.clone_dialog import CloneDialog
from .dialogs.ssh_dialog import SSHSettingsDialog
from .dialogs.accounts_dialog import AccountsDialog
from .dialogs.identity_dialog import IdentityDialog
from .dialogs.language_dialog import LanguageDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenSourceTree")
        self.resize(1280, 800)
        self._repo_tabs: dict[str, int] = {}  # path -> tab index
        self._setup_ui()
        self._setup_menu()
        self._setup_statusbar()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Main splitter: bookmarks | tabs
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # Bookmarks panel
        self._bookmarks = BookmarksPanel()
        self._bookmarks.setMinimumWidth(160)
        self._bookmarks.setMaximumWidth(260)
        self._bookmarks.repo_selected.connect(self._open_repo)
        self._splitter.addWidget(self._bookmarks)

        # Repo tabs
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        # Placeholder when no tabs
        self._placeholder = QWidget()
        ph_layout = QHBoxLayout(self._placeholder)
        from PyQt6.QtWidgets import QLabel
        ph_label = QLabel(
            "Open a repository from the bookmarks panel,\n"
            "or use File → Open / Clone to get started."
        )
        ph_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_label.setStyleSheet("color: #666; font-size: 14px;")
        ph_layout.addWidget(ph_label)
        self._splitter.addWidget(self._placeholder)

        self._splitter.setSizes([200, 1080])
        layout.addWidget(self._splitter)

    def _setup_menu(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu(t("menu.file"))
        open_action = file_menu.addAction(t("menu.file.open"))
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._on_open)

        clone_action = file_menu.addAction(t("menu.file.clone"))
        clone_action.triggered.connect(self._on_clone)

        file_menu.addSeparator()
        quit_action = file_menu.addAction(t("menu.file.quit"))
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(QApplication.instance().quit)

        # Settings menu
        settings_menu = menubar.addMenu(t("menu.settings"))
        acc_action = settings_menu.addAction(t("menu.settings.accounts"))
        acc_action.triggered.connect(self._on_accounts)
        settings_menu.addSeparator()
        ssh_action = settings_menu.addAction(t("menu.settings.ssh"))
        ssh_action.triggered.connect(self._on_ssh_settings)
        id_action = settings_menu.addAction(t("menu.settings.identity"))
        id_action.triggered.connect(self._on_identity)
        settings_menu.addSeparator()
        lang_action = settings_menu.addAction(t("menu.settings.language"))
        lang_action.triggered.connect(self._on_language)

        # View menu
        view_menu = menubar.addMenu(t("menu.view"))
        refresh_action = view_menu.addAction(t("menu.view.refresh"))
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.triggered.connect(self._refresh_current)

        # Help menu
        help_menu = menubar.addMenu(t("menu.help"))
        about_action = help_menu.addAction(t("menu.help.about"))
        about_action.triggered.connect(self._show_about)

    def _setup_statusbar(self):
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(t("status.ready"))

    def _open_repo(self, path: str):
        if path in self._repo_tabs:
            # Switch to existing tab
            idx = self._repo_tabs[path]
            if self._tabs.parent() is self._splitter:
                self._tabs.setCurrentIndex(idx)
            return

        try:
            tab = RepoTab(path)
        except Exception:
            return  # Error already shown in RepoTab constructor

        tab.status_message.connect(self._status.showMessage)
        tab.title_changed.connect(lambda t, p=path: self._update_tab_title(p, t))

        if self._placeholder.parent() is self._splitter:
            idx = self._splitter.indexOf(self._placeholder)
            self._placeholder.setParent(None)
            self._splitter.insertWidget(idx, self._tabs)
            self._splitter.setSizes([200, 1080])

        repo_name = os.path.basename(path)
        tab_idx = self._tabs.addTab(tab, repo_name)
        self._tabs.setCurrentIndex(tab_idx)
        self._repo_tabs[path] = tab_idx

    def _update_tab_title(self, path: str, title: str):
        if path in self._repo_tabs:
            idx = self._repo_tabs[path]
            self._tabs.setTabText(idx, title)

    def _close_tab(self, index: int):
        widget = self._tabs.widget(index)
        # Find path for this tab
        path_to_remove = None
        for path, idx in self._repo_tabs.items():
            if idx == index:
                path_to_remove = path
                break

        self._tabs.removeTab(index)
        if path_to_remove:
            del self._repo_tabs[path_to_remove]

        # Rebuild index map
        new_map = {}
        for path, idx in self._repo_tabs.items():
            new_idx = idx if idx < index else idx - 1
            new_map[path] = new_idx
        self._repo_tabs = new_map

        if self._tabs.count() == 0:
            idx = self._splitter.indexOf(self._tabs)
            self._tabs.setParent(None)
            self._splitter.insertWidget(idx, self._placeholder)
            self._splitter.setSizes([200, 1080])

    def _on_open(self):
        path = QFileDialog.getExistingDirectory(
            self, "Open Repository", os.path.expanduser("~")
        )
        if path:
            self._bookmarks.add_repo(path)

    def _on_clone(self):
        dlg = CloneDialog(self)
        if dlg.exec():
            path = dlg.result_path()
            if path:
                self._bookmarks.add_repo(path)

    def _refresh_current(self):
        current = self._tabs.currentWidget()
        if isinstance(current, RepoTab):
            current._refresh_all()

    def _on_accounts(self):
        AccountsDialog(self).exec()

    def _on_ssh_settings(self):
        SSHSettingsDialog(self).exec()

    def _on_identity(self):
        current = self._tabs.currentWidget()
        repo = current._repo if isinstance(current, RepoTab) else None
        IdentityDialog(repo, self).exec()

    def _on_language(self):
        LanguageDialog(self).exec()

    def _show_about(self):
        QMessageBox.about(self, t("about.title"), t("about.text"))
