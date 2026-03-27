from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QLineEdit,
    QPushButton, QAbstractItemView, QHeaderView, QLabel,
    QMenu, QApplication, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex, QTimer, QPoint
from PyQt6.QtGui import QAction

from app.i18n import t
from app.git.repo import GitRepo
from app.git.models import CommitRecord
from app.workers.git_worker import GitWorker
from PyQt6.QtCore import QThreadPool

from .commit_table_model import CommitTableModel, COL_GRAPH, COL_HASH, COL_MESSAGE, COL_AUTHOR, COL_DATE
from .commit_graph_delegate import CommitGraphDelegate, LANE_W, ROW_H


class CommitListView(QWidget):
    commit_selected      = pyqtSignal(object)   # CommitRecord or None
    working_copy_selected = pyqtSignal()
    refresh_requested    = pyqtSignal()          # emitted after context-menu ops
    status_message       = pyqtSignal(str)

    def __init__(self, repo: GitRepo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Filter bar
        filter_bar = QWidget()
        filter_bar.setObjectName("filterBar")
        fb_layout = QHBoxLayout(filter_bar)
        fb_layout.setContentsMargins(4, 4, 4, 4)
        fb_layout.setSpacing(4)
        fb_layout.addWidget(QLabel("🔍"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText(t("commit_list.filter_placeholder"))
        self._filter_edit.setClearButtonEnabled(True)
        self._clear_btn = QPushButton(t("commit_list.clear"))
        self._clear_btn.setObjectName("smallBtn")
        self._clear_btn.setFixedWidth(70)
        fb_layout.addWidget(self._filter_edit)
        fb_layout.addWidget(self._clear_btn)
        layout.addWidget(filter_bar)

        # Commit table
        self._model = CommitTableModel(self._repo)
        self._view = QTableView()
        self._view.setModel(self._model)
        self._view.setItemDelegateForColumn(COL_GRAPH, CommitGraphDelegate(self._view))
        self._view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setShowGrid(False)
        self._view.setWordWrap(False)
        self._view.setAlternatingRowColors(False)
        self._view.verticalHeader().setVisible(False)
        self._view.verticalHeader().setDefaultSectionSize(ROW_H)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        header = self._view.horizontalHeader()
        header.setSectionResizeMode(COL_GRAPH,   QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_HASH,    QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_MESSAGE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_AUTHOR,  QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_DATE,    QHeaderView.ResizeMode.Interactive)
        self._view.setColumnWidth(COL_GRAPH,  LANE_W * 8)
        self._view.setColumnWidth(COL_HASH,   70)
        self._view.setColumnWidth(COL_AUTHOR, 140)
        self._view.setColumnWidth(COL_DATE,   130)
        layout.addWidget(self._view)

        self._load_more_btn = QPushButton(t("commit_list.load_more"))
        self._load_more_btn.setVisible(False)
        layout.addWidget(self._load_more_btn)

        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(300)

    def _connect_signals(self):
        self._view.selectionModel().currentRowChanged.connect(self._on_row_changed)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        self._model.loading_done.connect(self._on_loading_done)
        self._filter_edit.textChanged.connect(lambda _: self._filter_timer.start())
        self._clear_btn.clicked.connect(self._filter_edit.clear)
        self._load_more_btn.clicked.connect(self._on_load_more)
        self._filter_timer.timeout.connect(lambda: self._model.set_filter(self._filter_edit.text()))

    # ── Public ────────────────────────────────────────────────────────────────

    def load_commits(self, branch: str = ""):
        self._model.load_initial(branch=branch)

    def refresh(self):
        self._model.load_initial(branch="", search=self._filter_edit.text())

    # ── Row selection ─────────────────────────────────────────────────────────

    def _on_row_changed(self, current: QModelIndex, _previous):
        if not current.isValid():
            self.commit_selected.emit(None)
            return
        commit = self._model.get_commit(current.row())
        if commit is None:
            self.working_copy_selected.emit()
        else:
            self.commit_selected.emit(commit)

    def _on_loading_done(self):
        self._load_more_btn.setVisible(self._model.canFetchMore())

    def _on_load_more(self):
        if self._model.canFetchMore():
            self._model.fetchMore()

    # ── Context menu ──────────────────────────────────────────────────────────

    def _on_context_menu(self, pos: QPoint):
        idx = self._view.indexAt(pos)
        if not idx.isValid():
            return
        commit = self._model.get_commit(idx.row())
        if commit is None:
            return

        menu = QMenu(self)
        h   = commit.hash
        sh  = commit.short_hash
        msg = commit.message[:50] + ("…" if len(commit.message) > 50 else "")

        # ── Reset ──
        reset_menu = menu.addMenu(f"Сбросить ветку на «{sh}»")
        soft_act   = reset_menu.addAction("Soft  — сохранить изменения в индексе")
        mixed_act  = reset_menu.addAction("Mixed — сохранить изменения в рабочей копии")
        hard_act   = reset_menu.addAction("Hard  — удалить все изменения ⚠")

        menu.addSeparator()

        # ── Other actions ──
        checkout_act    = menu.addAction(f"Checkout «{sh}» (detached HEAD)")
        branch_act      = menu.addAction("Создать ветку отсюда...")
        menu.addSeparator()
        cherrypick_act  = menu.addAction("Cherry-pick")
        revert_act      = menu.addAction("Revert (создать отменяющий коммит)")
        menu.addSeparator()
        copy_hash_act   = menu.addAction(f"Копировать хэш  ({sh})")
        copy_full_act   = menu.addAction(f"Копировать полный хэш")
        copy_msg_act    = menu.addAction("Копировать сообщение коммита")


        action = menu.exec(self._view.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action == soft_act:
            self._reset(h, "soft")
        elif action == mixed_act:
            self._reset(h, "mixed")
        elif action == hard_act:
            self._reset_hard(h)
        elif action == checkout_act:
            self._run_op(self._repo.checkout_detached, h,
                         f"Переключён на коммит {sh} (detached HEAD)")
        elif action == branch_act:
            self._create_branch_here(h)
        elif action == cherrypick_act:
            self._run_op(self._repo.cherry_pick, h, f"Cherry-pick {sh} выполнен")
        elif action == revert_act:
            self._run_op(self._repo.revert_commit, h, f"Revert {sh} выполнен")
        elif action == copy_hash_act:
            QApplication.clipboard().setText(sh)
        elif action == copy_full_act:
            QApplication.clipboard().setText(h)
        elif action == copy_msg_act:
            QApplication.clipboard().setText(commit.message)

    def _reset(self, hash: str, mode: str):
        label = {"soft": "Soft", "mixed": "Mixed", "hard": "Hard"}[mode]
        ret = QMessageBox.question(
            self, f"Reset {label}",
            f"Сбросить ветку на коммит {hash[:8]}?\n\n"
            f"Режим: {label} — {self._reset_description(mode)}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self._run_op(self._repo.reset_to_commit, hash, mode,
                         success=f"Reset {label} до {hash[:8]} выполнен")

    def _reset_hard(self, hash: str):
        ret = QMessageBox.warning(
            self, "Hard Reset — ВСЕ ИЗМЕНЕНИЯ БУДУТ УДАЛЕНЫ",
            f"Сбросить ветку на {hash[:8]} с режимом HARD?\n\n"
            "Все незакоммиченные изменения будут безвозвратно удалены!\n\n"
            "Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self._run_op(self._repo.reset_to_commit, hash, "hard",
                         success=f"Hard reset до {hash[:8]} выполнен")

    @staticmethod
    def _reset_description(mode: str) -> str:
        return {
            "soft":  "изменения останутся в индексе (staged)",
            "mixed": "изменения останутся в рабочей копии (unstaged)",
            "hard":  "все изменения будут удалены",
        }.get(mode, "")

    def _create_branch_here(self, hash: str):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Создать ветку", f"Имя новой ветки от {hash[:8]}:"
        )
        if ok and name.strip():
            self._run_op(self._repo.create_branch, name.strip(), hash,
                         success=f"Ветка '{name}' создана")

    def _run_op(self, fn, *args, success="Готово"):
        worker = GitWorker(fn, *args)
        worker.signals.result.connect(lambda _: self._on_op_done(success))
        worker.signals.error.connect(self._on_op_error)
        QThreadPool.globalInstance().start(worker)

    def _on_op_done(self, msg: str):
        self.status_message.emit(msg)
        self.refresh_requested.emit()
        self.refresh()

    def _on_op_error(self, error: str):
        lines = [l for l in error.splitlines() if l.strip()]
        self.status_message.emit("Ошибка: " + (lines[-1] if lines else ""))
        QMessageBox.critical(self, "Git Error", error)
