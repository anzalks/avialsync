"""Button icons that follow the theme.

Qt's standard media and navigation icons are drawn in one fixed ink, whatever
the palette says. On macOS that ink is black, so under the Dark appearance the
transport row showed black glyphs on a dark grey button — measured, close to no
contrast at all — while its text beside them was correctly light. The status
icons fail the other way: the platform's warning bubble is a pale outline that
all but disappears on the Light surface.

Two helpers, one per kind of icon:

* :func:`set_glyph_icon` keeps a standard icon's *shape* and repaints its ink in
  the button's own text colour, so the glyph reads exactly like the label next
  to it, enabled and disabled, and is re-inked on every appearance change.
* :func:`set_status_icon` draws a severity badge from :func:`theme.status_color`,
  so a warning is amber and an error red on both surfaces instead of whatever
  the platform's message-box artwork happens to be. The badge carries a glyph as
  well as a colour, so severity is never told by colour alone (rule 17).

Both reuse one follower per button, so switching an icon (Play to Pause, a new
severity) replaces what it follows rather than stacking a second listener.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QAbstractButton, QStyle
from shiboken6 import isValid

from avialsync.ui.theme import status_color

#: Builds the icon for a button from the palette it is about to be shown under.
IconBuilder = Callable[[QAbstractButton, QPalette], QIcon]

_FOLLOWER_NAME = "avialsync_icon_follower"


class _IconFollower(QObject):
    """Rebuilds one button's icon whenever the appearance changes."""

    def __init__(self, button: QAbstractButton, build: IconBuilder) -> None:
        super().__init__(button)
        self.setObjectName(_FOLLOWER_NAME)
        self._button = button
        self.build = build
        # A button carries no stylesheet, so unlike `theme.follow_palette` its
        # own PaletteChange does arrive on a theme switch, after Qt has
        # propagated the new palette — the moment its colours are current.
        button.installEventFilter(self)

    def apply(self) -> None:
        if isValid(self._button):
            self._button.setIcon(self.build(self._button, self._button.palette()))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.PaletteChange:
            self.apply()
        return False


def _follow(button: QAbstractButton, build: IconBuilder) -> None:
    """Give *button* the icon *build* makes, now and on every appearance change."""
    follower = button.findChild(_IconFollower, _FOLLOWER_NAME)
    if follower is None:
        follower = _IconFollower(button, build)
    else:
        follower.build = build
    follower.apply()


def _device_pixel_ratio(button: QAbstractButton) -> float:
    ratio = button.devicePixelRatioF()
    return ratio if ratio > 0 else 1.0


def _inked(source: QPixmap, ink: QColor) -> QPixmap:
    """Return *source*'s shape filled with *ink*, keeping its alpha."""
    out = QPixmap(source.size())
    out.setDevicePixelRatio(source.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), ink)
    painter.end()
    return out


def glyph_icon(
    button: QAbstractButton, palette: QPalette, standard: QStyle.StandardPixmap
) -> QIcon:
    """Return *standard* inked in *palette*'s button-text colours."""
    size = button.iconSize() if button.iconSize().isValid() else QSize(16, 16)
    source = button.style().standardIcon(standard).pixmap(size, _device_pixel_ratio(button))
    icon = QIcon()
    if source.isNull():
        return icon
    for mode, group in (
        (QIcon.Mode.Normal, QPalette.ColorGroup.Active),
        (QIcon.Mode.Active, QPalette.ColorGroup.Active),
        (QIcon.Mode.Selected, QPalette.ColorGroup.Active),
        (QIcon.Mode.Disabled, QPalette.ColorGroup.Disabled),
    ):
        inked = _inked(source, palette.color(group, QPalette.ColorRole.ButtonText))
        for state in (QIcon.State.Off, QIcon.State.On):
            icon.addPixmap(inked, mode, state)
    return icon


def set_glyph_icon(button: QAbstractButton, standard: QStyle.StandardPixmap) -> None:
    """Show *standard* on *button* in the button's own text colour, kept current."""
    _follow(button, lambda b, palette: glyph_icon(b, palette, standard))


#: Glyph drawn inside each severity badge. A shape difference as well as a
#: colour one, so the two warnings are never told apart by hue alone.
_SEVERITY_GLYPHS = {"error": "×", "warning": "!", "info": "i"}


def status_icon(button: QAbstractButton, palette: QPalette, severity: str) -> QIcon:
    """Return a round severity badge solved against *palette*."""
    size = button.iconSize() if button.iconSize().isValid() else QSize(16, 16)
    ratio = _device_pixel_ratio(button)
    pixmap = QPixmap(round(size.width() * ratio), round(size.height() * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    fill = status_color(palette, severity)
    # The glyph takes whichever pole contrasts with the disc, not the surface:
    # a pale disc on the Dark appearance needs dark ink, a deep one on Light
    # needs light ink.
    ink = palette.color(
        QPalette.ColorRole.Base if fill.lightnessF() >= 0.5 else QPalette.ColorRole.HighlightedText
    )

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    disc = QRectF(0.5, 0.5, size.width() - 1.0, size.height() - 1.0)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawEllipse(disc)
    font = QFont(button.font())
    font.setBold(True)
    font.setPixelSize(max(8, round(size.height() * 0.72)))
    painter.setFont(font)
    painter.setPen(ink)
    painter.drawText(disc, Qt.AlignmentFlag.AlignCenter, _SEVERITY_GLYPHS.get(severity, "!"))
    painter.end()
    return QIcon(pixmap)


def set_status_icon(button: QAbstractButton, severity: str) -> None:
    """Show a *severity* badge on *button*, re-coloured on every appearance change."""
    _follow(button, lambda b, palette: status_icon(b, palette, severity))
