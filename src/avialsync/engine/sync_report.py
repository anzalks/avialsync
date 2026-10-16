"""Publish an inspectable alignment report through the registered job system."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.artifact_io import publish
from avialsync.core.session import SyncProvenance
from avialsync.core.sync import SyncProposal
from avialsync.core.timeline import TimeMap


def proposal_record(proposal: SyncProposal) -> dict[str, Any]:
    """Serialize complete proposed evidence on a worker, before acceptance."""
    fit = proposal.fit
    return {
        "reference_id": proposal.reference_id,
        "reference_clock_id": proposal.reference_clock_id,
        "target_id": proposal.target_id,
        "method": str(fit.method),
        "description": fit.describe(),
        "precision_requirement_seconds": fit.precision_requirement,
        "precision_verified": fit.precision_verified,
        "measurement_resolution_seconds": fit.measurement_resolution,
        "matched_count": fit.matched_count,
        "rejected_count": fit.rejected_count,
        "coverage_fraction": fit.coverage_fraction,
        "largest_unsupported_interval_seconds": fit.largest_unsupported_interval,
        "extrapolated_before_seconds": fit.extrapolated_before,
        "extrapolated_after_seconds": fit.extrapolated_after,
        "match_tolerance_seconds": proposal.tolerance,
        "settings": proposal.settings,
        "mapping": fit.to_time_map().to_record(),
        "matches": [dataclasses.asdict(match) for match in proposal.matches],
        "unmatched_reference_times": list(proposal.unmatched_references),
    }


class SyncReportWorker(QObject):
    """Write a proposal or the accepted session records without blocking widgets."""

    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        path: Path,
        proposal: SyncProposal | None = None,
        records: tuple[SyncProvenance, ...] = (),
        mappings: dict[str, TimeMap] | None = None,
    ) -> None:
        super().__init__()
        self._path = path
        self._proposal = proposal
        self._records = records
        self._mappings = mappings or {}

    @Slot()
    def run(self) -> None:
        """Publish atomically, preserving the previous report if writing fails."""
        try:
            records = (
                [proposal_record(self._proposal)]
                if self._proposal
                else [self._accepted_record(record) for record in self._records]
            )
            report = {
                "schema": "avialsync-alignment-report/1",
                "accepted": self._proposal is None,
                "precision_scope": (
                    "Checks apply to recorded timestamps. Unmeasured hardware latency "
                    "and exposure timing are not certified."
                ),
                "alignments": records,
            }
            sources = list(self._mappings)
            for record in records:
                sources += [record["target_id"], record.get("reference_clock_id", "")]
            publish(
                self._path,
                lambda output: output.write_text(
                    json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
                ),
                kind="provenance",
                sources=sources,
            )
        except Exception as error:
            self.error.emit(str(error))
        else:
            self.finished.emit(str(self._path))

    def _accepted_record(self, record: SyncProvenance) -> dict[str, Any]:
        # Do not use asdict on the whole record: it deep-copies million-frame arrays.
        result = {
            field.name: getattr(record, field.name)
            for field in dataclasses.fields(record)
            if field.name not in {"exact_master", "exact_source"}
        }
        mapping = self._mappings.get(record.target_id)
        result["mapping"] = mapping.to_record() if mapping else None
        result["saved_match_count"] = len(record.matches)
        result["matches_complete"] = len(record.matches) == record.matched_count
        return result
