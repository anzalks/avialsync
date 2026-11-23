"""File I/O, exact-sync sidecar helpers, and dict parsers for .avv sessions."""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Any, TypeVar

import numpy as np
from numpy.typing import NDArray

from avialsync.core.drift import drift_from_legacy_entry
from avialsync.core.timeline import PreparedExactMapping

_EXACT_MAPPING_INLINE_LIMIT = 500

#: Appended to a session's stem for the folder holding its large exact-sync
#: mappings: ``trial.avv`` -> ``trial_avv_sync/``.
EXACT_MAPPING_DIR_SUFFIX = "_avv_sync"

_EntryT = TypeVar("_EntryT")


def exact_mapping_dir(session_path: Path) -> Path:
    """Return the folder beside *session_path* holding its exact-sync arrays.

    Part of the session, not the cache: a mapping the user accepted is
    a decision, and the session will not open without the arrays it names.
    Keeping them out of the cache root is what makes that root safe to delete.
    """
    return session_path.with_name(f"{session_path.stem}{EXACT_MAPPING_DIR_SUFFIX}")


def parse_video_entries(data: dict[str, Any], factory: Callable[..., _EntryT]) -> list[_EntryT]:
    """Deserialise ``videos`` records from *data* using *factory*."""
    return [
        factory(
            path=v["path"],
            offset=v.get("offset", 0.0),
            drift_ms_per_hour=drift_from_legacy_entry(v),
            integrity_flags=v.get("integrity_flags", {}),
            metadata=v.get("metadata", {}),
            view={str(k): float(val) for k, val in (v.get("view") or {}).items()},
        )
        for v in data.get("videos", [])
    ]


def parse_imaging_entries(data: dict[str, Any], factory: Callable[..., _EntryT]) -> list[_EntryT]:
    """Deserialise ``imaging`` records from *data* using *factory*."""
    return [
        factory(
            path=str(item["path"]),
            loader_id=str(item.get("loader_id", "")),
            import_config=dict(item.get("import_config", {})),
            offset=float(item.get("offset", 0.0)),
            drift_ms_per_hour=float(item.get("drift_ms_per_hour", 0.0)),
            display=dict(item.get("display", {})),
        )
        for item in data.get("imaging", [])
    ]


def parse_sensor_entries(data: dict[str, Any], factory: Callable[..., _EntryT]) -> list[_EntryT]:
    """Deserialise ``sensors`` records from *data* using *factory*."""
    return [
        factory(
            path=s["path"],
            channels=s.get("channels", []),
            channel_visibility={
                str(name): bool(visible)
                for name, visible in s.get("channel_visibility", {}).items()
            },
            loader_id=s.get("loader_id", ""),
            import_config=s.get("import_config", {}),
            import_report=s.get("import_report"),
            # Pre-v6 sessions have no sensor mapping; identity is correct.
            offset=float(s.get("offset", 0.0)),
            drift_ms_per_hour=drift_from_legacy_entry(s),
            tracking_overlay_visible=bool(s.get("tracking_overlay_visible", False)),
            tracking_plot_visible=bool(s.get("tracking_plot_visible", False)),
        )
        for s in data.get("sensors", [])
    ]


def parse_marker_entries(data: dict[str, Any], factory: Callable[..., _EntryT]) -> list[_EntryT]:
    """Deserialise ``markers`` records from *data* using *factory*."""
    return [
        factory(
            t_start=float(m["t_start"]),
            t_end=float(m["t_end"]) if m.get("t_end") is not None else None,
            label=m.get("label", ""),
            video_frames=list(m.get("video_frames", [])),
        )
        for m in data.get("markers", [])
    ]


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _parse_provenance_matches(raw_matches: list[dict[str, Any]]) -> list[dict[str, float]]:
    return [
        {
            "reference_time": float(match["reference_time"]),
            "raw_reference_time": float(match.get("raw_reference_time", match["reference_time"])),
            "target_time": float(match["target_time"]),
            "residual": float(match["residual"]),
        }
        for match in raw_matches
    ]


