"""Capture the Fix Identities images used by the user guide.

Run with ``conda run -n avialsync python tools/generate_identity_screenshots.py``.
Do **not** set ``QT_QPA_PLATFORM=offscreen`` — see ``tools/screenshot_kit.py``.

**Everything here is generated demonstration data.** The scene is two drawn
animals crossing paths, and the pose file is their true positions with the two
identities exchanged from the frame they pass each other — the mistake a
tracker makes, planted on purpose so the ground truth is known. Nothing comes
from a real recording (AGENTS.md rule 5), and every file the images show is
named ``synthetic_*`` so the picture says so itself rather than only this
docstring.

The scene is written into a temporary directory and opened through the drop
scanner's own routing. The one thing supplied by hand is the answer to the import
review dialog (overlay role and target video), which is modal and so cannot be
driven from a script; the panel in the images is otherwise what a real import
produces. Only ``docs/_static/screenshots/identity_*`` is written.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from avialsync.engine.transcode import encode_video

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screenshot_kit import capture, pin_appearance, pin_layout  # noqa: E402

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "docs" / "_static" / "screenshots"

WIDTH, HEIGHT = 640, 360
FPS = 30
SECONDS = 6
FRAMES = FPS * SECONDS
#: The frame the two animals are nearest each other, and the frame the
#: "tracker" exchanges them. Real swaps happen exactly here, which is why the
#: detector looks at how near two animals get rather than how fast a point moves.
SWAP_FRAME = FRAMES // 2
ANIMALS = ("mouseA", "mouseB")
PARTS = ("snout", "tailbase")
COLOURS = {"mouseA": (60, 200, 190), "mouseB": (240, 150, 60)}
HALF_BODY = 24.0

STEM = "synthetic_two_mice"


def _centre(animal: str, frame: int) -> tuple[float, float]:
    """Where *animal* really is: two paths that cross, closest at SWAP_FRAME."""
    s = frame / (FRAMES - 1)
    if animal == "mouseA":
        return 80.0 + 480.0 * s, 100.0 + 160.0 * s + 6.0 * np.sin(6.0 * s)
    return 560.0 - 480.0 * s, 260.0 - 160.0 * s + 14.0


def _heading(animal: str, frame: int) -> tuple[float, float]:
    """A unit vector along the animal's direction of travel."""
    ahead = _centre(animal, min(frame + 1, FRAMES - 1))
    behind = _centre(animal, max(frame - 1, 0))
    dx, dy = ahead[0] - behind[0], ahead[1] - behind[1]
    length = float(np.hypot(dx, dy)) or 1.0
    return dx / length, dy / length


def _true_part(animal: str, part: str, frame: int) -> tuple[float, float]:
    x, y = _centre(animal, frame)
    hx, hy = _heading(animal, frame)
    sign = 1.0 if part == "snout" else -1.0
    return x + sign * HALF_BODY * hx, y + sign * HALF_BODY * hy


def _draw_frame(frame: int) -> np.ndarray:
    """One drawn frame: an arena floor with each animal as a coloured body."""
    rows = np.arange(HEIGHT)[:, None]
    columns = np.arange(WIDTH)[None, :]
    image = np.empty((HEIGHT, WIDTH, 3), dtype=np.uint8)
    image[:] = (34, 38, 44)
    grid = ((rows % 40 == 0) | (columns % 40 == 0))[:, :, None]
    image = np.where(grid, np.uint8(46), image).astype(np.uint8)
    for animal in ANIMALS:
        cx, cy = _centre(animal, frame)
        hx, hy = _heading(animal, frame)
        # Distance along and across the body axis, in one vectorised pass.
        along = (columns - cx) * hx + (rows - cy) * hy
        across = -(columns - cx) * hy + (rows - cy) * hx
        inside = (along / (HALF_BODY + 4.0)) ** 2 + (across / 11.0) ** 2 <= 1.0
        image[inside] = COLOURS[animal]
    return image


def write_scene(folder: Path) -> tuple[Path, Path]:
    """Write the video and the two-animal pose file, and return their paths."""
    video = folder / f"{STEM}.mp4"

    def frames() -> Iterator[tuple[np.ndarray, float]]:
        for index in range(FRAMES):
            yield _draw_frame(index), index / FPS

    encode_video(video, frames(), rate=Fraction(FPS), time_base=Fraction(1, 90_000))

    columns = [(animal, part) for animal in ANIMALS for part in PARTS]
    rng = np.random.default_rng(7)
    lines = [
        "scorer," + ",".join(["synthetic"] * (3 * len(columns))),
        "individuals," + ",".join(animal for animal, _ in columns for _ in range(3)),
        "bodyparts," + ",".join(part for _, part in columns for _ in range(3)),
        "coords," + ",".join(["x", "y", "likelihood"] * len(columns)),
    ]
    other = {"mouseA": "mouseB", "mouseB": "mouseA"}
    for frame in range(FRAMES):
        cells: list[str] = [str(frame)]
        for animal, part in columns:
            # From SWAP_FRAME the tracker files each animal under the other's
            # name: the identity error the panel exists to find.
            labelled = other[animal] if frame >= SWAP_FRAME else animal
            x, y = _true_part(labelled, part, frame)
            jitter = rng.normal(0.0, 0.6, 2)
            cells += [f"{x + jitter[0]:.2f}", f"{y + jitter[1]:.2f}", "0.98"]
        lines.append(",".join(cells))
    pose = folder / f"{STEM}_DLC.csv"
    pose.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return video, pose


