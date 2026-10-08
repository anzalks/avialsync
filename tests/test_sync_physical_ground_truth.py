"""Physical-clock fixtures: every confidence label against clocks whose truth is known.

Passing the alignment tests shows the algorithms behave as coded. These check
the claim each proposal makes -- exact, verified, unverified, refused --
against `tools/make_fixtures.generate_sync_ground_truth`, which records the true
relation between every clock it writes (D-201).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avialsync.core.errors import SyncEvidenceError
from avialsync.core.pyramid import PyramidBuilder
from avialsync.core.sync import AlignmentMethod, fit_exact_index_mapping, fit_sync_events
from avialsync.core.timeline import TimeMap
from avialsync.core.triggers import TriggerKind, extract_pulses
from avialsync.engine import sync_worker as sync_worker_module
from avialsync.engine.sync_worker import EventEvidenceSpec, SignalEvidenceSpec, SyncWorker
from tools.make_fixtures import generate_sync_ground_truth

#: The DAQ clock's accepted placement and the target recorder's true one.
DAQ_MAP = TimeMap(2.0, 162.0)
TARGET_OFFSET, TARGET_DRIFT = 3.0, 216.0


@pytest.fixture(scope="module")
def truth(tmp_path_factory: pytest.TempPathFactory) -> dict[str, np.ndarray]:
    path = tmp_path_factory.mktemp("truth") / "sync_ground_truth.npz"
    generate_sync_ground_truth(path)
    with np.load(path) as data:
        return {name: data[name] for name in data.files}


def _run(worker: SyncWorker) -> tuple[list[object], list[str]]:
    found: list[object] = []
    errors: list[str] = []
    worker.finished.connect(found.append)
    worker.error.connect(errors.append)
    worker.run()
    return found, errors


def _camera(times: np.ndarray, clock: str = "camera") -> EventEvidenceSpec:
    return EventEvidenceSpec(clock, times, clock_id=clock, is_video_time_axis=True)


# ── Independent videos ───────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["exact_index", "auto", "affine"])
def test_independent_equal_length_videos_never_align(
    truth: dict[str, np.ndarray], mode: str
) -> None:
    """Identical 30 fps grids, 7.25 s apart in truth: no mode may pair them."""
    assert np.array_equal(truth["video_a_pts"], truth["video_b_pts"])
    assert float(truth["video_a_master_start"]) != float(truth["video_b_master_start"])

    found, errors = _run(
        SyncWorker(
            _camera(truth["video_a_pts"], "a"), _camera(truth["video_b_pts"], "b"), mode=mode
        )
    )

    assert not found
    assert "cannot place another source" in errors[0]


def test_core_refuses_exact_pairing_without_a_declared_strobe(
    truth: dict[str, np.ndarray],
) -> None:
    with pytest.raises(SyncEvidenceError, match="recorded camera-to-DAQ strobe"):
        fit_exact_index_mapping(
            truth["video_a_pts"], truth["video_b_pts"], reference_id="a", target_id="b"
        )


def test_an_undeclared_strobe_cannot_claim_exact_indices(truth: dict[str, np.ndarray]) -> None:
    """A strobe recorded for a different camera says nothing about this one."""
    found, errors = _run(
        SyncWorker(
            EventEvidenceSpec(
                "strobe",
                truth["reference_raw"],
                kind=TriggerKind.FRAME_STROBE,
                clock_id="daq",
                strobe_for="other camera",
                accepted_mapping=DAQ_MAP,
            ),
            _camera(truth["camera_pts"]),
            mode="exact_index",
        )
    )
    assert not found
    assert "declared for this video" in errors[0]


# ── Genuine strobes ──────────────────────────────────────────────────


def test_a_genuine_strobe_places_every_frame_at_its_measured_exposure(
    truth: dict[str, np.ndarray],
) -> None:
    """Strobe on a DAQ with offset and drift; camera on its own drifting clock."""
    found, errors = _run(
        SyncWorker(
            EventEvidenceSpec(
                "strobe",
                truth["reference_raw"],
                kind=TriggerKind.FRAME_STROBE,
                clock_id="daq",
                strobe_for="camera",
                accepted_mapping=DAQ_MAP,
            ),
            _camera(truth["camera_pts"]),
            mode="auto",
        )
    )

    assert errors == []
    proposal = found[0]
    assert proposal.fit.method is AlignmentMethod.EXACT
    assert proposal.fit.precision_verified
    mapping = proposal.fit.to_time_map()
    np.testing.assert_allclose(
        mapping.to_source_array(truth["master_events"]), truth["camera_pts"], atol=1e-9
    )
    assert proposal.matches[3].raw_reference_time == pytest.approx(truth["reference_raw"][3])


@pytest.mark.parametrize("strobe_key", ["dropped_strobe", "extra_strobe"])
def test_dropped_or_extra_strobe_cannot_claim_exact_indices(
    truth: dict[str, np.ndarray],
    strobe_key: str,
) -> None:
    found, errors = _run(
        SyncWorker(
            EventEvidenceSpec(
                "recorded strobe",
                truth[strobe_key],
                kind=TriggerKind.FRAME_STROBE,
                clock_id="daq",
                strobe_for="camera",
            ),
            _camera(truth["master_events"] + 3.0),
            mode="exact_index",
        )
    )
    assert not found
    assert "counts differ" in errors[0]


def test_a_drop_hidden_by_an_extra_pulse_is_caught_by_the_intervals(
    truth: dict[str, np.ndarray],
) -> None:
    """Counts agree, yet every frame after event 185 would take its neighbour's time."""
    strobe = np.sort(
        np.append(np.delete(truth["master_events"], 185), truth["master_events"][300] + 0.4)
    )
    found, errors = _run(
        SyncWorker(
            EventEvidenceSpec(
                "strobe",
                strobe,
                kind=TriggerKind.FRAME_STROBE,
                clock_id="daq",
                strobe_for="camera",
            ),
            _camera(truth["camera_pts"]),
            mode="exact_index",
        )
    )
    assert not found
    assert "interval patterns disagree" in errors[0]


