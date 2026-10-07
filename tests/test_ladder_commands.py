"""Undoable ladder edits keep the changed step as the inverse operation."""

from __future__ import annotations

from avialsync.core.commands import (
    MoveLadderStepCommand,
    SetLadderCommand,
    SetLadderLayoutCommand,
    SetLadderStepCommand,
    SetPhysicalPropCommand,
)
from avialsync.core.document import Document
from avialsync.core.physical_props import (
    BeltProp,
    BeltTrack,
    Ladder,
    LadderLayout,
    LadderPoint,
    LadderStep,
    PhysicalProp,
    PropStore,
    RungPattern,
    StepClick,
)


class Target:
    """The command bus's ladder methods, without a QApplication."""

    def __init__(self) -> None:
        self.props = PropStore()

    def set_ladder(self, name: str, ladder: Ladder | None) -> None:
        self.props.set(name, ladder)

    def set_physical_prop(self, name: str, prop: PhysicalProp | None) -> None:
        self.props.set(name, prop)

    def set_ladder_step(
        self, name: str, step_id: str, step: LadderStep | None, position: int | None = None
    ) -> None:
        self.props.set_step(name, step_id, step, position)

    def move_ladder_step(self, name: str, step_id: str, position: int) -> None:
        self.props.move_step(name, step_id, position)

    def set_ladder_layout(self, name: str, layout: LadderLayout) -> None:
        self.props.set_layout(name, layout)


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


def test_generic_prop_declarations_are_undoable_as_one_inverse_record() -> None:
    target = Target()
    document = Document()
    belt = BeltProp("belt", BeltTrack(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))))
    command = SetPhysicalPropCommand("belt", None, belt, "Add belt")
    document.execute(command, target)
    assert target.props.get("belt") == belt
    assert document.undo(target)
    assert target.props.get("belt") is None
    assert document.redo(target)
    assert target.props.get("belt") == belt


def test_reorder_keeps_irregular_steps_and_undo_restores_order() -> None:
    target = Target()
    steps = (_step("a", 1.0), _step("b", 17.0), _step("c", 3.0))
    target.props.set("steps", Ladder("steps", steps))
    document = Document()
    document.execute(MoveLadderStepCommand("steps", "c", 2, 0, "Move step"), target)
    assert target.props.get("steps").steps == (steps[2], steps[0], steps[1])
    assert document.undo(target)
    assert target.props.get("steps").steps == steps


def test_ladder_layout_change_is_one_undoable_step_that_keeps_clicks() -> None:
    target = Target()
    document = Document()
    ladder = Ladder("Ladder", (_step("a", 10.0), _step("b", 30.0)))
    document.execute(SetLadderCommand("Ladder", None, ladder, "Add"), target)
    document.execute(
        SetLadderLayoutCommand(
            "Ladder", LadderLayout(), LadderLayout("side_rails", RungPattern("a", "b", 5)), "Layout"
        ),
        target,
    )
    changed = target.props.get("Ladder")
    assert isinstance(changed, Ladder)
    assert changed.support == "side_rails"
    assert changed.pattern == RungPattern("a", "b", 5)
    assert changed.steps == ladder.steps
    document.undo(target)
    assert target.props.get("Ladder") == ladder
