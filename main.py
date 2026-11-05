import sys
import os

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt

from app.config import get_language, _ensure_config_dir
from app.i18n import load_language
from app.ui.main_window import MainWindow

os.environ["GIT_OPTIONAL_LOCKS"] = "0"

# Recreate ~/.config/OpenSourceTree (and ~/.ssh) up front on every launch.
# Previously this only happened lazily inside save_*() calls, so if the
# config dir had been deleted there was a window right after startup where
# reads/writes touching it (SSH command / askpass regeneration on the very
# first git call) could hit a half-missing directory tree.
try:
    _ensure_config_dir()
except Exception:
    # Never let a broken ~/.config stop the app from launching at all —
    # worst case, settings/bookmarks/SSH just won't persist this session.
    pass
def load_stylesheet(app: QApplication) -> None:
    from app.ui.theme import initialize
    base = os.path.dirname(os.path.abspath(__file__))
    # Preserve relative asset paths from the original application stylesheet.
    os.chdir(base)
    initialize(app, os.path.join(base, "style.qss"))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("OpenSourceTree")
    app.setApplicationVersion("0.1.0")
    app.setDesktopFileName("opensourcetree")

    # Определение пути к иконке (предполагается, что файл icon.png рядом)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_dir, 'OpenSourceTreeIcon.png')

    # Установка иконки
    app.setWindowIcon(QIcon.fromTheme("opensourcetree", QIcon(icon_path)))

    load_language(get_language())
    load_stylesheet(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
