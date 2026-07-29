import logging
from pathlib import Path

from avialview.loaders.neo_loader import NeoLoader
from avialview.loaders.video_standard import VideoStandardLoader

logging.basicConfig(level=logging.INFO)


def main():
    base_dir = Path(__file__).parent.parent / "TENSS26_Anzal"
    ephys_dir = base_dir / "2026-06-21_17-54-56"
    video_path = base_dir / "camera_top2026-06-21T17_54_59.avi"

    print(f"Checking Ephys Data at {ephys_dir}...")
    loader = NeoLoader()
    can_open_score = loader.can_open(ephys_dir)
    print(f"can_open() score for ephys dir: {can_open_score}")

    if can_open_score > 0:
        loader.open(ephys_dir, {})
        channels = loader.channels()
        print(f"Loaded {len(channels)} channels.")
        if channels:
            print("First 3 channels:")
            for ch in channels[:3]:
                print(f"  - {ch.name} ({ch.rate_hz} Hz, {ch.unit}, {ch.dtype})")

            # Read first chunk of first channel
            ch_name = channels[0].name
            print(f"Reading first chunk of {ch_name}...")
            chunk_iter = loader.read_chunks(ch_name)
            try:
                t, data = next(chunk_iter)
                print(f"  -> Read {len(t)} samples. t[0]={t[0]:.4f}, data[0]={data[0]:.4f}")
            except StopIteration:
                print("  -> No data found.")
    else:
        print("Cannot open ephys data.")

    print("\n-------------------------------\n")
    print(f"Checking Video Data at {video_path}...")
    video_loader = VideoStandardLoader()
    video_score = video_loader.can_open(video_path)
    print(f"can_open() score for video: {video_score}")

    if video_score > 0:
        video_loader.open(video_path, {})
        print(
            f"Video format: {video_loader._width}x{video_loader._height}, {video_loader.fps()} FPS"
        )
        print(f"Codec: {video_loader._codec}, Duration: {video_loader._duration:.2f}s")
    else:
        print("Cannot open video data.")


if __name__ == "__main__":
    main()
