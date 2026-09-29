"""The braid, its two selectors, and the drag that changes an identity (D-141).

What these pin down is that the gesture means what the plot shows: dragging a
lane's line onto another row asks for a flip at the node it snapped to, and
dragging it back off an accepted crossing asks for that flip to be undone
rather than for a second one stacked on top of it.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt

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
    assert group_label("custom:front paws") == "front paws"


def test_a_recording_with_nothing_derivable_points_at_new_group(qtbot) -> None:
    """Not a dead end. This is the recording that needs New group most."""
    widget = IdentityPanel()
    qtbot.addWidget(widget)

    widget.set_groups("", [], {})

    assert "New group" in widget._evidence.text()
    assert widget._new_group.isEnabled()


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


def test_a_drag_that_lands_on_its_own_row_seeks_instead_of_swapping(panel, qtbot) -> None:
    """A click that moves a pixel arrives as a drag, and must still seek.

    Treating it as nothing is what made the braid look like it did not respond
    to clicks at all, while the trace under it did.
    """
    panel.show_model(_model())
    times = _times()

    with (
        qtbot.assertNotEmitted(panel.swap_requested),
        qtbot.waitSignal(panel.seek_requested) as caught,
    ):
        _drag(panel, "testMouse", "testMouse", float(times[20]))

    assert caught.args[0] == pytest.approx(float(times[20]))


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


def test_selected_candidate_can_be_reviewed_nudged_and_applied(panel, qtbot) -> None:
    panel.show_model(_model(candidate=True))
    panel.set_video_available(True)

    with qtbot.waitSignal(panel.play_region_requested) as playback:
        panel._play.click()
    assert playback.args == pytest.approx([_times()[FLIP] - 2, _times()[FLIP] + 2])

    with qtbot.waitSignal(panel.seek_requested) as seek:
        panel._forward.click()
    assert seek.args[0] == pytest.approx(_times()[FLIP + 1])

    with qtbot.waitSignal(panel.apply_requested):
        panel._apply.click()
    # The nudge is what the apply will use: one button, and the frame under
    # review is the frame it accepts.
    assert panel.selected_index() == FLIP + 1
    event = panel.event_at(panel.selected_index())
    assert event is not None and event.parts == ()


def test_accepted_selection_offers_remove_and_still_allows_applying(panel, qtbot) -> None:
    """Apply is never conditional on the list: it means "swap from where I am".

    A swap accepted at frame 7 made its own crossing the selected row, which
    greyed the button out at frame 8 -- the next frame the person was looking
    at.
    """
    panel.show_model(_model(accepted=True))
    assert panel._apply.isEnabled()
    assert panel._remove.isEnabled()

    # Remove asks; the window answers with the swap in force at the playhead,
    # which is the mirror of how applying picks its frame.
    with qtbot.waitSignal(panel.remove_requested):
        panel._remove.click()


def test_drag_must_start_on_a_lane_line(panel, qtbot) -> None:
    panel.show_model(_model(candidate=True))
    model = panel._model
    assert model is not None

    with qtbot.assertNotEmitted(panel.swap_requested):
        panel._on_dragged(
            float(model.times[FLIP]),
            model.row(LANES[0]) - 0.4,
            float(model.times[FLIP]),
            model.row(LANES[1]),
        )


def test_real_pointer_drag_crosses_two_lanes(panel, qtbot) -> None:
    """Exercise pyqtgraph's scene dispatch, not only the panel's handler."""
    panel.show_model(_model(candidate=True))
    panel.resize(800, 520)
    panel.show()
    qtbot.waitExposed(panel)
    model = panel._model
    assert model is not None
    view = panel._braid.getPlotItem().getViewBox()
    start = panel._braid.mapFromScene(
        view.mapViewToScene(QPointF(float(model.times[FLIP]), model.row(LANES[0])))
    )
    end = panel._braid.mapFromScene(
        view.mapViewToScene(QPointF(float(model.times[FLIP]), model.row(LANES[1])))
    )
    with qtbot.waitSignal(panel.swap_requested, timeout=3000) as accepted:
        qtbot.mousePress(panel._braid.viewport(), Qt.MouseButton.LeftButton, pos=start)
        qtbot.mouseMove(panel._braid.viewport(), pos=end)
        qtbot.mouseRelease(panel._braid.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert accepted.args[0].index == FLIP


# ── swapping where the video is, not where a row is ──────────────────


def test_one_button_applies_a_swap_with_or_without_a_selected_crossing(panel, qtbot) -> None:
    """Choosing a crossing seeks the video to it, so the two are one gesture."""
    panel.show_model(_model())
    assert panel._apply.isEnabled()
    assert panel.selected_index() is None

    with qtbot.waitSignal(panel.apply_requested):
        panel._apply.click()


def test_a_frame_means_the_same_swap_however_it_was_reached(panel) -> None:
    """The drag, the reviewed row and the playhead build one event.

    Three gestures that disagreed about which lanes moved, or about whether a
    part-scoped selection applied, would be three ways to write a different
    sidecar from the same intent.
    """
    panel.show_model(_model(candidate=True))
    panel._part_box.setCurrentIndex(PARTS.index("wrist") + 1)

    from_playhead = panel.event_at(FLIP)

    assert from_playhead is not None
    assert from_playhead.index == FLIP
    assert set(from_playhead.lanes) == set(LANES)
    assert from_playhead.parts == ("wrist",)


def test_applying_is_offered_only_with_a_pair_on_screen(qtbot) -> None:
    widget = IdentityPanel()
    qtbot.addWidget(widget)
    widget.set_groups(SOURCE, [], {})

    assert not widget._apply.isEnabled()


def test_choosing_a_crossing_seeks_to_it_so_the_playhead_is_the_review(panel, qtbot) -> None:
    """Which is why applying reads the clock and nothing else."""
    panel.show_model(_model(candidate=True))

    with qtbot.waitSignal(panel.seek_requested) as caught:
        panel._on_clicked(float(_times()[FLIP]), 0.0)

    assert caught.args[0] == pytest.approx(float(_times()[FLIP]))
    assert panel.index_at(caught.args[0]) == FLIP


def test_an_accepted_crossing_is_not_offered_for_applying_again(panel) -> None:
    """It is already in force; Remove swap is what it has to offer."""
    panel.show_model(_model(accepted=True))
    panel._node_box.setCurrentIndex(0)

    assert panel.selected_index() is None
    assert panel._remove.isEnabled()


def test_a_time_off_the_end_still_names_a_real_frame(panel) -> None:
    """A playhead past the tracking is clamped, never keyed out of range."""
    panel.show_model(_model())

    event = panel.event_at(10_000)

    assert event is not None
    assert event.index == FRAMES - 1


# ── the side plots move the main timeline ────────────────────────────


def test_clicking_the_separation_trace_seeks_the_main_video(panel, qtbot) -> None:
    """Same time axis as the braid, and the closest approach is the moment."""
    panel.show_model(_model())
    times = _times()

    with qtbot.waitSignal(panel.seek_requested) as caught:
        panel._separation.getPlotItem().getViewBox().clicked.emit(float(times[FLIP]), 0.0)

    assert caught.args[0] == pytest.approx(float(times[FLIP]))


def test_clicking_a_crossing_itself_reviews_it_and_seeks(panel, qtbot) -> None:
    """The marks answer for themselves.

    A scatter point accepts the press that hits it, so a crossing that left the
    click to the view box underneath was the one thing on the plot that did not
    respond to being aimed at.
    """
    panel.show_model(_model(candidate=True))
    node = panel.nodes()[0]

    with qtbot.waitSignal(panel.seek_requested) as caught:
        panel._select_node(node)

    assert caught.args[0] == pytest.approx(node.at)


def test_the_crossings_carry_themselves_into_the_plot(panel) -> None:
    """So a click can name the node it hit rather than guessing by distance."""
    import pyqtgraph as pg

    panel.show_model(_model(accepted=True, candidate=True))
    scatters = [
        item
        for item in panel._braid.getPlotItem().items
        if isinstance(item, pg.ScatterPlotItem)
    ]

    assert scatters
    carried = [
        spot.data() for scatter in scatters for spot in scatter.points() if spot.data() is not None
    ]
    assert {node.accepted for node in carried} == {True, False}


# ── more than two identities ─────────────────────────────────────────

FOUR = SwapGroup(
    name=ANIMALS,
    lanes=("m1", "m2", "m3", "m4"),
    parts=("snout",),
    members=tuple((lane, "snout", f"{lane}_snout") for lane in ("m1", "m2", "m3", "m4")),
)


def test_two_identities_need_no_pair_chooser(panel) -> None:
    assert not panel._pair_box.isVisibleTo(panel)
    assert panel.pair() == LANES


def test_four_identities_offer_every_pair(qtbot) -> None:
    widget = IdentityPanel()
    qtbot.addWidget(widget)
    widget.set_groups(SOURCE, [FOUR], {})

    offered = [widget._pair_box.itemData(row) for row in range(widget._pair_box.count())]

    assert len(offered) == 6  # four animals, six pairs
    assert offered[0] == ["m1", "m2"]
    assert ["m3", "m4"] in offered


def test_a_swap_exchanges_the_pair_that_is_selected(qtbot) -> None:
    """With three animals, "the first two" is a guess, not an answer."""
    widget = IdentityPanel()
    qtbot.addWidget(widget)
    widget.set_groups(SOURCE, [FOUR], {})
    widget._pair_box.setCurrentIndex(
        [widget._pair_box.itemData(row) for row in range(widget._pair_box.count())].index(
            ["m3", "m4"]
        )
    )

    event = widget.event_at(12)

    assert event is not None
    assert set(event.lanes) == {"m3", "m4"}


# ── navigation that cannot lose the recording ────────────────────────


def test_neither_plot_can_be_scrolled_off_its_own_data(panel) -> None:
    """A wheel notch must never leave the person with nothing and no way back."""
    panel.show_model(_model())
    low, high = panel._model.span()

    for plot in (panel._braid, panel._separation):
        view = plot.getPlotItem().getViewBox()
        view.setXRange(high + 1000, high + 2000, padding=0)
        (shown_low, shown_high), _ = view.viewRange()
        assert shown_low < high + 100, "panned past the end of the recording"
        assert shown_high > low - 100


def test_identity_rows_are_not_a_navigable_axis(panel) -> None:
    """They are identities, not a measurement: zooming them loses the lanes."""
    panel.show_model(_model())

    assert panel._braid.getPlotItem().getViewBox().state["mouseEnabled"] == [True, False]


def test_reviewing_a_visible_crossing_does_not_re_frame_the_plot(panel) -> None:
    """Clicking a crossing that is already on screen keeps the zoom it had."""
    panel.show_model(_model(candidate=True))
    view = panel._braid.getPlotItem().getViewBox()
    times = _times()
    view.setXRange(times[FLIP] - 3.0, times[FLIP] + 3.0, padding=0)
    before, _ = view.viewRange()

    panel._select_node(panel.nodes()[0])

    after, _ = view.viewRange()
    assert after == pytest.approx(before, abs=1e-6)


def test_reviewing_an_off_screen_crossing_brings_it_into_view(panel) -> None:
    panel.show_model(_model(candidate=True))
    view = panel._braid.getPlotItem().getViewBox()
    times = _times()
    view.setXRange(times[0], times[10], padding=0)

    panel._select_node(panel.nodes()[0])

    (low, high), _ = view.viewRange()
    assert low <= times[FLIP] <= high
