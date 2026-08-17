"""Native-aware dark, light, and system appearance for AvialSync.

System appearance deliberately preserves Qt's platform palette and widget style.  That
means AvialSync follows the user's accent colour, contrast settings, and font choice
instead of imitating an operating-system theme with fixed colours.  The optional Dark
and Light appearances use a restrained palette while retaining that same accent. Theme
selection never changes widget geometry, input behaviour, view state, or playback state.
"""

from __future__ import annotations

import gc
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from PySide6.QtCore import QEvent, QObject, QSettings
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

THEME_DARK = "dark"
THEME_LIGHT = "light"
THEME_SYSTEM = "system"
FONT_SYSTEM = "system"
FONT_SMALL = "small"
FONT_MEDIUM = "medium"
FONT_LARGE = "large"

_system_palettes: dict[int, QPalette] = {}
_palette_listeners_installed: set[int] = set()
_applying_palette: set[int] = set()
_macos_accent: QColor | None = None
_system_fonts: dict[int, QFont] = {}
_font_scales: dict[int, float] = {}
_BASE_FONT_PROPERTY = "avialsync_base_font"
_FONT_FAMILY_PROPERTY = "avialsync_font_family"


def _is_dark_palette(palette: QPalette) -> bool:
    """Return whether a palette has a dark window surface."""
    return palette.color(QPalette.ColorRole.Window).lightnessF() < 0.5


def _system_palette(app: QApplication) -> QPalette:
    """Return the unmodified platform palette captured for *app*."""
    app_id = id(app)
    if app_id not in _system_palettes:
        _system_palettes[app_id] = QPalette(app.palette())
    return QPalette(_system_palettes[app_id])


def _system_font(app: QApplication) -> QFont:
    """Return the platform application font captured before user scaling."""
    app_id = id(app)
    if app_id not in _system_fonts:
        _system_fonts[app_id] = QFont(app.font())
    return QFont(_system_fonts[app_id])


def set_font_family(widget: QWidget, family: str) -> None:
    """Use *family* without opting a widget out of application font scaling."""
    widget.setProperty(_FONT_FAMILY_PROPERTY, family)
    font = QFont(widget.font())
    font.setFamily(family)
    widget.setFont(font)


def _scaled_font(font: QFont, factor: float) -> QFont:
    """Return *font* with its defined size scaled by the selected preference."""
    scaled = QFont(font)
    if scaled.pointSizeF() > 0:
        scaled.setPointSizeF(max(8.0, scaled.pointSizeF() * factor))
    elif scaled.pixelSize() > 0:
        scaled.setPixelSize(max(8, round(scaled.pixelSize() * factor)))
    return scaled


@contextmanager
def _collection_paused() -> Iterator[None]:
    """Hold Python's cyclic collector off for a block, restoring its prior state."""
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()


def _live_widgets(app: QApplication) -> list[QWidget]:
    """Return the widgets of *app* whose C++ objects still exist.

    Two hazards, and ``isValid`` only answers the second one (D-064).

    Building the list is itself a dereference. ``allWidgets`` copies a pointer
    list in C++, then wraps each pointer in a Python object one at a time, and
    wrapping allocates. An allocation can trip the cyclic collector, collecting
    a cycle can free a parentless widget along with its children, and the rest
    of the already-copied list still points at them — so the next wrap reads
    freed memory and the process dies with SIGSEGV. ``isValid`` cannot help:
    it needs a wrapper that this step is what produces. Hence two changes from
    the walk that crashed a macOS runner: the collector is held off across the
    snapshot, and the snapshot is rooted in the window trees rather than taken
    from Qt's global set, which keeps the pointers Qt hands over down to the
    handful of top-level widgets. Coverage is unchanged — a parentless QWidget
    *is* a top-level window in Qt, so every widget is a window or a descendant
    of one.

    The filter still runs, because setting a font during the walk that follows
    can free a later entry, and by then the entries are wrappers.
    """
    with _collection_paused():
        found: list[QWidget] = []
        seen: set[int] = set()
        for window in app.topLevelWidgets():
            for widget in (window, *window.findChildren(QWidget)):
                if id(widget) not in seen:
                    seen.add(id(widget))
                    found.append(widget)
    return [widget for widget in found if isValid(widget)]


def _capture_widget_base_fonts(app: QApplication) -> None:
    """Record live widget fonts before Qt propagates a new application font."""
    previous_factor = _font_scales.get(id(app), 1.0)
    for widget in _live_widgets(app):
        if not isValid(widget):
            continue
        base = widget.property(_BASE_FONT_PROPERTY)
        if not isinstance(base, QFont):
            base = _scaled_font(QFont(widget.font()), 1.0 / previous_factor)
            widget.setProperty(_BASE_FONT_PROPERTY, QFont(base))


