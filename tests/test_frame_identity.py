"""Ground truth for the one invariant the whole migration rests on.

**The frame displayed for source time ``t`` is the frame whose presentation
interval contains ``t`` — the last frame with ``pts <= t``.**

Every fixture here encodes each frame's own index into its pixels, so identity
is *read back off the decoded image* rather than inferred from a timestamp the
reader also chose.  That distinction is the entire value of this file: a reader
that returns the neighbouring frame still reports a perfectly plausible
timestamp, and only the pixels catch it.

The failure this guards against is not hypothetical.  A reader returning the
first frame with ``pts >= t`` is wrong at *every* scrub position strictly
between two frames — 33 ms of misattribution at 30 fps, enough to pin a
behavioural event to the wrong frame — and it passes any test that probes only
exact frame timestamps.  So each frame is probed three ways: on its own pts,
mid-interval, and a hair before the next frame.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avialsync.core.video_timing import frame_index_at
from avialsync.engine.pyav_reader import PyAVReader, to_rgb_array
from tests.util_framestrip import decode_frame_strip
from tests.util_pyav_fixtures import cfr_times, vfr_times, write_video

pytest.importorskip("av")

FRAME_COUNT = 180


@pytest.fixture(scope="module")
def cfr_video(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, np.ndarray]:
    """A constant-rate long-GOP fixture with B-frames."""
    path = tmp_path_factory.mktemp("identity") / "cfr.mp4"
    times = write_video(path, frame_times=cfr_times(FRAME_COUNT), gop_size=30)
    return path, times


@pytest.fixture(scope="module")
def vfr_video(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, np.ndarray]:
    """A genuinely variable-rate fixture — uneven intervals, not jitter."""
    path = tmp_path_factory.mktemp("identity") / "vfr.mp4"
    times = write_video(path, frame_times=vfr_times(FRAME_COUNT), gop_size=30)
    return path, times


def _probe_times(frame_times: np.ndarray, index: int) -> list[tuple[str, float]]:
    """Return three instants that must all resolve to ``index``.

    The last one sits just below the *next* frame's timestamp, which is the
    position an off-by-one reader gets wrong while still looking right on the
    exact-pts probe.
    """
    start = float(frame_times[index])
    if index + 1 < len(frame_times):
        end = float(frame_times[index + 1])
    else:
        end = start + float(frame_times[index] - frame_times[index - 1])
    return [
        ("exact", start),
        ("mid", start + (end - start) * 0.5),
        ("late", end - (end - start) * 0.01),
    ]


@pytest.mark.parametrize("fixture_name", ["cfr_video", "vfr_video"])
def test_every_probe_decodes_the_frame_whose_interval_contains_it(
    fixture_name: str, request: pytest.FixtureRequest
) -> None:
    """The decoded pixels must name the frame the invariant selects — everywhere."""
    path, written_times = request.getfixturevalue(fixture_name)

    with PyAVReader(path) as reader:
        assert reader.frame_count == FRAME_COUNT
        np.testing.assert_allclose(reader.frame_times, written_times, atol=1e-9)

        for index in range(FRAME_COUNT):
            for label, probe in _probe_times(reader.frame_times, index):
                frame = reader.frame_at_time(probe)
                decoded = decode_frame_strip(to_rgb_array(frame))
                assert decoded == index, (
                    f"{fixture_name} probe '{label}' at t={probe:.6f}s wanted frame "
                    f"{index} but the pixels say {decoded}"
                )


def test_a_first_frame_at_or_after_reader_would_fail_the_mid_interval_probes(
    cfr_video: tuple[Path, np.ndarray],
) -> None:
    """Pin the bug this file exists to catch, so the guard cannot rot silently.

    If someone "simplifies" ``frame_index_at`` into a ``pts >= t`` search, this
    is the arithmetic that changes.  Asserting the wrong answer *is* wrong keeps
    the distinction visible in the test suite rather than only in a comment.
    """
    _, frame_times = cfr_video
    wrong = 0
    for index in range(len(frame_times) - 1):
        _, mid = _probe_times(frame_times, index)[1]
        first_at_or_after = int(np.searchsorted(frame_times, mid, side="left"))
        if first_at_or_after != frame_index_at(frame_times, mid):
            wrong += 1
    assert wrong == len(frame_times) - 1, (
        "a first-frame-at-or-after reader must be wrong at every mid-interval "
        "probe; if it is not, the fixture stopped exercising the distinction"
    )


def test_lookups_are_keyed_by_index_so_nearby_scrub_positions_cannot_collide(
    cfr_video: tuple[Path, np.ndarray],
) -> None:
    """Two probes inside one interval are one cache entry, not two near-misses."""
    path, _ = cfr_video
    with PyAVReader(path) as reader:
        interval = float(reader.frame_times[41] - reader.frame_times[40])
        early = float(reader.frame_times[40]) + interval * 0.1
        late = float(reader.frame_times[40]) + interval * 0.9

        assert reader.index_at_time(early) == reader.index_at_time(late) == 40
        assert reader.frame_at_time(early) is reader.frame_at_time(late)


def test_seeking_backwards_still_lands_on_the_exact_frame(
    cfr_video: tuple[Path, np.ndarray],
) -> None:
    """A backward jump must re-seek rather than trust the decoder's position."""
    path, _ = cfr_video
    with PyAVReader(path, max_cached_frames=2) as reader:
        for index in (170, 3, 120, 61, 0, 179, 44):
            frame = reader.frame_at_index(index)
            assert decode_frame_strip(to_rgb_array(frame)) == index


def test_times_outside_the_stream_clamp_instead_of_raising(
    cfr_video: tuple[Path, np.ndarray],
) -> None:
    """Master time runs past a short source; that is a normal session, not an error."""
    path, _ = cfr_video
    with PyAVReader(path) as reader:
        assert decode_frame_strip(to_rgb_array(reader.frame_at_time(-5.0))) == 0
        assert decode_frame_strip(to_rgb_array(reader.frame_at_time(1e6))) == FRAME_COUNT - 1
