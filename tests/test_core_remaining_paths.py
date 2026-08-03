"""Behaviours on the last uncovered `core/` paths (BLUEPRINT.md Phase 6).

Each of these is reachable from ordinary use — a folder as a source, a
single-level pyramid, an irregularly sampled channel, a session carrying a
large exact mapping, or a plugin whose entry point does not import.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from avialview.core.cache import CacheManager
from avialview.core.pyramid import PyramidBuilder, PyramidReader
from avialview.core.registry import LoaderRegistry
from avialview.core.session import SessionState, SyncProvenance
from avialview.core.sync import fit_sync_events
from avialview.core.timeline import TimeMap


def _provenance(master: list[float], source: list[float]) -> SyncProvenance:
    """Accepted evidence carrying an exact per-frame mapping."""
    return SyncProvenance(
        reference_id="ttl",
        target_id="cam",
        offset=0.0,
        drift_ppm=0.0,
        rms_residual=0.0,
        max_residual=0.0,
        matched_count=len(master),
        rejected_count=0,
        tolerance=1e-3,
        exact_master=master,
        exact_source=source,
    )


class TestCacheKeysForDirectories:
    """A source can be a folder; hashing must not try to read its edges."""

    def test_a_directory_produces_a_stable_cache_key(self, tmp_path: Path) -> None:
        folder = tmp_path / "recording_set"
        folder.mkdir()
        manager = CacheManager()

        key = manager.generate_key(folder)

        assert key and key == manager.generate_key(folder)

    def test_two_directories_get_different_cache_keys(self, tmp_path: Path) -> None:
        first = tmp_path / "one"
        second = tmp_path / "two"
        first.mkdir()
        second.mkdir()
        manager = CacheManager()

        assert manager.generate_key(first) != manager.generate_key(second)


class TestIrregularSampling:
    """Gap detection keys off the median interval, which may not exist."""

    def test_a_single_sample_channel_reports_no_gaps(self, tmp_path: Path) -> None:
        """One sample has no interval at all, so nothing can be a gap."""
        cache = tmp_path / "single.avialcache"
        cache.mkdir(parents=True, exist_ok=True)
        PyramidBuilder(cache, "one").build_and_save(np.array([0.5]), np.array([2.0]))

        reader = PyramidReader(cache, "one")

        assert reader.value_at(0.5) == pytest.approx(2.0)

    def test_a_gap_reads_as_no_value_rather_than_the_neighbouring_one(self, tmp_path: Path) -> None:
        """Bridging a gap would draw data the instrument never recorded."""
        cache = tmp_path / "gappy.avialcache"
        cache.mkdir(parents=True, exist_ok=True)
        before = np.linspace(0.0, 1.0, 101)
        after = np.linspace(30.0, 31.0, 101)
        times = np.concatenate([before, after])
        values = np.concatenate([np.ones(101), np.full(101, 5.0)])
        PyramidBuilder(cache, "ch").build_and_save(times, values)

        reader = PyramidReader(cache, "ch")

        assert reader.value_at(0.5) == pytest.approx(1.0)
        assert reader.value_at(30.5) == pytest.approx(5.0)
        assert math.isnan(reader.value_at(15.0)), "the gap must not read as data"


class TestExactMappingPersistence:
    """An exact per-frame mapping is provenance; it must round-trip or fail."""

    def test_mismatched_exact_arrays_are_refused(self, tmp_path: Path) -> None:
        """Unequal lengths cannot describe a frame-to-frame correspondence."""
        state = SessionState(sync_provenance=[_provenance([0.0, 1.0, 2.0], [0.0, 1.0])])

        with pytest.raises(ValueError, match="different lengths"):
            state.save(tmp_path / "session.avv")

    def test_a_large_exact_mapping_survives_a_round_trip(self, tmp_path: Path) -> None:
        """Beyond the inline limit the mapping moves to a sidecar, not away."""
        master = np.linspace(0.0, 100.0, 5_000)
        source = master * 1.000001
        path = tmp_path / "big.avv"
        SessionState(sync_provenance=[_provenance(master.tolist(), source.tolist())]).save(path)

        restored = SessionState.load(path)

        assert len(restored.sync_provenance[0].exact_master) == len(master)
        assert restored.sync_provenance[0].exact_master[-1] == pytest.approx(master[-1])


class TestExactTimeMapRate:
    """Playback rate through a VFR interval comes from the exact mapping."""

    def test_rate_without_an_exact_mapping_is_the_drift_scale(self) -> None:
        mapping = TimeMap(offset=0.0, drift_ppm=1000.0)

        assert mapping.rate_scale_at(5.0) == pytest.approx(1.0 + 1000.0 * 1e-6)

    def test_rate_inside_an_exact_mapping_follows_the_samples(self) -> None:
        """A doubled source interval is a half-rate stretch of master time."""
        mapping = TimeMap()
        mapping.set_exact_mapping(np.array([0.0, 1.0, 2.0, 3.0]), np.array([0.0, 2.0, 4.0, 6.0]))

        assert mapping.rate_scale_at(1.5) == pytest.approx(2.0)

    def test_rate_before_and_after_the_mapping_is_clamped(self) -> None:
        """Outside its range the mapping extends rather than extrapolating."""
        mapping = TimeMap()
        mapping.set_exact_mapping(np.array([0.0, 1.0, 2.0, 3.0]), np.array([0.0, 2.0, 4.0, 6.0]))

        assert mapping.rate_scale_at(-100.0) == pytest.approx(2.0)
        assert mapping.rate_scale_at(100.0) == pytest.approx(2.0)


class TestBrokenEntryPointPlugins:
    """An installed plugin that fails to import must be named, not swallowed."""

    def test_a_failing_entry_point_is_logged_and_skipped(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from avialview.core import registry as registry_module

        class _BrokenEntryPoint:
            name = "broken_third_party"

            def load(self):
                raise ImportError("its dependency is not installed")

        monkeypatch.setattr(registry_module, "entry_points", lambda group: [_BrokenEntryPoint()])

        with caplog.at_level("WARNING"):
            registry = LoaderRegistry(plugin_dirs=[])

        assert any("broken_third_party" in record.getMessage() for record in caplog.records)
        assert registry.loaders, "built-in loaders must survive a broken entry point"


class TestCacheCommitFallback:
    """A directory rename can fail on a machine that holds handles open."""

    def test_a_failed_rename_falls_back_to_a_file_level_swap(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Windows sync clients hold directory handles; the commit must survive.

        Renaming a *directory* fails there even when its files are writable,
        which is normal under a synced Documents folder.
        """
        from avialview.core import cache as cache_module

        source = tmp_path / "recording.csv"
        source.write_text("t,v\n0,1\n", encoding="utf-8")
        manager = cache_module.CacheManager()
        cache_dir = manager.get_cache_dir(source)
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "old.npy").write_bytes(b"stale")
        temp_dir = manager.get_temp_cache_dir(source)
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "fresh.npy").write_bytes(b"new")

        def refuse_directory_rename(src, dst):
            raise OSError("directory handle is held open")

        monkeypatch.setattr(cache_module.os, "rename", refuse_directory_rename)

        manager.commit_cache(source, temp_dir)

        assert (cache_dir / "fresh.npy").read_bytes() == b"new"
        assert manager.is_cache_valid(source)

    def test_both_paths_failing_reports_both_causes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A cache that cannot be committed must say why, not fail silently."""
        from avialview.core import cache as cache_module
        from avialview.core.errors import CacheError

        source = tmp_path / "recording.csv"
        source.write_text("t,v\n0,1\n", encoding="utf-8")
        manager = cache_module.CacheManager()
        temp_dir = manager.get_temp_cache_dir(source)
        temp_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "fresh.npy").write_bytes(b"new")

        def refuse(*_args, **_kwargs):
            raise OSError("refused")

        monkeypatch.setattr(cache_module.os, "rename", refuse)
        monkeypatch.setattr(cache_module.os, "replace", refuse)

        with pytest.raises(CacheError, match="in-place fallback also failed"):
            manager.commit_cache(source, temp_dir)


class TestSyncInternals:
    """Branches of the affine search that ordinary evidence does not reach."""

    def test_an_exact_fit_without_a_mapping_is_still_a_time_map(self) -> None:
        """ExactSyncFit carries the mapping optionally, not always."""
        from avialview.core.sync import ExactSyncFit

        mapping = ExactSyncFit(
            offset=1.0,
            drift_ppm=0.0,
            rms_residual=0.0,
            max_residual=0.0,
            matched_count=3,
            rejected_count=0,
        ).to_time_map()

        assert not mapping.has_exact_mapping
        assert mapping.offset == pytest.approx(1.0)

    def test_no_pair_within_tolerance_yields_no_alignment(self) -> None:
        """Events with no counterpart at all must produce an empty match set."""
        from avialview.core.sync import _match_pairs

        reference = np.array([0.0, 1.0, 2.0])
        target = np.array([100.0, 101.0, 102.0])

        pairs = _match_pairs(reference, target, scale=1.0, offset=0.0, tolerance=1e-6)

        assert pairs.shape == (0, 2)

    def test_equal_quality_candidates_at_different_offsets_are_ambiguous(self) -> None:
        """Two perfect alignments mean the evidence cannot choose; refuse."""
        from avialview.core.sync import _is_ambiguous

        best = np.array([[0, 0], [1, 1], [2, 2]])
        rival = np.array([[0, 1], [1, 2], [2, 3]])

        assert _is_ambiguous([(best, 1.0, 0.0, 0.0), (rival, 1.0, 5.0, 0.0)], best, 0.0)

    def test_a_shorter_rival_candidate_is_not_ambiguity(self) -> None:
        """Fewer matched events is a worse fit, not a tie."""
        from avialview.core.sync import _is_ambiguous

        best = np.array([[0, 0], [1, 1], [2, 2]])
        shorter = np.array([[0, 1], [1, 2]])

        assert not _is_ambiguous([(best, 1.0, 0.0, 0.0), (shorter, 1.0, 5.0, 0.0)], best, 0.0)


class TestPyramidLevels:
    """The base level is returned as-is; downsampling starts above it."""

    def test_a_two_sample_channel_reads_both_ends(self, tmp_path: Path) -> None:
        """Too few samples to downsample, so level 1 is served directly."""
        cache = tmp_path / "pair.avialcache"
        cache.mkdir(parents=True, exist_ok=True)
        PyramidBuilder(cache, "two").build_and_save(np.array([0.0, 1.0]), np.array([3.0, 7.0]))

        reader = PyramidReader(cache, "two")

        assert reader.value_at(0.0) == pytest.approx(3.0)
        assert reader.value_at(1.0) == pytest.approx(7.0)

    def test_a_query_wider_than_the_data_returns_what_exists(self, tmp_path: Path) -> None:
        cache = tmp_path / "narrow.avialcache"
        cache.mkdir(parents=True, exist_ok=True)
        times = np.linspace(0.0, 1.0, 50)
        PyramidBuilder(cache, "ch").build_and_save(times, np.sin(times))

        times_out, _, _, _ = PyramidReader(cache, "ch").query(-100.0, 100.0, 500)

        assert len(times_out) > 0


class TestPyramidLevelHelpers:
    """Direct checks on the decimation helpers' degenerate inputs."""

    def test_level_one_is_the_data_itself(self) -> None:
        """The base level is not decimated; min and max are the sample."""
        from avialview.core.pyramid import build_pyramid_level

        times = np.array([0.0, 1.0, 2.0])
        values = np.array([3.0, 4.0, 5.0])

        decimated, minimums, maximums = build_pyramid_level(times, values, 1)

        assert np.array_equal(decimated, times)
        assert np.array_equal(minimums, values)
        assert np.array_equal(maximums, values)

    def test_a_stalled_clock_reports_no_gaps_rather_than_all_gaps(self) -> None:
        """Repeated timestamps give a zero median interval, not a gap threshold.

        A stuck acquisition clock must not make every sample look like a gap.
        """
        from avialview.core.pyramid import build_gap_mask

        gaps = build_gap_mask(np.array([1.0, 1.0, 1.0, 1.0]))

        assert gaps.shape == (4,)
        assert not gaps.any()

    def test_a_single_sample_has_no_interval_so_no_gaps(self) -> None:
        """One sample yields no adjacent pair at all."""
        from avialview.core.pyramid import build_gap_mask

        assert not build_gap_mask(np.array([5.0])).any()

    def test_a_nearer_right_neighbour_is_the_reading(self, tmp_path: Path) -> None:
        """`value_at` takes the closer of the two surrounding samples."""
        cache = tmp_path / "sided.avialcache"
        cache.mkdir(parents=True, exist_ok=True)
        PyramidBuilder(cache, "ch").build_and_save(
            np.array([0.0, 0.01, 0.02, 0.03]), np.array([10.0, 20.0, 30.0, 40.0])
        )
        reader = PyramidReader(cache, "ch")

        # 0.0199 sits nearer 0.02 than 0.01.
        assert reader.value_at(0.0199) == pytest.approx(30.0)
        # 0.0101 sits nearer 0.01 than 0.02.
        assert reader.value_at(0.0101) == pytest.approx(20.0)


