"""Reusable wheel setup stays separate from a recording's saved clicks."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDoubleSpinBox

from avialsync.core.settings_schema import setting_for
from avialsync.core.source import RotaryHint
from avialsync.ui.preferences_dialog import PreferencesDialog, read_setting
from avialsync.ui.wheel_dialogs import _WheelSetupDialog


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = QSettings("AvialSync", "AvialSync")
    store.clear()
    store.sync()
    yield
    store.clear()
    store.sync()


def _dialog(qtbot, hint: RotaryHint | None = None) -> _WheelSetupDialog:
    dialog = _WheelSetupDialog((), hint, [], None)
    qtbot.addWidget(dialog)
    return dialog


def test_first_setup_is_remembered_and_reused(qapp: QApplication, qtbot) -> None:
    first = _dialog(qtbot)
    assert first.remember.isChecked()
    first.bars.setValue(36)
    first.units.setCurrentIndex(first.units.findData("mm"))
    first.radius.setValue(50)
    first.accept()

    second = _dialog(qtbot)
    assert (second.bars.value(), second.units.currentData(), second.radius.value()) == (
        36,
        "mm",
        50,
    )
    assert not second.remember.isChecked()
    second.bars.setValue(48)
    second.accept()
    assert _dialog(qtbot).bars.value() == 36


def test_user_can_update_or_forget_saved_setup(qapp: QApplication, qtbot) -> None:
    first = _dialog(qtbot)
    first.bars.setValue(36)
    first.accept()
    update = _dialog(qtbot)
    update.bars.setValue(48)
    update.remember.setChecked(True)
    update.accept()
    forgotten = _dialog(qtbot)
    assert forgotten.bars.value() == 48
    forgotten.forget.click()
    assert forgotten.bars.value() == 0
    assert _dialog(qtbot).bars.value() == 0


def test_recording_hint_wins_without_overwriting_saved_setup(qapp: QApplication, qtbot) -> None:
    first = _dialog(qtbot)
    first.bars.setValue(36)
    first.accept()
    hinted = _dialog(qtbot, RotaryHint("encoder", bar_count=24, radius=15.0, units="cm"))
    assert (hinted.bars.value(), hinted.units.currentData(), hinted.radius.value()) == (
        24,
        "cm",
        15,
    )
    assert not hinted.remember.isChecked()
    hinted.accept()
    assert _dialog(qtbot).bars.value() == 36


def test_recording_hint_is_not_implicitly_saved(qapp: QApplication, qtbot) -> None:
    hinted = _dialog(qtbot, RotaryHint("encoder", bar_count=24, radius=15.0, units="cm"))
    assert not hinted.remember.isChecked()
    hinted.accept()
    assert _dialog(qtbot).bars.value() == 0


def test_preferences_can_reset_reusable_setup(qapp: QApplication, qtbot) -> None:
    first = _dialog(qtbot)
    first.bars.setValue(36)
    first.units.setCurrentIndex(first.units.findData("mm"))
    first.radius.setValue(50)
    first.accept()
    preferences = PreferencesDialog()
    qtbot.addWidget(preferences)
    radius = preferences._editors["wheel/radius"]
    assert isinstance(radius, QDoubleSpinBox)
    assert radius.value() == 50
    preferences._reset_all()
    assert read_setting(setting_for("wheel/bar_count")) == 0
    assert _dialog(qtbot).bars.value() == 0
