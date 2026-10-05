"""Accepting a flip changes what is read, and nothing else (D-141, D-142).

The end-to-end claim this file exists to pin: after a swap is accepted, every
consumer -- the overlay, the 3D view, a plot row, the readout -- reads the
edited tracker, because the edit was materialised into the source's cache
rather than applied by each of them. The recording and its imported pyramid are
byte-for-byte what they were, and undoing the flip points everything home.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from shiboken6 import isValid

from avialsync.core import identity_sidecar
from avialsync.core.commands import SetIdentityGroupCommand
from avialsync.core.identity_detect import Candidate
from avialsync.core.identity_groups import ANIMALS
from avialsync.core.identity_swaps import SwapEvent, SwapGroup
from avialsync.core.inspection import SourceInspection
from avialsync.core.point_edits import PointKey
from avialsync.core.pose import PosePoint, PoseSchema
from avialsync.core.pyramid import PyramidBuilder
from avialsync.core.session import SessionState
from avialsync.ui import identity_model_worker
from avialsync.ui.controllers import identity_controller, identity_view, import_controller
from avialsync.ui.main_window import MainWindow

FRAMES = 120
FLIP = 60
FPS = 30.0
VIDEO = "/data/arena.mp4"
INDIVIDUALS = ("testMouse", "conSpecific")
PARTS = ("snout", "wrist")

SCHEMA = PoseSchema(
    points=tuple(
        PosePoint(individual=individual, bodypart=part, axes=("x", "y"), has_likelihood=True)
        for individual in INDIVIDUALS
        for part in PARTS
    ),
    frame_indexed=True,
)


def _channel_value(point: str, axis: str) -> float:
    """A value that names its own column, so a swap is visible by inspection."""
    return (
        1000.0 * (INDIVIDUALS.index(point.split("_")[0]) + 1)
        + 10.0 * PARTS.index(point.split("_", 1)[1])
        + (1.0 if axis == "y" else 0.0)
    )


@pytest.fixture
def pose_source(tmp_path: Path) -> tuple[Path, Path, list[str]]:
    """A pose file on disk, and its imported cache."""
    pose = tmp_path / "twomice_DLC.csv"
    pose.write_text("scorer,DLC\nindividuals,testMouse\n", encoding="utf-8")

    cache = tmp_path / "twomice_DLC.csv_cache"
    cache.mkdir()
    times = np.arange(FRAMES, dtype=np.float64) / FPS
    channels: list[str] = []
    for point in SCHEMA.points:
        for axis in ("x", "y"):
            channel = point.channel(axis)
            values = np.full(FRAMES, _channel_value(point.name, axis), dtype=np.float64)
            PyramidBuilder(cache, channel).build_and_save(times, values)
            channels.append(channel)
        likelihood = point.likelihood_channel
        assert likelihood is not None
        PyramidBuilder(cache, likelihood).build_and_save(
            times, np.full(FRAMES, 0.4, dtype=np.float64)
        )
        channels.append(likelihood)
    return pose, cache, channels


def _register(window: MainWindow, pose: Path, cache: Path, channels: list[str]) -> None:
    import_controller.register_tracking_source(
        window,
        path=str(pose),
        cache_dir=cache,
        channels=channels,
        role="pose2d",
        inspection=SourceInspection(
            path=str(pose),
            loader_id="tracking",
            import_config={"overlay_video": VIDEO, "fps": FPS},
            pose=SCHEMA,
        ),
    )


@pytest.fixture
def window(qtbot, pose_source) -> MainWindow:
    pose, cache, channels = pose_source
    window = MainWindow()
    qtbot.addWidget(window)
    _register(window, pose, cache, channels)
    yield window
    if isValid(window):
        window.close()


def _readers(window: MainWindow, source: str, point: str):
    return window._overlay_sources[VIDEO][source]["points"][point]


def _shown(window: MainWindow, source: str, point: str, index: int) -> float:
    """What the overlay would draw for *point* at *index*, in x."""
    reader = _readers(window, source, point)[0]
    return float(reader.source_reader.mapped_columns()[1][index])


def _settle(qtbot, window: MainWindow, source: str) -> None:
    """Wait for the rebuild job, which runs off the UI thread like every job.

    Waiting for the generation the *current* edits name, not merely for one to
    exist: an unedited source already has an empty generation from its import,
    so anything weaker passes before the rebuild has started.
    """

    def _ready() -> bool:
        generation = identity_controller.edited_cache(window, source)
        wanted = identity_controller.program_for(window, source).fingerprint
        return (
            generation is not None
            and generation.fingerprint == wanted
            and bool(generation.channels)
        )

    qtbot.waitUntil(_ready, timeout=5000)


def _accept(window: MainWindow, source: str, at: int = FLIP) -> SwapEvent:
    event = SwapEvent(index=at, group=ANIMALS, lanes=INDIVIDUALS)
    identity_controller.apply(window, source, event, accept=True)
    return event


# ── the import declares what can be confused ─────────────────────────


def test_importing_a_multi_animal_file_declares_its_lanes(window, pose_source) -> None:
    source = str(pose_source[0])
    group = window.identity_swaps.group(source, ANIMALS)

    assert group is not None
    assert group.lanes == INDIVIDUALS
    assert sorted(group.parts) == sorted(PARTS)


# ── accepting one ────────────────────────────────────────────────────


def test_the_overlay_reads_the_other_animal_after_the_flip(qtbot, window, pose_source) -> None:
    source = str(pose_source[0])
    before = _shown(window, source, "testMouse_snout", FLIP)

    _accept(window, source)
    _settle(qtbot, window, source)

    assert _shown(window, source, "testMouse_snout", FLIP - 1) == before
    assert _shown(window, source, "testMouse_snout", FLIP) == _channel_value(
        "conSpecific_snout", "x"
    )
    assert _shown(window, source, "conSpecific_snout", FLIP) == _channel_value(
        "testMouse_snout", "x"
    )


def test_the_recording_and_its_imported_cache_are_untouched(qtbot, window, pose_source) -> None:
    pose, cache, _channels = pose_source
    source = str(pose)
    recording = pose.read_bytes()
    imported = {path.name: path.read_bytes() for path in cache.glob("*.npy")}

    _accept(window, source)
    _settle(qtbot, window, source)

    assert pose.read_bytes() == recording
    assert {path.name: path.read_bytes() for path in cache.glob("*.npy")} == imported


def test_an_accepted_flip_is_written_beside_the_pose_file(qtbot, window, pose_source) -> None:
    pose = pose_source[0]
    _accept(window, str(pose))
    _settle(qtbot, window, str(pose))

    held = identity_sidecar.read(pose)

    assert held is not None
    assert [event.index for event in held.events] == [FLIP]
    # The group travels with the event, so it stays interpretable even if a
    # later import names its lanes differently.
    assert held.groups[0].point("testMouse", "snout") == "testMouse_snout"


def test_an_accepted_flip_is_visible_and_can_be_deleted_from_changes(
    qtbot, window, pose_source
) -> None:
    """The list, plot, and source badge describe the same accepted event."""
    pose, cache, channels = pose_source
    source = str(pose)
    # This fixture registers the overlay directly; the normal import path also
    # creates plot rows and a sidebar source, which this test needs to inspect.
    window.sidebar.add_sensor(source, channels)
    window.plot_pane.load_channels(cache, channels[:2], source_id=source)
    window.plot_pane.wait_for_pending_rows()
    event = SwapEvent(index=FLIP, group=ANIMALS, lanes=INDIVIDUALS)
    identity_view.swap(window, source, event)
    _settle(qtbot, window, source)

    rows = window.changes_panel.rows
    assert len(rows) == 1
    assert rows[0].swap == event
    assert rows[0].t_master == pytest.approx(FLIP / FPS)
    assert "frame 60" in rows[0].detail
    sensor = window.sidebar.sensor_widget(source)
    assert sensor is not None
    assert sensor.identity_count.text() == "Swaps: 1"
    assert sensor.identity_count.isVisibleTo(sensor)
    assert window.plot_pane._interactions._identity_events[source][0][0] == pytest.approx(
        FLIP / FPS
    )
    window.plot_pane.set_timeline_bounds(0.0, FRAMES / FPS)
    window.plot_pane.set_cursor(FLIP / FPS, immediate=True)
    window.plot_pane._interactions.redraw_identity_markers()
    assert window.plot_pane._interactions._identity_items

    window.changes_panel._table.selectRow(0)
    window.changes_panel._on_delete()
    assert window.identity_swaps.count_for(source) == 0
    assert window.changes_panel.rows == []
    assert not window.plot_pane._interactions._identity_items
    assert not sensor.identity_count.isVisibleTo(sensor)
    window.document.undo(window._mutations)
    assert window.identity_swaps.count_for(source) == 1


def test_undoing_the_flip_points_every_reader_home(qtbot, window, pose_source) -> None:
    source = str(pose_source[0])
    before = _shown(window, source, "testMouse_snout", FLIP)
    event = _accept(window, source)
    _settle(qtbot, window, source)
    assert _shown(window, source, "testMouse_snout", FLIP) != before

    identity_controller.apply(window, source, event, accept=False)
    qtbot.waitUntil(lambda: _shown(window, source, "testMouse_snout", FLIP) == before, timeout=5000)

    assert window.identity_swaps.count_for(source) == 0


def test_show_original_switches_readers_without_losing_edits(qtbot, window, pose_source) -> None:
    """The comparison view and its undo change readers, never the edit program."""
    source = str(pose_source[0])
    raw = _shown(window, source, "testMouse_snout", FLIP)
    _accept(window, source)
    _settle(qtbot, window, source)
    edited = _shown(window, source, "testMouse_snout", FLIP)
    assert edited != raw

    window._act_show_original_tracker.trigger()
    assert window._show_original_tracker
    assert _shown(window, source, "testMouse_snout", FLIP) == raw
    assert window.identity_swaps.count_for(source) == 1
    state = SessionState.from_dict(window._build_session_state().to_dict())
    assert state.show_original_tracker
    assert not SessionState.from_dict({"version": 10}).show_original_tracker

    window.document.undo(window._mutations)
    assert not window._act_show_original_tracker.isChecked()
    assert _shown(window, source, "testMouse_snout", FLIP) == edited


def test_only_the_selected_part_moves_when_one_is_named(qtbot, window, pose_source) -> None:
    source = str(pose_source[0])
    identity_controller.apply(
        window,
        source,
        SwapEvent(index=FLIP, group=ANIMALS, lanes=INDIVIDUALS, parts=("wrist",)),
        accept=True,
    )
    _settle(qtbot, window, source)

    assert _shown(window, source, "testMouse_wrist", FLIP) == _channel_value(
        "conSpecific_wrist", "x"
    )
    assert _shown(window, source, "testMouse_snout", FLIP) == _channel_value("testMouse_snout", "x")


def test_an_accepted_flip_reaches_the_data_streams_lane(qtbot, window, pose_source) -> None:
    source = str(pose_source[0])
    _accept(window, source)
    _settle(qtbot, window, source)

    assert "Identity" in window.transport.overview.lane_labels()


# ── a correction rides the same rebuild ──────────────────────────────


def test_a_correction_reaches_the_cached_channel_too(qtbot, window, pose_source) -> None:
    """One edit program, so a hand correction lands where a flip does."""
    source = str(pose_source[0])

    window._mutations.set_tracked_point(source, "testMouse_snout", 7, (12.0, 34.0))
    qtbot.waitUntil(lambda: _shown(window, source, "testMouse_snout", 7) == 12.0, timeout=5000)

    assert window.point_edits.get(PointKey(source, "testMouse_snout", 7)) == (12.0, 34.0)
    assert _shown(window, source, "testMouse_snout", 8) == _channel_value("testMouse_snout", "x")


def test_a_correction_made_under_a_swapped_label_follows_its_own_column(
    qtbot, window, pose_source
) -> None:
    """The user drags what is labelled testMouse; the value belongs to the
    trajectory that label is currently showing, which is conSpecific's column."""
    source = str(pose_source[0])
    _accept(window, source)
    _settle(qtbot, window, source)

    window._mutations.set_tracked_point(
        source, "conSpecific_snout", FLIP + 5, (7.0, 8.0), "testMouse_snout"
    )
    qtbot.waitUntil(
        lambda: _shown(window, source, "testMouse_snout", FLIP + 5) == 7.0, timeout=5000
    )

    key = PointKey(source, "conSpecific_snout", FLIP + 5)
    assert window.point_edits.shown_as(key) == "testMouse_snout"


