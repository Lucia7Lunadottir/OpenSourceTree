from PyQt6.QtWidgets import QWidget, QLabel, QAbstractButton, QGroupBox, QMenu
from PyQt6.QtGui import QAction

from app.i18n import t


class UiTranslator:
    """Replaces i18n keys stored in a Qt Designer .ui form with translated strings.

    The .ui keeps keys (e.g. "extract.btn_close") instead of text. `apply` walks
    the form once and runs every non-empty key through t(). Keys with
    placeholders get their arguments per widget objectName (the form's own
    objectName is used for the window title).

    Translated here: window title, QLabel / QAbstractButton text, QGroupBox and
    QMenu title, tooltips and placeholder texts, and QAction text / toolTip /
    statusTip (actions of the form, e.g. menu-bar and toolbar actions).
    Anything else is set from code.
    """

    def __init__(self, format_args: dict[str, dict] | None = None):
        self._format_args = format_args or {}

    def apply(self, root: QWidget) -> None:
        self._translate(root, root.windowTitle, root.setWindowTitle)
        for w in root.findChildren(QWidget):
            if isinstance(w, (QLabel, QAbstractButton)):
                self._translate(w, w.text, w.setText)
            elif isinstance(w, QGroupBox):
                self._translate(w, w.title, w.setTitle)
            elif isinstance(w, QMenu):
                self._translate(w, w.title, w.setTitle)
            if hasattr(w, "placeholderText"):
                self._translate(w, w.placeholderText, w.setPlaceholderText)
            self._translate(w, w.toolTip, w.setToolTip)
        for action in root.findChildren(QAction):
            self._translate_action(action)
        # Layout metrics were computed from the raw keys loadUi saw; recompute them
        # for the translated text so minimum sizes are not stale.
        for w in (root, *root.findChildren(QWidget)):
            if w.layout() is not None:
                w.layout().invalidate()
        if root.layout() is not None:
            root.layout().activate()

    def _translate_action(self, action: QAction) -> None:
        # Without an explicit toolTip, QAction.toolTip() returns its text (minus
        # '&'); translating that would freeze a copy of the text as a tooltip.
        text = action.text()
        own_tooltip = action.toolTip() not in (text, text.replace("&", ""))
        self._translate(action, action.text, action.setText)
        if own_tooltip:
            self._translate(action, action.toolTip, action.setToolTip)
        self._translate(action, action.statusTip, action.setStatusTip)

    def _translate(self, obj, getter, setter) -> None:
        key = getter()
        if key and " " not in key and "." in key:   # a key, not literal text
            setter(t(key, **self._format_args.get(obj.objectName(), {})))
