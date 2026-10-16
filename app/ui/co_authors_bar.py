from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QToolButton, QSizePolicy
from PyQt6.QtCore import pyqtSignal

from app.i18n import t
from app.git.trailers import parse_co_authors
from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("co_authors_bar.ui")


class CoAuthorsBar(QWidget):
    """Shows Co-authored-by trailers found in a commit message as removable
    chips, plus a button to add a new one. Purely a view: it never edits the
    commit message text itself — callers apply add_requested/remove_requested
    to their own text buffer and call sync() with the result, keeping the
    message text as the single source of truth.

    The static frame (add button + trailing spacer) lives in co_authors_bar.ui;
    chips depend on the message and are built in code.
    """

    add_requested = pyqtSignal()
    remove_requested = pyqtSignal(str)  # email

    # widgets created by loadUi from co_authors_bar.ui
    chipsLayout: QHBoxLayout
    smallBtn: QToolButton   # "+ Co-author"; objectName is a style.qss selector

    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)
        self.smallBtn.clicked.connect(self.add_requested)

        self._chip_widgets: list[QWidget] = []

    def sync(self, message: str) -> None:
        """Rebuild chips from the Co-authored-by trailers in `message`."""
        for w in self._chip_widgets:
            self.chipsLayout.removeWidget(w)
            w.deleteLater()
        self._chip_widgets.clear()

        for name, email in parse_co_authors(message):
            chip = self._make_chip(name, email)
            # chips go before the add button and the trailing spacer
            self.chipsLayout.insertWidget(self.chipsLayout.count() - 2, chip)
            self._chip_widgets.append(chip)

    def _make_chip(self, name: str, email: str) -> QWidget:
        chip = QWidget()
        chip.setObjectName("coAuthorChip")
        row = QHBoxLayout(chip)
        row.setContentsMargins(8, 2, 4, 2)
        row.setSpacing(4)

        label = QLabel(name or email)
        label.setToolTip(f"{name} <{email}>")
        row.addWidget(label)

        remove_btn = QToolButton()
        remove_btn.setText("×")
        remove_btn.setObjectName("coAuthorRemoveBtn")
        remove_btn.setToolTip(t("coauthors.remove_btn"))
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(email))
        row.addWidget(remove_btn)

        chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return chip
