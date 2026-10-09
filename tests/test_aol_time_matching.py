"""AOL cameras matched to microscope trials by when they recorded, not by folder name.

The fixture mirrors the shape of a real experiment (2026-09-03, experiment_2):
the camera PC names its folders by its own clock a few seconds before the
controller names the trial, runs 0.7 s ahead of the controller once the zone
is removed, and some recordings did not start on their trial's trigger. The
numbers below are the fixture's ground truth, not measurements.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pytest

from avialsync.core.registry import LoaderRegistry
from avialsync.core.source import SessionItem
from avialsync.engine.drop_worker import DropScanWorker
from avialsync.loaders.aol_camera_join import AOLJoinedCameraSource
from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
from avialsync.loaders.aol_microscope_trial import joined_starts, read_trial
from avialsync.loaders.aol_trial_matching import CameraRecording, match_cameras
from avialsync.loaders.video_standard import VideoStandardLoader
from tests.test_aol_camera_join import _camera
from tests.test_aol_microscope_trial import _match_trial, _trial

ZONE = 7_200.0  # the controller PC is UTC+2 and writes its folder names in local time
SKEW = 0.7  # the camera PC's clock runs this far ahead of the controller's
T0 = dt.datetime(2026, 9, 3, 10, 0, 10, tzinfo=dt.UTC).timestamp()

#: trial folder (controller's local clock) -> STARTTIME (UTC), 2 s trials a minute apart
TRIALS = {
    "12-00-06": T0,
    "12-01-06": T0 + 60,
    "12-02-06": T0 + 120,
    "12-03-06": T0 + 180,
}
#: camera folder (camera PC's local clock) -> (trial, camera start relative to its trigger)
CAMERAS = {
    "12-00-03": ("12-00-06", 0.03),  # on the trigger, within the stamp jitter
    "12-00-58": ("12-01-06", -15.0),  # started and stopped before its trial: order only
    "12-01-59": ("12-02-06", -1.5),  # started early, overlapping its trial
    "12-03-01": ("12-03-06", -0.05),  # on the trigger
}
STRAY = "12-02-33"  # a recording between trials, which no trial was running for


def _local(trial: str, relative: float) -> float:
    """The camera PC's stamp for an instant *relative* s after *trial*'s trigger."""
    return TRIALS[trial] + ZONE + SKEW + relative


def _recordings() -> list[CameraRecording]:
    found = [CameraRecording(Path(name), _local(t, r)) for name, (t, r) in CAMERAS.items()]
    return [*found, CameraRecording(Path(STRAY), _local("12-02-06", 30.0))]


def test_cameras_pair_by_clock_when_no_folder_name_agrees() -> None:
    trials = [_match_trial(name, start, duration=2.0) for name, start in TRIALS.items()]
    match = match_cameras(trials, _recordings(), tolerance_s=10.0)

    assert match.clock_offset == pytest.approx(ZONE + SKEW, abs=0.05)
    paired = {p.camera.folder.name: (p.trial.folder.name, p.evidence) for p in match.pairs}
    assert paired == {
        "12-00-03": ("12-00-06", "clock"),
        "12-00-58": ("12-01-06", "order"),
        "12-01-59": ("12-02-06", "clock"),
        "12-03-01": ("12-03-06", "clock"),
    }
    offsets = {p.camera.folder.name: p.offset for p in match.pairs}
    # Within the jitter a camera started on its trigger; beyond it, where its clock says.
    assert offsets["12-00-03"] == offsets["12-03-01"] == 0.0
    assert offsets["12-01-59"] == pytest.approx(-1.5, abs=0.05)
    assert offsets["12-00-58"] == pytest.approx(-15.0, abs=0.05)
    assert [c.folder.name for c in match.unmatched] == [STRAY]


def test_one_camera_and_one_trial_start_together() -> None:
    """With nothing to compare against, the one pair is the clock's evidence."""
    trial = _match_trial("12-00-06", T0, duration=2.0)
    camera = CameraRecording(Path("12-00-01"), _local("12-00-06", 3.0))
    match = match_cameras([trial], [camera], tolerance_s=10.0)
    assert [(p.evidence, p.offset) for p in match.pairs] == [("clock", 0.0)]


