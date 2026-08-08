"""The conda-forge recipe must describe the package this repository builds."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

RECIPE = Path("packaging/conda/meta.yaml")
PYPROJECT = Path("pyproject.toml")


def _recipe_text() -> str:
    return RECIPE.read_text(encoding="utf-8")


def _project_metadata() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def test_recipe_version_matches_the_package() -> None:
    """A recipe pinned to a stale version publishes the wrong source archive."""
    declared = _project_metadata()["version"]
    recipe_version = re.search(r'{% set version = "([^"]+)" %}', _recipe_text())

    assert recipe_version is not None, "recipe declares no version"
    assert recipe_version.group(1) == declared


def test_recipe_runtime_covers_every_declared_dependency() -> None:
    """A missing run dependency is an import error on a user's first launch."""
    recipe = _recipe_text().lower()
    run_section = recipe.split("run:", 1)[1].split("test:", 1)[0]

    for dependency in _project_metadata()["dependencies"]:
        # Strip an environment marker ("tzdata; sys_platform == 'win32'")
        # before the version specifier, or the marker's own operators split
        # the name and the assertion looks for something like "tzdata; sys".
        requirement = dependency.split(";", 1)[0]
        name = re.split(r"[<>=!\[]", requirement, maxsplit=1)[0].strip().lower()
        assert f"- {name}" in run_section, f"{name} missing from the recipe's run section"


def test_recipe_declares_no_native_media_runtime() -> None:
    """The conda package is now the same shape as the wheel (D-075).

    Decoding, probing, proxy generation, clip export, and the demo all run
    in-process against the FFmpeg inside PyAV's wheel, so there is no media
    runtime for the recipe to declare. The recipe used to exist partly *because*
    conda could supply one and pip could not; that asymmetry is gone.
    """
    run_section = _recipe_text().lower().split("run:", 1)[1].split("test:", 1)[0]

    assert "- av" in run_section
    assert "- mpv" not in run_section
    assert "- ffmpeg" not in run_section, (
        "the recipe must not reintroduce a native media dependency"
    )


def test_recipe_python_range_matches_the_package() -> None:
    """conda must not offer the package on a Python the project excludes."""
    declared = _project_metadata()["requires-python"].replace(" ", "")
    recipe = _recipe_text()

    assert declared == ">=3.11,<3.13"
    assert recipe.count("python >=3.11,<3.13") >= 2  # host and run


def test_recipe_entry_point_matches_the_package() -> None:
    """The console script conda installs must be the one the package defines."""
    script = _project_metadata()["scripts"]["avialsync"]

    assert f"avialsync = {script}" in _recipe_text()
