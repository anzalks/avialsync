"""Window keyboard actions and focus policy, with explicit component inputs.

The live QAction remains the authority for text, shortcuts, repeat and category.
This builder shares the window's action list and letter set, and owns no clock
or playback state. Event delivery stays on the window's real Qt receiver.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence, QValidator
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit, QWidget

from avialsync.core.timeline import MasterClock
from avialsync.engine.player import Player
from avialsync.ui.plot_pane import PlotPane
from avialsync.ui.transport import Transport


@dataclass(frozen=True)
class KeyboardContext:
    """Only the components and callbacks needed to build window shortcuts."""

    owner: QWidget
    actions: list[QAction]
    letters: set[str]
    clock: MasterClock
    player: Player
    transport: Transport
    plots: PlotPane
    annotate: Callable[[], None]
    cycle_theme: Callable[[], None]
    show_shortcuts: Callable[[], None]


class KeyboardActions:
    """Build keyboard-only actions alongside menu-owned actions."""

    def __init__(self, context: KeyboardContext) -> None:
        self.context = context
        self._playback()
        self._navigation()
        self._marking()
        self._view()

    def add(
        self,
        text: str,
        category: str,
        handler: Callable[[], None],
        *keys: Any,
        repeatable: bool = False,
    ) -> QAction:
        """Register a live action with repeat opted into only for repeated gestures."""
        action = QAction(text, self.context.owner)
        action.setShortcuts([QKeySequence(key) for key in keys])
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        # Qt defaults to repeat. Toggles would flap on every OS key repeat,
        # so only stepping, jumping and zoom explicitly opt into it.
        action.setAutoRepeat(repeatable)
        action.triggered.connect(handler)
        action.setProperty("av_category", category)
        self.context.owner.addAction(action)
        self.context.actions.append(action)
        for sequence in action.shortcuts():
            shortcut = sequence.toString()
            if len(shortcut) == 1 and shortcut.isalpha():
                self.context.letters.add(shortcut.lower())
        return action

    def _playback(self) -> None:
        ctx = self.context
        self.add(
            "Play / Pause",
            "Playback",
            lambda: ctx.transport.play_toggled.emit(not ctx.clock.state.playing),
            Qt.Key.Key_Space,
        )
        self.add(
            "Step back 1 frame",
            "Playback",
            lambda: ctx.transport.frame_step_requested.emit(-1),
            Qt.Key.Key_Left,
            Qt.Key.Key_Comma,
            repeatable=True,
        )
        self.add(
            "Step forward 1 frame",
            "Playback",
            lambda: ctx.transport.frame_step_requested.emit(1),
            Qt.Key.Key_Right,
            Qt.Key.Key_Period,
            repeatable=True,
        )
        self.add(
            "Jump back 1 second",
            "Playback",
            lambda: ctx.transport.jump_requested.emit(-1.0),
            "Shift+Left",
            "J",
            repeatable=True,
        )
        self.add(
            "Jump forward 1 second",
            "Playback",
            lambda: ctx.transport.jump_requested.emit(1.0),
            "Shift+Right",
            repeatable=True,
        )

    def _navigation(self) -> None:
        ctx = self.context
        self.add("Pause", "Playback", lambda: ctx.transport.play_toggled.emit(False), "K")
        self.add("Step up playback rate", "Playback", ctx.transport.step_rate_up, "L")
        self.add(
            "Jump to start",
            "Playback",
            lambda: ctx.player.seek(ctx.clock.state.bounds[0]),
            Qt.Key.Key_Home,
        )
        self.add(
            "Jump to end",
            "Playback",
            lambda: ctx.player.seek(ctx.clock.state.bounds[1]),
            Qt.Key.Key_End,
        )

    def _marking(self) -> None:
        ctx = self.context
        self.add("Set A/B in-point", "Marking", ctx.transport.ab_in, Qt.Key.Key_BracketLeft, "I")
        self.add("Set A/B out-point", "Marking", ctx.transport.ab_out, Qt.Key.Key_BracketRight, "O")
        self.add("Add marker at playhead", "Marking", ctx.annotate, "M")

    def _view(self) -> None:
        ctx = self.context
        self.add("Cycle theme", "View", ctx.cycle_theme, "Ctrl+T")
        self.add("Plot zoom in", "View", ctx.plots.zoom_in, "+", repeatable=True)
        self.add("Plot zoom out", "View", ctx.plots.zoom_out, "-", repeatable=True)
        self.add("Keyboard shortcuts (alias)", "View", ctx.show_shortcuts, "?")


def reserve_playhead_key(owner: QWidget, event: QEvent) -> bool:
    """Reserve playhead keys within this window, preserving an active editor's caret."""
    if not isinstance(event, QKeyEvent) or event.key() not in _PLAYHEAD_KEYS:
        return False
    app = QApplication.instance()
    focus = app.focusWidget() if isinstance(app, QApplication) else None
    if focus is None or focus.window() is not owner:
        return False
    return event.key() == Qt.Key.Key_Space or not _is_mid_edit(focus)


