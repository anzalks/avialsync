"""One place that decides what reaches the terminal, and how it reads.

The application never configured ``logging`` at all, so every module and every
dependency fell through to the stdlib's last-resort handler: level WARNING,
destination stderr, format ``"%(message)s"`` — the bare message and nothing
else.  A user launching from a shell saw

    UI thread blocked for 361 ms
    Units "Deg." can not be converted to a quantity. Using dimensionless instead

with no way to tell which line was AvialSync reporting on itself and which was
``neo`` reporting on their recording, and with the second line repeated once
per channel that carried the unit.

Two things fix that, and both are presentation rather than suppression:

* **Name the source.**  Every line is prefixed with its level and logger, so
  ``neo``'s opinion of a file is visibly ``neo``'s.
* **Say each thing once.**  A per-channel warning about a unit string is one
  fact about the recording, not four.  Identical formatted messages after the
  first are dropped; messages that differ — two stalls of different lengths,
  two different unit strings — are all distinct facts and all get through.

This is the terminal only.  It is not the user-facing error path: typed
failures reach people through ``ui/feedback/error_presenter.py``, and source
quality problems through the per-source quality badge (AGENTS rules 10 and 12).
A log line is for whoever launched the process from a shell.
"""

from __future__ import annotations

import logging
import os
import sys

#: Env var overriding the console level, e.g. ``AVIALSYNC_LOG_LEVEL=DEBUG``.
LEVEL_ENV = "AVIALSYNC_LOG_LEVEL"
#: Env var restoring every repeat, for when a count matters more than quiet.
ALL_ENV = "AVIALSYNC_LOG_ALL"

_DEFAULT_LEVEL = logging.WARNING
_FORMAT = "%(levelname)s %(name)s: %(message)s"

#: Marks the handler as ours, so a second call replaces rather than duplicates.
_HANDLER_NAME = "avialsync-console"


class DedupeFilter(logging.Filter):
    """Pass each distinct formatted message once.

    Keyed on the *formatted* message, never on the format string: dropping by
    template would collapse "UI thread blocked for 361 ms" and "... 2031 ms"
    into one event, and those are two stalls, not a repeat.  Keyed with the
    logger name too, so two libraries saying the same words both get heard.
    """

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[tuple[str, int, str]] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        """Return whether *record* is the first of its exact message."""
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken format string is not fatal here
            return True
        # A traceback is the detail that makes a repeat worth seeing again.
        if record.exc_info is not None:
            return True
        key = (record.name, record.levelno, message)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


def _configured_level() -> int:
    """Resolve the console level from the environment, or the default."""
    requested = os.environ.get(LEVEL_ENV, "").strip().upper()
    if not requested:
        return _DEFAULT_LEVEL
    resolved = logging.getLevelName(requested)
    return resolved if isinstance(resolved, int) else _DEFAULT_LEVEL


def configure_logging() -> logging.Handler:
    """Install the console handler, replacing one from an earlier call.

    Returns the handler, so a test can assert what was installed rather than
    inspecting the root logger's list by index.
    """
    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter(_FORMAT))
    if not os.environ.get(ALL_ENV):
        handler.addFilter(DedupeFilter())

    level = _configured_level()
    handler.setLevel(level)
    root.addHandler(handler)
    # The root logger gates before any handler sees a record, so it has to be
    # at least as permissive as the handler or the level above would do nothing.
    root.setLevel(min(root.level or logging.WARNING, level))
    return handler
