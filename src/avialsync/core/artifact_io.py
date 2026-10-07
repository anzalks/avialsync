"""The atomic publication boundary for authored files and exports (D-197)."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

from avialsync.core.artifacts import ArtifactKind, ExistingFile, get_kind
from avialsync.core.cache import cache_root
from avialsync.core.errors import ExportError

_INVALID_WINDOWS = set('<>:"/\\|?*')
_RESERVED_WINDOWS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _validate(target: Path, kind: ArtifactKind, sources: Iterable[Path | str]) -> None:
    """Reject destinations that could damage loaded data or the cache."""
    if not target.name or any(char in _INVALID_WINDOWS for char in target.name):
        raise ExportError(f"{target.name!r} is not a portable file name")
    if target.name.rstrip(" .") != target.name or target.stem.upper() in _RESERVED_WINDOWS:
        raise ExportError(f"{target.name!r} is not a portable file name")
    resolved = target.resolve()
    if resolved.is_relative_to(cache_root().resolve()):
        raise ExportError("Choose a destination outside the disposable cache")
    if any(resolved == Path(source).resolve() for source in sources):
        raise ExportError("The destination is a loaded source file")
    if kind.existing is ExistingFile.REFUSE and target.exists():
        raise ExportError(f"{target.name} already exists")


def _sync_file(path: Path) -> None:
    # Windows fsync (_commit) needs a writable descriptor; "rb" raises EBADF there.
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _sync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    handle = os.open(path, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def publish(
    target: Path | str,
    write: Callable[[Path], object],
    *,
    kind: ArtifactKind | str,
    sources: Iterable[Path | str] = (),
) -> Path:
    """Write to a unique sibling, sync it, and atomically publish it.

    A failed writer or failed rename leaves the old destination untouched.
    ``write`` may raise a cancellation exception; cleanup still applies.
    """
    target = Path(target)
    definition = get_kind(kind)
    _validate(target, definition, sources)
    handle, name = tempfile.mkstemp(
        prefix=f".{target.stem}.", suffix=f".tmp{target.suffix}", dir=target.parent
    )
    os.close(handle)
    temporary = Path(name)
    try:
        write(temporary)
        _sync_file(temporary)
        if definition.existing is ExistingFile.REFUSE:
            os.link(temporary, target)
            temporary.unlink()
        else:
            os.replace(temporary, target)
        _sync_directory(target.parent)
    except PermissionError as exc:
        raise ExportError(
            f"{target.name} is in use or cannot be replaced; "
            "close it in the other program and retry"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return target


def publish_dir(
    target: Path | str,
    write: Callable[[Path], object],
    *,
    kind: ArtifactKind | str,
    sources: Iterable[Path | str] = (),
) -> Path:
    """Stage a directory beside its destination, then publish it."""
    import shutil

    target = Path(target)
    definition = get_kind(kind)
    _validate(target, definition, sources)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        write(temporary)
        for root, _directories, files in os.walk(temporary):
            for name in files:
                _sync_file(Path(root) / name)
            _sync_directory(Path(root))
        if target.exists():
            raise ExportError(f"{target.name} already exists; choose another folder")
        os.rename(temporary, target)
        _sync_directory(target.parent)
    except PermissionError as exc:
        raise ExportError(
            f"{target.name} is in use or cannot be replaced; "
            "close it in the other program and retry"
        ) from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target