def test_a_camera_beyond_the_tolerance_with_no_neighbours_is_not_paired() -> None:
    trial = _match_trial("12-00-06", T0, duration=2.0)
    camera = CameraRecording(Path("12-00-01"), _local("12-00-06", 30.0))
    match = match_cameras([trial], [camera], tolerance_s=10.0)
    assert not match.pairs and match.unmatched == (camera,)


def _experiment(tmp_path: Path, cameras_under: Path | None = None) -> tuple[Path, Path]:
    """The trials in ``<date>/<experiment>``, the camera PC's recordings in a mirror tree."""
    experiment = tmp_path / "2026-09-03" / "experiment_2"
    experiment.mkdir(parents=True)
    for name, start in TRIALS.items():
        _trial(experiment / name, start_ms=start * 1000.0, duration=2.0)
    videos = (cameras_under or tmp_path / "videos") / "2026-09-03" / "experiment_2"
    for shade, (name, (trial, relative)) in enumerate(CAMERAS.items()):
        stamp = dt.datetime.fromtimestamp(_local(trial, relative), tz=dt.UTC).replace(tzinfo=None)
        # 30 frames 100 ms apart: each recording is 2.9 s, overrunning a 2 s trial.
        _camera(videos / name, "FaceCam", 30, 100.0, 20 + shade * 40, first_stamp=stamp)
    stray = dt.datetime.fromtimestamp(_local("12-02-06", 30.0), tz=dt.UTC).replace(tzinfo=None)
    _camera(videos / STRAY, "FaceCam", 30, 100.0, 200, first_stamp=stray)
    return experiment, videos


def test_a_trial_finds_its_cameras_in_a_sibling_tree_by_their_clock(tmp_path: Path) -> None:
    experiment, videos = _experiment(tmp_path)
    on_trigger = AOLMicroscopeTrialSource().scan(experiment / "12-00-06", None)
    cameras = [item for item in on_trigger.items if item.loader is VideoStandardLoader]
    assert [item.path for item in cameras] == [videos / "12-00-03" / "FaceCam.avi"]
    assert cameras[0].source_epoch == pytest.approx(T0)
    assert not on_trigger.warnings

    # Alone, this trial and its camera agree with each other; the rest of the
    # experiment is what shows the camera started 1.5 s early.
    early = AOLMicroscopeTrialSource().scan(experiment / "12-02-06", None)
    camera = next(item for item in early.items if item.loader is VideoStandardLoader)
    assert camera.source_epoch == pytest.approx(TRIALS["12-02-06"] - 1.5, abs=0.05)
    assert "by its clock" in camera.label
    assert any("did not start on trial 12-02-06's trigger" in w for w in early.warnings)


