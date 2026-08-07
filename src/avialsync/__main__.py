"""CLI entry point."""

import argparse
import locale
import os
import sys
import time
from importlib.resources import files
from pathlib import Path

from avialsync.runtime import configure_media_runtime


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the supported AvialSync command-line arguments."""
    parser = argparse.ArgumentParser(prog="avialsync")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("demo", "open"),
        help="demo: generate and load the inspection demo. open: load PATH.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Session file (.avv) or a folder of recordings, for 'open'.",
    )
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.command == "open":
        if args.path is None:
            parser.error("open needs a path: avialsync open <session.avv|folder>")
        if not args.path.exists():
            # Refuse before Qt starts: a missing path is a typo, and reporting
            # it in a dialog behind a window that has already opened is worse
            # than reporting it on the terminal that issued the command.
            parser.error(f"no such file or folder: {args.path}")
    elif args.path is not None:
        parser.error(f"'{args.command}' takes no path argument")
    return args


def main() -> None:
    args = _parse_args(sys.argv[1:])
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from avialsync.demo import DEMO_CHANNEL_COUNT, DEMO_VIDEO_COUNT, DemoLaunch
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.theme import load_saved_font_size, load_saved_theme

    configure_media_runtime()
    app = QApplication(sys.argv)
    app_icon = QIcon(str(files("avialsync.resources").joinpath("avialsync.png")))
    app.setWindowIcon(app_icon)

    # Qt sets LC_NUMERIC from the user's locale, so "1.5" parses as 1 in a
    # decimal-comma locale. This existed for libmpv, whose option parser was
    # locale-sensitive; PyAV's is not, so the decoder no longer needs it. It is
    # kept because the change is process-wide and cheap to hold, not because
    # anything still depends on it — see MIGRATION_PYAV.md step 8.
    locale.setlocale(locale.LC_NUMERIC, "C")

    load_saved_theme(app)
    load_saved_font_size(app)

    win = MainWindow()
    win.setWindowIcon(app_icon)
    win.show()
    demo_launch = DemoLaunch(win) if args.command == "demo" else None
    if demo_launch is not None:
        QTimer.singleShot(0, demo_launch.start)
    elif args.command == "open":
        # Deferred so the window is mapped before scanning reports progress.
        QTimer.singleShot(0, lambda: win.open_path(args.path))

    if args.smoke_test and demo_launch is None:
        QTimer.singleShot(250, win.close)
    elif args.smoke_test:
        smoke_started = time.monotonic()
        # The harness sets this below its own timeout so this deadline fires
        # first and reports what the demo was still waiting for. A slow runner
        # needs a longer budget than a workstation, so it is not a constant.
        smoke_deadline = float(os.environ.get("AVIALSYNC_SMOKE_DEADLINE_S", "110"))

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
