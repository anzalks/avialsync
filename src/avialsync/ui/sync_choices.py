"""Recording identities and contextual choices for alignment setup."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt

from avialsync.engine.sync_worker import EvidenceSpec, SignalEvidenceSpec
from avialsync.ui.i18n import tr
from avialsync.ui.sync_lifecycle import as_window

if TYPE_CHECKING:
    from avialsync.ui.sync_wizard import SyncWizard


def recording_name(wizard: SyncWizard, spec: EvidenceSpec) -> str:
    """Use session labels without changing the source's persistent identity."""
    parent = as_window(wizard.parentWidget())
    clock = spec.clock_id or spec.source_id
    label = parent.session_runtime.item_labels.get(clock, "") if parent else ""
    if label:
        channel = spec.channel_id if isinstance(spec, SignalEvidenceSpec) else ""
        if not channel and " : " in spec.source_id:
            channel = spec.source_id.split(" : ", 1)[1]
        return f"{label} : {channel}" if channel else label
    return spec.display_name or Path(spec.source_id).name


def refresh_labels(wizard: SyncWizard) -> None:
    """Disambiguate equal filenames with the shortest useful parent context."""
    for combo, specs in (
        (wizard._reference_combo, wizard._references),
        (wizard._target_combo, wizard._targets),
    ):
        names = [recording_name(wizard, spec) for spec in specs]
        groups: dict[str, list[int]] = defaultdict(list)
        for index, name in enumerate(names):
            groups[name].append(index)
        for name, indices in groups.items():
            if len(indices) < 2:
                continue
            peers = [Path(specs[i].clock_id or specs[i].source_id) for i in indices]
            # At most the last three folders: a full path (a lab share, or a
            # temp folder) is not a name, and the tooltip carries it anyway.
            distinct: list[str] | None = None
            for depth in range(1, 4):
                contexts = [str(Path(*peer.parent.parts[-depth:])) for peer in peers]
                if len(set(contexts)) == len(peers):
                    distinct = contexts
                    break
            for number, index in enumerate(indices, start=1):
                names[index] = (
                    tr("{name} — {folder}").format(name=name, folder=distinct[number - 1])
                    if distinct is not None
                    else tr("{name} ({number})").format(name=name, number=number)
                )
        for index, (name, spec) in enumerate(zip(names, specs, strict=True)):
            path = Path(spec.clock_id or spec.source_id)
            combo.setItemText(index, name)
            combo.setItemData(index, f"{path}\n{spec.source_id}", Qt.ItemDataRole.ToolTipRole)


_SYNC_WORDS = frozenset(
    (
        "ttl",
        "sync",
        "strobe",
        "trigger",
        "trig",
        "frame",
        "frames",
        "camera",
        "cam",
        "pulse",
        "pulses",
        "din",
        "digital",
        "event",
        "events",
        "exposure",
    )
)


def _sync_rank(spec: EvidenceSpec) -> int:
    """Lower is likelier a sync line: declared triggers, then sync-named channels."""
    if not isinstance(spec, SignalEvidenceSpec):
        return 0 if not spec.is_frame_time_axis else 2
    from avialsync.ui.import_time_check import header_tokens

    words = set(header_tokens(spec.channel_id or spec.source_id))
    return 1 if words & _SYNC_WORDS else 3


def preferred_reference(wizard: SyncWizard) -> int:
    """The reference most likely to carry sync pulses, on another clock than the target.

    The first listed channel was the default, which on a typical rig is an
    analogue trace (a sine `ch0`) rather than the TTL line two rows below.
    """
    if not wizard._references:
        return -1
    target = wizard._targets[wizard._target_combo.currentIndex()] if wizard._targets else None
    target_clock = (target.clock_id or target.source_id) if target else ""
    ranked = sorted(
        range(len(wizard._references)),
        key=lambda i: (
            (wizard._references[i].clock_id or wizard._references[i].source_id) == target_clock,
            _sync_rank(wizard._references[i]),
            i,
        ),
    )
    return ranked[0]


def suggested_mode(wizard: SyncWizard) -> str:
    """Suggest an input route from availability, without declaring shared wiring."""
    references = {spec.clock_id or spec.source_id for spec in wizard._event_references}
    targets = {spec.clock_id or spec.source_id for spec in wizard._targets}
    if references and targets and len(references | targets) > 1:
        return "events"
    clocks = {spec.clock_id or spec.source_id for spec in wizard._visual_references}
    return "landmarks" if len(clocks) > 1 else "manual"


def change_mode(wizard: SyncWizard) -> None:
    """Keep recording choices where possible; paired observations never transfer."""
    selected = wizard._reference_combo.currentIndex()
    previous = wizard._references[selected].source_id if selected >= 0 else ""
    wizard._references = list(
        wizard._event_references
        if wizard._mode_combo.currentData() == "events"
        else wizard._visual_references
    )
    blocked = wizard._reference_combo.blockSignals(True)
    wizard._reference_combo.clear()
    for spec in wizard._references:
        wizard._reference_combo.addItem(spec.source_id)
    index = next((i for i, spec in enumerate(wizard._references) if spec.source_id == previous), 0)
    wizard._reference_combo.setCurrentIndex(index if wizard._references else -1)
    wizard._reference_combo.blockSignals(blocked)
    if wizard._references and wizard._targets and wizard._mode_combo.currentData() != "manual":
        clock = wizard._references[index].clock_id or wizard._references[index].source_id
        target = wizard._targets[wizard._target_combo.currentIndex()]
        if (target.clock_id or target.source_id) == clock:
            other = next(
                (
                    i
                    for i, spec in enumerate(wizard._targets)
                    if (spec.clock_id or spec.source_id) != clock
                ),
                0,
            )
            wizard._target_combo.setCurrentIndex(other)
    refresh_labels(wizard)
    wizard._configure_reference()
    wizard._landmarks.clear()


def setup_guidance(wizard: SyncWizard) -> tuple[str, bool]:
    """Explain the next useful gesture before enabling a preview."""
    if not wizard._targets:
        return tr("Load a recording to adjust its timing."), False
    if wizard._mode_combo.currentData() == "manual":
        return tr("Enter an offset, then preview the change before applying it."), True
    if not wizard._references:
        return tr("Load recorded sync signals, or choose Match visible events."), False
    reference = wizard._references[wizard._reference_combo.currentIndex()]
    target = wizard._targets[wizard._target_combo.currentIndex()]
    if (reference.clock_id or reference.source_id) == (target.clock_id or target.source_id):
        return tr("Choose recordings on different clocks."), False
    if wizard._mode_combo.currentData() == "landmarks":
        if not wizard._landmarks.pairs():
            return tr("Add at least one corresponding event pair, then preview."), False
        return tr("Preview the paired events. Separated events help check clock drift."), True
    return tr("Preview to see how well the selected sync signals match."), True
