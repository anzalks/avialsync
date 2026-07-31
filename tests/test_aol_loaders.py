"""Tests for AOL loaders (encoder log, EKS 3D tracking, session detection)."""

import textwrap
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture()
def tmp_encoder_log(tmp_path: Path) -> Path:
    """Create a minimal encoder_log.txt fixture."""
    content = textwrap.dedent("""\
        09:35:26:082 78602786502 46.298 -0.038
        09:35:26:086 78602787511 46.298 -0.036
        09:35:26:086 78602788499 46.298 -0.033
        09:35:26:086 78602789505 46.187 -0.945
        09:35:26:086 78602790497 46.253 -0.396
    """)
    p = tmp_path / "encoder_log.txt"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture()
def tmp_eks_csv(tmp_path: Path) -> Path:
    """Create a minimal EKS CSV fixture with x/y/z columns and fnum."""
    header = (
        "head_bar_x,head_bar_y,head_bar_z,head_bar_error,"
        "left_paw_x,left_paw_y,left_paw_z,left_paw_error,fnum"
    )
    rows = [
        "-56.76,5.93,461.35,2.13,-23.51,50.25,455.68,9.99,0",
        "-56.74,5.92,461.34,1.99,-23.23,50.21,456.10,9.57,1",
        "-56.73,5.91,461.33,1.95,-22.75,50.11,456.80,8.78,2",
        "-56.73,5.92,461.29,1.97,-22.29,49.98,457.46,8.23,3",
    ]
    p = tmp_path / "pose-3d" / "default_sv" / "_eks.csv"
    p.parent.mkdir(parents=True)
    p.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


@pytest.fixture()
def tmp_eks_csv_no_fnum(tmp_path: Path) -> Path:
    """Create an EKS CSV without a fnum column."""
    header = "paw_x,paw_y,paw_z"
    rows = ["1.0,2.0,3.0", "4.0,5.0,6.0", "7.0,8.0,9.0"]
    p = tmp_path / "_eks_nofnum.csv"
    p.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


@pytest.fixture()
def tmp_aol_session(tmp_path: Path) -> Path:
    """Create a minimal AOL session folder structure."""
    session_dir = tmp_path / "09-35-24"
    session_dir.mkdir()

    # Camera videos (tiny dummy files)
    (session_dir / "FaceCam.mp4").write_bytes(b"\x00" * 100)
    (session_dir / "FrontCam.mp4").write_bytes(b"\x00" * 100)

    # Labeled videos
    labeled = session_dir / "labeled_videos"
    labeled.mkdir()
    (labeled / "FaceCam_eks_labeled.mp4").write_bytes(b"\x00" * 100)
    (labeled / "FrontCam_eks_labeled.mp4").write_bytes(b"\x00" * 100)

    # Timing files
    timing_content = "1\t0.000\t08-05-2026;09:35:26.3120\n2\t4.346\t08-05-2026;09:35:26.3160\n"
    (session_dir / "FaceCam-relative times.txt").write_text(timing_content, encoding="utf-8")
    (session_dir / "FrontCam-relative times.txt").write_text(timing_content, encoding="utf-8")

    # Encoder log
    encoder = "09:35:26:082 78602786502 46.298 -0.038\n09:35:26:086 78602787511 46.298 -0.036\n"
    (session_dir / "encoder_log.txt").write_text(encoder, encoding="utf-8")

    # EKS tracking
    eks_dir = session_dir / "pose-3d" / "default_sv"
    eks_dir.mkdir(parents=True)
    eks_header = "head_x,head_y,head_z,fnum\n"
    eks_data = "1.0,2.0,3.0,0\n4.0,5.0,6.0,1\n"
    (eks_dir / "_eks.csv").write_text(eks_header + eks_data, encoding="utf-8")

    # Trial config
    config = "animal_id: test\nhardware:\n  camera_fps: 230.0\n"
    (session_dir / "trial_config.yml").write_text(config, encoding="utf-8")

    return session_dir


# ── AOLEncoderLoader tests ───────────────────────────────────────────


