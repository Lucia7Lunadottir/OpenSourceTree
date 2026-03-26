from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QLineEdit,
    QPushButton, QAbstractItemView, QHeaderView, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex, QTimer

from app.git.repo import GitRepo
from app.git.models import CommitRecord
from .commit_table_model import CommitTableModel, COL_GRAPH, COL_HASH, COL_MESSAGE, COL_AUTHOR, COL_DATE
from .commit_graph_delegate import CommitGraphDelegate, LANE_W, ROW_H


class CommitListView(QWidget):
    commit_selected = pyqtSignal(object)   # CommitRecord or None
    working_copy_selected = pyqtSignal()

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Filter bar
        filter_bar = QWidget()
        filter_bar.setObjectName("filterBar")
        fb_layout = QHBoxLayout(filter_bar)
        fb_layout.setContentsMargins(4, 4, 4, 4)
        fb_layout.setSpacing(4)

        filter_icon = QLabel("🔍")
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter commits (message, author)...")
        self._filter_edit.setClearButtonEnabled(True)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedWidth(50)

        fb_layout.addWidget(filter_icon)
        fb_layout.addWidget(self._filter_edit)
        fb_layout.addWidget(self._clear_btn)
        layout.addWidget(filter_bar)

        # Commit table
        self._model = CommitTableModel(self._repo)
        self._view = QTableView()
        self._view.setModel(self._model)
        self._view.setItemDelegateForColumn(COL_GRAPH, CommitGraphDelegate(self._view))
        self._view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setShowGrid(False)
        self._view.setWordWrap(False)
        self._view.setAlternatingRowColors(False)
        self._view.verticalHeader().setVisible(False)
        self._view.verticalHeader().setDefaultSectionSize(ROW_H)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Column widths
        header = self._view.horizontalHeader()
        header.setSectionResizeMode(COL_GRAPH, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_HASH, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_MESSAGE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_AUTHOR, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_DATE, QHeaderView.ResizeMode.Interactive)
        self._view.setColumnWidth(COL_GRAPH, LANE_W * 8)
        self._view.setColumnWidth(COL_HASH, 70)
        self._view.setColumnWidth(COL_AUTHOR, 140)
        self._view.setColumnWidth(COL_DATE, 130)

        layout.addWidget(self._view)

        # Load more button
        self._load_more_btn = QPushButton("Load more commits...")
        self._load_more_btn.setVisible(False)
        layout.addWidget(self._load_more_btn)

        # Filter debounce timer
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(300)

    def _connect_signals(self):
        self._view.selectionModel().currentRowChanged.connect(self._on_row_changed)
        self._model.loading_done.connect(self._on_loading_done)
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        self._clear_btn.clicked.connect(self._filter_edit.clear)
        self._load_more_btn.clicked.connect(self._on_load_more)
        self._filter_timer.timeout.connect(self._apply_filter)

    def load_commits(self, branch: str = ""):
        self._model.load_initial(branch=branch)

    def refresh(self):
        branch = ""
        search = self._filter_edit.text()
        self._model.load_initial(branch=branch, search=search)

    def _on_row_changed(self, current: QModelIndex, previous: QModelIndex):
        if not current.isValid():
            self.commit_selected.emit(None)
            return
        commit = self._model.get_commit(current.row())
        if commit is None:
            # Working copy row
            self.working_copy_selected.emit()
        else:
            self.commit_selected.emit(commit)

    def _on_loading_done(self):
        self._load_more_btn.setVisible(self._model.canFetchMore())

    def _on_filter_changed(self, text: str):
        self._filter_timer.start()

    def _apply_filter(self):
        self._model.set_filter(self._filter_edit.text())

    def _on_load_more(self):
        if self._model.canFetchMore():
            self._model.fetchMore()

    def select_working_copy(self):
        """Select the first row (working copy) if present."""
        if self._model.rowCount() > 0:
            self._view.selectRow(0)
