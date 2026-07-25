"""Tests for SessionState serialisation and schema migrations."""

import json
from pathlib import Path

import pytest

from avialview.core.session import (
    MarkerEntry,
    SensorEntry,
    SessionState,
    SyncProvenance,
    VideoEntry,
)

FIXTURE_V1 = Path(__file__).parent / "fixtures" / "session_v1.avv"
FIXTURE_V2 = Path(__file__).parent / "fixtures" / "session_v2.avv"
FIXTURE_V3 = Path(__file__).parent / "fixtures" / "session_v3.avv"


# ---------------------------------------------------------------------------
# v1 → v3 migration (regression guard — fixture must never be deleted)
# ---------------------------------------------------------------------------


def test_v1_session_loads_under_v4_schema():
    """A v1 .avv file must load correctly after the v2-v4 schema changes."""
    state = SessionState.load(FIXTURE_V1)

    assert len(state.videos) == 1
    assert state.videos[0].path == "/tmp/nonexistent_video.mp4"
    assert state.videos[0].offset == 0.5
    assert state.videos[0].integrity_flags == {}
    assert state.videos[0].metadata == {}

    assert len(state.sensors) == 1
    assert state.sensors[0].path == "/tmp/nonexistent_sensors.csv"
    assert state.sensors[0].channels == ["ch1", "ch2"]
    assert state.sensors[0].loader_id == ""
    assert state.sensors[0].import_config == {}
    assert state.sensors[0].import_report is None

    assert len(state.markers) == 2
    assert state.markers[0].t_end == 3.0
    assert state.markers[1].t_end is None
    # v3 field defaults to empty for v1 markers
    assert state.markers[0].video_frames == []
    assert state.markers[1].video_frames == []
    assert state.sync_provenance == []


def test_v1_session_roundtrips_as_v4(tmp_path: Path) -> None:
    """Loading a v1 session then saving it should produce a valid v4 file."""
    state = SessionState.load(FIXTURE_V1)
    out = tmp_path / "out.avv"
    state.save(out)

    data = json.loads(out.read_text())
    assert data["version"] == 4
    assert data["videos"][0]["offset"] == 0.5
    assert data["sensors"][0]["channels"] == ["ch1", "ch2"]
    assert data["sensors"][0]["import_report"] is None
    # v3 markers carry video_frames
    assert data["markers"][0]["video_frames"] == []


# ---------------------------------------------------------------------------
# v2 fixture (permanent — must never be deleted)
# ---------------------------------------------------------------------------


def test_v2_session_loads_under_v4_schema() -> None:
    """A v2 .avv file must load without error; video_frames defaults to []."""
    state = SessionState.load(FIXTURE_V2)
    assert len(state.markers) == 2
    assert state.markers[0].video_frames == []
    assert state.markers[1].video_frames == []


# ---------------------------------------------------------------------------
# v3 fixture (permanent — must never be deleted)
# ---------------------------------------------------------------------------


def test_v3_session_loads_correctly() -> None:
    """A v3 .avv file must preserve video_frames on load."""
    state = SessionState.load(FIXTURE_V3)
    assert len(state.markers) == 2

    m0 = state.markers[0]
    assert m0.label == "range1"
    assert len(m0.video_frames) == 1
    assert m0.video_frames[0]["path"] == "/tmp/nonexistent_video.mp4"
    assert m0.video_frames[0]["frame_index"] == 45
    assert m0.video_frames[0]["media_timestamp"] == pytest.approx(1.5)

    m1 = state.markers[1]
    assert m1.label == "pt1"
    assert m1.video_frames == []


def test_v3_session_roundtrips(tmp_path: Path) -> None:
    """A v3 session must survive a save/load cycle with video_frames intact."""
    state = SessionState.load(FIXTURE_V3)
    out = tmp_path / "v3_rt.avv"
    state.save(out)
    loaded = SessionState.load(out)

    assert loaded.markers[0].video_frames[0]["frame_index"] == 45
    assert loaded.markers[1].video_frames == []


# ---------------------------------------------------------------------------
# v2 in-memory roundtrip (inspection fields)
# ---------------------------------------------------------------------------


def test_v4_roundtrip_with_inspection_and_sync_fields(tmp_path: Path) -> None:
    """Inspection fields and accepted synchronization provenance survive a round trip."""
    state = SessionState(
        videos=[
            VideoEntry(
                path="/tmp/vid.mp4",
                offset=1.5,
                drift_ppm=2.5,
                integrity_flags={"is_vfr": True, "has_gaps": False},
                metadata={"container": "mp4", "width": 640},
            )
        ],
        sensors=[
            SensorEntry(
                path="/tmp/data.csv",
                channels=["x", "y"],
                loader_id="CSVLoader",
                import_config={"fps": 30.0},
                import_report={"rows_parsed": 100, "gap_count": 2},
            )
        ],
        markers=[
            MarkerEntry(
                t_start=1.0,
                video_frames=[{"path": "/tmp/vid.mp4", "frame_index": 30, "media_timestamp": 1.0}],
            )
        ],
        sync_provenance=[
            SyncProvenance(
                reference_id="sensor:ttl",
                target_id="video:cam1",
                offset=1.25,
                drift_ppm=3.5,
                rms_residual=0.001,
                max_residual=0.002,
                matched_count=12,
                rejected_count=1,
                tolerance=0.01,
                matches=[
                    {"reference_time": 1.0, "target_time": 2.25, "residual": 0.0},
                ],
            )
        ],
    )
    out = tmp_path / "v4.avv"
    state.save(out)

    data = json.loads(out.read_text())
    assert data["version"] == 4

    loaded = SessionState.load(out)
    assert loaded.videos[0].integrity_flags == {"is_vfr": True, "has_gaps": False}
    assert loaded.videos[0].drift_ppm == pytest.approx(2.5)
    assert loaded.videos[0].metadata["container"] == "mp4"
    assert loaded.sensors[0].loader_id == "CSVLoader"
    assert loaded.sensors[0].import_config == {"fps": 30.0}
    assert loaded.sensors[0].import_report == {"rows_parsed": 100, "gap_count": 2}
    assert loaded.markers[0].video_frames[0]["frame_index"] == 30
    assert loaded.sync_provenance[0].drift_ppm == pytest.approx(3.5)
    assert loaded.sync_provenance[0].matches[0]["target_time"] == pytest.approx(2.25)


# ---------------------------------------------------------------------------
# Error handling and edge cases
# ---------------------------------------------------------------------------


def test_unsupported_version_raises() -> None:
    """Version 99 must raise ValueError."""
    data = {"version": 99, "videos": [], "sensors": [], "markers": []}
    with pytest.raises(ValueError, match="Unsupported"):
        SessionState.from_dict(data)


def test_empty_session_roundtrip(tmp_path: Path) -> None:
    """An empty session should save and load without error."""
    state = SessionState()
    out = tmp_path / "empty.avv"
    state.save(out)
    loaded = SessionState.load(out)
    assert loaded.videos == []
    assert loaded.sensors == []
    assert loaded.markers == []
