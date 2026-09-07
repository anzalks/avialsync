"""The Changes panel: one list of what a person did, and a way back to each.

Annotations had a table of their own and corrections had nothing; neither table
was clickable, so "go back and look at that again" meant scrubbing for it by
hand. This covers the panel that replaced both.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.point_edits import PointKey, PointMove
from avialsync.ui import recovery
from avialsync.ui.changes_panel import ChangeRow
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
    yield win
    if isValid(win):
        win.close()


def _pose_file(tmp_path: Path) -> Path:
    path = tmp_path / "eks.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scorer", "DLC", "DLC"])
        writer.writerow(["bodyparts", "nose", "nose"])
        writer.writerow(["coords", "x", "y"])
        for frame in range(4):
            writer.writerow([frame, 10.0 + frame, 20.0])
    return path


def _correct(window: MainWindow, pose: Path, index: int) -> PointKey:
    key = PointKey(str(pose), "nose", index)
    window.video_grid.point_moved.emit(PointMove(key=key, before=None, after=(99.0, 88.0)))
    return key


# ── what it lists ────────────────────────────────────────────────────


def test_an_empty_session_lists_nothing(window: MainWindow) -> None:
    assert window.changes_panel.rows == []


def test_flags_and_corrections_share_one_list(window: MainWindow, tmp_path: Path) -> None:
    """They are the same kind of thing: a human judgement over a recording."""
    from tests.test_fix_tracker import _register_pose_source

    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [0.0, 0.1, 0.2, 0.3], rate=10.0)
    window.annotation_store.add_point(0.25, label="stance")
    _correct(window, pose, 1)

    kinds = [row.kind for row in window.changes_panel.rows]

    assert set(kinds) == {"Flag", "Correction"}
    assert len(kinds) == 2


def test_the_list_is_in_time_order(window: MainWindow, tmp_path: Path) -> None:
    """A reviewer reads this the way the recording ran."""
    from tests.test_fix_tracker import _register_pose_source

    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [0.0, 0.1, 0.2, 0.3], rate=10.0)
    window.annotation_store.add_point(0.25, label="later")
    _correct(window, pose, 1)

    times = [row.t_master for row in window.changes_panel.rows]

    assert times == sorted(times)
    assert times[0] == pytest.approx(0.1), "the correction at sample 1 comes first"


def test_a_correction_row_names_the_part_and_the_frame(window: MainWindow, tmp_path: Path) -> None:
    """A row that says only "a point moved" sends the reader back to the video."""
    from tests.test_fix_tracker import _register_pose_source

    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [10.0, 10.1, 10.2, 10.3], rate=10.0)
    _correct(window, pose, 1)

    row = window.changes_panel.rows[0]

    assert "nose" in row.detail
    assert "frame 101" in row.detail, "the video frame, not the sample index"
    assert row.where == "eks.csv"


def test_a_correction_still_lists_before_its_source_has_loaded(window: MainWindow) -> None:
    """Otherwise the panel disagrees with the count the session reports."""
    window.point_edits.set(PointKey("/not/loaded.csv", "nose", 7), (1.0, 2.0))

    rows = window.changes_panel.rows

    assert len(rows) == 1
    assert rows[0].where == "loaded.csv"


def test_an_unplaced_change_has_no_time_rather_than_time_zero(window: MainWindow) -> None:
    """A fake time in a time-sorted column reads as a measurement, not a gap.

    The Messages panel keeps untimed records out of its table for the same
    reason; here the time is not absent but not yet known, so the row stays and
    says so.
    """
    window.point_edits.set(PointKey("/not/loaded.csv", "nose", 7), (1.0, 2.0))

    assert window.changes_panel.rows[0].t_master is None
    assert window.changes_panel._when(window.changes_panel.rows[0]) == "—"


def test_an_unplaced_change_sorts_after_everything_that_has_a_time(
    window: MainWindow,
) -> None:
    window.annotation_store.add_point(5.0, label="late")
    window.point_edits.set(PointKey("/not/loaded.csv", "nose", 7), (1.0, 2.0))

    assert [row.t_master for row in window.changes_panel.rows] == [5.0, None]


def test_revisiting_an_unplaced_change_does_not_seek_to_the_start(
    window: MainWindow,
) -> None:
    """Seeking to zero would move the playhead somewhere the user did not ask."""
    window.clock.set_bounds(0.0, 10.0)
    window.player.seek(4.0, exact=True)
    window.point_edits.set(PointKey("/not/loaded.csv", "nose", 7), (1.0, 2.0))

    window._revisit_change(window.changes_panel.rows[0])

    assert window.clock.state.t == pytest.approx(4.0)


def test_an_empty_panel_says_so(window: MainWindow) -> None:
    """The Messages tab beside it does the same rather than showing a blank grid."""
    assert window.changes_panel._empty.isVisible() or not window.changes_panel.isVisible()

    window.annotation_store.add_point(1.0, label="stance")

    assert not window.changes_panel._empty.isVisibleTo(window.changes_panel)


def test_the_list_follows_the_stores(window: MainWindow, tmp_path: Path) -> None:
    window.annotation_store.add_point(1.0, label="stance")
    assert len(window.changes_panel.rows) == 1

    window.annotation_store.clear()
    assert window.changes_panel.rows == []


# ── going back to one ────────────────────────────────────────────────


def test_revisiting_a_correction_seeks_selects_and_points_at_it(
    window: MainWindow, tmp_path: Path
) -> None:
    """Landing on the right frame with nine markers on screen is half an answer."""
    from tests.test_fix_tracker import _register_pose_source

    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [0.0, 0.1, 0.2, 0.3], rate=10.0)
    key = _correct(window, pose, 2)
    row = window.changes_panel.rows[0]
    # The clock clamps a seek to the loaded timeline, and no media is open here.
    window.clock.set_bounds(0.0, 10.0)
    # `_select_video` only records a camera that has a pane, and opening real
    # media for this would test the decoder rather than the navigation.
    selected: list[str] = []
    window._select_video = selected.append  # type: ignore[method-assign]

    window._revisit_change(row)

    assert window.clock.state.t == pytest.approx(0.2)
    assert selected == ["cam.mp4"]
    assert row.point == key
    assert all(pane.paint_canvas.highlighted_point == key for pane in window.video_grid.panes)


def test_the_highlight_clears_itself(window: MainWindow, tmp_path: Path) -> None:
    """A ring that never goes away reads as a state the correction is in."""
    from tests.test_fix_tracker import _register_pose_source

    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [0.0, 0.1, 0.2, 0.3], rate=10.0)
    _correct(window, pose, 2)

    window._revisit_change(window.changes_panel.rows[0])
    assert window._highlight_timer.isActive()

    window._clear_point_highlight()
    assert all(pane.paint_canvas.highlighted_point is None for pane in window.video_grid.panes)


def test_revisiting_an_annotation_needs_no_point(window: MainWindow) -> None:
    window.annotation_store.add_point(1.5, label="stance")
    window.clock.set_bounds(0.0, 10.0)

    window._revisit_change(window.changes_panel.rows[0])

    assert window.clock.state.t == pytest.approx(1.5)


def test_a_row_that_is_not_a_change_is_ignored(window: MainWindow) -> None:
    window.clock.set_bounds(0.0, 10.0)

    window._revisit_change(object())
    window._revisit_change(ChangeRow(kind="Flag", t_master=2.0, where="", detail=""))

    assert window.clock.state.t == pytest.approx(2.0)


# ── removing one ─────────────────────────────────────────────────────


def test_removing_a_correction_restores_the_prediction_undoably(
    window: MainWindow, tmp_path: Path
) -> None:
    """Deleting is a mutation like any other and belongs on the undo stack."""
    from tests.test_fix_tracker import _register_pose_source

    pose = _pose_file(tmp_path)
    _register_pose_source(window, str(pose), [0.0, 0.1, 0.2, 0.3], rate=10.0)
    key = _correct(window, pose, 1)

    window._restore_predicted_point(key)

    assert window.point_edits.get(key) is None
    assert window.document.undo_label() == "Restore predicted nose at frame 1"

    window.document.undo(window._mutations)
    assert window.point_edits.get(key) == (99.0, 88.0)


def test_removing_a_correction_that_is_not_there_does_nothing(window: MainWindow) -> None:
    window._restore_predicted_point(PointKey("/nowhere.csv", "nose", 1))

    assert window.document.can_undo() is False
