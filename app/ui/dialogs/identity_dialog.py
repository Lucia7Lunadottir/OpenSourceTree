from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QLineEdit, QCheckBox, QPushButton, QLabel,
    QDialogButtonBox, QMessageBox, QGroupBox, QComboBox
)

from app.git.repo import GitRepo
from app.config import load_accounts
from app.i18n import t
from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("identity_dialog.ui")


class IdentityDialog(QDialog):
    """Configure git user.name and user.email (global or per-repo)."""

    # widgets created by loadUi from identity_dialog.ui
    globalCheck: QCheckBox
    globalGroup: QGroupBox
    globalNameEdit: QLineEdit
    globalEmailEdit: QLineEdit
    repoGroup: QGroupBox
    overrideCheck: QCheckBox
    repoNameEdit: QLineEdit
    repoEmailEdit: QLineEdit
    fillGroup: QGroupBox
    accountCombo: QComboBox
    fillButton: QPushButton
    hintLabel: QLabel
    buttonBox: QDialogButtonBox

    def __init__(self, repo: GitRepo | None = None, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._setup_ui()
        self._load_current()

    def _setup_ui(self):
        uic.loadUi(_UI_FILE, self)
        repo_args = {"name": self._repo.get_repo_name()} if self._repo is not None else {}
        UiTranslator({"repoGroup": repo_args}).apply(self)

        self.globalCheck.stateChanged.connect(self._on_scope_changed)
        if self._repo is None:
            self.globalCheck.setChecked(True)
            self.globalCheck.setEnabled(False)
            # Per-repo group is shown only when a repo is set
            self.repoGroup.hide()
        else:
            self.overrideCheck.stateChanged.connect(self._on_override_changed)

        # Fill from account
        accounts = load_accounts()
        if accounts:
            self.accountCombo.addItem(t("identity.account_placeholder"), None)
            for acc in accounts:
                label = acc.label or acc.username or acc.email
                self.accountCombo.addItem(label, acc)
            self.fillButton.clicked.connect(self._fill_from_account)
        else:
            self.fillGroup.hide()

        self.buttonBox.button(QDialogButtonBox.StandardButton.Save).setText(t("identity.btn_save"))
        self.buttonBox.accepted.connect(self._save)
        self.buttonBox.rejected.connect(self.reject)
        # Fit the height to the groups actually shown (independent of the .ui geometry)
        self.adjustSize()

    def _load_current(self):
        # Always show global values
        if self._repo:
            g_name, g_email = self._repo.get_identity(global_=True)
        else:
            # No repo: use a temp runner pointing to home
            import subprocess
            def _git_global(key):
                try:
                    return subprocess.run(
                        ["git", "config", "--global", key],
                        capture_output=True, text=True
                    ).stdout.strip()
                except Exception:
                    return ""
            g_name  = _git_global("user.name")
            g_email = _git_global("user.email")

        self.globalNameEdit.setText(g_name)
        self.globalEmailEdit.setText(g_email)

        if self._repo is not None:
            l_name, l_email = self._repo.get_identity(global_=False)
            has_local = bool(l_name or l_email)
            self.overrideCheck.setChecked(has_local)
            self.repoNameEdit.setText(l_name)
            self.repoEmailEdit.setText(l_email)
            self.repoNameEdit.setEnabled(has_local)
            self.repoEmailEdit.setEnabled(has_local)

    def _on_scope_changed(self):
        pass   # both groups always visible

    def _on_override_changed(self, state):
        enabled = bool(state)
        self.repoNameEdit.setEnabled(enabled)
        self.repoEmailEdit.setEnabled(enabled)
        if not enabled:
            self.repoNameEdit.clear()
            self.repoEmailEdit.clear()

    def _fill_from_account(self):
        acc = self.accountCombo.currentData()
        if acc is None:
            return
        if acc.username:
            self.globalNameEdit.setText(acc.username)
        if acc.email:
            self.globalEmailEdit.setText(acc.email)

    def _save(self):
        g_name  = self.globalNameEdit.text().strip()
        g_email = self.globalEmailEdit.text().strip()

        if not g_name or not g_email:
            QMessageBox.warning(self, t("identity.error.title"), t("identity.error.empty"))
            return

        errors = []
        try:
            if self._repo:
                self._repo.set_identity(g_name, g_email, global_=True)
            else:
                import subprocess
                subprocess.run(["git", "config", "--global", "user.name",  g_name],  check=True)
                subprocess.run(["git", "config", "--global", "user.email", g_email], check=True)
        except Exception as e:
            errors.append(t("identity.error.global_prefix", error=str(e)))

        if self._repo is not None:
            if self.overrideCheck.isChecked():
                r_name  = self.repoNameEdit.text().strip()
                r_email = self.repoEmailEdit.text().strip()
                try:
                    self._repo.set_identity(r_name, r_email, global_=False)
                except Exception as e:
                    errors.append(t("identity.error.repo_prefix", error=str(e)))
            else:
                # Remove local overrides if they exist
                try:
                    self._repo.runner.run(["config", "--unset", "user.name"])
                except Exception:
                    pass
                try:
                    self._repo.runner.run(["config", "--unset", "user.email"])
                except Exception:
                    pass

        if errors:
            QMessageBox.warning(self, t("identity.error.title"), t("identity.error.errors", errors="\n".join(errors)))
        else:
            self.accept()
