"""Keyboard shortcuts, listed and editable — still derived from live QActions.

The listing has always come from the live ``QAction`` objects rather than a
hardcoded table, which is what makes it impossible for it to drift from the
real bindings (D-022.6). That property is kept: editing was *added* to it, not
substituted for it.

Shortcuts were fixed before this. Every editor, DAW and IDE competing for the
same muscle memory allows rebinding, and a user whose habits came from one of
them had to relearn rather than adjust (WP-3).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.i18n import tr
from avialsync.ui.shortcut_overrides import (
    clear_override,
    conflicting_action,
    default_for,
    store_override,
)

# Preferred display order for categories
_CATEGORY_ORDER = ["Playback", "Marking", "Edit", "Align", "View", "File", "Other"]


class ShortcutsDialog(QDialog):
    """Lists every registered command, with its key editable.

    Derives content entirely from live QAction objects — impossible to drift
    from the real bindings (D-022.6).

    Parameters
    ----------
    actions_by_group:
        Dict mapping category name -> list of QAction objects.
    """

    def __init__(
        self,
        actions_by_group: dict[str, list[QAction]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Keyboard Shortcuts"))
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Double-click a key to change it. Reset restores the built-in binding.")
        )

        rows: list[tuple[str, str, str, QAction]] = []
        seen_cats = set(_CATEGORY_ORDER)
        ordered_cats = _CATEGORY_ORDER + [c for c in actions_by_group if c not in seen_cats]

        for cat in ordered_cats:
            acts = actions_by_group.get(cat)
            if not acts:
                continue
            for act in acts:
                # Unbound actions are listed too. One with no key is exactly
                # the one somebody wants to give a key, and omitting it left
                # the dialog unable to offer that.
                key_text = "  /  ".join(
                    text
                    for text in (
                        seq.toString(QKeySequence.SequenceFormat.NativeText)
                        for seq in act.shortcuts()
                    )
                    if text
                )
                label = act.text().replace("&", "").rstrip(". ").strip()
                rows.append((cat, key_text, label, act))

        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["Category", "Key", "Action"])
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        # Only the Key column is editable; the other two describe the action.
        table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed
        )
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        for row, (cat, key, action_label, act) in enumerate(rows):
            cat_item = QTableWidgetItem(cat)
            cat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, cat_item)

            key_item = QTableWidgetItem(key)
            key_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            key_item.setToolTip(tr("Double-click to change this shortcut"))
            key_item.setData(Qt.ItemDataRole.UserRole, act)
            table.setItem(row, 1, key_item)

            action_item = QTableWidgetItem(action_label)
            action_item.setFlags(action_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 2, action_item)

        layout.addWidget(table)
        if not rows:
            layout.addWidget(QLabel("No commands registered."))

        self._table = table
        table.itemChanged.connect(self._on_key_edited)

        self._notice = QLabel("")
        self._notice.setWordWrap(True)
        layout.addWidget(self._notice)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.close)
        reset = btn_box.addButton("Reset selected", QDialogButtonBox.ButtonRole.ResetRole)
        reset.clicked.connect(self._reset_selected)
        layout.addWidget(btn_box)

    # ── editing ──────────────────────────────────────────────────────

    def _actions(self) -> list[QAction]:
        """Every action the table holds, for conflict detection."""
        found: list[QAction] = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 1)
            act = item.data(Qt.ItemDataRole.UserRole) if item else None
            if isinstance(act, QAction):
                found.append(act)
        return found

    def _on_key_edited(self, item: QTableWidgetItem) -> None:
        """Bind what was typed, reporting a clash rather than refusing it."""
        if item.column() != 1:
            return
        act = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(act, QAction):
            return

        typed = item.text().strip()
        sequence = QKeySequence(typed)
        # `isEmpty()` is the wrong test: Qt parses "banana" into a non-empty
        # sequence of one meaningless key. What distinguishes nonsense is that
        # it renders back as nothing, so a round trip through `toString` is the
        # check -- verified against 'not a key', 'zzzz' and 'Ctrl+'.
        if typed and not sequence.toString():
            self._notice.setText(f"{typed!r} is not a key sequence. The shortcut is unchanged.")
            self._show_live_key(item, act)
            return

        clash = conflicting_action(self._actions(), typed, exclude=act)
        act.setShortcut(sequence)
        store_override(act, typed)
        self._show_live_key(item, act)

        if clash is not None:
            # Reported, not refused (Law 1). Two actions in different contexts
            # can legitimately share a key, and rebinding a set passes through
            # conflicting states on the way to a consistent one.
            self._notice.setText(
                f"{typed} is also bound to '{clash.text()}'. Both will respond to it."
            )
        else:
            self._notice.setText("")

    def _reset_selected(self) -> None:
        """Give the selected rows their built-in shortcuts back."""
        for row in {index.row() for index in self._table.selectedIndexes()}:
            item = self._table.item(row, 1)
            if item is None:
                continue
            act = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(act, QAction):
                continue
            clear_override(act)
            act.setShortcut(QKeySequence(default_for(act)))
            self._show_live_key(item, act)
        self._notice.setText("")

    def _show_live_key(self, item: QTableWidgetItem, act: QAction) -> None:
        """Show the action's real shortcut without re-entering the edit handler."""
        blocked = self._table.blockSignals(True)
        try:
            item.setText(act.shortcut().toString(QKeySequence.SequenceFormat.NativeText))
        finally:
            self._table.blockSignals(blocked)
