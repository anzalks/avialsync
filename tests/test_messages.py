"""Recorded messages: the core record, the store that maps them, and the panel."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QTableWidget

from avialsync.core.inspection import SourceInspection
from avialsync.core.messages import (
    MAX_MESSAGE_CHARS,
    MAX_MESSAGES,
    Message,
    bounded,
    clean,
)
from avialsync.core.source import TimeSeriesSource
from avialsync.ui.message_panel import MessagePanel, MessageStore

# ── The core record ──────────────────────────────────────────────────────


def test_message_round_trips_through_a_manifest_dict() -> None:
    """Messages survive the sidecar, which is the only path a cache hit takes."""
    original = Message(text="stimulus on", time=12.5, channel="MessageCenter")
    assert Message.from_dict(original.as_dict()) == original


def test_untimed_message_keeps_its_missing_time() -> None:
    """``None`` must not round-trip to 0.0 — that would assert a moment.

    A comment appended after a recording has no place on the clock, and a
    header serialised as t=0 would appear to describe the first sample.
    """
    note = Message(text="see lab notebook p.42")
    assert note.time is None
    assert Message.from_dict(note.as_dict()).time is None


def test_clean_folds_newlines_and_bounds_length() -> None:
    assert clean("two\nlines   here") == "two lines here"
    assert len(clean("x" * (MAX_MESSAGE_CHARS * 2))) == MAX_MESSAGE_CHARS


def test_bounded_puts_untimed_first_then_sorts_by_time() -> None:
    ordered = bounded(
        [
            Message(text="late", time=9.0),
            Message(text="header"),
            Message(text="early", time=1.0),
        ]
    )
    assert [m.text for m in ordered] == ["header", "early", "late"]


def test_bounded_caps_a_runaway_logger() -> None:
    """A rig logging prose per sample must not put millions of strings in JSON."""
    ordered = bounded([Message(text=f"m{i}", time=float(i)) for i in range(MAX_MESSAGES + 500)])
    assert len(ordered) == MAX_MESSAGES


def test_v1_plugins_report_no_messages() -> None:
    """The contract hook is additive: a frozen v1 loader must still satisfy it."""

    class LegacySource(TimeSeriesSource):
        @classmethod
        def can_open(cls, path):  # type: ignore[no-untyped-def]
            return 0.0

        def open(self, path, config):  # type: ignore[no-untyped-def]
            return None

        def channels(self):  # type: ignore[no-untyped-def]
            return []

        def read_chunks(self, ch):  # type: ignore[no-untyped-def]
            return iter(())

    assert LegacySource().messages() == []


def test_inspection_without_messages_key_loads() -> None:
    """A manifest written before this feature must still open, with no messages.

    This is why the import cache version is not bumped: every sidecar already on
    a user's disk stays valid, and re-importing is what gains the messages.
    """
    legacy = {"path": "/tmp/x.dat", "loader_id": "NeoLoader"}
    assert SourceInspection.from_dict(legacy).messages == ()


# ── The store ────────────────────────────────────────────────────────────


def test_store_maps_source_time_to_master(qtbot) -> None:
    """A message rides the source's TimeMap, like the samples it describes."""
    store = MessageStore()
    store.set_source_mapping("/data/a.dat", offset=2.0, drift_ppm=0.0)
    store.set_source_messages("/data/a.dat", (Message(text="go", time=10.0),))

    (mapped,) = store.messages()
    assert mapped.time == pytest.approx(8.0)


def test_offset_correction_moves_messages_with_the_samples(qtbot) -> None:
    """Re-aligning a source must not leave its notes behind on the old clock."""
    store = MessageStore()
    store.set_source_messages("/data/a.dat", (Message(text="go", time=10.0),))
    assert store.messages()[0].time == pytest.approx(10.0)

    store.set_source_mapping("/data/a.dat", offset=4.0, drift_ppm=0.0)
    assert store.messages()[0].time == pytest.approx(6.0)


