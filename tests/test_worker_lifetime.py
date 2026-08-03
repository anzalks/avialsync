"""Background job lifetime regression tests.

A QObject moved to a QThread with no owning Python reference is garbage
collected before QThread.started fires, so its run() slot never executes.
Before RECOVERY_PROMPT.md Phase 1, _start_drop_scan, _start_session_save,
and _start_session_load all did this — dropping any file, saving a
session, and loading a session were silently no-ops.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from avialsync.loaders.csv_loader import CSVLoader
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
