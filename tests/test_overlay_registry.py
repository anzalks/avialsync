"""Law 2: nothing is drawn over video that the user cannot turn off (D-090).

The conformance test here is :func:`test_the_registry_matches_what_is_drawn`.
It enumerates the registry against a hardcoded expectation, so adding an overlay
without registering it fails CI rather than review -- which is the whole point.
Before this existed, ``PaintCanvas`` had two visibility methods that no
production code called, and the camera name and timecode had no switch at all.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.session import SessionState
from avialsync.ui import recovery
from avialsync.ui.main_window import MainWindow
from avialsync.ui.overlay_registry import OVERLAY_LAYERS, OverlayState, layer_for

#: What the panes actually draw. Kept here, apart from the registry, so the two
#: have to be changed together and a new overlay cannot be added silently.
EXPECTED_INVENTORY = {
    "tracking.points",
    "tracking.point_labels",
    "tracking.legend",
    "camera.name",
    "camera.osd",
    "camera.no_footage",
}


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    # Qt may already have deleted it: pytest-qt runs processEvents()
    # after the call phase, which executes pending deleteLater()s.
    if isValid(win):
        win.close()


# ── conformance ──────────────────────────────────────────────────────


def test_the_registry_matches_what_is_drawn() -> None:
    """Adding an overlay without registering it must fail here."""
    registered = {layer.overlay_id for layer in OVERLAY_LAYERS}
    assert registered == EXPECTED_INVENTORY


def test_every_layer_is_fully_described() -> None:
    for layer in OVERLAY_LAYERS:
        assert layer.label, f"{layer.overlay_id} has no label"
        assert layer.group, f"{layer.overlay_id} has no group"
        assert layer.description, f"{layer.overlay_id} has no tooltip"


def test_overlay_ids_are_unique() -> None:
    ids = [layer.overlay_id for layer in OVERLAY_LAYERS]
    assert len(ids) == len(set(ids))


def test_every_layer_has_a_menu_entry(window: MainWindow) -> None:
    """The menu is generated, so this holds by construction -- and must keep holding."""
    assert set(window._overlay_actions) == EXPECTED_INVENTORY


# ── the state model ──────────────────────────────────────────────────


def test_defaults_come_from_the_registry() -> None:
    state = OverlayState()
    for layer in OVERLAY_LAYERS:
        assert state.is_visible(layer.overlay_id) is layer.default_visible


def test_body_part_names_default_off() -> None:
    """Nine tracked points' names cover the animal in the reference session."""
    assert layer_for("tracking.point_labels").default_visible is False


def test_a_global_change_applies_everywhere() -> None:
    state = OverlayState()
    assert state.set_visible("tracking.points", False) is True
    assert state.is_visible("tracking.points") is False
    assert state.is_visible("tracking.points", "/tmp/cam1.mp4") is False


def test_a_per_camera_override_beats_the_global(tmp_path) -> None:
    state = OverlayState()
    state.set_visible("tracking.points", False)
    state.set_visible("tracking.points", True, camera="/tmp/cam1.mp4")

    assert state.is_visible("tracking.points", "/tmp/cam1.mp4") is True
    assert state.is_visible("tracking.points", "/tmp/cam2.mp4") is False, "others untouched"


def test_clearing_an_override_follows_the_global_again() -> None:
    state = OverlayState()
    state.set_visible("tracking.points", False)
    state.set_visible("tracking.points", True, camera="/tmp/cam1.mp4")
    state.clear_override("tracking.points", "/tmp/cam1.mp4")
    assert state.is_visible("tracking.points", "/tmp/cam1.mp4") is False


def test_setting_the_same_value_reports_no_change() -> None:
    state = OverlayState()
    assert state.set_visible("tracking.points", True) is False


def test_an_unknown_layer_is_refused() -> None:
    assert OverlayState().set_visible("not.a.layer", False) is False


def test_forgetting_a_camera_drops_its_overrides() -> None:
    state = OverlayState()
    state.set_visible("tracking.points", False, camera="/tmp/cam1.mp4")
    state.forget_camera("/tmp/cam1.mp4")
    assert state.has_override("tracking.points", "/tmp/cam1.mp4") is False


