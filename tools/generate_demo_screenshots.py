"""Capture the synchronization walkthrough used in the README.

Run with ``conda run -n avialview python tools/generate_demo_screenshots.py``.
Uses the checked-in sample session, so the images are reproducible from a
clean clone and never depend on private field data (AGENTS.md rule 5).
"""

import argparse
import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from avialview.engine.importer import ImportWorker
from avialview.loaders.csv_loader import CSVLoader
from avialview.loaders.video_standard import VideoStandardLoader
from avialview.ui.main_window import MainWindow
from avialview.ui.sync_wizard import SyncWizard

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "docs" / "_static" / "screenshots"


def generate_screenshots(out_dir: Path = DEFAULT_OUTPUT_DIR):
    app = QApplication.instance() or QApplication(sys.argv)
    out_dir.mkdir(parents=True, exist_ok=True)

    window = MainWindow()
    window.resize(1024, 768)
    # Give it a nice layout
    window.show()

    def settle(rounds: int = 40) -> None:
        """Drain the event loop without blocking it.

        Sleeping here would be detected by the UI heartbeat as a stall and
        latched into the status bar, so the screenshot would advertise a
        freeze this harness itself caused.
        """
        for _ in range(rounds):
            app.processEvents()

    def save_shot(name):
        settle()
        # The status line latches until something replaces it, and driving the
        # UI synchronously from a script trips the stall detector. Reset it so
        # the capture shows the state a user reaches, not the harness's.
        window.transport.set_status("Ready")
        app.processEvents()
        window.grab().save(str(out_dir / name))
        print(f"Saved {name}")

    save_shot("demo_step1_empty.png")

    # 1. Load Video
    video_path = REPOSITORY_ROOT / "tests/fixtures/sample_session/camera_1.mp4"
    video_loader = VideoStandardLoader()
    video_loader.open(video_path, {})
    window._on_video_opened(str(video_path), video_loader, str(video_path))

    # Needs to process events so it loads in the UI
    for _ in range(10):
        app.processEvents()
    save_shot("demo_step2_video_loaded.png")

    # 2. Load CSV synchronously!
    csv_path = REPOSITORY_ROOT / "tests/fixtures/sample_session/signal_base.csv"
    worker = ImportWorker(csv_path, {}, CSVLoader)

    def on_finished(p, c, ch, b, i):
        window._on_import_finished(p, c, ch, b, i)

    worker.finished.connect(on_finished)
    worker.run()

    for _ in range(10):
        app.processEvents()
    save_shot("demo_step3_csv_loaded.png")

    # 3. Open Sync Wizard
    # We have to bypass exec() blocking, so we monkeypatch exec() to just show()
    SyncWizard.exec = lambda self: self.show()
    window._open_sync_wizard()

    wizards = window.findChildren(SyncWizard)
    wizard = wizards[0]
    for _ in range(10):
        app.processEvents()
    wizard.grab().save(str(out_dir / "demo_step4_wizard_open.png"))

    # 4. Select Exact Index
    wizard._strategy_combo.setCurrentIndex(1)
    wizard._use_all_times_chk.setChecked(True)
    for _ in range(10):
        app.processEvents()
    wizard.grab().save(str(out_dir / "demo_step5_wizard_configured.png"))

    # Click Preview
    wizard._preview_button.click()

    # Wait for thread
    timeout = time.time() + 5.0
    while wizard._thread is not None and time.time() < timeout:
        app.processEvents()
        time.sleep(0.05)

    for _ in range(10):
        app.processEvents()
    wizard.grab().save(str(out_dir / "demo_step6_wizard_previewed.png"))

    # 5. Accept Mapping
    wizard.accept()
    # accept normally closes it

    for _ in range(10):
        app.processEvents()
    save_shot("demo_step7_mapping_applied.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Where to write the PNGs (default: docs/_static/screenshots).",
    )
    generate_screenshots(parser.parse_args().output_dir)


if __name__ == "__main__":
    main()
