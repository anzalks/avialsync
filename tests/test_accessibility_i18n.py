"""Reachable without sight, and translatable (WP-12).

Before this: 40 accessible names against roughly 90 interactive widgets, one
description, no status tips, and not one ``tr()`` or ``QTranslator`` anywhere.
A screen reader met a window of unnamed buttons, and every string was hardcoded
English.

Both are enforced by sweep rather than by annotation, because the alternative
fixes today and not tomorrow: the ninety-first widget is the one added without
a name, and nothing would say so.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QSlider, QWidget
from shiboken6 import isValid

from avialsync.ui import recovery
from avialsync.ui.accessibility import (
    GLYPH_NAMES,
    apply_accessibility,
    derive_name,
    unnamed_widgets,
)
from avialsync.ui.i18n import catalogue_dir, install_translator, tr, translatable_ratio
from avialsync.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    # Qt may already have deleted it: pytest-qt runs processEvents()
    # after the call phase, which executes pending deleteLater()s.
    if isValid(win):
        win.close()


# ── deriving a name ──────────────────────────────────────────────────


def test_a_buttons_label_becomes_its_name(qapp: QApplication, qtbot) -> None:
    """What a sighted user reads is the right name for someone who cannot."""
    button = QPushButton("Open Videos")
    qtbot.addWidget(button)
    assert derive_name(button) == "Open Videos"


def test_an_explicit_name_is_never_overwritten(qapp: QApplication, qtbot) -> None:
    button = QPushButton("OK")
    button.setAccessibleName("Accept the proposed alignment")
    qtbot.addWidget(button)
    assert derive_name(button) == "Accept the proposed alignment"


@pytest.mark.parametrize("glyph", sorted(GLYPH_NAMES))
def test_a_glyph_gets_words(glyph: str, qapp: QApplication, qtbot) -> None:
    """ "Left square bracket" tells nobody what the control does."""
    button = QPushButton(glyph)
    qtbot.addWidget(button)
    name = derive_name(button)
    assert name == GLYPH_NAMES[glyph]
    assert len(name.split()) >= 2, "a symbol must become words, not another symbol"


def test_a_placeholder_names_a_text_field(qapp: QApplication, qtbot) -> None:
    field = QLineEdit()
    field.setPlaceholderText("Filter channels…")
    qtbot.addWidget(field)
    assert "Filter" in derive_name(field)


def test_a_tooltip_is_the_last_resort(qapp: QApplication, qtbot) -> None:
    slider = QSlider()
    slider.setToolTip("Adjust the shared time span. Applies to every plot.")
    qtbot.addWidget(slider)
    # First sentence only: a name is announced on every focus change.
    assert derive_name(slider) == "Adjust the shared time span"


def test_a_bare_widget_derives_nothing(qapp: QApplication, qtbot) -> None:
    button = QPushButton("")
    qtbot.addWidget(button)
    assert derive_name(button) == ""


# ── the sweep ────────────────────────────────────────────────────────


def test_the_sweep_names_what_it_can(qapp: QApplication, qtbot) -> None:
    root = QWidget()
    qtbot.addWidget(root)
    QPushButton("Save", root)
    QPushButton("[", root)

    named = apply_accessibility(root)

    assert named == 2
    buttons = root.findChildren(QPushButton)
    assert {b.accessibleName() for b in buttons} == {"Save", GLYPH_NAMES["["]}


def test_the_sweep_is_idempotent(qapp: QApplication, qtbot) -> None:
    root = QWidget()
    qtbot.addWidget(root)
    QPushButton("Save", root)

    apply_accessibility(root)
    assert apply_accessibility(root) == 0, "a second pass must find nothing to do"


def test_a_tooltip_becomes_the_description(qapp: QApplication, qtbot) -> None:
    root = QWidget()
    qtbot.addWidget(root)
    button = QPushButton("Auto", root)
    button.setToolTip("Choose black and white from what this frame contains")

    apply_accessibility(root)

    assert button.accessibleDescription().startswith("Choose black and white")


def test_a_description_is_not_a_repeat_of_the_name(qapp: QApplication, qtbot) -> None:
    root = QWidget()
    qtbot.addWidget(root)
    button = QPushButton("Save", root)
    button.setToolTip("Save")

    apply_accessibility(root)

    assert button.accessibleDescription() == ""


# ── the window as a whole ────────────────────────────────────────────


def test_nothing_interactive_is_left_unnamed(window: MainWindow) -> None:
    """The check that makes the sweep worth having."""
    unnamed = unnamed_widgets(window)
    described = [f"{type(w).__name__}({w.objectName() or 'unnamed'})" for w in unnamed]
    assert unnamed == [], f"a screen reader could not announce: {described}"


def test_the_window_ran_the_sweep(window: MainWindow) -> None:
    """A second pass finding nothing proves the first one ran."""
    assert apply_accessibility(window) == 0


def test_widgets_built_after_the_window_are_named_too(window: MainWindow, qtbot) -> None:
    """The sweep is not a one-shot at construction time (D-107).

    ``apply_accessibility`` was called once, from ``__init__``, against a
    window that necessarily holds no video panes, plot rows, source entries or
    quality badges -- the application starts empty. Every widget a user
    actually operates while working is built later, and none of them was ever
    swept. This stands in for that: a control added after construction is
    named by the re-sweep the source-change path runs.
    """
    from PySide6.QtWidgets import QPushButton

    late = QPushButton("Remove this source", window)
    qtbot.addWidget(late)
    assert late.accessibleName() == "", "the fixture must start unnamed"

    window._sweep_accessibility()

    assert late.accessibleName() == "Remove this source"


def test_a_dialog_is_swept_when_it_is_shown(window: MainWindow, qtbot) -> None:
    """Eleven dialog classes were never swept at all (D-107).

    None of them exists at construction time, so the single ``__init__`` sweep
    could not have reached any of them however well it worked. The show-time
    filter is what closes that, and it must work on a dialog this test invents
    rather than one that happens to name its own controls.
    """
    from PySide6.QtWidgets import QDialog, QPushButton

    dialog = QDialog(window)
    button = QPushButton("Relink this recording", dialog)
    qtbot.addWidget(dialog)
    assert button.accessibleName() == ""

    dialog.show()
    qtbot.waitExposed(dialog)

    assert button.accessibleName() == "Relink this recording"
    dialog.close()


def test_only_one_sweeper_is_ever_installed(qapp: QApplication, qtbot) -> None:
    """One filter per application, not one per window (D-107).

    A filter installed on the application object sees every event delivered to
    every object in the process, and one parented to the application is never
    removed. Installed unguarded from ``MainWindow.__init__``, two windows
    doubled the per-event cost and the test suite -- which builds a hundred --
    multiplied it by a hundred, taking a two-minute run to one that did not
    finish. The cost is invisible in any test that builds a single window,
    which is why this counts instead of timing.
    """
    from avialsync.ui.accessibility import ShowTimeSweeper, install_show_time_sweep

    first = install_show_time_sweep(qapp)
    for _ in range(5):
        assert install_show_time_sweep(qapp) is first, "each call added another filter"

    installed = [child for child in qapp.children() if isinstance(child, ShowTimeSweeper)]
    assert len(installed) == 1, f"{len(installed)} sweepers are filtering every event"


def test_the_shipped_dialogs_name_their_controls(window: MainWindow, qtbot) -> None:
    """The real dialogs, not a stand-in: shown, then checked.

    Constructed with the arguments the window gives them, so this fails if a
    dialog acquires a control that derives no name -- an icon-only button, say,
    whose glyph is not in ``GLYPH_NAMES``.
    """
    from avialsync.ui.command_palette import CommandPalette
    from avialsync.ui.preferences_dialog import PreferencesDialog
    from avialsync.ui.shortcuts_dialog import ShortcutsDialog

    grouped: dict[str, list] = {}
    for action in window._all_actions:
        grouped.setdefault(str(action.property("av_category") or "Other"), []).append(action)

    for dialog in (
        PreferencesDialog(window),
        ShortcutsDialog(grouped, window),
        CommandPalette(list(window._all_actions), window),
    ):
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.waitExposed(dialog)
        unnamed = unnamed_widgets(dialog)
        described = [f"{type(w).__name__}('{w.objectName()}')" for w in unnamed]
        assert unnamed == [], (
            f"{type(dialog).__name__} has controls a screen reader cannot announce: {described}"
        )
        dialog.close()


# ── translation ──────────────────────────────────────────────────────


def test_tr_returns_the_text_when_untranslated() -> None:
    """No catalogue is the common case and must not change what is displayed."""
    assert tr("Open Videos") == "Open Videos"


def test_installing_with_no_catalogue_is_not_an_error(qapp: QApplication) -> None:
    from PySide6.QtCore import QLocale

    assert install_translator(qapp, QLocale("xx_XX")) is False


def test_the_catalogue_directory_ships_with_the_package() -> None:
    assert catalogue_dir().is_dir()
    assert (catalogue_dir() / "README.md").is_file()


def test_every_extractable_literal_is_translatable() -> None:
    """Measured, not claimed.

    The threshold was 60 %, and the real figure sat at 67.6 % -- passing while
    52 of the 59 unwrapped literals were in one file, ``main_window.py``, and
    were the entire menu bar. Every menu title, every menu item, and the five
    inspector tab names were untranslatable, which is most of what a user of a
    translated build would read first (D-107).

    They are all wrapped now, so the gate is the real number rather than a
    floor beneath it. What this cannot count is f-strings, which ``lupdate``
    cannot extract at all and which need restructuring rather than wrapping;
    ``untranslated_calls`` skips them by design, so 100 % here means "every
    literal that *could* be wrapped is", not "the application is fully
    translated".
    """
    wrapped, total = translatable_ratio(Path("src/avialsync"))
    assert total > 100, "the sweep should have found plenty to wrap"
    assert wrapped == total, f"only {wrapped}/{total} literals are translatable"


def test_the_new_modules_are_fully_wrapped() -> None:
    """Whatever the legacy backlog, work added in this phase carries its own."""
    from avialsync.ui.i18n import untranslated_calls

    for name in ("empty_state.py", "levels_panel.py", "command_palette.py"):
        path = Path("src/avialsync/ui") / name
        assert untranslated_calls(path) == [], f"{name} has unwrapped user-facing text"
