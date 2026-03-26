from PyQt6.QtCore import (
    QAbstractTableModel, Qt, QModelIndex, pyqtSignal
)
from PyQt6.QtGui import QColor

from app.constants import GraphRole, CommitRole, PAGE_SIZE
from app.git.repo import GitRepo
from app.git.models import CommitRecord


COLUMNS = ["Graph", "Hash", "Message", "Author", "Date"]
COL_GRAPH = 0
COL_HASH = 1
COL_MESSAGE = 2
COL_AUTHOR = 3
COL_DATE = 4


class CommitTableModel(QAbstractTableModel):
    loading_done = pyqtSignal()

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._commits: list[CommitRecord] = []
        self._branch = ""
        self._search = ""
        self._has_more = True

    def load_initial(self, branch: str = "", search: str = ""):
        self._branch = branch
        self._search = search
        self.beginResetModel()
        self._commits = []
        self._has_more = True
        self.endResetModel()
        self._load_page(0)

    def _load_page(self, skip: int):
        try:
            new_commits = self._repo.get_commits(
                skip=skip,
                limit=PAGE_SIZE,
                branch=self._branch,
                search=self._search,
            )
        except Exception:
            new_commits = []

        if len(new_commits) < PAGE_SIZE:
            self._has_more = False

        if new_commits:
            start = len(self._commits)
            self.beginInsertRows(QModelIndex(), start, start + len(new_commits) - 1)
            self._commits.extend(new_commits)
            self.endInsertRows()

        self.loading_done.emit()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._commits)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._commits):
            return None

        commit = self._commits[index.row()]
        col = index.column()

        if role == GraphRole and col == COL_GRAPH:
            return commit.lane_data

        if role == CommitRole:
            return commit

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_GRAPH:
                return ""
            elif col == COL_HASH:
                return commit.short_hash
            elif col == COL_MESSAGE:
                return commit.message
            elif col == COL_AUTHOR:
                return commit.author
            elif col == COL_DATE:
                return commit.date.strftime("%Y-%m-%d %H:%M") if commit.date else ""

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_HASH:
                return QColor("#9cdcfe")
            elif col == COL_AUTHOR:
                return QColor("#ce9178")
            elif col == COL_DATE:
                return QColor("#888888")

        if role == Qt.ItemDataRole.ToolTipRole and col == COL_MESSAGE:
            refs_str = ", ".join(commit.refs) if commit.refs else ""
            return f"{commit.hash}\n{commit.message}\n{refs_str}".strip()

        return None

    def canFetchMore(self, parent=QModelIndex()) -> bool:
        return self._has_more

    def fetchMore(self, parent=QModelIndex()):
        self._load_page(len(self._commits))

    def set_filter(self, text: str):
        self.load_initial(branch=self._branch, search=text)

    def get_commit(self, row: int) -> CommitRecord | None:
        if 0 <= row < len(self._commits):
            return self._commits[row]
        return None

    def clear(self):
        self.beginResetModel()
        self._commits = []
        self._has_more = False
        self.endResetModel()
