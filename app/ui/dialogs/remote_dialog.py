import os
import subprocess
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QCheckBox, QDialogButtonBox,
    QMessageBox, QProgressBar, QLabel, QPushButton, QPlainTextEdit
)
from PyQt6.QtCore import QThreadPool

from app.i18n import t
from app.git.repo import GitRepo
from app.git.runner import is_auth_error, find_terminal
from app.config import ensure_agent_running, scan_default_ssh_keys, load_ssh_profiles
from app.ui.ui_translator import UiTranslator
from app.workers.streaming_worker import StreamingWorker

_UI_FILE = Path(__file__).with_name("remote_dialog.ui")


class RemoteDialog(QDialog):
    # widgets created by loadUi from remote_dialog.ui
    formLayout: QFormLayout
    remoteCombo: QComboBox
    branchCombo: QComboBox
    pruneCheck: QCheckBox
    fetchTagsCheck: QCheckBox
    rebaseCheck: QCheckBox
    forceCheck: QCheckBox
    tagsCheck: QCheckBox
    progressBar: QProgressBar
    liveLineLabel: QLabel
    output: QPlainTextEdit
    statusLabel: QLabel
    agentButton: QPushButton
    terminalButton: QPushButton
    upstreamButton: QPushButton
    buttonBox: QDialogButtonBox

    # option checkboxes the .ui holds for every mode; only these are shown
    _MODE_OPTIONS = {
        "fetch": ("pruneCheck", "fetchTagsCheck"),
        "pull":  ("rebaseCheck",),
        "push":  ("forceCheck", "tagsCheck"),
    }
    _ALL_OPTIONS = ("pruneCheck", "fetchTagsCheck", "rebaseCheck", "forceCheck", "tagsCheck")

    def __init__(self, repo: GitRepo, mode: str = "fetch", parent=None):
        super().__init__(parent)
        self._repo = repo
        self._mode = mode
        self._last_args = None
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)
        title_keys = {
            "fetch": "remote.title.fetch",
            "pull":  "remote.title.pull",
            "push":  "remote.title.push",
        }
        self.setWindowTitle(t(title_keys.get(mode, "remote.title.fetch")))
        self._setup_ui()

    def _setup_ui(self):
        remotes = self._get_remotes()
        if self._mode == "fetch":
            # Only fetch actually treats an empty remote as --all (every
            # remote). Push/pull silently fall back to a single default
            # remote instead, so offering "(all)" there implied a
            # multi-remote push/pull that never happened.
            self.remoteCombo.addItems([t("remote.all")] + remotes)
        else:
            self.remoteCombo.addItems(remotes)
            tracked = self._get_tracked_remote()
            if tracked and tracked in remotes:
                self.remoteCombo.setCurrentText(tracked)

        if self._mode in ("pull", "push"):
            self._branch_placeholder = t("remote.current_branch_placeholder")
            self.branchCombo.addItem(self._branch_placeholder)
            for b in self._get_branches():
                self.branchCombo.addItem(b)
            self.branchCombo.setCurrentIndex(0)
        else:
            self.formLayout.setRowVisible(self.branchCombo, False)

        shown = self._MODE_OPTIONS.get(self._mode, ())
        for name in self._ALL_OPTIONS:
            getattr(self, name).setVisible(name in shown)

        # hidden until an operation runs / fails
        for w in (self.progressBar, self.liveLineLabel, self.output,
                  self.agentButton, self.terminalButton, self.upstreamButton):
            w.setVisible(False)

        self.agentButton.clicked.connect(self._add_to_agent_and_retry)
        self.terminalButton.clicked.connect(self._retry_in_terminal)
        self.upstreamButton.clicked.connect(lambda: self._on_accept(set_upstream=True))

        self._ok_btn = self.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText(t(f"remote.title.{self._mode}"))
        self.buttonBox.accepted.connect(self._on_accept)
        self.buttonBox.rejected.connect(self.reject)

    def _get_remotes(self) -> list[str]:
        try:
            return [r.name for r in self._repo.get_remotes()]
        except Exception:
            return ["origin"]

    def _get_tracked_remote(self) -> str:
        """Remote the current branch's upstream points at, e.g. "origin"."""
        try:
            for b in self._repo.get_branches():
                if not b.is_remote and b.is_current and b.tracking:
                    return b.tracking.split("/", 1)[0]
        except Exception:
            pass
        return ""

    def _branch_text(self) -> str:
        """Return selected branch name, or '' if placeholder is selected."""
        text = self.branchCombo.currentText().strip()
        if text == self._branch_placeholder:
            return ""
        return text

    def _get_branches(self) -> list[str]:
        try:
            all_branches = self._repo.get_branches()
            local = [b.name for b in all_branches if not b.is_remote]
            if self._mode == "push":
                # A remote-tracking name like "origin/main" is not a valid
                # push *source* the way it looks — `git push aur origin/main`
                # resolves it (it exists as refs/remotes/origin/main) and
                # pushes it to `aur` under the literal name "origin/main",
                # silently creating a wrongly-named branch instead of
                # pushing "main". Only local branches make sense to push.
                return local
            remote = [b.name for b in all_branches if b.is_remote]
            return local + remote
        except Exception:
            return []

    def _build_fn(self, set_upstream: bool = False):
        remote = self.remoteCombo.currentText()
        if remote == t("remote.all"):
            remote = ""

        if self._mode == "fetch":
            prune = self.pruneCheck.isChecked()
            tags  = self.fetchTagsCheck.isChecked()
            self._last_args = (
                ["fetch"]
                + (["--prune"] if prune else [])
                + (["--tags"] if tags else [])
                + [remote or "--all"]
            )
            return lambda: self._repo.fetch_streaming(remote, prune, tags)

        elif self._mode == "pull":
            branch = self._branch_text()
            rebase = self.rebaseCheck.isChecked()
            self._last_args = ["pull"] + (["--rebase"] if rebase else []) + (
                [remote] if remote else []) + ([branch] if branch else [])
            return lambda: self._repo.pull_streaming(remote, branch, rebase)

        elif self._mode == "push":
            branch = self._branch_text()
            if set_upstream and not branch:
                # --set-upstream fails exactly like a bare push does when
                # there's no upstream yet unless the branch is named
                # explicitly too — resolve "(current branch)" for real.
                try:
                    branch = self._repo.get_head()
                except Exception:
                    pass
            force  = self.forceCheck.isChecked()
            tags   = self.tagsCheck.isChecked()
            self._last_args = ["push"] + (["--force-with-lease"] if force else []) + (
                ["--tags"] if tags else []) + (["--set-upstream"] if set_upstream else []) + (
                [remote] if remote else []) + (
                [branch] if branch else [])
            return lambda: self._repo.push_streaming(remote, branch, force, tags, set_upstream)

    def _on_accept(self, set_upstream: bool = False):
        fn = self._build_fn(set_upstream)
        self.terminalButton.setVisible(False)
        self.upstreamButton.setVisible(False)
        self._ok_btn.setEnabled(False)
        self.output.clear()
        self.output.setVisible(True)
        self.liveLineLabel.setText("")
        self.liveLineLabel.setVisible(True)
        self.progressBar.setRange(0, 0)
        self.progressBar.setVisible(True)
        self.statusLabel.setText(t(f"remote.title.{self._mode}") + "...")

        worker = StreamingWorker(fn)
        worker.signals.progress_text.connect(self._on_line)
        worker.signals.result.connect(self._on_done)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    # Prefixes that git uses for \r-overwritten in-place progress lines
    _PROGRESS_PREFIXES = (
        "Enumerating objects",
        "Counting objects",
        "Compressing objects",
        "Writing objects",
        "Total ",
        "Receiving objects",
        "Resolving deltas",
    )

    def _on_line(self, line: str):
        line = line.strip()
        if not line:
            return
        if any(line.startswith(p) for p in self._PROGRESS_PREFIXES):
            # Update the live progress label in place
            self.liveLineLabel.setText(line)
        else:
            self.output.appendPlainText(line)
            sb = self.output.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_done(self, _result):
        self.progressBar.setRange(0, 1)
        self.progressBar.setValue(1)
        self.progressBar.setVisible(False)
        self.liveLineLabel.setVisible(False)
        self.statusLabel.setText(t("remote.done"))
        self.accept()

    def _on_error(self, error: str):
        self.progressBar.setRange(0, 1)
        self.progressBar.setValue(1)
        self.progressBar.setVisible(False)
        self.liveLineLabel.setVisible(False)
        self._ok_btn.setEnabled(True)

        if is_auth_error(error):
            self.agentButton.setVisible(True)
            self.terminalButton.setVisible(True)
            self.statusLabel.setStyleSheet("color: rgb(255, 100, 100);")
            self.statusLabel.setText(t("remote.auth_required"))
        elif self._mode == "push" and "no upstream branch" in error.lower():
            # `git push <remote>` with no branch arg fails outright when the
            # current branch has never been pushed anywhere — happens a lot
            # when pushing an existing branch to a *second* remote (e.g. an
            # AUR git remote alongside origin). Offer to redo it with
            # --set-upstream instead of surfacing raw git jargon.
            self.upstreamButton.setVisible(True)
            self.statusLabel.setStyleSheet("color: rgb(255, 100, 100);")
            self.statusLabel.setText(t("remote.no_upstream"))
        else:
            # Output is already visible in the QPlainTextEdit above;
            # show the last non-empty line as a compact status hint.
            lines = [l for l in error.splitlines() if l.strip()]
            short = lines[-1] if lines else t("remote.error")
            self.statusLabel.setStyleSheet("color: rgb(255, 100, 100);")
            self.statusLabel.setText(f"✗  {short}")

    def _retry_in_terminal(self):
        if not self._last_args:
            return
        self.terminalButton.setVisible(False)
        self.agentButton.setVisible(False)
        self.statusLabel.setText(t("remote.opening_terminal"))
        try:
            self._repo.runner.run_in_terminal(self._last_args)
            self.statusLabel.setText(t("remote.done_terminal"))
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

        self.agentButton.setVisible(False)
        self.terminalButton.setVisible(False)
        self.statusLabel.setStyleSheet("color: rgb(140, 120, 180);")
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

        # Check the key was actually added
        check = subprocess.run(["ssh-add", "-l"], capture_output=True, text=True)
        if check.returncode != 0:
            # Agent is empty → user probably cancelled
            self.statusLabel.setText(t("remote.auth_required"))
            self.agentButton.setVisible(True)
            self.terminalButton.setVisible(True)
            return

        # Key is now in agent — retry the operation automatically
        self.statusLabel.setStyleSheet("color: rgb(140, 120, 180);")
        self.output.clear()
        self._on_accept()
