import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QSplitter,
    QListWidget, QListWidgetItem, QWidget, QLabel, QLineEdit,
    QComboBox, QPushButton, QDialogButtonBox, QMessageBox,
    QAbstractItemView, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QIcon, QColor

from app.config import (
    Account, PROVIDERS, load_accounts, save_accounts, fetch_avatar,
    AVATARS_DIR
)


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
        name = acc.label or acc.username or "(без имени)"
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Аккаунты")
        self.resize(820, 560)
        self._accounts: list[Account] = load_accounts()
        self._current_idx = -1
        self._dirty = False
        self._fetchers: list[AvatarFetcher] = []
        self._setup_ui()
        self._populate_list()
        if self._accounts:
            self._list.setCurrentRow(0)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: account list ──
        left = QWidget()
        left.setFixedWidth(230)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        hdr = QLabel("Аккаунты")
        hdr.setStyleSheet("font-weight: bold; color: rgb(203,166,247);")
        ll.addWidget(hdr)

        self._list = QListWidget()
        self._list.setIconSize(QSize(AccountItem.ICON_SIZE, AccountItem.ICON_SIZE))
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.currentRowChanged.connect(self._on_selected)
        ll.addWidget(self._list)

        add_btn    = QPushButton("+ Добавить")
        self._del_btn = QPushButton("Удалить")
        self._del_btn.setEnabled(False)
        btn_row = QHBoxLayout()
        btn_row.addWidget(add_btn)
        btn_row.addWidget(self._del_btn)
        ll.addLayout(btn_row)
        add_btn.clicked.connect(self._add_account)
        self._del_btn.clicked.connect(self._remove_account)
        splitter.addWidget(left)

        # ── Right: editor ──
        self._editor = QWidget()
        self._editor.setEnabled(False)
        el = QVBoxLayout(self._editor)
        el.setContentsMargins(8, 0, 0, 0)
        el.setSpacing(10)

        form = QFormLayout()

        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("напр. «GitHub Личный»")
        form.addRow("Название:", self._label_edit)

        self._provider_combo = QComboBox()
        for key, val in PROVIDERS.items():
            self._provider_combo.addItem(val["label"], key)
        form.addRow("Провайдер:", self._provider_combo)

        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("github.com")
        form.addRow("Хост:", self._host_edit)

        self._api_url_edit = QLineEdit()
        self._api_url_edit.setPlaceholderText("https://api.github.com  (для self-hosted)")
        form.addRow("API URL:", self._api_url_edit)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("your-login")
        form.addRow("Логин:", self._user_edit)

        self._email_edit = QLineEdit()
        self._email_edit.setPlaceholderText("you@example.com")
        form.addRow("E-mail (для коммитов):", self._email_edit)

        # Token row with show/hide toggle
        token_row = QHBoxLayout()
        self._token_edit = QLineEdit()
        self._token_edit.setPlaceholderText("Personal Access Token (HTTPS)")
        self._token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._show_token_btn = QPushButton("👁")
        self._show_token_btn.setFixedWidth(32)
        self._show_token_btn.setCheckable(True)
        self._show_token_btn.toggled.connect(
            lambda on: self._token_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        token_row.addWidget(self._token_edit)
        token_row.addWidget(self._show_token_btn)
        form.addRow("Токен доступа:", token_row)

        token_hint = QLabel(
            'Создать: GitHub → Settings → Developer settings → Personal access tokens.<br>'
            'Права: <code>repo</code> (для чтения/записи репозиториев).'
        )
        token_hint.setWordWrap(True)
        token_hint.setTextFormat(Qt.TextFormat.RichText)
        token_hint.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        form.addRow("", token_hint)

        el.addLayout(form)

        # Avatar section
        avatar_row = QHBoxLayout()
        self._avatar_label = QLabel()
        self._avatar_label.setFixedSize(64, 64)
        self._avatar_label.setStyleSheet(
            "border: 1px solid rgb(70,55,100); border-radius: 32px; background: rgb(40,36,62);"
        )
        self._avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar_label.setText("?")
        self._fetch_avatar_btn = QPushButton("Загрузить аватар")
        self._fetch_avatar_btn.clicked.connect(self._fetch_avatar)
        avatar_row.addWidget(self._avatar_label)
        avatar_row.addWidget(self._fetch_avatar_btn)
        avatar_row.addStretch()
        el.addLayout(avatar_row)

        # Test button
        self._test_btn = QPushButton("Проверить токен")
        self._test_btn.clicked.connect(self._test_token)
        el.addWidget(self._test_btn)

        self._test_result = QLabel("")
        self._test_result.setWordWrap(True)
        self._test_result.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        el.addWidget(self._test_result)

        el.addStretch()
        splitter.addWidget(self._editor)
        splitter.setSizes([230, 570])
        root.addWidget(splitter)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        btns.accepted.connect(self._save_all)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # Auto-fill host/api_url when provider changes
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        for w in (self._label_edit, self._host_edit, self._api_url_edit,
                  self._user_edit, self._email_edit, self._token_edit):
            w.textChanged.connect(self._mark_dirty)

    # ── List ──────────────────────────────────────────────────────────────────

    def _populate_list(self):
        self._list.clear()
        for acc in self._accounts:
            self._list.addItem(AccountItem(acc))

    def _on_selected(self, row: int):
        if self._dirty and self._current_idx >= 0:
            self._flush(self._current_idx)
        self._current_idx = row
        self._editor.setEnabled(row >= 0)
        self._del_btn.setEnabled(row >= 0)
        if row < 0 or row >= len(self._accounts):
            return
        acc = self._accounts[row]

        for w in (self._label_edit, self._host_edit, self._api_url_edit,
                  self._user_edit, self._email_edit, self._token_edit,
                  self._provider_combo):
            w.blockSignals(True)

        self._label_edit.setText(acc.label)
        self._host_edit.setText(acc.host)
        self._api_url_edit.setText(acc.api_url)
        self._user_edit.setText(acc.username)
        self._email_edit.setText(acc.email)
        self._token_edit.setText(acc.token)
        idx = self._provider_combo.findData(acc.provider)
        self._provider_combo.setCurrentIndex(idx if idx >= 0 else 0)

        for w in (self._label_edit, self._host_edit, self._api_url_edit,
                  self._user_edit, self._email_edit, self._token_edit,
                  self._provider_combo):
            w.blockSignals(False)

        self._refresh_avatar_display(acc)
        self._test_result.setText("")
        self._dirty = False

    def _mark_dirty(self):
        self._dirty = True
        if self._current_idx >= 0:
            self._flush(self._current_idx)
            item = self._list.item(self._current_idx)
            if isinstance(item, AccountItem):
                item.refresh()

    def _flush(self, idx: int):
        if idx < 0 or idx >= len(self._accounts):
            return
        acc = self._accounts[idx]
        acc.label    = self._label_edit.text().strip()
        acc.provider = self._provider_combo.currentData() or "custom"
        acc.host     = self._host_edit.text().strip()
        acc.api_url  = self._api_url_edit.text().strip()
        acc.username = self._user_edit.text().strip()
        acc.email    = self._email_edit.text().strip()
        acc.token    = self._token_edit.text().strip()

    def _on_provider_changed(self):
        key = self._provider_combo.currentData()
        info = PROVIDERS.get(key, {})
        if info.get("host") and not self._host_edit.text():
            self._host_edit.blockSignals(True)
            self._host_edit.setText(info["host"])
            self._host_edit.blockSignals(False)
        if info.get("api_url") and not self._api_url_edit.text():
            self._api_url_edit.blockSignals(True)
            self._api_url_edit.setText(info["api_url"])
            self._api_url_edit.blockSignals(False)
        self._mark_dirty()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _add_account(self):
        if self._dirty and self._current_idx >= 0:
            self._flush(self._current_idx)
        acc = Account(label="Новый аккаунт")
        self._accounts.append(acc)
        self._list.addItem(AccountItem(acc))
        self._list.setCurrentRow(len(self._accounts) - 1)

    def _remove_account(self):
        row = self._list.currentRow()
        if row < 0:
            return
        name = self._accounts[row].label or "аккаунт"
        ret = QMessageBox.question(
            self, "Удалить аккаунт", f"Удалить «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self._accounts.pop(row)
            self._populate_list()
            self._current_idx = -1
            self._dirty = False
            new_row = min(row, len(self._accounts) - 1)
            if new_row >= 0:
                self._list.setCurrentRow(new_row)
            else:
                self._editor.setEnabled(False)

    # ── Avatar ────────────────────────────────────────────────────────────────

    def _fetch_avatar(self):
        if self._current_idx < 0:
            return
        self._flush(self._current_idx)
        acc = self._accounts[self._current_idx]
        if not acc.username:
            self._test_result.setText("Укажите логин для загрузки аватара.")
            return
        self._fetch_avatar_btn.setEnabled(False)
        self._fetch_avatar_btn.setText("Загружаю...")
        fetcher = AvatarFetcher(acc)
        fetcher.done.connect(self._on_avatar_fetched)
        self._fetchers.append(fetcher)
        fetcher.start()

    def _on_avatar_fetched(self, account_id: str, path: str):
        for i, acc in enumerate(self._accounts):
            if acc.id == account_id:
                acc.avatar_path = path
                item = self._list.item(i)
                if isinstance(item, AccountItem):
                    item.account.avatar_path = path
                    item.refresh()
                if i == self._current_idx:
                    self._refresh_avatar_display(acc)
                break
        self._fetch_avatar_btn.setEnabled(True)
        self._fetch_avatar_btn.setText("Загрузить аватар")
        if not path:
            self._test_result.setText("Не удалось загрузить аватар (проверьте логин и токен).")

    def _refresh_avatar_display(self, acc: Account):
        p = acc.avatar_path
        if p and Path(p).exists():
            pix = QPixmap(p).scaled(
                64, 64,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._avatar_label.setPixmap(pix)
            self._avatar_label.setText("")
        else:
            self._avatar_label.setPixmap(QPixmap())
            self._avatar_label.setText("?")

    # ── Token test ────────────────────────────────────────────────────────────

    def _test_token(self):
        if self._current_idx >= 0:
            self._flush(self._current_idx)
        row = self._list.currentRow()
        if row < 0:
            return
        acc = self._accounts[row]
        if not acc.token:
            self._test_result.setText("Токен не указан.")
            return

        import urllib.request, json
        api_url = acc.api_url or PROVIDERS.get(acc.provider, {}).get("api_url", "")
        if not api_url:
            self._test_result.setText("API URL не определён для этого провайдера.")
            return

        self._test_btn.setEnabled(False)
        self._test_result.setText("Проверяю...")

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
            self._test_result.setText(f"✓ Успешно! Вошли как: {login}")
            # Update username if empty
            if not acc.username:
                acc.username = login
                self._user_edit.setText(login)
        except Exception as e:
            self._test_result.setText(f"✗ Ошибка: {e}")
        finally:
            self._test_btn.setEnabled(True)

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save_all(self):
        if self._dirty and self._current_idx >= 0:
            self._flush(self._current_idx)
        save_accounts(self._accounts)
        self.accept()
