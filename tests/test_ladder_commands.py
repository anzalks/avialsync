"""Undoable ladder edits keep the changed step as the inverse operation."""

from __future__ import annotations

from avialsync.core.commands import MoveLadderStepCommand, SetLadderCommand, SetLadderStepCommand
from avialsync.core.document import Document
from avialsync.core.physical_props import Ladder, LadderPoint, LadderStep, PropStore, StepClick


class Target:
    """The command bus's ladder methods, without a QApplication."""

    def __init__(self) -> None:
        self.props = PropStore()

    def set_ladder(self, name: str, ladder: Ladder | None) -> None:
        self.props.set(name, ladder)

    def set_ladder_step(
        self, name: str, step_id: str, step: LadderStep | None, position: int | None = None
    ) -> None:
        self.props.set_step(name, step_id, step, position)

    def move_ladder_step(self, name: str, step_id: str, position: int) -> None:
        self.props.move_step(name, step_id, position)


def _step(step_id: str, x: float) -> LadderStep:
    click = StepClick("Front", 7, x, 20.0)
    return LadderStep(step_id, f"Step {step_id}", (LadderPoint().with_click(click),))


def test_ladder_and_individual_step_undo_without_copying_other_steps() -> None:
    target = Target()
    document = Document()
    first = _step("first", 10.0)
    second = _step("second", 40.0)
    ladder = Ladder("horizontal ladder", (first, second))

    document.execute(SetLadderCommand(ladder.name, None, ladder, "Add ladder"), target)
    assert target.props.get(ladder.name) == ladder
    assert document.is_dirty

    changed = _step("first", 15.0)
    step_edit = SetLadderStepCommand(ladder.name, "first", first, changed, "Move step")
    document.execute(step_edit, target)
    assert target.props.get(ladder.name).steps == (changed, second)
    assert step_edit.before is first and step_edit.after is changed

    assert document.undo(target)
    assert target.props.get(ladder.name).steps == (first, second)
    assert document.undo(target)
    assert target.props.get(ladder.name) is None
    assert not document.is_dirty
    assert document.redo(target)
    assert document.redo(target)
    assert target.props.get(ladder.name).steps == (changed, second)


def test_remove_one_step_is_undoable_without_removing_the_ladder() -> None:
    target = Target()
    first = _step("a", 1.0)
    second = _step("b", 2.0)
    target.props.set("steps", Ladder("steps", (first, second)))
    document = Document()
    document.execute(SetLadderStepCommand("steps", "a", first, None, "Remove step", 0), target)
    assert target.props.get("steps").steps == (second,)
    assert document.undo(target)
    assert target.props.get("steps").steps == (first, second)


def test_reorder_keeps_irregular_steps_and_undo_restores_order() -> None:
    target = Target()
    steps = (_step("a", 1.0), _step("b", 17.0), _step("c", 3.0))
    target.props.set("steps", Ladder("steps", steps))
    document = Document()
    document.execute(MoveLadderStepCommand("steps", "c", 2, 0, "Move step"), target)
    assert target.props.get("steps").steps == (steps[2], steps[0], steps[1])
    assert document.undo(target)
    assert target.props.get("steps").steps == steps
