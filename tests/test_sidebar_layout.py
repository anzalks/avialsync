"""Source panels have to fit the sidebar they live in.

The defect this covers was reported as panel edges "not in place", and that is
exactly what it looked like. The sensor panel's content demanded 585 px of
width; the sidebar's minimum is a couple of hundred. A ``QScrollArea`` with
``setWidgetResizable(True)`` will not shrink its content below that content's
own minimum, and the horizontal scrollbar was set to ``ScrollBarAlwaysOff`` --
so the surplus was not scrolled to, it was cut off at the viewport edge.
Thirteen widgets ended mid-glyph past the right-hand side, and neighbouring
panels with different minimums were cut at different places, which is what made
it read as misalignment rather than as truncation.

Three things caused the 585 px, and each is guarded below:

* the offset and drift spin boxes, whose ``minimumSizeHint`` at six decimals
  over a full-day range is 192 px each,
* the collapsible section header, a ``QPushButton`` whose hint is its whole
  title,
* a ``QFormLayout`` holding a 132 px label column beside its value column.

None of them can be fixed with ``setMinimumWidth``: Qt floors a widget at its
own ``minimumSizeHint`` regardless. The size policy is the lever that works.

The last test is the backstop. Even if some future panel outgrows the sidebar
again, content must remain reachable by scrolling rather than silently vanish.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from avialsync.ui.sidebar import SensorInfoWidget, SidebarPane, VideoInfoWidget

VIDEO_META = {"fps": 230.0, "codec": "h264", "duration": 60.0}


@pytest.fixture
def sidebar_minimum(qapp: QApplication, qtbot) -> int:
    """The width the sidebar can actually be dragged down to."""
    pane = SidebarPane()
    qtbot.addWidget(pane)
    return pane.minimumWidth()


def _panel(kind: str, qtbot) -> QWidget:
    if kind == "sensor":
        widget = SensorInfoWidget("/data/FaceCam.mat", ["Jaw_MI", "Jaw_Speed"])
    else:
        widget = VideoInfoWidget("/data/cam1.mp4", dict(VIDEO_META))
    qtbot.addWidget(widget)
    widget.show()
    return widget


@pytest.mark.parametrize("kind", ["sensor", "video"])
def test_a_panel_fits_the_narrowest_sidebar(
    kind: str, sidebar_minimum: int, qapp: QApplication, qtbot
) -> None:
    """The whole point: content minimum must not exceed the container minimum."""
    widget = _panel(kind, qtbot)
    qapp.processEvents()

    needed = widget.minimumSizeHint().width()
    assert needed <= sidebar_minimum, (
        f"the {kind} panel needs {needed}px inside a {sidebar_minimum}px sidebar; "
        f"the difference is cut off, not scrolled to"
    )


@pytest.mark.parametrize("kind", ["sensor", "video"])
@pytest.mark.parametrize("width", [200, 240, 320])
def test_nothing_is_cut_off_at_any_usable_width(
    kind: str, width: int, qapp: QApplication, qtbot
) -> None:
    """No child may end past the right-hand edge of the panel holding it.

    ``layout().activate()`` matters here. Without it the children keep the
    geometry they had before the resize, and the check passes against stale
    numbers while the real layout is still broken.
    """
    widget = _panel(kind, qtbot)
    widget.resize(width, 700)
    widget.layout().activate()
    qapp.processEvents()

    clipped = [
        f"{type(child).__name__} ends at {child.x() + child.width()}px"
        for child in widget.findChildren(QWidget)
        if child.isVisible() and child.x() + child.width() > width + 2
    ]
    assert clipped == [], f"cut off at {width}px: {clipped[:4]}"


@pytest.mark.parametrize("kind", ["sensor", "video"])
def test_the_spin_boxes_give_up_their_size_hint(kind: str, qapp: QApplication, qtbot) -> None:
    """Six decimals of offset must not be what sets the panel's width."""
    from PySide6.QtWidgets import QDoubleSpinBox, QSizePolicy

    widget = _panel(kind, qtbot)
    spins = widget.findChildren(QDoubleSpinBox)
    assert spins, "expected offset/drift controls"
    for spin in spins:
        assert spin.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored, (
            "setMinimumWidth does not let a spin box shrink below its own "
            "minimumSizeHint; only the size policy does"
        )


def test_content_too_wide_is_scrollable_not_hidden(qapp: QApplication, qtbot) -> None:
    """The backstop, for whatever outgrows the sidebar next.

    ``AlwaysOff`` does not make content fit. It makes content that does not fit
    unreachable.
    """
    pane = SidebarPane()
    qtbot.addWidget(pane)

    policy = pane._scroll_area.horizontalScrollBarPolicy()
    assert policy != Qt.ScrollBarPolicy.ScrollBarAlwaysOff, (
        "with the bar forced off, anything wider than the viewport is clipped "
        "with no way for the user to reach it"
    )


# ── path length must never become a layout constraint ────────────────

LONG_PATH = (
    "/mnt/lab_storage/experiments/2026-08/subject_M47/session_03/"
    "FaceCam_whisker_tracking_processed.mat"
)
LONG_CHANNELS = [
    "Whisker_C2_angle_smoothed_deg",
    "Jaw_MI",
    "Nose_tip_velocity_mm_per_s",
]


def test_a_real_session_path_does_not_widen_the_panel(
    sidebar_minimum: int, qapp: QApplication, qtbot
) -> None:
    """98 characters of path is an ordinary depth for lab storage.

    Before elision this took the sensor panel's minimum from 187px to 491px --
    ``setWordWrap`` finds nowhere to break a path -- and the difference was cut
    off rather than scrolled to.
    """
    widget = SensorInfoWidget(LONG_PATH, LONG_CHANNELS)
    qtbot.addWidget(widget)
    widget.show()
    qapp.processEvents()

    assert widget.minimumSizeHint().width() <= sidebar_minimum


def test_an_elided_label_still_reports_its_full_text(qapp: QApplication, qtbot) -> None:
    """Copying a path out of the interface must not yield an ellipsis."""
    from avialsync.ui.elided_label import ElidedLabel

    label = ElidedLabel(LONG_PATH)
    qtbot.addWidget(label)
    label.resize(120, 20)
    qapp.processEvents()

    assert label.text() == LONG_PATH
    assert label.toolTip() == LONG_PATH, "the full path has to stay reachable"