# ── the panel, and the command bus behind its gestures ───────────────


def test_the_panel_opens_on_the_tracking_that_is_loaded(qtbot, window, pose_source) -> None:
    window._open_identity_panel()
    panel = window._identity_window.panel
    qtbot.waitUntil(lambda: panel._model is not None, timeout=5000)

    assert panel.source_id() == str(pose_source[0])
    assert panel.group_id() == ANIMALS
    assert panel.part() == ""
    assert not window._identity_window.isFloating()
    assert window.dockWidgetArea(window._identity_window) == Qt.DockWidgetArea.RightDockWidgetArea


def test_a_drag_in_the_panel_is_one_undoable_flip(qtbot, window, pose_source) -> None:
    source = str(pose_source[0])
    window._open_identity_panel()
    panel = window._identity_window.panel
    qtbot.waitUntil(lambda: panel._model is not None, timeout=5000)
    model = panel._model
    assert model is not None

    panel._on_dragged(
        float(model.times[FLIP]),
        model.row("testMouse"),
        float(model.times[FLIP]),
        model.row("conSpecific"),
    )
    _settle(qtbot, window, source)

    assert window.identity_swaps.count_for(source) == 1
    assert window.document.undo_label() == f"Swap conSpecific and testMouse from frame {FLIP}"

    window.document.undo(window._mutations)
    qtbot.waitUntil(lambda: window.identity_swaps.count_for(source) == 0, timeout=5000)
    assert _shown(window, source, "testMouse_snout", FLIP) == _channel_value("testMouse_snout", "x")


