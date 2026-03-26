from enum import Enum, auto
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt

PAGE_SIZE = 200
MAX_LANES = 32

# Custom Qt roles
GraphRole = Qt.ItemDataRole.UserRole + 1
CommitRole = Qt.ItemDataRole.UserRole + 2

# Lane colors — Catppuccin Mocha, fits the Equestria OS purple theme
LANE_COLORS = [
    QColor("#cba6f7"),  # lavender
    QColor("#89dceb"),  # sky
    QColor("#a6e3a1"),  # green
    QColor("#fab387"),  # peach
    QColor("#f38ba8"),  # red
    QColor("#89b4fa"),  # blue
    QColor("#f9e2af"),  # yellow
    QColor("#94e2d5"),  # teal
]

# Ref badge colors (purple theme)
REF_LOCAL_COLOR  = QColor(100, 50, 140)   # selection purple
REF_REMOTE_COLOR = QColor(40,  90, 140)   # blue-ish
REF_TAG_COLOR    = QColor(80,  60,  20)   # dark amber
REF_HEAD_COLOR   = QColor(40, 110,  60)   # green


class FileStatus(Enum):
    MODIFIED     = "M"
    ADDED        = "A"
    DELETED      = "D"
    RENAMED      = "R"
    COPIED       = "C"
    UNTRACKED    = "?"
    IGNORED      = "!"
    UNMERGED     = "U"
    TYPE_CHANGED = "T"


class BranchType(Enum):
    LOCAL  = auto()
    REMOTE = auto()
    TAG    = auto()
    STASH  = auto()


# Status display colors (purple-friendly palette)
STATUS_COLORS = {
    FileStatus.MODIFIED:     QColor("#f9e2af"),  # yellow
    FileStatus.ADDED:        QColor("#a6e3a1"),  # green
    FileStatus.DELETED:      QColor("#f38ba8"),  # red
    FileStatus.RENAMED:      QColor("#89dceb"),  # sky
    FileStatus.COPIED:       QColor("#89dceb"),
    FileStatus.UNTRACKED:    QColor("#cba6f7"),  # lavender
    FileStatus.UNMERGED:     QColor("#f38ba8"),
    FileStatus.TYPE_CHANGED: QColor("#f9e2af"),
}
