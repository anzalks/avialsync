"""Gather alignment evidence, and install and record an accepted proposal.

Video, sensor, and trigger-file targets share one path: the wizard only
offers a target this module can place, and acceptance, undo, and redo all place
it through :func:`install_sync_mapping`.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from avialsync.core.commands import AcceptSyncCommand
from avialsync.core.session import SyncProvenance
from avialsync.core.timeline import PreparedExactMapping, TimeMap
from avialsync.core.triggers import TriggerKind
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.core.sync import SyncProposal
    from avialsync.engine.sync_worker import EvidenceSpec
    from avialsync.engine.trigger_worker import TriggerTrainResult
    from avialsync.ui.main_window import MainWindow

#: Accepted matches and unmatched events drawn in the overview strip. The
#: complete evidence stays on the proposal; session provenance retains a sample. The strip is a
#: few hundred pixels wide and a hundred thousand ticks would only stall it.
_OVERVIEW_EVENT_LIMIT = 800


def collect_sync_evidence(
    window: MainWindow,
) -> tuple[list[EvidenceSpec], list[EvidenceSpec]]:
    """Every reference and target the wizard may offer, on their own clocks.

    A reference is a recorded TTL channel or a declared trigger train, carrying
    its clock's accepted mapping so the fit runs in master time. A target is
    anything acceptance can place: a video by its frame timestamps, a sensor,
    or a trigger file. A video's timestamps are never a reference -- they
    describe its own clock and cannot say when another clock started.
    """
    from avialsync.engine.sync_worker import EventEvidenceSpec, SignalEvidenceSpec

    channels = window.plot_pane.channels
    placeable = _placeable(window)
    panes = window.video_grid.pane_paths()
    references: list[EvidenceSpec] = [
        SignalEvidenceSpec(
            source_id=(
                f"{Path(channel.reader.source_id).name or channel.reader.cache_dir.name} : "
                f"{channel.reader.channel_id}"
            ),
            cache_dir=channel.reader.cache_dir,
            channel_id=channel.reader.channel_id,
            clock_id=channel.reader.source_id or str(channel.reader.cache_dir),
            accepted_mapping=channel.reader.time_map.copy(),
            **_declared_trigger(window, channel.reader.source_id, channel.reader.channel_id, panes),
        )
        for channel in channels
    ]
    targets: list[EvidenceSpec] = [
        EventEvidenceSpec(path, frame_times, clock_id=path, is_video_time_axis=True)
        for path, frame_times in window._video_frame_times.items()
        if path in placeable
    ]
    targets += [
        EventEvidenceSpec(
            path,
            np.asarray(window.imaging_pane.metadata_for(path).frame_times),
            clock_id=path,
            is_imaging_time_axis=True,
        )
        for path in window.imaging_pane.source_paths()
        if path in placeable
    ]
    targets += [
        SignalEvidenceSpec(
            source_id=channel.reader.source_id,
            cache_dir=channel.reader.cache_dir,
            channel_id=channel.reader.channel_id,
            clock_id=channel.reader.source_id,
            display_name=f"{Path(channel.reader.source_id).name} : {channel.reader.channel_id}",
            # Its own midpoint unless the wizard is told otherwise: a target's
            # levels need not be the reference's.
            threshold=None,
        )
        for channel in channels
        if channel.reader.source_id in placeable
    ]
    for file_path, trains in window._trigger_trains.items():
        for train in trains:
            spec = _trigger_spec(window, file_path, train, panes)
            references.append(spec)
            # The same train as a target places the whole file it came from.
            targets.append(
                dataclasses.replace(
                    spec, source_id=file_path, accepted_mapping=None, display_name=spec.source_id
                )
            )
    return references, targets


def _declared_trigger(
    window: MainWindow, source_id: str, channel_id: str, panes: list[str]
) -> dict[str, Any]:
    """The trigger kind and camera a loader declared for this channel, if it did.

    A declaration is where the wizard starts, not what it accepts: the fit is
    still shown with its evidence and placed only when the user accepts it.
    """
    declared = window.session_runtime.channel_triggers.get(source_id, {}).get(channel_id)
    if declared is None:
        return {}
    kind_name, target = declared
    try:
        kind = TriggerKind(kind_name)
    except ValueError:
        return {}
    strobe_for = next((path for path in panes if target and target in (path, Path(path).name)), "")
    return {"kind": kind, "strobe_for": strobe_for}


def has_alignment_evidence(window: MainWindow) -> bool:
    """Whether some reference and some placeable target sit on different clocks.

    The menu's precondition and the wizard's offer read the same rule, so the
    command is never enabled for evidence the wizard would not offer.
    """
    references = {channel.reader.source_id for channel in window.plot_pane.channels}
    references.update(window._trigger_trains)
    targets = _placeable(window)
    return len(targets) > 1 or any(
        reference != target for reference in references for target in targets
    )


def _placeable(window: MainWindow) -> set[str]:
    """Sources acceptance can place: videos with a pane, sensors, trigger files."""
    panes = set(window.video_grid.pane_paths())
    placeable = {
        path
        for path, frame_times in window._video_frame_times.items()
        if len(frame_times) >= 3 and path in panes
    }
    placeable.update(
        channel.reader.source_id
        for channel in window.plot_pane.channels
        if channel.reader.source_id in window._sensor_cache_dirs
    )
    placeable.update(window._trigger_trains)
    placeable.update(
        path
        for path in window.imaging_pane.source_paths()
        if window.imaging_pane.metadata_for(path).frame_count >= 2
    )
    return placeable


def _trigger_spec(
    window: MainWindow, file_path: str, train: TriggerTrainResult, panes: list[str]
) -> EvidenceSpec:
    """One declared train as reference evidence on its file's clock."""
    from avialsync.engine.sync_worker import EventEvidenceSpec

    times = np.asarray(train.times, dtype=np.float64)
    target = train.target
    durations = train.durations
    # A final pulse still high when the file ends has a rise and no fall, so no
    # duration: its exposure midpoint is unknown (core/triggers.extract_pulses).
    unfinished = range(len(durations), len(times)) if durations is not None else range(0)
    return EventEvidenceSpec(
        f"{Path(file_path).name} : {train.train_id}",
        times,
        kind=train.kind,
        clock_id=file_path,
        accepted_mapping=window.trigger_mapping(file_path).copy(),
        strobe_for=next(
            (path for path in panes if target and target in (path, Path(path).name)), ""
        ),
        incomplete_indices=tuple(unfinished),
        measurement_resolution=train.measurement_resolution,
        excluded_incomplete_count=train.excluded_incomplete_count,
    )


