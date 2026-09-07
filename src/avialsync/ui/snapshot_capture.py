"""Capture the window's surfaces for a snapshot figure, on the UI thread.

Nothing here grabs the window.  Each surface is re-rendered offscreen at the
resolution its own content justifies — a camera at the size it decoded at, the
3D pose re-projected into its tile, the channel stack whole rather than however
much of it fitted in the scroll viewport — and handed on as immutable
:class:`QImage` copies for :mod:`avialsync.engine.snapshot` to lay out on a
worker thread.

Re-rendering rather than grabbing is also what keeps one painting authority per
surface (AGENTS rule 15): these are the widgets' own ``paintEvent`` paths run at
a different scale, not a second drawing of the same thing.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from avialsync.engine.snapshot import (
    SnapshotFigure,
    SnapshotTheme,
    SnapshotTile,
    plan_media_layout,
)

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.video_pane import VideoPane

#: Longest edge a camera tile is rendered at.  Native resolution is the target;
#: this only stops a 4K rig from producing a figure nobody can open.
_MAX_TILE_EDGE = 1600
#: Bounds on how far a pane is over-rendered.  Below 1.0 a snapshot would carry
#: less than the window showed; above 4.0 the extra pixels are interpolation,
#: because no decoded frame is that much larger than the pane displaying it.
_MIN_RENDER_SCALE = 1.0
_MAX_RENDER_SCALE = 4.0
#: Size the 3D pose is re-projected at, 4:3 so it sits evenly beside cameras.
_TRACKING_TILE_SIZE = (760, 570)
#: Bounds on the plot stack's render scale.  A plot is vector-drawn, so beyond
#: a modest oversample the extra pixels buy nothing but file size.
_MIN_PLOT_SCALE = 0.5
_MAX_PLOT_SCALE = 3.0


def capture_theme() -> SnapshotTheme:
    """Read the figure's colours off the running application's palette.

    Palette roles only: themes are appearance-only, so an exported figure
    follows the workspace's appearance without any widget restyling of its own.
    """
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return SnapshotTheme.light()
    palette = app.palette()
    foreground = palette.color(QPalette.ColorRole.WindowText)
    background = palette.color(QPalette.ColorRole.Window)
    return SnapshotTheme(
        background=background,
        foreground=foreground,
        # A caption states measured values — a frame number, a rate — so it is
        # mixed towards the background rather than taken from the disabled role,
        # which is calibrated to say "you cannot use this" and reads as too
        # faint to trust once it is print on a page.
        muted=_blend(foreground, background, 0.68),
        panel=palette.color(QPalette.ColorRole.Mid),
        font_family=app.font().family(),
    )


def _blend(color: QColor, towards: QColor, weight: float) -> QColor:
    """Mix *color* towards another by *weight* (1.0 keeps *color* unchanged)."""
    other = 1.0 - weight
    return QColor(
        round(color.red() * weight + towards.red() * other),
        round(color.green() * weight + towards.green() * other),
        round(color.blue() * weight + towards.blue() * other),
    )


def _render_layers(widgets: list[QWidget], scale: float, background: QColor | None) -> QImage:
    """Render stacked, co-located widgets into one image at *scale*.

    The device pixel ratio is what applies the scale: Qt scales a widget's own
    painting to the target's ratio, so this is the widget's real paint code at a
    higher resolution rather than a magnified capture of it.  It is reset to 1
    afterwards because the figure works in real pixels throughout — sizing a
    canvas in device pixels while positioning content in device-independent ones
    is exactly the bug this export used to have.
    """
    first = widgets[0]
    width = max(1, round(first.width() * scale))
    height = max(1, round(first.height() * scale))
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(scale)
    image.fill(background if background is not None else Qt.GlobalColor.transparent)
    for widget in widgets:
        # Unbound on purpose: pyqtgraph's GraphicsView inherits QGraphicsView's
        # unrelated `render(painter, target, source)` overload, which shadows the
        # widget one. This asks for the widget render — viewport plus children —
        # whatever class the surface happens to be.
        QWidget.render(widget, image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    image.setDevicePixelRatio(1.0)
    return image


def _frame_render_scale(pane: VideoPane) -> float:
    """Choose a render scale that reproduces the decoded frame's own pixels."""
    geometry = pane.surface.frame_geometry()
    size = pane.video_size
    if geometry is None or size is None:
        return _MIN_RENDER_SCALE
    displayed_width = size[0] * geometry[0]
    if displayed_width <= 0:
        return _MIN_RENDER_SCALE
    wanted = min(size[0], _MAX_TILE_EDGE)
    return min(max(wanted / displayed_width, _MIN_RENDER_SCALE), _MAX_RENDER_SCALE)


