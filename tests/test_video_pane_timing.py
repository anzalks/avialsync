"""Timestamp-derived video readout tests."""

import numpy as np
import pytest

from avialview.ui.video_pane import displayed_frame_rate, instantaneous_frame_rate


def test_vfr_readout_reports_the_current_frame_interval() -> None:
    """VFR readout must not collapse variable intervals into one average FPS."""
    frame_times = np.array([0.0, 1 / 30, 2 / 30, 4 / 30])

    assert instantaneous_frame_rate(frame_times, 0.04, 0.0) == pytest.approx(30.0)
    assert instantaneous_frame_rate(frame_times, 0.08, 0.0) == pytest.approx(15.0)


def test_cfr_readout_stays_at_the_nominal_rate() -> None:
    """CFR video must not fluctuate because an observer fires between frames."""
    frame_times = np.array([0.0, 1 / 30, 2 / 30, 3 / 30])

    assert displayed_frame_rate(frame_times, 0.048, False, 30.0, 58.0) == 30.0
