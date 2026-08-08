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
from avialsync.loaders.open_ephys_session import OpenEphysSessionSource, parse_filename_time
from avialsync.loaders.video_standard import VideoStandardLoader, read_frame_timestamps
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
    assert cameras[0].loader is VideoStandardLoader
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
    evidence = read_frame_timestamps(sidecar)
    assert evidence is not None
    times = evidence.times
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


def test_sidecar_timing_is_never_auto_discovered(tmp_path: Path) -> None:
    """A same-stem CSV beside a video is at least as likely to be pose output.

    The session applies the sidecar because it knows the rig's convention; the
    video loader must not go looking, or a DLC export would be reinterpreted as
    frame timestamps.
    """
    video = VIDEO_FIXTURES / "dropped_frames.mp4"
    if not video.exists():
        pytest.skip("Fixtures not generated")

    decoy = tmp_path / "dropped_frames.csv"
    decoy.write_text("scorer,x,y\n0,1,2\n", encoding="utf-8")

    loader = VideoStandardLoader()
    loader.open(video, {})
    assert loader.exact_time_mapping() is None


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

    camera = VideoStandardLoader()
    camera.open(video, {"frame_timestamps": str(sidecar), "start_time": 5.0})
    mapping = camera.exact_time_mapping()
    assert mapping is not None
    master, source = mapping

    assert len(master) == frame_count
    assert master[0] == pytest.approx(5.0)
    assert master[-1] == pytest.approx(5.0 + exposures[-1])
    assert np.all(np.diff(master) > 0)
    assert np.all(np.diff(source) > 0)
    # The container's own timeline is untouched: that is what the decoder seeks through.
    assert source[0] == pytest.approx(0.0)


def test_camera_falls_back_to_container_timing_without_a_sidecar(tmp_path: Path) -> None:
    video = VIDEO_FIXTURES / "dropped_frames.mp4"
    if not video.exists():
        pytest.skip("Fixtures not generated")

    camera = VideoStandardLoader()
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


# ── Drag-and-drop robustness ────────────────────────────────────────────


def _drop(paths: list[Path]) -> tuple[list, object]:
    from avialsync.engine.drop_worker import DropScanWorker

    worker = DropScanWorker(paths, LoaderRegistry())
    collected: list = []
    for path in paths:
        collected.extend(worker._collect_drop_candidates(path))
    return collected, worker._layout


def test_drop_never_descends_into_a_sidecar_cache(tmp_path: Path) -> None:
    """Re-dropping a folder you already imported must not offer its cache back.

    A committed sidecar holds one ``.npy`` per channel and pyramid level — 482
    files for a single 32-channel stream — and every one of them arrived in the
    review dialog as an unrecognised candidate.
    """
    (tmp_path / "cam.mp4").write_bytes(b"x")
    cache = tmp_path / "cam.mp4.avialcache"
    cache.mkdir()
    for index in range(40):
        np.save(cache / f"ch{index}_t.npy", np.arange(3.0))
    (cache / "import.json").write_text("{}", encoding="utf-8")
    staging = tmp_path / ".tmp_avialcache_abc123"
    staging.mkdir()
    (staging / "leftover.npy").write_bytes(b"x")

    candidates, _layout = _drop([tmp_path])

    assert [path.name for path, _loader, _config in candidates] == ["cam.mp4"]


def test_first_session_of_a_multi_session_drop_owns_the_timeline(tmp_path: Path) -> None:
    """Two sessions dropped together load everything, but one anchor must win.

    Whichever was scanned last used to own `anchor_epoch`, which is arbitrary and
    silent. First-wins is at least deterministic and matches the order the user
    dropped them in.
    """
    first, second = tmp_path / "a", tmp_path / "b"
    write_recording(first)

    later = default_spec()
    later.record_dir_name = "2026-06-22_10-00-00"
    later.software_epoch_ms = SOFTWARE_EPOCH_MS + 86_400_000
    write_recording(second, later)

    candidates, layout = _drop([first, second])

    # Two streams and one TTL line each.
    assert len(candidates) == 6, "every stream of both sessions still loads"
    assert layout.anchor_epoch == pytest.approx(EXPECTED_ANCHOR, abs=1e-3)


