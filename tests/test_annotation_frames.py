"""Tests for frame-accurate annotation: VideoFrame, export, AnnotationPanel."""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from avialsync.ui.annotations import AnnotationStore, VideoFrame

# ── VideoFrame dataclass ──────────────────────────────────────────────


def test_video_frame_fields() -> None:
    vf = VideoFrame(path="/cam/a.mp4", frame_index=42, media_timestamp=1.4)
    assert vf.path == "/cam/a.mp4"
    assert vf.frame_index == 42
    assert vf.media_timestamp == pytest.approx(1.4)


# ── AnnotationStore with video_frames ────────────────────────────────


def test_add_point_stores_video_frames() -> None:
    store = AnnotationStore()
    vf = VideoFrame(path="/cam/a.mp4", frame_index=10, media_timestamp=0.333)
    m = store.add_point(5.0, label="nose", video_frames=[vf])
    assert len(m.video_frames) == 1
    assert m.video_frames[0].frame_index == 10


def test_add_point_no_frames_defaults_to_empty() -> None:
    store = AnnotationStore()
    m = store.add_point(1.0)
    assert m.video_frames == []


def test_add_range_stores_video_frames() -> None:
    store = AnnotationStore()
    vfs = [
        VideoFrame(path="/a.mp4", frame_index=0, media_timestamp=0.0),
        VideoFrame(path="/b.mp4", frame_index=3, media_timestamp=0.1),
    ]
    m = store.add_range(0.0, 2.0, label="run", video_frames=vfs)
    assert len(m.video_frames) == 2
    assert m.video_frames[1].path == "/b.mp4"


# ── export_csv — one row per (marker, video) ──────────────────────────


def test_export_csv_one_row_per_video(tmp_path: Path) -> None:
    store = AnnotationStore()
    store.add_point(
        1.5,
        label="stance",
        video_frames=[
            VideoFrame(path="/cam_left.mp4", frame_index=45, media_timestamp=1.5),
            VideoFrame(path="/cam_right.mp4", frame_index=46, media_timestamp=1.533),
        ],
    )
    out = tmp_path / "out.csv"
    store.export_csv(out)

    rows = list(csv.DictReader(out.read_text().splitlines()))
    assert len(rows) == 2
    assert rows[0]["label"] == "stance"
    assert rows[0]["video_path"] == "/cam_left.mp4"
    assert int(rows[0]["frame_index"]) == 45
    assert rows[1]["video_path"] == "/cam_right.mp4"
    assert int(rows[1]["frame_index"]) == 46


def test_export_csv_marker_with_no_frames(tmp_path: Path) -> None:
    store = AnnotationStore()
    store.add_point(3.0, label="event")
    out = tmp_path / "out.csv"
    store.export_csv(out)

    rows = list(csv.DictReader(out.read_text().splitlines()))
    assert len(rows) == 1
    assert rows[0]["video_path"] == ""
    assert rows[0]["frame_index"] == ""


def test_export_csv_columns(tmp_path: Path) -> None:
    store = AnnotationStore()
    store.add_point(0.0)
    out = tmp_path / "cols.csv"
    store.export_csv(out)

    reader = csv.DictReader(out.read_text().splitlines())
    expected = ["label", "comment", "t_master", "video_path", "frame_index", "media_timestamp"]
    assert reader.fieldnames == expected


# ── VideoGrid.frame_records_at ────────────────────────────────────────


def test_frame_records_at_empty_grid(qapp) -> None:
    from avialsync.ui.video_grid import VideoGrid

    grid = VideoGrid()
    records = grid.frame_records_at(5.0)
    assert records == []


def test_frame_records_at_single_pane(qapp) -> None:
    from avialsync.ui.video_grid import VideoGrid

    grid = VideoGrid()

    fake_pane = MagicMock()
    fake_pane.frame_record_at.return_value = (30, 1.0)

    grid.panes.append(fake_pane)
    grid._paths.append("/cam/a.mp4")

    records = grid.frame_records_at(1.0)
    assert len(records) == 1
    assert records[0]["path"] == "/cam/a.mp4"
    assert records[0]["frame_index"] == 30  # 1.0 s × 30 fps
    assert records[0]["media_timestamp"] == pytest.approx(1.0)


def test_shutdown_terminates_all_video_panes(qapp) -> None:
    """Pane-owned decode threads must stop before Qt destroys the grid."""
    from avialsync.ui.video_grid import VideoGrid

    grid = VideoGrid()
    panes = [MagicMock(), MagicMock()]
    grid.panes.extend(panes)
    grid._paths.extend(["/cam/a.mp4", "/cam/b.mp4"])

    grid.shutdown()

    for pane in panes:
        pane.close.assert_called_once_with()
        pane.deleteLater.assert_called_once_with()
    assert grid.panes == []
    assert grid.pane_paths() == []


def test_frame_records_at_offset_applied(qapp) -> None:
    from avialsync.ui.video_grid import VideoGrid

    grid = VideoGrid()

    fake_pane = MagicMock()
    fake_pane.frame_record_at.return_value = (50, 5.0)

    grid.panes.append(fake_pane)
    grid._paths.append("/cam/b.mp4")

    records = grid.frame_records_at(3.0)
    assert records[0]["media_timestamp"] == pytest.approx(5.0)  # 3 + 2
    assert records[0]["frame_index"] == 50  # 5.0 × 10


def test_frame_records_at_two_panes(qapp) -> None:
    from avialsync.ui.video_grid import VideoGrid

    grid = VideoGrid()

    for i, path in enumerate(["/a.mp4", "/b.mp4"]):
        p = MagicMock()
        p.frame_record_at.return_value = (25 * (i + 1), float(i + 1))
        grid.panes.append(p)
        grid._paths.append(path)

    records = grid.frame_records_at(1.0)
    assert len(records) == 2
    assert records[0]["media_timestamp"] == pytest.approx(1.0)
    assert records[1]["media_timestamp"] == pytest.approx(2.0)


def test_frame_records_use_real_vfr_timestamp_index(qapp) -> None:
    """Annotation frame numbers must never use t*fps arithmetic for VFR media."""
    from avialsync.ui.video_grid import VideoGrid

    grid = VideoGrid()
    pane = MagicMock()
    pane.frame_record_at.return_value = (2, 0.100)
    grid.panes.append(pane)
    grid._paths.append("/cam/vfr.mp4")

    records = grid.frame_records_at(0.11)

    pane.frame_record_at.assert_called_once_with(0.11)
    assert records == [{"path": "/cam/vfr.mp4", "frame_index": 2, "media_timestamp": 0.1}]