class TestAOLEncoderLoader:
    def test_can_open_encoder_log(self, tmp_encoder_log: Path) -> None:
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader

        assert AOLEncoderLoader.can_open(tmp_encoder_log) >= 0.9

    def test_can_open_rejects_csv(self, tmp_path: Path) -> None:
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader

        csv_file = tmp_path / "data.csv"
        csv_file.write_text("time,value\n1.0,2.0\n", encoding="utf-8")
        assert AOLEncoderLoader.can_open(csv_file) == 0.0

    def test_can_open_rejects_directory(self, tmp_path: Path) -> None:
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader

        assert AOLEncoderLoader.can_open(tmp_path) == 0.0

    def test_channels(self, tmp_encoder_log: Path) -> None:
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader

        loader = AOLEncoderLoader()
        loader.open(tmp_encoder_log, {})
        channels = loader.channels()
        assert len(channels) == 1
        assert channels[0].name == "encoder_velocity"

    def test_read_chunks(self, tmp_encoder_log: Path) -> None:
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader

        loader = AOLEncoderLoader()
        loader.open(tmp_encoder_log, {})

        all_t = []
        all_v = []
        for t, v in loader.read_chunks("encoder_velocity"):
            all_t.append(t)
            all_v.append(v)

        t_arr = np.concatenate(all_t)
        v_arr = np.concatenate(all_v)

        assert len(t_arr) > 0
        assert len(v_arr) > 0
        # Velocity values should match the last column
        np.testing.assert_allclose(v_arr[0], -0.038, atol=0.001)

    def test_read_chunks_invalid_channel(self, tmp_encoder_log: Path) -> None:
        """Unknown channels raise the typed core error, not a bare KeyError."""
        from avialview.core.errors import MissingColumnError
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader

        loader = AOLEncoderLoader()
        loader.open(tmp_encoder_log, {})
        with pytest.raises(MissingColumnError):
            list(loader.read_chunks("nonexistent"))

    def test_read_chunks_before_open(self) -> None:
        """Using the source before open() reports it, instead of raising AttributeError."""
        from avialview.core.errors import SourceOpenError
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader

        loader = AOLEncoderLoader()
        with pytest.raises(SourceOpenError):
            list(loader.read_chunks("encoder_velocity"))

    def test_open_validates_format(self, tmp_path: Path) -> None:
        """Malformed input raises the typed core error with actionable text."""
        from avialview.core.errors import SourceOpenError
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader

        bad = tmp_path / "bad_encoder.txt"
        bad.write_text("not an encoder log\n", encoding="utf-8")
        loader = AOLEncoderLoader()
        with pytest.raises(SourceOpenError, match="HH:MM:SS:mmm"):
            loader.open(bad, {})

    def test_encoder_axis_is_seconds_since_midnight(self, tmp_encoder_log: Path) -> None:
        """The encoder must stay on the anchor-reduced axis video and EKS use.

        Regression guard for a withdrawn "fix" that added the anchor-date epoch
        here and desynchronised the encoder by a whole date. See the module
        docstring and RECOVERY_PLAN.md V-04.
        """
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader

        loader = AOLEncoderLoader()
        loader.open(tmp_encoder_log, {"anchor_date": "2026-05-08"})
        t = np.concatenate([chunk[0] for chunk in loader.read_chunks("encoder_velocity")])

        # 09:35:26.082 since midnight, NOT an absolute 2026-05-08 epoch.
        expected = 9 * 3600 + 35 * 60 + 26 + 0.082
        np.testing.assert_allclose(t[0], expected, atol=1e-6)

    def test_encoder_crosses_midnight(self, tmp_path: Path) -> None:
        """A recording spanning 00:00 unwraps past 86400 instead of jumping back."""
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader

        content = "23:59:59:500 1 0.0 1.0\n00:00:00:500 2 0.0 2.0\n00:00:01:500 3 0.0 3.0\n"
        path = tmp_path / "encoder_log.txt"
        path.write_text(content, encoding="utf-8")

        loader = AOLEncoderLoader()
        loader.open(path, {})
        t = np.concatenate([chunk[0] for chunk in loader.read_chunks("encoder_velocity")])

        assert np.all(np.diff(t) > 0), f"time went backwards across midnight: {t}"
        np.testing.assert_allclose(t[0], 86399.5, atol=1e-6)
        np.testing.assert_allclose(t[1], 86400.5, atol=1e-6)
        np.testing.assert_allclose(t[2], 86401.5, atol=1e-6)

    def test_encoder_boundary_duplicate_is_collapsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A duplicate timestamp straddling a chunk boundary keeps the last value."""
        from avialview.loaders import aol_encoder_loader
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader

        monkeypatch.setattr(aol_encoder_loader, "_CHUNK_SIZE", 2)
        content = (
            "09:00:00:000 1 0.0 10.0\n"
            "09:00:00:001 2 0.0 11.0\n"
            "09:00:00:001 3 0.0 99.0\n"  # duplicate of the previous, across the boundary
            "09:00:00:002 4 0.0 13.0\n"
        )
        path = tmp_path / "encoder_log.txt"
        path.write_text(content, encoding="utf-8")

        loader = AOLEncoderLoader()
        loader.open(path, {})
        chunks = list(loader.read_chunks("encoder_velocity"))
        t = np.concatenate([c[0] for c in chunks])
        v = np.concatenate([c[1] for c in chunks])

        assert len(t) == len(np.unique(t)), f"duplicate survived the boundary: {t}"
        assert np.all(np.diff(t) > 0)
        # The duplicate pair collapses to its LAST value, per the source contract.
        np.testing.assert_allclose(v[np.searchsorted(t, 9 * 3600 + 0.001)], 99.0)

    def test_encoder_boundary_backward_jump_is_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A backward jump straddling a chunk boundary still raises."""
        from avialview.core.errors import NonMonotonicTimeError
        from avialview.loaders import aol_encoder_loader
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader

        monkeypatch.setattr(aol_encoder_loader, "_CHUNK_SIZE", 2)
        content = (
            "09:00:00:000 1 0.0 10.0\n"
            "09:00:00:005 2 0.0 11.0\n"
            "09:00:00:002 3 0.0 12.0\n"  # goes backwards across the boundary
            "09:00:00:009 4 0.0 13.0\n"
        )
        path = tmp_path / "encoder_log.txt"
        path.write_text(content, encoding="utf-8")

        loader = AOLEncoderLoader()
        loader.open(path, {})
        with pytest.raises(NonMonotonicTimeError):
            list(loader.read_chunks("encoder_velocity"))


