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
    """A pose file on disk, and the imported cache beside it."""
    pose = tmp_path / "twomice_DLC.csv"
    pose.write_text("scorer,DLC\nindividuals,testMouse\n", encoding="utf-8")

    cache = tmp_path / "twomice_DLC.csv.avialcache"
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
    assert sensor.identity_count.text() == "⇄ 1"
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
    assert "more than one identity" in empty._act_fix_identities.toolTip()
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
    cache = tmp_path / "crossing_DLC.csv.avialcache"
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
