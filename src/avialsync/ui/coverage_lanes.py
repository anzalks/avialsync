"""Where each source has data, where it has evidence, and where it has neither.

The residual plot and the correspondence plot both answer questions about the
*matched* events. Neither can show the thing a person asks first: do these
recordings even overlap, and is the alignment between them interpolated or
extrapolated?

Three bands per source, on one absolute time axis that always shows the whole
session:

* **data** -- where the source has samples or frames at all;
* **evidence** -- the span between its first and last sync point, which is
  where a mapping is interpolated rather than extended;
* **gaps** -- where the recording stopped and resumed, drawn in place rather
  than counted in a sentence.

The difference between the first two is the most under-reported thing in
alignment tooling. Interpolating between sync points and extending past the
last one are different claims, and a number that averages them is not a claim
about either.
"""

from __future__ import annotations

import dataclasses

import pyqtgraph as pg
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from avialsync.ui.i18n import tr
from avialsync.ui.plot_theme import apply_canvas_palette
from avialsync.ui.theme import coverage_color, status_color

__all__ = ["CoverageLanes", "SourceCoverage"]

#: Vertical room one source's lane occupies, in arbitrary plot units. The bands
#: are drawn inside it at fixed fractions so every lane reads the same way.
_LANE_HEIGHT = 1.0
_DATA_BAND = (0.15, 0.55)
_EVIDENCE_BAND = (0.60, 0.85)

#: Enough left-axis width for a filename. Without a floor the names go
#: undrawn: the axis sizes to its tick text once, and text set later does not
#: make it resize.
_LABEL_WIDTH = 110

#: Vertical pixels per source, so three lanes are legible and twelve still fit
#: in a dialog rather than pushing the evidence panels off it.
_PIXELS_PER_LANE = 26


def _key_text() -> str:
    """What the bands mean, in words rather than as colour alone.

    Categorical colour never carries meaning on its own here (rule 17, D-094):
    the same sentence is the key for a sighted reader and, through
    :meth:`CoverageLanes.describe`, the whole content for one using a screen
    reader.
    """
    return tr(
        "Bands, top to bottom in each lane: where evidence was measured, then the "
        "recording itself — plain where the alignment is measured, marked where it is "
        "extended past the last sync point, and marked differently again where the "
        "recording stops and resumes."
    )


@dataclasses.dataclass(frozen=True)
class SourceCoverage:
    """One source's spans on the master clock."""

    label: str
    #: Where this source has data at all, in master time.
    data: tuple[float, float]
    #: First and last sync point, or ``None`` when nothing was accepted.
    evidence: tuple[float, float] | None = None
    #: Where the recording stops and resumes, as ``(start, end)`` pairs.
    gaps: tuple[tuple[float, float], ...] = ()

    def extrapolated(self) -> tuple[tuple[float, float], ...]:
        """The parts of the data no evidence reaches, before and after it.

        An alignment holds between sync points because it was measured there.
        Outside them it is an extension of a trend, which may be right and is a
        different claim, and this is the span over which that claim is made.
        """
        if self.evidence is None:
            return (self.data,)
        spans = []
        if self.data[0] < self.evidence[0]:
            spans.append((self.data[0], self.evidence[0]))
        if self.data[1] > self.evidence[1]:
            spans.append((self.evidence[1], self.data[1]))
        return tuple(spans)


