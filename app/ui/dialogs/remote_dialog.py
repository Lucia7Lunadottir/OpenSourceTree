from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QComboBox, QLineEdit,
    QCheckBox, QDialogButtonBox, QMessageBox, QProgressBar, QLabel, QPushButton
)
from PyQt6.QtCore import QThreadPool

from app.git.repo import GitRepo
from app.git.runner import is_auth_error
from app.workers.git_worker import GitWorker


class RemoteDialog(QDialog):
    def __init__(self, repo: GitRepo, mode: str = "fetch", parent=None):
        super().__init__(parent)
        self._repo = repo
        self._mode = mode
        self._last_args = None   # saved for terminal retry
        titles = {"fetch": "Fetch", "pull": "Pull", "push": "Push"}
        self.setWindowTitle(titles.get(mode, "Remote"))
        self.setMinimumWidth(380)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        remotes = self._get_remotes()
        self._remote_combo = QComboBox()
        self._remote_combo.addItems(["(все)"] + remotes)
        form.addRow("Remote:", self._remote_combo)

        if self._mode in ("pull", "push"):
            self._branch_edit = QLineEdit()
            self._branch_edit.setPlaceholderText("(текущая ветка)")
            form.addRow("Ветка:", self._branch_edit)

        layout.addLayout(form)

        if self._mode == "fetch":
            self._prune_check = QCheckBox("Удалить удалённые ветки (--prune)")
            layout.addWidget(self._prune_check)
        elif self._mode == "pull":
            self._rebase_check = QCheckBox("Rebase вместо merge")
            layout.addWidget(self._rebase_check)
        elif self._mode == "push":
            self._force_check = QCheckBox("Force push (--force-with-lease)")
            self._tags_check = QCheckBox("Включить теги (--tags)")
            layout.addWidget(self._force_check)
            layout.addWidget(self._tags_check)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: rgb(140, 120, 180);")
        layout.addWidget(self._status_label)

        # Terminal retry button (hidden until auth error)
        self._terminal_btn = QPushButton("🖥  Повторить в терминале (нужен пароль / кодовая фраза)")
        self._terminal_btn.setVisible(False)
        self._terminal_btn.clicked.connect(self._retry_in_terminal)
        layout.addWidget(self._terminal_btn)

        btn_row = QHBoxLayout()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText(self._mode.capitalize())
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addLayout(btn_row)
        layout.addWidget(buttons)

    def _get_remotes(self) -> list[str]:
        try:
            return [r.name for r in self._repo.get_remotes()]
        except Exception:
            return ["origin"]

    def _build_args(self) -> tuple[list[str], callable]:
        """Return (git args for terminal, repo callable for worker)."""
        remote = self._remote_combo.currentText()
        if remote == "(все)":
            remote = ""

        if self._mode == "fetch":
            prune = self._prune_check.isChecked()
            args = ["fetch"]
            if prune:
                args.append("--prune")
            if remote:
                args.append(remote)
            else:
                args.append("--all")
            fn = lambda: self._repo.fetch(remote, prune)

        elif self._mode == "pull":
            branch = self._branch_edit.text().strip()
            rebase = self._rebase_check.isChecked()
            args = ["pull"]
            if rebase:
                args.append("--rebase")
            if remote:
                args.append(remote)
            if branch:
                args.append(branch)
            fn = lambda: self._repo.pull(remote, branch, rebase)

        elif self._mode == "push":
            branch = self._branch_edit.text().strip()
            force = self._force_check.isChecked()
            tags = self._tags_check.isChecked()
            args = ["push"]
            if force:
                args.append("--force-with-lease")
            if tags:
                args.append("--tags")
            if remote:
                args.append(remote)
            if branch:
                args.append(branch)
            fn = lambda: self._repo.push(remote, branch, force, tags)

        return args, fn

    def _on_accept(self):
        args, fn = self._build_args()
        self._last_args = args
        self._terminal_btn.setVisible(False)
        self._ok_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._status_label.setText(f"{self._mode.capitalize()}...")

        worker = GitWorker(fn)
        worker.signals.result.connect(self._on_done)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_done(self, result):
        self._progress.setVisible(False)
        self._status_label.setText("Готово.")
        self.accept()

    def _on_error(self, error: str):
        self._progress.setVisible(False)
        self._ok_btn.setEnabled(True)
        lines = [l for l in error.splitlines() if l.strip()]
        short = lines[-1] if lines else "Ошибка"
        self._status_label.setText(short)

        if is_auth_error(error):
            # Show terminal button instead of a modal dialog
            self._terminal_btn.setVisible(True)
            self._status_label.setText(
                "⚠  Требуется авторизация. Нажмите кнопку ниже чтобы повторить в терминале."
            )
        else:
            QMessageBox.critical(self, "Git Error", error)

    def _retry_in_terminal(self):
        if not self._last_args:
            return
        self._terminal_btn.setVisible(False)
        self._status_label.setText("Открываем терминал...")
        try:
            self._repo.runner.run_in_terminal(self._last_args)
            self._status_label.setText("Готово (операция выполнена в терминале).")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка терминала", str(e))
            self._ok_btn.setEnabled(True)
