"""Headless dataclasses for import statistics and source integrity (D-020).

No PySide6 imports — enforced by test_headless_core.py.
"""

from __future__ import annotations

import dataclasses
from typing import Any


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

    @property
    def any_flag(self) -> bool:
        return any(
            [
                self.is_vfr,
                self.fps_mismatch,
                self.has_gaps,
                self.drift_nonzero,
                self.fps_provisional,
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
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IntegrityFlags:
        return cls(
            is_vfr=d.get("is_vfr", False),
            fps_mismatch=d.get("fps_mismatch", False),
            has_gaps=d.get("has_gaps", False),
            drift_nonzero=d.get("drift_nonzero", False),
            fps_provisional=d.get("fps_provisional", False),
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "loader_id": self.loader_id,
            "import_config": dict(self.import_config),
            "import_report": self.import_report.as_dict() if self.import_report else None,
            "integrity_flags": self.integrity_flags.as_dict(),
            "fps_binding": self.fps_binding,
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
        )
