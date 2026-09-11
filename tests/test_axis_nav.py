"""Per-axis navigation: one gesture moves one axis, and reset goes somewhere declared."""

import numpy as np
import pyqtgraph as pg
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QGraphicsSceneWheelEvent

from avialsync.core.sync import SyncMatch, SyncProposal
from avialsync.core.timeline import TimeMap  # noqa: F401  (import guard for core headlessness)
from avialsync.ui.axis_nav import ZOOM_STEP, AxisNav, NavigableViewBox
from avialsync.ui.sync_evidence_view import SyncEvidenceView


def _nav(qtbot) -> tuple[AxisNav, pg.ViewBox, pg.PlotWidget]:
    """Build a bound nav strip, returning the plot so the caller keeps it alive.

    `qtbot.addWidget` holds its widgets weakly. A helper that let the
    `PlotWidget` fall out of scope would have its view box collected underneath
    the test, which surfaces as "Signal source has been deleted" from somewhere
    unrelated rather than as a lifetime error.
    """
    view_box = NavigableViewBox()
    plot = pg.PlotWidget(viewBox=view_box)
    view_box.setRange(xRange=(0.0, 100.0), yRange=(-10.0, 10.0), padding=0)
    nav = AxisNav(plot)
    qtbot.addWidget(nav)
    return nav, view_box, plot


def _span(view_box: pg.ViewBox, axis: int) -> float:
    low, high = view_box.viewRange()[axis]
    return float(high - low)


def test_zoom_moves_only_the_axis_asked_for(qtbot) -> None:
    """A press on the X controls must leave the residual scale alone."""
    nav, view_box, _plot = _nav(qtbot)
    x_before, y_before = _span(view_box, 0), _span(view_box, 1)

    nav.zoom("x", out=False)

    assert _span(view_box, 0) == pytest.approx(x_before / ZOOM_STEP, rel=1e-6)
    assert _span(view_box, 1) == pytest.approx(y_before, rel=1e-6)


def test_zoom_out_is_the_inverse_of_zoom_in(qtbot) -> None:
    """Two opposite presses return the view, so the gesture is not lossy."""
    nav, view_box, _plot = _nav(qtbot)
    before = _span(view_box, 1)

    nav.zoom("y", out=False)
    nav.zoom("y", out=True)

    assert _span(view_box, 1) == pytest.approx(before, rel=1e-6)


def test_reset_returns_to_the_declared_home_not_the_data(qtbot) -> None:
    """The whole point: reset goes where the owner said, not to auto-range."""
    nav, view_box, _plot = _nav(qtbot)
    nav.set_home_range((0.0, 500.0), (-2.0, 2.0))
    view_box.setRange(xRange=(10.0, 11.0), yRange=(-0.01, 0.01), padding=0)

    nav.reset_both()

    x_low, x_high = view_box.viewRange()[0]
    assert x_low <= 0.0 and x_high >= 500.0
    y_low, y_high = view_box.viewRange()[1]
    assert y_low <= -2.0 and y_high >= 2.0


def test_reset_without_a_home_range_does_not_raise(qtbot) -> None:
    """A view with nothing plotted still has to answer the button."""
    nav, view_box, _plot = _nav(qtbot)
    nav.set_home_range(None, None)
    nav.reset_both()


def test_degenerate_home_range_falls_back_instead_of_collapsing(qtbot) -> None:
    """A single-event fit spans nothing; the axis must not be set to a point."""
    nav, view_box, _plot = _nav(qtbot)
    nav.set_home_range((7.0, 7.0), (0.0, 0.0))
    nav.reset_both()
    assert _span(view_box, 0) > 0.0
    assert _span(view_box, 1) > 0.0


def _wheel(modifier: Qt.KeyboardModifier) -> QGraphicsSceneWheelEvent:
    """One notch forward, as pyqtgraph's scene actually delivers it."""
    event = QGraphicsSceneWheelEvent(QEvent.Type.GraphicsSceneWheel)
    event.setDelta(120)
    event.setModifiers(modifier)
    event.setScenePos(QPointF(0.0, 0.0))
    return event


def test_bare_wheel_is_time_only(qtbot) -> None:
    """The residual scale is the tolerance band; a scroll must not rescale it."""
    _, view_box, _plot = _nav(qtbot)
    y_before = _span(view_box, 1)

    view_box.wheelEvent(_wheel(Qt.KeyboardModifier.NoModifier))

    assert _span(view_box, 1) == pytest.approx(y_before, rel=1e-6)


def test_control_wheel_reaches_the_residual_axis(qtbot) -> None:
    """Y is still reachable -- it just needs to be asked for."""
    _, view_box, _plot = _nav(qtbot)
    x_before, y_before = _span(view_box, 0), _span(view_box, 1)

    view_box.wheelEvent(_wheel(Qt.KeyboardModifier.ControlModifier))

    assert _span(view_box, 1) != pytest.approx(y_before, rel=1e-6)
    assert _span(view_box, 0) == pytest.approx(x_before, rel=1e-6)