@pytest.mark.parametrize("strobe_key", ["dropped_strobe", "extra_strobe"])
def test_automatic_fit_demotes_broken_strobe_indices(
    truth: dict[str, np.ndarray],
    strobe_key: str,
) -> None:
    found, errors = _run(
        SyncWorker(
            EventEvidenceSpec(
                "recorded strobe",
                truth[strobe_key],
                kind=TriggerKind.FRAME_STROBE,
                clock_id="daq",
                strobe_for="camera",
            ),
            _camera(truth["master_events"] + 3.0),
            mode="auto",
        )
    )
    assert not errors
    assert found[0].fit.method is not AlignmentMethod.EXACT
    # The demoted fit still recovers the true placement from the shared events.
    assert found[0].fit.offset == pytest.approx(3.0, abs=1e-6)


# ── Master clock first ───────────────────────────────────────────────


def test_reference_offset_and_drift_are_applied_before_fitting(
    truth: dict[str, np.ndarray],
) -> None:
    found, errors = _run(
        SyncWorker(
            EventEvidenceSpec(
                "DAQ",
                truth["reference_raw"],
                clock_id="daq",
                accepted_mapping=DAQ_MAP,
            ),
            EventEvidenceSpec("target", truth["target_raw"], clock_id="target"),
            mode="affine",
        )
    )
    assert errors == []
    proposal = found[0]
    assert proposal.fit.offset == pytest.approx(TARGET_OFFSET, abs=1e-6)
    assert proposal.fit.drift_ms_per_hour == pytest.approx(TARGET_DRIFT, abs=1e-5)
    assert proposal.matches[0].reference_time == pytest.approx(truth["master_events"][0])
    assert proposal.matches[0].raw_reference_time == pytest.approx(truth["reference_raw"][0])
    assert proposal.reference_clock_id == "daq"


# ── Precision is judged separately from the search ───────────────────


def test_bounded_timing_error_inside_the_requirement_is_verified(
    truth: dict[str, np.ndarray],
) -> None:
    bound = float(truth["jitter_small_bound"])
    proposal = fit_sync_events(
        truth["master_events"],
        truth["target_jitter_small"],
        reference_id="daq",
        target_id="target",
        precision_requirement=0.001,
    )
    error = proposal.fit.to_time_map().to_source_array(truth["master_events"]) - truth["target_raw"]

    assert proposal.fit.max_residual <= 2 * bound
    assert np.max(np.abs(error)) <= bound
    assert proposal.fit.precision_verified
    assert "precision verified at 1.000 ms" in proposal.fit.describe()


