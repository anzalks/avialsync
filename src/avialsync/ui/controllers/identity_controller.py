"""Accepted identity flips: persisted beside the data, materialised into cache.

The same shape as :mod:`avialsync.ui.controllers.corrections_controller`, and
for the same reasons (D-099): a flip is a fact about the recording, so it is
written beside the pose file the moment it is accepted rather than waiting for
somebody to remember Ctrl+S, and the session records only a count so a missing
sidecar can be *reported* instead of silently showing the old identities.

What is new here is the second step.  A correction changes one sample and the
overlay can apply it as it paints; a flip changes every frame from here to the
end, and the plot rows, the 3D view, the readout and the exports all have to
agree with the overlay about who is who.  So an accepted flip is materialised:
:mod:`avialsync.core.edit_cache` writes the edited channels into a generation
of the source's own sidecar cache, and every reader is re-pointed at it.  From
then on nothing downstream knows that flips exist -- it is reading a tracker
that says what the user says it says (D-142).

The recording is never written, the imported pyramid is never written, and the
generation is a pure function of the two sidecars: deleting the cache costs a
rebuild and nothing else.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from avialsync.core import edit_cache, identity_sidecar
from avialsync.core.edit_program import EditProgram
from avialsync.core.edit_program import build as build_program
from avialsync.core.identity_groups import groups_for_schema, is_custom
from avialsync.core.identity_swaps import SwapEvent, SwapGroup
from avialsync.core.pose import PoseSchema
from avialsync.engine.identity_worker import MaterialiseWorker
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

#: Where a source's flips are kept.  A source is "session" only because writing
#: beside it failed, never by preference.
SIDECAR = "sidecar"
SESSION = "session"


# ── what the window knows about one pose source ──────────────────────


def schema_for(window: MainWindow, source_id: str) -> PoseSchema | None:
    """The pose structure of one imported source, as its loader declared it."""
    return window._pose_schemas.get(source_id)


def cache_dir_for(window: MainWindow, source_id: str) -> Path | None:
    """Where that source was imported to."""
    directory = window._pose_cache_dirs.get(source_id)
    return Path(directory) if directory else None


def program_for(window: MainWindow, source_id: str) -> EditProgram:
    """Everything standing between the recording and what is shown."""
    schema = schema_for(window, source_id)
    points = [point.name for point in schema.points] if schema is not None else []
    return build_program(source_id, window.identity_swaps, window.point_edits, points=points)


def routes_for(window: MainWindow, source_id: str) -> EditProgram:
    """The edit program for *source_id*, cached until its flips change.

    Cached because the overlay asks per point per paint, and rebuilding a
    program means re-reading every accepted event and every correction. The
    cache is dropped wholesale by :func:`forget_routes`, which the window calls
    from its swap observer -- so there is no second rule about when it is
    stale.
    """
    held = window._identity_routes.get(source_id)
    if held is None:
        held = program_for(window, source_id)
        window._identity_routes[source_id] = held
    return held


def forget_routes(window: MainWindow, source_id: str | None = None) -> None:
    """Drop the cached program for one source, or for all of them."""
    if source_id is None:
        window._identity_routes.clear()
    else:
        window._identity_routes.pop(source_id, None)


def data_point_for(window: MainWindow, source_id: str, name: str, index: int) -> str:
    """The column the point labelled *name* is showing at *index*.

    Itself, unless an accepted flip is in force -- and itself again while
    ``Show original tracker`` is on, because then the readers really are the
    imported prediction and what is on screen is what the model said (D-141).
    """
    if window._show_original_tracker:
        return name
    return routes_for(window, source_id).source_of(name, index)


def edited_cache(window: MainWindow, source_id: str) -> edit_cache.EditedCache | None:
    """The generation this source's readers are currently pointed at."""
    return window._edited_generations.get(source_id)


def directories_for(window: MainWindow, source_id: str) -> dict[str, Path]:
    """Where each of a source's channels should be read from, right now.

    Every channel, not only the edited ones: handing back the full map is what
    lets undoing the last flip point the readers home again by the same path
    that pointed them away.
    """
    cache = cache_dir_for(window, source_id)
    schema = schema_for(window, source_id)
    if cache is None or schema is None:
        return {}
    generation = None if window._show_original_tracker else edited_cache(window, source_id)
    channels: dict[str, Path] = {}
    for point in schema.points:
        names = [point.channel(axis) for axis in point.axes]
        likelihood = point.likelihood_channel
        if likelihood is not None:
            names.append(likelihood)
        for channel in names:
            channels[channel] = (
                generation.dir_for(cache, channel) if generation is not None else cache
            )
    return channels


# ── accepting and undoing ────────────────────────────────────────────


def apply(window: MainWindow, source_id: str, event: SwapEvent, *, accept: bool) -> bool:
    """Accept or undo one flip, then persist and rebuild.

    The single funnel every flip passes through -- the drag, its undo, and its
    redo alike -- which is why persistence hangs off it rather than off the
    store's observers: reading a sidecar in must not echo it straight back out
    (D-099).
    """
    store = window.identity_swaps
    changed = store.add(source_id, event) if accept else store.remove(source_id, event)
    if not changed:
        return False
    persist(window, source_id)
    refresh(window, source_id)
    return True