def reserve_letter_shortcut(owner: QWidget, letters: set[str], event: QEvent) -> bool:
    """Return letters only from editors whose own validator would reject them."""
    if not isinstance(event, QKeyEvent) or event.text().lower() not in letters:
        return False
    app = QApplication.instance()
    focus = app.focusWidget() if isinstance(app, QApplication) else None
    if focus is None or focus.window() is not owner:
        return False
    return _editor_rejects_text(focus, event.text())


_PLAYHEAD_KEYS = frozenset(
    {
        Qt.Key.Key_Space,
        Qt.Key.Key_Left,
        Qt.Key.Key_Right,
        Qt.Key.Key_Home,
        Qt.Key.Key_End,
        Qt.Key.Key_Comma,
        Qt.Key.Key_Period,
    }
)


def _validates_as_invalid(result: object) -> bool:
    """Return whether a Qt validator refused the text outright.

    ``QValidator.validate`` is typed as returning ``object`` by the PySide6
    stubs; it is really the state, or a tuple beginning with it, depending on
    the validator. Both shapes are read here rather than assumed, because
    guessing wrong would silently make every letter look acceptable and quietly
    undo the reservation this feeds.
    """
    state = result[0] if isinstance(result, tuple) and result else result
    return state == QValidator.State.Invalid


def _editor_rejects_text(widget: QWidget, text: str) -> bool:
    """Return whether *widget* would refuse *text* as typed input.

    A numeric field cannot hold a letter, so a letter arriving there is not
    editing — it is a shortcut the field happens to be swallowing. Asking the
    widget's own validator is what keeps this honest: a field that really does
    accept letters (an annotation label) keeps them, and only a field that would
    discard the character gives it up.
    """
    if len(text) != 1 or not text.isprintable():
        return False
    if isinstance(widget, QAbstractSpinBox):
        line_edit = widget.lineEdit()
        current = line_edit.text() if line_edit is not None else ""
        position = line_edit.cursorPosition() if line_edit is not None else len(current)
        candidate = current[:position] + text + current[position:]
        return _validates_as_invalid(widget.validate(candidate, position + 1))
    if isinstance(widget, QLineEdit):
        validator = widget.validator()
        if validator is None:
            # No validator means the field accepts arbitrary text, so a letter
            # typed into it is editing and belongs to the field.
            return False
        current = widget.text()
        position = widget.cursorPosition()
        candidate = current[:position] + text + current[position:]
        return _validates_as_invalid(validator.validate(candidate, position + 1))
    return False


def _is_mid_edit(widget: QWidget) -> bool:
    """Return whether *widget* is a text editor with an edit in progress.

    Only such a widget keeps the caret keys; an editor merely holding focus has
    no claim on them.
    """
    if isinstance(widget, QLineEdit):
        return bool(widget.isModified())
    if isinstance(widget, QAbstractSpinBox):
        line_edit = widget.lineEdit()
        return bool(line_edit is not None and line_edit.isModified())
    return False
