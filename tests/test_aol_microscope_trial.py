"""Synthetic-file tests for AOL microscope trial discovery and mosaic imaging."""

import datetime as dt
from pathlib import Path

import h5py
import numpy as np

from avialsync.loaders.aol_cell_roi_grid import AOLCellRoiGridSource
from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
from avialsync.loaders.aol_microscope_trial import MicroscopeTrial, is_microscope_trial, read_trial
from avialsync.loaders.aol_ribbon_scan import AOLRibbonScanSource
from avialsync.loaders.aol_roi_trace import AOLRoiTraceLoader
from avialsync.loaders.aol_trial_matching import derive_utc_offset, match_trial


def _trial(path: Path, *, bad_line_count: bool = False) -> Path:
    path.mkdir()
    (path / "params.mat").touch()
    with h5py.File(path / "params.mat", "w") as handle:
        handle.create_group("controller").create_dataset("aol_params", data=[1])
        fifo = handle.create_group("timings/timing_FIFO")
        fifo.create_dataset("STARTTIME", data=[1_700_000_000_000])
        line = np.arange(12, dtype=np.uint64) * 2
        fifo.create_dataset("line_time", data=line[:-1] if bad_line_count else line)
        refs = handle.create_group("#refs#")
        summary = refs.create_dataset("duration", data=[0.016])
        cell = handle.create_dataset("timings/summary", shape=(1, 1), dtype=h5py.ref_dtype)
        cell[0, 0] = summary.ref
    for roi in (1, 2, 3):
        with h5py.File(
            path / f"RibbonScan_ROI_{roi:04d}_repeat_0001_timepoints_2.mat", "w"
        ) as handle:
            values = np.empty((2, 2, 2, 3), dtype=np.uint16)
            values[:] = roi * 1000 + np.arange(2, dtype=np.uint16)[None, :, None, None]
            values[1] += 500
            handle.create_dataset("volume", data=values)
    return path


def _analysis(folder: Path) -> Path:
    """Add a MATLAB-cell-shaped two-mask analysis with a cross-tile mask."""
    activity_dir = folder / "roi_activity"
    activity_dir.mkdir()
    path = activity_dir / "hybrid_mosaic_repeat_0001_activity.mat"
    with h5py.File(path, "w") as handle:
        refs = handle.create_group("#refs#")
        first = np.zeros((4, 6), dtype=bool)
        first[0, 0] = True
        second = np.zeros((4, 6), dtype=bool)
        second[1, 2:4] = True
        ref_a = refs.create_dataset("mask_a", data=first)
        ref_b = refs.create_dataset("mask_b", data=second)
        masks = handle.create_dataset("masks", (1, 2), dtype=h5py.ref_dtype)
        masks[0, 0], masks[0, 1] = ref_a.ref, ref_b.ref
        handle.create_dataset("frame_time_s", data=[[0.0, 0.008]])
        handle.create_dataset("roi_traces", data=[[1.0, 2.0], [3.0, 4.0]])
        source_map = np.zeros((4, 6), dtype=np.uint16)
        source_map[:2, :3] = 1
        source_map[2:, :3] = 2
        source_map[:2, 3:] = 3
        handle.create_group("mosaic_info").create_dataset("source_roi_map", data=source_map)
        handle.create_group("correction_info").create_dataset("green_channel", data=[2])
    return path


