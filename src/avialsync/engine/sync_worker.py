"""Background TTL/event evidence extraction and alignment fitting."""

from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.errors import SyncEvidenceError
from avialsync.core.pyramid import RAW_CHUNK_SAMPLES, PyramidReader
from avialsync.core.sync import (
    SyncMatch,
    SyncProposal,
    fit_exact_index_mapping,
    fit_sync_events,
    prepare_display_summary,
)
from avialsync.core.timeline import TimeMap
from avialsync.core.triggers import Reconciliation, TriggerKind, extract_pulses


@dataclass(frozen=True)
class SignalEvidenceSpec:
    """A cached signal channel from which TTL transitions are extracted."""

    source_id: str
    cache_dir: Path
    channel_id: str
    threshold: float = 0.5
    use_all_times: bool = False
    #: What this train is evidence *of*, which is what lets the ladder choose a
    #: model. Defaults to the weakest kind: an unlabelled channel is a handful
    #: of landmarks until someone says otherwise.
    kind: TriggerKind = TriggerKind.SPARSE_EVENTS
    clock_id: str = ""
    accepted_mapping: TimeMap | None = None
    strobe_for: str = ""
    display_name: str = ""


@dataclass(frozen=True)
class EventEvidenceSpec:
    """Native timestamp evidence, such as camera-frame trigger timestamps."""

    source_id: str
    times: np.ndarray
    #: As above. Carried on the spec rather than asked for separately, because
    #: it travels with the evidence and every other route loses it -- which is
    #: what left `EXACT` and `PIECEWISE` unreachable while both were tested.
    kind: TriggerKind = TriggerKind.SPARSE_EVENTS
    clock_id: str = ""
    accepted_mapping: TimeMap | None = None
    is_video_time_axis: bool = False
    strobe_for: str = ""
    display_name: str = ""
    #: Pulses in :attr:`times` whose fall was never seen, so whose exposure
    #: midpoint is unknown. Left out of the fit and counted, as for a channel.
    incomplete_indices: tuple[int, ...] = ()


EvidenceSpec: TypeAlias = SignalEvidenceSpec | EventEvidenceSpec