def test_an_experiment_joins_cameras_by_clock_and_keeps_only_frames_in_each_trial(
    tmp_path: Path,
) -> None:
    experiment, _videos = _experiment(tmp_path)
    layout = AOLMicroscopeTrialSource().scan(experiment, None)
    joined = [item for item in layout.items if item.loader is AOLJoinedCameraSource]
    assert len(joined) == 1
    segments = joined[0].config["segments"]
    # 12-00-58 recorded only before its trial: matched, reported, not joined.
    assert [Path(s["video"]).parent.name for s in segments] == ["12-00-03", "12-01-59", "12-03-01"]
    assert [s["offset"] for s in segments] == pytest.approx([0.0, -1.5, 0.0], abs=0.05)
    assert any("12-00-58's cameras recorded outside" in w for w in layout.warnings)
    assert any(f"{STRAY}: no trial was recording" in w for w in layout.warnings)

    trials = [read_trial(experiment / name, verify=False) for name in TRIALS]
    starts = dict(zip(TRIALS, joined_starts(trials), strict=True))
    loader = AOLJoinedCameraSource()
    loader.open(joined[0].path, dict(joined[0].config))
    loader.prepare(lambda _fraction: None)
    mapping = loader.exact_time_mapping()
    assert mapping is not None
    master = mapping[0]
    early = master[(master >= starts["12-02-06"]) & (master < starts["12-03-06"] - 1e-6)]
    # The early camera's frames before its trigger are dropped; the rest keep
    # their recorded spacing, moved by the offset its clock gave.
    recorded = segments[1]["offset"] + np.arange(30) * 0.1
    expected = recorded[(recorded >= 0.0) & (recorded < starts["12-03-06"] - starts["12-02-06"])]
    assert len(expected) in (14, 15)
    np.testing.assert_allclose(early - starts["12-02-06"], expected, atol=1e-3)
    assert master[0] == pytest.approx(0.0, abs=1e-6)


def test_trials_and_cameras_dropped_together_pair_wherever_the_cameras_are(
    tmp_path: Path,
) -> None:
    experiment, videos = _experiment(tmp_path, cameras_under=tmp_path / "usb" / "camera_pc")
    dropped = [experiment / "12-00-06", experiment / "12-02-06", videos / "12-00-03"]
    dropped.append(videos / "12-01-59")
    claimed = AOLMicroscopeTrialSource().scan_together(dropped, [], None)
    assert claimed is not None
    layout, used = claimed
    assert used == dropped
    ribbon = layout.items[0]
    assert ribbon.config["trial_folders"] == [str(dropped[0]), str(dropped[1])]
    assert "(chosen trials) — 2 trials" in ribbon.label and len(layout.segments) == 2
    joined = [item for item in layout.items if item.loader is AOLJoinedCameraSource]
    assert [len(item.config["segments"]) for item in joined] == [2]


def test_cameras_dropped_onto_loaded_trials_join_them(tmp_path: Path) -> None:
    experiment, videos = _experiment(tmp_path, cameras_under=tmp_path / "usb" / "camera_pc")
    ribbon = AOLMicroscopeTrialSource().scan(experiment, None).items[0]
    # The experiment was moved by hand 5 s since it loaded: the cameras follow it.
    loaded = [SessionItem(ribbon.path, ribbon.loader, ribbon.config, source_epoch=T0 + 5.0)]
    claimed = AOLMicroscopeTrialSource().scan_together([videos], loaded, None)
    assert claimed is not None
    layout, used = claimed
    assert used == [videos] and not layout.session_epoch and not layout.segments
    assert [item.loader for item in layout.items] == [AOLJoinedCameraSource]
    assert layout.items[0].source_epoch == pytest.approx(T0 + 5.0)
    assert any(f"{STRAY}: no trial was recording" in w for w in layout.warnings)


def test_a_trial_dropped_onto_its_loaded_cameras_lands_on_them(tmp_path: Path) -> None:
    experiment, videos = _experiment(tmp_path, cameras_under=tmp_path / "usb" / "camera_pc")
    camera_session_epoch = _local("12-00-06", 0.03)  # where the camera session put frame 0
    loaded = [
        SessionItem(
            videos / "12-00-03" / "FaceCam.avi",
            VideoStandardLoader,
            source_epoch=camera_session_epoch,
        )
    ]
    claimed = AOLMicroscopeTrialSource().scan_together([experiment / "12-00-06"], loaded, None)
    assert claimed is not None
    layout, _used = claimed
    # Its trigger lands on the loaded camera's first frame, not two hours from it.
    assert [item.loader for item in layout.items] == [layout.items[0].loader]
    assert layout.items[0].source_epoch == pytest.approx(camera_session_epoch)
    assert layout.segments[0][0] == pytest.approx(camera_session_epoch)


