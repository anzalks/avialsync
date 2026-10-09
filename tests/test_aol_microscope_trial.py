"""Synthetic-file tests for AOL microscope trial discovery and mosaic imaging."""

import datetime as dt
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from avialsync.core.errors import ImagingChoiceRequired
from avialsync.core.registry import LoaderRegistry
from avialsync.engine.aol_trial_search import AOLTrialSearchWorker
from avialsync.loaders.aol_cell_roi_grid import AOLCellRoiGridSource
from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
from avialsync.loaders.aol_microscope_trial import (
    MicroscopeTrial,
    is_microscope_trial,
    read_trial,
)
from avialsync.loaders.aol_mosaic_layout import analysis_layout, branch_layout, choose_layout
from avialsync.loaders.aol_ribbon_scan import AOLRibbonScanSource
from avialsync.loaders.aol_roi_trace import AOLRoiTraceLoader
from avialsync.loaders.aol_trial_matching import derive_utc_offset, match_trial


def _cell(handle: h5py.File, name: str, data: object) -> None:
    """Store *data* the way the controller does: a 1x1 cell behind a reference."""
    target = handle.require_group("#refs#").create_dataset(name.replace("/", "_"), data=data)
    cell = handle.create_dataset(name, shape=(1, 1), dtype=h5py.ref_dtype)
    cell[0, 0] = target.ref


def _trial(
    path: Path,
    *,
    bad_line_count: bool = False,
    cells: bool = True,
    start_ms: float = 1_700_000_000_000,
) -> Path:
    """A three-ROI trial; timing fields are MATLAB cells, as in real params.mat."""
    path.mkdir()
    with h5py.File(path / "params.mat", "w") as handle:
        handle.create_group("controller").create_dataset("aol_params", data=[1])
        line = np.arange(12, dtype=np.uint64) * 2
        line = line[:-1] if bad_line_count else line
        if cells:
            _cell(handle, "timings/timing_FIFO/STARTTIME", [[start_ms]])
            _cell(handle, "timings/timing_FIFO/line_time", line[None, :])
        else:
            fifo = handle.create_group("timings/timing_FIFO")
            fifo.create_dataset("STARTTIME", data=[start_ms])
            fifo.create_dataset("line_time", data=line)
        _cell(handle, "timings/summary", [[0.016]])
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
        # The mosaic analysis keeps one correction struct per ribbon ROI, in a cell.
        infos = handle.create_dataset("correction_info", (2, 1), dtype=h5py.ref_dtype)
        for index, name in enumerate(("info_a", "info_b")):
            info = refs.create_group(name)
            info.create_dataset("green_channel", data=[[2]])
            infos[index, 0] = info.ref
    return path