def install_sync_mapping(
    window: MainWindow,
    source_id: str,
    offset: float,
    drift_ms_per_hour: float,
    exact_master: np.ndarray | None = None,
    exact_source: np.ndarray | None = None,
    prepared: PreparedExactMapping | None = None,
    *,
    strict: bool = True,
    anchor_offset: float | None = None,
    anchor_drift: float | None = None,
) -> None:
    """Place one video, sensor, or trigger file by an absolute mapping.

    Exact arrays are installed as the frozen buffers the fitting worker made
    (`PreparedExactMapping.adopt`), never rescanned or copied here, which is what
    keeps a million-frame accept, undo, or redo a short UI operation. Undo
    passes ``strict=False``: a source removed since is simply not placed.
    """
    if exact_master is not None and exact_source is not None and prepared is None:
        prepared = PreparedExactMapping.adopt(exact_master, exact_source)
    residual = window.user_offset(source_id, offset)
    if source_id in window.video_grid.pane_paths():
        window.video_grid.set_sync_mapping(
            source_id, offset, drift_ms_per_hour, prepared_mapping=prepared
        )
        window._video_time_mappings[source_id] = (offset, drift_ms_per_hour)
        window.sidebar.set_video_mapping(source_id, residual, drift_ms_per_hour)
        if source_id in window._video_source_bounds:
            window._set_video_coverage(
                source_id,
                window._video_source_bounds[source_id],
                offset,
                drift_ms_per_hour,
                prepared.master if prepared else None,
                prepared.source if prepared else None,
            )
    elif source_id in window.imaging_pane.source_paths():
        mapping = window.imaging_pane.source_config(source_id)[2]
        mapping.set_mapping(offset, drift_ms_per_hour)
        if prepared is not None:
            mapping.install_prepared_exact_mapping(prepared)
        window.imaging_pane.set_mapping(source_id, offset, drift_ms_per_hour)
        window.sidebar.set_imaging_mapping(source_id, residual, drift_ms_per_hour)
        from avialsync.ui.sync_lifecycle import refresh_coverage

        refresh_coverage(window, source_id)
    elif source_id in window._sensor_cache_dirs:
        cache_dir = window._sensor_cache_dirs[source_id]
        window.plot_pane.set_source_mapping(cache_dir, offset, drift_ms_per_hour, replace=True)
        if prepared is not None:
            window.plot_pane.set_source_exact_mapping(cache_dir, prepared.master, prepared.source)
        window.sidebar.set_sensor_mapping(source_id, residual, drift_ms_per_hour)
        window.message_store.set_source_mapping(source_id, offset, drift_ms_per_hour)
        bounds = window.plot_pane.source_bounds(cache_dir)
        if bounds is not None:
            window.transport.set_source_coverage(
                source_id, *bounds, "data", window.coverage_group_for(source_id)
            )
            window._recompute_bounds()
    elif source_id in window._trigger_trains:
        mapping = TimeMap(offset, drift_ms_per_hour)
        if prepared is not None:
            mapping.install_prepared_exact_mapping(prepared)
        window.set_trigger_mapping(source_id, mapping)
    elif strict:
        raise ValueError(f"Synchronization target is not loaded: {source_id}")
    if prepared is not None and (anchor_offset is not None or anchor_drift is not None):
        from avialsync.ui.sync_lifecycle import refresh_coverage, source_mapping

        adjusted = source_mapping(window, source_id)
        if adjusted is not None:
            if anchor_offset is not None:
                adjusted._exact_offset_anchor = anchor_offset
            if anchor_drift is not None:
                adjusted._exact_drift_anchor = anchor_drift
            refresh_coverage(window, source_id)
            if source_id in window._sensor_cache_dirs:
                window.plot_pane.set_source_mapping(
                    window._sensor_cache_dirs[source_id], offset, drift_ms_per_hour
                )
    window._recorded_mappings[source_id] = (residual, drift_ms_per_hour)


