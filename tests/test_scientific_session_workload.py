"""Cross-platform functional check for the representative scientific workload."""

from pathlib import Path

import numpy as np

from avialview.core.pyramid import PyramidBuilder, PyramidReader
from avialview.loaders.video_standard import VideoStandardLoader


def test_three_camera_four_stream_session_can_be_cached_and_queried(tmp_path: Path) -> None:
    """Exercise the session shape scientists use without treating CI as a speed test."""
    video_dir = Path(__file__).parent / "fixtures" / "videos"
    cameras = [video_dir / f"camera_{index}.mp4" for index in range(1, 4)]

    for camera in cameras:
        loader = VideoStandardLoader()
        loader.open(camera, {})
        assert loader.frame_times() is not None
        assert loader.frame_times().size > 0

    sample_rate_hz = 50_000
    duration_s = 2
    times = np.arange(sample_rate_hz * duration_s, dtype=np.float64) / sample_rate_hz
    readers: list[PyramidReader] = []
    for channel in range(4):
        cache_dir = tmp_path / f"stream_{channel}.avialcache"
        cache_dir.mkdir()
        values = np.sin(times * (channel + 1))
        PyramidBuilder(cache_dir, f"stream_{channel}").build_and_save(times, values)
        readers.append(PyramidReader(cache_dir, f"stream_{channel}"))

    for reader in readers:
        query_times, query_min, query_max, gap_mask = reader.query(0.25, 1.75, max_points=1_000)
        assert query_times.size <= 1_000
        assert query_min.size == query_times.size
        assert query_max.size == query_times.size
        assert gap_mask.size == query_times.size
