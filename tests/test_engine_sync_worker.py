"""Tests for background synchronization evidence extraction."""

from pathlib import Path

import numpy as np
import pytest

from avialsync.core.pyramid import PyramidBuilder
from avialsync.engine.sync_worker import EventEvidenceSpec, SignalEvidenceSpec, SyncWorker


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


class TestTheLadderPicksTheModel:
    """A strategy dropdown asks the user to certify what only the data knows."""

    def test_a_short_span_reports_an_offset_and_no_rate(self, qtbot) -> None:
        """1 ppm across ten seconds is ten microseconds. Nothing can measure it."""
        from avialsync.core.sync import AlignmentMethod

        reference = np.arange(0.0, 10.0, 1.0)
        worker = SyncWorker(
            EventEvidenceSpec("sensor:ttl", reference),
            EventEvidenceSpec("cam.mp4", reference + 1.25),
            mode="auto",
        )
        seen: list[object] = []
        worker.finished.connect(seen.append)

        worker.run()

        assert seen[0].fit.method is AlignmentMethod.SHIFT
        assert seen[0].fit.drift_ppm == 0.0
        assert seen[0].fit.offset == pytest.approx(1.25, abs=1e-6)

    def test_a_long_span_with_a_real_rate_keeps_it(self, qtbot) -> None:
        from avialsync.core.sync import AlignmentMethod

        rng = np.random.default_rng(31)
        reference = np.cumsum(rng.uniform(0.5, 1.5, 800))
        worker = SyncWorker(
            EventEvidenceSpec("sensor:ttl", reference),
            EventEvidenceSpec("cam.mp4", reference * (1.0 + 60e-6) + 2.0),
            mode="auto",
        )
        seen: list[object] = []
        worker.finished.connect(seen.append)

        worker.run()

        assert seen[0].fit.method is AlignmentMethod.AFFINE
        assert seen[0].fit.drift_ppm == pytest.approx(60.0, abs=1.0)

    def test_a_shared_sync_train_is_interpolated_between(self, qtbot) -> None:
        """Unpredictable drift: no single rate has to hold for the recording."""
        from avialsync.core.sync import AlignmentMethod
        from avialsync.core.triggers import TriggerKind

        rng = np.random.default_rng(32)
        reference = np.cumsum(rng.uniform(0.5, 1.5, 300))
        wobble = 0.02 * np.sin(reference / reference[-1] * 2 * np.pi)
        worker = SyncWorker(
            EventEvidenceSpec("sensor:sync", reference),
            EventEvidenceSpec("cam.mp4", reference + 1.5 + wobble),
            mode="auto",
            kind=TriggerKind.SYNC_TRAIN,
        )
        seen: list[object] = []
        errors: list[str] = []
        worker.finished.connect(seen.append)
        worker.error.connect(errors.append)

        worker.run()

        assert errors == []
        assert seen[0].fit.method is AlignmentMethod.PIECEWISE
        assert seen[0].fit.to_time_map().has_exact_mapping
