"""Fast, timestamp-based video readout and frame-index helpers."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from avialview.core.source import VideoMetadata
from avialview.core.timeline import TimeMap


def instantaneous_frame_rate(frame_times: np.ndarray | None, t: float, fallback: float) -> float:
    """Return the displayed frame's rate from its presentation interval."""
    if frame_times is None or len(frame_times) < 2:
        return fallback
    index = int(np.searchsorted(frame_times, t, side="right"))
    index = max(1, min(index, len(frame_times) - 1))
    interval = float(frame_times[index] - frame_times[index - 1])
    return 1.0 / interval if interval > 1e-9 else fallback


def displayed_frame_rate(
    frame_times: np.ndarray | None,
    t: float,
    is_vfr: bool,
    nominal_fps: float,
    fallback: float,
) -> float:
    """Use a stable nominal rate for CFR and timestamp evidence for VFR."""
    if is_vfr:
        return instantaneous_frame_rate(frame_times, t, fallback)
    return nominal_fps if nominal_fps > 0 else fallback


def human_file_size(size_bytes: int) -> str:
    """Format a byte count compactly for an on-video overlay."""
    size = float(max(0, size_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            decimals = 0 if unit == "B" else 1
            return f"{size:.{decimals}f} {unit}"
        size /= 1024.0
    return "0 B"


def format_video_osd(t: float, current_fps: float, metadata: VideoMetadata) -> str:
    """Build the compact, timestamp-authoritative video-pane information block."""
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    if metadata.is_vfr:
        rate_lines = (
            f"VFR: {metadata.min_frame_rate:.1f}–{metadata.max_frame_rate:.1f} fps"
            f" · now {current_fps:.1f}\n"
            f"Nominal CFR: {metadata.nominal_fps:.1f} fps"
        )
    else:
        measured = metadata.measured_fps or current_fps
        rate_lines = f"CFR: {metadata.nominal_fps:.3f} fps · measured {measured:.3f}"
    codec = metadata.codec.upper() if metadata.codec else "UNKNOWN"
    return (
        f"Time: {h:02d}:{m:02d}:{s:06.3f}\n"
        f"{rate_lines}\n"
        f"Codec: {codec} · Size: {human_file_size(metadata.file_size_bytes)}"
    )


def frame_index_at(frame_times: np.ndarray, source_time: float) -> int:
    """Return the presentation frame active at ``source_time``."""
    index = int(np.searchsorted(frame_times, source_time, side="right")) - 1
    return max(0, min(index, len(frame_times) - 1))


def adjacent_frame_time(
    frame_times: np.ndarray,
    source_time: float,
    direction: int,
) -> float:
    """Return the adjacent real presentation timestamp."""
    if direction > 0:
        index = int(np.searchsorted(frame_times, source_time, side="right"))
        index = min(index, len(frame_times) - 1)
    else:
        index = int(np.searchsorted(frame_times, source_time, side="left")) - 1
        index = max(index, 0)
    return float(frame_times[index])


class VideoTimingMixin:
    """Timestamp/readout behavior shared by every platform render path."""

    _frame_times: np.ndarray | None
    _metadata: VideoMetadata
    _is_vfr: bool
    _nominal_fps: float
    _decoder_fps: float
    _seek_pending: bool
    _seek_exact: bool
    _seek_target: float
    _mpv_seeking: bool
    _mapping_rate_scale: float
    is_seeking: bool
    time_pos: float
    time_map: TimeMap
    _osd_update: Any
    frame_presented: Any
    lbl_osd: Any
    paint_canvas: Any

    def _update_osd(self, t: float, fps: float) -> None:
        self.lbl_osd.setText(format_video_osd(t, fps, self._metadata))
        self.paint_canvas.update_time(t)

    def _observe_time(self, value: float) -> None:
        self.time_pos = value
        self._maybe_finish_seek()
        self.frame_presented.emit(value)
        fps = displayed_frame_rate(
            self._frame_times,
            value,
            self._is_vfr,
            self._nominal_fps,
            self._decoder_fps,
        )
        self._osd_update.emit(value, fps)

    def _observe_seeking(self, value: bool) -> None:
        self._mpv_seeking = value
        self._maybe_finish_seek()

    def _maybe_finish_seek(self) -> None:
        if not self._seek_pending:
            self.is_seeking = self._mpv_seeking
            return
        if self._mpv_seeking:
            self.is_seeking = True
            return
        if self._seek_exact and abs(self.time_pos - self._seek_target) > self._frame_tolerance(
            self._seek_target
        ):
            self.is_seeking = True
            return
        self._seek_pending = False
        self.is_seeking = False

    def _frame_tolerance(self, source_time: float) -> float:
        if self._frame_times is None or len(self._frame_times) < 2:
            return 0.05
        index = frame_index_at(self._frame_times, source_time)
        neighbour = min(index + 1, len(self._frame_times) - 1)
        if neighbour == index:
            neighbour = max(0, index - 1)
        interval = abs(float(self._frame_times[neighbour] - self._frame_times[index]))
        return max(0.001, interval * 0.5)

    def set_vfr(self, is_vfr: bool) -> None:
        """Mark the readout so its instantaneous rate is contextualized."""
        self._is_vfr = is_vfr
        self._metadata = replace(self._metadata, is_vfr=is_vfr)
        self._update_osd(self.time_pos, self._decoder_fps)

    def set_frame_times(self, frame_times: np.ndarray | None) -> None:
        """Supply decoded presentation timestamps."""
        self._frame_times = frame_times

    def set_nominal_fps(self, fps: float) -> None:
        """Supply a legacy plugin's nominal rate."""
        self._nominal_fps = fps
        self._metadata = replace(self._metadata, nominal_fps=fps)

    def set_video_metadata(self, metadata: VideoMetadata) -> None:
        """Supply timestamp-authoritative stream metadata."""
        self._metadata = metadata
        self._is_vfr = metadata.is_vfr
        self._nominal_fps = metadata.nominal_fps
        fps = displayed_frame_rate(
            self._frame_times,
            self.time_pos,
            self._is_vfr,
            self._nominal_fps,
            self._decoder_fps,
        )
        self._update_osd(self.time_pos, fps)

    def frame_record_at(self, t_master: float) -> tuple[int, float]:
        """Return the active frame index and real presentation timestamp."""
        source_time = self.time_map.to_source(t_master)
        if self._frame_times is not None and len(self._frame_times):
            index = frame_index_at(self._frame_times, source_time)
            return index, float(self._frame_times[index])
        fps = self._nominal_fps or self._decoder_fps or 30.0
        return max(0, int(source_time * fps)), source_time

    def frame_step_master_target(self, t_master: float, direction: int) -> float | None:
        """Return the adjacent decoded frame's master timestamp."""
        source_time = self.time_map.to_source(t_master)
        if self._frame_times is not None and len(self._frame_times):
            target = adjacent_frame_time(self._frame_times, source_time, direction)
            return self.time_map.to_master(target)
        return None

    def set_mapping_rate_at(self, t_master: float) -> None:
        """Apply the local accepted mapping slope without redundant mpv writes."""
        scale = self.time_map.rate_scale_at(t_master)
        if abs(scale - self._mapping_rate_scale) <= 1e-9:
            return
        self._mapping_rate_scale = scale
        self._apply_rate()

    def sync_tolerance_at_master(self, t_master: float) -> float:
        """Return a half-frame source-time drift tolerance."""
        return self._frame_tolerance(self.time_map.to_source(t_master))

    def _apply_rate(self) -> None:
        """Apply the concrete pane's composed playback rate."""
        raise NotImplementedError
