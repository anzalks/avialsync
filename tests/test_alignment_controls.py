"""The offset and drift controls must move a source, not stretch the session.

Reported as "the time aligning options push things too much in time or make
them disappear instead of moving them around": entering numbers in the sidebar
sent the timeline tens of thousands of seconds out and left the video panes
showing the "No Footage" placeholder.

Five defects in one path produced that, and each has a test here.

1. The master timeline was a running union that only ever grew. Moving a source
   back to where it started left the span it had passed through.
2. The spin boxes tracked the keyboard, so typing ``86400`` applied 8, 86, 864,
   8640 and 86400 -- five re-alignments, and with (1) the widest of them stuck.
3. A wall-clock source's placement against the session zero was handed to a
   spin box ranged at a day. It clamped to 86400 s in silence and the clamp was
   what the session saved (D-026).
4. That placement lived as a local inside `set_video_coverage`, so the pane's
   own TimeMap never received it and the first hand nudge replaced the whole
   mapping with the nudge -- five decades of jump, and no footage anywhere near
   the visible range.
5. A video offset edit ended in ``clock.play(); clock.pause()``, which notifies
   no subscriber, so the frame on screen stayed the one chosen under the old
   mapping.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from avialsync.core.pyramid import PyramidBuilder
from avialsync.ui.main_window import MainWindow
from avialsync.ui.sidebar import SensorInfoWidget

RATE_HZ = 100.0
COUNT = 2_000
DURATION_S = (COUNT - 1) / RATE_HZ
SENSOR = "/tmp/alignment-sensor.csv"
CAMERA = "/tmp/alignment-camera.mp4"

#: A plausible session start, well above `ABSOLUTE_EPOCH_FLOOR`.
EPOCH = 1_768_000_000.0


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    t = np.arange(COUNT, dtype=np.float64) / RATE_HZ
    PyramidBuilder(tmp_path, "a").build_and_save(t, t)
    return tmp_path


@pytest.fixture
def epoch_cache_dir(tmp_path: Path) -> Path:
    """A source whose cached samples carry wall-clock time, as `epoch_ms` does.

    Its own directory because PlotPane keys one TimeMap per cache directory:
    two sources sharing one would be moved by a single control.
    """
    other = tmp_path / "epoch"
    other.mkdir()
    t = EPOCH + np.arange(COUNT, dtype=np.float64) / RATE_HZ
    PyramidBuilder(other, "a").build_and_save(t, t)
    return other


@pytest.fixture
def window(qapp: QApplication, qtbot, cache_dir: Path) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win._on_import_finished(SENSOR, str(cache_dir), ["a"], (0.0, DURATION_S), None)
    return win


def _sensor(window: MainWindow) -> SensorInfoWidget:
    widget = window.sidebar.sensor_widget(SENSOR)
    assert widget is not None
    return widget


# ── 1. The timeline is derived, not accumulated ──────────────────────


def test_an_offset_moves_the_timeline_instead_of_growing_it(window: MainWindow) -> None:
    _sensor(window).offset_spin.setValue(5.0)

    start, end = window.clock.state.bounds
    assert (start, end) == pytest.approx((-5.0, DURATION_S - 5.0)), (
        "the span moved by the offset; it must not have grown by it"
    )


def test_putting_an_offset_back_puts_the_timeline_back(window: MainWindow) -> None:
    """The reported symptom in its simplest form."""
    original = window.clock.state.bounds

    _sensor(window).offset_spin.setValue(600.0)
    _sensor(window).offset_spin.setValue(0.0)

    assert window.clock.state.bounds == pytest.approx(original)


def test_removing_a_source_gives_back_the_span_it_claimed(
    window: MainWindow, cache_dir: Path
) -> None:
    other = "/tmp/alignment-far.csv"
    window._pending_sensor_mappings[other] = (-400.0, 0.0)
    window._on_import_finished(other, str(cache_dir), ["a"], (0.0, DURATION_S), None)
    assert window.clock.state.bounds[1] > 400.0

    window._on_sensor_remove_requested(other)

    assert window.clock.state.bounds == pytest.approx((0.0, DURATION_S))


def test_the_readout_is_not_moved_to_the_new_start(window: MainWindow, cache_dir: Path) -> None:
    """Bounds changing must not report a time the clock is not at."""
    window.player.seek(8.0, exact=True)

    _sensor(window).offset_spin.setValue(-30.0)

    from avialsync.ui.time_format import format_time

    shown = window.transport._time_edit.text()
    assert shown == format_time(window.clock.state.t, window.transport._time_mode, 0.0), (
        f"the transport reads {shown} while the clock is at {window.clock.state.t}"
    )


# ── 2. One commit per edit, not one per digit ────────────────────────


def test_typing_an_offset_applies_it_once(window: MainWindow, qtbot) -> None:
    applied: list[float] = []
    window.sidebar.sensor_mapping_changed.connect(lambda _p, offset, _d: applied.append(offset))
    spin = _sensor(window).offset_spin
    spin.setFocus()
    spin.selectAll()

    qtbot.keyClicks(spin, "86400")
    qtbot.keyClick(spin, Qt.Key.Key_Return)

    assert applied == [86400.0], (
        "every prefix of the typed number was applied as a separate alignment"
    )


def test_the_arrow_keys_still_commit_each_step(window: MainWindow, qtbot) -> None:
    """Turning off keyboard tracking must not cost the nudge gestures."""
    applied: list[float] = []
    window.sidebar.sensor_mapping_changed.connect(lambda _p, offset, _d: applied.append(offset))
    spin = _sensor(window).offset_spin
    spin.setFocus()

    qtbot.keyClick(spin, Qt.Key.Key_Up)

    assert applied == [pytest.approx(spin.singleStep())]


# ── 3. A placement is never clamped into a control ───────────────────


def test_a_wall_clock_placement_is_not_clamped_into_the_spin(qtbot) -> None:
    widget = SensorInfoWidget("/tmp/epoch.csv", ["a"])
    qtbot.addWidget(widget)

    widget.set_mapping(EPOCH, 0.0)

    assert widget.mapping()[0] == pytest.approx(EPOCH), (
        "the control substituted its own limit; a save would carry the substitute"
    )


def test_the_sidebar_shows_the_hand_correction_not_the_placement(
    window: MainWindow, epoch_cache_dir: Path
) -> None:
    """An `epoch_ms` source is placed at 1.77e9; the user's control shows 0."""
    epoch_sensor = "/tmp/epoch-sensor.csv"

    window._on_import_finished(
        epoch_sensor, str(epoch_cache_dir), ["a"], (EPOCH, EPOCH + DURATION_S), None
    )

    assert window.base_offset(epoch_sensor) == pytest.approx(EPOCH)
    assert window.sidebar.sensor_mapping(epoch_sensor)[0] == pytest.approx(0.0)
    assert window.clock.state.bounds == pytest.approx((0.0, DURATION_S)), (
        "a wall-clock source must land beside the recording, not 56 years from it"
    )