def _settle(app: QApplication, rounds: int = 60) -> None:
    for _ in range(rounds):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _wait(app: QApplication, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()


def _wait_idle(app: QApplication, window, timeout: float = 60.0) -> None:
    """Return once no registered job is running and the window has redrawn."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _wait(app, 0.3)
        if not window._job_manager.is_busy():
            break
    _settle(app)


def _load(window, folder: Path) -> None:
    """Open *folder* the way a drop onto the window would."""
    from avialsync.engine.drop_worker import DropScanWorker
    from avialsync.ui.controllers import drop_controller

    registry = window._registry
    worker = DropScanWorker([folder], registry)
    candidates = worker._collect_drop_candidates(folder)
    print(f"items: {[(p.name, c.__name__ if c else None) for p, c, _ in candidates]}")
    drop_controller.apply_session_layout(window, worker._layout)
    window.video_grid.begin_batch_add()
    video = next(path for path, _, _ in candidates if path.suffix == ".mp4")
    try:
        for path, loader_cls, config in candidates:
            if loader_cls is None:
                continue
            if path.suffix == ".csv":
                # What the import review fills in for a pose file that names its
                # camera (D-146). A drop of one loose file opens that modal
                # dialog; this harness supplies its answer instead of driving it.
                config = {
                    **(config or {}),
                    "fps": float(FPS),
                    "coords": ["x", "y"],
                    "role": "overlay2d",
                    "overlay_video": str(video),
                    "overlay_label": path.stem,
                }
            window._route_import_candidate(path, loader_cls, config)
    finally:
        window.video_grid.end_batch_add()


def _panel(window):
    """The identity panel, opened through the same menu action a user presses."""
    window._act_fix_identities.trigger()
    return window._identity_window.panel


def generate(out_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    """Write every Fix Identities screenshot."""
    from avialsync.ui.identity_group_dialog import IdentityGroupDialog
    from avialsync.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    pin_appearance(app)
    out_dir.mkdir(parents=True, exist_ok=True)

    def shot(window, name: str, highlights=(), *, numbered: bool = False) -> None:
        _settle(app)
        window.notifications.clear_all()
        _settle(app)
        capture(window, out_dir / name, highlights, numbered=numbered)

    with tempfile.TemporaryDirectory(prefix="avialsync-identity-") as scratch:
        folder = Path(scratch)
        write_scene(folder)
        window = MainWindow()
        try:
            window.resize(1900, 1000)
            window.show()
            _settle(app)
            _load(window, folder)
            _wait(app, 8.0)
            _wait_idle(app, window)
            pin_layout(window)
            # Name each marker by animal, through the same path as View →
            # Overlays: it is what makes a swapped identity visible in the
            # video, where colour alone would not say whose paw is whose.
            window._on_overlay_toggled("tracking.point_labels", True)
            _settle(app)

            def seek(seconds: float) -> None:
                window.player.seek(seconds, exact=True)
                _wait(app, 1.5)

            # Fix Tracker: the mode is a toggle on the toolbar under the videos.
            seek(2.0)
            window._act_fix_tracker.setChecked(True)
            _settle(app)
            shot(window, "identity_fix_tracker.png", [window.view_toolbar.fix_tracker_button])
            window._act_fix_tracker.setChecked(False)
            _settle(app)

            panel = _panel(window)
            _wait_idle(app, window)
            _wait(app, 1.5)
            shot(
                window,
                "identity_panel_opened.png",
                [panel._group_box, panel._part_box, panel._detect],
                numbered=True,
            )

            # The mistake as a viewer meets it: after the animals cross, the
            # names are on the wrong bodies.
            seek(4.5)
            pane = window.video_grid.visible_panes()[0]
            shot(window, "identity_wrong_labels.png", [pane])

            panel._detect.click()
            _wait_idle(app, window)
            _wait(app, 1.5)
            # Choosing a crossing seeks the video to it. The combo already sits
            # on the first row, so it emits nothing; seek to the same frame.
            crossing_frame = SWAP_FRAME
            seek(crossing_frame / FPS)
            shot(
                window,
                "identity_crossing.png",
                [panel._braid, panel._separation, panel._node_box],
                numbered=True,
            )
            shot(
                window,
                "identity_review_controls.png",
                [panel._back, panel._forward, panel._play, panel._apply],
                numbered=True,
            )

            # Apply at the frame on screen, exactly as the button does.
            panel._apply.click()
            _wait_idle(app, window)
            seek(4.5)
            shot(
                window,
                "identity_applied.png",
                [panel._remove, panel._remove_all],
                numbered=True,
            )

            schema = window._pose_schemas[panel.source_id()]
            dialog = IdentityGroupDialog(schema, (), window)
            # Filled in as a person would for this file: the same two animals the
            # panel already offered, declared by hand to show what each field means.
            dialog._name.setText("Both mice by hand")
            dialog._first.setText("mouseA")
            dialog._second.setText("mouseB")
            for index, part in enumerate(PARTS):
                if index:
                    dialog._add_pair()
                edit, first, second = dialog._rows[index]
                edit.setText(part)
                first.setCurrentIndex(first.findText(f"mouseA_{part}"))
                second.setCurrentIndex(second.findText(f"mouseB_{part}"))
            dialog.show()
            _settle(app)
            first_row = dialog._rows[0]
            capture(
                dialog,
                out_dir / "identity_new_group.png",
                [dialog._name, dialog._first, dialog._second, *first_row],
                numbered=True,
            )
            dialog.close()
        finally:
            window.close()
    print(f"Wrote identity screenshots to {out_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    generate(parser.parse_args().output_dir)
