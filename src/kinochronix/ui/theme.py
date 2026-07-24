"""Dark / light / system theme configuration for KinoChronix.

Uses QPalette for base widget colours (window, text, button) so every
QWidget — including plain containers — picks up the theme.  QSS is
layered on top only for controls that need pixel-precise styling
(slider grooves, combo-box dropdowns, etc.).

QOpenGLWidget ignores the palette background, so video panes render
correctly in both themes.
"""

import sys

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEME_DARK = "dark"
THEME_LIGHT = "light"
THEME_SYSTEM = "system"

# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------


def _dark_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#d4d4d4"))
    p.setColor(QPalette.ColorRole.Base, QColor("#2a2a2a"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#333333"))
    p.setColor(QPalette.ColorRole.Text, QColor("#d4d4d4"))
    p.setColor(QPalette.ColorRole.Button, QColor("#333333"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#d4d4d4"))
    p.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.Highlight, QColor("#094771"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2d2d2d"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#d4d4d4"))
    p.setColor(QPalette.ColorRole.Link, QColor("#0078d4"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#888888"))
    # Disabled
    p.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor("#666666"),
    )
    p.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor("#666666"),
    )
    p.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#666666"),
    )
    return p


def _light_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#f5f5f5"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#1e1e1e"))
    p.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#e8e8e8"))
    p.setColor(QPalette.ColorRole.Text, QColor("#1e1e1e"))
    p.setColor(QPalette.ColorRole.Button, QColor("#e0e0e0"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#1e1e1e"))
    p.setColor(QPalette.ColorRole.BrightText, QColor("#000000"))
    p.setColor(QPalette.ColorRole.Highlight, QColor("#0078d4"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#1e1e1e"))
    p.setColor(QPalette.ColorRole.Link, QColor("#0078d4"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#999999"))
    p.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor("#aaaaaa"),
    )
    p.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor("#aaaaaa"),
    )
    p.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#aaaaaa"),
    )
    return p


# ---------------------------------------------------------------------------
# QSS — only for controls that need pixel-level styling.
# No bare ``QWidget`` selectors — palette handles backgrounds.
# ---------------------------------------------------------------------------

_DARK_QSS = """
QSlider::groove:horizontal {
    background: #333; height: 6px; border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #0078d4; width: 14px; margin: -4px 0; border-radius: 7px;
}
QSlider::sub-page:horizontal {
    background: #0078d4; border-radius: 3px;
}
QSplitter::handle { background-color: #333; }
QGroupBox {
    border: 1px solid #444; border-radius: 4px;
    margin-top: 0.5em; padding-top: 0.6em;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 8px; padding: 0 4px;
}
QHeaderView::section {
    background-color: #2d2d2d; border: 1px solid #444; padding: 3px;
}
QTableWidget { gridline-color: #333; border: 1px solid #444; }
QProgressBar {
    border: 1px solid #555; border-radius: 3px; text-align: center;
}
QProgressBar::chunk { background-color: #0078d4; border-radius: 3px; }
QScrollBar:vertical {
    background: #1e1e1e; width: 10px;
}
QScrollBar::handle:vertical {
    background: #555; border-radius: 5px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #1e1e1e; height: 10px;
}
QScrollBar::handle:horizontal {
    background: #555; border-radius: 5px; min-width: 20px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QComboBox QAbstractItemView {
    background-color: #2d2d2d; selection-background-color: #094771;
}
QToolTip { border: 1px solid #555; padding: 4px; }
QFrame[frameShape="4"] { color: #444; }
"""

_LIGHT_QSS = """
QSlider::groove:horizontal {
    background: #ccc; height: 6px; border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #0078d4; width: 14px; margin: -4px 0; border-radius: 7px;
}
QSlider::sub-page:horizontal {
    background: #0078d4; border-radius: 3px;
}
QSplitter::handle { background-color: #ccc; }
QGroupBox {
    border: 1px solid #ccc; border-radius: 4px;
    margin-top: 0.5em; padding-top: 0.6em;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 8px; padding: 0 4px;
}
QHeaderView::section {
    background-color: #e8e8e8; border: 1px solid #ccc; padding: 3px;
}
QTableWidget { gridline-color: #ddd; border: 1px solid #ccc; }
QProgressBar {
    border: 1px solid #bbb; border-radius: 3px; text-align: center;
}
QProgressBar::chunk { background-color: #0078d4; border-radius: 3px; }
QComboBox QAbstractItemView {
    background-color: #fff; selection-background-color: #cce4f7;
}
QToolTip { border: 1px solid #ccc; padding: 4px; }
"""

# ---------------------------------------------------------------------------
# System theme detection
# ---------------------------------------------------------------------------


def _system_is_dark() -> bool:
    """Detect whether the OS is using a dark appearance."""
    if sys.platform == "darwin":
        try:
            from subprocess import check_output

            out = check_output(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                text=True,
            ).strip()
            return out.lower() == "dark"
        except Exception:
            return False
    app = QApplication.instance()
    if app:
        bg = app.palette().color(QPalette.ColorRole.Window)
        return bg.lightnessF() < 0.5
    return True


def _resolve_dark(pref: str) -> bool:
    if pref == THEME_DARK:
        return True
    if pref == THEME_LIGHT:
        return False
    return _system_is_dark()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_theme(app: QApplication, pref: str = THEME_SYSTEM) -> None:
    """Apply the chosen theme preference to the application."""
    dark = _resolve_dark(pref)
    app.setPalette(_dark_palette() if dark else _light_palette())
    app.setStyleSheet(_DARK_QSS if dark else _LIGHT_QSS)

    settings = QSettings("KinoChronix", "KinoChronix")
    settings.setValue("theme/preference", pref)


def load_saved_theme(app: QApplication) -> str:
    """Apply the saved theme preference. Returns the pref string."""
    settings = QSettings("KinoChronix", "KinoChronix")
    raw = settings.value("theme/preference", THEME_SYSTEM)

    # Migrate old bool-based setting
    if isinstance(raw, bool):
        pref = THEME_DARK if raw else THEME_LIGHT
    elif raw in (THEME_DARK, THEME_LIGHT, THEME_SYSTEM):
        pref = raw
    else:
        pref = THEME_SYSTEM

    apply_theme(app, pref)
    return pref


def current_preference() -> str:
    """Return the stored theme preference string."""
    settings = QSettings("KinoChronix", "KinoChronix")
    raw = settings.value("theme/preference", THEME_SYSTEM)
    if isinstance(raw, bool):
        return THEME_DARK if raw else THEME_LIGHT
    if raw in (THEME_DARK, THEME_LIGHT, THEME_SYSTEM):
        return raw
    return THEME_SYSTEM


def is_dark() -> bool:
    """Check whether the current resolved theme is dark."""
    return _resolve_dark(current_preference())
