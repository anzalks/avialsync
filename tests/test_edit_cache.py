"""The edited tracker is a derived cache generation, never a rewrite (D-142).

What these pin down is the boundary: the recording and its imported pyramid are
read-only, the edits produce a separate generation holding only the channels
they changed, and a consumer reading through it sees the corrected identities
without knowing that flips exist.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from avialsync.core import edit_cache
from avialsync.core.edit_program import build as build_program
from avialsync.core.identity_groups import ANIMALS, groups_for_schema
from avialsync.core.identity_swaps import SwapEvent, SwapStore
from avialsync.core.point_edits import PointEditStore, PointKey
from avialsync.core.pose import PosePoint, PoseSchema
from avialsync.core.pyramid import PyramidBuilder, PyramidReader

SOURCE = "/data/twomice_DLC.csv"
FRAMES = 200
FLIP = 50

SCHEMA = PoseSchema(
    points=tuple(
        PosePoint(individual=individual, bodypart=part, axes=("x", "y"), has_likelihood=True)
        for individual in ("testMouse", "conSpecific")
        for part in ("snout", "wrist")
    ),
    frame_indexed=True,
)


def _import(cache_dir: Path) -> dict[str, np.ndarray]:
    """Write a raw cache whose every channel holds a distinguishable ramp."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    times = np.arange(FRAMES, dtype=np.float64) / 30.0
    written: dict[str, np.ndarray] = {}
    for offset, point in enumerate(SCHEMA.points):
        for axis_index, axis in enumerate(("x", "y")):
            values = np.arange(FRAMES, dtype=np.float64) + 1000.0 * offset + 10.0 * axis_index
            PyramidBuilder(cache_dir, point.channel(axis)).build_and_save(times, values)
            written[point.channel(axis)] = values
        likelihood = np.full(FRAMES, 0.25 + 0.1 * offset, dtype=np.float64)
        channel = point.likelihood_channel
        assert channel is not None
        PyramidBuilder(cache_dir, channel).build_and_save(times, likelihood)
        written[channel] = likelihood
    return written


def _stores() -> tuple[SwapStore, PointEditStore]:
    swaps = SwapStore()
    swaps.set_groups(SOURCE, groups_for_schema(SCHEMA))
    return swaps, PointEditStore()


def _values(directory: Path, channel: str) -> np.ndarray:
    return np.array(PyramidReader(directory, channel).mapped_columns()[1])


def test_a_flip_makes_one_point_read_the_other_from_that_frame(tmp_path: Path) -> None:
    cache = tmp_path / "pose.csv.avialcache"
    raw = _import(cache)
    swaps, edits = _stores()
    swaps.add(SOURCE, SwapEvent(FLIP, ANIMALS, ("testMouse", "conSpecific")))

    program = build_program(SOURCE, swaps, edits)
    edited = edit_cache.materialise(cache, program, SCHEMA)

    shown = _values(edited.dir_for(cache, "testMouse_snout_x"), "testMouse_snout_x")
    assert np.array_equal(shown[:FLIP], raw["testMouse_snout_x"][:FLIP])
    assert np.array_equal(shown[FLIP:], raw["conSpecific_snout_x"][FLIP:])


def test_the_original_cache_is_not_written(tmp_path: Path) -> None:
    cache = tmp_path / "pose.csv.avialcache"
    raw = _import(cache)
    before = {path.name: path.stat().st_mtime_ns for path in cache.glob("*.npy")}
    swaps, edits = _stores()
    swaps.add(SOURCE, SwapEvent(FLIP, ANIMALS, ("testMouse", "conSpecific")))

    edit_cache.materialise(cache, build_program(SOURCE, swaps, edits), SCHEMA)

    assert {path.name: path.stat().st_mtime_ns for path in cache.glob("*.npy")} == before
    assert np.array_equal(_values(cache, "testMouse_snout_x"), raw["testMouse_snout_x"])


def test_only_the_channels_a_flip_changed_are_materialised(tmp_path: Path) -> None:
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    swaps, edits = _stores()
    swaps.add(
        SOURCE,
        SwapEvent(FLIP, ANIMALS, ("testMouse", "conSpecific"), parts=("snout",)),
    )

    edited = edit_cache.materialise(cache, build_program(SOURCE, swaps, edits), SCHEMA)

    assert "testMouse_snout_x" in edited.channels
    assert "testMouse_wrist_x" not in edited.channels
    # And an untouched channel is read from the original arrays, not a copy.
    assert edited.dir_for(cache, "testMouse_wrist_x") == cache


