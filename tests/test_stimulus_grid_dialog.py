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

    def value_at(self, time: float) -> float:
        return float(np.sin(time))


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
    assert "1.000000 s" in dialog.event_details.text()
    assert "0.500000 to 2.500000 s" in dialog.event_details.text()

    dialog.before_spin.setValue(0.25)
    dialog.after_spin.setValue(0.75)
    assert "0.750000 to 1.750000 s" in dialog.event_details.text()

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