def test_the_session_stores_the_whole_mapping(window: MainWindow, epoch_cache_dir: Path) -> None:
    """What is saved must reopen at the same place, placement included."""
    epoch_sensor = "/tmp/epoch-saved.csv"
    window._on_import_finished(
        epoch_sensor, str(epoch_cache_dir), ["a"], (EPOCH, EPOCH + DURATION_S), None
    )
    window.sidebar.set_sensor_mapping(epoch_sensor, 1.5, 0.0)

    state = window._build_session_state()

    entry = next(s for s in state.sensors if s.path == epoch_sensor)
    assert entry.offset == pytest.approx(EPOCH + 1.5)


# ── 4. A hand nudge is a nudge, not a new mapping ────────────────────


def test_a_nudge_does_not_replace_a_wall_clock_placement(window: MainWindow) -> None:
    window.adopt_session_start(EPOCH)
    window._set_video_coverage(CAMERA, (EPOCH, EPOCH + 20.0), 0.0, 0.0)

    window._on_video_offset_changed(CAMERA, 2.0)

    assert window._video_time_mappings[CAMERA][0] == pytest.approx(EPOCH + 2.0)
    assert window.transport.overview._coverage[CAMERA][:2] == pytest.approx((-2.0, 18.0)), (
        "a two-second nudge moved the camera by two seconds, not by an epoch"
    )


def test_a_wall_clock_camera_reaches_its_pane_already_placed(
    window: MainWindow, qtbot, monkeypatch
) -> None:
    """The pane decodes in source time, so it needs the placement, not zero."""
    from unittest.mock import MagicMock

    from avialsync.loaders.video_standard import VideoStandardLoader

    loader = VideoStandardLoader()
    loader._codec = "h264"
    loader._duration = 20.0
    loader._fps = 30.0
    loader._file_size = 1234
    monkeypatch.setattr(loader, "time_bounds", lambda: (EPOCH, EPOCH + 20.0))
    monkeypatch.setattr(loader, "frame_times", lambda: None)
    applied: list[tuple[str, float, float]] = []
    monkeypatch.setattr(
        window.video_grid,
        "set_sync_mapping",
        lambda path, offset, drift, *_a: applied.append((path, offset, drift)),
    )
    monkeypatch.setattr(window.video_grid, "add_pane", lambda *_a, **_k: MagicMock())
    monkeypatch.setattr(window.sidebar, "set_video_pane", lambda *_a: None)

    window._on_video_opened(CAMERA, loader, CAMERA)

    assert applied and applied[0][1] == pytest.approx(EPOCH), (
        "the pane was left mapping master zero onto a frame stamped 1.77e9"
    )


def test_undo_of_a_nudge_returns_the_placement(window: MainWindow) -> None:
    window.adopt_session_start(EPOCH)
    window._set_video_coverage(CAMERA, (EPOCH, EPOCH + 20.0), 0.0, 0.0)

    window._on_video_offset_changed(CAMERA, 2.0)
    window._on_video_offset_changed(CAMERA, 0.0)

    assert window._video_time_mappings[CAMERA][0] == pytest.approx(EPOCH)


# ── 5. Moving a source redraws it ────────────────────────────────────


def test_changing_a_video_offset_redecodes_the_current_frame(
    window: MainWindow, monkeypatch
) -> None:
    window._set_video_coverage(CAMERA, (0.0, 20.0), 0.0, 0.0)
    seeks: list[tuple[float, bool]] = []
    monkeypatch.setattr(window.player, "seek", lambda t, exact=False: seeks.append((t, exact)))

    window._on_video_offset_changed(CAMERA, 3.0)

    assert seeks == [(window.clock.state.t, True)], (
        "nothing was notified, so the pane kept the frame chosen under the old mapping"
    )
