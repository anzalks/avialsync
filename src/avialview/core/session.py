"""Session state and JSON serialization for .avv files."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import numpy as np

_EXACT_MAPPING_INLINE_LIMIT = 500


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
    exact_master: list[float] | np.ndarray = dataclasses.field(default_factory=list)
    exact_source: list[float] | np.ndarray = dataclasses.field(default_factory=list)


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
        """Serialise to a JSON-compatible dict (always writes version 5)."""
        provenance = []
        for item in self.sync_provenance:
            encoded = dataclasses.asdict(item)
            master = np.asarray(item.exact_master, dtype=np.float64)
            source = np.asarray(item.exact_source, dtype=np.float64)
            if len(master) != len(source):
                raise ValueError("Exact synchronization arrays have different lengths.")
            encoded["exact_master"] = (
                master.tolist() if len(master) <= _EXACT_MAPPING_INLINE_LIMIT else []
            )
            encoded["exact_source"] = (
                source.tolist() if len(source) <= _EXACT_MAPPING_INLINE_LIMIT else []
            )
            provenance.append(encoded)
        return {
            "version": 5,
            "videos": [dataclasses.asdict(v) for v in self.videos],
            "sensors": [dataclasses.asdict(s) for s in self.sensors],
            "markers": [dataclasses.asdict(m) for m in self.markers],
            "sync_provenance": provenance,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "plot_x0": self.plot_x0,
            "plot_x1": self.plot_x1,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        """Deserialise from a parsed JSON dict (accepts v1 through v5)."""
        version = data.get("version", 1)
        if version not in (1, 2, 3, 4, 5):
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
                exact_master=[float(value) for value in item.get("exact_master", [])],
                exact_source=[float(value) for value in item.get("exact_source", [])],
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
        """Write session JSON and large exact mappings atomically.

        Small mappings remain inline for backwards-readable hand-authored
        sessions.  Per-frame mappings use compact NumPy sidecars so saving does
        not first inflate them into millions of Python floats or JSON tokens.
        """
        payload = self.to_dict()
        sidecar_dir = path.with_suffix(f"{path.suffix}.avialcache")
        for index, provenance in enumerate(self.sync_provenance):
            master = np.asarray(provenance.exact_master, dtype=np.float64)
            source = np.asarray(provenance.exact_source, dtype=np.float64)
            if len(master) != len(source):
                raise ValueError("Exact synchronization arrays have different lengths.")
            if len(master) <= _EXACT_MAPPING_INLINE_LIMIT:
                continue
            sidecar_dir.mkdir(parents=True, exist_ok=True)
            filename = f"exact-sync-{index}-{uuid.uuid4().hex}.npz"
            mapping_path = sidecar_dir / filename
            temporary_path = sidecar_dir / f".{filename}.tmp.npz"
            np.savez_compressed(temporary_path, master=master, source=source)
            digest = hashlib.sha256(temporary_path.read_bytes()).hexdigest()
            os.replace(temporary_path, mapping_path)
            item = payload["sync_provenance"][index]
            item["exact_master"] = []
            item["exact_source"] = []
            item["exact_mapping"] = {
                "file": str(mapping_path.relative_to(path.parent)),
                "sha256": digest,
                "count": int(len(master)),
            }
        tmp = path.with_suffix(".avv.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> SessionState:
        """Read a .avv session file and validate any exact-map sidecars."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        state = cls.from_dict(data)
        raw_provenance = data.get("sync_provenance", [])
        for index, raw in enumerate(raw_provenance):
            mapping = raw.get("exact_mapping")
            if mapping is None:
                continue
            try:
                mapping_path = path.parent / str(mapping["file"])
                file_bytes = mapping_path.read_bytes()
                if hashlib.sha256(file_bytes).hexdigest() != str(mapping["sha256"]):
                    raise ValueError("checksum mismatch")
                with np.load(mapping_path) as arrays:
                    master = np.asarray(arrays["master"], dtype=np.float64)
                    source = np.asarray(arrays["source"], dtype=np.float64)
                if len(master) != len(source) or len(master) != int(mapping["count"]):
                    raise ValueError("array length mismatch")
            except (KeyError, OSError, ValueError):
                raise ValueError(
                    f"Invalid exact synchronization sidecar for entry {index}."
                ) from None
            state.sync_provenance[index].exact_master = master
            state.sync_provenance[index].exact_source = source
        return state