def test_shift_wheel_pans_without_zooming(qtbot) -> None:
    """Panning keeps the span and moves the window."""
    _, view_box, _plot = _nav(qtbot)
    span_before = _span(view_box, 0)
    low_before = view_box.viewRange()[0][0]

    view_box.wheelEvent(_wheel(Qt.KeyboardModifier.ShiftModifier))

    assert _span(view_box, 0) == pytest.approx(span_before, rel=1e-6)
    assert view_box.viewRange()[0][0] != pytest.approx(low_before, rel=1e-9)


def test_every_control_is_named_for_a_screen_reader(qtbot) -> None:
    """Rule 17: "−" alone is meaningless, and there are two of every button."""
    nav, _, _plot = _nav(qtbot)
    from PySide6.QtWidgets import QPushButton

    names = [b.accessibleName() for b in nav.findChildren(QPushButton)]
    assert len(names) == 7, f"three per axis plus fit-all, got {names}"
    assert all(names), "every button needs an accessible name"
    assert len(names) == len(set(names)), f"ambiguous control names: {names}"
    assert all(b.accessibleDescription() for b in nav.findChildren(QPushButton))


def test_each_group_stands_against_the_axis_it_moves(qtbot) -> None:
    """Position is what says which axis a control belongs to.

    The residual controls sit left of the canvas and the time controls below
    it, with fit-all in the corner where the two axes meet. A row of buttons
    under the plot would need captions to say the same thing.
    """
    nav, _, plot = _nav(qtbot)
    nav.resize(400, 300)
    nav.show()
    qtbot.waitExposed(nav)

    canvas = plot.geometry()
    from PySide6.QtWidgets import QPushButton

    boxes = {b.accessibleName(): b.geometry() for b in nav.findChildren(QPushButton)}
    residual = [g for name, g in boxes.items() if "residual" in name]
    time_axis = [g for name, g in boxes.items() if "time" in name]

    assert len(residual) == 3 and len(time_axis) == 3
    assert all(g.right() <= canvas.left() for g in residual), (
        "residual controls not beside the y axis"
    )
    assert all(g.top() >= canvas.bottom() for g in time_axis), "time controls not under the x axis"

    corner = next(g for name, g in boxes.items() if name == "Fit all")
    assert corner.right() <= canvas.left() and corner.top() >= canvas.bottom()


# ── the evidence view that uses it ───────────────────────────────────


def _proposal(matched: np.ndarray, unmatched: tuple[float, ...]) -> SyncProposal:
    from avialsync.core.sync import SyncFit

    return SyncProposal(
        reference_id="sensor:ttl",
        target_id="camera.mp4",
        fit=SyncFit(
            offset=1.0,
            drift_ppm=0.0,
            rms_residual=0.001,
            max_residual=0.002,
            matched_count=len(matched),
            rejected_count=len(unmatched),
        ),
        matches=tuple(SyncMatch(float(t), float(t) + 1.0, 0.001) for t in matched),
        tolerance=0.25,
        unmatched_references=unmatched,
    )


def test_home_range_covers_rejected_events_not_just_matched(qtbot) -> None:
    """A fit that matched a sliver must not open zoomed into that sliver."""
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    # Matched events huddle in a 50 s window; the rejected ones span an hour.
    matched = np.arange(3400.0, 3450.0, 1.0)
    unmatched = tuple(np.arange(0.0, 3600.0, 10.0))

    view.show_proposal(_proposal(matched, unmatched))

    x_low, x_high = view._plot.getViewBox().viewRange()[0]
    assert x_high - x_low > 3000.0, "the rejected evidence is off screen"


def test_axis_is_relative_to_the_first_event(qtbot) -> None:
    """Ticks read from zero; the absolute origin is stated in the label once."""
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    matched = np.arange(34540.0, 34590.0, 1.0)

    view.show_proposal(_proposal(matched, ()))

    x_low, _ = view._plot.getViewBox().viewRange()[0]
    assert abs(x_low) < 10.0, "axis still carries the absolute time base"
    label = view._plot.getPlotItem().getAxis("bottom").labelText
    assert "09:35:40" in label, f"origin not stated in the label: {label!r}"


def test_residual_axis_always_contains_the_tolerance_band(qtbot) -> None:
    """Without the band on screen the scatter has no scale."""
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    matched = np.arange(0.0, 20.0, 1.0)

    view.show_proposal(_proposal(matched, ()))

    y_low, y_high = view._plot.getViewBox().viewRange()[1]
    tolerance_ms = 0.25 * 1000.0
    assert y_low <= -tolerance_ms and y_high >= tolerance_ms


def test_developer_context_menu_is_not_offered(qtbot) -> None:
    """Downsample and Average would change the evidence being judged."""
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    assert view._plot.getPlotItem().vb.menu is None
