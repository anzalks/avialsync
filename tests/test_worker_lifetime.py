"""Background job lifetime regression tests.

A QObject moved to a QThread with no owning Python reference is garbage
collected before QThread.started fires, so its run() slot never executes.
_start_drop_scan, _start_session_save, and _start_session_load all did this
once — dropping any file, saving a session, and loading a session were
silently no-ops. They now route through MainWindow._run_job, which owns the
worker/thread pair for the life of the job.

The same four jobs failed a second way, for a different reason: ``_run_job``
returns a thread that is *already running*, so a result signal connected after
it returns races a worker that may already have finished. Every job here is
pinned by its observable effect, so a caller that reverts to wiring after the
call loses that effect (HANDOUT.md trap 31).
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from avialsync.loaders.csv_loader import CSVLoader
from avialsync.ui.controllers import export_controller
from avialsync.ui.main_window import MainWindow

FIXTURE_SESSION = Path(__file__).parent / "fixtures" / "session_v1.avv"


@pytest.fixture
def main_window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    win.close()


def _send_drop(target, path: Path) -> QDropEvent:
    """Deliver a real Qt drag-enter + drop of *path* onto *target*."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    enter_event = QDragEnterEvent(
        QPointF(10, 10).toPoint(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(target, enter_event)
    assert enter_event.isAccepted()

    drop_event = QDropEvent(
        QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton, Qt.NoModifier
    )
    QApplication.sendEvent(target, drop_event)
    return drop_event


def test_drop_routes_single_csv(
    main_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qtbot
) -> None:
    """A real (unmocked) drop of a CSV must reach _start_data_import via the real worker thread."""
    sensor = tmp_path / "sensor.csv"
    sensor.write_text("time,value\n0,1\n", encoding="utf-8")
    data_calls: list[tuple[Path, type]] = []

    monkeypatch.setattr(
        main_window._registry,
        "find_best_loader",
        lambda p: CSVLoader if p == sensor else None,
    )
    monkeypatch.setattr(
        main_window,
        "_start_data_import",
        lambda path, loader, pre_config=None: data_calls.append((path, loader)),
    )

    # Deliberately do NOT stub _start_drop_scan: this test exercises the real
    # DropScanWorker/QThread lifecycle, which is exactly what was broken.
    event = _send_drop(main_window, sensor)
    assert event.isAccepted()

    qtbot.waitUntil(lambda: len(data_calls) == 1, timeout=10_000)
    assert data_calls == [(sensor, CSVLoader)]


def test_drop_routes_avv_session(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, qtbot
) -> None:
    """Dropping a .avv session file must reach _start_session_load via the real worker thread."""
    assert FIXTURE_SESSION.exists()
    load_calls: list[Path] = []
    monkeypatch.setattr(
        main_window,
        "_start_session_load",
        lambda path: load_calls.append(path),
    )

    event = _send_drop(main_window, FIXTURE_SESSION)
    assert event.isAccepted()

    qtbot.waitUntil(lambda: len(load_calls) == 1, timeout=10_000)
    assert load_calls == [FIXTURE_SESSION]


def test_session_save_writes_file(main_window: MainWindow, tmp_path: Path, qtbot) -> None:
    """_start_session_save must actually run its worker and produce a file."""
    out = tmp_path / "saved.avv"

    main_window._start_session_save(out, is_autosave=False)

    qtbot.waitUntil(lambda: out.exists(), timeout=10_000)
    qtbot.waitUntil(lambda: not main_window._save_in_progress, timeout=10_000)


def test_second_save_is_allowed(main_window: MainWindow, tmp_path: Path, qtbot) -> None:
    """A save must not permanently latch _save_in_progress and block later saves."""
    first = tmp_path / "first.avv"
    second = tmp_path / "second.avv"

    main_window._start_session_save(first, is_autosave=False)
    qtbot.waitUntil(lambda: first.exists(), timeout=10_000)
    qtbot.waitUntil(lambda: not main_window._save_in_progress, timeout=10_000)

    main_window._start_session_save(second, is_autosave=False)
    qtbot.waitUntil(lambda: second.exists(), timeout=10_000)
    qtbot.waitUntil(lambda: not main_window._save_in_progress, timeout=10_000)


class _FakeFileDialog:
    """Answers the save prompt without showing one."""

    target: Path

    @staticmethod
    def getSaveFileName(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(_FakeFileDialog.target), "CSV Files (*.csv)"


class _StubThread:
    """What ``_run_job`` hands back, minus every QThread lifetime hazard.

    Only needs the two members a ``configure`` callback touches, plus the
    ``start`` a wrongly-wired caller would invoke.
    """

    def start(self) -> None:
        pass

    def quit(self) -> None:
        pass


class _RecordingMessageBox:
    """Records the dialogs the export would have shown."""

    shown: list[tuple[str, str]] = []

    @staticmethod
    def information(_parent: object, title: str, text: str) -> None:
        _RecordingMessageBox.shown.append((title, text))

    @staticmethod
    def critical(_parent: object, title: str, text: str) -> None:
        _RecordingMessageBox.shown.append((title, text))


def test_export_annotations_reports_completion(
    main_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qtbot
) -> None:
    """An export must run its worker and tell the user it finished.

    Coverage for the controller path, which was previously exercised only as far
    as ``AnnotationExportWorker`` itself. This does not pin the wiring order —
    a real export is slow enough relative to thread start-up that the racy form
    passes it 10 times out of 10;
    ``test_export_reports_even_if_the_worker_finishes_first`` is what pins that.
    """
    _FakeFileDialog.target = tmp_path / "annotations.csv"
    _RecordingMessageBox.shown = []
    monkeypatch.setattr(export_controller, "QFileDialog", _FakeFileDialog)
    monkeypatch.setattr(export_controller, "QMessageBox", _RecordingMessageBox)

    main_window.annotation_store.add_point(1.0, label="stance")
    main_window.annotation_store.add_point(2.0, label="swing")

    main_window._export_annotations()

    qtbot.waitUntil(lambda: _FakeFileDialog.target.exists(), timeout=10_000)
    qtbot.waitUntil(lambda: bool(_RecordingMessageBox.shown), timeout=10_000)

    title, text = _RecordingMessageBox.shown[0]
    assert title == "Export Complete", f"export reported {title!r}: {text}"
    assert "2 markers" in text


def test_export_reports_even_if_the_worker_finishes_first(
    main_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Result signals must be wired before the worker can emit, not after.

    ``JobManager.start`` starts the thread before it returns, so ``_run_job``
    hands back a thread whose worker is already running. Connecting afterwards
    is therefore a race, and one that real timings hide: the export is slow
    enough that the broken form still passes the end-to-end test above. This
    collapses the window instead of waiting for it — the stand-in runs the
    worker at exactly the point the real one starts the thread, so a caller that
    wires afterwards observes the emit it missed and no dialog is recorded.

    Generalises to any ``_run_job`` caller; the other three are pinned by their
    own effects above (HANDOUT.md trap 31).
    """
    _FakeFileDialog.target = tmp_path / "annotations.csv"
    _RecordingMessageBox.shown = []
    monkeypatch.setattr(export_controller, "QFileDialog", _FakeFileDialog)
    monkeypatch.setattr(export_controller, "QMessageBox", _RecordingMessageBox)

    def fake_run_job(worker, label="Working", configure=None):
        # A stand-in, not a real QThread: a caller wired the wrong way also calls
        # `thread.start()` on whatever this returns, and abandoning a started
        # QThread aborts the process — which would replace a clean assertion
        # failure with a crash and no message.
        thread = _StubThread()
        if configure is not None:
            configure(thread)
        worker.run()
        return thread

    monkeypatch.setattr(main_window, "_run_job", fake_run_job)

    main_window.annotation_store.add_point(1.0, label="stance")

    main_window._export_annotations()

    assert _RecordingMessageBox.shown, (
        "the export finished before its result signal was connected, so the user "
        "was never told — connect in the `configure` callback, not after _run_job"
    )
    assert _RecordingMessageBox.shown[0][0] == "Export Complete"