def test_a_correction_follows_the_column_it_was_made_on(tmp_path: Path) -> None:
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    swaps, edits = _stores()
    swaps.add(SOURCE, SwapEvent(FLIP, ANIMALS, ("testMouse", "conSpecific")))
    # Corrected in the file's own columns: after the flip this trajectory is
    # what testMouse displays, so that is where the corrected coordinate shows.
    edits.set(PointKey(SOURCE, "conSpecific_snout", 60), (7.5, 8.5))

    edited = edit_cache.materialise(cache, build_program(SOURCE, swaps, edits), SCHEMA)

    shown_x = _values(edited.dir_for(cache, "testMouse_snout_x"), "testMouse_snout_x")
    shown_y = _values(edited.dir_for(cache, "testMouse_snout_y"), "testMouse_snout_y")
    assert shown_x[60] == 7.5
    assert shown_y[60] == 8.5


def test_a_corrected_coordinate_is_not_left_at_the_models_low_confidence(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    swaps, edits = _stores()
    edits.set(PointKey(SOURCE, "testMouse_snout", 12), (1.0, 2.0))

    edited = edit_cache.materialise(cache, build_program(SOURCE, swaps, edits), SCHEMA)

    channel = "testMouse_snout_likelihood"
    likelihood = _values(edited.dir_for(cache, channel), channel)
    assert likelihood[12] == edit_cache.CORRECTED_LIKELIHOOD
    assert likelihood[11] < 1.0


def test_an_unedited_source_materialises_nothing(tmp_path: Path) -> None:
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    swaps, edits = _stores()

    edited = edit_cache.materialise(cache, build_program(SOURCE, swaps, edits), SCHEMA)

    assert not edited
    assert edited.dir_for(cache, "testMouse_snout_x") == cache
    assert not (cache / edit_cache.EDITED_DIR).exists()


def test_reopening_the_same_edits_reuses_the_generation(tmp_path: Path) -> None:
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    swaps, edits = _stores()
    swaps.add(SOURCE, SwapEvent(FLIP, ANIMALS, ("testMouse", "conSpecific")))
    program = build_program(SOURCE, swaps, edits)

    first = edit_cache.materialise(cache, program, SCHEMA)
    stamp = (first.directory / "manifest.json").stat().st_mtime_ns
    second = edit_cache.materialise(cache, program, SCHEMA)

    assert second.directory == first.directory
    assert second.channels == first.channels
    assert (second.directory / "manifest.json").stat().st_mtime_ns == stamp


def test_prune_removes_our_old_generations_and_nothing_else(tmp_path: Path) -> None:
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    swaps, edits = _stores()
    swaps.add(SOURCE, SwapEvent(FLIP, ANIMALS, ("testMouse", "conSpecific")))
    first = edit_cache.materialise(cache, build_program(SOURCE, swaps, edits), SCHEMA)
    swaps.add(SOURCE, SwapEvent(120, ANIMALS, ("testMouse", "conSpecific")))
    second = edit_cache.materialise(cache, build_program(SOURCE, swaps, edits), SCHEMA)

    stranger = cache / edit_cache.EDITED_DIR / "somebody_elses_folder"
    stranger.mkdir(parents=True)
    (stranger / "keep_me.txt").write_text("not ours", encoding="utf-8")

    removed = edit_cache.prune(cache, keep=[second.fingerprint])

    assert removed == [first.fingerprint]
    assert not first.directory.exists()
    assert second.directory.exists()
    assert (stranger / "keep_me.txt").exists()


def test_a_generation_says_what_it_is(tmp_path: Path) -> None:
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    swaps, edits = _stores()
    swaps.add(SOURCE, SwapEvent(FLIP, ANIMALS, ("testMouse", "conSpecific")))
    program = build_program(SOURCE, swaps, edits)
    edited = edit_cache.materialise(cache, program, SCHEMA)

    manifest = json.loads((edited.directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fingerprint"] == program.fingerprint
    assert edit_cache.load(cache, program.fingerprint) == edited
    assert edit_cache.load(cache, "0000000000000000") is None
