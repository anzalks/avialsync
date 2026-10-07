"""One shape for imaging and every other source; no text outside the translation gate (D-196)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile
from shiboken6 import isValid

from avialsync.loaders.imaging_loader import TIFFImagingLoader
from avialsync.ui.design_tokens import ControlRole, role_of
from avialsync.ui.i18n import untranslated_calls
from avialsync.ui.main_window import MainWindow
from avialsync.ui.transport import TimelineOverview

_TIMEOUT = 10_000


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    if isValid(win):
        win.close()


def test_the_gate_reads_messages_dialogs_and_f_strings(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "window.notifications.show_success(f'Imported {name}')\n"
        "QInputDialog.getText(self, 'Save Layout', 'Name this layout:')\n"
        "button.setAccessibleName(f'Hide plot {name}')\n"
        "button.setToolTip(tr('Hide {name}').format(name=name))\n",
        encoding="utf-8",
    )
    found = [text for _line, text in untranslated_calls(source)]
    assert found == ["f'Imported '", "Save Layout", "Name this layout:", "f'Hide plot '"]


def test_an_imaging_lane_says_imaging() -> None:
    assert TimelineOverview._coverage_label("/data/stack.tif", "imaging") == "Imaging · stack.tif"
    assert TimelineOverview._coverage_label("/data/a.csv", "data") == "Data · a.csv"


def test_every_open_action_has_a_sources_button(window) -> None:
    sidebar = window.sidebar
    assert sidebar.btn_open_nwb.text() == window._act_open_nwb.text() == "Open NWB…"
    assert sidebar.btn_open_imaging.text() == "Open Imaging…"
    assert window._act_open_imaging.property("av_id") == "file_open_2p_imaging"


def test_deleting_a_change_is_marked_destructive(window) -> None:
    panel = window.changes_panel
    assert role_of(panel._delete_button) is ControlRole.DESTRUCTIVE


def test_an_imaging_stack_is_a_sources_card_and_full_range_resets_levels(
    window, qtbot, tmp_path
) -> None:
    path = tmp_path / "calcium.tif"
    stack = np.stack([np.full((24, 32), index * 100, np.uint16) for index in range(4)])
    tifffile.imwrite(path, stack, photometric="minisblack")
    window.load_imaging(path, TIFFImagingLoader, {"fps": 10.0})
    qtbot.waitUntil(lambda: window.sidebar.imaging_widget(str(path)) is not None, timeout=_TIMEOUT)
    card = window.sidebar.imaging_widget(str(path))
    assert window.sidebar.imaging_group.isVisible()
    assert "32×24 · 16-bit" in card.summary_label.text()
    assert "Picture: 32×24 · 16-bit" in window.sidebar.properties_text(str(path))
    assert not hasattr(window.imaging_pane, "offset_spin"), "the card owns the mapping"

    controls = window.imaging_pane.controls
    qtbot.waitUntil(lambda: controls.full_range_button.isEnabled(), timeout=_TIMEOUT)
    controls.full_range_button.click()
    channel = window.imaging_pane.view_for(str(path)).channels[0]
    assert (channel.auto_low, channel.auto_high) == (0.0, 65535.0)

    window._on_imaging_remove_requested(str(path))
    assert window.sidebar.imaging_widget(str(path)) is None
    assert not window.sidebar.imaging_group.isVisible()
