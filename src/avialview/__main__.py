"""CLI entry point."""

import argparse
import locale
import os
import sys
import time
from importlib.resources import files

from avialview.runtime import configure_media_runtime


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the supported AvialView command-line arguments."""
    parser = argparse.ArgumentParser(prog="avialview")
    parser.add_argument("command", nargs="?", choices=("demo",))
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args(sys.argv[1:])
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from avialview.demo import DEMO_CHANNEL_COUNT, DEMO_VIDEO_COUNT, DemoLaunch
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
    demo_launch = DemoLaunch(win) if args.command == "demo" else None
    if demo_launch is not None:
        QTimer.singleShot(0, demo_launch.start)

    if args.smoke_test and demo_launch is None:
        QTimer.singleShot(250, win.close)
    elif args.smoke_test:
        smoke_started = time.monotonic()
        # The harness sets this below its own timeout so this deadline fires
        # first and reports what the demo was still waiting for. A slow runner
        # needs a longer budget than a workstation, so it is not a constant.
        smoke_deadline = float(os.environ.get("AVIALVIEW_SMOKE_DEADLINE_S", "110"))

        def poll_demo_ready() -> None:
            panes = win.video_grid.panes
            videos_ready = (
                len(panes) == DEMO_VIDEO_COUNT
                and all(pane._media_loaded for pane in panes)
                and not win._pending_video_loads
                and not win._video_load_jobs
                and win._video_pane_initializing is None
            )
            data_ready = (
                len(win.plot_pane.channels) == DEMO_CHANNEL_COUNT
                and not win._pending_imports
                and win._import_thread is None
            )
            if videos_ready and data_ready:
                win.close()
                return
            if time.monotonic() - smoke_started >= smoke_deadline:
                print(
                    "Demo smoke timed out: "
                    f"videos={len(panes)}/{DEMO_VIDEO_COUNT}, "
                    f"channels={len(win.plot_pane.channels)}/{DEMO_CHANNEL_COUNT}",
                    file=sys.stderr,
                )
                app.exit(2)
                return
            QTimer.singleShot(50, poll_demo_ready)

        QTimer.singleShot(50, poll_demo_ready)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