# ── AOLEksLoader tests ───────────────────────────────────────────────


class TestAOLEksLoader:
    def test_can_open_eks_csv(self, tmp_eks_csv: Path) -> None:
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        assert AOLEksLoader.can_open(tmp_eks_csv) >= 0.9

    def test_can_open_rejects_plain_csv(self, tmp_path: Path) -> None:
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        csv_file = tmp_path / "plain.csv"
        csv_file.write_text("time,value\n1.0,2.0\n", encoding="utf-8")
        assert AOLEksLoader.can_open(csv_file) == 0.0

    def test_can_open_rejects_directory(self, tmp_path: Path) -> None:
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        assert AOLEksLoader.can_open(tmp_path) == 0.0

    def test_is_frame_indexed(self, tmp_eks_csv: Path) -> None:
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        loader = AOLEksLoader()
        assert loader.is_frame_indexed() is True

    def test_channels_xyz_only(self, tmp_eks_csv: Path) -> None:
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        loader = AOLEksLoader()
        loader.open(tmp_eks_csv, {"fps": 230.0})
        channels = loader.channels()
        names = [ch.name for ch in channels]

        # Should include x/y/z but NOT error columns
        assert "head_bar_x" in names
        assert "head_bar_y" in names
        assert "head_bar_z" in names
        assert "left_paw_x" in names
        assert "head_bar_error" not in names
        assert "left_paw_error" not in names

    def test_read_chunks_with_fnum(self, tmp_eks_csv: Path) -> None:
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        loader = AOLEksLoader()
        loader.open(tmp_eks_csv, {"fps": 230.0})

        all_chunks = list(loader.read_all_chunks())
        assert len(all_chunks) > 0

        # Assert the loader contract across the whole stream rather than the
        # chunk shape: boundary carry retains the final sample for the next
        # batch, so the row count is a property of the stream, not of chunk 0.
        t = np.concatenate([chunk["head_bar_x"][0] for chunk in all_chunks])
        assert len(t) == 4
        # t should be fnum / fps: 0/230, 1/230, 2/230, 3/230
        np.testing.assert_allclose(t, np.arange(4) / 230.0, atol=1e-6)

    def test_read_chunks_without_fnum(self, tmp_eks_csv_no_fnum: Path) -> None:
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        loader = AOLEksLoader()
        loader.open(tmp_eks_csv_no_fnum, {"fps": 30.0})

        channels = loader.channels()
        assert len(channels) == 3  # paw_x, paw_y, paw_z

        all_chunks = list(loader.read_all_chunks())
        assert len(all_chunks) > 0
        t, v = all_chunks[0]["paw_x"]
        # Without fnum, row index is used
        np.testing.assert_allclose(t[0], 0.0, atol=1e-6)
        np.testing.assert_allclose(t[1], 1.0 / 30.0, atol=1e-6)

    def test_channels_report_camera_fps(self, tmp_eks_csv: Path) -> None:
        """EKS rows are one frame each, so rate_hz is the camera fps, not None."""
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        loader = AOLEksLoader()
        loader.open(tmp_eks_csv, {"fps": 230.0})
        assert all(ch.rate_hz == 230.0 for ch in loader.channels())

    def test_unknown_channel_raises_typed_error(self, tmp_eks_csv: Path) -> None:
        from avialview.core.errors import MissingColumnError
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        loader = AOLEksLoader()
        loader.open(tmp_eks_csv, {"fps": 230.0})
        with pytest.raises(MissingColumnError):
            list(loader.read_chunks("no_such_x"))

    def test_read_before_open_raises_typed_error(self) -> None:
        """Reading before open() reports it instead of raising AttributeError."""
        from avialview.core.errors import SourceOpenError
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        loader = AOLEksLoader()
        with pytest.raises(SourceOpenError):
            list(loader.read_all_chunks())

    def test_missing_xyz_columns_raises_typed_error(self, tmp_path: Path) -> None:
        from avialview.core.errors import SourceOpenError
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        path = tmp_path / "_eks.csv"
        path.write_text("alpha,beta\n1.0,2.0\n", encoding="utf-8")
        loader = AOLEksLoader()
        with pytest.raises(SourceOpenError, match="x/y/z"):
            loader.open(path, {})

    def test_bodypart_resolution_is_deterministic(self, tmp_path: Path) -> None:
        """Overlapping skeleton names must resolve identically regardless of hash order.

        'ear' is a suffix of 'left_ear'; longest-first matching must always pick
        'left_ear'. Iterating a set here previously made the answer depend on
        PYTHONHASHSEED, which changed channel names, cache keys and session files.
        """
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        header = "model_left_ear_x,model_left_ear_y,model_left_ear_z"
        path = tmp_path / "_eks.csv"
        path.write_text(header + "\n1.0,2.0,3.0\n", encoding="utf-8")

        skeleton = [("ear", "left_ear"), ("left_ear", "nose")]
        names = []
        for _ in range(5):
            loader = AOLEksLoader()
            loader.open(path, {"skeleton": skeleton})
            names.append([ch.name for ch in loader.channels()])

        assert all(n == names[0] for n in names)
        assert names[0] == ["left_ear_x", "left_ear_y", "left_ear_z"]

    def test_boundary_duplicate_is_collapsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A duplicate frame number straddling a batch boundary keeps the last value."""
        from avialview.loaders import aol_eks_loader
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        monkeypatch.setattr(aol_eks_loader, "_BATCH_SIZE", 2)
        header = "paw_x,paw_y,paw_z,fnum"
        rows = ["1.0,1.0,1.0,0", "2.0,2.0,2.0,1", "9.0,9.0,9.0,1", "4.0,4.0,4.0,2"]
        path = tmp_path / "_eks.csv"
        path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")

        loader = AOLEksLoader()
        loader.open(path, {"fps": 1.0})
        chunks = list(loader.read_all_chunks())
        t = np.concatenate([c["paw_x"][0] for c in chunks])
        v = np.concatenate([c["paw_x"][1] for c in chunks])

        assert len(t) == len(np.unique(t)), f"duplicate survived the boundary: {t}"
        assert np.all(np.diff(t) > 0)
        np.testing.assert_allclose(v[np.searchsorted(t, 1.0)], 9.0)

    def test_boundary_backward_jump_is_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A backward frame number straddling a batch boundary still raises."""
        from avialview.core.errors import NonMonotonicTimeError
        from avialview.loaders import aol_eks_loader
        from avialview.loaders.aol_eks_loader import AOLEksLoader

        monkeypatch.setattr(aol_eks_loader, "_BATCH_SIZE", 2)
        header = "paw_x,paw_y,paw_z,fnum"
        rows = ["1.0,1.0,1.0,0", "2.0,2.0,2.0,5", "3.0,3.0,3.0,2", "4.0,4.0,4.0,9"]
        path = tmp_path / "_eks.csv"
        path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")

        loader = AOLEksLoader()
        loader.open(path, {"fps": 1.0})
        with pytest.raises(NonMonotonicTimeError):
            list(loader.read_all_chunks())


