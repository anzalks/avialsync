import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from avialview.engine.importer import ImportWorker
from avialview.loaders.csv_loader import CSVLoader
from avialview.loaders.video_standard import VideoStandardLoader
from avialview.ui.main_window import MainWindow
from avialview.ui.sync_wizard import SyncWizard


def generate_screenshots():
    app = QApplication.instance() or QApplication(sys.argv)

    window = MainWindow()
    window.resize(1024, 768)
    # Give it a nice layout
    window.show()

    out_dir = Path(
        "/Users/anzalks/.gemini/antigravity-ide/brain/6e255d75-de3c-4175-9c68-bac59d332866/"
    )

    def save_shot(name):
        app.processEvents()
        window.grab().save(str(out_dir / name))
        print(f"Saved {name}")

    save_shot("demo_step1_empty.png")

    # 1. Load Video
    video_path = Path("tests/fixtures/sample_session/camera_1.mp4").resolve()
    video_loader = VideoStandardLoader()
    video_loader.open(video_path, {})
    window._on_video_opened(str(video_path), video_loader, str(video_path))

    # Needs to process events so it loads in the UI
    for _ in range(10):
        app.processEvents()
    save_shot("demo_step2_video_loaded.png")

    # 2. Load CSV synchronously!
    csv_path = Path("tests/fixtures/sample_session/signal_base.csv").resolve()
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
    import time

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


if __name__ == "__main__":
    generate_screenshots()