def _frame_rect(pane: VideoPane, scale: float, bounds: QRect) -> QRect:
    """Locate the frame inside a pane render, so the tile carries no letterbox.

    The transform comes from the surface that drew the frame, which is also
    what the tracking overlay projects through, so the crop cannot disagree
    with either.
    """
    geometry = pane.surface.frame_geometry()
    size = pane.video_size
    if geometry is None or size is None:
        return bounds
    frame_scale, offset_x, offset_y = geometry
    rect = QRect(
        round(offset_x * scale),
        round(offset_y * scale),
        max(1, round(size[0] * frame_scale * scale)),
        max(1, round(size[1] * frame_scale * scale)),
    )
    cropped = rect.intersected(bounds)
    return cropped if cropped.width() > 1 and cropped.height() > 1 else bounds


def _osd_detail(pane: VideoPane) -> str:
    """Flatten the pane's own readout into one caption line.

    Taken from the live OSD label rather than re-derived: the caption then says
    exactly what the pane said, and ``format_video_osd`` stays the only place
    that decides how a frame number or rate is written (AGENTS rule 15).  On
    screen it is a stacked block clipped to the pane's width; here it has a full
    caption line, which is where the truncated "Time: 00:0" came from.
    """
    return " · ".join(line.strip() for line in pane.lbl_osd.text().splitlines() if line.strip())


def capture_video_tile(pane: VideoPane, title: str) -> SnapshotTile | None:
    """Capture one camera at its decoded resolution, with its overlays."""
    surface = pane.surface
    if surface.width() <= 0 or surface.height() <= 0:
        return None

    if not pane.shows_footage or pane.video_size is None:
        return SnapshotTile(
            _placeholder_image(surface.width(), surface.height(), pane.lbl_no_footage.text()),
            title,
            _osd_detail(pane),
        )

    scale = _frame_render_scale(pane)
    # Surface then overlay: the overlay is translucent and co-located with the
    # surface, so this composites the marks over the frame exactly as the pane
    # stacks them.
    image = _render_layers([surface, pane.paint_canvas], scale, QColor(0, 0, 0))
    frame = image.copy(_frame_rect(pane, scale, image.rect()))
    return SnapshotTile(frame, title, _osd_detail(pane))


def _placeholder_image(width: int, height: int, message: str) -> QImage:
    """Draw the pane's own no-footage placeholder at tile size (D-010)."""
    image = QImage(max(1, width), max(1, height), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0))
    painter = QPainter(image)
    try:
        painter.setPen(QColor(200, 200, 200))
        painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, message)
    finally:
        painter.end()
    return image


def capture_tracking_tile(pane: Any) -> SnapshotTile | None:
    """Re-project the 3D pose into its own tile, or None when there is none."""
    canvas = getattr(pane, "canvas", None)
    if canvas is None or canvas.point_count == 0:
        return None
    width, height = _TRACKING_TILE_SIZE
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    try:
        canvas.render_scene(painter, width, height)
    finally:
        painter.end()
    return SnapshotTile(image, "3D Tracking", pane.status_label.text())


def plot_aspect(plot_pane: Any) -> float | None:
    """Width over height of the whole channel stack, or None when there is none.

    Read before anything is rendered: the figure's width is settled against
    this, so a forty-row stack narrows the page instead of being stretched to a
    multi-camera row's width.
    """
    stack = _plot_stack(plot_pane)
    if stack is None:
        return None
    return stack.width() / stack.height()