def accept_sync_proposal(window: MainWindow, target_path: str, proposal: object) -> None:
    """Install an explicitly accepted proposal, record it, and make it undoable."""
    from avialsync.core.sync import AlignmentMethod, SyncProposal

    if not isinstance(proposal, SyncProposal) or not proposal.applicable:
        raise ValueError("Only an applicable synchronization proposal can be applied.")
    fit = proposal.fit
    prepared: PreparedExactMapping | None = getattr(fit, "prepared_mapping", None)
    exact_master = getattr(fit, "exact_master", None)
    exact_source = getattr(fit, "exact_source", None)
    if prepared is None and exact_master is not None and exact_source is not None:
        prepared = PreparedExactMapping.adopt(exact_master, exact_source)
    if fit.method is AlignmentMethod.EXACT and target_path in window.video_grid.pane_paths():
        frame_times = window._video_frame_times.get(target_path)
        if frame_times is None or prepared is None or len(prepared.source) != len(frame_times):
            raise ValueError(
                "Exact alignment no longer matches the video's stored frame count. "
                "Preview the evidence again before accepting."
            )

    previous = next(
        (item for item in window._sync_provenance if item.target_id == target_path), None
    )
    prior_records = tuple(window._sync_provenance)
    from avialsync.ui.sync_lifecycle import invalidate

    invalidate(window, target_path)
    changed = {entry.target_id: entry for entry in window._sync_provenance}
    dependent_before = tuple(
        entry
        for entry in prior_records
        if entry.target_id != target_path and changed.get(entry.target_id) is not entry
    )
    before = window._recorded_mappings.get(target_path, (0.0, 0.0))
    install_sync_mapping(
        window,
        target_path,
        fit.offset,
        fit.drift_ms_per_hour,
        prepared=prepared,
        anchor_offset=getattr(fit, "exact_offset_anchor", None),
        anchor_drift=getattr(fit, "exact_drift_anchor", None),
    )
    provenance = _provenance(proposal, target_path, prepared)
    window._sync_provenance = [
        item for item in window._sync_provenance if item.target_id != target_path
    ]
    window._sync_provenance.append(provenance)
    # Acceptance stays explicit; recording it only
    # makes the accepted result reversible, so a user who takes the wrong
    # fit is not left reconstructing their previous mapping by hand.
    window._record(
        AcceptSyncCommand(
            source_id=target_path,
            before=before,
            after=window._recorded_mappings[target_path],
            evidence=provenance,
            before_evidence=previous,
            dependent_before=dependent_before,
        )
    )
    window.refresh_alignment_badges()
    window._refresh_action_availability()
    _show_accepted(window, target_path, proposal)


