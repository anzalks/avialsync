"""Trigger evidence from a CSV: the file says when, the config says what of."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avialsync.core.errors import FileUnreadableError
from avialsync.core.registry import LoaderRegistry
from avialsync.core.triggers import TriggerKind
from avialsync.loaders.trigger_csv import LEVEL, TIMESTAMPS, TriggerCSVSource


def _write_daq(path: Path, *, rate: float = 1000.0, seconds: float = 4.0) -> Path:
    """A DAQ export: a time column and three logical lines sampled alongside it.

    Two cameras strobing at different rates and one shared sync pulse, which is
    the shape of a real two-camera rig.
    """
    times = np.arange(0.0, seconds, 1.0 / rate)
    front = np.zeros_like(times)
    side = np.zeros_like(times)
    sync = np.zeros_like(times)
    for index in range(int(seconds * 20)):  # front camera at 20 Hz
        rise = 0.01 + index * 0.05
        front[(times >= rise) & (times < rise + 0.004)] = 1.0
    for index in range(int(seconds * 10)):  # side camera at 10 Hz
        rise = 0.01 + index * 0.1
        side[(times >= rise) & (times < rise + 0.004)] = 1.0
    for index in range(int(seconds)):  # 1 Hz shared sync
        rise = 0.02 + index * 1.0
        sync[(times >= rise) & (times < rise + 0.05)] = 1.0

    lines = ["t,front_strobe,side_strobe,sync_ttl"]
    lines += [
        f"{t:.6f},{f:.1f},{s:.1f},{y:.1f}"
        for t, f, s, y in zip(times, front, side, sync, strict=True)
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class TestFindingIt:
    def test_a_header_naming_trigger_lines_is_recognised(self, tmp_path: Path) -> None:
        assert TriggerCSVSource.can_open(_write_daq(tmp_path / "ttl.csv")) == pytest.approx(0.9)

    def test_a_plain_data_csv_is_not_volunteered_for(self, tmp_path: Path) -> None:
        """Most CSVs in a recording folder are data, not triggers."""
        path = tmp_path / "trace.csv"
        path.write_text("t,voltage,current\n0,1,2\n", encoding="utf-8")

        assert TriggerCSVSource.can_open(path) < 0.5

    def test_a_csv_without_a_time_column_is_refused_outright(self, tmp_path: Path) -> None:
        path = tmp_path / "odd.csv"
        path.write_text("frame,ttl\n0,1\n", encoding="utf-8")

        assert TriggerCSVSource.can_open(path) == 0.0

    def test_a_directory_is_not_a_trigger_file(self, tmp_path: Path) -> None:
        assert TriggerCSVSource.can_open(tmp_path) == 0.0

    def test_the_registry_offers_it(self) -> None:
        registry = LoaderRegistry()
        assert TriggerCSVSource in registry.triggers()

    def test_the_registry_resolves_a_file_to_it(self, tmp_path: Path) -> None:
        assert LoaderRegistry().trigger_for(_write_daq(tmp_path / "ttl.csv")) is TriggerCSVSource


class TestSuggestingAStartingPoint:
    def test_every_trigger_shaped_column_is_offered(self, tmp_path: Path) -> None:
        suggested = TriggerCSVSource.suggest_trains(_write_daq(tmp_path / "ttl.csv"))

        assert len(suggested) == 1
        columns = [train["column"] for train in suggested[0]["trains"]]
        assert columns == ["front_strobe", "side_strobe", "sync_ttl"]
        assert suggested[0]["time_column"] == "t"

    def test_nothing_is_ever_suggested_as_a_strobe(self, tmp_path: Path) -> None:
        """The one decision that must not be made for the user.

        Whether these pulses were emitted by exposures that *happened* is a
        fact about the wiring the file cannot describe, and it is what decides
        whether an exact per-frame mapping is allowed.
        """
        suggested = TriggerCSVSource.suggest_trains(_write_daq(tmp_path / "ttl.csv"))

        kinds = {train["kind"] for train in suggested[0]["trains"]}
        assert kinds == {str(TriggerKind.SYNC_TRAIN)}


class TestReadingTheTrains:
    def test_several_channels_align_several_things(self, tmp_path: Path) -> None:
        """One file, three trains, each about a different target."""
        source = TriggerCSVSource()
        source.open(
            _write_daq(tmp_path / "ttl.csv"),
            {
                "time_column": "t",
                "trains": [
                    {
                        "id": "front",
                        "column": "front_strobe",
                        "kind": str(TriggerKind.FRAME_STROBE),
                        "mode": LEVEL,
                        "target": "front.mp4",
                    },
                    {
                        "id": "side",
                        "column": "side_strobe",
                        "kind": str(TriggerKind.FRAME_STROBE),
                        "mode": LEVEL,
                        "target": "side.mp4",
                    },
                    {
                        "id": "sync",
                        "column": "sync_ttl",
                        "kind": str(TriggerKind.SYNC_TRAIN),
                        "mode": LEVEL,
                    },
                ],
            },
        )

        assert source.trains() == ["front", "side", "sync"]
        assert source.target_hint("front") == "front.mp4"
        assert source.target_hint("sync") == ""

        front, front_durations = source.read_train("front")
        side, _ = source.read_train("side")
        sync, _ = source.read_train("sync")

        assert len(front) == pytest.approx(80, abs=1)
        assert len(side) == pytest.approx(40, abs=1)
        assert len(sync) == pytest.approx(4, abs=1)
        # A strobe is timestamped at its exposure midpoint and carries duration.
        assert front_durations is not None
        assert float(np.mean(front_durations)) == pytest.approx(0.004, abs=5e-4)

    def test_two_cameras_become_alignable_to_each_other(self, tmp_path: Path) -> None:
        """Camera-to-camera, through the sensor that saw both strobes.

        Neither camera is a reference for the other directly; the DAQ that
        recorded both trains is, and each camera maps onto it.
        """
        from avialsync.core.sync import fit_sync_events

        source = TriggerCSVSource()
        source.open(
            _write_daq(tmp_path / "ttl.csv"),
            {
                "time_column": "t",
                "trains": [
                    {
                        "id": "front",
                        "column": "front_strobe",
                        "kind": str(TriggerKind.FRAME_STROBE),
                        "mode": LEVEL,
                    },
                    {
                        "id": "side",
                        "column": "side_strobe",
                        "kind": str(TriggerKind.FRAME_STROBE),
                        "mode": LEVEL,
                    },
                ],
            },
        )
        front, _ = source.read_train("front")
        side, _ = source.read_train("side")

        # The side camera's own file starts 1.5 s into the session.
        proposal = fit_sync_events(side, side + 1.5, reference_id="daq:side", target_id="side.mp4")

        assert proposal.acceptable
        assert proposal.fit.offset == pytest.approx(1.5, abs=1e-3)
        # And both cameras now share the DAQ's clock, which is what makes them
        # comparable to one another.
        assert front[0] < side[-1]

    def test_a_timestamp_column_is_read_as_events(self, tmp_path: Path) -> None:
        """A camera log: one row per exposure, no waveform to threshold."""
        path = tmp_path / "log.csv"
        path.write_text(
            "time,exposure_time\n" + "\n".join(f"{i},{i * 0.04:.4f}" for i in range(50)),
            encoding="utf-8",
        )
        source = TriggerCSVSource()
        source.open(
            path,
            {
                "trains": [
                    {
                        "id": "exposures",
                        "column": "exposure_time",
                        "kind": str(TriggerKind.FRAME_TRIGGER),
                        "mode": TIMESTAMPS,
                    }
                ]
            },
        )

        times, durations = source.read_train("exposures")

        assert len(times) == 50
        assert times[1] - times[0] == pytest.approx(0.04)
        assert durations is None, "a list of instants has no second edge"


class TestRefusals:
    def _open(self, tmp_path: Path, config: dict) -> None:
        TriggerCSVSource().open(_write_daq(tmp_path / "ttl.csv"), config)

    def test_no_declared_trains_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(FileUnreadableError, match="no trains declared"):
            self._open(tmp_path, {"time_column": "t", "trains": []})

    def test_a_missing_column_is_refused_at_open(self, tmp_path: Path) -> None:
        """While the user is still in the import dialog, not once an alignment
        has been built around it."""
        with pytest.raises(FileUnreadableError, match="no column 'nope'"):
            self._open(
                tmp_path,
                {
                    "time_column": "t",
                    "trains": [
                        {
                            "id": "a",
                            "column": "nope",
                            "kind": str(TriggerKind.SYNC_TRAIN),
                            "mode": LEVEL,
                        }
                    ],
                },
            )

    def test_an_unknown_kind_lists_the_known_ones(self, tmp_path: Path) -> None:
        with pytest.raises(FileUnreadableError, match="frame_strobe"):
            self._open(
                tmp_path,
                {
                    "time_column": "t",
                    "trains": [
                        {"id": "a", "column": "sync_ttl", "kind": "whatever", "mode": LEVEL}
                    ],
                },
            )

    def test_duplicate_train_ids_are_refused(self, tmp_path: Path) -> None:
        with pytest.raises(FileUnreadableError, match="both called"):
            self._open(
                tmp_path,
                {
                    "time_column": "t",
                    "trains": [
                        {
                            "id": "a",
                            "column": "sync_ttl",
                            "kind": str(TriggerKind.SYNC_TRAIN),
                            "mode": LEVEL,
                        },
                        {
                            "id": "a",
                            "column": "front_strobe",
                            "kind": str(TriggerKind.SYNC_TRAIN),
                            "mode": LEVEL,
                        },
                    ],
                },
            )

    def test_a_folder_says_so_rather_than_failing_to_parse(self, tmp_path: Path) -> None:
        with pytest.raises(FileUnreadableError, match="is a folder"):
            TriggerCSVSource().open(tmp_path, {"trains": []})

    def test_asking_for_a_train_that_is_not_there_lists_what_is(self, tmp_path: Path) -> None:
        source = TriggerCSVSource()
        source.open(
            _write_daq(tmp_path / "ttl.csv"),
            {
                "time_column": "t",
                "trains": [
                    {
                        "id": "sync",
                        "column": "sync_ttl",
                        "kind": str(TriggerKind.SYNC_TRAIN),
                        "mode": LEVEL,
                    }
                ],
            },
        )
        with pytest.raises(FileUnreadableError, match="It offers: sync"):
            source.read_train("front")
