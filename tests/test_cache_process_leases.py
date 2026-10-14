"""Separate application processes must respect cached reader generations."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

from avialsync.core.cache import CacheManager
from avialsync.core.cache_leases import (
    GenerationPin,
    pin_reader_directory,
    reserve_cache_entry,
    reserve_edited_generation,
)
from avialsync.core.cache_process_lock import ProcessLease
from avialsync.core.cache_store import remove_all
from avialsync.core.edit_cache import prune
from avialsync.core.errors import CacheError
from avialsync.core.pyramid import PyramidBuilder, PyramidReader

_HOLDER = """
import sys
from contextlib import ExitStack
from pathlib import Path
from avialsync.core.cache_leases import GenerationPin, reserve_cache_entry

with ExitStack() as stack:
    path = Path(sys.argv[2])
    if sys.argv[1] == 'reader':
        pin = GenerationPin(path)
        stack.callback(pin.close)
    else:
        assert stack.enter_context(reserve_cache_entry(path))
    print('ready', flush=True)
    sys.stdin.readline()
"""


@contextmanager
def _held_elsewhere(mode: str, directory: Path) -> Iterator[subprocess.Popen[str]]:
    """Hold a lease until the parent releases stdin, with bounded cleanup."""
    process = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, mode, str(directory)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        yield process
    finally:
        try:
            process.communicate(input="\n" if process.poll() is None else None, timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=10)


def _published_entry(tmp_path: Path) -> tuple[CacheManager, Path, Path]:
    source = tmp_path / "source.csv"
    source.write_text("time,signal\n0,1\n", encoding="utf-8")
    manager = CacheManager(root=tmp_path / "cache")
    staging = manager.get_temp_cache_dir(source)
    PyramidBuilder(staging, "signal").build_and_save(np.array([0.0, 1.0]), np.array([1.0, 2.0]))
    manager.commit_cache(source, staging)
    return manager, source, manager.get_cache_dir(source)


def test_reader_in_another_process_blocks_replacement(tmp_path: Path) -> None:
    _, _, entry = _published_entry(tmp_path)
    with _held_elsewhere("reader", entry):
        with reserve_cache_entry(entry) as reserved:
            assert not reserved
    with reserve_cache_entry(entry) as reserved:
        assert reserved


def test_shared_readers_can_coexist_across_processes(tmp_path: Path) -> None:
    _, _, entry = _published_entry(tmp_path)
    with _held_elsewhere("reader", entry):
        pin = pin_reader_directory(entry)
        assert pin is not None
        pin.close()


def test_writer_in_another_process_refuses_new_readers_and_writers(tmp_path: Path) -> None:
    _, _, entry = _published_entry(tmp_path)
    with _held_elsewhere("writer", entry):
        assert pin_reader_directory(entry) is None
        with reserve_cache_entry(entry) as reserved:
            assert not reserved


def test_cache_commit_and_eviction_preserve_another_process_reader(tmp_path: Path) -> None:
    manager, source, entry = _published_entry(tmp_path)
    staging = manager.get_temp_cache_dir(source)
    PyramidBuilder(staging, "signal").build_and_save(np.array([0.0, 1.0]), np.array([9.0, 9.0]))
    with _held_elsewhere("reader", entry):
        with pytest.raises(CacheError, match="in use"):
            manager.commit_cache(source, staging)
        report = remove_all(root=tmp_path / "cache")
        assert any("in use" in reason for _, reason in report.failed)
        assert entry.is_dir()
        np.testing.assert_array_equal(
            PyramidReader(entry, "signal").raw_slice(0.0, 1.0)[1], [1.0, 2.0]
        )
    manager.commit_cache(source, staging)
    np.testing.assert_array_equal(PyramidReader(entry, "signal").raw_slice(0.0, 1.0)[1], [9.0, 9.0])


def test_process_exit_releases_a_reader_lease(tmp_path: Path) -> None:
    _, _, entry = _published_entry(tmp_path)
    with _held_elsewhere("reader", entry) as process:
        process.kill()
        process.wait(timeout=10)
        with reserve_cache_entry(entry) as reserved:
            assert reserved


def test_published_pyramid_reader_holds_its_generation_until_closed(tmp_path: Path) -> None:
    _, _, entry = _published_entry(tmp_path)
    reader = PyramidReader(entry, "signal")
    with reserve_cache_entry(entry) as reserved:
        assert not reserved
    reader.close()
    reader.close()
    with reserve_cache_entry(entry) as reserved:
        assert reserved


def test_reader_reopen_releases_the_previous_entry(tmp_path: Path) -> None:
    _, _, first = _published_entry(tmp_path)
    second_root = tmp_path / "second"
    second_root.mkdir()
    _, _, second = _published_entry(second_root)
    reader = PyramidReader(first, "signal")
    reader.reopen(second)
    with reserve_cache_entry(first) as reserved:
        assert reserved
    with reserve_cache_entry(second) as reserved:
        assert not reserved
    reader.close()


def test_owned_staging_survives_cache_eviction_until_released(tmp_path: Path) -> None:
    manager, source, _ = _published_entry(tmp_path)
    staging = manager.get_temp_cache_dir(source)
    report = remove_all(root=tmp_path / "cache")
    assert staging.is_dir()
    assert any(str(staging) == path for path, _ in report.failed)
    manager.close()
    assert remove_all(root=tmp_path / "cache").removed == 1
    assert not staging.exists()


def test_closed_reader_rejects_reads_and_can_explicitly_reopen(tmp_path: Path) -> None:
    _, _, entry = _published_entry(tmp_path)
    reader = PyramidReader(entry, "signal")
    reader.close()
    with pytest.raises(CacheError, match="closed"):
        reader.coverage()
    reader.reopen(entry)
    assert reader.coverage() == (0.0, 1.0)
    reader.close()


def test_edited_reader_in_another_process_survives_pruning(tmp_path: Path) -> None:
    _, _, entry = _published_entry(tmp_path)
    generation = entry / "edited" / "old-generation"
    generation.mkdir(parents=True)
    (generation / "manifest.json").write_text(
        json.dumps({"marker": "avialsync-edited-tracker", "fingerprint": generation.name}),
        encoding="utf-8",
    )
    with _held_elsewhere("reader", generation):
        assert prune(entry, keep=[], generations=0) == []
        assert generation.is_dir()
    # A base reader does not prevent retiring an unrelated edited generation.
    base_pin = GenerationPin(entry)
    try:
        assert prune(entry, keep=[], generations=0) == [generation.name]
    finally:
        base_pin.close()


def test_retiring_generation_refuses_new_readers_and_base_replacement(tmp_path: Path) -> None:
    _, _, entry = _published_entry(tmp_path)
    generation = entry / "edited" / "retiring"
    generation.mkdir(parents=True)
    with reserve_edited_generation(generation) as reserved:
        assert reserved
        assert pin_reader_directory(generation) is None
        # Use another process to exercise the OS lock rather than local state.
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; "
                "from avialsync.core.cache_leases import reserve_cache_entry; "
                "with_context = reserve_cache_entry(Path(sys.argv[1])); "
                "assert not with_context.__enter__(); with_context.__exit__(None,None,None)",
                str(entry),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert probe.returncode == 0, probe.stderr
    assert not list((entry / "edited").glob(".leases"))


def test_reader_rechecks_existence_after_acquiring_native_lease(
    tmp_path: Path, monkeypatch
) -> None:
    _, _, entry = _published_entry(tmp_path)
    acquire = ProcessLease.acquire

    def retire_then_acquire(directory: Path, *, exclusive: bool) -> ProcessLease | None:
        shutil.rmtree(entry)
        return acquire(directory, exclusive=exclusive)

    monkeypatch.setattr(ProcessLease, "acquire", retire_then_acquire)
    assert pin_reader_directory(entry) is None
    # A failed construction must not retain the just-acquired lease.
    monkeypatch.setattr(ProcessLease, "acquire", acquire)
    with reserve_cache_entry(entry) as reserved:
        assert reserved


def test_worker_delivery_transfers_to_readers_without_filesystem_calls(
    tmp_path: Path, monkeypatch
) -> None:
    from avialsync.core import cache_leases
    from avialsync.core.inspection import SourceInspection
    from avialsync.engine.importer import ImportWorker

    source = tmp_path / "delivery.csv"
    source.write_text("time,value\n0,1\n1,2\n", encoding="utf-8")
    worker = ImportWorker(source, {"time_col": "time", "time_unit": "s", "separator": ","})
    deliveries: list[tuple] = []
    worker.finished.connect(lambda *args: deliveries.append(args))
    worker.run()
    assert len(deliveries) == 1
    _, directory, channels, _, inspection = deliveries[0]
    assert isinstance(inspection, SourceInspection)
    assert inspection.cache_pin is not None
    assert "cache_pin" not in inspection.as_dict()
    assert SourceInspection.from_dict(inspection.as_dict()).cache_pin is None

    def unexpected_io(*_args, **_kwargs):
        raise AssertionError("UI reader construction must clone the worker's lease in memory")

    with monkeypatch.context() as guarded:
        guarded.setattr(ProcessLease, "acquire", unexpected_io)
        guarded.setattr(Path, "is_dir", unexpected_io)
        guarded.setattr("avialsync.core.cache.read_entry_record", unexpected_io)
        reader = PyramidReader(Path(directory), channels[0])
        inspection.release_cache_pin()
        inspection.release_cache_pin()
        assert cache_leases.cache_entry_pinned(Path(directory))
    reader.close()
    with reserve_cache_entry(Path(directory)) as reserved:
        assert reserved
