"""Video transcoding on PyAV — scrub proxies and clip export.

Both operations used to shell out to the ``ffmpeg`` command line, which is why
the application needed a media runtime installed beside it. They run in-process
now, against the FFmpeg that PyAV carries inside its own wheel, so nothing here
requires anything on the machine (D-075).

Headless on purpose: no PySide6 import, so the workers that drive these can be
tested without Qt and the functions can be called from any thread. PyAV releases
the GIL during decode and encode, so a transcode does not block the UI thread it
was started from.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

logger = logging.getLogger(__name__)

#: Proxy height. 720p is small enough to decode several times faster than
#: source footage and large enough to still see what is in the frame.
PROXY_HEIGHT = 720

#: Encoder settings for a proxy. ``gop_size=1`` makes every frame a keyframe,
#: which is the entire point: a seek never has to decode forward, so scrubbing
#: a proxy costs one frame regardless of where it lands.
PROXY_CRF = "23"
PROXY_PRESET = "fast"

ProgressCallback = Callable[[float], None]
CancelCheck = Callable[[], bool]


class TranscodeCancelled(Exception):
    """Raised inside a transcode when its caller asked it to stop."""


def _even(value: float) -> int:
    """Round down to an even number; H.264 chroma subsampling requires it."""
    return max(2, int(value) // 2 * 2)


def remux_clip(source: Path | str, destination: Path | str, start: float, end: float) -> bool:
    """Copy the packets covering ``[start, end]`` into a new container.

    A stream copy: nothing is decoded or re-encoded, so the exported clip holds
    the original pixels rather than a second generation of them. That matters
    for a tool whose output people measure.

    The cut is keyframe-aligned at the start, exactly as ``ffmpeg -c copy`` is
    and for the same reason — a clip that began mid-GOP would have no frame to
    decode from. The first retained packet is therefore at or before ``start``.

    Args:
        source: Media to copy from.
        destination: Container to write. Its suffix picks the format.
        start: First wanted instant, in source seconds.
        end: Last wanted instant, in source seconds.

    Returns:
        True when at least one packet was written.
    """
    source, destination = Path(source), Path(destination)
    written = 0
    try:
        with av.open(str(source)) as input_container:
            stream = input_container.streams.video[0]
            time_base = stream.time_base
            if time_base is None:
                logger.warning("Cannot trim %s: the stream declares no time base", source)
                return False
            with av.open(str(destination), mode="w") as output_container:
                output_stream = output_container.add_stream_from_template(stream)
                input_container.seek(
                    int(start / time_base), stream=stream, backward=True, any_frame=False
                )
                first_pts: int | None = None
                for packet in input_container.demux(stream):
                    if packet.pts is None:
                        continue
                    if float(packet.pts * time_base) > end:
                        break
                    if first_pts is None:
                        first_pts = packet.pts
                    # Rebase onto zero so the clip starts at its own beginning
                    # rather than carrying the source's offset.
                    packet.pts -= first_pts
                    if packet.dts is not None:
                        packet.dts -= first_pts
                    packet.stream = output_stream
                    output_container.mux(packet)
                    written += 1
    except (av.FFmpegError, OSError, IndexError, ValueError):
        logger.warning("Could not trim %s to %s", source, destination, exc_info=True)
        return False
    return written > 0


def encode_proxy(
    source: Path | str,
    destination: Path | str,
    *,
    height: int = PROXY_HEIGHT,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> None:
    """Re-encode ``source`` to an all-keyframe proxy at ``height``.

    Args:
        source: Media to read.
        destination: File to write.
        height: Output height; width follows the source's aspect ratio.
        progress: Called with a fraction in ``[0, 1]`` as encoding advances.
        should_cancel: Polled per frame; a true result stops the encode.

    Raises:
        TranscodeCancelled: ``should_cancel`` returned true.
        av.FFmpegError: The source could not be read or the output written.
    """
    source, destination = Path(source), Path(destination)
    with av.open(str(source)) as input_container:
        stream = input_container.streams.video[0]
        # Decode with every core; a proxy build should not take longer than it
        # has to just because it is in the background.
        stream.thread_type = "AUTO"
        codec_context = stream.codec_context
        width = _even(codec_context.width * height / max(1, codec_context.height))
        out_height = _even(height)
        time_base = stream.time_base or Fraction(1, 90_000)
        total = _duration_seconds(input_container, stream)

        with av.open(str(destination), mode="w") as output_container:
            output_stream = output_container.add_stream(
                "libx264", rate=stream.average_rate or stream.base_rate or Fraction(30, 1)
            )
            output_stream.width = width
            output_stream.height = out_height
            output_stream.pix_fmt = "yuv420p"
            output_stream.codec_context.gop_size = 1
            # Both are required; setting only the stream's makes mux() reject
            # every packet with a bare EINVAL (HANDOUT.md, PyAV fixture trap).
            output_stream.time_base = time_base
            output_stream.codec_context.time_base = time_base
            output_stream.options = {"preset": PROXY_PRESET, "crf": PROXY_CRF}

            for frame in input_container.decode(stream):
                if should_cancel is not None and should_cancel():
                    raise TranscodeCancelled
                if frame.pts is None:
                    continue
                scaled = frame.reformat(width=width, height=out_height, format="yuv420p")
                scaled.pts = frame.pts
                scaled.time_base = time_base
                for packet in output_stream.encode(scaled):
                    output_container.mux(packet)
                if progress is not None and total > 0:
                    elapsed = float(frame.pts * time_base)
                    progress(min(1.0, max(0.0, elapsed / total)))
            for packet in output_stream.encode():
                output_container.mux(packet)
    if progress is not None:
        progress(1.0)


def encode_video(
    destination: Path | str,
    frames: Iterable[tuple[np.ndarray, float]],
    *,
    rate: Fraction,
    time_base: Fraction = Fraction(1, 90_000),
    gop_size: int = 30,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> None:
    """Encode ``(rgb_frame, seconds)`` pairs into an H.264 file.

    Each frame carries its own presentation time, so a caller can write
    genuinely variable-rate media by spacing them unevenly — which is how the
    demo's VFR camera is produced, rather than by asking an encoder to drop
    frames and hoping the timestamps follow.

    Args:
        destination: File to write.
        frames: Pairs of ``(H, W, 3)`` uint8 RGB arrays and their presentation
            times in seconds.
        rate: Nominal rate written into the container.
        time_base: Timestamp resolution. The 90 kHz default is the MPEG
            convention and divides common rates without drift.
        gop_size: Frames between keyframes.
        progress: Called with the elapsed presentation time in seconds, so a
            caller that knows the intended duration can turn it into a
            percentage without this function having to know one.
        should_cancel: Polled per frame; a true result stops the encode.

    Raises:
        TranscodeCancelled: ``should_cancel`` returned true.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(destination), mode="w")
    try:
        stream: av.VideoStream | None = None
        last_time = 0.0
        for image, seconds in frames:
            if should_cancel is not None and should_cancel():
                raise TranscodeCancelled
            if stream is None:
                height, width, _ = image.shape
                stream = container.add_stream("libx264", rate=rate)
                stream.width = _even(width)
                stream.height = _even(height)
                stream.pix_fmt = "yuv420p"
                stream.codec_context.gop_size = gop_size
                # Both are required; setting only the stream's makes mux()
                # reject every packet with a bare EINVAL.
                stream.time_base = time_base
                stream.codec_context.time_base = time_base
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            frame.pts = int(round(seconds / time_base))
            frame.time_base = time_base
            for packet in stream.encode(frame):
                container.mux(packet)
            last_time = seconds
            if progress is not None:
                progress(last_time)
        if stream is not None:
            for packet in stream.encode():
                container.mux(packet)
    finally:
        container.close()


def _duration_seconds(container: av.container.InputContainer, stream: av.VideoStream) -> float:
    """Return the stream's duration in seconds, for progress reporting only.

    Falls back through the container's own duration because a stream that
    declares none is ordinary; progress then simply stays at zero rather than
    the transcode failing over a cosmetic number.
    """
    time_base = stream.time_base
    if stream.duration is not None and time_base is not None:
        return float(stream.duration * time_base)
    if container.duration is not None:
        return container.duration / 1_000_000.0
    return 0.0
