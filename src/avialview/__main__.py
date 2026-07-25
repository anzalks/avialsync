"""CLI entry point."""

import locale
import sys


def main() -> None:
    from PySide6.QtWidgets import QApplication

    from avialview.ui.main_window import MainWindow
    from avialview.ui.theme import load_saved_font_size, load_saved_theme

    app = QApplication(sys.argv)

    # Prevent Qt from stomping LC_NUMERIC (breaks libmpv float parsing)
    locale.setlocale(locale.LC_NUMERIC, "C")

    load_saved_theme(app)
    load_saved_font_size(app)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
