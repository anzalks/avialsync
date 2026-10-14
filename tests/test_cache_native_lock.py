"""Verify the native locking boundary without needing a Windows host."""

from __future__ import annotations

import ctypes
import errno
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from avialsync.core import cache_process_lock as native
from avialsync.core.errors import CacheError


class NativeCall:
    """Record native arguments and return the configured Windows status."""

    def __init__(self) -> None:
        self.args: tuple = ()
        self.result = 1

    def __call__(self, *args: object) -> int:
        self.args = args
        return self.result


@pytest.fixture
def windows_api(monkeypatch):
    lock, unlock = NativeCall(), NativeCall()
    error = {"code": 33}
    dll = SimpleNamespace(LockFileEx=lock, UnlockFileEx=unlock)
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(get_osfhandle=lambda fd: fd + 100))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: dll, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error["code"], raising=False)
    monkeypatch.setattr(
        ctypes, "WinError", lambda code: OSError(code, "native failure"), raising=False
    )
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform="win32"))
    native._windows_api.cache_clear()
    yield lock, unlock, error
    native._windows_api.cache_clear()


def test_windows_locks_use_full_handles_and_immediate_shared_or_exclusive_flags(
    windows_api,
) -> None:
    lock, _, _ = windows_api
    assert native._try_lock(7, False)
    assert lock.args[:5] == (107, 1, 0, 1, 0)
    assert native._try_lock(7, True)
    assert lock.args[:5] == (107, 3, 0, 1, 0)
    assert len(lock.argtypes) == 6
    assert lock.argtypes[0] is ctypes.c_void_p


@pytest.mark.parametrize("code", [32, 33, 997])
def test_windows_contention_returns_without_waiting(windows_api, code: int) -> None:
    lock, _, error = windows_api
    lock.result = 0
    error["code"] = code
    assert native._try_lock(7, True) is False


def test_windows_other_failures_are_not_hidden(windows_api) -> None:
    lock, _, error = windows_api
    lock.result = 0
    error["code"] = 5
    with pytest.raises(OSError):
        native._try_lock(7, True)


def test_windows_unlock_uses_the_same_byte_range_and_reports_failures(windows_api) -> None:
    _, unlock, _ = windows_api
    native._unlock(7)
    assert unlock.args[:4] == (107, 0, 1, 0)
    unlock.result = 0
    with pytest.raises(OSError):
        native._unlock(7)


def test_lease_close_is_idempotent_and_releases_the_descriptor(tmp_path: Path) -> None:
    entry = tmp_path / "entry"
    lease = native.ProcessLease.acquire(entry, exclusive=True)
    assert lease is not None
    assert native.ProcessLease.acquire(entry, exclusive=True) is None
    lease.close()
    lease.close()
    again = native.ProcessLease.acquire(entry, exclusive=True)
    assert again is not None
    again.close()


def test_lease_failure_reports_the_storage_cause_and_closes_its_descriptor(
    tmp_path: Path, monkeypatch
) -> None:
    def fail(_descriptor: int, _exclusive: bool) -> bool:
        raise OSError(errno.EIO, "storage failure")

    monkeypatch.setattr(native, "_try_lock", fail)
    with pytest.raises(CacheError) as raised:
        native.ProcessLease.acquire(tmp_path / "entry", exclusive=True)
    assert isinstance(raised.value.__cause__, OSError)
