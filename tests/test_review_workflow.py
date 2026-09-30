from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.ui.main_window import MainWindow
from avialsync.ui.review_workflow import ReviewWorkflowDialog


def test_workflow_buttons_trigger_their_authoritative_actions(qapp: QApplication, qtbot) -> None:
    action_keys = ("open_video", "open_sensor", "synchronize", "save_session")
    actions = {key: QAction(key) for key in action_keys}
    triggered: list[str] = []
    for key, action in actions.items():
        action.triggered.connect(lambda _checked=False, selected=key: triggered.append(selected))

    dialog = ReviewWorkflowDialog(actions, None)
    qtbot.addWidget(dialog)
    for key in action_keys:
        dialog.action_buttons[key].click()

    assert triggered == list(action_keys)
    assert all(dialog.action_buttons[key].text() == actions[key].text() for key in action_keys)


def test_help_opens_a_reusable_accessible_workflow(qapp: QApplication, qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    try:
        window._act_review_workflow.trigger()
        dialog = window._help_controller._review_workflow_dialog

        assert dialog is not None
        assert dialog.isVisible()
        assert dialog.accessibleName() == "Recording review workflow"
        assert len(dialog.action_buttons) == 4

        window._act_review_workflow.trigger()
        assert window._help_controller._review_workflow_dialog is dialog
    finally:
        if isValid(window):
            window.close()
