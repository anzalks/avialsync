"""Resizing the window must rescale the panes, not sacrifice one to spare another."""

import pytest
from PySide6.QtWidgets import QApplication

from avialview.ui.main_window import MainWindow
from avialview.ui.pane_proportions import PaneProportions, distribute

# ── The allocator ────────────────────────────────────────────────────


def test_span_is_shared_in_proportion_and_fully_spent() -> None:
    """Every pixel is allocated: QSplitter silently reinterprets a short vector."""
    sizes = distribute([0.25, 0.75], span=1000, minimums=[0, 0])

    assert sizes == [250, 750]
    assert sum(sizes) == 1000


def test_truncated_pixels_go_to_the_panes_that_lost_the_most_of_one() -> None:
    """Three-way splits do not divide evenly; the total must still be exact."""
    sizes = distribute([1 / 3, 1 / 3, 1 / 3], span=1000, minimums=[0, 0, 0])

    assert sum(sizes) == 1000
    assert max(sizes) - min(sizes) <= 1


def test_a_pane_below_its_minimum_is_pinned_and_the_rest_reshare() -> None:
    """The 3D pane's header row keeps it above 406 px however narrow the window."""
    sizes = distribute([0.6, 0.4], span=700, minimums=[0, 406])

    assert sizes == [294, 406]
    assert sum(sizes) == 700


def test_pinning_one_pane_can_pin_another_and_both_are_honoured() -> None:
    """Re-sharing after a pin can push a second pane under its own minimum.

    A single pass would leave that one under-sized, so the allocator repeats
    until the pinned set stops growing.
    """
    sizes = distribute([0.8, 0.1, 0.1], span=300, minimums=[0, 100, 100])

    assert sizes == [100, 100, 100]


def test_minimums_that_cannot_fit_are_reported_rather_than_scaled_down() -> None:
    """No allocation satisfies both; Qt clamps, and it must see the real floors."""
    sizes = distribute([0.5, 0.5], span=100, minimums=[200, 300])

    assert sizes == [200, 300]


def test_a_pane_asking_for_nothing_still_gets_its_minimum() -> None:
    """A hidden pane records a zero fraction; showing it must not starve it."""
    sizes = distribute([1.0, 0.0], span=1000, minimums=[0, 150])

    assert sizes == [850, 150]


def test_fractions_that_carry_no_information_split_evenly() -> None:
    """An all-zero vector must not divide by zero or hand one pane everything."""
    assert distribute([0.0, 0.0], span=400, minimums=[0, 0]) == [200, 200]


def test_the_allocator_refuses_mismatched_pane_descriptions() -> None:
    with pytest.raises(ValueError):
        distribute([0.5, 0.5], span=100, minimums=[0])


# ── The window ───────────────────────────────────────────────────────


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qapp.processEvents()
    # MainWindow restores the real user's saved splitter state from QSettings,
    # so the layout a test starts from is otherwise whatever the machine
    # running it last arranged. Start from the documented defaults instead.
    win._apply_default_splitter_sizes()
    qapp.processEvents()
    yield win
    win.close()


def _fractions(splitter) -> list[float]:
    sizes = splitter.sizes()
    total = sum(sizes) or 1
    return [size / total for size in sizes]


def _resize(window: MainWindow, qapp: QApplication, width: int, height: int) -> None:
    """Resize and run the coalesced reallocation the resize timer would fire."""
    window.resize(width, height)
    qapp.processEvents()
    window._pane_proportions.reapply()
    qapp.processEvents()


def test_panes_keep_their_share_of_a_window_that_grows(
    window: MainWindow, qapp: QApplication
) -> None:
    """The workspace/Data Streams and video/plot splits must scale together."""
    _resize(window, qapp, 1280, 800)
    before = [_fractions(window._content_splitter), _fractions(window._v_splitter)]

    _resize(window, qapp, 1900, 1150)
    after = [_fractions(window._content_splitter), _fractions(window._v_splitter)]

    for original, resized in zip(before, after, strict=True):
        assert original == pytest.approx(resized, abs=0.01)


def test_shrinking_and_growing_again_returns_the_original_arrangement(
    window: MainWindow, qapp: QApplication
) -> None:
    """QSplitter's drift is one-way and accumulates.

    Shrinking used to charge the whole loss to whichever pane was not already
    on its minimum, and growing did not give it back: the plot area went from
    66% to 53% of the workspace height and stayed there.
    """
    _resize(window, qapp, 1280, 800)
    original = _fractions(window._v_splitter)

    _resize(window, qapp, 1000, 620)
    _resize(window, qapp, 1280, 800)

    assert _fractions(window._v_splitter) == pytest.approx(original, abs=0.01)


def test_dragging_a_handle_survives_the_next_window_resize(
    window: MainWindow, qapp: QApplication
) -> None:
    """A ratio the user set by hand is the ratio to hold, not one to overwrite."""
    _resize(window, qapp, 1280, 800)
    span = sum(window._content_splitter.sizes())
    window._content_splitter.setSizes([int(span * 0.5), span - int(span * 0.5)])
    window._pane_proportions.record(window._content_splitter)
    qapp.processEvents()
    chosen = _fractions(window._content_splitter)

    _resize(window, qapp, 1700, 1000)

    assert _fractions(window._content_splitter) == pytest.approx(chosen, abs=0.01)


def test_an_empty_video_area_shrinks_with_the_window(
    window: MainWindow, qapp: QApplication
) -> None:
    """The drop-target placeholder used to pin the media row at exactly 200 px.

    While it was pinned, every pixel a shorter window took came out of the plot
    area alone, so the two panes never scaled together.
    """
    assert window.video_grid.lbl_empty.isVisible()

    _resize(window, qapp, 1280, 800)
    tall = window._v_splitter.sizes()[0]
    tall_ratio = _fractions(window._v_splitter)
    _resize(window, qapp, 1280, 640)

    assert window._v_splitter.sizes()[0] < tall
    assert _fractions(window._v_splitter) == pytest.approx(tall_ratio, abs=0.02)


def test_the_first_run_layout_survives_the_first_window_resize(
    window: MainWindow, qapp: QApplication
) -> None:
    """The defaults are pixel counts, and a resize redistributes pixel counts.

    Before the shares were recorded, the seeded sizes were discarded the moment
    the window took its real geometry, and the pane with the largest minimum
    decided the split instead.
    """
    _resize(window, qapp, 1280, 800)

    assert _fractions(window._v_splitter) == pytest.approx([380 / 620, 240 / 620], abs=0.02)
    assert _fractions(window._content_splitter) == pytest.approx([620 / 780, 160 / 780], abs=0.02)


def test_pane_ratios_are_not_recorded_before_the_splitter_has_laid_out(
    qapp: QApplication, qtbot
) -> None:
    """A visible pane measuring zero is a layout that has not happened yet.

    Recording it would pin that pane at its minimum for the rest of the
    session, and no later resize would ever recover the ratio.
    """
    from PySide6.QtWidgets import QSplitter, QWidget

    splitter = QSplitter()
    qtbot.addWidget(splitter)
    for _ in range(2):
        splitter.addWidget(QWidget())
    splitter.show()
    qapp.processEvents()
    splitter.setSizes([0, 300])
    qapp.processEvents()
    assert splitter.sizes()[0] == 0

    proportions = PaneProportions()
    proportions.track(splitter)
    proportions.record(splitter)

    assert splitter not in proportions._fractions
