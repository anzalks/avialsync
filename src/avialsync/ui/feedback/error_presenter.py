"""Errors are presented, never dumped (AGENTS rule 12, D-088).

Every failure used to reach the user the same way: ``f"Could not do X:\\n{e}"``
in a bare ``QMessageBox`` with an OK button.  That is an exception string in a
box.  It tells someone that something failed, in the vocabulary of the code that
failed, and offers nothing to do about it — which AGENTS.md already forbade
("UI layer converts to user dialogs with actionable text") and which the code
did anyway, in forty places.

A presented error has three parts and this module is where they are decided:

**A title** naming what the user was doing, not what the code was doing.
**A cause** in plain language — what happened, and what it means for their data.
**Named recovery actions** — Locate file…, Retry, Open log, Copy diagnostics —
so the dialog is somewhere to act rather than somewhere to click OK.

The raw exception is kept, behind *Show details*.  It is what a bug report
needs and what a scientist reading a dialog does not.

Presentation is non-modal by default (D-091): the strip reports it and the
session stays reachable behind it.  A modal is used only when the user must
choose between recovery actions before anything else can sensibly happen.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from avialsync.core.errors import (
    AvialSyncError,
    CacheError,
    CodecUnsupportedError,
    FileUnreadableError,
    LoaderContractError,
    MissingColumnError,
    NonMonotonicTimeError,
    SourceOpenError,
    SyncAmbiguityError,
    SyncEvidenceError,
)

__all__ = ["Recovery", "PresentedError", "present", "presentation_for"]


@dataclasses.dataclass(frozen=True)
class Recovery:
    """One named thing the user can do about a failure."""

    #: Stable id, so a caller can offer only the actions it can actually honour.
    action_id: str
    label: str


#: The standard actions. A presenter names them; the caller wires the ones it
#: can perform and drops the rest, rather than offering a button that does
#: nothing.
LOCATE = Recovery("locate", "Locate file…")
RETRY = Recovery("retry", "Retry")
OPEN_LOG = Recovery("open_log", "Open log")
COPY_DIAGNOSTICS = Recovery("copy_diagnostics", "Copy diagnostics")
CHOOSE_COLUMN = Recovery("choose_column", "Choose a column…")
REIMPORT = Recovery("reimport", "Re-import with different settings…")


@dataclasses.dataclass(frozen=True)
class PresentedError:
    """A failure, in the user's terms."""

    title: str
    cause: str
    recoveries: tuple[Recovery, ...] = ()
    details: str = ""
    #: Whether the session can carry on without a decision. Almost always True:
    #: partial success beats refusal, and Law 1 says the application informs
    #: rather than blocks.
    recoverable: bool = True


#: What each typed exception means, and what to do about it.
#:
#: Keyed by class rather than matched on message text: a message is prose that
#: changes, a type is a contract. `tests/test_error_presenter.py` enumerates
#: `core/errors.py` against this table, so a new exception type without an
#: entry fails CI rather than silently falling back to its own repr.
_PRESENTERS: dict[type[BaseException], Callable[[BaseException], PresentedError]] = {}


def _register(
    exc_type: type[BaseException],
) -> Callable[
    [Callable[[BaseException], PresentedError]], Callable[[BaseException], PresentedError]
]:
    def decorate(
        builder: Callable[[BaseException], PresentedError],
    ) -> Callable[[BaseException], PresentedError]:
        _PRESENTERS[exc_type] = builder
        return builder

    return decorate


@_register(SourceOpenError)
def _source_open(error: BaseException) -> PresentedError:
    return PresentedError(
        title="That file could not be opened",
        cause=(
            "The file may have moved, be on a disconnected drive, or be in a format "
            "AvialSync has no loader for. Everything else in the session is unaffected."
        ),
        recoveries=(LOCATE, RETRY, COPY_DIAGNOSTICS),
        details=str(error),
    )


@_register(FileUnreadableError)
def _unreadable(error: BaseException) -> PresentedError:
    return PresentedError(
        title="That file could not be read",
        cause=(
            "The file was found but could not be parsed. It may be truncated, still "
            "being written by the acquisition system, or not the format it looks like."
        ),
        recoveries=(LOCATE, RETRY, COPY_DIAGNOSTICS),
        details=str(error),
    )


@_register(CodecUnsupportedError)
def _codec(error: BaseException) -> PresentedError:
    return PresentedError(
        title="That video uses a codec AvialSync cannot decode",
        cause=(
            "The container opened but its video stream is in an unsupported format. "
            "Generating a proxy converts it to something playable without touching "
            "the original recording."
        ),
        recoveries=(COPY_DIAGNOSTICS,),
        details=str(error),
    )


