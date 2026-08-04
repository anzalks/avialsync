"""Sphinx configuration for the AvialSync Read the Docs site."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPOSITORY_ROOT / "src"))

project = "AvialSync"
author = "Anzal K Shahul"
copyright = "2026, Anzal K Shahul"

# Read from the installed package rather than repeating it here. A hardcoded
# value said 0.0.1 through five releases, because nothing fails when it drifts.
try:
    release = _installed_version("avialsync")
except PackageNotFoundError:  # building from a source tree without an install
    release = "0.0.0+unknown"

# Sphinx reads any module-level `version` as its own config value, so this must
# stay a string. Binding `importlib.metadata.version` here instead made the
# build die with "expected string or bytes-like object, got 'function'".
version = ".".join(release.split(".")[:2])

extensions = ["myst_parser"]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
master_doc = "index"
exclude_patterns = ["_build"]
myst_heading_anchors = 3

#: Without this, `_static/` is never copied into the build and every image in
#: the documentation 404s while the build still reports success.
html_static_path = ["_static"]

html_theme = "furo"
html_title = f"AvialSync {release}"
html_logo = "_static/avialsync-logo.png"
html_favicon = "_static/avialsync-logo.png"
# Furo's three documented source options are the whole customisation: they add
# the "Edit this page" link. No custom CSS, JS, or footer markup — the theme
# default is what readers of Python documentation already know how to use.
html_theme_options = {
    "source_repository": "https://github.com/anzalks/avialsync/",
    "source_branch": "main",
    "source_directory": "docs/",
}
