"""Every transport shortcut must reach the playhead from anywhere in the window.

The failure this guards is a user report of keys that work "not always": Qt
offers each key to the focused widget as a ``ShortcutOverride`` before running a
window shortcut, and editors accept that offer. One click into a spin box, a
combo, or the timecode field and playback control went dead until focus moved
somewhere else — with nothing on screen to say why.

The matrix is generated rather than listed, so a widget added later, or a
shortcut added later, is covered without anyone remembering to extend this file.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QValidator
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from avialsync.ui.main_window import MainWindow

#: Keys that must drive the playhead no matter what holds focus.
PLAYHEAD_KEYS: tuple[tuple[str, Qt.Key, Qt.KeyboardModifier], ...] = (
    ("Space", Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier),
    ("Left", Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier),
    ("Right", Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier),
    ("Home", Qt.Key.Key_Home, Qt.KeyboardModifier.NoModifier),
    ("End", Qt.Key.Key_End, Qt.KeyboardModifier.NoModifier),
    ("Comma", Qt.Key.Key_Comma, Qt.KeyboardModifier.NoModifier),
    ("Period", Qt.Key.Key_Period, Qt.KeyboardModifier.NoModifier),
    ("Shift+Left", Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier),
    ("Shift+Right", Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier),
)

#: The J/K/L shuttle. Ordinary text, so these are reclaimed only from a field
#: that would have refused the character anyway.
SHUTTLE_KEYS: tuple[tuple[str, Qt.Key], ...] = (
    ("J", Qt.Key.Key_J),
    ("K", Qt.Key.Key_K),
    ("L", Qt.Key.Key_L),
)


@pytest.fixture()
def window(qtbot) -> MainWindow:
    main = MainWindow()
    qtbot.addWidget(main)
    main.resize(1200, 800)
    main.show()
    qtbot.waitExposed(main)
    return main


def _focusable(window: MainWindow) -> list[QWidget]:
    """Return every visible widget a click could put focus into."""
    return [
        widget
        for widget in window.findChildren(QWidget)
        if widget.focusPolicy() != Qt.FocusPolicy.NoFocus and widget.isVisible()
    ]


def _fires(
    window: MainWindow, widget: QWidget, key: Qt.Key, modifier: Qt.KeyboardModifier
) -> bool | None:
    """Return whether pressing *key* with *widget* focused triggers any shortcut.

    ``None`` means the widget would not take focus, so there is nothing to test
    on it — it can never be the thing swallowing a key. Reported rather than
    skipped: a ``pytest.skip`` here would abandon the whole matrix at the first
    such widget, which is how this test first passed while checking nothing.

    Watches the actions themselves rather than their effects: what matters is
    that the binding survived the focus widget, not what its handler then does.
    """
    app = QApplication.instance()
    assert isinstance(app, QApplication)

    widget.setFocus(Qt.FocusReason.MouseFocusReason)
    app.processEvents()
    if not widget.hasFocus():
        return None

    hits: list[str] = []
    connections = []
    for action in window._all_actions:
        connections.append(action.triggered.connect(lambda *_, a=action: hits.append(a.text())))
    try:
        QTest.keyClick(app.focusWidget() or widget, key, modifier)
        app.processEvents()
    finally:
        for action, connection in zip(window._all_actions, connections, strict=True):
            action.triggered.disconnect(connection)
    return bool(hits)


def test_the_window_registers_the_shuttle_letters(window: MainWindow) -> None:
    """The reservation reads its letters from the bindings, not a second list."""
    assert {"j", "k", "l"} <= window._letter_shortcuts


@pytest.mark.parametrize(("name", "key", "modifier"), PLAYHEAD_KEYS)
def test_playhead_keys_reach_the_playhead_from_every_focusable_widget(
    window: MainWindow, name: str, key: Qt.Key, modifier: Qt.KeyboardModifier
) -> None:
    """No widget in the window may swallow a playhead key.

    Generated over every focusable widget, so a control added later is covered
    without this file being touched.
    """
    dead: list[str] = []
    probed = 0
    for widget in _focusable(window):
        if not widget.isEnabled():
            continue
        result = _fires(window, widget, key, modifier)
        if result is None:
            continue
        probed += 1
        if not result:
            dead.append(type(widget).__name__)

    assert probed >= 5, f"only {probed} widgets took focus; the matrix is not being exercised"
    assert not dead, f"{name} was swallowed by: {sorted(set(dead))}"


@pytest.mark.parametrize(("name", "key"), SHUTTLE_KEYS)
def test_shuttle_letters_survive_fields_that_cannot_hold_a_letter(
    window: MainWindow, name: str, key: Qt.Key
) -> None:
    """A numeric field discards letters, so it must not eat the shuttle keys.

    Restricted to fields whose own validator rejects the character: a field that
    genuinely accepts letters keeps them, which is what stops this stealing the
    first keystroke of an annotation label.
    """
    from avialsync.ui.main_window import _editor_rejects_text

    dead: list[str] = []
    probed = 0
    for widget in _focusable(window):
        if not widget.isEnabled() or not _editor_rejects_text(widget, name.lower()):
            continue
        result = _fires(window, widget, key, Qt.KeyboardModifier.NoModifier)
        if result is None:
            continue
        probed += 1
        if not result:
            dead.append(type(widget).__name__)

    assert probed >= 1, "no letter-rejecting editor was probed; the matrix is not being exercised"
    assert not dead, f"{name} was swallowed by: {sorted(set(dead))}"


def test_a_field_that_accepts_letters_keeps_them(window: MainWindow) -> None:
    """The reservation must not steal the first keystroke of ordinary typing."""
    from PySide6.QtWidgets import QLineEdit

    from avialsync.ui.main_window import _editor_rejects_text

    free_text = QLineEdit(window)
    assert free_text.validator() is None
    assert not _editor_rejects_text(free_text, "j")
    assert not _editor_rejects_text(free_text, "k")


def test_the_timecode_field_accepts_everything_the_app_writes_into_it(
    window: MainWindow,
) -> None:
    """The validator must not reject the clock's own output, UTC suffix included."""
    from avialsync.ui.time_format import TimeDisplayMode, format_time

    validator = window.transport._time_edit.validator()
    assert validator is not None

    for mode in TimeDisplayMode:
        for seconds, epoch in ((0.0, 0.0), (3661.5, 0.0), (-12.25, 0.0), (5.196, 1782053691.824)):
            text = format_time(seconds, mode, epoch)
            state, _, _ = validator.validate(text, len(text))
            assert state == QValidator.State.Acceptable, f"{mode.name} wrote unacceptable {text!r}"


def test_the_timecode_field_refuses_a_letter_that_is_a_shortcut(window: MainWindow) -> None:
    validator = window.transport._time_edit.validator()
    assert validator is not None
    for letter in ("j", "k", "l"):
        state, _, _ = validator.validate(f"00:00:0{letter}", 8)
        assert state == QValidator.State.Invalid
