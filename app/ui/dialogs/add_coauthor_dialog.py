from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QDialog, QLineEdit, QDialogButtonBox, QMessageBox

from app.i18n import t
from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("add_coauthor_dialog.ui")


class AddCoAuthorDialog(QDialog):
    """Prompt for a Co-authored-by name + email pair."""

    # widgets created by loadUi from add_coauthor_dialog.ui
    nameEdit: QLineEdit
    emailEdit: QLineEdit
    buttonBox: QDialogButtonBox

    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)

        self.buttonBox.accepted.connect(self._on_accept)
        self.buttonBox.rejected.connect(self.reject)

    def _on_accept(self):
        if not self.name.strip() or "@" not in self.email:
            QMessageBox.warning(
                self, t("coauthors.add_dialog.title"), t("coauthors.add_dialog.invalid")
            )
            return
        self.accept()

    @property
    def name(self) -> str:
        return self.nameEdit.text().strip()

    @property
    def email(self) -> str:
        return self.emailEdit.text().strip()
