"""The window always finishes closing, and the playhead keys always reach it.

Two reported defects, plus a third found while reproducing them:

1. **The window sometimes would not close.** ``closeEvent`` ran seven teardown
   steps in bare sequence. A raise in any of them skipped the rest — including
   ``video_grid.shutdown()``, whose libmpv event threads outlive their widgets
   and keep the process alive.
2. **Playhead keys stopped working after some operations.** Qt offers each key
   to the focused widget as a ``ShortcutOverride`` before running a window
   shortcut, and ``QLineEdit``/``QAbstractSpinBox`` accept that offer for Space,
   the arrows, Home and End.
3. **The final autosave wrote a session with no videos**, because it ran after
   the grid that holds them had already been cleared.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QLineEdit,
    QVBoxLayout,
)

from avialview.ui.main_window import MainWindow

_VIDEO = "tests/fixtures/videos/camera_1.mp4"


@pytest.fixture
def window(qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    return win


def _playhead_events(window: MainWindow) -> list[str]:
    """Record every command that actually reached the playhead."""
    seen: list[str] = []
    window.transport.play_toggled.connect(lambda _v: seen.append("play"))
    window.transport.frame_step_requested.connect(lambda _d: seen.append("step"))
    window.clock.subscribe(lambda _t: seen.append("seek"))
    return seen


def _press(app: QApplication, key: Qt.Key) -> None:
    """Send *key* the way real input does — to whatever currently has focus."""
    QTest.keyClick(app.focusWidget(), key)
    app.processEvents()


# ── Playhead keys ─────────────────────────────────────────────────────

PLAYHEAD_KEYS = [
    Qt.Key.Key_Space,
    Qt.Key.Key_Left,
    Qt.Key.Key_Right,
    Qt.Key.Key_Home,
    Qt.Key.Key_End,
]


@pytest.mark.parametrize("key", PLAYHEAD_KEYS)
def test_a_spin_box_does_not_swallow_the_playhead_keys(window, qapp, key) -> None:
    """One click into the sweep-length spin box used to disable playback control."""
    spin = window.findChildren(QDoubleSpinBox)[0]
    spin.setFocus(Qt.FocusReason.MouseFocusReason)
    qapp.processEvents()
    seen = _playhead_events(window)

    _press(qapp, key)

    assert seen, f"{key} never reached the playhead from a focused spin box"


@pytest.mark.parametrize("key", PLAYHEAD_KEYS)
def test_the_time_field_does_not_swallow_the_playhead_keys(window, qapp, key) -> None:
    """Merely holding focus is not an edit in progress."""
    window.transport._time_edit.setFocus(Qt.FocusReason.MouseFocusReason)
    window.transport._time_edit.setModified(False)
    qapp.processEvents()
    seen = _playhead_events(window)

    _press(qapp, key)

    assert seen, f"{key} never reached the playhead from the idle time field"


def test_a_half_typed_timecode_keeps_its_caret_keys(window, qapp) -> None:
    """Correcting a timecode mid-entry must still work."""
    edit = window.transport._time_edit
    edit.setFocus(Qt.FocusReason.MouseFocusReason)
    QTest.keyClicks(edit, "00:01:2")
    qapp.processEvents()
    seen = _playhead_events(window)

    _press(qapp, Qt.Key.Key_Left)

    assert not seen, "the caret keys belong to an edit in progress"


def test_space_is_never_taken_by_a_numeric_editor(window, qapp) -> None:
    """No timecode or number contains a space, so Space is always playback."""
    edit = window.transport._time_edit
    edit.setFocus(Qt.FocusReason.MouseFocusReason)
    QTest.keyClicks(edit, "00:01:2")
    qapp.processEvents()
    seen = _playhead_events(window)

    _press(qapp, Qt.Key.Key_Space)

    assert seen, "Space must reach the playhead even mid-edit"


def test_a_dialogs_own_editors_keep_their_keys(window, qapp, qtbot) -> None:
    """The reservation is scoped to the main window, never reaching into a dialog."""
    dialog = QDialog(window)
    layout = QVBoxLayout(dialog)
    field = QLineEdit(dialog)
    layout.addWidget(field)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    field.setFocus(Qt.FocusReason.MouseFocusReason)
    qapp.processEvents()
    seen = _playhead_events(window)

    _press(qapp, Qt.Key.Key_Left)

    assert not seen, "a dialog's editor owns its own keys"
    dialog.close()


# ── Closing ───────────────────────────────────────────────────────────


def test_the_final_autosave_still_sees_the_open_videos(window, tmp_path: Path) -> None:
    """The grid used to be torn down before the session state was built."""
    window.video_grid.add_pane(_VIDEO)
    session = tmp_path / "session.avv"
    window._session_path = session

    window.close()

    saved = json.loads(session.read_text())
    assert len(saved["videos"]) == 1, "closing wiped the session's video list"


def test_a_failing_teardown_step_does_not_skip_the_rest(window, monkeypatch) -> None:
    """A raise used to abandon every later step, stranding libmpv event threads."""
    monkeypatch.setattr(
        window._heartbeat, "stop", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    shut_down: list[str] = []
    monkeypatch.setattr(window.video_grid, "shutdown", lambda: shut_down.append("video_grid"))

    window.close()

    assert shut_down == ["video_grid"], "video teardown must run even after a failure"


def test_one_bad_pane_does_not_strand_the_others(window, monkeypatch) -> None:
    """Per-pane isolation: pane 0 failing must not leave pane 1 running.

    The real libmpv clients are terminated first and the panes replaced by
    stand-ins. Stubbing ``close`` on a live pane would leave its event thread
    running past the end of the test, which aborts the interpreter.
    """
    window.video_grid.add_pane(_VIDEO)
    window.video_grid.add_pane(_VIDEO)
    for pane in window.video_grid.panes:
        pane.close()

    closed: list[str] = []

    class _Pane:
        def __init__(self, name: str, fails: bool) -> None:
            self._name, self._fails = name, fails

        def close(self) -> bool:
            if self._fails:
                raise RuntimeError("GL context already gone")
            closed.append(self._name)
            return True

        def deleteLater(self) -> None:
            pass

    window.video_grid.panes = [_Pane("first", True), _Pane("second", False)]

    window.video_grid.shutdown()

    assert closed == ["second"], "a failing pane must not skip the ones after it"
    assert window.video_grid.panes == []


def test_closing_is_never_refused(window) -> None:
    """Whatever happens, the close event is accepted."""
    window.video_grid.add_pane(_VIDEO)

    window.close()

    assert window.isHidden()
