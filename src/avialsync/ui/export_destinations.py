"""Remember one last chosen destination folder per registered export kind."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QWidget

from avialsync.core.settings_schema import setting_for
from avialsync.ui.app_settings import app_settings


def suggested(kind: str, default: Path) -> Path:
    """Use this kind's last folder with the caller's meaningful file name."""
    key = f"export/last_folder/{kind}"
    setting_for(key)
    stored = app_settings().value(key, "", type=str)
    folder = Path(stored) if isinstance(stored, str) and stored else None
    return (folder / default.name) if folder is not None and folder.is_dir() else default


def remember(kind: str, target: Path) -> None:
    """Persist the folder only after the user has chosen a destination."""
    key = f"export/last_folder/{kind}"
    setting_for(key)
    app_settings().setValue(key, str(target.parent))


def choose_file(
    parent: QWidget,
    kind: str,
    title: str,
    default: Path,
    filters: str,
) -> Path | None:
    """Run the standard save dialog with this export kind's last folder."""
    chosen, _filter = QFileDialog.getSaveFileName(
        parent, title, str(suggested(kind, default)), filters
    )
    if not chosen:
        return None
    target = Path(chosen)
    remember(kind, target)
    return target


def choose_folder(parent: QWidget, kind: str, title: str, default: Path) -> Path | None:
    """Choose an output folder and remember it for the same export kind."""
    chosen = QFileDialog.getExistingDirectory(parent, title, str(suggested(kind, default)))
    if not chosen:
        return None
    folder = Path(chosen)
    remember(kind, folder / "export")
    return folder
