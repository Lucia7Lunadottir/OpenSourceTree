from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QDialogButtonBox, QMessageBox
)

from app.i18n import t


class AddCoAuthorDialog(QDialog):
    """Prompt for a Co-authored-by name + email pair."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("coauthors.add_dialog.title"))
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(t("coauthors.add_dialog.name_placeholder"))
        form.addRow(t("coauthors.add_dialog.name_label"), self._name_edit)

        self._email_edit = QLineEdit()
        self._email_edit.setPlaceholderText(t("coauthors.add_dialog.email_placeholder"))
        form.addRow(t("coauthors.add_dialog.email_label"), self._email_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        if not self.name.strip() or "@" not in self.email:
            QMessageBox.warning(
                self, t("coauthors.add_dialog.title"), t("coauthors.add_dialog.invalid")
            )
            return
        self.accept()

    @property
    def name(self) -> str:
        return self._name_edit.text().strip()

    @property
    def email(self) -> str:
        return self._email_edit.text().strip()
