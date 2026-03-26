import os
import fnmatch as _fnmatch

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QProgressBar, QPlainTextEdit,
    QInputDialog, QMessageBox, QAbstractItemView, QFrame,
    QListWidget, QListWidgetItem, QSplitter
)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QFont, QColor

from app.i18n import t
from app.git.repo import GitRepo
from app.workers.git_worker import GitWorker
from app.workers.streaming_worker import StreamingWorker

LFS_ICON = "⬡"   # hollow hexagon — LFS badge


def _fmt_size(size: int) -> str:
    if size == 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def matches_lfs(path: str, patterns: list[str]) -> bool:
    """Return True if path matches any LFS tracked pattern."""
    name = os.path.basename(path)
    for pat in patterns:
        # Simple glob on basename (*.psd) or full path (models/**)
        if _fnmatch.fnmatch(name, pat):
            return True
        flat = pat.replace("**", "*")
        if _fnmatch.fnmatch(path, flat):
            return True
    return False


class LfsDialog(QDialog):
    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self.setWindowTitle(t("lfs.title"))
        self.setMinimumSize(640, 560)
        self._setup_ui()
        self._refresh()

    # ----------------------------------------------------------------- UI

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── Tracked patterns ──────────────────────────────────────────
        layout.addWidget(QLabel(f"<b>{t('lfs.tracked')}</b>"))

        self._patterns_list = QListWidget()
        self._patterns_list.setMaximumHeight(90)
        self._patterns_list.setAlternatingRowColors(True)
        layout.addWidget(self._patterns_list)

        pat_btn_row = QHBoxLayout()
        self._track_btn   = QPushButton(t("lfs.track_btn"))
        self._untrack_btn = QPushButton(t("lfs.untrack_btn"))
        self._track_btn.setToolTip(t("lfs.track_tooltip"))
        self._untrack_btn.setToolTip(t("lfs.untrack_tooltip"))
        self._track_btn.clicked.connect(self._on_track)
        self._untrack_btn.clicked.connect(self._on_untrack)
        pat_btn_row.addWidget(self._track_btn)
        pat_btn_row.addWidget(self._untrack_btn)
        pat_btn_row.addStretch()
        layout.addLayout(pat_btn_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #3c3c3c;")
        layout.addWidget(sep)

        # ── File table ────────────────────────────────────────────────
        layout.addWidget(QLabel(f"<b>{t('lfs.files_title')}</b>"))

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels([
            t("lfs.col_file"), t("lfs.col_size"), t("lfs.col_status")
        ])
        hdr = self._tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, hdr.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, hdr.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, hdr.ResizeMode.ResizeToContents)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setAlternatingRowColors(True)
        self._tree.setToolTip(t("lfs.tree_tooltip"))
        self._tree.itemDoubleClicked.connect(self._on_file_dbl_click)
        layout.addWidget(self._tree)

        # ── Action buttons ────────────────────────────────────────────
        action_row = QHBoxLayout()
        self._dl_all_btn  = QPushButton(t("lfs.download_all"))
        self._push_btn    = QPushButton(t("lfs.push_objs"))
        self._prune_btn   = QPushButton(t("lfs.prune"))
        self._refresh_btn = QPushButton(t("toolbar.refresh"))

        self._dl_all_btn.setToolTip(t("lfs.download_all_tooltip"))
        self._push_btn.setToolTip(t("lfs.push_objs_tooltip"))
        self._prune_btn.setToolTip(t("lfs.prune_tooltip"))

        for btn in (self._dl_all_btn, self._push_btn,
                    self._prune_btn, self._refresh_btn):
            action_row.addWidget(btn)
        layout.addLayout(action_row)

        self._dl_all_btn.clicked.connect(self._on_download_all)
        self._push_btn.clicked.connect(self._on_push)
        self._prune_btn.clicked.connect(self._on_prune)
        self._refresh_btn.clicked.connect(self._refresh)

        # ── Progress + output ─────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(110)
        self._output.setFont(QFont("Monospace", 9))
        self._output.setVisible(False)
        layout.addWidget(self._output)

    # ----------------------------------------------------------------- Data

    def _refresh(self):
        # Patterns list
        patterns = self._repo.lfs_tracked_patterns()
        self._patterns_list.clear()
        for pat in patterns:
            self._patterns_list.addItem(QListWidgetItem(pat))

        # File tree
        self._tree.clear()
        entries = self._repo.lfs_list_files()
        for entry in entries:
            label = f"{LFS_ICON} {entry.path}"
            status_text = t("lfs.downloaded") if entry.downloaded else t("lfs.pointer")
            item = QTreeWidgetItem([label, _fmt_size(entry.size), status_text])
            item.setData(0, Qt.ItemDataRole.UserRole, entry)
            if not entry.downloaded:
                item.setForeground(2, QColor("#dcdcaa"))   # yellow warning
                item.setToolTip(0, t("lfs.pointer_tooltip"))
            else:
                item.setForeground(2, QColor("#4ec9b0"))   # teal ok
            self._tree.addTopLevelItem(item)

    # ----------------------------------------------------------------- Slots

    def _on_track(self):
        pattern, ok = QInputDialog.getText(
            self, t("lfs.track_btn"), t("lfs.track_prompt")
        )
        if ok and pattern.strip():
            try:
                self._repo.lfs_track(pattern.strip())
                self._refresh()
            except Exception as e:
                QMessageBox.critical(self, t("lfs.error"), str(e))

    def _on_untrack(self):
        item = self._patterns_list.currentItem()
        if not item:
            QMessageBox.information(self, t("lfs.untrack_btn"),
                                    t("lfs.untrack_select_hint"))
            return
        pattern = item.text()
        try:
            self._repo.lfs_untrack(pattern)
            self._refresh()
        except Exception as e:
            QMessageBox.critical(self, t("lfs.error"), str(e))

    def _on_file_dbl_click(self, item: QTreeWidgetItem, _col: int):
        entry = item.data(0, Qt.ItemDataRole.UserRole)
        if entry and not entry.downloaded:
            self._run_streaming(lambda: self._repo.lfs_pull([entry.path]))

    def _on_download_all(self):
        self._run_streaming(self._repo.lfs_pull)

    def _on_push(self):
        remotes = [r.name for r in self._repo.get_remotes()]
        remote = remotes[0] if remotes else "origin"
        self._run_streaming(lambda: self._repo.lfs_push(remote))

    def _on_prune(self):
        self._set_busy(True)
        worker = GitWorker(self._repo.lfs_prune)
        worker.signals.result.connect(lambda msg: self._on_prune_done(str(msg)))
        worker.signals.error.connect(self._on_stream_error)
        worker.signals.finished.connect(lambda: self._set_busy(False))
        QThreadPool.globalInstance().start(worker)

    def _on_prune_done(self, msg: str):
        self._output.setVisible(True)
        self._output.appendPlainText(msg)
        self._set_busy(False)
        self._refresh()

    # ----------------------------------------------------------------- Helpers

    def _run_streaming(self, fn):
        self._output.clear()
        self._output.setVisible(True)
        self._set_busy(True)
        worker = StreamingWorker(fn)
        worker.signals.progress_text.connect(self._on_stream_line)
        worker.signals.result.connect(lambda _: self._on_stream_done())
        worker.signals.error.connect(self._on_stream_error)
        QThreadPool.globalInstance().start(worker)

    def _on_stream_line(self, line: str):
        if line.strip():
            self._output.appendPlainText(line)
            sb = self._output.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_stream_done(self):
        self._set_busy(False)
        self._refresh()

    def _on_stream_error(self, error: str):
        self._set_busy(False)
        self._output.appendPlainText(f"[Error] {error}")
        QMessageBox.critical(self, t("lfs.error"), error)

    def _set_busy(self, busy: bool):
        self._progress.setVisible(busy)
        for btn in (self._dl_all_btn, self._push_btn, self._prune_btn,
                    self._track_btn, self._untrack_btn, self._refresh_btn):
            btn.setEnabled(not busy)
