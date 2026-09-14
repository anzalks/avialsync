"""Every loader declares where its zero is, and placement follows from that.

An AOL session opened with about -34526 s already typed into every camera's
offset field. That number is not a correction, it is a coordinate: 34526.312 s
is 09:35:26, and the session puts all of its files on one seconds-since-midnight
axis so four unrelated formats can share a reference. The placement was pre-baked
into each item as ``config["offset"]``, which put it in the control the user
nudges by hand and left the master timeline starting nine hours from its own
recording.

Underneath that sat two authorities for the session's zero: `_session_start_time`
(NWB, drives placement) and `_session_anchor_epoch` (AOL, drove the clock
display). The AOL path fed only the second, so the placement machinery believed
the session had no wall clock at all.

Now a source declares the Unix epoch its timestamps count from and nothing else;
``session_zero - source_epoch`` does the rest (D-110).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from avialsync.core.registry import LoaderRegistry
from avialsync.core.session_time import placement_offset, source_epoch_for
from avialsync.core.source import SessionItem, SessionLayout
from avialsync.ui.main_window import MainWindow

#: The reference session's anchor date, 2026-05-08 00:00 UTC.
MIDNIGHT = 1_778_198_400.0
#: 09:35:26.312 on that date.
CAMERA_START = MIDNIGHT + 34_526.312


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    return win


def _aol_session(tmp_path: Path) -> SessionLayout:
    import sys

    sys.path.insert(0, str(Path("tests").resolve()))
    from test_aol_video_extraction_routing import _session_with_cameras, write_export

    session = _session_with_cameras(tmp_path, "FaceCam", "SideCam")
    write_export(session / "video-extraction" / "default", camera="FaceCam")
    return AOLSessionSourceScan(session)


def AOLSessionSourceScan(session: Path) -> SessionLayout:
    from avialsync.loaders.aol_session_loader import AOLSessionSource

    return AOLSessionSource().scan(session, LoaderRegistry())


# ── What the session declares ────────────────────────────────────────


def test_the_session_declares_when_the_recording_began(tmp_path: Path) -> None:
    layout = _aol_session(tmp_path)

    assert layout.session_epoch == pytest.approx(CAMERA_START), (
        "master zero is the instant the cameras started, not midnight"
    )
    assert layout.anchor_epoch == pytest.approx(MIDNIGHT), (
        "the anchor is still what the logs are measured from; the two differ"
    )


def test_no_item_carries_a_pre_baked_placement(tmp_path: Path) -> None:
    """A placement in `config` is one the user then owns -- and can wipe."""
    layout = _aol_session(tmp_path)

    for item in layout.items:
        assert "offset" not in item.config, (
            f"{item.path.name} still pre-bakes a placement into its config"
        )


def test_a_camera_declares_its_own_first_frame(tmp_path: Path) -> None:
    layout = _aol_session(tmp_path)

    cameras = [item for item in layout.items if item.path.suffix == ".mp4"]
    assert cameras
    for camera in cameras:
        assert camera.source_epoch == pytest.approx(CAMERA_START)


def test_a_seconds_since_midnight_item_declares_midnight(tmp_path: Path) -> None:
    layout = _aol_session(tmp_path)

    export = next(item for item in layout.items if item.path.suffix == ".mat")
    assert export.source_epoch == pytest.approx(MIDNIGHT)


def test_every_aol_item_lands_at_the_start_of_the_timeline(tmp_path: Path) -> None:
    """The whole point: one clock, and it starts where the recording does."""
    layout = _aol_session(tmp_path)
    zero = layout.session_epoch

    for item in layout.items:
        epoch = source_epoch_for(0.0, item.source_epoch)
        offset = placement_offset(epoch, zero)
        # Each item's first sample on its own axis: a container counts from 0,
        # everything else from midnight.
        own_start = 0.0 if item.path.suffix == ".mp4" else 34_526.312
        assert own_start - offset == pytest.approx(0.0, abs=1e-3), (
            f"{item.path.name} lands at {own_start - offset:.3f} s, not at the start"
        )


# ── One authority for the session's zero ─────────────────────────────


def test_a_declared_session_zero_reaches_the_placement_machinery(
    window: MainWindow, tmp_path: Path
) -> None:
    """It used to reach only the clock display, and placement never heard."""
    from avialsync.ui.controllers import drop_controller

    layout = _aol_session(tmp_path)

    drop_controller.apply_session_layout(window, layout)

    assert window.session_start_time == pytest.approx(CAMERA_START)


def test_the_clock_still_reads_wall_time_after_the_unification(
    window: MainWindow, tmp_path: Path
) -> None:
    from avialsync.ui.controllers import drop_controller
    from avialsync.ui.time_format import TimeDisplayMode

    drop_controller.apply_session_layout(window, _aol_session(tmp_path))

    assert window._time_mode is TimeDisplayMode.UTC
    assert window.transport._t_epoch == pytest.approx(CAMERA_START)


def test_a_declared_epoch_places_a_source_without_touching_its_offset_field(
    window: MainWindow, tmp_path: Path
) -> None:
    """A camera arrives at master zero with 0.000 s in the control."""
    from avialsync.ui.controllers import drop_controller

    drop_controller.apply_session_layout(window, _aol_session(tmp_path))
    camera = next(path for path in window._declared_source_epochs if path.endswith("FaceCam.mp4"))

    base = window.declare_base_offset(camera, 0.0)

    assert base == pytest.approx(0.0)
    assert window.user_offset(camera, base) == pytest.approx(0.0)


def test_a_midnight_log_is_placed_beside_the_cameras(window: MainWindow, tmp_path: Path) -> None:
    """0.23 s before them, which is where the encoder truly starts."""
    from avialsync.ui.controllers import drop_controller

    drop_controller.apply_session_layout(window, _aol_session(tmp_path))
    log = "/tmp/encoder_log.txt"
    window._declared_source_epochs[log] = MIDNIGHT

    base = window.declare_base_offset(log, 34_526.082)

    assert 34_526.082 - base == pytest.approx(-0.23, abs=1e-3)


# ── The ordinary loaders are unchanged ───────────────────────────────


def test_a_plain_container_still_keeps_its_own_zero(window: MainWindow) -> None:
    assert window.declare_base_offset("/tmp/plain.mp4", 0.0) == 0.0
    assert window.session_start_time == 0.0, "a relative source declares no wall clock"


def test_an_epoch_csv_is_still_placed_without_declaring_anything(
    window: MainWindow,
) -> None:
    """The magnitude guess still carries every loader that says nothing."""
    epoch = 1_768_000_000.0

    base = window.declare_base_offset("/tmp/epoch.csv", epoch)

    assert base == pytest.approx(epoch)
    assert epoch - base == pytest.approx(0.0)


def test_a_session_declaring_no_anchor_places_nothing(window: MainWindow) -> None:
    """A folder with no date is not guessed at."""
    from avialsync.ui.controllers import drop_controller

    drop_controller.apply_session_layout(window, SessionLayout(items=[]))

    assert window.session_start_time == 0.0


def test_an_item_may_decline_to_declare(tmp_path: Path) -> None:
    """`None` is the honest answer, and it has to stay the default."""
    assert SessionItem(tmp_path / "x.csv").source_epoch is None
