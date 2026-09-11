"""Background TTL/event evidence extraction and alignment fitting."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.pyramid import RAW_CHUNK_SAMPLES, PyramidReader
from avialsync.core.sync import (
    SyncProposal,
    extract_ttl_edges,
    fit_exact_index_mapping,
    fit_sync_events,
)
from avialsync.core.triggers import TriggerKind


@dataclass(frozen=True)
class SignalEvidenceSpec:
    """A cached signal channel from which TTL transitions are extracted."""

    source_id: str
    cache_dir: Path
    channel_id: str
    threshold: float = 0.5
    use_all_times: bool = False


@dataclass(frozen=True)
class EventEvidenceSpec:
    """Native timestamp evidence, such as camera-frame trigger timestamps."""

    source_id: str
    times: np.ndarray


EvidenceSpec: TypeAlias = SignalEvidenceSpec | EventEvidenceSpec


class SyncWorker(QObject):
    """Build an evidence-based proposal without blocking the UI thread."""

    finished = Signal(object)  # SyncProposal
    error = Signal(str)

    def __init__(
        self,
        reference: EvidenceSpec,
        target: EvidenceSpec,
        mode: str = "affine",
        index_offset: int = 0,
        kind: TriggerKind = TriggerKind.SPARSE_EVENTS,
    ) -> None:
        super().__init__()
        self._reference = reference
        self._target = target
        self._mode = mode
        self._index_offset = index_offset
        #: What the reference train is evidence of, which is what lets the
        #: ladder pick a model. Defaults to the weakest kind: an unlabelled
        #: channel is a handful of landmarks until someone says otherwise.
        self._kind = kind

    @Slot()
    def run(self) -> None:
        """Extract raw evidence and emit one deterministic fit proposal."""
        try:
            is_exact = self._mode == "exact_index"
            reference_times = self._event_times(self._reference, use_all_times=is_exact)
            target_times = self._event_times(self._target, use_all_times=is_exact)

            if is_exact:
                proposal = fit_exact_index_mapping(
                    reference_times,
                    target_times,
                    reference_id=self._reference.source_id,
                    target_id=self._target.source_id,
                    index_offset=self._index_offset,
                )
            elif self._mode == "auto":
                proposal = self._fit_automatically(reference_times, target_times)
            else:
                proposal = fit_sync_events(
                    reference_times,
                    target_times,
                    reference_id=self._reference.source_id,
                    target_id=self._target.source_id,
                )
            self.finished.emit(proposal)
        except Exception as error:
            self.error.emit(str(error))

    def _fit_automatically(
        self, reference_times: np.ndarray, target_times: np.ndarray
    ) -> SyncProposal:
        """Let the evidence and the span pick the model, not a dropdown.

        A strategy dropdown asks the user to certify something only the data
        knows -- whether the span can support a rate, whether the pulses are
        regular enough to interpolate between. The affine search runs first
        because every guard lives there and must pass whatever the model turns
        out to be; the ladder then decides what to *report*.
        """
        from avialsync.core.alignment import (
            MIN_PIECEWISE_KNOTS,
            choose_method,
            demote_to_shift,
            fit_piecewise,
        )
        from avialsync.core.sync import AlignmentMethod

        proposal = fit_sync_events(
            reference_times,
            target_times,
            reference_id=self._reference.source_id,
            target_id=self._target.source_id,
        )
        span = float(reference_times[-1] - reference_times[0]) if len(reference_times) else 0.0
        method = choose_method(
            self._kind,
            reconciliation=None,
            matched_count=proposal.fit.matched_count,
            span=span,
            drift_ppm=proposal.fit.drift_ppm,
            noise=proposal.fit.rms_residual,
        )

        if method is AlignmentMethod.PIECEWISE and proposal.fit.matched_count >= (
            MIN_PIECEWISE_KNOTS
        ):
            return fit_piecewise(
                reference_times,
                target_times,
                reference_id=self._reference.source_id,
                target_id=self._target.source_id,
            )
        if method is AlignmentMethod.SHIFT:
            # The rate the affine fit produced is not reportable over this span;
            # dropping it is not a loss of information, it is declining to
            # present noise as a measurement.
            return dataclasses.replace(proposal, fit=demote_to_shift(proposal.fit))
        if method is AlignmentMethod.UNVALIDATED:
            return dataclasses.replace(
                proposal,
                fit=dataclasses.replace(proposal.fit, method=AlignmentMethod.UNVALIDATED),
            )
        return proposal

    @staticmethod
    def _event_times(spec: EvidenceSpec, use_all_times: bool = False) -> np.ndarray:
        if isinstance(spec, EventEvidenceSpec):
            return np.asarray(spec.times, dtype=np.float64)

        reader = PyramidReader(spec.cache_dir, spec.channel_id)
        if use_all_times or getattr(spec, "use_all_times", False):
            times, _, _ = reader.mapped_columns()
            return times

        chunks = reader.iter_raw_chunks(RAW_CHUNK_SAMPLES)
        events = extract_ttl_edges(chunks, source_id=spec.source_id, threshold=spec.threshold)
        return np.asarray([event.time for event in events], dtype=np.float64)
