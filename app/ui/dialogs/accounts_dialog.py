import os
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QSplitter, QListWidget, QListWidgetItem, QWidget, QLabel,
    QLineEdit, QComboBox, QPushButton, QDialogButtonBox, QMessageBox,
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QIcon

from app.config import (
    Account, PROVIDERS, load_accounts, save_accounts, fetch_avatar,
    AVATARS_DIR
)
from app.i18n import t
from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("accounts_dialog.ui")


# ── Avatar fetcher thread ─────────────────────────────────────────────────────

class AvatarFetcher(QThread):
    done = pyqtSignal(str, str)   # account_id, local_path

    def __init__(self, account: Account):
        super().__init__()
        self._account = account

    def run(self):
        path = fetch_avatar(self._account)
        self.done.emit(self._account.id, path)


# ── List item ────────────────────────────────────────────────────────────────

class AccountItem(QListWidgetItem):
    ICON_SIZE = 40

    def __init__(self, account: Account):
        super().__init__()
        self.account = account
        self.setSizeHint(QSize(0, 52))
        self.refresh()

    def refresh(self):
        acc = self.account
        provider_label = PROVIDERS.get(acc.provider, {}).get("label", acc.provider)
        name = acc.label or acc.username or t("accounts.no_name")
        self.setText(f"{name}\n{provider_label}  •  {acc.host or '—'}")
        self._load_avatar()

    def _load_avatar(self):
        p = self.account.avatar_path
        if p and Path(p).exists():
            pix = QPixmap(p).scaled(
                self.ICON_SIZE, self.ICON_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setIcon(QIcon(pix))
        else:
            self.setIcon(QIcon())


# ── Main Dialog ───────────────────────────────────────────────────────────────

class AccountsDialog(QDialog):
    # widgets created by loadUi from accounts_dialog.ui
    splitter: QSplitter
    accountList: QListWidget
    addButton: QPushButton
    removeButton: QPushButton
    editorPanel: QWidget
    labelEdit: QLineEdit
    providerCombo: QComboBox
    hostEdit: QLineEdit
    apiUrlEdit: QLineEdit
    userEdit: QLineEdit
    emailEdit: QLineEdit
    tokenEdit: QLineEdit
    showTokenButton: QPushButton
    avatarLabel: QLabel
    fetchAvatarButton: QPushButton
    testButton: QPushButton
    testResultLabel: QLabel
    buttonBox: QDialogButtonBox

    def __init__(self, parent=None):
        super().__init__(parent)
        self._accounts: list[Account] = load_accounts()
        self._current_idx = -1
        self._dirty = False
        self._fetchers: list[AvatarFetcher] = []
        self._setup_ui()
        self._populate_list()
        if self._accounts:
            self.accountList.setCurrentRow(0)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)

        self.accountList.setIconSize(QSize(AccountItem.ICON_SIZE, AccountItem.ICON_SIZE))
        self.accountList.currentRowChanged.connect(self._on_selected)
        self.addButton.clicked.connect(self._add_account)
        self.removeButton.clicked.connect(self._remove_account)

        for key, val in PROVIDERS.items():
            self.providerCombo.addItem(val["label"], key)

        self.showTokenButton.toggled.connect(
            lambda on: self.tokenEdit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        self.fetchAvatarButton.clicked.connect(self._fetch_avatar)
        self.testButton.clicked.connect(self._test_token)
        self.splitter.setSizes([230, 570])

        self.buttonBox.button(QDialogButtonBox.StandardButton.Save).setText(t("accounts.btn_save"))
        self.buttonBox.accepted.connect(self._save_all)
        self.buttonBox.rejected.connect(self.reject)

        # Auto-fill host/api_url when provider changes
        self.providerCombo.currentIndexChanged.connect(self._on_provider_changed)
        for w in (self.labelEdit, self.hostEdit, self.apiUrlEdit,
                  self.userEdit, self.emailEdit, self.tokenEdit):
            w.textChanged.connect(self._mark_dirty)

    # ── List ──────────────────────────────────────────────────────────────────

    def _populate_list(self):
        self.accountList.clear()
        for acc in self._accounts:
            self.accountList.addItem(AccountItem(acc))

    def _on_selected(self, row: int):
        if self._dirty and self._current_idx >= 0:
            self._flush(self._current_idx)
        self._current_idx = row
        self.editorPanel.setEnabled(row >= 0)
        self.removeButton.setEnabled(row >= 0)
        if row < 0 or row >= len(self._accounts):
            return
        acc = self._accounts[row]

        for w in (self.labelEdit, self.hostEdit, self.apiUrlEdit,
                  self.userEdit, self.emailEdit, self.tokenEdit,
                  self.providerCombo):
            w.blockSignals(True)

        self.labelEdit.setText(acc.label)
        self.hostEdit.setText(acc.host)
        self.apiUrlEdit.setText(acc.api_url)
        self.userEdit.setText(acc.username)
        self.emailEdit.setText(acc.email)
        self.tokenEdit.setText(acc.token)
        idx = self.providerCombo.findData(acc.provider)
        self.providerCombo.setCurrentIndex(idx if idx >= 0 else 0)

        for w in (self.labelEdit, self.hostEdit, self.apiUrlEdit,
                  self.userEdit, self.emailEdit, self.tokenEdit,
                  self.providerCombo):
            w.blockSignals(False)

        self._refresh_avatar_display(acc)
        self.testResultLabel.setText("")
        self._dirty = False

    def _mark_dirty(self):
        self._dirty = True
        if self._current_idx >= 0:
            self._flush(self._current_idx)
            item = self.accountList.item(self._current_idx)
            if isinstance(item, AccountItem):
                item.refresh()

    def _flush(self, idx: int):
        if idx < 0 or idx >= len(self._accounts):
            return
        acc = self._accounts[idx]
        acc.label    = self.labelEdit.text().strip()
        acc.provider = self.providerCombo.currentData() or "custom"
        acc.host     = self.hostEdit.text().strip()
        acc.api_url  = self.apiUrlEdit.text().strip()
        acc.username = self.userEdit.text().strip()
        acc.email    = self.emailEdit.text().strip()
        acc.token    = self.tokenEdit.text().strip()

    def _on_provider_changed(self):
        key = self.providerCombo.currentData()
        info = PROVIDERS.get(key, {})
        if info.get("host") and not self.hostEdit.text():
            self.hostEdit.blockSignals(True)
            self.hostEdit.setText(info["host"])
            self.hostEdit.blockSignals(False)
        if info.get("api_url") and not self.apiUrlEdit.text():
            self.apiUrlEdit.blockSignals(True)
            self.apiUrlEdit.setText(info["api_url"])
            self.apiUrlEdit.blockSignals(False)
        self._mark_dirty()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _add_account(self):
        if self._dirty and self._current_idx >= 0:
            self._flush(self._current_idx)
        acc = Account(label=t("accounts.new_account"))
        self._accounts.append(acc)
        self.accountList.addItem(AccountItem(acc))
        self.accountList.setCurrentRow(len(self._accounts) - 1)

    def _remove_account(self):
        row = self.accountList.currentRow()
        if row < 0:
            return
        name = self._accounts[row].label or t("accounts.account_no_name")
        ret = QMessageBox.question(
            self, t("accounts.confirm_remove.title"), t("accounts.confirm_remove.text", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self._accounts.pop(row)
            self._populate_list()
            self._current_idx = -1
            self._dirty = False
            new_row = min(row, len(self._accounts) - 1)
            if new_row >= 0:
                self.accountList.setCurrentRow(new_row)
            else:
                self.editorPanel.setEnabled(False)

    # ── Avatar ────────────────────────────────────────────────────────────────

    def _fetch_avatar(self):
        if self._current_idx < 0:
            return
        self._flush(self._current_idx)
        acc = self._accounts[self._current_idx]
        if not acc.username:
            self.testResultLabel.setText(t("accounts.avatar_no_login"))
            return
        self.fetchAvatarButton.setEnabled(False)
        self.fetchAvatarButton.setText(t("accounts.btn_fetching_avatar"))
        fetcher = AvatarFetcher(acc)
        fetcher.done.connect(self._on_avatar_fetched)
        self._fetchers.append(fetcher)
        fetcher.start()

    def _on_avatar_fetched(self, account_id: str, path: str):
        for i, acc in enumerate(self._accounts):
            if acc.id == account_id:
                acc.avatar_path = path
                item = self.accountList.item(i)
                if isinstance(item, AccountItem):
                    item.account.avatar_path = path
                    item.refresh()
                if i == self._current_idx:
                    self._refresh_avatar_display(acc)
                break
        self.fetchAvatarButton.setEnabled(True)
        self.fetchAvatarButton.setText(t("accounts.btn_fetch_avatar"))
        if not path:
            self.testResultLabel.setText(t("accounts.avatar_load_error"))

    def _refresh_avatar_display(self, acc: Account):
        p = acc.avatar_path
        if p and Path(p).exists():
            pix = QPixmap(p).scaled(
                64, 64,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.avatarLabel.setPixmap(pix)
            self.avatarLabel.setText("")
        else:
            self.avatarLabel.setPixmap(QPixmap())
            self.avatarLabel.setText("?")

    # ── Token test ────────────────────────────────────────────────────────────

    def _test_token(self):
        if self._current_idx >= 0:
            self._flush(self._current_idx)
        row = self.accountList.currentRow()
        if row < 0:
            return
        acc = self._accounts[row]
        if not acc.token:
            self.testResultLabel.setText(t("accounts.test_no_token"))
            return

        import urllib.request, json
        api_url = acc.api_url or PROVIDERS.get(acc.provider, {}).get("api_url", "")
        if not api_url:
            self.testResultLabel.setText(t("accounts.test_no_api"))
            return

        self.testButton.setEnabled(False)
        self.testResultLabel.setText(t("accounts.test_checking"))

        try:
            headers = {
                "Authorization": f"Bearer {acc.token}",
                "User-Agent": "OpenSourceTree/0.1",
            }
            if acc.provider == "github":
                url = f"{api_url}/user"
            elif acc.provider == "gitlab":
                url = f"{api_url}/user"
            else:
                url = f"{api_url}/user"

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())

            login = data.get("login") or data.get("username") or data.get("name", "?")
            self.testResultLabel.setText(t("accounts.test_success", login=login))
            # Update username if empty
            if not acc.username:
                acc.username = login
                self.userEdit.setText(login)
        except Exception as e:
            self.testResultLabel.setText(t("accounts.test_error", error=str(e)))
        finally:
            self.testButton.setEnabled(True)

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save_all(self):
        if self._dirty and self._current_idx >= 0:
            self._flush(self._current_idx)
        save_accounts(self._accounts)
        self.accept()
