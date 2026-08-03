"""Edge behaviour of the pyramid reader and the loader registry.

Both sit on paths a user reaches by accident rather than by design: asking for
a value outside a channel's coverage, or dropping a plugin that does not
import. Neither may raise into the UI or silently do nothing surprising
(BLUEPRINT.md Phase 6: 100% on core).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.core.registry import LoaderRegistry


@pytest.fixture
def channel(tmp_path: Path) -> PyramidReader:
    """A one-second channel sampled at 100 Hz, with a gap in the middle."""
    cache = tmp_path / "edges.avialcache"
    cache.mkdir(parents=True, exist_ok=True)
    times = np.linspace(0.0, 1.0, 101)
    values = np.sin(times * 2 * np.pi)
    PyramidBuilder(cache, "ch").build_and_save(times, values)
    return PyramidReader(cache, "ch")


class TestValueAtCoverageEdges:
    """`value_at` answers for any time; outside coverage the answer is NaN."""

    def test_an_exact_sample_time_returns_that_sample(self, channel: PyramidReader) -> None:
        assert channel.value_at(0.5) == pytest.approx(math.sin(0.5 * 2 * math.pi), abs=1e-6)

    def test_a_time_between_samples_returns_the_nearer_one(self, channel: PyramidReader) -> None:
        """Nearest-sample, not interpolation: the readout must not invent data."""
        just_after = channel.value_at(0.5001)
        exact = channel.value_at(0.5)

        assert just_after == pytest.approx(exact)

    def test_slightly_before_the_first_sample_still_reads(self, channel: PyramidReader) -> None:
        """A cursor a hair before t0 is a rounding artefact, not absent data."""
        assert not math.isnan(channel.value_at(-0.01))

    def test_far_before_the_first_sample_is_not_a_reading(self, channel: PyramidReader) -> None:
        assert math.isnan(channel.value_at(-10.0))

    def test_slightly_after_the_last_sample_still_reads(self, channel: PyramidReader) -> None:
        assert not math.isnan(channel.value_at(1.01))

    def test_far_after_the_last_sample_is_not_a_reading(self, channel: PyramidReader) -> None:
        assert math.isnan(channel.value_at(10.0))


class TestEmptyChannel:
    """A channel with no samples must answer, not raise, on every query."""

    @pytest.fixture
    def empty(self, tmp_path: Path) -> PyramidReader:
        cache = tmp_path / "empty.avialcache"
        cache.mkdir(parents=True, exist_ok=True)
        PyramidBuilder(cache, "none").build_and_save(
            np.array([], dtype=np.float64), np.array([], dtype=np.float64)
        )
        return PyramidReader(cache, "none")

    def test_value_at_is_nan(self, empty: PyramidReader) -> None:
        assert math.isnan(empty.value_at(0.0))

    def test_query_returns_empty_arrays(self, empty: PyramidReader) -> None:
        times, minimums, maximums, gaps = empty.query(0.0, 1.0, 100)

        assert len(times) == 0
        assert len(minimums) == 0
        assert len(maximums) == 0
        assert len(gaps) == 0


class TestPluginDiscovery:
    """A third-party plugin must never take the application down with it."""

    def test_a_missing_plugin_directory_is_not_an_error(self, tmp_path: Path) -> None:
        """Users are told to create ~/.avialsync/plugins; most never do."""
        registry = LoaderRegistry(plugin_dirs=[tmp_path / "absent"])

        assert registry.loaders

    def test_a_plugin_that_fails_to_import_is_reported_not_swallowed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Silent failure made a broken plugin vanish with no way to tell why."""
        (tmp_path / "broken.py").write_text("import nonexistent_module_xyz\n", encoding="utf-8")

        with caplog.at_level("WARNING"):
            registry = LoaderRegistry(plugin_dirs=[tmp_path])

        assert registry.loaders, "built-in loaders must survive a broken plugin"
        assert any("broken" in record.getMessage() for record in caplog.records)

    def test_private_modules_are_skipped(self, tmp_path: Path) -> None:
        """A leading underscore marks a helper, not a plugin to import."""
        (tmp_path / "_helper.py").write_text("raise AssertionError('imported')\n", encoding="utf-8")

        assert LoaderRegistry(plugin_dirs=[tmp_path]).loaders

    def test_an_unknown_extension_has_no_best_loader(self, tmp_path: Path) -> None:
        unknown = tmp_path / "recording.unknownext"
        unknown.write_bytes(b"\x00\x01")

        assert LoaderRegistry().find_best_loader(unknown) is None
