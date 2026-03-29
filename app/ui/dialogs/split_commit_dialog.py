from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QTreeWidget, QTreeWidgetItem, QPushButton, QProgressBar,
    QDialogButtonBox, QSizePolicy, QFrame
)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QColor, QFont

from app.i18n import t
from app.git.repo import GitRepo
from app.workers.git_worker import GitWorker

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
    def __init__(self, repo: GitRepo, sha: str, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._sha  = sha
        self._batches: list[list[str]] = []
        self._file_sizes: list[tuple[str, int]] = []
        self._message = ""

        self.setWindowTitle(t("split_commit.title"))
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self._setup_ui()
        self._load_data()

    # ------------------------------------------------------------------ UI

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Subtitle
        self._subtitle = QLabel("…")
        self._subtitle.setWordWrap(True)
        font = QFont()
        font.setPointSize(10)
        self._subtitle.setFont(font)
        layout.addWidget(self._subtitle)

        # Spinner / loading label
        self._loading_label = QLabel(t("split_commit.splitting") + " …")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setStyleSheet("color: #9cdcfe;")
        layout.addWidget(self._loading_label)

        # Batches container (hidden while loading)
        self._batches_widget = QFrame()
        self._batches_layout = QVBoxLayout(self._batches_widget)
        self._batches_layout.setContentsMargins(0, 0, 0, 0)
        self._batches_layout.setSpacing(4)
        self._batches_widget.setVisible(False)
        layout.addWidget(self._batches_widget, 1)

        # Large-file warning area
        self._warn_label = QLabel("")
        self._warn_label.setWordWrap(True)
        self._warn_label.setStyleSheet("color: #ce9178;")
        self._warn_label.setVisible(False)
        layout.addWidget(self._warn_label)

        # Progress bar (hidden until Split clicked)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)   # indeterminate
        self._progress_bar.setFixedHeight(14)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        # Buttons
        self._button_box = QDialogButtonBox()
        self._split_btn  = self._button_box.addButton(
            t("split_commit.btn_split"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._split_btn.setObjectName("primaryButton")
        self._split_btn.setEnabled(False)
        self._button_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._button_box.rejected.connect(self.reject)
        self._split_btn.clicked.connect(self._on_split)
        layout.addWidget(self._button_box)

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
        self._loading_label.setVisible(False)

        self._batches = _compute_batches(file_sizes)
        total = sum(s for _, s in file_sizes)
        n = len(self._batches)
        short_sha = self._sha[:7]
        self._subtitle.setText(
            t("split_commit.subtitle",
              sha=short_sha,
              message=self._message[:60],
              size=_fmt_size(total),
              n=n)
        )

        self._populate_batches()
        self._check_warnings(file_sizes)
        self._batches_widget.setVisible(True)
        self._split_btn.setEnabled(len(self._batches) > 1)

    def _on_load_error(self, err: str):
        self._loading_label.setText(f"Error: {err}")

    # ------------------------------------------------------------------ Batch display

    def _populate_batches(self):
        # Clear previous content
        while self._batches_layout.count():
            item = self._batches_layout.takeAt(0)
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
            self._batches_layout.addWidget(group)

    def _check_warnings(self, file_sizes: list[tuple[str, int]]):
        large = [(p, s) for p, s in file_sizes if s > GITHUB_FILE_MAX]
        if not large:
            self._warn_label.setVisible(False)
            return
        lines = [
            t("split_commit.large_file_warn", path=p, size=_fmt_size(s))
            for p, s in large
        ]
        self._warn_label.setText("\n".join(lines))
        self._warn_label.setVisible(True)

    # ------------------------------------------------------------------ Split

    def _on_split(self):
        if not self._batches:
            return
        self._split_btn.setEnabled(False)
        self._progress_bar.setVisible(True)

        worker = GitWorker(
            self._repo.split_commit, self._sha, self._batches, self._message
        )
        worker.signals.result.connect(self._on_split_done)
        worker.signals.error.connect(self._on_split_error)
        QThreadPool.globalInstance().start(worker)

    def _on_split_done(self, _):
        self._progress_bar.setVisible(False)
        self.accept()

    def _on_split_error(self, err: str):
        from PyQt6.QtWidgets import QMessageBox
        self._progress_bar.setVisible(False)
        self._split_btn.setEnabled(True)
        QMessageBox.critical(self, t("error.git_error"), err)
