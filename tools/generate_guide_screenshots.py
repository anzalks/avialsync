"""Capture the annotated screenshots used by the user guide and tutorials.

Every image here boxes the controls its step actually uses, because a picture of
a nine-field dialog does not tell anyone which field the sentence beside it is
talking about.

Run with ``conda run -n avialsync python tools/generate_guide_screenshots.py``.
Do **not** set ``QT_QPA_PLATFORM=offscreen`` — see ``tools/screenshot_kit.py``.

Uses the checked-in sample session, so these are reproducible from a clean
clone and never touch private field data (AGENTS.md rule 5).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from avialsync.engine.importer import ImportWorker
from avialsync.loaders.csv_loader import CSVLoader
from avialsync.loaders.video_standard import VideoStandardLoader
from avialsync.ui.import_wizard import ImportWizard
from avialsync.ui.main_window import MainWindow
from avialsync.ui.sync_wizard import SyncWizard

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screenshot_kit import capture, pin_appearance, pin_layout, settle, staged_fixture  # noqa: E402

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "docs" / "_static" / "screenshots"
SAMPLE_SESSION = REPOSITORY_ROOT / "tests" / "fixtures" / "sample_session"


def _load_session(window: MainWindow, app: QApplication, session: Path) -> None:
    """Open the sample video and signal through the ordinary code paths."""
    video = session / "camera_1.mp4"
    loader = VideoStandardLoader()
    loader.open(video, {})
    window._on_video_opened(str(video), loader, str(video))
    settle(app)

    # ImportWorker takes the loader *class* and a config dict, in that order.
    csv_path = session / "signal_base.csv"
    worker = ImportWorker(csv_path, {}, CSVLoader)
    worker.finished.connect(
        lambda p, c, ch, b, i: window._on_import_finished(p, c, ch, b, i)  # noqa: PLW0108
    )
    worker.run()
    settle(app)


def generate(out_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    """Write every annotated guide screenshot, from a temporary copy of the sample session."""
    with staged_fixture(SAMPLE_SESSION) as session:
        _generate(out_dir, session)


def _generate(out_dir: Path, session: Path) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    pin_appearance(app)
    out_dir.mkdir(parents=True, exist_ok=True)

    window = MainWindow()
    window.resize(1280, 860)
    window.show()
    settle(app)
    pin_layout(window)
    settle(app)
    _load_session(window, app, session)
    window.transport.set_status("Ready")
    settle(app)

    try:
        _capture_all(window, app, out_dir, session)
        _capture_messages(window, app, out_dir, session)
    finally:
        # Ownership is explicit: each pane owns a decode thread, and Qt aborts
        # if one is still running when its QThread is destroyed. A failure
        # mid-capture must not turn into a crash that hides the real error.
        window.close()
        settle(app)
    print(f"Wrote guide screenshots to {out_dir}")


def _capture_messages(window: MainWindow, app: QApplication, out_dir: Path, session: Path) -> None:
    """Show the Messages tab with a few generated rig messages in it.

    The fixtures carry no prose of their own: the generated Open Ephys session's
    ``sync_messages.txt`` holds clock-sync lines, and the tab rightly shows none
    of them. So the store is fed the way ``tests/test_messages.py`` feeds it, and
    the messages are worded and attributed to a file called ``synthetic_rig_log``
    so the image says for itself that nobody's recording wrote them.
    """
    from avialsync.core.messages import Message

    window.message_store.set_source_messages(
        str(session / "synthetic_rig_log.txt"),
        (
            Message(text="Generated example: these lines were written for this image."),
            Message(text="trial 1: stimulus on", time=0.5, channel="MessageCenter"),
            Message(text="trial 1: reward delivered", time=1.6, channel="MessageCenter"),
            Message(text="trial 2: stimulus on", time=2.7, channel="MessageCenter"),
            Message(text="trial 2: no response", time=3.5, channel="MessageCenter"),
        ),
    )
    window._left_tabs.setCurrentWidget(window.message_panel)
    # The message text is the last column; at the inspector's usual width it is
    # scrolled off the right edge, and the image would show times and a source
    # but not a single message.
    window._h_splitter.setSizes([640, 640])
    settle(app)
    capture(
        window,
        out_dir / "guide_messages_tab.png",
        [window.message_panel],
        crop=window._left_tabs,
    )
    window._left_tabs.setCurrentIndex(0)
    window.message_store.clear()
    pin_layout(window)
    settle(app)


def _capture_all(window: MainWindow, app: QApplication, out_dir: Path, session: Path) -> None:
    """Write each annotated capture in turn."""
    info = _video_info_widget(window)

    # --- Offsets and drift, on the source itself -----------------------
    if info is not None:
        capture(
            window,
            out_dir / "guide_offset_fields.png",
            [info.offset_spin, info.drift_spin],
            numbered=True,
        )

    # --- Under the videos: flagging a frame, snapshot -------------------
    # Both buttons live on the view toolbar beneath the video grid, not on
    # Transport or the Data Streams strip they used to sit on.
    toolbar = window.view_toolbar
    capture(
        window,
        out_dir / "guide_flag_and_snapshot.png",
        [toolbar.flag_button, toolbar.snapshot_button],
        numbered=True,
    )

    transport = window.transport
    capture(
        window,
        out_dir / "guide_ab_range.png",
        [transport._ab_in_btn, transport._ab_out_btn],
        numbered=True,
    )

    # --- The import wizard, field by field -----------------------------
    wizard = ImportWizard(session / "signal_base.csv")
    wizard.show()
    settle(app)
    capture(
        wizard,
        out_dir / "guide_import_structure.png",
        [wizard._has_headers_cb, wizard._sep_combo, wizard._time_col_combo],
        numbered=True,
    )
    capture(
        wizard,
        out_dir / "guide_import_time_format.png",
        [wizard._fmt_combo, wizard._unit_combo],
        numbered=True,
    )
    capture(
        wizard,
        out_dir / "guide_import_timezone.png",
        [wizard._tz_combo, wizard._anchor_chk],
        numbered=True,
    )
    capture(
        wizard,
        out_dir / "guide_import_sentinels.png",
        [wizard._sentinel_combo, wizard._euro_chk],
        numbered=True,
    )
    wizard.close()
    settle(app)

    # --- The synchronization wizard, field by field --------------------
    # No `exec` monkeypatch any more: the wizard is shown without blocking, so
    # that it can be read against the window it is asking about (D-108). It
    # used to need patching out or this script would stop here forever.
    window._open_sync_wizard()
    settle(app)
    wizards = window.findChildren(SyncWizard)
    if wizards:
        wizard = wizards[0]
        settle(app)
        capture(
            wizard,
            out_dir / "guide_sync_evidence.png",
            [wizard._reference_combo, wizard._target_combo],
            numbered=True,
        )
        capture(
            wizard,
            out_dir / "guide_sync_ttl_threshold.png",
            [wizard._threshold, wizard._use_all_times_chk],
            numbered=True,
        )
        capture(
            wizard,
            out_dir / "guide_sync_strategy.png",
            [wizard._strategy_combo, wizard._index_offset],
            numbered=True,
        )
        capture(
            wizard,
            out_dir / "guide_sync_manual.png",
            [wizard._manual_offset, wizard._manual_drift, wizard._manual_button],
            numbered=True,
        )
        capture(
            wizard,
            out_dir / "guide_sync_preview_accept.png",
            [wizard._preview_button, wizard._buttons],
            numbered=True,
        )
        wizard.close()
        settle(app)


def _video_info_widget(window: MainWindow):
    """Return the sidebar's per-video widget, whatever its concrete class."""
    for child in window.sidebar.findChildren(object):
        if hasattr(child, "offset_spin") and hasattr(child, "drift_spin"):
            return child
    return None


if __name__ == "__main__":
    generate()
