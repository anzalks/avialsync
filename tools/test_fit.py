from pathlib import Path

import numpy as np

from avialview.core.sync import fit_sync_events
from avialview.loaders.neo_loader import NeoLoader
from avialview.loaders.video_standard import VideoStandardLoader

# Load Ephys
ephys_path = Path("TENSS26_Anzal/2026-06-21_17-54-56").resolve()
neo_loader = NeoLoader()
neo_loader.open(ephys_path, {})
chunks = neo_loader.read_chunks("Evt-Acquisition Board TTL Input")
times = []
for t, d in chunks:
    indices = np.where(d > 0.5)[0]
    times.append(t[indices])
ephys = np.concatenate(times) if times else np.array([])

# Load Video
video_path = Path("TENSS26_Anzal/camera_top2026-06-21T17_54_59.avi").resolve()
video_loader = VideoStandardLoader()
video_loader.open(video_path, {})
video = video_loader.frame_times()

try:
    proposal = fit_sync_events(ephys, video, reference_id="ref", target_id="tgt")
    print(f"Matched: {proposal.fit.matched_count}")
    print(f"Offset: {proposal.fit.offset}")
    print(f"Drift PPM: {proposal.fit.drift_ppm}")
except Exception as e:
    print(f"Match failed: {e}")
