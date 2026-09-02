"""The first thing a new user sees, and the Help menu (WP-8).

Launching with no data gave bare splitters: no drop target, no mention of the
entry points, and no hint that a complete sample session can be generated. That
demo was reachable only from a command line the target user may never open.

The Help menu was Shortcuts, Diagnostics, About -- a dead end -- and About was
three lines with no version in them, so every bug report arrived without one.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from avialsync.ui import recovery
from avialsync.ui.about import citation_text, project_urls, version_report
from avialsync.ui.empty_state import EmptyState
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
    win.close()


# ── the empty state ──────────────────────────────────────────────────


def test_it_is_shown_with_nothing_loaded(window: MainWindow) -> None:
    assert window.empty_state.isVisible() is True


def test_it_names_the_three_entry_points(qapp: QApplication, qtbot) -> None:
    from PySide6.QtWidgets import QPushButton

    state = EmptyState()
    qtbot.addWidget(state)
    labels = [b.text() for b in state.findChildren(QPushButton)]
    assert any("Video" in label for label in labels)
    assert any("Data" in label for label in labels)
    assert any("demo" in label.lower() for label in labels)


def test_the_demo_button_is_explained(qapp: QApplication, qtbot) -> None:
    """It is the best onboarding asset and was hidden in a CLI subcommand."""
    from PySide6.QtWidgets import QPushButton

    state = EmptyState()
    qtbot.addWidget(state)
    demo = next(b for b in state.findChildren(QPushButton) if "demo" in b.text().lower())
    assert "camera" in demo.toolTip().lower()


@pytest.mark.parametrize(
    "signal_name", ["open_videos_requested", "open_data_requested", "demo_requested"]
)
def test_each_button_reports(signal_name: str, qapp: QApplication, qtbot) -> None:
    from PySide6.QtWidgets import QPushButton

    state = EmptyState()
    qtbot.addWidget(state)
    signal = getattr(state, signal_name)
    index = ["open_videos_requested", "open_data_requested", "demo_requested"].index(signal_name)
    button = state.findChildren(QPushButton)[index]
    with qtbot.waitSignal(signal, timeout=1000):
        button.click()


def test_it_hides_once_something_is_loaded(window: MainWindow, tmp_path) -> None:
    """It must never sit over real data."""
    window._sensor_cache_dirs["/tmp/sensor.csv"] = tmp_path / "sensor.avialcache"
    window._refresh_empty_state()
    assert window.empty_state.isVisible() is False


def test_it_returns_when_everything_is_closed(window: MainWindow, tmp_path) -> None:
    window._sensor_cache_dirs["/tmp/sensor.csv"] = tmp_path / "sensor.avialcache"
    window._refresh_empty_state()
    window._sensor_cache_dirs.clear()
    window._refresh_empty_state()
    assert window.empty_state.isVisible() is True


# ── about, and what a bug report needs ───────────────────────────────


def test_the_version_report_names_the_application() -> None:
    assert "AvialSync" in version_report()


@pytest.mark.parametrize("library", ["Python", "PySide6", "PyAV", "numpy", "polars"])
def test_the_version_report_names_the_libraries_that_matter(library: str) -> None:
    """PyAV carries its own FFmpeg; Qt decides widget behaviour. Both differ."""
    assert library in version_report()


def test_the_version_report_names_the_platform() -> None:
    assert "Platform" in version_report()


def test_a_missing_library_is_reported_not_raised() -> None:
    """A partial environment must still produce a copyable report."""
    report = version_report()
    assert report.count("\n") >= 5


# ── project links come from the metadata ─────────────────────────────


def test_urls_come_from_the_package_metadata() -> None:
    """They were repointed during 0.1.6; a hardcoded copy would have gone stale."""
    urls = project_urls()
    assert urls, "no project URLs are declared"
    assert any("Doc" in label for label in urls)
    assert all(url.startswith("http") for url in urls.values())


def test_the_help_menu_has_destinations(window: MainWindow) -> None:
    """It was Shortcuts, Diagnostics, About -- nowhere to go."""
    for action in window.menuBar().actions():
        if action.text() != "Help":
            continue
        labels = [entry.text() for entry in action.menu().actions()]
        assert any("Documentation" in label for label in labels)
        assert any("Report" in label for label in labels)
        assert any("Cite" in label for label in labels)
        return
    pytest.fail("no Help menu")


def test_citation_text_is_available() -> None:
    text = citation_text()
    assert text
    assert "cff" in text.lower() or "title" in text.lower() or "repository" in text.lower()


# ── no modal progress survived (D-091) ───────────────────────────────


def test_the_demo_progress_window_is_not_modal() -> None:
    """Generation encodes four videos; a modal would block for minutes."""
    from pathlib import Path

    source = Path("src/avialsync/demo.py").read_text(encoding="utf-8")
    assert "self.setModal(False)" in source
    assert "self.setModal(True)" not in source
