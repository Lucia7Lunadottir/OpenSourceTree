"""Theme switching: the original purple look or any Equestria OS theme.

Sources keep their original colours. The base look applies them untouched,
so it is exactly the pre-theme OpenSourceTree. An Equestria look translates
each original colour through theme_colors.LEGACY_COLORS.

The choice is stored in OpenSourceTree's own config and never changes the
shared Equestria theme: "base", "system" (follow the shared theme) or the
name of one Equestria theme.

Theme changes only repaint existing views; they never reload repositories.
"""
import re
from pathlib import Path

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication, QWidget, QTextBrowser, QTreeWidget, QTreeWidgetItemIterator,
    QListWidget, QListWidgetItem, QTreeWidgetItem, QTableWidget,
)
try:
    from equestria_kit import themes
    from equestria_kit import qt as kit_qt
except ModuleNotFoundError as error:
    if error.name != 'equestria_kit':
        raise
    themes = kit_qt = None
KIT_AVAILABLE = themes is not None

from app.config import get_theme_mode, set_theme_mode
from app.ui.theme_colors import LEGACY_COLORS

BASE, SYSTEM = 'base', 'system'

# The original Fusion palette, role → colour.
_BASE_PALETTE = (
    ('Window', (26, 24, 41)), ('WindowText', (220, 215, 245)), ('Base', (26, 24, 41)),
    ('AlternateBase', (30, 28, 48)), ('ToolTipBase', (30, 28, 48)), ('ToolTipText', (220, 215, 245)),
    ('Text', (220, 215, 245)), ('Button', (30, 28, 48)), ('ButtonText', (220, 215, 245)),
    ('BrightText', (255, 255, 255)), ('Link', (203, 166, 247)), ('Highlight', (120, 90, 180)),
    ('HighlightedText', (255, 255, 255)), ('PlaceholderText', (100, 90, 130)),
)
_BASE_DISABLED = (('Text', (100, 90, 130)), ('ButtonText', (100, 90, 130)), ('WindowText', (100, 90, 130)))

# Colour literals in CSS. "white" must not match inside "white-space".
_CSS_COLOR = re.compile(r'rgba?\([\d\s,]+\)|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|(?<![-\w])white(?![-\w])')
_HTML_PART = re.compile(r'(?P<start><style\b[^>]*>)(?P<sheet>.*?)(?P<end></style>)|(?P<tag><[^>]+>)', re.I | re.S)
_STYLE_ATTR = re.compile(r"(\bstyle\s*=\s*)([\"'])(.*?)(\2)", re.I | re.S)


def _mix(first: str, second: str, amount: float) -> str:
    a, b = QColor(first), QColor(second)
    return QColor(*(round(x + (y - x) * amount) for x, y in
                    zip(a.getRgb()[:3], b.getRgb()[:3]))).name()


class Look:
    """Maps an original OpenSourceTree colour to the colour shown on screen."""
    name = ''

    def color(self, value) -> QColor:
        raise NotImplementedError

    def lane(self, value: QColor) -> QColor:
        return QColor(value)

    def css(self, text: str) -> str:
        return text

    def palette(self) -> QPalette:
        palette = QPalette()
        for role, rgb in _BASE_PALETTE:
            palette.setColor(getattr(QPalette.ColorRole, role), self.color(QColor(*rgb)))
        for role, rgb in _BASE_DISABLED:
            palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role),
                             self.color(QColor(*rgb)))
        return palette


class BaseLook(Look):
    """The original purple: every colour stays exactly as written."""
    name = BASE

    def color(self, value) -> QColor:
        return QColor(value)


class EquestriaLook(Look):
    """An Equestria OS theme applied through the legacy colour table."""

    def __init__(self, name: str, colors: dict):
        self.name = name
        roles = dict(colors)
        roles.setdefault('accent2', roles['accent'])
        roles['accent_text'] = kit_qt.readable(roles.get('accent_text', roles['accent']), roles['base'])
        roles['sel'], roles['on_sel'] = self._selection(roles)
        self.roles = roles

    @staticmethod
    def _selection(roles: dict) -> tuple:
        # As much accent as the text on top still reads well (bright accents
        # like Sunset's gold would otherwise turn every selection into a glare).
        for step in range(55, 15, -5):
            fill = _mix(roles['surface0'], roles['accent'], step / 100)
            if kit_qt.contrast(roles['text'], fill) >= 4.5:
                return fill, roles['text']
        return fill, max(('#ffffff', roles['crust']), key=lambda c: kit_qt.contrast(c, fill))

    def _resolve(self, spec) -> str:
        if isinstance(spec, tuple):
            first, second, amount = spec
            return _mix(self.roles[first], self.roles[second], amount)
        return self.roles[spec]

    def color(self, value) -> QColor:
        original = QColor(value)
        spec = LEGACY_COLORS.get(original.name())
        if spec is None:
            return original
        result = QColor(self._resolve(spec))
        result.setAlpha(original.alpha())
        return result

    def lane(self, value: QColor) -> QColor:
        return QColor(kit_qt.readable(value.name(), self.roles['base']))

    def css(self, text: str) -> str:
        def replace(match):
            raw = match.group()
            if raw.lower().startswith('rgb'):
                parts = [int(p) for p in raw[raw.index('(') + 1:-1].split(',')]
                mapped = self.color(QColor(*parts[:3]))
                if len(parts) == 4:
                    return f'rgba({mapped.red()}, {mapped.green()}, {mapped.blue()}, {parts[3]})'
                return mapped.name()
            mapped = self.color(QColor(raw))
            return raw if mapped == QColor(raw) else mapped.name()
        return _CSS_COLOR.sub(replace, text)