# ── AOL Session detection tests ──────────────────────────────────────


class TestAOLSessionDetection:
    def test_is_aol_session(self, tmp_aol_session: Path) -> None:
        from avialview.loaders.aol_session_loader import is_aol_session

        assert is_aol_session(tmp_aol_session) is True

    def test_is_aol_session_rejects_plain_dir(self, tmp_path: Path) -> None:
        from avialview.loaders.aol_session_loader import is_aol_session

        assert is_aol_session(tmp_path) is False

    def test_is_aol_session_rejects_file(self, tmp_encoder_log: Path) -> None:
        from avialview.loaders.aol_session_loader import is_aol_session

        assert is_aol_session(tmp_encoder_log) is False

    def test_build_manifest(self, tmp_aol_session: Path) -> None:
        from avialview.loaders.aol_session_loader import build_manifest

        manifest = build_manifest(tmp_aol_session)

        # Raw footage wins: the overlay is drawn live, so a labeled_videos
        # render would show every marker twice and could not be toggled.
        assert len(manifest.videos) == 2
        assert not any("labeled" in str(v) for v in manifest.videos)

        # Camera labels extracted from filename
        assert "FaceCam" in manifest.camera_labels
        assert "FrontCam" in manifest.camera_labels

        # EKS file found
        assert len(manifest.eks_files) == 1
        assert "_eks.csv" in str(manifest.eks_files[0])

        # Encoder found
        assert manifest.encoder_file is not None

        # Timing files
        assert "FaceCam" in manifest.timing_files
        assert "FrontCam" in manifest.timing_files

        # FPS from trial_config.yml
        assert manifest.camera_fps == 230.0

    def test_build_manifest_uses_raw_videos(self, tmp_path: Path) -> None:
        """Root MP4s are the normal case."""
        from avialview.loaders.aol_session_loader import build_manifest

        session = tmp_path / "session"
        session.mkdir()
        (session / "FaceCam.mp4").write_bytes(b"\x00" * 100)
        (session / "FaceCam-relative times.txt").write_text("1\t0.0\tdate\n", encoding="utf-8")
        (session / "encoder_log.txt").write_text("09:35:26:082 1234 46.0 -0.5\n", encoding="utf-8")

        manifest = build_manifest(session)
        assert len(manifest.videos) == 1
        assert manifest.videos[0].name == "FaceCam.mp4"

    def test_build_manifest_falls_back_to_labeled_when_no_raw_footage(self, tmp_path: Path) -> None:
        """A session with only rendered videos must still open."""
        from avialview.loaders.aol_session_loader import build_manifest

        session = tmp_path / "session"
        labeled = session / "labeled_videos"
        labeled.mkdir(parents=True)
        (labeled / "FaceCam_labeled.mp4").write_bytes(b"\x00" * 100)

        manifest = build_manifest(session)

        assert len(manifest.videos) == 1
        assert "labeled" in str(manifest.videos[0])
        assert manifest.camera_labels == ["FaceCam"]

    def test_trial_config_parsing(self, tmp_aol_session: Path) -> None:
        from avialview.loaders.aol_session_loader import build_manifest

        manifest = build_manifest(tmp_aol_session)
        assert manifest.trial_config.get("animal_id") == "test"
        hw = manifest.trial_config.get("hardware")
        assert isinstance(hw, dict)
        assert hw.get("camera_fps") == 230.0
