"""Exports are ordinary registered jobs, and report like everything else (D-107).

The four exports -- snapshot, data slice, video clip, A/B region statistics --
each kept their own ``dict[QThread, object]`` on the window, wired their own
``started``/``finished``/``error``, wrote the transport status line directly,
and announced the result in a raw ``QMessageBox``. Two of them raised a modal on
*success*, for work the user had already been told was running.

``tests/test_feedback_surface.py`` has the static guards -- no raw ``QThread``,
no ``QMessageBox`` outside ``ui/feedback/``. Those catch a regression in the
shape of the code. These catch a regression in what the user actually gets: the
job is registered so it can be listed and cancelled, and the outcome arrives on
the notification strip rather than in a box that has to be dismissed.

The workers are not run here. Each is a thread entry point with its own tests in
``test_engine_export.py``; what is under test is the wiring between the
controller, ``JobManager``, and the feedback surface, so the handlers are called
directly with the payloads the real signals carry.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.ui import recovery
from avialsync.ui.controllers import export_controller
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


# ── registration ─────────────────────────────────────────────────────


def test_a_data_export_is_a_registered_job(window: MainWindow, tmp_path: Path, qtbot) -> None:
    """It has to be in the registry to be listed, watched, and cancellable.

    Registration is asserted at the moment the job starts, before the worker
    can finish and drop out again -- with no readers there is nothing to write,
    so the worker is quick.
    """
    started: list[str] = []
    real_start = window._job_manager.start

    def recording_start(label, worker, configure=None):
        started.append(label)
        return real_start(label, worker, configure=configure)

    window._job_manager.start = recording_start  # type: ignore[method-assign]

    export_controller.start_data_export(window, 0.0, 1.0, tmp_path / "slice.csv")

    assert len(started) == 1, "the export did not go through JobManager"
    assert "slice.csv" in started[0], f"the job is unlabelled: {started[0]!r}"
    window._job_manager.shutdown()


def test_a_video_clip_export_is_a_registered_job(window: MainWindow, tmp_path: Path) -> None:
    started: list[str] = []
    real_start = window._job_manager.start

    def recording_start(label, worker, configure=None):
        started.append(label)
        return real_start(label, worker, configure=configure)

    window._job_manager.start = recording_start  # type: ignore[method-assign]

    export_controller.start_video_clip_export(
        window, [("cam1.mp4", 0.0, 1.0, tmp_path / "cam1_trim.mp4")]
    )

    assert len(started) == 1
    assert "clip" in started[0].lower()
    window._job_manager.shutdown()


# ── outcomes reach the strip, not a modal ────────────────────────────


def test_a_finished_data_export_reports_without_a_modal(window: MainWindow) -> None:
    """This was `QMessageBox.information` -- a modal on success."""
    export_controller.on_data_export_finished(window, "/data/slice.csv")

    assert "slice.csv" in window.notifications.message
    assert window.notifications.is_sticky is False, (
        "a success the user asked for should clear itself, not need dismissing"
    )


def test_a_finished_snapshot_reports_on_the_strip(window: MainWindow) -> None:
    """This reported only in the status line, so a background save said nothing."""
    export_controller.on_snapshot_finished(window, "/data/snapshot.png")

    assert "snapshot.png" in window.notifications.message


def test_a_complete_clip_export_reports_success(window: MainWindow) -> None:
    export_controller.on_video_clip_finished(window, 3, 3)

    assert "3" in window.notifications.message
    assert window.notifications.is_sticky is False


def test_a_partial_clip_export_stays_until_it_is_read(window: MainWindow) -> None:
    """ "Exported 2 of 3" is not a success, and must not fade like one."""
    export_controller.on_video_clip_finished(window, 2, 3)

    assert "2" in window.notifications.message and "3" in window.notifications.message
    assert window.notifications.is_sticky is True


# ── failures are presented, never dumped ─────────────────────────────


def test_an_export_failure_goes_through_the_presenter(window: MainWindow) -> None:
    """AGENTS rule 12: the raw text belongs behind Show details, not in the message.

    The old shape was ``QMessageBox.critical(window, "Export Error", error)``
    with the worker's string as the whole message.
    """
    raw = "OSError: [Errno 28] No space left on device: '/data/slice.csv'"

    export_controller.on_data_export_error(window, raw)

    assert window.notifications.is_sticky is True, "a failure must not fade"
    assert raw not in window.notifications.message, "the raw text leaked into the message"
    assert raw in window.notifications.details, "and it must still be reachable"
    assert "could not be written" in window.notifications.message.lower()


def test_a_snapshot_failure_names_what_the_user_was_doing(window: MainWindow) -> None:
    export_controller.on_snapshot_error(window, "PermissionError: denied")

    assert "snapshot" in window.notifications.message.lower()
    assert "PermissionError" in window.notifications.details


def test_a_clip_failure_is_presented(window: MainWindow) -> None:
    export_controller.on_video_clip_error(window, "ffmpeg: invalid argument")

    assert window.notifications.is_sticky is True
    assert "ffmpeg" in window.notifications.details


# ── preconditions report rather than raising a box ───────────────────


def test_exporting_a_slice_with_no_data_warns_without_asking_for_a_filename(
    window: MainWindow, monkeypatch
) -> None:
    """The action is greyed for this, but the command must still answer safely.

    A command palette entry, a stored shortcut, or a state change between the
    menu opening and the click can all reach it. It says what is missing
    instead of raising the "No Data" box it used to.
    """

    class _NoDialog:
        @staticmethod
        def getSaveFileName(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("a filename was asked for with nothing to export")

    monkeypatch.setattr(export_controller, "QFileDialog", _NoDialog)

    export_controller.export_data_slice(window)

    assert "sensor" in window.notifications.message.lower()


def test_exporting_a_clip_with_no_loop_says_which_keys_set_one(
    window: MainWindow, monkeypatch
) -> None:
    class _NoDialog:
        @staticmethod
        def getSaveFileName(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("a filename was asked for with no range marked")

    monkeypatch.setattr(export_controller, "QFileDialog", _NoDialog)
    window.video_grid._paths.append("cam1.mp4")
    window.transport._ab_in_t = None

    export_controller.export_video_clip(window)

    message = window.notifications.message
    assert "[" in message and "]" in message, f"say which keys mark a range: {message!r}"
