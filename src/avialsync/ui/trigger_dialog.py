"""Saying what each column of a trigger file actually is.

Nothing in a CSV says whether a logical line is a camera's exposure strobe, a
pulse generator's trigger, or a shared sync wave -- and that distinction is not
cosmetic. A strobe is evidence that frames *happened* and licenses an exact
per-frame mapping; a trigger records only that they were asked for, and a drop
looks exactly like a frame that arrived. So the user declares it, once, and the
declaration is what the session stores and what the model ladder reads.

The dialog leads with that question rather than burying it: the kind column is
the first thing after the name, and nothing is pre-selected as a strobe.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.triggers import TriggerKind
from avialsync.ui.i18n import tr
from avialsync.ui.theme import set_bold

__all__ = ["TriggerEvidenceDialog"]

#: What each kind means, in the terms that decide what it licenses. Shown as
#: the row's tooltip, because the difference between two of these is the
#: difference between an exact mapping and a fitted one.
_KIND_HELP = {
    TriggerKind.FRAME_STROBE: (
        "The camera emitted one pulse per exposure it actually took. Pulse count is "
        "frame count, a dropped frame shows as a gap in the train, and each frame can "
        "be given the time its own exposure was measured at."
    ),
    TriggerKind.FRAME_TRIGGER: (
        "A pulse generator asked the camera for each exposure. This records the "
        "request, not the result: a frame the camera dropped looks exactly like one it "
        "kept, so pairing by index would shift everything after the loss."
    ),
    TriggerKind.SYNC_TRAIN: (
        "A shared square wave both systems recorded, far sparser than the frame rate. "
        "Enough to follow the two clocks wherever they wander, not enough to identify "
        "a frame."
    ),
    TriggerKind.SPARSE_EVENTS: (
        "A few landmarks -- a start pulse, a stop pulse, a switch thrown by hand. "
        "Enough to place a recording, rarely enough to check the placing."
    ),
}

_COLUMNS = ("Use", "Train", "Column", "What it is", "Evidence about")


@dataclass(frozen=True)
class TrainChoice:
    """One train the user kept, and what they said it is."""

    train_id: str
    column: str
    kind: TriggerKind
    target: str
    mode: str


class TriggerEvidenceDialog(QDialog):
    """Confirm or correct what a trigger file's columns are."""

    def __init__(
        self,
        path: Path,
        suggestion: dict[str, Any],
        target_paths: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Trigger evidence — {name}").format(name=path.name))
        self._suggestion = suggestion
        self._target_paths = list(target_paths)

        layout = QVBoxLayout(self)
        heading = QLabel(
            tr(
                "Say what each of these columns is. Which way the wire ran decides what "
                "the pulses can prove, and nothing in the file records it."
            )
        )
        heading.setWordWrap(True)
        set_bold(heading)
        layout.addWidget(heading)

        trains = list(suggestion.get("trains", []))
        self._table = QTableWidget(len(trains), len(_COLUMNS), self)
        self._table.setHorizontalHeaderLabels([tr(name) for name in _COLUMNS])
        self._table.verticalHeader().setVisible(False)
        self._table.setAccessibleName(tr("Trigger trains in this file"))
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for row, train in enumerate(trains):
            self._build_row(row, train)
        layout.addWidget(self._table)

        self._note = QLabel(
            tr(
                "Nothing is offered as an exposure strobe by default: whether these "
                "pulses came from frames that happened is a fact about the wiring, and "
                "it is what decides whether an exact per-frame mapping is allowed."
            )
        )
        self._note.setWordWrap(True)
        layout.addWidget(self._note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Use as evidence"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── construction ─────────────────────────────────────────────────

    def _build_row(self, row: int, train: dict[str, Any]) -> None:
        """One row per column the provider found, defaulting to kept."""
        use = QCheckBox(self)
        use.setChecked(True)
        use.setAccessibleName(tr("Use {name} as evidence").format(name=train.get("id", "")))
        self._table.setCellWidget(row, 0, use)

        self._table.setItem(row, 1, QTableWidgetItem(str(train.get("id", ""))))
        self._table.setItem(row, 2, QTableWidgetItem(str(train.get("column", ""))))

        kinds = QComboBox(self)
        for kind in TriggerKind:
            kinds.addItem(_kind_label(kind), str(kind))
            kinds.setItemData(kinds.count() - 1, _KIND_HELP[kind], 3)  # Qt::ToolTipRole
        kinds.setCurrentIndex(kinds.findData(str(train.get("kind", TriggerKind.SYNC_TRAIN))))
        kinds.setAccessibleName(tr("What {name} is evidence of").format(name=train.get("id", "")))
        kinds.currentIndexChanged.connect(lambda _i, combo=kinds: self._explain(combo))
        self._table.setCellWidget(row, 3, kinds)

        targets = QComboBox(self)
        targets.addItem(tr("(ask when aligning)"), "")
        for candidate in self._target_paths:
            targets.addItem(Path(candidate).name, candidate)
        hinted = str(train.get("target", ""))
        if hinted:
            index = targets.findData(hinted)
            targets.setCurrentIndex(index if index >= 0 else 0)
        targets.setAccessibleName(
            tr("What {name} is evidence about").format(name=train.get("id", ""))
        )
        self._table.setCellWidget(row, 4, targets)

    def _explain(self, combo: QComboBox) -> None:
        """Put the chosen kind's consequences under the table, not in a tooltip only."""
        self._note.setText(_KIND_HELP[TriggerKind(str(combo.currentData()))])

    # ── result ───────────────────────────────────────────────────────

    def choices(self) -> list[TrainChoice]:
        """The trains the user kept, with what they said each one is."""
        kept: list[TrainChoice] = []
        declared = list(self._suggestion.get("trains", []))
        for row in range(self._table.rowCount()):
            use = self._table.cellWidget(row, 0)
            if not isinstance(use, QCheckBox) or not use.isChecked():
                continue
            kinds = self._table.cellWidget(row, 3)
            targets = self._table.cellWidget(row, 4)
            train_item = self._table.item(row, 1)
            column_item = self._table.item(row, 2)
            if not isinstance(kinds, QComboBox) or not isinstance(targets, QComboBox):
                continue
            kept.append(
                TrainChoice(
                    train_id=train_item.text() if train_item else "",
                    column=column_item.text() if column_item else "",
                    kind=TriggerKind(str(kinds.currentData())),
                    target=str(targets.currentData()),
                    mode=str(declared[row].get("mode", "level"))
                    if row < len(declared)
                    else "level",
                )
            )
        return kept

    def config(self) -> dict[str, Any]:
        """The provider configuration these choices amount to."""
        return {
            "time_column": self._suggestion.get("time_column", ""),
            "trains": [
                {
                    "id": choice.train_id,
                    "column": choice.column,
                    "kind": str(choice.kind),
                    "mode": choice.mode,
                    "target": choice.target,
                }
                for choice in self.choices()
            ],
        }


def _kind_label(kind: TriggerKind) -> str:
    """A name a person recognises, rather than the wire value."""
    return {
        TriggerKind.FRAME_STROBE: tr("Camera exposure strobe"),
        TriggerKind.FRAME_TRIGGER: tr("External frame trigger"),
        TriggerKind.SYNC_TRAIN: tr("Shared sync pulse train"),
        TriggerKind.SPARSE_EVENTS: tr("Sparse landmarks"),
    }[kind]
