from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QTimer

from avialview.core.pyramid import PyramidBuilder
from avialview.loaders.video_standard import VideoStandardLoader
from avialview.ui.main_window import MainWindow
from avialview.ui.sync_wizard import SyncWizard


def test_exact_sync_flow(qtbot, tmp_path: Path):
    window = MainWindow()
    qtbot.addWidget(window)

    # 1. Load Video
    video_path = Path("tests/fixtures/sample_session/camera_1.mp4").resolve()
    video_loader = VideoStandardLoader()
    video_loader.open(video_path, {})
    window._on_video_opened(str(video_path), video_loader, str(video_path))

    # 2. Build ground-truth per-frame trigger evidence in master time.
    frame_times = video_loader.frame_times()
    assert frame_times is not None
    master_times = np.asarray(frame_times) + 100.0
    cache_dir = tmp_path / "frame_triggers.avialcache"
    cache_dir.mkdir()
    PyramidBuilder(cache_dir, "trigger").build_and_save(master_times, np.ones_like(master_times))
    window.plot_pane.set_timeline_bounds(float(master_times[0]), float(master_times[-1]))
    window.plot_pane.load_channels(cache_dir, ["trigger"])

    # 3. Open Sync Wizard and interact
    def interact():
        wizards = window.findChildren(SyncWizard)
        assert len(wizards) == 1
        wizard = wizards[0]

        # 4. Select Exact Index
        wizard._strategy_combo.setCurrentIndex(1)
        wizard._use_all_times_chk.setChecked(True)

        # Click Preview
        wizard._preview_button.click()

        # We cannot use qtbot.waitUntil easily inside singleShot, but we can use QTimer
        def check_finished():
            if wizard._thread is None:
                assert wizard.proposal is not None
                assert wizard.proposal.acceptable
                wizard.accept()
            else:
                QTimer.singleShot(100, check_finished)

        QTimer.singleShot(100, check_finished)

    QTimer.singleShot(0, interact)

    # This blocks until wizard.accept() is called which ends exec()
    window._open_sync_wizard()

    pane = window.video_grid.panes[0]
    assert pane.time_map.to_source(float(master_times[5])) == pytest.approx(frame_times[5])
    assert pane.time_map.rate_scale == pytest.approx(1.0)
    session = window._build_session_state()
    assert session.sync_provenance[0].exact_master[5] == pytest.approx(master_times[5])
    assert session.sync_provenance[0].exact_source[5] == pytest.approx(frame_times[5])

    window.close()
