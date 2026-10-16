import os
import fnmatch as _fnmatch
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QPushButton, QTreeWidget, QTreeWidgetItem, QProgressBar,
    QPlainTextEdit, QInputDialog, QMessageBox, QListWidget, QListWidgetItem,
    QHeaderView
)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QColor

from app.i18n import t
from app.git.repo import GitRepo
from app.ui.ui_translator import UiTranslator
from app.workers.git_worker import GitWorker
from app.workers.streaming_worker import StreamingWorker

_UI_FILE = Path(__file__).with_name("lfs_dialog.ui")

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
    # widgets created by loadUi from lfs_dialog.ui
    patternsList: QListWidget
    trackButton: QPushButton
    untrackButton: QPushButton
    fileTree: QTreeWidget
    downloadAllButton: QPushButton
    pushObjectsButton: QPushButton
    pruneButton: QPushButton
    refreshButton: QPushButton
    progressBar: QProgressBar
    output: QPlainTextEdit

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)
        self._setup_ui()
        self._refresh()

    # ----------------------------------------------------------------- UI

    def _setup_ui(self):
        # Column header texts are i18n keys in the .ui; per-section resize
        # modes can't be expressed in Designer.
        header_item = self.fileTree.headerItem()
        for col in range(self.fileTree.columnCount()):
            header_item.setText(col, t(header_item.text(col)))
        hdr = self.fileTree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        # hidden until an operation runs
        self.progressBar.setVisible(False)
        self.output.setVisible(False)

        self.trackButton.clicked.connect(self._on_track)
        self.untrackButton.clicked.connect(self._on_untrack)
        self.fileTree.itemDoubleClicked.connect(self._on_file_dbl_click)
        self.downloadAllButton.clicked.connect(self._on_download_all)
        self.pushObjectsButton.clicked.connect(self._on_push)
        self.pruneButton.clicked.connect(self._on_prune)
        self.refreshButton.clicked.connect(self._refresh)

    # ----------------------------------------------------------------- Data

    def _refresh(self):
        # Patterns list
        patterns = self._repo.lfs_tracked_patterns()
        self.patternsList.clear()
        for pat in patterns:
            self.patternsList.addItem(QListWidgetItem(pat))

        # File tree
        self.fileTree.clear()
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
            self.fileTree.addTopLevelItem(item)

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
        item = self.patternsList.currentItem()
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
        self.output.setVisible(True)
        self.output.appendPlainText(msg)
        self._set_busy(False)
        self._refresh()

    # ----------------------------------------------------------------- Helpers

    def _run_streaming(self, fn):
        self.output.clear()
        self.output.setVisible(True)
        self._set_busy(True)
        worker = StreamingWorker(fn)
        worker.signals.progress_text.connect(self._on_stream_line)
        worker.signals.result.connect(lambda _: self._on_stream_done())
        worker.signals.error.connect(self._on_stream_error)
        QThreadPool.globalInstance().start(worker)

    def _on_stream_line(self, line: str):
        if line.strip():
            self.output.appendPlainText(line)
            sb = self.output.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_stream_done(self):
        self._set_busy(False)
        self._refresh()

    def _on_stream_error(self, error: str):
        self._set_busy(False)
        self.output.appendPlainText(f"[Error] {error}")
        QMessageBox.critical(self, t("lfs.error"), error)

    def _set_busy(self, busy: bool):
        self.progressBar.setVisible(busy)
        for btn in (self.downloadAllButton, self.pushObjectsButton, self.pruneButton,
                    self.trackButton, self.untrackButton, self.refreshButton):
            btn.setEnabled(not busy)
