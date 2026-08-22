"""Tests for AOLVideoExtractionLoader (video-extraction-toolbox exports).

Fixtures mirror the documented on-disk shapes exactly. MATLAB is column-major
and declares HDF5 dataspaces in C order, so every array here is written in the
order h5py *reports* it -- ``metrics/<metric>`` as ``(n_roi, n_col, n_frames)``
and the time vectors as ``(1, n_frames)``. Writing them the MATLAB way round
would make the tests pass against a loader that indexes the data wrongly.
"""

import json
import logging
from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")

FLOW_COLUMNS = [
    "MI",
    "MeanFlow",
    "TopFlow",
    "DirCoh",
    "Brightness",
    "Axial",
    "Lateral",
    "Speed",
    "PeakSpeed",
    "Drift",
]


def write_export(
    directory: Path,
    camera: str = "FaceCam",
    *,
    roi_labels: tuple[str, ...] = ("Jaw", "Whisker"),
    roi_ids: tuple[int, ...] | None = None,
    metrics: dict[str, np.ndarray] | None = None,
    metric_columns: dict[str, list[str]] | None = None,
    metric_column_source: dict[str, str] | None = None,
    n_frames: int = 5,
    absolute_times: np.ndarray | None = None,
    relative_times: np.ndarray | None = None,
    sampling_rate: float = 229.998,
    write_sidecar: bool = True,
    tool: str = "video-extraction-toolbox",
) -> Path:
    """Write one ``<Camera>.mat`` + ``<Camera>.metadata.json`` pair."""
    directory.mkdir(parents=True, exist_ok=True)
    n_roi = len(roi_labels)
    if roi_ids is None:
        roi_ids = tuple(452952480448816 + index for index in range(n_roi))

    if metrics is None:
        # Deterministic values: value = roi*1000 + column*10 + frame
        data = np.zeros((n_roi, len(FLOW_COLUMNS), n_frames), dtype=np.float64)
        for roi in range(n_roi):
            for column in range(len(FLOW_COLUMNS)):
                for frame in range(n_frames):
                    data[roi, column, frame] = roi * 1000 + column * 10 + frame
        # Every real file starts with a NaN in MI: a frame-difference metric
        # has no predecessor at frame 1.
        data[:, 0, 0] = np.nan
        metrics = {"flow_kinematics": data}

    if metric_columns is None:
        metric_columns = {"flow_kinematics": FLOW_COLUMNS}
    if metric_column_source is None:
        metric_column_source = {name: "file" for name in metrics}

    mat_path = directory / f"{camera}.mat"
    with h5py.File(mat_path, "w") as handle:
        group = handle.create_group("metrics")
        for name, array in metrics.items():
            group.create_dataset(name, data=array)
        if absolute_times is not None:
            handle.create_dataset("absolute_times", data=absolute_times.reshape(1, -1))
        if relative_times is not None:
            handle.create_dataset("timestamps", data=relative_times.reshape(1, -1))
        if absolute_times is None and relative_times is None:
            handle.create_dataset(
                "absolute_times",
                data=(1778229326.312 + np.arange(n_frames) / sampling_rate).reshape(1, -1),
            )
        handle.create_dataset("sampling_rate", data=np.array([[sampling_rate]]))
        handle.create_dataset("roi_ids", data=np.asarray(roi_ids, dtype=np.float64).reshape(-1, 1))

    if write_sidecar:
        sidecar = {
            "tool": tool,
            "variant": "default",
            "camera": camera,
            "metrics": list(metrics),
            "metric_columns": metric_columns,
            "metric_column_source": metric_column_source,
            "n_rois": n_roi,
            "roi_labels": list(roi_labels),
            "roi_ids": list(roi_ids),
        }
        (directory / f"{camera}.metadata.json").write_text(json.dumps(sidecar), encoding="utf-8")
    return mat_path


@pytest.fixture()
def export(tmp_path: Path) -> Path:
    return write_export(tmp_path / "video-extraction" / "default")


