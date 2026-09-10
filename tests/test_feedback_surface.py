"""Long work is never modal (WP-5, D-091).

The defect: a 1 GB CSV import -- which the performance budget allows sixty
seconds -- ran behind a modal ``QProgressDialog``. The work was always on a
worker, so the model was already right; the modality was gratuitous, and it
made the whole window unusable for a minute.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.ui import recovery
from avialsync.ui.feedback.activity_bar import ActivityBar, _format_duration
from avialsync.ui.feedback.jobs_panel import JobsPanel
from avialsync.ui.feedback.notifications import NotificationStrip
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
    # Qt may already have deleted it: pytest-qt runs processEvents()
    # after the call phase, which executes pending deleteLater()s.
    if isValid(win):
        win.close()


# ── the conformance check ────────────────────────────────────────────


def test_no_modal_progress_dialog_remains() -> None:
    """QProgressDialog is banned from src/ (D-091, AGENTS rule 11)."""
    from pathlib import Path

    offenders = []
    for path in Path("src/avialsync").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if "QProgressDialog" not in line:
                continue
            # Prose explaining why it is gone is not a use of it.
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("``") or "``" in line:
                continue
            offenders.append(f"{path}:{number}")

    assert offenders == [], f"modal progress is banned: {offenders}"


#: The one package allowed to build a dialog that interrupts. Everything else
#: reports through ``ui/feedback/``'s activity bar, notification strip, jobs
#: panel, or the typed error presenter.
_DIALOG_PACKAGE = "src/avialsync/ui/feedback"


def _code_lines(path) -> list[tuple[int, str]]:
    """Lines of *path* with comments and reStructuredText prose dropped.

    A rule is allowed to be *explained* in the file that no longer breaks it;
    the guards below would otherwise be unfixable, since the fix has to name
    the thing it removed.
    """
    lines = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("``") or "``" in line:
            continue
        lines.append((number, line))
    return lines


def test_no_message_box_outside_the_feedback_package() -> None:
    """``QMessageBox`` is banned from src/ outside ui/feedback/ (D-107).

    BLUEPRINT.md has listed this as a Phase 7 exit criterion since the phase was
    written -- "no ``QProgressDialog`` and no ``QMessageBox`` outside the
    presenter" -- but only the first half was ever enforced by a test, and the
    second half drifted to nineteen call sites across five modules while the
    suite stayed green. Four of them announced *success* in a modal.

    The boundary is the package, not the presenter function: ``ui/feedback/``
    owns the error presenter, the notification strip, and the one scrolling
    text dialog for content the user explicitly asked to see. A sixth dialect
    added anywhere else fails here.
    """
    from pathlib import Path

    offenders = []
    for path in Path("src/avialsync").rglob("*.py"):
        if _DIALOG_PACKAGE in path.as_posix():
            continue
        for number, line in _code_lines(path):
            if "QMessageBox" in line:
                offenders.append(f"{path}:{number}")

    assert offenders == [], (
        f"outcomes are reported through ui/feedback/, never a bare message box: {offenders}"
    )


#: Files allowed to construct a ``QThread`` directly, and why. Every other
#: background job goes through ``MainWindow._run_job`` -> ``JobManager``, which
#: is what gives it a name in the Tasks panel, a stall watchdog, and an orderly
#: abandonment at shutdown.
_UNMANAGED_THREAD_FILES = {
    # Not a job: one decode thread per video pane, created with the pane and
    # living as long as it. It has no completion to report and is stopped by
    # `VideoGrid.shutdown()`, whose ordering the D-062 notes in that file pin.
    "src/avialsync/ui/video_pane.py",
    # Owned by a modal the user explicitly opened, which is its own progress
    # and cancel surface (AGENTS rule 11 permits exactly this). Neither can
    # outlive its dialog, so neither can strand the window.
    "src/avialsync/ui/sync_wizard.py",
    "src/avialsync/demo.py",
    # JobManager is where the managed ones are created.
    "src/avialsync/ui/job_manager.py",
}


def test_every_background_job_is_registered() -> None:
    """A ``QThread`` in src/ is either registered or on the stated list (D-107).

    ``ui/job_manager.py`` has always said registering there is "the only
    supported way to start background work in this application". It was not:
    the four exports, the CSV import, the proxy builder, and the video probes
    each kept their own ``dict[QThread, object]``, so the Tasks panel showed
    four of the nine things the application could be doing, cancel reached two
    of them, and the stall watchdog saw none of the rest.

    This is the test that makes the docstring true. Adding a raw ``QThread``
    now costs an entry here with a reason, which is the point -- the exceptions
    are real, and they should be arguable rather than accidental.
    """
    from pathlib import Path

    offenders = []
    for path in Path("src/avialsync").rglob("*.py"):
        if path.as_posix() in _UNMANAGED_THREAD_FILES:
            continue
        for number, line in _code_lines(path):
            if "QThread(" in line:
                offenders.append(f"{path}:{number}")

    assert offenders == [], (
        "start background work with MainWindow._run_job, or add the file to "
        f"_UNMANAGED_THREAD_FILES with a reason: {offenders}"
    )


# ── the activity bar ─────────────────────────────────────────────────


def test_the_bar_is_hidden_until_something_runs(qapp: QApplication, qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)
    assert bar.isVisible() is False


def test_beginning_an_activity_shows_it(qapp: QApplication, qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)
    bar.show()
    bar.begin("Importing sensor.csv")
    assert bar.description == "Importing sensor.csv"
    assert bar.percent == 0


def test_progress_reaches_the_bar(qapp: QApplication, qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)
    bar.begin("Importing")
    bar.set_progress(100)
    assert bar.percent == 100


def test_ending_hides_it_again(qapp: QApplication, qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)
    bar.show()
    bar.begin("Importing")
    bar.end()
    assert bar.isVisible() is False


def test_no_estimate_before_there_is_evidence(qapp: QApplication, qtbot) -> None:
    """An estimate that swings wildly teaches the user to ignore it."""
    bar = ActivityBar()
    qtbot.addWidget(bar)
    bar.begin("Importing")
    bar.set_progress(1)
    assert "left" not in bar.eta_text


def test_cancel_is_offered_and_emitted(qapp: QApplication, qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)
    with qtbot.waitSignal(bar.cancel_requested, timeout=1000):
        bar._cancel.click()


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.4, "under a second"), (12, "12 s"), (90, "1 min 30 s"), (3700, "1 h 01 min")],
)
def test_durations_read_naturally(seconds: float, expected: str) -> None:
    assert _format_duration(seconds) == expected


# ── notifications ────────────────────────────────────────────────────


def test_success_dismisses_itself(qapp: QApplication, qtbot) -> None:
    strip = NotificationStrip()
    qtbot.addWidget(strip)
    strip.show_success("Imported sensor.csv")
    assert strip.message == "Imported sensor.csv"
    assert strip.is_sticky is False, "a success the user asked for should not linger"


def test_failure_stays_until_dismissed(qapp: QApplication, qtbot) -> None:
    """An error that fades before it is read is worse than one that interrupts."""
    strip = NotificationStrip()
    qtbot.addWidget(strip)
    strip.show()
    strip.show_error("Could not import sensor.csv", details="OSError: no such file")
    assert strip.is_sticky is True


def test_details_are_behind_a_button(qapp: QApplication, qtbot) -> None:
    """Raw text belongs behind "Show details", not in the message (AGENTS rule 12)."""
    strip = NotificationStrip()
    qtbot.addWidget(strip)
    strip.show_error("Could not import sensor.csv", details="Traceback ...")
    assert "Traceback" not in strip.message
    assert strip._details_button.isVisible() or strip.details == "Traceback ..."


def test_details_are_emitted_on_request(qapp: QApplication, qtbot) -> None:
    strip = NotificationStrip()
    qtbot.addWidget(strip)
    strip.show_error("Failed", details="the reason")
    with qtbot.waitSignal(strip.details_requested, timeout=1000) as blocker:
        strip._details_button.click()
    assert blocker.args == ["the reason"]


def test_a_message_with_no_details_offers_no_button(qapp: QApplication, qtbot) -> None:
    strip = NotificationStrip()
    qtbot.addWidget(strip)
    strip.show()
    strip.show_warning("Exported 3 of 4 clips")
    assert strip._details_button.isVisible() is False


def test_dismissing_clears_it(qapp: QApplication, qtbot) -> None:
    strip = NotificationStrip()
    qtbot.addWidget(strip)
    strip.show()
    strip.show_error("Failed")
    strip.clear()
    assert strip.isVisible() is False


# ── the jobs panel ───────────────────────────────────────────────────


def test_running_jobs_are_listed(qapp: QApplication, qtbot) -> None:
    panel = JobsPanel()
    qtbot.addWidget(panel)
    panel.refresh([("Importing sensor.csv", "running", 3.2)])
    assert panel.row_count == 1


def test_finished_jobs_are_kept_as_history(qapp: QApplication, qtbot) -> None:
    panel = JobsPanel()
    qtbot.addWidget(panel)
    panel.record_finished("Proxy for cam1.mp4", "done", 42.0)
    panel.refresh([])
    assert panel.row_count == 1
    assert panel.history[0].label == "Proxy for cam1.mp4"


def test_history_is_bounded(qapp: QApplication, qtbot) -> None:
    """An unbounded list of finished jobs is a memory leak with a scrollbar."""
    panel = JobsPanel()
    qtbot.addWidget(panel)
    for index in range(50):
        panel.record_finished(f"job {index}", "done", 1.0)
    assert len(panel.history) <= 20


# ── the window wiring ────────────────────────────────────────────────


def test_the_window_has_a_feedback_surface(window: MainWindow) -> None:
    assert window.activity_bar is not None
    assert window.notifications is not None
    assert window.jobs_panel is not None


def test_a_tasks_tab_exists(window: MainWindow) -> None:
    titles = [window._left_tabs.tabText(i) for i in range(window._left_tabs.count())]
    assert "Tasks" in titles


def test_cancel_stops_the_active_task(window: MainWindow) -> None:
    cancelled: list[bool] = []
    window._active_cancel = lambda: cancelled.append(True)
    window.activity_bar.begin("Importing")

    window._cancel_active_task()

    assert cancelled == [True]
    assert window.activity_bar.isVisible() is False


def test_cancel_survives_a_dead_worker(window: MainWindow) -> None:
    """The worker's C++ side can already be gone; that is not a crash."""

    def _gone() -> None:
        raise RuntimeError("wrapped C/C++ object has been deleted")

    window._active_cancel = _gone
    window.activity_bar.begin("Importing")
    window._cancel_active_task()  # must not raise
    assert window.activity_bar.isVisible() is False