def test_trial_detector_and_line_clock_times(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    assert is_microscope_trial(folder)
    assert not is_microscope_trial(folder / "RibbonScan_ROI_0001_repeat_0001_timepoints_2.mat")

    trial = read_trial(folder)
    assert trial.start_epoch == 1_700_000_000.0
    assert trial.duration == pytest.approx(0.016)
    np.testing.assert_allclose(trial.frame_times, [2.5e-8, 8.5e-8])
    assert trial.roi_frame_times is not None
    assert trial.roi_frame_times.shape == (2, 3)
    assert trial.timing_source.startswith("line clock")
    assert trial.warnings == ()


def test_trial_reads_plain_datasets_as_well_as_matlab_cells(tmp_path: Path) -> None:
    """Real params.mat wraps STARTTIME and line_time in cells; plain values still work."""
    plain = read_trial(_trial(tmp_path / "12-00-00", cells=False))
    cells = read_trial(_trial(tmp_path / "12-10-00"))
    assert plain.start_epoch == cells.start_epoch == 1_700_000_000.0
    np.testing.assert_array_equal(plain.frame_times, cells.frame_times)
    assert cells.timing_source.startswith("line clock")


def test_scan_reads_names_only_while_the_source_verifies_pixels(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    (folder / "RibbonScan_ROI_0003_repeat_0001_timepoints_2.mat").write_bytes(b"not hdf5")
    assert len(read_trial(folder, verify=False).roi_files) == 3
    verified = read_trial(folder)
    assert len(verified.roi_files) == 2
    assert verified.roi_numbers == (1, 2)
    assert any("unreadable" in message for message in verified.warnings)
    # The scanned ROI count still sizes the line clock, so timing survives a lost file.
    assert verified.roi_frame_times is not None


def test_ribbon_source_tiles_and_leaves_unoccupied_pixels_nan(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    source = AOLRibbonScanSource()
    metadata = source.open(folder, {})
    # Shown as MATLAB shows it: each 2-line x 3-pixel plane is a 3 x 2 tile,
    # numbered left to right, then down.
    assert (metadata.frame_count, metadata.height, metadata.width) == (2, 6, 4)
    assert metadata.axes == "CTYX"
    frame = source.read_frame(1, channel=1)
    assert np.all(frame[:3, :2] == 1501)
    assert np.all(frame[:3, 2:] == 2501)
    assert np.all(frame[3:, :2] == 3501)
    assert np.isnan(frame[3:, 2:]).all()
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
    second = _trial(experiment / "12-10-00", start_ms=1_700_000_600_000)
    (experiment / "Reference_Stack.tif").write_bytes(b"not a test image")
    scanner = AOLMicroscopeTrialSource()

    direct = scanner.scan(first, None)
    assert len(direct.items) == 1
    assert direct.items[0].source_epoch == 1_700_000_000.0

    # An experiment is one long session: its trials joined into one source.
    joined = scanner.scan(experiment, None)
    assert [item.path for item in joined.items] == [experiment]
    assert joined.items[0].config["trial_folders"] == [str(first), str(second)]
    assert joined.session_epoch == 1_700_000_000.0
    assert all(item.path.suffix.lower() != ".tif" for item in joined.items)


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


def test_a_single_ribbon_file_opens_raw_at_its_own_line_clock_times(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    path = folder / "RibbonScan_ROI_0002_repeat_0001_timepoints_2.mat"
    assert AOLRibbonScanSource.can_open(path) > 0
    assert LoaderRegistry(plugin_dirs=[]).find_best_loader(path) is AOLRibbonScanSource

    source = AOLRibbonScanSource()
    metadata = source.open(path, {})
    assert (metadata.dtype, metadata.axes, metadata.shape) == ("uint16", "CTYX", (2, 2, 3, 2))
    assert metadata.channel_names == ("Red", "Green")
    trial = read_trial(folder)
    assert trial.roi_frame_times is not None
    np.testing.assert_array_equal(metadata.frame_times, trial.roi_frame_times[:, 1])
    with h5py.File(path, "r") as handle:
        stored = handle["volume"][()]
    frame = source.read_frame(1, channel=1)
    assert frame.dtype == np.uint16
    np.testing.assert_array_equal(frame, stored[1, 1].T)
    source.close()


def test_a_lone_ribbon_file_without_its_trial_asks_for_a_rate(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    lone = tmp_path / "copy"
    lone.mkdir()
    path = lone / "RibbonScan_ROI_0001_repeat_0001_timepoints_2.mat"
    shutil.copy(folder / path.name, path)
    with pytest.raises(ImagingChoiceRequired):
        AOLRibbonScanSource().open(path, {})
    metadata = AOLRibbonScanSource().open(path, {"fps": 4.0})
    np.testing.assert_allclose(metadata.frame_times, [0.0, 0.25])


def test_the_labs_tile_map_places_tiles_when_present(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    activity = _analysis(folder)
    with h5py.File(activity, "r+") as handle:
        roi_map = handle["mosaic_info/source_roi_map"]
        swapped = np.asarray(roi_map[()])
        swapped[swapped == 1], swapped[swapped == 3] = 9, 1
        swapped[swapped == 9] = 3
        roi_map[...] = swapped
    layout = analysis_layout(read_trial(folder))
    assert layout is not None
    assert layout.origins == {1: (3, 0), 2: (0, 2), 3: (0, 0)}
    assert layout.size == (6, 4)
    source = AOLRibbonScanSource()
    source.open(folder, {})
    frame = source.read_frame(0, channel=0)
    assert np.all(frame[3:, :2] == 1000) and np.all(frame[:3, :2] == 3000)


def test_channel_names_follow_the_labs_record(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    assert AOLRibbonScanSource().open(folder, {}).channel_names == ("Red", "Green")
    activity = _analysis(folder)
    with h5py.File(activity, "r+") as handle:
        handle["#refs#/info_a/green_channel"][...] = [[1]]
        handle["#refs#/info_b/green_channel"][...] = [[1]]
    assert AOLRibbonScanSource().open(folder, {}).channel_names == ("Green", "Red")
    with h5py.File(activity, "r+") as handle:
        handle["#refs#/info_b/green_channel"][...] = [[2]]
    # Structs that disagree are no record at all: the rig default stands.
    assert AOLRibbonScanSource().open(folder, {}).channel_names == ("Red", "Green")


def test_a_dropped_mosaic_analysis_opens_as_its_roi_grid(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    activity = _analysis(folder)
    assert AOLCellRoiGridSource.can_open(activity) > 0
    assert LoaderRegistry(plugin_dirs=[]).find_best_loader(activity) is AOLCellRoiGridSource
    assert AOLCellRoiGridSource().open(activity, {}).frame_count == 2


def test_both_trial_imaging_sources_are_registered_for_import_and_restore() -> None:
    names = {cls.__name__ for cls in LoaderRegistry(plugin_dirs=[]).loaders()}
    assert {"AOLRibbonScanSource", "AOLCellRoiGridSource", "AOLRoiTraceLoader"} <= names


def test_trial_search_finds_the_camera_trial_on_its_day(tmp_path: Path) -> None:
    # 1_700_000_000 s is 2023-11-14 22:13:20 UTC; the folder is named 5 s earlier
    # in local time, here UTC, as the controller names its trials.
    experiment = tmp_path / "saved" / "2023-11-14" / "experiment_1"
    experiment.mkdir(parents=True)
    _trial(experiment / "22-13-15")
    worker = AOLTrialSearchWorker(tmp_path / "saved", 1_700_000_002.0, 10.0)
    result = worker.search()
    assert result["status"] == "matched"
    assert result["folder"] == str(experiment / "22-13-15")
    assert result["utc_offset_s"] == 0
    assert result["residual_s"] == pytest.approx(2.0)

    distant = AOLTrialSearchWorker(tmp_path / "saved", 1_700_000_100.0, 10.0).search()
    assert distant["status"] == "ambiguous_or_distant"
    assert AOLTrialSearchWorker(tmp_path / "none", 1_700_000_002.0, 10.0).search()["status"] == (
        "missing_day"
    )


def _thin_mask(folder: Path) -> None:
    """Branches A = ROIs 1, 2 and B = ROI 3; each ROI's dendrite is one stored line."""
    with h5py.File(folder / "thin_mask.mat", "w") as handle:
        refs = handle.create_group("#refs#")
        handle.create_dataset("ROIs", data=[[1.0, 2.0, 3.0]])
        for name in ("masks", "soma_masks", "branch_projection"):
            handle.create_dataset(
                name, (3 if name != "branch_projection" else 2, 1), h5py.ref_dtype
            )
        for roi in (1, 2, 3):
            mask = np.zeros((2, 3), dtype=np.uint8)
            mask[0, :] = 1  # stored line 0, every pixel along the ribbon
            handle["masks"][roi - 1, 0] = refs.create_dataset(f"m{roi}", data=mask).ref
            soma = np.zeros((2, 3), dtype=np.uint8)
            handle["soma_masks"][roi - 1, 0] = refs.create_dataset(f"s{roi}", data=soma).ref
        handle["branch_projection"][0, 0] = refs.create_dataset("a", data=np.zeros((2, 6))).ref
        handle["branch_projection"][1, 0] = refs.create_dataset("b", data=np.zeros((2, 3))).ref


def test_the_tree_is_rebuilt_branch_by_branch_from_the_thin_mask(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    _thin_mask(folder)
    layout = branch_layout(read_trial(folder))
    assert layout is not None
    # Branch A stacks ROIs 1 and 2 down column 0; branch B is column 1.
    assert layout.origins == {1: (0, 0), 2: (3, 0), 3: (0, 2)}
    assert layout.size == (6, 4)
    assert layout.branches == ((1, 2), (3,))
    assert choose_layout(read_trial(folder)).kind == "branches"

    source = AOLRibbonScanSource()
    source.open(folder, {})
    frame = source.read_frame(0, channel=0)
    assert np.all(frame[:3, :2] == 1000) and np.all(frame[3:, :2] == 2000)
    assert np.all(frame[:3, 2:] == 3000) and np.isnan(frame[3:, 2:]).all()


def test_dendrite_roi_view_keeps_only_masked_pixels(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    _thin_mask(folder)
    source = AOLRibbonScanSource()
    metadata = source.open(folder, {"trial_folder": str(folder), "mask": "thin"})
    assert "dendrite ROI masks" in metadata.timing_source
    frame = source.read_frame(0, channel=0)
    # Stored line 0 is display column 0 of each tile.
    assert np.all(frame[:3, 0] == 1000) and np.isnan(frame[:3, 1]).all()
    assert np.all(frame[0:3, 2] == 3000) and np.isnan(frame[0:3, 3]).all()


def test_population_patches_pack_after_the_tree(tmp_path: Path) -> None:
    folder = _trial(tmp_path / "12-00-00")
    _thin_mask(folder)
    activity = _analysis(folder)
    with h5py.File(activity, "r+") as handle:
        handle.create_group("hybrid_layout").create_dataset("first_population_roi", data=[[3.0]])
    layout = branch_layout(read_trial(folder))
    assert layout is not None
    assert layout.branches == ((1, 2), (3,))
    assert layout.origins[3] == (0, 2)


def test_an_experiment_plays_end_to_end_with_blank_gaps(tmp_path: Path) -> None:
    experiment = tmp_path / "experiment_1"
    experiment.mkdir()
    first = _trial(experiment / "12-00-00")
    second = _trial(experiment / "12-10-00", start_ms=1_700_000_600_000)
    source = AOLRibbonScanSource()
    metadata = source.open(experiment, {"trial_folders": [str(first), str(second)]})
    # Two frames per trial plus one blank frame between them.
    assert metadata.frame_count == 5
    assert metadata.frame_times[3] == pytest.approx(600.0 + metadata.frame_times[0])
    assert np.isnan(source.read_frame(2, 0)).all()
    assert np.nanmax(source.read_frame(3, 0)) > 0
    assert "2 trials" in metadata.timing_source

    overlapping = _trial(experiment / "12-20-00", start_ms=1_700_000_600_000)
    with pytest.raises(Exception, match="before the previous one ends"):
        AOLRibbonScanSource().open(experiment, {"trial_folders": [str(second), str(overlapping)]})


def test_the_controller_log_supplies_a_missing_rate(tmp_path: Path) -> None:
    experiment = tmp_path / "experiment_1"
    experiment.mkdir()
    (experiment / "Log.txt").write_text(
        "Recording @ 12-00-00 :  - 3 ROIs - 1x0.5s @4 Hz - MC on\n", encoding="utf-8"
    )
    folder = _trial(experiment / "12-00-00")
    with h5py.File(folder / "params.mat", "r+") as handle:
        del handle["timings/summary"]
        del handle["timings/timing_FIFO/line_time"]
    trial = read_trial(folder)
    assert trial.timing_source == "Log.txt nominal rate (4 Hz)"
    np.testing.assert_allclose(trial.frame_times, [0.0, 0.25])

    lone_dir = experiment / "12-30-00"
    lone_dir.mkdir()
    (experiment / "Log.txt").write_text(
        "Recording @ 12-00-00 : x @4 Hz\nRecording @ 12-30-00 : y @8 Hz\n", encoding="utf-8"
    )
    lone = lone_dir / "RibbonScan_ROI_0001_repeat_0001_timepoints_2.mat"
    shutil.copy(folder / lone.name, lone)
    metadata = AOLRibbonScanSource().open(lone, {})
    np.testing.assert_allclose(metadata.frame_times, [0.0, 0.125])
