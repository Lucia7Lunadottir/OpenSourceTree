from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QComboBox,
    QCheckBox, QDialogButtonBox, QMessageBox, QProgressBar, QLabel,
    QPushButton, QPlainTextEdit
)
from PyQt6.QtCore import QThreadPool

from app.i18n import t
from app.git.repo import GitRepo
from app.git.runner import is_auth_error
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
            layout.addWidget(self._prune_check)
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
            self._last_args = ["fetch"] + (["--prune"] if prune else []) + [remote or "--all"]
            return lambda: self._repo.fetch_streaming(remote, prune)

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
        lines = [l for l in error.splitlines() if l.strip()]
        short = lines[-1] if lines else t("remote.error")
        self._status_label.setText(short)

        if is_auth_error(error):
            self._terminal_btn.setVisible(True)
            self._status_label.setText(t("remote.auth_required"))
        else:
            QMessageBox.critical(self, t("error.git_error"), error)

    def _retry_in_terminal(self):
        if not self._last_args:
            return
        self._terminal_btn.setVisible(False)
        self._status_label.setText(t("remote.opening_terminal"))
        try:
            self._repo.runner.run_in_terminal(self._last_args)
            self._status_label.setText(t("remote.done_terminal"))
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, t("remote.terminal_error"), str(e))
            self._ok_btn.setEnabled(True)
