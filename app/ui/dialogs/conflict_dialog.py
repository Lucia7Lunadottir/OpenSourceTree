import os
import subprocess
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QPlainTextEdit, QMessageBox
from PyQt6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont
)

from app.i18n import t
from app.git.repo import GitRepo
from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("conflict_dialog.ui")


class _ConflictHighlighter(QSyntaxHighlighter):
    _FMT_OURS    = None
    _FMT_SEP     = None
    _FMT_THEIRS  = None
    _FMT_CONTENT_OURS   = None
    _FMT_CONTENT_THEIRS = None

    def __init__(self, document):
        super().__init__(document)
        self._in_ours   = False
        self._in_theirs = False

        def fmt(bg, fg, bold=False):
            f = QTextCharFormat()
            f.setBackground(QColor(bg))
            f.setForeground(QColor(fg))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            return f

        self._FMT_OURS   = fmt("#4a1a1a", "#ff8080", bold=True)
        self._FMT_SEP    = fmt("#3a3a10", "#e0d060", bold=True)
        self._FMT_THEIRS = fmt("#1a3a1a", "#80cc80", bold=True)
        self._FMT_CONTENT_OURS   = fmt("#2e1a1a", "#ffb0b0")
        self._FMT_CONTENT_THEIRS = fmt("#1a2e1a", "#a8e0a8")

    def highlightBlock(self, text: str):
        if text.startswith("<<<<<<<"):
            self._in_ours = True
            self._in_theirs = False
            self.setFormat(0, len(text), self._FMT_OURS)
        elif text.startswith("======="):
            self._in_ours = False
            self._in_theirs = True
            self.setFormat(0, len(text), self._FMT_SEP)
        elif text.startswith(">>>>>>>"):
            self._in_theirs = False
            self.setFormat(0, len(text), self._FMT_THEIRS)
        elif self._in_ours:
            self.setFormat(0, len(text), self._FMT_CONTENT_OURS)
        elif self._in_theirs:
            self.setFormat(0, len(text), self._FMT_CONTENT_THEIRS)


class ConflictDialog(QDialog):
    # widgets created by loadUi from conflict_dialog.ui
    infoLabel: QLabel
    editor: QPlainTextEdit
    oursButton: QPushButton
    theirsButton: QPushButton
    editorButton: QPushButton
    primaryButton: QPushButton   # "Mark resolved"; objectName is a style.qss selector
    closeButton: QPushButton

    def __init__(self, repo: GitRepo, path: str, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._path = path
        filename = os.path.basename(path)
        uic.loadUi(_UI_FILE, self)
        UiTranslator({self.objectName(): {"filename": filename}}).apply(self)
        self._highlighter = _ConflictHighlighter(self.editor.document())
        self.oursButton.clicked.connect(self._on_accept_ours)
        self.theirsButton.clicked.connect(self._on_accept_theirs)
        self.editorButton.clicked.connect(self._on_open_editor)
        self.primaryButton.clicked.connect(self._on_mark_resolved)
        self.closeButton.clicked.connect(self.reject)
        self._load()

    def _load(self):
        content = self._repo.conflict_content(self._path)
        self.editor.setPlainText(content)
        n = content.count("<<<<<<<")
        self.infoLabel.setText(
            t("conflict.sections", n=n) if n else t("conflict.no_markers")
        )
        # Disable resolve button until user explicitly acts
        self.primaryButton.setEnabled(n == 0)

    # ----------------------------------------------------------------- Actions

    def _on_accept_ours(self):
        try:
            self._repo.resolve_ours(self._path)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, t("conflict.error"), str(e))

    def _on_accept_theirs(self):
        try:
            self._repo.resolve_theirs(self._path)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, t("conflict.error"), str(e))

    def _on_open_editor(self):
        full_path = os.path.join(self._repo.path, self._path)
        opened = False

        # Try $VISUAL / $EDITOR env vars first
        for var in ("VISUAL", "EDITOR"):
            editor = os.environ.get(var, "")
            if editor:
                try:
                    subprocess.Popen([editor, full_path])
                    opened = True
                    break
                except Exception:
                    pass

        # Fallback: xdg-open
        if not opened:
            try:
                subprocess.Popen(["xdg-open", full_path])
                opened = True
            except Exception:
                pass

        if opened:
            # After editing, reload content and enable resolve button
            self._reload_after_edit()
        else:
            QMessageBox.information(
                self, t("conflict.open_editor"),
                t("conflict.no_editor", path=full_path)
            )

    def _reload_after_edit(self):
        """Re-read file from disk and enable 'Mark Resolved' if no markers remain."""
        content = self._repo.conflict_content(self._path)
        self.editor.setPlainText(content)
        n = content.count("<<<<<<<")
        self.infoLabel.setText(
            t("conflict.sections", n=n) if n else t("conflict.no_markers")
        )
        self.primaryButton.setEnabled(True)   # let user decide

    def _on_mark_resolved(self):
        try:
            self._repo.mark_resolved(self._path)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, t("conflict.error"), str(e))
