"""Native-aware dark, light, and system appearance for KinoChronix.

System appearance deliberately preserves Qt's platform palette and widget style.  That
means KinoChronix follows the user's accent colour, contrast settings, and font choice
instead of imitating an operating-system theme with fixed colours.  The optional Dark
and Light appearances use a restrained palette while retaining that same accent.
"""

from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

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


def _qss(
    palette: QPalette,
    *,
    dark: bool,
    native: bool,
    accent: QColor | None = None,
) -> str:
    """Return only styling Qt cannot consistently derive from a palette."""
    tooltip_base = palette.color(QPalette.ColorRole.ToolTipBase).name()
    tooltip_text = palette.color(QPalette.ColorRole.ToolTipText).name()
    border = palette.color(QPalette.ColorRole.Mid).name()
    accent_name = (accent or palette.color(QPalette.ColorRole.Link)).name()
    if native:
        return f"""
QSlider::handle:horizontal {{
    background: {accent_name}; width: 14px; margin: -4px 0; border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background: {accent_name}; border-radius: 3px; }}
QToolTip {{
    background-color: {tooltip_base}; color: {tooltip_text};
    border: 1px solid {border}; padding: 4px;
}}
"""

    accent_qss = accent_name
    groove = "#3b3b3b" if dark else "#c8c8c8"
    handle = "#5a5a5a" if dark else "#858585"
    surface = palette.color(QPalette.ColorRole.Window).name()
    base = palette.color(QPalette.ColorRole.Base).name()
    selected = palette.color(QPalette.ColorRole.Highlight).name()
    return f"""
QSlider::groove:horizontal {{
    background: {groove}; height: 6px; border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {accent_qss}; width: 14px; margin: -4px 0; border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background: {accent_qss}; border-radius: 3px; }}
QSplitter::handle {{ background-color: {groove}; }}
QGroupBox {{
    border: 1px solid {border}; border-radius: 4px;
    margin-top: 0.5em; padding-top: 0.6em;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
QHeaderView::section {{ background-color: {base}; border: 1px solid {border}; padding: 3px; }}
QTableWidget {{ gridline-color: {border}; border: 1px solid {border}; }}
QProgressBar {{ border: 1px solid {border}; border-radius: 3px; text-align: center; }}
QProgressBar::chunk {{ background-color: {accent_qss}; border-radius: 3px; }}
QScrollBar:vertical {{ background: {surface}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {handle}; border-radius: 5px; min-height: 20px; }}
QScrollBar:horizontal {{ background: {surface}; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {handle}; border-radius: 5px; min-width: 20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QComboBox QAbstractItemView {{ background-color: {base}; selection-background-color: {selected}; }}
QToolTip {{
    background-color: {tooltip_base}; color: {tooltip_text};
    border: 1px solid {border}; padding: 4px;
}}
"""


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
        app.setStyleSheet(
            _qss(palette, dark=dark, native=native, accent=system_accent(system_palette))
        )
    finally:
        _applying_palette.discard(app_id)

    app.setProperty("kinochronix_theme_dark", dark)
    app.setProperty("kinochronix_theme_native", native)
    if persist:
        QSettings("KinoChronix", "KinoChronix").setValue("theme/preference", pref)


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
    """Apply and persist a system-relative application font-size preference."""
    factors = {FONT_SYSTEM: 1.0, FONT_SMALL: 0.9, FONT_MEDIUM: 1.0, FONT_LARGE: 1.15}
    if pref not in factors:
        pref = FONT_SYSTEM
    font = _system_font(app)
    if pref != FONT_SYSTEM:
        point_size = font.pointSizeF()
        if point_size <= 0:
            point_size = 12.0
        font.setPointSizeF(max(8.0, point_size * factors[pref]))
    app.setFont(font)
    QSettings("KinoChronix", "KinoChronix").setValue("font/preference", pref)


def load_saved_font_size(app: QApplication) -> str:
    """Apply the saved font-size preference and return its normalized value."""
    pref = current_font_preference()
    apply_font_size(app, pref)
    return pref


def load_saved_theme(app: QApplication) -> str:
    """Apply the saved preference and return its normalized value."""
    raw = QSettings("KinoChronix", "KinoChronix").value("theme/preference", THEME_SYSTEM)
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
    raw = QSettings("KinoChronix", "KinoChronix").value("theme/preference", THEME_SYSTEM)
    if isinstance(raw, bool):
        return THEME_DARK if raw else THEME_LIGHT
    return raw if raw in (THEME_DARK, THEME_LIGHT, THEME_SYSTEM) else THEME_SYSTEM


def current_font_preference() -> str:
    """Return the persisted font-size preference."""
    raw = QSettings("KinoChronix", "KinoChronix").value("font/preference", FONT_SYSTEM)
    return raw if raw in (FONT_SYSTEM, FONT_SMALL, FONT_MEDIUM, FONT_LARGE) else FONT_SYSTEM


def is_dark() -> bool:
    """Return whether the currently resolved application appearance is dark."""
    app = QApplication.instance()
    if app is not None:
        return bool(app.property("kinochronix_theme_dark"))
    return current_preference() == THEME_DARK
