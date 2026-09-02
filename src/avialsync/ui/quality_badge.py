"""What is wrong with a recording, said plainly (D-088, Law 1).

"Dirty" has two meanings and this module is the second one.  *Document* dirty
is unsaved changes, and the title bar carries it.  *Data* dirty is the source
itself — gaps, NaN and sentinel runs, a frame rate the container lied about,
dropped exposures, an alignment nobody has accepted.

None of it blocks anything.  A file with every one of these findings still
loads, still plays, and still exports; the user is *told*, never stopped.  That
is the whole of Law 1 applied to data: partial success beats refusal, and a
scientist is entitled to look at an imperfect recording without arguing with a
dialog first.

The loaders already detect all of this — ``IntegrityFlags`` and
``ImportReport`` have carried it since Phase 3.  Until now it reached the user
as a bare "⚠" that opened a properties sheet.  This turns the same data into
sentences, with the time to jump to where the evidence is.
"""

from __future__ import annotations

import dataclasses

from avialsync.core.inspection import SourceInspection

__all__ = ["Finding", "findings_for", "worst_severity"]

#: Ordered worst-first, so a badge can colour itself from the highest finding.
_SEVERITY_ORDER = ("error", "warning", "info")


@dataclasses.dataclass(frozen=True)
class Finding:
    """One thing worth knowing about a loaded source."""

    #: "error", "warning", or "info". Nothing here is fatal -- an error is
    #: something that will produce wrong conclusions if unnoticed, not
    #: something that stopped the load.
    severity: str
    #: A few words, for the badge tooltip.
    summary: str
    #: A sentence or two: what it is, and what it means for the data.
    detail: str
    #: Master time to jump to, when the finding has a location.
    at_time: float | None = None


def _gap_findings(inspection: SourceInspection) -> list[Finding]:
    report = inspection.import_report
    if report is None:
        return []
    findings: list[Finding] = []

    if report.gap_count:
        first = report.gap_locations[0] if report.gap_locations else None
        findings.append(
            Finding(
                severity="warning",
                summary=f"{report.gap_count} gap{'s' if report.gap_count != 1 else ''} in time",
                detail=(
                    f"The recording stops and resumes {report.gap_count} time"
                    f"{'s' if report.gap_count != 1 else ''}. Traces are drawn with the gap "
                    "left empty rather than bridged, so nothing is invented across it."
                ),
                at_time=first,
            )
        )

    if report.nan_count:
        findings.append(
            Finding(
                severity="info",
                summary=f"{report.nan_count} missing samples",
                detail=(
                    f"{report.nan_count} samples are NaN. They are excluded from ranges "
                    "and statistics rather than counted as zero."
                ),
            )
        )

    if report.sentinel_count:
        findings.append(
            Finding(
                severity="warning",
                summary=f"{report.sentinel_count} sentinel values",
                detail=(
                    f"{report.sentinel_count} samples matched the sentinel this import was "
                    "configured with and were read as missing. If that value is real data "
                    "in this recording, re-import without the sentinel setting."
                ),
            )
        )

    dropped = report.rows_dropped_nonmonotonic
    if dropped:
        findings.append(
            Finding(
                severity="error",
                summary=f"{dropped} rows out of order",
                detail=(
                    f"{dropped} rows had timestamps that went backwards and were dropped, "
                    "because they cannot be placed on the master clock. A wrapped counter "
                    "or a concatenated recording is the usual cause, and both mean the "
                    "time base needs checking before drawing conclusions."
                ),
            )
        )

    if report.rows_dropped_duplicate:
        findings.append(
            Finding(
                severity="info",
                summary=f"{report.rows_dropped_duplicate} duplicate timestamps",
                detail=(
                    f"{report.rows_dropped_duplicate} rows repeated a timestamp already "
                    "seen; the first was kept."
                ),
            )
        )

    return findings


def _timing_findings(inspection: SourceInspection) -> list[Finding]:
    flags = inspection.integrity_flags
    findings: list[Finding] = []

    if flags.is_vfr:
        findings.append(
            Finding(
                severity="info",
                summary="Variable frame rate",
                detail=(
                    "Frames are not evenly spaced. AvialSync uses each frame's own "
                    "presentation timestamp, so this is handled correctly — but a nominal "
                    "frame rate quoted elsewhere will not describe this recording."
                ),
            )
        )

    if flags.fps_mismatch:
        findings.append(
            Finding(
                severity="warning",
                summary="Declared rate disagrees with the frames",
                detail=(
                    "The container declares one frame rate and the frame timestamps imply "
                    "another. The measured rate is used. Anything computed from the "
                    "declared rate elsewhere will drift against this recording."
                ),
            )
        )

    if flags.frames_dropped:
        findings.append(
            Finding(
                severity="warning",
                summary="Dropped frames",
                detail=(
                    "The camera's own counter skips exposures it never stored. Alignment "
                    "is unaffected — timestamps are still correct — but the recording has "
                    "less temporal resolution than its frame rate suggests."
                ),
            )
        )

    if flags.fps_provisional:
        findings.append(
            Finding(
                severity="warning",
                summary="Frame rate assumed, not read",
                detail=(
                    "This source counts frames rather than recording time, and no frame "
                    "rate was declared, so one was assumed. Every timestamp derived from "
                    "it is provisional until a video supplies the real rate."
                ),
            )
        )

    if flags.drift_nonzero:
        findings.append(
            Finding(
                severity="info",
                summary="Drift correction applied",
                detail=(
                    "A non-zero drift maps this source onto the master clock. The file's "
                    "own timestamps are unchanged — the correction is a mapping."
                ),
            )
        )

    return findings


def findings_for(
    inspection: SourceInspection | None,
    *,
    has_accepted_alignment: bool = True,
) -> list[Finding]:
    """Everything worth telling the user about one source, worst first.

    *has_accepted_alignment* is passed in rather than read off the inspection
    because alignment is a property of the session, not of the file: the same
    recording is aligned in one session and not in another.
    """
    if inspection is None:
        return []

    findings = _gap_findings(inspection) + _timing_findings(inspection)

    if not has_accepted_alignment:
        findings.append(
            Finding(
                severity="info",
                summary="No accepted alignment",
                detail=(
                    "This source sits on the master clock by its own timestamps alone. "
                    "That is correct when the hardware shared a clock, and a guess when "
                    "it did not."
                ),
            )
        )

    return sorted(findings, key=lambda f: _SEVERITY_ORDER.index(f.severity))


def worst_severity(findings: list[Finding]) -> str:
    """The highest severity present, or "" when there is nothing to report."""
    for severity in _SEVERITY_ORDER:
        if any(finding.severity == severity for finding in findings):
            return severity
    return ""
