import os
import subprocess
import shutil
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QSplitter, QListWidget, QListWidgetItem, QWidget, QLabel,
    QLineEdit, QSpinBox, QComboBox, QPushButton, QDialogButtonBox,
    QFileDialog, QMessageBox, QTextEdit, QGroupBox, QCheckBox, QApplication
)
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QColor

from app.config import (
    SSHProfile, load_ssh_profiles, save_ssh_profiles,
    scan_default_ssh_keys, ensure_agent_running, OPENSSH_CONFIG
)
from app.i18n import t
from app.ui.ui_translator import UiTranslator

_KEYGEN_UI_FILE = Path(__file__).with_name("ssh_keygen_dialog.ui")
_SETTINGS_UI_FILE = Path(__file__).with_name("ssh_dialog.ui")


def _bind_reveal_button(button: QPushButton, edit: QLineEdit) -> None:
    """Checkable 👁 button toggles the password echo mode of its line edit."""
    button.toggled.connect(
        lambda on: edit.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
        )
    )


# ── Key generator dialog ───────────────────────────────────────────────────────

class KeyGenerateDialog(QDialog):
    """Proper dialog for generating SSH keys with passphrase support."""

    # widgets created by loadUi from ssh_keygen_dialog.ui
    typeCombo: QComboBox
    sizeLabel: QLabel
    sizeCombo: QComboBox
    pathEdit: QLineEdit
    browseButton: QPushButton
    commentEdit: QLineEdit
    passEdit: QLineEdit
    showPassButton: QPushButton
    confirmEdit: QLineEdit
    showConfirmButton: QPushButton
    addToAgentCheck: QCheckBox
    previewLabel: QLabel
    buttonBox: QDialogButtonBox

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result_path = ""
        self._setup_ui()

    def _setup_ui(self):
        uic.loadUi(_KEYGEN_UI_FILE, self)
        UiTranslator().apply(self)

        # Key type (item data = ssh-keygen -t value)
        self.typeCombo.addItem(t("ssh.keygen.type_ed25519"), "ed25519")
        self.typeCombo.addItem(t("ssh.keygen.type_rsa"), "rsa")
        self.typeCombo.addItem(t("ssh.keygen.type_ecdsa"), "ecdsa")
        self.typeCombo.currentIndexChanged.connect(self._on_type_changed)

        # Key size (only for RSA/ECDSA)
        self.sizeCombo.setVisible(False)
        self.sizeLabel.setVisible(False)

        ssh_dir = Path.home() / ".ssh"
        self.pathEdit.setText(str(ssh_dir / "id_ed25519"))
        self.pathEdit.setPlaceholderText(str(ssh_dir / "id_ed25519"))
        self.browseButton.clicked.connect(self._browse_path)
        self.commentEdit.setText(os.environ.get("USER", ""))

        _bind_reveal_button(self.showPassButton, self.passEdit)
        _bind_reveal_button(self.showConfirmButton, self.confirmEdit)

        # Connect for live preview
        self.typeCombo.currentIndexChanged.connect(self._update_preview)
        self.pathEdit.textChanged.connect(self._update_preview)
        self.commentEdit.textChanged.connect(self._update_preview)
        self._update_preview()

        # Buttons
        self.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setText(t("ssh.keygen.btn_generate"))
        self.buttonBox.accepted.connect(self._generate)
        self.buttonBox.rejected.connect(self.reject)
        # Fit the height to the rows actually shown (independent of the .ui geometry)
        self.adjustSize()

    def _on_type_changed(self):
        key_type = self.typeCombo.currentData()
        show_size = key_type in ("rsa", "ecdsa")
        self.sizeCombo.setVisible(show_size)
        self.sizeLabel.setVisible(show_size)
        # Update default path
        paths = {"ed25519": "id_ed25519", "rsa": "id_rsa", "ecdsa": "id_ecdsa"}
        stem = paths.get(key_type, "id_key")
        ssh_dir = Path.home() / ".ssh"
        self.pathEdit.setText(str(ssh_dir / stem))
        self._update_preview()

    def _browse_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self, t("ssh.keygen.save_dialog_title"),
            str(Path.home() / ".ssh"),
            t("ssh.keygen.save_dialog_filter")
        )
        if path:
            self.pathEdit.setText(path)

    def _update_preview(self):
        key_type = self.typeCombo.currentData() or "ed25519"
        path = self.pathEdit.text().strip() or "~/.ssh/id_ed25519"
        comment = self.commentEdit.text().strip()

        parts = ["ssh-keygen", f"-t {key_type}"]
        if key_type == "rsa":
            parts.append(f"-b {self.sizeCombo.currentText()}")
        if comment:
            parts.append(f"-C \"{comment}\"")
        parts.append(f"-f \"{path}\"")
        self.previewLabel.setText(" ".join(parts))

    def _generate(self):
        path = self.pathEdit.text().strip()
        if not path:
            QMessageBox.warning(self, t("ssh.keygen.error.title"), t("ssh.keygen.error.no_path"))
            return

        passphrase = self.passEdit.text()
        confirm = self.confirmEdit.text()
        if passphrase != confirm:
            QMessageBox.warning(self, t("ssh.keygen.error.title"), t("ssh.keygen.error.passwords_mismatch"))
            return

        if Path(path).exists():
            ret = QMessageBox.question(
                self, t("ssh.keygen.error.file_exists"),
                t("ssh.keygen.error.file_exists_msg", path=path),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return

        key_type = self.typeCombo.currentData() or "ed25519"
        comment = self.commentEdit.text().strip()

        # Ensure .ssh dir exists with correct permissions
        ssh_dir = Path(path).parent
        ssh_dir.mkdir(parents=True, exist_ok=True)
        ssh_dir.chmod(0o700)

        if passphrase:
            # Has passphrase — run in terminal for security (passphrase not stored in memory)
            import shlex
            cmd_parts = ["ssh-keygen", f"-t {key_type}"]
            if key_type == "rsa":
                cmd_parts.append(f"-b {self.sizeCombo.currentText()}")
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
                QMessageBox.critical(self, t("ssh.keygen.error.key_gen_title"),
                                     result.stderr or t("ssh.keygen.error.key_gen_title"))
                return
        else:
            # No passphrase — run directly
            args = ["ssh-keygen", "-t", key_type]
            if key_type == "rsa":
                args += ["-b", self.sizeCombo.currentText()]
            if comment:
                args += ["-C", comment]
            args += ["-f", path, "-N", ""]

            result = subprocess.run(args, capture_output=True, text=True)
            if result.returncode != 0:
                QMessageBox.critical(self, t("ssh.keygen.error.key_gen_title"),
                                     result.stderr or t("ssh.keygen.error.key_gen_title"))
                return

        if not Path(path).exists():
            QMessageBox.critical(self, t("ssh.keygen.error.title"), t("ssh.keygen.error.key_not_created"))
            return

        # Add to agent if requested
        if self.addToAgentCheck.isChecked() and _ssh_agent_running():
            _add_key_to_agent(path, passphrase)

        self._result_path = path
        self.accept()

    def result_path(self) -> str:
        return self._result_path

    def result_comment(self) -> str:
        return self.commentEdit.text().strip()


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
        name = self.profile.name or self.profile.host_alias or t("ssh.profile_no_name")
        host = self.profile.hostname or "?"
        agent_mark = " 🔓" if self.in_agent else ""
        self.setText(f"{name}{agent_mark}\n{host}")
        color = QColor(203, 166, 247) if self.profile.key_path else QColor(140, 120, 180)
        self.setForeground(color)


# ── Main Dialog ────────────────────────────────────────────────────────────────

class SSHSettingsDialog(QDialog):
    # widgets created by loadUi from ssh_dialog.ui
    splitter: QSplitter
    profileList: QListWidget
    addButton: QPushButton
    removeButton: QPushButton
    generateButton: QPushButton
    importButton: QPushButton
    editorPanel: QWidget
    nameEdit: QLineEdit
    keyEdit: QLineEdit
    browseKeyButton: QPushButton
    pubkeyLabel: QLabel
    copyPubkeyButton: QPushButton
    aliasEdit: QLineEdit
    hostEdit: QLineEdit
    userEdit: QLineEdit
    portSpin: QSpinBox
    strictCombo: QComboBox
    agentGroup: QGroupBox
    agentStatusLabel: QLabel
    agentKeysList: QListWidget
    addAgentButton: QPushButton
    removeAgentButton: QPushButton
    clearAgentButton: QPushButton
    refreshAgentButton: QPushButton
    testButton: QPushButton
    testOutput: QTextEdit
    buttonBox: QDialogButtonBox

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profiles: list[SSHProfile] = load_ssh_profiles()
        self._current_idx: int = -1
        self._dirty = False
        self._agent_keys: list[str] = []
        self._setup_ui()
        self._populate_list()
        if self._profiles:
            self.profileList.setCurrentRow(0)
        self._refresh_agent_status()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        uic.loadUi(_SETTINGS_UI_FILE, self)
        UiTranslator().apply(self)

        self.profileList.currentRowChanged.connect(self._on_profile_selected)
        self.browseKeyButton.clicked.connect(self._browse_key)
        self.copyPubkeyButton.clicked.connect(self._copy_pubkey)

        self.addAgentButton.clicked.connect(self._add_to_agent)
        self.removeAgentButton.clicked.connect(self._remove_from_agent)
        self.clearAgentButton.clicked.connect(self._clear_agent)
        self.refreshAgentButton.clicked.connect(self._refresh_agent_status)

        self.testButton.clicked.connect(self._test_connection)
        self.splitter.setSizes([230, 610])

        # ── Dialog buttons ──
        self.buttonBox.button(QDialogButtonBox.StandardButton.Save).setText(t("ssh.btn_save_all"))
        self.buttonBox.accepted.connect(self._save_all)
        self.buttonBox.rejected.connect(self.reject)

        # Connections
        self.addButton.clicked.connect(self._add_profile)
        self.removeButton.clicked.connect(self._remove_profile)
        self.generateButton.clicked.connect(self._generate_key)
        self.importButton.clicked.connect(self._import_keys)

        for w in (self.nameEdit, self.keyEdit, self.aliasEdit,
                  self.hostEdit, self.userEdit):
            w.textChanged.connect(self._on_field_changed)
        self.portSpin.valueChanged.connect(self._on_field_changed)
        self.strictCombo.currentTextChanged.connect(self._on_field_changed)
        self.keyEdit.editingFinished.connect(self._refresh_pubkey_display)

    # ── Agent ─────────────────────────────────────────────────────────────────

    def _refresh_agent_status(self):
        self._worker = AgentStatusWorker()
        self._worker.done.connect(self._on_agent_status)
        self._worker.start()

    def _on_agent_status(self, keys: list):
        self._agent_keys = keys
        if not _ssh_agent_running():
            self.agentStatusLabel.setText(t("ssh.agent_status_not_running"))
            self.agentStatusLabel.setStyleSheet("font-size: 11px; color: rgb(255,150,100);")
        elif not keys:
            self.agentStatusLabel.setText(t("ssh.agent_status_no_keys"))
            self.agentStatusLabel.setStyleSheet("font-size: 11px; color: rgb(140,120,180);")
        else:
            self.agentStatusLabel.setText(t("ssh.agent_status_keys", n=len(keys)))
            self.agentStatusLabel.setStyleSheet("font-size: 11px; color: rgb(160,220,130);")

        # Populate keys list
        self.agentKeysList.clear()
        for key_path in keys:
            self.agentKeysList.addItem(f"🔓  {key_path}")
        if not keys and _ssh_agent_running():
            self.agentKeysList.addItem(t("ssh.agent_no_keys"))

        # Update profile list items
        for i in range(self.profileList.count()):
            item = self.profileList.item(i)
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
            QMessageBox.warning(self, t("ssh.agent.title"), t("ssh.agent.no_key_file"))
            return

        if not ensure_agent_running():
            QMessageBox.warning(self, t("ssh.agent.title"), t("ssh.agent.start_failed"))
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
                QMessageBox.warning(self, t("ssh.agent.title"),
                                    t("ssh.agent.add_failed", error=result.stderr, path=p.key_path))
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
            QMessageBox.warning(self, t("ssh.agent.title"), t("ssh.agent.remove_error", error=result.stderr))
        self._refresh_agent_status()

    def _clear_agent(self):
        ret = QMessageBox.question(
            self, t("ssh.agent.clear.title"), t("ssh.agent.clear.text"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        result = subprocess.run(["ssh-add", "-D"], capture_output=True, text=True)
        if result.returncode != 0:
            QMessageBox.warning(self, t("ssh.agent.title"), t("ssh.agent.clear_error", error=result.stderr))
        self._refresh_agent_status()

    # ── List management ───────────────────────────────────────────────────────

    def _populate_list(self):
        self.profileList.clear()
        for p in self._profiles:
            self.profileList.addItem(ProfileItem(p))

    def _on_profile_selected(self, row: int):
        if self._dirty and self._current_idx >= 0:
            self._flush_editor_to_profile(self._current_idx)

        self._current_idx = row
        self.editorPanel.setEnabled(row >= 0)
        self.removeButton.setEnabled(row >= 0)
        # Agent section is always accessible regardless of profile selection
        self.agentGroup.setEnabled(True)

        if row < 0 or row >= len(self._profiles):
            return

        p = self._profiles[row]
        for w in (self.nameEdit, self.keyEdit, self.aliasEdit,
                  self.hostEdit, self.userEdit, self.portSpin, self.strictCombo):
            w.blockSignals(True)

        self.nameEdit.setText(p.name)
        self.keyEdit.setText(p.key_path)
        self.aliasEdit.setText(p.host_alias)
        self.hostEdit.setText(p.hostname)
        self.userEdit.setText(p.username)
        self.portSpin.setValue(p.port)
        idx = self.strictCombo.findText(p.strict_host_checking)
        self.strictCombo.setCurrentIndex(idx if idx >= 0 else 0)

        for w in (self.nameEdit, self.keyEdit, self.aliasEdit,
                  self.hostEdit, self.userEdit, self.portSpin, self.strictCombo):
            w.blockSignals(False)

        self._refresh_pubkey_display()
        self._dirty = False

    def _on_field_changed(self, *_):
        self._dirty = True
        if self._current_idx >= 0:
            self._flush_editor_to_profile(self._current_idx)
            item = self.profileList.item(self._current_idx)
            if isinstance(item, ProfileItem):
                item.refresh_label()

    def _flush_editor_to_profile(self, idx: int):
        if idx < 0 or idx >= len(self._profiles):
            return
        p = self._profiles[idx]
        p.name                = self.nameEdit.text().strip()
        p.key_path            = self.keyEdit.text().strip()
        p.host_alias          = self.aliasEdit.text().strip()
        p.hostname            = self.hostEdit.text().strip()
        p.username            = self.userEdit.text().strip() or "git"
        p.port                = self.portSpin.value()
        p.strict_host_checking = self.strictCombo.currentText()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _add_profile(self):
        if self._dirty and self._current_idx >= 0:
            self._flush_editor_to_profile(self._current_idx)
        p = SSHProfile(name=t("ssh.new_profile_name"))
        self._profiles.append(p)
        self.profileList.addItem(ProfileItem(p))
        self.profileList.setCurrentRow(len(self._profiles) - 1)

    def _remove_profile(self):
        row = self.profileList.currentRow()
        if row < 0:
            return
        name = self._profiles[row].name or t("ssh.profile_no_name")
        ret = QMessageBox.question(
            self, t("ssh.confirm_remove.title"),
            t("ssh.confirm_remove.text", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self._profiles.pop(row)
            self._populate_list()
            self._current_idx = -1
            self._dirty = False
            new_row = min(row, len(self._profiles) - 1)
            if new_row >= 0:
                self.profileList.setCurrentRow(new_row)
            else:
                self.editorPanel.setEnabled(False)

    # ── Key management ────────────────────────────────────────────────────────

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("ssh.browse_key_title"),
            os.path.expanduser("~/.ssh"),
            t("ssh.browse_key_filter"),
        )
        if path:
            self.keyEdit.setText(path)
            self._refresh_pubkey_display()

    def _refresh_pubkey_display(self):
        key = self.keyEdit.text().strip()
        pub = key + ".pub" if key else ""
        if pub and os.path.exists(pub):
            try:
                text = Path(pub).read_text().strip()
                if len(text) > 90:
                    display = text[:55] + "..." + text[-25:]
                else:
                    display = text
                self.pubkeyLabel.setText(display)
            except Exception:
                self.pubkeyLabel.setText(t("ssh.pubkey_read_error"))
        else:
            self.pubkeyLabel.setText(t("ssh.pubkey_not_found"))

    def _copy_pubkey(self):
        key = self.keyEdit.text().strip()
        pub = key + ".pub" if key else ""
        if not pub or not os.path.exists(pub):
            QMessageBox.warning(self, t("ssh.copy_pubkey.title"), t("ssh.copy_pubkey.no_file"))
            return
        text = Path(pub).read_text().strip()
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, t("ssh.copy_pubkey.done_title"), t("ssh.copy_pubkey.done_text"))

    def _generate_key(self):
        if not shutil.which("ssh-keygen"):
            QMessageBox.critical(self, t("ssh.keygen.error.title"), t("ssh.keygen_not_found_msg"))
            return

        dlg = KeyGenerateDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        key_path = dlg.result_path()
        if not key_path or not Path(key_path).exists():
            QMessageBox.warning(self, t("ssh.key_not_created.title"), t("ssh.key_not_created.text"))
            return

        # Auto-create profile
        comment = dlg.result_comment()
        p = SSHProfile(
            name=comment or Path(key_path).stem,
            key_path=key_path,
        )
        self._profiles.append(p)
        self._populate_list()
        self.profileList.setCurrentRow(len(self._profiles) - 1)

        QMessageBox.information(self, t("ssh.key_created.title"), t("ssh.key_created.text", path=key_path))
        self._refresh_agent_status()

    def _import_keys(self):
        existing_paths = {p.key_path for p in self._profiles}
        found = scan_default_ssh_keys()
        new_keys = [k for k in found if k not in existing_paths]

        if not new_keys:
            QMessageBox.information(self, t("ssh.import.confirm.title"), t("ssh.import.none_found"))
            return

        msg = t("ssh.import.confirm.text", keys="\n".join(f"  • {k}" for k in new_keys))
        ret = QMessageBox.question(self, t("ssh.import.confirm.title"), msg,
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return

        for k in new_keys:
            p = SSHProfile(name=Path(k).stem, key_path=k)
            self._profiles.append(p)

        self._populate_list()
        self.profileList.setCurrentRow(len(self._profiles) - 1)

    # ── Test connection ────────────────────────────────────────────────────────

    def _test_connection(self):
        if self._current_idx >= 0:
            self._flush_editor_to_profile(self._current_idx)
        row = self.profileList.currentRow()
        if row < 0:
            return
        p = self._profiles[row]

        if not p.key_path or not os.path.exists(p.key_path):
            self.testOutput.setPlainText(t("ssh.test.no_key"))
            return
        if not p.hostname:
            self.testOutput.setPlainText(t("ssh.test.no_host"))
            return

        target = p.host_alias or p.hostname
        self.testButton.setEnabled(False)
        self.testOutput.setPlainText(t("ssh.test.connecting"))

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
                self.testOutput.setPlainText("✓ " + output)
            else:
                self.testOutput.setPlainText(output or t("ssh.test.exit_code", code=result.returncode))
        except subprocess.TimeoutExpired:
            self.testOutput.setPlainText(t("ssh.test.timeout"))
        except Exception as e:
            self.testOutput.setPlainText(t("ssh.test.error", error=str(e)))
        finally:
            self.testButton.setEnabled(True)

    # ── Save ──────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """Always persist profiles — whether user clicks Save, Cancel, or X."""
        if self._dirty and self._current_idx >= 0:
            self._flush_editor_to_profile(self._current_idx)
        save_ssh_profiles(self._profiles)
        super().closeEvent(event)

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
