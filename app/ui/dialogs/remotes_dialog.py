import re
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from app.i18n import t
from app.git.repo import GitRepo
from app.ui.ui_translator import UiTranslator

_UI_FILE = Path(__file__).with_name("remotes_dialog.ui")


def _https_to_ssh(url: str) -> str:
    """Convert https://host/user/repo.git  →  git@host:user/repo.git"""
    m = re.match(r"https?://([^/]+)/(.+)", url)
    if m:
        return f"git@{m.group(1)}:{m.group(2)}"
    return url


def _is_https(url: str) -> bool:
    return url.startswith("https://") or url.startswith("http://")


class RemotesDialog(QDialog):
    # widgets created by loadUi from remotes_dialog.ui
    table: QTableWidget
    newNameEdit: QLineEdit
    newUrlEdit: QLineEdit
    addButton: QPushButton
    closeButton: QPushButton

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        uic.loadUi(_UI_FILE, self)
        UiTranslator().apply(self)
        self._setup_table()
        self.addButton.clicked.connect(self._on_add)
        self.closeButton.clicked.connect(self.accept)
        self._load()

    def _setup_table(self):
        # Column header texts are i18n keys in the .ui; per-section resize
        # modes can't be expressed in Designer.
        for col in range(self.table.columnCount()):
            header_item = self.table.horizontalHeaderItem(col)
            header_item.setText(t(header_item.text()))
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 140)

    def _load(self):
        self.table.setRowCount(0)
        try:
            remotes = self._repo.get_remotes()
        except Exception:
            remotes = []

        for r in remotes:
            self._add_row(r.name, r.fetch_url)

    def _add_row(self, name: str, url: str):
        row = self.table.rowCount()
        self.table.insertRow(row)

        name_item = QTableWidgetItem(name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, name_item)

        url_item = QTableWidgetItem(url)
        self.table.setItem(row, 1, url_item)

        https = _is_https(url)
        type_item = QTableWidgetItem("HTTPS ⚠" if https else "SSH ✓")
        type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        type_item.setForeground(QColor("#f5a623") if https else QColor("#4ec9b0"))
        self.table.setItem(row, 2, type_item)

        action_widget = self._make_action_cell(row, name, url)
        self.table.setCellWidget(row, 3, action_widget)

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
        item = self.table.item(row, 1)
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
        name = self.newNameEdit.text().strip()
        url  = self.newUrlEdit.text().strip()
        if not name or not url:
            QMessageBox.warning(self, t("remotes.title"), t("remotes.add_empty"))
            return
        try:
            self._repo.add_remote(name, url)
        except Exception as e:
            QMessageBox.critical(self, t("error.git_error"), str(e))
            return
        self.newNameEdit.clear()
        self.newUrlEdit.clear()
        self._load()