def test_braid_data_is_read_in_a_registered_worker(qtbot, window, monkeypatch) -> None:
    original = identity_model_worker.build_braid
    threads: list[int] = []

    def recorded(job):
        threads.append(threading.get_ident())
        return original(job)

    monkeypatch.setattr(identity_model_worker, "build_braid", recorded)
    ui_thread = threading.get_ident()
    window._open_identity_panel()
    qtbot.waitUntil(lambda: window._identity_window.panel._model is not None, timeout=5000)

    assert threads and all(thread != ui_thread for thread in threads)


def test_selected_crossing_plays_in_the_main_transport(qtbot, window, pose_source) -> None:
    source = str(pose_source[0])
    window._swap_candidates[(source, ANIMALS, "")] = (
        Candidate(index=FLIP, lanes=INDIVIDUALS, separation=4.2, cost_ratio=0.3, gap=0),
    )
    window._open_identity_panel()
    panel = window._identity_window.panel
    qtbot.waitUntil(lambda: len(panel.nodes()) == 1, timeout=5000)
    assert window.transport.overview._identity_candidates
    window.clock.set_bounds(0.0, (FRAMES - 1) / FPS)
    window.transport.set_bounds(0.0, (FRAMES - 1) / FPS)
    panel.set_video_available(True)
    panel._play.click()

    assert window.transport._ab_in_t == pytest.approx(0.0)
    assert window.transport._ab_out_t == pytest.approx((FRAMES - 1) / FPS)
    assert window.clock.state.playing
    window.player.set_playing(False)


