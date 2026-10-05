from PyQt6.QtWidgets import QTextBrowser
from PyQt6.QtCore import Qt, pyqtSignal
from html import escape

from app.i18n import t
from app.git.models import CommitInfo


def _person(name: str, email: str) -> str:
    return f"{escape(name)} &lt;{escape(email)}&gt;"


class CommitInfoPanel(QTextBrowser):
    """Full information about the selected commit.

    Pure view: it renders a CommitInfo and knows nothing about git.
    A click on a parent hash emits `parent_clicked` so the owner can jump to it.
    """
    parent_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)
        self.setMinimumWidth(0)
        self.anchorClicked.connect(lambda url: self.parent_clicked.emit(url.toString()))
        self.clear_info()

    def clear_info(self):
        self.setHtml(f"<p style='color:#7a6e9e'>{escape(t('commit_info.empty'))}</p>")

    def show_error(self, message: str):
        self.setHtml(f"<p style='color:#f44747'>{escape(message)}</p>")

    def show_info(self, info: CommitInfo):
        label = lambda key: f"<td style='color:#7a6e9e; padding-right:10px' valign='top'>{escape(t(key))}</td>"
        rows = [
            (label("commit_info.hash"), f"<span style='font-family:monospace'>{info.hash}</span>"),
            (label("commit_info.author"), _person(info.author, info.author_email)),
            (label("commit_info.author_date"), info.author_date.strftime("%Y-%m-%d %H:%M:%S %z")),
        ]
        same = (info.author, info.author_email) == (info.committer, info.committer_email)
        if not same or info.author_date != info.committer_date:
            rows.append((label("commit_info.committer"), _person(info.committer, info.committer_email)))
            rows.append((label("commit_info.committer_date"),
                         info.committer_date.strftime("%Y-%m-%d %H:%M:%S %z")))
        if info.co_authors:
            rows.append((label("commit_info.co_authors"),
                         "<br>".join(_person(n, e) for n, e in info.co_authors)))
        if info.parents:
            links = ", ".join(
                f"<a href='{p}' style='color:#9cdcfe; font-family:monospace'>{p[:10]}</a>"
                for p in info.parents
            )
            rows.append((label("commit_info.parents"), links))
        if info.refs:
            rows.append((label("commit_info.refs"), escape(", ".join(info.refs))))
        stats = t("commit_info.stats_value", files=info.files_changed,
                  ins=info.insertions, dels=info.deletions)
        rows.append((label("commit_info.stats"), escape(stats)))

        table = "".join(f"<tr>{lbl}<td>{val}</td></tr>" for lbl, val in rows)
        body = f"<pre style='white-space:pre-wrap'>{escape(info.body)}</pre>" if info.body else ""
        self.setHtml(
            f"<h3 style='margin:0 0 6px 0'>{escape(info.subject)}</h3>"
            f"{body}<table cellspacing='2'>{table}</table>"
        )
