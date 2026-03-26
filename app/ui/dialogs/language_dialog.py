from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout,
    QComboBox, QLabel, QDialogButtonBox
)

from app.i18n import t, available_languages, current_language
from app.config import set_language


class LanguageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("dialog.language.title"))
        self.setMinimumWidth(340)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        self._combo = QComboBox()
        current = current_language()
        for i, (code, name) in enumerate(available_languages()):
            self._combo.addItem(name, code)
            if code == current:
                self._combo.setCurrentIndex(i)
        form.addRow(t("dialog.language.label"), self._combo)
        layout.addLayout(form)

        hint = QLabel(t("dialog.language.restart"))
        hint.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _save(self):
        code = self._combo.currentData()
        if code:
            set_language(code)
        self.accept()