def test_a_custom_group_is_undoable_and_persisted(qtbot, window, pose_source) -> None:
    source = str(pose_source[0])
    group = SwapGroup(
        name="custom:front paws",
        lanes=("A", "B"),
        parts=("front",),
        members=(("A", "front", "testMouse_snout"), ("B", "front", "conSpecific_snout")),
    )
    window.document.execute(SetIdentityGroupCommand(source, group), window._mutations)
    assert window.identity_swaps.group(source, group.name) == group
    held = identity_sidecar.read(pose_source[0])
    assert held is not None and group in held.groups

    window.document.undo(window._mutations)
    assert window.identity_swaps.group(source, group.name) is None
    window.document.redo(window._mutations)
    assert window.identity_swaps.group(source, group.name) == group


def test_a_custom_group_survives_a_read_only_source_folder(
    qtbot, window, pose_source, monkeypatch
) -> None:
    source = str(pose_source[0])
    group = SwapGroup(
        name="custom:paws",
        lanes=("A", "B"),
        parts=("paw",),
        members=(("A", "paw", "testMouse_snout"), ("B", "paw", "conSpecific_snout")),
    )

    def read_only(*_args, **_kwargs):
        raise OSError("read only")

    monkeypatch.setattr(identity_sidecar, "write", read_only)
    window.document.execute(SetIdentityGroupCommand(source, group), window._mutations)
    manifest = identity_controller.build_manifest(window)
    assert manifest[0]["groups"] == [group.as_dict()]

    window.identity_swaps.clear()
    identity_controller.restore_manifest(window, manifest)
    identity_controller.adopt(window, source)
    assert window.identity_swaps.group(source, group.name) == group


def test_fix_identities_is_offered_only_when_there_is_something_to_fix(
    qtbot, window, pose_source
) -> None:
    assert window._act_fix_identities.isEnabled()

    empty = MainWindow()
    qtbot.addWidget(empty)
    assert not empty._act_fix_identities.isEnabled()
    assert "Import 2D tracking" in empty._act_fix_identities.toolTip()
    if isValid(empty):
        empty.close()


# ── finding one, end to end ──────────────────────────────────────────


def test_a_scan_proposes_the_flip_that_was_injected(qtbot, tmp_path) -> None:
    """The failure is injected into known trajectories, so the frame is known.

    End to end this time: through the worker, the readers and the selectors,
    rather than against the detector's own function.
    """
    pose = tmp_path / "crossing_DLC.csv"
    pose.write_text("scorer,DLC\n", encoding="utf-8")
    cache = tmp_path / "crossing_DLC.csv_cache"
    cache.mkdir()

    times = np.arange(FRAMES, dtype=np.float64) / FPS
    frames = np.arange(FRAMES, dtype=np.float64)
    # Two animals crossing, twelve pixels apart, with the labels exchanged from
    # FLIP onward -- which is what an estimator writes when it loses track.
    truth = {
        "testMouse": (5.0 * frames, np.full(FRAMES, 50.0)),
        "conSpecific": (2 * 5.0 * FLIP - 5.0 * frames, np.full(FRAMES, 62.0)),
    }
    seen = {
        "testMouse": tuple(
            np.concatenate([truth["testMouse"][axis][:FLIP], truth["conSpecific"][axis][FLIP:]])
            for axis in (0, 1)
        ),
        "conSpecific": tuple(
            np.concatenate([truth["conSpecific"][axis][:FLIP], truth["testMouse"][axis][FLIP:]])
            for axis in (0, 1)
        ),
    }

    channels: list[str] = []
    for point in SCHEMA.points:
        for axis_index, axis in enumerate(("x", "y")):
            channel = point.channel(axis)
            PyramidBuilder(cache, channel).build_and_save(times, seen[point.individual][axis_index])
            channels.append(channel)
        likelihood = point.likelihood_channel
        assert likelihood is not None
        PyramidBuilder(cache, likelihood).build_and_save(
            times, np.full(FRAMES, 0.9, dtype=np.float64)
        )
        channels.append(likelihood)

    window = MainWindow()
    qtbot.addWidget(window)
    _register(window, pose, cache, channels)
    source = str(pose)

    identity_view.detect(window, source, ANIMALS, "snout")
    qtbot.waitUntil(
        lambda: all(
            (source, ANIMALS, part) in window._swap_candidates for part in ("", "snout", "wrist")
        ),
        timeout=10_000,
    )

    found = window._swap_candidates[(source, ANIMALS, "snout")]
    assert [candidate.index for candidate in found] == [FLIP]
    assert [
        candidate.index for candidate in window._swap_candidates[(source, ANIMALS, "wrist")]
    ] == [FLIP]
    # Proposed, never applied: nothing is edited until a person says so.
    assert window.identity_swaps.count_for(source) == 0
    if isValid(window):
        window.close()


