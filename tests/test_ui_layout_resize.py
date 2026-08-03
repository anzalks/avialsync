"""Window and pane resizing behaviour.

Three defects motivated these tests:

1. ``QSplitter`` stretch factors alone let Qt hand the plot area zero pixels when
   the media pane's size hint already filled the splitter, so plots came up
   fully collapsed.
2. Panes were collapsible by drag.  A zero-height plot area or zero-width video
   area leaves no handle affordance to bring it back.
3. The 3D tracking pane always occupied a third of the media width and raised
   the window's minimum width, even in sessions with no tracking data.

``QSplitter.saveState`` stores the collapsible flag, so the policy has to be
re-asserted after ``restoreState`` — that regression is covered here too.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from avialview.core.pyramid import PyramidBuilder
from avialview.ui.main_window import MainWindow


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    # Tall enough that the panes' minimum heights leave room to move. At
    # 900 the Linux font metrics inflate those minimums until they consume
    # the whole splitter, so a drag genuinely cannot move and the tests
    # below were asserting freedom the layout did not have.
    win.resize(1400, 1600)
    win.show()
    qapp.processEvents()
    yield win
    win.close()


def _splitters(window: MainWindow):
    return {
        "horizontal": window._h_splitter,
        "content": window._content_splitter,
        "vertical": window._v_splitter,
        "media": window._media_splitter,
    }


# ── No pane starts collapsed ──────────────────────────────────────────


def test_plot_area_starts_with_real_height(window: MainWindow) -> None:
    """The regression: plots used to be handed zero pixels on launch."""
    sizes = window._v_splitter.sizes()
    assert sizes[1] > 0, "PlotPane started fully collapsed"
    assert window.plot_pane.height() > 0


def test_every_visible_pane_starts_with_real_size(window: MainWindow) -> None:
    for name, splitter in _splitters(window).items():
        sizes = splitter.sizes()
        for index in range(splitter.count()):
            if splitter.widget(index).isVisible():
                assert sizes[index] > 0, f"{name} pane {index} started collapsed"


# ── Drag can never destroy a pane ─────────────────────────────────────


def test_no_splitter_allows_collapsing_a_pane(window: MainWindow) -> None:
    for name, splitter in _splitters(window).items():
        assert not splitter.childrenCollapsible(), f"{name} still allows collapse"


def test_policy_survives_restoring_a_permissive_saved_layout(
    window: MainWindow, qapp: QApplication
) -> None:
    """saveState stores the collapsible flag; restoring must not undo the policy."""
    window._v_splitter.setChildrenCollapsible(True)
    stale = window._v_splitter.saveState()

    window._v_splitter.restoreState(stale)
    assert window._v_splitter.childrenCollapsible() is True  # precondition

    window._enforce_splitter_policy()

    assert window._v_splitter.childrenCollapsible() is False


def test_a_stale_zero_sized_pane_is_repaired(window: MainWindow, qapp: QApplication) -> None:
    """A layout saved before this policy could carry a zero pane; repair it."""
    collapsed = window._v_splitter.widget(1)
    # Qt honours a child's minimum height even when collapsing is allowed, and
    # that minimum is larger than zero on every platform, so the stale state
    # has to be staged rather than merely requested. This is the setup, not the
    # thing under test: the repair below is.
    minimum_height = collapsed.minimumHeight()
    collapsed.setMinimumHeight(0)
    window._v_splitter.setChildrenCollapsible(True)
    window._v_splitter.setSizes([window._v_splitter.height(), 0])
    qapp.processEvents()
    assert window._v_splitter.sizes()[1] == 0
    collapsed.setMinimumHeight(minimum_height)

    window._enforce_splitter_policy()
    window._repair_collapsed_panes()
    qapp.processEvents()

    assert window._v_splitter.sizes()[1] > 0


# ── Shrinking the window keeps every pane usable ──────────────────────


def test_shrinking_the_window_keeps_all_panes_visible(
    window: MainWindow, qapp: QApplication
) -> None:
    window.resize(760, 520)
    qapp.processEvents()

    for name, splitter in _splitters(window).items():
        sizes = splitter.sizes()
        for index in range(splitter.count()):
            if splitter.widget(index).isVisible():
                assert sizes[index] > 0, f"{name} pane {index} vanished when shrinking"


def test_window_minimum_width_fits_a_laptop_display(window: MainWindow) -> None:
    """A rigid minimum makes the window feel unresizable on a small screen."""
    assert window.minimumSizeHint().width() <= 900


def test_user_splitter_positions_are_honoured(window: MainWindow, qapp: QApplication) -> None:
    """Dragging a handle must actually move it, not snap back."""
    total = sum(window._v_splitter.sizes())
    window._v_splitter.setSizes([total // 4, total - total // 4])
    qapp.processEvents()

    sizes = window._v_splitter.sizes()
    assert sum(sizes) == total, "the splitter changed size instead of redistributing"
    assert sizes[1] > sizes[0], "splitter position did not stick"


# ── 3D pane only takes space when it has data ─────────────────────────


def test_tracking_pane_is_hidden_without_xyz_channels(window: MainWindow) -> None:
    assert not window.tracking_3d_pane.isVisible()
    assert window._media_splitter.sizes()[0] == window._media_splitter.width()


def test_tracking_pane_appears_once_a_source_has_triplets(
    window: MainWindow, qapp: QApplication, tmp_path: Path
) -> None:
    times = np.arange(500, dtype=np.float64) / 50.0
    for name in ("nose_x", "nose_y", "nose_z"):
        PyramidBuilder(tmp_path, name).build_and_save(times, times)

    window._on_import_finished(
        "/tmp/pose.csv", str(tmp_path), ["nose_x", "nose_y", "nose_z"], (0.0, 9.98), None
    )
    qapp.processEvents()

    assert window.tracking_3d_pane.isVisible()
    assert window._media_splitter.sizes()[1] > 0


def test_video_keeps_the_full_media_width_without_tracking_data(
    window: MainWindow, qapp: QApplication
) -> None:
    window.resize(900, 600)
    qapp.processEvents()

    assert window.video_grid.width() == window._media_splitter.width()
