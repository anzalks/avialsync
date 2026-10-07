"""A custom identity group maps user-named lanes to real pose columns."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox

from avialsync.core.pose import PosePoint, PoseSchema
from avialsync.ui.identity_group_dialog import IdentityGroupDialog


def test_a_pair_of_pose_columns_becomes_a_declared_group(qtbot) -> None:
    schema = PoseSchema(
        points=(
            PosePoint(individual="", bodypart="pawA", axes=("x", "y"), has_likelihood=False),
            PosePoint(individual="", bodypart="pawB", axes=("x", "y"), has_likelihood=False),
        ),
        frame_indexed=True,
    )
    dialog = IdentityGroupDialog(schema, ())
    qtbot.addWidget(dialog)
    dialog._name.setText("front paws")
    dialog._first.setText("left")
    dialog._second.setText("right")
    dialog._rows[0][0].setText("front")
    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons is not None

    qtbot.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)

    group = dialog.group()
    assert group is not None
    assert group.name == "custom:front paws"
    assert group.lanes == ("left", "right")
    assert group.point("left", "front") == "pawA"
    assert group.point("right", "front") == "pawB"
