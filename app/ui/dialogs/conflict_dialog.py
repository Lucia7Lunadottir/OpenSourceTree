import os
import subprocess

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QDialogButtonBox, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont
)

from app.i18n import t
from app.git.repo import GitRepo


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
    def __init__(self, repo: GitRepo, path: str, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._path = path
        filename = os.path.basename(path)
        self.setWindowTitle(t("conflict.title", filename=filename))
        self.setMinimumSize(700, 500)
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Info bar
        info = QFrame()
        info.setObjectName("conflictInfo")
        info_row = QHBoxLayout(info)
        info_row.setContentsMargins(8, 6, 8, 6)
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #dcdcaa; font-weight: bold;")
        info_row.addWidget(QLabel("⚠"))
        info_row.addWidget(self._info_label, 1)
        layout.addWidget(info)

        hint = QLabel(t("conflict.hint"))
        hint.setStyleSheet("color: #9cdcfe; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Content viewer
        self._editor = QPlainTextEdit()
        self._editor.setReadOnly(True)
        self._editor.setFont(QFont("Monospace", 10))
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._editor)
        self._highlighter = _ConflictHighlighter(self._editor.document())

        # Legend
        legend = QHBoxLayout()
        for color, label in (
            ("#ff8080", t("conflict.legend_ours")),
            ("#e0d060", t("conflict.legend_sep")),
            ("#80cc80", t("conflict.legend_theirs")),
        ):
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color};")
            legend.addWidget(dot)
            legend.addWidget(QLabel(label))
            legend.addSpacing(12)
        legend.addStretch()
        layout.addLayout(legend)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Action buttons
        btn_row = QHBoxLayout()
        self._ours_btn   = QPushButton(t("conflict.accept_ours"))
        self._theirs_btn = QPushButton(t("conflict.accept_theirs"))
        self._editor_btn = QPushButton(t("conflict.open_editor"))
        self._resolve_btn = QPushButton(t("conflict.mark_resolved"))
        self._resolve_btn.setObjectName("primaryButton")

        self._ours_btn.setToolTip(t("conflict.accept_ours_tip"))
        self._theirs_btn.setToolTip(t("conflict.accept_theirs_tip"))
        self._editor_btn.setToolTip(t("conflict.open_editor_tip"))
        self._resolve_btn.setToolTip(t("conflict.mark_resolved_tip"))

        self._ours_btn.clicked.connect(self._on_accept_ours)
        self._theirs_btn.clicked.connect(self._on_accept_theirs)
        self._editor_btn.clicked.connect(self._on_open_editor)
        self._resolve_btn.clicked.connect(self._on_mark_resolved)

        close_btn = QPushButton(t("conflict.close"))
        close_btn.clicked.connect(self.reject)

        btn_row.addWidget(self._ours_btn)
        btn_row.addWidget(self._theirs_btn)
        btn_row.addWidget(self._editor_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._resolve_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _load(self):
        content = self._repo.conflict_content(self._path)
        self._editor.setPlainText(content)
        n = content.count("<<<<<<<")
        self._info_label.setText(
            t("conflict.sections", n=n) if n else t("conflict.no_markers")
        )
        # Disable resolve button until user explicitly acts
        self._resolve_btn.setEnabled(n == 0)

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
        self._editor.setPlainText(content)
        n = content.count("<<<<<<<")
        self._info_label.setText(
            t("conflict.sections", n=n) if n else t("conflict.no_markers")
        )
        self._resolve_btn.setEnabled(True)   # let user decide

    def _on_mark_resolved(self):
        try:
            self._repo.mark_resolved(self._path)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, t("conflict.error"), str(e))
