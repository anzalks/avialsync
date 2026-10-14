"""Nonblocking shared/exclusive cache leases released by the operating system.

Lock files live beside entries and retain their inodes across eviction. Removing
them while a reader holds a lock would let another process lock a different
inode for the same entry. The files contain no recording or authored data.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Protocol, cast

from avialsync.core.errors import CacheError


class _WindowsCtypes(Protocol):
    """Windows stdlib symbols absent from the POSIX typeshed view of ctypes."""

    def WinDLL(self, name: str, *, use_last_error: bool) -> ctypes.CDLL: ...
    def get_last_error(self) -> int: ...
    def WinError(self, code: int) -> OSError: ...


class _WindowsMsvcrt(Protocol):
    """The Windows CRT handle accessor, called only on Windows."""

    def get_osfhandle(self, descriptor: int) -> int: ...


class _Overlapped(ctypes.Structure):
    """The native Windows byte-range lock offset, valid on 32/64-bit Python."""

    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", ctypes.c_uint32),
        ("OffsetHigh", ctypes.c_uint32),
        ("hEvent", ctypes.c_void_p),
    ]


@lru_cache(maxsize=1)
def _windows_api() -> ctypes.CDLL:
    library = cast(_WindowsCtypes, ctypes).WinDLL("kernel32", use_last_error=True)
    library.LockFileEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(_Overlapped),
    ]
    library.LockFileEx.restype = ctypes.c_int
    library.UnlockFileEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(_Overlapped),
    ]
    library.UnlockFileEx.restype = ctypes.c_int
    return library


def _windows_lock(descriptor: int, exclusive: bool) -> bool:
    import msvcrt

    flags = 0x1 | (0x2 if exclusive else 0)  # FAIL_IMMEDIATELY, EXCLUSIVE_LOCK.
    acquired = _windows_api().LockFileEx(
        cast(_WindowsMsvcrt, msvcrt).get_osfhandle(descriptor),
        flags,
        0,
        1,
        0,
        ctypes.byref(_Overlapped()),
    )
    if acquired:
        return True
    native = cast(_WindowsCtypes, ctypes)
    code = native.get_last_error()
    if code in {32, 33, 997}:  # sharing/lock violation, or an unavailable async lock.
        return False
    raise native.WinError(code)


def _try_lock(descriptor: int, exclusive: bool) -> bool:
    if sys.platform == "win32":
        return _windows_lock(descriptor, exclusive)
    import fcntl

    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    try:
        fcntl.flock(descriptor, mode | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EAGAIN}:
            return False
        raise
    return True


def _unlock(descriptor: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        if not _windows_api().UnlockFileEx(
            cast(_WindowsMsvcrt, msvcrt).get_osfhandle(descriptor),
            0,
            1,
            0,
            ctypes.byref(_Overlapped()),
        ):
            native = cast(_WindowsCtypes, ctypes)
            raise native.WinError(native.get_last_error())
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


class ProcessLease:
    """One OS-backed lease, retained until its last local reader releases it."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor: int | None = descriptor

    @classmethod
    def acquire(cls, directory: Path, *, exclusive: bool) -> ProcessLease | None:
        """Acquire without waiting, returning None when another owner holds it."""
        from avialsync.core.cache import EDITED_SUBDIR, SOURCES_DIR

        edited = directory.parent.name == EDITED_SUBDIR
        owner = directory.parent.parent if edited else directory
        name = f"{owner.name}/{EDITED_SUBDIR}/{directory.name}" if edited else owner.name
        identity = hashlib.sha256(os.fsencode(os.path.normcase(name))).hexdigest()
        root = owner.parent.parent if owner.parent.name == SOURCES_DIR else owner.parent
        lock_path = root / ".leases" / f"{identity}.lock"
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                if _try_lock(descriptor, exclusive):
                    return cls(descriptor)
            except BaseException:
                os.close(descriptor)
                raise
            os.close(descriptor)
            return None
        except OSError as error:
            raise CacheError("The cache could not acquire a generation lease") from error

    def close(self) -> None:
        """Release immediately; process exit also releases a retained lease."""
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is not None:
            try:
                _unlock(descriptor)
            finally:
                os.close(descriptor)
