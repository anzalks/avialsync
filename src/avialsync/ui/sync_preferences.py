"""Schema-owned layout memory and session-scoped alignment selection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from avialsync.core.settings_schema import setting_for
from avialsync.ui.preferences_dialog import read_setting, write_setting
from avialsync.ui.sync_choices import preferred_reference, suggested_mode
from avialsync.ui.sync_lifecycle import as_window

if TYPE_CHECKING:
    from avialsync.ui.sync_wizard import SyncWizard


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
        for specs, combo, source_id in (
            (wizard._references, wizard._reference_combo, saved[2]),
            (wizard._targets, wizard._target_combo, saved[3]),
        ):
            index = next((i for i, spec in enumerate(specs) if spec.source_id == source_id), -1)
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
        wizard._references[reference].source_id if reference >= 0 else "",
        wizard._targets[target].source_id if target >= 0 else "",
    )
