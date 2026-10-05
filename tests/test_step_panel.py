"""The shared guided-step panel (D-176, INTERFACE_DESIGN_PLAN §4.4, DS-8)."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton

from avialsync.ui.design_tokens import ControlRole, role_of
from avialsync.ui.step_panel import StepPanel


def test_one_primary_one_sentence_detail_behind_more(qtbot) -> None:
    panel = StepPanel("Wheel · Example")
    qtbot.addWidget(panel)
    panel.show()
    first, second = QPushButton("Next Point"), QPushButton("Done")
    panel.set_primary(first)
    panel.set_primary(second)
    primaries = [
        b
        for b in panel.findChildren(QPushButton)
        if b.isVisible() and role_of(b) is ControlRole.PRIMARY
    ]
    assert primaries == [second], "at most one primary is shown (R2)"

    panel.set_instruction("Click point 2B in camera_3.")
    assert "\n" not in panel.instruction.text()
    panel.add_more(QLabel("Rings are clicks; dashed diamonds are projected estimates."))
    assert not panel.more.isVisible()
    panel.more_toggle.click()
    assert panel.more.isVisible()

    panel.set_progress(5, 12)
    assert panel.progress.accessibleName() == "Step 5 of 12"


def test_destructive_choices_live_in_the_overflow_and_follow_their_button(qtbot) -> None:
    panel = StepPanel("Props")
    qtbot.addWidget(panel)
    discarded: list[bool] = []
    discard = QPushButton("Discard Clicks")
    discard.clicked.connect(lambda: discarded.append(True))
    panel.add_overflow(discard, destructive=True)
    assert not discard.isVisible()
    (action,) = [a for a in panel.overflow.menu().actions() if not a.isSeparator()]
    assert action.property("av_role") == "destructive" and not action.icon().isNull()
    discard.setEnabled(False)
    assert not action.isEnabled(), "the entry greys with the button it stands for"
    discard.setEnabled(True)
    action.trigger()
    assert discarded == [True]


def test_learn_more_links_to_the_guide(qtbot) -> None:
    panel = StepPanel("Wheel")
    qtbot.addWidget(panel)
    panel.set_learn_more("https://example.invalid/guide#wheels")
    assert "https://example.invalid/guide#wheels" in panel.learn_more.text()
