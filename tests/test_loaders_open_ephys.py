"""Tests for the Open Ephys session plugin and the neo ingest path behind it.

Every fixture here is synthetic (AGENTS §5).  ``open_ephys_fixture`` writes a
recording small enough for a ``tmp_path`` and real enough that neo opens it, so
these exercise the same path a rig recording takes.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import numpy as np
import pytest

from avialsync.core.registry import LoaderRegistry
from avialsync.core.source import SessionLayout
from avialsync.loaders import open_ephys_format as fmt
from avialsync.loaders.neo_loader import NeoLoader, safe_channel_name
from avialsync.loaders.open_ephys_camera import OpenEphysCameraLoader, read_frame_timestamps
from avialsync.loaders.open_ephys_session import OpenEphysSessionSource, parse_filename_time
from tests.open_ephys_fixture import (
    FIRST_SAMPLE_TIME,
    SOFTWARE_EPOCH_MS,
    RecordingSpec,
    StreamSpec,
    TTLSpec,
    default_spec,
    write_recording,
)

VIDEO_FIXTURES = Path(__file__).parent / "fixtures" / "videos"

#: The fixture's software time is three hours behind its local directory name.
EXPECTED_UTC_OFFSET = 3 * 3600.0

#: Acquisition-clock zero, as UTC: the software epoch minus the first sample.
EXPECTED_ANCHOR = SOFTWARE_EPOCH_MS / 1000.0 - FIRST_SAMPLE_TIME


@pytest.fixture()
def recording(tmp_path: Path) -> Path:
    """A two-stream Open Ephys recording with one TTL line."""
    return write_recording(tmp_path)


@pytest.fixture()
def session_dir(tmp_path: Path) -> Path:
    """A session folder: the record-node tree plus a camera recorded beside it."""
    write_recording(tmp_path)
    (tmp_path / "camera_top2026-06-21T17_54_59.avi").write_bytes(b"not a real container")
    return tmp_path


# ── Dataset discovery ───────────────────────────────────────────────────


def test_find_recordings_reaches_a_nested_record_node(session_dir: Path) -> None:
    """The manifest is four levels below a session folder and must still be found."""
    found = fmt.find_recordings(session_dir)
    assert len(found) == 1
    assert found[0].name == "recording1"
    assert (found[0] / "structure.oebin").is_file()


def test_find_recordings_respects_its_depth_bound(session_dir: Path) -> None:
    """A bound low enough to miss the manifest must return nothing, not search on."""
    assert fmt.find_recordings(session_dir, max_depth=2) == []


def test_find_recordings_skips_sidecar_caches(session_dir: Path) -> None:
    """An .avialcache holds thousands of files and must never be descended into."""
    cache = session_dir / "decoy.avialcache" / "Record Node 1" / "experiment1" / "recording1"
    cache.mkdir(parents=True)
    (cache / "structure.oebin").write_text("{}", encoding="utf-8")
    assert all(".avialcache" not in str(found) for found in fmt.find_recordings(session_dir))


def test_dataset_root_resolves_to_the_recording_not_the_record_node(recording: Path) -> None:
    """``settings.xml`` beside the record node must not capture the search.

    Matching ``*.xml`` first resolved the root two levels above the samples, and
    neo was then pointed at a directory holding only settings.
    """
    record_node = recording.parents[1]
    assert (record_node / "settings.xml").is_file()
    assert NeoLoader._find_dataset_root(record_node) == recording


# ── Who claims what ─────────────────────────────────────────────────────


def test_session_claims_a_folder_holding_ephys_and_cameras(session_dir: Path) -> None:
    assert OpenEphysSessionSource.can_open(session_dir) == 1.0


def test_neo_declines_a_folder_that_also_holds_cameras(session_dir: Path) -> None:
    """The regression: a drop with video beside the ephys must not resolve to one loader.

    ``can_open`` returning non-zero here meant the whole folder imported as ephys
    and the cameras silently vanished; returning zero leaves it to the session.
    """
    assert NeoLoader.can_open(session_dir) == 0.0


def test_neo_claims_the_recording_itself(recording: Path) -> None:
    assert NeoLoader.can_open(recording) == 1.0
    assert NeoLoader.can_open(recording.parents[2]) == 1.0


def test_registry_routes_the_session_folder_to_the_session_plugin(session_dir: Path) -> None:
    registry = LoaderRegistry()
    assert registry.find_best_session(session_dir) is OpenEphysSessionSource
    assert registry.find_best_loader(session_dir) is None


# ── Wall-clock evidence ─────────────────────────────────────────────────


def test_anchor_epoch_is_software_time_minus_the_first_sample(recording: Path) -> None:
    software = fmt.parse_software_epoch(recording)
    assert software == SOFTWARE_EPOCH_MS / 1000.0
    assert fmt.anchor_epoch(software, FIRST_SAMPLE_TIME) == pytest.approx(EXPECTED_ANCHOR)


def test_anchor_epoch_is_zero_without_an_absolute_instant() -> None:
    """No software time means no wall clock, and the session stays on relative time."""
    assert fmt.anchor_epoch(None, 5.0) == 0.0
    assert fmt.anchor_epoch(1.0, None) == 0.0


def test_utc_offset_comes_from_the_recordings_own_two_clocks(recording: Path) -> None:
    """The rig's timezone is derivable in-band, so nothing has to assume one."""
    assert fmt.recording_utc_offset(recording) == pytest.approx(EXPECTED_UTC_OFFSET)


