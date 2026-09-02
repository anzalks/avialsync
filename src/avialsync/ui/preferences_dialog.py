"""Preferences, generated from the schema (WP-7, D-092).

There was no Preferences window at all. Real settings existed and were spread
across View-menu radio groups and five ``QSettings`` call sites, so nothing
could enumerate them, reset one, or report them.

The dialog is built from :data:`~avialsync.core.settings_schema.SETTINGS` rather
than laid out by hand, which is the point: adding a setting to the schema adds
its control, its help text, and its Reset button together, and none of the three
can be forgotten separately.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.settings_schema import SETTINGS, Setting, settings_by_group
from avialsync.ui.i18n import tr

__all__ = ["PreferencesDialog", "read_setting", "write_setting", "settings_report"]

_ORGANISATION = "AvialSync"
_APPLICATION = "AvialSync"


def _store() -> QSettings:
    return QSettings(_ORGANISATION, _APPLICATION)


def read_setting(setting: Setting) -> Any:
    """Current value of *setting*, or its default.

    Coerced through the declared type: ``QSettings`` returns strings on some
    platforms and native types on others, and a bool that arrives as ``"false"``
    is otherwise true.
    """
    raw = _store().value(setting.key, setting.default)
    if setting.kind is bool:
        if isinstance(raw, str):
            return raw.strip().lower() in {"true", "1", "yes"}
        return bool(raw)
    try:
        return setting.kind(raw)
    except (TypeError, ValueError):
        return setting.default


def write_setting(setting: Setting, value: Any) -> None:
    _store().setValue(setting.key, value)


def settings_report() -> str:
    """Every setting and its current value, for Diagnostics and bug reports.

    Worth its weight the first time someone reports behaviour that turns out
    to be a preference they had changed and forgotten.
    """
    lines = []
    for setting in SETTINGS:
        value = read_setting(setting)
        marker = "" if value == setting.default else "  (changed)"
        lines.append(f"{setting.key} = {value!r}{marker}")
    return "\n".join(lines)


class PreferencesDialog(QDialog):
    """One tab per group, one row per declared setting."""

    #: Emitted with a key whenever a value changes, so the window can apply it
    #: immediately rather than on close.
    setting_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Preferences"))
        self.setMinimumWidth(520)
        self._editors: dict[str, QWidget] = {}

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        for group, entries in settings_by_group().items():
            tabs.addTab(self._build_page(entries), group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        reset_all = buttons.addButton(
            "Reset all to defaults", QDialogButtonBox.ButtonRole.ResetRole
        )
        reset_all.clicked.connect(self._reset_all)
        layout.addWidget(buttons)

    def _build_page(self, entries: list[Setting]) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        for setting in entries:
            row = QHBoxLayout()
            editor = self._build_editor(setting)
            self._editors[setting.key] = editor
            row.addWidget(editor, stretch=1)

            reset = QPushButton("Reset")
            reset.setToolTip(f"Back to the default ({setting.default!r})")
            reset.setAccessibleName(f"Reset {setting.label} to its default")
            reset.clicked.connect(lambda _checked, s=setting: self._reset(s))
            row.addWidget(reset)

            container = QWidget()
            container.setLayout(row)
            label = QLabel(setting.label)
            if setting.help_text:
                # The reason, not just the name: a setting whose effect is not
                # obvious is one nobody dares change.
                label.setToolTip(setting.help_text)
                container.setToolTip(setting.help_text)
            form.addRow(label, container)

            if setting.help_text:
                note = QLabel(setting.help_text)
                note.setWordWrap(True)
                note.setTextFormat(Qt.TextFormat.PlainText)
                note.setEnabled(False)
                form.addRow("", note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _build_editor(self, setting: Setting) -> QWidget:
        value = read_setting(setting)

        if setting.kind is bool:
            box = QCheckBox()
            box.setChecked(bool(value))
            box.setAccessibleName(setting.label)
            box.toggled.connect(lambda checked, s=setting: self._store_value(s, checked))
            return box

        if setting.choices:
            combo = QComboBox()
            combo.addItems(list(setting.choices))
            if str(value) in setting.choices:
                combo.setCurrentText(str(value))
            combo.setAccessibleName(setting.label)
            combo.currentTextChanged.connect(lambda text, s=setting: self._store_value(s, text))
            return combo

        spin = QSpinBox()
        spin.setRange(
            int(setting.minimum if setting.minimum is not None else 0),
            int(setting.maximum if setting.maximum is not None else 1_000_000),
        )
        spin.setValue(int(value))
        spin.setAccessibleName(setting.label)
        spin.valueChanged.connect(lambda number, s=setting: self._store_value(s, number))
        return spin

    # ── changing values ──────────────────────────────────────────────

    def _store_value(self, setting: Setting, value: Any) -> None:
        write_setting(setting, value)
        self.setting_changed.emit(setting.key)

    def _reset(self, setting: Setting) -> None:
        write_setting(setting, setting.default)
        self._reload(setting)
        self.setting_changed.emit(setting.key)

    def _reset_all(self) -> None:
        for setting in SETTINGS:
            write_setting(setting, setting.default)
            self._reload(setting)
            self.setting_changed.emit(setting.key)

    def _reload(self, setting: Setting) -> None:
        """Show the stored value without re-storing it."""
        editor = self._editors.get(setting.key)
        if editor is None:
            return
        value = read_setting(setting)
        blocked = editor.blockSignals(True)
        try:
            if isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))
            elif isinstance(editor, QComboBox):
                editor.setCurrentText(str(value))
            elif isinstance(editor, QSpinBox):
                editor.setValue(int(value))
        finally:
            editor.blockSignals(blocked)
