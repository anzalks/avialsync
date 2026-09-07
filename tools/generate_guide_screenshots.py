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
from avialsync.ui.transport import TimelineEvidence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screenshot_kit import capture, pin_appearance, pin_layout, settle  # noqa: E402

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "docs" / "_static" / "screenshots"
SESSION = REPOSITORY_ROOT / "tests" / "fixtures" / "sample_session"


def _load_session(window: MainWindow, app: QApplication) -> None:
    """Open the sample video and signal through the ordinary code paths."""
    video = SESSION / "camera_1.mp4"
    loader = VideoStandardLoader()
    loader.open(video, {})
    window._on_video_opened(str(video), loader, str(video))
    settle(app)

    # ImportWorker takes the loader *class* and a config dict, in that order.
    csv_path = SESSION / "signal_base.csv"
    worker = ImportWorker(csv_path, {}, CSVLoader)
    worker.finished.connect(
        lambda p, c, ch, b, i: window._on_import_finished(p, c, ch, b, i)  # noqa: PLW0108
    )
    worker.run()
    settle(app)


def generate(out_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    """Write every annotated guide screenshot."""
    app = QApplication.instance() or QApplication(sys.argv)
    pin_appearance(app)
    out_dir.mkdir(parents=True, exist_ok=True)

    window = MainWindow()
    window.resize(1280, 860)
    window.show()
    settle(app)
    pin_layout(window)
    settle(app)
    _load_session(window, app)
    window.transport.set_status("Ready")
    settle(app)

    try:
        _capture_all(window, app, out_dir)
    finally:
        # Ownership is explicit: each pane owns a decode thread, and Qt aborts
        # if one is still running when its QThread is destroyed. A failure
        # mid-capture must not turn into a crash that hides the real error.
        window.close()
        settle(app)
    print(f"Wrote guide screenshots to {out_dir}")


def _capture_all(window: MainWindow, app: QApplication, out_dir: Path) -> None:
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

    # --- Data Streams strip: flagging a frame, snapshot ----------------
    # Those buttons live on the TimelineEvidence strip rather than on
    # Transport itself, so they are looked up rather than assumed.
    evidence = window.findChild(TimelineEvidence)
    if evidence is not None:
        capture(
            window,
            out_dir / "guide_flag_and_snapshot.png",
            [evidence.flag_button, evidence.snapshot_button],
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
    wizard = ImportWizard(SESSION / "signal_base.csv")
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
    SyncWizard.exec = lambda self: self.show()  # type: ignore[method-assign]
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
