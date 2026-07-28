"""CLI entry point."""

import argparse
import locale
import sys
from importlib.resources import files

from avialview.runtime import configure_media_runtime


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the supported AvialView command-line arguments."""
    parser = argparse.ArgumentParser(prog="avialview")
    parser.add_argument("command", nargs="?", choices=("demo",))
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args(sys.argv[1:])
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from avialview.demo import ensure_demo_data, load_demo
    from avialview.ui.main_window import MainWindow
    from avialview.ui.theme import load_saved_font_size, load_saved_theme

    configure_media_runtime()
    demo_paths = ensure_demo_data() if args.command == "demo" else None
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
    if demo_paths is not None:
        QTimer.singleShot(0, lambda: load_demo(win, *demo_paths))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
