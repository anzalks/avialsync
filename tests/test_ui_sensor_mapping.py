"""Sensor offset/drift editing in the sidebar re-aligns plots without reimporting."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from avialview.core.pyramid import PyramidBuilder
from avialview.ui.main_window import MainWindow
from avialview.ui.sidebar import SensorInfoWidget

RATE_HZ = 100.0
COUNT = 2_000
SENSOR_PATH = "/tmp/fixture-sensor.csv"


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    t = np.arange(COUNT, dtype=np.float64) / RATE_HZ
    for name in ("a", "b"):
        PyramidBuilder(tmp_path, name).build_and_save(t, t)
    return tmp_path


@pytest.fixture
def window(qapp: QApplication, qtbot, cache_dir: Path) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win._on_import_finished(
        SENSOR_PATH,
        str(cache_dir),
        ["a", "b"],
        (0.0, (COUNT - 1) / RATE_HZ),
        None,
    )
    yield win
    win.close()


def _sensor_widget(window: MainWindow) -> SensorInfoWidget:
    widget = window.sidebar.sensor_widget(SENSOR_PATH)
    assert widget is not None
    return widget


def test_sidebar_offers_offset_and_drift_for_a_sensor(window: MainWindow) -> None:
    widget = _sensor_widget(window)
    assert widget.offset_spin.suffix() == " s"
    assert widget.drift_spin.suffix() == " ppm"
    assert widget.mapping() == (0.0, 0.0)


def test_editing_the_offset_remaps_every_row_of_that_source(window: MainWindow) -> None:
    _sensor_widget(window).offset_spin.setValue(5.0)

    for channel in window.plot_pane.channels:
        assert channel.reader.time_map.offset == pytest.approx(5.0)


def test_editing_the_offset_shifts_master_coverage(window: MainWindow) -> None:
    before = window.plot_pane.source_bounds(window._sensor_cache_dirs[SENSOR_PATH])

    _sensor_widget(window).offset_spin.setValue(4.0)

    after = window.plot_pane.source_bounds(window._sensor_cache_dirs[SENSOR_PATH])
    assert after[0] == pytest.approx(before[0] - 4.0)
    assert after[1] == pytest.approx(before[1] - 4.0)


def test_editing_the_offset_does_not_reload_the_channels(window: MainWindow) -> None:
    """Re-aligning must be a redraw, not a reimport — readers keep their identity."""
    readers_before = [id(channel.reader) for channel in window.plot_pane.channels]

    _sensor_widget(window).offset_spin.setValue(2.5)

    assert [id(channel.reader) for channel in window.plot_pane.channels] == readers_before


def test_editing_the_drift_reaches_the_readers(window: MainWindow) -> None:
    _sensor_widget(window).drift_spin.setValue(150.0)

    for channel in window.plot_pane.channels:
        assert channel.reader.time_map.drift_ppm == pytest.approx(150.0)


def test_readout_follows_the_new_mapping(window: MainWindow) -> None:
    """The cursor readout must report the sample now under the master cursor."""
    reader = window.plot_pane.channels[0].reader
    before = reader.sample_at(5.0)

    _sensor_widget(window).offset_spin.setValue(3.0)

    after = reader.sample_at(5.0)
    assert after[0] == before[0] + int(round(3.0 * RATE_HZ))


def test_mapping_is_written_into_the_saved_session(window: MainWindow) -> None:
    _sensor_widget(window).offset_spin.setValue(1.5)
    _sensor_widget(window).drift_spin.setValue(-25.0)

    state = window._build_session_state()

    entry = next(s for s in state.sensors if s.path == SENSOR_PATH)
    assert entry.offset == pytest.approx(1.5)
    assert entry.drift_ppm == pytest.approx(-25.0)


def test_restored_mapping_is_applied_when_the_import_reports_back(
    window: MainWindow, cache_dir: Path
) -> None:
    """Session restore holds the mapping until the async import finishes."""
    other = "/tmp/other-sensor.csv"
    window._pending_sensor_mappings[other] = (2.0, 10.0)

    window._on_import_finished(other, str(cache_dir), ["a"], (0.0, 20.0), None)

    widget = window.sidebar.sensor_widget(other)
    assert widget is not None
    assert widget.mapping() == pytest.approx((2.0, 10.0))
    assert other not in window._pending_sensor_mappings


def test_setting_a_mapping_programmatically_does_not_echo_back(window: MainWindow) -> None:
    """set_mapping is display-only; it must not re-emit into the handler."""
    emitted: list[tuple[str, float, float]] = []
    window.sidebar.sensor_mapping_changed.connect(
        lambda path, offset, drift: emitted.append((path, offset, drift))
    )

    window.sidebar.set_sensor_mapping(SENSOR_PATH, 9.0, 3.0)

    assert emitted == []
    assert window.sidebar.sensor_mapping(SENSOR_PATH) == pytest.approx((9.0, 3.0))


def test_export_references_carry_the_accepted_mapping(window: MainWindow) -> None:
    _sensor_widget(window).offset_spin.setValue(6.0)

    references = window._reader_references()

    assert references
    assert all(reference.offset == pytest.approx(6.0) for reference in references)


def test_removing_a_sensor_drops_its_mapping(window: MainWindow) -> None:
    window._on_sensor_remove_requested(SENSOR_PATH)

    assert SENSOR_PATH not in window._sensor_cache_dirs
    assert window.plot_pane.channels == []