class TestAmbiguityLoopExhaustion:
    """Equal-length rivals that are not perfect fits are not ambiguity."""

    def test_a_rival_with_real_residual_is_not_a_tie(self) -> None:
        from avialview.core.sync import _is_ambiguous

        best = np.array([[0, 0], [1, 1], [2, 2]])
        rival = np.array([[0, 1], [1, 2], [2, 3]])

        # Same pair count and a different offset, but a residual well above
        # the perfect-fit threshold: the best candidate genuinely wins.
        assert not _is_ambiguous([(best, 1.0, 0.0, 0.0), (rival, 1.0, 5.0, 0.5)], best, 0.0)


def test_a_failed_backup_restore_still_falls_back_to_the_swap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The worst commit case must still leave a valid cache.

    The old sidecar has been renamed aside, installing the new one fails, and
    putting the old one back fails too. Losing both would leave no cache at
    all; the file-level swap is what rescues it.
    """
    from avialview.core import cache as cache_module

    source = tmp_path / "recording.csv"
    source.write_text("t,v\n0,1\n", encoding="utf-8")
    manager = cache_module.CacheManager()
    cache_dir = manager.get_cache_dir(source)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "old.npy").write_bytes(b"stale")
    temp_dir = manager.get_temp_cache_dir(source)
    temp_dir.mkdir(parents=True, exist_ok=True)
    (temp_dir / "fresh.npy").write_bytes(b"new")

    real_rename = cache_module.os.rename
    calls = {"count": 0}

    def rename_once_then_refuse(src, dst):
        """Move the old cache aside, then refuse to install or restore."""
        calls["count"] += 1
        if calls["count"] == 1:
            real_rename(src, dst)
            return
        raise OSError("handle is held open")

    monkeypatch.setattr(cache_module.os, "rename", rename_once_then_refuse)

    manager.commit_cache(source, temp_dir)

    assert calls["count"] >= 3, "the restore attempt must have been made"
    assert (cache_dir / "fresh.npy").read_bytes() == b"new"
    assert manager.is_cache_valid(source)


def test_a_candidate_that_worsens_when_refitted_is_discarded() -> None:
    """A sequence offset can match enough events and then fail its own refit.

    The search matches against an initial scale, refits affinely to whatever
    matched, then re-matches. Spurious events can make the refit pull the fit
    away from the pulses that seeded it, leaving too few pairs to trust. That
    candidate has to be dropped rather than carried forward on its first,
    better-looking count.

    These are jittered pulses with three spurious extras — the shape real TTL
    evidence has, not a constructed adversarial case.
    """
    reference = np.array(
        [
            0.083557,
            0.202835,
            0.305691,
            0.385947,
            0.496853,
            0.615984,
            0.719579,
            0.812366,
            0.899866,
            1.006767,
            1.094572,
        ]
    )
    target = np.array(
        [
            0.58112,
            0.696455,
            0.808669,
            0.889249,
            0.995047,
            1.06106,
            1.11676,
            1.214552,
            1.310641,
            1.357911,
            1.405558,
            1.506231,
            1.507512,
            1.604032,
        ]
    )

    proposal = fit_sync_events(reference, target, reference_id="ttl", target_id="cam")

    # A surviving candidate still wins; the discarded one must not be it.
    assert proposal.fit.matched_count >= 3
    assert proposal.fit.rms_residual <= proposal.tolerance
