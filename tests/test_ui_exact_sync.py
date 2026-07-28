import pytest
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from avialview.ui.main_window import MainWindow
from avialview.ui.sync_wizard import SyncWizard
from avialview.loaders.csv_loader import CSVLoader
from avialview.loaders.video_standard import VideoStandardLoader
from avialview.engine.importer import ImportWorker

def test_exact_sync_flow(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    
    # 1. Load Video
    video_path = Path("tests/fixtures/sample_session/camera_1.mp4").resolve()
    video_loader = VideoStandardLoader()
    video_loader.open(video_path, {})
    window._on_video_opened(str(video_path), video_loader, str(video_path))
        
    # 2. Load CSV synchronously!
    csv_path = Path("tests/fixtures/sample_session/signal_base.csv").resolve()
    
    worker = ImportWorker(csv_path, {}, CSVLoader)
    def on_finished(p, c, ch, b, i):
        window._on_import_finished(p, c, ch, b, i)
        
    worker.finished.connect(on_finished)
    worker.run() # Run synchronously!
    qtbot.wait(100)
    
    # 3. Open Sync Wizard and interact
    def interact():
        wizards = window.findChildren(SyncWizard)
        assert len(wizards) == 1
        wizard = wizards[0]
        
        # 4. Select Exact Index
        wizard._strategy_combo.setCurrentIndex(1)
        wizard._use_all_times_chk.setChecked(True)
        
        # Click Preview
        wizard._preview_button.click()
        
        # We cannot use qtbot.waitUntil easily inside singleShot, but we can use QTimer
        def check_finished():
            if wizard._thread is None:
                assert wizard.proposal is not None
                assert wizard.proposal.acceptable
                wizard.accept()
            else:
                QTimer.singleShot(100, check_finished)
                
        QTimer.singleShot(100, check_finished)
        
    QTimer.singleShot(0, interact)
    
    # This blocks until wizard.accept() is called which ends exec()
    window._open_sync_wizard()
    
    pane = window.video_grid.panes[0]
    assert pane.time_map._exact_master is not None
    assert pane.time_map._exact_source is not None
    print("SUCCESS: Exact master has", len(pane.time_map._exact_master), "points")
    assert len(pane.time_map._exact_master) > 10