def _apply_font_to_existing_widgets(app: QApplication, factor: float) -> None:
    """Scale live widgets from their unscaled base fonts without changing their roles."""
    for widget in _live_widgets(app):
        # Re-checked inside the loop as well as when the list was taken: each
        # setFont below can be what frees the next entry.
        if not isValid(widget):
            continue
        base = widget.property(_BASE_FONT_PROPERTY)
        if not isinstance(base, QFont):
            # A widget created after the preference was applied inherits the app
            # font; derive its unscaled base before applying the next preference.
            base = _scaled_font(QFont(widget.font()), 1.0 / _font_scales.get(id(app), 1.0))
            widget.setProperty(_BASE_FONT_PROPERTY, QFont(base))
        target = _scaled_font(base, factor)
        family = widget.property(_FONT_FAMILY_PROPERTY)
        if isinstance(family, str) and family:
            target.setFamily(family)
        widget.setFont(target)
    _font_scales[id(app)] = factor


def _accent(palette: QPalette) -> QColor:
    """Read the platform's selected/accent colour with a safe fallback."""
    accent = palette.color(QPalette.ColorRole.Highlight)
    return accent if accent.isValid() else QColor("#0078d4")


_MACOS_ACCENT_COLORS = {
    -1: "#8e8e93",  # Graphite
    0: "#ff453a",  # Red
    1: "#ff9f0a",  # Orange
    2: "#ffd60a",  # Yellow
    3: "#30d158",  # Green
    4: "#0a84ff",  # Blue
    5: "#bf5af2",  # Purple
    6: "#ff375f",  # Pink
}


def system_accent(palette: QPalette) -> QColor:
    """Return the user's platform accent, including macOS's explicit preference.

    Qt exposes macOS's pale selection colour through ``Highlight`` on some
    versions, rather than the actual Accent Color selected in System Settings.
    ``AppleAccentColor`` is the authoritative setting for custom-painted UI.
    """
    global _macos_accent
    if sys.platform == "darwin":
        if _macos_accent is not None:
            return QColor(_macos_accent)
        try:
            # The one subprocess in this codebase that does not splat
            # `runtime.no_window_kwargs()`, and deliberately: it is unreachable
            # off macOS, and those kwargs carry only Windows' CREATE_NO_WINDOW.
            # Splatting here would be dead code. If this call ever stops being
            # darwin-only, it needs them.
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleAccentColor"],
                capture_output=True,
                text=True,
                check=True,
                timeout=1,
            )
            _macos_accent = QColor(_MACOS_ACCENT_COLORS[int(result.stdout.strip())])
            return QColor(_macos_accent)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            pass
    return _accent(palette)


# ── Derived colours for custom-painted evidence ──────────────────────────
#
# Qt has palette roles for surfaces, text, selection and links, and none for
# "this is a defect" or "this lane is not that lane".  Custom-painted widgets
# therefore used literal hex, which is how a tick tuned on a dark build turned
# into a smear on a light one and stopped following the user's accent entirely.
#
# What is fixed below is *hue* and nothing else.  Saturation and lightness are
# solved against the live surface on every call, so one constant renders as a
# pale mark on a dark panel and a deep one on a white panel, and a palette
# change moves it without anybody storing a second value.

#: Lightness a painted mark targets, per surface polarity.  Far enough from the
#: surface that a one-pixel tick is still visible, short of the pure white and
#: pure black that make thin marks shimmer on sub-pixel-rendered displays.
_MARK_LIGHTNESS_ON_DARK = 0.70
_MARK_LIGHTNESS_ON_LIGHT = 0.38

#: Saturation for a derived mark.  High enough to read as a colour rather than
#: as grey, low enough not to vibrate against a saturated accent.
_MARK_SATURATION = 0.58

#: The one colour convention worth keeping fixed: a defect is red, in every
#: theme and under every accent.  Everything else is derived from the accent.
_DEFECT_HUE = 0.995

#: Severity hues for transient status text, in turns: caution amber, alert
#: orange, defect red.  Deliberately ordered so the three read as a progression.
_CAUTION_HUE = 0.11
_ALERT_HUE = 0.05

#: How far apart two derived hues must stay to remain tellable apart.
_MIN_HUE_SEPARATION = 0.08