@_register(MissingColumnError)
def _missing_column(error: BaseException) -> PresentedError:
    available = getattr(error, "available", [])
    column = getattr(error, "column", "")
    listed = ", ".join(available[:12]) or "none"
    return PresentedError(
        title=f"No column named {column!r}",
        cause=f"The file was read, but that column is not in it. It has: {listed}.",
        recoveries=(CHOOSE_COLUMN, REIMPORT),
        details=str(error),
    )


@_register(NonMonotonicTimeError)
def _non_monotonic(error: BaseException) -> PresentedError:
    row = getattr(error, "row", None)
    where = f" at row {row}" if row is not None else ""
    return PresentedError(
        title="Timestamps go backwards in that file",
        cause=(
            f"Time steps backwards{where}, so samples cannot be placed on the master "
            "clock in order. This usually means a wrapped counter, a concatenated "
            "recording, or the wrong column chosen as time."
        ),
        recoveries=(REIMPORT, COPY_DIAGNOSTICS),
        details=str(error),
    )


@_register(CacheError)
def _cache(error: BaseException) -> PresentedError:
    return PresentedError(
        title="The sidecar cache could not be used",
        cause=(
            "The parsed copy beside your recording could not be read or written. "
            "Your recording is untouched — cache writes are atomic, so the previous "
            "cache is still valid. Check free space and folder permissions."
        ),
        recoveries=(RETRY, OPEN_LOG, COPY_DIAGNOSTICS),
        details=str(error),
    )


@_register(LoaderContractError)
def _loader_contract(error: BaseException) -> PresentedError:
    return PresentedError(
        title="A format plugin returned data AvialSync cannot use",
        cause=(
            "The file is readable; the plugin that read it returned chunks that do "
            "not line up. This is a defect in the plugin rather than in your data, "
            "so the diagnostics are worth sending to whoever maintains it."
        ),
        recoveries=(COPY_DIAGNOSTICS, OPEN_LOG),
        details=str(error),
    )


@_register(SyncAmbiguityError)
def _sync_ambiguous(error: BaseException) -> PresentedError:
    return PresentedError(
        title="The alignment evidence fits more than one answer",
        cause=(
            "Several offsets match the events equally well, so accepting one would "
            "be a guess. Nothing has been changed. Narrow the evidence — a longer "
            "span, or a channel with a less regular pattern — and try again."
        ),
        recoveries=(RETRY,),
        details=str(error),
    )


@_register(SyncEvidenceError)
def _sync_evidence(error: BaseException) -> PresentedError:
    return PresentedError(
        title="There is not enough evidence to align these sources",
        cause=(
            "Too few events matched to fit an offset worth trusting. Nothing has "
            "been changed. A manual offset is available if the recordings have no "
            "shared events to match."
        ),
        recoveries=(RETRY,),
        details=str(error),
    )


@_register(AvialSyncError)
def _generic(error: BaseException) -> PresentedError:
    return PresentedError(
        title="That did not work",
        cause=(
            "The operation failed and was stopped. Your recordings and the open "
            "session are unchanged."
        ),
        recoveries=(RETRY, COPY_DIAGNOSTICS),
        details=str(error),
    )


def presentation_for(error: BaseException) -> PresentedError:
    """Return the presentation for *error*, walking its class hierarchy.

    Walking the MRO rather than requiring an exact match means a new subclass
    of an already-handled type presents sensibly on the day it is added, and
    the enumeration test only has to insist on the *base* types being covered.
    """
    for klass in type(error).__mro__:
        builder = _PRESENTERS.get(klass)
        if builder is not None:
            return builder(error)
    return PresentedError(
        title="Something went wrong",
        cause=(
            "An unexpected error stopped the operation. Your recordings and the "
            "open session are unchanged."
        ),
        recoveries=(COPY_DIAGNOSTICS, OPEN_LOG),
        details=f"{type(error).__name__}: {error}",
    )


def present(error: BaseException, *, doing: str = "") -> PresentedError:
    """Presentation for *error*, optionally naming what the user was doing.

    *doing* replaces the generic title with the user's own framing — "Could not
    open cam2.mp4" says more than "That file could not be opened" — while the
    cause and the recoveries stay the ones the error type earned.
    """
    presented = presentation_for(error)
    if not doing:
        return presented
    return dataclasses.replace(presented, title=doing)
