"""One cache folder for everything derived, and nothing else in it (D-160).

The cache moved out of the user's data folders into one per-user root, so that
deleting a single folder resets everything AvialSync can rebuild.  These pin
the three properties that make that safe:

* nothing derived is written beside a recording any more;
* removal deletes only directories this package wrote, inside the cache root;
* what is *not* derived -- corrections, swaps, markers, props, accepted sync
  mappings -- stays beside the data or the session, outside the root.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from avialsync.core import cache_store, sidecar_names
from avialsync.core.cache import (
    CACHE_DIR_ENV,
    ENTRY_RECORD,
    SOURCES_DIR,
    CacheManager,
    cache_dir_for,
    cache_root,
    entry_name,
    read_entry_record,
)
from avialsync.core.custom_markers import marker_file_for
from avialsync.core.identity_sidecar import sidecar_path as swap_path
from avialsync.core.point_edit_sidecar import sidecar_path as correction_path
from avialsync.core.prop_file import prop_path
from avialsync.core.session import SessionState, SyncProvenance, exact_mapping_dir


def _entry(root: Path, source: Path, payload: str = "x" * 100) -> Path:
    """Commit a minimal entry for *source* under *root*; return its directory."""
    manager = CacheManager(loader_version=1, root=root)
    staging = manager.get_temp_cache_dir(source)
    (staging / "a_v.npy").write_text(payload, encoding="utf-8")
    manager.commit_cache(source, staging)
    return manager.get_cache_dir(source)


def _source(folder: Path, name: str = "signal.csv") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("t,x\n0,1\n", encoding="utf-8")
    return path


# ── where the root is ────────────────────────────────────────────────


def test_the_environment_variable_overrides_the_platform_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "scratch"))
    assert cache_root() == tmp_path / "scratch"


@pytest.mark.parametrize(
    ("platform", "expected_tail"),
    [
        ("darwin", ("Library", "Caches", "avialsync")),
        ("linux", (".cache", "avialsync")),
    ],
)
def test_the_default_root_is_the_platform_user_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, expected_tail: tuple[str, ...]
) -> None:
    monkeypatch.delenv(CACHE_DIR_ENV, raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert cache_root() == tmp_path.joinpath(*expected_tail)


def test_windows_uses_local_app_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(CACHE_DIR_ENV, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert cache_root() == tmp_path / "Local" / "avialsync" / "Cache"


def test_linux_honours_an_absolute_xdg_cache_home_and_ignores_a_relative_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(CACHE_DIR_ENV, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert cache_root() == tmp_path / "xdg" / "avialsync"
    monkeypatch.setenv("XDG_CACHE_HOME", "relative/cache")
    assert cache_root() == tmp_path / ".cache" / "avialsync"


def test_the_suite_never_writes_into_the_real_user_cache() -> None:
    """conftest points the root at a temporary folder for the whole run."""
    assert os.environ.get(CACHE_DIR_ENV)
    assert cache_root() == Path(os.environ[CACHE_DIR_ENV])


# ── how an entry is named ───────────────────────────────────────────


def test_one_source_gets_one_entry_however_it_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dropped with a folder, opened alone or restored: one file, one entry."""
    source = _source(tmp_path / "trial")
    monkeypatch.chdir(tmp_path)
    relative = Path("trial") / "signal.csv"
    dotted = tmp_path / "trial" / "." / "signal.csv"

    assert entry_name(source) == entry_name(relative) == entry_name(dotted)
    assert cache_dir_for(source, tmp_path / "root") == (
        tmp_path / "root" / SOURCES_DIR / entry_name(source)
    )


def test_same_named_files_in_different_folders_get_different_entries(tmp_path: Path) -> None:
    first = _source(tmp_path / "a")
    second = _source(tmp_path / "b")
    assert entry_name(first) != entry_name(second)
    assert entry_name(first).startswith("signal.csv-")


