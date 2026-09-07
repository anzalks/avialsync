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

Each video pane is zoomed onto the limbs before recording, since the joints the
tracking overlay marks are otherwise a cluster of dots too small to read at GIF
size. Pass ``--video-zoom 1.0`` for the fitted whole-animal view instead.

The frame size and palette are chosen for how fast the loop appears, not for
fidelity: this is the first thing on the README, so it has to be readable enough
to show the layout and small enough to arrive before the reader scrolls past it.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from screenshot_kit import pin_appearance, pin_layout

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "docs" / "_static" / "screenshots" / "aol_session_overview.gif"

#: Longest we wait for one exact seek to reach every pane before capturing anyway.
SEEK_TIMEOUT_SECONDS = 5.0

#: Longest we wait for the loaded window to stop redrawing before recording.
QUIET_TIMEOUT_SECONDS = 60.0
#: Per-pixel channel-sum difference that counts as a real change, not render noise.
QUIET_TOLERANCE = 24
#: Fraction of changed pixels below which two grabs count as the same picture.
QUIET_FRACTION = 0.001

#: Gap in pane pixels left above the highest tracked marker once the video panes
#: are framed. Small enough that the head bar reads as sitting on the pane's top
#: edge, wide enough that its marker is not clipped in half by it.
VIDEO_FRAME_TOP_MARGIN = 12.0

#: Clearance in pane pixels kept beside the outermost markers. A marker exactly
#: on the border reads as cut off, and its name is drawn beside it.
VIDEO_FRAME_SIDE_MARGIN = 16.0


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


def _tracked_points(pane: object) -> list[tuple[float, float]]:
    """Return the pane's limb markers in video pixels at the frame it is showing.

    Read from the overlay canvas rather than from the readers directly so the
    framing is decided by exactly the markers the reader will see drawn, at the
    time the pane is actually parked on.
    """
    canvas = pane.paint_canvas  # type: ignore[attr-defined]
    points: list[tuple[float, float]] = []
    for track in canvas.tracks:
        for reader_x, reader_y in track.points.values():
            x = reader_x.value_at(canvas.t)
            y = reader_y.value_at(canvas.t)
            if not (np.isnan(x) or np.isnan(y)):
                points.append((float(x), float(y)))
    return points


def _frame_pane_on_limbs(pane: object, zoom: float, crowded_zoom: float) -> None:
    """Magnify one video pane and hang its topmost marker off the pane's top edge."""
    surface = pane.surface  # type: ignore[attr-defined]
    points = _tracked_points(pane)
    fitted = surface.frame_geometry()
    if not points or fitted is None:
        # Nothing tracked in this camera at this instant: a centred zoom is
        # still better than the fitted view, and guessing a pan would be worse.
        surface.zoom_by(zoom)
        return

    # Pull back the one camera the requested zoom is too tight for.
    #
    # The zoom is asked for once for all three cameras, but they are not aimed
    # alike: the one looking along the animal spreads the same nine joints over
    # twice the pane width the others need, and at the shared zoom it is visibly
    # closer in than its neighbours. Backing that pane off keeps the three
    # roughly matched; the cameras that already fit are left at what was asked.
    marker_span = (max(x for x, _ in points) - min(x for x, _ in points)) * fitted[0]
    room = surface.width() - 2 * VIDEO_FRAME_SIDE_MARGIN
    if marker_span > 0.0 and marker_span * zoom > room:
        zoom = min(zoom, crowded_zoom)
        print(f"markers overrun this pane; holding this camera at {zoom:.2f}x")

    surface.zoom_by(zoom)
    geometry = surface.frame_geometry()
    if geometry is None:
        return
    scale, offset_x, offset_y = geometry
    top_x, top_y = min(points, key=lambda point: point[1])
    surface.pan_by(
        QPointF(
            surface.width() / 2.0 - (offset_x + top_x * scale),
            VIDEO_FRAME_TOP_MARGIN - (offset_y + top_y * scale),
        )
    )
    _nudge_markers_into_view(surface, points)