def test_the_window_tells_every_pane_which_column_a_label_shows(qtbot, window, pose_source) -> None:
    """The resolver is not merely implemented, it is installed and correct.

    Phase 8's lesson, one layer down: a capability that is not driven from the
    running application is a capability you do not have.
    """
    source = str(pose_source[0])
    _accept(window, source)
    _settle(qtbot, window, source)

    assert (
        identity_controller.data_point_for(window, source, "testMouse_snout", FLIP)
        == "conSpecific_snout"
    )
    assert (
        identity_controller.data_point_for(window, source, "testMouse_snout", FLIP - 1)
        == "testMouse_snout"
    )
    resolver = window.video_grid.identity_resolver()
    assert resolver is not None
    assert resolver(source, "testMouse_snout", FLIP) == "conSpecific_snout"


# ── a recording whose names reveal nothing (the New group case) ───────


@pytest.fixture
def unpaired_source(tmp_path: Path) -> tuple[Path, Path, list[str]]:
    """Points a tracker can confuse that no naming convention pairs."""
    pose = tmp_path / "onemouse_DLC.csv"
    pose.write_text("scorer,DLC\n", encoding="utf-8")
    cache = tmp_path / "onemouse_DLC.csv_cache"
    cache.mkdir()
    times = np.arange(FRAMES, dtype=np.float64) / FPS
    channels: list[str] = []
    for index, part in enumerate(("wrist", "leg", "head")):
        for axis in ("x", "y"):
            channel = f"{part}_{axis}"
            PyramidBuilder(cache, channel).build_and_save(
                times, np.full(FRAMES, 10.0 * index, dtype=np.float64)
            )
            channels.append(channel)
    return pose, cache, channels


def _unpaired_schema() -> PoseSchema:
    return PoseSchema(
        points=tuple(
            PosePoint(individual="", bodypart=part, axes=("x", "y"))
            for part in ("wrist", "leg", "head")
        ),
        frame_indexed=True,
    )


def test_fix_identities_opens_for_a_recording_with_nothing_derivable(
    qtbot, unpaired_source
) -> None:
    """The case that needs New group most must not be the case that is locked out.

    Animals and left-against-right are the two a schema states for itself. A
    wrist the tracker confuses with a leg is just as real and no name reveals
    it, so gating the panel on a derived group put the only affordance that
    creates one behind a door that only a group could open.
    """
    pose, cache, channels = unpaired_source
    window = MainWindow()
    qtbot.addWidget(window)
    import_controller.register_tracking_source(
        window,
        path=str(pose),
        cache_dir=cache,
        channels=channels,
        role="overlay2d",
        inspection=SourceInspection(
            path=str(pose),
            loader_id="tracking",
            import_config={"overlay_video": VIDEO, "fps": FPS},
            pose=_unpaired_schema(),
        ),
    )

    assert window.identity_swaps.groups_for(str(pose)) == ()
    assert window._act_fix_identities.isEnabled()

    window._open_identity_panel()
    panel = window._identity_window.panel

    assert panel.source_id() == str(pose)
    assert "New group" in panel._evidence.text()
    assert panel._new_group.isEnabled()
    if isValid(window):
        window.close()


def test_a_declared_pair_draws_its_braid(qtbot, unpaired_source) -> None:
    """Declaring the pair is the whole point: the panel must then work."""
    pose, cache, channels = unpaired_source
    window = MainWindow()
    qtbot.addWidget(window)
    import_controller.register_tracking_source(
        window,
        path=str(pose),
        cache_dir=cache,
        channels=channels,
        role="overlay2d",
        inspection=SourceInspection(
            path=str(pose),
            loader_id="tracking",
            import_config={"overlay_video": VIDEO, "fps": FPS},
            pose=_unpaired_schema(),
        ),
    )
    window._open_identity_panel()

    declared = SwapGroup(
        name="custom:limbs",
        lanes=("A", "B"),
        parts=("limb",),
        members=(("A", "limb", "wrist"), ("B", "limb", "leg")),
    )
    window.document.execute(SetIdentityGroupCommand(str(pose), declared), window._mutations)

    panel = window._identity_window.panel
    assert "custom:limbs" in panel.group_ids()
    assert identity_view.job_for(window, str(pose), "custom:limbs", "") is not None
    if isValid(window):
        window.close()


