"""Headless dataclasses for import statistics and source integrity (D-020).

No PySide6 imports — enforced by test_headless_core.py.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from avialsync.core.messages import Message
from avialsync.core.pose import PoseSchema


@dataclasses.dataclass(frozen=True)
class ImportReport:
    """Statistics collected by ImportWorker during one source import."""

    rows_parsed: int = 0
    rows_dropped_duplicate: int = 0
    rows_dropped_nonmonotonic: int = 0
    gap_count: int = 0
    nan_count: int = 0
    sentinel_count: int = 0
    gap_locations: tuple[float, ...] = ()
    import_timestamp: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows_parsed": self.rows_parsed,
            "rows_dropped_duplicate": self.rows_dropped_duplicate,
            "rows_dropped_nonmonotonic": self.rows_dropped_nonmonotonic,
            "gap_count": self.gap_count,
            "nan_count": self.nan_count,
            "sentinel_count": self.sentinel_count,
            "gap_locations": list(self.gap_locations),
            "import_timestamp": self.import_timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ImportReport:
        return cls(
            rows_parsed=d.get("rows_parsed", 0),
            rows_dropped_duplicate=d.get("rows_dropped_duplicate", 0),
            rows_dropped_nonmonotonic=d.get("rows_dropped_nonmonotonic", 0),
            gap_count=d.get("gap_count", 0),
            nan_count=d.get("nan_count", 0),
            sentinel_count=d.get("sentinel_count", 0),
            gap_locations=tuple(d.get("gap_locations", [])),
            import_timestamp=d.get("import_timestamp", 0.0),
        )


@dataclasses.dataclass(frozen=True)
class IntegrityFlags:
    """Anomaly flags for one loaded source.

    Video flags (is_vfr, fps_mismatch) are set by MainWindow._load_video.
    Data flags (has_gaps, fps_provisional) are set by ImportWorker.
    drift_nonzero is set when the user assigns a non-zero drift to any source.
    """

    is_vfr: bool = False
    fps_mismatch: bool = False
    has_gaps: bool = False
    drift_nonzero: bool = False
    fps_provisional: bool = False
    #: The camera's own frame counter skipped exposures it never stored.
    #: Distinct from ``has_gaps``: alignment is intact, resolution is not.
    frames_dropped: bool = False

    @property
    def any_flag(self) -> bool:
        return any(
            [
                self.is_vfr,
                self.fps_mismatch,
                self.has_gaps,
                self.drift_nonzero,
                self.fps_provisional,
                self.frames_dropped,
            ]
        )

    def flag_labels(self) -> list[str]:
        labels = []
        if self.is_vfr:
            labels.append("Variable frame rate")
        if self.fps_mismatch:
            labels.append("Nominal ≠ measured fps")
        if self.has_gaps:
            labels.append("Data gaps detected")
        if self.drift_nonzero:
            labels.append("Non-zero drift set")
        if self.fps_provisional:
            labels.append("FPS is provisional (no video loaded)")
        return labels

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_vfr": self.is_vfr,
            "fps_mismatch": self.fps_mismatch,
            "has_gaps": self.has_gaps,
            "drift_nonzero": self.drift_nonzero,
            "fps_provisional": self.fps_provisional,
            "frames_dropped": self.frames_dropped,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IntegrityFlags:
        return cls(
            is_vfr=d.get("is_vfr", False),
            fps_mismatch=d.get("fps_mismatch", False),
            has_gaps=d.get("has_gaps", False),
            drift_nonzero=d.get("drift_nonzero", False),
            fps_provisional=d.get("fps_provisional", False),
            frames_dropped=d.get("frames_dropped", False),
        )


@dataclasses.dataclass
class SourceInspection:
    """All collected inspection data for one loaded source.

    Not frozen because import_config is a mutable dict.
    """

    path: str
    loader_id: str = ""
    import_config: dict[str, Any] = dataclasses.field(default_factory=dict)
    import_report: ImportReport | None = None
    integrity_flags: IntegrityFlags = dataclasses.field(default_factory=IntegrityFlags)
    fps_binding: str = ""  # "provisional", "bound:<video_path>", or ""

    #: Free-text records the source file carried, in *source* time.  They ride
    #: here rather than on a signal of their own because this is what already
    #: reaches the UI intact on a cache hit, when the loader is never opened at
    #: all.  A manifest written before messages existed simply has none, which
    #: is why no cache version bump is needed: nothing already cached changes
    #: meaning, and a recording re-imported once gains its messages.
    messages: tuple[Message, ...] = ()

    #: What this source's channels *mean*, when it is a pose (D-140). It rides
    #: here for the same reason ``messages`` does: this is what reaches the UI
    #: intact on a cache hit, where the loader is never opened. ``None`` for
    #: every source that is not a pose, which is most of them.
    pose: PoseSchema | None = None
    #: Each channel's unit as its loader declared it -- ``µV`` for ephys, ``deg``
    #: for an encoder angle -- so the plot labels can name what an axis is. It
    #: rides here because this reaches the UI on a cache hit. ``None`` when the
    #: manifest predates the field (not "no units"); empty units are omitted.
    channel_units: dict[str, str] | None = None
    #: Initial plot visibility declared by a loader; saved channel visibility
    #: overrides live in the session, so a changed default reaches untouched files.
    default_channel_visibility: dict[str, bool] | None = None
    #: Optional channel descriptions declared by the source plugin.
    channel_descriptions: dict[str, str] | None = None

    def units(self) -> dict[str, str]:
        """Each channel's unit: the loader's, overridden by any the import set."""
        merged = dict(self.channel_units or {})
        configured = self.import_config.get("units", {})
        if isinstance(configured, dict):
            merged.update({str(name): str(unit) for name, unit in configured.items() if unit})
        return merged

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "loader_id": self.loader_id,
            "import_config": dict(self.import_config),
            "import_report": self.import_report.as_dict() if self.import_report else None,
            "integrity_flags": self.integrity_flags.as_dict(),
            "fps_binding": self.fps_binding,
            "messages": [message.as_dict() for message in self.messages],
            "pose": self.pose.as_dict() if self.pose else None,
            "channel_units": dict(self.channel_units) if self.channel_units is not None else None,
            "default_channel_visibility": (
                dict(self.default_channel_visibility)
                if self.default_channel_visibility is not None
                else None
            ),
            "channel_descriptions": (
                dict(self.channel_descriptions) if self.channel_descriptions is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SourceInspection:
        report_d = d.get("import_report")
        return cls(
            path=d.get("path", ""),
            loader_id=d.get("loader_id", ""),
            import_config=dict(d.get("import_config", {})),
            import_report=ImportReport.from_dict(report_d) if report_d else None,
            integrity_flags=IntegrityFlags.from_dict(d.get("integrity_flags", {})),
            fps_binding=d.get("fps_binding", ""),
            messages=tuple(Message.from_dict(m) for m in d.get("messages", [])),
            pose=PoseSchema.from_dict(d["pose"]) if d.get("pose") else None,
            channel_units=(
                {str(k): str(v) for k, v in d["channel_units"].items()}
                if isinstance(d.get("channel_units"), dict)
                else None
            ),
            default_channel_visibility=(
                {str(k): bool(v) for k, v in d["default_channel_visibility"].items()}
                if isinstance(d.get("default_channel_visibility"), dict)
                else None
            ),
            channel_descriptions=(
                {str(k): str(v) for k, v in d["channel_descriptions"].items()}
                if isinstance(d.get("channel_descriptions"), dict)
                else None
            ),
        )
