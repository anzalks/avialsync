"""Shared capture helpers for the documentation screenshots.

Two things every screenshot tool in this directory needs, and got wrong
independently before this existed:

**Pin the appearance.** An unpinned theme follows whichever preference the
developer last saved, so the same command produced light-mode images on one
machine and dark-mode on another, and the docs ended up with a mix.

**Do not run these under ``QT_QPA_PLATFORM=offscreen``.** The offscreen plugin
has no native menu bar, so Qt draws one inside the window and every capture
gains a File/View/Help strip that a real macOS user never sees.

The third thing is new: a guide screenshot has to show *where to click*. A
picture of a dialog does not tell anyone which of its nine fields matters for
the step being described, so :func:`capture` draws a red box around the widgets
a step actually uses, and numbers them when order matters.
"""

from __future__ import annotations

import csv
import math
import shutil
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QEventLoop, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from avialsync.engine.transcode import encode_video
from avialsync.ui import theme

#: Highlight colour. Chosen to stay legible on both the dark chrome and the
#: black video panes, and to be distinguishable by someone who cannot separate
#: red from green — nothing in the UI itself is this colour, so the box reads as
#: an annotation rather than as part of the application.
HIGHLIGHT = QColor(255, 64, 64)
HIGHLIGHT_WIDTH = 3

#: Padding between a widget's bounds and its box, so the outline never sits on
#: top of the text it is pointing at.
_PAD = 4


def pin_appearance(app: QApplication) -> None:
    """Force the documented appearance without touching saved preferences.

    ``apply_theme`` persists, which would silently rewrite the preference of
    whoever runs this. The private ``_apply`` is used deliberately for its
    ``persist=False``: taking a screenshot must not be a settings change.
    """
    theme._apply(app, theme.THEME_DARK, persist=False)


@contextmanager
def staged_fixture(source: Path) -> Iterator[Path]:
    """Copy a fixture folder somewhere neutral and yield the copy.

    A window shows the paths it was given: the sidebar card, the sync wizard's
    evidence menus. Opened from the repository they read
    ``/Users/<whoever ran this>/Documents/...``, which put a username into a
    published image. Opening a copy from a temporary directory keeps the
    operator out of the picture. The copy is additive (``copytree`` into a fresh
    directory) and the directory is this call's own, removed on exit.
    """
    with tempfile.TemporaryDirectory(prefix="avialsync-docs-") as scratch:
        target = Path(scratch) / source.name
        shutil.copytree(source, target)
        yield target


def write_synthetic_sync_fixture(folder: Path) -> Path:
    """Create short synthetic camera and trigger files in a caller-owned temp folder."""
    folder.mkdir(parents=True, exist_ok=True)
    video_path = folder / "camera_1.mp4"

    def frames() -> Iterator[tuple[np.ndarray, float]]:
        for index in range(120):
            timestamp = index / 30.0
            image = np.full((360, 640, 3), (54, 62, 67), dtype=np.uint8)
            x = 80 + (index * 4) % 480
            image[155:205, x : x + 50] = (205, 215, 211)
            image[170:190, x + 15 : x + 35] = (245, 242, 224)
            yield image, timestamp

    encode_video(video_path, frames(), rate=Fraction(30, 1))

    signal_path = folder / "signal_base.csv"
    trigger_path = folder / "frame_triggers.csv"
    with (
        signal_path.open("w", newline="", encoding="utf-8") as signal_file,
        trigger_path.open("w", newline="", encoding="utf-8") as trigger_file,
    ):
        signal_writer = csv.writer(signal_file)
        trigger_writer = csv.writer(trigger_file)
        signal_writer.writerow(("time", "ch0", "ch1", "ch2", "TTL"))
        trigger_writer.writerow(("t", "cam_strobe"))
        for sample_index in range(4250):
            timestamp = sample_index / 1000.0
            pulse_index = round((timestamp - 0.25) * 30)
            pulse_start = 0.25 + pulse_index / 30.0
            high = 0 <= pulse_index < 120 and pulse_start <= timestamp < pulse_start + 0.004
            pulse = 1.0 if high else 0.0
            signal_writer.writerow(
                (
                    f"{timestamp:.3f}",
                    f"{math.sin(2 * math.pi * timestamp):.6f}",
                    f"{math.cos(2 * math.pi * 0.5 * timestamp):.6f}",
                    "1" if timestamp >= 2.0 else "0",
                    f"{pulse:.1f}",
                )
            )
            trigger_writer.writerow((f"{timestamp:.3f}", f"{pulse:.1f}"))

    return folder


def wait_until(
    app: QApplication,
    ready: Callable[[], bool],
    description: str,
    timeout_ms: int = 5000,
) -> None:
    """Drive Qt until a screenshot prerequisite is ready or raise on timeout."""
    if ready():
        return
    loop = QEventLoop(app)
    poll = QTimer(loop)
    poll.setInterval(10)
    poll.timeout.connect(lambda: loop.quit() if ready() else None)
    deadline = QTimer(loop)
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout_ms)
    loop.exec()
    poll.stop()
    deadline.stop()
    loop.deleteLater()
    if not ready():
        raise RuntimeError(f"Timed out waiting for {description}.")