def test_an_entry_name_is_a_safe_file_name_on_every_platform(tmp_path: Path) -> None:
    """Windows rejects ``<>:"|?*``; a long name must not overflow a path either."""
    name = entry_name(tmp_path / ('a<b>c:d"e|f?g*h' + "x" * 300 + ".csv"))
    assert not set('<>:"/\\|?*') & set(name)
    assert len(name) <= 60
    assert not name.startswith(".")


# ── nothing beside the data ─────────────────────────────────────────


def test_building_and_rebuilding_an_entry_writes_nothing_beside_the_source(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    source = _source(data)
    root = tmp_path / "root"

    directory = _entry(root, source)
    _entry(root, source, payload="rebuilt")

    assert sorted(path.name for path in data.iterdir()) == ["signal.csv"]
    assert directory.parent == root / SOURCES_DIR
    assert read_entry_record(directory) == os.path.abspath(source)
    assert (directory / "a_v.npy").read_text(encoding="utf-8") == "rebuilt"
    assert [path.name for path in (root / SOURCES_DIR).iterdir()] == [directory.name]


def test_a_staging_directory_is_recognisably_ours_before_it_is_committed(tmp_path: Path) -> None:
    """A crash mid-import leaves staging that a later removal can still clear."""
    source = _source(tmp_path / "data")
    root = tmp_path / "root"
    staging = CacheManager(root=root).get_temp_cache_dir(source)

    assert staging.parent == root / SOURCES_DIR
    assert staging.name.startswith(".tmp-")
    assert [entry.directory for entry in cache_store.list_entries(root)] == [staging]
    assert cache_store.remove_all(root).removed == 1
    assert not staging.exists()


# ── removal ─────────────────────────────────────────────────────────


def test_removing_one_trial_keeps_every_other_trials_cache(tmp_path: Path) -> None:
    root = tmp_path / "root"
    trial = tmp_path / "data" / "trial1"
    kept_trial = tmp_path / "data" / "trial2"
    inside = [
        _entry(root, _source(trial, "cam.mp4")),
        _entry(root, _source(trial / "pose-3d", "pose.csv")),
    ]
    kept = _entry(root, _source(kept_trial, "cam.mp4"))
    # A sibling whose name merely starts with the trial's is another trial.
    lookalike = _entry(root, _source(tmp_path / "data" / "trial10", "cam.mp4"))

    entries = cache_store.entries_under([trial], root)
    report = cache_store.remove_entries(entries, root)

    assert sorted(entry.directory for entry in entries) == sorted(inside)
    assert report.removed == 2 and not report.failed
    assert not any(directory.exists() for directory in inside)
    assert kept.is_dir() and lookalike.is_dir()
    # The data itself is never part of a removal.
    assert (trial / "cam.mp4").is_file() and (trial / "pose-3d" / "pose.csv").is_file()


def test_remove_all_empties_the_cache_and_reports_the_bytes_freed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _entry(root, _source(tmp_path / "a"), payload="x" * 1000)
    _entry(root, _source(tmp_path / "b"), payload="y" * 1000)

    report = cache_store.remove_all(root)

    assert report.removed == 2
    assert report.freed_bytes >= 2000
    assert cache_store.list_entries(root) == []
    assert root.is_dir(), "the root itself is never removed"


def test_a_hard_linked_array_is_counted_once(tmp_path: Path) -> None:
    """The importer links one timestamp array into every channel (D-071)."""
    root = tmp_path / "root"
    directory = _entry(root, _source(tmp_path / "a"), payload="")
    np.save(directory / "shared_t.npy", np.zeros(10_000))
    for index in range(5):
        try:
            os.link(directory / "shared_t.npy", directory / f"ch{index}_t.npy")
        except OSError:
            pytest.skip("this file system cannot hard-link")
    size = (directory / "shared_t.npy").stat().st_size

    report = cache_store.remove_all(root)

    assert size <= report.freed_bytes < 2 * size


def test_removal_refuses_a_directory_outside_the_cache(tmp_path: Path) -> None:
    """The guard is the record *and* the place: a forged record outside is refused."""
    root = tmp_path / "root"
    _entry(root, _source(tmp_path / "a"))
    outside = tmp_path / "data" / "looks_like_an_entry"
    outside.mkdir(parents=True)
    (outside / ENTRY_RECORD).write_text(
        json.dumps({"format": "avialsync-cache-entry/1", "source": "x"}), encoding="utf-8"
    )
    (outside / "recording.bin").write_bytes(b"irreplaceable")

    report = cache_store.remove_entries([cache_store.CacheEntry(outside, "x")], root)

    assert report.removed == 0 and len(report.failed) == 1
    assert (outside / "recording.bin").read_bytes() == b"irreplaceable"


def test_removal_leaves_anything_in_the_cache_folder_it_did_not_write(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _entry(root, _source(tmp_path / "a"))
    stranger = root / SOURCES_DIR / "put-here-by-hand"
    stranger.mkdir()
    (stranger / "notes.txt").write_text("mine", encoding="utf-8")

    report = cache_store.remove_all(root)
    forced = cache_store.remove_entries([cache_store.CacheEntry(stranger, "x")], root)

    assert report.removed == 1
    assert forced.removed == 0
    assert (stranger / "notes.txt").read_text(encoding="utf-8") == "mine"


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_removal_never_follows_a_symlink_out_of_the_cache(tmp_path: Path) -> None:
    root = tmp_path / "root"
    real = _entry(root, _source(tmp_path / "a"))
    data = tmp_path / "data"
    data.mkdir()
    (data / "recording.bin").write_bytes(b"irreplaceable")
    (data / ENTRY_RECORD).write_text(
        json.dumps({"format": "avialsync-cache-entry/1", "source": "x"}), encoding="utf-8"
    )
    link = root / SOURCES_DIR / "linked-entry"
    link.symlink_to(data, target_is_directory=True)

    listed = cache_store.list_entries(root)
    forced = cache_store.remove_entries([cache_store.CacheEntry(link, "x")], root)
    cache_store.remove_all(root)

    assert [entry.directory for entry in listed] == [real]
    assert forced.removed == 0
    assert (data / "recording.bin").read_bytes() == b"irreplaceable"


def test_an_entry_that_cannot_be_moved_aside_is_kept_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows refuses the rename while a file is open; nothing is half-deleted."""
    root = tmp_path / "root"
    directory = _entry(root, _source(tmp_path / "a"))

    def in_use(src: object, dst: object) -> None:
        raise PermissionError(13, "in use")

    monkeypatch.setattr(cache_store, "_RETRY_DELAYS", (0.0, 0.0))
    monkeypatch.setattr(os, "rename", in_use)
    report = cache_store.remove_all(root)

    assert report.removed == 0 and len(report.failed) == 1
    assert read_entry_record(directory) is not None
    assert (directory / "a_v.npy").is_file()


def test_a_briefly_held_entry_is_removed_once_it_is_let_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scanner holding a fresh file for a moment must not leave the entry behind."""
    root = tmp_path / "root"
    directory = _entry(root, _source(tmp_path / "a"))
    real_rename = os.rename
    refusals = [PermissionError(32, "sharing violation")] * 2

    def held_twice(src: str, dst: str) -> None:
        if refusals:
            raise refusals.pop()
        real_rename(src, dst)

    monkeypatch.setattr(cache_store, "_RETRY_DELAYS", (0.0, 0.0, 0.0))
    monkeypatch.setattr(os, "rename", held_twice)
    report = cache_store.remove_all(root)

    assert report.removed == 1 and not report.failed
    assert not directory.exists()


def test_a_trash_directory_left_by_an_interrupted_removal_is_swept(tmp_path: Path) -> None:
    root = tmp_path / "root"
    trash = root / SOURCES_DIR / f"{cache_store.TRASH_PREFIX}abc"
    trash.mkdir(parents=True)
    (trash / "a_v.npy").write_bytes(b"x")

    cache_store.remove_all(root)

    assert not trash.exists()


# ── what a "trial" is ───────────────────────────────────────────────


def test_a_trial_is_the_deepest_folder_holding_all_its_sources(tmp_path: Path) -> None:
    trial = tmp_path / "data" / "mouse1" / "trial3"
    sources = [trial / "videos" / "cam1.mp4", trial / "pose-3d" / "pose.csv", trial / "ttl.csv"]
    assert cache_store.working_folders(sources) == [trial]


def test_one_file_alone_is_a_trial_in_its_own_folder(tmp_path: Path) -> None:
    assert cache_store.working_folders([tmp_path / "x" / "a.csv"]) == [tmp_path / "x"]


def test_scattered_sources_never_widen_to_the_home_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two folders under home would make home the "trial": every cache in it."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    first = tmp_path / "a" / "x.csv"
    second = tmp_path / "b" / "y.mp4"
    assert cache_store.working_folders([first, second]) == [first, second]
    loose = tmp_path / "loose.csv"
    assert cache_store.working_folders([loose]) == [loose]


def test_nothing_loaded_is_no_folder() -> None:
    assert cache_store.working_folders([]) == []


# ── what stays beside the data ──────────────────────────────────────


def test_sidecars_have_one_extension_and_keep_the_sources_full_name(tmp_path: Path) -> None:
    pose = tmp_path / "FaceCam_eks.csv"

    assert correction_path(pose).name == "FaceCam_eks_csv_avialfix.csv"
    assert swap_path(pose).name == "FaceCam_eks_csv_avialswap.csv"
    assert marker_file_for(pose).name == "FaceCam_eks_custom_markers.csv"
    assert prop_path(tmp_path, "wheel").name == "wheel_prop.toml"
    for path in (correction_path(pose), swap_path(pose), marker_file_for(pose)):
        assert path.parent == tmp_path
        assert path.suffixes == [".csv"]
    # Two sources differing only in extension never share a corrections file.
    assert correction_path(tmp_path / "a.csv") != correction_path(tmp_path / "a.h5")
    assert sidecar_names.flat_name("Face.Cam.csv") == "Face_Cam_csv"


def test_large_sync_mappings_live_with_the_session_not_in_the_cache(tmp_path: Path) -> None:
    """The session will not open without them, so a cache clear must not reach them."""
    session_path = tmp_path / "trial.avv"
    master = np.arange(1000, dtype=np.float64)
    state = SessionState(
        sync_provenance=[
            SyncProvenance(
                reference_id="a",
                target_id="b",
                offset=0.0,
                drift_ms_per_hour=0.0,
                rms_residual=0.0,
                max_residual=0.0,
                matched_count=len(master),
                rejected_count=0,
                tolerance=0.01,
                exact_master=master,
                exact_source=master + 0.5,
            )
        ]
    )

    state.save(session_path)
    stored = json.loads(session_path.read_text(encoding="utf-8"))
    loaded = SessionState.load(session_path)

    folder = exact_mapping_dir(session_path)
    assert folder == tmp_path / "trial_avv_sync"
    assert [path.parent for path in folder.iterdir()] == [folder]
    assert stored["sync_provenance"][0]["exact_mapping"]["file"].startswith("trial_avv_sync/")
    assert not cache_root().is_relative_to(tmp_path)
    np.testing.assert_array_equal(loaded.sync_provenance[0].exact_source, master + 0.5)


def test_an_unwritable_cache_folder_costs_the_timestamp_cache_not_the_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache is an optimisation; a full or locked cache disk must not fail an open."""
    from avialsync.loaders.video_standard import VideoStandardLoader

    def refuse(self: CacheManager, source_path: Path) -> Path:
        raise PermissionError(13, "cache folder not writable")

    monkeypatch.setattr(CacheManager, "get_temp_cache_dir", refuse)
    video = _source(tmp_path / "data", "cam.mp4")

    VideoStandardLoader()._save_frame_times_cache(video, np.arange(5, dtype=np.float64))

    assert not cache_dir_for(video).exists()
