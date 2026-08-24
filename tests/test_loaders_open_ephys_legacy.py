"""Tests for the Open Ephys original-format message reader (D-085).

neo reads every other file in one of these folders and deliberately not
``messages.events``, so this is the only path the prose has.  Fixtures are
written from the format's own shape (AGENTS §5): plain ASCII lines of
``<sample number> <text>``, with no 1024-byte header, preceded by the sync
preamble the GUI writes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from avialsync.loaders import open_ephys_legacy as legacy

#: The rate the fixture's preamble declares, as an Open Ephys rig would.
RATE_HZ = 30000.0

#: The 1 MHz software clock on the ``Software time:`` line.  Reading the rate
#: from there instead of from ``start time:`` divides every message by ~33.
SOFTWARE_CLOCK_HZ = 1000000

PREAMBLE = (
    f"0 Software time: 145610@{SOFTWARE_CLOCK_HZ}Hz\n0 Processor: 101 start time: 0@{RATE_HZ:g}Hz\n"
)


def write_legacy(
    root: Path, body: str = "", *, preamble: str = PREAMBLE, rate: float | None = RATE_HZ
) -> Path:
    """Write an original-format recording directory and return it."""
    root.mkdir(parents=True, exist_ok=True)
    (root / legacy.MESSAGES_NAME).write_text(preamble + body, encoding="utf-8")

    # Every other file in the folder opens with 1024 bytes of "key = value;".
    header = f"header.sampleRate = {rate:g};\n".encode() if rate else b"header.foo = 1;\n"
    (root / "100_CH1.continuous").write_bytes(header.ljust(1024, b"\x00") + b"\x00" * 64)
    return root


def test_a_folder_of_continuous_files_with_messages_is_recognised(tmp_path: Path) -> None:
    assert legacy.is_legacy_recording(write_legacy(tmp_path / "rec"))


def test_messages_alone_are_not_a_recording(tmp_path: Path) -> None:
    """A stray messages file is not a folder of samples to hang them on."""
    lone = tmp_path / "stray"
    lone.mkdir()
    (lone / legacy.MESSAGES_NAME).write_text(PREAMBLE, encoding="utf-8")
    assert not legacy.is_legacy_recording(lone)


def test_typed_messages_are_read_with_times(tmp_path: Path) -> None:
    """The whole point: text neo discards, on the axis neo puts samples on."""
    recording = write_legacy(
        tmp_path / "rec",
        body="60000 baseline start\n90000 stimulus on\n",
    )
    messages = legacy.read_messages(recording)

    assert [m.text for m in messages] == ["baseline start", "stimulus on"]
    assert [m.time for m in messages] == pytest.approx([2.0, 3.0])
    assert {m.channel for m in messages} == {legacy.MESSAGES_NAME}


def test_the_sync_preamble_is_used_not_shown(tmp_path: Path) -> None:
    """A preamble places the clock; it is not something a person wrote.

    The binary format's ``sync_messages.txt`` is treated the same way — parsed
    for its epoch, never listed as a note.
    """
    recording = write_legacy(tmp_path / "rec", body="60000 baseline start\n")
    texts = [m.text for m in legacy.read_messages(recording)]

    assert texts == ["baseline start"]
    assert not any("Software time" in text for text in texts)
    assert not any("start time" in text for text in texts)


def test_the_software_clock_is_not_mistaken_for_the_sample_rate(tmp_path: Path) -> None:
    """``Software time:`` runs at 1 MHz; ``start time:`` carries the real rate."""
    recording = write_legacy(tmp_path / "rec", body="60000 baseline start\n")
    (time,) = [m.time for m in legacy.read_messages(recording)]

    assert time == pytest.approx(60000 / RATE_HZ)
    assert time != pytest.approx(60000 / SOFTWARE_CLOCK_HZ)


def test_a_missing_preamble_falls_back_to_the_continuous_header(tmp_path: Path) -> None:
    """Every ``.continuous`` file states the rate, so the folder still answers."""
    recording = write_legacy(tmp_path / "rec", body="60000 baseline start\n", preamble="")
    (time,) = [m.time for m in legacy.read_messages(recording)]
    assert time == pytest.approx(2.0)


def test_a_message_with_no_knowable_rate_stays_untimed(tmp_path: Path) -> None:
    """Pinning it to zero would assert a moment the file never recorded (D-078)."""
    recording = write_legacy(
        tmp_path / "rec", body="60000 baseline start\n", preamble="", rate=None
    )
    (message,) = legacy.read_messages(recording)

    assert message.text == "baseline start"
    assert message.time is None


def test_a_line_without_a_stamp_is_kept_as_an_untimed_note(tmp_path: Path) -> None:
    """Still something somebody wrote; the file just did not time it."""
    recording = write_legacy(tmp_path / "rec", body="rig restarted\n60000 baseline start\n")
    messages = legacy.read_messages(recording)

    assert [(m.text, m.time) for m in messages] == [
        ("rig restarted", None),
        ("baseline start", pytest.approx(2.0)),
    ]


def test_an_absent_messages_file_is_not_an_error(tmp_path: Path) -> None:
    """Losing a comment must never fail an import (D-078)."""
    empty = tmp_path / "rec"
    empty.mkdir()
    assert legacy.read_messages(empty) == []


def test_times_are_not_rebased_on_the_first_recorded_sample(tmp_path: Path) -> None:
    """neo's ``_segment_t_start`` is ``timestamp0 / rate``, with no subtraction.

    Rebasing here would offset every note from the trace it describes by the
    recording's own start sample.
    """
    recording = write_legacy(
        tmp_path / "rec",
        body="90000 stimulus on\n",
        preamble=f"0 Processor: 101 start time: 60000@{RATE_HZ:g}Hz\n",
    )
    (time,) = [m.time for m in legacy.read_messages(recording)]

    assert time == pytest.approx(3.0)  # 90000 / 30000, not (90000 - 60000) / 30000


def test_a_signed_level_is_a_level_not_a_message() -> None:
    """The plot/prose test must agree with itself on every numeric spelling.

    ``str.isdigit`` was the test and is False for ``-1``, ``+1`` and ``1.5``.
    A format labelling its lines that way would have them skipped as
    unplottable *and* listed as messages, one row per edge (D-085).
    """
    from avialsync.loaders.neo_loader import _is_numeric_label

    assert all(_is_numeric_label(level) for level in ("1", "-1", "+1", "1.5", "0"))
    assert not any(_is_numeric_label(prose) for prose in ("baseline start", "trial 3", "", "1a"))


def test_a_legacy_recording_routes_to_the_original_format_reader(tmp_path: Path) -> None:
    """``messages()`` must pick the reader by what the folder actually is.

    Driven through ``_resolved_path`` rather than ``open()`` because neo has to
    read a whole valid ``.continuous`` bundle to reach this point, and the seam
    under test is which reader the folder selects — not neo's own parsing, which
    its own tests cover.
    """
    from avialsync.loaders.neo_loader import NeoLoader

    recording = write_legacy(tmp_path / "rec", body="60000 baseline start\n")
    loader = NeoLoader()
    loader._resolved_path = recording

    assert [(m.text, m.time) for m in loader.messages()] == [("baseline start", pytest.approx(2.0))]


def test_a_folder_that_is_neither_format_falls_back_to_neo(tmp_path: Path) -> None:
    """``None`` from the format readers means "use neo's event labels"."""
    from avialsync.loaders.neo_loader import NeoLoader

    plain = tmp_path / "plain"
    plain.mkdir()
    loader = NeoLoader()
    loader._resolved_path = plain

    assert loader._recording_messages() is None
    # No block was opened, so the neo path has nothing to report and must not raise.
    assert loader.messages() == []
