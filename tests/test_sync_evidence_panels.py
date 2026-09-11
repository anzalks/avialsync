"""Residuals cannot show a wrong pairing. The correspondence panel can.

Residuals are conditional on the matching: they measure how tightly the matched
pairs agree with the model and say nothing about whether those are the right
pairs, so a degenerate match reports a *smaller* residual than a correct one. A
real fit reached acceptance reading "RMS 0.000 ms, worst 0.000 ms" at a rate
four decades outside physics, and the residual plot beside it drew a flat band
at zero and said the residuals were scattered evenly with no remaining trend.
Both statements were true.
"""

from __future__ import annotations

import numpy as np
import pytest

from avialsync.core.sync import SyncFit, SyncMatch, SyncProposal
from avialsync.ui.sync_evidence_view import SyncEvidenceView


def _proposal(reference: np.ndarray, target: np.ndarray, *, rejected=()) -> SyncProposal:
    residuals = np.zeros(len(reference))
    return SyncProposal(
        reference_id="sensor:ttl",
        target_id="cam.mp4",
        fit=SyncFit(
            offset=float(target[0] - reference[0]),
            drift_ppm=0.0,
            rms_residual=0.0,
            max_residual=0.0,
            matched_count=len(reference),
            rejected_count=len(rejected),
            reference_count=len(reference) + len(rejected),
            target_count=len(target),
        ),
        matches=tuple(
            SyncMatch(float(r), float(t), float(e))
            for r, t, e in zip(reference, target, residuals, strict=True)
        ),
        tolerance=0.25,
        unmatched_references=tuple(float(value) for value in rejected),
    )


def _view(qtbot) -> SyncEvidenceView:
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    return view


def _plotted_span(plot) -> tuple[float, float]:
    """The x and y extent of the scatter actually drawn on *plot*."""
    xs: list[float] = []
    ys: list[float] = []
    for item in plot.getPlotItem().listDataItems():
        x, y = item.getData()
        if x is None or len(x) < 3:  # the 1:1 guide has two points
            continue
        xs.extend(np.asarray(x, dtype=float))
        ys.extend(np.asarray(y, dtype=float))
    return (max(xs) - min(xs), max(ys) - min(ys))


class TestAWrongRateIsVisibleWhereAResidualIsNot:
    def test_a_matching_rate_draws_a_diagonal(self, qtbot) -> None:
        reference = np.arange(0.0, 240.0, 1.0) + 34540.0
        view = _view(qtbot)

        view.show_proposal(_proposal(reference, reference + 1.24))

        x_span, y_span = _plotted_span(view._pairing)
        assert y_span / x_span == pytest.approx(1.0, abs=0.05)

    def test_a_four_to_one_rate_draws_a_four_to_one_slope(self, qtbot) -> None:
        """The screenshot's fit. Its residuals were exactly zero."""
        reference = np.arange(0.0, 240.0, 1.0) + 34540.0
        view = _view(qtbot)

        view.show_proposal(_proposal(reference, reference * 4.35))

        x_span, y_span = _plotted_span(view._pairing)
        assert y_span / x_span == pytest.approx(4.35, rel=0.05)

    def test_the_residual_panel_says_nothing_about_it(self, qtbot) -> None:
        """Stated as a test so the limitation is not rediscovered."""
        reference = np.arange(0.0, 240.0, 1.0) + 34540.0
        view = _view(qtbot)

        view.show_proposal(_proposal(reference, reference * 4.35))

        assert "no remaining trend" in view._reading.text()


