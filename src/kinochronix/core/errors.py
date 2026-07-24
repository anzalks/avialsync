"""KinoChronix exception hierarchy."""

from typing import Any


class KinoChronixError(Exception):
    """Base exception for all KinoChronix errors."""

    pass


class NonMonotonicTimeError(KinoChronixError):
    """Raised when time series timestamps go backwards."""

    def __init__(self, message: str, row: int, context: Any = None):
        super().__init__(message)
        self.row = row
        self.context = context


class SourceOpenError(KinoChronixError):
    """Raised when a media or data source fails to open."""

    pass


class CacheError(KinoChronixError):
    """Raised when the sidecar binary cache encounters an error."""

    pass
