"""The braid, its two selectors, and the drag that changes an identity (D-141).

What these pin down is that the gesture means what the plot shows: dragging a
lane's line onto another row asks for a flip at the node it snapped to, and
dragging it back off an accepted crossing asks for that flip to be undone
rather than for a second one stacked on top of it.
"""

from __future__ import annotations

import numpy as np
import pytest

from avialsync.core.identity_detect import Trajectory
from avialsync.core.identity_groups import ANIMALS
from avialsync.core.identity_swaps import SwapEvent, SwapGroup
from avialsync.ui.identity_braid import BraidNode, build_model
from avialsync.ui.identity_panel import ALL_PARTS_ITEM, IdentityPanel, group_label

FRAMES = 200
FLIP = 100
LANES = ("testMouse", "conSpecific")
PARTS = ("snout", "wrist")
SOURCE = "/data/twomice.csv"

GROUP = SwapGroup(
    name=ANIMALS,
    lanes=LANES,
    parts=PARTS,
    members=tuple((lane, part, f"{lane}_{part}") for lane in LANES for part in PARTS),
)


def _times() -> np.ndarray:
    return np.arange(FRAMES, dtype=float) / 30.0


def _tracks() -> dict[str, Trajectory]:
    frames = np.arange(FRAMES, dtype=float)
    return {
        "testMouse": Trajectory(frames, np.full(FRAMES, 50.0)),
        "conSpecific": Trajectory(2 * FLIP - frames, np.full(FRAMES, 62.0)),
    }


def _model(*, accepted: bool = False, candidate: bool = False):
    times = _times()
    routing = [(FLIP, {"testMouse": "conSpecific", "conSpecific": "testMouse"})] if accepted else []
    nodes = []
    if accepted:
        nodes.append(
            BraidNode(index=FLIP, at=float(times[FLIP]), lanes=LANES, accepted=True, detail="")
        )
    if candidate:
        nodes.append(
            BraidNode(
                index=FLIP,
                at=float(times[FLIP]),
                lanes=LANES,
                accepted=False,
                detail="came within 4.2 px",
            )
        )
    return build_model(lanes=LANES, times=times, routing=routing, nodes=nodes, tracks=_tracks())


@pytest.fixture
def panel(qtbot) -> IdentityPanel:
    widget = IdentityPanel()
    qtbot.addWidget(widget)
    widget.set_groups(SOURCE, [GROUP], {(ANIMALS, ""): (1, 0), (ANIMALS, "wrist"): (0, 2)})
    return widget


# ── the selectors ────────────────────────────────────────────────────


def test_the_part_menu_offers_every_part_and_all_of_them_at_once(panel) -> None:
    offered = [panel._part_box.itemData(row) for row in range(panel._part_box.count())]

    assert offered == [ALL_PARTS_ITEM, *PARTS]
    assert panel.part() == ALL_PARTS_ITEM


def test_the_part_menu_says_where_the_candidates_are(panel) -> None:
    """Choosing a part is not blind: the counts are in the menu, not after a click."""
    labels = [panel._part_box.itemText(row) for row in range(panel._part_box.count())]

    assert "1 candidate(s)" in labels[0]
    assert "2 accepted" in labels[PARTS.index("wrist") + 1]
    assert labels[PARTS.index("snout") + 1] == "snout"


def test_a_group_id_is_never_what_the_user_reads() -> None:
    assert group_label("animals") == "Animals"
    assert group_label("sides") == "Left / Right"
    assert group_label("sides:testMouse") == "Left / Right — testMouse"


def test_a_recording_with_nothing_confusable_says_so(qtbot) -> None:
    widget = IdentityPanel()
    qtbot.addWidget(widget)

    widget.set_groups("", [], {})

    assert "no labels that could be confused" in widget._evidence.text()


# ── the picture ──────────────────────────────────────────────────────


def test_an_accepted_flip_moves_a_lane_onto_the_other_row(panel) -> None:
    model = _model(accepted=True)
    panel.show_model(model)

    assert model.row("testMouse") != model.row("conSpecific")
    assert model.routing[-1][1]["testMouse"] == "conSpecific"


