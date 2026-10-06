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
from avialsync.ui.time_format import format_rate


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


#: Pixel formats whose name does not carry a depth but whose samples are 8-bit.
_EIGHT_BIT_FORMATS = ("gray", "rgb24", "bgr24", "rgba", "bgra", "argb", "abgr", "nv12", "nv21")


def bit_depth_of(pixel_format: str) -> int | None:
    """Bits per sample named by an FFmpeg pixel format, or None when it says nothing.

    ``gray12le`` and ``yuv420p10le`` carry the depth in the name; ``yuv420p``
    and ``gray`` are 8-bit; ``rgb48le`` is 16. A decoded frame is still the
    authority (``SourceFormat.bits``); this is for before the first frame.
    """
    import re

    name = pixel_format.lower().strip()
    if not name:
        return None
    if name.startswith(("rgb48", "bgr48", "rgba64", "bgra64")):
        return 16
    match = re.search(r"(?:gray|p|f)(\d{1,2})(?:le|be)?$", name)
    if match and 8 <= int(match.group(1)) <= 32:
        return int(match.group(1))
    if name in _EIGHT_BIT_FORMATS or re.fullmatch(r"yuv[aj]?4[0-4][0-4]p", name):
        return 8
    return None


def format_picture(metadata: VideoMetadata, bits: int | None = None) -> str:
    """``1440×1080 · 12-bit``: what the picture is, for the overlay and properties."""
    depth = bits if bits is not None else bit_depth_of(metadata.pixel_format)
    parts = []
    if metadata.width and metadata.height:
        parts.append(f"{metadata.width}×{metadata.height}")
    if depth is not None:
        parts.append(f"{depth}-bit")
    return " · ".join(parts)


def format_video_osd(
    t: float,
    current_fps: float,
    metadata: VideoMetadata,
    frame: tuple[int, int | None] | None = None,
    detail: str = "full",
    bits: int | None = None,
) -> str:
    """Build the timestamp-authoritative video-pane information block.

    ``detail`` is ``"compact"`` -- time and frame, then resolution and bit
    depth on a second line, the default on a pane (D-174, D-183) -- or
    ``"full"``, which adds
    the rate, codec, pixel format and size lines. ``bits`` is the decoded
    frame's depth when known; otherwise it is read from the pixel format.

    ``frame`` is ``(index, total)``, both counted the way every other frame
    number in the app is: zero-based, so what the overlay shows is the same
    integer an exported annotation row or a DLC sidecar carries.  It is None
    when the rate is unknown, because a guessed frame number would be indistin-
    guishable from a measured one.
    """
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    if frame is None:
        frame_text = "—"
    else:
        index, total = frame
        frame_text = f"{index}" if total is None else f"{index} / {total - 1}"
    picture = format_picture(metadata, bits)
    if detail == "compact":
        # Two short lines rather than one long one: when; then what the picture
        # is. One long line wrapped wherever the pane ran out, and squeezed the
        # camera name beside it.
        compact = f"{h:02d}:{m:02d}:{s:06.3f} · f {frame_text}"
        return f"{compact}\n{picture}" if picture else compact
    if metadata.is_vfr:
        rate_lines = (
            f"VFR: {format_rate(metadata.min_frame_rate)}–"
            f"{format_rate(metadata.max_frame_rate)} fps · now {format_rate(current_fps)}\n"
            f"Nominal CFR: {format_rate(metadata.nominal_fps)} fps"
        )
    else:
        measured = metadata.measured_fps or current_fps
        rate_lines = (
            f"CFR: {format_rate(metadata.nominal_fps)} fps · measured {format_rate(measured)}"
        )
    codec = metadata.codec.upper() if metadata.codec else "UNKNOWN"
    return (
        f"Time: {h:02d}:{m:02d}:{s:06.3f}\n"
        f"Frame: {frame_text}\n"
        f"{rate_lines}\n"
        f"Codec: {codec} · Size: {human_file_size(metadata.file_size_bytes)}"
        + (f"\nPicture: {picture}" if picture else "")
        + (f" · {metadata.pixel_format}" if picture and metadata.pixel_format else "")
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
    _osd_detail: str
    _osd_last: tuple[float, float]

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

    def osd_text(self, detail: str) -> str:
        """The readout for the frame last shown, at *detail* (a snapshot asks for full)."""
        t, fps = getattr(self, "_osd_last", (0.0, 0.0))
        # The decoded frame's depth when there is one: the file's pixel format
        # only names what the encoder was asked for.
        bits = getattr(getattr(self, "source_format", None), "bits", None)
        return format_video_osd(t, fps, self._metadata, self._source_frame(t), detail, bits)

    def _update_osd(self, t: float, fps: float) -> None:
        self._osd_last = (t, fps)
        self.lbl_osd.setText(self.osd_text(self._osd_detail))
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
