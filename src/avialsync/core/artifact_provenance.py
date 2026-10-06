"""Portable provenance records for authored files and requested exports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from avialsync.core.artifact_io import publish
from avialsync.core.artifacts import ArtifactKind, get_kind


def record(
    kind: ArtifactKind | str,
    sources: list[Path | str] | tuple[Path | str, ...] = (),
    *,
    session: Path | str | None = None,
    time_maps: dict[str, dict[str, float]] | None = None,
    edit_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Capture one versioned write record from plain data on the worker thread."""
    definition = get_kind(kind)
    try:
        app_version = version("avialsync")
    except PackageNotFoundError:
        app_version = "unknown"
    source_records: list[dict[str, str | int | None]] = []
    for item in sources:
        path = Path(item)
        try:
            size: int | None = path.stat().st_size
        except OSError:
            size = None
        source_records.append({"name": path.name, "size_bytes": size})
    return {
        "software": f"avialsync {app_version}",
        "format": definition.schema,
        "written": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "sources": source_records,
        "session": str(session) if session else None,
        "time_maps": time_maps or {},
        "edit_counts": edit_counts or {},
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
