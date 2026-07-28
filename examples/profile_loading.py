import time
from pathlib import Path
from avialview.loaders.neo_loader import NeoLoader
from avialview.loaders.video_standard import VideoStandardLoader

def main():
    base_dir = Path(__file__).parent.parent / "TENSS26_Anzal"
    ephys_dir = base_dir / "2026-06-21_17-54-56"
    video_path = base_dir / "camera_top2026-06-21T17_54_59.avi"
    
    t0 = time.time()
    loader = NeoLoader()
    loader.open(ephys_dir, {})
    t1 = time.time()
    print(f"NeoLoader.open took {t1 - t0:.2f} seconds")
    
    t0 = time.time()
    vloader = VideoStandardLoader()
    vloader.open(video_path, {})
    t1 = time.time()
    print(f"VideoStandardLoader.open took {t1 - t0:.2f} seconds")

if __name__ == "__main__":
    main()
