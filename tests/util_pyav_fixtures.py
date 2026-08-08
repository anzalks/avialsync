"""PyAV fixture writers for frame-exactness and seek-latency tests.

Every fixture encodes each frame's own index into its pixels via
:func:`tests.util_framestrip.encode_frame_index`, so a test reads identity back
off the decoded image instead of inferring it from a timestamp.  That is the
whole point: a reader that returns the wrong frame still returns a *plausible*
timestamp, and only the pixels catch it.

The writers deliberately keep B-frames on (no ``ultrafast``).  Long-GOP H.264
demuxes in decode order, and a pts table built by walking packets is scrambled
unless it is sorted into display order — a fixture without B-frames would let
that bug pass.
"""

from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import numpy as np

from tests.util_framestrip import encode_frame_index

#: Timestamps are written on a 90 kHz grid, the MPEG convention.  It divides
#: 30 fps exactly and 230 fps to within 0.4 ppm, so a fixture's nominal
#: timestamps are not themselves a source of rounding error under test.
TIME_BASE = Fraction(1, 90_000)


@lru_cache(maxsize=4)
def _detail_planes(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Build the static pixel content once per resolution.

    Rebuilding this per frame cost 9.2 ms at 1440x1080 — more than half the
    time to write a benchmark fixture, spent on pixels that never change.
    """
    ramp_y = np.arange(height, dtype=np.int32)[:, None]
    ramp_x = np.arange(width, dtype=np.int32)[None, :]
    pattern = ((ramp_x + ramp_y) % 251).astype(np.uint8)
    speckle = (((ramp_x * 7919) ^ (ramp_y * 104_729)) % 97).astype(np.uint8)
    return np.ascontiguousarray(np.broadcast_to(pattern, (height, width))), np.ascontiguousarray(
        np.broadcast_to(speckle, (height, width))
    )


def _identity_frame(index: int, width: int, height: int, detail: bool) -> np.ndarray:
    """Build one RGB frame carrying ``index`` in flat black/white blocks.

    ``detail`` adds deterministic high-frequency content that *moves*.  A flat
    frame encodes to almost nothing and decodes far faster than real footage,
    which would make a seek benchmark measure the fixture rather than the
    decoder.  The identity fixtures leave it off so the index blocks stay
    pristine.
    """
    frame = np.full((height, width, 3), 96, dtype=np.uint8)
    if detail:
        pattern, speckle = _detail_planes(width, height)
        # Shifting the pattern gives every frame real inter-frame residual, so
        # P- and B-frames cost bits the way session footage does.
        frame[:, :, 0] = np.roll(pattern, -index * 7, axis=1)
        frame[:, :, 1] = np.roll(pattern, -index * 7 + 13, axis=1)
        frame[:, :, 2] = speckle
    encode_frame_index(frame, index)
    return frame


def write_video(
    path: Path,
    *,
    frame_times: list[float],
    width: int = 640,
    height: int = 360,
    gop_size: int = 30,
    nominal_fps: Fraction = Fraction(30, 1),
    detail: bool = False,
) -> np.ndarray:
    """Write an H.264 fixture whose frames present at ``frame_times`` seconds.

    Returns the timestamps as they were actually written — quantised onto
    :data:`TIME_BASE` — because that, not the requested float, is what a reader
    can ever report back.

    Trap: ``stream.time_base`` and ``stream.codec_context.time_base`` must
    *both* be set.  Setting only the former makes ``mux()`` reject every packet
    with a bare ``ArgumentError: Invalid argument ... returned 22``, which reads
    like a corrupt file rather than a missing attribute.
    """
    import av

    path.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(path), mode="w")
    try:
        stream = container.add_stream("libx264", rate=nominal_fps)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        stream.codec_context.gop_size = gop_size
        stream.time_base = TIME_BASE
        stream.codec_context.time_base = TIME_BASE
        # ``veryfast`` writes a 1440x1080 fixture 2.5x faster than x264's
        # default. Not ``ultrafast``: that is the one preset that disables
        # B-frames, and B-frames are exactly what makes these fixtures able to
        # catch a pts table left in decode order.
        stream.options = {"preset": "veryfast"}

        written = np.empty(len(frame_times), dtype=np.float64)
        for index, seconds in enumerate(frame_times):
            ticks = int(round(seconds / TIME_BASE))
            written[index] = ticks * float(TIME_BASE)
            frame = av.VideoFrame.from_ndarray(
                _identity_frame(index, width, height, detail), format="rgb24"
            )
            frame.pts = ticks
            frame.time_base = TIME_BASE
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()
    return written


def cfr_times(count: int, fps: float = 30.0) -> list[float]:
    """Return constant-rate presentation timestamps."""
    return [index / fps for index in range(count)]


def vfr_times(count: int, base_fps: float = 30.0) -> list[float]:
    """Return variable-rate presentation timestamps.

    The interval cycles deterministically between roughly 20 and 45 fps, which
    is the shape of real machine-vision footage under a varying exposure
    trigger — not noise around a nominal rate, but genuinely uneven spacing
    that ``t / fps`` arithmetic cannot reproduce.
    """
    times: list[float] = []
    now = 0.0
    for index in range(count):
        times.append(now)
        now += (1.0 / base_fps) * (1.0 + 0.5 * ((index % 7) / 6.0 - 0.5) * 2.0)
    return times
