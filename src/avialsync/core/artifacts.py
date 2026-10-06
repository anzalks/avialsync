"""Definitions for files AvialSync writes outside its disposable cache (D-197)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from avialsync.core.sidecar_names import beside


class ArtifactClass(StrEnum):
    """Ownership and destination of a written file."""

    SIDECAR = "sidecar"
    SESSION = "session"
    EXPORT = "export"


class ExistingFile(StrEnum):
    """What publication does when the destination already exists."""

    REPLACE = "replace"
    REFUSE = "refuse"


@dataclass(frozen=True, slots=True)
class ArtifactKind:
    """One stable file kind and its publication contract."""

    id: str
    artifact_class: ArtifactClass
    format: str
    schema: str
    provenance: str
    existing: ExistingFile
    read_back: bool
    sidecar_suffix: str | None = None
    source_stem: bool = False

    def target_for(self, source: Path | str) -> Path:
        """Derive a sidecar name from a source, when this kind is a sidecar."""
        if self.sidecar_suffix is None:
            raise ValueError(f"{self.id} needs a user-selected destination")
        if self.source_stem:
            path = Path(source)
            return path.with_name(path.stem + self.sidecar_suffix)
        return beside(source, self.sidecar_suffix)


def _sidecar(
    id: str, suffix: str, format: str, provenance: str, *, source_stem: bool = False
) -> ArtifactKind:
    return ArtifactKind(
        id,
        ArtifactClass.SIDECAR,
        format,
        f"avialsync-{id}/1",
        provenance,
        ExistingFile.REPLACE,
        True,
        suffix,
        source_stem,
    )


def _export(id: str, format: str, provenance: str) -> ArtifactKind:
    return ArtifactKind(
        id,
        ArtifactClass.EXPORT,
        format,
        f"avialsync-{id}/1",
        provenance,
        ExistingFile.REPLACE,
        False,
    )


# Cache entries are intentionally absent: cache_store alone removes them (D-160).
KINDS: dict[str, ArtifactKind] = {
    kind.id: kind
    for kind in (
        _sidecar("pointfix", "_avialfix.csv", "CSV", "comment header"),
        _sidecar("identity-swap", "_avialswap.csv", "CSV", "comment header"),
        _sidecar(
            "custom-markers-2d",
            "_custom_markers.csv",
            "DLC CSV",
            "companion JSON",
            source_stem=True,
        ),
        _sidecar(
            "custom-markers-3d",
            "_custom_markers.csv",
            "DLC CSV",
            "companion JSON",
            source_stem=True,
        ),
        _sidecar("prop", "_prop.toml", "TOML 1.0", "format field"),
        ArtifactKind(
            "calibration",
            ArtifactClass.SIDECAR,
            "anipose TOML",
            "anipose-calibration/1",
            "TOML comment",
            ExistingFile.REPLACE,
            True,
        ),
        ArtifactKind(
            "calibration-ref",
            ArtifactClass.SIDECAR,
            "text",
            "avialsync-calibration-ref/1",
            "comment header",
            ExistingFile.REPLACE,
            True,
        ),
        ArtifactKind(
            "session",
            ArtifactClass.SESSION,
            "JSON",
            "avialsync-session/13",
            "top-level fields",
            ExistingFile.REPLACE,
            True,
        ),
        ArtifactKind(
            "sync-array",
            ArtifactClass.SESSION,
            "NPZ",
            "avialsync-sync-array/1",
            "session manifest",
            ExistingFile.REPLACE,
            True,
        ),
        _export("corrected-pose", "DLC CSV", "scorer and companion JSON"),
        _export("dlc-retraining", "DLC CSV", "companion JSON"),
        _export("dlc-frame", "PNG", "PNG text"),
        _export("annotations", "CSV", "companion JSON"),
        _export("data-slice-csv", "CSV", "comment header"),
        _export("data-slice-parquet", "Parquet", "schema metadata"),
        _export("snapshot", "PNG", "PNG text"),
        _export("clip", "MP4 or MKV", "container metadata"),
        _export("stimulus-grid", "MP4", "container metadata"),
        _export("provenance", "JSON", "top-level fields"),
    )
}


def get_kind(kind: ArtifactKind | str) -> ArtifactKind:
    """Resolve a stable kind ID, rejecting unknown file types."""
    if isinstance(kind, ArtifactKind):
        return kind
    return KINDS[kind]