def _provenance(
    proposal: SyncProposal, target_path: str, prepared: PreparedExactMapping | None
) -> SyncProvenance:
    """The reproducible record: raw reference times, clock, and precision state."""
    fit = proposal.fit
    offset_anchor = getattr(fit, "exact_offset_anchor", None)
    drift_anchor = getattr(fit, "exact_drift_anchor", None)
    return SyncProvenance(
        reference_id=proposal.reference_id,
        reference_clock_id=proposal.reference_clock_id,
        target_id=target_path,
        offset=fit.offset,
        drift_ms_per_hour=fit.drift_ms_per_hour,
        rms_residual=fit.rms_residual,
        max_residual=fit.max_residual,
        matched_count=fit.matched_count,
        rejected_count=fit.rejected_count,
        tolerance=proposal.tolerance,
        method=str(fit.method),
        reference_count=fit.reference_count,
        target_count=fit.target_count,
        offset_stderr=fit.offset_stderr,
        ambiguity_margin=fit.ambiguity_margin,
        precision_requirement=fit.precision_requirement,
        precision_verified=fit.precision_verified,
        coverage_fraction=fit.coverage_fraction,
        largest_unsupported_interval=fit.largest_unsupported_interval,
        extrapolated_before=fit.extrapolated_before,
        extrapolated_after=fit.extrapolated_after,
        excluded_incomplete_count=fit.excluded_incomplete_count,
        measurement_resolution=fit.measurement_resolution,
        settings=dict(proposal.settings),
        exact_offset_anchor=(fit.offset if offset_anchor is None else offset_anchor)
        if prepared is not None
        else None,
        exact_drift_anchor=(fit.drift_ms_per_hour if drift_anchor is None else drift_anchor)
        if prepared is not None
        else None,
        restricted_to=list(fit.restricted_to) if fit.restricted_to else [],
        matches=[
            {
                "reference_time": match.reference_time,
                "raw_reference_time": (
                    match.raw_reference_time
                    if match.raw_reference_time is not None
                    else match.reference_time
                ),
                "target_time": match.target_time,
                "residual": match.residual,
            }
            for match in (proposal.matches[i] for i in _spread(len(proposal.matches), 500))
        ],
        # The same frozen buffers the TimeMap holds: shared, never copied.
        exact_master=prepared.master if prepared is not None else [],
        exact_source=prepared.source if prepared is not None else [],
    )


def _show_accepted(window: MainWindow, target_path: str, proposal: SyncProposal) -> None:
    """Report the result and mark a bounded sample of its evidence in the strip."""
    fit = proposal.fit
    display = proposal.display
    if display is not None:
        shown = [
            (float(t), float(r) / 1000.0)
            for t, r in zip(display.reference_times, display.residual_ms, strict=True)
        ]
        unmatched = display.rejected_times.tolist()
    else:
        matches = proposal.matches
        shown = [
            (matches[i].reference_time, matches[i].residual)
            for i in _spread(len(matches), _OVERVIEW_EVENT_LIMIT)
        ]
        rejected = proposal.unmatched_references
        unmatched = [rejected[i] for i in _spread(len(rejected), _OVERVIEW_EVENT_LIMIT)]
    name = Path(target_path).name
    window.transport.set_status(f"Aligned · {fit.describe()}", "info")
    window.transport.set_ttl_events(
        [(time, f"Target: {name} · residual: {residual * 1000:.3f} ms") for time, residual in shown]
    )
    window._overview_gaps.update(
        {time: f"Unmatched reference event ({name})" for time in unmatched}
    )
    window.transport.set_gap_events(sorted(window._overview_gaps.items()))
    if target_path in window.video_grid.pane_paths():
        window.player.seek(window.clock.state.t, exact=True)
    window.statusBar().showMessage(
        tr("Accepted alignment for {name}: {description}").format(
            name=name, description=fit.describe()
        ),
        5000,
    )


def _spread(count: int, limit: int) -> range | np.ndarray:
    """Every index of a small set, or *limit* evenly spaced across a large one."""
    if count <= limit:
        return range(count)
    return np.unique(np.linspace(0, count - 1, limit, dtype=np.intp))
