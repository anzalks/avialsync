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
            EventEvidenceSpec("sensor:sync", reference, kind=TriggerKind.SYNC_TRAIN),
            EventEvidenceSpec("cam.mp4", reference + 1.5 + wobble),
            mode="auto",
        )
        seen: list[object] = []
        errors: list[str] = []
        worker.finished.connect(seen.append)
        worker.error.connect(errors.append)

        worker.run()

        assert errors == []
        assert seen[0].fit.method is AlignmentMethod.PIECEWISE
        assert seen[0].fit.to_time_map().has_exact_mapping


class TestTheRungsThatWereUnreachable:
    """Both were fully tested in `core/` and could never be selected in the app.

    `EXACT` needed a `Reconciliation` the worker passed as `None`
    unconditionally, and `PIECEWISE` needed a `TriggerKind` no caller carried,
    so every automatic fit chose between affine and shift whatever the user had
    declared their evidence to be.
    """

    def test_a_strobe_whose_counts_agree_reaches_exact(self) -> None:
        from avialsync.core.sync import AlignmentMethod
        from avialsync.core.triggers import TriggerKind

        rng = np.random.default_rng(41)
        reference = np.cumsum(rng.uniform(0.02, 0.05, 400))
        worker = SyncWorker(
            EventEvidenceSpec("cam:strobe", reference, kind=TriggerKind.FRAME_STROBE),
            EventEvidenceSpec("cam.mp4", reference + 1.5, kind=TriggerKind.FRAME_STROBE),
            mode="auto",
        )
        seen: list[object] = []
        errors: list[str] = []
        worker.finished.connect(seen.append)
        worker.error.connect(errors.append)

        worker.run()

        assert errors == []
        assert seen[0].fit.method is AlignmentMethod.EXACT

    def test_a_trigger_train_with_the_same_counts_does_not(self) -> None:
        """Agreement on requested exposures is the absence of evidence."""
        from avialsync.core.sync import AlignmentMethod
        from avialsync.core.triggers import TriggerKind

        rng = np.random.default_rng(42)
        reference = np.cumsum(rng.uniform(0.02, 0.05, 400))
        worker = SyncWorker(
            EventEvidenceSpec("daq:trigger", reference, kind=TriggerKind.FRAME_TRIGGER),
            EventEvidenceSpec("cam.mp4", reference + 1.5, kind=TriggerKind.FRAME_TRIGGER),
            mode="auto",
        )
        seen: list[object] = []
        worker.finished.connect(seen.append)

        worker.run()

        assert seen[0].fit.method is not AlignmentMethod.EXACT

    def test_a_strobe_whose_counts_disagree_does_not(self) -> None:
        """Frames were lost; pairing by index would shift everything after."""
        from avialsync.core.sync import AlignmentMethod
        from avialsync.core.triggers import TriggerKind

        rng = np.random.default_rng(43)
        reference = np.cumsum(rng.uniform(0.02, 0.05, 400))
        worker = SyncWorker(
            EventEvidenceSpec("cam:strobe", reference, kind=TriggerKind.FRAME_STROBE),
            EventEvidenceSpec("cam.mp4", reference[:380] + 1.5, kind=TriggerKind.FRAME_STROBE),
            mode="auto",
        )
        seen: list[object] = []
        worker.finished.connect(seen.append)

        worker.run()

        assert seen[0].fit.method is not AlignmentMethod.EXACT

    def test_a_declared_sync_train_reaches_piecewise(self) -> None:
        from avialsync.core.sync import AlignmentMethod
        from avialsync.core.triggers import TriggerKind

        rng = np.random.default_rng(44)
        reference = np.cumsum(rng.uniform(0.5, 1.5, 300))
        wobble = 0.02 * np.sin(reference / reference[-1] * 2 * np.pi)
        worker = SyncWorker(
            EventEvidenceSpec("daq:sync", reference, kind=TriggerKind.SYNC_TRAIN),
            EventEvidenceSpec("cam.mp4", reference + 1.5 + wobble),
            mode="auto",
        )
        seen: list[object] = []
        worker.finished.connect(seen.append)

        worker.run()

        assert seen[0].fit.method is AlignmentMethod.PIECEWISE

    def test_an_undeclared_channel_still_gets_the_weakest_reading(self) -> None:
        """A spec with no kind means nobody said; it must not be assumed."""
        rng = np.random.default_rng(45)
        reference = np.cumsum(rng.uniform(0.02, 0.05, 400))
        worker = SyncWorker(
            EventEvidenceSpec("unlabelled", reference),
            EventEvidenceSpec("cam.mp4", reference + 1.5),
            mode="auto",
        )
        seen: list[object] = []
        worker.finished.connect(seen.append)

        worker.run()

        from avialsync.core.sync import AlignmentMethod

        assert seen[0].fit.method is not AlignmentMethod.EXACT


class TestBothEdgesReachTheFit:
    """A cached channel is thresholded with `extract_pulses`, not one edge."""

    @staticmethod
    def _cache(tmp_path, *, width: float, period: float, count: int):
        """A square wave in a pyramid cache, as a sensor channel arrives."""
        times = np.arange(0.0, period * (count + 1), 1e-4)
        values = np.zeros_like(times)
        rises = [period * 0.5 + index * period for index in range(count)]
        for rise in rises:
            values[(times >= rise) & (times < rise + width)] = 1.0
        PyramidBuilder(tmp_path, "strobe").build_and_save(times, values)
        return np.asarray(rises)

    def test_a_declared_strobe_is_timestamped_mid_exposure(self, tmp_path: Path) -> None:
        """The instant the frame represents, not the instant the shutter opened."""
        from avialsync.core.triggers import TriggerKind

        rises = self._cache(tmp_path, width=0.02, period=0.1, count=20)
        spec = SignalEvidenceSpec("cam:strobe", tmp_path, "strobe", kind=TriggerKind.FRAME_STROBE)

        times = SyncWorker._event_times(spec)

        assert times[0] == pytest.approx(rises[0] + 0.01, abs=2e-3)

    def test_every_other_kind_keeps_its_rising_edge(self, tmp_path: Path) -> None:
        """A request or a sync wave is an instant; it has no middle."""
        from avialsync.core.triggers import TriggerKind

        rises = self._cache(tmp_path, width=0.02, period=0.1, count=20)
        spec = SignalEvidenceSpec("daq:sync", tmp_path, "strobe", kind=TriggerKind.SYNC_TRAIN)

        times = SyncWorker._event_times(spec)

        assert times[0] == pytest.approx(rises[0], abs=2e-3)

    def test_an_undeclared_channel_is_unchanged_from_before(self, tmp_path: Path) -> None:
        """The default kind must not silently move existing sessions' events."""
        rises = self._cache(tmp_path, width=0.02, period=0.1, count=20)
        spec = SignalEvidenceSpec("unlabelled", tmp_path, "strobe")

        times = SyncWorker._event_times(spec)

        assert times[0] == pytest.approx(rises[0], abs=2e-3)
