from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import pyqtSignal

from app.i18n import t
from app.constants import HUGE_DIFF_BYTES


def format_size(size: int) -> str:
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.1f} GB"
    return f"{size / 1024 ** 2:.1f} MB"


class LargeFileBanner(QFrame):
    """Warning strip above the diff: "this file is large, open it fully?"."""
    open_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("conflictBanner")  # reuse the existing warning style
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 5, 8, 5)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setMinimumWidth(0)
        self._button = QPushButton(t("diff.large.open"))
        self._button.setFixedHeight(22)
        self._button.clicked.connect(self.open_requested)
        row.addWidget(QLabel("⚠"))
        row.addWidget(self._label, 1)
        row.addWidget(self._button)
        self.hide()

    def show_for(self, size: int):
        key = "diff.huge.warning" if size >= HUGE_DIFF_BYTES else "diff.large.warning"
        self._label.setText(t(key, size=format_size(size)))
        self._button.setEnabled(True)
        self.show()

    def set_loading(self):
        self._button.setEnabled(False)

    def hide_banner(self):
        self.hide()
