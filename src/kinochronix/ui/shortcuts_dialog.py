"""Keyboard shortcuts reference dialog — derived from live QAction registry (D-022.6)."""

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

# Preferred display order for categories
_CATEGORY_ORDER = ["Playback", "Marking", "View", "File", "Other"]


class ShortcutsDialog(QDialog):
    """Modal dialog listing all keyboard shortcuts.

    Derives content entirely from live QAction objects — impossible to drift
    from the real bindings (D-022.6).

    Parameters
    ----------
    actions_by_group:
        Dict mapping category name → list of QAction objects that have shortcuts.
    """

    def __init__(
        self,
        actions_by_group: dict[str, list[QAction]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        # Flatten into (category, key_text, description) rows in defined order
        rows: list[tuple[str, str, str]] = []
        seen_cats = set(_CATEGORY_ORDER)
        ordered_cats = _CATEGORY_ORDER + [c for c in actions_by_group if c not in seen_cats]

        for cat in ordered_cats:
            acts = actions_by_group.get(cat)
            if not acts:
                continue
            for act in acts:
                seqs = act.shortcuts()
                if not seqs:
                    continue
                key_text = "  /  ".join(
                    s.toString(QKeySequence.SequenceFormat.NativeText)
                    for s in seqs
                    if s.toString(QKeySequence.SequenceFormat.NativeText)
                )
                if not key_text:
                    continue
                rows.append((cat, key_text, act.text().replace("…", "").strip()))

        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["Category", "Key", "Action"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        for row, (cat, key, action) in enumerate(rows):
            cat_item = QTableWidgetItem(cat)
            cat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 0, cat_item)

            key_item = QTableWidgetItem(key)
            key_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 1, key_item)

            table.setItem(row, 2, QTableWidgetItem(action))

        layout.addWidget(table)

        if not rows:
            layout.addWidget(QLabel("No shortcuts registered."))

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.close)
        layout.addWidget(btn_box)