def test_utc_offset_is_rejected_when_it_is_not_a_timezone(tmp_path: Path) -> None:
    """A near-miss is a coincidence; accepting it would shift every camera by an hour."""
    local = datetime.datetime(2026, 6, 21, 17, 54, 56)
    epoch = local.replace(tzinfo=datetime.UTC).timestamp()
    assert fmt.utc_offset_seconds(local, epoch - 3600.0) == pytest.approx(3600.0)
    assert fmt.utc_offset_seconds(local, epoch - 3600.0 - 400.0) is None


def test_utc_offset_needs_a_parsable_session_directory(tmp_path: Path) -> None:
    spec = default_spec()
    spec.record_dir_name = "my_recording"
    recording = write_recording(tmp_path, spec)
    assert fmt.recording_utc_offset(recording) is None


def test_parse_record_dir_time_rejects_other_names() -> None:
    assert fmt.parse_record_dir_time("2026-06-21_17-54-56") is not None
    assert fmt.parse_record_dir_time("Record Node 1") is None
    assert fmt.parse_record_dir_time("2026-06-21") is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("camera_top2026-06-21T17_54_59.avi", datetime.datetime(2026, 6, 21, 17, 54, 59)),
        ("cam-2026-06-21_09-00-01.mp4", datetime.datetime(2026, 6, 21, 9, 0, 1)),
        ("untimed_camera.avi", None),
    ],
)
def test_parse_filename_time(name: str, expected: datetime.datetime | None) -> None:
    assert parse_filename_time(name) == expected


# ── Session layout ──────────────────────────────────────────────────────


def _layout(session_dir: Path) -> SessionLayout:
    return OpenEphysSessionSource().scan(session_dir, LoaderRegistry())


def test_layout_places_everything_on_the_acquisition_clock(session_dir: Path) -> None:
    layout = _layout(session_dir)
    assert layout.anchor_epoch == pytest.approx(EXPECTED_ANCHOR, abs=1e-3)
    assert len(layout.items) == 4  # two streams, one TTL line, one camera


def test_layout_gives_every_stream_its_own_path(session_dir: Path) -> None:
    """A sidecar cache is named after its source path, so shared paths overwrite.

    Two streams pointed at the recording directory would take turns invalidating
    one another's cache, and each import would rebuild what the last one wrote.
    """
    layout = _layout(session_dir)
    paths = [item.path for item in layout.items]
    assert len(set(paths)) == len(paths)

    streams = [item for item in layout.items if item.config.get("stream_id") is not None]
    assert len(streams) == 2
    for item in streams:
        assert item.loader is NeoLoader
        assert item.path.parent.name == "continuous"
        assert item.path.is_dir()
        # The loader still opens the recording; only the cache identity differs.
        assert Path(item.config["root"]).name == "recording1"


def test_layout_routes_ttl_through_neo(session_dir: Path) -> None:
    events = [item for item in _layout(session_dir).items if item.config.get("events")]
    assert len(events) == 1
    assert events[0].loader is NeoLoader
    assert events[0].path.name == "TTL"