def persist(window: MainWindow, source_id: str) -> None:
    """Write one source's flips beside its pose file, now."""
    if not source_id:
        return
    events = list(window.identity_swaps.events_for(source_id))
    groups = list(window.identity_swaps.groups_for(source_id))
    try:
        written = identity_sidecar.write(Path(source_id), events, groups)
    except OSError as error:
        _fall_back_to_the_session(window, source_id, error)
        return

    window._swap_storage[source_id] = SIDECAR
    if source_id not in window._announced_swap_files:
        window._announced_swap_files.add(source_id)
        window.notifications.show_success(
            tr("Identity swaps for {source} are saved beside it, in {file}.").format(
                source=Path(source_id).name, file=written.name
            )
        )


def _fall_back_to_the_session(window: MainWindow, source_id: str, error: OSError) -> None:
    """Keep the work when the data directory will not take it."""
    window._swap_storage[source_id] = SESSION
    logger.warning("Could not write identity swaps beside %s", source_id, exc_info=error)
    if source_id in window._announced_swap_files:
        return
    window._announced_swap_files.add(source_id)
    window.notifications.show_warning(
        tr(
            "Identity swaps for {source} are kept in this session: its folder "
            "could not be written. Save the session to keep them."
        ).format(source=Path(source_id).name),
        details=str(error),
    )


def adopt(window: MainWindow, source_id: str) -> None:
    """Declare a source's groups and load the flips that live beside it."""
    if not source_id:
        return
    schema = schema_for(window, source_id)
    if schema is not None:
        window.identity_swaps.set_groups(source_id, groups_for_schema(schema))
    window.identity_swaps.adopt_groups(source_id, window._expected_swap_groups.pop(source_id, ()))
    # Declaring lanes is not an edit, so the store does not notify -- but it is
    # exactly what decides whether Fix Identities has anything to act on, and a
    # command that greys out with its reason has to be told (D-107).
    window._refresh_action_availability()

    held = identity_sidecar.read(Path(source_id))
    expected = window._expected_swap_counts.pop(source_id, None)
    if held is None:
        if expected:
            _report_missing(window, source_id, expected)
        refresh(window, source_id)
        return

    # The sidecar's own group definitions win nothing and lose nothing: they
    # fill in whatever this session could not derive, so an event stays
    # interpretable when a loader names its lanes differently.
    window.identity_swaps.adopt_groups(source_id, held.groups)
    window.identity_swaps.load_source(source_id, held.events)
    window._swap_storage[source_id] = SIDECAR

    name = Path(source_id).name
    if held.skipped:
        window.notifications.show_warning(
            tr("{n} identity swap(s) in {file} could not be read and were skipped.").format(
                n=held.skipped, file=identity_sidecar.sidecar_path(source_id).name
            )
        )
    if expected is not None and expected != len(held.events):
        window.notifications.show_warning(
            tr(
                "This session recorded {expected} identity swap(s) for {source} "
                "and its swaps file holds {found}."
            ).format(expected=expected, source=name, found=len(held.events))
        )
    refresh(window, source_id)


def _report_missing(window: MainWindow, source_id: str, expected: int) -> None:
    window.notifications.show_warning(
        tr(
            "This session recorded {expected} identity swap(s) for {source}, "
            "and no swaps file was found beside it."
        ).format(expected=expected, source=Path(source_id).name)
    )


# ── making the edits the thing that is read ──────────────────────────


def refresh(window: MainWindow, source_id: str) -> None:
    """Rebuild this source's edited generation, then re-point its readers.

    Skipped when the generation the edits name is already on disk, which is
    what makes reopening a session with edits cost nothing.  The rebuild itself
    is a registered job: it writes a pyramid per edited channel and has no
    business on the UI thread (rules 3 and 11).
    """
    cache = cache_dir_for(window, source_id)
    schema = schema_for(window, source_id)
    if cache is None or schema is None:
        return

    program = program_for(window, source_id)
    ready = edit_cache.load(cache, program.fingerprint)
    if ready is not None or not program:
        _adopt_generation(
            window,
            source_id,
            ready or edit_cache.EditedCache(fingerprint=program.fingerprint, directory=cache),
        )
        return

    worker = MaterialiseWorker(source_id, cache, program, schema)

    def _wire(_thread: Any) -> None:
        # Marshalled, not connected bare: these land on the worker's thread
        # otherwise, and every one of them touches widgets (D-051).
        worker.finished.connect(
            on_ui_thread(
                lambda finished_source, edited: _adopt_generation(window, finished_source, edited),
                window,
            )
        )
        worker.error.connect(
            on_ui_thread(
                lambda message: window.notifications.show_warning(
                    tr("The edited tracking for {source} could not be built.").format(
                        source=Path(source_id).name
                    ),
                    details=message,
                ),
                window,
            )
        )

    window._run_job(
        worker,
        label=tr("Applying tracking edits to {source}").format(source=Path(source_id).name),
        configure=_wire,
    )