def pin_layout(window: QWidget) -> None:
    """Put the panes back where a first run puts them.

    ``MainWindow.__init__`` restores saved geometry, so a developer who has
    ever dragged a splitter photographs their own arrangement: one run left the
    video pane 85 px tall with a blank band under the plots, which reads as a
    layout bug in the application rather than as the personal setting it was.
    Re-seeding the documented ratios is the same guarantee
    :func:`pin_appearance` gives for the theme, and like it, it writes nothing
    back -- the proportion store this touches lives on the window, not on disk.

    Call it *after* ``show()`` and a :func:`settle`: a splitter redistributes
    sizes on its first real resize, so seeding before the window has its final
    size seeds nothing.

    It also takes down the launch-time recovery offer. ``MainWindow.__init__``
    asks whether this machine has unsaved work from a previous run, so whoever
    last quit the real application mid-session decides whether the docs get a
    notification bar across them. Dismissing declines without deleting (D-105),
    so this reads the operator's snapshot and leaves it exactly where it was.
    """
    window._apply_default_splitter_sizes()
    window.notifications.clear()


def capture(
    window: QWidget,
    path: Path,
    highlights: Sequence[QWidget] = (),
    *,
    numbered: bool = False,
    crop: QWidget | None = None,
) -> None:
    """Grab *window* and save it, boxing each widget in *highlights*.

    Args:
        window: The widget to capture. Usually the main window or a dialog.
        path: Destination PNG.
        highlights: Widgets to outline, in the order the reader should use them.
        numbered: Draw a step number on each box. Use when the order matters;
            leave off when the boxes are alternatives or a single target, where
            numbers would imply a sequence that does not exist.
        crop: A widget inside *window* to cut the image down to, after the boxes
            are drawn. For a control that lives in one corner, where a full
            window would leave it a few pixels tall.
    """
    # Loading a fixture posts "Imported ..." toasts that wait to be dismissed
    # (D-107), so an image taken straight after one carries a Dismiss button
    # that no reader would recognise as part of the window. Declining them
    # acts on nothing.
    notifications = getattr(window, "notifications", None)
    if notifications is not None:
        notifications.clear_all()
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
    pixmap = window.grab()
    if highlights:
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(HIGHLIGHT, HIGHLIGHT_WIDTH))
        for index, widget in enumerate(highlights, start=1):
            box = _bounds_in(window, widget)
            if box is None:
                continue
            painter.drawRoundedRect(box, 5, 5)
            if numbered:
                _draw_step_number(painter, box, index)
        painter.end()
    if crop is not None:
        box = _bounds_in(window, crop)
        if box is not None:
            # The pixmap is device-pixel sized; the box is in logical pixels.
            ratio = pixmap.devicePixelRatio()
            pixmap = pixmap.copy(
                QRect(
                    round(box.x() * ratio),
                    round(box.y() * ratio),
                    round(box.width() * ratio),
                    round(box.height() * ratio),
                )
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(path))


def _bounds_in(window: QWidget, widget: QWidget) -> QRect | None:
    """Return *widget*'s padded rectangle in *window* coordinates.

    Returns None for a widget that is hidden or has no size yet, so a step that
    highlights something not currently on screen produces a plain screenshot
    rather than a box drawn at the origin.
    """
    if not widget.isVisible() or widget.width() <= 0 or widget.height() <= 0:
        return None
    top_left = widget.mapTo(window, QPoint(0, 0))
    return QRect(top_left, widget.size()).adjusted(-_PAD, -_PAD, _PAD, _PAD)


def _draw_step_number(painter: QPainter, box: QRect, number: int) -> None:
    """Draw a filled step badge on the box's top-left corner."""
    radius = 11
    centre = box.topLeft()
    circle = QRect(centre.x() - radius, centre.y() - radius, radius * 2, radius * 2)
    painter.save()
    painter.setBrush(HIGHLIGHT)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(circle)
    painter.setPen(QPen(QColor(255, 255, 255)))
    font = QFont(painter.font())
    font.setBold(True)
    font.setPointSize(max(9, radius))
    painter.setFont(font)
    painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(number))
    painter.restore()


def settle(app: QApplication, rounds: int = 40) -> None:
    """Drain the event loop without blocking it.

    Sleeping here would be detected by the UI heartbeat as a stall and latched
    into the status bar, so the screenshot would advertise a freeze this harness
    itself caused.

    ``processEvents`` deliberately does not deliver ``DeferredDelete``: Qt holds
    those until the event loop that posted them returns, which never happens in
    a script that drives the UI by hand. A widget replaced during capture --
    the sidebar's "No sensor data loaded." note, once a file loads -- is then
    only *removed from its layout* and keeps painting at its last geometry, so
    the screenshot shows the placeholder overlapping the card that replaced it.
    A real user never sees that frame. Flushing them here makes the capture
    agree with the running application.
    """
    for _ in range(rounds):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
