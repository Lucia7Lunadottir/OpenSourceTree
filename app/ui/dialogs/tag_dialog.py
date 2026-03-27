import os
import subprocess

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QCheckBox,
    QDialogButtonBox, QMessageBox, QLabel, QPushButton, QPlainTextEdit,
    QProgressBar
)
from PyQt6.QtCore import QThreadPool

from app.i18n import t
from app.git.repo import GitRepo
from app.git.runner import is_auth_error, find_terminal
from app.config import ensure_agent_running, scan_default_ssh_keys, load_ssh_profiles
from app.workers.git_worker import GitWorker
from app.workers.streaming_worker import StreamingWorker


class TagDialog(QDialog):
    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._tag_name = ""
        self._remote = "origin"
        self.setWindowTitle(t("tag.title"))
        self.setMinimumWidth(400)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("v1.0.0")
        form.addRow(t("tag.name"), self._name_edit)

        self._ref_edit = QLineEdit("HEAD")
        form.addRow(t("tag.from_ref"), self._ref_edit)

        self._message_edit = QLineEdit()
        self._message_edit.setPlaceholderText(t("tag.message_placeholder"))
        form.addRow(t("tag.message"), self._message_edit)

        layout.addLayout(form)

        self._push_check = QCheckBox(t("tag.push_after"))
        self._push_check.setChecked(True)
        layout.addWidget(self._push_check)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(90)
        self._output.setVisible(False)
        font = self._output.font()
        font.setFamily("Monospace")
        font.setPointSize(9)
        self._output.setFont(font)
        layout.addWidget(self._output)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        layout.addWidget(self._status_label)

        self._agent_btn = QPushButton(t("remote.add_to_agent"))
        self._agent_btn.setVisible(False)
        self._agent_btn.clicked.connect(self._add_to_agent_and_retry)
        layout.addWidget(self._agent_btn)

        self._terminal_btn = QPushButton(t("remote.retry_terminal"))
        self._terminal_btn.setVisible(False)
        self._terminal_btn.clicked.connect(self._retry_in_terminal)
        layout.addWidget(self._terminal_btn)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText(t("tag.btn"))
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _set_busy(self, text: str):
        self._status_label.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        self._status_label.setText(text)
        self._ok_btn.setEnabled(False)

    def _on_accept(self):
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, t("tag.title"), t("tag.error.empty_name"))
            return
        self._tag_name = name
        ref     = self._ref_edit.text().strip() or "HEAD"
        message = self._message_edit.text().strip()

        self._set_busy(t("tag.creating"))
        worker = GitWorker(self._repo.create_tag, name, ref, message)
        worker.signals.result.connect(lambda _: self._after_create())
        worker.signals.error.connect(self._on_create_error)
        QThreadPool.globalInstance().start(worker)

    def _after_create(self):
        if not self._push_check.isChecked():
            self.accept()
            return
        self._start_push()

    def _start_push(self):
        self._agent_btn.setVisible(False)
        self._terminal_btn.setVisible(False)
        self._output.clear()
        self._output.setVisible(True)
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)
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
            self._output.appendPlainText(line.rstrip())
            sb = self._output.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_push_done(self, _):
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._progress.setVisible(False)
        self.accept()

    def _on_push_error(self, error: str):
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._progress.setVisible(False)
        self._ok_btn.setEnabled(True)

        if is_auth_error(error):
            self._agent_btn.setVisible(True)
            self._terminal_btn.setVisible(True)
            self._status_label.setStyleSheet("color: rgb(255,100,100); font-size: 11px;")
            self._status_label.setText(t("remote.auth_required"))
        else:
            lines = [l for l in error.splitlines() if l.strip()]
            short = lines[-1] if lines else t("remote.error")
            self._status_label.setStyleSheet("color: rgb(255,100,100); font-size: 11px;")
            self._status_label.setText(f"✗  {short}")

    def _on_create_error(self, error: str):
        self._ok_btn.setEnabled(True)
        self._status_label.setStyleSheet("color: rgb(255,100,100); font-size: 11px;")
        self._status_label.setText("")
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

        self._agent_btn.setVisible(False)
        self._terminal_btn.setVisible(False)
        self._status_label.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        self._status_label.setText(t("remote.opening_terminal"))

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
            self._status_label.setText(t("remote.auth_required"))
            self._agent_btn.setVisible(True)
            self._terminal_btn.setVisible(True)
            return

        self._output.clear()
        self._start_push()

    def _retry_in_terminal(self):
        self._agent_btn.setVisible(False)
        self._terminal_btn.setVisible(False)
        self._status_label.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        self._status_label.setText(t("remote.opening_terminal"))
        try:
            self._repo.runner.run_in_terminal(
                ["push", self._remote, f"refs/tags/{self._tag_name}"]
            )
            self._status_label.setText(t("remote.done_terminal"))
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, t("remote.terminal_error"), str(e))
            self._ok_btn.setEnabled(True)