def _surface(palette: QPalette) -> QColor:
    """Return the surface custom-painted evidence is drawn on."""
    return palette.color(QPalette.ColorRole.AlternateBase)


def on_surface(palette: QPalette, hue: float, saturation: float = _MARK_SATURATION) -> QColor:
    """Return a mark of *hue* whose lightness is solved against *palette*.

    This is what replaces a hex literal.  The caller states the meaning it wants
    a colour for; how light that has to be is a property of the surface, which
    only the live palette knows.
    """
    dark = _surface(palette).lightnessF() < 0.5
    lightness = _MARK_LIGHTNESS_ON_DARK if dark else _MARK_LIGHTNESS_ON_LIGHT
    return QColor.fromHslF(hue % 1.0, saturation, lightness)


def accent_hue(palette: QPalette) -> float:
    """Return the platform accent's hue, or a stable stand-in when it has none.

    ``hueF`` answers -1 for an achromatic colour, and macOS' Graphite accent is
    very nearly that.  Deriving a lane colour from -1 would silently produce the
    same colour for every lane, so a grey accent falls back to a fixed hue and
    the lanes stay tellable apart.
    """
    hue = system_accent(palette).hueF()
    return 0.58 if hue < 0.0 else float(hue)


def _separated(hue: float, avoid: float, minimum: float = _MIN_HUE_SEPARATION) -> float:
    """Return *hue* pushed away from *avoid* until they are distinguishable.

    Without this, a cyan accent rotates its derived message hue straight onto
    the defect red, and two lanes that mean opposite things paint identically.
    """
    distance = abs((hue - avoid + 0.5) % 1.0 - 0.5)
    if distance >= minimum:
        return hue % 1.0
    return (avoid + minimum) % 1.0


def evidence_color(palette: QPalette, kind: str) -> QColor:
    """Return the colour for one timeline lane, derived from the live palette.

    Coverage and sync keep the accent and the ``Link`` role directly: they are
    broad filled spans, already palette-driven, and normalising them would churn
    a working appearance for nothing. The lanes that had no role to sit on —
    defects and recorded messages — are derived here instead of hardcoded.
    """
    if kind in {"video", "ttl", "sync"}:
        return system_accent(palette)
    if kind == "data":
        return palette.color(QPalette.ColorRole.Link)
    if kind == "gap":
        return on_surface(palette, _DEFECT_HUE)
    if kind == "message":
        # Opposite the accent, so it can never collide with the sync lane, then
        # pushed clear of the defect red so it cannot be misread as an error.
        return on_surface(palette, _separated(accent_hue(palette) + 0.5, _DEFECT_HUE))
    return palette.color(QPalette.ColorRole.WindowText)


def status_color(palette: QPalette, severity: str) -> QColor:
    """Return the colour for a transient status message of *severity*."""
    if severity == "busy":
        return on_surface(palette, _CAUTION_HUE)
    if severity == "warning":
        return on_surface(palette, _ALERT_HUE)
    if severity == "error":
        return on_surface(palette, _DEFECT_HUE)
    return palette.color(QPalette.ColorRole.WindowText)


#: How many marker colours before the sequence repeats.  Seven evenly-spaced
#: hues is about the limit of what stays tellable apart at a two-pixel tick.
MARKER_COLOR_COUNT = 7

#: Markers are more saturated than an evidence lane.  Measured, not guessed: at
#: the mark saturation used elsewhere the closest pair of the seven differs by
#: 0.14 in RGB, which is under the 0.15 two colours need to be tellable apart.
_MARKER_SATURATION = 0.8


def marker_color(palette: QPalette, index: int) -> QColor:
    """Return the *index*-th categorical marker colour for this palette.

    A categorical palette is not a theme colour: its job is to tell one marker
    from the next, so the hues are spread evenly around the wheel on purpose and
    do not track the accent — an accent-relative sequence would collapse toward
    the accent and stop distinguishing anything, which is the one thing it is
    for.

    Even spacing is also why this does not use :func:`_separated`: pushing one
    hue clear of the defect red destroys the spacing and shoves that marker into
    its neighbour. The sequence is offset by half a step instead, which keeps
    every gap equal *and* leaves no marker sitting exactly on the defect hue.
    Markers do not need to be told apart from a gap anyway — they are a
    different lane in a different widget, both of them labelled.

    What the palette does decide is how light each one is, so the sequence stays
    readable on a white plot background and on a black one. The literal list this
    replaces was tuned for a light background and washed out on a dark one.
    """
    hue = (index % MARKER_COLOR_COUNT + 0.5) / MARKER_COLOR_COUNT
    return on_surface(palette, hue, saturation=_MARKER_SATURATION)


