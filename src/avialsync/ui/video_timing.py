"""Fast, timestamp-based video readout and frame-index helpers."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from avialsync.core.source import VideoMetadata
from avialsync.core.timeline import TimeMap

# Frame selection lives in core/ so the headless decoder resolves time through
# the same call this readout names it with — one authority, never two (D-075).
# Re-exported here because this is the import path the UI already knows.
from avialsync.core.video_timing import adjacent_frame_time, frame_index_at


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
    rate_scale: float = 1.0,
) -> float:
    """Use a stable nominal rate for CFR and timestamp evidence for VFR.

    ``frame_times`` are presentation timestamps in *source* time, so the rate they
    give is the rate the container advances at.  ``rate_scale`` — source seconds
    per master second, from the pane's :class:`TimeMap` — converts that onto the
    master timeline, which is the axis the printed VFR range is measured on and
    the one every other source shares.  It is 1.0 for an ordinary video, so this
    changes nothing without an accepted or declared per-frame mapping; with one,
    a camera whose container claims 30 fps correctly reads as the 45.8 Hz it was
    actually exposed at.
    """
    if is_vfr:
        rate = instantaneous_frame_rate(frame_times, t, fallback)
        return rate * rate_scale if rate_scale > 0 else rate
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


def format_video_osd(
    t: float,
    current_fps: float,
    metadata: VideoMetadata,
    frame: tuple[int, int | None] | None = None,
) -> str:
    """Build the compact, timestamp-authoritative video-pane information block.

    ``frame`` is ``(index, total)``, both counted the way every other frame
    number in the app is: zero-based, so what the overlay shows is the same
    integer an exported annotation row or a DLC sidecar carries.  It is None
    when the rate is unknown, because a guessed frame number would be indistin-
    guishable from a measured one.
    """
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
    if frame is None:
        frame_text = "—"
    else:
        index, total = frame
        frame_text = f"{index}" if total is None else f"{index} / {total - 1}"
    return (
        f"Time: {h:02d}:{m:02d}:{s:06.3f}\n"
        f"Frame: {frame_text}\n"
        f"{rate_lines}\n"
        f"Codec: {codec} · Size: {human_file_size(metadata.file_size_bytes)}"
    )


class VideoTimingMixin:
    """Timestamp and readout behaviour shared by the pane's decode paths.

    What is *not* here any more is the settle machinery — ``_maybe_finish_seek``,
    ``_frame_tolerance``, and the ``seeking`` observation that drove them.  Those
    existed because libmpv decided which frame to display while the pts table
    decided which frame the readout named, and the two had to be reconciled
    within a tolerance.  The decoder now resolves time through the same
    ``frame_index_at`` call the readout uses, so there is nothing left to
    reconcile: one authority selects *and* names the frame (D-075).  Do not
    reintroduce a second one.
    """

    _frame_times: np.ndarray | None
    _metadata: VideoMetadata
    _is_vfr: bool
    _nominal_fps: float
    _decoder_fps: float
    is_seeking: bool
    time_pos: float
    time_map: TimeMap
    frame_presented: Any
    lbl_osd: Any
    paint_canvas: Any

    def _queue_osd_update(self, t: float, fps: float) -> None:
        """Queue the concrete pane's coalesced UI-thread update."""
        raise NotImplementedError

    def _source_frame(self, source_time: float) -> tuple[int, int | None] | None:
        """Return ``(index, total)`` for the frame on screen at *source_time*.

        Costs one binary search over the decoded presentation timestamps — a
        few microseconds, paid at most ``_OSD_MAX_HZ`` times per pane because
        the only caller is the already-coalesced OSD paint.  It resolves the
        frame with the same call the decoder used to select it, so the number
        shown can never name a different frame from the one on screen.
        """
        frame_times = self._frame_times
        if frame_times is not None and len(frame_times):
            return frame_index_at(frame_times, source_time), len(frame_times)
        fps = self._nominal_fps or self._decoder_fps
        if fps <= 0:
            return None
        return max(0, int(source_time * fps)), None

    def _update_osd(self, t: float, fps: float) -> None:
        self.lbl_osd.setText(format_video_osd(t, fps, self._metadata, self._source_frame(t)))
        # The overlay's data readers expect master time (via MappedChannelReader)
        master_t = self.time_map.to_master(t)
        self.paint_canvas.update_time(master_t)

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

    def source_time_at_master(self, t_master: float) -> float:
        """Return the source instant this pane should be showing for ``t_master``."""
        return float(self.time_map.to_source(t_master))
