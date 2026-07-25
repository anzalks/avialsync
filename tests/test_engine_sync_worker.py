"""Tests for background synchronization evidence extraction."""

from pathlib import Path

import numpy as np
import pytest

from kinochronix.core.pyramid import PyramidBuilder
from kinochronix.engine.sync_worker import EventEvidenceSpec, SignalEvidenceSpec, SyncWorker


def test_sync_worker_extracts_cached_ttl_and_fits_frame_events(tmp_path: Path) -> None:
    """Cached signal extraction stays compatible with video-frame event evidence."""
    times = np.arange(0.0, 10.0, 0.1)
    values = np.zeros_like(times)
    values[::10] = 1.0
    values[1::10] = 0.0
    PyramidBuilder(tmp_path, "ttl").build_and_save(times, values)
    target = np.arange(1.0, 10.0, 1.0) + 1.5

    worker = SyncWorker(
        SignalEvidenceSpec("sensor:ttl", tmp_path, "ttl"),
        EventEvidenceSpec("video:camera", target),
    )
    proposals: list[object] = []
    errors: list[str] = []
    worker.finished.connect(proposals.append)
    worker.error.connect(errors.append)
    worker.run()

    assert errors == []
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.fit.offset == pytest.approx(1.5)
