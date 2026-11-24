"""Session state and JSON serialization for .avv files."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from avialsync.core.session_io import (
    _EXACT_MAPPING_INLINE_LIMIT,
    EXACT_MAPPING_DIR_SUFFIX,
    exact_mapping_dir,
    load_session_file,
    parse_imaging_entries,
    parse_marker_entries,
    parse_sensor_entries,
    parse_sync_provenance,
    parse_trigger_entries,
    parse_video_entries,
    save_session_file,
)

__all__ = [
    "EXACT_MAPPING_DIR_SUFFIX",
    "ImagingEntry",
    "MarkerEntry",
    "SensorEntry",
    "SessionState",
    "SyncProvenance",
    "TriggerEntry",
    "VideoEntry",
    "exact_mapping_dir",
]


@dataclasses.dataclass
class VideoEntry:
    """Persisted state for one loaded video."""

    path: str
    offset: float = 0.0
    drift_ms_per_hour: float = 0.0
    integrity_flags: dict[str, object] = dataclasses.field(default_factory=dict)
    metadata: dict[str, object] = dataclasses.field(default_factory=dict)
    view: dict[str, float] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ImagingEntry:
    """Persisted imaging stack, its import choices, mapping and display (schema v13).

    ``import_config`` holds the scientific choices made at import -- dataset,
    axis order, depth plane, a typed frame rate -- so a reopened session reads
    the same planes at the same times without asking again. ``display`` holds
    the viewer's channel, level and averaging choices
    (:class:`avialsync.core.imaging_display.ImagingView`); it never changes
    which plane is shown when.
    """

    path: str
    loader_id: str
    import_config: dict[str, Any] = dataclasses.field(default_factory=dict)
    offset: float = 0.0
    drift_ms_per_hour: float = 0.0
    display: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class SensorEntry:
    """Persisted state for one loaded time-series source."""

    path: str
    channels: list[str] = dataclasses.field(default_factory=list)
    loader_id: str = ""
    import_config: dict[str, object] = dataclasses.field(default_factory=dict)
    import_report: dict[str, object] | None = None
    #: Source-to-master mapping (schema v6).  Time-series sources get the same
    #: offset/drift treatment as video so a sensor recorded on its own clock can
    #: be aligned without rewriting cached samples.
    offset: float = 0.0
    drift_ms_per_hour: float = 0.0
    #: Per-tracker presentation choices (schema v11).  They are intentionally
    #: per source: a 2D pose file may be compared against raw footage without
    #: hiding another camera's tracker, and a dense pose need not occupy plots.
    tracking_overlay_visible: bool = True
    tracking_plot_visible: bool = False
    #: User overrides from loader-declared channel visibility defaults (schema v14).
    channel_visibility: dict[str, bool] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class MarkerEntry:
    """Persisted annotation marker."""

    t_start: float
    t_end: float | None = None
    label: str = ""
    video_frames: list[dict[str, Any]] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class SyncProvenance:
    """Accepted synchronization evidence summary persisted in a session."""

    reference_id: str
    target_id: str
    offset: float
    drift_ms_per_hour: float
    rms_residual: float
    max_residual: float
    matched_count: int
    rejected_count: int
    tolerance: float
    #: How this mapping was arrived at (schema v9). Values are
    #: `core.sync.AlignmentMethod`; a v8 session has none and is read back as
    #: an affine fit, which is what every mapping those sessions could record
    #: actually was.
    method: str = "affine"
    #: Events offered on each side (schema v9), so a match *rate* can be
    #: stated. Not recoverable from `rejected_count`, which sums both sides.
    reference_count: int = 0
    target_count: int = 0
    #: Uncertainty on the offset, `rms/sqrt(n)` (schema v9). `max_residual` is
    #: a bound on the worst single pair and reads as a "±" when printed as one.
    offset_stderr: float = 0.0
    #: How decisively the winning lag beat the best rival at a different one
    #: (schema v9). 1.0 is unopposed; 0.0 is a coin toss.
    ambiguity_margin: float = 1.0
    #: What replaced this evidence, when the mapping it describes no longer
    #: holds (schema v9). Kept rather than deleted so the user can see what
    #: the alignment *was*, and that it is no longer that.
    superseded_by: str = ""
    #: The window of reference time the fit was computed over (schema v9), when
    #: the user restricted it.
    restricted_to: list[float] = dataclasses.field(default_factory=list)
    matches: list[dict[str, float]] = dataclasses.field(default_factory=list)
    exact_master: list[float] | np.ndarray = dataclasses.field(default_factory=list)
    exact_source: list[float] | np.ndarray = dataclasses.field(default_factory=list)
    #: The clock the reference events were recorded on.
    reference_clock_id: str = ""
    #: 0.0 for a record saved before precision was assessed: "not
    #: assessed" is reported, never "unverified".
    precision_requirement: float = 0.0
    precision_verified: bool = False
    coverage_fraction: float = 0.0
    largest_unsupported_interval: float = 0.0
    extrapolated_before: float = 0.0
    extrapolated_after: float = 0.0
    excluded_incomplete_count: int = 0
    measurement_resolution: float = 0.0
    #: Reference events inside the target's recording once mapped.
    overlap_reference_count: int = 0
    exact_offset_anchor: float | None = None
    exact_drift_anchor: float | None = None
    settings: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class TriggerEntry:
    """A trigger file and what the user said its lines are (schema v9).

    Only the path and the configuration are stored. The trains themselves are
    re-read on restore, exactly as sensor channels are re-imported, so a file
    that has changed on disk is read as it now is rather than as it once was.
    """

    path: str
    config: dict[str, Any] = dataclasses.field(default_factory=dict)
    offset: float = 0.0
    drift_ms_per_hour: float = 0.0


@dataclasses.dataclass
class SessionState:
    """Complete serialisable state of an AvialSync session.

    Only stores paths and logical offsets — UI geometry is stored separately
    via QSettings so it does not pollute the data-layer .avv file.
    """

    videos: list[VideoEntry] = dataclasses.field(default_factory=list)
    imaging: list[ImagingEntry] = dataclasses.field(default_factory=list)
    sensors: list[SensorEntry] = dataclasses.field(default_factory=list)
    markers: list[MarkerEntry] = dataclasses.field(default_factory=list)
    sync_provenance: list[SyncProvenance] = dataclasses.field(default_factory=list)
    t_start: float = 0.0
    t_end: float = 0.0
    plot_x0: float | None = None
    plot_x1: float | None = None
    #: Overlay visibility, schema v7. Only differences from each layer's default
    #: are written.
    overlays: dict[str, Any] = dataclasses.field(default_factory=dict)
    #: Per-source display window, schema v7 (normalised 0-1).
    display_levels: dict[str, Any] = dataclasses.field(default_factory=dict)
    #: Hand corrections to tracked points, schema v8.
    point_edits: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    #: Unix epoch of master-clock zero, after NWB's `session_start_time` (schema v9).
    session_start_time: float = 0.0
    #: Trigger evidence the user loaded and typed (schema v9).
    triggers: list[TriggerEntry] = dataclasses.field(default_factory=list)
    #: Accepted identity swaps per pose source, schema v10.
    identity_swaps: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    #: Compare imported tracker against edited generation without changing either.
    show_original_tracker: bool = False
    #: 3D view orientation and camera zoom/pan for this session.
    view_3d: dict[str, Any] = dataclasses.field(default_factory=dict)
    #: Plot layout presentation mode (schema v15): stacked, grouped, overlay, or heatmap.
    plot_view_mode: str = "stacked"
    #: Pinned channels kept visible at the top of the plot pane (schema v15).
    pinned_channels: list[dict[str, str]] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dict (always writes version 15)."""
        provenance = [_encode_sync_provenance(item) for item in self.sync_provenance]
        markers = [
            {
                "t_start": m.t_start,
                "t_end": m.t_end,
                "label": m.label,
                "video_frames": [dict(vf) for vf in m.video_frames],
            }
            for m in self.markers
        ]
        return {
            "version": 15,
            "videos": [dataclasses.asdict(v) for v in self.videos],
            "imaging": [dataclasses.asdict(v) for v in self.imaging],
            "sensors": [dataclasses.asdict(s) for s in self.sensors],
            "markers": markers,
            "sync_provenance": provenance,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "plot_x0": self.plot_x0,
            "plot_x1": self.plot_x1,
            "overlays": self.overlays,
            "display_levels": self.display_levels,
            "point_edits": self.point_edits,
            "session_start_time": self.session_start_time,
            "triggers": [dataclasses.asdict(entry) for entry in self.triggers],
            "identity_swaps": self.identity_swaps,
            "show_original_tracker": self.show_original_tracker,
            "view_3d": self.view_3d,
            "plot_view_mode": self.plot_view_mode,
            "pinned_channels": [dict(item) for item in self.pinned_channels],
        }

    def exact_pairs(self) -> list[tuple[NDArray[np.float64], NDArray[np.float64]]]:
        """Return float64 ``(master, source)`` arrays aligned with ``sync_provenance``."""
        return [
            (
                np.asarray(item.exact_master, dtype=np.float64),
                np.asarray(item.exact_source, dtype=np.float64),
            )
            for item in self.sync_provenance
        ]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        """Deserialise from a parsed JSON dict (accepts v1 through v15).

        Every added field is optional with a default, so an older file loads and
        renders exactly as it did before the bump.
        """
        version = data.get("version", 1)
        if version not in range(1, 16):
            raise ValueError(f"Unsupported session file version: {version}")
        raw_mode = data.get("plot_view_mode", "stacked")
        mode = (
            str(raw_mode) if raw_mode in ("stacked", "grouped", "overlay", "heatmap") else "stacked"
        )
        pinned = [
            {"source_id": str(item.get("source_id", "")), "channel": str(item["channel"])}
            for item in (data.get("pinned_channels") or [])
            if isinstance(item, dict) and item.get("channel")
        ]
        return cls(
            videos=parse_video_entries(data, VideoEntry),
            imaging=parse_imaging_entries(data, ImagingEntry),
            sensors=parse_sensor_entries(data, SensorEntry),
            markers=parse_marker_entries(data, MarkerEntry),
            sync_provenance=parse_sync_provenance(data, SyncProvenance),
            t_start=data.get("t_start", 0.0),
            t_end=data.get("t_end", 0.0),
            plot_x0=data.get("plot_x0"),
            plot_x1=data.get("plot_x1"),
            session_start_time=float(data.get("session_start_time", 0.0)),
            triggers=parse_trigger_entries(data, TriggerEntry),
            overlays=data.get("overlays") or {},
            display_levels=data.get("display_levels") or {},
            point_edits=list(data.get("point_edits") or []),
            identity_swaps=list(data.get("identity_swaps") or []),
            show_original_tracker=bool(data.get("show_original_tracker", False)),
            view_3d=dict(data.get("view_3d") or {}),
            plot_view_mode=mode,
            pinned_channels=pinned,
        )

    def save(self, path: Path) -> None:
        """Write session JSON and large exact mappings atomically."""
        payload = self.to_dict()
        source_paths = (
            *(entry.path for entry in self.videos),
            *(entry.path for entry in self.sensors),
            *(entry.path for entry in self.imaging),
        )
        save_session_file(path, payload, self.exact_pairs(), source_paths)

    @classmethod
    def load(cls, path: Path) -> SessionState:
        """Read a .avv session file and validate any exact-map sidecars."""
        state, sidecars = load_session_file(path, cls.from_dict)
        for index, prepared in sidecars:
            state.sync_provenance[index].exact_master = prepared.master
            state.sync_provenance[index].exact_source = prepared.source
        return state


