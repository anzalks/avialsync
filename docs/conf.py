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
html_theme_options = {
    "source_repository": "https://github.com/anzalks/avialsync/",
    "source_branch": "main",
    "source_directory": "docs/",
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/anzalks/avialsync",
            "html": (
                '<svg stroke="currentColor" fill="currentColor" viewBox="0 0 16 16">'
                '<path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 '
                "7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-"
                ".48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 "
                "2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-"
                ".08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1"
                ".53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.8"
                "7 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8"
                '.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"></path></svg>'
            ),
            "class": "",
        },
    ],
}
