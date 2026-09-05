"""Law 1 conformance: opening and quitting are never gated (D-088, D-089).

> The application never refuses to open a file, and never blocks the user to
> tell them something. It informs them and stays out of the way.

UX_FOUNDATIONS_PLAN.md §9 asks for this as a single test: with unsaved changes
present, File → Open, drag-and-drop, Open Recent, and quit each proceed with no
modal in the way. Each of those paths is covered on its own elsewhere; what was
missing is the one that fails the moment somebody adds a "save your changes?"
gate in front of any of them, which is the shape every editor acquires by
accident.

The gate detector is deliberately blunt: every ``QMessageBox`` convenience
method is replaced by one that records and answers Cancel. A gate that got
added would both show up in the recording and take the "no, stop" branch, so a
test that only asserted the file still loaded could not pass by accident.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from shiboken6 import isValid

from avialsync.core.commands import AddMarkerCommand
from avialsync.core.document import MarkerRecord
from avialsync.ui import recovery
from avialsync.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    """Quitting writes a recovery snapshot; keep it out of real app data."""
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def main_window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    # Qt may already have deleted it: pytest-qt runs processEvents()
    # after the call phase, which executes pending deleteLater()s.
    if isValid(win):
        win.close()


@pytest.fixture
def gates(monkeypatch) -> list[str]:
    """Record every modal box raised, and answer each one "no"."""
    recorded: list[str] = []

    def recording(name: str):
        def gate(*args, **kwargs):
            recorded.append(name)
            return QMessageBox.StandardButton.Cancel

        return gate

    for method in ("question", "warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, method, staticmethod(recording(method)))
    return recorded


def _with_unsaved_changes(window: MainWindow) -> None:
    """One real edit, through the command bus, so the document is dirty."""
    window.document.record(
        AddMarkerCommand(MarkerRecord(t_start=1.0, t_end=None, label="spike", index=0))
    )
    assert window.document.is_dirty, "the fixture must actually be dirty"


def test_file_open_proceeds_with_unsaved_changes(
    main_window: MainWindow, tmp_path: Path, monkeypatch, gates: list[str]
) -> None:
    _with_unsaved_changes(main_window)
    video = tmp_path / "camera.mp4"
    video.write_bytes(b"")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(video)], ""))
    )
    opened: list[Path] = []
    monkeypatch.setattr(main_window, "_load_video", opened.append)

    main_window._open_video()

    assert opened == [video], "the open must happen, not wait behind a question"
    assert gates == []


def test_open_recent_proceeds_with_unsaved_changes(
    main_window: MainWindow, tmp_path: Path, monkeypatch, gates: list[str]
) -> None:
    _with_unsaved_changes(main_window)
    session = tmp_path / "yesterday.avv"
    session.write_text("{}", encoding="utf-8")
    loaded: list[Path] = []
    monkeypatch.setattr(main_window, "_start_session_load", loaded.append)

    main_window._open_recent(str(session))

    assert loaded == [session]
    assert gates == []


def test_a_drop_proceeds_with_unsaved_changes(
    main_window: MainWindow, tmp_path: Path, monkeypatch, gates: list[str]
) -> None:
    from avialsync.core.source import SessionLayout
    from avialsync.engine.drop_worker import DropScanWorker
    from avialsync.loaders.csv_loader import CSVLoader

    _with_unsaved_changes(main_window)
    sensor = tmp_path / "sensor.csv"
    sensor.write_text("time,value\n0,1\n", encoding="utf-8")
    monkeypatch.setattr(
        main_window._registry,
        "find_best_loader",
        lambda p: CSVLoader if p == sensor else None,
    )
    imported: list[Path] = []
    monkeypatch.setattr(
        main_window,
        "_start_data_import",
        lambda path, loader, pre_config=None: imported.append(path),
    )

    def scan_here(paths):
        worker = DropScanWorker(paths, main_window._registry)
        main_window._on_drop_scan_finished(
            worker._collect_drop_candidates(paths[0]), SessionLayout()
        )

    monkeypatch.setattr(main_window, "_start_drop_scan", scan_here)

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(sensor))])
    QApplication.sendEvent(
        main_window,
        QDragEnterEvent(
            QPointF(10, 10).toPoint(),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.NoButton,
            Qt.NoModifier,
        ),
    )
    drop = QDropEvent(
        QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton, Qt.NoModifier
    )
    QApplication.sendEvent(main_window, drop)

    assert drop.isAccepted()
    assert imported == [sensor]
    assert gates == []


def test_quitting_proceeds_with_unsaved_changes(
    main_window: MainWindow, gates: list[str], isolated_recovery_dir: Path
) -> None:
    """Always close, and never lose the work: quit writes a snapshot instead."""
    _with_unsaved_changes(main_window)
    main_window.annotation_store.add_point(1.0, "spike")

    main_window.close()

    assert gates == []
    assert main_window.isVisible() is False
    assert recovery.read_recovery() is not None, "quit must preserve unsaved work (D-089)"


def test_an_unsupported_file_is_reported_not_refused(
    main_window: MainWindow, tmp_path: Path, monkeypatch, gates: list[str]
) -> None:
    """Nothing claims the file, so the user is informed -- without a modal."""
    mystery = tmp_path / "recording.xyz"
    mystery.write_bytes(b"\x00\x01")
    monkeypatch.setattr(main_window._registry, "find_best_loader", lambda p: None)
    reported: list[BaseException] = []
    monkeypatch.setattr(
        main_window, "report_failure", lambda error, doing="": reported.append(error)
    )

    main_window._start_data_import(mystery)

    assert gates == [], "an unsupported file may not raise a modal (AGENTS rule 10)"
    assert len(reported) == 1, "and it may not fail silently either"


def test_a_missing_recent_session_is_reported_not_refused(
    main_window: MainWindow, tmp_path: Path, monkeypatch, gates: list[str]
) -> None:
    """Open Recent is one of the four paths rule 10 names by name."""
    reported: list[BaseException] = []
    monkeypatch.setattr(
        main_window, "report_failure", lambda error, doing="": reported.append(error)
    )
    loaded: list[Path] = []
    monkeypatch.setattr(main_window, "_start_session_load", loaded.append)

    main_window._open_recent(str(tmp_path / "deleted.avv"))

    assert gates == []
    assert loaded == [], "there is nothing to load"
    assert len(reported) == 1
