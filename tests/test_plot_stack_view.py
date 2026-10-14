"""Linked geometry restores the caller's block state on success and failure."""

import pyqtgraph as pg
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QResizeEvent

from avialsync.ui.plot_stack_view import PlotStackView


@pytest.mark.parametrize("failed", [False, True])
def test_resize_restores_preexisting_link_blocks(qtbot, monkeypatch, failed: bool) -> None:
    views = [pg.ViewBox(), pg.ViewBox()]
    views[1].blockLink(True)
    widget = PlotStackView(lambda: views)
    qtbot.addWidget(widget)

    def layout(_self, _event):
        assert all(view.linksBlocked for view in views)
        if failed:
            raise RuntimeError("layout failure")

    monkeypatch.setattr(pg.GraphicsLayoutWidget, "resizeEvent", layout)
    event = QResizeEvent(QSize(640, 480), QSize(320, 240))
    if failed:
        with pytest.raises(RuntimeError, match="layout failure"):
            widget.resizeEvent(event)
    else:
        widget.resizeEvent(event)
    assert [view.linksBlocked for view in views] == [False, True]


def test_rows_without_a_live_viewbox_do_not_participate_in_geometry_links(qtbot) -> None:
    widget = PlotStackView(lambda: [None])
    qtbot.addWidget(widget)
    widget.resizeEvent(QResizeEvent(QSize(640, 480), QSize(320, 240)))


def test_linked_child_cannot_clear_its_masters_preexisting_block(qtbot) -> None:
    master, child = pg.ViewBox(), pg.ViewBox()
    widget = PlotStackView(lambda: [master, child])
    qtbot.addWidget(widget)
    widget.addItem(master, row=0, col=0)
    widget.addItem(child, row=1, col=0)
    child.setXLink(master)
    widget.resize(640, 480)
    widget.show()
    qtbot.waitExposed(widget)
    master.blockLink(True)
    widget.resize(900, 480)
    assert master.linksBlocked
    assert not child.linksBlocked
