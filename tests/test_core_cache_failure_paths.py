"""Cache contention and storage failure keep ownership and previous data coherent."""

from __future__ import annotations

import errno
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from avialsync.core import cache, cache_leases, cache_process_lock
from avialsync.core.cache import CacheManager, read_entry_record
from avialsync.core.cache_leases import (
    GenerationPin,
    cache_entry_mutating,
    pin_published_reader,
    reserve_cache_entry,
    reserve_edited_generation,
)
from avialsync.core.errors import CacheError
from tests.test_cache_process_leases import _held_elsewhere, _published_entry


def test_published_reader_and_validation_refuse_an_external_writer(tmp_path: Path) -> None:
    manager, source, entry = _published_entry(tmp_path)
    with _held_elsewhere("writer", entry):
        assert not manager.is_cache_valid(source)
        with pytest.raises(CacheError, match="in use"):
            pin_published_reader(entry)


def test_missing_entry_recovery_is_nonblocking_under_external_ownership(tmp_path: Path) -> None:
    entry = tmp_path / "cache" / "sources" / "missing"
    with _held_elsewhere("writer", entry):
        CacheManager._recover_interrupted_swap(entry)
        assert not entry.exists()


def test_active_staging_is_not_treated_as_a_published_reader(tmp_path: Path) -> None:
    manager, source, _ = _published_entry(tmp_path)
    staging = manager.get_temp_cache_dir(source)
    assert pin_published_reader(staging) is None
    manager.close()


def test_local_reservations_refuse_new_pins_and_nested_mutation(tmp_path: Path) -> None:
    _, _, entry = _published_entry(tmp_path)
    with reserve_cache_entry(entry) as reserved:
        assert reserved and cache_entry_mutating(entry)
        with pytest.raises(FileNotFoundError):
            GenerationPin(entry)
    assert not cache_entry_mutating(entry)
    with pytest.raises(ValueError, match="edited"):
        with reserve_edited_generation(entry):
            pass


def test_new_stage_lease_failure_is_reported(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.csv"
    source.write_text("source", encoding="utf-8")
    manager = CacheManager(root=tmp_path / "cache")
    monkeypatch.setattr(cache.ProcessLease, "acquire", lambda *args, **kwargs: None)
    with pytest.raises(CacheError, match="staging"):
        manager.get_temp_cache_dir(source)


def test_generation_reservation_releases_earlier_leases_on_native_error(
    tmp_path: Path, monkeypatch
) -> None:
    _, _, entry = _published_entry(tmp_path)
    generation = entry / "edited" / "generation"
    generation.mkdir(parents=True)
    acquire = cache_leases.ProcessLease.acquire

    def fail_second(directory: Path, *, exclusive: bool):
        if directory == generation:
            raise CacheError("storage failed")
        return acquire(directory, exclusive=exclusive)

    with monkeypatch.context() as patch:
        patch.setattr(cache_leases.ProcessLease, "acquire", fail_second)
        with pytest.raises(CacheError, match="storage failed"):
            with reserve_edited_generation(generation):
                pass
    with reserve_cache_entry(entry) as reserved:
        assert reserved


def test_other_native_posix_errors_are_not_treated_as_contention(monkeypatch) -> None:
    def invalid_descriptor(*_args) -> None:
        raise OSError(errno.EBADF, "invalid descriptor")

    monkeypatch.setitem(
        sys.modules,
        "fcntl",
        SimpleNamespace(
            flock=invalid_descriptor,
            LOCK_EX=1,
            LOCK_SH=2,
            LOCK_NB=4,
            LOCK_UN=8,
        ),
    )
    monkeypatch.setattr(cache_process_lock, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(OSError) as failure:
        cache_process_lock._try_lock(999, True)
    assert failure.value.errno == errno.EBADF


def test_invalid_entry_record_is_not_a_managed_entry(tmp_path: Path) -> None:
    (tmp_path / cache.ENTRY_RECORD).write_text('{"marker":"another application"}')
    assert read_entry_record(tmp_path) is None


def test_access_record_failure_is_informational(tmp_path: Path, monkeypatch) -> None:
    manager, source, _ = _published_entry(tmp_path)

    def inaccessible(*_args, **_kwargs) -> None:
        raise PermissionError("read only")

    monkeypatch.setattr(cache.os, "utime", inaccessible)
    manager.record_access(source)


def test_edited_carry_and_backup_recovery_fail_without_destroying_old_data(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "entry"
    backup = tmp_path / ".entry.backup-fixture"
    (backup / "edited").mkdir(parents=True)
    (backup / "edited" / "keep").write_text("old data")

    def unavailable(*_args) -> None:
        raise PermissionError("held by another program")

    monkeypatch.setattr(cache.os, "rename", unavailable)
    CacheManager._carry_edited(backup, entry)
    assert (backup / "edited" / "keep").read_text() == "old data"
    monkeypatch.setattr(cache.os, "replace", unavailable)
    CacheManager._recover_interrupted_swap(entry)
    assert backup.is_dir() and not entry.exists()
