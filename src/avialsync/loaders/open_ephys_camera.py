"""Camera video timed by the acquisition rig's own per-frame timestamp sidecar.

Machine-vision capture software commonly writes two files: a container, and a
sidecar naming every frame it actually kept.  The container is the unreliable
one.  It declares a constant nominal rate whether or not the camera achieved it,
so a capture that free-ran at 45.8 Hz and dropped frames still arrives labelled
30 fps CFR — on one real 26 877-frame recording that stretched 785 s of footage
across 895 s of timeline, and no amount of offset adjustment can take that back
out, because the error accumulates.

The sidecar is evidence and the container is a guess, so the sidecar wins
(the same rule as "ffprobe start times lie for some machine-vision containers").
Fitting a corrected constant rate is not enough either: with dropped frames a
single rate leaves over a second of error at the worst frame.  What this loader
produces instead is a per-frame mapping between master time and the media time
mpv seeks to, so every frame lands where it was actually exposed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.loaders.video_standard import VideoStandardLoader

logger = logging.getLogger(__name__)

#: Sidecar suffix searched for beside a video file.
SIDECAR_SUFFIX = ".csv"

#: Divisor turning the sidecar's integer timestamps into seconds.  These cameras
#: stamp a free-running nanosecond counter, which is why only the *differences*
#: between rows are used and the absolute value is discarded.
_NANOSECONDS = 1e9


def find_timestamp_sidecar(video: Path) -> Path | None:
    """Return the per-frame timestamp file recorded beside *video*, if any."""
    sidecar = video.with_suffix(SIDECAR_SUFFIX)
    return sidecar if sidecar.is_file() else None


def read_frame_timestamps(sidecar: Path) -> np.ndarray | None:
    """Return one timestamp in seconds per recorded frame, or ``None``.

    The file is ``frame_number,timestamp`` with no header.  Only the timestamp
    column is used; the frame counter is the camera's own free-running index and
    its gaps are what prove frames were dropped, but the mapping is built from
    the rows that exist rather than from the counter.

    Returns ``None`` rather than raising for anything unreadable: a missing or
    malformed sidecar costs exact timing, which is a degraded import, while a
    raised error would cost the video entirely.
    """
    try:
        if sidecar.stat().st_size == 0:
            logger.warning("Frame timestamp sidecar %s is empty.", sidecar)
            return None
        raw = np.loadtxt(sidecar, delimiter=",", dtype=np.float64, ndmin=2)
    except (OSError, ValueError):
        logger.warning("Cannot parse frame timestamp sidecar %s", sidecar, exc_info=True)
        return None
    if raw.size == 0 or raw.ndim != 2 or raw.shape[1] < 2:
        logger.warning("Frame timestamp sidecar %s has no timestamp column.", sidecar)
        return None

    times: np.ndarray = np.asarray(raw[:, 1], dtype=np.float64) / _NANOSECONDS
    if len(times) < 2 or not np.all(np.isfinite(times)):
        logger.warning("Frame timestamp sidecar %s holds no usable timestamps.", sidecar)
        return None
    if np.any(np.diff(times) <= 0):
        logger.warning("Frame timestamps in %s are not strictly increasing.", sidecar)
        return None
    rebased: np.ndarray = times - times[0]
    return rebased


class OpenEphysCameraLoader(VideoStandardLoader):
    """A rig camera whose true frame times come from a sidecar, not the container.

    Session-routed only.  ``can_open`` returns zero so an ordinary video drop
    still resolves to the general video loader: the sidecar convention belongs to
    the acquisition software, and a plain MP4 with an unrelated CSV beside it must
    not be reinterpreted through it.
    """

    @classmethod
    def display_name(cls) -> str:
        return "Rig Camera (sidecar-timed)"

    def __init__(self) -> None:
        super().__init__()
        self._exact_master: np.ndarray | None = None
        self._exact_source: np.ndarray | None = None

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Return 0.0 always; a session names this loader explicitly."""
        return 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Probe the container, then bind its frames to their recorded times.

        Config keys:
            ``frame_timestamps``: path to the sidecar; defaults to the video's
                own stem with a ``.csv`` suffix.
            ``start_time``: master time of the first recorded frame.  Defaults to
                0.0, which leaves the video on its own relative axis.
        """
        super().open(path, config)

        sidecar_value = config.get("frame_timestamps")
        sidecar = Path(sidecar_value) if sidecar_value else find_timestamp_sidecar(path)
        if sidecar is None:
            logger.info("No frame timestamp sidecar beside %s; using container timing.", path.name)
            return

        recorded = read_frame_timestamps(sidecar)
        if recorded is None:
            return

        self._bind_exact_mapping(recorded, float(config.get("start_time", 0.0)), sidecar)

    def _bind_exact_mapping(self, recorded: np.ndarray, start_time: float, sidecar: Path) -> None:
        """Pair recorded exposure times with the media times mpv seeks to."""
        source = self._frame_times
        if source is None or len(source) < 2:
            logger.warning(
                "No container frame timestamps for %s; sidecar timing cannot be applied.",
                self._path,
            )
            return

        paired = min(len(source), len(recorded))
        if len(source) != len(recorded):
            # Pairing runs from frame zero, so a common prefix is still correct
            # for every frame it covers.  Worth saying out loud: a large mismatch
            # usually means the sidecar belongs to a different take.
            logger.warning(
                "%s has %d frames but %s lists %d; timing the first %d.",
                Path(str(self._path)).name,
                len(source),
                sidecar.name,
                len(recorded),
                paired,
            )

        self._exact_source = np.asarray(source[:paired], dtype=np.float64)
        self._exact_master = recorded[:paired] + start_time
        logger.info(
            "%s timed from %s: %d frames over %.3f s (container claimed %.3f s at %.3f fps).",
            Path(str(self._path)).name,
            sidecar.name,
            paired,
            float(self._exact_master[-1] - self._exact_master[0]),
            self._duration,
            self._fps,
        )

    def exact_time_mapping(self) -> tuple[np.ndarray, np.ndarray] | None:
        """Return per-frame ``(master_time, source_time)`` evidence, if available."""
        if self._exact_master is None or self._exact_source is None:
            return None
        return self._exact_master, self._exact_source
