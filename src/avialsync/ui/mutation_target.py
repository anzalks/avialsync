"""The live application, as the command bus sees it (WP-1 step 4, D-087).

:class:`~avialsync.core.document.Document` executes commands against a
``MutationTarget`` — a protocol declared in ``core/`` precisely so the bus never
touches a widget.  This module is the one implementation that does, binding that
protocol to a running :class:`~avialsync.ui.main_window.MainWindow`.

Two rules shape everything here.

**Drive the control, not just the model.**  Undoing an offset has to move the
spin box the user moved, not only the pane behind it: a control still showing a
value the session no longer holds is worse than no undo, because it lies about
the current state.  So each method goes in through the same widget API the user
would have used, and lets the existing signal chain do the rest.

**Suspend recording while replaying.**  Driving those widgets makes them emit
the very signals that record commands, so an undo would immediately record
itself as a new edit and the stack would never unwind.  :meth:`replaying` holds
the window's recording flag down for the duration.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.document import MarkerRecord, SourceRecord
from avialsync.ui.annotations import Marker

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def marker_record(marker: Marker, index: int) -> MarkerRecord:
    """Describe a UI :class:`Marker` in the bus's own vocabulary.

    ``core/`` may not import the UI's ``Marker`` — it carries palette-resolved
    colour and per-video frame snapshots — so the two types stay separate and
    this is the seam between them.
    """
    return MarkerRecord(
        t_start=marker.t_start,
        t_end=marker.t_end,
        label=marker.label,
        index=index,
    )


class WindowMutationTarget:
    """Apply and reverse commands against a live ``MainWindow``."""

    def __init__(self, window: MainWindow) -> None:
        self._window = window
        #: Markers removed by a command, kept so the same object -- with its
        #: colour index and per-video frame snapshots -- comes back on undo.
        #: Rebuilding one from a MarkerRecord would silently drop both.
        self._removed_markers: dict[tuple[float, float | None, str], Marker] = {}

    def retain_removed(self, marker: Marker) -> None:
        """Hold a marker the *user* deleted, so undo can restore that object.

        The common deletion path never goes through this target: the user hits
        Delete, the store removes it, and the window records the command after
        the fact. Without retaining it here, undo would construct a fresh marker
        and silently drop the colour index and per-video frame snapshots that
        made it that annotation rather than a new one.
        """
        self._removed_markers[(marker.t_start, marker.t_end, marker.label)] = marker

    # ── replay guard ─────────────────────────────────────────────────

    @contextlib.contextmanager
    def replaying(self) -> Iterator[None]:
        """Suppress command recording for the duration of an undo or redo."""
        window = self._window
        previous = window._recording_suspended
        window._recording_suspended = True
        try:
            yield
        finally:
            window._recording_suspended = previous

    # ── source mapping ───────────────────────────────────────────────

    def set_source_mapping(self, source_id: str, offset: float, drift_ppm: float) -> None:
        window = self._window
        with self.replaying():
            if source_id in window.video_grid.pane_paths():
                window.sidebar.set_video_offset(source_id, offset)
                window._on_video_offset_changed(source_id, offset)
            else:
                window.sidebar.set_sensor_mapping(source_id, offset, drift_ppm)
                window._on_sensor_mapping_changed(source_id, offset, drift_ppm)

    def source_mapping(self, source_id: str) -> tuple[float, float]:
        window = self._window
        if source_id in window.video_grid.pane_paths():
            offset, drift_ppm = window._video_time_mappings.get(source_id, (0.0, 0.0))
            return (window.sidebar.video_offset(source_id) or offset, drift_ppm)
        return window.sidebar.sensor_mapping(source_id)

    # ── annotations ──────────────────────────────────────────────────

    def add_marker(self, marker: MarkerRecord) -> None:
        window = self._window
        key = (marker.t_start, marker.t_end, marker.label)
        with self.replaying():
            retained = self._removed_markers.pop(key, None)
            if retained is not None:
                window.annotation_store.insert(marker.index, retained)
            elif marker.t_end is None:
                window.annotation_store.add_point(marker.t_start, marker.label)
            else:
                window.annotation_store.add_range(marker.t_start, marker.t_end, marker.label)

    def remove_marker(self, marker: MarkerRecord) -> None:
        window = self._window
        with self.replaying():
            for index, candidate in enumerate(window.annotation_store.markers):
                if (
                    candidate.t_start == marker.t_start
                    and candidate.t_end == marker.t_end
                    and candidate.label == marker.label
                ):
                    self._removed_markers[(marker.t_start, marker.t_end, marker.label)] = candidate
                    window.annotation_store.remove(index)
                    return

    def set_marker_label(self, index: int, label: str) -> None:
        with self.replaying():
            self._window.annotation_store.set_label(index, label)

    # ── visibility ───────────────────────────────────────────────────

    def set_source_visible(self, source_id: str, visible: bool) -> None:
        window = self._window
        with self.replaying():
            window.sidebar.set_video_visible(source_id, visible)
            window.video_grid.set_pane_visible(source_id, visible)

    def set_channel_visible(self, source_id: str, channel: str, visible: bool) -> None:
        window = self._window
        with self.replaying():
            window.sidebar.set_channel_visible(channel, visible, source_id)
            window.plot_pane.set_channel_visible(ChannelKey(source_id, channel), visible)

    def set_overlay_visible(self, overlay_id: str, camera: str | None, visible: bool) -> None:
        """Reserved for WP-4's overlay registry, which does not exist yet.

        Declared because the protocol declares it: a partial implementation
        would fail an ``isinstance`` check against the protocol and make the
        whole target look broken rather than this one operation unbuilt.
        """
        raise NotImplementedError(
            "Overlay visibility is routed once WP-4 adds the overlay registry."
        )

    # ── sources ──────────────────────────────────────────────────────

    def add_source(self, record: SourceRecord) -> None:
        """Reload a removed source.

        Re-opening is asynchronous and goes through the loader registry, so this
        restarts the open rather than restoring widgets directly; the offset and
        drift the source had are re-applied by the caller's command once it
        lands.
        """
        window = self._window
        with self.replaying():
            if record.kind == "video":
                window._load_video(Path(record.path), record.offset, record.drift_ppm)
            else:
                window._start_data_import(Path(record.path))

    def remove_source(self, source_id: str) -> None:
        window = self._window
        with self.replaying():
            if source_id in window.video_grid.pane_paths():
                window._on_video_remove_requested(source_id)
            else:
                window._on_sensor_remove_requested(source_id)

    def apply_sync(self, source_id: str, offset: float, drift_ppm: float, evidence: Any) -> None:
        """Re-apply or reverse an accepted alignment.

        Reversing restores the plain offset/drift mapping the source had before
        acceptance. It deliberately does not re-derive an exact sample mapping:
        raw timestamps are never rewritten (architecture rule 8), so the
        provenance the command carries is the record of what was accepted.
        """
        window = self._window
        with self.replaying():
            window.video_grid.set_offset(source_id, offset)
            window.sidebar.set_video_offset(source_id, offset)
            window._video_time_mappings[source_id] = (offset, drift_ppm)
            window._sync_provenance = [
                entry for entry in window._sync_provenance if entry.target_id != source_id
            ]
            if evidence is not None:
                window._sync_provenance.append(evidence)

    # ── whole workspace (Reset Session only) ─────────────────────────

    def capture_workspace(self) -> Any:
        """Snapshot enough to restore the workspace after a reset.

        The one place a command is allowed bulk state, and only because there is
        no compact way to describe "everything that was open" (D-087). It is a
        session document plus the loaded paths, not a deep copy of the widgets.
        """
        window = self._window
        return {
            "state": window._build_session_state(),
            "videos": list(window.video_grid.pane_paths()),
            "sensors": list(window._sensor_cache_dirs),
        }

    def restore_workspace(self, snapshot: Any) -> None:
        window = self._window
        with self.replaying():
            for path in snapshot.get("videos", []):
                window._load_video(Path(path))
            for path in snapshot.get("sensors", []):
                window._start_data_import(Path(path))
            state = snapshot.get("state")
            if state is not None:
                for entry in state.markers:
                    if entry.t_end is None:
                        window.annotation_store.add_point(entry.t_start, entry.label)
                    else:
                        window.annotation_store.add_range(entry.t_start, entry.t_end, entry.label)

    def clear_workspace(self) -> None:
        from avialsync.ui.controllers import session_controller

        with self.replaying():
            session_controller.reset_session(self._window)

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def display_name(source_id: str) -> str:
        """A source's file name, for command labels the user reads."""
        return Path(source_id).name or source_id
