"""Session state and JSON serialization for .avv files."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QSettings


@dataclasses.dataclass
class VideoEntry:
    """Persisted state for one loaded video."""

    path: str
    offset: float = 0.0
    drift_ppm: float = 0.0
    integrity_flags: dict[str, object] = dataclasses.field(default_factory=dict)
    metadata: dict[str, object] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class SensorEntry:
    """Persisted state for one loaded sensor CSV."""

    path: str
    channels: list[str] = dataclasses.field(default_factory=list)
    loader_id: str = ""
    import_config: dict[str, object] = dataclasses.field(default_factory=dict)
    import_report: dict[str, object] | None = None


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
    drift_ppm: float
    rms_residual: float
    max_residual: float
    matched_count: int
    rejected_count: int
    tolerance: float
    matches: list[dict[str, float]] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class SessionState:
    """Complete serialisable state of a AvialView session.

    Only stores paths and logical offsets — UI geometry is stored separately
    via QSettings so it does not pollute the data-layer .avv file.
    """

    videos: list[VideoEntry] = dataclasses.field(default_factory=list)
    sensors: list[SensorEntry] = dataclasses.field(default_factory=list)
    markers: list[MarkerEntry] = dataclasses.field(default_factory=list)
    sync_provenance: list[SyncProvenance] = dataclasses.field(default_factory=list)
    t_start: float = 0.0
    t_end: float = 0.0
    plot_x0: float | None = None
    plot_x1: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dict (always writes version 4)."""
        return {
            "version": 4,
            "videos": [dataclasses.asdict(v) for v in self.videos],
            "sensors": [dataclasses.asdict(s) for s in self.sensors],
            "markers": [dataclasses.asdict(m) for m in self.markers],
            "sync_provenance": [dataclasses.asdict(p) for p in self.sync_provenance],
            "t_start": self.t_start,
            "t_end": self.t_end,
            "plot_x0": self.plot_x0,
            "plot_x1": self.plot_x1,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        """Deserialise from a parsed JSON dict (accepts v1 through v4)."""
        version = data.get("version", 1)
        if version not in (1, 2, 3, 4):
            raise ValueError(f"Unsupported session file version: {version}")

        videos = [
            VideoEntry(
                path=v["path"],
                offset=v.get("offset", 0.0),
                drift_ppm=v.get("drift_ppm", 0.0),
                integrity_flags=v.get("integrity_flags", {}),
                metadata=v.get("metadata", {}),
            )
            for v in data.get("videos", [])
        ]
        sensors = [
            SensorEntry(
                path=s["path"],
                channels=s.get("channels", []),
                loader_id=s.get("loader_id", ""),
                import_config=s.get("import_config", {}),
                import_report=s.get("import_report"),
            )
            for s in data.get("sensors", [])
        ]
        markers = [
            MarkerEntry(
                t_start=float(m["t_start"]),
                t_end=float(m["t_end"]) if m.get("t_end") is not None else None,
                label=m.get("label", ""),
                video_frames=list(m.get("video_frames", [])),
            )
            for m in data.get("markers", [])
        ]
        sync_provenance = [
            SyncProvenance(
                reference_id=str(item["reference_id"]),
                target_id=str(item["target_id"]),
                offset=float(item["offset"]),
                drift_ppm=float(item["drift_ppm"]),
                rms_residual=float(item["rms_residual"]),
                max_residual=float(item["max_residual"]),
                matched_count=int(item["matched_count"]),
                rejected_count=int(item["rejected_count"]),
                tolerance=float(item["tolerance"]),
                matches=[
                    {
                        "reference_time": float(match["reference_time"]),
                        "target_time": float(match["target_time"]),
                        "residual": float(match["residual"]),
                    }
                    for match in item.get("matches", [])
                ],
            )
            for item in data.get("sync_provenance", [])
        ]

        return cls(
            videos=videos,
            sensors=sensors,
            markers=markers,
            sync_provenance=sync_provenance,
            t_start=data.get("t_start", 0.0),
            t_end=data.get("t_end", 0.0),
            plot_x0=data.get("plot_x0"),
            plot_x1=data.get("plot_x1"),
        )

    def save(self, path: Path) -> None:
        """Write session to a .avv JSON file atomically."""
        tmp = path.with_suffix(".avv.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> SessionState:
        """Read a .avv session file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


# ── Recent-files helper ──────────────────────────────────────────────

_MAX_RECENT = 10
_SETTINGS_KEY = "session/recent_files"


def add_recent(path: str) -> None:
    """Push *path* to the top of the recent-files list."""
    settings = QSettings("AvialView", "AvialView")
    recent: list[str] = cast(list[str], settings.value(_SETTINGS_KEY, [], type=list))
    if path in recent:
        recent.remove(path)
    recent.insert(0, path)
    settings.setValue(_SETTINGS_KEY, recent[:_MAX_RECENT])


def get_recent() -> list[str]:
    """Return the recent-files list, newest first."""
    settings = QSettings("AvialView", "AvialView")
    return cast(list[str], settings.value(_SETTINGS_KEY, [], type=list))


def clear_recent() -> None:
    """Clear the recent-files list."""
    settings = QSettings("AvialView", "AvialView")
    settings.setValue(_SETTINGS_KEY, [])
