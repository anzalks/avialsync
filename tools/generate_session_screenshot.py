"""Capture a screenshot of a real session folder opened through its plugin.

Run with, for example::

    conda run -n avialsync python tools/generate_session_screenshot.py /path/to/09-35-24

Unlike ``tools/generate_demo_screenshots.py``, which uses the checked-in sample
session and therefore reproduces from a clean clone, this one photographs
whatever recording folder you point it at. The path is an argument and never
hardcoded: field data lives outside the repository and differs per lab.

It drives the real intake — session plugin discovery, the layout it returns, and
the ordinary per-source load path — so what is captured is what a user gets by
dropping the folder on the window, not a staged arrangement.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "docs" / "_static" / "screenshots" / "session_overview.png"


def capture(session_dir: Path, out_path: Path, width: int, height: int, seek_fraction: float):
    from avialsync.engine.drop_worker import DropScanWorker
    from avialsync.ui.controllers import drop_controller
    from avialsync.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    window = MainWindow()
    window.resize(width, height)
    window.show()

    def settle(rounds: int = 60) -> None:
        """Drain the event loop without blocking it.

        Sleeping would be caught by the UI heartbeat and latched into the status
        bar, so the capture would advertise a freeze this harness caused.
        """
        for _ in range(rounds):
            app.processEvents()

    def settle_for(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()

    registry = window._registry
    session_cls = registry.find_best_session(session_dir)
    if session_cls is None:
        raise SystemExit(f"No session plugin claims {session_dir}. Nothing to capture.")
    print(f"session plugin: {session_cls.__name__}")

    worker = DropScanWorker([session_dir], registry)
    candidates = worker._collect_drop_candidates(session_dir)
    print(f"items: {len(candidates)}")

    # Adopt the session's own anchor/fps/skeleton exactly as a drop would, then
    # route each item directly. The batch dialog is skipped on purpose: it is
    # modal, and the plugin has already decided what this folder contains.
    drop_controller.apply_session_layout(window, worker._layout)
    window.video_grid.begin_batch_add()
    try:
        for path, loader_cls, config in candidates:
            if loader_cls is not None:
                window._route_import_candidate(path, loader_cls, config)
    finally:
        window.video_grid.end_batch_add()

    # Video probes, pane construction and imports are all asynchronous.
    settle_for(25.0)

    bounds = window.clock.state.bounds
    if bounds != (0.0, 0.0):
        target = bounds[0] + (bounds[1] - bounds[0]) * seek_fraction
        window.player.seek(target, exact=True)
        print(f"bounds {bounds[0]:.3f}..{bounds[1]:.3f}, seeking to {target:.3f}")
    settle_for(8.0)

    window.plot_pane.fit_all_y()
    settle_for(3.0)

    # Do NOT resize the window here to force a relayout: a resize tears down and
    # rebuilds the mpv render panes, and the capture comes back with three black
    # video panes instead of frames.

    window.transport.set_status("Ready")
    settle()

    for channel in window.plot_pane.channels:
        print(f"row {channel.name}: x={channel.plot_item.viewRange()[0]}")

    window.grab().save(str(out_path))
    print(f"saved {out_path}")
    window.close()
    settle()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path, help="recording folder to open")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument(
        "--seek",
        type=float,
        default=0.35,
        help="fraction of the master span to park the playhead at (0..1)",
    )
    args = parser.parse_args()

    session_dir = args.session_dir.expanduser().resolve()
    if not session_dir.is_dir():
        raise SystemExit(f"{session_dir} is not a directory")
    capture(session_dir, args.out.resolve(), args.width, args.height, args.seek)


if __name__ == "__main__":
    main()
