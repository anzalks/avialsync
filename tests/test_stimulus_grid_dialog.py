from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt

from avialsync.engine.export_worker import ReaderReference
from avialsync.ui.stimulus_grid_dialog import StimulusChannelOption, StimulusGridDialog


class _Reader:
    def coverage(self) -> tuple[float, float]:
        return 0.0, 5.0

    def query(self, _start: float, _end: float, max_points: int):
        times = np.linspace(0.0, 5.0, min(20, max_points))
        values = np.sin(times)
        return times, values - 0.1, values + 0.1, np.zeros(len(times), dtype=bool)

    def available_sample_at(self, time: float) -> tuple[int, float] | None:
        return (0, float(np.sin(time))) if time <= 5.0 else None


def test_dialog_shows_first_event_window_and_limits_selected_events(qtbot, tmp_path) -> None:
    channel = StimulusChannelOption(
        "stimulus",
        ReaderReference(tmp_path, "stimulus"),
        _Reader(),
    )
    dialog = StimulusGridDialog([channel])
    qtbot.addWidget(dialog)

    dialog.set_events(tuple(float(index) for index in range(1, 15)))

    assert len(dialog.selected_events()) == 12
    assert dialog.selected_events()[0] == 1.0
    assert "1.000 s" in dialog.event_details.text()  # D-185: ms is the readable unit
    assert "0.500 to 2.500 s" in dialog.event_details.text()
    assert "Video length: 2.00 s at 1x" in dialog.event_details.text()
    assert dialog.custom_speed_spin.isHidden()
    assert dialog.fps_spin.value() == 10
    assert dialog.fps_spin.accessibleName() == "Cursor update rate"
    assert not dialog.high_detail()

    dialog.output_detail_combo.setCurrentIndex(1)
    assert dialog.high_detail()
    dialog.output_detail_combo.setCurrentIndex(0)

    preset = dialog.speed_combo.findData(0.1)
    dialog.speed_combo.setCurrentIndex(preset)
    assert dialog.playback_speed() == 0.1
    assert "Video length: 20.00 s at 0.1x" in dialog.event_details.text()
    dialog.speed_combo.setCurrentIndex(dialog.speed_combo.count() - 1)
    assert not dialog.custom_speed_spin.isHidden()
    dialog.custom_speed_spin.setValue(0.130435)
    assert dialog.playback_speed() == 0.130435
    assert "Video length: 15.33 s at 0.130435x" in dialog.event_details.text()

    dialog.before_spin.setValue(0.25)
    dialog.after_spin.setValue(0.75)
    assert "0.750 to 1.750 s" in dialog.event_details.text()

    first = dialog.event_table.item(0, 0)
    extra = dialog.event_table.item(12, 0)
    last = dialog.event_table.item(13, 0)
    assert first is not None and extra is not None and last is not None
    extra.setCheckState(Qt.CheckState.Checked)
    assert extra.checkState() == Qt.CheckState.Unchecked
    assert dialog.selected_events()[-1] == 12.0
    first.setCheckState(Qt.CheckState.Unchecked)
    last.setCheckState(Qt.CheckState.Checked)
    assert len(dialog.selected_events()) == 12
    assert dialog.selected_events()[-1] == 14.0


def test_dialog_draws_worker_overview_without_querying_source_on_ui(qtbot, tmp_path) -> None:
    class NoUiQuery(_Reader):
        def query(self, _start: float, _end: float, max_points: int):
            raise AssertionError("The dialog must use the worker's overview")

    dialog = StimulusGridDialog(
        [StimulusChannelOption("stimulus", ReaderReference(tmp_path, "stimulus"), NoUiQuery())]
    )
    qtbot.addWidget(dialog)
    times = np.array([0.0, 1.0, 2.0])
    values = np.array([1.0, 2.0, 3.0])
    dialog.set_preview(0, ((0.0, 2.0), times, values, values, np.zeros(3, dtype=bool)))

    assert len(dialog.timeline.plotItem.listDataItems()) == 2
