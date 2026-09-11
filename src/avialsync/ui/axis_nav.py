"""Per-axis navigation for a pyqtgraph canvas: scroll, zoom, and a real reset.

The alignment evidence view shipped a bare ``PlotWidget`` and told it nothing,
so it inherited pyqtgraph's stock interaction: both axes free, wheel zooming
both at once, and a reset buried in a developer context menu next to
Downsample and Average.  Two of those are actively wrong for evidence being
judged before acceptance.

*Free Y zoom throws away the tolerance band*, which is the only thing giving
the residual scatter a scale -- one wheel click and "3 ms" means nothing.

*Reset must go somewhere declared.*  pyqtgraph's "View All" auto-ranges to the
plotted points, and auto-ranging to the matched subset is what parked a
catastrophically wrong fit in the fifty-second window where it happened to look
good.  :meth:`AxisNav.set_home_range` makes the owner state what "all" means --
for evidence, the full span the fit was computed over, not the part that
survived it.

This is the single authority for that gesture set (architecture rule 15): the
buttons, the wheel, and the keyboard drive the same view box through the same
methods, so a plot cannot acquire a second dialect of "zoom out".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGraphicsSceneWheelEvent,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["AxisNav", "NavigableViewBox", "ZOOM_STEP"]

#: One button press or wheel notch. Chosen to need ~3 presses to halve a range,
#: which reads as deliberate rather than as a jump.
ZOOM_STEP = 1.25

#: A range narrower than this in view units is treated as degenerate and reset
#: rather than scaled, so repeated zoom-in cannot collapse an axis to a point
#: it can never recover from by zooming out.
_MIN_SPAN = 1e-12


class NavigableViewBox(pg.ViewBox):
    """A view box whose wheel means one thing at a time.

    pyqtgraph's default wheel scales both axes together.  On a residual plot
    that silently changes the vertical scale -- the tolerance band -- while the
    user believes they are moving along time.  Here the bare wheel is time,
    and the other axis needs a modifier to move at all:

    * wheel — zoom the X axis about the cursor
    * ``Shift`` + wheel — pan along X
    * ``Ctrl`` + wheel — zoom the Y axis about the cursor

    ``Ctrl`` rather than ``Alt`` because Alt+wheel is a window-management
    gesture on several Linux desktops and never reaches the widget.
    """

    def wheelEvent(self, event: QGraphicsSceneWheelEvent, axis: int | None = None) -> None:
        """Route one wheel notch to exactly one axis."""
        delta = float(event.delta())
        if not delta:
            event.accept()
            return

        modifiers = event.modifiers()
        notches = delta / 120.0
        center = self.mapSceneToView(event.scenePos())

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            # Pan by a fraction of what is on screen, so the gesture feels the
            # same whether the user is looking at a whole session or a second
            # of it.
            (x_min, x_max), _ = self.viewRange()
            self.translateBy(x=-(x_max - x_min) * 0.1 * notches)
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            self.scaleBy(s=(1.0, ZOOM_STEP**-notches), center=center)
        else:
            self.scaleBy(s=(ZOOM_STEP**-notches, 1.0), center=center)
        event.accept()


class AxisNav(QWidget):
    """A compact strip of per-axis zoom and reset controls for one view box.

    Buttons rather than a context menu because the most useful control here --
    getting back to the whole picture -- should not be hidden behind the
    gesture that produced the wrong picture.
    """

    def __init__(self, view_box: pg.ViewBox, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view_box = view_box
        self._home_x: tuple[float, float] | None = None
        self._home_y: tuple[float, float] | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._build_axis_group(layout, tr("Time"), "x")
        layout.addSpacing(8)
        self._build_axis_group(layout, tr("Residual"), "y")
        layout.addSpacing(8)

        self._fit_all = self._button(
            tr("Fit all"),
            tr("Show the whole span the fit was computed over, not only the matched part"),
            self.reset_both,
        )
        layout.addWidget(self._fit_all)
        layout.addStretch(1)

    # ── construction helpers ─────────────────────────────────────────

    def _build_axis_group(self, layout: QHBoxLayout, label: str, axis: str) -> None:
        """Add a ``label  [-] [+] [reset]`` group driving one axis."""
        caption = QLabel(label, self)
        caption.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(caption)

        # Accessible names carry the axis, because "−" alone is meaningless to
        # a screen reader and there are two of every button here (rule 17).
        layout.addWidget(
            self._button(
                "−",
                tr("Zoom out {axis}").format(axis=label),
                lambda: self.zoom(axis, out=True),
                accessible=tr("Zoom out {axis}").format(axis=label),
            )
        )
        layout.addWidget(
            self._button(
                "+",
                tr("Zoom in {axis}").format(axis=label),
                lambda: self.zoom(axis, out=False),
                accessible=tr("Zoom in {axis}").format(axis=label),
            )
        )
        layout.addWidget(
            self._button(
                tr("Reset"),
                tr("Return {axis} to its full range").format(axis=label),
                lambda: self.reset(axis),
                accessible=tr("Reset {axis}").format(axis=label),
            )
        )

    def _button(
        self,
        text: str,
        tooltip: str,
        on_click: Callable[[], None],
        accessible: str | None = None,
    ) -> QPushButton:
        """One control, described for both a pointer and a screen reader."""
        button = QPushButton(text, self)
        button.setToolTip(tooltip)
        button.setAccessibleName(accessible or text)
        button.setAccessibleDescription(tooltip)
        button.setAutoRepeat(True)
        button.setFixedHeight(22)
        button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        button.clicked.connect(on_click)
        return button

    # ── the range "reset" returns to ─────────────────────────────────

    def set_home_range(
        self, x_range: tuple[float, float] | None, y_range: tuple[float, float] | None
    ) -> None:
        """Declare what the full picture is, for reset to return to.

        Passing ``None`` for an axis falls back to pyqtgraph's auto-range for
        that axis alone.  Callers with evidence should always pass X: the whole
        point is that the evidence span is known and is not the same as the
        extent of the points that happened to match.
        """
        self._home_x = x_range
        self._home_y = y_range

    # ── the gestures themselves ──────────────────────────────────────

    def zoom(self, axis: str, *, out: bool) -> None:
        """Scale one axis about the centre of what is currently shown."""
        factor = ZOOM_STEP if out else 1.0 / ZOOM_STEP
        scale = (factor, 1.0) if axis == "x" else (1.0, factor)
        self._view_box.scaleBy(s=scale)

    def reset(self, axis: str) -> None:
        """Return one axis to its declared home range."""
        home = self._home_x if axis == "x" else self._home_y
        if home is None or not self._is_usable(home):
            self._view_box.enableAutoRange(axis=axis)
            self._view_box.disableAutoRange(axis=axis)
            return
        if axis == "x":
            self._view_box.setXRange(*home, padding=0.02)
        else:
            self._view_box.setYRange(*home, padding=0.05)

    def reset_both(self) -> None:
        """Return both axes at once, which is what "fit all" means."""
        self.reset("x")
        self.reset("y")

    @staticmethod
    def _is_usable(span: tuple[float, float]) -> bool:
        """Whether a home range describes an interval a view box can show."""
        low, high = span
        return bool(high - low > _MIN_SPAN)
