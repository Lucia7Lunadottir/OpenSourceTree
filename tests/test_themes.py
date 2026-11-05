"""Run headlessly; never use the user's settings or repositories."""
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['GIT_OPTIONAL_LOCKS'] = '0'
_TEST_HOME = tempfile.TemporaryDirectory(prefix='ost-theme-tests-')
os.environ['HOME'] = _TEST_HOME.name
os.environ['XDG_CONFIG_HOME'] = str(Path(_TEST_HOME.name) / '.config')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import subprocess
from unittest.mock import patch
import pytest
from PyQt6.QtCore import QThreadPool
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem
from app.ui import theme
from app.ui.theme_colors import LEGACY_COLORS, KEPT_AS_IS
pytest.importorskip('equestria_kit')
from equestria_kit import themes

STYLESHEET = (ROOT / 'style.qss').read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def app():
    instance = QApplication.instance() or QApplication([])
    theme.initialize(instance, str(ROOT / 'style.qss'))
    yield instance
    QThreadPool.globalInstance().waitForDone(5000)


@pytest.fixture
def controller(app):
    ctl = theme.controller()
    yield ctl
    ctl.set_choice(theme.BASE)


def test_base_is_the_original_look(controller, app):
    controller.set_choice(theme.BASE)
    assert app.styleSheet() == STYLESHEET
    assert app.palette().window().color() == QColor(26, 24, 41)
    assert app.palette().highlight().color() == QColor(120, 90, 180)
    assert theme.legacy('#9cdcfe') == QColor('#9cdcfe')


def test_every_source_color_has_a_theme_role():
    literal = re.compile(r'rgba?\([\d\s,]+\)|QColor\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)'
                         r'|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|(?<![-\w])white(?![-\w])')
    files = [ROOT / 'style.qss', *(ROOT / 'app').rglob('*.ui'), *(ROOT / 'app').rglob('*.py')]
    missing = set()
    for path in files:
        if path.name.startswith('theme'):
            continue
        for match in literal.finditer(path.read_text(encoding='utf-8')):
            raw = match.group()
            numbers = re.findall(r'\d+', raw) if '(' in raw else None
            name = (QColor(*map(int, numbers[:3])) if numbers else QColor(raw)).name()
            if name not in LEGACY_COLORS and name not in KEPT_AS_IS:
                missing.add(f'{path.relative_to(ROOT)}: {raw}')
    assert not missing


def test_every_theme_and_back_restores_base(controller, app):
    from app.ui.diff_viewer import DiffViewer
    viewer = DiffViewer()
    viewer.show_diff('+literal style="color:#4ec9b0" <tag> & #d4d4d4\n-removed\n@@ hunk')
    text = viewer.toPlainText()
    listing = QListWidget()
    item = QListWidgetItem('file', listing)
    theme.foreground(item, QColor('#d4d4d4'))
    tree = QTreeWidget()
    branch = QTreeWidgetItem(tree, ['branch'])
    theme.foreground(branch, 0, QColor('#4ec9b0'))
    try:
        with patch('subprocess.Popen', side_effect=AssertionError('Theme change ran a process')):
            for name in controller.theme_names():
                controller.set_choice(name)
                look = controller.look
                assert look.name == name
                assert app.palette().window().color().name() == look.roles['base']
                assert item.foreground().color().name() == look.roles['text']
                assert branch.foreground(0).color().name() == look.roles['green']
                assert viewer.toPlainText() == text
                assert 'white-space' in viewer._theme_html
            controller.set_choice(theme.BASE)
        assert app.styleSheet() == STYLESHEET
        assert item.foreground().color() == QColor('#d4d4d4')
        assert branch.foreground(0).color() == QColor('#4ec9b0')
    finally:
        for widget in (viewer, listing, tree):
            widget.close()


def test_selection_text_stays_readable(controller):
    from equestria_kit import qt as kit_qt
    for name in controller.theme_names():
        controller.set_choice(name)
        roles = controller.look.roles
        assert kit_qt.contrast(roles['on_sel'], roles['sel']) >= 4.5, name


def test_menu_lists_themes_and_keeps_shared_choice(controller, app):
    from app.ui.main_window import MainWindow
    shared = themes.current_name()
    window = MainWindow()
    try:
        names = [a.text() for a in window._theme_menu.actions() if a.isCheckable()]
        assert names[2:] == controller.theme_names()
        other = next(n for n in controller.theme_names() if n != shared)
        window._theme_actions[other].trigger()
        assert controller.look.name == other
        assert window._theme_actions[other].isChecked()
        assert themes.current_name() == shared
        window._theme_actions[theme.SYSTEM].trigger()
        assert controller.look.name == shared
    finally:
        window.close()


def test_system_choice_follows_shared_theme(controller):
    controller.set_choice(theme.SYSTEM)
    other = next(n for n in controller.theme_names() if n != controller.system_name)
    controller._on_system_change(other)
    assert controller.look.name == other
    controller.set_choice(theme.BASE)
    controller._on_system_change(controller.theme_names()[0])
    assert controller.look.name == theme.BASE