class TestCanOpen:
    def test_claims_an_export_with_its_sidecar(self, export: Path) -> None:
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        assert AOLVideoExtractionLoader.can_open(export) >= 0.9

    def test_rejects_a_mat_without_a_sidecar(self, tmp_path: Path) -> None:
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        path = write_export(tmp_path / "bare", write_sidecar=False)
        assert AOLVideoExtractionLoader.can_open(path) == 0.0

    def test_rejects_a_sidecar_from_another_tool(self, tmp_path: Path) -> None:
        """A JSON sidecar is not enough; it has to name this toolbox."""
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        path = write_export(tmp_path / "other", tool="something-else")
        assert AOLVideoExtractionLoader.can_open(path) == 0.0

    def test_rejects_malformed_sidecar_without_raising(self, tmp_path: Path) -> None:
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        path = write_export(tmp_path / "broken")
        (tmp_path / "broken" / "FaceCam.metadata.json").write_text("{not json", encoding="utf-8")
        assert AOLVideoExtractionLoader.can_open(path) == 0.0

    def test_rejects_directory_and_non_mat(self, tmp_path: Path) -> None:
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        assert AOLVideoExtractionLoader.can_open(tmp_path) == 0.0
        other = tmp_path / "notes.txt"
        other.write_text("x", encoding="utf-8")
        assert AOLVideoExtractionLoader.can_open(other) == 0.0

    def test_sidecar_path_survives_a_dotted_camera_name(self, tmp_path: Path) -> None:
        """Chained with_suffix would turn Face.Cam.mat into Face.metadata.json."""
        from avialsync.loaders.aol_video_extraction_loader import sidecar_path

        assert sidecar_path(tmp_path / "Face.Cam.mat").name == "Face.Cam.metadata.json"


class TestChannels:
    def test_one_channel_per_roi_column_pair(self, export: Path) -> None:
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        loader = AOLVideoExtractionLoader()
        loader.open(export, {})
        names = [channel.name for channel in loader.channels()]

        assert len(names) == 2 * len(FLOW_COLUMNS)
        assert "Jaw_MI" in names
        assert "Jaw_Speed" in names
        assert "Whisker_Axial" in names

    def test_channel_names_are_safe_as_filenames(self, tmp_path: Path) -> None:
        """A channel name becomes a cache filename verbatim.

        The schema suggests "{roi}/{column}", but PyramidBuilder writes
        `cache_dir / f"{channel_id}_t.npy"` with no sanitisation, so a slash
        would be a path separator on POSIX and rejected outright on Windows.
        """
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        path = write_export(tmp_path / "odd", roi_labels=("Left/Right", 'Odd:Name"'))
        loader = AOLVideoExtractionLoader()
        loader.open(path, {})

        for channel in loader.channels():
            assert not set(channel.name) & set('<>:"/\\|?*'), channel.name

    def test_roi_labels_keep_their_spaces(self, tmp_path: Path) -> None:
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        path = write_export(tmp_path / "spaced", roi_labels=("Caudal Forelimb",))
        loader = AOLVideoExtractionLoader()
        loader.open(path, {})
        assert "Caudal Forelimb_Speed" in [c.name for c in loader.channels()]

    def test_rate_comes_from_sampling_rate(self, export: Path) -> None:
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        loader = AOLVideoExtractionLoader()
        loader.open(export, {})
        assert all(c.rate_hz == pytest.approx(229.998) for c in loader.channels())

    def test_is_not_frame_indexed(self) -> None:
        """It carries its own time axis, unlike the per-ROI v6 store."""
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        assert AOLVideoExtractionLoader().is_frame_indexed() is False

    def test_duplicate_roi_labels_disambiguate_by_roi_id(self, tmp_path: Path) -> None:
        """ROI labels are user-entered and not unique within a camera."""
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        path = write_export(tmp_path / "dupe", roi_labels=("Paw", "Paw"))
        loader = AOLVideoExtractionLoader()
        loader.open(path, {})
        names = [c.name for c in loader.channels()]

        assert len(names) == len(set(names)), "a channel name was silently lost"
        assert len(names) == 2 * len(FLOW_COLUMNS)

    def test_two_metrics_sharing_a_column_name_do_not_collide(self, tmp_path: Path) -> None:
        """motion_index and flow_kinematics both emit MI."""
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        n_frames = 4
        path = write_export(
            tmp_path / "two",
            roi_labels=("Jaw",),
            n_frames=n_frames,
            metrics={
                "motion_index": np.ones((1, 1, n_frames)),
                "flow_kinematics": np.zeros((1, len(FLOW_COLUMNS), n_frames)),
            },
            metric_columns={"motion_index": ["MI"], "flow_kinematics": FLOW_COLUMNS},
        )
        loader = AOLVideoExtractionLoader()
        loader.open(path, {})
        names = [c.name for c in loader.channels()]

        assert len(names) == len(set(names))
        assert len(names) == 1 + len(FLOW_COLUMNS)
        assert any("motion_index" in name for name in names)

    def test_channel_order_is_deterministic(self, tmp_path: Path) -> None:
        """Names become cache filenames and session keys; order must not vary."""
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        n_frames = 3
        path = write_export(
            tmp_path / "order",
            n_frames=n_frames,
            metrics={
                "motion_index": np.ones((2, 1, n_frames)),
                "flow_kinematics": np.zeros((2, len(FLOW_COLUMNS), n_frames)),
            },
            metric_columns={"motion_index": ["MI"], "flow_kinematics": FLOW_COLUMNS},
        )
        runs = []
        for _ in range(4):
            loader = AOLVideoExtractionLoader()
            loader.open(path, {})
            runs.append([c.name for c in loader.channels()])
        assert all(run == runs[0] for run in runs)

    def test_missing_column_names_fall_back_to_numbered_ones(self, tmp_path: Path) -> None:
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        n_frames = 3
        path = write_export(
            tmp_path / "nonames",
            roi_labels=("Jaw",),
            n_frames=n_frames,
            metrics={"custom": np.zeros((1, 2, n_frames))},
            metric_columns={},
            metric_column_source={"custom": "table"},
        )
        loader = AOLVideoExtractionLoader()
        loader.open(path, {})
        assert [c.name for c in loader.channels()] == ["Jaw_custom_1", "Jaw_custom_2"]


