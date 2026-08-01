"""The window always finishes closing, and the playhead keys always reach it.

Two reported defects, plus a third found while reproducing them:

1. **The window sometimes would not close.** ``closeEvent`` ran seven teardown
   steps in bare sequence. A raise in any of them skipped the rest — including
   ``video_grid.shutdown()``, whose libmpv event threads outlive their widgets
   and keep the process alive.
2. **Playhead keys stopped working after some operations.** Qt offers each key
   to the focused widget as a ``ShortcutOverride`` before running a window
   shortcut, and ``QLineEdit``/``QAbstractSpinBox`` accept that offer for Space,
   the arrows, Home and End.
3. **The final autosave wrote a session with no videos**, because it ran after
   the grid that holds them had already been cleared.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QLineEdit,
    QVBoxLayout,
)

from avialview.ui.main_window import MainWindow

_VIDEO = "tests/fixtures/videos/camera_1.mp4"


@pytest.fixture
def window(qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    return win


def _playhead_events(window: MainWindow) -> list[str]:
    """Record every command that actually reached the playhead."""
    seen: list[str] = []
    window.transport.play_toggled.connect(lambda _v: seen.append("play"))
    window.transport.frame_step_requested.connect(lambda _d: seen.append("step"))
    window.clock.subscribe(lambda _t: seen.append("seek"))
    return seen


def _press(app: QApplication, key: Qt.Key) -> None:
    """Send *key* the way real input does — to whatever currently has focus."""
    QTest.keyClick(app.focusWidget(), key)
    app.processEvents()


# ── Playhead keys ─────────────────────────────────────────────────────

PLAYHEAD_KEYS = [
    Qt.Key.Key_Space,
    Qt.Key.Key_Left,
    Qt.Key.Key_Right,
    Qt.Key.Key_Home,
    Qt.Key.Key_End,
]


@pytest.mark.parametrize("key", PLAYHEAD_KEYS)
def test_a_spin_box_does_not_swallow_the_playhead_keys(window, qapp, key) -> None:
    """One click into the sweep-length spin box used to disable playback control."""
    spin = window.findChildren(QDoubleSpinBox)[0]
    spin.setFocus(Qt.FocusReason.MouseFocusReason)
    qapp.processEvents()
    seen = _playhead_events(window)

    _press(qapp, key)

    assert seen, f"{key} never reached the playhead from a focused spin box"


@pytest.mark.parametrize("key", PLAYHEAD_KEYS)
def test_the_time_field_does_not_swallow_the_playhead_keys(window, qapp, key) -> None:
    """Merely holding focus is not an edit in progress."""
    window.transport._time_edit.setFocus(Qt.FocusReason.MouseFocusReason)
    window.transport._time_edit.setModified(False)
    qapp.processEvents()
    seen = _playhead_events(window)

    _press(qapp, key)

    assert seen, f"{key} never reached the playhead from the idle time field"


def test_a_half_typed_timecode_keeps_its_caret_keys(window, qapp) -> None:
    """Correcting a timecode mid-entry must still work."""
    edit = window.transport._time_edit
    edit.setFocus(Qt.FocusReason.MouseFocusReason)
    QTest.keyClicks(edit, "00:01:2")
    qapp.processEvents()
    seen = _playhead_events(window)

    _press(qapp, Qt.Key.Key_Left)

    assert not seen, "the caret keys belong to an edit in progress"


def test_space_is_never_taken_by_a_numeric_editor(window, qapp) -> None:
    """No timecode or number contains a space, so Space is always playback."""
    edit = window.transport._time_edit
    edit.setFocus(Qt.FocusReason.MouseFocusReason)
    QTest.keyClicks(edit, "00:01:2")
    qapp.processEvents()
    seen = _playhead_events(window)

    _press(qapp, Qt.Key.Key_Space)

    assert seen, "Space must reach the playhead even mid-edit"


def test_a_dialogs_own_editors_keep_their_keys(window, qapp, qtbot) -> None:
    """The reservation is scoped to the main window, never reaching into a dialog."""
    dialog = QDialog(window)
    layout = QVBoxLayout(dialog)
    field = QLineEdit(dialog)
    layout.addWidget(field)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    field.setFocus(Qt.FocusReason.MouseFocusReason)
    qapp.processEvents()
    seen = _playhead_events(window)

    _press(qapp, Qt.Key.Key_Left)

    assert not seen, "a dialog's editor owns its own keys"
    dialog.close()


# ── Closing ───────────────────────────────────────────────────────────


def test_the_final_autosave_still_sees_the_open_videos(window, tmp_path: Path) -> None:
    """The grid used to be torn down before the session state was built."""
    window.video_grid.add_pane(_VIDEO)
    session = tmp_path / "session.avv"
    window._session_path = session

    window.close()

    saved = json.loads(session.read_text())
    assert len(saved["videos"]) == 1, "closing wiped the session's video list"


def test_a_failing_teardown_step_does_not_skip_the_rest(window, monkeypatch) -> None:
    """A raise used to abandon every later step, stranding libmpv event threads."""
    monkeypatch.setattr(
        window._heartbeat, "stop", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    shut_down: list[str] = []
    monkeypatch.setattr(window.video_grid, "shutdown", lambda: shut_down.append("video_grid"))

    window.close()

    assert shut_down == ["video_grid"], "video teardown must run even after a failure"


def test_one_bad_pane_does_not_strand_the_others(window, monkeypatch) -> None:
    """Per-pane isolation: pane 0 failing must not leave pane 1 running.

    The real libmpv clients are terminated first and the panes replaced by
    stand-ins. Stubbing ``close`` on a live pane would leave its event thread
    running past the end of the test, which aborts the interpreter.
    """
    window.video_grid.add_pane(_VIDEO)
    window.video_grid.add_pane(_VIDEO)
    for pane in window.video_grid.panes:
        pane.close()

    closed: list[str] = []

    class _Pane:
        def __init__(self, name: str, fails: bool) -> None:
            self._name, self._fails = name, fails

        def close(self) -> bool:
            if self._fails:
                raise RuntimeError("GL context already gone")
            closed.append(self._name)
            return True

        def deleteLater(self) -> None:
            pass

    window.video_grid.panes = [_Pane("first", True), _Pane("second", False)]

    window.video_grid.shutdown()

    assert closed == ["second"], "a failing pane must not skip the ones after it"
    assert window.video_grid.panes == []


def test_closing_is_never_refused(window) -> None:
    """Whatever happens, the close event is accepted."""
    window.video_grid.add_pane(_VIDEO)

    window.close()

    assert window.isHidden()


# ── Loading must not take the UI thread away ──────────────────────────


def _pyramid_channels(tmp_path: Path, count: int) -> Path:
    """Build *count* cheap channels in one cache directory."""
    import numpy as np

    from avialview.core.pyramid import PyramidBuilder

    cache = tmp_path / "many.avialcache"
    cache.mkdir(parents=True, exist_ok=True)
    times = np.linspace(0.0, 10.0, 2_000)
    for index in range(count):
        PyramidBuilder(cache, f"ch{index}").build_and_save(times, np.sin(times * (index + 1)))
    return cache


def test_a_large_load_does_not_build_every_row_at_once(window, tmp_path) -> None:
    """Row construction is ~10 ms each; 32 in one call is a third of a second frozen."""
    cache = _pyramid_channels(tmp_path, 32)

    window.plot_pane.load_channels(cache, [f"ch{i}" for i in range(32)])

    assert window.plot_pane._pending_rows, "the whole selection was built in one blocking call"
    assert window.plot_pane.channels, "the first slice must still appear immediately"


def test_the_playhead_still_answers_while_rows_are_being_built(window, qapp, tmp_path) -> None:
    """The window must stay usable during a load, not go white."""
    cache = _pyramid_channels(tmp_path, 32)
    window.plot_pane.load_channels(cache, [f"ch{i}" for i in range(32)])
    assert window.plot_pane._pending_rows
    seen = _playhead_events(window)

    qapp.processEvents()
    _press(qapp, Qt.Key.Key_Space)

    assert seen, "playback control was unavailable mid-load"


def test_closing_mid_load_is_accepted_and_abandons_the_queue(window, tmp_path) -> None:
    """A close must never wait for row construction it no longer needs."""
    cache = _pyramid_channels(tmp_path, 32)
    window.plot_pane.load_channels(cache, [f"ch{i}" for i in range(32)])
    assert window.plot_pane._pending_rows

    window.close()

    assert window.isHidden()
    assert window.plot_pane._pending_rows == []


def test_every_row_lands_on_the_shared_window(qtbot, tmp_path) -> None:
    """A row built in a later slice used to keep a default X range.

    An X link only propagates on a *change* of the master's range, so rows
    linked afterwards were left mis-scaled against the rows already on screen.
    The pane is given a real size: pyqtgraph maps a link through view geometry,
    and an unsized offscreen viewport produces meaningless ranges.
    """
    from avialview.ui.plot_pane import PlotPane

    cache = _pyramid_channels(tmp_path, 8)
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(900, 500)
    pane.set_timeline_bounds(0.0, 10.0)

    pane.load_channels(cache, [f"ch{i}" for i in range(8)])
    assert pane._pending_rows, "this test is only meaningful across several slices"
    pane.wait_for_pending_rows()
    pane.set_window_duration(2.5)

    ranges = [tuple(ch.plot_item.viewRange()[0]) for ch in pane.channels]

    assert len(ranges) == 8
    for observed in ranges[1:]:
        assert observed == pytest.approx(ranges[0])


def test_completion_does_not_ride_on_the_tail_of_a_slice(qtbot, tmp_path) -> None:
    """Finishing a load is its own event-loop turn.

    `_finish_loading` costs ~19 ms. Running it directly from the last slice made
    one block out of two and was most of what kept the worst case near 90 ms.
    """
    from avialview.ui.plot_pane import PlotPane

    cache = _pyramid_channels(tmp_path, 8)
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(900, 500)
    pane.set_timeline_bounds(0.0, 10.0)

    finished: list[int] = []
    pane.channels_loaded.connect(lambda: finished.append(1))
    pane.load_channels(cache, [f"ch{i}" for i in range(8)])

    # Drain only the row-building turns; completion must still be outstanding.
    while pane._pending_rows:
        qtbot.wait(1)
    assert finished == [], "completion ran inside the final build slice"

    qtbot.waitUntil(lambda: finished == [1], timeout=2000)


def test_a_slice_stops_before_a_row_would_overrun_it(qtbot, tmp_path, monkeypatch) -> None:
    """The budget is checked before the next row, not after one already overran.

    Checking afterwards let a slice run to roughly twice its budget whenever a
    row started just under the deadline.
    """
    from avialview.ui import plot_pane as plot_pane_module

    cache = _pyramid_channels(tmp_path, 12)
    pane = plot_pane_module.PlotPane()
    qtbot.addWidget(pane)
    pane.resize(900, 500)
    pane.set_timeline_bounds(0.0, 10.0)

    # A row that costs the entire budget: exactly one may be built per slice.
    real_create = plot_pane_module.create_channel_plot

    def slow_create(*args, **kwargs):
        result = real_create(*args, **kwargs)
        time.sleep(plot_pane_module._ROW_BUILD_SLICE_S)
        return result

    monkeypatch.setattr(plot_pane_module, "create_channel_plot", slow_create)

    pane.load_channels(cache, [f"ch{i}" for i in range(12)])

    assert len(pane.channels) == 1, (
        f"a slice built {len(pane.channels)} rows when each one costs the whole budget"
    )