class ThemeController(QObject):
    """Owns the current look and repaints the running application."""
    changed = pyqtSignal(str)

    def __init__(self, app: QApplication, stylesheet: str):
        super().__init__(app)
        self.app, self.stylesheet = app, stylesheet
        self.choice = get_theme_mode() if KIT_AVAILABLE else BASE
        self.system_name = themes.current_name() if KIT_AVAILABLE else ''
        self.look = self._look_for(self.choice)
        if KIT_AVAILABLE:
            themes.follow(self._on_system_change, lambda: self.system_name)

    def theme_names(self) -> list:
        return list(themes.THEMES) if KIT_AVAILABLE else []

    def set_choice(self, choice: str) -> None:
        if not KIT_AVAILABLE:
            choice = BASE
        set_theme_mode(choice)
        self.choice = choice
        self._set_look(self._look_for(choice))

    def _look_for(self, choice: str) -> Look:
        if not KIT_AVAILABLE or choice == BASE:
            return BaseLook()
        name = themes.registry().resolve(self.system_name if choice == SYSTEM else choice)
        return EquestriaLook(name, themes.THEMES[name])

    def _on_system_change(self, name: str) -> None:
        self.system_name = name
        if self.choice == SYSTEM:
            self._set_look(self._look_for(SYSTEM))
        else:
            self.changed.emit(self.choice)   # the menu shows the system theme's name

    def _set_look(self, look: Look) -> None:
        self.look = look
        self.apply()

    def apply(self) -> None:
        self.app.setPalette(self.look.palette())
        self.app.setStyleSheet(self.look.css(self.stylesheet))
        for widget in self.app.allWidgets():
            css = widget.property(_STYLE_PROP)
            if css is not None:
                widget.setStyleSheet(self.look.css(css))
            _recolor_items(widget)
            if isinstance(widget, ThemedTextBrowser):
                widget.refresh_theme()
            widget.update()
        self.changed.emit(self.choice)


_controller = None
_BASE_LOOK = BaseLook()
_ITEM_COLOR_ROLE = int(Qt.ItemDataRole.UserRole) + 4096
_STYLE_PROP = '_opensourcetree_style'


def initialize(app: QApplication, stylesheet: str) -> ThemeController:
    global _controller
    if _controller is None:
        app.setStyle('Fusion')
        _controller = ThemeController(app, Path(stylesheet).read_text(encoding='utf-8'))
        _controller.apply()
    return _controller


def controller():
    return _controller


def _look() -> Look:
    return _controller.look if _controller is not None else _BASE_LOOK


def legacy(value) -> QColor:
    """An original colour as shown in the current theme."""
    return _look().color(value)


def lane_color(value: QColor) -> QColor:
    return _look().lane(value)


def style(widget: QWidget, css: str) -> None:
    """setStyleSheet() with original colours; restyled on theme changes."""
    widget.setProperty(_STYLE_PROP, css)
    widget.setStyleSheet(_look().css(css))


def form_styles(root: QWidget) -> None:
    """Register the inline styles of a Designer form."""
    for widget in (root, *root.findChildren(QWidget)):
        # Nested custom widgets may already be registered.
        if widget.property(_STYLE_PROP) is None and widget.styleSheet():
            style(widget, widget.styleSheet())


def foreground(item, *args) -> None:
    """setForeground() with an original colour; recoloured on theme changes."""
    col, value = (args[0], args[1]) if len(args) == 2 else (0, args[0])
    original = QColor(value.color() if hasattr(value, 'color') else value)
    shown = legacy(original)
    # QListWidgetItem and the SSH profile item use data(role), tree items data(column, role)
    if isinstance(item, QTreeWidgetItem):
        item.setForeground(col, shown)
        item.setData(col, _ITEM_COLOR_ROLE, original.name())
    else:
        item.setForeground(shown)
        item.setData(_ITEM_COLOR_ROLE, original.name())


def _recolor_items(widget) -> None:
    if isinstance(widget, QTreeWidget):
        iterator = QTreeWidgetItemIterator(widget)
        while iterator.value():
            item = iterator.value()
            for col in range(widget.columnCount()):
                original = item.data(col, _ITEM_COLOR_ROLE)
                if original:
                    item.setForeground(col, legacy(original))
            iterator += 1
    elif isinstance(widget, QListWidget):
        for row in range(widget.count()):
            item = widget.item(row)
            original = item.data(_ITEM_COLOR_ROLE)
            if original:
                item.setForeground(legacy(original))
    elif isinstance(widget, QTableWidget):
        for row in range(widget.rowCount()):
            for col in range(widget.columnCount()):
                item = widget.item(row, col)
                original = item.data(_ITEM_COLOR_ROLE) if item else None
                if original:
                    item.setForeground(legacy(original))


class ThemedTextBrowser(QTextBrowser):
    """Keeps the original HTML; recolours only CSS, never diff/commit content."""
    def setHtml(self, html: str) -> None:
        self._theme_html = html
        look = _look()
        def replace(match):
            if match.group('tag'):
                def attribute(attr):
                    return attr.group(1) + attr.group(2) + look.css(attr.group(3)) + attr.group(4)
                return _STYLE_ATTR.sub(attribute, match.group('tag'))
            return match.group('start') + look.css(match.group('sheet')) + match.group('end')
        super().setHtml(_HTML_PART.sub(replace, html))

    def setPlainText(self, text: str) -> None:
        self._theme_html = None
        super().setPlainText(text)

    def refresh_theme(self) -> None:
        html = getattr(self, '_theme_html', None)
        if html is not None:
            cursor = self.textCursor()
            vertical, horizontal = self.verticalScrollBar().value(), self.horizontalScrollBar().value()
            self.setHtml(html)
            self.setTextCursor(cursor)
            self.verticalScrollBar().setValue(vertical)
            self.horizontalScrollBar().setValue(horizontal)
