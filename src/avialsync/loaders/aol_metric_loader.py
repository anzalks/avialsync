"""AOL Extracted-Metric MAT Loader.

Reads the per-(ROI, metric) `-v6` MAT files an optical-flow/motion-index
toolbox externalizes next to an AOL session's primary `.mat` -- see
``avialsync_data_schema.md`` for the full contract this loader implements.
Each file holds one plain numeric array under the variable
``roi_metric_data``: no time column, no header, one row per extracted frame.

The primary `Analysis_Set` file (`-v7.3`, MCOS classdef instances) is
explicitly out of scope -- it needs MATLAB or a from-scratch MCOS decoder, and
nothing in this module attempts to read it. Only the plain single-variable
exports under a `data_root`-style folder are handled here.
"""

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.errors import MissingColumnError, SourceOpenError
from avialsync.core.source import ChannelInfo, TimeSeriesSource

logger = logging.getLogger(__name__)

#: `helper_functions/parse_roi_data_filename.m`'s own contract: a positive
#: integer ROI id, a literal double underscore, then the metric name.
#: `thumbnail.mat` never matches (no leading digits), which is what keeps the
#: one reference-frame file per camera folder out of this loader.
ROI_METRIC_FILENAME_RE = re.compile(r"^(\d+)__(.+)\.mat$")

#: `Extracted_Data.saveobj` / `write_roi_metric.m`'s single exported variable.
_VARIABLE_NAME = "roi_metric_data"

#: Column names stored alongside the numbers. Optional, and absent on older
#: files, which is why the metric-name table below still exists as a fallback.
_COLUMNS_VARIABLE_NAME = "roi_metric_columns"

_BATCH_SIZE = 50_000

#: `get_metric_column_names` in `Video.m` -- column order for the built-in
#: metrics. A custom metric (arbitrary `varname` passed to `Video.analyse`)
#: has no fixed shape, so it falls back to generic names sized to the array.
_METRIC_COLUMNS: dict[str, list[str]] = {
    "motion_index": ["MI"],
    "optical_flow": ["MI", "MeanFlow", "TopFlow", "DirCoh", "Brightness"],
    "flow_kinematics": [
        "MI",
        "MeanFlow",
        "TopFlow",
        "DirCoh",
        "Brightness",
        "Axial",
        "Lateral",
        "Speed",
        "PeakSpeed",
        "Drift",
    ],
}


def _stored_column_names(raw: object) -> list[str] | None:
    """Return column names read from the file, or ``None`` when it stored none.

    MATLAB writes this as a cell of char arrays, which ``scipy.io.loadmat``
    hands back as a nested object array; older exports omit the variable
    entirely. Anything unreadable is treated as absent rather than fatal --
    the numbers are still perfectly good with fallback names.
    """
    if raw is None:
        return None
    try:
        flattened = np.asarray(raw, dtype=object).ravel()
        names = [
            str(np.asarray(item).ravel()[0]) if np.ndim(item) else str(item) for item in flattened
        ]
    except (TypeError, ValueError, IndexError):
        return None
    cleaned = [name.strip() for name in names if str(name).strip()]
    return cleaned or None


def _column_names(metric: str, n_columns: int) -> list[str]:
    """Resolve column names for *metric*, falling back to generic ones.

    A mismatch between a recognised metric's expected width and what is
    actually in the file (a version skew, a hand-edited export) is not
    guessed past -- attaching the wrong semantic label to a column is worse
    than a generic one, so a mismatch logs and falls back rather than
    truncating or padding the known list.
    """
    known = _METRIC_COLUMNS.get(metric)
    if known is not None and len(known) == n_columns:
        return known
    if known is not None:
        logger.warning(
            "MAT metric '%s' has %d column(s), expected %d for a built-in metric; "
            "using generic column names instead of mislabeling them.",
            metric,
            n_columns,
            len(known),
        )
    if n_columns == 1:
        return [metric]
    return [f"{metric}_{i}" for i in range(n_columns)]