def test_layout_places_the_camera_by_its_filename(session_dir: Path) -> None:
    """The camera's local filename resolves onto the acquisition clock.

    ``17:54:59`` at the +03:00 offset the recording itself declares is
    ``14:54:59`` UTC — 1.996 s after the software time the GUI wrote, which is
    the instant the first sample was taken at ``t = 5.0``.
    """
    camera_utc = datetime.datetime(2026, 6, 21, 17, 54, 59, tzinfo=datetime.UTC).timestamp()
    expected = camera_utc - EXPECTED_UTC_OFFSET - EXPECTED_ANCHOR

    cameras = [item for item in _layout(session_dir).items if item.path.suffix == ".avi"]
    assert len(cameras) == 1
    assert cameras[0].loader is OpenEphysCameraLoader
    assert cameras[0].config["start_time"] == pytest.approx(expected, abs=1e-3)
    assert cameras[0].config["start_time"] == pytest.approx(FIRST_SAMPLE_TIME + 1.996, abs=1e-3)


def test_camera_without_a_resolvable_start_lands_on_the_first_sample(tmp_path: Path) -> None:
    """Zero would sit off the front of every stream, which begins several seconds in."""
    spec = default_spec()
    spec.software_epoch_ms = None
    write_recording(tmp_path, spec)
    (tmp_path / "untimed.avi").write_bytes(b"x")

    cameras = [item for item in _layout(tmp_path).items if item.path.suffix == ".avi"]
    assert cameras[0].config["start_time"] == pytest.approx(FIRST_SAMPLE_TIME, abs=1e-3)


def test_layout_attaches_a_timestamp_sidecar_when_one_exists(session_dir: Path) -> None:
    sidecar = session_dir / "camera_top2026-06-21T17_54_59.csv"
    sidecar.write_text("0,0\n1,20000000\n", encoding="utf-8")

    cameras = [item for item in _layout(session_dir).items if item.path.suffix == ".avi"]
    assert Path(cameras[0].config["frame_timestamps"]) == sidecar


def test_layout_ignores_video_inside_the_record_tree(session_dir: Path) -> None:
    """Only cameras beside the recording are session media, not files within it."""
    buried = session_dir / "2026-06-21_17-54-56" / "preview.avi"
    buried.write_bytes(b"x")
    cameras = [item for item in _layout(session_dir).items if item.path.suffix == ".avi"]
    assert [camera.path.name for camera in cameras] == ["camera_top2026-06-21T17_54_59.avi"]


# ── Neo ingest ──────────────────────────────────────────────────────────


def test_stream_channels_share_one_timestamp_array(recording: Path) -> None:
    """The bulk path is what stops a 32-channel stream storing 32 identical clocks."""
    loader = NeoLoader()
    loader.open(recording, {"stream_id": "1"})
    assert [channel.name for channel in loader.channels()] == ["CH1", "CH2"]
    assert loader.read_all_chunks is not None

    chunks = list(loader.read_all_chunks())
    assert chunks
    for chunk in chunks:
        assert set(chunk) == {"CH1", "CH2"}
        times = chunk["CH1"][0]
        assert np.array_equal(chunk["CH2"][0], times)
        assert np.all(np.diff(times) > 0)

    total = sum(len(chunk["CH1"][0]) for chunk in chunks)
    assert total == 2000
    assert chunks[0]["CH1"][0][0] == pytest.approx(FIRST_SAMPLE_TIME)


def test_bulk_path_is_withheld_when_streams_disagree_on_a_clock(recording: Path) -> None:
    """Two rates cannot share a timestamp array, so the importer must not be offered one."""
    loader = NeoLoader()
    loader.open(recording, {})
    assert loader.read_all_chunks is None
    assert len(loader.channels()) == 3  # CH1, CH2, AUX1


def test_channel_by_channel_reads_agree_with_the_bulk_read(recording: Path) -> None:
    loader = NeoLoader()
    loader.open(recording, {"stream_id": "1"})
    assert loader.read_all_chunks is not None
    bulk = np.concatenate([chunk["CH2"][1] for chunk in loader.read_all_chunks()])
    single = np.concatenate([values for _times, values in loader.read_chunks("CH2")])
    assert np.allclose(bulk, single)


def test_unknown_stream_id_is_an_error_not_an_empty_import(recording: Path) -> None:
    from avialsync.core.errors import SourceOpenError

    with pytest.raises(SourceOpenError):
        NeoLoader().open(recording, {"stream_id": "nope"})