def test_timing_error_beyond_the_requirement_is_usable_but_unverified(
    truth: dict[str, np.ndarray],
) -> None:
    """Three milliseconds of jitter passes a 250 ms search and fails a 1 ms claim."""
    bound = float(truth["jitter_large_bound"])
    proposal = fit_sync_events(
        truth["master_events"],
        truth["target_jitter_large"],
        reference_id="daq",
        target_id="target",
        precision_requirement=0.001,
    )
    error = proposal.fit.to_time_map().to_source_array(truth["master_events"]) - truth["target_raw"]

    assert proposal.tolerance > 0.1, "the search window is the broad pulse-spacing rule"
    assert proposal.applicable
    assert proposal.fit.max_residual > 0.001
    assert np.max(np.abs(error)) <= bound
    assert not proposal.fit.precision_verified
    assert "precision unverified at 1.000 ms" in proposal.fit.describe()


def test_sparse_shared_events_find_matches_without_claiming_precision(
    truth: dict[str, np.ndarray],
) -> None:
    proposal = fit_sync_events(
        truth["sparse_reference"],
        truth["sparse_target"],
        reference_id="daq",
        target_id="target",
        precision_requirement=0.001,
    )
    assert proposal.applicable
    assert proposal.fit.max_residual < 1e-6
    assert proposal.fit.largest_unsupported_interval > 100.0
    assert not proposal.fit.precision_verified
    assert "precision unverified" in proposal.fit.describe()


def test_target_events_past_the_evidence_are_reported_as_extrapolated(
    truth: dict[str, np.ndarray],
) -> None:
    """The target runs 300 events past the last shared one."""
    proposal = fit_sync_events(
        truth["master_events"][:100],
        truth["target_raw"],
        reference_id="daq",
        target_id="target",
        precision_requirement=0.001,
    )
    expected_after = float(truth["target_raw"][-1] - truth["target_raw"][99])

    assert proposal.fit.extrapolated_after == pytest.approx(expected_after)
    assert proposal.fit.extrapolated_before == 0.0
    assert proposal.fit.coverage_fraction == pytest.approx(0.25, abs=0.02)
    assert not proposal.fit.precision_verified


def test_a_sensor_target_is_judged_over_its_whole_recording(
    truth: dict[str, np.ndarray], tmp_path: Path
) -> None:
    """Pulses for 100 s, then 300 s of signal the mapping is extrapolated over."""
    rate = 1000.0
    pulses = truth["target_raw"][:100]
    times = np.arange(pulses[0] - 1.0, pulses[-1] + 300.0, 1.0 / rate)
    values = np.zeros_like(times)
    for rise in pulses:
        values[(times >= rise) & (times < rise + 0.02)] = 1.0
    PyramidBuilder(tmp_path, "sync").build_and_save(times, values)
    reference = EventEvidenceSpec(
        "DAQ", truth["reference_raw"][:100], clock_id="daq", accepted_mapping=DAQ_MAP
    )
    target = SignalEvidenceSpec("sensor.csv", tmp_path, "sync", clock_id="sensor.csv")

    found, errors = _run(SyncWorker(reference, target, mode="affine", precision_requirement=0.01))

    assert errors == []
    fit = found[0].fit
    assert fit.offset == pytest.approx(TARGET_OFFSET, abs=1e-3)
    assert fit.extrapolated_after == pytest.approx(300.0, abs=1.0)
    assert fit.max_residual <= 0.01, "edge quantisation alone would pass at 10 ms"
    assert not fit.precision_verified, "300 s of extrapolation cannot be verified"


def test_a_record_saved_before_assessment_says_not_assessed() -> None:
    from avialsync.core.session import SessionState

    state = SessionState.from_dict(
        {
            "sync_provenance": [
                {
                    "reference_id": "daq",
                    "target_id": "cam.mp4",
                    "offset": 1.0,
                    "drift_ms_per_hour": 0.0,
                    "rms_residual": 0.0,
                    "max_residual": 0.0,
                    "matched_count": 10,
                    "rejected_count": 0,
                    "tolerance": 0.01,
                }
            ]
        }
    )
    assert state.sync_provenance[0].precision_requirement == 0.0


# ── Missing data in the reference ────────────────────────────────────


