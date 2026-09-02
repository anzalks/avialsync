"""Everything the application can do, in one searchable list (WP-3).

The menus have grown: File, Edit, View with Theme, Font Size, Time Display and
Overlays nested inside it, Help, a pane context menu, a sidebar, and a
transport. Finding a command means knowing which of those it lives in, and the
newest ones -- the overlay switches especially -- are three levels down.

The palette derives from the same live ``QAction`` objects the shortcuts dialog
uses (D-022.6), so it cannot list something that does not exist or miss
something that does. An action's name comes from the action; there is no second
place where a command is called anything (D-092).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

__all__ = ["CommandPalette", "fuzzy_score"]


def fuzzy_score(needle: str, haystack: str) -> float:
    """Score *haystack* against *needle*; 0 means no match.

    Subsequence matching rather than substring, so "ovl" finds "Overlays" and
    "shcam" finds "Show camera name". Contiguous runs and a match at the start
    of a word score higher, which is what puts the command someone meant above
    the one that merely contains the same letters.
    """
    needle = needle.strip().lower()
    if not needle:
        return 1.0
    text = haystack.lower()

    score = 0.0
    position = 0
    previous_index = -2
    for character in needle:
        index = text.find(character, position)
        if index < 0:
            return 0.0
        score += 1.0
        if index == previous_index + 1:
            # Contiguity outweighs a word start, and has to. Scoring word
            # starts higher let "open" rank "Overlays per name" -- three
            # unrelated words -- above "Open Videos", because each of its
            # letters happened to begin one.
            score += 3.0
        elif index == 0 or text[index - 1] in " -/_":
            score += 1.5
        previous_index = index
        position = index + 1

    if text.startswith(needle):
        # An exact prefix is the strongest evidence there is about what was
        # meant, and no accumulation of scattered bonuses should beat it.
        score += 6.0

    # Prefer shorter targets: with equal evidence, the more specific command is
    # the one that was meant.
    return score / (1.0 + 0.01 * len(text))


class CommandPalette(QDialog):
    """Type to find a command; Enter runs it."""

    def __init__(self, actions: list[QAction], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Commands")
        self.setModal(True)
        self.setMinimumWidth(560)

        # Only what can actually be done now. Offering a disabled command and
        # doing nothing when it is chosen is worse than not offering it.
        self._actions = [action for action in actions if action.isEnabled() and action.text()]

        layout = QVBoxLayout(self)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Type a command…")
        self._search.setClearButtonEnabled(True)
        self._search.setAccessibleName("Search commands")
        self._search.textChanged.connect(self._refresh)
        self._search.returnPressed.connect(self._run_selected)
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.setAccessibleName("Matching commands")
        self._list.itemActivated.connect(lambda _item: self._run_selected())
        layout.addWidget(self._list)

        self._refresh("")
        self._search.setFocus()

    # ── matching ─────────────────────────────────────────────────────

    def _refresh(self, needle: str) -> None:
        scored = []
        for action in self._actions:
            label = self._label_for(action)
            score = fuzzy_score(needle, label)
            if score > 0:
                scored.append((score, label, action))
        scored.sort(key=lambda entry: (-entry[0], entry[1]))

        self._list.clear()
        for _score, label, action in scored:
            shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            item = QListWidgetItem(f"{label}\t{shortcut}" if shortcut else label)
            item.setData(Qt.ItemDataRole.UserRole, action)
            if action.toolTip() and action.toolTip() != action.text():
                item.setToolTip(action.toolTip())
            self._list.addItem(item)

        if self._list.count():
            self._list.setCurrentRow(0)

    @staticmethod
    def _label_for(action: QAction) -> str:
        """The action's own text, with its category for context.

        Prefixing with the category is what lets "view over" reach an overlay
        switch: the word the user remembers is often where it lives rather than
        what it is called.
        """
        category = str(action.property("av_category") or "")
        text = action.text().replace("&", "").strip()
        return f"{category} — {text}" if category else text

    # ── running ──────────────────────────────────────────────────────

    def _run_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        action = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        if isinstance(action, QAction):
            action.trigger()

    def keyPressEvent(self, event) -> None:
        """Let the arrow keys drive the list while the cursor stays in the field."""
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self._list.currentRow()
            step = 1 if event.key() == Qt.Key.Key_Down else -1
            self._list.setCurrentRow(max(0, min(self._list.count() - 1, row + step)))
            return
        super().keyPressEvent(event)
