"""Plugin checks report bad contracts while keeping discovery and bounded reads usable."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from avialsync.core.plugin_check import check_path, list_plugins
from avialsync.core.source import (
    ChannelInfo,
    ImagingMetadata,
    ImagingSource,
    SessionItem,
    SessionLayout,
    TimeSeriesSource,
)
from avialsync.loaders.video_standard import VideoStandardLoader


class SeriesSource(TimeSeriesSource):
    """A fixture plugin whose contract can be varied independently of parsing."""

    declared: list[ChannelInfo] = [ChannelInfo("signal", "V", "float64", 1.0)]
    chunks: tuple = ((np.array([0.0, 1.0]), np.array([3.0, 4.0])),)

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 1.0

    def open(self, path: Path, config: dict) -> None:
        return None

    def channels(self) -> list[ChannelInfo]:
        return self.declared

    def read_chunks(self, channel: str) -> Iterator:
        yield from self.chunks


class StackSource(ImagingSource):
    """Fixture imaging planes with independently declared presentation times."""

    times = np.array([0.0, 1.0])

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 1.0

    def open(self, path: Path, config: dict) -> ImagingMetadata:
        return ImagingMetadata(len(self.times), 2, 2, "uint16", self.times, "fixture")

    def read_frame(self, index: int, channel: int = 0) -> np.ndarray:
        return np.zeros((2, 2), dtype=np.uint16)

    def close(self) -> None:
        return None


class MovieSource(VideoStandardLoader):
    """Fixture video metadata independent of a container or decoder."""

    times: np.ndarray | None = np.array([0.0, 1.0])

    def open(self, path: Path, config: dict) -> None:
        return None

    def frame_times(self) -> np.ndarray | None:
        return self.times


def _registry(loader: type | None, session: type | None = None, tied: bool = False) -> object:
    return SimpleNamespace(
        find_best_session=lambda path: session,
        tied_sessions=lambda path: [session, session] if tied and session else [],
        find_best_loader=lambda path: loader,
        tied_loaders=lambda path: [loader, loader] if tied and loader else [],
    )


def test_discovery_report_keeps_disabled_plugins_and_load_failures_visible() -> None:
    registry = SimpleNamespace(
        plugins=lambda: [("data", SeriesSource, "fixture")],
        is_enabled=lambda cls: False,
        plugin_errors=[("broken", "dependency unavailable")],
    )
    report = list_plugins(registry)
    assert not report.ok
    assert "[switched off]" in report.text()
    assert "dependency unavailable" in report.text()


def test_unclaimed_and_tied_files_are_reported(tmp_path: Path) -> None:
    path = tmp_path / "source.fixture"
    assert "nothing installed claims" in check_path(_registry(None), path).text()
    report = check_path(_registry(SeriesSource, tied=True), path)
    assert not report.ok and "same score" in report.text()


@pytest.mark.parametrize(
    ("chunks", "fragment"),
    [
        (((np.array([[0.0]]), np.array([1.0])),), "1-D arrays"),
        (((np.array([0.0]), np.array([1.0, 2.0])),), "one length"),
        (((np.array([1.0, 0.0]), np.array([1.0, 2.0])),), "backwards"),
        (
            ((np.array([0.0, 1.0]), np.array([1.0, 2.0])), (np.array([0.5]), np.array([3.0]))),
            "backwards",
        ),
    ],
)
def test_bad_chunk_shapes_or_order_fail_the_contract(
    tmp_path: Path, monkeypatch, chunks: tuple, fragment: str
) -> None:
    monkeypatch.setattr(SeriesSource, "chunks", chunks)
    report = check_path(_registry(SeriesSource), tmp_path / "data.fixture")
    assert not report.ok and fragment in report.text()


def test_empty_chunks_and_bounded_sampling_remain_usable(tmp_path: Path, monkeypatch) -> None:
    chunks = (
        (np.array([]), np.array([])),
        (np.array([0.0]), np.array([1.0])),
        (np.array([1.0]), np.array([2.0])),
        (np.array([-1.0]), np.array([3.0])),
    )
    monkeypatch.setattr(SeriesSource, "chunks", chunks)
    report = check_path(_registry(SeriesSource), tmp_path / "data.fixture")
    assert report.ok and report.text().endswith("OK")


@pytest.mark.parametrize(
    "declared", [[], [ChannelInfo("bad", "V", "float64", 1.0, trigger="invented_kind")]]
)
def test_missing_channels_or_unknown_trigger_semantics_are_reported(
    tmp_path: Path, monkeypatch, declared: list
) -> None:
    monkeypatch.setattr(SeriesSource, "declared", declared)
    assert not check_path(_registry(SeriesSource), tmp_path / "data.fixture").ok


@pytest.mark.parametrize(
    ("loader", "times", "valid"),
    [
        (StackSource, np.array([0.0, 1.0]), True),
        (StackSource, np.array([0.0, 0.0]), False),
        (MovieSource, None, True),
        (MovieSource, np.array([0.0, 1.0]), True),
        (MovieSource, np.array([1.0, 0.0]), False),
    ],
)
def test_imaging_and_video_timing_contracts(
    tmp_path: Path, monkeypatch, loader: type, times: np.ndarray | None, valid: bool
) -> None:
    monkeypatch.setattr(loader, "times", times)
    assert check_path(_registry(loader), tmp_path / "image.fixture").ok == valid


def test_plugin_open_exception_is_a_report_problem(tmp_path: Path, monkeypatch) -> None:
    def fail(*_args) -> None:
        raise ValueError("bad header")

    monkeypatch.setattr(SeriesSource, "open", fail)
    assert (
        "ValueError: bad header"
        in check_path(_registry(SeriesSource), tmp_path / "bad.fixture").text()
    )


def test_session_checks_all_epochs_trials_warnings_and_unclaimed_items(tmp_path: Path) -> None:
    class Scanner:
        @classmethod
        def display_name(cls) -> str:
            return "Session"

        def scan(self, path: Path, registry: object) -> SessionLayout:
            return SessionLayout(
                items=[
                    SessionItem(path / "data.fixture", None, {"offset": 0.0}, source_epoch=200.0)
                ],
                segments=[(150.0, 150.0, "empty"), (100.0, 105.0, "overlap")],
                warnings=["missing camera"],
                session_epoch=100.0,
                anchor_epoch=100.0,
            )

    report = check_path(_registry(None, Scanner, tied=True), tmp_path)
    text = report.text()
    assert not report.ok and "same score" in text
    assert "missing camera" in text and "no loader" in text
    assert "session_epoch" in text and "anchor_epoch" in text
    assert "both an offset" in text and "not an absolute instant" in text
    assert "ends at or before" in text and "inside the trial before" in text


def test_session_scan_exception_does_not_abort_the_checker(tmp_path: Path) -> None:
    class BrokenScanner:
        @classmethod
        def display_name(cls) -> str:
            return "Session"

        def scan(self, path: Path, registry: object) -> SessionLayout:
            raise OSError("missing header")

    report = check_path(_registry(None, BrokenScanner), tmp_path)
    assert "scan raised OSError: missing header" in report.text()
