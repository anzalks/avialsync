"""Moving a restored session onto files that were relocated.

Split from `session_controller`: everything keyed by a file path -- the
sources, trigger evidence, accepted alignment records, corrections and
identity swaps -- follows the files the user located, together.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

from avialsync.core.source import source_exists
from avialsync.ui import imaging_integration
from avialsync.ui.controllers import corrections_controller, identity_controller

if TYPE_CHECKING:
    from avialsync.core.session import SessionState
    from avialsync.ui.main_window import MainWindow


def relinked(identifier: str, relink_map: dict[str, str]) -> str:
    """*identifier* after a relink: a path, or a ``path : channel`` evidence id."""
    if identifier in relink_map:
        return relink_map[identifier]
    path, separator, channel = identifier.partition(" : ")
    if separator and path in relink_map:
        return f"{relink_map[path]}{separator}{channel}"
    return identifier


def _missing_files(state: SessionState) -> tuple[list[str], dict[str, str]]:
    """Every file *state* names that is not where it was, with its kind."""
    missing: list[str] = []
    kind_labels: dict[str, str] = {}
    for ve in state.videos:
        if not source_exists(Path(ve.path)):
            missing.append(ve.path)
            kind_labels[ve.path] = "video"
    for se in state.sensors:
        if not source_exists(Path(se.path)):
            missing.append(se.path)
            kind_labels[se.path] = "sensor"
    imaging_integration.collect_missing(state.imaging, missing, kind_labels)
    # Trigger files move with the rest; without a row here a moved trigger file
    # could only be reported, and the alignment evidence it carries was lost.
    for te in state.triggers:
        if te.path not in kind_labels and not Path(te.path).exists():
            missing.append(te.path)
            kind_labels[te.path] = "trigger"
    return missing, kind_labels


def relink_missing(window: MainWindow, state: SessionState) -> dict[str, str] | None:
    """Ask for any missing files and move *state* onto where they now are.

    None means the user cancelled the open.
    """
    missing, kind_labels = _missing_files(state)
    relink_map: dict[str, str] = {}
    if missing:
        from avialsync.ui.relink_dialog import RelinkDialog

        dlg = RelinkDialog(missing, kind_labels, window)
        if dlg.exec() == RelinkDialog.DialogCode.Rejected:
            return None
        relink_map = dlg.resolved_mapping()

    for old_path, new_path in relink_map.items():
        # Corrections are keyed by the pose file's path; without this a session
        # whose CSV moved would open with every correction silently inactive,
        # and its expected count would be checked against a file that is gone.
        corrections_controller.remap(window, str(old_path), str(new_path))
        # Accepted identity swaps are keyed the same way, and were orphaned.
        identity_controller.remap(window, str(old_path), str(new_path))
    if relink_map:
        state.triggers = [
            dataclasses.replace(entry, path=relink_map.get(entry.path, entry.path))
            for entry in state.triggers
        ]
        state.sync_provenance = [
            dataclasses.replace(
                record,
                target_id=relinked(record.target_id, relink_map),
                reference_id=relinked(record.reference_id, relink_map),
                reference_clock_id=relinked(record.reference_clock_id, relink_map),
            )
            for record in state.sync_provenance
        ]
    return relink_map
