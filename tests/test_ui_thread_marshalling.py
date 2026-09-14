"""Completion handlers run on the UI thread, whatever thread emitted them.

Connecting a worker's ``finished``/``error`` signal straight to a closure gives
a *direct* connection: a plain callable is not a ``QObject``, so Qt has no
receiver thread to queue into and runs it wherever the signal was emitted --
the worker. Whatever widgets that handler touches are then touched from a
worker thread, which is the failure D-051 describes and which showed up in CI
as ``QObject: Cannot create children for a parent that is in a different
thread``.

``Qt.QueuedConnection`` is not the fix. Without a context object the *sender*
supplies the thread affinity, so the call is merely queued back into the worker
thread; the test below pins that, because it is the obvious wrong repair.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Qt, QThread, Signal

from avialsync.ui.job_manager import on_ui_thread

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "avialsync"

#: Signals emitted from a worker thread by everything `JobManager` runs.
WORKER_SIGNALS = {"finished", "error", "progress"}


class _Emitter(QObject):
    """Stands in for a worker: lives on another thread and emits from there."""

    finished = Signal(object)

    def run(self) -> None:
        self.finished.emit("payload")


def _thread_of_delivery(qtbot, connect) -> QThread:
    """Run an emitter on its own thread; return the thread its handler ran in."""
    anchor = QObject()
    emitter = _Emitter()
    thread = QThread()
    emitter.moveToThread(thread)

    seen: list[QThread] = []
    connect(emitter, anchor, lambda _payload: seen.append(QThread.currentThread()))

    thread.started.connect(emitter.run)
    # Deliberately *not* `emitter.finished.connect(thread.quit)`. That raced the
    # case this file exists to pin: a queued connection with no receiver is
    # posted to the worker's own event loop, so quitting that loop from the same
    # signal is a race between dispatching the call and tearing down the loop it
    # is sitting in. The `finally` below quits the thread once the delivery has
    # been observed, which is teardown rather than part of the measurement.
    thread.start()
    try:
        qtbot.waitUntil(lambda: bool(seen), timeout=5_000)
    finally:
        thread.quit()
        thread.wait(5_000)
    return seen[0]


def test_a_wrapped_handler_runs_on_the_ui_thread(qtbot) -> None:
    delivered = _thread_of_delivery(
        qtbot,
        lambda emitter, anchor, fn: emitter.finished.connect(on_ui_thread(fn, anchor)),
    )

    assert delivered is QThread.currentThread()


def test_a_bare_closure_does_not(qtbot) -> None:
    """Why the wrapper exists, not a behaviour anything should rely on."""
    delivered = _thread_of_delivery(qtbot, lambda emitter, anchor, fn: emitter.finished.connect(fn))

    assert delivered is not QThread.currentThread()


def test_a_queued_connection_is_not_the_fix(qtbot) -> None:
    """With no context object the sender supplies the affinity, so this
    queues the call back into the worker thread it was trying to leave."""
    delivered = _thread_of_delivery(
        qtbot,
        lambda emitter, anchor, fn: emitter.finished.connect(fn, Qt.QueuedConnection),
    )

    assert delivered is not QThread.currentThread()


# ── Guard ─────────────────────────────────────────────────────────────


def _unmarshalled_worker_connections(path: Path) -> list[tuple[int, str]]:
    """Return ``(line, signal)`` for worker connections made to a bare callable.

    A bound method (``window._on_finished``, ``thread.quit``) is an attribute of
    a real ``QObject`` and Qt queues it already. A ``Lambda``, or a bare name
    bound to a local ``def``, is what has no receiver.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "connect" or not node.args:
            continue
        signal = node.func.value
        if not isinstance(signal, ast.Attribute) or signal.attr not in WORKER_SIGNALS:
            continue
        # Only signals owned by something named like a worker; a dialog's own
        # `finished` is emitted on the UI thread and needs no marshalling.
        owner = ast.unparse(signal.value)
        if "worker" not in owner.lower():
            continue
        handler = node.args[0]
        if isinstance(handler, (ast.Lambda, ast.Name)):
            offenders.append((node.lineno, f"{owner}.{signal.attr}"))
    return offenders


@pytest.mark.parametrize("path", sorted(SRC_ROOT.rglob("*.py")), ids=lambda p: p.name)
def test_no_worker_signal_is_connected_to_a_bare_callable(path: Path) -> None:
    offenders = _unmarshalled_worker_connections(path)

    assert not offenders, (
        f"{path.relative_to(SRC_ROOT)}: worker signal connected to a bare callable at "
        f"{offenders}. Wrap it with `on_ui_thread(fn, window)` or connect a bound "
        "method of a QObject, or the handler runs on the worker thread (D-051)."
    )
