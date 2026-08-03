"""Tests for the installed ``avialview open`` command."""

from __future__ import annotations

from pathlib import Path

import pytest

from avialview.__main__ import _parse_args


def test_open_accepts_a_session_file(tmp_path: Path) -> None:
    """The documented `avialview open <session>` invocation is supported."""
    session = tmp_path / "session.avv"
    session.write_text("{}", encoding="utf-8")

    args = _parse_args(["open", str(session)])

    assert args.command == "open"
    assert args.path == session


def test_open_accepts_a_recording_folder(tmp_path: Path) -> None:
    """AGENTS.md documents opening a sample-session folder, not only a file."""
    args = _parse_args(["open", str(tmp_path)])

    assert args.path == tmp_path


def test_open_without_a_path_is_rejected() -> None:
    """`open` with nothing to open must not silently start an empty window."""
    with pytest.raises(SystemExit):
        _parse_args(["open"])


def test_open_reports_a_missing_path_before_starting_qt(tmp_path: Path) -> None:
    """A typo must fail on the terminal, not in a dialog behind a window."""
    with pytest.raises(SystemExit):
        _parse_args(["open", str(tmp_path / "absent")])


def test_demo_still_takes_no_path(tmp_path: Path) -> None:
    """Only `open` consumes a path; a stray one is a mistake worth reporting."""
    with pytest.raises(SystemExit):
        _parse_args(["demo", str(tmp_path)])


def test_bare_launch_opens_nothing() -> None:
    """Launching with no arguments stays the empty-window case."""
    args = _parse_args([])

    assert args.command is None
    assert args.path is None


def test_open_routes_through_the_drag_and_drop_scan(tmp_path: Path, qtbot) -> None:
    """`open` and dropping the same path must not drift apart.

    The drop scanner already recognises .avv files, folders holding them, and
    loose recordings, so routing through it keeps one implementation.
    """
    from avialview.ui.main_window import MainWindow

    scanned: list[list[Path]] = []
    window = MainWindow()
    qtbot.addWidget(window)
    window._start_drop_scan = lambda paths: scanned.append(paths)  # type: ignore[method-assign]

    window.open_path(tmp_path)

    assert scanned == [[tmp_path]]


def test_open_session_dialog_loads_once(monkeypatch, qtbot) -> None:
    """Choosing a session in the dialog must start one load, not two.

    `_open_session` called `_start_session_load` twice, so every File > Open
    ran the whole session-load pipeline a second time against the same path.
    """
    from PySide6.QtWidgets import QFileDialog

    from avialview.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    loads: list[Path] = []
    window._start_session_load = lambda path: loads.append(path)  # type: ignore[method-assign]
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("/tmp/s.avv", ""))
    )

    window._open_session()

    assert loads == [Path("/tmp/s.avv")]


def test_open_session_dialog_cancels_cleanly(monkeypatch, qtbot) -> None:
    """Dismissing the dialog must not load anything."""
    from PySide6.QtWidgets import QFileDialog

    from avialview.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    loads: list[Path] = []
    window._start_session_load = lambda path: loads.append(path)  # type: ignore[method-assign]
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))

    window._open_session()

    assert loads == []
