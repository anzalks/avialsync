"""The terminal says who is speaking, and says each thing once.

The app configured `logging` nowhere, so every record fell through to the
stdlib's last-resort handler: bare `%(message)s` on stderr. Launching from a
shell produced

    UI thread blocked for 361 ms
    Units "Deg." can not be converted to a quantity. Using dimensionless instead
    Units "Deg." can not be converted to a quantity. Using dimensionless instead

— AvialSync's own stall report and `neo`'s opinion of a recording, in the same
anonymous voice, the second one repeated once per channel carrying the unit.
"""

from __future__ import annotations

import logging

import pytest

from avialsync.logging_setup import ALL_ENV, LEVEL_ENV, DedupeFilter, configure_logging


@pytest.fixture
def console(monkeypatch):
    """Install the handler against a clean environment, and take it out after."""
    monkeypatch.delenv(LEVEL_ENV, raising=False)
    monkeypatch.delenv(ALL_ENV, raising=False)
    root = logging.getLogger()
    before = list(root.handlers)
    level_before = root.level
    handler = configure_logging()
    yield handler
    root.handlers = before
    root.setLevel(level_before)


def _emit(handler, records: list[tuple[str, str]]) -> list[str]:
    """Push (logger name, message) pairs through the handler's own filters."""
    written: list[str] = []
    for name, message in records:
        record = logging.LogRecord(name, logging.WARNING, __file__, 0, message, None, None)
        if all(f.filter(record) for f in handler.filters):
            written.append(handler.format(record))
    return written


def test_a_line_names_the_logger_that_wrote_it(console) -> None:
    """ "Units ... dimensionless" must be visibly neo's opinion, not ours."""
    written = _emit(
        console,
        [
            ("neo.io.proxyobjects", 'Units "Deg." can not be converted to a quantity'),
            ("avialsync.ui.ui_heartbeat", "UI thread blocked for 361 ms"),
        ],
    )

    assert written[0].startswith("WARNING neo.io.proxyobjects: ")
    assert written[1].startswith("WARNING avialsync.ui.ui_heartbeat: ")


def test_one_fact_about_a_recording_is_reported_once(console) -> None:
    """Four channels carrying "Deg." is one fact about the file, not four."""
    units = 'Units "Deg." can not be converted to a quantity. Using dimensionless instead'
    written = _emit(console, [("neo.io.proxyobjects", units)] * 4)

    assert len(written) == 1


def test_distinct_messages_all_get_through(console) -> None:
    """Two stalls of different lengths are two events, not a repeat.

    Deduplication keys on the formatted message; keying on the format string
    would have collapsed these, which is the failure mode that would make a
    stall detector useless.
    """
    written = _emit(
        console,
        [
            ("avialsync.ui.ui_heartbeat", "UI thread blocked for 361 ms"),
            ("avialsync.ui.ui_heartbeat", "UI thread blocked for 2031 ms"),
            ("neo.io.proxyobjects", 'Units "°C" can not be converted to a quantity'),
        ],
    )

    assert len(written) == 3


def test_the_same_words_from_two_libraries_are_two_messages(console) -> None:
    """The logger name is part of the key: nobody is silenced by a coincidence."""
    same = "could not read"
    written = _emit(console, [("neo.rawio", same), ("avialsync.core", same)])

    assert len(written) == 2


def test_a_traceback_is_never_deduplicated() -> None:
    """A repeat carrying an exception is the detail worth seeing again."""
    dedupe = DedupeFilter()
    try:
        raise ValueError("boom")
    except ValueError as error:
        info = (type(error), error, error.__traceback__)

    plain = logging.LogRecord("x", logging.ERROR, __file__, 0, "failed", None, None)
    first = logging.LogRecord("x", logging.ERROR, __file__, 0, "failed", None, info)
    second = logging.LogRecord("x", logging.ERROR, __file__, 0, "failed", None, info)

    assert dedupe.filter(plain)
    assert dedupe.filter(first)
    assert dedupe.filter(second)


def test_the_repeats_can_be_asked_for_back(monkeypatch) -> None:
    """Dropping records needs an escape hatch, or a count becomes unmeasurable."""
    monkeypatch.delenv(LEVEL_ENV, raising=False)
    monkeypatch.setenv(ALL_ENV, "1")
    root = logging.getLogger()
    before, level_before = list(root.handlers), root.level
    try:
        handler = configure_logging()
        assert _emit(handler, [("neo", "same")] * 3) == ["WARNING neo: same"] * 3
    finally:
        root.handlers = before
        root.setLevel(level_before)


def test_the_level_comes_from_the_environment(monkeypatch) -> None:
    monkeypatch.delenv(ALL_ENV, raising=False)
    monkeypatch.setenv(LEVEL_ENV, "DEBUG")
    root = logging.getLogger()
    before, level_before = list(root.handlers), root.level
    try:
        handler = configure_logging()
        assert handler.level == logging.DEBUG
        # The root gate must open too, or the handler's level does nothing.
        assert root.getEffectiveLevel() <= logging.DEBUG
    finally:
        root.handlers = before
        root.setLevel(level_before)


def test_an_unreadable_level_falls_back_rather_than_crashing_the_launch(monkeypatch) -> None:
    """A typo in an env var must not stop the application starting."""
    monkeypatch.delenv(ALL_ENV, raising=False)
    monkeypatch.setenv(LEVEL_ENV, "LOUD")
    root = logging.getLogger()
    before, level_before = list(root.handlers), root.level
    try:
        assert configure_logging().level == logging.WARNING
    finally:
        root.handlers = before
        root.setLevel(level_before)


def test_configuring_twice_does_not_double_every_line(console) -> None:
    """A second call replaces our handler instead of stacking another."""
    root = logging.getLogger()
    before = sum(1 for h in root.handlers if h.get_name() == "avialsync-console")

    configure_logging()

    after = sum(1 for h in root.handlers if h.get_name() == "avialsync-console")
    assert before == after == 1
