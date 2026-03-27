import os
import subprocess

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QComboBox,
    QCheckBox, QDialogButtonBox, QMessageBox, QProgressBar, QLabel,
    QPushButton, QPlainTextEdit
)
from PyQt6.QtCore import QThreadPool

from app.i18n import t
from app.git.repo import GitRepo
from app.git.runner import is_auth_error, find_terminal
from app.config import ensure_agent_running, scan_default_ssh_keys, load_ssh_profiles
from app.workers.streaming_worker import StreamingWorker


class RemoteDialog(QDialog):
    def __init__(self, repo: GitRepo, mode: str = "fetch", parent=None):
        super().__init__(parent)
        self._repo = repo
        self._mode = mode
        self._last_args = None
        title_keys = {
            "fetch": "remote.title.fetch",
            "pull":  "remote.title.pull",
            "push":  "remote.title.push",
        }
        self.setWindowTitle(t(title_keys.get(mode, "remote.title.fetch")))
        self.setMinimumWidth(480)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        remotes = self._get_remotes()
        self._remote_combo = QComboBox()
        self._remote_combo.addItems([t("remote.all")] + remotes)
        form.addRow(t("remote.label"), self._remote_combo)

        if self._mode in ("pull", "push"):
            self._branch_placeholder = (
                "(текущая)" if t("remote.branch") == "Ветка:" else "(current branch)"
            )
            self._branch_combo = QComboBox()
            self._branch_combo.setEditable(True)
            self._branch_combo.addItem(self._branch_placeholder)
            for b in self._get_branches():
                self._branch_combo.addItem(b)
            self._branch_combo.setCurrentIndex(0)
            form.addRow(t("remote.branch"), self._branch_combo)

        layout.addLayout(form)

        if self._mode == "fetch":
            self._prune_check = QCheckBox(t("remote.prune"))
            self._fetch_tags_check = QCheckBox(t("remote.fetch_tags"))
            self._fetch_tags_check.setChecked(True)
            layout.addWidget(self._prune_check)
            layout.addWidget(self._fetch_tags_check)
        elif self._mode == "pull":
            self._rebase_check = QCheckBox(t("remote.rebase"))
            layout.addWidget(self._rebase_check)
        elif self._mode == "push":
            self._force_check = QCheckBox(t("remote.force_push"))
            self._tags_check  = QCheckBox(t("remote.include_tags"))
            layout.addWidget(self._force_check)
            layout.addWidget(self._tags_check)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(110)   # ~6 lines
        self._output.setVisible(False)
        font = self._output.font()
        font.setFamily("Monospace")
        font.setPointSize(9)
        self._output.setFont(font)
        layout.addWidget(self._output)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: rgb(140, 120, 180);")
        layout.addWidget(self._status_label)

        self._agent_btn = QPushButton(t("remote.add_to_agent"))
        self._agent_btn.setVisible(False)
        self._agent_btn.clicked.connect(self._add_to_agent_and_retry)
        layout.addWidget(self._agent_btn)

        self._terminal_btn = QPushButton(t("remote.retry_terminal"))
        self._terminal_btn.setVisible(False)
        self._terminal_btn.clicked.connect(self._retry_in_terminal)
        layout.addWidget(self._terminal_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText(t(f"remote.title.{self._mode}"))
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _get_remotes(self) -> list[str]:
        try:
            return [r.name for r in self._repo.get_remotes()]
        except Exception:
            return ["origin"]

    def _branch_text(self) -> str:
        """Return selected branch name, or '' if placeholder is selected."""
        text = self._branch_combo.currentText().strip()
        if text == self._branch_placeholder:
            return ""
        return text

    def _get_branches(self) -> list[str]:
        try:
            return [b.name for b in self._repo.get_branches() if not b.is_remote]
        except Exception:
            return []

    def _build_fn(self):
        remote = self._remote_combo.currentText()
        if remote == t("remote.all"):
            remote = ""

        if self._mode == "fetch":
            prune = self._prune_check.isChecked()
            tags  = self._fetch_tags_check.isChecked()
            self._last_args = (
                ["fetch"]
                + (["--prune"] if prune else [])
                + (["--tags"] if tags else [])
                + [remote or "--all"]
            )
            return lambda: self._repo.fetch_streaming(remote, prune, tags)

        elif self._mode == "pull":
            branch = self._branch_text()
            rebase = self._rebase_check.isChecked()
            self._last_args = ["pull"] + (["--rebase"] if rebase else []) + (
                [remote] if remote else []) + ([branch] if branch else [])
            return lambda: self._repo.pull_streaming(remote, branch, rebase)

        elif self._mode == "push":
            branch = self._branch_text()
            force  = self._force_check.isChecked()
            tags   = self._tags_check.isChecked()
            self._last_args = ["push"] + (["--force-with-lease"] if force else []) + (
                ["--tags"] if tags else []) + ([remote] if remote else []) + (
                [branch] if branch else [])
            return lambda: self._repo.push_streaming(remote, branch, force, tags)

    def _on_accept(self):
        fn = self._build_fn()
        self._terminal_btn.setVisible(False)
        self._ok_btn.setEnabled(False)
        self._output.clear()
        self._output.setVisible(True)
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)
        self._status_label.setText(t(f"remote.title.{self._mode}") + "...")

        worker = StreamingWorker(fn)
        worker.signals.progress_text.connect(self._on_line)
        worker.signals.result.connect(self._on_done)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_line(self, line: str):
        if line.strip():
            self._output.appendPlainText(line)
            sb = self._output.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_done(self, _result):
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._progress.setVisible(False)
        self._status_label.setText(t("remote.done"))
        self.accept()

    def _on_error(self, error: str):
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._progress.setVisible(False)
        self._ok_btn.setEnabled(True)

        if is_auth_error(error):
            self._agent_btn.setVisible(True)
            self._terminal_btn.setVisible(True)
            self._status_label.setStyleSheet("color: rgb(255, 100, 100);")
            self._status_label.setText(t("remote.auth_required"))
        else:
            # Output is already visible in the QPlainTextEdit above;
            # show the last non-empty line as a compact status hint.
            lines = [l for l in error.splitlines() if l.strip()]
            short = lines[-1] if lines else t("remote.error")
            self._status_label.setStyleSheet("color: rgb(255, 100, 100);")
            self._status_label.setText(f"✗  {short}")

    def _retry_in_terminal(self):
        if not self._last_args:
            return
        self._terminal_btn.setVisible(False)
        self._agent_btn.setVisible(False)
        self._status_label.setText(t("remote.opening_terminal"))
        try:
            self._repo.runner.run_in_terminal(self._last_args)
            self._status_label.setText(t("remote.done_terminal"))
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, t("remote.terminal_error"), str(e))
            self._ok_btn.setEnabled(True)

    # ----------------------------------------------------------------- Agent

    def _find_ssh_key(self) -> str:
        """Return the most likely SSH private key path, or ''."""
        for p in load_ssh_profiles():
            if p.key_path and os.path.exists(p.key_path):
                return p.key_path
        keys = scan_default_ssh_keys()
        return keys[0] if keys else ""

    def _add_to_agent_and_retry(self):
        """Add SSH key to agent (once), then retry the git operation silently."""
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
        self._status_label.setStyleSheet("color: rgb(140, 120, 180);")
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

        # Check the key was actually added
        check = subprocess.run(["ssh-add", "-l"], capture_output=True, text=True)
        if check.returncode != 0:
            # Agent is empty → user probably cancelled
            self._status_label.setText(t("remote.auth_required"))
            self._agent_btn.setVisible(True)
            self._terminal_btn.setVisible(True)
            return

        # Key is now in agent — retry the operation automatically
        self._status_label.setStyleSheet("color: rgb(140, 120, 180);")
        self._output.clear()
        self._on_accept()
