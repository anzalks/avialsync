"""Enforce overall and complete core line/branch coverage from coverage.py JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CORE_PREFIX = "src/avialsync/core/"


def _relative_name(name: str) -> str:
    """Normalize Windows separators and absolute checkout paths."""
    normalized = name.replace("\\", "/")
    return normalized[normalized.index(CORE_PREFIX) :] if CORE_PREFIX in normalized else normalized


def evaluate(report: dict[str, Any], root: Path) -> list[str]:
    """Return every failed requirement, using integer counts rather than rounded percentages."""
    problems: list[str] = []
    files = report.get("files", {})
    if not report.get("meta", {}).get("branch_coverage"):
        problems.append("Branch coverage must be enabled.")
    totals = report.get("totals", {})
    covered = totals.get("covered_lines", 0) + totals.get("covered_branches", 0)
    total = totals.get("num_statements", 0) + totals.get("num_branches", 0)
    if not total or covered * 100 < total * 80:
        percentage = covered * 100 / total if total else 0.0
        problems.append(f"Overall line/branch coverage {percentage:.2f}% is below 80%.")
    core = {
        _relative_name(name): data
        for name, data in files.items()
        if CORE_PREFIX in name.replace("\\", "/")
    }
    expected = {path.relative_to(root).as_posix() for path in (root / CORE_PREFIX).rglob("*.py")}
    if not expected:
        problems.append("No core source files were found.")
    for name in sorted(expected - core.keys()):
        problems.append(f"Missing core coverage: {name}")
    for name, data in sorted(core.items()):
        summary = data["summary"]
        missing_lines = summary["num_statements"] - summary["covered_lines"]
        missing_branches = summary["num_branches"] - summary["covered_branches"]
        if missing_lines or missing_branches:
            problems.append(
                f"{name}: {missing_lines} lines and {missing_branches} branches uncovered."
            )
    return problems


def main() -> int:
    """Read one report, print gate failures, and return a failing exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        problems = evaluate(report, root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Coverage report could not be checked: {error}")
        return 1
    for problem in problems:
        print(problem)
    if not problems:
        print("Coverage gate passed: overall >=80%; every core line and branch covered.")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
