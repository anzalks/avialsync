"""Compact, evidence-aware controls for filling or extending ladder steps."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.ladder_support import Position, rung_places
from avialsync.core.physical_props import Ladder, LadderPoint, LadderStep, RungPattern
from avialsync.ui.i18n import tr


def seed_steps(
    steps: Sequence[LadderStep], between_endpoints: bool, pattern: RungPattern | None = None
) -> tuple[LadderStep, LadderStep] | None:
    """Select the same observed anchors for readiness and accepted layout edits."""
    candidates = list(steps) if between_endpoints else [s for s in steps if len(s.points) == 2]
    if pattern is not None and pattern.between_endpoints == between_endpoints:
        by_id = {s.step_id: s for s in steps}
        if pattern.first in by_id and pattern.second in by_id:
            candidates = [by_id[pattern.first], by_id[pattern.second]]
    if len(candidates) < 2:
        return None
    first, last = candidates[0], candidates[-1] if between_endpoints else candidates[1]
    if (
        len(first.points) not in (1, 2)
        or len(first.points) != len(last.points)
        or (not between_endpoints and len(first.points) != 2)
    ):
        return None
    return first, last


def seed_positions(seeds: tuple[LadderStep, LadderStep]) -> list[list[Position | None]] | None:
    """Use solved 3D, or one shared camera; never combine unrelated image spaces."""
    points = [p for step in seeds for p in step.points]
    if all(p.xyz is not None for p in points):
        return [[p.xyz for p in step.points] for step in seeds]
    cameras = set.intersection(*({c.camera for c in p.clicks} for p in points))
    if not cameras:
        return None
    camera = sorted(cameras)[0]
    return [
        [next((c.x, c.y) for c in p.clicks if c.camera == camera) for p in s.points] for s in seeds
    ]


def pattern_readiness(
    steps: Sequence[LadderStep], between: bool, count: int, pattern: RungPattern | None = None
) -> tuple[bool, str]:
    """The shared evidence check for the button and its command handler."""
    if not 2 <= count <= 10_000:
        return False, tr("The total must be between 2 and 10000, including both anchors.")
    seeds = seed_steps(steps, between, pattern)
    if seeds is None:
        return False, (
            tr("Click first and last footholds, or both ends of the first and last rungs.")
            if between
            else tr("Click both ends of two neighbouring rungs.")
        )
    positions = seed_positions(seeds)
    if positions is None or any(
        p is None for p in rung_places(positions, (0, 1, count), between_endpoints=between)
    ):
        return False, tr("Use distinct steps visible in the same camera, or solved in 3D.")
    if not between:
        return True, tr("Extends from the two neighbouring rungs; guides are estimates.")
    return True, (
        tr("Count includes both endpoints. Even spacing in 3D; guides are estimates.")
        if all(p.xyz is not None for s in seeds for p in s.points)
        else tr("Count includes both endpoints. Image guides remain 2D estimates.")
    )


class LadderPatternControls(QWidget):
    """Count includes the anchors; pending clicks are accepted only by a named action."""

    requested = Signal(int, bool)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAccessibleName(tr("Ladder spacing"))
        self._name: str | None = None
        self._pattern: RungPattern | None = None
        self._steps: tuple[LadderStep, ...] = ()
        self._pending = False
        self._blocked = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.mode = QComboBox(self)
        self.mode.addItem(tr("First and last steps"), True)
        self.mode.addItem(tr("Two neighbouring rungs"), False)
        self.mode.setAccessibleName(tr("Ladder spacing mode"))
        self.mode.setAccessibleDescription(
            tr("Fill between endpoints, or extend from two neighbours.")
        )
        self.count = QSpinBox(self)
        self.count.setRange(0, 10_000)
        self.count.setSpecialValueText(tr("Off"))
        self.count.setAccessibleName(tr("Steps in total"))
        self.count.setAccessibleDescription(
            tr("Total including both clicked endpoints; Off removes the guide.")
        )
        form.addRow(tr("Spacing"), self.mode)
        form.addRow(tr("Steps in total"), self.count)
        layout.addLayout(form)
        self.apply = QPushButton(self)
        self.apply.setAccessibleDescription(
            tr("Save a complete pending step and apply the selected spacing guide.")
        )
        self.note = QLabel(self)
        self.note.setWordWrap(True)
        layout.addWidget(self.apply)
        layout.addWidget(self.note)
        self.mode.currentIndexChanged.connect(self._refresh)
        self.count.valueChanged.connect(self._refresh)
        self.apply.clicked.connect(
            lambda: self.requested.emit(self.count.value(), bool(self.mode.currentData()))
        )
        self._refresh()

    def set_context(
        self, ladder: Ladder | None, pending: tuple[LadderPoint, ...] = (), *, blocked: bool = False
    ) -> None:
        """Preserve an unapplied count while the user clicks the endpoint steps."""
        name, pattern = (ladder.name, ladder.pattern) if ladder else (None, None)
        if name != self._name or pattern != self._pattern:
            changed_name = name != self._name
            self._name, self._pattern = name, pattern
            self.count.setValue(0 if pattern is None else pattern.count)
            if pattern is not None or changed_name:
                self.mode.setCurrentIndex(0 if pattern is None or pattern.between_endpoints else 1)
        self._steps = () if ladder is None else ladder.steps
        self._pending = bool(pending)
        self._blocked = blocked
        if pending:
            self._steps = (*self._steps, LadderStep("__pending__", tr("Pending step"), pending))
        self._refresh()

    def _refresh(self) -> None:
        between = bool(self.mode.currentData())
        count = self.count.value()
        if count == 0:
            text = tr("Remove spacing guide")
            ready = self._pattern is not None
            reason = (
                tr("Keeps observed steps and removes only the estimated guide.")
                if ready
                else tr("Set a total of at least two steps.")
            )
        else:
            text = (
                (tr("Save step and fill between") if between else tr("Save step and extend rungs"))
                if self._pending
                else (
                    tr("Fill between first and last")
                    if between
                    else tr("Extend from two neighbours")
                )
            )
            ready, reason = (
                (False, tr("Finish or cancel the current step before changing spacing."))
                if self._blocked
                else pattern_readiness(self._steps, between, count, self._pattern)
            )
        self.apply.setText(text)
        self.apply.setAccessibleName(text)
        self.apply.setEnabled(ready)
        self.apply.setToolTip(reason)
        self.note.setText(reason)
