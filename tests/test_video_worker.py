"""Asynchronous video source preparation coverage."""

from pathlib import Path

from avialsync.core.source import VideoSource
from avialsync.engine.video_worker import VideoOpenWorker


class _PreparedVideo(VideoSource):
    @classmethod
    def can_open(cls, path: Path) -> float:
        return 1.0

    def open(self, path: Path, config: dict[str, object]) -> None:
        self.path = path

    def needs_conversion(self) -> bool:
        return True

    def prepare(self, progress_cb):
        progress_cb(0.5)
        return self.path.with_suffix(".proxy.mp4")

    def media_path(self) -> Path:
        return self.path

    def start_time(self) -> float | None:
        return None

    def time_bounds(self) -> tuple[float, float]:
        return (0.0, 1.0)

    def frame_times(self):
        return None

    def fps(self) -> float:
        return 30.0

    def label(self) -> str:
        return "prepared"


def test_video_worker_prepares_before_emitting_media_path(monkeypatch) -> None:
    """Conversion sources emit their prepared media path, not the original input."""

    class _Registry:
        def find_best_loader(self, path: Path):
            return _PreparedVideo

    monkeypatch.setattr("avialsync.engine.video_worker.LoaderRegistry", _Registry)
    worker = VideoOpenWorker(Path("camera.raw"))
    opened: list[tuple[str, object, str]] = []
    worker.opened.connect(lambda original, loader, media: opened.append((original, loader, media)))

    worker.run()

    assert len(opened) == 1
    assert opened[0][0] == "camera.raw"
    assert opened[0][2] == "camera.proxy.mp4"