def test_an_empty_folder_yields_nothing_rather_than_failing(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    candidates, layout = _drop([empty])
    assert candidates == []
    assert layout.anchor_epoch == 0.0


def test_an_unrecognised_file_is_offered_unresolved_not_dropped(tmp_path: Path) -> None:
    """The review dialog lets the user name a loader, so an unknown file is a row."""
    (tmp_path / "thing.xyz").write_bytes(b"x")
    candidates, _layout = _drop([tmp_path])
    assert len(candidates) == 1
    assert candidates[0][1] is None


# ── The container/sidecar disagreement has to be visible ────────────────


def test_camera_metadata_reports_the_rate_it_was_actually_exposed_at(tmp_path: Path) -> None:
    """Rates come from the sidecar; the container's claim stays beside them.

    Computed from container timestamps this reads "CFR 30.000 · measured 30.000",
    because the container really is CFR — which hides the very discrepancy that
    makes the sidecar necessary.
    """
    video = VIDEO_FIXTURES / "dropped_frames.mp4"
    if not video.exists():
        pytest.skip("Fixtures not generated")

    plain = VideoStandardProbe(video)
    exposures = np.cumsum(np.full(plain.frame_count, 0.02)) - 0.02
    exposures[plain.frame_count // 2 :] += 0.04  # a dropped frame halfway through
    sidecar = tmp_path / "cam.csv"
    sidecar.write_text(
        "\n".join(f"{i},{int(v * 1e9)}" for i, v in enumerate(exposures)), encoding="utf-8"
    )

    camera = VideoStandardLoader()
    camera.open(video, {"frame_timestamps": str(sidecar), "start_time": 5.0})
    metadata = camera.video_metadata()

    assert metadata.is_vfr is True
    assert metadata.nominal_fps == pytest.approx(30.0), "the container's claim stays visible"
    assert metadata.measured_fps == pytest.approx(50.0, rel=0.02), "sidecar says ~50 Hz"
    assert metadata.max_frame_rate == pytest.approx(50.0, rel=0.02)
    assert metadata.min_frame_rate < 20.0, "the dropped frame shows as a slow interval"
    assert metadata.duration == pytest.approx(exposures[-1], abs=1e-6)
    assert metadata.frame_count == plain.frame_count


def test_camera_metadata_is_unchanged_without_a_sidecar() -> None:
    video = VIDEO_FIXTURES / "dropped_frames.mp4"
    if not video.exists():
        pytest.skip("Fixtures not generated")

    camera = VideoStandardLoader()
    camera.open(video, {})
    assert camera.video_metadata().nominal_fps == pytest.approx(30.0)


def test_displayed_rate_is_reported_on_the_master_timeline() -> None:
    """The "now" figure is printed beside a master-axis range and must share its axis.

    Presentation timestamps are source time, so a container claiming 30 fps reads
    as 30 however fast the camera really ran. The mapping's slope converts it.
    """
    from avialsync.ui.video_timing import displayed_frame_rate

    source_times = np.arange(10, dtype=np.float64) / 30.0

    assert displayed_frame_rate(source_times, 0.5, True, 30.0, 30.0) == pytest.approx(30.0)
    # Source runs at 30 fps but covers master time 1.526x faster: 45.8 Hz exposures.
    scaled = displayed_frame_rate(source_times, 0.5, True, 30.0, 30.0, rate_scale=1.526)
    assert scaled == pytest.approx(45.8, abs=0.1)
    # A constant-rate video is unaffected, mapping or not.
    assert displayed_frame_rate(source_times, 0.5, False, 30.0, 30.0, 1.526) == pytest.approx(30.0)


# ── Naming is uniform across plugin contracts ───────────────────────────


def test_a_rig_plugin_is_named_system_then_kind() -> None:
    """One rig must read the same wherever it appears, beside the others.

    "Rig Camera (sidecar-timed)" described the implementation: it sorted nowhere
    near its own session's rows and named no folder the user recognised.
    """
    from avialsync.loaders.aol_eks_loader import AOLEksLoader
    from avialsync.loaders.aol_encoder_loader import AOLEncoderLoader
    from avialsync.loaders.aol_session_loader import AOLSessionSource

    assert AOLEncoderLoader.display_name() == "AOL Encoder Log"
    assert AOLEksLoader.display_name() == "AOL 3D Tracking"
    assert AOLSessionSource.display_name() == "AOL Session"

    assert OpenEphysSessionSource.display_name() == "Open Ephys Session"
    # A video is a video whichever rig recorded it: the type names the data,
    # never the system. Which rig it came from is the session's business, and
    # it is already in the row's own label.
    assert VideoStandardLoader.display_name() == "Video"


def test_every_session_plugin_can_name_itself() -> None:
    """`SessionSource` had no naming hook, so a session had no name to show."""
    from avialsync.core.source import SessionSource, _Nameable

    assert issubclass(SessionSource, _Nameable)
    for session_cls in LoaderRegistry().sessions():
        assert session_cls.display_name().strip()


@pytest.mark.parametrize(
    ("class_name", "expected"),
    [
        ("AOLSessionSource", "AOL Session"),
        ("AOLEksLoader", "AOL Eks"),
        ("OpenEphysSessionSource", "Open Ephys Session"),
        ("CSVLoader", "CSV"),
        ("NeoLoader", "Neo"),
        ("Loader", "Loader"),
    ],
)
def test_derived_names_break_acronyms_correctly(class_name: str, expected: str) -> None:
    """The fallback names any plugin that does not override, so it must read well.

    The old rule split only after a lower-case letter, so it never broke a run of
    capitals: ``AOLSessionSource`` came back as "AOLSession" — the very case the
    docstring used as its example.
    """
    from avialsync.core.source import default_display_name

    assert default_display_name(type(class_name, (), {})) == expected


def test_no_two_plugins_share_a_display_name() -> None:
    """A duplicate name makes the review dialog's dropdown ambiguous to pick from."""
    registry = LoaderRegistry()
    labels = [cls.display_name() for cls in registry.loaders()]
    labels += [alias for cls in registry.loaders() for alias in cls.display_aliases()]
    assert len(labels) == len(set(labels)), f"duplicate format labels: {labels}"


# ── The dialog has to say which row costs minutes ───────────────────────


def test_session_labels_name_each_stream_by_shape(session_dir: Path) -> None:
    """Four streams read by one loader, under directories named for the board.

    Filename and detected type together still did not say which row was the
    32-channel 30 kHz one — the only row whose import costs minutes and
    gigabytes. The session knows; the dialog could only re-derive a path.
    """
    labels = {item.label for item in _layout(session_dir).items}
    assert "board — 2 ch @ 1 kHz" in labels
    assert "aux — 1 ch @ 100 Hz" in labels
    assert any(label.startswith("TTL events") for label in labels)
    assert any(label.endswith("— camera") for label in labels)


def test_a_label_is_not_part_of_the_cache_key(session_dir: Path) -> None:
    """Rewording a table cell must never invalidate a multi-gigabyte sidecar."""
    for item in _layout(session_dir).items:
        assert "label" not in item.config


def test_dialog_shows_session_labels_and_falls_back_to_filenames(session_dir: Path) -> None:
    from avialsync.ui.batch_import_dialog import BatchImportDialog

    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])

    layout = _layout(session_dir)
    candidates = [(item.path, item.loader, dict(item.config)) for item in layout.items]
    labels = {str(item.path): item.label for item in layout.items if item.label}
    # A path the session said nothing about must still get a row name.
    unlabelled = session_dir / "stray.csv"
    unlabelled.write_text("time,v\n0,1\n", encoding="utf-8")
    candidates.append((unlabelled, None, None))

    dialog = BatchImportDialog(candidates, labels=labels)
    shown = {dialog._table.item(row, 0).text() for row in range(dialog._table.rowCount())}

    assert "board — 2 ch @ 1 kHz" in shown
    assert "stray.csv" in shown, "an unlabelled candidate falls back to its filename"
    dialog.deleteLater()


