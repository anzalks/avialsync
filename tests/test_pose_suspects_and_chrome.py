"""Tests for edit-aware pose suspect scanning and QSS-free VideoPane overlay chrome."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from PySide6.QtGui import QColor, QPalette

from avialsync.core.point_edits import PointKey
from avialsync.core.timeline import TimeMap
from avialsync.ui import pose_suspects
from avialsync.ui.video_pane import VideoPane


@dataclasses.dataclass(frozen=True)
class _PointStub:
    name: str
    axes: tuple[str, ...]
    likelihood_channel: str | None = None

    def channel(self, axis: str) -> str:
        return f"{self.name}_{axis}"


@dataclasses.dataclass(frozen=True)
class _SchemaStub:
    points: tuple[_PointStub, ...]


class _MmapChannelReader:
    """Minimal PyramidReader double backed by read-only .npy memmaps on disk."""

    def __init__(self, cache_dir: Path, channel: str) -> None:
        self._t = np.load(cache_dir / f"{channel}_t.npy", mmap_mode="r")
        self._v = np.load(cache_dir / f"{channel}_v.npy", mmap_mode="r")
        self._g = np.load(cache_dir / f"{channel}_g.npy", mmap_mode="r")
        self.closed = False

    def mapped_columns(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self._t, self._v, self._g

    def close(self) -> None:
        self.closed = True


def _write_channel(
    directory: Path,
    ch_name: str,
    times: np.ndarray,
    values: np.ndarray,
    gaps: np.ndarray | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / f"{ch_name}_t.npy", np.asarray(times, dtype=np.float64))
    np.save(directory / f"{ch_name}_v.npy", np.asarray(values, dtype=np.float64))
    gap_arr = np.zeros(len(values), dtype=bool) if gaps is None else np.asarray(gaps, dtype=bool)
    np.save(directory / f"{ch_name}_g.npy", gap_arr)


def test_find_suspects_flags_and_point_overrides_eliminate_suspects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Velocity jumps and low-likelihood frames disappear once overridden in Fix Tracker."""
    monkeypatch.setattr(pose_suspects, "PyramidReader", _MmapChannelReader)

    n = 20
    times = np.arange(n, dtype=np.float64) * 0.1
    xs = np.full(n, 100.0, dtype=np.float64)
    ys = np.full(n, 100.0, dtype=np.float64)
    lik = np.full(n, 0.98, dtype=np.float64)

    # Frame 5: low confidence; Frame 12: abrupt teleport spike
    lik[5] = 0.15
    xs[12] = 250.0
    ys[12] = 250.0

    _write_channel(tmp_path, "nose_x", times, xs)
    _write_channel(tmp_path, "nose_y", times, ys)
    _write_channel(tmp_path, "nose_likelihood", times, lik)

    schema: Any = _SchemaStub(
        points=(_PointStub("nose", ("x", "y"), likelihood_channel="nose_likelihood"),)
    )

    suspects = pose_suspects.find_suspects_in_cache(
        "pose_1", tmp_path, schema, TimeMap(), threshold=0.6
    )
    by_index = {s.sample_index: s for s in suspects}
    assert set(by_index) == {5, 12}
    assert "low confidence (0.15)" in by_index[5].reason
    assert "jump (" in by_index[12].reason
    assert "px)" in by_index[12].reason

    repaired = pose_suspects.find_suspects_in_cache(
        "pose_1",
        tmp_path,
        schema,
        TimeMap(),
        threshold=0.6,
        point_overrides={
            ("nose", 5): (100.0, 100.0),
            ("nose", 12): (100.0, 100.0),
            ("nose", 999): (0.0, 0.0),
        },
    )
    assert repaired == []