def parse_sync_provenance(data: dict[str, Any], factory: Callable[..., _EntryT]) -> list[_EntryT]:
    """Deserialise ``sync_provenance`` records from *data* using *factory*."""
    return [
        factory(
            reference_id=str(item["reference_id"]),
            target_id=str(item["target_id"]),
            offset=float(item["offset"]),
            drift_ms_per_hour=drift_from_legacy_entry(item),
            rms_residual=float(item["rms_residual"]),
            max_residual=float(item["max_residual"]),
            matched_count=int(item["matched_count"]),
            rejected_count=int(item["rejected_count"]),
            tolerance=float(item["tolerance"]),
            # A v8 session recorded only affine fits and manual entries it could
            # not distinguish, so "affine" is the honest default on migration.
            method=str(item.get("method", "affine")),
            reference_count=int(item.get("reference_count", 0)),
            target_count=int(item.get("target_count", 0)),
            offset_stderr=float(item.get("offset_stderr", 0.0)),
            ambiguity_margin=float(item.get("ambiguity_margin", 1.0)),
            reference_clock_id=str(item.get("reference_clock_id", "")),
            precision_requirement=float(item.get("precision_requirement", 0.0)),
            precision_verified=bool(item.get("precision_verified", False)),
            coverage_fraction=float(item.get("coverage_fraction", 0.0)),
            largest_unsupported_interval=float(item.get("largest_unsupported_interval", 0.0)),
            extrapolated_before=float(item.get("extrapolated_before", 0.0)),
            extrapolated_after=float(item.get("extrapolated_after", 0.0)),
            excluded_incomplete_count=int(item.get("excluded_incomplete_count", 0)),
            measurement_resolution=float(item.get("measurement_resolution", 0.0)),
            overlap_reference_count=int(item.get("overlap_reference_count", 0)),
            exact_offset_anchor=_optional_float(item.get("exact_offset_anchor")),
            exact_drift_anchor=_optional_float(item.get("exact_drift_anchor")),
            settings=dict(item.get("settings", {})),
            superseded_by=str(item.get("superseded_by", "")),
            restricted_to=[float(value) for value in item.get("restricted_to", [])],
            matches=_parse_provenance_matches(item.get("matches", [])),
            exact_master=[float(value) for value in item.get("exact_master", [])],
            exact_source=[float(value) for value in item.get("exact_source", [])],
        )
        for item in data.get("sync_provenance", [])
    ]


def parse_trigger_entries(data: dict[str, Any], factory: Callable[..., _EntryT]) -> list[_EntryT]:
    """Deserialise ``triggers`` records from *data* using *factory*."""
    return [
        factory(
            path=str(item["path"]),
            config=dict(item.get("config", {})),
            offset=float(item.get("offset", 0.0)),
            drift_ms_per_hour=float(item.get("drift_ms_per_hour", 0.0)),
        )
        for item in data.get("triggers", [])
    ]


def exact_pair_filename(master: NDArray[np.float64], source: NDArray[np.float64]) -> str:
    """Return a content-addressed ``.npz`` filename for an exact mapping pair."""
    master_c = np.ascontiguousarray(master, dtype=np.float64)
    source_c = np.ascontiguousarray(source, dtype=np.float64)
    hasher = hashlib.blake2b(digest_size=16)
    hasher.update(f"{master_c.dtype}:{master_c.shape}:".encode("ascii"))
    hasher.update(memoryview(master_c))
    hasher.update(f"|{source_c.dtype}:{source_c.shape}:".encode("ascii"))
    hasher.update(memoryview(source_c))
    return f"exact-sync-{hasher.hexdigest()}.npz"


def prune_exact_sidecars(sidecar_dir: Path, keep_files: set[Path]) -> None:
    """Remove unreferenced ``exact-sync-*.npz`` files and delete *sidecar_dir* if empty."""
    if not sidecar_dir.is_dir():
        return
    for candidate in sidecar_dir.glob("exact-sync-*.npz"):
        if candidate not in keep_files:
            with contextlib.suppress(OSError):
                candidate.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        if not any(sidecar_dir.iterdir()):
            sidecar_dir.rmdir()


