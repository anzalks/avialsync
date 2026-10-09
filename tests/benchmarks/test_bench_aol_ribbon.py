"""Frame assembly budget for a full 96-tile AOL ribbon scan."""

from __future__ import annotations

import h5py
import numpy as np
import pytest

from avialsync.loaders.aol_ribbon_scan import AOLRibbonScanSource

_FRAME_BUDGET_S = 0.030


@pytest.mark.benchmark(group="aol-ribbon-mosaic")
def test_bench_full_ribbon_mosaic_frame(benchmark, tmp_path):
    """Assemble one 510×150 frame (the lab's orientation) from all 96 ROI files in a tick."""
    trial = tmp_path / "12-33-56"
    trial.mkdir()
    with h5py.File(trial / "params.mat", "w") as handle:
        handle.create_group("controller").create_dataset("aol_params", data=[1])
    volume = np.zeros((2, 2, 15, 51), dtype=np.uint16)
    for roi in range(1, 97):
        path = trial / f"RibbonScan_ROI_{roi:04d}_repeat_0001_timepoints_2.mat"
        with h5py.File(path, "w") as handle:
            handle.create_dataset("volume", data=volume, chunks=(2, 1, 15, 51))

    source = AOLRibbonScanSource()
    metadata = source.open(trial, {})
    assert (metadata.height, metadata.width) == (510, 150)
    frame = benchmark(source.read_frame, 1)
    assert frame.shape == (510, 150)
    assert benchmark.stats.stats.median < _FRAME_BUDGET_S
    source.close()