def test_rates_read_the_way_an_experimenter_says_them() -> None:
    from avialsync.loaders.open_ephys_session import _format_rate

    assert _format_rate(30000.0) == "30 kHz"
    assert _format_rate(1000.0) == "1 kHz"
    assert _format_rate(100.0) == "100 Hz"
    assert _format_rate(2500.0) == "2.5 kHz"


def test_a_type_names_the_data_never_the_rig(session_dir: Path) -> None:
    """One reader serves many kinds, so the type must not be the reader's name.

    Every stream of a recording comes through neo, which typed an 18-channel IMU
    — Euler angles, acceleration, gravity, temperature — as "Electrophysiology
    Data" purely because neo is what reads it. And a camera is a camera whichever
    rig recorded it; "Open Ephys Video" named the system, not the data.
    """
    kinds = {item.label: item.kind for item in _layout(session_dir).items}

    assert kinds["aux — 1 ch @ 100 Hz"] == ""
    assert kinds["camera_top2026-06-21T17_54_59.avi — camera"] == "Video"
    assert any(kind == "TTL Events" for kind in kinds.values())

    # Every declared kind must be a label its own loader actually offers, or the
    # dialog has nothing to select and silently falls back.
    offered = set(NeoLoader.display_aliases()) | {NeoLoader.display_name()}
    offered |= {VideoStandardLoader.display_name()}
    for kind in kinds.values():
        assert not kind or kind in offered, f"{kind!r} is not offered by any loader"