def _adopt_generation(window: MainWindow, source_id: str, edited: edit_cache.EditedCache) -> None:
    """Point every reader of this source at *edited*, and tidy older ones.

    A result that no longer describes the current edits is dropped. Every edit
    starts a rebuild, so several are in flight while a person works, and they
    finish in whatever order the disk allows -- adopting each as it arrives
    would let a slow job for two edits ago decide what the overlay shows.
    """
    if edited.fingerprint != program_for(window, source_id).fingerprint:
        logger.debug(
            "Dropping a superseded edited generation for %s (%s).", source_id, edited.fingerprint
        )
        return
    window._edited_generations[source_id] = edited
    directories = directories_for(window, source_id)
    if not directories:
        return

    _repoint_source(window, source_id, directories)

    cache = cache_dir_for(window, source_id)
    if cache is not None:
        # The current generation, and nothing else this module wrote. The
        # previous one is not kept: its readers are closed by the line above,
        # and a directory per edit would grow without bound beside the data.
        edit_cache.prune(cache, keep=[edited.fingerprint])
    for video, sources in window._overlay_sources.items():
        if source_id in sources:
            window._refresh_overlays(video)
    window._refresh_pose_3d()
    window._refresh_identity_panel()


def apply_reader_view(window: MainWindow) -> None:
    """Switch each pose source between imported and edited cache readers."""
    for source_id in window._pose_schemas:
        directories = directories_for(window, source_id)
        if not directories:
            continue
        _repoint_source(window, source_id, directories)
    for video in window._overlay_sources:
        window._refresh_overlays(video)
    window._refresh_pose_3d()
    window._refresh_identity_panel()


def _repoint_source(window: MainWindow, source_id: str, directories: dict[str, Path]) -> None:
    """Use the same reader switch for a new generation and the View action."""
    window.plot_pane.read_channels_from(source_id, directories)
    _repoint_overlays(window, source_id, directories)
    _repoint_pose_3d(window, source_id, directories)


def _repoint_overlays(window: MainWindow, source_id: str, directories: dict[str, Path]) -> None:
    for sources in window._overlay_sources.values():
        entry = sources.get(source_id)
        if entry is None:
            continue
        for readers in (entry.get("points") or {}).values():
            for reader in readers:
                channel = reader.channel_id
                if channel in directories:
                    reader.read_from(directories[channel])


def _repoint_pose_3d(window: MainWindow, source_id: str, directories: dict[str, Path]) -> None:
    for reader in window._pose_3d_sources.get(source_id, ()):
        channel = reader.channel_id
        if channel in directories:
            reader.read_from(directories[channel])


# ── the session's own record ─────────────────────────────────────────


def build_manifest(window: MainWindow) -> list[dict[str, Any]]:
    """Describe flips and fallback group declarations for the ``.avv``."""
    manifest: list[dict[str, Any]] = []
    sources = window.identity_swaps.source_ids() | set(window._swap_storage)
    for source_id in sorted(sources):
        custom = [
            group.as_dict()
            for group in window.identity_swaps.groups_for(source_id)
            if is_custom(group.name)
        ]
        if not custom and not window.identity_swaps.count_for(source_id):
            continue
        storage = window._swap_storage.get(source_id, SIDECAR)
        entry: dict[str, Any] = {
            "source": source_id,
            "count": window.identity_swaps.count_for(source_id),
            "storage": storage,
        }
        if storage == SESSION:
            # The fallback: the flips themselves, because nothing beside the
            # pose file could hold them.
            entry["swaps"] = window.identity_swaps.to_list(source_id)
            entry["groups"] = custom
        manifest.append(entry)
    return manifest


def restore_manifest(window: MainWindow, manifest: list[dict[str, Any]] | None) -> None:
    """Take what a session recorded, and check it as each source imports."""
    window._expected_swap_counts.clear()
    window._expected_swap_groups.clear()
    for entry in manifest or []:
        try:
            source_id = str(entry["source"])
        except (KeyError, TypeError):
            continue
        if entry.get("storage") == SESSION:
            window.identity_swaps.adopt(entry.get("swaps") or [])
            window._swap_storage[source_id] = SESSION
            window._expected_swap_groups[source_id] = tuple(
                SwapGroup.from_dict(group)
                for group in entry.get("groups") or []
                if isinstance(group, dict)
            )
            continue
        try:
            window._expected_swap_counts[source_id] = int(entry.get("count", 0))
        except (TypeError, ValueError):
            continue


def remap(window: MainWindow, old_id: str, new_id: str) -> None:
    """Follow a relinked pose file to its new path."""
    window.identity_swaps.remap_source(old_id, new_id)
    if old_id in window._swap_storage:
        window._swap_storage[new_id] = window._swap_storage.pop(old_id)
