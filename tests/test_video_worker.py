"""Asynchronous video source preparation coverage."""

from pathlib import Path

from PySide6.QtCore import QThread

from avialsync.core.source import VideoSource
from avialsync.engine.video_worker import VideoOpenWorker
from avialsync.ui.job_manager import Job, JobManager


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
        def find_best_loader(self, path: Path, kind: type | None = None):
            return _PreparedVideo

    monkeypatch.setattr("avialsync.engine.video_worker.LoaderRegistry", _Registry)
    worker = VideoOpenWorker(Path("camera.raw"))
    opened: list[tuple[str, object, str]] = []
    worker.opened.connect(lambda original, loader, media: opened.append((original, loader, media)))

    worker.run()

    assert len(opened) == 1
    assert opened[0][0] == "camera.raw"
    assert opened[0][2] == "camera.proxy.mp4"


def test_atomic_proxy_finishes_when_cancel_is_requested_during_encoding(monkeypatch) -> None:
    class _AtomicVideo(_PreparedVideo):
        def prepare_is_atomic(self) -> bool:
            return True

    class _Registry:
        def find_best_loader(self, path: Path, kind: type | None = None):
            return _AtomicVideo

    monkeypatch.setattr("avialsync.engine.video_worker.LoaderRegistry", _Registry)
    worker = VideoOpenWorker(Path("camera.raw"))
    opened: list[str] = []
    cancelled: list[bool] = []
    cancellable_at_half: list[bool] = []

    def halfway(value: int) -> None:
        if value == 50:
            cancellable_at_half.append(Job("Encoding", worker, QThread()).can_cancel())
            worker.cancel()

    worker.progress.connect(halfway)
    worker.opened.connect(lambda _original, _loader, media: opened.append(media))
    worker.cancelled.connect(lambda: cancelled.append(True))

    worker.run()

    assert opened == ["camera.proxy.mp4"]
    assert not cancelled
    assert cancellable_at_half == [False]


def test_job_status_shows_reported_proxy_progress(qapp) -> None:
    manager = JobManager()
    thread = QThread()
    worker = VideoOpenWorker(Path("camera.raw"))
    job = Job("Loading video camera.raw", worker, thread, progress_percent=42)
    manager._jobs[thread] = job

    assert manager.status_text() == "Loading video camera.raw… 42%"