def test_imu_and_diagnostic_streams_are_typed_by_what_they_are(tmp_path: Path) -> None:
    from tests.open_ephys_fixture import RecordingSpec, StreamSpec

    spec = RecordingSpec(
        streams=[
            StreamSpec(name="IMU_port_A", sample_rate=100.0, channels=["Eul-Y"], samples=100),
            StreamSpec(name="memory_usage", sample_rate=100.0, channels=["MEM"], samples=100),
            StreamSpec(name="acquisition_board", sample_rate=30000.0, channels=["CH1"], samples=99),
        ],
        ttl=None,
    )
    write_recording(tmp_path, spec)
    kinds = {item.label.split(" —")[0]: item.kind for item in _layout(tmp_path).items}

    assert kinds["IMU_port_A"] == "IMU / Motion Data"
    assert kinds["memory_usage"] == "Auxiliary / Diagnostics"
    assert kinds["acquisition_board"] == "", "ephys falls through to the reader's own name"


def test_dialog_preselects_the_declared_kind(session_dir: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from avialsync.ui.batch_import_dialog import BatchImportDialog

    QApplication.instance() or QApplication([])
    layout = _layout(session_dir)
    dialog = BatchImportDialog(
        [(item.path, item.loader, dict(item.config)) for item in layout.items],
        labels={str(item.path): item.label for item in layout.items if item.label},
        kinds={str(item.path): item.kind for item in layout.items if item.kind},
    )
    shown = {
        dialog._table.item(row, 0).text(): dialog._combos[row].currentText()
        for row in range(dialog._table.rowCount())
    }
    assert shown["camera_top2026-06-21T17_54_59.avi — camera"] == "Video"
    assert [text for name, text in shown.items() if name.startswith("TTL")] == ["TTL Events"]
    # Selecting a kind must not change which loader actually runs.
    for _path, loader_cls, _config in dialog.get_selections():
        assert loader_cls in (NeoLoader, VideoStandardLoader)
    dialog.deleteLater()


# ── Failure has to be legible ───────────────────────────────────────────


def test_csv_loader_refuses_a_directory_with_something_actionable(session_dir: Path) -> None:
    """A recording's TTL *directory* sits beside an alias named "…Events (CSV)".

    Choosing it by hand let polars raise IsADirectoryError, which surfaced as
    "Failed to parse CSV" plus a console traceback and nothing to act on.
    """
    from avialsync.core.errors import FileUnreadableError
    from avialsync.loaders.csv_loader import CSVLoader

    ttl = next(session_dir.rglob("*/TTL"))
    assert ttl.is_dir()
    assert CSVLoader.can_open(ttl) == 0.0

    with pytest.raises(FileUnreadableError) as excinfo:
        CSVLoader().open(ttl, {})
    assert "folder, not a CSV file" in str(excinfo.value)


def test_csv_loader_declines_a_directory_named_like_a_csv(tmp_path: Path) -> None:
    """`.suffix` alone said yes: a directory can be called anything."""
    from avialsync.loaders.csv_loader import CSVLoader

    directory = tmp_path / "events.csv"
    directory.mkdir()
    assert CSVLoader.can_open(directory) == 0.0


def test_a_kind_matching_nothing_falls_back_rather_than_skipping(session_dir: Path) -> None:
    """Index 0 of the combo is "Skip", so an unmatched kind used to drop the row.

    The user would have seen it listed, left it alone, and had it silently not
    import — the worst of the available failures, because nothing reports it.
    """
    from PySide6.QtWidgets import QApplication

    from avialsync.ui.batch_import_dialog import BatchImportDialog

    QApplication.instance() or QApplication([])
    layout = _layout(session_dir)
    candidates = [(item.path, item.loader, dict(item.config)) for item in layout.items]
    bogus = {str(item.path): "No Such Kind" for item in layout.items}

    dialog = BatchImportDialog(candidates, kinds=bogus)
    selected = dialog.get_selections()

    assert len(selected) == len(candidates), "every row must still resolve to a loader"
    for _path, loader_cls, _config in selected:
        assert loader_cls is not None
    dialog.deleteLater()


# ── Dropped exposures are missing data, but they are not gaps ───────────


def test_dropped_exposures_are_counted_from_the_frame_counter(tmp_path: Path) -> None:
    """The counter is the only proof they existed.

    Timestamps alone cannot tell "a frame was dropped here" from "the camera ran
    slower here", so discarding that column lost a quarter of one real take with
    nothing anywhere to say so.
    """
    from avialsync.loaders.video_standard import read_frame_timestamps

    sidecar = tmp_path / "cam.csv"
    # Counter steps of 2 are one lost exposure each; three lost in total.
    sidecar.write_text("10,0\n11,20000000\n13,60000000\n14,80000000\n17,140000000\n")

    evidence = read_frame_timestamps(sidecar)
    assert evidence is not None
    assert len(evidence.times) == 5
    assert evidence.dropped == 3


def test_a_restarting_counter_reports_no_drops_rather_than_nonsense(tmp_path: Path) -> None:
    from avialsync.loaders.video_standard import read_frame_timestamps

    sidecar = tmp_path / "cam.csv"
    sidecar.write_text("10,0\n11,20000000\n0,40000000\n1,60000000\n")
    evidence = read_frame_timestamps(sidecar)
    assert evidence is not None
    assert evidence.dropped == 0


def test_single_frame_drops_are_far_below_the_gap_threshold() -> None:
    """Why dropped frames never appear as gap bars, and should not.

    A gap means "no coverage here, do not draw across it". A dropped frame
    leaves the timeline covered and every stored frame correctly placed; only
    resolution is lost. One drop spans two sample intervals against a threshold
    of ten, so `build_gap_mask` finds nothing — and marking thousands of them
    would bury the trace rather than inform it.
    """
    from avialsync.core.pyramid import build_gap_mask

    interval = 0.02185
    times = np.arange(500, dtype=np.float64) * interval
    times[250:] += interval  # one exposure dropped halfway through

    assert build_gap_mask(times).sum() == 0
    assert float(np.max(np.diff(times))) == pytest.approx(2 * interval)
    assert 2 * interval < 10 * float(np.median(np.diff(times)))


def test_dropped_frames_reach_the_readout_and_raise_a_flag(tmp_path: Path) -> None:
    from avialsync.core.inspection import IntegrityFlags
    from avialsync.ui.source_properties import _frame_count_text

    video = VIDEO_FIXTURES / "dropped_frames.mp4"
    if not video.exists():
        pytest.skip("Fixtures not generated")

    stored = VideoStandardProbe(video).frame_count
    counter = np.arange(stored) * 2  # every other exposure lost
    sidecar = tmp_path / "cam.csv"
    sidecar.write_text(
        "\n".join(f"{c},{int(i * 0.02 * 1e9)}" for i, c in enumerate(counter)), encoding="utf-8"
    )

    loader = VideoStandardLoader()
    loader.open(video, {"frame_timestamps": str(sidecar), "start_time": 0.0})
    metadata = loader.video_metadata()

    assert metadata.dropped_frames == stored - 1
    assert "dropped" in _frame_count_text(metadata)
    assert IntegrityFlags(frames_dropped=metadata.dropped_frames > 0).any_flag


def test_a_video_without_a_sidecar_reports_no_drops() -> None:
    video = VIDEO_FIXTURES / "dropped_frames.mp4"
    if not video.exists():
        pytest.skip("Fixtures not generated")

    loader = VideoStandardLoader()
    loader.open(video, {})
    assert loader.video_metadata().dropped_frames == 0