def test_ttl_becomes_a_square_wave_at_its_recorded_edges(recording: Path) -> None:
    loader = NeoLoader()
    loader.open(recording, {"events": True})
    assert [channel.name for channel in loader.channels()] == ["TTL-1"]
    assert loader.channels()[0].rate_hz is None

    times, values = next(iter(loader.read_chunks("TTL-1")))
    assert np.all(np.diff(times) > 0), "ingest contract requires strictly increasing times"
    assert np.array_equal(values[0::2], np.ones(5))
    assert np.array_equal(values[1::2], np.zeros(5))
    assert np.allclose(times[values > 0.5], [5.5, 5.6, 5.7, 5.8, 6.5])


def test_ttl_pulses_never_overrun_the_next_edge(tmp_path: Path) -> None:
    """A glitched width must be clamped, not emitted as a decreasing timestamp."""
    spec = default_spec()
    assert spec.ttl is not None
    spec.ttl = TTLSpec(stream="board", rise_times=[5.5, 5.502, 5.6], width=0.05)
    recording = write_recording(tmp_path, spec)

    loader = NeoLoader()
    loader.open(recording, {"events": True})
    times, _values = next(iter(loader.read_chunks("TTL-1")))
    assert np.all(np.diff(times) > 0)


def test_recording_without_ttl_reports_no_event_channels(tmp_path: Path) -> None:
    """An empty event channel used to become a full-length trace of zeros."""
    from avialsync.core.errors import SourceOpenError

    spec = default_spec()
    spec.ttl = None
    recording = write_recording(tmp_path, spec)
    with pytest.raises(SourceOpenError):
        NeoLoader().open(recording, {"events": True})


def test_channel_names_are_legal_filenames_everywhere() -> None:
    """A channel name becomes a cache filename; Windows rejects these characters."""
    assert safe_channel_name("Channels: (Eul-Y Eul-R)") == "Channels_ (Eul-Y Eul-R)"
    assert safe_channel_name('a/b\\c*d?e"f<g>h|i') == "a_b_c_d_e_f_g_h_i"
    assert safe_channel_name("   ") == "channel"


def test_stream_folder_names_come_from_the_manifest(recording: Path) -> None:
    assert sorted(fmt.stream_folder_names(recording)) == ["Board-1.aux", "Board-1.board"]


def test_stream_folder_names_survive_a_corrupt_manifest(recording: Path) -> None:
    (recording / "structure.oebin").write_text("{not json", encoding="utf-8")
    assert fmt.stream_folder_names(recording) == []


def test_manifest_without_continuous_streams_yields_no_folders(recording: Path) -> None:
    (recording / "structure.oebin").write_text(json.dumps({"events": []}), encoding="utf-8")
    assert fmt.stream_folder_names(recording) == []


# ── Camera timing ───────────────────────────────────────────────────────


def test_read_frame_timestamps_returns_seconds_from_the_first_frame(tmp_path: Path) -> None:
    sidecar = tmp_path / "cam.csv"
    sidecar.write_text("63892,2041339938256\n63893,2041361788128\n63895,2041405488000\n")
    times = read_frame_timestamps(sidecar)
    assert times is not None
    assert times[0] == 0.0
    assert times[1] == pytest.approx(0.02184987, abs=1e-8)
    assert len(times) == 3


@pytest.mark.parametrize(
    "content",
    [
        "",
        "1\n2\n",  # no timestamp column
        "0,100\n1,50\n",  # not increasing
        "0,100\n1,nan\n2,300\n",  # not finite
    ],
)
def test_read_frame_timestamps_declines_unusable_sidecars(tmp_path: Path, content: str) -> None:
    """Bad timing evidence costs exact timing; it must never cost the video."""
    sidecar = tmp_path / "cam.csv"
    sidecar.write_text(content)
    assert read_frame_timestamps(sidecar) is None


def test_camera_never_claims_a_file_on_its_own(tmp_path: Path) -> None:
    """Session-routed only: a plain video with an unrelated CSV beside it is not this."""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    assert OpenEphysCameraLoader.can_open(video) == 0.0


