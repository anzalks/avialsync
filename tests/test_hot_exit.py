"""Hot exit: quitting never prompts and never loses work (WP-1 steps 7-8, D-089).

The defect these cover is specific and was silent. ``autosave()`` returned
early when ``_session_path`` was ``None``, so the two-minute autosave protected
only sessions that had already been saved manually. An untitled session -- four
cameras, tuned offsets, forty annotations -- was discarded on close with no
prompt and no trace.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.ui import recovery
from avialsync.ui.controllers import session_controller
from avialsync.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    """Keep every test off the real app-data location.

    Autouse and first: the window fixture's teardown closes the window, which
    writes a recovery snapshot. Without this redirect that write would land in
    the developer's own app-data directory and offer a restore on their next
    real launch.
    """
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def main_window(qapp: QApplication, qtbot) -> MainWindow:
    """Match the fixture in test_ui_main.py rather than sharing one.

    Per-file window fixtures are the existing convention here; hoisting this
    into conftest would change teardown ordering for a passing suite.
    """
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    # Qt may already have deleted it: pytest-qt runs processEvents()
    # after the call phase, which executes pending deleteLater()s.
    if isValid(win):
        win.close()


def _seed_workspace(window) -> None:
    """Give the window something worth losing."""
    window.annotation_store.add_point(1.0, "spike")


# ── the snapshot itself ──────────────────────────────────────────────


def test_write_and_read_round_trip(isolated_recovery_dir) -> None:
    state = {"videos": [{"path": "/data/cam1.mp4"}], "markers": []}
    assert recovery.write_recovery(state, None) is True

    snapshot = recovery.read_recovery()
    assert snapshot is not None
    assert snapshot.state == state
    assert snapshot.session_path is None
    assert snapshot.describes_untitled_session is True


def test_no_snapshot_reads_as_none(isolated_recovery_dir) -> None:
    assert recovery.read_recovery() is None
    assert recovery.pending_recovery() is None


def test_a_corrupt_snapshot_is_discarded_not_raised(isolated_recovery_dir) -> None:
    """A safety net that throws on the way up is worse than an absent one."""
    recovery.recovery_path().write_text("{not json at all", encoding="utf-8")
    assert recovery.read_recovery() is None
    assert not recovery.recovery_path().exists(), "the unusable file is cleared"


def test_a_truncated_write_leaves_the_previous_snapshot(isolated_recovery_dir, monkeypatch) -> None:
    recovery.write_recovery({"videos": ["good"]}, None)

    def _explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("json.dump", _explode)
    assert recovery.write_recovery({"videos": ["bad"]}, None) is False

    snapshot = recovery.read_recovery()
    assert snapshot is not None
    assert snapshot.state == {"videos": ["good"]}


def test_clear_removes_the_snapshot(isolated_recovery_dir) -> None:
    recovery.write_recovery({"videos": ["x"]}, None)
    recovery.clear_recovery()
    assert recovery.read_recovery() is None


def test_clear_on_a_missing_snapshot_is_harmless(isolated_recovery_dir) -> None:
    recovery.clear_recovery()  # must not raise


# ── what counts as recoverable ───────────────────────────────────────


def test_an_empty_state_is_not_worth_recovering() -> None:
    assert recovery.is_empty_state({"videos": [], "sensors": [], "markers": []}) is True
    assert recovery.is_empty_state({"videos": [{"path": "a"}]}) is False
    assert recovery.is_empty_state({}) is True


def test_a_snapshot_superseded_by_a_real_save_is_dropped(isolated_recovery_dir, tmp_path) -> None:
    """Offering a restore the user does not need trains them to dismiss it."""
    session_file = tmp_path / "session.avv"
    session_file.write_text("{}", encoding="utf-8")

    recovery.write_recovery({"videos": ["x"]}, str(session_file))
    # Make the session file clearly newer than the snapshot.
    stale = recovery.read_recovery()
    assert stale is not None
    import os

    future = stale.recovered_at + 3600
    os.utime(session_file, (future, future))

    assert recovery.pending_recovery() is None
    assert recovery.read_recovery() is None, "the superseded snapshot is cleared"


def test_a_snapshot_newer_than_its_save_is_offered(isolated_recovery_dir, tmp_path) -> None:
    import os

    session_file = tmp_path / "session.avv"
    session_file.write_text("{}", encoding="utf-8")
    os.utime(session_file, (1000.0, 1000.0))

    recovery.write_recovery({"videos": ["x"]}, str(session_file))
    assert recovery.pending_recovery() is not None


def test_an_untitled_snapshot_is_always_offered(isolated_recovery_dir) -> None:
    recovery.write_recovery({"videos": ["x"]}, None)
    pending = recovery.pending_recovery()
    assert pending is not None
    assert pending.describes_untitled_session is True


def test_a_snapshot_whose_session_file_vanished_is_offered(isolated_recovery_dir, tmp_path) -> None:
    recovery.write_recovery({"videos": ["x"]}, str(tmp_path / "gone.avv"))
    assert recovery.pending_recovery() is not None


# ── the controller wiring ────────────────────────────────────────────


def test_autosave_of_an_untitled_session_writes_recovery(main_window, isolated_recovery_dir):
    """The defect this whole feature exists for."""
    _seed_workspace(main_window)
    main_window._session_path = None

    session_controller.autosave(main_window)

    snapshot = recovery.read_recovery()
    assert snapshot is not None, "an untitled session must not be left unprotected"
    assert snapshot.session_path is None
    assert snapshot.state["markers"], "the annotation survived"


def test_closing_an_untitled_session_preserves_it(main_window, isolated_recovery_dir):
    _seed_workspace(main_window)
    main_window._session_path = None

    session_controller.autosave_before_close(main_window)

    snapshot = recovery.read_recovery()
    assert snapshot is not None
    assert snapshot.state["markers"]


def test_closing_an_empty_workspace_writes_nothing(main_window, isolated_recovery_dir):
    main_window._session_path = None
    session_controller.autosave_before_close(main_window)
    assert recovery.read_recovery() is None


def test_reset_then_quit_does_not_overwrite_good_work(main_window, isolated_recovery_dir):
    """The trap: a reset must clear the snapshot, never blank it out.

    Reset empties the workspace and sets ``_session_path`` to ``None``. If the
    close-time write then ran against that empty workspace it would replace a
    good snapshot with nothing -- the safety net causing exactly the loss it
    exists to prevent.
    """
    _seed_workspace(main_window)
    main_window._session_path = None
    session_controller.autosave(main_window)
    assert recovery.read_recovery() is not None

    session_controller.reset_session(main_window)
    assert recovery.read_recovery() is None, "a reset clears the snapshot outright"

    session_controller.autosave_before_close(main_window)
    assert recovery.read_recovery() is None, "an emptied workspace writes nothing"


def test_an_unserialisable_workspace_does_not_break_the_close(main_window, isolated_recovery_dir):
    """closeEvent must survive a workspace it cannot encode."""
    main_window._session_path = None
    main_window._sync_provenance.append(object())  # not a dataclass; to_dict raises

    session_controller.autosave_before_close(main_window)  # must not raise

    assert recovery.read_recovery() is None


def test_saving_clears_the_recovery_snapshot(main_window, isolated_recovery_dir, tmp_path):
    _seed_workspace(main_window)
    main_window._session_path = None
    session_controller.autosave(main_window)
    assert recovery.read_recovery() is not None

    main_window._session_path = tmp_path / "saved.avv"
    main_window._mark_session_saved()
    recovery.clear_recovery()

    assert recovery.read_recovery() is None
    assert main_window.document.is_dirty is False


# ── the title (WP-1 step 5) ──────────────────────────────────────────


def test_an_untitled_session_says_so(main_window):
    main_window._session_path = None
    main_window._update_window_title()
    assert main_window.windowTitle() == "Untitled[*] — AvialSync"


def test_the_title_names_the_open_session(main_window):
    main_window._session_path = Path("/tmp/experiment_4.avv")
    main_window._update_window_title()
    assert "experiment_4" in main_window.windowTitle()
    assert main_window.windowTitle().endswith("— AvialSync")


def test_the_modified_marker_follows_dirty_state(main_window):
    from avialsync.core.commands import AddMarkerCommand
    from avialsync.core.document import MarkerRecord

    main_window._update_window_title()
    assert main_window.isWindowModified() is False

    main_window.document.record(
        AddMarkerCommand(MarkerRecord(t_start=1.0, t_end=None, label="m", index=0))
    )
    assert main_window.isWindowModified() is True, "an edit marks the window modified"

    main_window._mark_session_saved()
    assert main_window.isWindowModified() is False


def test_a_long_drag_updates_the_title_at_most_twice(main_window):
    """A 200-step offset drag must not storm the title repaint (WP-1 step 6)."""
    from avialsync.core.commands import SetSourceMappingCommand

    main_window._update_window_title()
    updates: list[bool] = []
    main_window.document.observe_dirty(updates.append)

    previous = 0.0
    for step in range(200):
        after = (step + 1) * 0.01
        main_window.document.record(SetSourceMappingCommand("cam1", (previous, 0.0), (after, 0.0)))
        previous = after

    assert len(updates) <= 2, f"expected at most 2 title updates, got {len(updates)}"
    assert len(main_window.document) == 1, "the drag is one undo step"


# ── offering it back (the half that was missing) ──────────────────────


def test_a_fresh_launch_offers_unsaved_work(main_window, isolated_recovery_dir):
    """The snapshot was written on every quit and nothing ever offered it back.

    ``pending_recovery()`` implemented the "is this worth offering" rule from
    the day D-089 landed, but no caller in ``src/`` invoked it -- only this
    file did. Work was preserved on disk and unreachable from the interface,
    and because the payload nests the session under a ``state`` key, Open
    Session could not read it either.
    """
    recovery.write_recovery({"videos": [{"path": "/data/cam1.mp4"}]}, None)

    assert session_controller.offer_pending_recovery(main_window) is True
    strip = main_window.notifications
    assert strip.isVisible()
    assert strip.action_label == "Restore"
    assert strip.is_sticky, "an offer that fades before it is read is not an offer"


def test_nothing_pending_offers_nothing(main_window, isolated_recovery_dir):
    assert session_controller.offer_pending_recovery(main_window) is False
    assert main_window.notifications.isVisible() is False


def test_declining_the_offer_leaves_the_snapshot_alone(main_window, isolated_recovery_dir):
    """Dismiss is not discard.

    The snapshot is the only copy of that work. A stray click on Dismiss must
    not be what deletes it -- the next quit overwrites it in the ordinary way,
    so nothing accumulates by leaving it.
    """
    recovery.write_recovery({"videos": [{"path": "/data/cam1.mp4"}]}, None)
    session_controller.offer_pending_recovery(main_window)

    main_window.notifications.clear()

    assert recovery.read_recovery() is not None, "declining must not delete the work"
    assert main_window.notifications.isVisible() is False


def test_restoring_loads_the_work_and_marks_it_unsaved(main_window, isolated_recovery_dir):
    _seed_workspace(main_window)
    main_window._session_path = None
    session_controller.autosave(main_window)
    main_window.annotation_store.clear()

    session_controller.offer_pending_recovery(main_window)
    main_window.notifications.action_button.click()

    assert main_window.document.is_dirty, "restored work lives in no file yet"
    assert recovery.read_recovery() is None, "the snapshot is consumed by a restore"


def test_a_snapshot_that_cannot_be_decoded_is_reported_not_deleted(
    main_window, isolated_recovery_dir
):
    """Clearing before the restore succeeds would be the loss it guards against."""
    recovery.write_recovery({"videos": "not a list of entries"}, None)
    session_controller.offer_pending_recovery(main_window)

    main_window.notifications.action_button.click()

    assert recovery.read_recovery() is not None, "an undecodable snapshot is kept"
    assert "could not be restored" in main_window.notifications.message


def test_the_offer_names_when_the_work_is_from(main_window, isolated_recovery_dir):
    recovery.write_recovery({"videos": [{"path": "/data/cam1.mp4"}]}, None)
    session_controller.offer_pending_recovery(main_window)
    assert "Unsaved work from" in main_window.notifications.message


def test_a_message_without_an_action_does_not_inherit_the_last_one(
    main_window, isolated_recovery_dir
):
    """The button is one widget reused by every message posted to the strip.

    Since D-107 a later message no longer displaces the offer -- it queues
    behind it -- so the inheritance this guards against can only happen when
    the queued message is promoted. That is the moment to check.
    """
    recovery.write_recovery({"videos": [{"path": "/data/cam1.mp4"}]}, None)
    session_controller.offer_pending_recovery(main_window)
    assert main_window.notifications.action_button.isVisible()

    main_window.notifications.show_error("Something else failed")
    main_window.notifications.clear()

    assert main_window.notifications.message == "Something else failed"
    assert main_window.notifications.action_button.isVisible() is False
    assert main_window.notifications.action_label == ""


def test_a_later_failure_does_not_evict_the_offer(main_window, isolated_recovery_dir):
    """The offer is the only in-session route back to unsaved work (D-107).

    It is posted once, at startup, from a single call site. Before the strip
    queued, any plugin error or autoload notice landing behind it replaced it,
    and the work stayed on disk with nothing left in the interface pointing at
    it. Losing a *message* is a nuisance; losing this one is losing the work.
    """
    recovery.write_recovery({"videos": [{"path": "/data/cam1.mp4"}]}, None)
    session_controller.offer_pending_recovery(main_window)

    main_window.notifications.show_error("A plugin failed to load")
    main_window.notifications.show_success("Imported sensor.csv")

    assert main_window.notifications.action_label == "Restore"
    assert "Unsaved work from" in main_window.notifications.message
    assert main_window.notifications.pending_count == 2


def test_constructing_the_window_is_what_makes_the_offer(qapp, qtbot, isolated_recovery_dir):
    """The regression that matters: the function existing is not the fix.

    ``pending_recovery()`` was correct and tested from the day it landed. What
    was missing was any caller, so this asserts the wiring rather than the
    rule -- a window that comes up with unsaved work on disk must say so
    without anyone calling the controller by hand.
    """
    from shiboken6 import isValid

    recovery.write_recovery({"videos": [{"path": "/data/cam1.mp4"}]}, None)

    win = MainWindow()
    qtbot.addWidget(win)
    # Shown, because a child of a hidden parent reports itself hidden however
    # the strip was posted; the question here is whether anything posted it.
    win.show()
    try:
        assert win.notifications.isVisible(), "a fresh launch never mentioned the snapshot"
        assert win.notifications.action_label == "Restore"
    finally:
        if isValid(win):
            win.close()
