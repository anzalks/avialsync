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