class TestReading:
    def test_values_are_indexed_roi_column_frame(self, export: Path) -> None:
        """The whole point of matching h5py's reported axis order."""
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        loader = AOLVideoExtractionLoader()
        loader.open(export, {})
        chunks = list(loader.read_all_chunks())
        assert len(chunks) == 1

        # roi 1 ("Whisker"), column 7 ("Speed"): 1*1000 + 7*10 + frame
        _times, values = chunks[0]["Whisker_Speed"]
        np.testing.assert_allclose(values, 1000 + 70 + np.arange(5))

    def test_the_leading_mi_nan_is_preserved(self, export: Path) -> None:
        """Dropping it would shift the channel one frame against every source."""
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        loader = AOLVideoExtractionLoader()
        loader.open(export, {})
        chunk = next(iter(loader.read_all_chunks()))
        times, values = chunk["Jaw_MI"]

        assert np.isnan(values[0]), "the first MI sample must stay NaN"
        assert len(times) == 5
        assert not np.any(np.isnan(values[1:]))

    def test_absolute_times_are_rebased_onto_the_session_axis(self, tmp_path: Path) -> None:
        """An AOL session's master axis is seconds since midnight UTC (D-045)."""
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        anchor = 1778198400.0  # 2026-05-08T00:00:00Z
        absolute = anchor + 34526.312 + np.arange(4) / 230.0
        path = write_export(tmp_path / "abs", n_frames=4, absolute_times=absolute)

        loader = AOLVideoExtractionLoader()
        loader.open(path, {"anchor_epoch": anchor})
        times, _values = next(iter(loader.read_all_chunks()))["Jaw_MI"]

        np.testing.assert_allclose(times, 34526.312 + np.arange(4) / 230.0, atol=1e-6)

    def test_relative_times_are_shifted_by_the_camera_start(self, tmp_path: Path) -> None:
        """The fallback axis starts at 0.0 and needs the camera start added."""
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        relative = np.arange(4) / 230.0
        path = write_export(tmp_path / "rel", n_frames=4, relative_times=relative)

        loader = AOLVideoExtractionLoader()
        loader.open(path, {"start_epoch": 34526.312, "anchor_epoch": 1778198400.0})
        times, _values = next(iter(loader.read_all_chunks()))["Jaw_MI"]

        assert loader.times_are_epoch is False
        np.testing.assert_allclose(times, 34526.312 + relative, atol=1e-6)

    def test_an_unconfigured_open_keeps_the_files_own_axis(self, export: Path) -> None:
        """Opened alone, outside a session, nothing is shifted."""
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        loader = AOLVideoExtractionLoader()
        loader.open(export, {})
        times, _values = next(iter(loader.read_all_chunks()))["Jaw_MI"]
        assert times[0] == pytest.approx(1778229326.312, abs=1e-3)

    def test_read_chunks_serves_one_channel(self, export: Path) -> None:
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        loader = AOLVideoExtractionLoader()
        loader.open(export, {})
        values = np.concatenate([v for _t, v in loader.read_chunks("Whisker_Drift")])
        np.testing.assert_allclose(values, 1000 + 90 + np.arange(5))

    def test_batches_along_the_frame_axis(self, export: Path, monkeypatch) -> None:
        from avialsync.loaders import aol_video_extraction_loader
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        monkeypatch.setattr(aol_video_extraction_loader, "_BATCH_SIZE", 2)
        loader = AOLVideoExtractionLoader()
        loader.open(export, {})
        chunks = list(loader.read_all_chunks())

        assert len(chunks) == 3  # 5 frames at batch size 2
        times = np.concatenate([c["Jaw_Speed"][0] for c in chunks])
        assert len(times) == 5
        assert np.all(np.diff(times) > 0)

    def test_unknown_channel_raises_typed_error(self, export: Path) -> None:
        from avialsync.core.errors import MissingColumnError
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        loader = AOLVideoExtractionLoader()
        loader.open(export, {})
        with pytest.raises(MissingColumnError):
            list(loader.read_chunks("nope"))

    def test_read_before_open_raises_typed_error(self) -> None:
        from avialsync.core.errors import SourceOpenError
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        with pytest.raises(SourceOpenError):
            list(AOLVideoExtractionLoader().read_all_chunks())