def test_gap_nan_and_sentinel_runs_exclude_incomplete_pulses_across_chunks() -> None:
    times = np.arange(0.0, 0.8, 0.01)
    values = np.zeros_like(times)
    for start in (0.10, 0.30, 0.50):
        values[(times >= start) & (times < start + 0.05)] = 1.0
    gaps = np.zeros(len(times), dtype=bool)
    gaps[32] = True  # Between chunks, inside the second high pulse.
    values[52] = np.nan  # Inside the third high pulse.
    train = extract_pulses(
        [(times[:33], values[:33], gaps[:33]), (times[33:], values[33:], gaps[33:])],
        source_id="daq",
        kind=TriggerKind.FRAME_STROBE,
    )
    assert train.incomplete_count == 2
    assert train.count == 1
    assert train.times[0] == pytest.approx(0.125, abs=0.01)

    # A sentinel is finite, so its provider must mark the run in the gap mask.
    values[52] = -32768.0
    gaps[51:53] = True
    sentinel_train = extract_pulses(
        [(times[:33], values[:33], gaps[:33]), (times[33:], values[33:], gaps[33:])],
        source_id="daq",
        kind=TriggerKind.FRAME_STROBE,
    )
    assert sentinel_train.incomplete_count == 2
    assert sentinel_train.count == 1


def test_a_recording_that_opens_mid_pulse_counts_that_pulse() -> None:
    times = np.arange(0.0, 0.5, 0.01)
    values = np.zeros_like(times)
    values[:3] = 1.0
    values[20:25] = 1.0

    train = extract_pulses([(times, values)], source_id="daq", kind=TriggerKind.SYNC_TRAIN)

    assert train.count == 1
    assert train.incomplete_count == 1


def _strobe_cache_with_holes(cache: Path, chunk: int) -> tuple[np.ndarray, int]:
    """A 1 kHz strobe, 40 pulses, with holes at and inside chunk boundaries.

    Returns the midpoints of the pulses that survive intact and how many
    pulses the holes made incomplete.
    """
    rate, period, width = 1000.0, 0.1, 0.02
    times = np.arange(0.0, 4.05, 1.0 / rate)
    values = np.zeros_like(times)
    rises = 0.03 + period * np.arange(40)
    for rise in rises:
        values[(times >= rise - 1e-9) & (times < rise + width - 1e-9)] = 1.0
    keep = np.ones(len(times), dtype=bool)
    # 1. A gap starting at the last sample of the first chunk, inside pulse 4.
    boundary = chunk - 1
    assert values[boundary] == 1.0
    keep[boundary + 1 : boundary + 13] = False
    # 2. A non-finite run inside pulse 12, mid-chunk.
    values[int((rises[12] + 0.01) * rate)] = np.nan
    # 3. A gap inside pulse 20, mid-chunk.
    start = int((rises[20] + 0.005) * rate)
    keep[start : start + 12] = False
    times, values = times[keep], values[keep]
    # 4. An intact pulse straddles a later chunk boundary with no gap at all:
    # chunking by itself must never split it.
    boundaries = np.arange(2, (len(times) - 1) // chunk + 1) * chunk
    assert np.any((values[boundaries - 1] == 1.0) & (values[boundaries] == 1.0))
    PyramidBuilder(cache, "strobe").build_and_save(times, values)
    broken = {4, 12, 20}
    intact = np.array([rise + width / 2 for i, rise in enumerate(rises) if i not in broken])
    return intact, len(broken)


def test_the_worker_reads_gap_masks_and_reports_excluded_pulses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunk = 433
    monkeypatch.setattr(sync_worker_module, "RAW_CHUNK_SAMPLES", chunk)
    intact, broken = _strobe_cache_with_holes(tmp_path, chunk)
    reference = SignalEvidenceSpec(
        "daq : strobe",
        tmp_path,
        "strobe",
        kind=TriggerKind.FRAME_STROBE,
        clock_id="daq",
        strobe_for="camera",
    )
    frames = 0.03 + 0.1 * np.arange(40) + 0.01 + 5.0

    times = SyncWorker(reference, _camera(frames))._event_times(reference)
    np.testing.assert_allclose(times, intact, atol=1.5e-3)

    found, errors = _run(SyncWorker(reference, _camera(frames), mode="exact_index"))
    assert not found
    assert f"{broken} strobe pulse(s) crossed missing data" in errors[0]

    found, errors = _run(
        SyncWorker(reference, _camera(np.delete(frames, [4, 12, 20])), mode="affine")
    )
    assert errors == []
    assert found[0].fit.excluded_incomplete_count == broken
    assert f"{broken} incomplete pulses excluded" in found[0].fit.describe()
