"""Capture a short looping animation of a real session folder opened through its plugin.

Run with, for example::

    conda run -n avialsync python tools/generate_session_screenshot.py /path/to/09-35-24

Unlike ``tools/generate_demo_screenshots.py``, which uses the checked-in sample
session and therefore reproduces from a clean clone, this one photographs
whatever recording folder you point it at. The path is an argument and never
hardcoded: field data lives outside the repository and differs per lab.

It drives the real intake — session plugin discovery, the layout it returns, and
the ordinary per-source load path — so what is captured is what a user gets by
dropping the folder on the window, not a staged arrangement.

The output is an animated GIF rather than a still. A single frame cannot show
the one thing this app exists for, which is every source moving on one clock.
The defaults spend one second of wall time on one second of session time, so the
motion a reader sees runs at the speed the recording was made at; at the 230 fps
these cameras record, stepping frame by frame instead would advance the traces by
a few milliseconds and look frozen. Raise ``--span`` above ``--duration`` to
compress a longer stretch, at the cost of no longer showing real-time speed.

The frame size and palette are chosen for how fast the loop appears, not for
fidelity: this is the first thing on the README, so it has to be readable enough
to show the layout and small enough to arrive before the reader scrolls past it.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "docs" / "_static" / "screenshots" / "session_overview.gif"

#: Longest we wait for one exact seek to reach every pane before capturing anyway.
SEEK_TIMEOUT_SECONDS = 5.0

#: Longest we wait for the loaded window to stop redrawing before recording.
QUIET_TIMEOUT_SECONDS = 60.0
#: Per-pixel channel-sum difference that counts as a real change, not render noise.
QUIET_TOLERANCE = 24
#: Fraction of changed pixels below which two grabs count as the same picture.
QUIET_FRACTION = 0.001


def _to_pillow(image: QImage) -> Image.Image:
    """Copy a QImage into Pillow without a PNG round trip.

    Qt pads every scanline to a four-byte boundary, so the source stride is
    passed explicitly rather than recomputed from the width.
    """
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    return Image.frombytes(
        "RGB",
        (rgb.width(), rgb.height()),
        rgb.constBits().tobytes(),
        "raw",
        "RGB",
        rgb.bytesPerLine(),
    )


def quantize_to_shared_palette(frames: list[Image.Image], colors: int) -> list[Image.Image]:
    """Map every frame onto one palette derived from all of them.

    Per-frame palettes force the GIF writer to store each frame whole. One
    shared palette lets it store only the pixels that changed, which for a UI
    that is mostly static between frames is the difference between a loop that
    appears instantly and one that streams in. Dithering is off for the same
    reason: its noise defeats the run-length coding underneath GIF.

    Median cut, not maximum coverage: this window is mostly neutral grey, and
    maximum coverage picks representatives off the grey axis, which tints every
    flat panel a different colour from the app it is a picture of.
    """
    width, height = frames[0].size
    stack = Image.new("RGB", (width, height * len(frames)))
    for index, frame in enumerate(frames):
        stack.paste(frame, (0, index * height))
    palette = stack.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    return [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]


def write_gif(frames: list[Image.Image], out_path: Path, duration: float, colors: int) -> None:
    """Write ``frames`` as one endlessly looping GIF spanning ``duration`` seconds."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # GIF delays are stored in hundredths of a second, so round to that grid
    # instead of letting each decoder truncate differently.
    delay_ms = max(20, round(duration * 1000 / len(frames) / 10) * 10)
    first, *rest = quantize_to_shared_palette(frames, colors)
    first.save(
        out_path,
        save_all=True,
        append_images=rest,
        duration=delay_ms,
        loop=0,
        optimize=True,
    )
    size_kb = out_path.stat().st_size / 1024
    print(f"saved {out_path} ({len(frames)} frames, {delay_ms} ms each, {size_kb:.0f} kB)")


def _load_session(window, session_dir: Path) -> None:
    """Open ``session_dir`` the way a drop onto the window would."""
    from avialsync.engine.drop_worker import DropScanWorker
    from avialsync.ui.controllers import drop_controller

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


