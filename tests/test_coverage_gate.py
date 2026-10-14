"""The coverage gate rejects missing code, uncovered branches and rounded-up scores."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.check_coverage import evaluate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def report_root(tmp_path: Path) -> tuple[dict, Path]:
    core = tmp_path / "src" / "avialsync" / "core"
    core.mkdir(parents=True)
    (core / "sample.py").write_text("value = 1\n")
    summary = {"covered_lines": 2, "num_statements": 2, "covered_branches": 2, "num_branches": 2}
    report = {
        "meta": {"branch_coverage": True},
        "totals": dict(summary),
        "files": {"src/avialsync/core/sample.py": {"summary": summary}},
    }
    return report, tmp_path


def test_complete_core_and_eighty_percent_overall_pass(report_root) -> None:
    report, root = report_root
    report["totals"].update(covered_lines=6, num_statements=8)
    assert evaluate(report, root) == []


@pytest.mark.parametrize(
    "counts",
    [
        {"covered_lines": 1},
        {"covered_branches": 1},
        {"covered_lines": 19_999, "num_statements": 20_000},
    ],
)
def test_core_cannot_round_or_average_away_missing_work(report_root, counts: dict) -> None:
    report, root = report_root
    report["files"]["src/avialsync/core/sample.py"]["summary"].update(counts)
    assert any("uncovered" in problem for problem in evaluate(report, root))


def test_overall_threshold_is_independent_of_core(report_root) -> None:
    report, root = report_root
    report["totals"].update(covered_lines=5, num_statements=8)
    assert any("below 80%" in problem for problem in evaluate(report, root))


def test_missing_modules_and_disabled_branch_measurement_fail(report_root) -> None:
    report, root = report_root
    (root / "src/avialsync/core/missing.py").write_text("value = 2\n")
    report["meta"]["branch_coverage"] = False
    problems = evaluate(report, root)
    assert any("Missing core coverage" in problem for problem in problems)
    assert "Branch coverage must be enabled." in problems


def test_absolute_windows_paths_are_checked(report_root) -> None:
    report, root = report_root
    record = report["files"].pop("src/avialsync/core/sample.py")
    report["files"][r"C:\checkout\src\avialsync\core\sample.py"] = record
    assert evaluate(report, root) == []


def test_empty_or_unmeasured_reports_do_not_pass(report_root, tmp_path: Path) -> None:
    report, root = report_root
    empty = copy.deepcopy(report)
    empty["totals"] = {}
    assert evaluate(empty, root)
    assert "No core source files were found." in evaluate(report, tmp_path / "absent")


def test_executable_ellipsis_annotations_and_slices_are_not_excluded(tmp_path: Path) -> None:
    module = tmp_path / "coverage_fixture.py"
    module.write_text("""def choose(flag: bool) -> tuple[str, ...]:
    if flag:
        return ("chosen",)
    return ("other",)

class Indexable:
    def __getitem__(self, key):
        return key

def slice_axis():
    return Indexable()[..., 0]

choose(True)
slice_axis()
""")
    script = """import coverage, json, runpy, sys
c = coverage.Coverage(config_file=sys.argv[1], source=[sys.argv[2]], data_file=None)
c.start()
runpy.run_path(sys.argv[3])
c.stop()
_, statements, excluded, missing, _ = c.analysis2(sys.argv[3])
print(json.dumps({"statements": statements, "excluded": excluded, "missing": missing}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(ROOT / "pyproject.toml"), str(tmp_path), str(module)],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    data = json.loads(result.stdout)
    assert 4 in data["missing"]
    assert 1 in data["statements"] and 11 in data["statements"]
    assert data["excluded"] == []
