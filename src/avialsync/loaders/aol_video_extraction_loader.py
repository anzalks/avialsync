"""Video-extraction-toolbox ROI metric loader.

Reads one camera's extracted optical-flow / motion-energy metrics from the
``video-extraction/<variant>/`` export the behaviour video-extraction-toolbox
writes back into the acquisition tree::

    <recording>/video-extraction/<variant>/FaceCam.mat
    <recording>/video-extraction/<variant>/FaceCam.metadata.json

The MAT file is **v7.3, which is HDF5** -- ``scipy.io.loadmat`` handles MAT 7.2
and below only and cannot open it, so this loader uses ``h5py``.  The JSON
sidecar is required, not optional: MATLAB stores cell/char arrays as HDF5
object references to ``uint16`` arrays, so every label read from the MAT would
have to be dereferenced and character-decoded, while the sidecar carries the
same values as plain JSON types.  The toolbox writes the sidecar whenever it
writes the MAT.

Distinct from :mod:`avialsync.loaders.aol_metric_loader`, which reads the
upstream per-``(ROI, metric)`` v6 store the exporter itself reads from.  This
export is the preferred surface: it carries the time axis, the ROI labels and
the ROI geometry that the per-ROI store does not.
"""

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.errors import MissingColumnError, NonMonotonicTimeError, SourceOpenError
from avialsync.core.source import ChannelInfo, TimeSeriesSource

logger = logging.getLogger(__name__)

#: The sidecar's own identifying tag, and the reason detection is unambiguous
#: rather than "some MATLAB file in the tree".
_TOOL_TAG = "video-extraction-toolbox"

_BATCH_SIZE = 50_000

#: Characters Windows rejects in a filename. A channel name becomes a cache
#: filename verbatim (``PyramidBuilder`` writes ``cache_dir / f"{channel_id}_t.npy"``
#: with no sanitisation), so the schema's suggested ``"{roi}/{column}"`` channel
#: id would be a path separator on POSIX and fail outright on Windows.
_UNSAFE_IN_FILENAME = '<>:"/\\|?*'

#: `metric_column_source` values meaning the column labels were inferred now
#: rather than recorded, and so should be reported rather than trusted silently.
_UNCERTAIN_COLUMN_SOURCES = {"table", "mismatch"}

#: ``config["time_base"]``: place frame 1 at the camera start the session
#: resolved and keep the file's own frame-to-frame spacing, rather than
#: trusting the absolute POSIX axis the exporter wrote. Any other value, and
#: the absence of the key, means the absolute axis rebased onto the anchor --
#: which is what a file opened outside a session gets.
TIME_BASE_CAMERA_START = "camera_start"

#: How far the two axes may disagree about where frame 1 lands before it is
#: worth a log line. Well under the smallest offset an experimenter would care
#: about, and far above the sub-millisecond rounding of a 230 Hz timestamp log.
_AXIS_DISAGREEMENT_TOLERANCE_S = 0.05


def _safe_label(text: str) -> str:
    """Return *text* with characters no Windows filename may contain replaced.

    ROI labels are typed by an experimentalist, so they routinely contain
    spaces and occasionally punctuation. Spaces are legal on all three
    platforms and are kept; the rest of the reserved set is not.
    """
    cleaned = "".join("_" if character in _UNSAFE_IN_FILENAME else character for character in text)
    cleaned = "".join(character if character.isprintable() else "_" for character in cleaned)
    return cleaned.strip() or "roi"


def sidecar_path(path: Path) -> Path:
    """Return the metadata sidecar beside *path*.

    Built from the stem rather than by chaining ``with_suffix`` -- a camera
    named ``Face.Cam`` would otherwise resolve to ``Face.metadata.json``.
    """
    return path.parent / f"{path.stem}.metadata.json"