def test_find_suspects_reads_channel_dirs_and_formats_3d_vs_2d_jumps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Swapped channels resolve through channel_dirs and 3D schemas format jumps in units."""
    monkeypatch.setattr(pose_suspects, "PyramidReader", _MmapChannelReader)

    base_dir = tmp_path / "base"
    swap_dir = tmp_path / "swapped"
    n = 20
    times = np.arange(n, dtype=np.float64) * 0.1
    clean = np.full(n, 10.0, dtype=np.float64)
    jumped = clean.copy()
    jumped[8] = 110.0  # 100.0 jump only in swapped directory

    _write_channel(base_dir, "paw_x", times, clean)
    _write_channel(base_dir, "paw_y", times, clean)
    _write_channel(swap_dir, "paw_x", times, jumped)

    schema_2d: Any = _SchemaStub(points=(_PointStub("paw", ("x", "y")),))
    schema_3d: Any = _SchemaStub(points=(_PointStub("paw", ("x", "y", "z")),))

    assert pose_suspects.find_suspects_in_cache("src", base_dir, schema_2d, TimeMap(), 0.5) == []

    suspects_2d = pose_suspects.find_suspects_in_cache(
        "src",
        base_dir,
        schema_2d,
        TimeMap(),
        threshold=0.5,
        channel_dirs={"paw_x": swap_dir},
    )
    assert len(suspects_2d) == 1
    assert suspects_2d[0].sample_index == 8
    assert suspects_2d[0].reason == "paw: jump (100.0 px)"

    suspects_3d = pose_suspects.find_suspects_in_cache(
        "src",
        base_dir,
        schema_3d,
        TimeMap(),
        threshold=0.5,
        channel_dirs={"paw_x": swap_dir},
    )
    assert len(suspects_3d) == 1
    assert suspects_3d[0].sample_index == 8
    assert suspects_3d[0].reason == "paw: jump (100.0 units)"


def test_collect_specs_signature_and_reset_generation_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qtbot: Any
) -> None:
    """Edit state enters specs/signatures and stale scans abort after Reset Session."""
    del qtbot
    monkeypatch.setattr(pose_suspects, "confidence_threshold", lambda: 0.6)
    monkeypatch.setattr(pose_suspects, "on_ui_thread", lambda fn, _win: fn)

    cache_dir = tmp_path / "cache"
    swap_dir = tmp_path / "swap"
    cache_dir.mkdir()
    swap_dir.mkdir()

    schema: Any = _SchemaStub(points=(_PointStub("nose", ("x", "y")),))
    captured_jobs: list[Any] = []
    seeks: list[float] = []

    window: Any = SimpleNamespace(
        _pose_schemas={"pose_1": schema},
        _pose_cache_dirs={"pose_1": cache_dir},
        _overlay_sources={},
        _pose_3d_sources={},
        _show_original_tracker=False,
        _edited_generations={"pose_1": SimpleNamespace(directories={"nose_x": swap_dir})},
        point_edits={PointKey("pose_1", "nose", 4): (12.0, 34.0)},
        identity_swaps=[object()],
        session_runtime=SimpleNamespace(generation=3),
        clock=SimpleNamespace(state=SimpleNamespace(t=0.0, bounds=(0.0, 10.0))),
        player=SimpleNamespace(seek=lambda t, exact=True: seeks.append(t)),
        video_grid=SimpleNamespace(highlight_point=lambda _key: None),
        _highlight_timer=SimpleNamespace(start=lambda _ms: None),
        statusBar=lambda: SimpleNamespace(showMessage=lambda _msg, _ms: None),
        notifications=SimpleNamespace(show_success=lambda _msg: None),
        _run_job=lambda worker, label, configure: captured_jobs.append((worker, configure)),
    )

    specs_edited = pose_suspects._collect_specs(window)
    assert specs_edited[0].channel_dirs == {"nose_x": swap_dir}
    assert specs_edited[0].point_overrides == {("nose", 4): (12.0, 34.0)}
    sig_edited = pose_suspects._signature_for(window, specs_edited, 0.6)

    window._show_original_tracker = True
    specs_orig = pose_suspects._collect_specs(window)
    assert specs_orig[0].channel_dirs == {}
    assert specs_orig[0].point_overrides == {}
    assert pose_suspects._signature_for(window, specs_orig, 0.6) != sig_edited

    window._show_original_tracker = False
    pose_suspects.jump_suspect_frame(window, +1)
    assert len(captured_jobs) == 1
    worker, configure = captured_jobs[0]
    dummy_thread = SimpleNamespace(quit=lambda *_: None)
    configure(dummy_thread)

    # Simulate Reset Session bumping generation while background scan was running
    window.session_runtime.generation = 4
    worker.finished.emit(sig_edited, [])
    assert not hasattr(window, "_suspect_cache")
    assert seeks == []


def test_video_pane_overlay_chrome_uses_palette_without_stylesheets(qtbot: Any) -> None:
    """Overlay container and readout labels must not carry widget-level QSS."""
    pane = VideoPane()
    qtbot.addWidget(pane)
    try:
        assert pane.overlay.styleSheet() == ""
        assert pane.overlay.autoFillBackground() is False

        for label in (pane.lbl_name, pane.lbl_osd, pane.lbl_no_footage):
            assert label.styleSheet() == ""
            assert label.autoFillBackground() is True
            assert label.palette().color(QPalette.ColorRole.WindowText) == QColor(255, 255, 255)

        assert pane.lbl_name.palette().color(QPalette.ColorRole.Window) == QColor(0, 0, 0, 128)
        assert pane.lbl_osd.palette().color(QPalette.ColorRole.Window) == QColor(0, 0, 0, 128)
        assert pane.lbl_no_footage.palette().color(QPalette.ColorRole.Window) == QColor(
            0, 0, 0, 255
        )
    finally:
        pane.close()
