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
import os
import shutil
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QEvent, QEventLoop, QPoint, QRect, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QCheckBox,
    QPushButton,
    QWidget,
)

from avialsync.core.cache import CACHE_DIR_ENV
from avialsync.engine.transcode import encode_video
from avialsync.ui import recovery, theme
from avialsync.ui.time_format import apply_number_locale


def isolate_user_state() -> Path:
    """Point settings, the recovery snapshot, and the cache at a throwaway folder.

    A screenshot run builds a real ``MainWindow`` and closes it, and closing a
    window that holds anything writes the recovery snapshot unconditionally
    (D-089). Unisolated, photographing the docs replaced the operator's own
    unsaved-work snapshot with a synthetic session, and wrote window geometry
    and preferences into their installed application. This is the same
    sandbox ``tests/conftest.py`` gives the test suite, applied at import so it
    precedes every ``QSettings`` the tools construct. It returns the folder.
    """
    sandbox = Path(tempfile.mkdtemp(prefix="avialsync-screenshots-"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(sandbox))
    recovery_target = sandbox / "appdata"
    recovery_target.mkdir()
    recovery.recovery_dir = lambda: recovery_target
    os.environ[CACHE_DIR_ENV] = str(sandbox / "cache")
    return sandbox


#: The sandbox every tool importing this module runs in.
USER_STATE_SANDBOX = isolate_user_state()

#: Highlight colour. Chosen to stay legible on both the dark chrome and the
#: black video panes, and to be distinguishable by someone who cannot separate
#: red from green — nothing in the UI itself is this colour, so the box reads as
#: an annotation rather than as part of the application.
HIGHLIGHT = QColor(255, 64, 64)
HIGHLIGHT_WIDTH = 3

#: Padding between a widget's bounds and its box: compact controls on macOS
#: already carry internal focus margin, so 1 px hugs the control without
#: crossing into adjacent form rows or stacked buttons.
_PAD_COMPACT = 1
_PAD_CONTAINER = 2
_BADGE_RADIUS = 9
_BOX_CLEAR_GAP = 4

HighlightTarget = QWidget | Sequence[QWidget]


def pin_appearance(app: QApplication) -> None:
    """Force the documented appearance without touching saved preferences.

    ``apply_theme`` persists, which would silently rewrite the preference of
    whoever runs this. The private ``_apply`` is used deliberately for its
    ``persist=False``: taking a screenshot must not be a settings change.
    """
    theme._apply(app, theme.THEME_DARK, persist=False)
    # The number policy the application applies at startup (D-173): without it
    # a screenshot shows the build machine's decimal separator, not the app's.
    apply_number_locale()


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


def pin_layout(window: Any) -> None:
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
    notification bar across them. Clearing drops the banner without deleting
    the snapshot (D-105), leaving the operator's recovery file untouched.
    """
    window._apply_default_splitter_sizes()
    window.notifications.clear_all()


def capture(
    window: QWidget,
    path: Path,
    highlights: Sequence[HighlightTarget] = (),
    *,
    numbered: bool = False,
    crop: QWidget | None = None,
) -> None:
    """Grab *window* and save it, boxing each widget or widget group in *highlights*."""
    notifications = getattr(window, "notifications", None)
    if notifications is not None:
        notifications.clear_all()
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
    crop_rect = _crop_bounds_in(window, crop) if crop is not None else None
    canvas_rect = crop_rect if crop_rect is not None else window.rect()
    safe_canvas = canvas_rect.adjusted(
        HIGHLIGHT_WIDTH, HIGHLIGHT_WIDTH, -HIGHLIGHT_WIDTH, -HIGHLIGHT_WIDTH
    )
    pixmap = window.grab()
    if highlights:
        entries: list[tuple[QRect, QWidget]] = []
        for target in highlights:
            resolved = _target_bounds_in(window, target, safe_canvas)
            if resolved is not None:
                entries.append(resolved)
        boxes = _decollide_boxes([rect for rect, _ in entries])
        widgets = [w for _, w in entries]
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(HIGHLIGHT, HIGHLIGHT_WIDTH))
        for box in boxes:
            painter.drawRoundedRect(box, 5, 5)
        if numbered:
            placed_badges: list[QRect] = []
            badge_canvas = canvas_rect.adjusted(2, 2, -2, -2)
            for idx, (box, primary_widget) in enumerate(zip(boxes, widgets, strict=True)):
                circle = _choose_badge_circle(
                    box, idx, boxes, placed_badges, badge_canvas, primary_widget
                )
                placed_badges.append(circle)
                _draw_step_number(painter, circle, idx + 1)
        painter.end()
    if crop_rect is not None:
        ratio = pixmap.devicePixelRatio()
        pixmap = pixmap.copy(
            QRect(
                round(crop_rect.x() * ratio),
                round(crop_rect.y() * ratio),
                round(crop_rect.width() * ratio),
                round(crop_rect.height() * ratio),
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(path))


def _crop_bounds_in(window: QWidget, crop: QWidget) -> QRect | None:
    """Return *crop*'s exact unpadded rectangle in *window* coordinates."""
    if not crop.isVisible() or crop.width() <= 0 or crop.height() <= 0:
        return None
    top_left = crop.mapTo(window, QPoint(0, 0))
    return QRect(top_left, crop.size()).intersected(window.rect())


def _bounds_in(window: QWidget, widget: QWidget) -> QRect | None:
    """Return *widget*'s padded, viewport-clamped rectangle in *window* coordinates."""
    if not widget.isVisible() or widget.width() <= 0 or widget.height() <= 0:
        return None
    top_left = widget.mapTo(window, QPoint(0, 0))
    width = widget.width()
    if isinstance(widget, QCheckBox):
        width = min(width, widget.sizeHint().width() + 6)
    pad = _PAD_COMPACT if widget.height() <= 44 else _PAD_CONTAINER
    rect = QRect(top_left.x(), top_left.y(), width, widget.height()).adjusted(-pad, -pad, pad, pad)
    parent = widget.parentWidget()
    while parent is not None and parent is not window:
        if isinstance(parent, QAbstractScrollArea):
            vp = parent.viewport()
            if vp is not None and vp.isVisible():
                vp_rect = QRect(vp.mapTo(window, QPoint(0, 0)), vp.size()).adjusted(2, 2, -2, -2)
                rect = rect.intersected(vp_rect)
        parent = parent.parentWidget()
    return rect if rect.width() > 4 and rect.height() > 4 else None


def _target_bounds_in(
    window: QWidget, target: HighlightTarget, safe_canvas: QRect
) -> tuple[QRect, QWidget] | None:
    """Resolve a single widget or a sequence of widgets into one clamped box."""
    members: tuple[QWidget, ...] = (target,) if isinstance(target, QWidget) else tuple(target)
    rects = [(r, w) for w in members if (r := _bounds_in(window, w)) is not None]
    if not rects:
        return None
    combined = rects[0][0]
    for rect, _ in rects[1:]:
        combined = combined.united(rect)
    clamped = combined.intersected(safe_canvas)
    if clamped.width() <= 4 or clamped.height() <= 4:
        return None
    return clamped, rects[0][1]


def _contains_mostly(outer: QRect, inner: QRect) -> bool:
    inter = outer.intersected(inner)
    if inter.isEmpty():
        return False
    area = max(1, inner.width() * inner.height())
    return (inter.width() * inter.height()) / area >= 0.8


def _decollide_boxes(boxes: list[QRect]) -> list[QRect]:
    """Separate adjacent highlight outlines so strokes never touch or cross."""
    out = [QRect(b) for b in boxes]
    half_gap = _BOX_CLEAR_GAP // 2
    for _ in range(2):
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                a, b = out[i], out[j]
                if _contains_mostly(a, b) or _contains_mostly(b, a):
                    continue
                x_ov = min(a.right(), b.right()) - max(a.left(), b.left())
                y_ov = min(a.bottom(), b.bottom()) - max(a.top(), b.top())
                dy = abs(a.center().y() - b.center().y())
                dx = abs(a.center().x() - b.center().x())
                if x_ov > 6 and dy >= 12:
                    upper, lower = (a, b) if a.center().y() <= b.center().y() else (b, a)
                    if upper.bottom() >= lower.top() - _BOX_CLEAR_GAP:
                        mid = (upper.bottom() + lower.top()) // 2
                        if (
                            mid - half_gap - upper.top() >= 10
                            and lower.bottom() - (mid + half_gap) >= 10
                        ):
                            upper.setBottom(mid - half_gap)
                            lower.setTop(mid + half_gap)
                elif y_ov > 6 and dx >= 14:
                    left_b, right_b = (a, b) if a.center().x() <= b.center().x() else (b, a)
                    if left_b.right() >= right_b.left() - _BOX_CLEAR_GAP:
                        mid = (left_b.right() + right_b.left()) // 2
                        if (
                            mid - half_gap - left_b.left() >= 12
                            and right_b.right() - (mid + half_gap) >= 12
                        ):
                            left_b.setRight(mid - half_gap)
                            right_b.setLeft(mid + half_gap)
    return out


def _choose_badge_circle(
    box: QRect,
    index: int,
    boxes: list[QRect],
    placed_badges: list[QRect],
    canvas_rect: QRect,
    primary_widget: QWidget,
) -> QRect:
    """Pick a collision-free badge circle for *box* within *canvas_rect*."""
    r = _BADGE_RADIUS
    wide_button = isinstance(primary_widget, QPushButton) and box.width() >= 160
    stacked_with_button = wide_button and any(
        m != index
        and abs(boxes[m].left() - box.left()) < 24
        and abs(boxes[m].center().y() - box.center().y()) < 80
        for m in range(len(boxes))
    )
    narrow_button = box.width() < 60
    candidates: list[tuple[int, int]] = []
    if stacked_with_button:
        candidates.append((box.left() + r + 5, box.center().y()))
    if narrow_button:
        candidates.extend(
            [
                (box.left() + 1, box.top() - 4),
                (box.right() - 1, box.top() - 4),
                (box.left() + 1, box.bottom() + 4),
                (box.right() - 1, box.bottom() + 4),
            ]
        )
    candidates.extend(
        [
            (box.left() + 1, box.top() - 4),
            (box.right() + r + 5, box.center().y()),
            (box.right() - 2, box.top() - 4),
            (box.left() + r + 5, box.center().y())
            if wide_button
            else (box.left() + 8, box.bottom() + 3),
            (box.left() + 8, box.bottom() + 3),
            (box.right() - 6, box.bottom() + 3),
        ]
    )
    for cx, cy in candidates:
        circle = QRect(cx - r, cy - r, r * 2, r * 2)
        if not canvas_rect.contains(circle):
            continue
        if any(
            m != index
            and not _contains_mostly(boxes[m], box)
            and circle.intersects(boxes[m].adjusted(-3, -3, 3, 3))
            for m in range(len(boxes))
        ):
            continue
        if any(circle.intersects(prev.adjusted(-2, -2, 2, 2)) for prev in placed_badges):
            continue
        return circle
    # Clamped fallback inside canvas_rect, clear of boxes immediately above
    cx = max(canvas_rect.left() + r, min(canvas_rect.right() - r, box.left() + r + 4))
    cy = max(canvas_rect.top() + r, min(canvas_rect.bottom() - r, box.top() + r + 5))
    return QRect(cx - r, cy - r, r * 2, r * 2)


def _draw_step_number(painter: QPainter, circle: QRect, number: int) -> None:
    """Draw a filled step badge with a subtle dark halo so it separates from borders."""
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(24, 26, 30))
    painter.drawEllipse(circle.adjusted(-2, -2, 2, 2))
    painter.setBrush(HIGHLIGHT)
    painter.drawEllipse(circle)
    painter.setPen(QPen(QColor(255, 255, 255)))
    font = QFont(painter.font())
    font.setBold(True)
    font.setPointSize(9)
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