def capture(
    session_dir: Path,
    out_path: Path,
    width: int,
    height: int,
    seek_fraction: float,
    span: float,
    frames: int,
    duration: float,
    gif_size: tuple[int, int],
    colors: int,
) -> None:
    """Open ``session_dir``, record ``frames`` of playback, and write the loop."""
    from avialsync.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)

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

    def wait_for_seek() -> None:
        """Return once every seeking pane has settled on the new frame.

        "The request was queued" is not "the frame is painted", so this waits on
        each pane's own seeking state, which clears in the same slot that swaps
        in the decoded frame, then drains a few more rounds for the paint.
        """
        deadline = time.monotonic() + SEEK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            app.processEvents()
            if window.player.seeker.is_settled():
                break
        settle()

    def grab() -> Image.Image:
        image = window.grab().toImage()
        scaled = image.scaled(
            gif_size[0],
            gif_size[1],
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return _to_pillow(scaled)

    def wait_until_quiet(timeout: float = QUIET_TIMEOUT_SECONDS) -> None:
        """Hold at a fixed playhead until the window stops redrawing itself.

        Source coverage starts as the import worker's estimate and is replaced by
        the span the readers actually cover once every queued plot row exists,
        which repaints the Data Streams lanes seconds after the video panes
        already look finished. Recording through that moment bakes it into the
        loop, where a one-off redraw reads as a blink. Comparing successive grabs
        catches it without this script having to know which widget lags: nothing
        moves on its own while playback is paused.
        """
        deadline = time.monotonic() + timeout
        previous: np.ndarray | None = None
        while time.monotonic() < deadline:
            settle_for(0.5)
            current = np.asarray(grab(), dtype=np.int16)
            if previous is not None and not window._job_manager.is_busy():
                changed = float((np.abs(current - previous).sum(axis=2) > QUIET_TOLERANCE).mean())
                if changed < QUIET_FRACTION:
                    return
            previous = current
        print(f"window still redrawing after {timeout:.0f} s; recording anyway")

    _load_session(window, session_dir)

    # Video probes, pane construction and imports are all asynchronous.
    settle_for(25.0)

    bounds = window.clock.state.bounds
    if bounds[1] <= bounds[0]:
        raise SystemExit(
            "The session has no time span; nothing loaded. Aborting rather than "
            "writing a GIF of twelve identical frames."
        )
    start = bounds[0] + (bounds[1] - bounds[0]) * seek_fraction
    # Never run the clip past the end of the recording: a shorter loop beats one
    # that freezes on the last frame for half its length.
    span = min(span, max(0.0, bounds[1] - start))
    print(f"bounds {bounds[0]:.3f}..{bounds[1]:.3f}, clip {start:.3f}..{start + span:.3f}")

    window.player.seek(start, exact=True)
    wait_for_seek()
    window.plot_pane.fit_all_y()
    settle_for(3.0)
    wait_until_quiet()

    # Do NOT resize the window here to force a relayout: a resize can land the
    # capture between a layout change and the next paint, and the screenshot
    # comes back with black video panes instead of frames.

    window.transport.set_status("Ready")
    settle()

    step = span / frames
    captured: list[Image.Image] = []
    for index in range(frames):
        window.player.seek(start + index * step, exact=True)
        wait_for_seek()
        # The status line latches whatever the last operation said, and driving
        # the UI from a script trips the stall detector.
        window.transport.set_status("Ready")
        app.processEvents()
        captured.append(grab())
        print(f"frame {index + 1}/{frames}")

    write_gif(captured, out_path, duration, colors)
    window.close()
    settle()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path, help="recording folder to open")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--width", type=int, default=1600, help="window width while capturing")
    parser.add_argument("--height", type=int, default=1000, help="window height while capturing")
    parser.add_argument(
        "--seek",
        type=float,
        default=0.35,
        help="fraction of the master span the clip starts at (0..1)",
    )
    parser.add_argument(
        "--span",
        type=float,
        default=1.0,
        help="seconds of session time the clip covers",
    )
    parser.add_argument("--frames", type=int, default=12, help="number of GIF frames")
    parser.add_argument(
        "--duration",
        type=float,
        default=1.0,
        help="seconds one loop of the GIF lasts",
    )
    parser.add_argument("--gif-width", type=int, default=960, help="max GIF width")
    parser.add_argument("--gif-height", type=int, default=720, help="max GIF height")
    parser.add_argument(
        "--colors",
        type=int,
        default=256,
        help="shared palette size, 256 being the most GIF allows",
    )
    args = parser.parse_args()

    session_dir = args.session_dir.expanduser().resolve()
    if not session_dir.is_dir():
        raise SystemExit(f"{session_dir} is not a directory")
    if args.frames < 2:
        raise SystemExit("--frames must be at least 2 for an animation")
    capture(
        session_dir,
        args.out.resolve(),
        args.width,
        args.height,
        args.seek,
        args.span,
        args.frames,
        args.duration,
        (args.gif_width, args.gif_height),
        args.colors,
    )


if __name__ == "__main__":
    main()
