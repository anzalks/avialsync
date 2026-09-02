"""Showing the evidence behind an alignment, not just its summary (WP-10).

BLUEPRINT principle 8 requires that TTL/event alignment "presents the matched
evidence, offset/drift fit, residuals, and confidence before the user accepts
it". What it actually presented was one sentence:

    47 matched events; 3 unmatched; offset 1.240000 s; drift 12.400 ppm;
    maximum residual 3.100 ms.

Those four numbers are a *summary*. They cannot show whether the residuals are
scattered evenly or drifting, whether the rejected events cluster at one end,
or whether the fit is carried by a handful of points at the extremes. A user is
being asked to accept a correction to scientific timing on faith in an average.

This draws the residuals against the tolerance band that decided them, and the
matched and rejected events on a shared axis, so the shape of the fit is
visible before it is accepted.

Decimated like any plot in this application: never more points than pixels
(architecture rule 4). A 50 kHz TTL channel can match tens of thousands of
events, and drawing all of them would spend the frame budget to produce a
smear.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from avialsync.core.sync import SyncProposal
from avialsync.ui.i18n import tr
from avialsync.ui.theme import status_color

__all__ = ["SyncEvidenceView", "decimate_residuals"]

#: Roughly one marker per horizontal pixel at a usable panel width. Beyond this
#: the scatter is a band rather than a set of points, and the extremes -- which
#: are what a reader is looking for -- are what get lost first.
MAX_PLOTTED_POINTS = 800

#: A residual trend below this is not worth reporting, whatever the scatter.
#: Sub-microsecond drift across a recording is arithmetic, not evidence.
_TREND_FLOOR_MS = 0.001


def decimate_residuals(
    times: np.ndarray, residuals: np.ndarray, limit: int = MAX_PLOTTED_POINTS
) -> tuple[np.ndarray, np.ndarray]:
    """Reduce to at most *limit* points, keeping the extremes.

    Not a plain stride: dropping every *n*-th point would drop the worst
    residual as readily as a typical one, and the worst residual is the single
    most important thing on this plot. Each bucket contributes its largest
    absolute residual, so the envelope survives.
    """
    count = len(times)
    if count <= limit or count == 0:
        return times, residuals

    bucket_edges = np.linspace(0, count, limit + 1, dtype=int)
    kept_times = np.empty(limit, dtype=float)
    kept_residuals = np.empty(limit, dtype=float)

    for index in range(limit):
        start, stop = bucket_edges[index], bucket_edges[index + 1]
        if stop <= start:
            stop = start + 1
        window = residuals[start:stop]
        worst = int(np.argmax(np.abs(window)))
        kept_times[index] = times[start + worst]
        kept_residuals[index] = window[worst]

    return kept_times, kept_residuals


class SyncEvidenceView(QWidget):
    """Residuals against the tolerance that judged them."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._headline = QLabel("No alignment has been proposed.")
        self._headline.setWordWrap(True)
        layout.addWidget(self._headline)

        self._plot = pg.PlotWidget()
        self._plot.setLabel("bottom", "Reference time", units="s")
        self._plot.setLabel("left", "Residual", units="ms")
        self._plot.showGrid(x=True, y=True, alpha=0.2)
        self._plot.setMinimumHeight(180)
        layout.addWidget(self._plot)

        self._reading = QLabel("")
        self._reading.setWordWrap(True)
        layout.addWidget(self._reading)

        self.setAccessibleName(tr("Alignment evidence"))

    # ── showing a proposal ───────────────────────────────────────────

    def show_proposal(self, proposal: SyncProposal | None) -> None:
        """Draw the evidence behind *proposal*, or clear."""
        self._plot.clear()
        if proposal is None:
            self._headline.setText(tr("No alignment has been proposed."))
            self._reading.setText("")
            return

        fit = proposal.fit
        self._headline.setText(
            f"{fit.matched_count} matched, {fit.rejected_count} rejected · "
            f"offset {fit.offset:.6f} s · drift {fit.drift_ppm:.3f} ppm · "
            f"RMS {fit.rms_residual * 1000:.3f} ms · worst {fit.max_residual * 1000:.3f} ms"
        )

        if not proposal.matches:
            self._reading.setText(
                "No individual matches were retained, so there is nothing to plot. "
                "The summary above is the whole of the evidence."
            )
            return

        times = np.array([match.reference_time for match in proposal.matches], dtype=float)
        residuals = np.array([match.residual * 1000.0 for match in proposal.matches], dtype=float)
        plotted_times, plotted_residuals = decimate_residuals(times, residuals)

        tolerance_ms = proposal.tolerance * 1000.0
        if tolerance_ms > 0:
            # The band that decided which events counted. Without it the
            # scatter has no scale and "3 ms" means nothing.
            band = pg.LinearRegionItem(
                values=(-tolerance_ms, tolerance_ms),
                orientation="horizontal",
                movable=False,
                brush=pg.mkBrush(128, 128, 128, 40),
            )
            band.setZValue(-10)
            self._plot.addItem(band)

        self._plot.plot(
            plotted_times,
            plotted_residuals,
            pen=None,
            symbol="o",
            symbolSize=5,
            symbolBrush=pg.mkBrush(status_color(self.palette(), "info")),
        )

        if proposal.unmatched_references:
            # Rejected events at the foot of the plot: where they sit in time
            # is the question -- a cluster at one end means the recordings
            # only overlap partly, which no residual can show.
            rejected = np.array(proposal.unmatched_references, dtype=float)
            floor = float(np.min(plotted_residuals)) if len(plotted_residuals) else 0.0
            self._plot.plot(
                rejected,
                np.full(len(rejected), floor),
                pen=None,
                symbol="x",
                symbolSize=7,
                symbolBrush=pg.mkBrush(status_color(self.palette(), "error")),
            )

        self._reading.setText(self._read_the_shape(times, residuals, proposal))

    # ── saying what the plot shows ───────────────────────────────────

    @staticmethod
    def _read_the_shape(times: np.ndarray, residuals: np.ndarray, proposal: SyncProposal) -> str:
        """Describe the fit in words, for a reader who cannot see the plot.

        Also the accessible description: a scatter plot is invisible to a
        screen reader, and the shape it shows is the thing being judged.
        """
        notes: list[str] = []

        if len(times) >= 3:
            # A residual trend means the offset/drift model has not absorbed
            # everything, which is exactly what a plain average hides.
            slope = float(np.polyfit(times - times[0], residuals, 1)[0])
            span = float(times[-1] - times[0]) or 1.0
            drift_across = abs(slope) * span
            scatter = float(np.std(residuals))
            # Both tests, because either alone misreports. Against scatter
            # alone, perfectly flat residuals have a standard deviation of
            # exactly zero and any floating-point slope beats it. Against an
            # absolute floor alone, a genuinely noisy fit would hide a real
            # trend inside its own spread.
            if drift_across > scatter and drift_across > _TREND_FLOOR_MS:
                notes.append(
                    f"Residuals trend by {drift_across:.3f} ms across the recording, "
                    "so some timing difference the fit did not absorb remains."
                )
            else:
                notes.append("Residuals are scattered evenly, with no remaining trend.")

        rejected = len(proposal.unmatched_references)
        if rejected:
            total = rejected + proposal.fit.matched_count
            notes.append(
                f"{rejected} of {total} reference events found no partner "
                f"({100.0 * rejected / max(total, 1):.0f}%)."
            )

        if proposal.fit.matched_count < 10:
            notes.append(
                "Few matches: an offset fitted from this many events is easily "
                "moved by one bad one."
            )

        return " ".join(notes)
