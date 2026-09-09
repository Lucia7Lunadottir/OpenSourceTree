from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QToolButton, QSizePolicy
from PyQt6.QtCore import pyqtSignal

from app.i18n import t
from app.git.trailers import parse_co_authors


class CoAuthorsBar(QWidget):
    """Shows Co-authored-by trailers found in a commit message as removable
    chips, plus a button to add a new one. Purely a view: it never edits the
    commit message text itself — callers apply add_requested/remove_requested
    to their own text buffer and call sync() with the result, keeping the
    message text as the single source of truth.
    """

    add_requested = pyqtSignal()
    remove_requested = pyqtSignal(str)  # email

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

        self._add_btn = QToolButton()
        self._add_btn.setText(t("coauthors.add_btn"))
        self._add_btn.setObjectName("smallBtn")
        self._add_btn.clicked.connect(self.add_requested)
        self._layout.addWidget(self._add_btn)
        self._layout.addStretch()

        self._chip_widgets: list[QWidget] = []

    def sync(self, message: str) -> None:
        """Rebuild chips from the Co-authored-by trailers in `message`."""
        for w in self._chip_widgets:
            self._layout.removeWidget(w)
            w.deleteLater()
        self._chip_widgets.clear()

        for name, email in parse_co_authors(message):
            chip = self._make_chip(name, email)
            self._layout.insertWidget(self._layout.count() - 2, chip)
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
