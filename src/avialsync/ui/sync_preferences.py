"""Schema-owned layout memory and session-scoped alignment selection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from avialsync.core.settings_schema import setting_for
from avialsync.ui.preferences_dialog import read_setting, write_setting
from avialsync.ui.sync_choices import preferred_reference, suggested_mode
from avialsync.ui.sync_lifecycle import as_window

if TYPE_CHECKING:
    from avialsync.engine.sync_worker import EvidenceSpec
    from avialsync.ui.sync_wizard import SyncWizard


def _selection_key(spec: EvidenceSpec) -> str:
    """Encode channel/train identity alongside ``source_id`` in a single string."""
    channel_id = str(getattr(spec, "channel_id", "") or "")
    if channel_id:
        return f"{spec.source_id}\x00{channel_id}"
    if spec.display_name:
        return f"{spec.source_id}\x00{spec.display_name}"
    return spec.source_id


def _find_saved_spec(specs: list[EvidenceSpec], saved_entry: Any, saved_channel: str = "") -> int:
    """Match a saved selection, falling back to ``source_id`` for older entries."""
    if isinstance(saved_entry, tuple):
        src = str(saved_entry[0]) if saved_entry else ""
        ch = str(saved_entry[1]) if len(saved_entry) > 1 else ""
        if ch:
            exact_tuple = next(
                (
                    i
                    for i, spec in enumerate(specs)
                    if spec.source_id == src and getattr(spec, "channel_id", "") == ch
                ),
                -1,
            )
            if exact_tuple >= 0:
                return exact_tuple
        return next((i for i, spec in enumerate(specs) if spec.source_id == src), -1)

    entry = str(saved_entry)
    if saved_channel:
        by_channel = next(
            (
                i
                for i, spec in enumerate(specs)
                if spec.source_id == entry and getattr(spec, "channel_id", "") == saved_channel
            ),
            -1,
        )
        if by_channel >= 0:
            return by_channel
    exact = next((i for i, spec in enumerate(specs) if _selection_key(spec) == entry), -1)
    if exact >= 0:
        return exact
    return next((i for i, spec in enumerate(specs) if spec.source_id == entry), -1)


def preference(key: str) -> Any:
    """Read defaults from the registry, rather than defining a second table."""
    setting = setting_for(f"alignment/{key}")
    assert setting is not None
    return read_setting(setting)


def restore(wizard: SyncWizard) -> None:
    """Restore presentation and loaded selections, with fresh evidence every time."""
    parent = as_window(wizard.parentWidget())
    wizard._session_generation = parent.session_runtime.generation if parent else None
    saved = parent.session_runtime.alignment_selection if parent else None
    if saved is not None and saved[0] != wizard._session_generation:
        saved = None
    mode = saved[1] if saved else suggested_mode(wizard)
    if mode == "events" and not wizard._event_references:
        mode = suggested_mode(wizard)
    index = wizard._mode_combo.findData(mode)
    if index == wizard._mode_combo.currentIndex():
        wizard._mode_changed(index)
    else:
        wizard._mode_combo.setCurrentIndex(index)
    if not saved and wizard._mode_combo.currentData() == "events":
        preferred = preferred_reference(wizard)
        if preferred >= 0:
            wizard._reference_combo.setCurrentIndex(preferred)
    if saved:
        extra_target_channel = str(saved[4]) if len(saved) > 4 else ""
        for specs, combo, saved_id, channel_hint in (
            (wizard._references, wizard._reference_combo, saved[2], ""),
            (wizard._targets, wizard._target_combo, saved[3], extra_target_channel),
        ):
            index = _find_saved_spec(specs, saved_id, channel_hint)
            if index >= 0:
                combo.setCurrentIndex(index)
        _advance_past_aligned(wizard, parent)
    wizard.steps.more_toggle.setChecked(bool(preference("advanced")))
    wizard._fit_details.more_toggle.setChecked(bool(preference("fit_details")))
    wizard._drift_toggle.setChecked(bool(preference("manual_drift")))


def _advance_past_aligned(wizard: SyncWizard, parent: object) -> None:
    """Reopening after Apply offers the next camera, not the one just aligned.

    Aligning a rig's cameras one after another is the ordinary case, and the
    remembered target was the camera the last Apply had already placed.
    """
    records = getattr(parent, "accepted_alignment_records", None)
    if not callable(records) or not wizard._targets:
        return
    aligned = {record.target_id for record in records() if not record.superseded_by}

    def done(index: int) -> bool:
        spec = wizard._targets[index]
        return spec.source_id in aligned or (spec.clock_id or spec.source_id) in aligned

    if not done(wizard._target_combo.currentIndex()):
        return
    reference = (
        wizard._references[wizard._reference_combo.currentIndex()]
        if wizard._references and wizard._reference_combo.currentIndex() >= 0
        else None
    )
    reference_clock = (reference.clock_id or reference.source_id) if reference else ""
    following = next(
        (
            i
            for i, spec in enumerate(wizard._targets)
            if not done(i) and (spec.clock_id or spec.source_id) != reference_clock
        ),
        -1,
    )
    if following >= 0:
        wizard._target_combo.setCurrentIndex(following)


def save(wizard: SyncWizard) -> None:
    """Cancel may remember UI choices, but never applies or remembers a preview."""
    for key, value in (
        ("window_width", wizard.width()),
        ("window_height", wizard.height()),
        ("advanced", wizard.steps.more_toggle.isChecked()),
        ("fit_details", wizard._fit_details.more_toggle.isChecked()),
        ("manual_drift", wizard._drift_toggle.isChecked()),
    ):
        setting = setting_for(f"alignment/{key}")
        assert setting is not None
        write_setting(setting, value)
    parent = as_window(wizard.parentWidget())
    if parent is None or parent.session_runtime.generation != wizard._session_generation:
        return
    reference = wizard._reference_combo.currentIndex()
    target = wizard._target_combo.currentIndex()
    parent.session_runtime.alignment_selection = (
        parent.session_runtime.generation,
        str(wizard._mode_combo.currentData()),
        _selection_key(wizard._references[reference]) if reference >= 0 else "",
        _selection_key(wizard._targets[target]) if target >= 0 else "",
    )
