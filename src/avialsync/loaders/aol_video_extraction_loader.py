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

        self._validate_time_axis(path)
        self._time_shift = self._resolve_time_shift()
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

    def _resolve_time_shift(self) -> float:
        """Return what to add to the file's own axis to reach master time.

        Which correction applies depends on *which* axis the file turned out to
        carry, and only this object knows that -- the sidecar does not say, and
        a session scanner would have to open the HDF5 to find out. So the
        session hands over both reference points and the decision is made here
        rather than guessed at scan time.

        An AOL session's master axis is seconds since midnight UTC (D-045): the
        manifest reads each camera's absolute start epoch and subtracts the
        session's anchor-date epoch. So an absolute POSIX axis needs that same
        anchor subtracted, while a recording-relative axis starting at 0.0
        needs its camera's already-rebased start added instead.

        Both default to ``0.0``, so a file opened on its own outside a session
        keeps whichever axis it was written with.
        """
        if self._times_are_epoch:
            return -float(self._config.get("anchor_epoch", 0.0))
        return float(self._config.get("start_epoch", 0.0))

    def _read_time_axis(self, handle: Any, path: Path) -> None:
        """Prefer the absolute POSIX axis; fall back to recording-relative.

        ``absolute_times`` comes from the camera's own timestamp log rather
        than from ``sampling_rate * index``, which is what makes it usable for
        cross-source alignment.
        """
        if "absolute_times" in handle:
            self._times = np.asarray(handle["absolute_times"], dtype=np.float64).ravel()
            self._times_are_epoch = True
        elif "timestamps" in handle:
            self._times = np.asarray(handle["timestamps"], dtype=np.float64).ravel()
            self._times_are_epoch = False
            logger.info("%s has no absolute_times; using the recording-relative axis.", path.name)
        else:
            raise SourceOpenError(
                f"Neither 'absolute_times' nor 'timestamps' found in {path}. "
                "A video-extraction export always carries one of them."
            )

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
