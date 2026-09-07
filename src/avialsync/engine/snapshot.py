"""Compose a report-grade snapshot figure from images captured off the window.

A snapshot is not a screen grab.  Each camera's frame is captured at the
resolution it decoded at, the 3D pose is re-projected into its own tile, and the
channel stack is rendered whole — including rows scrolled out of view — so the
file answers "what was happening at this instant" rather than "what fitted on
this monitor".

Layout is planned here and nowhere else.  The capture side asks
:func:`plan_media_layout` how wide the figure will be so it can render the plot
stack to match, and that same plan is what :func:`render_figure` draws — one
authority for the geometry, never two.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen

#: Figure geometry in output pixels.  Deliberately fixed rather than derived
#: from the window: a snapshot's proportions must not change because someone
#: dragged a splitter before pressing the button.
_MARGIN = 28
_GUTTER = 18
_TILE_HEIGHT = 340
_CAPTION_HEIGHT = 46
_HEADER_HEIGHT = 88
_FOOTER_HEIGHT = 42
_MIN_CONTENT_WIDTH = 1400
_MAX_CONTENT_WIDTH = 3200
#: How far a row of tiles may be enlarged to fill the figure width.  Without a
#: cap, one portrait tile alone on a row grows to several thousand pixels tall.
_MAX_JUSTIFY = 1.6
#: Height the plot band aims to stay within.  A channel stack is drawn whole,
#: so its aspect ratio is whatever its rows add up to, and fitting a forty-row
#: stack to a five-camera figure's width would make the band four times taller
#: than it is on screen.  This pulls the *figure* narrower instead of cropping
#: the stack: tiles wrap onto more rows and every channel still appears.
_MAX_PLOT_HEIGHT = 6000

_TITLE_PIXEL_SIZE = 24
_SUBTITLE_PIXEL_SIZE = 14
_CAPTION_PIXEL_SIZE = 15
_CAPTION_DETAIL_PIXEL_SIZE = 12
_FOOTER_PIXEL_SIZE = 12


@dataclass(frozen=True)
class SnapshotTheme:
    """Colours and typeface the figure is drawn in.

    Read off the running application's palette so an exported figure matches the
    workspace it came from; themes are appearance-only, and this carries the
    appearance rather than re-deciding it.
    """

    background: QColor
    foreground: QColor
    muted: QColor
    panel: QColor
    font_family: str = ""

    @classmethod
    def light(cls) -> SnapshotTheme:
        """A neutral light theme, used when no application palette is available."""
        return cls(
            background=QColor(255, 255, 255),
            foreground=QColor(24, 24, 24),
            muted=QColor(120, 120, 120),
            panel=QColor(236, 236, 236),
        )


@dataclass(frozen=True)
class SnapshotTile:
    """One captured surface — a camera frame or the 3D pose — and its caption."""

    image: QImage
    title: str
    detail: str = ""


@dataclass(frozen=True)
class TilePlacement:
    """Where one tile's image lands, in coordinates local to the media band."""

    tile: SnapshotTile
    rect: QRect


@dataclass(frozen=True)
class MediaLayout:
    """The planned media band: how wide the figure is and where each tile sits."""

    content_width: int
    height: int
    placements: tuple[TilePlacement, ...]


@dataclass(frozen=True)
class SnapshotFigure:
    """Everything needed to draw one snapshot, captured and immutable.

    Built on the UI thread and drawn on a worker: it holds :class:`QImage`
    copies rather than live widgets, so nothing here reaches back into a widget
    that may have repainted since.
    """

    layout: MediaLayout
    plot: QImage | None
    title: str
    subtitle: str
    footer: str
    theme: SnapshotTheme

    @property
    def content_width(self) -> int:
        """Width of the drawable column, excluding the figure's margins."""
        return self.layout.content_width

    @property
    def is_empty(self) -> bool:
        """Whether the window had nothing to show at capture time."""
        return not self.layout.placements and self.plot is None


