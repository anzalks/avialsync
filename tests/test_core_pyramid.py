import warnings
from pathlib import Path

import numpy as np
import pytest

from avialview.core.pyramid import (
    PyramidBuilder,
    PyramidReader,
    build_gap_mask,
    build_pyramid_level,
)


def test_build_pyramid_level():
    t = np.arange(100, dtype=float)
    v = np.arange(100, dtype=float)

    # Introduce NaNs
    v[5:10] = np.nan

    t_dec, v_min, v_max = build_pyramid_level(t, v, level=16)

    assert len(t_dec) == 7  # 100 // 16 + 1 = 6 + 1 = 7
    assert t_dec[0] == 0.0
    assert t_dec[1] == 16.0
    assert t_dec[-1] == 96.0  # remainder start

    assert v_min[0] == 0.0
    assert v_max[0] == 15.0  # Since 5-9 are NaN, max is still 15

    assert v_min[-1] == 96.0
    assert v_max[-1] == 99.0


def test_pyramid_nan_inf():
    from avialview.core.pyramid import build_pyramid_level

    t = np.arange(16.0)
    v = np.ones(16)
    v[0] = np.nan
    v[1] = np.inf
    v[2] = -np.inf

    t_dec, vmin, vmax = build_pyramid_level(t, v, level=16)
    assert len(t_dec) == 1
    # nanmin/nanmax ignores NaN, but inf is treated as inf
    # so max should be inf, min should be -inf
    assert vmax[0] == np.inf
    assert vmin[0] == -np.inf


def test_all_nan_blocks_do_not_emit_runtime_warnings():
    """Missing-data blocks are valid pyramid input, not diagnostic noise."""
    t = np.arange(16.0)
    v = np.full(16, np.nan)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        _, vmin, vmax = build_pyramid_level(t, v, level=16)

    assert np.isnan(vmin[0])
    assert np.isnan(vmax[0])


def test_pyramid_gap_mask():
    from avialview.core.pyramid import build_gap_mask

    t = np.array(
        [0.0, 0.1, 0.2, 0.3, 1.5, 1.6, 1.7]
    )  # gap between 0.3 and 1.5 is 1.2s. Median dt is 0.1
    mask = build_gap_mask(t)
    # median dt = 0.1, threshold = 1.0. dt[3] = 1.2 > 1.0. So mask[3] should be True.
    assert len(mask) == len(t)
    assert mask[3]
    assert not mask[2]
    assert not mask[4]


def test_build_gap_mask():
    t = np.array([0.0, 1.0, 2.0, 3.0, 15.0, 16.0])
    mask = build_gap_mask(t)

    # dt = [1, 1, 1, 12, 1], median_dt = 1.0, threshold = 10.0
    assert list(mask) == [False, False, False, True, False, False]


def test_pyramid_builder_and_reader(tmp_path: Path):
    t = np.arange(1000, dtype=float)
    v = np.sin(t)

    builder = PyramidBuilder(tmp_path, "ch0")
    builder.build_and_save(t, v)

    reader = PyramidReader(tmp_path, "ch0")

    # Query fine resolution
    t_q, vmin_q, vmax_q, gap_q = reader.query(100, 200, max_points=1000)
    assert len(t_q) == 101
    assert gap_q.sum() == 0
    assert t_q[0] == 100.0

    # Query coarse resolution (forcing level 256)
    t_c, vmin_c, vmax_c, gap_c = reader.query(
        0, 1000, max_points=50
    )  # 1000 pts // 16 = 62 > 50; 1000 pts // 256 = 3 <= 50. So it picks level 256.
    assert len(t_c) == 4  # 1000 // 256 = 3 + 1 remainder block = 4
    assert t_c[0] == 0.0


def test_pyramid_builder_propagates_sidecar_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A background sidecar failure must fail the import, never look successful."""

    def fail_save(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(np, "save", fail_save)

    with pytest.raises(OSError, match="disk full"):
        PyramidBuilder(tmp_path, "ch0").build_and_save(np.arange(16.0), np.arange(16.0))


def test_pathological_gap_mask():
    """Verify subsampled gap_mask (stride 10k) detects correctly on clustered gaps (D-023)."""
    # Create 180k samples, uniform dt=0.02 (50Hz)
    t = np.arange(180_000, dtype=float) * 0.02

    # Inject a clustered block of large gaps near the end
    # This creates 1000 sequential gaps of 10.02s each.
    t[-1000:] += np.arange(1000, dtype=float) * 10.0

    mask = build_gap_mask(t)

    # The true median dt is still 0.02 because 179k elements have dt=0.02.
    # Threshold = 0.2. So indices up to -1001 should be False, -1000 onwards True.
    # The subsampled median estimator must not be skewed enough to miss this.
    assert not mask[0]
    assert not mask[-1002]
    assert mask[-1000]
    assert mask[-2]
