"""Relinking finds the files that moved together, and says what it guessed."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog

from avialsync.ui.controllers.relink_controller import relinked as _relinked
from avialsync.ui.relink_dialog import RelinkDialog


def test_locating_one_file_finds_the_ones_that_moved_with_it(
    qapp: QApplication, qtbot, tmp_path: Path, monkeypatch
) -> None:
    new_root = tmp_path / "new_drive" / "exp1"
    (new_root / "cams").mkdir(parents=True)
    (new_root / "daq").mkdir()
    for name in ("cams/front.mp4", "cams/side.mp4", "daq/ttl.csv"):
        (new_root / name).write_bytes(b"\x00")
    missing = [
        "/old_drive/exp1/cams/front.mp4",
        "/old_drive/exp1/cams/side.mp4",
        "/old_drive/exp1/daq/ttl.csv",
        "/elsewhere/notes.csv",
    ]
    dialog = RelinkDialog(missing, {})
    qtbot.addWidget(dialog)
    assert not dialog._open_btn.isEnabled()
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(new_root / "cams" / "front.mp4"), ""),
    )

    dialog._browse(0, missing[0])

    mapping = dialog.resolved_mapping()
    assert mapping[missing[1]] == str(new_root / "cams" / "side.mp4")
    assert mapping[missing[2]] == str(new_root / "daq" / "ttl.csv")
    assert missing[3] not in mapping
    assert dialog._open_btn.isEnabled()
    assert "moved to" in dialog._table.item(1, 2).toolTip()


def test_opening_without_missing_files_drops_what_was_located(
    qapp: QApplication, qtbot, tmp_path: Path, monkeypatch
) -> None:
    located = tmp_path / "cam.mp4"
    located.write_bytes(b"\x00")
    dialog = RelinkDialog(["/gone/cam.mp4"], {})
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(located), ""))
    dialog._browse(0, "/gone/cam.mp4")

    dialog._skip_btn.click()

    assert dialog.resolved_mapping() == {}


def test_a_renamed_file_is_flagged(qapp: QApplication, qtbot, tmp_path: Path, monkeypatch) -> None:
    other = tmp_path / "different.mp4"
    other.write_bytes(b"\x00")
    dialog = RelinkDialog(["/gone/cam.mp4"], {"/gone/cam.mp4": "video"})
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(other), ""))

    dialog._browse(0, "/gone/cam.mp4")

    assert "different file name" in dialog._table.item(0, 2).toolTip()
    assert dialog._table.item(0, 0).text() == "Video"


def test_evidence_ids_follow_their_file() -> None:
    relink = {"/old/daq.csv": "/new/daq.csv"}

    assert _relinked("/old/daq.csv", relink) == "/new/daq.csv"
    assert _relinked("/old/daq.csv : TTL", relink) == "/new/daq.csv : TTL"
    assert _relinked("/other.csv : TTL", relink) == "/other.csv : TTL"