def loop_pin_color(palette: QPalette, which: str) -> QColor:
    """Return the A or B loop-pin colour, both derived from the accent.

    A and B are a pair, so they are placed a fixed distance apart on the wheel
    rather than picked independently: whatever the accent, they stay as far from
    each other as they were designed to be.
    """
    base = accent_hue(palette)
    offset = 0.33 if which == "in" else 0.66
    return on_surface(palette, _separated(base + offset, _DEFECT_HUE))


class _PaletteStyleFollower(QObject):
    """Re-runs a widget's stylesheet builder whenever its palette changes."""

    def __init__(self, widget: QWidget, build: Callable[[QPalette], str]) -> None:
        super().__init__(widget)
        self._widget = widget
        self._build = build
        self._applying = False
        widget.installEventFilter(self)
        self._apply()

    def _apply(self) -> None:
        if self._applying:
            return
        self._applying = True
        try:
            self._widget.setStyleSheet(self._build(self._widget.palette()))
        finally:
            self._applying = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.PaletteChange:
            self._apply()
        return False


def follow_palette(widget: QWidget, build: Callable[[QPalette], str]) -> None:
    """Keep *widget*'s stylesheet derived from the live palette.

    Qt re-resolves palette *roles* when the appearance changes, but a stylesheet
    is a literal from the moment it is set — nothing re-runs the f-string that
    produced it. That is why every hardcoded ``setStyleSheet("color: #...")``
    in this application froze at whichever theme was current when the widget was
    built, and stayed there through a light/dark switch.

    Prefer :meth:`QWidget.setForegroundRole` where a plain palette role will do;
    it needs no helper at all. Use this for the cases a role cannot express —
    a severity colour, an attention badge — so they still follow the theme.

    The follower is parented to the widget, so it dies with it.
    """
    _PaletteStyleFollower(widget, build)


def _palette_with_surfaces(dark: bool, accent: QColor) -> QPalette:
    """Build an explicit appearance while retaining the platform accent colour."""
    p = QPalette()
    if dark:
        p.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
        p.setColor(QPalette.ColorRole.WindowText, QColor("#f0f0f0"))
        p.setColor(QPalette.ColorRole.Base, QColor("#282828"))
        p.setColor(QPalette.ColorRole.AlternateBase, QColor("#333333"))
        p.setColor(QPalette.ColorRole.Text, QColor("#f0f0f0"))
        p.setColor(QPalette.ColorRole.Button, QColor("#303030"))
        p.setColor(QPalette.ColorRole.ButtonText, QColor("#f0f0f0"))
        p.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
        p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2d2d2d"))
        p.setColor(QPalette.ColorRole.ToolTipText, QColor("#f5f5f5"))
        p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9a9a9a"))
        p.setColor(QPalette.ColorRole.Highlight, accent.darker(160))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        disabled = QColor("#8a8a8a")
    else:
        p.setColor(QPalette.ColorRole.Window, QColor("#f5f5f5"))
        p.setColor(QPalette.ColorRole.WindowText, QColor("#1b1b1b"))
        p.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        p.setColor(QPalette.ColorRole.AlternateBase, QColor("#eeeeee"))
        p.setColor(QPalette.ColorRole.Text, QColor("#1b1b1b"))
        p.setColor(QPalette.ColorRole.Button, QColor("#ededed"))
        p.setColor(QPalette.ColorRole.ButtonText, QColor("#1b1b1b"))
        p.setColor(QPalette.ColorRole.BrightText, QColor("#000000"))
        p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
        p.setColor(QPalette.ColorRole.ToolTipText, QColor("#1b1b1b"))
        p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#707070"))
        p.setColor(QPalette.ColorRole.Highlight, accent)
        p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        disabled = QColor("#747474")

    p.setColor(QPalette.ColorRole.Link, accent)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return p


def _install_system_appearance_listener(app: QApplication) -> None:
    """Follow platform palette changes while the System preference is active."""
    app_id = id(app)
    if app_id in _palette_listeners_installed:
        return
    _palette_listeners_installed.add(app_id)

    def on_palette_changed(palette: QPalette) -> None:
        global _macos_accent
        if app_id in _applying_palette or current_preference() != THEME_SYSTEM:
            return
        _macos_accent = None
        _system_palettes[app_id] = QPalette(palette)
        _apply(app, THEME_SYSTEM, persist=False)

    app.paletteChanged.connect(on_palette_changed)  # type: ignore[arg-type]


