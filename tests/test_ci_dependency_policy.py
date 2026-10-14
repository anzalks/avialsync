"""CI/release installs share tested interpreter-specific runtime and build constraints."""

import re
from pathlib import Path

import yaml

WORKFLOWS = [Path(".github/workflows/ci.yml"), Path(".github/workflows/release.yml")]


def test_every_python_install_has_runtime_and_isolated_build_constraints() -> None:
    for path in WORKFLOWS:
        workflow = yaml.safe_load(path.read_text())
        for name, job in workflow["jobs"].items():
            installs = [step for step in job["steps"] if "pip install" in step.get("run", "")]
            if not installs:
                continue
            env = {**workflow.get("env", {}), **job.get("env", {})}
            assert "requirements/ci-py" in env["PIP_CONSTRAINT"], (path, name)
            assert env["PIP_BUILD_CONSTRAINT"] == env["PIP_CONSTRAINT"]
            assert any("pip install --upgrade pip" in step.get("run", "") for step in installs)
            assert any(
                step.get("uses", "").startswith("actions/checkout@") for step in job["steps"]
            )
            for step in job["steps"]:
                settings = step.get("with", {})
                if settings.get("cache") == "pip":
                    assert "requirements/ci-py*.txt" in settings["cache-dependency-path"]


def test_constraints_are_exact_unique_pins_and_preserve_qt_upper_bound() -> None:
    for path in Path("requirements").glob("ci-py*.txt"):
        lines = [
            line for line in path.read_text().splitlines() if line and not line.startswith("#")
        ]
        assert all(re.fullmatch(r"[a-zA-Z0-9_.-]+==[^\s;]+", line) for line in lines)
        names = [line.split("==")[0].lower() for line in lines]
        assert len(names) == len(set(names))
        pins = dict(line.split("==") for line in lines)
        assert (
            pins["pyside6"]
            == pins["pyside6-addons"]
            == pins["pyside6-essentials"]
            == pins["shiboken6"]
        )
        assert tuple(map(int, pins["pyside6"].split(".")[:2])) < (6, 12)
        assert {
            "hatchling",
            "pytest",
            "numpy",
            "av",
            "polars",
            "mypy",
            "ruff",
            "pyinstaller",
        } <= pins.keys()


def test_native_quality_matrix_preserves_full_tests_and_enforces_coverage_once() -> None:
    for path, name in [(WORKFLOWS[0], "test"), (WORKFLOWS[1], "quality")]:
        job = yaml.safe_load(path.read_text())["jobs"][name]
        matrix = job["strategy"]["matrix"]
        assert matrix["os"] == ["ubuntu-24.04", "macos-15", "windows-2022"]
        assert matrix["python-version"] == ["3.11", "3.12"]
        assert "exclude" not in matrix
        steps = job["steps"]
        test = next(step for step in steps if step.get("run", "").startswith("pytest "))
        assert "--ignore=tests/benchmarks" in test["run"]
        assert "--cov=avialsync" in test["run"] and "--timeout=60" in test["run"]
        gate = next(step for step in steps if "tools/check_coverage.py" in step.get("run", ""))
        assert gate["if"] == "runner.os == 'Linux' && matrix.python-version == '3.12'"
    assert "mypy --strict src/avialsync/core" in WORKFLOWS[0].read_text()
    assert "mypy --strict src/avialsync/core" in WORKFLOWS[1].read_text()


def test_every_workflow_apt_install_excludes_recommends() -> None:
    for path in WORKFLOWS:
        for line in path.read_text().splitlines():
            if "apt-get install" in line and not line.strip().startswith("#"):
                assert "--no-install-recommends" in line, (path, line)
    assert "xvfb xauth" in WORKFLOWS[1].read_text()


def test_hosted_documentation_uses_the_same_runtime_and_build_constraints() -> None:
    config = yaml.safe_load(Path(".readthedocs.yaml").read_text())
    commands = config["build"]["jobs"]["install"]
    assert all("--constraint requirements/ci-py3.12.txt" in command for command in commands)
    assert "--build-constraint requirements/ci-py3.12.txt" in commands[-1]
    assert config["sphinx"]["fail_on_warning"]
