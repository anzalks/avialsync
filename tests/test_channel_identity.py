"""Two sources may share a channel name without controlling each other.

P3.5 P1 identity.  Channel names used to be treated as globally unique, so two
files that both contain ``force_z`` overwrote each other's plot row, readout row,
unit, and visibility state.  Identity is now ``(source_id, channel_id)``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from avialsync.core.channel_reader import ChannelKey, MappedChannelReader, disambiguate
from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.engine.export import compute_region_stats, export_data_slice_csv
from avialsync.ui.main_window import MainWindow

SHARED_NAME = "force_z"
LEFT = "/tmp/left-rig.csv"
RIGHT = "/tmp/right-rig.csv"


@pytest.fixture
def two_sources(tmp_path: Path) -> tuple[Path, Path]:
    """Two independent caches that both contain a channel called force_z."""
    times = np.arange(1_000, dtype=np.float64) / 100.0
    left = tmp_path / "left"
    right = tmp_path / "right"
    for directory, scale in ((left, 1.0), (right, -1.0)):
        directory.mkdir()
        PyramidBuilder(directory, SHARED_NAME).build_and_save(times, times * scale)
    return left, right


@pytest.fixture
def window(qapp: QApplication, qtbot, two_sources: tuple[Path, Path]) -> MainWindow:
    left, right = two_sources
    win = MainWindow()
    qtbot.addWidget(win)
    win._on_import_finished(LEFT, str(left), [SHARED_NAME], (0.0, 9.99), None)
    win._on_import_finished(RIGHT, str(right), [SHARED_NAME], (0.0, 9.99), None)
    yield win
    win.close()


# ── ChannelKey ────────────────────────────────────────────────────────


def test_channel_key_is_hashable_and_source_scoped() -> None:
    keys = {ChannelKey(LEFT, SHARED_NAME), ChannelKey(RIGHT, SHARED_NAME)}
    assert len(keys) == 2


def test_label_stays_bare_when_the_name_is_unique() -> None:
    labels = disambiguate([ChannelKey(LEFT, "a"), ChannelKey(RIGHT, "b")])
    assert set(labels.values()) == {"a", "b"}


def test_label_is_qualified_only_for_a_contested_name() -> None:
    labels = disambiguate(
        [
            ChannelKey(LEFT, SHARED_NAME),
            ChannelKey(RIGHT, SHARED_NAME),
            ChannelKey(LEFT, "unique"),
        ]
    )
    assert labels[ChannelKey(LEFT, SHARED_NAME)] == f"{SHARED_NAME} · left-rig.csv"
    assert labels[ChannelKey(RIGHT, SHARED_NAME)] == f"{SHARED_NAME} · right-rig.csv"
    assert labels[ChannelKey(LEFT, "unique")] == "unique"


def test_reader_reports_its_key(two_sources: tuple[Path, Path]) -> None:
    reader = MappedChannelReader(PyramidReader(two_sources[0], SHARED_NAME), None, LEFT)
    assert reader.key == ChannelKey(LEFT, SHARED_NAME)
    assert reader.source_id == LEFT


# ── Plot rows ─────────────────────────────────────────────────────────


def test_both_sources_get_their_own_row(window: MainWindow) -> None:
    keys = {channel.reader.key for channel in window.plot_pane.channels}
    assert keys == {ChannelKey(LEFT, SHARED_NAME), ChannelKey(RIGHT, SHARED_NAME)}


def test_hiding_one_sources_channel_leaves_the_other_visible(window: MainWindow) -> None:
    window._on_channel_visibility_changed(LEFT, SHARED_NAME, False)

    by_source = {ch.reader.source_id: ch.visible for ch in window.plot_pane.channels}
    assert by_source[LEFT] is False
    assert by_source[RIGHT] is True


def test_removing_one_sources_channel_leaves_the_other_loaded(window: MainWindow) -> None:
    window._on_channel_remove_requested(LEFT, SHARED_NAME)

    remaining = [ch.reader.source_id for ch in window.plot_pane.channels]
    assert remaining == [RIGHT]


def test_a_bare_name_matches_every_owner_and_says_so(window: MainWindow, caplog) -> None:
    """An unqualified name is ambiguous; that must be reported, not guessed."""
    with caplog.at_level(logging.WARNING, logger="avialsync.ui.plot_pane"):
        window.plot_pane.set_channel_visible(SHARED_NAME, False)

    assert all(not ch.visible for ch in window.plot_pane.channels)
    assert any("owned by 2 sources" in record.getMessage() for record in caplog.records)


# ── Units ─────────────────────────────────────────────────────────────


def test_units_are_source_scoped(window: MainWindow) -> None:
    window.plot_pane.set_channel_units({ChannelKey(LEFT, SHARED_NAME): "N"})

    units = {ch.reader.source_id: ch.unit for ch in window.plot_pane.channels}
    assert units[LEFT] == "N"
    assert units[RIGHT] == ""


# ── Readout rows ──────────────────────────────────────────────────────


def test_readout_keeps_one_row_per_source(window: MainWindow) -> None:
    readers = [ch.reader for ch in window.plot_pane.channels]
    window.readout_panel.update_sources(readers)

    assert set(window.readout_panel._rows) == {
        ChannelKey(LEFT, SHARED_NAME),
        ChannelKey(RIGHT, SHARED_NAME),
    }


def test_readout_rows_report_different_values_per_source(window: MainWindow) -> None:
    """The two sources hold opposite-signed data; neither may shadow the other."""
    readers = {ch.reader.source_id: ch.reader for ch in window.plot_pane.channels}

    left_value = readers[LEFT].sample_at(5.0)[1]
    right_value = readers[RIGHT].sample_at(5.0)[1]

    assert left_value == pytest.approx(5.0)
    assert right_value == pytest.approx(-5.0)


# ── Export and statistics ─────────────────────────────────────────────


def test_region_stats_emit_one_row_per_source(
    two_sources: tuple[Path, Path], tmp_path: Path
) -> None:
    readers = [
        MappedChannelReader(PyramidReader(two_sources[0], SHARED_NAME), None, LEFT),
        MappedChannelReader(PyramidReader(two_sources[1], SHARED_NAME), None, RIGHT),
    ]

    stats = compute_region_stats(readers, 1.0, 2.0)

    assert len(stats) == 2
    assert {row["source"] for row in stats} == {"left-rig.csv", "right-rig.csv"}
    assert stats[0]["mean"] == pytest.approx(-stats[1]["mean"])


def test_csv_export_labels_each_block_with_its_source(
    two_sources: tuple[Path, Path], tmp_path: Path
) -> None:
    readers = [
        MappedChannelReader(PyramidReader(two_sources[0], SHARED_NAME), None, LEFT),
        MappedChannelReader(PyramidReader(two_sources[1], SHARED_NAME), None, RIGHT),
    ]
    output = tmp_path / "slice.csv"

    export_data_slice_csv(readers, 1.0, 1.02, output)

    text = output.read_text(encoding="utf-8")
    assert "# Source: left-rig.csv" in text
    assert "# Source: right-rig.csv" in text