def _apply(app: QApplication, pref: str, *, persist: bool) -> None:
    """Apply *pref* without duplicating preference persistence logic."""
    system_palette = _system_palette(app)
    native = pref == THEME_SYSTEM
    dark = _is_dark_palette(system_palette) if native else pref == THEME_DARK
    palette = (
        system_palette if native else _palette_with_surfaces(dark, system_accent(system_palette))
    )
    app_id = id(app)
    _applying_palette.add(app_id)
    try:
        app.setPalette(palette)
        # A QApplication stylesheet wraps Qt's native style and selector rules can alter
        # control metrics and interaction affordances.  Palette roles cover all allowed
        # theme variation (surfaces, text, selection, accent, and tooltips) without
        # changing seek/scrollbar/splitter geometry or platform control behaviour.
        app.setStyleSheet("")
    finally:
        _applying_palette.discard(app_id)

    app.setProperty("avialsync_theme_dark", dark)
    app.setProperty("avialsync_theme_native", native)
    if persist:
        QSettings("AvialSync", "AvialSync").setValue("theme/preference", pref)


def apply_theme(app: QApplication, pref: str = THEME_SYSTEM) -> None:
    """Apply and persist System, Dark, or Light appearance.

    System follows Qt's platform palette, including a live system palette update when
    Qt reports one.  Explicit appearances keep the platform accent but set their own
    readable surface colours.
    """
    if pref not in (THEME_SYSTEM, THEME_DARK, THEME_LIGHT):
        pref = THEME_SYSTEM
    _install_system_appearance_listener(app)
    _apply(app, pref, persist=True)


def apply_font_size(app: QApplication, pref: str = FONT_SYSTEM) -> None:
    """Apply and persist a system-relative font preference to live and future widgets."""
    factors = {FONT_SYSTEM: 1.0, FONT_SMALL: 0.9, FONT_MEDIUM: 1.0, FONT_LARGE: 1.15}
    if pref not in factors:
        pref = FONT_SYSTEM
    font = _system_font(app)
    if pref != FONT_SYSTEM:
        point_size = font.pointSizeF()
        if point_size <= 0:
            point_size = 12.0
        font.setPointSizeF(max(8.0, point_size * factors[pref]))
    _capture_widget_base_fonts(app)
    app.setFont(font)
    # Applied here rather than from a zero-delay timer. Deferring it coalesced
    # rapid preference changes, which a menu action does not need, and bought
    # that with a window in which the callback could run after the widgets it
    # walks — or the application itself — had been torn down, which is a
    # segfault rather than an exception (D-064). `setFont` has already
    # propagated synchronously by this point, so there is nothing to wait for.
    _apply_font_to_existing_widgets(app, factors[pref])
    QSettings("AvialSync", "AvialSync").setValue("font/preference", pref)


def load_saved_font_size(app: QApplication) -> str:
    """Apply the saved font-size preference and return its normalized value."""
    pref = current_font_preference()
    apply_font_size(app, pref)
    return pref


def load_saved_theme(app: QApplication) -> str:
    """Apply the saved preference and return its normalized value."""
    raw = QSettings("AvialSync", "AvialSync").value("theme/preference", THEME_SYSTEM)
    if isinstance(raw, bool):
        pref = THEME_DARK if raw else THEME_LIGHT
    elif raw in (THEME_DARK, THEME_LIGHT, THEME_SYSTEM):
        pref = raw
    else:
        pref = THEME_SYSTEM
    apply_theme(app, pref)
    return pref


def current_preference() -> str:
    """Return the persisted preference, normalized for legacy settings."""
    raw = QSettings("AvialSync", "AvialSync").value("theme/preference", THEME_SYSTEM)
    if isinstance(raw, bool):
        return THEME_DARK if raw else THEME_LIGHT
    return raw if raw in (THEME_DARK, THEME_LIGHT, THEME_SYSTEM) else THEME_SYSTEM


def current_font_preference() -> str:
    """Return the persisted font-size preference."""
    raw = QSettings("AvialSync", "AvialSync").value("font/preference", FONT_SYSTEM)
    return raw if raw in (FONT_SYSTEM, FONT_SMALL, FONT_MEDIUM, FONT_LARGE) else FONT_SYSTEM


def is_dark() -> bool:
    """Return whether the currently resolved application appearance is dark."""
    app = QApplication.instance()
    if app is not None:
        return bool(app.property("avialsync_theme_dark"))
    return current_preference() == THEME_DARK
