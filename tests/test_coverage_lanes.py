"""Do these recordings overlap, and is the alignment measured or extended?

Neither the residual plot nor the correspondence plot can answer either. They
are both about the matched events; this is about the recordings.
"""

from __future__ import annotations

import pytest

from avialsync.ui.coverage_lanes import CoverageLanes, SourceCoverage


class TestMeasuredAgainstExtended:
    """The most under-reported distinction in alignment tooling."""

    def test_evidence_covering_everything_extrapolates_nowhere(self) -> None:
        source = SourceCoverage("cam.mp4", data=(0.0, 100.0), evidence=(0.0, 100.0))
        assert source.extrapolated() == ()

    def test_data_beyond_the_last_sync_point_is_extended_not_measured(self) -> None:
        source = SourceCoverage("cam.mp4", data=(0.0, 100.0), evidence=(10.0, 60.0))

        assert source.extrapolated() == ((0.0, 10.0), (60.0, 100.0))

    def test_with_no_accepted_alignment_all_of_it_is(self) -> None:
        source = SourceCoverage("cam.mp4", data=(0.0, 100.0), evidence=None)

        assert source.extrapolated() == ((0.0, 100.0),)

    def test_the_description_separates_the_two(self, qtbot) -> None:
        lanes = CoverageLanes()
        qtbot.addWidget(lanes)

        lanes.show_sources(
            [SourceCoverage("cam.mp4", data=(0.0, 100.0), evidence=(10.0, 60.0))]
        )

        text = lanes.describe()
        assert "across 50.0 s" in text
        assert "extended across 50.0 s" in text

    def test_an_unaligned_source_says_so(self, qtbot) -> None:
        lanes = CoverageLanes()
        qtbot.addWidget(lanes)

        lanes.show_sources([SourceCoverage("cam.mp4", data=(0.0, 100.0))])

        assert "no accepted alignment" in lanes.describe()


class TestItAlwaysShowsTheWholeSession:
    def test_two_barely_overlapping_sources_both_fit(self, qtbot) -> None:
        """Auto-ranging to the overlap would hide the one thing worth seeing."""
        lanes = CoverageLanes()
        qtbot.addWidget(lanes)

        lanes.show_sources(
            [
                SourceCoverage("early.csv", data=(0.0, 60.0)),
                SourceCoverage("late.mp4", data=(55.0, 600.0)),
            ]
        )

        low, high = lanes.session_span()
        assert low == pytest.approx(0.0)
        assert high == pytest.approx(600.0)

        shown_low, shown_high = lanes._plot.getViewBox().viewRange()[0]
        assert shown_low <= 0.0 and shown_high >= 600.0

    def test_a_degenerate_span_still_gives_the_axis_room(self, qtbot) -> None:
        lanes = CoverageLanes()
        qtbot.addWidget(lanes)

        lanes.show_sources([SourceCoverage("still.png", data=(5.0, 5.0))])

        low, high = lanes.session_span()
        assert high > low

    def test_with_nothing_loaded_it_says_so(self, qtbot) -> None:
        lanes = CoverageLanes()
        qtbot.addWidget(lanes)

        lanes.show_sources([])

        assert "No sources loaded" in lanes.describe()
        assert not lanes._plot.getPlotItem().items


class TestWhatIsDrawn:
    def test_every_source_gets_a_lane_label(self, qtbot) -> None:
        lanes = CoverageLanes()
        qtbot.addWidget(lanes)

        lanes.show_sources(
            [
                SourceCoverage("a.csv", data=(0.0, 10.0)),
                SourceCoverage("b.mp4", data=(0.0, 10.0)),
            ]
        )

        axis = lanes._plot.getPlotItem().getAxis("left")
        labels = {label for _position, label in axis._tickLevels[0]}
        assert labels == {"a.csv", "b.mp4"}

    def test_gaps_are_drawn_in_place_not_counted_in_a_sentence(self, qtbot) -> None:
        lanes = CoverageLanes()
        qtbot.addWidget(lanes)

        without = CoverageLanes()
        qtbot.addWidget(without)
        without.show_sources([SourceCoverage("a.csv", data=(0.0, 100.0))])
        lanes.show_sources(
            [SourceCoverage("a.csv", data=(0.0, 100.0), gaps=((30.0, 35.0), (70.0, 72.0)))]
        )

        assert len(lanes._plot.getPlotItem().items) > len(without._plot.getPlotItem().items)

    def test_the_y_axis_cannot_be_dragged_off(self, qtbot) -> None:
        """The lanes are categories, not a quantity; panning them means nothing."""
        lanes = CoverageLanes()
        qtbot.addWidget(lanes)

        assert lanes._plot.getViewBox().state["mouseEnabled"] == [True, False]
