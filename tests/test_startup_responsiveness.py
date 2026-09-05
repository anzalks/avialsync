"""The UI thread must not import plugins, and a wedged decoder must not be destroyed.

Two defects, both present in the shipped v0.1.6 and both reported as "the app
hangs for four seconds and then prints a QThread warning":

1. ``LoaderRegistry.__init__`` imported every built-in loader inline, inside
   ``MainWindow.__init__``. That is module IO on the UI thread (architecture
   rule 3) -- ``neo`` pulls in scipy and quantities, the AOL loader pulls in
   h5py. Measured at ~470 ms warm and over four seconds cold behind on-access
   virus scanning, all before the window appeared (D-095).
2. A decode thread is ``QThread(self)``, parented to its pane. When teardown's
   wait timed out, Qt destroyed a running QThread -- "QThread: Destroyed while
   thread '' is still running" -- which can abort the process (D-096).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from avialsync.core.registry import LoaderRegistry
from avialsync.ui import video_pane as video_pane_module
from avialsync.ui.main_window import MainWindow

# ── plugin discovery is off the UI thread (D-095) ────────────────────


def test_constructing_the_registry_imports_nothing(tmp_path: Path) -> None:
    """The constructor must be cheap; discovery is what costs."""
    registry = LoaderRegistry(plugin_dirs=[tmp_path])
    assert registry._discovered is False
    assert registry._loaders == []


def test_discovery_happens_on_first_use(tmp_path: Path) -> None:
    registry = LoaderRegistry(plugin_dirs=[tmp_path])
    assert registry.loaders(), "asking for loaders must discover them"
    assert registry._discovered is True


@pytest.mark.parametrize(
    "use",
    [
        lambda r: r.loaders(),
        lambda r: r.sessions(),
        lambda r: r.plugin_errors,
        lambda r: r.find_best_loader(Path("x.csv")),
        lambda r: r.find_best_session(Path("x")),
    ],
    ids=["loaders", "sessions", "plugin_errors", "find_best_loader", "find_best_session"],
)
def test_every_public_accessor_waits_for_discovery(use, tmp_path: Path) -> None:
    """A caller must never observe a half-discovered registry.

    `plugin_errors` matters most here: reporting an empty list mid-warm-up
    would have Diagnostics tell the user every plugin loaded fine.
    """
    registry = LoaderRegistry(plugin_dirs=[tmp_path])
    use(registry)
    assert registry._discovered is True


def test_discovery_runs_once_under_concurrent_use(tmp_path: Path) -> None:
    """`drop_worker` already queries the registry from a worker thread."""
    registry = LoaderRegistry(plugin_dirs=[tmp_path])
    calls: list[int] = []
    original = registry._discover

    def counting_discover() -> None:
        calls.append(1)
        time.sleep(0.02)  # widen the window a racing thread could slip through
        original()

    registry._discover = counting_discover  # type: ignore[method-assign]

    threads = [threading.Thread(target=registry.loaders) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sum(calls) == 1, "eight concurrent callers must not import eight times"


def test_warmup_completes_and_is_idempotent(tmp_path: Path) -> None:
    registry = LoaderRegistry(plugin_dirs=[tmp_path])
    registry.start_warmup()
    registry.start_warmup()  # must not start a second thread
    assert registry.loaders()
    assert registry._discovered is True


def test_main_window_construction_does_not_block_on_discovery(
    qapp: QApplication, qtbot, monkeypatch
) -> None:
    """The regression test for the four-second launch.

    Asserts the *shape* of the fix rather than a wall-clock budget: CI machines
    are too variable for a timing assertion.

    It asserts which thread the import work ran on, not whether it had finished.
    "`_discovered` is still False when the window exists" reads as the stricter
    check and is not: run after any test that has already imported neo, scipy
    and h5py, the warm-up thread completes inside the constructor and the flag
    is legitimately True. That made this test pass alone and fail in a full
    run, which is a race in the test, not a defect in the window. What must
    never happen is those imports landing on the UI thread.
    """
    ran_on: list[threading.Thread] = []
    original = LoaderRegistry._discover

    def recording_discover(self: LoaderRegistry) -> None:
        ran_on.append(threading.current_thread())
        original(self)

    monkeypatch.setattr(LoaderRegistry, "_discover", recording_discover)

    win = MainWindow()
    qtbot.addWidget(win)
    try:
        warmup = win._registry._warmup
    finally:
        win.close()

    assert warmup is not None, "the constructor must hand discovery to a thread"
    assert threading.main_thread() not in ran_on, (
        "MainWindow.__init__ must not wait for plugin discovery; "
        "it imports neo, scipy, and h5py and blocks the UI thread "
        f"(discovery ran on {[thread.name for thread in ran_on]})"
    )


# ── an abandoned decode thread is detached, not destroyed (D-096) ────


class _StubThread(QThread):
    """A thread that ignores quit(), standing in for a wedged decoder.

    The stop Event is built in ``__init__``, not in ``run``: creating it on the
    worker thread lets ``release`` race the start and set a different Event,
    leaving the thread parked for its full timeout.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stop = threading.Event()

    def run(self) -> None:  # pragma: no cover - timing dependent
        self._stop.wait(30)

    def release(self) -> None:
        self._stop.set()


def test_abandoning_a_decoder_detaches_it_from_its_parent(qapp: QApplication, qtbot) -> None:
    """A running QThread destroyed with its parent aborts the process."""
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    qtbot.addWidget(parent)
    thread = _StubThread(parent)
    assert thread.parent() is parent

    video_pane_module._abandon_decoder(thread, object())

    assert thread.parent() is None, "an abandoned thread must not die with its pane"
    assert any(entry[0] is thread for entry in video_pane_module._ABANDONED_DECODERS)

    thread.release()
    thread.quit()
    thread.wait(5000)
    video_pane_module.drain_abandoned_decoders(timeout_ms=5000)


def test_a_finished_abandoned_decoder_is_released(qapp: QApplication, qtbot) -> None:
    """The retention must not become a leak."""
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    qtbot.addWidget(parent)
    thread = _StubThread(parent)
    thread.start()
    video_pane_module._abandon_decoder(thread, object())

    thread.release()
    thread.quit()
    thread.wait(5000)
    video_pane_module.drain_abandoned_decoders(timeout_ms=5000)

    assert not any(entry[0] is thread for entry in video_pane_module._ABANDONED_DECODERS)


def test_decode_threads_are_named(qapp: QApplication, qtbot) -> None:
    """An unnamed thread is why the Qt warning said '' and named no camera."""
    from avialsync.ui.video_pane import VideoPane

    pane = VideoPane()
    qtbot.addWidget(pane)
    try:
        pane.open(str(Path("nonexistent_camera.mp4")))
        thread = pane._thread
        assert thread is not None
        assert "nonexistent_camera.mp4" in thread.objectName()
    finally:
        pane.shutdown() if hasattr(pane, "shutdown") else None
        pane.close()
