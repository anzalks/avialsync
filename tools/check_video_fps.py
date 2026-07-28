from pathlib import Path
from avialview.loaders.video_standard import VideoStandardLoader

video_loader = VideoStandardLoader()
video_loader.open(Path("TENSS26_Anzal/camera_top2026-06-21T17_54_59.avi").resolve(), {})
video_times = video_loader.frame_times()
print(f"Video has {len(video_times)} frames.")
print(f"First 5 video times: {video_times[:5]}")
diffs = [video_times[i] - video_times[i-1] for i in range(1, min(100, len(video_times)))]
avg_diff = sum(diffs)/len(diffs)
print(f"Average time diff: {avg_diff:.4f} s -> {1/avg_diff:.2f} FPS")