def _plot_stack(plot_pane: Any) -> QWidget | None:
    """The channel stack widget, when it has visible rows with a real size."""
    if not getattr(plot_pane, "channels", None):
        return None
    stack: QWidget = plot_pane.graphics_layout
    if stack.width() <= 0 or stack.height() <= 0:
        return None
    return stack


def capture_plot_image(plot_pane: Any, content_width: int) -> QImage | None:
    """Render the whole channel stack at the figure's width.

    The stack widget is rendered, not the scroll area around it: it already
    carries the height its rows need, so rows below the fold — the ones the old
    export cut in half — come out with the rest.
    """
    stack = _plot_stack(plot_pane)
    if stack is None:
        return None
    scale = min(max(content_width / stack.width(), _MIN_PLOT_SCALE), _MAX_PLOT_SCALE)
    image = _render_layers([stack], scale, None)
    if image.width() != content_width and image.width() > 0:
        image = image.scaledToWidth(content_width, Qt.TransformationMode.SmoothTransformation)
    return image


def _video_tiles(window: MainWindow) -> list[SnapshotTile]:
    """Capture every displayed camera, named by its file."""
    grid = window.video_grid
    paths = grid.pane_paths()
    displayed = set(map(id, grid.visible_panes()))
    tiles: list[SnapshotTile] = []
    for index, pane in enumerate(grid.panes):
        if id(pane) not in displayed:
            continue
        # The grid blanks a lone camera's on-video label, but a figure read
        # later still has to say which recording it is looking at.
        title = Path(paths[index]).name if index < len(paths) else f"Camera {index + 1}"
        tile = capture_video_tile(pane, title)
        if tile is not None:
            tiles.append(tile)
    return tiles


def _subtitle(window: MainWindow, tiles: int) -> str:
    """State the instant the figure describes, and what it was drawn from.

    The time is written by the transport, so a figure exported while the window
    is showing UTC says UTC too.  Re-deriving it here would need a second copy
    of the display mode and the epoch, and a second copy is how a caption comes
    to disagree with the clock above it (AGENTS rule 15).
    """
    parts = [f"t = {window.transport.format_master_time(window.clock.state.t)}"]
    if tiles:
        parts.append(f"{tiles} camera{'s' if tiles != 1 else ''}")
    # Visible rows only: the subtitle counts what the figure actually contains,
    # not what the session has loaded. A hidden channel is not in the plot band.
    channels = sum(1 for channel in getattr(window.plot_pane, "channels", ()) if channel.visible)
    if channels:
        parts.append(f"{channels} channel{'s' if channels != 1 else ''}")
    return " · ".join(parts)


def _footer(window: MainWindow) -> str:
    """Name the session and when the figure was written."""
    session = window._session_path
    name = session.name if session is not None else "unsaved session"
    stamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    return f"AvialSync · {name} · exported {stamp}"


def _title(window: MainWindow) -> str:
    """Title the figure after the session, matching the window title's name."""
    session = window._session_path
    return session.stem if session is not None else "Untitled session"


def capture_figure(window: MainWindow) -> SnapshotFigure:
    """Capture every displayed surface into one layout-planned figure."""
    tiles = _video_tiles(window)
    tracking = capture_tracking_tile(window.tracking_3d_pane)
    if tracking is not None:
        tiles.append(tracking)

    layout = plan_media_layout(tiles, plot_aspect(window.plot_pane))
    return SnapshotFigure(
        layout=layout,
        plot=capture_plot_image(window.plot_pane, layout.content_width),
        title=_title(window),
        subtitle=_subtitle(window, len(tiles) - (1 if tracking is not None else 0)),
        footer=_footer(window),
        theme=capture_theme(),
    )


def capture_pane_figure(window: MainWindow, pane: VideoPane, title: str) -> SnapshotFigure:
    """Capture a single camera as its own figure, without the rest of the window."""
    tile = capture_video_tile(pane, title)
    tiles = [tile] if tile is not None else []
    return SnapshotFigure(
        layout=plan_media_layout(tiles),
        plot=None,
        title=title,
        subtitle=_subtitle(window, len(tiles)),
        footer=_footer(window),
        theme=capture_theme(),
    )
