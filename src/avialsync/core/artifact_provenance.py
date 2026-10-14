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
    source_records: list[dict[str, Any]] = []
    for path in dict.fromkeys(Path(item) for item in sources):
        try:
            size: int | None = path.stat().st_size
            fingerprint: str | None = source_fingerprint(path)
        except OSError:
            size = None
            fingerprint = None
        source_records.append(
            {
                "name": path.name,
                "path": str(path),
                "size_bytes": size,
                "fingerprint_algorithm": "xxh64-first-middle-last-64KiB",
                "fingerprint": fingerprint,
            }
        )
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