def test_trial_detector_and_line_clock_times(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    assert is_microscope_trial(folder)
    assert not is_microscope_trial(folder / "RibbonScan_ROI_0001_repeat_0001_timepoints_2.mat")

    trial = read_trial(folder)
    assert trial.start_epoch == 1_700_000_000.0
    np.testing.assert_allclose(trial.frame_times, [2.5e-8, 8.5e-8])
    assert trial.roi_frame_times is not None
    assert trial.roi_frame_times.shape == (2, 3)
    assert trial.timing_source.startswith("line clock")


def test_ribbon_source_tiles_and_leaves_unoccupied_pixels_nan(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    source = AOLRibbonScanSource()
    metadata = source.open(folder, {})
    assert (metadata.frame_count, metadata.height, metadata.width) == (2, 4, 6)
    assert metadata.axes == "CTYX"
    frame = source.read_frame(1, channel=1)
    assert np.all(frame[:2, :3] == 1501)
    assert np.all(frame[2:, :3] == 2501)
    assert np.all(frame[:2, 3:] == 3501)
    assert np.isnan(frame[2:, 3:]).all()
    source.close()


def test_trial_falls_back_when_line_clock_length_is_wrong(tmp_path: Path) -> None:
    trial = read_trial(_trial(tmp_path / "12-00-00", bad_line_count=True))
    assert trial.roi_frame_times is None
    assert trial.frame_times.tolist() == [0.0, 0.008]
    assert any("uniform" in message for message in trial.warnings)


def test_trial_session_scanner_and_experiment_folder_are_trial_scoped(tmp_path: Path) -> None:
    experiment = tmp_path / "experiment_1"
    experiment.mkdir()
    first = _trial(experiment / "12-00-00")
    second = _trial(experiment / "12-10-00")
    (experiment / "Reference_Stack.tif").write_bytes(b"not a test image")
    scanner = AOLMicroscopeTrialSource()

    direct = scanner.scan(first, None)
    assert len(direct.items) == 1
    assert direct.items[0].source_epoch == 1_700_000_000.0

    grouped = scanner.scan(experiment, None)
    assert {item.path for item in grouped.items} == {first, second}
    assert len({item.config["_exclusive_group"] for item in grouped.items}) == 1
    assert all(item.path.suffix.lower() != ".tif" for item in grouped.items)


def test_cell_roi_grid_and_traces_use_masks_and_source_map(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    activity = _analysis(folder)
    grid = AOLCellRoiGridSource()
    metadata = grid.open(activity, {"activity_file": str(activity), "trial_folder": str(folder)})
    assert metadata.frame_count == 2
    image = grid.read_frame(1)
    finite = image[np.isfinite(image)]
    np.testing.assert_array_equal(np.sort(finite), [1501, 1501, 3501])
    grid.close()

    traces = AOLRoiTraceLoader()
    traces.open(activity, {"activity_file": str(activity)})
    channels = traces.channels()
    assert [channel.name for channel in channels] == ["roi_1", "roi_2"]
    assert "ribbon ROI 1" in channels[0].description
    assert "ribbon ROIs 1, 3" in channels[1].description
    time, values = next(traces.read_chunks("roi_2"))
    np.testing.assert_allclose(time, [0.0, 0.008])
    np.testing.assert_allclose(values, [2.0, 4.0])

    layout = AOLMicroscopeTrialSource().scan(folder, None)
    assert len(layout.items) == 3


def _match_trial(folder: str, start: float, duration: float = 10.0) -> MicroscopeTrial:
    """Build timing-only metadata for matching tests."""
    return MicroscopeTrial(
        folder=Path(folder),
        start_epoch=start,
        duration=duration,
        roi_files=(),
        repeat=1,
        timepoints=2,
        lines=1,
        width=1,
        channels=1,
        frame_times=np.array([0.0, 1.0]),
        roi_frame_times=None,
        timing_source="fixture",
        warnings=(),
    )


def test_derive_offset_handles_half_hour_zones_and_midnight() -> None:
    day = dt.date(2026, 6, 24)
    start = dt.datetime(2026, 6, 24, 10, 0, tzinfo=dt.UTC).timestamp()
    assert derive_utc_offset([_match_trial("12-30-00", start)], day) == 9_000

    next_day = dt.date(2026, 6, 25)
    before_midnight = dt.datetime(2026, 6, 24, 23, 0, tzinfo=dt.UTC).timestamp()
    assert derive_utc_offset([_match_trial("01-00-00", before_midnight)], next_day) == 7_200


def test_inconsistent_offsets_and_ambiguous_or_distant_trials_do_not_pair() -> None:
    day = dt.date(2026, 6, 24)
    starts = [
        _match_trial("12-00-00", dt.datetime(2026, 6, 24, 10, tzinfo=dt.UTC).timestamp()),
        _match_trial("14-00-00", dt.datetime(2026, 6, 24, 11, tzinfo=dt.UTC).timestamp()),
    ]
    assert derive_utc_offset(starts, day) is None
    camera = dt.datetime(2026, 6, 24, 12, tzinfo=dt.UTC).timestamp()
    duplicate = [_match_trial("10-00-00", camera), _match_trial("10-05-00", camera)]
    assert match_trial(duplicate, camera, 0) is None
    assert match_trial([_match_trial("10-00-00", camera + 100)], camera, 0, 10) is None


def test_match_uses_containment_then_nearest_within_tolerance() -> None:
    trial = _match_trial("10-00-00", 1_700_000_000.0, duration=10)
    contained = match_trial([trial], 1_700_007_202.0, 7_200)
    assert contained is not None
    assert contained.trial is trial
    assert contained.residual_s == 2.0

    near = match_trial([trial], 1_700_007_195.0, 7_200, tolerance_s=10)
    assert near is not None
    assert near.residual_s == -5.0
