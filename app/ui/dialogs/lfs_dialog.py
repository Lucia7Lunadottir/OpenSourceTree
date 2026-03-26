from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QProgressBar, QPlainTextEdit,
    QInputDialog, QMessageBox, QAbstractItemView, QFrame
)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QFont

from app.i18n import t
from app.git.repo import GitRepo
from app.workers.git_worker import GitWorker
from app.workers.streaming_worker import StreamingWorker


def _fmt_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class LfsDialog(QDialog):
    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self.setWindowTitle(t("lfs.title"))
        self.setMinimumSize(600, 480)
        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Tracked patterns row
        patterns_row = QHBoxLayout()
        self._patterns_label = QLabel("")
        self._patterns_label.setWordWrap(True)
        self._patterns_label.setStyleSheet("color: #9cdcfe;")
        patterns_row.addWidget(QLabel(t("lfs.tracked") + ":"), 0)
        patterns_row.addWidget(self._patterns_label, 1)
        layout.addLayout(patterns_row)

        btn_row = QHBoxLayout()
        self._track_btn = QPushButton(t("lfs.track_btn"))
        self._untrack_btn = QPushButton(t("lfs.untrack_btn"))
        self._track_btn.clicked.connect(self._on_track)
        self._untrack_btn.clicked.connect(self._on_untrack)
        btn_row.addWidget(self._track_btn)
        btn_row.addWidget(self._untrack_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #3c3c3c;")
        layout.addWidget(sep)

        # File table
        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels([t("lfs.col_file"), t("lfs.col_size"), t("lfs.col_status")])
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(0, self._tree.header().ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, self._tree.header().ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, self._tree.header().ResizeMode.ResizeToContents)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setAlternatingRowColors(True)
        self._tree.itemDoubleClicked.connect(self._on_file_dbl_click)
        layout.addWidget(self._tree)

        # Action buttons
        action_row = QHBoxLayout()
        self._dl_all_btn = QPushButton(t("lfs.download_all"))
        self._push_btn   = QPushButton(t("lfs.push_objs"))
        self._prune_btn  = QPushButton(t("lfs.prune"))
        self._refresh_btn = QPushButton(t("toolbar.refresh"))
        for btn in (self._dl_all_btn, self._push_btn, self._prune_btn, self._refresh_btn):
            action_row.addWidget(btn)
        layout.addLayout(action_row)

        self._dl_all_btn.clicked.connect(self._on_download_all)
        self._push_btn.clicked.connect(self._on_push)
        self._prune_btn.clicked.connect(self._on_prune)
        self._refresh_btn.clicked.connect(self._refresh)

        # Progress + output
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(110)
        mono = QFont("Monospace", 9)
        self._output.setFont(mono)
        self._output.setVisible(False)
        layout.addWidget(self._output)

    def _refresh(self):
        patterns = self._repo.lfs_tracked_patterns()
        self._patterns_label.setText(", ".join(patterns) if patterns else "—")

        self._tree.clear()
        entries = self._repo.lfs_list_files()
        for entry in entries:
            item = QTreeWidgetItem([
                entry.path,
                _fmt_size(entry.size),
                t("lfs.downloaded") if entry.downloaded else t("lfs.pointer"),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, entry)
            if not entry.downloaded:
                item.setForeground(2, self._tree.palette().color(
                    self._tree.palette().ColorRole.Highlight))
            self._tree.addTopLevelItem(item)

    def _on_track(self):
        pattern, ok = QInputDialog.getText(self, t("lfs.track_btn"), t("lfs.track_prompt"))
        if ok and pattern.strip():
            try:
                self._repo.lfs_track(pattern.strip())
                self._refresh()
            except Exception as e:
                QMessageBox.critical(self, t("lfs.error"), str(e))

    def _on_untrack(self):
        item = self._tree.currentItem()
        if not item:
            return
        entry = item.data(0, Qt.ItemDataRole.UserRole)
        if not entry:
            return
        try:
            self._repo.lfs_untrack(entry.path)
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
        self._output.appendPlainText(msg)
        self._set_busy(False)
        self._refresh()

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
