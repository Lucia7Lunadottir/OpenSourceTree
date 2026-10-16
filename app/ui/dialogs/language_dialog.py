from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QDialog, QComboBox, QDialogButtonBox

from app.i18n import available_languages, current_language
from app.config import set_language
from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("language_dialog.ui")


class LanguageDialog(QDialog):
    # widgets created by loadUi from language_dialog.ui
    languageCombo: QComboBox
    buttonBox: QDialogButtonBox

    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)

        self.buttonBox.accepted.connect(self._save)
        self.buttonBox.rejected.connect(self.reject)

        self._populate()

    def _populate(self):
        current = current_language()
        for i, (code, name) in enumerate(available_languages()):
            self.languageCombo.addItem(name, code)
            if code == current:
                self.languageCombo.setCurrentIndex(i)

    def _save(self):
        code = self.languageCombo.currentData()
        if code:
            set_language(code)
        self.accept()