class TestMalformedFiles:
    def test_ragged_metric_is_declined_not_guessed(self, tmp_path: Path) -> None:
        """Mis-indexing would attribute one ROI's numbers to another."""
        from avialsync.core.errors import SourceOpenError
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        path = write_export(tmp_path / "ragged")
        with h5py.File(path, "a") as handle:
            del handle["metrics/flow_kinematics"]
            handle["metrics"].create_dataset(
                "flow_kinematics",
                (2, 1),
                dtype=h5py.special_dtype(ref=h5py.Reference),
            )

        loader = AOLVideoExtractionLoader()
        with pytest.raises(SourceOpenError, match="ragged"):
            loader.open(path, {})

    def test_frame_count_disagreeing_with_timestamps_is_rejected(self, tmp_path: Path) -> None:
        from avialsync.core.errors import SourceOpenError
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        path = write_export(
            tmp_path / "mismatch",
            roi_labels=("Jaw",),
            n_frames=5,
            metrics={"flow_kinematics": np.zeros((1, len(FLOW_COLUMNS), 4))},
        )
        loader = AOLVideoExtractionLoader()
        with pytest.raises(SourceOpenError, match="timestamps"):
            loader.open(path, {})

    def test_backwards_time_raises_the_typed_error(self, tmp_path: Path) -> None:
        """Well-formed exports never do this, but a truncated log can."""
        from avialsync.core.errors import NonMonotonicTimeError
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        times = np.array([100.0, 101.0, 100.5, 102.0])
        path = write_export(tmp_path / "back", n_frames=4, absolute_times=times)
        loader = AOLVideoExtractionLoader()
        with pytest.raises(NonMonotonicTimeError):
            loader.open(path, {})

    def test_missing_metrics_group_is_rejected(self, tmp_path: Path) -> None:
        from avialsync.core.errors import SourceOpenError
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        path = write_export(tmp_path / "nometrics")
        with h5py.File(path, "a") as handle:
            del handle["metrics"]

        loader = AOLVideoExtractionLoader()
        with pytest.raises(SourceOpenError, match="metrics"):
            loader.open(path, {})

    def test_open_without_a_sidecar_explains_itself(self, tmp_path: Path) -> None:
        from avialsync.core.errors import SourceOpenError
        from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

        path = write_export(tmp_path / "nosidecar", write_sidecar=False)
        loader = AOLVideoExtractionLoader()
        with pytest.raises(SourceOpenError, match="sidecar"):
            loader.open(path, {})


def test_inferred_column_names_are_reported(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A 'table' tag means the labels were inferred now, not recorded.

    Half the measured export carried this. Both were correct, but only a
    'file' or 'context' tag is self-certifying, so an inference must not be
    presented silently as a recorded fact.
    """
    from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

    path = write_export(tmp_path / "inferred", metric_column_source={"flow_kinematics": "table"})
    loader = AOLVideoExtractionLoader()
    with caplog.at_level(logging.WARNING):
        loader.open(path, {})

    assert any("table" in record.getMessage() for record in caplog.records)


def test_recorded_column_names_are_not_reported(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from avialsync.loaders.aol_video_extraction_loader import AOLVideoExtractionLoader

    path = write_export(tmp_path / "recorded", metric_column_source={"flow_kinematics": "file"})
    loader = AOLVideoExtractionLoader()
    with caplog.at_level(logging.WARNING):
        loader.open(path, {})

    assert not caplog.records