def _nudge_markers_into_view(surface: object, points: list[tuple[float, float]]) -> None:
    """Shift a framed pane sideways by as little as it takes to show every marker.

    Centring on the topmost marker sets the vertical framing, but it says nothing
    about how the rest spread out beside it: in the camera looking along the
    animal, the head bar sits at one end of the row and half the limbs fall off
    the pane. A camera whose markers already fit is not moved.
    """
    geometry = surface.frame_geometry()  # type: ignore[attr-defined]
    if geometry is None:
        return
    scale, offset_x, _ = geometry
    left = offset_x + min(x for x, _ in points) * scale
    right = offset_x + max(x for x, _ in points) * scale
    width = surface.width()  # type: ignore[attr-defined]
    if right - left > width - 2 * VIDEO_FRAME_SIDE_MARGIN:
        # Only reachable if a marker moved between the zoom cap and here: split
        # the loss evenly rather than dropping one whole limb off one side.
        surface.pan_by(QPointF(width / 2.0 - (left + right) / 2.0, 0.0))  # type: ignore[attr-defined]
        return
    overshoot_left = max(0.0, VIDEO_FRAME_SIDE_MARGIN - left)
    overshoot_right = max(0.0, right - (width - VIDEO_FRAME_SIDE_MARGIN))
    surface.pan_by(QPointF(overshoot_left - overshoot_right, 0.0))  # type: ignore[attr-defined]


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
    azimuth_deg: float | None = None,
    elevation_deg: float | None = None,
    video_zoom: float = 1.0,
    crowded_zoom: float = 1.0,
) -> None:
    """Open ``session_dir``, record ``frames`` of playback, and write the loop."""
    from avialsync.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    pin_appearance(app)

    window = MainWindow()
    window.resize(width, height)
    window.show()

    # Seed the first-run pane ratio rather than inheriting a saved one.
    #
    # MainWindow restores splitter state from QSettings, so how much height the
    # plots get is decided by however the app was last left on this machine —
    # two runs of this same command produced three visible trace rows and then
    # one. A documentation image has to be a property of the recording, not of
    # the operator's window. Applied before loading so the relayout it causes
    # settles during the import rather than under the capture. The stills
    # harness needed the same guarantee, so the call lives in the kit now.
    pin_layout(window)

    def settle(rounds: int = 60) -> None:
        """Drain the event loop without blocking it.

        Sleeping would be caught by the UI heartbeat and latched into the status
        bar, so the capture would advertise a freeze this harness caused.

        ``DeferredDelete`` is flushed for the reason ``screenshot_kit.settle``
        gives: Qt holds those until an event loop returns, and this script never
        runs one, so a replaced widget would keep painting over the one that
        replaced it.
        """
        for _ in range(rounds):
            app.processEvents()
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

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

    # Frame the 3D pose the way a reader would: press Fit View.
    #
    # The 3D camera fits once when tracking first arrives, and its scene bounds
    # then only ever *grow* — `set_cursor` expands them with every pose it is
    # shown. By the time the loading above has settled, the camera is framing
    # the union of every pose the cursor passed through, so the one pose the
    # loop actually shows sits small and off-centre inside it, with the limbs
    # nearest the camera collapsing onto each other. Fit View resets those
    # bounds to the current pose, which is the picture the pane is for.
    window.tracking_3d_pane.fit_button.click()

    # Then place the camera, when the caller named an angle. The pane's default
    # orbit shows this rig's limbs nearly end-on, so elbow, paw and toe project
    # onto one another and their labels overlap into an unreadable clump; a
    # front-on view separates every joint.
    #
    # Reaching past the public surface is deliberate and confined to this
    # harness: orbiting is a mouse gesture, and synthesising drag events to
    # arrive at a known angle would be less exact than naming the angle.
    if azimuth_deg is not None:
        window.tracking_3d_pane.canvas._azimuth = math.radians(azimuth_deg)
    if elevation_deg is not None:
        window.tracking_3d_pane.canvas._elevation = math.radians(elevation_deg)
    window.tracking_3d_pane.canvas.update()
    settle()

    # Frame the video panes on the limbs, the way a reader would with the pane's
    # own zoom buttons and a middle-button drag.
    #
    # Fitted whole, each camera spends most of its pane on apparatus, body and
    # head, and the tracked joints — shoulder through toe — end up as a cluster
    # of markers too small to read at GIF size. Zooming alone does not fix that:
    # centred, the magnified view keeps whatever the camera happens to be aimed
    # at, and each camera sees the animal somewhere else. So the pan that follows
    # is derived from the overlay's own markers at the frame being recorded: the
    # topmost one — the head bar, in this rig — is hung at the top centre of the
    # pane, which lands the skeleton below it in every camera at once.
    if video_zoom > 1.0:
        for pane in window.video_grid.visible_panes():
            _frame_pane_on_limbs(pane, video_zoom, crowded_zoom)
        settle()

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
        "--azimuth",
        type=float,
        default=None,
        help="3D camera azimuth in degrees; omit to keep the pane's own orbit",
    )
    parser.add_argument(
        "--elevation",
        type=float,
        default=None,
        help="3D camera elevation in degrees; 0 puts the ground plane edge-on",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=1.0,
        help="seconds one loop of the GIF lasts",
    )
    parser.add_argument(
        "--video-zoom",
        type=float,
        default=1.25**8,
        help=(
            "magnify each video pane onto the limbs; 1.0 keeps the fitted view. "
            "The default is eight presses of a pane's + button (1.25 each)"
        ),
    )
    parser.add_argument(
        "--crowded-zoom",
        type=float,
        default=1.25**7,
        help=(
            "zoom used instead for a camera whose markers overrun the pane at "
            "--video-zoom; the default is one press of + less"
        ),
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
        args.azimuth,
        args.elevation,
        args.video_zoom,
        args.crowded_zoom,
    )


if __name__ == "__main__":
    main()
