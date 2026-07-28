"""CLI entry point."""

import locale
import sys
from importlib.resources import files

from avialview.runtime import configure_media_runtime


def main() -> None:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from avialview.ui.main_window import MainWindow
    from avialview.ui.theme import load_saved_font_size, load_saved_theme

    configure_media_runtime()
    app = QApplication(sys.argv)
    app_icon = QIcon(str(files("avialview.resources").joinpath("avialview.png")))
    app.setWindowIcon(app_icon)

    # Prevent Qt from stomping LC_NUMERIC (breaks libmpv float parsing)
    locale.setlocale(locale.LC_NUMERIC, "C")

    load_saved_theme(app)
    load_saved_font_size(app)

    win = MainWindow()
    win.setWindowIcon(app_icon)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