def _blend_rgb(
    fg: tuple[int, int, int], bg: tuple[int, int, int], alpha: float
) -> tuple[int, int, int]:
    return (
        round(fg[0] * alpha + bg[0] * (1.0 - alpha)),
        round(fg[1] * alpha + bg[1] * (1.0 - alpha)),
        round(fg[2] * alpha + bg[2] * (1.0 - alpha)),
    )


def quantize_gif_frames(frames: list[Any], colors: int = 256) -> list[Any]:
    """Quantize *frames* to one shared GIF palette without losing sparse marker hues.

    Monochrome camera footage and dark UI chrome occupy >99 % of the pixels in a
    session overview, so pure ``MEDIANCUT`` allocates almost every slot to greys
    and snaps tiny coloured pose dots to grey. Reserving explicit slots for
    ``POINT_COLORS`` (plus anti-aliased fur/canvas blends and UI accents) keeps
    both neutral flat panels and vivid body-part markers intact.
    """
    from PIL import Image

    from avialsync.ui.tracking_colors import POINT_COLORS

    reserved: list[tuple[int, int, int]] = []
    if colors >= 128:
        fur_bg = (116, 116, 116)
        dark_bg = (32, 34, 38)
        for rgb in POINT_COLORS:
            reserved.append(rgb)
            reserved.append(_blend_rgb(rgb, fur_bg, 0.68))
            reserved.append(_blend_rgb(rgb, dark_bg, 0.68))
        reserved.extend(
            [
                (0, 255, 255),
                (255, 166, 35),
                (196, 132, 28),
                (10, 132, 255),
                (0, 102, 214),
                (60, 200, 190),
                (240, 150, 60),
                (68, 132, 122),
                (68, 92, 136),
                (255, 64, 64),
            ]
        )
    # Deduplicate while keeping order
    unique_reserved = list(dict.fromkeys(reserved))
    auto_count = max(32, min(256, colors) - len(unique_reserved))

    width, height = frames[0].size
    sample = (
        frames
        if len(frames) <= 12
        else [frames[i] for i in np.linspace(0, len(frames) - 1, 8, dtype=int)]
    )
    stack = Image.new("RGB", (width, height * len(sample)))
    for index, frame in enumerate(sample):
        stack.paste(frame, (0, index * height))

    base = stack.quantize(colors=auto_count, method=Image.Quantize.MEDIANCUT)
    base_palette = base.getpalette() or []
    raw_pal = list(base_palette[: auto_count * 3])
    for r, g, b in unique_reserved[: max(0, min(256, colors) - auto_count)]:
        raw_pal.extend((int(r), int(g), int(b)))
    while len(raw_pal) < 768:
        raw_pal.extend((0, 0, 0))

    pal_img = Image.new("P", (16, 16))
    pal_img.putpalette(raw_pal[:768])
    return [frame.quantize(palette=pal_img, dither=Image.Dither.NONE) for frame in frames]
