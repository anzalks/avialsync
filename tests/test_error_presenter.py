"""Errors are presented, never dumped (WP-6, AGENTS rule 12, D-088).

Every failure used to reach the user as ``f"Could not do X:\\n{exception}"`` in a
modal box with an OK button -- an exception string, in the vocabulary of the
code that failed, offering nothing to do about it.

:func:`test_every_error_type_has_a_presenter` is the guard that matters: it
enumerates ``core/errors.py``, so a new exception type without a presentation
fails CI rather than silently falling back to its own repr.
"""

from __future__ import annotations

import inspect

import pytest
from PySide6.QtWidgets import QApplication

from avialsync.core import errors as errors_module
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
from avialsync.core.inspection import ImportReport, IntegrityFlags, SourceInspection
from avialsync.ui import recovery
from avialsync.ui.feedback.error_presenter import present, presentation_for
from avialsync.ui.main_window import MainWindow
from avialsync.ui.quality_badge import findings_for, worst_severity


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    win.close()


def _all_error_types() -> list[type[BaseException]]:
    return [
        obj
        for _name, obj in inspect.getmembers(errors_module, inspect.isclass)
        if issubclass(obj, AvialSyncError) and obj.__module__ == errors_module.__name__
    ]


# ── the conformance guard ────────────────────────────────────────────


def test_every_error_type_has_a_presenter() -> None:
    """A new exception without a presentation must fail here, not in the field."""
    for error_type in _all_error_types():
        presented = presentation_for(error_type.__new__(error_type))
        assert presented.title, f"{error_type.__name__} has no title"
        assert presented.cause, f"{error_type.__name__} has no cause"


def test_error_types_were_actually_discovered() -> None:
    """Guards the guard: an empty sweep would pass the test above vacuously."""
    assert len(_all_error_types()) >= 8


# ── what a presentation contains ─────────────────────────────────────


@pytest.mark.parametrize(
    "error",
    [
        SourceOpenError("boom"),
        FileUnreadableError("boom"),
        CodecUnsupportedError("boom"),
        CacheError("boom"),
        LoaderContractError("boom"),
        SyncEvidenceError("boom"),
        SyncAmbiguityError("boom"),
        MissingColumnError("t", ["a", "b"]),
        NonMonotonicTimeError("boom", row=42),
    ],
    ids=lambda e: type(e).__name__,
)
def test_a_presentation_is_in_the_users_terms(error: BaseException) -> None:
    presented = presentation_for(error)
    assert presented.title
    assert len(presented.cause.split()) >= 8, "a cause should be a sentence, not a word"
    assert presented.details, "the raw text must be kept, behind Show details"


def test_the_raw_exception_is_not_in_the_message() -> None:
    """Raw text belongs behind Show details, not in the sentence."""
    presented = presentation_for(SourceOpenError("Errno 2 no such file: /x/y.mp4"))
    assert "Errno 2" not in presented.title
    assert "Errno 2" not in presented.cause
    assert "Errno 2" in presented.details


def test_recoveries_are_named_actions() -> None:
    presented = presentation_for(SourceOpenError("boom"))
    labels = [recovery_action.label for recovery_action in presented.recoveries]
    assert "Locate file…" in labels
    assert all(action.action_id for action in presented.recoveries)


def test_a_missing_column_names_what_is_available() -> None:
    """The actionable part is what the file does have."""
    presented = presentation_for(MissingColumnError("time", ["t_sec", "force", "angle"]))
    assert "t_sec" in presented.cause


def test_a_non_monotonic_error_names_the_row() -> None:
    presented = presentation_for(NonMonotonicTimeError("backwards", row=1234))
    assert "1234" in presented.cause


def test_an_unknown_exception_still_presents() -> None:
    """A plugin can raise anything; the user still gets a sentence."""
    presented = presentation_for(ValueError("something odd"))
    assert presented.title
    assert "ValueError" in presented.details


