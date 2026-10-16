from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton
from PyQt6.QtCore import pyqtSignal

from app.i18n import t
from app.constants import HUGE_DIFF_BYTES
from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("large_file_banner.ui")


def format_size(size: int) -> str:
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.1f} GB"
    return f"{size / 1024 ** 2:.1f} MB"


class LargeFileBanner(QFrame):
    """Warning strip above the diff: "this file is large, open it fully?".

    Static layout lives in large_file_banner.ui; the form's objectName
    "conflictBanner" reuses the existing warning style from style.qss.
    """
    open_requested = pyqtSignal()

    # widgets created by loadUi from large_file_banner.ui
    iconLabel: QLabel
    messageLabel: QLabel
    openButton: QPushButton

    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)
        self.openButton.clicked.connect(self.open_requested)
        self.hide()

    def show_for(self, size: int):
        key = "diff.huge.warning" if size >= HUGE_DIFF_BYTES else "diff.large.warning"
        self.messageLabel.setText(t(key, size=format_size(size)))
        self.openButton.setEnabled(True)
        self.show()

    def set_loading(self):
        self.openButton.setEnabled(False)

    def hide_banner(self):
        self.hide()
