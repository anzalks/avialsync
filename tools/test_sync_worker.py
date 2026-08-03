import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from avialsync.engine.sync_worker import EventEvidenceSpec, SignalEvidenceSpec, SyncWorker
from avialsync.loaders.video_standard import VideoStandardLoader

app = QCoreApplication.instance() or QCoreApplication(sys.argv)

cache_dir = Path("TENSS26_Anzal/2026-06-21_17-54-56.avialcache")
if not cache_dir.exists():
    print("Cache dir doesn't exist! Did you run import?")

ref_spec = SignalEvidenceSpec(
    source_id="2026-06-21_17-54-56",
    channel_id="Evt-Acquisition Board TTL Input",
    cache_dir=cache_dir,
    threshold=0.5,
)

video_path = Path("TENSS26_Anzal/camera_top2026-06-21T17_54_59.avi").resolve()
video_loader = VideoStandardLoader()
video_loader.open(video_path, {})
tgt_spec = EventEvidenceSpec(source_id=str(video_path), times=video_loader.frame_times())

worker = SyncWorker(ref_spec, tgt_spec, "affine")


def on_finished(proposal):
    print("Finished! Offset:", proposal.fit.offset)
    print("Drift PPM:", proposal.fit.drift_ppm)
    print("Matched count:", proposal.fit.matched_count)
    app.quit()


def on_error(msg):
    print("Error:", msg)
    app.quit()


worker.finished.connect(on_finished)
worker.error.connect(on_error)
worker.run()
