"""The edited tracker is a derived cache generation, never a rewrite (D-142).

What these pin down is the boundary: the recording and its imported pyramid are
read-only, the edits produce a separate generation holding only the channels
they changed, and a consumer reading through it sees the corrected identities
without knowing that flips exist.
"""

from __future__ import annotations

import json
import os
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
    made = []
    for index in (FLIP, 120, 140, 160):
        swaps.add(SOURCE, SwapEvent(index, ANIMALS, ("testMouse", "conSpecific")))
        made.append(edit_cache.materialise(cache, build_program(SOURCE, swaps, edits), SCHEMA))
        os.utime(made[-1].directory, (index, index))
    first, newest = made[0], made[-1]

    stranger = cache / edit_cache.EDITED_DIR / "somebody_elses_folder"
    stranger.mkdir(parents=True)
    (stranger / "keep_me.txt").write_text("not ours", encoding="utf-8")

    removed = edit_cache.prune(cache, keep=[newest.fingerprint])

    assert removed == [first.fingerprint]
    assert not first.directory.exists()
    assert newest.directory.exists()
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


def test_prune_never_removes_a_generation_being_written(tmp_path: Path) -> None:
    """A rebuild in flight is not rubbish left behind by an old one.

    Every edit starts a job, and a person dragging points starts several. The
    first to finish prunes; if that sweep can reach another job's staging
    directory, the other job dies half-written with a FileNotFoundError from
    inside numpy, and the edit it was applying is silently lost.
    """
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    swaps, edits = _stores()
    swaps.add(SOURCE, SwapEvent(FLIP, ANIMALS, ("testMouse", "conSpecific")))
    done = edit_cache.materialise(cache, build_program(SOURCE, swaps, edits), SCHEMA)

    in_flight = cache / edit_cache.EDITED_DIR / ".tmp_another_job"
    in_flight.mkdir(parents=True)
    (in_flight / "half_written.npy").write_bytes(b"\x00")

    removed = edit_cache.prune(cache, keep=[done.fingerprint])

    assert in_flight.exists()
    assert (in_flight / "half_written.npy").exists()
    assert removed == []


def test_two_rebuilds_of_the_same_edits_do_not_share_a_staging_directory(
    tmp_path: Path,
) -> None:
    """Two jobs for one fingerprint must not write into one directory."""
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    swaps, edits = _stores()
    swaps.add(SOURCE, SwapEvent(FLIP, ANIMALS, ("testMouse", "conSpecific")))
    program = build_program(SOURCE, swaps, edits)

    first = edit_cache.materialise(cache, program, SCHEMA, rebuild=True)
    second = edit_cache.materialise(cache, program, SCHEMA, rebuild=True)

    assert first.directory == second.directory
    assert second.channels
    # Nothing of either run is left behind in the staging area.
    leftovers = [
        entry.name
        for entry in (cache / edit_cache.EDITED_DIR).iterdir()
        if entry.name.startswith(".tmp_")
    ]
    assert leftovers == []


def test_prune_leaves_recent_generations_for_readers_still_on_them(tmp_path: Path) -> None:
    """A reader holds a path, not a subscription.

    The braid is built from a snapshot of where each channel lives, in a job
    that runs while the person keeps editing. Pruning to the newest generation
    alone deleted the directory that job was reading, and it died with a
    FileNotFoundError out of numpy instead of drawing anything.
    """
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    swaps, edits = _stores()
    directories = []
    for index in (30, 60, 90, 110):
        swaps.add(SOURCE, SwapEvent(index, ANIMALS, ("testMouse", "conSpecific")))
        made = edit_cache.materialise(cache, build_program(SOURCE, swaps, edits), SCHEMA)
        directories.append(made)
        os.utime(made.directory, (index, index))

    newest = directories[-1]
    edit_cache.prune(cache, keep=[newest.fingerprint])

    kept = {entry.name for entry in (cache / edit_cache.EDITED_DIR).iterdir()}
    assert newest.directory.name in kept
    # The one before it, and the one before that: a job two edits behind still
    # finds its files.
    assert directories[-2].directory.name in kept
    assert directories[-3].directory.name in kept
    assert directories[0].directory.name not in kept


