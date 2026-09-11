"""Trigger evidence from a CSV, either as a sampled line or as event times.

The two shapes a lab actually has. A DAQ export carries a time column and one
or more logical lines sampled alongside the data, and the events are the
transitions in them. A camera's own log carries a timestamp per exposure, and
the events are the rows. Both arrive as `.csv`; nothing about the file says
which, or which of its columns is a camera strobe rather than a stimulus
marker, or which camera a strobe belongs to.

So the configuration says, and the configuration is what the session stores.
Declaring a column ``frame_strobe`` is a statement about the wiring -- that
these pulses were emitted by exposures that happened -- and
`core.alignment.choose_method` derives the model from it rather than asking the
user to pick one. Declaring it ``frame_trigger`` says the opposite, and gets a
weaker model for it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from avialsync.core.errors import FileUnreadableError
from avialsync.core.source import TriggerSource
from avialsync.core.triggers import TriggerKind, extract_pulses

__all__ = ["LEVEL", "TIMESTAMPS", "TriggerCSVSource", "describe_config"]

#: A column sampled alongside the data; the events are its transitions.
LEVEL = "level"
#: A column holding one timestamp per event; the events are its rows.
TIMESTAMPS = "timestamps"

#: Column names that are a time axis, in the spellings labs actually use.
_TIME_NAMES = ("time", "t", "timestamp", "timestamps", "time_s", "seconds", "sec")

#: Column names that look like a logical line worth offering as a train.
_TRIGGER_HINTS = ("ttl", "trigger", "strobe", "sync", "pulse", "exposure", "frame", "event")


def describe_config(config: dict[str, Any]) -> str:
    """One line naming what this configuration claims, for a report or a log."""
    trains = config.get("trains", [])
    if not trains:
        return "no trigger trains configured"
    return "; ".join(
        f"{train.get('id', '?')} = {train.get('kind', '?')} from column "
        f"{train.get('column', '?')!r}"
        for train in trains
    )


class TriggerCSVSource(TriggerSource):
    """Read declared trigger trains out of a delimited text file.

    Configuration shape::

        {
          "time_column": "t",
          "trains": [
            {"id": "front_strobe", "column": "cam0", "kind": "frame_strobe",
             "mode": "level", "threshold": 0.5, "target": "front.mp4"},
            {"id": "sync", "column": "sync", "kind": "sync_train", "mode": "level"},
            {"id": "stim", "column": "stim_time", "kind": "sparse_events",
             "mode": "timestamps"}
          ]
        }

    ``time_column`` is required for ``level`` trains and ignored by
    ``timestamps`` ones, whose column *is* the time.
    """

    @classmethod
    def display_name(cls) -> str:
        """Named for the kind of evidence, not the rig that produced it."""
        return "Trigger / TTL (CSV)"

    @classmethod
    def display_aliases(cls) -> list[str]:
        """The purposes users come looking for this under."""
        return ["Camera Frame Strobe (CSV)", "Sync Pulse Train (CSV)"]

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._frame: pl.DataFrame | None = None

    # ── discovery ────────────────────────────────────────────────────

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Prefer a delimited file whose header names something trigger-shaped.

        Deliberately below `CSVLoader`'s flat 0.8 unless the header actually
        looks like trigger evidence: most CSVs in a recording folder are data,
        and a format that volunteers for all of them is a format the user has
        to keep correcting.
        """
        if path.is_dir() or path.suffix.lower() not in (".csv", ".tsv", ".txt"):
            return 0.0
        header = _peek_header(path)
        if not header:
            return 0.0
        lowered = [name.strip().lower() for name in header]
        if not any(name in _TIME_NAMES for name in lowered):
            return 0.0
        if any(hint in name for name in lowered for hint in _TRIGGER_HINTS):
            return 0.9
        return 0.2

    @classmethod
    def suggest_trains(cls, path: Path) -> list[dict[str, Any]]:
        """A starting configuration the user corrects, never one applied silently.

        Every suggestion is `sync_train`: the weakest kind that is still useful.
        Guessing `frame_strobe` would be guessing about wiring this file cannot
        describe, and that guess decides whether an exact per-frame mapping is
        allowed -- the one decision that must not be made for the user.
        """
        header = _peek_header(path)
        lowered = [name.strip().lower() for name in header]
        time_column = next((header[i] for i, name in enumerate(lowered) if name in _TIME_NAMES), "")
        trains = [
            {
                "id": header[index],
                "column": header[index],
                "kind": str(TriggerKind.SYNC_TRAIN),
                "mode": LEVEL,
                "threshold": 0.5,
            }
            for index, name in enumerate(lowered)
            if name not in _TIME_NAMES and any(hint in name for hint in _TRIGGER_HINTS)
        ]
        return [{"time_column": time_column, "trains": trains}] if trains else []

    # ── the contract ─────────────────────────────────────────────────

    def open(self, path: Path, config: dict[str, Any]) -> None:
        if path.is_dir():
            raise FileUnreadableError(
                f"{path.name} is a folder, not a delimited file. Choose a single file, "
                "or a format that reads a recording directory."
            )
        try:
            frame = pl.read_csv(path, separator="\t" if path.suffix.lower() == ".tsv" else ",")
        except Exception as error:  # noqa: BLE001 - polars raises many shapes
            raise FileUnreadableError(f"{path.name} could not be read: {error}") from error

        self._path = path
        self._config = dict(config)
        self._frame = frame
        self._validate()

    def trains(self) -> list[str]:
        return [str(train["id"]) for train in self._config.get("trains", [])]

    def kind_of(self, train_id: str) -> str:
        return str(self._train(train_id).get("kind", TriggerKind.SYNC_TRAIN))

    def read_train(self, train_id: str) -> tuple[np.ndarray, np.ndarray | None]:
        train = self._train(train_id)
        column = str(train["column"])
        values = self._column(column)

        if str(train.get("mode", LEVEL)) == TIMESTAMPS:
            times = np.asarray(values, dtype=np.float64)
            times = times[np.isfinite(times)]
            if len(times) and np.any(np.diff(times) <= 0):
                times = np.unique(times)
            # A list of instants has no second edge, so no duration is known.
            # Saying None is the honest answer; a zero would be a measurement.
            return times, None

        time_column = str(self._config.get("time_column", ""))
        times = np.asarray(self._column(time_column), dtype=np.float64)
        pulses = extract_pulses(
            [(times, np.asarray(values, dtype=np.float64))],
            source_id=f"{self._name()}:{train_id}",
            kind=TriggerKind(self.kind_of(train_id)),
            threshold=float(train.get("threshold", 0.5)),
            min_interval=float(train.get("min_interval", 0.0)),
        )
        return pulses.times, pulses.durations

    def target_hint(self, train_id: str) -> str:
        return str(self._train(train_id).get("target", ""))

    # ── internals ────────────────────────────────────────────────────

    def _name(self) -> str:
        return self._path.name if self._path is not None else "trigger-csv"

    def _train(self, train_id: str) -> dict[str, Any]:
        for train in self._config.get("trains", []):
            if str(train.get("id")) == train_id:
                return dict(train)
        raise FileUnreadableError(
            f"{self._name()} has no trigger train called {train_id!r}. It offers: "
            f"{', '.join(self.trains()) or 'none'}."
        )

    def _column(self, name: str) -> pl.Series:
        if self._frame is None:
            raise FileUnreadableError("No trigger file has been opened.")
        if name not in self._frame.columns:
            raise FileUnreadableError(
                f"{self._name()} has no column {name!r}. It has: {', '.join(self._frame.columns)}."
            )
        return self._frame.get_column(name)

    def _validate(self) -> None:
        """Refuse a configuration that names something the file does not have.

        At open, not at read: a train that cannot be read is worth knowing
        about while the user is still looking at the import dialog, not once an
        alignment has been set up around it.
        """
        declared = self._config.get("trains", [])
        if not declared:
            raise FileUnreadableError(
                f"{self._name()} was opened as trigger evidence with no trains declared. "
                "Say which columns are trigger lines and what kind of trigger each one is."
            )
        seen: set[str] = set()
        for train in declared:
            train_id = str(train.get("id", ""))
            if not train_id:
                raise FileUnreadableError("Every trigger train needs an id.")
            if train_id in seen:
                raise FileUnreadableError(f"Two trigger trains are both called {train_id!r}.")
            seen.add(train_id)
            self._column(str(train.get("column", "")))
            try:
                TriggerKind(str(train.get("kind", "")))
            except ValueError:
                raise FileUnreadableError(
                    f"{train_id!r} declares an unknown trigger kind "
                    f"{train.get('kind')!r}. Known kinds: "
                    f"{', '.join(k.value for k in TriggerKind)}."
                ) from None
            if str(train.get("mode", LEVEL)) == LEVEL:
                self._column(str(self._config.get("time_column", "")))


def _peek_header(path: Path) -> list[str]:
    """The first row's field names, without reading the file in."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            first = handle.readline()
    except OSError:
        return []
    separator = "\t" if path.suffix.lower() == ".tsv" else ","
    return [field.strip() for field in first.rstrip("\r\n").split(separator) if field.strip()]