class TestWhatElseThePanelCarries:
    def test_rejected_evidence_is_drawn_where_it_sits_in_time(self, qtbot) -> None:
        """A quantity of ink, not a percentage in a clause at the bottom."""
        reference = np.arange(0.0, 100.0, 1.0) + 34540.0
        rejected = np.arange(0.5, 100.0, 1.0) + 34540.0
        view = _view(qtbot)

        view.show_proposal(_proposal(reference, reference + 1.0, rejected=rejected))

        drawn = sum(
            len(item.getData()[0])
            for item in view._pairing.getPlotItem().listDataItems()
            if item.getData()[0] is not None
        )
        assert drawn >= len(reference) + len(rejected)

    def test_a_one_to_one_guide_is_drawn_to_compare_against(self, qtbot) -> None:
        """Two axes at different scales make any straight line look like 45 degrees."""
        reference = np.arange(0.0, 50.0, 1.0) + 34540.0
        view = _view(qtbot)

        view.show_proposal(_proposal(reference, reference + 1.0))

        guides = [
            item
            for item in view._pairing.getPlotItem().listDataItems()
            if item.getData()[0] is not None and len(item.getData()[0]) == 2
        ]
        assert guides, "no 1:1 guide drawn"
        x, y = guides[0].getData()
        assert (y[1] - y[0]) == pytest.approx(x[1] - x[0])

    def test_the_two_panels_share_one_time_axis(self, qtbot) -> None:
        """A point picked out above is the same instant below it."""
        reference = np.arange(0.0, 100.0, 1.0) + 34540.0
        view = _view(qtbot)
        view.show_proposal(_proposal(reference, reference + 1.0))

        view._plot.getViewBox().setXRange(10.0, 20.0, padding=0)

        low, high = view._pairing.getViewBox().viewRange()[0]
        assert low == pytest.approx(10.0, abs=0.5)
        assert high == pytest.approx(20.0, abs=0.5)

    def test_clearing_empties_both_panels(self, qtbot) -> None:
        reference = np.arange(0.0, 50.0, 1.0) + 34540.0
        view = _view(qtbot)
        view.show_proposal(_proposal(reference, reference + 1.0))

        view.show_proposal(None)

        assert not view._pairing.getPlotItem().listDataItems()
        assert not view._plot.getPlotItem().listDataItems()


class TestInterrogatingAPoint:
    """A scatter nobody can question point by point is a picture of evidence."""

    def test_hovering_names_the_event_under_the_cursor(self, qtbot) -> None:
        reference = np.arange(0.0, 50.0, 1.0) + 34540.0
        view = _view(qtbot)
        view.resize(600, 400)
        view.show_proposal(_proposal(reference, reference + 1.0))

        box = view._plot.getViewBox()
        scene_pos = box.mapViewToScene(_point(10.0, 0.0))
        view._on_hover(scene_pos)

        assert "Event" in view._readout.text()
        assert "residual" in view._readout.text()

    def test_clicking_publishes_the_events_own_timestamp(self, qtbot) -> None:
        """The reference source's clock, not the master clock: the fit being
        judged has not been applied to anything yet."""
        reference = np.arange(0.0, 50.0, 1.0) + 34540.0
        view = _view(qtbot)
        view.resize(600, 400)
        view.show_proposal(_proposal(reference, reference + 1.0))

        seen: list[float] = []
        view.point_selected.connect(seen.append)
        box = view._plot.getViewBox()
        view._on_click(_FakeClick(box.mapViewToScene(_point(10.0, 0.0))))

        assert seen, "no point was published"
        assert seen[0] == pytest.approx(34550.0, abs=2.0)

    def test_hovering_outside_every_canvas_clears_the_readout(self, qtbot) -> None:
        reference = np.arange(0.0, 50.0, 1.0) + 34540.0
        view = _view(qtbot)
        view.resize(600, 400)
        view.show_proposal(_proposal(reference, reference + 1.0))

        view._on_hover(_point(-10_000.0, -10_000.0))

        assert view._readout.text() == ""

    def test_a_click_with_nothing_plotted_is_harmless(self, qtbot) -> None:
        view = _view(qtbot)
        view._on_click(_FakeClick(_point(0.0, 0.0)))


def _point(x: float, y: float):
    from PySide6.QtCore import QPointF

    return QPointF(x, y)


class _FakeClick:
    """The one method `_on_click` reads off a pyqtgraph mouse event."""

    def __init__(self, scene_pos) -> None:
        self._scene_pos = scene_pos

    def scenePos(self):
        return self._scene_pos
