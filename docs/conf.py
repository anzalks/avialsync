"""Sphinx configuration for the AvialSync Read the Docs site."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

project = "AvialSync"
copyright = "2026, AvialSync contributors"
author = "AvialSync contributors"
release = "0.0.1"

extensions = ["myst_parser"]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
master_doc = "index"
exclude_patterns = ["_build"]
html_theme = "alabaster"
html_title = "AvialSync Documentation"
myst_heading_anchors = 3
