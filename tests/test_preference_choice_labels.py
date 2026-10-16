"""Preferences show choices by name, and the font scale offers real steps."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QComboBox

from avialsync.core.settings_schema import SETTINGS, setting_for
from avialsync.ui import theme
from avialsync.ui.preferences_dialog import PreferencesDialog


def test_every_choice_setting_names_its_choices() -> None:
    for setting in SETTINGS:
        if setting.choices:
            assert len(setting.choice_labels) == len(setting.choices), setting.key
            assert all(label for label in setting.choice_labels), setting.key


def test_preferences_combos_show_labels_and_store_keys(qapp: QApplication, qtbot) -> None:
    dialog = PreferencesDialog()
    qtbot.addWidget(dialog)
    combo = dialog._editors["wheel/units"]
    assert isinstance(combo, QComboBox)

    assert combo.itemText(0) == "(none)"
    assert combo.itemData(0) == ""
    theme_combo = dialog._editors["theme/preference"]
    assert isinstance(theme_combo, QComboBox)
    assert [theme_combo.itemText(i) for i in range(theme_combo.count())] == [
        "System",
        "Light",
        "Dark",
    ]


def test_font_steps_go_beyond_the_platform_size() -> None:
    """Medium equalled System and Large was 1.15."""
    font = setting_for("font/preference")
    assert font is not None
    assert "extra_large" in font.choices
    factors = [theme.FONT_FACTORS[key] for key in font.choices if key != "system"]
    assert factors == sorted(factors)
    assert theme.FONT_FACTORS[theme.FONT_MEDIUM] > 1.0
    assert max(factors) >= 1.5


def test_first_window_size_fits_the_screen(qapp: QApplication) -> None:
    from PySide6.QtGui import QGuiApplication

    from avialsync.ui.controllers.workspace_layout import first_window_size as _first_size

    width, height = _first_size()
    area = QGuiApplication.primaryScreen().availableGeometry()

    assert width <= max(640, area.width() - 32)
    assert height <= max(480, area.height() - 32)
    assert (width, height) <= (1280, 800)