# ── swapping from the playhead, while watching (D-141) ───────────────


def _braid(qtbot, window: MainWindow):
    """Open the panel, wait for the braid a worker builds, and admit its span.

    The clock clamps a seek to its bounds, which are whatever the loaded
    recordings declare; this fixture registers tracking without a video, so the
    span has to be stated or every seek lands on zero.
    """
    window._open_identity_panel()
    panel = window._identity_window.panel
    qtbot.waitUntil(lambda: panel._model is not None, timeout=5000)
    window.clock.set_bounds(*panel._model.span())
    return panel


def test_applying_with_nothing_selected_uses_the_playhead(qtbot, window, pose_source) -> None:
    """Watch it happen, then say so -- no row to find first."""
    source = str(pose_source[0])
    panel = _braid(qtbot, window)
    model = panel._model
    assert model is not None

    window.clock.seek(float(model.times[FLIP]))
    window._apply_identity_swap()
    _settle(qtbot, window, source)

    assert window.identity_swaps.count_for(source) == 1
    assert window.identity_swaps.events_for(source)[0].index == FLIP
    assert _shown(window, source, "testMouse_snout", FLIP) == _channel_value(
        "conSpecific_snout", "x"
    )


def test_a_playhead_swap_is_undoable_like_any_other(qtbot, window, pose_source) -> None:
    source = str(pose_source[0])
    raw = _shown(window, source, "testMouse_snout", FLIP)
    panel = _braid(qtbot, window)
    assert panel._model is not None

    window.clock.seek(float(panel._model.times[FLIP]))
    window._apply_identity_swap()
    _settle(qtbot, window, source)

    window.document.undo(window._mutations)
    qtbot.waitUntil(lambda: _shown(window, source, "testMouse_snout", FLIP) == raw, timeout=5000)
    assert window.identity_swaps.count_for(source) == 0


def test_the_playhead_swap_works_while_the_clock_is_running(qtbot, window, pose_source) -> None:
    """A person sees a flip *during* playback; requiring a pause loses it."""
    source = str(pose_source[0])
    panel = _braid(qtbot, window)
    assert panel._model is not None
    window.clock.seek(float(panel._model.times[FLIP]))
    window.clock.play()

    window._apply_identity_swap()
    _settle(qtbot, window, source)

    assert window.identity_swaps.count_for(source) == 1
    window.clock.pause()


def test_a_superseded_rebuild_does_not_decide_what_is_shown(qtbot, window, pose_source) -> None:
    """Rebuilds finish in whatever order the disk allows, not in edit order."""
    from avialsync.core.edit_cache import EditedCache

    source = str(pose_source[0])
    _accept(window, source)
    _settle(qtbot, window, source)
    current = identity_controller.edited_cache(window, source)
    assert current is not None

    identity_controller._adopt_generation(
        window,
        source,
        EditedCache(fingerprint="0000000000000000", directory=pose_source[1]),
    )

    assert identity_controller.edited_cache(window, source) is current
    assert _shown(window, source, "testMouse_snout", FLIP) == _channel_value(
        "conSpecific_snout", "x"
    )


def test_the_swap_lands_on_the_frame_on_screen_and_the_playhead_stays(
    qtbot, window, pose_source
) -> None:
    """The frame a person is looking at is the frame the swap starts on.

    And applying does not move them off it: the rebuild redraws the braid, and
    a redraw that re-selected a crossing and seeked to it would take the video
    somewhere they did not ask to go.
    """
    source = str(pose_source[0])
    panel = _braid(qtbot, window)
    assert panel._model is not None
    watching = float(panel._model.times[FLIP + 7])
    window.clock.seek(watching)

    window._apply_identity_swap()
    _settle(qtbot, window, source)

    assert window.identity_swaps.events_for(source)[0].index == FLIP + 7
    assert window.clock.state.t == pytest.approx(watching)
    assert _shown(window, source, "testMouse_snout", FLIP + 7) == _channel_value(
        "conSpecific_snout", "x"
    )
    assert _shown(window, source, "testMouse_snout", FLIP + 6) == _channel_value(
        "testMouse_snout", "x"
    )


def test_a_second_swap_while_watching_uses_where_the_video_now_is(
    qtbot, window, pose_source
) -> None:
    """Not the crossing a redraw happened to put in the list."""
    source = str(pose_source[0])
    panel = _braid(qtbot, window)
    assert panel._model is not None
    # Held now: a rebuild clears the braid while it runs, and the master times
    # of a source do not change when its identities are relabelled.
    times = panel._model.times

    window.clock.seek(float(times[20]))
    window._apply_identity_swap()
    _settle(qtbot, window, source)

    window.clock.seek(float(times[80]))
    window._apply_identity_swap()
    qtbot.waitUntil(lambda: window.identity_swaps.count_for(source) == 2, timeout=5000)

    assert sorted(e.index for e in window.identity_swaps.events_for(source)) == [20, 80]