def test_a_lone_trial_or_camera_folder_is_left_to_its_own_scan(tmp_path: Path) -> None:
    experiment, videos = _experiment(tmp_path)
    source = AOLMicroscopeTrialSource()
    assert source.scan_together([experiment / "12-00-06"], [], None) is None
    assert source.scan_together([experiment], [], None) is None
    assert source.scan_together([videos / "12-00-03"], [], None) is None


def _drop(paths: list[Path], registry: LoaderRegistry) -> tuple[list, object]:
    worker = DropScanWorker(paths, registry)
    results: list[tuple[list, object]] = []
    worker.finished.connect(lambda candidates, layout: results.append((candidates, layout)))
    worker.run()
    assert len(results) == 1
    return results[0]


def test_a_drop_of_trial_and_camera_folders_is_laid_out_once(tmp_path: Path) -> None:
    experiment, videos = _experiment(tmp_path, cameras_under=tmp_path / "usb" / "camera_pc")
    registry = LoaderRegistry(plugin_dirs=[])
    candidates, layout = _drop([experiment / "12-00-06", videos / "12-00-03"], registry)
    loaders = sorted(loader.__name__ for _path, loader, _config in candidates)
    assert loaders == ["AOLRibbonScanSource", "VideoStandardLoader"]
    assert layout.session_epoch == pytest.approx(T0)


def test_a_failing_group_scan_falls_back_to_one_path_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment, videos = _experiment(tmp_path, cameras_under=tmp_path / "usb" / "camera_pc")

    def broken(*_args: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(AOLMicroscopeTrialSource, "scan_together", broken)
    registry = LoaderRegistry(plugin_dirs=[])
    candidates, _layout = _drop([experiment / "12-00-06", videos / "12-00-03"], registry)
    assert {path for path, _loader, _config in candidates} >= {experiment / "12-00-06"}
    assert any("scan failed" in message for _name, message in registry.plugin_errors)


def test_camera_folders_dropped_alone_load_as_their_trials(tmp_path: Path) -> None:
    """The same cameras record every trial: one joined video each, not one per trial."""
    experiment, videos = _experiment(tmp_path)
    claimed = AOLMicroscopeTrialSource().scan_together([videos], [], None)
    assert claimed is not None
    layout, used = claimed
    assert used == [videos]
    ribbon = layout.items[0]
    assert ribbon.path == experiment  # every trial had a recording
    assert [name for _start, _end, name in layout.segments] == list(TRIALS)
    assert [item.loader for item in layout.items[1:]] == [AOLJoinedCameraSource]
    assert any("skip the imaging in the review" in w for w in layout.warnings)


def test_camera_folders_without_trials_play_back_to_back(tmp_path: Path) -> None:
    _trials, videos = _experiment(tmp_path, cameras_under=tmp_path / "usb" / "camera_pc")
    claimed = AOLMicroscopeTrialSource().scan_together([videos], [], None)
    assert claimed is not None
    layout, _used = claimed
    assert [item.loader for item in layout.items] == [AOLJoinedCameraSource]
    segments = layout.items[0].config["segments"]
    assert len(segments) == len(layout.segments) == len(CAMERAS) + 1
    # Each recording follows the last: 30 frames 100 ms apart run 3.0 s.
    assert [s["start"] for s in segments] == pytest.approx([0.0, 3.0, 6.0, 9.0, 12.0])
    assert layout.session_epoch == pytest.approx(_local("12-00-06", 0.03))
    assert "play back to back" in layout.warnings[0]


def test_camera_sessions_with_more_than_cameras_are_left_to_their_scanner(tmp_path: Path) -> None:
    _trials, videos = _experiment(tmp_path, cameras_under=tmp_path / "usb" / "camera_pc")
    (videos / "12-00-03" / "pose.csv").write_text("t,x\n0,1\n", encoding="utf-8")
    assert AOLMicroscopeTrialSource().scan_together([videos], [], None) is None
