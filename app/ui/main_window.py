import os
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QTabWidget, QStatusBar, QMenuBar, QMenu,
    QLabel, QApplication, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QAction

from app.i18n import t

from .bookmarks_panel import BookmarksPanel
from .repo_tab import RepoTab
from .elided_label import ClickableElidedLabel
from .log_panel import LogPanel
from .ui_translator import UiTranslator
from .dialogs.clone_dialog import CloneDialog
from .dialogs.ssh_dialog import SSHSettingsDialog
from .dialogs.accounts_dialog import AccountsDialog
from .dialogs.identity_dialog import IdentityDialog
from .dialogs.language_dialog import LanguageDialog

_UI_FILE = Path(__file__).with_name("main_window.ui")


class MainWindow(QMainWindow):
    # widgets / actions created by loadUi from main_window.ui
    # lower-case objectNames: "centralWidget" / "menuBar" / "statusBar" would
    # shadow the QMainWindow methods of the same name
    centralwidget: QWidget
    mainSplitter: QSplitter
    bookmarksPanel: BookmarksPanel  # promoted widget (no constructor arguments)
    placeholderPage: QWidget
    placeholderLabel: QLabel
    repoTabs: QTabWidget
    menubar: QMenuBar
    menuFile: QMenu
    menuSettings: QMenu
    menuView: QMenu
    menuHelp: QMenu
    statusbar: QStatusBar
    actionOpen: QAction
    actionClone: QAction
    actionQuit: QAction
    actionAccounts: QAction
    actionSsh: QAction
    actionIdentity: QAction
    actionLanguage: QAction
    actionRefresh: QAction
    actionAbout: QAction

    def __init__(self):
        super().__init__()
        self._repo_tabs: dict[str, int] = {}  # path -> tab index
        self._setup_ui()
        self._setup_menu()
        self._setup_statusbar()

    def _setup_ui(self):
        # Static layout (splitter with bookmarks / placeholder / tabs, menu bar,
        # status bar) lives in main_window.ui and is editable in Qt Designer.
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)

        self._splitter = self.mainSplitter
        self._bookmarks = self.bookmarksPanel
        self._placeholder = self.placeholderPage
        self._tabs = self.repoTabs

        # Initially no repository is open: the tab widget waits outside the
        # splitter and the placeholder takes its place (see _open_repo).
        self._tabs.setParent(None)

        self._bookmarks.repo_selected.connect(self._open_repo)
        self._tabs.tabCloseRequested.connect(self._close_tab)

        self._splitter.setSizes([200, 1080])   # not stored by Designer

    def _setup_menu(self):
        # Designer stores shortcuts as fixed key strings; the platform's
        # standard Open / Quit bindings can only be set from code.
        self.actionOpen.setShortcut(QKeySequence.StandardKey.Open)
        self.actionQuit.setShortcut(QKeySequence.StandardKey.Quit)

        triggers = {
            self.actionOpen: self._on_open,
            self.actionClone: self._on_clone,
            self.actionQuit: QApplication.instance().quit,
            self.actionAccounts: self._on_accounts,
            self.actionSsh: self._on_ssh_settings,
            self.actionIdentity: self._on_identity,
            self.actionLanguage: self._on_language,
            self.actionRefresh: self._refresh_current,
            self.actionAbout: self._show_about,
        }
        for action, slot in triggers.items():
            action.triggered.connect(slot)

    def _setup_statusbar(self):
        self._status = self.statusbar
        # Elided + clickable: a long message must not widen the window; a click
        # opens the log panel with the full history. Built in code: a promoted
        # ClickableElidedLabel would get the parent as its `text` argument.
        self._status_label = ClickableElidedLabel(t("status.ready"))
        self._status_label.clicked.connect(self._toggle_log_panel)
        self._status.addWidget(self._status_label, 1)

        # LogPanel is its own .ui form (a QDockWidget with a body widget);
        # embedded in this .ui, Designer would add a contents widget that
        # loadUi then sets over the panel's own body.
        self._log_panel = LogPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_panel)
        self._log_panel.hide()

    def _show_status(self, message: str):
        self._status_label.set_full_text(message)
        self._log_panel.append_message(message)

    def _toggle_log_panel(self):
        self._log_panel.setVisible(not self._log_panel.isVisible())

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

        tab.status_message.connect(self._show_status)
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
