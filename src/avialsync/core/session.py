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
    #: Source-to-master mapping (schema v6).  Time-series sources get the same
    #: offset/drift treatment as video so a sensor recorded on its own clock can
    #: be aligned without rewriting cached samples.
    offset: float = 0.0
    drift_ppm: float = 0.0


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
    #: How this mapping was arrived at (schema v9). The numbers beside it
    #: cannot say: a typed offset and a three-event fit with perfect residuals
    #: are the same six floats, and the reader used to render the typed one as
    #: the most confident record in the session. Values are
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
    #: holds (schema v9). Accepting a fit and then nudging the source by five
    #: frames left the session still claiming the fit's residual, because
    #: nothing connected the two; the record is kept rather than deleted so the
    #: user can see what the alignment *was*, and that it is no longer that.
    superseded_by: str = ""
    matches: list[dict[str, float]] = dataclasses.field(default_factory=list)
    exact_master: list[float] | np.ndarray = dataclasses.field(default_factory=list)
    exact_source: list[float] | np.ndarray = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class SessionState:
    """Complete serialisable state of a AvialSync session.

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
    #: Overlay visibility, schema v7 (D-090). Only differences from each
    #: layer's default are written, so a later change of default still reaches
    #: sessions that never expressed a preference.
    overlays: dict[str, Any] = dataclasses.field(default_factory=dict)
    #: Per-source display window, schema v7 (D-093). Normalised 0-1 so it keeps
    #: its meaning if the same rig is later recorded at a different bit depth.
    display_levels: dict[str, Any] = dataclasses.field(default_factory=dict)
    #: Hand corrections to tracked points, schema v8 (D-099). Sparse: one entry
    #: per coordinate the user moved, in the pose source's own video pixels. The
    #: imported CSV and its cache are never rewritten, so removing this list
    #: restores exactly the model's own predictions.
    point_edits: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dict (always writes version 9)."""
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
            "version": 9,
            "videos": [dataclasses.asdict(v) for v in self.videos],
            "sensors": [dataclasses.asdict(s) for s in self.sensors],
            "markers": [dataclasses.asdict(m) for m in self.markers],
            "sync_provenance": provenance,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "plot_x0": self.plot_x0,
            "plot_x1": self.plot_x1,
            "overlays": self.overlays,
            "display_levels": self.display_levels,
            "point_edits": self.point_edits,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        """Deserialise from a parsed JSON dict (accepts v1 through v8).

        Every v8 field is optional with a default, so a v7 file loads and
        renders exactly as it did before the bump -- that equivalence is the
        migration test, not an aspiration.
        """
        version = data.get("version", 1)
        if version not in (1, 2, 3, 4, 5, 6, 7, 8, 9):
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
                # Pre-v6 sessions have no sensor mapping; identity is correct.
                offset=float(s.get("offset", 0.0)),
                drift_ppm=float(s.get("drift_ppm", 0.0)),
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
                # A v8 session recorded nothing but affine fits and manual
                # entries it could not distinguish, so "affine" is the only
                # honest default -- and the reason the field exists is that the
                # two were indistinguishable, which no migration can undo.
                method=str(item.get("method", "affine")),
                reference_count=int(item.get("reference_count", 0)),
                target_count=int(item.get("target_count", 0)),
                offset_stderr=float(item.get("offset_stderr", 0.0)),
                ambiguity_margin=float(item.get("ambiguity_margin", 1.0)),
                superseded_by=str(item.get("superseded_by", "")),
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
            overlays=data.get("overlays") or {},
            display_levels=data.get("display_levels") or {},
            point_edits=list(data.get("point_edits") or []),
        )

    def save(self, path: Path) -> None:
        """Write session JSON and large exact mappings atomically.

        Small mappings remain inline for backwards-readable hand-authored
        sessions.  Per-frame mappings use compact NumPy sidecars so saving does
        not first inflate them into millions of Python floats or JSON tokens.
        """
        # `to_dict` validates every provenance entry's array lengths and raises
        # on a mismatch, so it has already run for all of them by the time this
        # loop starts; repeating the check here was unreachable.
        payload = self.to_dict()
        sidecar_dir = path.with_suffix(f"{path.suffix}.avialcache")
        for index, provenance in enumerate(self.sync_provenance):
            master = np.asarray(provenance.exact_master, dtype=np.float64)
            source = np.asarray(provenance.exact_source, dtype=np.float64)
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
