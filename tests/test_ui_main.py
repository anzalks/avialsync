"""Main Window regression tests."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from kinochronix.core.session import SensorEntry, SessionState
from kinochronix.ui.main_window import MainWindow


@pytest.fixture
def main_window(qapp: QApplication) -> MainWindow:
    win = MainWindow()
    win.show()
    return win


# ── Bug a: _on_annotate_requested crash ──────────────────────────────


def test_annotate_no_attribute_error(main_window: MainWindow) -> None:
    """_on_annotate_requested must not raise with zero videos loaded."""
    main_window._on_annotate_requested()


def test_annotate_with_pane_present_no_error(main_window: MainWindow) -> None:
    """_on_annotate_requested must not raise when a pane is present.

    test_annotate_no_attribute_error missed this: with empty panes the for-loop
    body never runs. The crash lived inside the loop — pane.time_map.path raised
    AttributeError because TimeMap has no .path attribute.
    """
    from unittest.mock import MagicMock

    from kinochronix.core.timeline import TimeMap

    fake_pane = MagicMock()
    fake_pane.time_map = TimeMap()  # real TimeMap — to_source() works, no .path
    fake_pane._fps = 30.0

    main_window.video_grid.panes.append(fake_pane)
    main_window.video_grid._paths.append("/fake/video.mp4")

    # Before fix: AttributeError 'TimeMap' has no attribute 'path'
    main_window._on_annotate_requested()

    # One marker must have been added to the store
    assert len(main_window.annotation_store.markers) == 1


# ── Bug b: _start_csv_import → _start_data_import ────────────────────


def test_session_restore_calls_data_import(main_window: MainWindow) -> None:
    """Session restore with a sensor entry must call _start_data_import.

    Regression: _restore_session was calling self._start_csv_import() which
    does not exist — AttributeError on every session restore with sensors.
    """
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        csv_path = Path(f.name)
        f.write(b"t,x\n0.0,1.0\n1.0,2.0\n")

    state = SessionState(sensors=[SensorEntry(path=str(csv_path), channels=[])])

    with patch.object(main_window, "_start_data_import") as mock_import:
        main_window._restore_session(state)
        mock_import.assert_called_once_with(csv_path)