def test_camera_maps_frames_to_when_they_were_exposed(tmp_path: Path) -> None:
    """The container's nominal rate is a guess; the sidecar is evidence."""
    video = VIDEO_FIXTURES / "dropped_frames.mp4"
    if not video.exists():
        pytest.skip("Fixtures not generated")

    loader = VideoStandardProbe(video)
    frame_count = loader.frame_count
    # A camera that free-ran faster than the container claims, dropping frames.
    exposures = np.cumsum(np.full(frame_count, 0.02)) - 0.02
    exposures[frame_count // 2 :] += 0.05
    sidecar = tmp_path / "cam.csv"
    sidecar.write_text(
        "\n".join(f"{index},{int(value * 1e9)}" for index, value in enumerate(exposures))
    )

    camera = OpenEphysCameraLoader()
    camera.open(video, {"frame_timestamps": str(sidecar), "start_time": 5.0})
    mapping = camera.exact_time_mapping()
    assert mapping is not None
    master, source = mapping

    assert len(master) == frame_count
    assert master[0] == pytest.approx(5.0)
    assert master[-1] == pytest.approx(5.0 + exposures[-1])
    assert np.all(np.diff(master) > 0)
    assert np.all(np.diff(source) > 0)
    # The container's own timeline is untouched: that is what mpv seeks through.
    assert source[0] == pytest.approx(0.0)


def test_camera_falls_back_to_container_timing_without_a_sidecar(tmp_path: Path) -> None:
    video = VIDEO_FIXTURES / "dropped_frames.mp4"
    if not video.exists():
        pytest.skip("Fixtures not generated")

    camera = OpenEphysCameraLoader()
    camera.open(video, {"start_time": 5.0})
    assert camera.exact_time_mapping() is None
    assert camera.fps() > 0


class VideoStandardProbe:
    """Read a fixture's frame count without duplicating the loader's ffprobe call."""

    def __init__(self, path: Path) -> None:
        from avialsync.loaders.video_standard import VideoStandardLoader

        loader = VideoStandardLoader()
        loader.open(path, {})
        frame_times = loader.frame_times()
        assert frame_times is not None
        self.frame_count = len(frame_times)


def test_unrelated_recording_spec_stays_importable(tmp_path: Path) -> None:
    """A single-stream recording with no TTL is still a valid session."""
    spec = RecordingSpec(
        streams=[StreamSpec(name="only", sample_rate=500.0, channels=["A"], samples=100)],
        ttl=None,
    )
    write_recording(tmp_path, spec)
    layout = _layout(tmp_path)
    assert len(layout.items) == 1
    assert layout.items[0].config["stream_id"] == "0"


# ── Exact-mapping contract at the UI boundary ───────────────────────────


class _MappingLoader:
    """Minimal stand-in for a VideoSource that declares per-frame timing."""

    def __init__(self, mapping: object) -> None:
        self._mapping = mapping

    def exact_time_mapping(self) -> object:
        if isinstance(self._mapping, Exception):
            raise self._mapping
        return self._mapping


@pytest.mark.parametrize(
    "mapping",
    [
        None,
        (np.array([0.0, 1.0]), np.array([0.0])),  # mismatched lengths
        (np.array([0.0]), np.array([0.0])),  # too short to interpolate
        (np.array([0.0, 1.0]), np.array([0.0, np.nan])),  # not finite
        (np.array([0.0, 1.0, 0.5]), np.array([0.0, 1.0, 2.0])),  # master not increasing
        (np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0, 1.0])),  # source not increasing
        RuntimeError("plugin exploded"),
    ],
)
def test_invalid_declared_mappings_are_refused(mapping: object) -> None:
    """This arrives from a plugin, so it is checked rather than trusted.

    A mapping that is not strictly increasing would corrupt every seek made
    through it, and a plugin raising here must cost timing, not the video.
    """
    from avialsync.ui.controllers.video_controller import _declared_exact_mapping

    assert _declared_exact_mapping(_MappingLoader(mapping), "clip.mp4") is None  # type: ignore[arg-type]


def test_valid_declared_mapping_is_accepted() -> None:
    from avialsync.ui.controllers.video_controller import _declared_exact_mapping

    loader = _MappingLoader((np.array([5.0, 5.5, 6.0]), np.array([0.0, 0.4, 0.9])))
    result = _declared_exact_mapping(loader, "clip.mp4")  # type: ignore[arg-type]
    assert result is not None
    master, source = result
    assert master.dtype == np.float64
    assert np.array_equal(master, [5.0, 5.5, 6.0])
    assert np.array_equal(source, [0.0, 0.4, 0.9])


def test_video_source_default_declares_no_exact_mapping() -> None:
    """The hook is additive: a frozen v1 video plugin must be unaffected by it."""
    from avialsync.core.source import VideoSource

    assert VideoSource.exact_time_mapping(object()) is None  # type: ignore[arg-type]