class AOLMetricLoader(TimeSeriesSource):
    """Extracted Metric (Optical Flow / MI).

    Format: single-variable `-v6` MAT file, filename
    ``<roi_id>__<metric>.mat``. Columns follow §3 of
    ``avialsync_data_schema.md``. No time axis is stored; frame index (row
    order) combines with the camera's fps and start epoch, supplied by the
    AOL session manifest exactly as it does for EKS tracking.
    """

    @classmethod
    def display_name(cls) -> str:
        return "Extracted Metric (Optical Flow / MI)"

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._metric: str = ""
        self._data: np.ndarray | None = None
        self._channel_names: list[str] = []

    def is_frame_indexed(self) -> bool:
        """Rows are frames with no stored time axis, same contract as EKS."""
        return True

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Match the `<roi_id>__<metric>.mat` filename, then confirm the variable.

        The variable check uses ``scipy.io.whosmat``, which reads only the MAT
        header -- cheap enough to run on every dropped path, unlike loading
        the array itself.
        """
        if path.is_dir():
            return 0.0
        if path.suffix.lower() != ".mat":
            return 0.0
        if ROI_METRIC_FILENAME_RE.match(path.name) is None:
            return 0.0

        try:
            from scipy.io import whosmat

            names = {entry[0] for entry in whosmat(str(path))}
        except Exception:
            return 0.0

        return 0.9 if _VARIABLE_NAME in names else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Load the single `roi_metric_data` array and resolve column names."""
        self._path = path
        self._config = config

        match = ROI_METRIC_FILENAME_RE.match(path.name)
        if match is None:
            raise SourceOpenError(
                f"Filename does not match '<roi_id>__<metric>.mat': {path}. "
                "Check that this is a data_root export, not the primary Analysis_Set file."
            )
        self._metric = str(config.get("metric") or match.group(2))

        try:
            from scipy.io import loadmat

            mat = loadmat(str(path))
        except Exception as exc:
            raise SourceOpenError(
                f"Could not read MAT file {path}: {exc}. "
                "This loader reads plain '-v6' single-variable exports only -- the primary "
                "Analysis_Set file ('-v7.3', MCOS classdef instances) needs MATLAB to read."
            ) from exc

        if _VARIABLE_NAME not in mat:
            raise SourceOpenError(
                f"'{_VARIABLE_NAME}' variable not found in {path}. "
                "Check that this is a per-ROI metric export from write_roi_metric.m."
            )

        stored_columns = _stored_column_names(mat.get(_COLUMNS_VARIABLE_NAME))
        data = np.asarray(mat[_VARIABLE_NAME], dtype=np.float64)
        if data.ndim == 1:
            data = data[:, None]
        elif data.ndim != 2:
            raise SourceOpenError(
                f"Unexpected '{_VARIABLE_NAME}' shape {data.shape} in {path}; "
                "expected a 1-D or 2-D numeric array (T frames x C columns)."
            )

        self._data = data
        # Names recorded with the numbers beat names inferred from the metric
        # name: the file is the only thing that knows what it actually wrote.
        if stored_columns is not None and len(stored_columns) == data.shape[1]:
            self._channel_names = stored_columns
        else:
            if stored_columns is not None:
                logger.warning(
                    "'%s' in %s lists %d name(s) for %d column(s); ignoring it.",
                    _COLUMNS_VARIABLE_NAME,
                    path.name,
                    len(stored_columns),
                    data.shape[1],
                )
            self._channel_names = _column_names(self._metric, data.shape[1])

        logger.info(
            "AOL metric loader: %d frame(s), %d channel(s) (%s) from %s",
            data.shape[0],
            len(self._channel_names),
            self._metric,
            path.name,
        )

    def channels(self) -> list[ChannelInfo]:
        """Return one ChannelInfo per column, at the camera's frame rate."""
        rate_hz = float(self._config.get("fps", 0.0)) or None
        return [
            ChannelInfo(name=name, unit="", dtype="Float64", rate_hz=rate_hz)
            for name in self._channel_names
        ]

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield (time, value) chunks for one channel.

        Compatibility path for the frozen v1 contract; a caller reading every
        channel should prefer ``read_all_chunks`` to project every column in
        one pass instead of one full scan per channel.
        """
        if ch not in self._channel_names:
            raise MissingColumnError(ch, list(self._channel_names))
        for chunk in self.read_all_chunks(channels=(ch,)):
            yield chunk[ch]

    def read_all_chunks(
        self, channels: "tuple[str, ...] | None" = None
    ) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
        """Yield every requested channel from the in-memory array, batch by batch.

        The MAT file is already fully materialized by ``open()`` -- ``scipy.io``
        has no partial-read API for `-v6` files -- so batching here only bounds
        how much gets handed to the importer per iteration, not the underlying
        I/O. Frame index is ``arange``-derived, so it is monotonic by
        construction and needs none of the boundary de-duplication the EKS CSV
        loader carries for its externally-authored frame numbers.
        """
        if self._path is None or self._data is None:
            raise SourceOpenError(
                "Metric source used before open(). Call open(path, config) first."
            )

        selected = channels if channels is not None else tuple(self._channel_names)
        try:
            col_indices = [self._channel_names.index(name) for name in selected]
        except ValueError as exc:
            raise MissingColumnError(str(exc), list(self._channel_names)) from exc

        fps = float(self._config.get("fps", 30.0))
        start_epoch = float(self._config.get("start_epoch", 0.0))
        n_rows = self._data.shape[0]

        for start in range(0, n_rows, _BATCH_SIZE):
            end = min(start + _BATCH_SIZE, n_rows)
            t = np.arange(start, end, dtype=np.float64) / fps + start_epoch
            yield {
                name: (t, self._data[start:end, idx])
                for name, idx in zip(selected, col_indices, strict=True)
            }
