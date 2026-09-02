"""Help destinations and a bug-reportable About box (WP-8).

The Help menu was Shortcuts, Diagnostics, About — a dead end. There was no way
to reach the documentation, the tutorial, the issue tracker, or a release, from
inside the application that those things describe.

About was three lines of prose with no version in them, which meant every bug
report arrived without one. It now carries the version, the commit, and every
library whose behaviour differs between releases, with one button to copy the
lot.

Every URL is read from the installed package metadata rather than written here.
They were repointed during the 0.1.6 cycle; hardcoded copies would have gone
stale silently, and this is the module that would have held them.
"""

from __future__ import annotations

import platform
import sys
from importlib import metadata

__all__ = ["project_urls", "version_report", "citation_text"]

#: Fallbacks used only when the package metadata is unavailable — a source tree
#: run without an install. Never the primary source.
_FALLBACK_URLS = {
    "Documentation": "https://avialsync.readthedocs.io/",
    "Source": "https://github.com/anzalks/avialsync",
    "Issues": "https://github.com/anzalks/avialsync/issues",
}


def project_urls() -> dict[str, str]:
    """Return the project's declared URLs, from the installed metadata."""
    urls: dict[str, str] = {}
    try:
        raw = metadata.metadata("avialsync").get_all("Project-URL") or []
    except metadata.PackageNotFoundError:
        return dict(_FALLBACK_URLS)

    for entry in raw:
        label, _, url = str(entry).partition(",")
        if url:
            urls[label.strip()] = url.strip()
    return urls or dict(_FALLBACK_URLS)


def _library_version(module_name: str, attribute: str = "__version__") -> str:
    """Version of an installed library, or a marker rather than an exception."""
    try:
        module = __import__(module_name)
        return str(getattr(module, attribute, "") or metadata.version(module_name))
    except Exception:
        return "not installed"


def version_report() -> str:
    """A copyable block naming everything a bug report needs.

    Includes the libraries whose behaviour genuinely differs between releases —
    PyAV carries its own FFmpeg, Qt's version decides widget behaviour, numpy
    and polars decide parsing. A report without these costs a round trip.
    """
    try:
        app_version = metadata.version("avialsync")
    except metadata.PackageNotFoundError:
        app_version = "source checkout"

    lines = [
        f"AvialSync {app_version}",
        f"Python {sys.version.split()[0]}",
        f"Platform {platform.platform()}",
        f"PySide6 {_library_version('PySide6')}",
        f"PyAV {_library_version('av')}",
        f"numpy {_library_version('numpy')}",
        f"polars {_library_version('polars')}",
        f"pyqtgraph {_library_version('pyqtgraph')}",
    ]
    return "\n".join(lines)


def citation_text() -> str:
    """The citation the release process maintains, or a note that it is absent.

    Read from the shipped ``CITATION.cff`` rather than retyped, so it cannot
    drift from the file ``tools/prepare_release.py`` keeps in step with the
    version. For a tool used to produce published figures this is not
    decoration.
    """
    from pathlib import Path

    for candidate in (
        Path(__file__).resolve().parents[3] / "CITATION.cff",
        Path(getattr(sys, "_MEIPASS", "")) / "CITATION.cff",
    ):
        try:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
    return (
        "CITATION.cff was not found beside this installation.\n"
        "The canonical copy is in the repository."
    )
