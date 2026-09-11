"""One declared zero, reaching the window and the clocks that display it.

`core/session_time.py` decides the arithmetic; these cover what the window does
with it. Both halves were broken in the same way -- by nobody ever declaring a
reference -- and they failed differently: a fifty-four-year timeline in one
case, and two menu options that quietly did nothing in the other.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.ui.main_window import MainWindow
from avialsync.ui.time_format import TimeDisplayMode, format_time

#: 2026-01-09T23:06:40Z, chosen so the formatted result is checkable by eye.
EPOCH = 1_768_000_000.0


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    if isValid(win):
        win.close()


class TestDeclaringTheZero:
    def test_a_session_starts_without_a_wall_clock(self, window: MainWindow) -> None:
        """Honest: nothing has claimed to know when this recording happened."""
        assert window.session_start_time == 0.0

    def test_the_first_absolute_source_declares_it(self, window: MainWindow) -> None:
        assert window.adopt_session_start(EPOCH) == pytest.approx(EPOCH)
        assert window.session_start_time == pytest.approx(EPOCH)

    def test_a_container_relative_source_declares_nothing(self, window: MainWindow) -> None:
        window.adopt_session_start(0.0)
        assert window.session_start_time == 0.0

    def test_a_second_source_never_moves_it(self, window: MainWindow) -> None:
        """A reference that moved would renumber what the user wrote down."""
        window.adopt_session_start(EPOCH)
        window.adopt_session_start(EPOCH - 3600.0)
        assert window.session_start_time == pytest.approx(EPOCH)


class TestTheDisplayModesThatCouldNotWork:
    """`format_time` always took an epoch, and nothing ever passed one.

    So UTC and local time-of-day fell through to elapsed time for every
    session, on a menu that has offered all three since D-020.
    """

    def test_utc_is_elapsed_time_until_a_reference_exists(self) -> None:
        assert format_time(65.0, TimeDisplayMode.UTC, 0.0) == format_time(
            65.0, TimeDisplayMode.RELATIVE, 0.0
        )

    def test_declaring_a_reference_reaches_the_transport(self, window: MainWindow) -> None:
        window.adopt_session_start(EPOCH)
        assert window.transport._t_epoch == pytest.approx(EPOCH)

    def test_it_reaches_every_surface_that_prints_a_time(self, window: MainWindow) -> None:
        window.adopt_session_start(EPOCH)
        assert window.plot_pane._t_epoch == pytest.approx(EPOCH)
        assert window.message_panel._t_epoch == pytest.approx(EPOCH)
        assert window.changes_panel._t_epoch == pytest.approx(EPOCH)

    def test_changing_mode_does_not_drop_the_reference(self, window: MainWindow) -> None:
        """Each surface takes the epoch as a defaulted argument, so a mode
        change that passed only the mode would reset them to elapsed time."""
        window.adopt_session_start(EPOCH)
        window._set_time_mode(TimeDisplayMode.UTC)
        assert window.plot_pane._t_epoch == pytest.approx(EPOCH)
        assert window.message_panel._t_epoch == pytest.approx(EPOCH)

    def test_with_a_reference_utc_is_a_wall_clock(self) -> None:
        assert format_time(0.0, TimeDisplayMode.UTC, EPOCH) == "23:06:40.000 UTC"
        assert format_time(65.0, TimeDisplayMode.UTC, EPOCH) == "23:07:45.000 UTC"


class TestTheFiftyFourYearTimeline:
    def test_an_epoch_source_and_a_container_source_share_a_span(self, window: MainWindow) -> None:
        """The bug in the shape it took: bounds are a union of both sources.

        Before the reference existed, a video at [0, 300] beside an `epoch_ms`
        CSV at [1.7e9, 1.7e9+300] produced a master timeline running from 0 to
        1.7e9 -- two five-minute islands fifty-four years apart, with a scrub
        bar spanning the gap.
        """
        from avialsync.core.session_time import rebase_offset
        from avialsync.core.timeline import TimeMap

        reference = window.adopt_session_start(EPOCH)

        sensor = TimeMap(offset=rebase_offset(EPOCH, reference))
        video = TimeMap(offset=rebase_offset(0.0, reference))

        sensor_span = (sensor.to_master(EPOCH), sensor.to_master(EPOCH + 300.0))
        video_span = (video.to_master(0.0), video.to_master(300.0))

        assert sensor_span == pytest.approx(video_span)
        union = (min(sensor_span[0], video_span[0]), max(sensor_span[1], video_span[1]))
        assert union[1] - union[0] == pytest.approx(300.0)


class TestItSurvivesTheSession:
    def test_the_reference_round_trips(self, tmp_path) -> None:
        from avialsync.core.session import SessionState

        out = tmp_path / "dated.avv"
        SessionState(session_start_time=EPOCH).save(out)

        assert SessionState.load(out).session_start_time == pytest.approx(EPOCH)

    def test_a_session_without_one_reads_back_as_relative(self, tmp_path) -> None:
        import json

        from avialsync.core.session import SessionState

        path = tmp_path / "undated.avv"
        path.write_text(json.dumps({"version": 8, "videos": [], "sensors": []}), encoding="utf-8")

        assert SessionState.load(path).session_start_time == 0.0
