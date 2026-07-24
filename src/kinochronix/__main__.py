"""CLI entry point."""
import sys


def main() -> None:
    from PySide6.QtWidgets import QApplication

    from kinochronix.ui.main_window import MainWindow
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
