"""Alignment: the evidence, the menu, and nudging by a frame (WP-10).

BLUEPRINT principle 8 asks that alignment "presents the matched evidence,
offset/drift fit, residuals, and confidence before the user accepts it". What
it presented was four numbers. Those are a summary: they cannot show whether
residuals drift across the recording, whether rejections cluster at one end, or
whether the fit rests on a handful of extremes.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from avialsync.core.sync import SyncFit, SyncMatch, SyncProposal
from avialsync.ui import recovery
from avialsync.ui.main_window import MainWindow
from avialsync.ui.sync_evidence_view import (
    MAX_PLOTTED_POINTS,
    SyncEvidenceView,
    decimate_residuals,
)


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    # Qt may already have deleted it: pytest-qt runs processEvents()
    # after the call phase, which executes pending deleteLater()s.
    if isValid(win):
        win.close()


class _StubPane(QWidget):
    def __init__(self) -> None:
        super().__init__()
        from avialsync.core.timeline import TimeMap

        self.time_map = TimeMap()

    has_media = False

    def has_footage_at_master(self, t: float) -> bool:  # pragma: no cover - stub
        return True

    def set_has_footage(self, has: bool) -> None:  # pragma: no cover - stub
        pass


def _proposal(matched: int = 20, rejected: tuple[float, ...] = (), trend: float = 0.0):
    matches = tuple(
        SyncMatch(
            reference_time=float(i),
            target_time=float(i) + 1.0,
            residual=0.001 + trend * i,
        )
        for i in range(matched)
    )
    residuals = [m.residual for m in matches] or [0.0]
    return SyncProposal(
        reference_id="/tmp/ephys.csv",
        target_id="/tmp/cam1.mp4",
        fit=SyncFit(
            offset=1.0,
            drift_ppm=12.0,
            rms_residual=float(np.sqrt(np.mean(np.square(residuals)))),
            max_residual=max(abs(r) for r in residuals),
            matched_count=matched,
            rejected_count=len(rejected),
        ),
        matches=matches,
        tolerance=0.005,
        unmatched_references=rejected,
    )


# ── decimation keeps what matters ────────────────────────────────────


def test_small_sets_are_left_alone() -> None:
    times = np.arange(10, dtype=float)
    residuals = np.arange(10, dtype=float)
    out_times, out_residuals = decimate_residuals(times, residuals)
    assert len(out_times) == 10
    assert np.array_equal(out_residuals, residuals)


def test_large_sets_are_reduced() -> None:
    """A 50 kHz TTL channel can match tens of thousands of events."""
    times = np.arange(50_000, dtype=float)
    residuals = np.random.default_rng(0).normal(size=50_000)
    out_times, _ = decimate_residuals(times, residuals)
    assert len(out_times) <= MAX_PLOTTED_POINTS


def test_the_worst_residual_survives_decimation() -> None:
    """A plain stride would drop the worst point as readily as a typical one."""
    times = np.arange(10_000, dtype=float)
    residuals = np.zeros(10_000)
    residuals[7_321] = 99.0  # the one point a reader is looking for

    _out_times, out_residuals = decimate_residuals(times, residuals)
    assert out_residuals.max() == 99.0


def test_a_large_negative_residual_also_survives() -> None:
    times = np.arange(10_000, dtype=float)
    residuals = np.zeros(10_000)
    residuals[500] = -99.0
    _out, out_residuals = decimate_residuals(times, residuals)
    assert out_residuals.min() == -99.0


def test_an_empty_set_is_handled() -> None:
    out_times, out_residuals = decimate_residuals(np.array([]), np.array([]))
    assert len(out_times) == 0
    assert len(out_residuals) == 0


# ── the view ─────────────────────────────────────────────────────────


def test_it_starts_empty(qapp: QApplication, qtbot) -> None:
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    assert "No alignment" in view._headline.text()


def test_showing_none_clears_it(qapp: QApplication, qtbot) -> None:
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    view.show_proposal(_proposal())
    view.show_proposal(None)
    assert "No alignment" in view._headline.text()


def test_the_headline_carries_the_numbers(qapp: QApplication, qtbot) -> None:
    """The summary is kept -- it is the header, not the whole evidence."""
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    view.show_proposal(_proposal(matched=47))
    text = view._headline.text()
    assert "47 matched" in text
    assert "offset" in text and "drift" in text and "RMS" in text


def test_a_trend_in_the_residuals_is_reported(qapp: QApplication, qtbot) -> None:
    """The thing an average cannot show: timing the fit did not absorb."""
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    view.show_proposal(_proposal(matched=40, trend=0.0005))
    assert "trend" in view._reading.text().lower()


def test_an_even_scatter_is_reported_as_even(qapp: QApplication, qtbot) -> None:
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    view.show_proposal(_proposal(matched=40, trend=0.0))
    assert "evenly" in view._reading.text().lower()


def test_rejections_are_counted_in_words(qapp: QApplication, qtbot) -> None:
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    view.show_proposal(_proposal(matched=18, rejected=(1.0, 2.0)))
    assert "found no partner" in view._reading.text()


def test_a_thin_fit_is_called_out(qapp: QApplication, qtbot) -> None:
    """An offset from five events is moved by one bad one."""
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    view.show_proposal(_proposal(matched=5))
    assert "few matches" in view._reading.text().lower()


def test_a_proposal_with_no_retained_matches_says_so(qapp: QApplication, qtbot) -> None:
    """Evidence is bounded; a large fit keeps only a sample of its matches."""
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    view.show_proposal(_proposal(matched=0))
    assert "nothing to plot" in view._reading.text()


def test_the_reading_is_the_accessible_description(qapp: QApplication, qtbot) -> None:
    """A scatter plot is invisible to a screen reader; the shape is the point."""
    view = SyncEvidenceView()
    qtbot.addWidget(view)
    view.show_proposal(_proposal(matched=40))
    assert view._reading.text()
    assert view.accessibleName()


# ── the menu ─────────────────────────────────────────────────────────


def test_alignment_has_its_own_menu(window: MainWindow) -> None:
    """It is not a file operation; it is the reason the application exists."""
    titles = [action.text() for action in window.menuBar().actions()]
    assert "Align" in titles


def test_the_file_menu_no_longer_owns_it(window: MainWindow) -> None:
    for action in window.menuBar().actions():
        if action.text() != "File":
            continue
        labels = [entry.text() for entry in action.menu().actions()]
        assert not any("Synchronize" in label for label in labels)
        return
    pytest.fail("no File menu")


def test_the_align_menu_offers_nudging(window: MainWindow) -> None:
    labels = [action.text() for action in window._align_menu.actions()]
    assert any("earlier" in label for label in labels)
    assert any("later" in label for label in labels)


# ── nudging by a frame ───────────────────────────────────────────────


def _fake_video(window: MainWindow, path: str = "/tmp/cam1.mp4", fps: float = 230.0) -> str:
    window.sidebar.add_video(path, {})
    window.video_grid.panes.append(_StubPane())
    window.video_grid._paths.append(path)
    window.video_grid._pane_enabled.append(True)
    window._video_fps[path] = fps
    return path


def test_a_nudge_moves_by_one_frame(window: MainWindow) -> None:
    """The spin box stepped 0.05 s -- more than a frame at any targeted rate."""
    path = _fake_video(window, fps=230.0)
    window._nudge_alignment(+1)
    assert window.sidebar.video_offset(path) == pytest.approx(1.0 / 230.0, abs=1e-6)


def test_nudging_both_ways_returns_to_where_it_started(window: MainWindow) -> None:
    path = _fake_video(window)
    window._nudge_alignment(+1)
    window._nudge_alignment(-1)
    assert window.sidebar.video_offset(path) == pytest.approx(0.0, abs=1e-9)


def test_a_nudge_is_undoable(window: MainWindow) -> None:
    path = _fake_video(window)
    window.document.clear()
    window._nudge_alignment(+1)
    window.document.undo(window._mutations)
    assert window.sidebar.video_offset(path) == pytest.approx(0.0, abs=1e-9)


def test_nudging_with_no_video_says_so(window: MainWindow) -> None:
    window._nudge_alignment(+1)
    assert "video" in window.notifications.message.lower()


def test_a_source_without_a_rate_still_nudges(window: MainWindow) -> None:
    """Falls back to a millisecond rather than dividing by zero."""
    path = _fake_video(window, fps=0.0)
    window._nudge_alignment(+1)
    assert window.sidebar.video_offset(path) == pytest.approx(0.001, abs=1e-9)


# ── the confidence readout ───────────────────────────────────────────


def test_an_unaligned_source_says_so(window: MainWindow) -> None:
    assert window.alignment_confidence("/tmp/cam1.mp4") == "no accepted alignment"


def test_an_aligned_source_reports_its_evidence(window: MainWindow) -> None:
    """Persistent, and derived from what was actually accepted."""
    from avialsync.core.session import SyncProvenance

    window._sync_provenance.append(
        SyncProvenance(
            reference_id="/tmp/ephys.csv",
            target_id="/tmp/cam1.mp4",
            offset=1.0,
            drift_ppm=0.0,
            rms_residual=0.001,
            max_residual=0.003,
            matched_count=47,
            rejected_count=1,
            tolerance=0.005,
        )
    )
    text = window.alignment_confidence("/tmp/cam1.mp4")
    assert "47 events" in text
    assert "3.0 ms" in text


# ── which camera a nudge moves (the multi-camera bug) ────────────────


def test_a_single_camera_needs_no_selection(window: MainWindow) -> None:
    path = _fake_video(window, "/tmp/only.mp4")
    assert window._focused_video_path() == path


def test_several_cameras_with_no_selection_pick_none(window: MainWindow) -> None:
    """It used to return the first, so every nudge moved FaceCam silently."""
    _fake_video(window, "/tmp/cam1.mp4")
    _fake_video(window, "/tmp/cam2.mp4")
    _fake_video(window, "/tmp/cam3.mp4")
    assert window._focused_video_path() is None


def test_nudging_several_cameras_asks_rather_than_guessing(window: MainWindow) -> None:
    _fake_video(window, "/tmp/cam1.mp4")
    _fake_video(window, "/tmp/cam2.mp4")

    window._nudge_alignment(+1)

    assert "click the camera" in window.notifications.message.lower()
    assert window.sidebar.video_offset("/tmp/cam1.mp4") == pytest.approx(0.0)


def test_selecting_a_camera_makes_the_nudge_target_it(window: MainWindow) -> None:
    _fake_video(window, "/tmp/cam1.mp4")
    second = _fake_video(window, "/tmp/cam2.mp4")

    window._select_video(second)
    window._nudge_alignment(+1)

    assert window.sidebar.video_offset(second) > 0
    assert window.sidebar.video_offset("/tmp/cam1.mp4") == pytest.approx(0.0)


def test_touching_a_cameras_offset_selects_it(window: MainWindow) -> None:
    """Changing an offset means "this one" as clearly as any selection gesture."""
    _fake_video(window, "/tmp/cam1.mp4")
    second = _fake_video(window, "/tmp/cam2.mp4")

    window._select_video(second)
    window._nudge_alignment(-1)

    assert window.sidebar.video_offset(second) < 0


def test_selecting_an_unloaded_camera_is_ignored(window: MainWindow) -> None:
    _fake_video(window, "/tmp/cam1.mp4")
    _fake_video(window, "/tmp/cam2.mp4")
    window._select_video("/tmp/never_loaded.mp4")
    assert window._focused_video_path() is None


def test_a_removed_camera_stops_being_the_target(window: MainWindow) -> None:
    """A stale selection must not silently redirect a later nudge."""
    _fake_video(window, "/tmp/cam1.mp4")
    second = _fake_video(window, "/tmp/cam2.mp4")
    window._select_video(second)

    window.video_grid._paths.remove(second)
    window.video_grid.panes.pop()

    assert window._focused_video_path() == "/tmp/cam1.mp4", "one left, so no ambiguity"
