"""File → Cache: delete one trial's cache, all of it, or show the folder (D-160).

Driven through the real import path, because the property that matters is end
to end: the trial's entries go, every other trial's stay, the data folder is
byte-for-byte what it was, and the workspace comes back exactly as it was --
still unsaved when it was unsaved.
"""

from __future__ import annotations

import gc
from pathlib import Path

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu
from shiboken6 import isValid

from avialsync.core import cache_store
from avialsync.core.cache import CacheManager, cache_dir_for, cache_root
from avialsync.loaders.csv_loader import CSVLoader
from avialsync.ui import recovery
from avialsync.ui.controllers import cache_controller
from avialsync.ui.main_window import MainWindow

_CONFIG = {"time_col": "time", "time_unit": "s", "separator": ","}


@pytest.fixture(autouse=True)
def isolated_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    return target


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    if isValid(win):
        win.close()


def _recording(folder: Path, name: str = "signal.csv") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("time,x\n" + "".join(f"{i * 0.1:.1f},{i}\n" for i in range(20)))
    return path


def _import(window: MainWindow, qtbot, path: Path) -> None:
    window._enqueue_import(path, CSVLoader, dict(_CONFIG))
    qtbot.waitUntil(lambda: str(path) in window._sensor_cache_dirs, timeout=15_000)
    qtbot.waitUntil(lambda: not window._job_manager.is_busy(), timeout=15_000)


def _snapshot(folder: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(folder)): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _other_trial_entry(tmp_path: Path) -> Path:
    """An entry for a trial that is not loaded, built without the UI."""
    source = _recording(tmp_path / "data" / "trial2")
    manager = CacheManager(loader_version=1)
    staging = manager.get_temp_cache_dir(source)
    (staging / "x_v.npy").write_bytes(b"x")
    manager.commit_cache(source, staging)
    return manager.get_cache_dir(source)


def _menu(window: MainWindow, title: str) -> QMenu:
    # Looked up by title, never through ``QAction.menu()``: that wrapper owns
    # the menu it returns and deletes it when collected.
    (menu,) = [menu for menu in window.findChildren(QMenu) if menu.title() == title]
    return menu


def _action(window: MainWindow, text: str) -> QAction:
    (action,) = [action for action in _menu(window, "Cache").actions() if action.text() == text]
    return action


def test_the_file_menu_offers_the_cache_commands(window: MainWindow) -> None:
    cache_menu = _menu(window, "Cache")
    gc.collect()
    labels = [action.text() for action in cache_menu.actions()]

    assert cache_menu.menuAction() in _menu(window, "File").actions()
    assert labels == ["Delete Cache for This Trial", "Delete All Cache", "Show Cache Folder"]


def test_trial_deletion_needs_a_trial_and_an_idle_workspace(
    window: MainWindow, qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window._refresh_action_availability()
    assert not _action(window, "Delete Cache for This Trial").isEnabled()
    assert _action(window, "Delete All Cache").isEnabled()

    _import(window, qtbot, _recording(tmp_path / "data" / "trial1"))
    window._refresh_action_availability()
    assert _action(window, "Delete Cache for This Trial").isEnabled()

    monkeypatch.setattr(window._job_manager, "is_busy", lambda: True)
    window._refresh_action_availability()
    assert not _action(window, "Delete Cache for This Trial").isEnabled()
    assert not _action(window, "Delete All Cache").isEnabled()


def test_deleting_a_trials_cache_keeps_other_trials_and_reloads_the_trial(
    window: MainWindow, qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trial = tmp_path / "data" / "trial1"
    signal = _recording(trial)
    pose = _recording(trial / "pose-3d", "pose.csv")
    other = _other_trial_entry(tmp_path)
    _import(window, qtbot, signal)
    _import(window, qtbot, pose)
    before = _snapshot(trial)
    first_build = (cache_dir_for(signal) / "meta.json").stat().st_mtime_ns
    removals: list[cache_store.RemovalReport] = []
    real_report = cache_controller._report
    monkeypatch.setattr(
        cache_controller,
        "_report",
        lambda win, report, where, restored: (
            removals.append(report),
            real_report(win, report, where, restored),
        ),
    )
    window.document.mark_dirty()

    window._refresh_action_availability()
    _action(window, "Delete Cache for This Trial").trigger()
    qtbot.waitUntil(lambda: bool(removals), timeout=15_000)
    qtbot.waitUntil(
        lambda: (
            {str(signal), str(pose)} <= set(window._sensor_cache_dirs)
            and not window.session_runtime.restoring
        ),
        timeout=15_000,
    )

    assert removals[0].removed == 2 and not removals[0].failed
    assert other.is_dir(), "another trial's cache is not this trial's to delete"
    assert (cache_dir_for(signal) / "meta.json").stat().st_mtime_ns != first_build
    assert _snapshot(trial) == before, "the data folder is never touched"
    assert window.document.is_dirty, "unsaved work is still unsaved after the reload"


def test_deleting_all_cache_with_nothing_loaded_empties_the_root(
    window: MainWindow, qtbot, tmp_path: Path
) -> None:
    _other_trial_entry(tmp_path)
    assert cache_store.list_entries()

    window._refresh_action_availability()
    _action(window, "Delete All Cache").trigger()
    qtbot.waitUntil(lambda: not cache_store.list_entries(), timeout=15_000)
    qtbot.waitUntil(lambda: not window._job_manager.is_busy(), timeout=15_000)

    assert not window._anything_loaded()
    assert cache_root().is_dir()


def test_show_cache_folder_opens_the_root(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        cache_controller.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile())
    )

    cache_controller.show_cache_folder(window)

    assert [Path(path) for path in opened] == [cache_root()]


@pytest.mark.parametrize(
    ("count", "text"),
    [(0, "0 B"), (999, "999 B"), (1500, "1.5 KB"), (2_500_000, "2.5 MB"), (3 * 10**10, "30.0 GB")],
)
def test_sizes_read_the_way_people_say_them(count: int, text: str) -> None:
    assert cache_controller._size(count) == text


def test_unsaved_marking_belongs_to_one_restore_only() -> None:
    """A reset between the deletion and the reload makes the request stale."""
    from avialsync.ui.controllers.session_state import SessionRuntimeState

    runtime = SessionRuntimeState(generation=4)
    runtime.dirty_after_restore = 4
    assert runtime.take_dirty_after_restore()
    assert not runtime.take_dirty_after_restore(), "it is consumed"

    runtime.dirty_after_restore = 4
    runtime.generation += 1
    assert not runtime.take_dirty_after_restore()
