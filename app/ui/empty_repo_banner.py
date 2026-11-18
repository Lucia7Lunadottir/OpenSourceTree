from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton
from PyQt6.QtCore import pyqtSignal

from app.i18n import t
from app.git.remote_attach import EmptyRepoState
from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("empty_repo_banner.ui")


class EmptyRepoBanner(QFrame):
    """Strip above the commit list of a repository without commits: says what to
    do next and offers the one fitting action. It only shows; what the button
    does is up to EmptyRepoController.

    Static layout lives in empty_repo_banner.ui; the form's objectName
    "conflictBanner" reuses the existing warning style from style.qss.
    """
    action_requested = pyqtSignal()

    # widgets created by loadUi from empty_repo_banner.ui
    iconLabel: QLabel
    messageLabel: QLabel
    actionButton: QPushButton

    # state -> (message key, button key); no button key = advice only
    _TEXTS = {
        EmptyRepoState.NO_REMOTE: ("empty_repo.no_remote", "empty_repo.btn.connect"),
        EmptyRepoState.NEEDS_FETCH: ("empty_repo.needs_fetch", "empty_repo.btn.fetch"),
        EmptyRepoState.REMOTE_HAS_HISTORY: ("empty_repo.has_history", "empty_repo.btn.attach"),
        EmptyRepoState.REMOTE_EMPTY: ("empty_repo.remote_empty", None),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)
        self.actionButton.clicked.connect(self.action_requested)
        self.hide()

    def show_state(self, state: EmptyRepoState, remote: str = "", ref: str = ""):
        message_key, button_key = self._TEXTS[state]
        self.messageLabel.setText(t(message_key, remote=remote, ref=ref))
        self.actionButton.setVisible(button_key is not None)
        if button_key:
            self.actionButton.setText(t(button_key, remote=remote, ref=ref))
        self.show()

    def hide_banner(self):
        self.hide()