def _reusable_sidecar_digest(mapping_path: Path) -> str | None:
    """Return SHA-256 hex digest if *mapping_path* exists and is non-empty, else ``None``."""
    try:
        if not mapping_path.is_file() or mapping_path.stat().st_size <= 0:
            return None
        raw = mapping_path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(raw).hexdigest() if raw else None


def save_session_file(
    path: Path,
    payload: dict[str, Any],
    exact_pairs: Sequence[tuple[NDArray[np.float64], NDArray[np.float64]]],
    source_paths: tuple[str, ...],
) -> None:
    """Write session JSON and large exact-sync sidecar arrays atomically."""
    from avialsync.core.artifact_io import publish
    from avialsync.core.artifact_provenance import record

    sidecar_dir = exact_mapping_dir(path)
    referenced_sidecars: set[Path] = set()
    for index, (master, source) in enumerate(exact_pairs):
        if len(master) <= _EXACT_MAPPING_INLINE_LIMIT:
            continue
        master_c = np.ascontiguousarray(master, dtype=np.float64)
        source_c = np.ascontiguousarray(source, dtype=np.float64)
        mapping_path = sidecar_dir / exact_pair_filename(master_c, source_c)
        digest = _reusable_sidecar_digest(mapping_path)
        if digest is None:
            sidecar_dir.mkdir(parents=True, exist_ok=True)
            publish(
                mapping_path,
                partial(np.savez_compressed, master=master_c, source=source_c),
                kind="sync-array",
            )
            digest = hashlib.sha256(mapping_path.read_bytes()).hexdigest()
        referenced_sidecars.add(mapping_path)
        item = payload["sync_provenance"][index]
        item["exact_master"] = []
        item["exact_source"] = []
        item["exact_mapping"] = {
            "file": mapping_path.relative_to(path.parent).as_posix(),
            "sha256": digest,
            "count": int(len(master_c)),
        }
    payload["format"] = "avialsync-session/15"
    payload["provenance"] = record("session", source_paths, session=path)

    def write(temporary: Path) -> None:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    publish(path, write, kind="session", sources=source_paths)
    prune_exact_sidecars(sidecar_dir, referenced_sidecars)


def load_exact_sidecars(
    data: dict[str, Any], base_dir: Path
) -> list[tuple[int, PreparedExactMapping]]:
    """Load and checksum-verify exact-sync sidecars referenced in *data*."""
    sidecars: list[tuple[int, PreparedExactMapping]] = []
    raw_provenance = data.get("sync_provenance", [])
    if not isinstance(raw_provenance, list):
        return sidecars
    for index, raw in enumerate(raw_provenance):
        if not isinstance(raw, dict):
            continue
        mapping = raw.get("exact_mapping")
        if mapping is None:
            continue
        try:
            mapping_path = base_dir / str(mapping["file"])
            file_bytes = mapping_path.read_bytes()
            if hashlib.sha256(file_bytes).hexdigest() != str(mapping["sha256"]):
                raise ValueError("checksum mismatch")
            with np.load(mapping_path) as arrays:
                master = np.asarray(arrays["master"], dtype=np.float64)
                source = np.asarray(arrays["source"], dtype=np.float64)
            if len(master) != len(source) or len(master) != int(mapping["count"]):
                raise ValueError("array length mismatch")
            prepared = PreparedExactMapping.prepare(master, source)
        except (KeyError, OSError, ValueError):
            raise ValueError(f"Invalid exact synchronization sidecar for entry {index}.") from None
        sidecars.append((index, prepared))
    return sidecars


def load_session_file(
    path: Path,
    from_dict: Callable[[dict[str, Any]], _EntryT],
) -> tuple[_EntryT, list[tuple[int, PreparedExactMapping]]]:
    """Read a .avv session file, parse via *from_dict*, and load sidecars."""
    with open(path, encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    state = from_dict(data)
    return state, load_exact_sidecars(data, path.parent)
