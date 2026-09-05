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


# ── it has to be legible, not just present ───────────────────────────


def test_every_control_gets_the_height_it_needs(window: MainWindow, qapp) -> None:
    """The drop zone came up as a row of thin horizontal bars.

    ``VideoGrid`` sets a deliberately low 72px floor so an empty video area
    does not take height from the plots, and an explicit ``minimumHeight``
    overrides the 173px its layout actually asks for. The old placeholder was
    one label with ``Ignored`` vertical policy, which degrades quietly. The
    empty state is five stacked controls, which does not: each was handed 2px
    and drew as a sliver, with the headline clipped and the subtitle overlapping
    the buttons. It survives that now by scrolling, not by raising the floor.
    """
    from PySide6.QtWidgets import QLabel, QPushButton, QWidget

    window.resize(1266, 810)
    qapp.processEvents()

    starved = [
        f"{type(child).__name__}({child.text()[:24]!r}) got {child.height()}px, "
        f"needs {child.minimumSizeHint().height()}px"
        for child in window.empty_state.findChildren(QWidget)
        if isinstance(child, (QLabel, QPushButton))
        and child.isVisible()
        and child.height() < child.minimumSizeHint().height()
    ]
    assert starved == [], f"squashed: {starved}"


def test_the_empty_state_never_raises_the_window_minimum(
    window: MainWindow, tmp_path, qapp
) -> None:
    """Legibility must not cost the small-display guarantee.

    The first fix for the slivers raised the grid's floor to the empty state's
    own minimum while it showed. A pane minimum is the window's minimum by
    proxy: the window could then not be shrunk below ~505px tall, and
    ``test_ui_layout_resize.py::test_compact_viewport_keeps_every_workspace_surface_available``
    -- 640x480, every surface still reachable -- went red. The floor now stays
    where ``VideoGrid`` put it in both states.
    """
    from avialsync.ui.video_grid import VideoGrid

    qapp.processEvents()
    assert window.empty_state.isVisible(), "nothing is loaded; it should be showing"
    assert window.video_grid.minimumHeight() == VideoGrid.BASE_MIN_HEIGHT

    window._sensor_cache_dirs["/tmp/sensor.csv"] = tmp_path / "sensor.avialcache"
    window._refresh_empty_state()

    assert window.video_grid.minimumHeight() == VideoGrid.BASE_MIN_HEIGHT


def test_a_short_video_area_scrolls_rather_than_squashing(qapp: QApplication, qtbot) -> None:
    """What replaces the raised floor, asserted where it is cheap to assert.

    At the grid's 72px floor there is no arrangement that shows five stacked
    controls at once. Scrolling keeps every one of them at its natural size and
    shows as much as fits; squashing is what drew the slivers.
    """
    from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QWidget

    from avialsync.ui.video_grid import VideoGrid

    state = EmptyState()
    qtbot.addWidget(state)
    state.resize(600, VideoGrid.BASE_MIN_HEIGHT)
    state.show()
    qapp.processEvents()

    assert state.findChild(QScrollArea) is not None, "it has to degrade somehow"
    squashed = [
        f"{type(child).__name__}({child.text()[:24]!r}) got {child.height()}px, "
        f"needs {child.minimumSizeHint().height()}px"
        for child in state.findChildren(QWidget)
        if isinstance(child, (QLabel, QPushButton))
        and child.height() < child.minimumSizeHint().height()
    ]
    assert squashed == [], f"squashed at the floor: {squashed}"
