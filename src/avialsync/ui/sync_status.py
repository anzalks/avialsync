"""Short, evidence-derived alignment states on every source card."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QWidget

from avialsync.core.sync import AlignmentMethod
from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.core.session import SyncProvenance
    from avialsync.ui.main_window import MainWindow


def short_status(entry: SyncProvenance | None, adjusted: bool = False) -> str:
    """Separate placement, explicit manual choices, precision and stale evidence."""
    if entry is None:
        return (
            tr("Manual timing · unverified") if adjusted else tr("Recorded timestamps · unverified")
        )
    if entry.superseded_by:
        return tr("Alignment needs review")
    if entry.method == AlignmentMethod.MANUAL:
        return tr("Manual timing · unverified")
    if entry.method == AlignmentMethod.UNVALIDATED:
        return tr("Sparse landmarks · unverified")
    prefix = (
        tr("Exposure mapping") if entry.method == AlignmentMethod.EXACT else tr("Shared events")
    )
    if entry.method == AlignmentMethod.LANDMARKS:
        prefix = tr("Visual landmarks")
    state = tr("precision verified") if entry.precision_verified else tr("precision unverified")
    return tr("{method} · {state}").format(method=prefix, state=state)


def refresh_cards(window: MainWindow) -> None:
    """Update only on document changes; labels never participate in clock ticks."""
    records = {entry.target_id: entry for entry in window._sync_provenance}
    cards: dict[str, QWidget | None] = dict(window.sidebar._video_widgets)
    cards.update({path: window.sidebar.sensor_widget(path) for path in window._sensor_cache_dirs})
    cards.update(
        {path: window.sidebar.imaging_widget(path) for path in window.imaging_pane.source_paths()}
    )
    for path, card in cards.items():
        if card is None:
            continue
        label = card.findChild(ElidedLabel, "alignment_status")
        if label is None:
            label = ElidedLabel("", card)
            label.setObjectName("alignment_status")
            label.setAccessibleName(tr("Source alignment status"))
            layout = card.layout()
            if isinstance(layout, QVBoxLayout):
                layout.insertWidget(1, label)
        adjusted = window._recorded_mappings.get(path, (0.0, 0.0)) != (0.0, 0.0)
        label.setText(short_status(records.get(path), adjusted))
        label.setToolTip(window.alignment_confidence(path))
        label.setAccessibleDescription(window.alignment_confidence(path))


def describe_provenance(entry: SyncProvenance) -> str:
    """Render a persisted record with the same claims as its live fitted model."""
    from avialsync.core.sync import AlignmentMethod, SyncFit

    return SyncFit(
        offset=entry.offset,
        drift_ms_per_hour=entry.drift_ms_per_hour,
        rms_residual=entry.rms_residual,
        max_residual=entry.max_residual,
        matched_count=entry.matched_count,
        rejected_count=entry.rejected_count,
        reference_count=entry.reference_count,
        target_count=entry.target_count,
        offset_stderr=entry.offset_stderr,
        ambiguity_margin=entry.ambiguity_margin,
        method=AlignmentMethod(entry.method),
        restricted_to=(
            (entry.restricted_to[0], entry.restricted_to[1])
            if len(entry.restricted_to) == 2
            else None
        ),
        precision_requirement=entry.precision_requirement,
        precision_verified=entry.precision_verified,
        coverage_fraction=entry.coverage_fraction,
        largest_unsupported_interval=entry.largest_unsupported_interval,
        extrapolated_before=entry.extrapolated_before,
        extrapolated_after=entry.extrapolated_after,
        excluded_incomplete_count=entry.excluded_incomplete_count,
        measurement_resolution=entry.measurement_resolution,
        overlap_reference_count=entry.overlap_reference_count,
    ).describe()
