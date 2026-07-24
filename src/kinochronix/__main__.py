"""CLI entry point."""

import locale
import sys


def main() -> None:
    from PySide6.QtWidgets import QApplication

    from kinochronix.ui.main_window import MainWindow
    from kinochronix.ui.theme import load_saved_theme

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Prevent Qt from stomping LC_NUMERIC (breaks libmpv float parsing)
    locale.setlocale(locale.LC_NUMERIC, "C")

    load_saved_theme(app)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
