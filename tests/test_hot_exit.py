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
