import os
import subprocess
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QLineEdit, QCheckBox, QComboBox, QPushButton,
    QDialogButtonBox, QLabel, QFileDialog, QMessageBox,
    QGroupBox, QTextEdit
)
from PyQt6.QtCore import Qt
from app import config


class SSHSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH Settings")
        self.setMinimumWidth(480)
        self._cfg = config.load_ssh_config()
        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Key group ──
        key_group = QGroupBox("SSH Key")
        key_layout = QFormLayout(key_group)

        key_row = QHBoxLayout()
        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("~/.ssh/id_rsa  (оставьте пустым для системного ключа)")
        browse_btn = QPushButton("Обзор...")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_key)
        key_row.addWidget(self._key_edit)
        key_row.addWidget(browse_btn)
        key_layout.addRow("Файл ключа:", key_row)

        self._agent_check = QCheckBox("Использовать ssh-agent (рекомендуется)")
        key_layout.addRow("", self._agent_check)
        layout.addWidget(key_group)

        # ── Connection group ──
        conn_group = QGroupBox("Подключение")
        conn_layout = QFormLayout(conn_group)

        self._strict_combo = QComboBox()
        self._strict_combo.addItems(["accept-new", "yes", "no"])
        self._strict_combo.setToolTip(
            "accept-new — принять новые хосты, отклонить изменённые\n"
            "yes — всегда проверять\n"
            "no — не проверять (небезопасно)"
        )
        conn_layout.addRow("Проверка хоста:", self._strict_combo)

        self._extra_edit = QLineEdit()
        self._extra_edit.setPlaceholderText("напр.: ServerAliveInterval=60 ConnectTimeout=15")
        conn_layout.addRow("Доп. опции:", self._extra_edit)
        layout.addWidget(conn_group)

        # ── Test group ──
        test_group = QGroupBox("Тест подключения")
        test_layout = QFormLayout(test_group)

        test_row = QHBoxLayout()
        self._test_host_edit = QLineEdit()
        self._test_host_edit.setPlaceholderText("git@github.com")
        self._test_btn = QPushButton("Проверить")
        self._test_btn.clicked.connect(self._test_connection)
        test_row.addWidget(self._test_host_edit)
        test_row.addWidget(self._test_btn)
        test_layout.addRow("Хост:", test_row)

        self._test_output = QTextEdit()
        self._test_output.setReadOnly(True)
        self._test_output.setFixedHeight(70)
        self._test_output.setPlaceholderText("Результат проверки появится здесь...")
        test_layout.addRow("", self._test_output)
        layout.addWidget(test_group)

        # ── Hint ──
        hint = QLabel(
            "Совет: если репозиторий требует пароль или кодовую фразу ключа — "
            "операции fetch/pull/push автоматически откроют терминал."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: rgb(140, 120, 180); font-size: 11px;")
        layout.addWidget(hint)

        # ── Buttons ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_values(self):
        self._key_edit.setText(self._cfg.get("key_path", ""))
        self._agent_check.setChecked(self._cfg.get("use_agent", True))
        strict = self._cfg.get("strict_host_checking", "accept-new")
        idx = self._strict_combo.findText(strict)
        self._strict_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._extra_edit.setText(self._cfg.get("extra_options", ""))

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл SSH-ключа",
            os.path.expanduser("~/.ssh"),
            "Все файлы (*)",
        )
        if path:
            self._key_edit.setText(path)

    def _save(self):
        cfg = {
            "key_path": self._key_edit.text().strip(),
            "use_agent": self._agent_check.isChecked(),
            "strict_host_checking": self._strict_combo.currentText(),
            "extra_options": self._extra_edit.text().strip(),
        }
        config.save_ssh_config(cfg)
        self.accept()

    def _test_connection(self):
        host = self._test_host_edit.text().strip()
        if not host:
            self._test_output.setPlainText("Введите адрес хоста (напр. git@github.com)")
            return

        self._test_btn.setEnabled(False)
        self._test_output.setPlainText("Подключаемся...")

        from app.config import build_git_ssh_command, load_ssh_config
        # Build SSH command with current (unsaved) values
        tmp_cfg = {
            "key_path": self._key_edit.text().strip(),
            "use_agent": self._agent_check.isChecked(),
            "strict_host_checking": self._strict_combo.currentText(),
            "extra_options": self._extra_edit.text().strip(),
        }
        ssh_base = build_git_ssh_command(tmp_cfg)
        # ssh -T git@github.com  — standard test for GitHub/GitLab
        ssh_parts = ssh_base.split()
        cmd = ssh_parts + ["-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15
            )
            output = (result.stdout + result.stderr).strip()
            # GitHub returns rc=1 but with a success message
            if "successfully authenticated" in output.lower() or "welcome to gitlab" in output.lower():
                self._test_output.setPlainText("✓ " + output)
            else:
                self._test_output.setPlainText(output or f"Завершено с кодом {result.returncode}")
        except subprocess.TimeoutExpired:
            self._test_output.setPlainText("Таймаут подключения (10 с)")
        except Exception as e:
            self._test_output.setPlainText(f"Ошибка: {e}")
        finally:
            self._test_btn.setEnabled(True)
