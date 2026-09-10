"""A command is available exactly when it can do something (D-107).

Of the forty-six actions ``MainWindow`` owns, two called ``setEnabled`` before
this: a menu placeholder and a locked overlay. Everything else stayed live
whatever was loaded, and answered a click it could not honour with a modal
saying so -- "Load sensor data before exporting", "No videos are loaded",
"Please set an A/B loop first". That is the state told *after* the gesture.

These tests exist because an enablement rule is easy to get subtly wrong in the
direction nobody notices: a precondition that is never true disables a command
forever, and the only symptom is a permanently greyed menu item that everyone
assumes is meant to be greyed. So each one drives the precondition from both
sides -- unavailable, then available -- rather than asserting the greyed state
alone.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.ui import recovery
from avialsync.ui.main_window import MainWindow


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
    if isValid(win):
        win.close()


def _action(window: MainWindow, text: str):
    """The registered action whose text is *text*, by the label a user reads."""
    for action, _precondition, _reason, _tip in window._action_preconditions:
        if action.text() == text:
            return action
    raise AssertionError(
        f"no action named {text!r}; registered: "
        f"{sorted(a.text() for a, _p, _r, _t in window._action_preconditions)}"
    )


# ── the registry itself ──────────────────────────────────────────────


def test_every_precondition_can_be_answered(window: MainWindow) -> None:
    """A precondition that raises would silently disable its command forever.

    ``_refresh_action_availability`` swallows ``AttributeError`` and
    ``RuntimeError`` so a half-torn-down pane cannot crash a refresh, which is
    right -- and which also means a precondition reaching for an attribute that
    does not exist fails closed and invisibly. This calls each one directly,
    outside that guard, so a typo in a lambda is a test failure rather than a
    greyed menu item nobody can explain.
    """
    for action, precondition, _reason, _tip in window._action_preconditions:
        result = precondition()
        assert isinstance(result, bool), (
            f"{action.text()!r}'s precondition returned {result!r}, not a bool"
        )


def test_every_registered_action_offers_a_reason(window: MainWindow) -> None:
    """Greying alone moves the dead end earlier; it does not remove it."""
    for action, _precondition, reason, _tip in window._action_preconditions:
        assert reason.strip(), f"{action.text()!r} greys out without saying why"


def test_an_empty_window_disables_what_needs_a_recording(window: MainWindow) -> None:
    """The application starts empty, so most of this starts unavailable."""
    for name in (
        "Save Session…",
        "Export Snapshot…",
        "Export Data Slice…",
        "Export Trimmed Video Clip…",
        "Generate Proxy…",
        "Export Changes…",
        "Synchronize TTL / events…",
    ):
        assert _action(window, name).isEnabled() is False, f"{name} claims it can run"


def test_an_unavailable_action_says_why_in_its_tooltip(window: MainWindow) -> None:
    action = _action(window, "Export Data Slice…")
    assert action.isEnabled() is False
    assert "sensor" in action.toolTip().lower(), action.toolTip()


# ── each precondition, from both sides ───────────────────────────────


def test_a_loaded_channel_enables_the_data_slice(window: MainWindow) -> None:
    action = _action(window, "Export Data Slice…")
    assert action.isEnabled() is False

    window.plot_pane.channels.append(object())
    window._refresh_action_availability()

    assert action.isEnabled() is True


def test_the_clip_export_needs_both_a_video_and_a_loop(window: MainWindow) -> None:
    """Two conditions, so the test has to fail the way each one fails."""
    action = _action(window, "Export Trimmed Video Clip…")

    window.video_grid._paths.append("cam1.mp4")
    window._refresh_action_availability()
    assert action.isEnabled() is False, "a video alone is not a range to cut"

    window.transport._ab_in_t = 1.0
    window._refresh_action_availability()
    assert action.isEnabled() is True


def test_a_video_enables_the_proxy_builder(window: MainWindow) -> None:
    action = _action(window, "Generate Proxy…")
    assert action.isEnabled() is False

    window.video_grid._paths.append("cam1.mp4")
    window._refresh_action_availability()

    assert action.isEnabled() is True


def test_a_marker_enables_the_changes_export(window: MainWindow) -> None:
    """The store's own signal drives the refresh, so this does not call it."""
    action = _action(window, "Export Changes…")
    assert action.isEnabled() is False

    window.annotation_store.add_point(1.0, "spike")

    assert action.isEnabled() is True, "adding a marker must refresh availability"


def test_alignment_needs_evidence_on_both_sides(window: MainWindow) -> None:
    action = _action(window, "Synchronize TTL / events…")

    window.plot_pane.channels.append(object())
    window._refresh_action_availability()
    assert action.isEnabled() is False, "a reference with no target is not evidence"

    window._video_frame_times["cam1.mp4"] = [0.0, 0.1, 0.2]
    window._refresh_action_availability()
    assert action.isEnabled() is True


# ── the tooltip is restored, not overwritten ─────────────────────────


def test_becoming_available_restores_the_original_tooltip(window: MainWindow) -> None:
    """The reason is borrowed while greyed, never kept.

    ``Synchronize TTL / events…`` is the one with a tooltip of its own, so it is
    the one that proves the reason does not permanently replace it.
    """
    action = _action(window, "Synchronize TTL / events…")
    assert "load" in action.toolTip().lower(), "greyed, so it should be explaining itself"

    window.plot_pane.channels.append(object())
    window._video_frame_times["cam1.mp4"] = [0.0, 0.1, 0.2]
    window._refresh_action_availability()

    assert action.isEnabled() is True
    assert action.toolTip() == "Fit an offset from events both recordings share"


# ── availability is refreshed where state changes ────────────────────


def test_opening_a_menu_refreshes_availability(window: MainWindow) -> None:
    """A shortcut or the palette can reach a command without opening its menu.

    The state-change hooks are what keep those honest; this covers the belt to
    their braces -- the menu re-asking at the moment it is about to be read.
    """
    from PySide6.QtWidgets import QMenu

    action = _action(window, "Generate Proxy…")
    window.video_grid._paths.append("cam1.mp4")
    assert action.isEnabled() is False, "nothing has told the window yet"

    # The menu is taken from the action rather than found by title. macOS moves
    # actions carrying a `MenuRole` into the application menu, and a title match
    # is the kind of thing that passes on the machine it was written on and
    # raises StopIteration on someone else's.
    menus = [obj for obj in action.associatedObjects() if isinstance(obj, QMenu)]
    assert menus, "the action is not in a menu, so nothing would refresh it"
    for menu in menus:
        menu.aboutToShow.emit()

    assert action.isEnabled() is True


def test_a_source_change_refreshes_availability(window: MainWindow) -> None:
    """`_refresh_empty_state` is the hook every load and unload already runs."""
    action = _action(window, "Export Snapshot…")
    window.video_grid._paths.append("cam1.mp4")

    window._refresh_empty_state()

    assert action.isEnabled() is True
