from datetime import datetime
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QDockWidget, QWidget, QPlainTextEdit, QPushButton
from PyQt6.QtGui import QFont

from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("log_panel.ui")


class LogPanel(QDockWidget):
    """Bottom panel with the history of status-bar messages (full text)."""

    MAX_BLOCKS = 2000

    # widgets created by loadUi from log_panel.ui
    body: QWidget
    logText: QPlainTextEdit
    clearButton: QPushButton

    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)
        # setWidget() inside loadUi already measured the button row with the
        # raw key text; re-activate so the nested layout drops that cached
        # minimum and the dock's minimum size matches the translated text.
        self.body.layout().activate()

        # Not expressible in .ui: the block limit comes from MAX_BLOCKS, and
        # Designer's <font> has no style hint (TypeWriter = monospace fallback).
        self.logText.setMaximumBlockCount(self.MAX_BLOCKS)
        font = self.logText.font()
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.logText.setFont(font)

        self.clearButton.clicked.connect(self.logText.clear)

    def append_message(self, message: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.logText.appendPlainText(f"[{stamp}] {message.strip()}")
        bar = self.logText.verticalScrollBar()
        bar.setValue(bar.maximum())