def test_a_braid_channel_that_vanished_does_not_take_the_whole_plot_with_it(
    tmp_path: Path,
) -> None:
    """Defence in depth behind the keep window, not a substitute for it."""
    from avialsync.ui.identity_model_worker import _values

    class _Job:
        directories = {"testMouse_snout_x": tmp_path / "not-a-generation"}

    assert len(_values(_Job(), "testMouse_snout_x")) == 0
    assert len(_values(_Job(), "unknown_channel_x")) == 0


def test_a_job_that_finds_its_generation_already_committed_leaves_it_alone(
    tmp_path: Path, monkeypatch
) -> None:
    """Two jobs for one fingerprint, both started before either committed.

    The first commits and its readers start painting from it. The second used to
    ``rmtree`` the committed directory before moving its own copy in, so a
    reader that loaded ``_t.npy`` then found ``_v.npy`` gone -- the field
    traceback, and from there a native crash in the overlay's paint.
    """
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    swaps, edits = _stores()
    swaps.add(SOURCE, SwapEvent(FLIP, ANIMALS, ("testMouse", "conSpecific")))
    program = build_program(SOURCE, swaps, edits)

    committed = edit_cache.materialise(cache, program, SCHEMA)
    reader = PyramidReader(committed.dir_for(cache, "testMouse_snout_y"), "testMouse_snout_y")

    removed: list[Path] = []
    original_remove = edit_cache._remove_generation
    monkeypatch.setattr(
        edit_cache,
        "_remove_generation",
        lambda directory: (removed.append(directory), original_remove(directory)),
    )
    # The second job looked before the first had committed.
    real_load = edit_cache.load
    calls = iter([None])
    monkeypatch.setattr(
        edit_cache,
        "load",
        lambda cache_dir, fingerprint: next(calls, real_load(cache_dir, fingerprint)),
    )

    again = edit_cache.materialise(cache, program, SCHEMA)

    assert committed.directory not in removed
    assert again.directory == committed.directory
    assert again.channels == committed.channels
    assert len(reader.mapped_columns()[1]) == FRAMES


def test_an_explicit_rebuild_never_leaves_a_file_missing(tmp_path: Path, monkeypatch) -> None:
    """A rebuild swaps files in place; it does not delete the directory first."""
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    swaps, edits = _stores()
    swaps.add(SOURCE, SwapEvent(FLIP, ANIMALS, ("testMouse", "conSpecific")))
    program = build_program(SOURCE, swaps, edits)
    committed = edit_cache.materialise(cache, program, SCHEMA)
    names = {entry.name for entry in committed.directory.iterdir()}

    seen_missing: list[str] = []
    real_replace = os.replace

    def watching_replace(src: Path, dst: Path) -> None:
        present = (
            {entry.name for entry in committed.directory.iterdir()}
            if committed.directory.exists()
            else set()
        )
        seen_missing.extend(sorted(names - present))
        real_replace(src, dst)

    monkeypatch.setattr(edit_cache.os, "replace", watching_replace)
    rebuilt = edit_cache.materialise(cache, program, SCHEMA, rebuild=True)

    assert seen_missing == []
    assert {entry.name for entry in rebuilt.directory.iterdir()} == names


def test_a_generation_built_on_an_older_import_is_rebuilt_not_reused(tmp_path: Path) -> None:
    """A generation is a function of the edits *and* the base it edited.

    It was found by the edits' fingerprint alone, so once a re-import kept it
    (a frame rate learned from the camera re-dates every sample), the same
    edits would have kept showing the old timing indefinitely.
    """
    cache = tmp_path / "pose.csv.avialcache"
    _import(cache)
    (cache / "meta.json").write_text('{"fps": 30}', encoding="utf-8")
    swaps, edits = _stores()
    swaps.add(SOURCE, SwapEvent(FLIP, ANIMALS, ("testMouse", "conSpecific")))
    program = build_program(SOURCE, swaps, edits)
    edit_cache.materialise(cache, program, SCHEMA)
    assert edit_cache.load(cache, program.fingerprint) is not None

    (cache / "meta.json").write_text('{"fps": 59.94}', encoding="utf-8")

    assert edit_cache.load(cache, program.fingerprint) is None
    rebuilt = edit_cache.materialise(cache, program, SCHEMA)
    assert rebuilt.channels
    assert edit_cache.load(cache, program.fingerprint) is not None