# ── removing one accepted swap removes one (D-141) ───────────────────


def test_removing_one_accepted_swap_leaves_the_others(qtbot, window, pose_source) -> None:
    source = str(pose_source[0])
    first = SwapEvent(index=30, group=ANIMALS, lanes=INDIVIDUALS)
    second = SwapEvent(index=90, group=ANIMALS, lanes=INDIVIDUALS)
    for event in (first, second):
        identity_view.swap(window, source, event)
    _settle(qtbot, window, source)

    identity_view.undo(window, source, second)
    qtbot.waitUntil(lambda: window.identity_swaps.count_for(source) == 1, timeout=5000)

    assert window.identity_swaps.events_for(source) == (first,)


def test_removing_a_part_swap_does_not_take_the_whole_animal_with_it(
    qtbot, window, pose_source
) -> None:
    """The scope removed is the scope accepted, not the one the selector shows.

    Accept a whole-animal flip, then ask to remove a wrist-only one at the same
    frame: matching on frame and lanes alone found the whole-animal event and
    removed that, which reads as "it removed everything".
    """
    source = str(pose_source[0])
    whole = SwapEvent(index=40, group=ANIMALS, lanes=INDIVIDUALS)
    identity_view.swap(window, source, whole)
    _settle(qtbot, window, source)

    identity_view.undo(
        window,
        source,
        SwapEvent(index=40, group=ANIMALS, lanes=INDIVIDUALS, parts=("wrist",)),
    )

    assert window.identity_swaps.events_for(source) == (whole,)


def test_remove_all_clears_one_source_in_one_undo_step(qtbot, window, pose_source) -> None:
    source = str(pose_source[0])
    for index in (30, 60, 90):
        identity_view.swap(window, source, SwapEvent(index, ANIMALS, INDIVIDUALS))
    _settle(qtbot, window, source)
    assert window.identity_swaps.count_for(source) == 3

    identity_view.remove_all(window, source)
    qtbot.waitUntil(lambda: window.identity_swaps.count_for(source) == 0, timeout=5000)

    window.document.undo(window._mutations)
    qtbot.waitUntil(lambda: window.identity_swaps.count_for(source) == 3, timeout=5000)


def test_play_original_sits_with_the_other_video_controls(qtbot, window, pose_source) -> None:
    """One QAction drives the menu item and the checkbox (rule 15)."""
    source = str(pose_source[0])
    box = window.view_toolbar.original_tracker_box
    assert box.text() == "Play original"
    assert not box.isChecked()

    _accept(window, source)
    _settle(qtbot, window, source)
    edited = _shown(window, source, "testMouse_snout", FLIP)

    box.click()

    assert window._act_show_original_tracker.isChecked()
    assert window._show_original_tracker
    shown = _shown(window, source, "testMouse_snout", FLIP)
    assert shown != edited
    assert shown == _channel_value("testMouse_snout", "x")

    box.click()
    assert _shown(window, source, "testMouse_snout", FLIP) == edited


def test_remove_all_is_offered_with_its_count(qtbot, window, pose_source) -> None:
    source = str(pose_source[0])
    panel = _braid(qtbot, window)
    assert not panel._remove_all.isEnabled()

    for index in (30, 60):
        identity_view.swap(window, source, SwapEvent(index, ANIMALS, INDIVIDUALS))
    _settle(qtbot, window, source)
    qtbot.waitUntil(lambda: panel._remove_all.isEnabled(), timeout=5000)

    assert "2" in panel._remove_all.text()


def test_applying_twice_on_the_same_frame_is_not_two_undo_steps(qtbot, window, pose_source) -> None:
    """A no-op does not deserve a place in the undo history."""
    source = str(pose_source[0])
    panel = _braid(qtbot, window)
    assert panel._model is not None
    window.clock.seek(float(panel._model.times[FLIP]))

    window._apply_identity_swap()
    _settle(qtbot, window, source)
    label = window.document.undo_label()

    window._apply_identity_swap()

    assert window.identity_swaps.count_for(source) == 1
    assert window.document.undo_label() == label


def test_apply_stays_available_on_the_frame_after_a_swap(qtbot, window, pose_source) -> None:
    """Swapping at 7 must not grey the button out at 8."""
    source = str(pose_source[0])
    panel = _braid(qtbot, window)
    assert panel._model is not None
    times = panel._model.times

    window.clock.seek(float(times[FLIP]))
    window._apply_identity_swap()
    _settle(qtbot, window, source)
    qtbot.waitUntil(lambda: panel._model is not None, timeout=5000)

    assert panel._apply.isEnabled()
    window.clock.seek(float(times[FLIP + 1]))
    window._apply_identity_swap()
    qtbot.waitUntil(lambda: window.identity_swaps.count_for(source) == 2, timeout=5000)

    assert sorted(e.index for e in window.identity_swaps.events_for(source)) == [FLIP, FLIP + 1]


