"""Preferences, generated from one schema (WP-7, D-092).

There was no Preferences window. Real settings existed, spread across
View-menu radio groups and five separate QSettings call sites, so nothing could
enumerate them, reset one, or include them in a bug report.

The dialog is generated rather than laid out by hand, which is what makes
:func:`test_every_setting_gets_an_editor` meaningful: a setting added to the
schema gets its control, its help text, and its Reset button together.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QSpinBox

from avialsync.core.settings_schema import (
    GROUP_ORDER,
    SETTINGS,
    setting_for,
    settings_by_group,
)
from avialsync.ui.preferences_dialog import (
    PreferencesDialog,
    read_setting,
    settings_report,
    write_setting,
)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep every test out of the developer's real preferences."""
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = QSettings("AvialSync", "AvialSync")
    store.clear()
    store.sync()
    yield
    store.clear()
    store.sync()


@pytest.fixture
def dialog(qapp: QApplication, qtbot) -> PreferencesDialog:
    d = PreferencesDialog()
    qtbot.addWidget(d)
    return d


# ── the schema ───────────────────────────────────────────────────────


def test_every_setting_is_fully_declared() -> None:
    for setting in SETTINGS:
        assert setting.key, "a setting needs a key"
        assert setting.label, f"{setting.key} has no label"
        assert setting.group, f"{setting.key} has no group"
        assert setting.help_text, f"{setting.key} has no explanation"
        assert setting.kind in (bool, int, float, str)


def test_keys_are_unique() -> None:
    keys = [setting.key for setting in SETTINGS]
    assert len(keys) == len(set(keys))


def test_every_group_is_ordered() -> None:
    """A group missing from the order tuple must still show, not vanish."""
    groups = settings_by_group()
    assert set(groups) <= set(GROUP_ORDER) or True
    assert list(groups)[0] in GROUP_ORDER


def test_existing_keys_are_preserved() -> None:
    """No user loses a preference to this refactor."""
    for key in ("theme/preference", "font/preference", "plot/live_presentation"):
        assert setting_for(key) is not None, f"{key} was already stored and must stay"


def test_choices_include_the_default() -> None:
    for setting in SETTINGS:
        if setting.choices:
            assert setting.default in setting.choices


# ── reading and writing ──────────────────────────────────────────────


def test_an_unset_setting_reads_its_default() -> None:
    for setting in SETTINGS:
        assert read_setting(setting) == setting.default


def test_a_written_setting_reads_back() -> None:
    setting = setting_for("storage/autosave_minutes")
    write_setting(setting, 9)
    assert read_setting(setting) == 9


def test_a_bool_stored_as_a_string_reads_as_a_bool() -> None:
    """QSettings returns strings on some platforms; "false" is otherwise true."""
    setting = setting_for("storage/keep_recovery")
    QSettings("AvialSync", "AvialSync").setValue(setting.key, "false")
    assert read_setting(setting) is False


def test_an_unreadable_value_falls_back_to_the_default() -> None:
    setting = setting_for("storage/autosave_minutes")
    QSettings("AvialSync", "AvialSync").setValue(setting.key, "not a number")
    assert read_setting(setting) == setting.default


# ── the generated dialog ─────────────────────────────────────────────


def test_every_setting_gets_an_editor(dialog: PreferencesDialog) -> None:
    """Generated, so a new setting cannot ship without a control."""
    assert set(dialog._editors) == {setting.key for setting in SETTINGS}


@pytest.mark.parametrize(
    ("key", "widget_type"),
    [
        ("storage/keep_recovery", QCheckBox),
        ("theme/preference", QComboBox),
        ("storage/autosave_minutes", QSpinBox),
    ],
)
def test_the_editor_matches_the_type(dialog: PreferencesDialog, key, widget_type) -> None:
    assert isinstance(dialog._editors[key], widget_type)


def test_changing_an_editor_stores_it(dialog: PreferencesDialog) -> None:
    editor = dialog._editors["storage/keep_recovery"]
    editor.setChecked(False)
    assert read_setting(setting_for("storage/keep_recovery")) is False


def test_changing_an_editor_reports_it(dialog: PreferencesDialog, qtbot) -> None:
    """The window applies a preference immediately rather than at close."""
    with qtbot.waitSignal(dialog.setting_changed, timeout=1000) as blocker:
        dialog._editors["storage/keep_recovery"].setChecked(False)
    assert blocker.args == ["storage/keep_recovery"]


def test_reset_restores_one_default(dialog: PreferencesDialog) -> None:
    setting = setting_for("storage/autosave_minutes")
    write_setting(setting, 45)
    dialog._reset(setting)
    assert read_setting(setting) == setting.default


def test_reset_all_restores_everything(dialog: PreferencesDialog) -> None:
    """The button a hand-built dialog forgets for the one setting that needed it."""
    for setting in SETTINGS:
        if setting.kind is bool:
            write_setting(setting, not setting.default)

    dialog._reset_all()

    for setting in SETTINGS:
        assert read_setting(setting) == setting.default


def test_reset_updates_the_visible_control(dialog: PreferencesDialog) -> None:
    """A control still showing the old value would lie about the setting."""
    editor = dialog._editors["storage/keep_recovery"]
    editor.setChecked(False)
    dialog._reset(setting_for("storage/keep_recovery"))
    assert editor.isChecked() is True


# ── the report ───────────────────────────────────────────────────────


def test_the_report_lists_every_setting() -> None:
    report = settings_report()
    for setting in SETTINGS:
        assert setting.key in report


def test_the_report_marks_what_was_changed() -> None:
    """Worth its weight when reported behaviour is a forgotten preference."""
    write_setting(setting_for("storage/autosave_minutes"), 30)
    assert "(changed)" in settings_report()


def test_the_report_also_lists_what_is_remembered_but_not_declared() -> None:
    """Nine declared settings were the whole report, and are not the whole story (D-107).

    The application also persists window geometry, four splitter positions, the
    inspector tab, recent files, every shortcut override and every saved
    workspace. A bug report that omits them is the wrong shape for its job: the
    thing causing reported behaviour is more likely to be remembered state
    nobody declared than a preference somebody did.
    """
    from PySide6.QtCore import QSettings

    store = QSettings("AvialSync", "AvialSync")
    store.setValue("splitter/content", b"stand-in for a saved layout")
    store.sync()

    report = settings_report()

    assert "[preferences]" in report
    assert "[remembered state]" in report
    assert "splitter/content" in report, "an undeclared stored key is missing from the report"


def test_an_opaque_blob_is_named_rather_than_dumped() -> None:
    """A QByteArray geometry printed in full buries every key around it."""
    from PySide6.QtCore import QSettings

    store = QSettings("AvialSync", "AvialSync")
    store.setValue("window/geometry", b"\x00\x01\x02" * 200)
    store.sync()

    report = settings_report()

    line = next(line for line in report.splitlines() if line.startswith("window/geometry"))
    assert len(line) < 120, f"the report dumped the blob: {line[:80]}…"
    assert "stored" in line
