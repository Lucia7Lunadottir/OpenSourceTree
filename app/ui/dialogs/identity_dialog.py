from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QLineEdit, QCheckBox, QPushButton, QLabel,
    QDialogButtonBox, QMessageBox, QGroupBox, QComboBox
)
from PyQt6.QtCore import Qt

from app.git.repo import GitRepo
from app.config import load_accounts
from app.i18n import t


class IdentityDialog(QDialog):
    """Configure git user.name and user.email (global or per-repo)."""

    def __init__(self, repo: GitRepo | None = None, parent=None):
        super().__init__(parent)
        self._repo = repo
        self.setWindowTitle(t("identity.title"))
        self.setMinimumWidth(440)
        self._setup_ui()
        self._load_current()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Scope selector
        scope_row = QHBoxLayout()
        scope_label = QLabel(t("identity.scope_label"))
        self._global_check = QCheckBox(t("identity.scope_global"))
        self._global_check.setChecked(True)
        self._global_check.stateChanged.connect(self._on_scope_changed)
        scope_row.addWidget(scope_label)
        scope_row.addWidget(self._global_check)
        scope_row.addStretch()
        layout.addLayout(scope_row)

        if self._repo is None:
            self._global_check.setChecked(True)
            self._global_check.setEnabled(False)

        # Global identity group
        self._global_group = QGroupBox(t("identity.group_global"))
        gf = QFormLayout(self._global_group)
        self._global_name = QLineEdit()
        self._global_name.setPlaceholderText(t("identity.field_name_placeholder"))
        gf.addRow(t("identity.field_name"), self._global_name)
        self._global_email = QLineEdit()
        self._global_email.setPlaceholderText(t("identity.field_email_placeholder"))
        gf.addRow(t("identity.field_email"), self._global_email)
        layout.addWidget(self._global_group)

        # Per-repo group (shown only when repo is set and scope is local)
        if self._repo is not None:
            self._repo_group = QGroupBox(t("identity.group_repo", name=self._repo.get_repo_name()))
            rf = QFormLayout(self._repo_group)

            self._override_check = QCheckBox(t("identity.override_check"))
            self._override_check.stateChanged.connect(self._on_override_changed)
            rf.addRow("", self._override_check)

            self._repo_name = QLineEdit()
            self._repo_name.setPlaceholderText(t("identity.repo_name_placeholder"))
            self._repo_name.setEnabled(False)
            rf.addRow(t("identity.field_name"), self._repo_name)

            self._repo_email = QLineEdit()
            self._repo_email.setPlaceholderText(t("identity.repo_name_placeholder"))
            self._repo_email.setEnabled(False)
            rf.addRow(t("identity.field_email"), self._repo_email)

            layout.addWidget(self._repo_group)

        # Fill from account
        accounts = load_accounts()
        if accounts:
            fill_group = QGroupBox(t("identity.group_fill"))
            fl = QFormLayout(fill_group)
            self._account_combo = QComboBox()
            self._account_combo.addItem(t("identity.account_placeholder"), None)
            for acc in accounts:
                label = acc.label or acc.username or acc.email
                self._account_combo.addItem(label, acc)
            fill_btn = QPushButton(t("identity.btn_fill"))
            fill_btn.clicked.connect(self._fill_from_account)
            row = QHBoxLayout()
            row.addWidget(self._account_combo)
            row.addWidget(fill_btn)
            fl.addRow(t("identity.field_account"), row)
            layout.addWidget(fill_group)

        hint = QLabel(t("identity.hint"))
        hint.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        layout.addWidget(hint)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Save).setText(t("identity.btn_save"))
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

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

        self._global_name.setText(g_name)
        self._global_email.setText(g_email)

        if self._repo is not None:
            l_name, l_email = self._repo.get_identity(global_=False)
            has_local = bool(l_name or l_email)
            self._override_check.setChecked(has_local)
            self._repo_name.setText(l_name)
            self._repo_email.setText(l_email)
            self._repo_name.setEnabled(has_local)
            self._repo_email.setEnabled(has_local)

    def _on_scope_changed(self):
        pass   # both groups always visible

    def _on_override_changed(self, state):
        enabled = bool(state)
        self._repo_name.setEnabled(enabled)
        self._repo_email.setEnabled(enabled)
        if not enabled:
            self._repo_name.clear()
            self._repo_email.clear()

    def _fill_from_account(self):
        acc = self._account_combo.currentData()
        if acc is None:
            return
        if acc.username:
            self._global_name.setText(acc.username)
        if acc.email:
            self._global_email.setText(acc.email)

    def _save(self):
        g_name  = self._global_name.text().strip()
        g_email = self._global_email.text().strip()

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

        if self._repo is not None and hasattr(self, "_override_check"):
            if self._override_check.isChecked():
                r_name  = self._repo_name.text().strip()
                r_email = self._repo_email.text().strip()
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