# ── removing acts where the video is (the mirror of applying) ─────────


def test_remove_reverses_the_swap_in_force_at_the_playhead(qtbot, window, pose_source) -> None:
    source = str(pose_source[0])
    panel = _braid(qtbot, window)
    assert panel._model is not None
    times = panel._model.times
    for index in (20, 80):
        identity_view.swap(window, source, SwapEvent(index, ANIMALS, INDIVIDUALS))
    _settle(qtbot, window, source)

    window.clock.seek(float(times[90]))
    window._remove_identity_swap()
    qtbot.waitUntil(lambda: window.identity_swaps.count_for(source) == 1, timeout=5000)

    # The one at 80 was in force at frame 90; the earlier one is untouched.
    assert [e.index for e in window.identity_swaps.events_for(source)] == [20]


def test_remove_never_reaches_a_swap_later_than_the_playhead(qtbot, window, pose_source) -> None:
    """Standing at frame 30, Remove must not undo the crossing at 80."""
    source = str(pose_source[0])
    panel = _braid(qtbot, window)
    assert panel._model is not None
    times = panel._model.times
    for index in (20, 80):
        identity_view.swap(window, source, SwapEvent(index, ANIMALS, INDIVIDUALS))
    _settle(qtbot, window, source)

    window.clock.seek(float(times[30]))
    window._remove_identity_swap()
    qtbot.waitUntil(lambda: window.identity_swaps.count_for(source) == 1, timeout=5000)

    assert [e.index for e in window.identity_swaps.events_for(source)] == [80]


def test_apply_then_remove_on_one_frame_is_a_round_trip(qtbot, window, pose_source) -> None:
    """Which is all Remove has to be: the reverse of the swap just made."""
    source = str(pose_source[0])
    panel = _braid(qtbot, window)
    assert panel._model is not None
    raw = _shown(window, source, "testMouse_snout", FLIP)
    window.clock.seek(float(panel._model.times[FLIP]))

    window._apply_identity_swap()
    _settle(qtbot, window, source)
    assert _shown(window, source, "testMouse_snout", FLIP) != raw

    window._remove_identity_swap()
    qtbot.waitUntil(lambda: _shown(window, source, "testMouse_snout", FLIP) == raw, timeout=5000)
    assert window.identity_swaps.count_for(source) == 0


def test_remove_with_nothing_in_force_says_so(qtbot, window, pose_source) -> None:
    panel = _braid(qtbot, window)
    assert panel._model is not None
    window.clock.seek(float(panel._model.times[FLIP]))

    window._remove_identity_swap()

    assert "nothing to reverse" in window.notifications.message


# ── a way back for a panel that was detached or lost ─────────────────


def test_bring_panels_back_redocks_a_floating_panel(qtbot, window, pose_source) -> None:
    """A dock dragged onto a screen that is later unplugged is otherwise gone."""
    window._open_identity_panel()
    panel = window._identity_window
    panel.setFloating(True)
    panel.move(-20000, -20000)
    assert panel.isFloating()

    window._bring_panels_back()

    assert not panel.isFloating()
    assert not panel.isHidden()


def test_a_reopened_panel_is_never_left_off_every_screen(qtbot, window, pose_source) -> None:
    from PySide6.QtGui import QGuiApplication

    window._open_identity_panel()
    panel = window._identity_window
    panel.setFloating(True)
    panel.move(-20000, -20000)

    window._open_identity_panel()

    assert QGuiApplication.screenAt(panel.frameGeometry().center()) is not None


def test_bringing_panels_back_reopens_one_that_was_closed(qtbot, window, pose_source) -> None:
    window._open_identity_panel()
    panel = window._identity_window
    panel.close()
    assert panel.isHidden()

    window._bring_panels_back()

    assert not panel.isHidden()


def test_a_detached_panel_carries_its_own_way_back(qtbot, window, pose_source) -> None:
    """The button belongs on the panel, not on the window it left.

    A control on the main window is no use to somebody looking at the panel,
    and none at all when the panel is on another screen.
    """
    window._open_identity_panel()
    panel = window._identity_window
    bar = panel.title_bar

    assert bar._attach.text() == "Detach"

    panel.setFloating(True)
    assert bar._attach.text() == "Attach"
    assert "Attach this panel" in bar._attach.toolTip()

    bar._attach.click()

    assert not panel.isFloating()
    assert bar._attach.text() == "Detach"


def test_the_panel_title_bar_can_close_it(qtbot, window, pose_source) -> None:
    window._open_identity_panel()
    panel = window._identity_window
    close = [
        button
        for button in panel.title_bar.findChildren(type(panel.title_bar._attach))
        if button.text() == "Close"
    ]

    assert close, "a panel that can be detached must also be closable from itself"
    close[0].click()
    assert panel.isHidden()
