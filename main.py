import sys
import os

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor, QIcon
from PyQt6.QtCore import Qt

from app.config import get_language
from app.i18n import load_language
from app.ui.main_window import MainWindow


def apply_dark_palette(app: QApplication) -> None:
    """Equestria OS purple Fusion palette."""
    app.setStyle("Fusion")
    palette = QPalette()

    bg       = QColor(26,  24,  41)   # root background
    panel    = QColor(30,  28,  48)   # panels
    input_bg = QColor(40,  36,  62)   # input fields
    text     = QColor(220, 215, 245)  # main text
    dim_text = QColor(100,  90, 130)  # disabled text
    accent   = QColor(120,  90, 180)  # accent / highlight
    sel_text = QColor(255, 255, 255)  # selected text
    link     = QColor(203, 166, 247)  # lavender links

    palette.setColor(QPalette.ColorRole.Window,          bg)
    palette.setColor(QPalette.ColorRole.WindowText,      text)
    palette.setColor(QPalette.ColorRole.Base,            bg)
    palette.setColor(QPalette.ColorRole.AlternateBase,   panel)
    palette.setColor(QPalette.ColorRole.ToolTipBase,     panel)
    palette.setColor(QPalette.ColorRole.ToolTipText,     text)
    palette.setColor(QPalette.ColorRole.Text,            text)
    palette.setColor(QPalette.ColorRole.Button,          panel)
    palette.setColor(QPalette.ColorRole.ButtonText,      text)
    palette.setColor(QPalette.ColorRole.BrightText,      QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Link,            link)
    palette.setColor(QPalette.ColorRole.Highlight,       accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, sel_text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(100, 90, 130))

    g = QPalette.ColorGroup.Disabled
    palette.setColor(g, QPalette.ColorRole.Text,       dim_text)
    palette.setColor(g, QPalette.ColorRole.ButtonText, dim_text)
    palette.setColor(g, QPalette.ColorRole.WindowText, dim_text)

    app.setPalette(palette)


def load_stylesheet(app: QApplication) -> None:
    base = os.path.dirname(os.path.abspath(__file__))
    qss_path = os.path.join(base, "style.qss")
    # Make url() paths in QSS resolve relative to project root
    os.chdir(base)
    try:
        with open(qss_path, "r") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        pass


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("OpenSourceTree")
    app.setApplicationVersion("0.1.0")

    # Определение пути к иконке (предполагается, что файл icon.png рядом)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_dir, 'OpenSourceTreeIcon.png')

    # Установка иконки
    app.setWindowIcon(QIcon(icon_path))

    load_language(get_language())
    apply_dark_palette(app)
    load_stylesheet(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