def test_a_subclass_inherits_its_parents_presentation() -> None:
    class _NewSyncProblem(SyncEvidenceError):
        pass

    presented = presentation_for(_NewSyncProblem("boom"))
    assert "evidence" in presented.cause.lower() or "evidence" in presented.title.lower()


def test_doing_replaces_the_generic_title() -> None:
    presented = present(SourceOpenError("boom"), doing="Could not open cam2.mp4")
    assert presented.title == "Could not open cam2.mp4"
    assert presented.recoveries, "the recoveries the type earned are kept"


# ── nothing is refused (Law 1) ───────────────────────────────────────


def test_every_presentation_is_recoverable() -> None:
    """Load failures inform; they never stop the session appearing."""
    for error_type in _all_error_types():
        presented = presentation_for(error_type.__new__(error_type))
        assert presented.recoverable is True


def test_report_failure_uses_the_strip_not_a_modal(window: MainWindow) -> None:
    window.report_failure(SourceOpenError("no such file"), doing="Could not open cam1.mp4")
    assert window.notifications.message.startswith("Could not open cam1.mp4")
    assert window.notifications.is_sticky is True, "a failure must not fade before it is read"
    assert "no such file" in window.notifications.details


# ── data-quality findings (the other dirtiness) ──────────────────────


def test_a_clean_source_reports_nothing() -> None:
    inspection = SourceInspection(path="/tmp/a.csv", import_report=ImportReport())
    assert findings_for(inspection) == []


def test_no_inspection_reports_nothing() -> None:
    assert findings_for(None) == []


def test_gaps_are_reported_with_a_time_to_jump_to() -> None:
    inspection = SourceInspection(
        path="/tmp/a.csv",
        import_report=ImportReport(gap_count=3, gap_locations=(12.5, 40.0, 91.2)),
    )
    findings = findings_for(inspection)
    gap = next(f for f in findings if "gap" in f.summary)
    assert gap.at_time == 12.5
    assert "3" in gap.summary


def test_rows_out_of_order_are_an_error_not_a_note() -> None:
    """Dropped non-monotonic rows change what the data means."""
    inspection = SourceInspection(
        path="/tmp/a.csv",
        import_report=ImportReport(rows_dropped_nonmonotonic=7),
    )
    findings = findings_for(inspection)
    assert worst_severity(findings) == "error"


def test_sentinel_values_say_how_to_undo_the_assumption() -> None:
    inspection = SourceInspection(path="/tmp/a.csv", import_report=ImportReport(sentinel_count=12))
    detail = findings_for(inspection)[0].detail
    assert "re-import" in detail.lower()


def test_vfr_is_information_not_a_problem() -> None:
    """AvialSync handles it correctly; the user should know, not worry."""
    inspection = SourceInspection(path="/tmp/a.mp4", integrity_flags=IntegrityFlags(is_vfr=True))
    findings = findings_for(inspection)
    assert findings[0].severity == "info"


def test_a_declared_rate_mismatch_is_a_warning() -> None:
    inspection = SourceInspection(
        path="/tmp/a.mp4", integrity_flags=IntegrityFlags(fps_mismatch=True)
    )
    assert worst_severity(findings_for(inspection)) == "warning"


def test_missing_alignment_is_reported() -> None:
    inspection = SourceInspection(path="/tmp/a.mp4")
    findings = findings_for(inspection, has_accepted_alignment=False)
    assert any("alignment" in f.summary.lower() for f in findings)


def test_findings_are_ordered_worst_first() -> None:
    inspection = SourceInspection(
        path="/tmp/a.csv",
        import_report=ImportReport(nan_count=5, rows_dropped_nonmonotonic=2, gap_count=1),
    )
    severities = [f.severity for f in findings_for(inspection)]
    assert severities == sorted(severities, key=["error", "warning", "info"].index)


def test_worst_severity_of_nothing_is_empty() -> None:
    assert worst_severity([]) == ""