# ── the locked layer (D-010) ─────────────────────────────────────────


def test_the_no_footage_placeholder_cannot_be_hidden() -> None:
    """Hiding it would let a blank pane be mistaken for black footage."""
    state = OverlayState()
    assert state.set_visible("camera.no_footage", False) is False
    assert state.is_visible("camera.no_footage") is True


def test_the_locked_layer_is_registered_and_shown_greyed(window: MainWindow) -> None:
    """Registered, not omitted: the exception stays visible, not folklore."""
    action = window._overlay_actions["camera.no_footage"]
    assert action.isEnabled() is False
    assert action.toolTip(), "the reason it is locked must be readable"


def test_hide_all_leaves_the_locked_layer_alone(window: MainWindow) -> None:
    window._set_all_overlays(False)
    assert window.overlay_state.is_visible("camera.no_footage") is True
    assert window.overlay_state.is_visible("tracking.points") is False


# ── persistence (schema v7) ──────────────────────────────────────────


def test_only_differences_from_default_are_written() -> None:
    """So a later change of default still reaches sessions with no preference."""
    state = OverlayState()
    assert state.to_dict() == {}

    state.set_visible("tracking.points", False)
    assert state.to_dict() == {"global": {"tracking.points": False}}


def test_visibility_round_trips_through_the_session() -> None:
    state = OverlayState()
    state.set_visible("tracking.points", False)
    state.set_visible("camera.osd", False, camera="/tmp/cam1.mp4")
    payload = state.to_dict()

    restored = OverlayState()
    restored.load(payload)
    assert restored.is_visible("tracking.points") is False
    assert restored.is_visible("camera.osd", "/tmp/cam1.mp4") is False
    assert restored.is_visible("camera.osd", "/tmp/cam2.mp4") is True


def test_an_unknown_layer_in_a_session_is_skipped() -> None:
    """A session written with a plugin overlay must still open without it."""
    state = OverlayState()
    state.load({"global": {"plugin.something": False, "tracking.points": False}})
    assert state.is_visible("tracking.points") is False
    assert layer_for("plugin.something") is None


def test_loading_resets_anything_the_payload_omits() -> None:
    state = OverlayState()
    state.set_visible("tracking.points", False)
    state.load({})
    assert state.is_visible("tracking.points") is True


def test_a_v6_session_loads_with_default_overlays() -> None:
    """The migration test: a pre-v7 file renders exactly as it did before."""
    v6 = {"version": 6, "videos": [], "sensors": [], "markers": []}
    state = SessionState.from_dict(v6)
    assert state.overlays == {}

    overlays = OverlayState()
    overlays.load(state.overlays)
    for layer in OVERLAY_LAYERS:
        assert overlays.is_visible(layer.overlay_id) is layer.default_visible


def test_the_session_writes_version_7() -> None:
    assert SessionState().to_dict()["version"] == 7


# ── the window wiring ────────────────────────────────────────────────


def test_toggling_a_layer_is_undoable(window: MainWindow) -> None:
    window._on_overlay_toggled("tracking.points", False)
    assert window.overlay_state.is_visible("tracking.points") is False
    assert window.document.undo_label() == "Hide overlay Tracking points"

    window.document.undo(window._mutations)
    assert window.overlay_state.is_visible("tracking.points") is True


def test_a_per_camera_toggle_is_undoable(window: MainWindow) -> None:
    window._on_overlay_toggled("camera.osd", False, camera="/tmp/cam1.mp4")
    assert window.overlay_state.is_visible("camera.osd", "/tmp/cam1.mp4") is False

    window.document.undo(window._mutations)
    assert window.overlay_state.is_visible("camera.osd", "/tmp/cam1.mp4") is True


def test_the_menu_check_state_follows_an_undo(window: MainWindow) -> None:
    """A checkbox left ticked after undo would lie about what is drawn."""
    action = window._overlay_actions["tracking.points"]
    window._on_overlay_toggled("tracking.points", False)
    window._apply_overlay_state()
    assert action.isChecked() is False

    window.document.undo(window._mutations)
    assert action.isChecked() is True
