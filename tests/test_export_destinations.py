"""Each export kind reopens where its last output went (D-197)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog

from avialsync.ui import export_destinations
from avialsync.ui.i18n import untranslated_calls


def test_a_save_prompt_offers_the_last_folder_with_its_own_name(tmp_path: Path) -> None:
    export_destinations.remember("snapshot", tmp_path / "earlier.png")
    assert export_destinations.suggested("snapshot", Path("snapshot.png")) == (
        tmp_path / "snapshot.png"
    )
    assert export_destinations.suggested("clip", Path("clip.mp4")) == Path("clip.mp4")


def test_a_folder_prompt_opens_in_the_last_folder(
    qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The folder itself, not the folder joined to the default's name."""
    offered: list[str] = []

    def answer(_parent: object, _title: str, start: str) -> str:
        offered.append(start)
        return str(tmp_path)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", answer)
    export_destinations.choose_folder(None, "clip", "Clips", Path.home())
    export_destinations.choose_folder(None, "clip", "Clips", Path.home())
    assert offered == [str(Path.home()), str(tmp_path)]


def test_the_translation_gate_reads_titles_given_to_the_pickers(tmp_path: Path) -> None:
    source = tmp_path / "caller.py"
    source.write_text(
        'choose_file(window, "clip", "Export Clip", Path("a.mp4"), tr("Video (*.mp4)"))\n'
        'choose_folder(window, "clip", tr("Export Clip"), Path.home())\n',
        encoding="utf-8",
    )
    assert [line for line, _text in untranslated_calls(source)] == [1]
