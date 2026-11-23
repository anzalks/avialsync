"""Bidirectional spatial-to-temporal linking between 2P ROI imaging tiles and plot rows."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

from avialsync.core.channel_reader import ChannelKey
from avialsync.ui.i18n import tr
from avialsync.ui.plot_modes import PLOT_MODE_STACKED

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

__all__ = [
    "extract_roi_token",
    "install_roi_linking",
]

_ROI_RE = re.compile(r"(?:^|[._\s-])roi[_-]?(\d+)$", re.IGNORECASE)


@lru_cache(maxsize=4096)
def extract_roi_token(channel_name: str) -> str | None:
    """Normalize a channel name like ``'DfOverF.roi17'`` or ``'roi_17'`` to ``'roi17'``."""
    match = _ROI_RE.search(channel_name.strip())
    if match is None:
        return None
    return f"roi{int(match.group(1))}"


def install_roi_linking(window: MainWindow) -> None:
    """Connect ImagingPane ROI clicks and PlotPane row hovers bidirectionally."""
    window.imaging_pane.roi_clicked.connect(lambda roi_id: _on_roi_clicked(window, roi_id))
    window.plot_pane.hovered_channel_changed.connect(
        lambda key: _on_plot_channel_hovered(window, key)
    )


def _on_roi_clicked(window: MainWindow, roi_id: str) -> None:
    target_token = extract_roi_token(roi_id) or roi_id.lower()
    matched = [
        ch
        for ch in window.plot_pane.channels
        if (extract_roi_token(ch.name) or ch.name.lower()) == target_token
    ]
    if not matched:
        return
    row = matched[0]
    if not row.visible:
        window.sidebar.set_channel_visible(row.name, True, row.reader.source_id)
        window.plot_pane.set_channel_visible(row.reader.key, True)
    if window.plot_pane.view_mode != PLOT_MODE_STACKED:
        window.plot_pane.set_view_mode(PLOT_MODE_STACKED)
    window.plot_pane.scroll_to_channel(row.reader.key)
    window.statusBar().showMessage(
        tr("Selected {roi} → plot trace {channel}").format(roi=roi_id, channel=row.name),
        2500,
    )


def _on_plot_channel_hovered(window: MainWindow, key: object) -> None:
    if not isinstance(key, ChannelKey):
        window.imaging_pane.highlight_roi(None)
        return
    token = extract_roi_token(key.channel_id)
    window.imaging_pane.highlight_roi(token)