def test_the_separation_trace_keeps_the_closest_approach(panel) -> None:
    """Decimated by minimum: the frame where they touched is the whole point."""
    model = _model()
    _times_out, distance = model.separation

    assert float(np.min(distance)) == pytest.approx(12.0, abs=0.5)


def test_the_braid_says_what_it_shows_for_a_reader_who_cannot_see_it(panel) -> None:
    panel.show_model(_model(accepted=True, candidate=True))

    described = panel.describe()

    assert "testMouse" in described and "conSpecific" in described
    assert "1 accepted swap(s)" in described


# ── the gesture ──────────────────────────────────────────────────────


def _drag(panel: IdentityPanel, start_lane: str, end_lane: str, at: float) -> None:
    model = panel._model
    assert model is not None
    panel._on_dragged(at, model.row(start_lane), at, model.row(end_lane))


def test_dragging_a_line_onto_another_row_asks_for_a_swap(panel, qtbot) -> None:
    panel.show_model(_model(candidate=True))
    times = _times()

    with qtbot.waitSignal(panel.swap_requested) as caught:
        _drag(panel, "testMouse", "conSpecific", float(times[FLIP]))

    event = caught.args[0]
    assert isinstance(event, SwapEvent)
    assert event.index == FLIP
    assert set(event.lanes) == set(LANES)
    assert event.parts == ()  # "All parts" moves the whole animal


def test_a_drag_snaps_to_the_node_rather_than_to_the_pointer(panel, qtbot) -> None:
    panel.show_model(_model(candidate=True))
    times = _times()
    # A pointer three frames early still means the crossing it is pointing at.
    with qtbot.waitSignal(panel.swap_requested) as caught:
        _drag(panel, "testMouse", "conSpecific", float(times[FLIP - 3]))

    assert caught.args[0].index == FLIP


def test_a_drag_far_from_any_node_lands_on_the_frame_it_was_made_at(panel, qtbot) -> None:
    panel.show_model(_model())
    times = _times()

    with qtbot.waitSignal(panel.swap_requested) as caught:
        _drag(panel, "testMouse", "conSpecific", float(times[20]))

    assert caught.args[0].index == 20


def test_dragging_a_line_back_off_a_crossing_undoes_that_flip(panel, qtbot) -> None:
    """Not a second transposition: two events would say a person judged two
    crossings where they judged one."""
    panel.show_model(_model(accepted=True))
    times = _times()

    with qtbot.waitSignal(panel.undo_requested) as caught:
        _drag(panel, "testMouse", "conSpecific", float(times[FLIP]))

    assert caught.args[0].index == FLIP


def test_a_drag_that_lands_on_its_own_row_changes_nothing(panel, qtbot) -> None:
    panel.show_model(_model(candidate=True))
    times = _times()

    with qtbot.assertNotEmitted(panel.swap_requested):
        _drag(panel, "testMouse", "testMouse", float(times[FLIP]))


def test_selecting_one_part_scopes_the_swap_to_it(panel, qtbot) -> None:
    panel.show_model(_model(candidate=True))
    panel._part_box.setCurrentIndex(PARTS.index("wrist") + 1)
    times = _times()

    with qtbot.waitSignal(panel.swap_requested) as caught:
        _drag(panel, "testMouse", "conSpecific", float(times[FLIP]))

    assert caught.args[0].parts == ("wrist",)


def test_clicking_a_node_goes_there(panel, qtbot) -> None:
    panel.show_model(_model(candidate=True))
    times = _times()

    with qtbot.waitSignal(panel.seek_requested) as caught:
        panel._on_clicked(float(times[FLIP]), 0.0)

    assert caught.args[0] == pytest.approx(float(times[FLIP]))
    assert "4.2 px" in panel._evidence.text()


def test_asking_for_a_scan_names_what_is_selected(panel, qtbot) -> None:
    panel._part_box.setCurrentIndex(PARTS.index("snout") + 1)

    with qtbot.waitSignal(panel.detect_requested) as caught:
        panel._detect.click()

    assert caught.args == [ANIMALS, "snout"]