def _encode_sync_provenance(item: SyncProvenance) -> dict[str, Any]:
    """Serialise one provenance record without deep-copying large exact arrays."""
    if not isinstance(item, SyncProvenance):
        raise TypeError(f"Expected SyncProvenance, got {type(item).__name__}")
    master = np.asarray(item.exact_master, dtype=np.float64)
    source = np.asarray(item.exact_source, dtype=np.float64)
    if len(master) != len(source):
        raise ValueError("Exact synchronization arrays have different lengths.")
    inline = len(master) <= _EXACT_MAPPING_INLINE_LIMIT
    return {
        "reference_id": item.reference_id,
        "target_id": item.target_id,
        "offset": item.offset,
        "drift_ms_per_hour": item.drift_ms_per_hour,
        "rms_residual": item.rms_residual,
        "max_residual": item.max_residual,
        "matched_count": item.matched_count,
        "rejected_count": item.rejected_count,
        "tolerance": item.tolerance,
        "method": item.method,
        "reference_count": item.reference_count,
        "target_count": item.target_count,
        "offset_stderr": item.offset_stderr,
        "ambiguity_margin": item.ambiguity_margin,
        "superseded_by": item.superseded_by,
        "restricted_to": list(item.restricted_to),
        "matches": [dict(match) for match in item.matches],
        "exact_master": master.tolist() if inline else [],
        "exact_source": source.tolist() if inline else [],
        "reference_clock_id": item.reference_clock_id,
        "precision_requirement": item.precision_requirement,
        "precision_verified": item.precision_verified,
        "coverage_fraction": item.coverage_fraction,
        "largest_unsupported_interval": item.largest_unsupported_interval,
        "extrapolated_before": item.extrapolated_before,
        "extrapolated_after": item.extrapolated_after,
        "excluded_incomplete_count": item.excluded_incomplete_count,
        "measurement_resolution": item.measurement_resolution,
        "overlap_reference_count": item.overlap_reference_count,
        "exact_offset_anchor": item.exact_offset_anchor,
        "exact_drift_anchor": item.exact_drift_anchor,
        "settings": dict(item.settings),
    }
