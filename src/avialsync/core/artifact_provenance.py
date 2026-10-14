"""Portable provenance records for authored files and requested exports."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from avialsync import __version__
from avialsync.core.artifact_io import publish
from avialsync.core.artifacts import ArtifactKind, get_kind
from avialsync.core.cache import source_fingerprint
from avialsync.core.session import SyncProvenance
from avialsync.core.source import container_of


def _source_record(path: Path) -> dict[str, Any]:
    """Identify an object inside its actual file/store without inventing file metadata."""
    storage = container_of(path) or path
    directory = storage.is_dir()
    try:
        stat = storage.stat()
        size: int | None = None if directory else stat.st_size
        fingerprint: str | None = source_fingerprint(storage)
    except OSError:
        size, fingerprint = None, None
    result: dict[str, Any] = {
        "name": path.name,
        "path": str(path),
        "size_bytes": size,
        "fingerprint_algorithm": (
            "xxh64-tree-metadata-and-first-middle-last-64KiB"
            if directory
            else "xxh64-first-middle-last-64KiB"
        ),
        "fingerprint": fingerprint,
    }
    if storage != path:
        result["container_path"] = str(storage)
    return result


def record(
    kind: ArtifactKind | str,
    sources: list[Path | str] | tuple[Path | str, ...] = (),
    *,
    session: Path | str | None = None,
    time_maps: Mapping[str, Mapping[str, object]] | None = None,
    edit_counts: dict[str, int] | None = None,
    alignment_evidence: Sequence[SyncProvenance] = (),
) -> dict[str, Any]:
    """Capture one versioned write record from plain data on the worker thread."""
    definition = get_kind(kind)
    source_records = [
        _source_record(path) for path in dict.fromkeys(Path(item) for item in sources)
    ]
    return {
        "provenance_version": 2,
        "software": f"avialsync {__version__}",
        "format": definition.schema,
        "written": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "sources": source_records,
        "session": str(session) if session else None,
        "time_maps": {key: dict(value) for key, value in (time_maps or {}).items()},
        "edit_counts": edit_counts or {},
        "alignment_evidence": [
            {
                field.name: getattr(entry, field.name)
                for field in dataclasses.fields(entry)
                if field.name not in {"exact_master", "exact_source"}
            }
            for entry in alignment_evidence
        ],
    }


def companion_path(target: Path | str) -> Path:
    """Return the JSON companion name for a strict external layout."""
    path = Path(target)
    return path.with_name(f"{path.stem}_avialsync.json")


def write_companion(
    target: Path | str,
    payload: dict[str, Any],
    *,
    sources: tuple[Path | str, ...] = (),
) -> Path:
    """Publish provenance where the main file has no extensible fields."""
    companion = companion_path(target)
    return publish(
        companion,
        lambda temporary: temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        ),
        kind="provenance",
        sources=sources,
    )
