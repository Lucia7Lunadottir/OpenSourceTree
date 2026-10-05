from datetime import datetime

from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from app.i18n import t


class LogPanel(QDockWidget):
    """Bottom panel with the history of status-bar messages (full text)."""

    MAX_BLOCKS = 2000

    def __init__(self, parent=None):
        super().__init__(t("log.title"), parent)
        self.setObjectName("logPanel")
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(self.MAX_BLOCKS)
        font = QFont("Monospace", 10)
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self._text.setFont(font)
        self._text.setMinimumWidth(0)
        layout.addWidget(self._text, 1)

        row = QHBoxLayout()
        row.addStretch()
        clear_btn = QPushButton(t("log.clear"))
        clear_btn.clicked.connect(self._text.clear)
        row.addWidget(clear_btn)
        layout.addLayout(row)

        self.setWidget(body)
        self.setMinimumWidth(0)
        self.setMinimumHeight(90)

    def append_message(self, message: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self._text.appendPlainText(f"[{stamp}] {message.strip()}")
        bar = self._text.verticalScrollBar()
        bar.setValue(bar.maximum())