def read_sidecar(path: Path) -> dict[str, Any] | None:
    """Return the parsed sidecar for *path*, or ``None`` if it is not ours.

    Never raises: this runs inside ``can_open`` for every dropped path, and a
    malformed or unrelated JSON file beside a MAT is a "not mine", not an error.
    """
    sidecar = sidecar_path(path)
    if not sidecar.is_file():
        return None
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(meta, dict) or meta.get("tool") != _TOOL_TAG:
        return None
    return meta


class AOLVideoExtractionLoader(TimeSeriesSource):
    """Extracted ROI Metrics (Video Extraction).

    One file is one camera. Each ``(ROI, column)`` pair is one channel, so a
    7-ROI camera carrying the 10-column ``flow_kinematics`` metric contributes
    70 channels.

    Unlike the pose exports in the same recording folder, these are ordinary
    recorded signals: they are plotted, not drawn over video (D-046).
    """

    @classmethod
    def display_name(cls) -> str:
        return "Extracted ROI Metrics (Video Extraction)"

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._meta: dict[str, Any] = {}
        self._camera: str = ""
        self._times: np.ndarray | None = None
        #: Both recorded axes, as the file carries them. Which one reaches
        #: master time is decided in :meth:`_select_time_axis` once the config
        #: is known, not while reading.
        self._absolute_times: np.ndarray | None = None
        self._relative_times: np.ndarray | None = None
        self._times_are_epoch: bool = False
        self._sampling_rate: float = 0.0
        self._time_shift: float = 0.0
        #: channel name -> (metric, roi_index, column_index)
        self._channels: dict[str, tuple[str, int, int]] = {}
        self._data: dict[str, np.ndarray] = {}

    def is_frame_indexed(self) -> bool:
        """False: this export carries its own time axis.

        The per-ROI v6 store has no time vector and must be told an fps; this
        one records both a recording-relative and an absolute POSIX axis taken
        from the camera's own hardware timestamp log, so nothing here is
        derived from ``index / fps``.
        """
        return False

    @property
    def camera(self) -> str:
        """The camera this file belongs to, as the sidecar names it."""
        return self._camera

    @property
    def times_are_epoch(self) -> bool:
        """Whether the loaded axis is absolute POSIX rather than recording-relative."""
        return self._times_are_epoch

    @property
    def sampling_rate(self) -> float:
        """Nominal frame rate the toolbox recorded, or ``0.0`` when absent."""
        return self._sampling_rate

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Claim a MAT file whose sidecar names this toolbox.

        Reads only the small JSON sidecar, never the HDF5 file, so this stays
        cheap enough to run on every dropped path.
        """
        if path.is_dir() or path.suffix.lower() != ".mat":
            return 0.0
        # A named sidecar carrying the tool's own tag is unambiguous, so this
        # outranks a generic MAT handler without claiming every MATLAB file.
        return 0.95 if read_sidecar(path) is not None else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Read the sidecar, then every numeric array from the HDF5 file."""
        self._path = path
        self._config = config

        meta = read_sidecar(path)
        if meta is None:
            raise SourceOpenError(
                f"No usable '{sidecar_path(path).name}' beside {path.name}. "
                f"This loader needs the '{_TOOL_TAG}' JSON sidecar the toolbox writes "
                "next to every exported .mat; the labels are not readable from the MAT alone."
            )
        self._meta = meta
        self._camera = str(meta.get("camera") or path.stem)

        try:
            import h5py
        except ImportError as exc:  # pragma: no cover - the dependency is declared
            raise SourceOpenError(
                f"Reading {path.name} needs h5py: the toolbox writes MATLAB v7.3, which is "
                "HDF5, and scipy.io.loadmat handles v7.2 and below only."
            ) from exc

        try:
            with h5py.File(path, "r") as handle:
                self._read_time_axis(handle, path)
                self._read_metrics(handle, path)
        except (SourceOpenError, NonMonotonicTimeError):
            raise
        except Exception as exc:
            raise SourceOpenError(
                f"Could not read the HDF5 contents of {path}: {exc}. "
                "Check that this is a video-extraction-toolbox export written as MATLAB v7.3."
            ) from exc

        self._select_time_axis(path)
        self._validate_time_axis(path)
        self._channels = self._build_channels(path)
        self._warn_about_inferred_columns()

        logger.info(
            "Video-extraction loader: %s, %d metric(s), %d channel(s), %d frame(s) at %.3f Hz",
            self._camera,
            len(self._data),
            len(self._channels),
            0 if self._times is None else self._times.size,
            self._sampling_rate,
        )

    def _select_time_axis(self, path: Path) -> None:
        """Choose which recorded axis reaches master time, and how far to move it.

        The two axes are not interchangeable, and the difference is a time
        zone. ``absolute_times`` is true POSIX UTC: the exporter converted the
        camera's *local* wall clock when it wrote the file. An AOL session's
        master axis is the wall clock itself, read as seconds since midnight
        (D-045) -- the encoder log, the camera timing files, and every folder
        name in the tree are on it. Measured on the reference session, the two
        differ by exactly the recording site's UTC offset: 3600 s, which put
        every ROI metric a full hour before the video it was extracted from.

        So inside a session the camera start wins. ``timestamps`` and the
        camera's ``*-relative times.txt`` are the same numbers from the same
        hardware log -- 60.187474 s against 60187.474 ms on the measured file --
        so anchoring frame 1 at the start the manifest already resolved puts the
        metrics on the session's own clock with no time zone in the arithmetic.

        A file opened on its own has no camera start to anchor to and keeps its
        absolute axis, rebased onto whatever anchor it was given.
        """
        absolute, relative = self._absolute_times, self._relative_times
        camera_start = float(self._config.get("start_epoch", 0.0))

        if self._config.get("time_base") == TIME_BASE_CAMERA_START:
            if relative is None:
                # Only an absolute axis was written. Its *spacing* is still the
                # camera's own, so re-zeroing it recovers the relative axis the
                # exporter did not store rather than declining a usable file.
                assert absolute is not None  # _read_time_axis guarantees one axis
                relative = absolute - absolute[0]
            self._times = relative
            self._times_are_epoch = False
            self._time_shift = camera_start
            self._warn_about_axis_disagreement(path)
            return

        if absolute is not None:
            self._times = absolute
            self._times_are_epoch = True
            self._time_shift = -float(self._config.get("anchor_epoch", 0.0))
            return

        self._times = relative
        self._times_are_epoch = False
        self._time_shift = camera_start

    def _warn_about_axis_disagreement(self, path: Path) -> None:
        """Report how far the file's own absolute axis sits from the camera start.

        A whole-hour gap is the recording site's UTC offset and is exactly what
        timing from the camera start exists to absorb. Anything else is the file
        and the session genuinely disagreeing about when the recording began,
        which is worth seeing rather than silently correcting away.
        """
        absolute = self._absolute_times
        anchor = float(self._config.get("anchor_epoch", 0.0))
        if absolute is None or absolute.size == 0 or anchor <= 0.0:
            return
        residual = (absolute[0] - anchor) - self._time_shift
        if abs(residual) <= _AXIS_DISAGREEMENT_TOLERANCE_S:
            return
        logger.info(
            "%s: absolute_times puts frame 1 %.3f s from the camera start this session "
            "resolved; timing from the camera start. A whole-hour difference is the "
            "recording site's UTC offset, which the exporter applied and the session's "
            "wall-clock axis does not (D-045).",
            path.name,
            residual,
        )

    def _read_time_axis(self, handle: Any, path: Path) -> None:
        """Read every recorded axis without yet choosing between them.

        Both are kept: neither is redundant. ``absolute_times`` is the only one
        that means anything to a file opened on its own, and ``timestamps`` is
        the only one free of the time zone the exporter baked into the other.
        Which reaches master time is :meth:`_select_time_axis`'s decision, and
        it needs the config, which is why it is not made here.
        """
        if "absolute_times" in handle:
            self._absolute_times = np.asarray(handle["absolute_times"], dtype=np.float64).ravel()
        if "timestamps" in handle:
            self._relative_times = np.asarray(handle["timestamps"], dtype=np.float64).ravel()

        if self._absolute_times is None and self._relative_times is None:
            raise SourceOpenError(
                f"Neither 'absolute_times' nor 'timestamps' found in {path}. "
                "A video-extraction export always carries one of them."
            )
        if self._absolute_times is None:
            logger.info("%s has no absolute_times; using the recording-relative axis.", path.name)

        if "sampling_rate" in handle:
            rate = np.asarray(handle["sampling_rate"], dtype=np.float64).ravel()
            if rate.size:
                self._sampling_rate = float(rate[0])

    def _read_metrics(self, handle: Any, path: Path) -> None:
        """Load every ``metrics/<metric>`` array, declining ragged ones."""
        group = handle.get("metrics")
        if group is None:
            raise SourceOpenError(
                f"No 'metrics' group in {path}. Check that this is a video-extraction export."
            )

        for metric in group:
            dataset = group[metric]
            if dataset.dtype == object:
                # A per-ROI MATLAB cell, written when one camera's ROIs disagree
                # on shape. Declining beats guessing an indexing scheme: the
                # alternative silently attributes one ROI's numbers to another.
                raise SourceOpenError(
                    f"Metric '{metric}' in {path.name} is stored ragged (a per-ROI cell "
                    "rather than a 3-D array), which this loader cannot index reliably."
                )
            array = np.asarray(dataset, dtype=np.float64)
            if array.ndim != 3:
                raise SourceOpenError(
                    f"Metric '{metric}' in {path.name} has shape {array.shape}; "
                    "expected 3-D (n_roi, n_col, n_frames) as h5py reports it."
                )
            self._data[str(metric)] = array

        if not self._data:
            raise SourceOpenError(f"The 'metrics' group in {path} is empty; nothing to import.")

    def _validate_time_axis(self, path: Path) -> None:
        """Reject a decreasing axis; well-formed exports never have one."""
        times = self._times
        if times is None or times.size == 0:
            raise SourceOpenError(f"{path} carries an empty time axis.")
        if times.size > 1:
            deltas = np.diff(times)
            if np.any(deltas < 0):
                index = int(np.flatnonzero(deltas < 0)[0])
                raise NonMonotonicTimeError(
                    f"Time goes backwards at frame {index + 1} of {path.name}. "
                    "These timestamps come from a per-camera hardware log, which can be "
                    "truncated; the file needs re-exporting.",
                    row=index + 1,
                )

    def _build_channels(self, path: Path) -> dict[str, tuple[str, int, int]]:
        """Map one channel name to each ``(metric, roi, column)`` triple.

        Names are built deterministically -- metrics in sorted order, ROIs and
        columns in array order -- because a channel name becomes a cache
        filename and a session-file key, so it must not depend on dict or set
        iteration order.
        """
        labels = [str(label) for label in self._meta.get("roi_labels", [])]
        roi_ids = list(self._meta.get("roi_ids", []))
        columns_by_metric = self._meta.get("metric_columns", {})
        frames = 0 if self._times is None else self._times.size

        channels: dict[str, tuple[str, int, int]] = {}
        for metric in sorted(self._data):
            array = self._data[metric]
            n_roi, n_col, n_frames = array.shape
            if n_frames != frames:
                raise SourceOpenError(
                    f"Metric '{metric}' in {path.name} has {n_frames} frames but the file "
                    f"carries {frames} timestamps; the export is inconsistent."
                )

            names = columns_by_metric.get(metric)
            if not isinstance(names, list) or len(names) != n_col:
                names = [f"{metric}_{index + 1}" for index in range(n_col)]

            for roi_index in range(n_roi):
                raw_label = labels[roi_index] if roi_index < len(labels) else f"roi{roi_index}"
                roi = _safe_label(raw_label)
                for column_index in range(n_col):
                    column = str(names[column_index])
                    key = self._unique_key(channels, roi, roi_ids, roi_index, metric, column)
                    channels[key] = (metric, roi_index, column_index)
        return channels

    @staticmethod
    def _unique_key(
        taken: dict[str, tuple[str, int, int]],
        roi: str,
        roi_ids: list[Any],
        roi_index: int,
        metric: str,
        column: str,
    ) -> str:
        """Return a channel name not already in *taken*.

        Two independent collisions are possible and both are real. ROI labels
        are user-entered and not unique within a camera, and two metrics in one
        file share column names -- ``motion_index`` and ``flow_kinematics``
        both emit ``MI``. The metric is tried first because it keeps the name
        readable; the ROI id is the fallback that cannot collide, being unique
        by construction.
        """
        base = f"{roi}_{column}"
        if base not in taken:
            return base
        with_metric = f"{roi}_{metric}_{column}"
        if with_metric not in taken:
            return with_metric
        roi_id = roi_ids[roi_index] if roi_index < len(roi_ids) else roi_index
        return f"{roi}#{roi_id}_{metric}_{column}"

    def _warn_about_inferred_columns(self) -> None:
        """Report metrics whose column labels were inferred rather than recorded.

        ``table`` means "something N columns wide turned up and the N-name table
        for this metric was applied", and ``mismatch`` means a stored list was
        rejected. Neither is a reason to refuse the file, but silently
        presenting an inference as a recorded fact is what this avoids.
        """
        sources = self._meta.get("metric_column_source", {})
        if not isinstance(sources, dict):
            return
        for metric, origin in sorted(sources.items()):
            if str(origin) in _UNCERTAIN_COLUMN_SOURCES:
                logger.warning(
                    "Column names for metric '%s' in %s are %s-derived, not recorded with the "
                    "data: they were inferred from the metric name and column count.",
                    metric,
                    self._camera,
                    origin,
                )

    def channels(self) -> list[ChannelInfo]:
        """Return one ChannelInfo per ``(ROI, column)`` pair."""
        rate = self._sampling_rate or None
        return [
            ChannelInfo(name=name, unit="", dtype="Float64", rate_hz=rate)
            for name in self._channels
        ]

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield (time, value) chunks for one channel.

        Compatibility path for the frozen v1 contract; the importer prefers
        ``read_all_chunks``, which serves every channel from the same pass.
        """
        if ch not in self._channels:
            raise MissingColumnError(ch, list(self._channels))
        for chunk in self.read_all_chunks(channels=(ch,)):
            yield chunk[ch]

    def read_all_chunks(
        self, channels: "tuple[str, ...] | None" = None
    ) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
        """Yield every requested channel, batched along the frame axis.

        ``open()`` already materialised the arrays -- the export is one camera's
        worth of frames, not a streaming source -- so batching here bounds what
        the importer is handed per iteration rather than the underlying I/O.

        NaNs pass through untouched. Every file's ``MI`` column begins with one,
        because a frame-difference metric has no predecessor at frame 1;
        dropping or filling it would shift the whole channel one frame against
        every other source in the session.
        """
        if self._path is None or self._times is None:
            raise SourceOpenError(
                "Video-extraction source used before open(). Call open(path, config) first."
            )

        selected = tuple(self._channels) if channels is None else channels
        missing = [name for name in selected if name not in self._channels]
        if missing:
            raise MissingColumnError(missing[0], list(self._channels))

        total = self._times.size
        for start in range(0, total, _BATCH_SIZE):
            stop = min(start + _BATCH_SIZE, total)
            times = self._times[start:stop] + self._time_shift
            chunk: dict[str, tuple[np.ndarray, np.ndarray]] = {}
            for name in selected:
                metric, roi, column = self._channels[name]
                chunk[name] = (times, self._data[metric][roi, column, start:stop])
            yield chunk
