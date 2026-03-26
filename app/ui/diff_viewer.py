from PyQt6.QtWidgets import QTextBrowser
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

try:
    from pygments import highlight
    from pygments.lexers import get_lexer_for_filename, TextLexer
    from pygments.lexers.diff import DiffLexer
    from pygments.formatters import HtmlFormatter
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False

MONOKAI_CSS = """
body { background: #1e1e1e; color: #d4d4d4; font-family: monospace; font-size: 13px; margin: 0; padding: 8px; }
.hll { background-color: #264f78; }
.c { color: #6a9955; }
.k { color: #569cd6; font-weight: bold; }
.n { color: #d4d4d4; }
.o { color: #d4d4d4; }
.s { color: #ce9178; }
.nc { color: #4ec9b0; }
.nf { color: #dcdcaa; }
.gi { color: #4ec9b0; background: #1a3a2a; display: block; }
.gd { color: #f44747; background: #3a1a1a; display: block; }
.gu { color: #569cd6; font-weight: bold; display: block; }
.gh { color: #9cdcfe; font-weight: bold; }
pre { margin: 0; white-space: pre-wrap; word-wrap: break-word; }
"""


class DiffViewer(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setReadOnly(True)
        font = QFont("Monospace", 11)
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.setFont(font)
        self._show_placeholder()

    def _show_placeholder(self):
        self.setHtml(
            '<html><body style="background:#1e1e1e;color:#666;font-family:monospace;'
            'padding:16px;">Select a file to view diff</body></html>'
        )

    def show_diff(self, diff_text: str, filename: str = ""):
        if not diff_text.strip():
            self._show_placeholder()
            return

        if PYGMENTS_AVAILABLE:
            try:
                lexer = DiffLexer()
                formatter = HtmlFormatter(
                    style="monokai",
                    noclasses=True,
                    prestyles="font-family: monospace; font-size: 13px;",
                    nobackground=False,
                )
                highlighted = highlight(diff_text, lexer, formatter)
                # Wrap in dark background
                html = f"""
                <html>
                <head><style>
                {MONOKAI_CSS}
                {formatter.get_style_defs()}
                </style></head>
                <body>{highlighted}</body>
                </html>
                """
                self.setHtml(html)
            except Exception:
                self._show_plain(diff_text)
        else:
            self._show_plain(diff_text)

    def _show_plain(self, diff_text: str):
        lines = []
        for line in diff_text.splitlines():
            escaped = (
                line.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            if line.startswith("+") and not line.startswith("+++"):
                color = "#4ec9b0"
                bg = "#1a3a2a"
            elif line.startswith("-") and not line.startswith("---"):
                color = "#f44747"
                bg = "#3a1a1a"
            elif line.startswith("@@"):
                color = "#569cd6"
                bg = "#1e1e1e"
            else:
                color = "#d4d4d4"
                bg = "#1e1e1e"
            lines.append(
                f'<div style="background:{bg};color:{color};white-space:pre;">{escaped}</div>'
            )
        html = (
            '<html><body style="background:#1e1e1e;font-family:monospace;'
            'font-size:13px;margin:0;padding:4px;">'
            + "".join(lines)
            + "</body></html>"
        )
        self.setHtml(html)

    def show_binary(self, filename: str = ""):
        name = filename or "file"
        self.setHtml(
            f'<html><body style="background:#1e1e1e;color:#9cdcfe;font-family:monospace;'
            f'padding:16px;"><i>Binary file: {name}</i></body></html>'
        )

    def clear_diff(self):
        self._show_placeholder()
