"""AOL loaders honour the frozen ingest contract across batch boundaries (V-15, V-05).

`core/source.py` requires that chunks, *including their boundaries*, are globally
chronological and that duplicate timestamps keep the final value. `CSVLoader`
carries the last row across batches to achieve that; the AOL loaders must too. A
backward jump or duplicate that straddles a batch boundary was previously
accepted silently, which is worse than one inside a batch — it is invisible.

V-05: the per-channel compatibility path also projects only the column it was
asked for, so a caller looping over 15 channels does not read 45 columns each
time.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import avialsync.loaders.aol_eks_loader as eks_module
from avialsync.core.errors import NonMonotonicTimeError
from avialsync.loaders.aol_eks_loader import AOLEksLoader

HEADER = "nose_x,nose_y,nose_z,nose_error,tail_x,tail_y,tail_z,tail_error,fnum"


def _row(frame: int, value: float) -> str:
    return f"{value},{value},{value},0.1,{value},{value},{value},0.1,{frame}"


def _write(path: Path, frames: list[int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [_row(frame, float(index)) for index, frame in enumerate(frames)]
    path.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def tiny_batches(monkeypatch) -> int:
    """Shrink the batch size so a boundary is reachable in a small fixture."""
    monkeypatch.setattr(eks_module, "_BATCH_SIZE", 4)
    return 4


# ── V-15: chronology across the boundary ──────────────────────────────


def test_backward_frame_across_a_batch_boundary_is_rejected(
    tmp_path: Path, tiny_batches: int
) -> None:
    """Frame 3 follows frame 9 across the boundary; that must not pass silently."""
    path = _write(tmp_path / "_eks.csv", [0, 1, 2, 9, 3, 4, 5, 6])
    loader = AOLEksLoader()
    loader.open(path, {"fps": 100.0})

    with pytest.raises(NonMonotonicTimeError):
        list(loader.read_all_chunks())


def test_backward_frame_inside_a_batch_is_rejected(tmp_path: Path, tiny_batches: int) -> None:
    """The in-batch case must behave identically — same guarantee, same error."""
    path = _write(tmp_path / "_eks.csv", [0, 5, 2, 6])
    loader = AOLEksLoader()
    loader.open(path, {"fps": 100.0})

    with pytest.raises(NonMonotonicTimeError):
        list(loader.read_all_chunks())


def test_duplicate_frame_across_a_batch_boundary_keeps_the_final_value(
    tmp_path: Path, tiny_batches: int
) -> None:
    """The contract says a duplicate timestamp keeps the last value, not the first."""
    path = _write(tmp_path / "_eks.csv", [0, 1, 2, 3, 3, 4, 5, 6])
    loader = AOLEksLoader()
    loader.open(path, {"fps": 100.0})

    times, values = _collect(loader, "nose_x")

    assert np.all(np.diff(times) > 0), "a duplicate survived the boundary"
    # Rows 3 and 4 both carry frame 3, with values 3.0 and 4.0; the later wins.
    frame_3 = values[np.isclose(times, 3 / 100.0)]
    assert frame_3.tolist() == [4.0]


def test_every_row_survives_a_clean_boundary(tmp_path: Path, tiny_batches: int) -> None:
    """Carrying a pending row must not drop or duplicate it."""
    frames = list(range(10))
    path = _write(tmp_path / "_eks.csv", frames)
    loader = AOLEksLoader()
    loader.open(path, {"fps": 100.0})

    times, values = _collect(loader, "nose_x")

    assert len(times) == len(frames)
    assert values.tolist() == [float(i) for i in range(len(frames))]


def _collect(loader: AOLEksLoader, channel: str) -> tuple[np.ndarray, np.ndarray]:
    times: list[np.ndarray] = []
    values: list[np.ndarray] = []
    for chunk in loader.read_all_chunks():
        t, v = chunk[channel]
        times.append(t)
        values.append(v)
    return np.concatenate(times), np.concatenate(values)


# ── V-05: the per-channel path projects one column ────────────────────


def test_read_chunks_projects_only_the_requested_channel(tmp_path: Path, monkeypatch) -> None:
    """A 15-channel file must not read 45 columns to answer for one."""
    path = _write(tmp_path / "_eks.csv", [0, 1, 2, 3])
    loader = AOLEksLoader()
    loader.open(path, {"fps": 100.0})

    projected: list[list[str]] = []
    original_select = eks_module.pl.LazyFrame.select

    def record(self, columns):
        projected.append(list(columns))
        return original_select(self, columns)

    monkeypatch.setattr(eks_module.pl.LazyFrame, "select", record)
    list(loader.read_chunks("nose_x"))

    assert projected, "the scan never ran"
    assert projected[0] == ["nose_x", "fnum"]


def test_read_chunks_still_returns_the_same_data_as_the_bulk_path(tmp_path: Path) -> None:
    """Projection is an optimisation; it must not change a single sample."""
    path = _write(tmp_path / "_eks.csv", [0, 1, 2, 3, 4])
    loader = AOLEksLoader()
    loader.open(path, {"fps": 100.0})

    bulk_t, bulk_v = _collect(loader, "nose_y")
    single = list(loader.read_chunks("nose_y"))
    single_t = np.concatenate([t for t, _ in single])
    single_v = np.concatenate([v for _, v in single])

    assert np.array_equal(single_t, bulk_t)
    assert np.array_equal(single_v, bulk_v)


def test_read_all_chunks_defaults_to_every_channel(tmp_path: Path) -> None:
    path = _write(tmp_path / "_eks.csv", [0, 1, 2])
    loader = AOLEksLoader()
    loader.open(path, {"fps": 100.0})

    chunk = next(iter(loader.read_all_chunks()))

    assert {"nose_x", "nose_y", "nose_z", "tail_x", "tail_y", "tail_z"} <= set(chunk)


def test_requesting_an_unknown_channel_names_the_real_ones(tmp_path: Path) -> None:
    from avialsync.core.errors import MissingColumnError

    path = _write(tmp_path / "_eks.csv", [0, 1])
    loader = AOLEksLoader()
    loader.open(path, {"fps": 100.0})

    with pytest.raises(MissingColumnError) as excinfo:
        list(loader.read_chunks("elbow_x"))

    assert "nose_x" in excinfo.value.available