def content_width_for(natural: int, plot_aspect: float | None) -> int:
    """Choose the figure's column width from what it has to show.

    The tiles ask for a width; a tall channel stack argues it down, because the
    stack is drawn whole and its height follows from that width.  Never below
    :data:`_MIN_CONTENT_WIDTH`, so a long stack makes a tall figure rather than
    an illegibly narrow one.
    """
    wanted = natural
    if plot_aspect is not None and plot_aspect > 0:
        wanted = min(wanted, round(_MAX_PLOT_HEIGHT * plot_aspect))
    return min(max(wanted, _MIN_CONTENT_WIDTH), _MAX_CONTENT_WIDTH)


def plan_media_layout(
    tiles: tuple[SnapshotTile, ...] | list[SnapshotTile],
    plot_aspect: float | None = None,
) -> MediaLayout:
    """Pack tiles into justified rows and report the figure width they imply.

    Every tile is first normalised to one nominal row height so a row of
    cameras reads evenly whatever each recording's resolution is, then rows are
    wrapped and stretched to a common width.  *plot_aspect* is the channel
    stack's width-over-height, when there is one, so the width this settles on
    is one both bands can live with.
    """
    tiles = tuple(tiles)
    if not tiles:
        return MediaLayout(content_width_for(_MIN_CONTENT_WIDTH, plot_aspect), 0, ())

    widths = [
        max(1, round(tile.image.width() * _TILE_HEIGHT / max(1, tile.image.height())))
        for tile in tiles
    ]
    natural = sum(widths) + _GUTTER * (len(tiles) - 1)
    content_width = content_width_for(natural, plot_aspect)

    rows: list[list[tuple[SnapshotTile, int]]] = []
    row: list[tuple[SnapshotTile, int]] = []
    used = 0
    for tile, width in zip(tiles, widths, strict=True):
        extra = width + (_GUTTER if row else 0)
        if row and used + extra > content_width:
            rows.append(row)
            row, used, extra = [], 0, width
        row.append((tile, width))
        used += extra
    if row:
        rows.append(row)

    placements: list[TilePlacement] = []
    y = 0
    for entries in rows:
        span = sum(width for _, width in entries)
        gutters = _GUTTER * (len(entries) - 1)
        factor = min((content_width - gutters) / span, _MAX_JUSTIFY) if span else 1.0
        height = max(1, round(_TILE_HEIGHT * factor))
        scaled = [max(1, round(width * factor)) for _, width in entries]
        # A row held back by the justification cap is centred rather than
        # stretched, so one tile never sits oddly against the left margin.
        x = max(0, (content_width - (sum(scaled) + gutters)) // 2)
        for index, ((tile, _), width) in enumerate(zip(entries, scaled, strict=True)):
            if index == len(entries) - 1 and x + width + _GUTTER > content_width:
                width = content_width - x  # absorb rounding so the row is flush
            placements.append(TilePlacement(tile, QRect(x, y, width, height)))
            x += width + _GUTTER
        y += height + _CAPTION_HEIGHT + _GUTTER

    return MediaLayout(content_width, max(0, y - _GUTTER), tuple(placements))


def figure_size(figure: SnapshotFigure) -> tuple[int, int]:
    """Return the ``(width, height)`` in pixels that :func:`render_figure` produces."""
    width = figure.content_width + 2 * _MARGIN
    height = _HEADER_HEIGHT + _FOOTER_HEIGHT
    if figure.layout.placements:
        height += figure.layout.height + _GUTTER
    plot_height = _plot_height(figure)
    if plot_height:
        height += plot_height + _GUTTER
    return width, height


def _plot_height(figure: SnapshotFigure) -> int:
    """Height the plot stack occupies once fitted to the content width."""
    plot = figure.plot
    if plot is None or plot.isNull() or plot.width() <= 0:
        return 0
    return max(1, round(plot.height() * figure.content_width / plot.width()))


def _font(theme: SnapshotTheme, pixel_size: int, *, bold: bool = False) -> QFont:
    """Build a figure font at an exact pixel size, so layout is display-independent."""
    font = QFont(theme.font_family) if theme.font_family else QFont()
    font.setPixelSize(pixel_size)
    font.setBold(bold)
    return font


def _draw_text(
    painter: QPainter,
    font: QFont,
    color: QColor,
    rect: QRect,
    text: str,
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
) -> None:
    """Draw one line of text, elided rather than clipped when it will not fit."""
    if not text:
        return
    painter.setFont(font)
    painter.setPen(QPen(color))
    elided = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
    painter.drawText(rect, int(alignment), elided)


def render_figure(figure: SnapshotFigure) -> QImage:
    """Draw the captured figure onto one opaque image.

    Opaque by construction: the canvas is filled with the theme background
    before anything is placed on it, and every band is drawn at an explicit
    pixel rect.  The earlier composer sized its canvas in device pixels but
    positioned content in device-independent ones, which on a 2x display left
    three quarters of the file transparent.
    """
    theme = figure.theme
    width, height = figure_size(figure)
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(theme.background)

    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        content = QRect(_MARGIN, 0, figure.content_width, 0)
        _draw_text(
            painter,
            _font(theme, _TITLE_PIXEL_SIZE, bold=True),
            theme.foreground,
            QRect(content.x(), 22, content.width(), _TITLE_PIXEL_SIZE + 8),
            figure.title,
        )
        _draw_text(
            painter,
            _font(theme, _SUBTITLE_PIXEL_SIZE),
            theme.muted,
            QRect(content.x(), 52, content.width(), _SUBTITLE_PIXEL_SIZE + 8),
            figure.subtitle,
        )
        painter.setPen(QPen(theme.panel, 1))
        painter.drawLine(content.x(), _HEADER_HEIGHT - 12, content.right(), _HEADER_HEIGHT - 12)

        y = _HEADER_HEIGHT
        if figure.layout.placements:
            _draw_media_band(painter, figure, content.x(), y)
            y += figure.layout.height + _GUTTER

        plot_height = _plot_height(figure)
        if plot_height and figure.plot is not None:
            painter.drawImage(
                QRectF(content.x(), y, figure.content_width, plot_height), figure.plot
            )
            y += plot_height + _GUTTER

        _draw_text(
            painter,
            _font(theme, _FOOTER_PIXEL_SIZE),
            theme.muted,
            QRect(content.x(), height - _FOOTER_HEIGHT, content.width(), _FOOTER_HEIGHT - 12),
            figure.footer,
        )
    finally:
        painter.end()
    return image


def _draw_media_band(
    painter: QPainter, figure: SnapshotFigure, origin_x: int, origin_y: int
) -> None:
    """Draw every tile with its caption beneath it, never over it."""
    theme = figure.theme
    caption_font = _font(theme, _CAPTION_PIXEL_SIZE, bold=True)
    detail_font = _font(theme, _CAPTION_DETAIL_PIXEL_SIZE)

    for placement in figure.layout.placements:
        rect = placement.rect.translated(origin_x, origin_y)
        # A frame letterboxed against the theme background would read as part of
        # the recording, so tiles sit on their own panel colour.
        painter.fillRect(rect, theme.panel)
        image = placement.tile.image
        if not image.isNull():
            painter.drawImage(QRectF(rect), image)
        painter.setPen(QPen(theme.panel, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        _draw_text(
            painter,
            caption_font,
            theme.foreground,
            QRect(rect.x(), rect.bottom() + 6, rect.width(), _CAPTION_PIXEL_SIZE + 6),
            placement.tile.title,
        )
        _draw_text(
            painter,
            detail_font,
            theme.muted,
            QRect(rect.x(), rect.bottom() + 26, rect.width(), _CAPTION_DETAIL_PIXEL_SIZE + 6),
            placement.tile.detail,
        )


def save_figure(figure: SnapshotFigure, path: Path) -> None:
    """Render *figure* and write it as a PNG.

    Raises:
        OSError: if the file could not be written.
    """
    image = render_figure(figure)
    # PySide6's stub declares QImage.save's `format` as bytes, but the runtime
    # rejects bytes and accepts str:
    #   QImage.save(path, b"PNG") -> ValueError: called with wrong argument values
    #   QImage.save(path, "PNG")  -> True
    # (QPixmap.save's stub correctly says str; QImage's does not.) Matching the
    # stub would break snapshot export, so the stub is what is wrong here.
    if not image.save(str(path), "PNG"):  # type: ignore[call-overload]
        raise OSError(f"Could not write snapshot: {path}")