class SyncWorker(QObject):
    """Build an evidence-based proposal without blocking the UI thread."""

    finished = Signal(object)  # SyncProposal
    error = Signal(str)
    cancelled = Signal()
    progress = Signal(int)

    def __init__(
        self,
        reference: EvidenceSpec,
        target: EvidenceSpec,
        mode: str = "affine",
        index_offset: int = 0,
        tolerance: float | None = None,
        precision_requirement: float = 0.001,
        restrict_to: tuple[float, float] | None = None,
    ) -> None:
        super().__init__()
        self._reference = reference
        self._target = target
        self._mode = mode
        self._index_offset = index_offset
        #: How far a pair may be apart and still count. ``None`` derives it
        #: from the pulse rate, which is a heuristic about distinguishability
        #: and says nothing about the precision the user actually needs.
        self._tolerance = tolerance
        self._precision_requirement = precision_requirement
        #: A window of *reference* time to fit within. "The first thirty
        #: seconds are garbage, fit from there on" is a routine and legitimate
        #: scientific control, and it changes what the result claims.
        self._restrict_to = restrict_to
        self._reference_incomplete_count = 0
        self._cancel_requested = threading.Event()

    def cancel(self) -> None:
        """Request cancellation from the UI thread."""
        self._cancel_requested.set()

    def can_cancel(self) -> bool:
        """Whether this preview still accepts cancellation."""
        return not self._cancel_requested.is_set()

    def _check_cancel(self) -> None:
        if self._cancel_requested.is_set():
            raise SyncEvidenceError("Synchronization preview was cancelled.")

    @property
    def _kind(self) -> TriggerKind:
        """What the reference train is evidence of, from the reference itself.

        Read off the spec rather than accepted as a second argument: a caller
        that had to pass it separately could pass a different one, and that is
        exactly the duplication rule 15 exists to prevent. It travels with the
        evidence, and every route that lost it lost two rungs of the ladder.
        """
        return self._reference.kind

    @Slot()
    def run(self) -> None:
        """Extract raw evidence and emit one deterministic fit proposal."""
        try:
            self.progress.emit(5)
            self._require_shared_evidence()
            is_exact = self._mode == "exact_index"
            reference_raw = self._event_times(self._reference, use_all_times=is_exact)
            self._check_cancel()
            target_times = self._event_times(self._target, use_all_times=is_exact)
            self.progress.emit(35)
            mapping = self._reference.accepted_mapping
            reference_times = (
                mapping.to_master_array(reference_raw) if mapping is not None else reference_raw
            )
            reference_times = self._restricted(reference_times)

            if is_exact:
                self._require_exact_evidence(reference_times, target_times)
                proposal = fit_exact_index_mapping(
                    reference_times,
                    target_times,
                    reference_id=self._reference.source_id,
                    target_id=self._target.source_id,
                    index_offset=self._index_offset,
                    verified_shared_strobe=True,
                    precision_requirement=self._precision_requirement,
                )
            elif self._mode == "auto":
                proposal = self._fit_automatically(reference_times, target_times)
            else:
                proposal = fit_sync_events(
                    reference_times,
                    target_times,
                    reference_id=self._reference.source_id,
                    target_id=self._target.source_id,
                    max_residual=self._tolerance,
                    precision_requirement=self._precision_requirement,
                    is_cancelled=self._cancel_requested.is_set,
                    target_span=self._target_span(),
                )
            proposal = self._record_restriction(proposal)
            proposal = self._record_reference_clock(proposal, mapping)
            self._check_cancel()
            self.progress.emit(85)
            self.finished.emit(
                dataclasses.replace(proposal, display=prepare_display_summary(proposal))
            )
            self.progress.emit(100)
        except Exception as error:
            if self._cancel_requested.is_set():
                self.cancelled.emit()
            else:
                self.error.emit(str(error))

    def _fit_automatically(
        self, reference_times: np.ndarray, target_times: np.ndarray
    ) -> SyncProposal:
        """Let the evidence and the span pick the model, not a dropdown.

        A strategy dropdown asks the user to certify something only the data
        knows -- whether the span can support a rate, whether the pulses are
        regular enough to interpolate between. A declared strobe whose exact
        checks all pass is answered first; otherwise the affine search runs,
        because every guard lives there and must pass whatever the model turns
        out to be, and the ladder then decides what to *report*.
        """
        from avialsync.core.alignment import (
            MIN_PIECEWISE_KNOTS,
            choose_method,
            demote_to_shift,
            fit_piecewise,
        )
        from avialsync.core.sync import AlignmentMethod

        if self._exact_evidence_holds(reference_times, target_times):
            # A declared, complete strobe whose pulses and intervals agree with
            # the stored frames is the strongest evidence there is. It goes
            # first because a regular frame train is exactly what makes the
            # affine search ambiguous, and that must not hide it.
            return self._exact(reference_times, target_times)
        target_span = self._target_span()
        proposal = fit_sync_events(
            reference_times,
            target_times,
            reference_id=self._reference.source_id,
            target_id=self._target.source_id,
            max_residual=self._tolerance,
            precision_requirement=self._precision_requirement,
            is_cancelled=self._cancel_requested.is_set,
            target_span=target_span,
        )
        span = float(reference_times[-1] - reference_times[0]) if len(reference_times) else 0.0
        method = choose_method(
            self._kind,
            reconciliation=self._reconciliation(reference_times, target_times),
            matched_count=proposal.fit.matched_count,
            span=span,
            drift_ms_per_hour=proposal.fit.drift_ms_per_hour,
            noise=proposal.fit.rms_residual,
        )

        if method is AlignmentMethod.EXACT:
            self._require_exact_evidence(reference_times, target_times)
            return self._exact(reference_times, target_times)
        if method is AlignmentMethod.PIECEWISE and proposal.fit.matched_count >= (
            MIN_PIECEWISE_KNOTS
        ):
            return fit_piecewise(
                reference_times,
                target_times,
                reference_id=self._reference.source_id,
                target_id=self._target.source_id,
                tolerance=self._tolerance,
                precision_requirement=self._precision_requirement,
                is_cancelled=self._cancel_requested.is_set,
                target_span=target_span,
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

    def _exact(self, reference_times: np.ndarray, target_times: np.ndarray) -> SyncProposal:
        """Pair every stored frame with the exposure the strobe measured for it.

        Nothing is fitted: the pairing is the answer, and its confidence is the
        checked count and interval agreement rather than any scatter.
        """
        return fit_exact_index_mapping(
            reference_times,
            target_times,
            reference_id=self._reference.source_id,
            target_id=self._target.source_id,
            verified_shared_strobe=True,
            precision_requirement=self._precision_requirement,
        )

    def _exact_evidence_holds(self, reference: np.ndarray, target: np.ndarray) -> bool:
        if self._kind is not TriggerKind.FRAME_STROBE:
            return False
        try:
            self._require_exact_evidence(reference, target)
        except SyncEvidenceError:
            return False
        return True

    def _require_shared_evidence(self) -> None:
        """Refuse pairings that cannot say anything about two clocks.

        A video's frame timestamps count from its own first frame. Two cameras
        at the same frame rate have identical timestamps whenever they started,
        so a fit between them -- or from one to anything else -- finds a
        perfect match that measures nothing. They remain each video's time
        axis, the target side of a fit, and nothing more.
        """
        reference, target = self._reference, self._target
        if reference.clock_id and reference.clock_id == target.clock_id:
            raise SyncEvidenceError("Reference and target use the same source clock.")
        if isinstance(reference, EventEvidenceSpec) and reference.is_video_time_axis:
            raise SyncEvidenceError(
                "A video's own frame timestamps cannot place another source: they "
                "describe only that video's clock. Use a recorded TTL, exposure "
                "strobe, or another shared event as the reference."
            )

    def _target_span(self) -> tuple[float, float] | None:
        """The whole target recording in its own clock, when it outruns its events.

        A sensor's mapping is applied to every sample it holds, not only to the
        pulses that were matched, so the stretch past the last pulse is
        extrapolated and is reported as such. A video's events are its frames,
        and a trigger train's are the train, so those need nothing more.
        """
        target = self._target
        if not isinstance(target, SignalEvidenceSpec):
            return None
        times, _, _ = PyramidReader(target.cache_dir, target.channel_id).mapped_columns()
        if not len(times):
            return None
        return float(times[0]), float(times[-1])

    def _require_exact_evidence(self, reference: np.ndarray, target: np.ndarray) -> None:
        """Require a declared camera strobe and an intact frame index."""
        if (
            self._reference.kind is not TriggerKind.FRAME_STROBE
            or not isinstance(self._target, EventEvidenceSpec)
            or not self._target.is_video_time_axis
            or self._reference.strobe_for != self._target.clock_id
        ):
            raise SyncEvidenceError(
                "Exact alignment needs a recorded camera-to-DAQ strobe declared "
                "for this video. A video's own timestamps only describe its local clock."
            )
        if self._reference_incomplete_count:
            raise SyncEvidenceError(
                f"{self._reference_incomplete_count} strobe pulse(s) crossed missing "
                "data and were excluded, so frame indices after them cannot be "
                "paired exactly."
            )
        if self._index_offset:
            raise SyncEvidenceError(
                "An index offset leaves frame identity unproved: exact pairing starts "
                "at the first stored frame. Fit to shared events instead."
            )
        if len(reference) != len(target):
            raise SyncEvidenceError(
                "Strobe and stored-frame counts differ. Frame indices after a dropped "
                "or extra pulse cannot be paired exactly."
            )
        if len(reference) > 2:
            ref_intervals = np.diff(reference)
            target_intervals = np.diff(target)
            scale = np.median(ref_intervals) / np.median(target_intervals)
            # Detect a missing exposure paired against an unrelated adjacent
            # frame even when a spurious pulse keeps the total count equal.
            if np.max(np.abs(ref_intervals - target_intervals * scale)) > max(
                0.1 * float(np.median(ref_intervals)), 0.001
            ):
                raise SyncEvidenceError(
                    "Strobe and frame interval patterns disagree; dropped or extra "
                    "events make an exact index pairing unsafe."
                )

    def _record_reference_clock(
        self, proposal: SyncProposal, mapping: TimeMap | None
    ) -> SyncProposal:
        """Keep raw reference event times beside the master-clock fit."""
        fit = dataclasses.replace(
            proposal.fit, excluded_incomplete_count=self._reference_incomplete_count
        )
        if mapping is None:
            return dataclasses.replace(
                proposal,
                fit=fit,
                reference_clock_id=self._reference.clock_id or self._reference.source_id,
            )
        # One vectorised inverse rather than a dataclass copy per match: a
        # ten-thousand-event preview is benchmarked against 250 ms.
        master = np.fromiter(
            (match.reference_time for match in proposal.matches),
            dtype=np.float64,
            count=len(proposal.matches),
        )
        matches = tuple(
            SyncMatch(match.reference_time, match.target_time, match.residual, raw)
            for match, raw in zip(
                proposal.matches, mapping.to_source_array(master).tolist(), strict=True
            )
        )
        return dataclasses.replace(
            proposal,
            fit=fit,
            matches=matches,
            reference_clock_id=self._reference.clock_id or self._reference.source_id,
        )

    def _restricted(self, times: np.ndarray) -> np.ndarray:
        """Keep only the reference events inside the requested window.

        The *target* is deliberately not trimmed. Restricting the reference
        says which evidence to fit from; trimming the target as well would
        also throw away the partners those events need, and turn a narrower
        question into a worse answer.
        """
        if self._restrict_to is None or not len(times):
            return times
        start, end = self._restrict_to
        kept = times[(times >= start) & (times <= end)]
        if len(kept) < 2:
            raise SyncEvidenceError(
                f"Only {len(kept)} reference event(s) fall between {start:.3f} s and "
                f"{end:.3f} s. Widen the window, or clear it to fit over everything."
            )
        return kept

    def _record_restriction(self, proposal: SyncProposal) -> SyncProposal:
        """Carry the window into the result, because it changes what it claims."""
        if self._restrict_to is None:
            return proposal
        return dataclasses.replace(
            proposal,
            fit=dataclasses.replace(proposal.fit, restricted_to=self._restrict_to),
        )

    def _reconciliation(
        self, reference_times: np.ndarray, target_times: np.ndarray
    ) -> Reconciliation | None:
        """Whether the pulse count and the frame count agree, when both exist.

        Only meaningful where the reference is evidence about frames at all: a
        sparse landmark train has no opinion about how many frames there are,
        and comparing its count to a container's would invent a disagreement.

        This being unreachable -- the caller passed ``None`` unconditionally --
        is what kept `AlignmentMethod.EXACT` out of every automatic fit while
        the code selecting it was fully tested.
        """
        if not self._kind.identifies_frames or not isinstance(self._target, EventEvidenceSpec):
            return None
        if self._kind is TriggerKind.FRAME_STROBE and not self._exact_evidence_holds(
            reference_times, target_times
        ):
            return None
        return Reconciliation(
            pulses=int(len(reference_times)),
            frames=int(len(target_times)),
            kind=self._kind,
        )

    def _event_times(self, spec: EvidenceSpec, use_all_times: bool = False) -> np.ndarray:
        if isinstance(spec, EventEvidenceSpec):
            times = np.asarray(spec.times, dtype=np.float64)
            if spec is self._reference:
                self._reference_incomplete_count = len(spec.incomplete_indices)
            if spec.incomplete_indices:
                return np.delete(times, spec.incomplete_indices)
            return times

        reader = PyramidReader(spec.cache_dir, spec.channel_id)
        if use_all_times or getattr(spec, "use_all_times", False):
            times, values, gaps = reader.mapped_columns()
            valid = np.isfinite(values)
            if spec is self._reference:
                self._reference_incomplete_count = int(
                    np.count_nonzero(~valid) + np.count_nonzero(gaps)
                )
            return times[valid]

        chunks = reader.iter_raw_chunks_with_gaps(RAW_CHUNK_SAMPLES)
        # Both edges, not one. `extract_ttl_edges` returns rising edges alone,
        # which throws away exposure duration and timestamps a frame at the
        # instant the shutter opened rather than at the middle of the interval
        # it integrated over -- the wrong instant for a subject moving through
        # it, and the one high-speed behaviour work cares about.
        #
        # Only a declared FRAME_STROBE is midpointed; every other kind keeps its
        # rising edge, because a request or a sync wave is an instant and has no
        # middle. `_train_from_edges` is what makes that distinction.
        train = extract_pulses(
            chunks,
            source_id=spec.source_id,
            kind=spec.kind,
            threshold=spec.threshold,
        )
        if spec is self._reference:
            self._reference_incomplete_count = train.incomplete_count
        if train.incomplete_indices:
            return np.delete(train.times, train.incomplete_indices)
        return np.asarray(train.times, dtype=np.float64)
