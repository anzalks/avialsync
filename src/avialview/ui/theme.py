"""Native-aware dark, light, and system appearance for AvialView.

System appearance deliberately preserves Qt's platform palette and widget style.  That
means AvialView follows the user's accent colour, contrast settings, and font choice
instead of imitating an operating-system theme with fixed colours.  The optional Dark
and Light appearances use a restrained palette while retaining that same accent. Theme
selection never changes widget geometry, input behaviour, view state, or playback state.
"""

from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

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
_font_requests: dict[int, int] = {}
_BASE_FONT_PROPERTY = "avialview_base_font"
_FONT_FAMILY_PROPERTY = "avialview_font_family"


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


def _capture_widget_base_fonts(app: QApplication) -> None:
    """Record live widget fonts before Qt propagates a new application font."""
    previous_factor = _font_scales.get(id(app), 1.0)
    for widget in app.allWidgets():
        base = widget.property(_BASE_FONT_PROPERTY)
        if not isinstance(base, QFont):
            base = _scaled_font(QFont(widget.font()), 1.0 / previous_factor)
            widget.setProperty(_BASE_FONT_PROPERTY, QFont(base))


def _apply_font_to_existing_widgets(app: QApplication, factor: float) -> None:
    """Scale live widgets from their unscaled base fonts without changing their roles."""
    for widget in app.allWidgets():
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

    app.setProperty("avialview_theme_dark", dark)
    app.setProperty("avialview_theme_native", native)
    if persist:
        QSettings("AvialView", "AvialView").setValue("theme/preference", pref)


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
    app_id = id(app)
    request = _font_requests.get(app_id, 0) + 1
    _font_requests[app_id] = request

    def apply_to_live_widgets() -> None:
        if _font_requests.get(app_id) == request:
            _apply_font_to_existing_widgets(app, factors[pref])

    QTimer.singleShot(0, apply_to_live_widgets)
    QSettings("AvialView", "AvialView").setValue("font/preference", pref)


def load_saved_font_size(app: QApplication) -> str:
    """Apply the saved font-size preference and return its normalized value."""
    pref = current_font_preference()
    apply_font_size(app, pref)
    return pref


def load_saved_theme(app: QApplication) -> str:
    """Apply the saved preference and return its normalized value."""
    raw = QSettings("AvialView", "AvialView").value("theme/preference", THEME_SYSTEM)
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
    raw = QSettings("AvialView", "AvialView").value("theme/preference", THEME_SYSTEM)
    if isinstance(raw, bool):
        return THEME_DARK if raw else THEME_LIGHT
    return raw if raw in (THEME_DARK, THEME_LIGHT, THEME_SYSTEM) else THEME_SYSTEM


def current_font_preference() -> str:
    """Return the persisted font-size preference."""
    raw = QSettings("AvialView", "AvialView").value("font/preference", FONT_SYSTEM)
    return raw if raw in (FONT_SYSTEM, FONT_SMALL, FONT_MEDIUM, FONT_LARGE) else FONT_SYSTEM


def is_dark() -> bool:
    """Return whether the currently resolved application appearance is dark."""
    app = QApplication.instance()
    if app is not None:
        return bool(app.property("avialview_theme_dark"))
    return current_preference() == THEME_DARK
