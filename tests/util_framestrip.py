"""Frame strip encoder and decoder for robust video sync testing.

We encode a 32-bit integer into the top row of a video frame.
Each bit is represented by a BLOCK_SIZE x BLOCK_SIZE square.
White (255) = 1, Black (0) = 0.
This survives 4:2:0 subsampling and aggressive compression.
"""

import numpy as np
import subprocess
import tempfile
import pathlib

BLOCK_SIZE = 16
NUM_BITS = 32


def encode_frame_index(frame: np.ndarray, index: int) -> None:
    """Encode a 32-bit integer into the top-left pixels of the given frame (in-place).

    Args:
        frame: (H, W) or (H, W, 3) numpy array (uint8).
        index: The frame index to encode.
    """
    for i in range(NUM_BITS):
        bit = (index >> i) & 1
        val = 255 if bit else 0
        x_start = i * BLOCK_SIZE
        x_end = x_start + BLOCK_SIZE
        if frame.ndim == 3:
            frame[0:BLOCK_SIZE, x_start:x_end, :] = val
        else:
            frame[0:BLOCK_SIZE, x_start:x_end] = val


def decode_frame_strip(frame: np.ndarray) -> int:
    """Decode a 32-bit integer from the top-left pixels of the given frame.

    Args:
        frame: (H, W) or (H, W, 3) numpy array (uint8).

    Returns:
        The decoded integer.
    """
    if frame.ndim == 3:
        frame = frame[..., 0]

    index = 0
    for i in range(NUM_BITS):
        x_center = i * BLOCK_SIZE + (BLOCK_SIZE // 2)
        y_center = BLOCK_SIZE // 2
        region = frame[y_center - 2 : y_center + 2, x_center - 2 : x_center + 2]
        mean_val = np.mean(region)

        if mean_val > 128:
            index |= 1 << i

    return index


def test_framestrip_in_memory() -> None:
    """Test that we can perfectly round-trip integers through the encoder/decoder."""
    for i in [0, 1, 2, 255, 1024, 65535, 12345678, 2**31 - 1]:
        frame_gray = np.zeros((360, 640), dtype=np.uint8)
        encode_frame_index(frame_gray, i)
        assert decode_frame_strip(frame_gray) == i

        frame_rgb = np.zeros((360, 640, 3), dtype=np.uint8)
        encode_frame_index(frame_rgb, i)
        assert decode_frame_strip(frame_rgb) == i


def test_framestrip_via_ffmpeg() -> None:
    """Generate a tiny video, extract frames with ffmpeg, decode, assert indices."""
    width, height = 640, 360
    fps = 30
    frames = 10

    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = pathlib.Path(temp_dir_str)
        video_path = temp_dir / "test_vid.mp4"

        # 1. Generate frames and pipe to ffmpeg to encode an h264 video
        cmd_encode = [
            "ffmpeg",
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-s",
            f"{width}x{height}",
            "-pix_fmt",
            "gray",
            "-r",
            str(fps),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ]

        proc = subprocess.Popen(cmd_encode, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert proc.stdin is not None

        for i in range(frames):
            frame = np.full((height, width), 128, dtype=np.uint8)
            encode_frame_index(frame, i)
            proc.stdin.write(frame.tobytes())

        proc.stdin.close()
        proc.wait()
        assert proc.returncode == 0

        # 2. Extract frames to png
        png_dir = temp_dir / "pngs"
        png_dir.mkdir()
        cmd_extract = ["ffmpeg", "-i", str(video_path), str(png_dir / "frame_%04d.png")]
        subprocess.run(cmd_extract, check=True, stderr=subprocess.DEVNULL)

        # 3. Read PNGs, decode, assert
        # We need an image reading library. PySide6 or pyqtgraph? Or just matplotlib/imageio?
        # PySide6 is installed, we can use QImage.
        from PySide6.QtGui import QImage

        for i in range(frames):
            png_file = png_dir / f"frame_{i + 1:04d}.png"
            assert png_file.exists(), f"Missing extracted frame {i}"
            img = QImage(str(png_file))
            assert not img.isNull()

            # Convert to numpy array (grayscale)
            img = img.convertToFormat(QImage.Format.Format_Grayscale8)
            ptr = img.bits()
            # In PySide6, bits() might return a memoryview or ctypes object.
            # Convert pointer safely based on size
            arr = np.frombuffer(ptr, np.uint8).reshape((height, img.bytesPerLine()))
            # Remove padding
            arr = arr[:, :width]

            decoded = decode_frame_strip(arr)
            assert decoded == i, f"Expected {i}, got {decoded}"