class CoverageLanes(QWidget):
    """One strip per source, on a shared time axis that never auto-ranges."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget()
        self._plot.setMenuEnabled(False)
        self._plot.setMouseEnabled(x=True, y=False)
        self._plot.getPlotItem().hideButtons()
        self._plot.setLabel("bottom", tr("Master time (s)"))
        self._plot.setMinimumHeight(70)
        self._plot.setAccessibleName(tr("Source coverage"))
        # Room for the lane names. The left axis sizes itself to its tick text,
        # and text set after the widget is laid out does not re-trigger that --
        # so without a floor the names are simply not drawn.
        self._plot.getPlotItem().getAxis("left").setWidth(_LABEL_WIDTH)
        layout.addWidget(self._plot)

        self._key = QLabel(self)
        self._key.setWordWrap(True)
        self._key.setText(_key_text())
        layout.addWidget(self._key)

        self._sources: list[SourceCoverage] = []
        self._apply_palette()

    # ── following the appearance ─────────────────────────────────────

    def changeEvent(self, event: QEvent) -> None:
        """Re-theme, and redraw the bars, which are fixed-colour brushes."""
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._apply_palette()
            if self._sources:
                self.show_sources(self._sources)

    def _apply_palette(self) -> None:
        apply_canvas_palette(self._plot, self.palette())

    # ── drawing ──────────────────────────────────────────────────────

    def show_sources(self, sources: list[SourceCoverage]) -> None:
        """Draw every source's lane, or clear when there are none."""
        self._plot.clear()
        self._sources = list(sources)
        if not sources:
            return

        palette = self.palette()
        for index, source in enumerate(sources):
            base = float(len(sources) - 1 - index) * _LANE_HEIGHT
            self._draw_band(source.data, base, _DATA_BAND, coverage_color(palette))
            for span in source.extrapolated():
                # Same band, marked: this is data the alignment reaches by
                # extension rather than by measurement.
                self._draw_band(span, base, _DATA_BAND, status_color(palette, "warning"))
            if source.evidence is not None:
                self._draw_band(
                    source.evidence, base, _EVIDENCE_BAND, status_color(palette, "info")
                )
            for gap in source.gaps:
                self._draw_band(gap, base, _DATA_BAND, status_color(palette, "error"))

        axis = self._plot.getPlotItem().getAxis("left")
        axis.setTicks(
            [
                [
                    (float(len(sources) - 1 - index) * _LANE_HEIGHT + 0.35, source.label)
                    for index, source in enumerate(sources)
                ]
            ]
        )
        self._plot.setYRange(-0.1, len(sources) * _LANE_HEIGHT, padding=0)
        self._plot.setXRange(*self.session_span(), padding=0.02)
        # Grows with the number of sources rather than squeezing them, and the
        # dialog's own layout decides what to do about it.
        self._plot.setMinimumHeight(max(70, len(sources) * _PIXELS_PER_LANE + 40))
        self._key.setAccessibleDescription(self.describe())

    def session_span(self) -> tuple[float, float]:
        """The whole session, which is what this view always shows.

        Never the union of what happened to be matched. Two recordings that
        barely overlap is the single most important thing this view can say,
        and auto-ranging to the overlap is what would hide it.
        """
        if not self._sources:
            return (0.0, 1.0)
        starts = [source.data[0] for source in self._sources]
        ends = [source.data[1] for source in self._sources]
        low, high = min(starts), max(ends)
        return (low, high) if high > low else (low, low + 1.0)

    def _draw_band(
        self,
        span: tuple[float, float],
        base: float,
        band: tuple[float, float],
        colour: object,
    ) -> None:
        """One filled rectangle, in master time."""
        start, end = float(span[0]), float(span[1])
        if end <= start:
            return
        low = base + band[0]
        high = base + band[1]
        item = pg.FillBetweenItem(
            pg.PlotDataItem([start, end], [low, low]),
            pg.PlotDataItem([start, end], [high, high]),
            brush=pg.mkBrush(colour),
        )
        self._plot.addItem(item)

    def describe(self) -> str:
        """What the lanes show, for a reader who cannot see them.

        A bar chart is invisible to a screen reader and the overlap it shows is
        the thing being judged (rule 17).
        """
        if not self._sources:
            return tr("No sources loaded.")
        lines = []
        for source in self._sources:
            span = source.data[1] - source.data[0]
            if source.evidence is None:
                lines.append(
                    tr("{name}: {span:.1f} s of data, no accepted alignment.").format(
                        name=source.label, span=span
                    )
                )
                continue
            extended = sum(end - start for start, end in source.extrapolated())
            lines.append(
                tr(
                    "{name}: {span:.1f} s of data, aligned by evidence across "
                    "{measured:.1f} s of it, extended across {extended:.1f} s."
                ).format(
                    name=source.label,
                    span=span,
                    measured=source.evidence[1] - source.evidence[0],
                    extended=extended,
                )
            )
        return " ".join(lines)
