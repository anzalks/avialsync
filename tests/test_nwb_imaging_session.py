"""NWB imaging proxies, the NWB session layout, and importing an NWB file (D-188)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("h5py")
av = pytest.importorskip("av")

from avialsync.core.registry import LoaderRegistry  # noqa: E402
from avialsync.core.source import TimeSeriesSource, VideoSource  # noqa: E402
from avialsync.loaders import nwb_format  # noqa: E402
from avialsync.loaders.nwb_imaging import NWBImagingSource, proxy_origin  # noqa: E402
from avialsync.loaders.nwb_loader import NWBLoader  # noqa: E402
from avialsync.loaders.nwb_session import NWBSessionSource  # noqa: E402
from avialsync.loaders.video_standard import VideoStandardLoader  # noqa: E402
from tests.nwb_fixture import (  # noqa: E402
    IMAGING_FRAMES,
    IMAGING_RATE,
    IMAGING_SHAPE,
    SESSION_EPOCH,
    NWBSpec,
    _imaging_frames,
    write_nwb,
    write_nwb1,
    write_zarr_nwb,
)


def _decode(path: Path, pixel_format: str) -> list[np.ndarray]:
    with av.open(str(path)) as container:
        return [frame.to_ndarray(format=pixel_format) for frame in container.decode(video=0)]


def _prepared(path: Path, config: dict | None = None) -> NWBImagingSource:
    source = NWBImagingSource()
    source.open(path, config or {})
    progress: list[float] = []
    source.prepare(progress.append)
    assert progress[-1] == 1.0
    return source


# ── Imaging proxy ─────────────────────────────────────────────────────────


def test_proxy_holds_every_pixel_as_recorded(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb")
    source = _prepared(path)

    frames = _decode(source.media_path(), "gray16le")

    stored = _imaging_frames("uint16")
    assert len(frames) == IMAGING_FRAMES
    assert all(np.array_equal(a, b) for a, b in zip(frames, stored, strict=True))
    assert source.video_metadata().pixel_format == "gray16le"
    assert (source.video_metadata().height, source.video_metadata().width) == IMAGING_SHAPE


def test_proxy_frames_carry_the_nwb_timestamps(tmp_path: Path) -> None:
    """The pane picks frames from the proxy's own times; those must be the file's."""
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(imaging_start=0.5))
    source = _prepared(path)

    expected = 0.5 + np.arange(IMAGING_FRAMES) / IMAGING_RATE
    np.testing.assert_allclose(source.frame_times(), expected, atol=1e-6)
    start, end = source.time_bounds()
    assert start == pytest.approx(0.5, abs=1e-6)
    assert end == pytest.approx(expected[-1] + 1 / IMAGING_RATE, abs=1e-5)
    assert source.fps() == pytest.approx(IMAGING_RATE, rel=1e-4)
    assert source.label() == "TwoPhotonSeries"


def test_proxy_is_built_once_and_reused(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb")
    first = _prepared(path).media_path()
    built = first.stat().st_mtime_ns

    second = _prepared(path).media_path()

    assert second == first
    assert second.stat().st_mtime_ns == built


def test_proxy_and_time_series_import_do_not_share_a_cache_entry(tmp_path: Path, qapp) -> None:
    """The time series own the entry named after the file; the proxy must not replace it."""
    from avialsync.engine.importer import ImportWorker

    path = write_nwb(tmp_path / "s.nwb")
    worker = ImportWorker(path, {}, NWBLoader)
    results: list[tuple] = []
    worker.finished.connect(lambda *args: results.append(args))
    worker.run()
    proxy = _prepared(path).media_path()

    cache_dir = Path(results[0][1])
    assert proxy.parent != cache_dir
    assert (cache_dir / "ElectricalSeries.ch10_v.npy").is_file()
    again: list[tuple] = []
    worker = ImportWorker(path, {}, NWBLoader)
    worker.finished.connect(lambda *args: again.append(args))
    worker.run()
    assert Path(again[0][1]) == cache_dir and proxy.is_file()


@pytest.mark.parametrize("dtype", ["uint8", "int16", "float32"])
def test_other_pixel_types_play_without_changing_the_file(tmp_path: Path, dtype: str) -> None:
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(imaging_dtype=dtype))
    source = _prepared(path)

    frames = _decode(source.media_path(), "gray" if dtype == "uint8" else "gray16le")

    assert len(frames) == IMAGING_FRAMES
    stored = _imaging_frames(dtype)
    if dtype == "uint8":
        assert all(np.array_equal(a, b) for a, b in zip(frames, stored, strict=True))
    else:
        # Mapped for display, order preserved: brighter samples stay brighter.
        flat_stored = stored.astype(np.float64).ravel()
        flat_shown = np.stack(frames).astype(np.float64).ravel()
        assert np.corrcoef(flat_stored, flat_shown)[0, 1] > 0.99


def test_a_series_starting_before_zero_counts_from_its_first_frame(tmp_path: Path) -> None:
    """MP4 drops frames before zero, so the proxy starts at the first frame instead."""
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(imaging_start=-0.2))
    source = _prepared(path)

    assert len(source.frame_times()) == IMAGING_FRAMES
    assert source.frame_times()[0] == pytest.approx(0.0, abs=1e-6)
    assert proxy_origin(-0.2) == -0.2
    assert proxy_origin(0.3) == 0.0


def test_an_explicit_series_is_honoured_and_a_missing_one_named(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(second_imaging=True))
    source = _prepared(path, {"series": "/acquisition/TwoPhotonSeriesGreen"})
    assert len(source.frame_times()) == 5

    with pytest.raises(Exception, match="/acquisition/Nope"):
        NWBImagingSource().open(path, {"series": "/acquisition/Nope"})


# ── Session layout ────────────────────────────────────────────────────────


def test_a_file_lays_out_its_time_series_and_imaging_on_its_own_clock(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb")

    layout = NWBSessionSource().scan(path, LoaderRegistry())

    loaders = {item.loader for item in layout.items}
    assert loaders == {NWBLoader, NWBImagingSource}
    assert layout.session_epoch == pytest.approx(SESSION_EPOCH)
    assert all(item.source_epoch == pytest.approx(SESSION_EPOCH) for item in layout.items)
    series = next(item for item in layout.items if item.loader is NWBLoader)
    imaging = next(item for item in layout.items if item.loader is NWBImagingSource)
    assert series.path == path
    # Its own name inside the file, so the two are two sources, not one.
    assert imaging.path == path / "acquisition" / "TwoPhotonSeries"
    assert imaging.label == "TwoPhotonSeries — imaging in s.nwb"
    assert any("SpikeWaveforms" in warning for warning in layout.warnings)


def test_kinds_are_labels_their_loaders_offer(tmp_path: Path) -> None:
    layout = NWBSessionSource().scan(write_nwb(tmp_path / "s.nwb"), LoaderRegistry())

    for item in layout.items:
        assert item.loader is not None
        assert item.kind in {item.loader.display_name(), *item.loader.display_aliases()}


def test_every_imaging_series_is_offered_raw_acquisition_first(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(second_imaging=True))

    layout = NWBSessionSource().scan(path, LoaderRegistry())

    imaging = [item.path.name for item in layout.items if item.loader is NWBImagingSource]
    # The longer of two acquisition series is the one a file is shown with.
    assert imaging == ["TwoPhotonSeries", "TwoPhotonSeriesGreen"]


def test_an_imaging_path_opens_the_series_it_names(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(second_imaging=True))
    named = path / "acquisition" / "TwoPhotonSeriesGreen"

    assert NWBImagingSource.can_open(named) > NWBImagingSource.can_open(path)
    assert NWBImagingSource.can_open(tmp_path / "missing.nwb" / "acquisition" / "X") == 0.0
    source = _prepared(named)
    assert len(source.frame_times()) == 5 and source.label() == "TwoPhotonSeriesGreen"


def test_a_path_inside_a_file_is_a_source_that_exists(tmp_path: Path) -> None:
    """Restore and relink must not report an imaging series missing because it is not a file."""
    from avialsync.core.source import container_of, source_exists

    path = write_nwb(tmp_path / "s.nwb")
    inside = path / "acquisition" / "TwoPhotonSeries"

    assert container_of(inside) == path
    assert source_exists(inside)
    assert container_of(tmp_path / "gone.mp4") is None
    assert not source_exists(tmp_path / "gone.mp4")
    assert not source_exists(tmp_path / "gone" / "deeper.mp4")


def test_negative_imaging_start_is_placed_by_offset(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(imaging_start=-0.2))

    layout = NWBSessionSource().scan(path, LoaderRegistry())

    imaging = next(item for item in layout.items if item.loader is NWBImagingSource)
    assert imaging.config["offset"] == pytest.approx(0.2)


def test_an_external_video_beside_the_file_is_laid_out_at_its_start(tmp_path: Path) -> None:
    from tests.util_pyav_fixtures import cfr_times, write_video

    video = tmp_path / "cam.mp4"
    write_video(video, frame_times=cfr_times(10), width=64, height=48)
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(external_video="cam.mp4"))

    layout = NWBSessionSource().scan(path, LoaderRegistry())

    item = next(item for item in layout.items if item.path == video.resolve())
    assert item.loader is VideoStandardLoader
    assert item.kind == "Video"
    assert item.source_epoch == pytest.approx(SESSION_EPOCH + 1.5)


def test_a_missing_external_video_is_reported(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(external_video="videos/cam.mp4"))

    layout = NWBSessionSource().scan(path, LoaderRegistry())

    assert any("videos/cam.mp4" in warning for warning in layout.warnings)


def test_a_zone_less_start_time_is_reported(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(session_start="2024-03-05T10:00:00"))

    layout = NWBSessionSource().scan(path, LoaderRegistry())

    assert any("time zone" in warning for warning in layout.warnings)


def test_nwb1_session_includes_signal_and_imaging(tmp_path: Path) -> None:
    layout = NWBSessionSource().scan(write_nwb1(tmp_path / "old.nwb"), LoaderRegistry())

    assert len(layout.items) == 2
    assert layout.anchor_epoch == SESSION_EPOCH
    assert layout.items[1].path.name == "camera"


def test_session_claims_nwb_files_and_zarr_folders_only(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb")
    zarr = write_zarr_nwb(tmp_path / "z.nwb.zarr")

    assert NWBSessionSource.can_open(path) > 0
    assert NWBSessionSource.can_open(zarr) > 0
    assert NWBSessionSource.can_open(tmp_path) == 0.0
    assert len(NWBSessionSource().scan(zarr, LoaderRegistry()).items) == 2


def test_zarr_and_nwb1_imaging_proxies_keep_exact_frames(tmp_path: Path) -> None:
    for path in (
        write_zarr_nwb(tmp_path / "z.nwb.zarr"),
        write_nwb1(tmp_path / "old.nwb"),
    ):
        source = _prepared(path)
        frames = _decode(source.media_path(), "gray16le")
        assert len(frames) == 3
        assert all(
            np.array_equal(actual, expected)
            for actual, expected in zip(frames, _imaging_frames("uint16")[:3], strict=True)
        )


# ── Resolution and intake ─────────────────────────────────────────────────


def test_a_kind_picks_between_the_two_readers_of_one_file(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb")
    registry = LoaderRegistry()

    assert registry.find_best_loader(path) is NWBLoader
    assert registry.find_best_loader(path, kind=TimeSeriesSource) is NWBLoader
    assert registry.find_best_loader(path, kind=VideoSource) is NWBImagingSource
    assert registry.find_best_loader(path / "acquisition" / "TwoPhotonSeries") is NWBImagingSource
    assert registry.find_best_session(path) is NWBSessionSource


def test_dropping_a_file_asks_the_session_scanners(tmp_path: Path, qapp) -> None:
    from avialsync.engine.drop_worker import DropScanWorker

    path = write_nwb(tmp_path / "s.nwb")
    worker = DropScanWorker([path], LoaderRegistry())
    results: list[tuple] = []
    worker.finished.connect(lambda candidates, layout: results.append((candidates, layout)))

    worker.run()

    candidates, layout = results[0]
    assert {loader for _path, loader, _config in candidates} == {NWBLoader, NWBImagingSource}
    assert layout.session_epoch == pytest.approx(SESSION_EPOCH)


def test_a_plain_file_drop_still_resolves_per_file(tmp_path: Path, qapp) -> None:
    from avialsync.engine.drop_worker import DropScanWorker
    from avialsync.loaders.csv_loader import CSVLoader

    csv = tmp_path / "trace.csv"
    csv.write_text("time,v\n0,1\n1,2\n", encoding="utf-8")
    worker = DropScanWorker([csv], LoaderRegistry())
    results: list[tuple] = []
    worker.finished.connect(lambda candidates, layout: results.append((candidates, layout)))

    worker.run()

    assert results[0][0][0][1] is CSVLoader


def test_importing_a_file_spans_every_series_and_keeps_its_units(tmp_path: Path, qapp) -> None:
    from avialsync.engine.importer import ImportWorker

    path = write_nwb(tmp_path / "s.nwb")
    worker = ImportWorker(path, {}, NWBLoader)
    results: list[tuple] = []
    progress: list[int] = []
    worker.finished.connect(lambda *args: results.append(args))
    worker.error.connect(lambda message: pytest.fail(message))
    worker.progress.connect(progress.append)

    worker.run()

    _path, cache_dir, channels, bounds, inspection = results[0]
    assert "ElectricalSeries.ch12" in channels and "units.unit9" in channels
    # Notes start at 0.1 s, ephys at 0, the last trial ends at 9 s and the last note is at 9.5 s.
    assert bounds[0] <= 0.0 and bounds[1] >= 9.0
    assert inspection.channel_units["ElectricalSeries.ch12"] == "V"
    assert any(message.channel == "trials" for message in inspection.messages)
    assert progress == sorted(progress) and progress[-1] == 100
    cache = Path(cache_dir)
    # One stored clock per series, shared by its columns.
    assert (cache / "ElectricalSeries.ch10_t.npy").stat().st_ino == (
        cache / "ElectricalSeries.ch13_t.npy"
    ).stat().st_ino or np.array_equal(
        np.load(cache / "ElectricalSeries.ch10_t.npy"),
        np.load(cache / "ElectricalSeries.ch13_t.npy"),
    )


def test_grouped_import_rejects_undeclared_channels(tmp_path: Path, qapp) -> None:
    from avialsync.engine.importer import ImportWorker

    class Liar(NWBLoader):
        def iter_channel_groups(self):  # type: ignore[override]
            yield ["nobody"], iter([{"nobody": (np.array([0.0]), np.array([1.0]))}])

    path = write_nwb(tmp_path / "s.nwb")
    worker = ImportWorker(path, {}, Liar)
    errors: list[str] = []
    worker.error.connect(errors.append)

    worker.run()

    assert errors and "did not declare" in errors[0]


def test_scan_is_cheap_on_a_file_with_many_series(tmp_path: Path) -> None:
    """Scanning reads attributes and shapes, never samples."""
    path = write_nwb(tmp_path / "s.nwb")
    contents = nwb_format.scan(path)

    assert len(contents.series) >= 7
