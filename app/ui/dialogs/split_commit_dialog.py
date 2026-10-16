from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QGroupBox,
    QTreeWidget, QTreeWidgetItem, QPushButton, QProgressBar,
    QDialogButtonBox, QSizePolicy, QFrame
)
from PyQt6.QtCore import QThreadPool
from PyQt6.QtGui import QColor

from app.i18n import t
from app.git.repo import GitRepo
from app.ui.ui_translator import UiTranslator
from app.workers.git_worker import GitWorker

_UI_FILE = Path(__file__).with_name("split_commit_dialog.ui")

GITHUB_FILE_MAX = 100 * 1024 * 1024   # 100 MB
BATCH_LIMIT     = 1 * 1024 * 1024 * 1024  # 1 GB


def _fmt_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024**3:.1f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024**2:.0f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def _compute_batches(file_sizes: list[tuple[str, int]]) -> list[list[str]]:
    """Greedy batch assignment. Files >GITHUB_FILE_MAX each get their own batch.
    Deletions (size=0) are appended to the last batch."""
    deletions = [p for p, s in file_sizes if s == 0]
    non_zero  = [(p, s) for p, s in file_sizes if s > 0]
    # Sort largest first so big files go first and don't fragment small ones
    non_zero.sort(key=lambda x: x[1], reverse=True)

    batches: list[list[str]] = []
    current_batch: list[str] = []
    current_size = 0

    for path, size in non_zero:
        if size > GITHUB_FILE_MAX and current_batch:
            # This file is already oversized — give it its own batch
            batches.append(current_batch)
            current_batch = [path]
            current_size = size
        elif current_size + size > BATCH_LIMIT and current_batch:
            batches.append(current_batch)
            current_batch = [path]
            current_size = size
        else:
            current_batch.append(path)
            current_size += size

    if current_batch:
        batches.append(current_batch)

    if deletions:
        if batches:
            batches[-1].extend(deletions)
        else:
            batches.append(deletions)

    return batches


class SplitCommitDialog(QDialog):
    # widgets created by loadUi from split_commit_dialog.ui
    subtitleLabel: QLabel
    loadingLabel: QLabel
    batchesFrame: QFrame
    batchesLayout: QVBoxLayout
    warnLabel: QLabel
    progressBar: QProgressBar
    primaryButton: QPushButton   # "Split"; objectName is a style.qss selector
    buttonBox: QDialogButtonBox

    def __init__(self, repo: GitRepo, sha: str, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._sha  = sha
        self._batches: list[list[str]] = []
        self._file_sizes: list[tuple[str, int]] = []
        self._message = ""

        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)
        self._setup_ui()
        self._load_data()

    # ------------------------------------------------------------------ UI

    def _setup_ui(self):
        # hidden while loading / until Split is clicked
        for w in (self.batchesFrame, self.warnLabel, self.progressBar):
            w.setVisible(False)
        # Designer can't put a custom button inside a QDialogButtonBox:
        # the .ui lays it out next to the box, here it moves into it.
        self.buttonBox.addButton(self.primaryButton, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttonBox.rejected.connect(self.reject)
        self.primaryButton.clicked.connect(self._on_split)

    # ------------------------------------------------------------------ Data loading

    def _load_data(self):
        try:
            detail = self._repo.get_commit_detail(self._sha)
            self._message = detail.message if detail else self._sha[:8]
        except Exception:
            self._message = self._sha[:8]

        worker = GitWorker(self._repo.get_commit_file_sizes, self._sha)
        worker.signals.result.connect(self._on_data_ready)
        worker.signals.error.connect(self._on_load_error)
        QThreadPool.globalInstance().start(worker)

    def _on_data_ready(self, file_sizes: list[tuple[str, int]]):
        self._file_sizes = file_sizes
        self.loadingLabel.setVisible(False)

        self._batches = _compute_batches(file_sizes)
        total = sum(s for _, s in file_sizes)
        n = len(self._batches)
        short_sha = self._sha[:7]
        self.subtitleLabel.setText(
            t("split_commit.subtitle",
              sha=short_sha,
              message=self._message[:60],
              size=_fmt_size(total),
              n=n)
        )

        self._populate_batches()
        self._check_warnings(file_sizes)
        self.batchesFrame.setVisible(True)
        self.primaryButton.setEnabled(len(self._batches) > 1)

    def _on_load_error(self, err: str):
        self.loadingLabel.setText(f"Error: {err}")

    # ------------------------------------------------------------------ Batch display

    def _populate_batches(self):
        # Clear previous content
        while self.batchesLayout.count():
            item = self.batchesLayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        size_map = dict(self._file_sizes)

        for i, batch in enumerate(self._batches, 1):
            batch_size = sum(size_map.get(p, 0) for p in batch)
            header = t("split_commit.batch_header", i=i, size=_fmt_size(batch_size))

            group = QGroupBox(header)
            group.setFlat(False)
            gl = QVBoxLayout(group)
            gl.setContentsMargins(4, 4, 4, 4)
            gl.setSpacing(2)

            tree = QTreeWidget()
            tree.setColumnCount(2)
            tree.setHeaderHidden(True)
            tree.setRootIsDecorated(False)
            tree.header().setStretchLastSection(False)
            tree.setColumnWidth(0, 360)
            tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

            for path in batch:
                sz = size_map.get(path, 0)
                item = QTreeWidgetItem([path, _fmt_size(sz)])
                item.setForeground(0, QColor("#d4d4d4"))
                item.setForeground(1, QColor("#9cdcfe"))
                if sz > GITHUB_FILE_MAX:
                    item.setForeground(0, QColor("#ce9178"))
                tree.addTopLevelItem(item)

            # Adjust height to content
            tree.setMinimumHeight(min(len(batch) * 22 + 4, 150))
            tree.setMaximumHeight(min(len(batch) * 22 + 4, 150))
            gl.addWidget(tree)
            self.batchesLayout.addWidget(group)

    def _check_warnings(self, file_sizes: list[tuple[str, int]]):
        large = [(p, s) for p, s in file_sizes if s > GITHUB_FILE_MAX]
        if not large:
            self.warnLabel.setVisible(False)
            return
        lines = [
            t("split_commit.large_file_warn", path=p, size=_fmt_size(s))
            for p, s in large
        ]
        self.warnLabel.setText("\n".join(lines))
        self.warnLabel.setVisible(True)

    # ------------------------------------------------------------------ Split

    def _on_split(self):
        if not self._batches:
            return
        self.primaryButton.setEnabled(False)
        self.progressBar.setVisible(True)

        worker = GitWorker(
            self._repo.split_commit, self._sha, self._batches, self._message
        )
        worker.signals.result.connect(self._on_split_done)
        worker.signals.error.connect(self._on_split_error)
        QThreadPool.globalInstance().start(worker)

    def _on_split_done(self, _):
        self.progressBar.setVisible(False)
        self.accept()

    def _on_split_error(self, err: str):
        from PyQt6.QtWidgets import QMessageBox
        self.progressBar.setVisible(False)
        self.primaryButton.setEnabled(True)
        QMessageBox.critical(self, t("error.git_error"), err)
