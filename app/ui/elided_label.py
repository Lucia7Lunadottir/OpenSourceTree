from PyQt6.QtWidgets import QLabel, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QMouseEvent, QFontMetrics


class ClickableElidedLabel(QLabel):
    """One-line label that never forces its parent to grow.

    A plain QLabel reports the width of its full text as its minimum size, so a
    long (or multi-line git error) message stretched the whole window to the
    screen width. This label shows the text elided with "…" to whatever width
    it is given, keeps the full text in the tooltip and emits `clicked`.
    """
    clicked = pyqtSignal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_full_text(text)

    def set_full_text(self, text: str):
        self._full_text = text
        self.setToolTip(text)
        self._apply_elide()

    def full_text(self) -> str:
        return self._full_text

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:
        return QSize(0, super().sizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self):
        one_line = " ".join(self._full_text.split())
        fm = QFontMetrics(self.font())
        # setText on QLabel would re-derive the size hint from the elided text
        # only, which is fine: it is at most `width()` wide by construction.
        super().setText(fm.elidedText(one_line, Qt.TextElideMode.ElideRight, max(self.width(), 0)))

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)
