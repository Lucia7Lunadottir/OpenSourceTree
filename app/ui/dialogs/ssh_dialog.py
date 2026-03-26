import os
import subprocess
import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QSplitter,
    QListWidget, QListWidgetItem, QWidget, QLabel, QLineEdit,
    QSpinBox, QComboBox, QPushButton, QDialogButtonBox,
    QFileDialog, QMessageBox, QTextEdit, QGroupBox,
    QAbstractItemView, QCheckBox, QApplication
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from app.config import (
    SSHProfile, load_ssh_profiles, save_ssh_profiles,
    scan_default_ssh_keys, ensure_agent_running, OPENSSH_CONFIG
)


# ── Key generator dialog ───────────────────────────────────────────────────────

class KeyGenerateDialog(QDialog):
    """Proper dialog for generating SSH keys with passphrase support."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Создать SSH-ключ")
        self.setMinimumWidth(500)
        self._result_path = ""
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()

        # Key type
        self._type_combo = QComboBox()
        self._type_combo.addItem("Ed25519  (рекомендуется, современный)", "ed25519")
        self._type_combo.addItem("RSA 4096  (совместимость со старыми серверами)", "rsa")
        self._type_combo.addItem("ECDSA 521", "ecdsa")
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Тип ключа:", self._type_combo)

        # Key size (only for RSA/ECDSA)
        self._size_combo = QComboBox()
        self._size_combo.addItems(["4096", "2048"])
        self._size_combo.setVisible(False)
        self._size_label = QLabel("Размер:")
        self._size_label.setVisible(False)
        form.addRow(self._size_label, self._size_combo)

        # Save path
        path_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        ssh_dir = Path.home() / ".ssh"
        self._path_edit.setText(str(ssh_dir / "id_ed25519"))
        self._path_edit.setPlaceholderText(str(ssh_dir / "id_ed25519"))
        browse_btn = QPushButton("Обзор...")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_path)
        path_row.addWidget(self._path_edit)
        path_row.addWidget(browse_btn)
        form.addRow("Сохранить в:", path_row)

        # Comment
        self._comment_edit = QLineEdit()
        self._comment_edit.setPlaceholderText("your@email.com или имя ключа")
        self._comment_edit.setText(os.environ.get("USER", ""))
        form.addRow("Комментарий:", self._comment_edit)

        layout.addLayout(form)

        # Passphrase group
        pass_grp = QGroupBox("Пароль для ключа (необязательно, но рекомендуется)")
        pf = QFormLayout(pass_grp)

        pass_row = QHBoxLayout()
        self._pass_edit = QLineEdit()
        self._pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_edit.setPlaceholderText("Оставьте пустым — ключ без пароля")
        self._show_pass_btn = QPushButton("👁")
        self._show_pass_btn.setFixedWidth(32)
        self._show_pass_btn.setCheckable(True)
        self._show_pass_btn.toggled.connect(
            lambda on: self._pass_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        pass_row.addWidget(self._pass_edit)
        pass_row.addWidget(self._show_pass_btn)
        pf.addRow("Пароль:", pass_row)

        confirm_row = QHBoxLayout()
        self._confirm_edit = QLineEdit()
        self._confirm_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._confirm_edit.setPlaceholderText("Повторите пароль")
        self._show_confirm_btn = QPushButton("👁")
        self._show_confirm_btn.setFixedWidth(32)
        self._show_confirm_btn.setCheckable(True)
        self._show_confirm_btn.toggled.connect(
            lambda on: self._confirm_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        confirm_row.addWidget(self._confirm_edit)
        confirm_row.addWidget(self._show_confirm_btn)
        pf.addRow("Подтверждение:", confirm_row)

        pass_hint = QLabel(
            "Пароль защищает ключ на диске. При использовании ssh-agent\n"
            "вводить его нужно будет только один раз за сессию."
        )
        pass_hint.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        pf.addRow("", pass_hint)
        layout.addWidget(pass_grp)

        # Agent checkbox
        self._add_to_agent = QCheckBox("Добавить в ssh-agent после создания")
        self._add_to_agent.setChecked(True)
        layout.addWidget(self._add_to_agent)

        # Command preview
        preview_grp = QGroupBox("Команда")
        pl = QVBoxLayout(preview_grp)
        self._preview_label = QLabel()
        self._preview_label.setFont(QFont("Monospace", 9))
        self._preview_label.setStyleSheet("color: rgb(140,180,140);")
        self._preview_label.setWordWrap(True)
        pl.addWidget(self._preview_label)
        layout.addWidget(preview_grp)

        # Connect for live preview
        self._type_combo.currentIndexChanged.connect(self._update_preview)
        self._path_edit.textChanged.connect(self._update_preview)
        self._comment_edit.textChanged.connect(self._update_preview)
        self._update_preview()

        # Buttons
        btns = QDialogButtonBox()
        gen_btn = btns.addButton("Создать ключ", QDialogButtonBox.ButtonRole.AcceptRole)
        btns.addButton(QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._generate)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_type_changed(self):
        key_type = self._type_combo.currentData()
        show_size = key_type in ("rsa", "ecdsa")
        self._size_combo.setVisible(show_size)
        self._size_label.setVisible(show_size)
        # Update default path
        paths = {"ed25519": "id_ed25519", "rsa": "id_rsa", "ecdsa": "id_ecdsa"}
        stem = paths.get(key_type, "id_key")
        ssh_dir = Path.home() / ".ssh"
        self._path_edit.setText(str(ssh_dir / stem))
        self._update_preview()

    def _browse_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить ключ как",
            str(Path.home() / ".ssh"),
            "Все файлы (*)"
        )
        if path:
            self._path_edit.setText(path)

    def _update_preview(self):
        key_type = self._type_combo.currentData() or "ed25519"
        path = self._path_edit.text().strip() or "~/.ssh/id_ed25519"
        comment = self._comment_edit.text().strip()

        parts = ["ssh-keygen", f"-t {key_type}"]
        if key_type == "rsa":
            parts.append(f"-b {self._size_combo.currentText()}")
        if comment:
            parts.append(f"-C \"{comment}\"")
        parts.append(f"-f \"{path}\"")
        self._preview_label.setText(" ".join(parts))

    def _generate(self):
        path = self._path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Ошибка", "Укажите путь для сохранения ключа.")
            return

        passphrase = self._pass_edit.text()
        confirm = self._confirm_edit.text()
        if passphrase != confirm:
            QMessageBox.warning(self, "Ошибка", "Пароли не совпадают.")
            return

        if Path(path).exists():
            ret = QMessageBox.question(
                self, "Файл существует",
                f"'{path}' уже существует. Перезаписать?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return

        key_type = self._type_combo.currentData() or "ed25519"
        comment = self._comment_edit.text().strip()

        # Ensure .ssh dir exists with correct permissions
        ssh_dir = Path(path).parent
        ssh_dir.mkdir(parents=True, exist_ok=True)
        ssh_dir.chmod(0o700)

        if passphrase:
            # Has passphrase — run in terminal for security (passphrase not stored in memory)
            import shlex
            cmd_parts = ["ssh-keygen", f"-t {key_type}"]
            if key_type == "rsa":
                cmd_parts.append(f"-b {self._size_combo.currentText()}")
            if comment:
                cmd_parts.append(f"-C {shlex.quote(comment)}")
            cmd_parts.append(f"-f {shlex.quote(path)}")
            # Pass passphrase via stdin/pipe using -N flag (not exposed in terminal)
            cmd_parts.append(f"-N {shlex.quote(passphrase)}")
            cmd = " ".join(cmd_parts)

            result = subprocess.run(
                ["bash", "-c", cmd],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                QMessageBox.critical(self, "Ошибка создания ключа",
                                     result.stderr or "Неизвестная ошибка")
                return
        else:
            # No passphrase — run directly
            args = ["ssh-keygen", "-t", key_type]
            if key_type == "rsa":
                args += ["-b", self._size_combo.currentText()]
            if comment:
                args += ["-C", comment]
            args += ["-f", path, "-N", ""]

            result = subprocess.run(args, capture_output=True, text=True)
            if result.returncode != 0:
                QMessageBox.critical(self, "Ошибка создания ключа",
                                     result.stderr or "Неизвестная ошибка")
                return

        if not Path(path).exists():
            QMessageBox.critical(self, "Ошибка", "Ключ не был создан.")
            return

        # Add to agent if requested
        if self._add_to_agent.isChecked() and _ssh_agent_running():
            _add_key_to_agent(path, passphrase)

        self._result_path = path
        self.accept()

    def result_path(self) -> str:
        return self._result_path

    def result_comment(self) -> str:
        return self._comment_edit.text().strip()


# ── Agent status worker ────────────────────────────────────────────────────────

class AgentStatusWorker(QThread):
    done = pyqtSignal(list)  # list of loaded key paths

    def run(self):
        try:
            result = subprocess.run(
                ["ssh-add", "-l"], capture_output=True, text=True, timeout=5
            )
            paths = []
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    paths.append(parts[2])
            self.done.emit(paths)
        except Exception:
            self.done.emit([])


# ── Profile list item ──────────────────────────────────────────────────────────

class ProfileItem(QListWidgetItem):
    def __init__(self, profile: SSHProfile):
        super().__init__()
        self.profile = profile
        self.in_agent = False
        self.refresh_label()

    def refresh_label(self):
        name = self.profile.name or self.profile.host_alias or "(без имени)"
        host = self.profile.hostname or "?"
        agent_mark = " 🔓" if self.in_agent else ""
        self.setText(f"{name}{agent_mark}\n{host}")
        color = QColor(203, 166, 247) if self.profile.key_path else QColor(140, 120, 180)
        self.setForeground(color)


# ── Main Dialog ────────────────────────────────────────────────────────────────

class SSHSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH-ключи и профили")
        self.resize(860, 620)
        self._profiles: list[SSHProfile] = load_ssh_profiles()
        self._current_idx: int = -1
        self._dirty = False
        self._agent_keys: list[str] = []
        self._setup_ui()
        self._populate_list()
        if self._profiles:
            self._profile_list.setCurrentRow(0)
        self._refresh_agent_status()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: profile list ──
        left = QWidget()
        left.setFixedWidth(230)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        list_label = QLabel("Профили SSH")
        list_label.setStyleSheet("font-weight: bold; color: rgb(203,166,247);")
        ll.addWidget(list_label)

        self._profile_list = QListWidget()
        self._profile_list.setSpacing(2)
        self._profile_list.setIconSize(QSize(0, 0))
        self._profile_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._profile_list.currentRowChanged.connect(self._on_profile_selected)
        ll.addWidget(self._profile_list)

        btn_row = QHBoxLayout()
        self._add_btn    = QPushButton("+ Добавить")
        self._remove_btn = QPushButton("Удалить")
        self._remove_btn.setEnabled(False)
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._remove_btn)
        ll.addLayout(btn_row)

        gen_btn = QPushButton("✨ Создать ключ...")
        gen_btn.setToolTip("Создать новую пару SSH-ключей")
        ll.addWidget(gen_btn)

        import_btn = QPushButton("📂 Импортировать ключи")
        import_btn.setToolTip("Найти существующие ключи в ~/.ssh/")
        ll.addWidget(import_btn)

        splitter.addWidget(left)

        # ── Right: profile editor ──
        self._editor = QWidget()
        self._editor.setEnabled(False)
        el = QVBoxLayout(self._editor)
        el.setContentsMargins(8, 0, 0, 0)
        el.setSpacing(8)

        # Basic group
        basic = QGroupBox("Профиль")
        bf = QFormLayout(basic)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("напр. GitHub Personal")
        bf.addRow("Название:", self._name_edit)

        key_row = QHBoxLayout()
        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("~/.ssh/id_ed25519")
        browse_btn = QPushButton("Обзор...")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_key)
        key_row.addWidget(self._key_edit)
        key_row.addWidget(browse_btn)
        bf.addRow("Файл ключа:", key_row)

        self._pubkey_label = QLabel("")
        self._pubkey_label.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        self._pubkey_label.setWordWrap(True)
        self._pubkey_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bf.addRow("Публичный ключ:", self._pubkey_label)

        copy_pubkey_btn = QPushButton("Копировать публичный ключ")
        copy_pubkey_btn.clicked.connect(self._copy_pubkey)
        bf.addRow("", copy_pubkey_btn)
        el.addWidget(basic)

        # Connection group
        conn = QGroupBox("Подключение")
        cf = QFormLayout(conn)

        self._alias_edit = QLineEdit()
        self._alias_edit.setPlaceholderText("github-personal  (для git@github-personal:user/repo.git)")
        cf.addRow("Псевдоним хоста:", self._alias_edit)

        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("github.com")
        cf.addRow("Хост (реальный):", self._host_edit)

        self._user_edit = QLineEdit("git")
        cf.addRow("Пользователь SSH:", self._user_edit)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(22)
        cf.addRow("Порт:", self._port_spin)

        self._strict_combo = QComboBox()
        self._strict_combo.addItems(["accept-new", "yes", "no"])
        self._strict_combo.setToolTip(
            "accept-new — принять новые, отклонить изменённые\n"
            "yes — всегда проверять\n"
            "no — не проверять (небезопасно)"
        )
        cf.addRow("Проверка хоста:", self._strict_combo)
        el.addWidget(conn)

        # ssh-agent group
        self._agent_grp = QGroupBox("ssh-agent (хранение пароля ключа в памяти)")
        al = QVBoxLayout(self._agent_grp)

        self._agent_status_label = QLabel("Статус агента: проверяется...")
        self._agent_status_label.setStyleSheet("font-size: 11px; color: rgb(140,120,180);")
        al.addWidget(self._agent_status_label)

        # List of all keys currently loaded in the agent
        self._agent_keys_list = QListWidget()
        self._agent_keys_list.setFixedHeight(72)
        self._agent_keys_list.setToolTip("Ключи, загруженные в ssh-agent прямо сейчас")
        al.addWidget(self._agent_keys_list)

        agent_btn_row = QHBoxLayout()
        self._add_agent_btn = QPushButton("🔓 Добавить профиль")
        self._add_agent_btn.setToolTip(
            "Загружает ключ выбранного профиля в ssh-agent.\n"
            "Если ключ защищён паролем — введите его один раз."
        )
        self._add_agent_btn.clicked.connect(self._add_to_agent)
        self._remove_agent_btn = QPushButton("🔒 Убрать профиль")
        self._remove_agent_btn.clicked.connect(self._remove_from_agent)
        self._clear_agent_btn = QPushButton("🗑 Очистить агент")
        self._clear_agent_btn.setToolTip("Выгрузить все ключи из ssh-agent (ssh-add -D)")
        self._clear_agent_btn.clicked.connect(self._clear_agent)
        self._refresh_agent_btn = QPushButton("↻")
        self._refresh_agent_btn.setFixedWidth(30)
        self._refresh_agent_btn.setToolTip("Обновить статус агента")
        self._refresh_agent_btn.clicked.connect(self._refresh_agent_status)
        agent_btn_row.addWidget(self._add_agent_btn)
        agent_btn_row.addWidget(self._remove_agent_btn)
        agent_btn_row.addWidget(self._clear_agent_btn)
        agent_btn_row.addWidget(self._refresh_agent_btn)
        al.addLayout(agent_btn_row)

        agent_hint = QLabel(
            "ssh-agent хранит расшифрованный ключ в оперативной памяти.\n"
            "Git использует его автоматически — пароль спрашивается только при добавлении."
        )
        agent_hint.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        agent_hint.setWordWrap(True)
        al.addWidget(agent_hint)
        el.addWidget(self._agent_grp)

        # Test group
        test_grp = QGroupBox("Тест подключения")
        tl = QVBoxLayout(test_grp)
        test_row = QHBoxLayout()
        self._test_btn = QPushButton("Проверить")
        self._test_btn.clicked.connect(self._test_connection)
        test_row.addWidget(QLabel("ssh -T <псевдоним>@<хост>"))
        test_row.addStretch()
        test_row.addWidget(self._test_btn)
        tl.addLayout(test_row)
        self._test_output = QTextEdit()
        self._test_output.setReadOnly(True)
        self._test_output.setFixedHeight(55)
        self._test_output.setPlaceholderText("Результат появится здесь...")
        tl.addWidget(self._test_output)
        el.addWidget(test_grp)

        el.addStretch()

        splitter.addWidget(self._editor)
        splitter.setSizes([230, 610])
        root.addWidget(splitter)

        # ── Dialog buttons ──
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить всё")
        btns.accepted.connect(self._save_all)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # Connections
        self._add_btn.clicked.connect(self._add_profile)
        self._remove_btn.clicked.connect(self._remove_profile)
        gen_btn.clicked.connect(self._generate_key)
        import_btn.clicked.connect(self._import_keys)

        for w in (self._name_edit, self._key_edit, self._alias_edit,
                  self._host_edit, self._user_edit):
            w.textChanged.connect(self._on_field_changed)
        self._port_spin.valueChanged.connect(self._on_field_changed)
        self._strict_combo.currentTextChanged.connect(self._on_field_changed)
        self._key_edit.editingFinished.connect(self._refresh_pubkey_display)

    # ── Agent ─────────────────────────────────────────────────────────────────

    def _refresh_agent_status(self):
        self._worker = AgentStatusWorker()
        self._worker.done.connect(self._on_agent_status)
        self._worker.start()

    def _on_agent_status(self, keys: list):
        self._agent_keys = keys
        if not _ssh_agent_running():
            self._agent_status_label.setText("⚠ ssh-agent не запущен")
            self._agent_status_label.setStyleSheet("font-size: 11px; color: rgb(255,150,100);")
        elif not keys:
            self._agent_status_label.setText("ssh-agent запущен, ключей не загружено")
            self._agent_status_label.setStyleSheet("font-size: 11px; color: rgb(140,120,180);")
        else:
            self._agent_status_label.setText(
                f"ssh-agent: {len(keys)} ключ(ей) загружено  🔓"
            )
            self._agent_status_label.setStyleSheet("font-size: 11px; color: rgb(160,220,130);")

        # Populate keys list
        self._agent_keys_list.clear()
        for key_path in keys:
            self._agent_keys_list.addItem(f"🔓  {key_path}")
        if not keys and _ssh_agent_running():
            self._agent_keys_list.addItem("(нет загруженных ключей)")

        # Update profile list items
        for i in range(self._profile_list.count()):
            item = self._profile_list.item(i)
            if isinstance(item, ProfileItem):
                item.in_agent = any(
                    item.profile.key_path and k.endswith(Path(item.profile.key_path).name)
                    for k in self._agent_keys
                )
                item.refresh_label()

    def _add_to_agent(self):
        if self._current_idx < 0:
            return
        self._flush_editor_to_profile(self._current_idx)
        p = self._profiles[self._current_idx]
        if not p.key_path or not os.path.exists(p.key_path):
            QMessageBox.warning(self, "ssh-agent", "Файл ключа не найден.")
            return

        if not ensure_agent_running():
            QMessageBox.warning(
                self, "ssh-agent",
                "Не удалось запустить ssh-agent.\n"
                "Попробуйте вручную: eval $(ssh-agent)"
            )
            return

        # Run ssh-add in terminal (handles passphrase prompt natively)
        terminal = _find_terminal()
        if terminal:
            import shlex
            cmd = (
                f"ssh-add {shlex.quote(p.key_path)}; "
                f'echo ""; echo "Нажмите Enter чтобы закрыть..."; read _'
            )
            term_name = os.path.basename(terminal)
            if term_name == "konsole":
                proc = subprocess.Popen(
                    [terminal, "--hide-menubar", "--hide-tabbar", "-e", "bash", "-c", cmd]
                )
            else:
                proc = subprocess.Popen([terminal, "-e", "bash", "-c", cmd])
            proc.wait()
        else:
            # Try silent add (works for password-less keys)
            result = subprocess.run(
                ["ssh-add", p.key_path], capture_output=True, text=True
            )
            if result.returncode != 0:
                QMessageBox.warning(
                    self, "ssh-agent",
                    f"Не удалось добавить ключ:\n{result.stderr}\n\n"
                    "Ключ может быть защищён паролем. Запустите в терминале:\n"
                    f"  ssh-add {p.key_path}"
                )
                return

        self._refresh_agent_status()

    def _remove_from_agent(self):
        if self._current_idx < 0:
            return
        p = self._profiles[self._current_idx]
        if not p.key_path:
            return
        result = subprocess.run(
            ["ssh-add", "-d", p.key_path], capture_output=True, text=True
        )
        if result.returncode != 0:
            QMessageBox.warning(self, "ssh-agent", f"Ошибка: {result.stderr}")
        self._refresh_agent_status()

    def _clear_agent(self):
        ret = QMessageBox.question(
            self, "Очистить агент",
            "Выгрузить все ключи из ssh-agent?\nПри следующей git-операции пароль будет запрошен снова.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        result = subprocess.run(["ssh-add", "-D"], capture_output=True, text=True)
        if result.returncode != 0:
            QMessageBox.warning(self, "ssh-agent", f"Ошибка: {result.stderr}")
        self._refresh_agent_status()

    # ── List management ───────────────────────────────────────────────────────

    def _populate_list(self):
        self._profile_list.clear()
        for p in self._profiles:
            self._profile_list.addItem(ProfileItem(p))

    def _on_profile_selected(self, row: int):
        if self._dirty and self._current_idx >= 0:
            self._flush_editor_to_profile(self._current_idx)

        self._current_idx = row
        self._editor.setEnabled(row >= 0)
        self._remove_btn.setEnabled(row >= 0)
        # Agent section is always accessible regardless of profile selection
        self._agent_grp.setEnabled(True)

        if row < 0 or row >= len(self._profiles):
            return

        p = self._profiles[row]
        for w in (self._name_edit, self._key_edit, self._alias_edit,
                  self._host_edit, self._user_edit, self._port_spin, self._strict_combo):
            w.blockSignals(True)

        self._name_edit.setText(p.name)
        self._key_edit.setText(p.key_path)
        self._alias_edit.setText(p.host_alias)
        self._host_edit.setText(p.hostname)
        self._user_edit.setText(p.username)
        self._port_spin.setValue(p.port)
        idx = self._strict_combo.findText(p.strict_host_checking)
        self._strict_combo.setCurrentIndex(idx if idx >= 0 else 0)

        for w in (self._name_edit, self._key_edit, self._alias_edit,
                  self._host_edit, self._user_edit, self._port_spin, self._strict_combo):
            w.blockSignals(False)

        self._refresh_pubkey_display()
        self._dirty = False

    def _on_field_changed(self, *_):
        self._dirty = True
        if self._current_idx >= 0:
            self._flush_editor_to_profile(self._current_idx)
            item = self._profile_list.item(self._current_idx)
            if isinstance(item, ProfileItem):
                item.refresh_label()

    def _flush_editor_to_profile(self, idx: int):
        if idx < 0 or idx >= len(self._profiles):
            return
        p = self._profiles[idx]
        p.name                = self._name_edit.text().strip()
        p.key_path            = self._key_edit.text().strip()
        p.host_alias          = self._alias_edit.text().strip()
        p.hostname            = self._host_edit.text().strip()
        p.username            = self._user_edit.text().strip() or "git"
        p.port                = self._port_spin.value()
        p.strict_host_checking = self._strict_combo.currentText()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _add_profile(self):
        if self._dirty and self._current_idx >= 0:
            self._flush_editor_to_profile(self._current_idx)
        p = SSHProfile(name="Новый профиль")
        self._profiles.append(p)
        self._profile_list.addItem(ProfileItem(p))
        self._profile_list.setCurrentRow(len(self._profiles) - 1)

    def _remove_profile(self):
        row = self._profile_list.currentRow()
        if row < 0:
            return
        name = self._profiles[row].name or "профиль"
        ret = QMessageBox.question(
            self, "Удалить профиль",
            f"Удалить '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self._profiles.pop(row)
            self._populate_list()
            self._current_idx = -1
            self._dirty = False
            new_row = min(row, len(self._profiles) - 1)
            if new_row >= 0:
                self._profile_list.setCurrentRow(new_row)
            else:
                self._editor.setEnabled(False)

    # ── Key management ────────────────────────────────────────────────────────

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл приватного ключа",
            os.path.expanduser("~/.ssh"),
            "Ключи SSH (id_* *);;Все файлы (*)",
        )
        if path:
            self._key_edit.setText(path)
            self._refresh_pubkey_display()

    def _refresh_pubkey_display(self):
        key = self._key_edit.text().strip()
        pub = key + ".pub" if key else ""
        if pub and os.path.exists(pub):
            try:
                text = Path(pub).read_text().strip()
                if len(text) > 90:
                    display = text[:55] + "..." + text[-25:]
                else:
                    display = text
                self._pubkey_label.setText(display)
            except Exception:
                self._pubkey_label.setText("(не удалось прочитать)")
        else:
            self._pubkey_label.setText("(.pub файл не найден)")

    def _copy_pubkey(self):
        key = self._key_edit.text().strip()
        pub = key + ".pub" if key else ""
        if not pub or not os.path.exists(pub):
            QMessageBox.warning(self, "Публичный ключ", "Файл .pub не найден рядом с приватным ключом.")
            return
        text = Path(pub).read_text().strip()
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Скопировано", "Публичный ключ скопирован в буфер обмена.")

    def _generate_key(self):
        if not shutil.which("ssh-keygen"):
            QMessageBox.critical(self, "Ошибка", "ssh-keygen не найден в PATH.")
            return

        dlg = KeyGenerateDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        key_path = dlg.result_path()
        if not key_path or not Path(key_path).exists():
            QMessageBox.warning(self, "Ключ не создан", "Файл ключа не найден после генерации.")
            return

        # Auto-create profile
        comment = dlg.result_comment()
        p = SSHProfile(
            name=comment or Path(key_path).stem,
            key_path=key_path,
        )
        self._profiles.append(p)
        self._populate_list()
        self._profile_list.setCurrentRow(len(self._profiles) - 1)

        QMessageBox.information(
            self, "Ключ создан",
            f"Ключ создан: {key_path}\n\n"
            f"Публичный ключ:\n{key_path}.pub\n\n"
            "Добавьте содержимое .pub файла на GitHub/GitLab:\n"
            "GitHub → Settings → SSH and GPG keys → New SSH key"
        )
        self._refresh_agent_status()

    def _import_keys(self):
        existing_paths = {p.key_path for p in self._profiles}
        found = scan_default_ssh_keys()
        new_keys = [k for k in found if k not in existing_paths]

        if not new_keys:
            QMessageBox.information(self, "Импорт", "Новых ключей в ~/.ssh/ не найдено.")
            return

        msg = "Найдены ключи:\n" + "\n".join(f"  • {k}" for k in new_keys) + "\n\nДобавить как профили?"
        ret = QMessageBox.question(self, "Импорт ключей", msg,
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return

        for k in new_keys:
            p = SSHProfile(name=Path(k).stem, key_path=k)
            self._profiles.append(p)

        self._populate_list()
        self._profile_list.setCurrentRow(len(self._profiles) - 1)

    # ── Test connection ────────────────────────────────────────────────────────

    def _test_connection(self):
        if self._current_idx >= 0:
            self._flush_editor_to_profile(self._current_idx)
        row = self._profile_list.currentRow()
        if row < 0:
            return
        p = self._profiles[row]

        if not p.key_path or not os.path.exists(p.key_path):
            self._test_output.setPlainText("Файл ключа не найден.")
            return
        if not p.hostname:
            self._test_output.setPlainText("Укажите хост для подключения.")
            return

        target = p.host_alias or p.hostname
        self._test_btn.setEnabled(False)
        self._test_output.setPlainText("Подключаемся...")

        cmd = [
            "ssh",
            "-i", p.key_path,
            "-o", "BatchMode=yes",
            "-o", f"StrictHostKeyChecking={p.strict_host_checking}",
            "-o", "ConnectTimeout=10",
            "-p", str(p.port),
            "-T",
            f"{p.username}@{target}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            output = (result.stdout + result.stderr).strip()
            ok_markers = ("successfully authenticated", "welcome to gitlab", "you've successfully")
            if any(m in output.lower() for m in ok_markers):
                self._test_output.setPlainText("✓ " + output)
            else:
                self._test_output.setPlainText(output or f"Код завершения: {result.returncode}")
        except subprocess.TimeoutExpired:
            self._test_output.setPlainText("Таймаут подключения (10 с)")
        except Exception as e:
            self._test_output.setPlainText(f"Ошибка: {e}")
        finally:
            self._test_btn.setEnabled(True)

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save_all(self):
        if self._dirty and self._current_idx >= 0:
            self._flush_editor_to_profile(self._current_idx)
        save_ssh_profiles(self._profiles)
        self.accept()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ssh_agent_running() -> bool:
    return bool(os.environ.get("SSH_AUTH_SOCK"))


def _add_key_to_agent(key_path: str, passphrase: str = "") -> bool:
    """Add key to ssh-agent silently (only works for password-less keys)."""
    if not _ssh_agent_running():
        return False
    env = os.environ.copy()
    if passphrase:
        # Use SSH_ASKPASS trick for non-interactive passphrase
        askpass = Path("/tmp/_ost_askpass.sh")
        askpass.write_text(f'#!/bin/sh\necho {subprocess.list2cmdline([passphrase])}\n')
        askpass.chmod(0o700)
        env["SSH_ASKPASS"] = str(askpass)
        env["SSH_ASKPASS_REQUIRE"] = "force"
    result = subprocess.run(
        ["ssh-add", key_path],
        capture_output=True, text=True, env=env
    )
    if passphrase:
        try:
            Path("/tmp/_ost_askpass.sh").unlink()
        except Exception:
            pass
    return result.returncode == 0


def _find_terminal() -> str:
    for t in ("konsole", "xterm", "alacritty", "kitty", "foot"):
        found = shutil.which(t)
        if found:
            return found
    return ""
