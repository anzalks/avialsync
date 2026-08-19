"""Tests for AOLMetricLoader (extracted optical-flow/MI per-ROI MAT files).

Fixture layout follows avialsync_data_schema.md §2-3: a plain single-variable
'-v6' MAT file named '<roi_id>__<metric>.mat', holding 'roi_metric_data' as a
T-frame x C-column numeric array, no time axis, no header.
"""

from pathlib import Path

import numpy as np
import pytest

scipy_io = pytest.importorskip("scipy.io")


def _write_metric_mat(path: Path, data: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scipy_io.savemat(str(path), {"roi_metric_data": data})


@pytest.fixture()
def tmp_motion_index_mat(tmp_path: Path) -> Path:
    """One-column motion_index export, four frames."""
    p = tmp_path / "EyeCam" / "12345__motion_index.mat"
    _write_metric_mat(p, np.array([[0.1], [0.2], [0.3], [0.4]]))
    return p


@pytest.fixture()
def tmp_optical_flow_mat(tmp_path: Path) -> Path:
    """Five-column optical_flow export, three frames."""
    p = tmp_path / "FaceCam" / "999__optical_flow.mat"
    data = np.array(
        [
            [0.1, 1.0, 2.0, 0.5, 100.0],
            [0.2, 1.1, 2.1, 0.6, 101.0],
            [0.3, 1.2, 2.2, 0.7, 102.0],
        ]
    )
    _write_metric_mat(p, data)
    return p


@pytest.fixture()
def tmp_thumbnail_mat(tmp_path: Path) -> Path:
    p = tmp_path / "EyeCam" / "thumbnail.mat"
    _write_metric_mat(p, np.zeros((8, 8)))
    return p


class TestAOLMetricLoaderCanOpen:
    def test_can_open_motion_index(self, tmp_motion_index_mat: Path) -> None:
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        assert AOLMetricLoader.can_open(tmp_motion_index_mat) >= 0.9

    def test_can_open_rejects_thumbnail(self, tmp_thumbnail_mat: Path) -> None:
        """thumbnail.mat carries no roi_id prefix and is a static reference frame."""
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        assert AOLMetricLoader.can_open(tmp_thumbnail_mat) == 0.0

    def test_can_open_rejects_directory(self, tmp_path: Path) -> None:
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        assert AOLMetricLoader.can_open(tmp_path) == 0.0

    def test_can_open_rejects_non_matching_filename(self, tmp_path: Path) -> None:
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        p = tmp_path / "optical_flow_and_MI.mat"  # the primary Analysis_Set file
        p.write_bytes(b"\x00" * 16)
        assert AOLMetricLoader.can_open(p) == 0.0

    def test_can_open_rejects_wrong_variable(self, tmp_path: Path) -> None:
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        p = tmp_path / "EyeCam" / "1__motion_index.mat"
        p.parent.mkdir(parents=True)
        scipy_io.savemat(str(p), {"something_else": np.array([[1.0]])})
        assert AOLMetricLoader.can_open(p) == 0.0


class TestAOLMetricLoaderChannels:
    def test_motion_index_single_channel(self, tmp_motion_index_mat: Path) -> None:
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        loader = AOLMetricLoader()
        loader.open(tmp_motion_index_mat, {"fps": 30.0})
        channels = loader.channels()
        assert [ch.name for ch in channels] == ["MI"]
        assert all(ch.rate_hz == 30.0 for ch in channels)

    def test_optical_flow_five_channels(self, tmp_optical_flow_mat: Path) -> None:
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        loader = AOLMetricLoader()
        loader.open(tmp_optical_flow_mat, {"fps": 60.0})
        names = [ch.name for ch in loader.channels()]
        assert names == ["MI", "MeanFlow", "TopFlow", "DirCoh", "Brightness"]

    def test_is_frame_indexed(self, tmp_motion_index_mat: Path) -> None:
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        assert AOLMetricLoader().is_frame_indexed() is True

    def test_custom_metric_falls_back_to_generic_names(self, tmp_path: Path) -> None:
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        p = tmp_path / "SideCam" / "7__my_custom_score.mat"
        _write_metric_mat(p, np.array([[1.0, 2.0], [3.0, 4.0]]))
        loader = AOLMetricLoader()
        loader.open(p, {"fps": 30.0})
        names = [ch.name for ch in loader.channels()]
        assert names == ["my_custom_score_0", "my_custom_score_1"]

    def test_known_metric_with_wrong_width_falls_back_rather_than_mislabels(
        self, tmp_path: Path
    ) -> None:
        """A version-skewed export with the wrong column count is not mislabeled."""
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        p = tmp_path / "EyeCam" / "3__optical_flow.mat"
        _write_metric_mat(p, np.array([[1.0, 2.0], [3.0, 4.0]]))  # optical_flow wants 5 cols
        loader = AOLMetricLoader()
        loader.open(p, {"fps": 30.0})
        names = [ch.name for ch in loader.channels()]
        assert names == ["optical_flow_0", "optical_flow_1"]
        assert "MeanFlow" not in names


class TestAOLMetricLoaderReadChunks:
    def test_read_all_chunks_values_and_time(self, tmp_optical_flow_mat: Path) -> None:
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        loader = AOLMetricLoader()
        loader.open(tmp_optical_flow_mat, {"fps": 10.0, "start_epoch": 5.0})

        chunks = list(loader.read_all_chunks())
        assert len(chunks) == 1
        t, v = chunks[0]["MI"]
        np.testing.assert_allclose(t, np.array([0, 1, 2]) / 10.0 + 5.0)
        np.testing.assert_allclose(v, [0.1, 0.2, 0.3])

        _, brightness = chunks[0]["Brightness"]
        np.testing.assert_allclose(brightness, [100.0, 101.0, 102.0])

    def test_read_chunks_single_channel(self, tmp_motion_index_mat: Path) -> None:
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        loader = AOLMetricLoader()
        loader.open(tmp_motion_index_mat, {"fps": 30.0})
        t_arr = []
        v_arr = []
        for t, v in loader.read_chunks("MI"):
            t_arr.append(t)
            v_arr.append(v)
        t = np.concatenate(t_arr)
        v = np.concatenate(v_arr)
        np.testing.assert_allclose(t, np.arange(4) / 30.0)
        np.testing.assert_allclose(v, [0.1, 0.2, 0.3, 0.4])

    def test_read_chunks_respects_batch_size(
        self, tmp_motion_index_mat: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from avialsync.loaders import aol_metric_loader
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        monkeypatch.setattr(aol_metric_loader, "_BATCH_SIZE", 2)
        loader = AOLMetricLoader()
        loader.open(tmp_motion_index_mat, {"fps": 30.0})
        chunks = list(loader.read_all_chunks())
        assert len(chunks) == 2  # 4 frames / batch size 2

    def test_read_chunks_invalid_channel_raises_typed_error(
        self, tmp_motion_index_mat: Path
    ) -> None:
        from avialsync.core.errors import MissingColumnError
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        loader = AOLMetricLoader()
        loader.open(tmp_motion_index_mat, {"fps": 30.0})
        with pytest.raises(MissingColumnError):
            list(loader.read_chunks("nonexistent"))

    def test_read_before_open_raises_typed_error(self) -> None:
        from avialsync.core.errors import SourceOpenError
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        loader = AOLMetricLoader()
        with pytest.raises(SourceOpenError):
            list(loader.read_all_chunks())


class TestAOLMetricLoaderOpenValidation:
    def test_open_rejects_missing_variable(self, tmp_path: Path) -> None:
        from avialsync.core.errors import SourceOpenError
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        p = tmp_path / "EyeCam" / "1__motion_index.mat"
        p.parent.mkdir(parents=True)
        scipy_io.savemat(str(p), {"something_else": np.array([[1.0]])})
        loader = AOLMetricLoader()
        with pytest.raises(SourceOpenError, match="roi_metric_data"):
            loader.open(p, {})

    def test_open_rejects_bad_filename(self, tmp_path: Path) -> None:
        from avialsync.core.errors import SourceOpenError
        from avialsync.loaders.aol_metric_loader import AOLMetricLoader

        p = tmp_path / "optical_flow_and_MI.mat"
        _write_metric_mat(p, np.array([[1.0]]))
        loader = AOLMetricLoader()
        with pytest.raises(SourceOpenError, match="roi_id"):
            loader.open(p, {})
