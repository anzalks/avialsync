"""AvialSync's own icon set, as SVG markup (D-169).

Drawn for this application on a 24-unit grid with 2-unit round strokes, and
licensed with it (AGPL-3.0-or-later): no third-party set, so no licence to
track and nothing to download. The markup lives in Python rather than in
``.svg`` files so the wheel and the PyInstaller bundle carry it with no
packaging rule of their own -- a missing data file is an empty button, found
by a user.

Colour in the markup is irrelevant. ``icons.svg_icon`` renders the shape and
inks it in the button's own palette colour, exactly as ``glyph_icon`` re-inks
Qt's standard icons, so every glyph follows the theme.
"""

from __future__ import annotations

__all__ = ["GLYPHS", "svg"]

_OPEN = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="#000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
)
_CLOSE = "</svg>"

#: Each value is the inside of one ``<svg>``: strokes by default, ``fill`` where
#: a solid shape reads better at 16 px (the transport triangles, the dots).
GLYPHS: dict[str, str] = {
    # Playback
    "play": '<path d="M7 4.5v15l12-7.5z" fill="#000"/>',
    "pause": '<rect x="6" y="5" width="4" height="14" rx="1" fill="#000"/>'
    '<rect x="14" y="5" width="4" height="14" rx="1" fill="#000"/>',
    "frame-back": '<path d="M6 5v14"/><path d="M18 5.5v13L9 12z" fill="#000"/>',
    "frame-forward": '<path d="M18 5v14"/><path d="M6 5.5v13L15 12z" fill="#000"/>',
    "jump-back": '<path d="M12 6v12l-8-6z" fill="#000"/><path d="M20 6v12l-8-6z" fill="#000"/>',
    "jump-forward": '<path d="M4 6v12l8-6z" fill="#000"/><path d="M12 6v12l8-6z" fill="#000"/>',
    "loop-in": '<path d="M9 4H5v16h4"/><path d="M11 12h8"/><path d="M16 9l3 3-3 3"/>',
    "loop-out": '<path d="M15 4h4v16h-4"/><path d="M13 12H5"/><path d="M8 9l-3 3 3 3"/>',
    "loop-clear": '<path d="M6 4H3v16h3"/><path d="M18 4h3v16h-3"/>'
    '<path d="M9 9l6 6"/><path d="M15 9l-6 6"/>',
    # Viewing
    "zoom-in": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L20 20"/>'
    '<path d="M10.5 7.5v6"/><path d="M7.5 10.5h6"/>',
    "zoom-out": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L20 20"/>'
    '<path d="M7.5 10.5h6"/>',
    "fit": '<path d="M4 9V4h5"/><path d="M15 4h5v5"/><path d="M20 15v5h-5"/><path d="M9 20H4v-5"/>',
    "fullscreen": '<path d="M4 9V4h5"/><path d="M4 4l6 6"/><path d="M20 15v5h-5"/>'
    '<path d="M20 20l-6-6"/>',
    "snapshot": '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
    "eye": '<path d="M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z"/>'
    '<circle cx="12" cy="12" r="3"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13 7l4 4"/>',
    "marker": '<circle cx="12" cy="12" r="5"/><path d="M12 2v5"/><path d="M12 17v5"/>'
    '<path d="M2 12h5"/><path d="M17 12h5"/>',
    "flag": '<path d="M5 21V4"/><path d="M5 4h12l-2.5 4L17 12H5"/>',
    # Commands
    "close": '<path d="M6 6l12 12"/><path d="M18 6L6 18"/>',
    "remove": '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>'
    '<path d="M10 11v6"/><path d="M14 11v6"/>',
    "reset": '<path d="M4 4v6h6"/><path d="M5.5 15a7.5 7.5 0 1 0 1.8-7.8L4 10"/>',
    "open": '<path d="M3 7V5h6l2 2h10v12H3z"/><path d="M3 10h18"/>',
    "add": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "more": '<circle cx="5" cy="12" r="1.6" fill="#000"/><circle cx="12" cy="12" r="1.6" '
    'fill="#000"/><circle cx="19" cy="12" r="1.6" fill="#000"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "settings": '<path d="M4 6h10"/><path d="M18 6h2"/><circle cx="16" cy="6" r="2"/>'
    '<path d="M4 12h2"/><path d="M10 12h10"/><circle cx="8" cy="12" r="2"/>'
    '<path d="M4 18h10"/><path d="M18 18h2"/><circle cx="16" cy="18" r="2"/>',
    # Kinds of source and inspector pages
    "video": '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3z"/>',
    "data": '<path d="M3 12c2-6 4-6 6 0s4 6 6 0 4-6 6 0"/>',
    # A field of view with two cells in it: an imaging stack, not a camera.
    "imaging": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="10" r="2.5"/>'
    '<circle cx="15.5" cy="15" r="2"/>',
    "sources": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "values": '<path d="M4 6h3"/><path d="M11 6h9"/><path d="M4 12h3"/><path d="M11 12h9"/>'
    '<path d="M4 18h3"/><path d="M11 18h9"/>',
    "messages": '<path d="M4 5h16v11H9l-5 4z"/>',
    "changes": '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 8v4l3 2"/>',
    "props": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5"/>'
    '<path d="M12 12v9"/><path d="M12 12L4 7.5"/>',
    "align": '<path d="M4 7h10"/><path d="M10 17h10"/><path d="M12 4v16"/>'
    '<path d="M9 10l3-3 3 3"/>',
    "tasks": '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    "warning": '<path d="M12 3L2 20h20z"/><path d="M12 9v5"/><path d="M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5h.01"/>',
}


def svg(name: str) -> bytes:
    """Return the complete SVG document for glyph *name*."""
    return f"{_OPEN}{GLYPHS[name]}{_CLOSE}".encode()
