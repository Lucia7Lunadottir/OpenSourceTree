import re

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QAbstractItemView, QWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from app.i18n import t
from app.git.repo import GitRepo


def _https_to_ssh(url: str) -> str:
    """Convert https://host/user/repo.git  →  git@host:user/repo.git"""
    m = re.match(r"https?://([^/]+)/(.+)", url)
    if m:
        return f"git@{m.group(1)}:{m.group(2)}"
    return url


def _is_https(url: str) -> bool:
    return url.startswith("https://") or url.startswith("http://")


class RemotesDialog(QDialog):
    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self.setWindowTitle(t("remotes.title"))
        self.setMinimumSize(680, 340)
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        hint = QLabel(t("remotes.hint"))
        hint.setStyleSheet("color: rgb(140,120,180); font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Table: Name | URL | Type | Actions
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels([
            t("remotes.col_name"),
            t("remotes.col_url"),
            t("remotes.col_type"),
            t("remotes.col_action"),
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(3, 140)
        self._table.verticalHeader().setDefaultSectionSize(30)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

        # Add remote row
        add_row = QHBoxLayout()
        add_row.addWidget(QLabel(t("remotes.add_name")))
        self._new_name = QLineEdit()
        self._new_name.setPlaceholderText("origin")
        self._new_name.setFixedWidth(90)
        add_row.addWidget(self._new_name)
        add_row.addWidget(QLabel(t("remotes.add_url")))
        self._new_url = QLineEdit()
        self._new_url.setPlaceholderText("https://github.com/user/repo.git  or  git@github.com:user/repo.git")
        add_row.addWidget(self._new_url, 1)
        add_btn = QPushButton(t("remotes.add_btn"))
        add_btn.clicked.connect(self._on_add)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        close_btn = QPushButton(t("conflict.close"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _load(self):
        self._table.setRowCount(0)
        try:
            remotes = self._repo.get_remotes()
        except Exception:
            remotes = []

        for r in remotes:
            self._add_row(r.name, r.fetch_url)

    def _add_row(self, name: str, url: str):
        row = self._table.rowCount()
        self._table.insertRow(row)

        name_item = QTableWidgetItem(name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 0, name_item)

        url_item = QTableWidgetItem(url)
        self._table.setItem(row, 1, url_item)

        https = _is_https(url)
        type_item = QTableWidgetItem("HTTPS ⚠" if https else "SSH ✓")
        type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        type_item.setForeground(QColor("#f5a623") if https else QColor("#4ec9b0"))
        self._table.setItem(row, 2, type_item)

        action_widget = self._make_action_cell(row, name, url)
        self._table.setCellWidget(row, 3, action_widget)

    # Compact inline style that overrides the global "padding: 5px 14px" from style.qss
    _ICON_BTN  = "padding: 2px 5px; min-width: 0;"
    _DEL_STYLE = "padding: 2px 5px; min-width: 0; color: rgb(243,139,168);"
    _SSH_STYLE = "padding: 2px 8px; min-width: 0; color: #f5a623; font-weight: bold;"

    def _make_action_cell(self, row: int, name: str, url: str):
        container = QWidget()
        w = QHBoxLayout(container)
        w.setContentsMargins(4, 2, 4, 2)
        w.setSpacing(4)

        if _is_https(url):
            ssh_btn = QPushButton("→ SSH")
            ssh_btn.setStyleSheet(self._SSH_STYLE)
            ssh_btn.setToolTip(t("remotes.switch_ssh_tip") + f"\n→ {_https_to_ssh(url)}")
            ssh_btn.clicked.connect(lambda _, n=name, u=url: self._on_switch_ssh(n, u))
            w.addWidget(ssh_btn)

        save_btn = QPushButton("✓")
        save_btn.setFixedWidth(30)
        save_btn.setStyleSheet(self._ICON_BTN)
        save_btn.setToolTip(t("remotes.save_url_tip"))
        save_btn.clicked.connect(lambda _, r=row, n=name: self._on_save_url(r, n))
        w.addWidget(save_btn)

        del_btn = QPushButton("✕")
        del_btn.setFixedWidth(30)
        del_btn.setStyleSheet(self._DEL_STYLE)
        del_btn.setToolTip(t("remotes.remove_tip"))
        del_btn.clicked.connect(lambda _, n=name: self._on_remove(n))
        w.addWidget(del_btn)

        return container

    # ----------------------------------------------------------------- Actions

    def _on_switch_ssh(self, name: str, old_url: str):
        new_url = _https_to_ssh(old_url)
        ret = QMessageBox.question(
            self, t("remotes.switch_ssh"),
            t("remotes.switch_ssh_confirm", name=name, old=old_url, new=new_url),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        try:
            self._repo.set_remote_url(name, new_url)
        except Exception as e:
            QMessageBox.critical(self, t("error.git_error"), str(e))
            return
        self._load()

    def _on_save_url(self, row: int, name: str):
        item = self._table.item(row, 1)
        if not item:
            return
        new_url = item.text().strip()
        if not new_url:
            QMessageBox.warning(self, t("remotes.title"), t("remotes.empty_url"))
            return
        try:
            self._repo.set_remote_url(name, new_url)
        except Exception as e:
            QMessageBox.critical(self, t("error.git_error"), str(e))
            return
        self._load()

    def _on_remove(self, name: str):
        ret = QMessageBox.question(
            self, t("remotes.title"),
            t("remotes.remove_confirm", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            try:
                self._repo.remove_remote(name)
            except Exception as e:
                QMessageBox.critical(self, t("error.git_error"), str(e))
            self._load()

    def _on_add(self):
        name = self._new_name.text().strip()
        url  = self._new_url.text().strip()
        if not name or not url:
            QMessageBox.warning(self, t("remotes.title"), t("remotes.add_empty"))
            return
        try:
            self._repo.add_remote(name, url)
        except Exception as e:
            QMessageBox.critical(self, t("error.git_error"), str(e))
            return
        self._new_name.clear()
        self._new_url.clear()
        self._load()
