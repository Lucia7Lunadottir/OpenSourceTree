from PyQt6.QtWidgets import QWidget, QLabel, QAbstractButton, QGroupBox

from app.i18n import t


class UiTranslator:
    """Replaces i18n keys stored in a Qt Designer .ui form with translated strings.

    The .ui keeps keys (e.g. "extract.btn_close") instead of text. `apply` walks
    the form once and runs every non-empty key through t(). Keys with
    placeholders get their arguments per widget objectName (the form's own
    objectName is used for the window title).

    Translated here: window title, QLabel / QAbstractButton text, QGroupBox
    title, tooltips and placeholder texts. Anything else is set from code.
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
            if hasattr(w, "placeholderText"):
                self._translate(w, w.placeholderText, w.setPlaceholderText)
            self._translate(w, w.toolTip, w.setToolTip)
        # Layout metrics were computed from the raw keys loadUi saw; recompute them
        # for the translated text so minimum sizes are not stale.
        for w in (root, *root.findChildren(QWidget)):
            if w.layout() is not None:
                w.layout().invalidate()
        if root.layout() is not None:
            root.layout().activate()

    def _translate(self, widget: QWidget, getter, setter) -> None:
        key = getter()
        if key and " " not in key and "." in key:   # a key, not literal text
            setter(t(key, **self._format_args.get(widget.objectName(), {})))
