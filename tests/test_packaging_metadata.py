"""Tests for published-package compatibility metadata."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


def test_package_caps_python_at_3_12() -> None:
    """Published metadata supports exactly the tested Python range."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    assert metadata["project"]["requires-python"] == ">=3.11,<3.13"


def _declared_version() -> str:
    """The version in pyproject.toml, which every other authority follows."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    return str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])


def test_every_version_authority_agrees() -> None:
    """Four files declare the version, and a release is only safe if all four match.

    ``tools/prepare_release.py`` updates all four, and until now nothing checked
    that it had. Only the conda recipe was pinned to the package
    (``test_conda_recipe.py``); ``__version__`` and ``CITATION.cff`` were not
    pinned to anything.

    ``__version__`` is the one that could ship wrong. ``packaging/avialsync.spec``
    reads it to stamp the frozen bundle and the macOS
    ``CFBundleShortVersionString``, and the release workflow's
    ``verify_release_ref`` compares the *tag* against ``pyproject.toml`` only.
    So a stale ``__version__`` produces a tag, a wheel and a PyPI release that
    all agree on 0.1.8 while the installer reports 0.1.7 -- with every existing
    gate green.

    Hand-editing one file is the obvious way in; a half-applied
    ``prepare_release.py`` run is the other, since it rewrites the four in
    sequence and a failure between them leaves exactly this state.
    """
    root = Path(__file__).parents[1]
    declared = _declared_version()

    module = (root / "src/avialsync/__init__.py").read_text(encoding="utf-8")
    module_version = re.search(r'^__version__ = "([^"]+)"', module, re.MULTILINE)
    assert module_version is not None, "src/avialsync/__init__.py declares no __version__"
    assert module_version.group(1) == declared, (
        f"__version__ is {module_version.group(1)}, pyproject.toml says {declared}; "
        "the frozen bundle would report the wrong version"
    )

    citation = (root / "CITATION.cff").read_text(encoding="utf-8")
    citation_version = re.search(r'^version: "([^"]+)"', citation, re.MULTILINE)
    assert citation_version is not None, "CITATION.cff declares no version"
    assert citation_version.group(1) == declared, (
        f"CITATION.cff is {citation_version.group(1)}, pyproject.toml says {declared}"
    )


def test_the_release_helper_updates_every_authority() -> None:
    """The guard above is only as good as the tool it guards.

    A fifth version authority added later would be caught by nothing: the test
    above enumerates the files it knows about, so it cannot notice one it was
    never told about. This pins the other direction -- the release helper must
    touch each file the guard checks -- so adding an authority without teaching
    the helper fails here.
    """
    helper = (Path(__file__).parents[1] / "tools/prepare_release.py").read_text(encoding="utf-8")

    for authority in ("pyproject.toml", "src/avialsync/__init__.py", "CITATION.cff"):
        assert authority in helper, f"prepare_release.py never updates {authority}"
    assert "packaging/conda/meta.yaml" in helper, "prepare_release.py never updates the recipe"