def test_one_recordings_notes_are_not_repeated_per_stream(qtbot) -> None:
    """A session fans one recording into several streams; the note is still one.

    Each stream's import carries the same annotation stream, so without this the
    panel shows a four-stream recording's every message four times.
    """
    store = MessageStore()
    note = Message(text="stimulus on", time=6.0, channel="MessageCenter")
    store.set_source_messages("/rec/board", (note,))
    store.set_source_messages("/rec/aux", (note,))

    assert [m.text for m in store.messages()] == ["stimulus on"]


def test_distinct_notes_at_the_same_instant_both_survive(qtbot) -> None:
    """Dedup keys on text as well as time, or a real second note vanishes."""
    store = MessageStore()
    store.set_source_messages(
        "/rec/board",
        (Message(text="stimulus on", time=6.0), Message(text="animal moved", time=6.0)),
    )
    assert len(store.messages()) == 2


def test_removing_a_source_removes_its_messages(qtbot) -> None:
    store = MessageStore()
    store.set_source_messages("/data/a.dat", (Message(text="go", time=1.0),))
    store.remove_source("/data/a.dat")
    assert store.messages() == []


def test_untimed_notes_lead_the_list(qtbot) -> None:
    store = MessageStore()
    store.set_source_messages(
        "/data/a.dat",
        (Message(text="timed", time=5.0), Message(text="preamble")),
    )
    assert [m.text for m in store.messages()] == ["preamble", "timed"]


# ── The panel ────────────────────────────────────────────────────────────


def _table(panel: MessagePanel) -> QTableWidget:
    return panel.findChild(QTableWidget)


def test_panel_lists_timed_messages_in_order(qtbot) -> None:
    store = MessageStore()
    panel = MessagePanel(store)
    qtbot.addWidget(panel)
    store.set_source_messages(
        "/data/a.dat",
        (Message(text="second", time=9.0), Message(text="first", time=1.0)),
    )

    table = _table(panel)
    assert table.rowCount() == 2
    assert table.item(0, 2).text() == "first"
    assert table.item(1, 2).text() == "second"


def test_panel_never_lets_a_data_record_be_edited(qtbot) -> None:
    """The text belongs to the source file; an editable cell would invite a lie."""
    store = MessageStore()
    panel = MessagePanel(store)
    qtbot.addWidget(panel)
    store.set_source_messages("/data/a.dat", (Message(text="go", time=1.0),))

    assert _table(panel).editTriggers() == QTableWidget.EditTrigger.NoEditTriggers


def test_untimed_notes_are_not_rows_in_the_timed_table(qtbot) -> None:
    """A header has no time, so it must not occupy a sorted time column."""
    store = MessageStore()
    panel = MessagePanel(store)
    qtbot.addWidget(panel)
    store.set_source_messages(
        "/data/a.dat",
        (Message(text="preamble"), Message(text="timed", time=3.0)),
    )

    table = _table(panel)
    assert table.rowCount() == 1
    assert table.item(0, 2).text() == "timed"


def test_selecting_a_row_asks_for_a_seek(qtbot) -> None:
    store = MessageStore()
    panel = MessagePanel(store)
    qtbot.addWidget(panel)
    store.set_source_messages("/data/a.dat", (Message(text="go", time=7.5),))

    with qtbot.waitSignal(panel.seek_requested) as blocker:
        _table(panel).selectRow(0)
    assert blocker.args[0] == pytest.approx(7.5)


def test_filter_narrows_the_table(qtbot) -> None:
    store = MessageStore()
    panel = MessagePanel(store)
    qtbot.addWidget(panel)
    store.set_source_messages(
        "/data/a.dat",
        (Message(text="stimulus on", time=1.0), Message(text="animal moved", time=2.0)),
    )

    panel._search.setText("stimulus")
    table = _table(panel)
    assert table.rowCount() == 1
    assert table.item(0, 2).text() == "stimulus on"
