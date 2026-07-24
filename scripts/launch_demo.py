
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette

from kinochronix.ui.main_window import MainWindow

def load_data(win):
    print("Loading videos...")
    base_dir = Path("examples/data")
    for i in range(1, 4):
        win.video_grid.add_pane(str(base_dir / f"camera_{i}.mp4"))
    
    print("Loading CSV (mocking the finish signal directly for demo)...")
    from kinochronix.engine.importer import ImportWorker
    from kinochronix.core.cache import CacheManager
    
    # We just run the import worker synchronously for the demo launch
    config = {"time_col": "time", "time_unit": "s", "separator": ","}
    worker = ImportWorker(base_dir / "sensors.csv", config)
    worker.run() # blocks, but it's only 10k points so instant
    
    cache_mgr = CacheManager(loader_version=1)
    cache_dir = cache_mgr.get_cache_dir(base_dir / "sensors.csv")
    
    win._on_import_finished(cache_dir, ["Accel_X", "Accel_Y", "Gyro_Z", "Steering_Angle"], (0.0, 10.0))
    print("App is ready! Playing now...")
    
    # Auto-play
    win.player.play()

def main():
    app = QApplication(sys.argv)
    
    app.setStyle("Fusion")
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(18, 18, 18))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(30, 30, 30))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(dark_palette)
    
    win = MainWindow()
    win.show()
    
    # Schedule load_data after the event loop starts so the window renders first
    QTimer.singleShot(500, lambda: load_data(win))
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
