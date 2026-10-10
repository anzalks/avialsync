"""Regression checks for how background workers are destroyed (D-062)."""

from __future__ import annotations

import re
from pathlib import Path

# Every module that moves a worker onto a QThread. Found, not listed: a fixed
# list missed the imaging pane, which reintroduced the deadlock (D-212).
WORKER_OWNING_MODULES = tuple(
    sorted(
        path
        for path in Path("src/avialsync").rglob("*.py")
        if "moveToThread(" in path.read_text(encoding="utf-8")
    )
)
WORKER_DELETE_LATER = re.compile(r"\.connect\(\s*(?:self\.)?_*worker\.deleteLater\s*\)")


def test_no_worker_is_destroyed_inside_its_own_thread() -> None:
    """A worker moved onto a QThread must not be ``deleteLater``-ed from it.

    Both ``worker.finished.connect(worker.deleteLater)`` and
    ``thread.finished.connect(worker.deleteLater)`` are *direct* connections
    when the worker lives in that thread, so ``~QObject`` runs inside the
    worker's own event loop. Destroying a QObject severs its connections while
    holding one of Qt's 131 **pooled** signal/slot mutexes, and PySide's
    ``disconnectNotify`` override then blocks on the GIL. A UI thread that
    holds the GIL and waits on a colliding mutex from that pool — closing a
    QProgressDialog does exactly that — deadlocks against it permanently.

    Pooled mutexes are chosen by object address, so unrelated objects collide
    and the hang is intermittent: it reproduced in roughly one demo launch in
    six. Every owner releases its worker from a UI-thread slot instead.
    """
    offenders: list[str] = []
    for path in WORKER_OWNING_MODULES:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if WORKER_DELETE_LATER.search(line):
                offenders.append(f"{path}:{number}: {line.strip()}")

    assert not offenders, "Workers must be released on the UI thread:\n" + "\n".join(offenders)


def test_the_scan_covers_every_worker_owner() -> None:
    """The guard is only as good as the modules it reads."""
    names = {path.name for path in WORKER_OWNING_MODULES}
    assert {"demo.py", "job_manager.py", "imaging_pane.py", "video_pane.py"} <= names
