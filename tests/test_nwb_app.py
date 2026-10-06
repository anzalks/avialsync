"""An NWB file opened in the running application, end to end (D-188).

The loaders are tested on their own elsewhere. This is what the user does: drop
one ``.nwb`` file on the window, accept the review, and get a video pane for the
imaging and plot rows for every series, on one clock -- then save the session
and get the same back.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog
from shiboken6 import isValid

pytest.importorskip("h5py")

from avialsync.core.session import SessionState  # noqa: E402
from avialsync.ui.batch_import_dialog import BatchImportDialog  # noqa: E402
from avialsync.ui.main_window import MainWindow  # noqa: E402
from tests.nwb_fixture import SESSION_EPOCH, write_nwb  # noqa: E402


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    if isValid(win):
        win.close()


@pytest.fixture
def accept_review(monkeypatch: pytest.MonkeyPatch) -> None:
    def accept(dialog: BatchImportDialog) -> int:
        QTimer.singleShot(0, dialog, dialog.accept)
        return QDialog.exec(dialog)

    monkeypatch.setattr(BatchImportDialog, "exec", accept)


def _imaging(path: Path) -> str:
    return str(path / "acquisition" / "TwoPhotonSeries")


def _wait_loaded(window: MainWindow, qtbot, path: Path) -> None:
    qtbot.waitUntil(lambda: _imaging(path) in window.video_grid.pane_paths(), timeout=20_000)
    qtbot.waitUntil(lambda: str(path) in window._sensor_cache_dirs, timeout=20_000)
    qtbot.waitUntil(lambda: window.video_grid.panes[0].has_media, timeout=20_000)


def test_dropping_an_nwb_file_shows_its_imaging_and_its_series(
    window: MainWindow, qtbot, tmp_path: Path, accept_review: None
) -> None:
    path = write_nwb(tmp_path / "session.nwb")

    window.open_path(path)
    _wait_loaded(window, qtbot, path)

    # Two sources, told apart: the imaging pane and the file's time series.
    assert window.video_grid.pane_paths() == [_imaging(path)]
    assert set(window._inspections) == {str(path), _imaging(path)}
    coverage = window.transport.overview._coverage
    assert coverage[_imaging(path)][2] == "video"
    assert coverage[str(path)][2] == "data"
    # Every series' rows, named by where they sit in the file.
    qtbot.waitUntil(lambda: len(window.plot_pane.channels) > 10, timeout=20_000)
    names = {channel.name for channel in window.plot_pane.channels}
    assert {"ElectricalSeries.ch10", "Position.SpatialSeries.x", "trials"} <= names
    # One clock: the file's own start time is the session's zero.
    assert window.session_start_time == pytest.approx(SESSION_EPOCH)
    # Trial rows and annotations reached the messages panel.
    assert len(window.message_store.messages()) >= 6


def test_an_nwb_session_saves_and_reopens(
    window: MainWindow, qtbot, tmp_path: Path, accept_review: None, qapp: QApplication
) -> None:
    path = write_nwb(tmp_path / "session.nwb")
    window.open_path(path)
    _wait_loaded(window, qtbot, path)

    state = window._build_session_state()
    saved = tmp_path / "nwb.avv"
    state.save(saved)

    reloaded = SessionState.load(saved)
    assert [video.path for video in reloaded.videos] == [_imaging(path)]
    assert [sensor.path for sensor in reloaded.sensors] == [str(path)]

    again = MainWindow()
    qtbot.addWidget(again)
    again.show()
    try:
        again._start_session_load(saved)
        _wait_loaded(again, qtbot, path)
        assert again.video_grid.pane_paths() == [_imaging(path)]
    finally:
        again.close()


def test_nudging_the_series_leaves_the_imaging_where_it_is(
    window: MainWindow, qtbot, tmp_path: Path, accept_review: None
) -> None:
    """Two sources from one file must not answer to each other's offset."""
    path = write_nwb(tmp_path / "session.nwb")
    window.open_path(path)
    _wait_loaded(window, qtbot, path)
    pane = window.video_grid.panes[0]
    before = pane.time_map.offset

    window._on_sensor_mapping_changed(str(path), 0.25, 0.0)
    qtbot.wait(50)

    assert pane.time_map.offset == before
    rows = [c for c in window.plot_pane.channels if c.name == "ElectricalSeries.ch10"]
    assert rows and rows[0].reader.time_map.offset == pytest.approx(0.25)


def test_imaging_frames_land_at_their_nwb_times(
    window: MainWindow, qtbot, tmp_path: Path, accept_review: None
) -> None:
    """The proxy's frame times are the file's, and the series' coverage is all of it."""
    path = write_nwb(tmp_path / "session.nwb")
    window.open_path(path)
    _wait_loaded(window, qtbot, path)
    coverage = window.transport.overview._coverage

    # Twelve frames at 30 Hz from 0.5 s, relative to the file's own start.
    assert coverage[_imaging(path)][:2] == pytest.approx((0.5, 0.9), abs=1e-3)
    assert window.video_grid.panes[0].time_map.offset == pytest.approx(0.0)
    # The last trial ends at 9 s: the series' span is every group's, not the first's.
    qtbot.waitUntil(lambda: coverage[str(path)][1] >= 9.0, timeout=20_000)
    assert coverage[str(path)][0] == pytest.approx(0.0, abs=1e-3)
