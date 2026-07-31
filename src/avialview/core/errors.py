"""AvialView exception hierarchy."""

from typing import Any


class AvialViewError(Exception):
    """Base exception for all AvialView errors."""

    pass


class NonMonotonicTimeError(AvialViewError):
    """Raised when time series timestamps go backwards."""

    def __init__(self, message: str, row: int, context: Any = None):
        super().__init__(message)
        self.row = row
        self.context = context


class SourceOpenError(AvialViewError):
    """Raised when a media or data source fails to open."""

    pass


class CacheError(AvialViewError):
    """Raised when the sidecar binary cache encounters an error."""

    pass


class CodecUnsupportedError(AvialViewError):
    """Raised when a video codec is not supported."""

    pass


class MissingColumnError(AvialViewError):
    """Raised when a required CSV column is missing."""

    def __init__(self, column: str, available: list[str]):
        self.column = column
        self.available = available
        super().__init__(f"Column '{column}' not found. Available: {', '.join(available)}")


class FileUnreadableError(AvialViewError):
    """Raised when a file cannot be read or parsed."""

    pass


class LoaderContractError(AvialViewError):
    """Raised when a source plugin violates the frozen v1 ingest contract.

    Distinct from :class:`SourceOpenError`: the file is readable, but the loader
    returned something the importer cannot align — mismatched chunk lengths,
    a missing declared channel, or chunks that disagree about their timestamps.
    The actionable fix is in the plugin, not in the user's data.
    """


class SyncEvidenceError(AvialViewError):
    """Raised when synchronization evidence is malformed or insufficient."""

    pass


class SyncAmbiguityError(SyncEvidenceError):
    """Raised when event evidence supports multiple equally valid alignments."""

    pass
