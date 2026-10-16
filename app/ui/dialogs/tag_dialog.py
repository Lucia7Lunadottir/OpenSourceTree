import os
import subprocess
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QLineEdit, QCheckBox, QDialogButtonBox, QMessageBox, QLabel,
    QPushButton, QPlainTextEdit, QProgressBar
)
from PyQt6.QtCore import QThreadPool

from app.i18n import t
from app.git.repo import GitRepo
from app.git.runner import is_auth_error, find_terminal
from app.config import ensure_agent_running, scan_default_ssh_keys, load_ssh_profiles
from app.ui.ui_translator import UiTranslator
from app.workers.git_worker import GitWorker
from app.workers.streaming_worker import StreamingWorker

_UI_FILE = Path(__file__).with_name("tag_dialog.ui")


class TagDialog(QDialog):
    # widgets created by loadUi from tag_dialog.ui
    nameEdit: QLineEdit
    refEdit: QLineEdit
    messageEdit: QLineEdit
    pushCheck: QCheckBox
    progressBar: QProgressBar
    outputEdit: QPlainTextEdit
    statusLabel: QLabel
    agentButton: QPushButton
    terminalButton: QPushButton
    buttonBox: QDialogButtonBox

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._tag_name = ""
        self._remote = "origin"
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)

        # shown only while pushing / after an auth error
        for w in (self.progressBar, self.outputEdit, self.agentButton, self.terminalButton):
            w.setVisible(False)
        # a standard button's text can't be set in Designer
        self._ok_btn = self.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText(t("tag.btn"))

        self.agentButton.clicked.connect(self._add_to_agent_and_retry)
        self.terminalButton.clicked.connect(self._retry_in_terminal)
        self.buttonBox.accepted.connect(self._on_accept)
        self.buttonBox.rejected.connect(self.reject)

    def _set_busy(self, text: str):
        self.statusLabel.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        self.statusLabel.setText(text)
        self._ok_btn.setEnabled(False)

    def _on_accept(self):
        name = self.nameEdit.text().strip()
        if not name:
            QMessageBox.warning(self, t("tag.title"), t("tag.error.empty_name"))
            return
        self._tag_name = name
        ref     = self.refEdit.text().strip() or "HEAD"
        message = self.messageEdit.text().strip()

        self._set_busy(t("tag.creating"))
        worker = GitWorker(self._repo.create_tag, name, ref, message)
        worker.signals.result.connect(lambda _: self._after_create())
        worker.signals.error.connect(self._on_create_error)
        QThreadPool.globalInstance().start(worker)

    def _after_create(self):
        if not self.pushCheck.isChecked():
            self.accept()
            return
        self._start_push()

    def _start_push(self):
        self.agentButton.setVisible(False)
        self.terminalButton.setVisible(False)
        self.outputEdit.clear()
        self.outputEdit.setVisible(True)
        self.progressBar.setRange(0, 0)
        self.progressBar.setVisible(True)
        self._set_busy(t("tag.pushing"))

        worker = StreamingWorker(
            lambda: self._repo.push_tag_streaming(self._tag_name, self._remote)
        )
        worker.signals.progress_text.connect(self._on_push_line)
        worker.signals.result.connect(self._on_push_done)
        worker.signals.error.connect(self._on_push_error)
        QThreadPool.globalInstance().start(worker)

    def _on_push_line(self, line: str):
        if line.strip():
            self.outputEdit.appendPlainText(line.rstrip())
            sb = self.outputEdit.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_push_done(self, _):
        self.progressBar.setRange(0, 1)
        self.progressBar.setValue(1)
        self.progressBar.setVisible(False)
        self.accept()

    def _on_push_error(self, error: str):
        self.progressBar.setRange(0, 1)
        self.progressBar.setValue(1)
        self.progressBar.setVisible(False)
        self._ok_btn.setEnabled(True)

        if is_auth_error(error):
            self.agentButton.setVisible(True)
            self.terminalButton.setVisible(True)
            self.statusLabel.setStyleSheet("color: rgb(255,100,100); font-size: 11px;")
            self.statusLabel.setText(t("remote.auth_required"))
        else:
            lines = [l for l in error.splitlines() if l.strip()]
            short = lines[-1] if lines else t("remote.error")
            self.statusLabel.setStyleSheet("color: rgb(255,100,100); font-size: 11px;")
            self.statusLabel.setText(f"✗  {short}")

    def _on_create_error(self, error: str):
        self._ok_btn.setEnabled(True)
        self.statusLabel.setStyleSheet("color: rgb(255,100,100); font-size: 11px;")
        self.statusLabel.setText("")
        QMessageBox.critical(self, t("tag.error"), error)

    # ── SSH agent recovery ────────────────────────────────────────────────────

    def _find_ssh_key(self) -> str:
        for p in load_ssh_profiles():
            if p.key_path and os.path.exists(p.key_path):
                return p.key_path
        keys = scan_default_ssh_keys()
        return keys[0] if keys else ""

    def _add_to_agent_and_retry(self):
        import shlex
        key = self._find_ssh_key()
        if not key:
            QMessageBox.warning(
                self, "ssh-agent",
                "SSH-ключ не найден.\n"
                "Укажите путь к ключу в Настройки → SSH-ключи."
            )
            return

        if not ensure_agent_running():
            QMessageBox.warning(
                self, "ssh-agent",
                "Не удалось запустить ssh-agent.\n"
                "Запустите его вручную:\n  eval $(ssh-agent)"
            )
            return

        terminal = find_terminal()
        if not terminal:
            QMessageBox.warning(self, "ssh-agent", "Терминал не найден.")
            return

        self.agentButton.setVisible(False)
        self.terminalButton.setVisible(False)
        self.statusLabel.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        self.statusLabel.setText(t("remote.opening_terminal"))

        cmd = (
            f"ssh-add {shlex.quote(key)}; "
            f'echo ""; echo "──── Нажмите Enter чтобы продолжить ────"; read _'
        )
        term_name = os.path.basename(terminal)
        if term_name == "konsole":
            proc = subprocess.Popen(
                [terminal, "--hide-menubar", "--hide-tabbar", "-e", "bash", "-c", cmd]
            )
        else:
            proc = subprocess.Popen([terminal, "-e", "bash", "-c", cmd])
        proc.wait()

        check = subprocess.run(["ssh-add", "-l"], capture_output=True, text=True)
        if check.returncode != 0:
            self.statusLabel.setText(t("remote.auth_required"))
            self.agentButton.setVisible(True)
            self.terminalButton.setVisible(True)
            return

        self.outputEdit.clear()
        self._start_push()

    def _retry_in_terminal(self):
        self.agentButton.setVisible(False)
        self.terminalButton.setVisible(False)
        self.statusLabel.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        self.statusLabel.setText(t("remote.opening_terminal"))
        try:
            self._repo.runner.run_in_terminal(
                ["push", self._remote, f"refs/tags/{self._tag_name}"]
            )
            self.statusLabel.setText(t("remote.done_terminal"))
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, t("remote.terminal_error"), str(e))
            self._ok_btn.setEnabled(True)
